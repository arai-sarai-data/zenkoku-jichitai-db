"""総務省「市町村別決算状況調」「都道府県決算状況調」を全年度取り込み、団体×項目の表にする。

原本: 総務省が公開するExcel(年度・表ごと)。各行に原本のURLを残す。
出力:
  data/kessan/<年度>/<表名>.csv     1行=1団体。列=項目(複数行の見出しをつないだ名前)。単位は千円(表による)
  data/kessan/sources.csv           年度・表名・原本URL・団体数
  work/kessan_all.zip               全年度(リポジトリには直近 KEEP_YEARS 年度だけ置き、全年度はReleaseへ)

使い方: python crawler/kessan.py
"""
import csv
import io
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlutil import parse_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "zenkoku-jichitai-db/0.1 (public-interest open database of local government finance)"}
INDEXES = {
    "市町村": "https://www.soumu.go.jp/iken/kessan_jokyo_2.html",
    "都道府県": "https://www.soumu.go.jp/iken/kessan_jokyo_1.html",
}
KEEP_YEARS = 5
WAIT = 1.5
_last = 0.0


def get(url):
    global _last
    d = WAIT - (time.time() - _last)
    if d > 0:
        time.sleep(d)
    _last = time.time()
    r = requests.get(url, headers=UA, timeout=180)
    r.raise_for_status()
    return r


def page(url):
    r = get(url)
    return parse_html(r), r.url


def year_label(text):
    m = re.search(r"(令和|平成)\s*(\d+|元)\s*年度", text)
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return (2018 + n) if m.group(1) == "令和" else (1988 + n)


def url_year(href):
    m = re.search(r"/(r|h)(\d{2})_\w+\.html?$", href)
    if not m:
        return None
    n = int(m.group(2))
    return (2018 + n) if m.group(1) == "r" else (1988 + n)


def rows_from_file(data, ext):
    """Excel(xlsx/xls)の最初のシートを行のリストで返す(各行は列番号→値)"""
    if ext == ".xlsx":
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    import xlrd
    sh = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
    return [sh.row_values(i) for i in range(sh.nrows)]


def clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        s = s[:-2]
    return re.sub(r"\s+", "", s)


PREFS = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
         "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
         "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
         "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
         "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]


def pref_code(name):
    i = PREFS.index(name) + 1
    c5 = f"{i:02d}000"
    return c5 + str((11 - sum(int(c) * w for c, w in zip(c5, (6, 5, 4, 3, 2))) % 11) % 10)


def parse_pref_table(rows):
    """都道府県の表: 1列目が都道府県名(団体コードなし)。見出しは「区分」の行から始まる"""
    name_col, first = None, None
    for i, r in enumerate(rows[:80]):
        for j, v in enumerate(r[:3]):
            if clean(v) in PREFS:
                name_col, first = j, i
                break
        if first is not None:
            break
    if first is None:
        return None, None
    names_in = sum(1 for r in rows if name_col < len(r) and clean(r[name_col]) in PREFS)
    if names_in < 40:          # 都道府県別の表でなければ扱わない(総括表など)
        return None, None
    hdr = next((i for i in range(first) if any(clean(v) == "区分" for v in rows[i])), max(0, first - 4))
    width = max(len(r) for r in rows[hdr:first + 1])
    levels = []
    for i in range(hdr, first):
        r = [clean(v) for v in rows[i]] + [""] * (width - len(rows[i]))
        if all((not v) or re.fullmatch(r"[（(].*[)）]", v) for v in r):
            continue
        levels.append(r)
    for lv in levels[:1]:
        cur = ""
        for j in range(name_col + 1, width):
            if lv[j]:
                cur = lv[j]
            else:
                lv[j] = cur
    names = []
    for j in range(width):
        parts = []
        for lv in levels:
            v = lv[j] if j < len(lv) else ""
            if v and v != "区分" and (not parts or parts[-1] != v):
                parts.append(v)
        names.append("/".join(parts) or f"列{j + 1}")
    out = []
    for r in rows[first:]:
        nm = clean(r[name_col] if name_col < len(r) else "")
        if nm not in PREFS:
            continue
        vals = [clean(v) for v in r] + [""] * (width - len(r))
        out.append([pref_code(nm), nm] + vals[name_col + 1:width])
    return ["団体コード", "団体名"] + names[name_col + 1:width], out


def parse_table(rows):
    """見出し行(「団体コード」を含む行)から下に続く複数行の見出しをつなぎ、列名を作る"""
    hdr = None
    for i, r in enumerate(rows[:40]):
        if any(clean(v) == "団体コード" for v in r):
            hdr = i
            break
    if hdr is None:
        return parse_pref_table(rows)
    code_col = [clean(v) for v in rows[hdr]].index("団体コード")
    # データ開始行: 団体コード列に5～6桁の数字が初めて出る行
    start = None
    for i in range(hdr + 1, min(hdr + 30, len(rows))):
        if re.fullmatch(r"\d{5,6}", clean(rows[i][code_col] if code_col < len(rows[i]) else "")):
            start = i
            break
    if start is None:
        return None, None
    width = max(len(r) for r in rows[hdr:start + 1])
    levels = []
    for i in range(hdr, start):
        r = [clean(v) for v in rows[i]] + [""] * (width - len(rows[i]))
        # 単位だけの行((千円)など)は列名に入れない
        if all((not v) or re.fullmatch(r"[（(].*[)）]", v) for v in r):
            continue
        levels.append(r)
    # 最上段(グループ見出し)だけ横方向に引き継ぐ(結合セルの再現)
    for lv in levels[:1]:
        cur = ""
        for j in range(code_col + 2, width):
            if lv[j]:
                cur = lv[j]
            else:
                lv[j] = cur
    names = []
    for j in range(width):
        parts = []
        for lv in levels:
            v = lv[j] if j < len(lv) else ""
            if v and (not parts or parts[-1] != v):
                parts.append(v)
        names.append("/".join(parts) or f"列{j + 1}")
    names[code_col] = "団体コード"
    if code_col + 1 < width:
        names[code_col + 1] = "団体名"
    out = []
    for r in rows[start:]:
        code = clean(r[code_col] if code_col < len(r) else "")
        if not re.fullmatch(r"\d{5,6}", code):
            continue
        vals = [clean(v) for v in r] + [""] * (width - len(r))
        out.append(vals[code_col:width])
    return names[code_col:width], out


def main():
    (ROOT / "data" / "kessan").mkdir(parents=True, exist_ok=True)
    allroot = ROOT / "work" / "kessan_all"
    sources = []
    for level, idx in INDEXES.items():
        doc, base = page(idx)
        years = []
        for a in doc.iterfind(".//a[@href]"):
            href = urljoin(base, a.get("href"))
            y = year_label(a.text_content()) or url_year(href)
            if y and href.endswith((".html", ".htm")):
                years.append((y, href))
        years = sorted(set(years), reverse=True)
        print(level, "年度ページ", len(years), file=sys.stderr)
        latest = {y for y, _ in years[:KEEP_YEARS]}
        for y, yurl in years:
            try:
                ydoc, ybase = page(yurl)
            except Exception as e:  # noqa: BLE001
                print("skip", yurl, e, file=sys.stderr)
                continue
            for a in ydoc.iterfind(".//a[@href]"):
                href = urljoin(ybase, a.get("href"))
                ext = Path(href.split("?")[0]).suffix.lower()
                if ext not in (".xlsx", ".xls"):
                    continue
                # 表名: リンクの前後の見出し+リンク文字
                title = clean(a.text_content()) or Path(href).stem
                head = a.xpath("preceding::*[self::h2 or self::h3 or self::h4][1]")
                section = clean(head[0].text_content()) if head else ""
                table = re.sub(r"[\\/:*?\"<>|（）()]", "_", f"{level}_{section}_{title}")[:80].strip("_")
                try:
                    data = get(href).content
                    rows = rows_from_file(data, ext)
                    names, recs = parse_table(rows)
                except Exception as e:  # noqa: BLE001
                    print("fail", href, e, file=sys.stderr)
                    sources.append([y, level, table, href, 0, f"error: {e}"[:100]])
                    continue
                if not names:
                    sources.append([y, level, table, href, 0, "見出し不明"])
                    continue
                for dest in ([ROOT / "data" / "kessan" / str(y)] if y in latest else []) + [allroot / str(y)]:
                    dest.mkdir(parents=True, exist_ok=True)
                    with open(dest / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(names + ["原本URL"])
                        for r in recs:
                            w.writerow(r + [href])
                sources.append([y, level, table, href, len(recs), ""])
                print(y, level, table, len(recs), file=sys.stderr)
    with open(ROOT / "data" / "kessan" / "sources.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["年度", "区分", "表名", "原本URL", "団体数", "備考"])
        w.writerows(sorted(sources, reverse=True))
    import shutil
    if allroot.exists():
        shutil.make_archive(str(ROOT / "work" / "kessan_all"), "zip", allroot)
    ok = sum(1 for s in sources if s[4])
    print(f"表 {ok}/{len(sources)} 件を取り込み")


if __name__ == "__main__":
    main()
