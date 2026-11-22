"""自治体マスタ(全国1,788団体: 47都道府県+1,741市区町村)を作る。

- 市区町村: 総務省「市町村別決算状況調」の概況Excel(都市別・町村別)から団体コードと名称を取る
- 都道府県: 団体コードを計算で作る
- 公式サイトURL: Wikidata(P429=全国地方公共団体コード, P856=公式サイト)から引く

出力: data/master.csv  (code,pref,name,kind,official_url)
"""
import csv
import io
import re
import sys
from urllib.parse import urlparse
from pathlib import Path

import openpyxl
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "master.csv"
UA = {"User-Agent": "zenkoku-jichitai-db/0.1 (public-interest open database; contact via GitHub)"}

KESSAN_GAIKYO = [
    "https://www.soumu.go.jp/main_content/001061669.xlsx",  # 令和6年度 都市別 概況
    "https://www.soumu.go.jp/main_content/001061674.xlsx",  # 令和6年度 町村別 概況
]
PREFS = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
         "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
         "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
         "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
         "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]


def check_digit(code5: str) -> str:
    s = sum(int(c) * w for c, w in zip(code5, (6, 5, 4, 3, 2)))
    return str((11 - s % 11) % 10)


def municipalities():
    rows = []
    for url in KESSAN_GAIKYO:
        r = requests.get(url, headers=UA, timeout=180)
        r.raise_for_status()
        ws = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True).worksheets[0]
        pref = ""
        for row in ws.iter_rows(values_only=True):
            o = str(row[14]).strip() if len(row) > 14 and row[14] is not None else ""   # O列: 団体コード
            p = str(row[15]).strip() if len(row) > 15 and row[15] is not None else ""   # P列: 名称
            compact = p.replace(" ", "").replace("　", "")
            if not o and compact in PREFS:
                pref = compact
            elif len(o) == 6 and o.isdigit():
                kind = "特別区" if o.startswith("131") and int(o[2:5]) <= 123 else ("市" if url.endswith("669.xlsx") else "町村")
                rows.append({"code": o, "pref": pref, "name": p, "kind": kind})
    return rows


def prefectures():
    out = []
    for i, name in enumerate(PREFS, start=1):
        c5 = f"{i:02d}000"
        out.append({"code": c5 + check_digit(c5), "pref": name, "name": name, "kind": "都道府県"})
    return out


def load_overrides():
    """手で確かめて直した公式URL(data/url_overrides.csv)"""
    path = ROOT / "data" / "url_overrides.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["code"]: r["official_url"] for r in csv.DictReader(f)}


def page_mentions(url, name, pref):
    """トップページにその団体名が出てくるか。'ok' / 'ng' / 'unreachable'"""
    try:
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        text = r.content.decode(r.apparent_encoding or "utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return "unreachable"
    if r.status_code >= 400:
        return "unreachable"
    short = name.replace("　", "").replace(" ", "")
    return "ok" if (short in text or (pref + short) in text) else "ng"


def wikidata_sites():
    q = """SELECT ?code ?site WHERE { ?item wdt:P429 ?code . ?item wdt:P856 ?site . }"""
    r = requests.get("https://query.wikidata.org/sparql", params={"query": q, "format": "json"},
                     headers={**UA, "Accept": "application/sparql-results+json"}, timeout=300)
    r.raise_for_status()
    cands = {}
    for b in r.json()["results"]["bindings"]:
        code = b["code"]["value"].strip()
        url = b["site"]["value"].strip()
        if len(code) == 5:
            code += check_digit(code)
        cands.setdefault(code, []).append(url)
    return cands


FOREIGN = re.compile(r"(//(en|english|foreign|lang|multilingual|kr|ko|zh|cn|tw)[.-])|(/(en|english|foreign|lang|multilingual|global|ko|zh|cn|zh-cn|zh-tw)(/|$))", re.I)


def ranked(urls):
    def key(u):
        path = urlparse(u).path.strip("/")
        return (bool(FOREIGN.search(u)), ".lg.jp" not in u, not urlparse(u).netloc.endswith(".jp"),
                len(path), not u.startswith("https"), len(u))
    return sorted(set(urls), key=key)


def best_url(urls):
    """同じ団体に複数の公式URLがあるとき、日本語のトップページらしいものを選ぶ"""
    def key(u):
        path = urlparse(u).path.strip("/")
        return (
            bool(FOREIGN.search(u)),          # 外国語版は後回し
            ".lg.jp" not in u,                # .lg.jp を優先
            len(path),                        # トップに近いもの
            not u.startswith("https"),
            len(u),
        )
    return sorted(set(urls), key=key)[0]


def main():
    rows = prefectures() + municipalities()
    try:
        cands = wikidata_sites()
    except Exception as e:  # noqa: BLE001
        print("wikidata failed:", e, file=sys.stderr)
        cands = {}
    overrides = load_overrides()
    from concurrent.futures import ThreadPoolExecutor

    def choose(r):
        if r["code"] in overrides:
            return overrides[r["code"]], "override"
        urls = ranked(cands.get(r["code"], []))
        first_unreachable = None
        for u in urls:
            res = page_mentions(u, r["name"], r["pref"])
            if res == "ok":
                return u, "ok"
            if res == "unreachable" and first_unreachable is None:
                first_unreachable = u
        # 団体名が確認できない: 海外から読めないだけ(unreachable)ならその候補を使う。全部 ng なら要確認
        if first_unreachable:
            return first_unreachable, "unreachable"
        return (urls[0] if urls else ""), "ng"

    with ThreadPoolExecutor(32) as ex:
        picked = list(ex.map(choose, rows))
    for r, (u, chk) in zip(rows, picked):
        r["official_url"], r["url_check"] = u, chk
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "pref", "name", "kind", "official_url", "url_check"])
        w.writeheader()
        w.writerows(rows)
    n_muni = sum(1 for r in rows if r["kind"] != "都道府県")
    n_url = sum(1 for r in rows if r["official_url"])
    from collections import Counter
    print(f"団体数 {len(rows)} (市区町村 {n_muni}) / 公式URLあり {n_url} / 確認 {dict(Counter(r['url_check'] for r in rows))}")
    for r in rows:
        if r["url_check"] == "ng":
            print("要確認(団体名が見当たらない):", r["code"], r["name"], r["official_url"], file=sys.stderr)
    if n_muni != 1741:
        print("警告: 市区町村数が1,741ではありません", file=sys.stderr)


if __name__ == "__main__":
    main()
