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
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docrules import looks_like_doc  # noqa: E402

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ROOT = Path(__file__).resolve().parent.parent
UA = "zenkoku-jichitai-db/0.1 (public-interest open database of local government finance; +https://github.com/)"
WAIT = 2.0
MAX_FILES_PER_ENTITY = 40
MAX_BYTES = 60 * 1024 * 1024
WORKERS = 16
RETRIES = 3
ENTITY_BUDGET = 30 * 60   # 1団体あたりの上限時間(秒)。超えた分は「時間上限」として次回取り直す
# INCREMENTAL=1: 既存の data/docs/<県>.csv で取得済みの原本は残し、未取得・失敗分だけ取りに行く
INCREMENTAL = os.environ.get("INCREMENTAL") == "1"
ONLY_CODES = set(filter(None, os.environ.get("ONLY_CODES", "").split(",")))
# 取り直しても無駄な失敗(robots.txtで禁止・ファイルが無い)
FINAL_ERRORS = ("robots", "HTTPError: 404", "HTTPError: 410", "not a document", "too large")


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


def sniff_ext(data, url):
    """中身から種類を判定する(拡張子のないダウンロードURLに対応)。HTMLなら None"""
    head = data[:2048].lstrip().lower()
    if data[:4] == b"%PDF":
        return ".pdf"
    if data[:2] == b"PK":
        z = data[:4096]
        if b"xl/" in z:
            return ".xlsx"
        if b"word/" in z:
            return ".docx"
        return ".zip"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return ".doc" if url.lower().split("?")[0].endswith(".doc") else ".xls"
    if head.startswith((b"<!doctype html", b"<html")) or b"<html" in head[:512]:
        return None
    return Path(urlparse(url).path).suffix.lower() or ".bin"


def download(sess, url):
    """原本を取得。接続失敗・5xx・タイムアウトは間隔を空けて最大 RETRIES 回。証明書の不備は検証なしで取り直す(公開文書の読み取りのみ)"""
    verify = True
    err = ""
    for i in range(RETRIES):
        try:
            resp = sess.get(url, timeout=(20, 60), stream=True, verify=verify)   # 接続20秒・読み取り60秒
            if resp.status_code in (404, 410):
                return None, f"HTTPError: {resp.status_code}"
            resp.raise_for_status()
            buf = io.BytesIO()
            for chunk in resp.iter_content(1 << 16):
                buf.write(chunk)
                if buf.tell() > MAX_BYTES:
                    return None, "too large"
            return buf.getvalue(), ""
        except requests.exceptions.SSLError as e:
            err = f"SSLError: {e}"[:120]
            verify = False
            continue
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:120]
            code = getattr(getattr(e, "response", None), "status_code", 0) or 0
            if 400 <= code < 500 and code not in (408, 429):
                return None, err
            time.sleep(5 * (i + 1))
    return None, err


def pick(rows):
    """1団体あたり、確度の高いものを優先して最大 MAX_FILES_PER_ENTITY 件"""
    docs = [r for r in rows if r["is_document"] == "1" or looks_like_doc(r["url"], r.get("link_text", ""))]
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
    started = time.time()
    for r in pick(rows):
        url = r["url"]
        if time.time() - started > ENTITY_BUDGET:
            results.append({"code": code, "kind": r["kind"], "url": url, "link_text": r["link_text"],
                            "found_on": r["found_on"], "sha256": "", "bytes": 0, "pages": 0, "text_chars": 0,
                            "needs_ocr": "", "stored_as": "", "error": "時間上限(次回取り直し)"})
            continue
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
        data, err = download(sess, url)
        if err:
            rec["error"] = err
            results.append(rec)
            continue
        sha = hashlib.sha256(data).hexdigest()
        ext = sniff_ext(data, url)
        if ext is None:
            rec["error"] = "not a document (HTML)"
            results.append(rec)
            continue
        rec["sha256"], rec["bytes"] = sha, len(data)
        if data[:4] == b"%PDF":
            pages, text = pdf_text(data)
        elif data[:2] == b"PK" and ext in (".xlsx", ".zip"):
            pages, text = xlsx_text(data) if ext == ".xlsx" else (0, "")
        else:
            pages, text = 0, ""
        # PDFから取り出した文字に壊れた文字(サロゲート)が混じると保存で止まるため、置き換えておく
        text = (text or "").encode("utf-8", "replace").decode("utf-8")
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


def process_entity_safe(args):
    """1団体の失敗で県全体が止まらないようにする"""
    try:
        return process_entity(args)
    except Exception as e:  # noqa: BLE001
        print(f"{args[1]}: 原本の取得を中断 {type(e).__name__}: {e}")
        return []


def main():
    pref = sys.argv[1].zfill(2)
    by_code = defaultdict(list)
    with open(ROOT / "data" / "links" / f"{pref}.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_code[r["code"]].append(r)
    keep = []
    out_path = ROOT / "data" / "docs" / f"{pref}.csv"
    if INCREMENTAL and out_path.exists():
        # 取得済み・取り直しても無駄なものは残し、それ以外(未取得・一時的な失敗)だけ取りに行く
        done = set()
        with open(out_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["sha256"] or r["error"].startswith(FINAL_ERRORS):
                    keep.append(r)
                    done.add(r["url"])
        by_code = {c: [r for r in rows if r["url"] not in done] for c, rows in by_code.items()}
    if ONLY_CODES:
        by_code = {c: rows for c, rows in by_code.items() if c in ONLY_CODES}
    jobs = [(pref, code, rows) for code, rows in by_code.items() if rows]
    print(f"{pref}: 取りに行く団体 {len(jobs)} / 残す取得済み {len(keep)} 件")
    out = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for res in ex.map(process_entity_safe, jobs):
            out.extend(res)
    if keep:
        got = {r["url"] for r in out}
        out = [r for r in keep if r["url"] not in got] + out
    (ROOT / "data" / "docs").mkdir(parents=True, exist_ok=True)
    fields = ["code", "kind", "url", "link_text", "found_on", "sha256", "bytes", "pages", "text_chars",
              "needs_ocr", "stored_as", "error"]
    with open(ROOT / "data" / "docs" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    ok = sum(1 for r in out if r["sha256"])
    ocr = sum(1 for r in out if str(r["needs_ocr"]) == "1")
    print(f"{pref}: files {ok}/{len(out)}, needs_ocr {ocr}")


if __name__ == "__main__":
    main()
