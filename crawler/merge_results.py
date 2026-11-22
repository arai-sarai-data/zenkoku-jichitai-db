"""再巡回の結果を、results ブランチにある前回の結果へ団体単位で差し替える。

使い方: python crawler/merge_results.py <県コード> <前回resultsのフォルダ>
  data/links/<県>.csv と data/status/<県>.csv(今回分)を、前回分と合わせて上書きする。
  今回巡回した団体の行は今回分に置き換え、それ以外の団体は前回分を残す。
  ただし今回のほうが読めたページが少ない団体は、前回分を残す(悪化させない)。
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
pref, prev = sys.argv[1].zfill(2), Path(sys.argv[2])


def read(p):
    if not p.exists():
        return [], []
    with open(p, encoding="utf-8") as f:
        rd = csv.DictReader(f)
        return list(rd), rd.fieldnames or []


new_st, st_fields = read(ROOT / "data" / "status" / f"{pref}.csv")
old_st, old_st_fields = read(prev / "status" / f"{pref}.csv")
new_ln, ln_fields = read(ROOT / "data" / "links" / f"{pref}.csv")
old_ln, old_ln_fields = read(prev / "links" / f"{pref}.csv")

old_pages = {r["code"]: int(r.get("pages") or 0) for r in old_st}
replace = {r["code"] for r in new_st if int(r.get("pages") or 0) >= old_pages.get(r["code"], 0)}

fields = list(dict.fromkeys((old_st_fields or []) + (st_fields or [])))
status = [r for r in old_st if r["code"] not in replace] + [r for r in new_st if r["code"] in replace]
status.sort(key=lambda r: r["code"])
with open(ROOT / "data" / "status" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(status)

lfields = list(dict.fromkeys((old_ln_fields or []) + (ln_fields or [])))
links = [r for r in old_ln if r["code"] not in replace] + [r for r in new_ln if r["code"] in replace]
with open(ROOT / "data" / "links" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=lfields, extrasaction="ignore")
    w.writeheader()
    w.writerows(links)
print(f"{pref}: 差し替え {len(replace)} 団体 / 合計 {len(status)} 団体")
