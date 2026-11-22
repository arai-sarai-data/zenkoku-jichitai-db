"""各自治体の公式サイトを回り、3種類の原本の置き場を見つける。

  budget  : 当初予算(予算書・予算の概要など)
  bids    : 入札・契約の結果(落札結果)。県の共同「入札情報サービス」など外部サイトへのリンクも記録
  grants  : 自治体独自の補助金・助成金

方法: トップページと sitemap.xml から始め、リンク文字とURLを手がかりに
「それらしいページ」から優先して最大 MAX_PAGES ページを回る(best-first)。
robots.txt に従い、同じサイトへは WAIT 秒以上の間隔を空ける。

使い方: python crawler/discover.py 01      (都道府県コード2桁。その県の県庁+全市区町村)
出力:   data/links/<県コード>.csv   1行=見つけた原本(ページまたはPDF等)
        data/status/<県コード>.csv  1行=1団体の回った結果(種類ごとの件数)
"""
import csv
import heapq
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import requests
from lxml import html as lxml_html  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
from htmlutil import parse_html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = "zenkoku-jichitai-db/0.1 (public-interest open database of local government finance; +https://github.com/)"
WAIT = 2.0          # 同一サイトへのリクエスト間隔(秒)
MAX_PAGES = 300     # 1団体あたり最大ページ数
WORKERS = 16        # 同時に回る団体数(別サイトなので並列化してよい。同一サイトへの間隔は WAIT で守る)
TIMEOUT = 20
TIME_BUDGET = 20 * 60   # 1団体あたりの上限時間(秒)。遅いサイトで全体が止まらないように
DOC_EXT = (".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".zip")

KEYWORDS = {
    "budget": ["当初予算", "予算書", "予算の概要", "予算概要", "予算案", "予算説明書", "予算に関する説明書",
               "予算・決算", "予算", "財政状況", "財政"],
    "bids": ["入札結果", "落札結果", "契約結果", "入札・契約", "入札契約", "入札及び契約", "入札情報",
             "落札", "随意契約", "契約情報", "入札"],
    "pref_muni_budget": ["市町村当初予算", "市町村の当初予算", "市町村予算", "市町村の予算", "市町村財政", "財政要覧",
                         "市町村の財政"],
    "grants": ["補助金", "助成金", "補助制度", "助成制度", "支援制度", "奨励金", "交付金", "給付金", "補助", "助成"],
}
# 単独で強い語(見つけたら「確度高」)
STRONG = {
    "budget": re.compile(r"当初予算|(令和|平成)\s*[0-9０-９元]+\s*年度\s*(一般会計)?(補正)?予算|予算(書|の概要|概要|案|説明書|に関する説明書|の状況|について|編成|資料|のあらまし|のポイント)|財政状況(の公表|公表)"),
    "bids": re.compile(r"(入札|落札|契約)(結果|状況|情報の公表)|入札・契約"),
    "grants": re.compile(r"(補助金|助成金|奨励金|支援制度|補助制度|助成制度)"),
    "pref_muni_budget": re.compile(r"市(区)?町村.{0,6}(当初予算|予算(の概要|状況|規模))|財政要覧|市(区)?町村財政(の状況|の概要|状況)"),
}
NAV_HINT = re.compile(r"(くらし|事業者|ビジネス|産業|行政|市政|町政|村政|区政|県政|財政|組織|分類|カテゴリ|一覧|sitemap|サイトマップ)")
EXTERNAL_BID = re.compile(r"(ppi|nyusatsu|e-?bid|denshi|choutatsu|chotatsu|cals|e-?nyu|keiyaku|efftis)", re.I)
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mp3", ".ics", ".css", ".js")


def score(text: str, url: str):
    """リンク文字とURLから、各種類へのそれらしさを点数化"""
    s = {}
    t = text or ""
    for kind, words in KEYWORDS.items():
        v = 0
        for i, w in enumerate(words):
            if w in t:
                v = max(v, 10 - i * 0.5)
        if STRONG[kind].search(t):
            v += 5
        if kind == "budget" and re.search(r"yosan|zaisei", url, re.I):
            v += 2
        if kind == "bids" and re.search(r"nyusatsu|nyuusatsu|keiyaku|rakusatsu", url, re.I):
            v += 2
        if kind == "grants" and re.search(r"hojo|josei|shien", url, re.I):
            v += 2
        if kind == "pref_muni_budget" and re.search(r"shichoson|sityouson|shichouson|zaisei", url, re.I):
            v += 2
        if v:
            s[kind] = v
    return s


class Site:
    def __init__(self, base):
        self.base = base
        p = urlparse(base)
        self.host = p.netloc.lower()
        self.root = f"{p.scheme}://{p.netloc}"
        self.hosts = {self._bare(self.host)}
        self.codes = {}   # 応答コードの集計   # このサイトとして扱うドメイン(リダイレクト先も追加する)
        self.sess = requests.Session()
        self.sess.headers["User-Agent"] = UA
        self.last = 0.0
        self.robots = RobotFileParser()
        try:
            r = self._get(self.root + "/robots.txt")
            self.robots.parse(r.text.splitlines() if r is not None and r.status_code == 200 else [])
        except Exception:  # noqa: BLE001
            self.robots.parse([])

    @staticmethod
    def _gov_key(h):
        """city.tonami.toyama.jp と city.tonami.lg.jp を同じ自治体とみなすための鍵 (種別, 名前)"""
        labels = Site._bare(h).split(".")
        if len(labels) >= 3 and labels[0] in ("city", "town", "vill", "village", "pref", "ku"):
            return (labels[0], labels[1])
        return None

    @staticmethod
    def _bare(h):
        h = h.lower().split(":")[0]
        return h[4:] if h.startswith("www.") else h

    def adopt(self, url):
        """トップページがリダイレクトした先(例: 旧ドメイン → .lg.jp)も同じサイトとして扱う"""
        p = urlparse(url)
        self.hosts.add(self._bare(p.netloc))
        if self._bare(p.netloc) != self._bare(self.host):
            self.host = p.netloc.lower()
            self.root = f"{p.scheme}://{p.netloc}"

    def _get(self, url, stream=False):
        last_err = None
        for attempt in range(3):   # 接続エラー・タイムアウトは間隔を空けて最大3回
            delay = WAIT * (1 + attempt * 2) - (time.time() - self.last)
            if delay > 0:
                time.sleep(delay)
            self.last = time.time()
            try:
                r = self.sess.get(url, timeout=TIMEOUT, allow_redirects=True, stream=stream)
                if r.status_code in (429, 503) and attempt < 2:
                    time.sleep(10 * (attempt + 1))
                    continue
                return r
            except (requests.ConnectionError, requests.Timeout) as e:
                last_err = e
        raise last_err

    def allowed(self, url):
        try:
            return self.robots.can_fetch(UA, url)
        except Exception:  # noqa: BLE001
            return True

    def same_site(self, url):
        h = self._bare(urlparse(url).netloc)
        if any(h == b or h.endswith("." + b) for b in self.hosts):
            return True
        k = self._gov_key(h)
        return k is not None and any(self._gov_key(b) == k for b in self.hosts)

    def fetch(self, url):
        if not self.allowed(url):
            self.codes["robots"] = self.codes.get("robots", 0) + 1
            return None, "robots"
        r = self._get(url)
        self.codes[str(r.status_code)] = self.codes.get(str(r.status_code), 0) + 1
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype:
            return None, ctype
        return r, ctype


def crawl(entity):
    code, name, base = entity["code"], entity["name"], entity["official_url"]
    found = []        # (kind, url, text, page_url, is_doc, external, strong)
    status = {"code": code, "pref": entity["pref"], "name": name, "official_url": base,
              "pages": 0, "error": "", **{k: 0 for k in KEYWORDS}, "final_url": "", "codes": ""}
    if not base:
        status["error"] = "公式URL不明"
        return found, status
    try:
        site = Site(base)
    except Exception as e:  # noqa: BLE001
        status["error"] = f"init: {e}"
        return found, status
    status["final_url"] = ""

    seen = set()
    heap = []  # (-priority, counter, url, depth)
    counter = 0

    def push(url, prio, depth):
        nonlocal counter
        url = urldefrag(url)[0]
        if url in seen or not url.startswith("http"):
            return
        seen.add(url)
        counter += 1
        heapq.heappush(heap, (-prio, counter, url, depth))

    push(base, 100, 0)
    pb = urlparse(base)
    host = pb.netloc
    alt_host = host[4:] if host.startswith("www.") else "www." + host
    alts = [f"{'http' if pb.scheme == 'https' else 'https'}://{host}/", f"{pb.scheme}://{alt_host}/"]
    gk = Site._gov_key(host)
    if gk and not host.endswith(".lg.jp"):
        alts.append(f"https://www.{gk[0]}.{gk[1]}.lg.jp/")   # 例: city.kazuno.akita.jp → city.kazuno.lg.jp
    for alt in alts:
        push(alt, 99, 0)
    # sitemap.xml があれば候補を足す
    try:
        if site.allowed(site.root + "/sitemap.xml"):
            r = site._get(site.root + "/sitemap.xml")
            if r.status_code == 200 and "<loc>" in r.text:
                for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)[:5000]:
                    sc = score("", loc)
                    if sc:
                        push(loc, max(sc.values()), 1)
    except Exception:  # noqa: BLE001
        pass

    last_error = ""
    started = time.time()
    strong_found = {k: 0 for k in KEYWORDS}
    while heap and status["pages"] < MAX_PAGES:
        if time.time() - started > TIME_BUDGET:
            status["error"] = status["error"] or "時間上限"
            break
        negp, _, url, depth = heapq.heappop(heap)
        try:
            r, ctype = site.fetch(url)
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}"
            site.codes[last_error] = site.codes.get(last_error, 0) + 1
            continue
        if r is None:
            continue
        if status["pages"] == 0:
            site.adopt(r.url)
            # robots.txt も移転先のものを読み直す
            try:
                rr = site._get(site.root + "/robots.txt")
                site.robots = RobotFileParser()
                site.robots.parse(rr.text.splitlines() if rr.status_code == 200 else [])
            except Exception:  # noqa: BLE001
                pass
        status["pages"] += 1
        try:
            doc = parse_html(r)
        except Exception:  # noqa: BLE001
            continue
        title = (doc.findtext(".//title") or "").strip()
        page_sc = score(title, r.url)
        for a in doc.iterfind(".//a[@href]"):
            href = a.get("href", "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            link = urljoin(r.url, href)
            text = " ".join(a.text_content().split())[:200]
            low = link.lower().split("?")[0]
            if low.endswith(SKIP_EXT):
                continue
            sc = score(text, link)
            is_doc = low.endswith(DOC_EXT)
            internal = site.same_site(link)
            # 原本候補として記録: 文書ファイル、またはページ自体が該当種類らしいページ内の文書
            for kind, v in sc.items():
                strong = bool(STRONG[kind].search(text))
                if strong:
                    strong_found[kind] += 1
                ctx = page_sc.get(kind, 0)
                if (is_doc and (v >= 8 or ctx >= 8)) or strong or \
                        (not internal and kind == "bids" and EXTERNAL_BID.search(link)):
                    found.append((kind, link, text, r.url, is_doc, not internal, strong))
            if is_doc and not sc:
                for kind, v in page_sc.items():
                    if v >= 8:
                        found.append((kind, link, text, r.url, True, not internal, False))
            # 次に回るページ(まだ確度の高い原本が少ない種類を優先)
            if internal and not is_doc and depth < 6:
                prio = 0
                for kind, v in sc.items():
                    have = strong_found[kind]
                    weight = 1.5 if have == 0 else (1.0 if have < 10 else 0.3)
                    prio = max(prio, v * weight)
                if NAV_HINT.search(text):
                    prio += 3
                if prio > 0 or depth < 1:
                    push(link, prio - depth * 0.5, depth + 1)

    status["final_url"] = site.root
    status["codes"] = " ".join(f"{k}:{v}" for k, v in sorted(site.codes.items()))
    if status["pages"] == 0:
        status["error"] = last_error or "取得0ページ"
    # 重複を除く
    uniq = {}
    for f in found:
        key = (f[0], f[1])
        if key not in uniq or (f[6] and not uniq[key][6]):
            uniq[key] = f
    found = list(uniq.values())
    for k in KEYWORDS:
        status[k] = sum(1 for f in found if f[0] == k)
    return found, status


def main():
    pref = sys.argv[1].zfill(2)
    with open(ROOT / "data" / "master.csv", encoding="utf-8") as f:
        ents = [r for r in csv.DictReader(f) if r["code"].startswith(pref)]
    import os
    only = {c.strip() for c in os.environ.get("ONLY_CODES", "").split(",") if c.strip()}
    if only:
        ents = [e for e in ents if e["code"] in only]
    (ROOT / "data" / "links").mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "status").mkdir(parents=True, exist_ok=True)
    links_path = ROOT / "data" / "links" / f"{pref}.csv"
    status_path = ROOT / "data" / "status" / f"{pref}.csv"
    results = []
    with ThreadPoolExecutor(WORKERS) as ex:
        for found, st in ex.map(crawl, ents):
            results.append((found, st))
            print(st["code"], st["name"], st["pages"], st["budget"], st["bids"], st["grants"], st["error"], flush=True)
    retrieved = time.strftime("%Y-%m-%d")
    with open(links_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["code", "name", "kind", "url", "link_text", "found_on", "is_document", "external", "strong", "retrieved"])
        for found, st in results:
            for kind, url, text, page, is_doc, ext, strong in sorted(found):
                w.writerow([st["code"], st["name"], kind, url, text, page, int(is_doc), int(ext), int(strong), retrieved])
    with open(status_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0][1].keys()) if results else ["code"])
        w.writeheader()
        for _, st in results:
            w.writerow(st)


if __name__ == "__main__":
    main()
