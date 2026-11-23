"""data/docs/*.csv の取得状況を表示する(原本の取得数・取れた団体数・失敗の内訳)"""
import csv
import glob
import re
from collections import Counter

tot = ok = 0
codes, errs = set(), Counter()
for f in glob.glob("data/docs/*.csv"):
    with open(f, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            tot += 1
            if r["sha256"]:
                ok += 1
                codes.add(r["code"])
            elif r["error"]:
                errs[re.sub(r"[:(].*", "", r["error"])] += 1
print(f"原本 {ok}/{tot} 件、原本を取れた団体 {len(codes)}")
for k, v in errs.most_common(10):
    print(f"  失敗 {k}: {v}")
