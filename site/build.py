"""公開サイト(静的HTML)を data/ から作る。GitHub Pages で配信する。

ページ:
  index.html            検索(自治体名)と都道府県一覧
  p/<県コード>.html      県内の団体一覧と収録状況
  m/<団体コード>.html     団体ページ: 決算の主な数字(原本Excelへのリンク付き)、当初予算・入札結果・補助金の原本リンク
  about.html            出典・注意事項
  data/search.json      検索用の団体一覧

方針: 表示するものは必ず原本(役所が公開したファイルやページ)へのリンクを付ける。原本を示せないものは載せない。
"""
import csv
import html
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
KIND_LABEL = {"budget": "当初予算", "bids": "入札・契約結果", "grants": "補助金・助成金"}
KEY_ITEMS = ["歳入総額", "歳出総額", "実質収支", "財政力指数", "経常収支比率", "実質公債費比率", "将来負担比率",
             "地方税", "地方交付税", "人件費", "扶助費", "公債費", "普通建設事業費", "民生費", "教育費", "土木費"]
LINKS_PER_KIND = 60

CSS = """
:root{--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e6;--accent:#0b57d0;--bg:#fff;--chip:#f3f4f6}
@media (prefers-color-scheme:dark){:root{--fg:#ececf1;--muted:#a1a1aa;--line:#2f2f35;--accent:#8ab4f8;--bg:#141416;--chip:#222227}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;color:var(--fg);background:var(--bg);line-height:1.7}
header,main,footer{max-width:1040px;margin:0 auto;padding:16px 20px}
header{border-bottom:1px solid var(--line)}header a{color:inherit;text-decoration:none;font-weight:700}
h1{font-size:1.6rem;margin:.6em 0 .2em}h2{font-size:1.15rem;margin:1.8em 0 .6em;border-bottom:1px solid var(--line);padding-bottom:.3em}
a{color:var(--accent)}.muted{color:var(--muted);font-size:.9rem}
table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;background:var(--chip);font-size:.8rem;margin-right:4px}
.ok{background:#d9f2e3;color:#14532d}.ng{background:#fde2e1;color:#7f1d1d}
@media (prefers-color-scheme:dark){.ok{background:#173d29;color:#bbf7d0}.ng{background:#4a1d1d;color:#fecaca}}
input[type=search]{width:100%;font-size:1.05rem;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
ul.res{list-style:none;padding:0}ul.res li{padding:4px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px}
footer{border-top:1px solid var(--line);margin-top:40px}
"""


def esc(s):
    return html.escape(str(s or ""))


def page(title, body, depth=0):
    up = "../" * depth
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | 全国自治体 予算・入札・補助金データベース</title>
<link rel="stylesheet" href="{up}style.css"></head><body>
<header><a href="{up}index.html">全国自治体 予算・入札・補助金データベース</a></header>
<main>{body}</main>
<footer class="muted">表示している数字・情報には、すべて役所が公開した原本へのリンクを付けています。正確な内容は必ず原本でご確認ください。
<a href="{up}about.html">出典と注意事項</a></footer></body></html>"""


def read_csv(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_kessan():
    """直近年度の決算表から、団体ごとに主な数字を拾う。{code: [(年度, 項目, 値, 単位, 原本URL)]}"""
    base = ROOT / "data" / "kessan"
    out = defaultdict(list)
    if not base.exists():
        return out, None
    years = sorted([d.name for d in base.iterdir() if d.is_dir() and d.name.isdigit()], reverse=True)
    if not years:
        return out, None
    y = years[0]
    seen = defaultdict(set)
    for f in sorted((base / y).glob("*.csv")):
        rows = read_csv(f)
        if not rows:
            continue
        cols = list(rows[0].keys())
        picks = []
        for item in KEY_ITEMS:
            for c in cols:
                last = c.split("/")[-1]
                if last == item or (c.endswith(item) and len(c) - len(item) <= 4):
                    picks.append((item, c))
                    break
        for r in rows:
            code = r.get("団体コード", "")[:6]
            for item, c in picks:
                v = r.get(c, "")
                if v in ("", "-") or item in seen[code]:
                    continue
                seen[code].add(item)
                unit = "" if any(k in item for k in ("指数", "比率")) else "千円"
                out[code].append((y, item, v, unit, r.get("原本URL", ""), f.stem))
    return out, y


def fmt(v, unit):
    try:
        x = float(v)
    except ValueError:
        return esc(v)
    if unit == "千円":
        return f"{x * 1000 / 1e8:,.1f} 億円" if abs(x) >= 100000 else f"{x:,.0f} 千円"
    return f"{x:g}" + ("%" if "比率" in unit else "")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "m").mkdir(parents=True)
    (OUT / "p").mkdir()
    (OUT / "data").mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")

    master = read_csv(ROOT / "data" / "master.csv")
    status = {}
    for p in (ROOT / "data" / "status").glob("*.csv"):
        for r in read_csv(p):
            status[r["code"]] = r
    links = defaultdict(lambda: defaultdict(list))
    retrieved = {}
    for p in (ROOT / "data" / "links").glob("*.csv"):
        for r in read_csv(p):
            links[r["code"]][r["kind"]].append(r)
            retrieved[r["code"]] = r.get("retrieved", "")
    policy = {}   # 団体コード → 利用ルールの判定(crawler/policy.py)
    for p in (ROOT / "data" / "policy").glob("*.csv"):
        for r in read_csv(p):
            policy[r["code"]] = r
    kessan, kyear = load_kessan()
    cards = defaultdict(list)   # 団体コード → [(年度, PDF, ページ)]
    for r in read_csv(ROOT / "data" / "kessan" / "cards.csv"):
        cards[r["団体コード"]].append((r["年度"], r["PDF"], r["ページ"]))
    for v in cards.values():
        v.sort(reverse=True)
    pref_budget = defaultdict(list)   # 県がまとめた市町村予算資料(県コード2桁 → リンク)
    for code, kinds in links.items():
        for r in kinds.get("pref_muni_budget", []):
            if r.get("strong") == "1":
                pref_budget[code[:2]].append(r)

    by_pref = defaultdict(list)
    for m in master:
        by_pref[m["code"][:2]].append(m)

    # 団体ページ
    for m in master:
        code = m["code"]
        st = status.get(code, {})
        body = [f"<p class=muted>{esc(m['pref'])}</p><h1>{esc(m['name'])}</h1>",
                f"<p>公式サイト: <a href=\"{esc(m['official_url'])}\" rel=noopener>{esc(m['official_url'])}</a></p>"]
        # 決算
        body.append(f"<h2>決算の主な数字{f'（{kyear}年度）' if kyear else ''}</h2>")
        ks = kessan.get(code, [])
        if ks:
            body.append("<table><tr><th>項目</th><th>値</th><th>原本</th></tr>")
            for y, item, v, unit, src, table in ks:
                body.append(f"<tr><td>{esc(item)}</td><td class=num>{fmt(v, unit)}</td>"
                            f"<td><a href=\"{esc(src)}\">総務省 決算状況調（Excel）</a></td></tr>")
            body.append("</table><p class=muted>出典: 総務省「市町村別決算状況調」「都道府県決算状況調」。普通会計。</p>")
        else:
            body.append("<p class=muted>未収録</p>")
        cs = cards.get(code, [])
        if cs:
            body.append("<p>決算カード（総務省・原本PDF）: " + "、".join(
                f"<a href=\"{esc(pdf)}#page={pg}\" rel=noopener>{y}年度（{pg}ページ）</a>" for y, pdf, pg in cs[:5]) + "</p>")
        # 原本リンク(予算・入札・補助金)
        for kind, label in KIND_LABEL.items():
            items = links[code][kind]
            items.sort(key=lambda r: (r["strong"] != "1", r["is_document"] != "1", r["link_text"]))
            mark = '<span class="chip ok">収録</span>' if items else '<span class="chip ng">未収録</span>'
            body.append(f"<h2>{label} {mark}</h2>")
            if items:
                body.append("<table><tr><th>原本</th><th>掲載ページ</th></tr>")
                for r in items[:LINKS_PER_KIND]:
                    t = r["link_text"] or r["url"]
                    ext = " <span class=chip>外部サイト</span>" if r["external"] == "1" else ""
                    doc = " <span class=chip>ファイル</span>" if r["is_document"] == "1" else ""
                    body.append(f"<tr><td><a href=\"{esc(r['url'])}\" rel=noopener>{esc(t)}</a>{doc}{ext}</td>"
                                f"<td><a href=\"{esc(r['found_on'])}\" rel=noopener class=muted>掲載元</a></td></tr>")
                body.append("</table>")
                if len(items) > LINKS_PER_KIND:
                    body.append(f"<p class=muted>ほか {len(items) - LINKS_PER_KIND} 件</p>")
            elif kind == "budget" and pref_budget.get(code[:2]):
                body.append("<p>この団体の公式サイトでは見つかっていません。県がまとめた市町村の予算資料に含まれている場合があります。</p><ul>")
                for r in pref_budget[code[:2]][:10]:
                    body.append(f"<li><a href=\"{esc(r['url'])}\" rel=noopener>{esc(r['link_text'] or r['url'])}</a>"
                                f"（{esc(r['name'])}）</li>")
                body.append("</ul>")
            else:
                body.append(f"<p class=muted>この団体の公式サイトから{label}の原本はまだ見つかっていません。"
                            f"<a href=\"{esc(m['official_url'])}\">公式サイト</a>でご確認ください。</p>")
        # 利用ルール(原本コピーの扱い)
        pol = policy.get(code, {})
        rule = {"free": "自由利用（出典を明記すれば複製・公開できる）。原本のコピーと読み取った文字も公開しています。",
                "partial": "一部のページ・データだけ自由利用。原本はリンクのみ載せています。",
                "consult": "転載・複製には事前の相談などが必要。原本はリンクのみ載せています。"}.get(
            pol.get("reuse"), "利用ルールを確認できていません。原本はリンクのみ載せています。")
        src = f"（<a href=\"{esc(pol['policy_url'])}\" rel=noopener>この団体の利用ルール</a>）" if pol.get("policy_url") else ""
        body.append(f"<h2>原本の扱い</h2><p>{rule}{src}</p>")
        if st:
            body.append(f"<p class=muted>収集日: {esc(retrieved.get(code, ''))} ・ 巡回ページ数: {esc(st.get('pages'))}</p>")
        (OUT / "m" / f"{code}.html").write_text(page(m["name"], "".join(body), 1), encoding="utf-8")

    # 県ページ
    pref_names = {}
    for pc, ms in sorted(by_pref.items()):
        pref_names[pc] = ms[0]["pref"]
        rows = ["<table><tr><th>団体</th>" + "".join(f"<th>{l}</th>" for l in KIND_LABEL.values()) + "<th>決算</th></tr>"]
        for m in ms:
            c = m["code"]
            cells = "".join('<td><span class="chip ok">収録</span></td>' if links[c][k] else '<td><span class="chip ng">未収録</span></td>'
                            for k in KIND_LABEL)
            kc = '<td><span class="chip ok">収録</span></td>' if kessan.get(c) else '<td><span class="chip ng">未収録</span></td>'
            rows.append(f"<tr><td><a href=\"../m/{c}.html\">{esc(m['name'])}</a></td>{cells}{kc}</tr>")
        rows.append("</table>")
        (OUT / "p" / f"{pc}.html").write_text(page(pref_names[pc], f"<h1>{esc(pref_names[pc])}</h1>" + "".join(rows), 1),
                                             encoding="utf-8")

    # 検索データとトップ
    (OUT / "data" / "search.json").write_text(json.dumps(
        [[m["code"], m["pref"], m["name"]] for m in master], ensure_ascii=False), encoding="utf-8")
    total = len(master)
    cov = {k: sum(1 for m in master if links[m["code"]][k]) for k in KIND_LABEL}
    kcov = sum(1 for m in master if kessan.get(m["code"]))
    covtxt = "".join(f"<tr><td>{l}</td><td class=num>{cov[k]:,} / {total:,}</td></tr>" for k, l in KIND_LABEL.items())
    prefs = "".join(f"<a href=\"p/{pc}.html\">{esc(n)}</a>" for pc, n in sorted(pref_names.items()))
    index = f"""<h1>全国の自治体の予算・入札・補助金を、原本付きで</h1>
<p>全国 {total:,} 団体（47都道府県・1,741市区町村）の決算・当初予算・入札/契約結果・補助金を、役所が公開した原本へのリンクと一緒に調べられます。</p>
<input type=search id=q placeholder="自治体名で検索（例: 甲府市）" autocomplete=off><ul class=res id=res></ul>
<h2>都道府県から探す</h2><div class=grid>{prefs}</div>
<h2>収録状況</h2><table><tr><td>決算の主な数字</td><td class=num>{kcov:,} / {total:,}</td></tr>{covtxt}</table>
<script>
let D=[];fetch('data/search.json').then(r=>r.json()).then(j=>D=j);
const q=document.getElementById('q'),res=document.getElementById('res');
q.addEventListener('input',()=>{{const s=q.value.trim();res.innerHTML='';if(!s)return;
D.filter(x=>(x[1]+x[2]).includes(s)).slice(0,30).forEach(x=>{{const li=document.createElement('li');
li.innerHTML='<a href="m/'+x[0]+'.html">'+x[1]+' '+x[2]+'</a>';res.appendChild(li)}})}});
</script>"""
    (OUT / "index.html").write_text(page("トップ", index), encoding="utf-8")
    about = """<h1>出典と注意事項</h1>
<h2>出典</h2><ul>
<li>決算: 総務省「市町村別決算状況調」「都道府県決算状況調」（各ページに原本Excelへのリンクがあります）</li>
<li>当初予算・入札/契約結果・補助金: 各自治体の公式サイト（各リンクが原本です）</li>
<li>自治体の一覧: 総務省の決算状況調の団体コード。公式サイトのURLは Wikidata を参考にしています</li></ul>
<h2>注意事項</h2><ul>
<li>原本の置き場は自動で探しているため、見落としや関係のないリンクが含まれることがあります。</li>
<li>正確な内容は必ず原本でご確認ください。原本が移動・削除されている場合があります。</li>
<li>収集は各サイトの robots.txt に従い、同じサイトへのアクセスには間隔を空けています。</li></ul>"""
    (OUT / "about.html").write_text(page("出典と注意事項", about), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site: {total} 団体, 決算 {kcov}, " + ", ".join(f"{k} {v}" for k, v in cov.items()))


if __name__ == "__main__":
    main()
