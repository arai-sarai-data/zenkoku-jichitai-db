"""日本国内のブラウザで巡回した結果(JSON)を、results ブランチの県ごとの結果に団体単位で差し替える。

入力: JSON  {団体コード: {"name":..,"pref":..,"official_url":..,"final_url":..,"pages":N,"codes":{..},"found":[[kind,url,text,found_on,is_doc,external,strong],...]}}
使い方: python tools/ingest_browser.py browser_results.json <results ブランチのフォルダ>
         → data/links/<県>.csv, data/status/<県>.csv を作り、crawler/merge_results.py で前回分と合わせる
"""
import csv
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
res = json.load(open(sys.argv[1], encoding="utf-8"))
prev = Path(sys.argv[2])
today = time.strftime("%Y-%m-%d")
by_pref = defaultdict(dict)
for code, r in res.items():
    by_pref[code[:2]][code] = r
KINDS = ["budget", "bids", "pref_muni_budget", "grants"]
for pref, ents in by_pref.items():
    (ROOT / "data" / "links").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "status").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "links" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "kind", "url", "link_text", "found_on", "is_document", "external", "strong", "retrieved"])
        for code, r in sorted(ents.items()):
            for kind, url, text, page, is_doc, ext, strong in sorted(r["found"]):
                w.writerow([code, r["name"], kind, url, text, page, is_doc, ext, strong, today])
    with open(ROOT / "data" / "status" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "pref", "name", "official_url", "pages", "error", *KINDS, "final_url", "codes", "via"])
        w.writeheader()
        for code, r in sorted(ents.items()):
            cnt = {k: sum(1 for x in r["found"] if x[0] == k) for k in KINDS}
            w.writerow({"code": code, "pref": r.get("pref", ""), "name": r["name"], "official_url": r.get("official_url", ""),
                        "pages": r["pages"], "error": "" if r["pages"] else "取得0ページ", **cnt,
                        "final_url": r.get("final_url", ""), "codes": " ".join(f"{k}:{v}" for k, v in sorted(r.get("codes", {}).items())),
                        "via": "国内ブラウザ"})
    subprocess.run([sys.executable, str(ROOT / "crawler" / "merge_results.py"), pref, str(prev)], check=True)
print("取り込み:", {p: len(e) for p, e in by_pref.items()})
