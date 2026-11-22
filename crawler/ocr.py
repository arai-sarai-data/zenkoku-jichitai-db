"""文字が取り出せなかった(画像の)PDFだけをOCRにかける。

使い方: python crawler/ocr.py 01
入力:   data/docs/<県>.csv (needs_ocr=1 の行), work/originals/<県>/...
出力:   work/text/<県>/<団体コード>/<sha16>.txt, data/docs/<県>.csv の text_chars/needs_ocr を更新
必要:   tesseract-ocr, tesseract-ocr-jpn, poppler-utils (pdftoppm)
"""
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_PAGES = 200


def ocr_pdf(path: Path) -> str:
    out = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-l", str(MAX_PAGES), "-png", str(path), f"{td}/p"],
                       check=True, timeout=1800)
        for img in sorted(Path(td).glob("p-*.png")):
            r = subprocess.run(["tesseract", str(img), "-", "-l", "jpn", "--psm", "6"],
                               capture_output=True, text=True, timeout=300)
            out.append(r.stdout)
    return "\n\f".join(out)


def main():
    pref = sys.argv[1].zfill(2)
    path = ROOT / "data" / "docs" / f"{pref}.csv"
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    done = {}
    for r in rows:
        if r["needs_ocr"] != "1" or not r["stored_as"]:
            continue
        src = ROOT / "work" / "originals" / r["stored_as"]
        if r["sha256"] in done:
            r["text_chars"], r["needs_ocr"] = done[r["sha256"]], "ocr"
            continue
        try:
            text = ocr_pdf(src)
        except Exception as e:  # noqa: BLE001
            r["error"] = f"ocr: {e}"[:120]
            continue
        tdir = ROOT / "work" / "text" / pref / r["code"]
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / (r["sha256"][:16] + ".txt")).write_text(text, encoding="utf-8")
        r["text_chars"], r["needs_ocr"] = len(text.strip()), "ocr"
        done[r["sha256"]] = r["text_chars"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["code"])
        w.writeheader()
        w.writerows(rows)
    print(f"{pref}: OCR {len(done)} files")


if __name__ == "__main__":
    main()
