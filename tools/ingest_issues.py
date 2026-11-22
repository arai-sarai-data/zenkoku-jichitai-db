"""国内ブラウザ巡回の結果(GitHub Issue「browser-crawl <団体コード> <名前>」の本文、gzip+base64)を取り込む。

1. まだ取り込んでいない Issue を読み、復号して browser_results.json にまとめる
2. tools/ingest_browser.py で results ブランチの県ごとの結果に団体単位で差し替える
3. 取り込んだ Issue 番号を data/browser_ingested.txt に記録(重複取り込みを防ぐ)

使い方: python tools/ingest_issues.py <results ブランチのフォルダ>
"""
import base64
import csv
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
prev = Path(sys.argv[1])
done_path = ROOT / "data" / "browser_ingested.txt"
done = set(done_path.read_text().split()) if done_path.exists() else set()
if "--all" in sys.argv:      # 全国収集で上書きされた後などに、全Issueを取り込み直す
    done = set()

issues = json.loads(subprocess.run(
    ["gh", "api", "--paginate", "repos/arai-sarai-data/zenkoku-jichitai-db/issues?state=all&per_page=100"],
    capture_output=True, text=True, check=True).stdout.replace("][", ","))
master = {}
mp = ROOT / "data" / "master.csv"
if mp.exists():
    with open(mp, encoding="utf-8") as f:
        master = {r["code"]: r for r in csv.DictReader(f)}
out, used = {}, []
for it in sorted(issues, key=lambda x: x["number"]):
    if not it["title"].startswith("browser-crawl ") or str(it["number"]) in done:
        continue
    body = (it.get("body") or "").strip()
    if not body.startswith("MFDB-B64:"):
        continue
    try:
        d = json.loads(gzip.decompress(base64.b64decode(body[len("MFDB-B64:"):])))
    except Exception as e:  # noqa: BLE001
        print("skip", it["number"], e)
        continue
    m = master.get(d["code"], {})
    out[d["code"]] = {"name": d["name"], "pref": m.get("pref", ""), "official_url": m.get("official_url", ""),
                      "final_url": d.get("final_url", ""), "pages": d.get("pages", 0), "codes": d.get("codes", {}),
                      "found": d.get("found", [])}
    used.append(str(it["number"]))
if not out:
    print("新しい結果なし")
    sys.exit(0)
tmp = ROOT / "work" / "browser_results.json"
tmp.parent.mkdir(parents=True, exist_ok=True)
tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
subprocess.run([sys.executable, str(ROOT / "tools" / "ingest_browser.py"), str(tmp), str(prev)], check=True)
done_path.parent.mkdir(parents=True, exist_ok=True)
done_path.write_text("\n".join(sorted(done | set(used), key=int)) + "\n")
print("取り込んだ Issue:", used, "団体:", sorted(out))
