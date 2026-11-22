"""サイタくん(www.subsidy-support.tech)の補助金オープンデータを取り込み、自前の巡回結果と突き合わせる。

目的:
  1. 自前の巡回で補助金を拾えていない団体を見つける(サイタくんにはあるのに、こちらは0件)
  2. 自前で見つけていない「原本ページ」を洗い出し、巡回の改善に使う
  3. サイタくんは募集終了の制度を消すため、毎日の取り込みで履歴をこちらに残す

出典表示: サイタくん (www.subsidy-support.tech)  ライセンス: CDLA-Permissive-2.0

出力:
  data/saita/latest.csv              当日の全件(主要項目のみ)
  data/saita/history.csv             これまでに一度でも載った制度(初出日・最終確認日つき)
  data/compare/grants_coverage.csv   団体ごとの件数比較と要確認フラグ
  data/compare/grants_missed.csv     サイタくんの原本URLのうち、自前の巡回で見つけていないもの
"""
import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent
ALL_URL = "https://www.subsidy-support.tech/data/subsidies/all"
UA = {"User-Agent": "zenkoku-jichitai-db/0.1 (public-interest open database; attribution: Saita-kun subsidy-support.tech)"}
FIELDS = ["id", "title", "prefectures", "municipality", "gov_level", "support_type", "maximum_amount",
          "subsidy_rate", "application_deadline", "acceptance_start", "institution_name", "detailed_url", "updated_at"]


def load_saita():
    r = requests.get(ALL_URL, headers=UA, timeout=300, allow_redirects=True)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        for key in ("subsidies", "items", "records", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        raise ValueError(f"unexpected JSON keys: {list(data)[:10]}")
    return data


def flat(v):
    if isinstance(v, list):
        return " / ".join(str(x) for x in v)
    return "" if v is None else str(v)


def norm_url(u):
    u = (u or "").strip()
    return u.rstrip("/").replace("http://", "https://")


def main():
    today = time.strftime("%Y-%m-%d")
    recs = load_saita()
    (ROOT / "data" / "saita").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "compare").mkdir(parents=True, exist_ok=True)

    # 1) 当日分
    with open(ROOT / "data" / "saita" / "latest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in recs:
            w.writerow([flat(r.get(k)) for k in FIELDS])

    # 2) 履歴(消えた制度も残す)
    hist_path = ROOT / "data" / "saita" / "history.csv"
    hist = {}
    if hist_path.exists():
        with open(hist_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                hist[row["id"]] = row
    for r in recs:
        rid = str(r.get("id"))
        row = {k: flat(r.get(k)) for k in FIELDS}
        row["first_seen"] = hist.get(rid, {}).get("first_seen", today)
        row["last_seen"] = today
        hist[rid] = row
    with open(hist_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS + ["first_seen", "last_seen"])
        w.writeheader()
        for row in sorted(hist.values(), key=lambda x: (x["first_seen"], x["id"])):
            w.writerow(row)

    # 3) 突き合わせ(自前の巡回結果があるときだけ)
    master_path = ROOT / "data" / "master.csv"
    if not master_path.exists():
        print(f"saita: {len(recs)} records (master.csv がないため突き合わせは省略)")
        return
    with open(master_path, encoding="utf-8") as f:
        master = list(csv.DictReader(f))
    by_name = {}
    for m in master:
        if m["kind"] != "都道府県":
            by_name[(m["pref"], m["name"])] = m["code"]

    def find_code(pref, muni):
        muni = (muni or "").strip()
        if not muni:
            return None
        if muni.startswith(pref):
            muni = muni[len(pref):]
        if (pref, muni) in by_name:
            return by_name[(pref, muni)]
        # 政令市の区など「横浜市中区」→「横浜市」
        for (p, n), c in by_name.items():
            if p == pref and muni.startswith(n):
                return c
        return None

    saita_by_code = defaultdict(list)
    for r in recs:
        if r.get("gov_level") != "municipal":
            continue
        prefs = r.get("prefectures") or []
        pref = prefs[0] if isinstance(prefs, list) and prefs else flat(prefs)
        code = find_code(pref, r.get("municipality"))
        if code:
            saita_by_code[code].append(r)

    ours_count, ours_urls = defaultdict(int), defaultdict(set)
    for p in sorted((ROOT / "data" / "links").glob("*.csv")):
        with open(p, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["kind"] == "grants":
                    ours_count[row["code"]] += 1
                    ours_urls[row["code"]].add(norm_url(row["url"]))
                    ours_urls[row["code"]].add(norm_url(row["found_on"]))

    missed = []
    with open(ROOT / "data" / "compare" / "grants_coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "pref", "name", "ours", "saita", "saita_not_found_by_us", "flag"])
        for m in master:
            if m["kind"] == "都道府県":
                continue
            code = m["code"]
            s = saita_by_code.get(code, [])
            not_found = [r for r in s if norm_url(r.get("detailed_url")) not in ours_urls[code]]
            for r in not_found:
                missed.append([code, m["pref"], m["name"], r.get("title"), r.get("detailed_url"),
                               urlparse(r.get("detailed_url") or "").netloc])
            if ours_count[code] == 0 and s:
                flag = "要確認:自前0件"
            elif ours_count[code] == 0 and not s:
                flag = "両方0件"
            elif not_found:
                flag = "一部見落とし"
            else:
                flag = ""
            w.writerow([code, m["pref"], m["name"], ours_count[code], len(s), len(not_found), flag])
    with open(ROOT / "data" / "compare" / "grants_missed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "pref", "name", "title", "detailed_url", "host"])
        w.writerows(missed)
    zero = sum(1 for m in master if m["kind"] != "都道府県" and ours_count[m["code"]] == 0 and saita_by_code.get(m["code"]))
    print(f"saita: {len(recs)} records, municipal matched {sum(len(v) for v in saita_by_code.values())}, "
          f"自前0件でサイタくんにある団体 {zero}, 見落としURL {len(missed)}, 履歴 {len(hist)}")


if __name__ == "__main__":
    main()
