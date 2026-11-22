"""段階0: 官公需情報ポータルサイト検索APIの収録状況を確認する。

都道府県(LG_Code 01-47) x 調達種別(1物品/2工事/3役務) x 月 ごとに件数を数え、
結果に出てくる市区町村(CityCode)の数から、全国1,741市区町村のうち
何自治体の入札が載っているかを推定する。

出力: stage0/out/kkj_summary.json, stage0/out/kkj_city_counts.csv
"""
import csv
import json
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import requests

API = "https://www.kkj.go.jp/api/"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
WAIT = 2.0  # 秒。政府サーバーに負荷をかけないよう間隔を空ける
MONTHS = 3  # 直近何か月分を調べるか


def month_ranges(n):
    today = date.today()
    y, m = today.year, today.month
    ranges = []
    for _ in range(n):
        start = date(y, m, 1)
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = date(ny, nm, 1)
        ranges.append((start.isoformat(), end.isoformat()))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return ranges


def local(tag):
    return tag.rsplit("}", 1)[-1]


def query(params):
    for attempt in range(3):
        try:
            r = requests.get(API, params=params, timeout=60)
            r.raise_for_status()
            return ET.fromstring(r.content)
        except Exception as e:  # noqa: BLE001
            print("retry", attempt, params, e)
            time.sleep(10)
    return None


def main():
    hits_total = 0
    truncated = []
    city_counter = Counter()
    city_names = {}
    org_counter = Counter()
    pref_hits = defaultdict(int)
    has_doc_uri = 0
    items_seen = 0
    sample = []

    for pref in range(1, 48):
        lg = f"{pref:02d}"
        for start, end in month_ranges(MONTHS):
            for cat in ("1", "2", "3"):
                params = {
                    "LG_Code": lg,
                    "Category": cat,
                    "CFT_Issue_Date": f"{start}/{end}",
                    "Count": "1000",
                }
                root = query(params)
                time.sleep(WAIT)
                if root is None:
                    continue
                hits = None
                results = []
                for el in root.iter():
                    name = local(el.tag)
                    if name == "SearchHits" and el.text:
                        hits = int(el.text)
                    elif name == "SearchResult":
                        results.append({local(c.tag): (c.text or "").strip() for c in el})
                hits = hits if hits is not None else len(results)
                hits_total += hits
                pref_hits[lg] += hits
                if hits > len(results):
                    truncated.append({**params, "hits": hits, "returned": len(results)})
                for it in results:
                    items_seen += 1
                    code = it.get("CityCode", "")
                    if code:
                        city_counter[code] += 1
                        city_names[code] = it.get("PrefectureName", "") + it.get("CityName", "")
                    org_counter[it.get("OrganizationName", "")] += 1
                    if it.get("ExternalDocumentURI"):
                        has_doc_uri += 1
                    if len(sample) < 20:
                        sample.append(it)
        print(lg, pref_hits[lg])

    with open(OUT / "kkj_city_counts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["CityCode", "Name", "items"])
        for code, n in city_counter.most_common():
            w.writerow([code, city_names.get(code, ""), n])

    summary = {
        "period_months": MONTHS,
        "hits_total": hits_total,
        "items_seen": items_seen,
        "distinct_city_codes": len(city_counter),
        "distinct_organizations": len(org_counter),
        "items_with_original_url": has_doc_uri,
        "hits_by_prefecture": pref_hits,
        "truncated_queries": truncated,
        "sample_items": sample,
        "fields_seen": sorted({k for s in sample for k in s}),
    }
    (OUT / "kkj_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("sample_items", "hits_by_prefecture")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
