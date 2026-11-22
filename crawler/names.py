"""自治体名のローマ字(英語表記)を作る。多言語ページの見出しに使う。

読み(カナ)は総務省「全国地方公共団体コード」の一覧(Excel)から取り、ヘボン式でローマ字にする。
  例: 札幌市 / ｻｯﾎﾟﾛｼ → Sapporo City、 檜原村 / ﾋﾉﾊﾗﾑﾗ → Hinohara Village

出力: data/names_en.csv  code,name,kana,name_en
"""
import csv
import io
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parent.parent
PAGE = "https://www.soumu.go.jp/denshijiti/code.html"
UA = {"User-Agent": "zenkoku-jichitai-db/0.1 (+https://github.com/arai-sarai-data/zenkoku-jichitai-db)"}

# カナ → ローマ字(ヘボン式)。拗音・促音・長音を扱う
DIGRAPH = {
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "シャ": "sha", "シュ": "shu", "ショ": "sho", "チャ": "cha", "チュ": "chu",
    "チョ": "cho", "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo", "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo", "ミャ": "mya",
    "ミュ": "myu", "ミョ": "myo", "リャ": "rya", "リュ": "ryu", "リョ": "ryo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "ジャ": "ja", "ジュ": "ju", "ジョ": "jo", "ビャ": "bya", "ビュ": "byu", "ビョ": "byo", "ピャ": "pya", "ピュ": "pyu",
    "ピョ": "pyo", "ヂャ": "ja", "ヂュ": "ju", "ヂョ": "jo",
}
MONO = dict(zip(
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヰヱヲン"
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポァィゥェォヴ",
    ["a", "i", "u", "e", "o", "ka", "ki", "ku", "ke", "ko", "sa", "shi", "su", "se", "so", "ta", "chi", "tsu", "te", "to",
     "na", "ni", "nu", "ne", "no", "ha", "hi", "fu", "he", "ho", "ma", "mi", "mu", "me", "mo", "ya", "yu", "yo",
     "ra", "ri", "ru", "re", "ro", "wa", "i", "e", "o", "n",
     "ga", "gi", "gu", "ge", "go", "za", "ji", "zu", "ze", "zo", "da", "ji", "zu", "de", "do",
     "ba", "bi", "bu", "be", "bo", "pa", "pi", "pu", "pe", "po", "a", "i", "u", "e", "o", "vu"]))


def kana_to_romaji(kana):
    s = unicodedata.normalize("NFKC", kana or "").replace(" ", "").replace("　", "")
    s = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)   # ひらがな → カタカナ
    out, i = [], 0
    while i < len(s):
        two = s[i:i + 2]
        if two in DIGRAPH:
            out.append(DIGRAPH[two]); i += 2; continue
        c = s[i]
        if c == "ッ":
            nxt = DIGRAPH.get(s[i + 1:i + 3]) or MONO.get(s[i + 1:i + 2], "")
            out.append("t" if nxt.startswith("ch") else nxt[:1]); i += 1; continue
        if c == "ー":
            i += 1; continue   # 長音は表記しない(Osaka, Tokyo と同じ流儀)
        out.append(MONO.get(c, "")); i += 1
    r = "".join(out)
    r = re.sub(r"ou(?=[^aeiou]|$)", "o", r)                 # 長母音 ou → o (Tōkyō → Tokyo)
    r = re.sub(r"uu", "u", r)
    r = re.sub(r"oo(?=[^aeiou]|$)", "o", r)
    return r


SUFFIX = [("都", "ト", "Metropolis"), ("道", "ドウ", ""), ("府", "フ", "Prefecture"), ("県", "ケン", "Prefecture"),
          ("市", "シ", "City"), ("区", "ク", "City"), ("町", "マチ", "Town"), ("町", "チョウ", "Town"),
          ("村", "ムラ", "Village"), ("村", "ソン", "Village")]


def english(name, kana):
    k = unicodedata.normalize("NFKC", kana or "").replace(" ", "")
    k = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in k)
    if name == "北海道":
        return "Hokkaido"
    if name == "東京都":
        return "Tokyo Metropolis"
    for kanji, ksuf, word in SUFFIX:
        if name.endswith(kanji) and k.endswith(ksuf):
            base = kana_to_romaji(k[: -len(ksuf)])
            return (base[:1].upper() + base[1:] + (" " + word if word else "")).strip()
    base = kana_to_romaji(k)
    return base[:1].upper() + base[1:]


def read_book(content):
    """団体コード一覧のExcelから {code: 行} を読む。見出しの改行・数値のコードにも対応"""
    import openpyxl
    if content[:2] != b"PK":   # 古い .xls
        import xlrd
        bk = xlrd.open_workbook(file_contents=content)
        sheets = [(sh.name, (sh.row_values(i) for i in range(sh.nrows))) for sh in bk.sheets()]
    else:
        wb = openpyxl.load_workbook(io.BytesIO(content))   # read_only だと表の範囲を誤って1行しか読めないことがある
        sheets = [(ws.title, ws.iter_rows(values_only=True)) for ws in wb.worksheets]

    def norm(v):
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return re.sub(r"\s", "", unicodedata.normalize("NFKC", str(v if v is not None else "")))

    rows = {}
    for title, it in sheets:
        head = None
        for r in it:
            cells = [norm(c) for c in r]
            if head is None:
                if any("団体コード" in c for c in cells):
                    head = cells
                    print(f"  [{title}] 見出し: {head}")
                continue

            def get(*keys):
                for key in keys:
                    for i, h in enumerate(head):
                        if key in h and i < len(cells) and cells[i]:
                            return cells[i]
                return ""
            code = re.sub(r"\D", "", get("団体コード"))
            if not code:
                continue
            code = code.zfill(6)[:6]   # 数値で保存されていると先頭の0が落ちる
            city, city_k = get("市区町村名(漢字)", "市区町村名"), get("市区町村名(カナ)", "市区町村名カナ")
            pref, pref_k = get("都道府県名(漢字)", "都道府県名"), get("都道府県名(カナ)", "都道府県名カナ")
            if city == city_k:
                city = ""
            name, kana = (city, city_k) if city else (pref, pref_k)
            if name and code not in rows:
                rows[code] = {"code": code, "name": name, "kana": kana, "name_en": english(name, kana)}
        print(f"  [{title}] ここまで {len(rows)} 団体")
    return rows


def main():
    page = requests.get(PAGE, headers=UA, timeout=60)
    page.encoding = page.apparent_encoding
    links = list(dict.fromkeys(re.findall(r'href="([^"]+\.xlsx?)"', page.text)))
    if not links:
        sys.exit("団体コード一覧のExcelが見つかりません")
    best = {}
    for href in links[:6]:   # 最初のExcelが一覧とは限らないので順に試す
        print("試す:", urljoin(PAGE, href))
        try:
            got = read_book(requests.get(urljoin(PAGE, href), headers=UA, timeout=120).content)
        except Exception as e:   # noqa: BLE001
            print("  読めず:", e)
            continue
        if len(got) > len(best):
            best = got
        if len(best) >= 1700:
            break
    rows = best
    if len(rows) < 1700:
        sys.exit(f"読み取れた団体が少なすぎます: {len(rows)}")
    out = ROOT / "data" / "names_en.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "kana", "name_en"])
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["code"]))
    print(f"names_en: {len(rows)} 団体")


if __name__ == "__main__":
    main()
