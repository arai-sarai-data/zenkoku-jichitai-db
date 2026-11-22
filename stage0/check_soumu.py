"""段階0: 総務省の決算データ(市町村別決算状況調・決算カード)で全国がそろうか確認する。

1. 令和6年度 市町村別決算状況調のExcel 10本を取得し、載っている団体コードの数を数える
   (都市別+町村別で全国1,741市区町村がそろうか)
2. 決算カード(令和6年度・北海道の1本目)のPDFを取得し、1ページ=1団体かを確認する
   (原本リンクを「PDF+ページ番号」で作れるか)

出力: stage0/out/soumu_summary.json
"""
import io
import json
import re
from pathlib import Path

import openpyxl
import requests
from pypdf import PdfReader

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "zenkoku-jichitai-db stage0 check (non-commercial research)"}

KESSAN_FILES = {
    "都市_概況": "https://www.soumu.go.jp/main_content/001061669.xlsx",
    "都市_歳入内訳": "https://www.soumu.go.jp/main_content/001061670.xlsx",
    "都市_目的別歳出": "https://www.soumu.go.jp/main_content/001061671.xlsx",
    "都市_性質別歳出": "https://www.soumu.go.jp/main_content/001061672.xlsx",
    "都市_地方債現在高等": "https://www.soumu.go.jp/main_content/001061673.xlsx",
    "町村_概況": "https://www.soumu.go.jp/main_content/001061674.xlsx",
    "町村_歳入内訳": "https://www.soumu.go.jp/main_content/001061675.xlsx",
    "町村_目的別歳出": "https://www.soumu.go.jp/main_content/001061676.xlsx",
    "町村_性質別歳出": "https://www.soumu.go.jp/main_content/001061677.xlsx",
    "町村_地方債現在高等": "https://www.soumu.go.jp/main_content/001061678.xlsx",
}
CARD_PDF = "https://www.soumu.go.jp/main_content/001063944.pdf"  # 令和6年度 市町村決算カード 北海道1
CODE_RE = re.compile(r"^\d{5,6}$")  # 団体コード(5桁 or 検査数字付き6桁)


def get(url):
    r = requests.get(url, headers=UA, timeout=180)
    r.raise_for_status()
    return r.content


def main():
    summary = {"kessan": {}, "card": {}}
    all_codes = set()
    for name, url in KESSAN_FILES.items():
        try:
            wb = openpyxl.load_workbook(io.BytesIO(get(url)), read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001
            summary["kessan"][name] = {"error": str(e)}
            continue
        info = {"sheets": {}}
        codes = set()
        for ws in wb.worksheets:
            header = []
            n = 0
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i < 8:
                    header.append([c for c in row[:12] if c is not None])
                for c in row[:4]:
                    s = str(c).strip() if c is not None else ""
                    if CODE_RE.match(s):
                        codes.add(s[:5])
                        break
                n += 1
            info["sheets"][ws.title] = {"rows": n, "head": header}
        info["distinct_codes"] = len(codes)
        all_codes |= codes
        summary["kessan"][name] = info

    summary["all_distinct_codes"] = len(all_codes)
    summary["all_codes_sample"] = sorted(all_codes)[:20]

    try:
        reader = PdfReader(io.BytesIO(get(CARD_PDF)))
        pages = len(reader.pages)
        heads = []
        for p in reader.pages[:5]:
            text = (p.extract_text() or "").strip().splitlines()
            heads.append(text[:6])
        summary["card"] = {"url": CARD_PDF, "pages": pages, "first_pages_head": heads}
    except Exception as e:  # noqa: BLE001
        summary["card"] = {"error": str(e)}

    (OUT / "soumu_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("distinct municipality codes:", summary["all_distinct_codes"], "card pages:", summary["card"].get("pages"))


if __name__ == "__main__":
    main()
