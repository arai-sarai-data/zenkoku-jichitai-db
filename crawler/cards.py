"""総務省「決算カード」(原本PDF)の、団体ごとのページ番号を作る。

市町村分は都道府県ごとに1本のPDFで、先頭の目次に「市区町村名 ページ」が並ぶ。
これを読んで、団体コード → (PDFのURL, ページ) の対応表を作る。サイトでは #page=N 付きのリンクにする。
都道府県分は全都道府県で1本のPDF(年度により分割)。各ページ先頭の団体名で対応を取る。

出力: data/kessan/cards.csv  (年度, 団体コード, 団体名, PDFのURL, ページ)
"""
import csv
import io
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlutil import parse_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX = "https://www.soumu.go.jp/iken/zaisei/card.html"
UA = {"User-Agent": "zenkoku-jichitai-db/0.1 (public-interest open database of local government finance)"}
YEARS_BACK = 5
WAIT = 1.5
_last = 0.0


def get(url):
    global _last
    d = WAIT - (time.time() - _last)
    if d > 0:
        time.sleep(d)
    _last = time.time()
    r = requests.get(url, headers=UA, timeout=300)
    r.raise_for_status()
    return r


def year_of(text, href):
    m = re.search(r"(令和|平成)\s*([0-9０-９]+|元)\s*年度", text)
    if m:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        return (2018 + n) if m.group(1) == "令和" else (1988 + n)
    m = re.search(r"card-(\d+)\.html", href)     # card-25.html = 令和6年度(2024) … 年度=1999+番号
    return 1999 + int(m.group(1)) if m else None


def main():
    master = {}
    with open(ROOT / "data" / "master.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            master.setdefault(r["pref"], {})[r["name"].replace(" ", "").replace("　", "")] = r["code"]
    doc = parse_html(get(INDEX))
    year_pages = []
    for a in doc.iterfind(".//a[@href]"):
        href = urljoin(INDEX, a.get("href"))
        if re.search(r"/card-\d+\.html$", href):
            y = year_of(a.text_content(), href)
            if y:
                year_pages.append((y, href))
    year_pages = sorted(set(year_pages), reverse=True)[:YEARS_BACK]
    print("年度ページ", year_pages, file=sys.stderr)
    out = []
    for y, yurl in year_pages:
        ydoc = parse_html(get(yurl))
        pdfs = []
        for a in ydoc.iterfind(".//a[@href]"):
            href = urljoin(yurl, a.get("href"))
            if href.lower().endswith(".pdf"):
                # どの県のPDFか: 同じ行(tr)の先頭セル
                tr = a.xpath("ancestor::tr[1]")
                pref = ""
                if tr:
                    cells = [c.text_content().strip() for c in tr[0].xpath("./th|./td")]
                    pref = next((c for c in cells if re.search(r"(都|道|府|県)$", c)), "")
                pdfs.append((pref, href))
        for pref, href in pdfs:
            try:
                reader = PdfReader(io.BytesIO(get(href).content))
            except Exception as e:  # noqa: BLE001
                print("fail", href, e, file=sys.stderr)
                continue
            toc_text = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(2, len(reader.pages))))
            pref_name = pref or (re.search(r"都道府県名\s*(\S+?[都道府県])", toc_text) or [None, ""])[1]
            names = master.get(pref_name, {})
            found = 0
            # 目次: 「敦賀市 3」のように 名前 と ページ が並ぶ
            for m in re.finditer(r"([^\s\d]{1,10}?[市区町村])\s*(\d{1,3})(?!\d)", toc_text):
                nm, pg = m.group(1), int(m.group(2))
                code = names.get(nm)
                if code and pg <= len(reader.pages):
                    out.append([y, code, nm, href, pg])
                    found += 1
            print(y, pref_name, href, "目次から", found, "団体", file=sys.stderr)
    (ROOT / "data" / "kessan").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "kessan" / "cards.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["年度", "団体コード", "団体名", "PDF", "ページ"])
        w.writerows(sorted(set(map(tuple, out)), reverse=True))
    latest = max((r[0] for r in out), default=None)
    n_latest = len({r[1] for r in out if r[0] == latest})
    print(f"決算カード: {len(out)} 件、最新年度 {latest} は {n_latest} 団体")


if __name__ == "__main__":
    main()
