"""段階0: Jグランツ公開APIの収録状況を確認する。

公募中・終了済みを含む全件を取得し、
- 総件数
- 対象地域(target_area_search)ごとの件数
- 制度名に市区町村名が入っている件数(自治体独自制度の目安)
- 詳細APIで公募要領などの原本が取れるか
を調べる。

出力: stage0/out/jgrants_summary.json, stage0/out/jgrants_list.csv
"""
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

BASE = "https://api.jgrants-portal.go.jp/exp/v1/public"
OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)

# キーワード必須のため、ほぼ全制度に含まれる語で網羅を試みる
KEYWORDS = ["補助金", "助成金", "支援", "事業", "交付金", "給付金", "奨励金"]
LOCAL_RE = re.compile(r"[^\s「（(]{1,6}?(都|道|府|県|市|町|村|区)")


def fetch_list(keyword, acceptance):
    params = {"keyword": keyword, "sort": "created_date", "order": "DESC", "acceptance": acceptance}
    r = requests.get(f"{BASE}/subsidies", params=params, timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    rows = {}
    counts = {}
    for kw in KEYWORDS:
        for acc in ("0", "1"):
            try:
                data = fetch_list(kw, acc)
            except Exception as e:  # noqa: BLE001
                counts[f"{kw}/{acc}"] = f"error: {e}"
                continue
            counts[f"{kw}/{acc}"] = data.get("metadata", {}).get("resultset", {}).get("count")
            for it in data.get("result", []):
                rows[it["id"]] = it
            time.sleep(2)

    area = Counter()
    local_title = 0
    for it in rows.values():
        for a in (it.get("target_area_search") or "").split(" / "):
            area[a.strip() or "(空)"] += 1
        if LOCAL_RE.search(it.get("title") or ""):
            local_title += 1

    # 原本(公募要領など)が取れるか、数件だけ詳細を確認
    detail_checks = []
    for it in list(rows.values())[:5]:
        try:
            d = requests.get(f"{BASE}/subsidies/id/{it['id']}", timeout=120).json()
            res = (d.get("result") or [{}])[0]
            detail_checks.append({
                "id": it["id"],
                "title": it.get("title"),
                "front_page_url": res.get("front_subsidy_detail_page_url"),
                "attachments": {
                    k: len(res.get(k) or []) for k in ("application_guidelines", "outline_of_grant", "application_form")
                },
            })
        except Exception as e:  # noqa: BLE001
            detail_checks.append({"id": it["id"], "error": str(e)})
        time.sleep(2)

    with open(OUT / "jgrants_list.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "target_area_search", "institution_name", "acceptance_end_datetime"])
        for it in rows.values():
            w.writerow([it.get("id"), it.get("title"), it.get("target_area_search"),
                        it.get("institution_name"), it.get("acceptance_end_datetime")])

    summary = {
        "counts_by_query": counts,
        "unique_subsidies": len(rows),
        "titles_with_local_name": local_title,
        "institution_name_null": sum(1 for it in rows.values() if not it.get("institution_name")),
        "by_target_area": area.most_common(),
        "detail_checks": detail_checks,
    }
    (OUT / "jgrants_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("counts_by_query", "unique_subsidies", "titles_with_local_name")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
