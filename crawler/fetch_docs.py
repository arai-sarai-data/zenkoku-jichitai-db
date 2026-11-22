"""見つけた原本ファイル(PDF・Excel等)を取得し、文字が取り出せるか(OCRが要るか)を調べる。

使い方: python crawler/fetch_docs.py 01
入力:   data/links/<県>.csv
出力:   work/originals/<県>/<団体コード>/<sha256先頭16桁>.<拡張子>   原本のコピー(リポジトリには入れず、Releaseに置く)
        work/text/<県>/<団体コード>/<sha16>.txt                       取り出した文字
        data/docs/<県>.csv   1行=1原本 (url, sha256, bytes, pages, text_chars, needs_ocr, ...)
"""
import csv
import hashlib
import io
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

ROOT = Path(__file__).resolve().parent.parent
UA = "zenkoku-jichitai-db/0.1 (public-interest open database of local government finance; +https://github.com/)"
WAIT = 2.0
MAX_FILES_PER_ENTITY = 40
MAX_BYTES = 60 * 1024 * 1024
WORKERS = 16


def pdf_text(data):
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = len(reader.pages)
        texts = []
        for p in reader.pages:
            try:
                texts.append(p.extract_text() or "")
            except Exception:  # noqa: BLE001
                texts.append("")
        return pages, "\n\f".join(texts)
    except Exception:  # noqa: BLE001
        return 0, ""


def xlsx_text(data):
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            lines.append(f"## {ws.title}")
            for row in ws.iter_rows(values_only=True):
                vals = ["" if v is None else str(v) for v in row]
                if any(vals):
                    lines.append("\t".join(vals))
        return len(wb.worksheets), "\n".join(lines)
    except Exception:  # noqa: BLE001
        return 0, ""


def pick(rows):
    """1団体あたり、確度の高いものを優先して最大 MAX_FILES_PER_ENTITY 件"""
    docs = [r for r in rows if r["is_document"] == "1"]
    docs.sort(key=lambda r: (r["strong"] != "1", r["kind"]))
    seen, out = set(), []
    for r in docs:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        out.append(r)
        if len(out) >= MAX_FILES_PER_ENTITY:
            break
    return out


def process_entity(args):
    pref, code, rows = args
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    robots = {}
    last = defaultdict(float)
    results = []
    for r in pick(rows):
        url = r["url"]
        host = urlparse(url).netloc
        if host not in robots:
            rp = RobotFileParser()
            try:
                rr = sess.get(f"{urlparse(url).scheme}://{host}/robots.txt", timeout=20)
                rp.parse(rr.text.splitlines() if rr.status_code == 200 else [])
            except Exception:  # noqa: BLE001
                rp.parse([])
            robots[host] = rp
        rec = {"code": code, "kind": r["kind"], "url": url, "link_text": r["link_text"], "found_on": r["found_on"],
               "sha256": "", "bytes": 0, "pages": 0, "text_chars": 0, "needs_ocr": "", "stored_as": "", "error": ""}
        if not robots[host].can_fetch(UA, url):
            rec["error"] = "robots"
            results.append(rec)
            continue
        wait = WAIT - (time.time() - last[host])
        if wait > 0:
            time.sleep(wait)
        last[host] = time.time()
        try:
            resp = sess.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            buf = io.BytesIO()
            for chunk in resp.iter_content(1 << 16):
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    raise ValueError("too large")
            data = buf.getvalue()
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:120]
            results.append(rec)
            continue
        sha = hashlib.sha256(data).hexdigest()
        ext = Path(urlparse(url).path).suffix.lower() or ".bin"
        rec["sha256"], rec["bytes"] = sha, len(data)
        if data[:4] == b"%PDF":
            pages, text = pdf_text(data)
        elif data[:2] == b"PK" and ext in (".xlsx", ".zip"):
            pages, text = xlsx_text(data) if ext == ".xlsx" else (0, "")
        else:
            pages, text = 0, ""
        rec["pages"], rec["text_chars"] = pages, len(text.strip())
        if data[:4] == b"%PDF":
            # 1ページあたり50文字未満なら画像PDFとみなしOCR対象
            rec["needs_ocr"] = int(pages > 0 and rec["text_chars"] / pages < 50)
        tdir = ROOT / "work" / "text" / pref / code
        tdir.mkdir(parents=True, exist_ok=True)
        if text:
            (tdir / (sha[:16] + ".txt")).write_text(text, encoding="utf-8")
        # 原本のコピーは、OCRが必要なもの(文字が取り出せない画像PDF)だけ保存する。
        # それ以外は原本URL+ハッシュ値+取り出した文字で足りる(容量を抑えるため)。
        if rec["needs_ocr"] == 1:
            odir = ROOT / "work" / "originals" / pref / code
            odir.mkdir(parents=True, exist_ok=True)
            name = sha[:16] + ext
            (odir / name).write_bytes(data)
            rec["stored_as"] = f"{pref}/{code}/{name}"
        results.append(rec)
    return results


def main():
    pref = sys.argv[1].zfill(2)
    by_code = defaultdict(list)
    with open(ROOT / "data" / "links" / f"{pref}.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_code[r["code"]].append(r)
    jobs = [(pref, code, rows) for code, rows in by_code.items()]
    out = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for res in ex.map(process_entity, jobs):
            out.extend(res)
    (ROOT / "data" / "docs").mkdir(parents=True, exist_ok=True)
    fields = ["code", "kind", "url", "link_text", "found_on", "sha256", "bytes", "pages", "text_chars",
              "needs_ocr", "stored_as", "error"]
    with open(ROOT / "data" / "docs" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    ok = sum(1 for r in out if r["sha256"])
    ocr = sum(1 for r in out if r["needs_ocr"] == 1)
    print(f"{pref}: files {ok}/{len(out)}, needs_ocr {ocr}")


if __name__ == "__main__":
    main()
