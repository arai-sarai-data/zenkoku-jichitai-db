"""各自治体サイトの「著作権・リンク・利用規約」ページを読み、原本のコピーを公開してよいかを判定する。

  reuse : free    … 政府標準利用規約・公共データ利用規約・CC BY など、出典を書けば自由に複製・公開できる
          partial … 一部のページ・データだけ自由利用(全体としては公開しない扱い)
          consult … 転載・複製の前に相談・連絡・許可を求めている、または無断転載を禁じている
          unknown … ルールのページが見つからない、または読み取れない(安全側に倒し、公開しない扱い)
  link  : free    … リンクは自由(連絡不要)
          notice  … リンクの際に連絡・届出を求めている
          unknown … 記載が見つからない

使い方: python crawler/policy.py 01      (都道府県コード2桁)
入力:   data/status/<県>.csv (final_url)。無ければ data/master.csv の公式サイトURL
出力:   data/policy/<県>.csv  code,name,policy_url,reuse,link,evidence

原本のコピー(Release)は reuse=free の団体だけ公開する。リンクと数字は全団体で載せる。
"""
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover import Site, WORKERS, safe_join  # noqa: E402
from htmlutil import parse_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_FETCH = 6   # 1団体あたりに読むルールのページ数の上限

# ルールのページを探すリンク文字・URL
POLICY_TEXT = re.compile(r"著作権|リンク(について|ポリシー|の方針|集)?$|リンクについて|利用規約|利用ルール|サイトポリシー|"
                         r"ウェブサイトポリシー|ホームページ(の|について|ご利用)|サイトの(ご)?利用|ご利用(にあたって|について|上の注意)|"
                         r"このサイトについて|当サイトについて|免責")
POLICY_URL = re.compile(r"(copyright|policy|kiyaku|riyou|terms|link|chosaku|chosakuken|sitepolicy|site_policy|about_site|aboutsite|menseki)",
                        re.I)

FREE = re.compile(r"政府標準利用規約|公共データ利用規約|クリエイティブ・?コモンズ|Creative\s*Commons|CC[\s\-]?BY|"
                  r"(複製|転載|二次利用|公衆送信)[^。]{0,40}(自由に|ご自由に)(利用|ご利用|使用|複製|転載)?|"
                  r"自由に(複製|転載|二次利用)")
CONSULT = re.compile(r"(転載|複製|転用|引用|二次利用|使用|利用|掲載)[^。]{0,50}(事前に|あらかじめ|必ず)[^。]{0,25}(相談|連絡|許可|承諾|承認|申請|問い合わせ|問合せ)|"
                     r"(無断|許可なく|許可無く|承諾なく)[^。]{0,20}(転載|複製|転用|使用|引用|利用|改変)[^。]{0,25}(禁|でき|ご遠慮|お断り)")
LINK_FREE = re.compile(r"リンク[^。]{0,60}(自由|原則フリー|フリー|連絡(は|の)?(必要|不要)|届出(は|の)?(必要|不要)|"
                       r"手続き(等)?(を行う|は|の)?(こと)?なく|許可(は|の)?(必要|不要))")
LINK_NOTICE = re.compile(r"リンク[^。]{0,60}(事前に|あらかじめ)[^。]{0,25}(連絡|届|申請|許可|承諾|お知らせ|メール)")
NEGATED = re.compile(r"(必要|要)(は)?(ありません|ない|ございません)|不要")


def classify(text):
    """ルールのページの本文から reuse / link と根拠の短い抜き書きを返す"""
    reuse, link, ev = "unknown", "unknown", ""
    sentences = re.split(r"(?<=[。\n])", text)
    consult_hit = next((s for s in sentences if CONSULT.search(s) and not NEGATED.search(s)), None)
    free_hit = next((s for s in sentences if FREE.search(s)), None)
    strong_free = free_hit and re.search(r"政府標準利用規約|公共データ利用規約|クリエイティブ・?コモンズ|Creative\s*Commons|CC[\s\-]?BY",
                                          free_hit)
    if free_hit and (strong_free or not consult_hit):
        # 「各ページで表記されたデータは二次利用可」のような一部だけの許可は、全体を自由利用とはみなさない
        partial = re.search(r"各ページ|一部の|表記され|明記されている(データ|もの|コンテンツ)|記載があるもの", free_hit) and \
            not re.search(r"(全て|すべて|全部)のページ|特に記載の(無|な)い限り|特記されていない限り|権利表記の記載がない限り", free_hit)
        reuse, ev = ("partial" if partial else "free"), free_hit
    elif consult_hit:
        reuse, ev = "consult", consult_hit
    if LINK_NOTICE.search(text) and not any(LINK_NOTICE.search(s) and NEGATED.search(s) for s in sentences):
        link = "notice"
    elif LINK_FREE.search(text):
        link = "free"
    ev = re.sub(r"\s+", " ", ev).strip()[:120]
    return reuse, link, ev


def check(row):
    code, name = row["code"], row["name"]
    url = (row.get("final_url") or row.get("official_url") or row.get("url") or "").strip()
    out = {"code": code, "name": name, "policy_url": "", "reuse": "unknown", "link": "unknown", "evidence": ""}
    if not url:
        return out
    try:
        site = Site(url)
        r = site._get(url)
        if r is None or r.status_code != 200:
            return out
        site.adopt(r.url)
        doc = parse_html(r)
        cands = []
        for a in doc.xpath(".//a[@href]"):
            t = (a.text_content() or "").strip()
            href = safe_join(r.url, a.get("href") or "")
            if not href or not site.same_site(href) or href.lower().split("?")[0].endswith((".pdf", ".jpg", ".png", ".zip")):
                continue
            if POLICY_TEXT.search(t) or POLICY_URL.search(href):
                cands.append((0 if re.search(r"著作権|利用規約|利用ルール|ポリシー", t) else 1, href))
        seen, texts = set(), []
        for _, href in sorted(cands):
            if href in seen or len(seen) >= MAX_FETCH or not site.allowed(href):
                continue
            seen.add(href)
            p = site._get(href)
            if p is None or p.status_code != 200 or "html" not in p.headers.get("content-type", "html"):
                continue
            pd = parse_html(p)
            body = pd.text_content()
            texts.append((href, body))
            reuse, link, ev = classify(body)
            if reuse != "unknown" and not out["policy_url"]:
                out.update(policy_url=href, reuse=reuse, evidence=ev)
            if link != "unknown" and out["link"] == "unknown":
                out["link"] = link
                out["policy_url"] = out["policy_url"] or href
            if out["reuse"] != "unknown" and out["link"] != "unknown":
                break
        if not out["policy_url"] and texts:
            out["policy_url"] = texts[0][0]
    except Exception as e:  # noqa: BLE001
        out["evidence"] = f"error: {type(e).__name__}"
    return out


def main():
    pref = sys.argv[1].zfill(2)
    st = ROOT / "data" / "status" / f"{pref}.csv"
    if st.exists():
        rows = list(csv.DictReader(open(st, encoding="utf-8")))
    else:
        rows = [r for r in csv.DictReader(open(ROOT / "data" / "master.csv", encoding="utf-8")) if r["code"][:2] == pref]
    with ThreadPoolExecutor(WORKERS) as ex:
        res = sorted(ex.map(check, rows), key=lambda r: r["code"])
    (ROOT / "data" / "policy").mkdir(parents=True, exist_ok=True)
    with open(ROOT / "data" / "policy" / f"{pref}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "policy_url", "reuse", "link", "evidence"])
        w.writeheader()
        w.writerows(res)
    n = len(res)
    cnt = {k: sum(1 for r in res if r["reuse"] == k) for k in ("free", "partial", "consult", "unknown")}
    print(f"{pref}: {n} 団体  自由利用 {cnt['free']} / 一部 {cnt['partial']} / 要相談 {cnt['consult']} / 不明 {cnt['unknown']}  "
          f"リンク連絡要 {sum(1 for r in res if r['link'] == 'notice')}")


if __name__ == "__main__":
    main()
