"""results ブランチの収集結果から、巡回に失敗・不足した団体を選び、再巡回の計画(GitHub Actionsのmatrix)を出す。

選ぶ条件(どれか):
  - 読めたページが20未満
  - エラー(接続失敗・時間上限など)
  - 予算・入札・補助金のどれかで確度の高い原本が0件 (missing のとき)
  - 原本ファイルらしいリンクが1件もない

使い方: python crawler/recrawl_plan.py <resultsのフォルダ>   → 標準出力に {"include":[{"pref":"05","codes":"052094,..."}]}
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import looks_like_doc  # noqa: E402

base = Path(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else "failed"   # failed: 失敗のみ / missing: 原本0件の種類がある団体も
plan = defaultdict(list)
for p in sorted((base / "status").glob("*.csv")):
    pref = p.stem
    strong = defaultdict(lambda: defaultdict(int))
    docs = defaultdict(int)
    lp = base / "links" / p.name
    if lp.exists():
        with open(lp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("strong") == "1":
                    strong[r["code"]][r["kind"]] += 1
                if r.get("is_document") == "1" or looks_like_doc(r.get("url", ""), r.get("link_text", "")):
                    docs[r["code"]] += 1
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pages = int(r.get("pages") or 0)
            failed = pages < 20 or r.get("error") or docs[r["code"]] == 0
            missing = any(strong[r["code"]][k] == 0 for k in ("budget", "bids", "grants"))
            if failed or (mode == "missing" and missing):
                plan[pref].append(r["code"])
include = [{"pref": k, "codes": ",".join(v)} for k, v in sorted(plan.items()) if v]
print(json.dumps({"include": include}, ensure_ascii=False))
print(f"再巡回: {sum(len(v) for v in plan.values())} 団体 / {len(include)} 都道府県", file=sys.stderr)
