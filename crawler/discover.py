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
import os
import heapq
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urldefrag
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
try:
    import playwright  # noqa: F401
    RENDER_OK = os.environ.get("NO_RENDER") != "1"
except ImportError:
    RENDER_OK = False
from docrules import DOC_EXT, DOC_HINT, DL_URL, looks_like_doc  # noqa: E402,F401

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
# ページの題名が「財政・予算」程度(6点)でも、そのページ内の文書は原本候補にする(例: 古座川町は画像リンクで文字なし)
PAGE_CTX_MIN = 6
NAV_HINT = re.compile(r"(くらし|暮らし|総務課|財政課|企画課|契約課|管財課|役場|課のページ|部署|事業者|ビジネス|産業|行政|市政|町政|村政|区政|県政|財政|組織|分類|カテゴリ|一覧|sitemap|サイトマップ)")
EXTERNAL_BID = re.compile(r"(ppi|nyusatsu|e-?bid|denshi|choutatsu|chotatsu|cals|e-?nyu|keiyaku|efftis)", re.I)
JS_URL = re.compile(r"""["'](/[A-Za-z0-9_\-./%]+?\.(?:html?|php|jsp|aspx?)|https?://[^"'\s<>]+?)["']""")
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


RENDER_MIN_PAGES = 10   # 通常の読み取りでこれ未満しか読めなかったサイトは、ブラウザで描画して読み直す
_open_sites = threading.local()


class Rendered:
    """ブラウザで描画したページを requests の Response と同じように扱うための入れ物"""
    def __init__(self, url, html, status):
        self.url, self.status_code = url, status
        self.text = html
        self.content = html.encode("utf-8")
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.apparent_encoding = "utf-8"


class Site:
    def __init__(self, base, render=False):
        self.render = render
        self._pw = self._browser = self._page = None
        if not hasattr(_open_sites, "items"):
            _open_sites.items = []
        _open_sites.items.append(self)
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

    # ドメインのうち自治体名でない部分(種別・都道府県名・汎用語)。残りが自治体名の部分
    GENERIC = {"www", "city", "town", "vill", "village", "pref", "ku", "lg", "jp", "go", "or", "ne", "co", "ac",
               "ed", "gr", "com", "net", "org", "info", "web", "official", "hp", "www2", "www3",
               "hokkaido", "aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima", "ibaraki", "tochigi",
               "gunma", "saitama", "chiba", "tokyo", "kanagawa", "niigata", "toyama", "ishikawa", "fukui",
               "yamanashi", "nagano", "gifu", "shizuoka", "aichi", "mie", "shiga", "kyoto", "osaka", "hyogo",
               "nara", "wakayama", "tottori", "shimane", "okayama", "hiroshima", "yamaguchi", "tokushima",
               "kagawa", "ehime", "kochi", "fukuoka", "saga", "nagasaki", "kumamoto", "oita", "miyazaki",
               "kagoshima", "okinawa", "metro"}

    @classmethod
    def _name_labels(cls, h):
        return {x for x in cls._bare(h).split(".") if len(x) >= 4 and x not in cls.GENERIC}

    def same_site(self, url):
        h = self._bare(urlparse(url).netloc)
        if any(h == b or h.endswith("." + b) for b in self.hosts):
            return True
        k = self._gov_key(h)
        if k is not None and any(self._gov_key(b) == k for b in self.hosts):
            return True
        # 公式サイトが別ドメインへ移った場合(例: town.shibecha.hokkaido.jp → hokkaido.shibecha.jp)。
        # 自治体名の部分(shibecha)が同じなら同じ自治体のサイトとみなす
        names = self._name_labels(h)
        return bool(names) and any(names & self._name_labels(b) for b in self.hosts)

    def _render(self, url):
        """JavaScriptで中身を作るサイト用: Chromiumで開いて描画後のHTMLを返す"""
        if self._page is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(executable_path=os.environ.get("CHROME_PATH") or None)
            self._page = self._browser.new_page(user_agent=UA, locale="ja-JP")
        delay = WAIT - (time.time() - self.last)
        if delay > 0:
            time.sleep(delay)
        self.last = time.time()
        resp = self._page.goto(url, wait_until="networkidle", timeout=45000)
        ctype = (resp.headers.get("content-type", "") if resp else "") or "text/html"
        status = resp.status if resp else 200
        if "html" not in ctype:
            return Rendered(self._page.url, "", status), ctype
        return Rendered(self._page.url, self._page.content(), status), ctype

    def close(self):
        for x in (self._browser, self._pw):
            try:
                if x is self._pw and x is not None:
                    x.stop()
                elif x is not None:
                    x.close()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._page = None

    def fetch(self, url):
        if not self.allowed(url):
            self.codes["robots"] = self.codes.get("robots", 0) + 1
            return None, "robots"
        if self.render:
            r, ctype = self._render(url)
            self.codes[str(r.status_code)] = self.codes.get(str(r.status_code), 0) + 1
            if "html" not in ctype or r.status_code >= 400:
                return None, ctype
            return r, ctype
        r = self._get(url)
        self.codes[str(r.status_code)] = self.codes.get(str(r.status_code), 0) + 1
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype:
            return None, ctype
        return r, ctype


def safe_join(base, href):
    """壊れたURL(角かっこ入りなど)でも例外にしない urljoin"""
    try:
        return urljoin(base, href)
    except ValueError:
        return None


def _close_sites():
    for site in getattr(_open_sites, "items", []):
        site.close()
    _open_sites.items = []


def crawl_safe(entity):
    """1団体の予期しない失敗で県全体が止まらないようにする。
    数ページしか読めなかったサイト(JavaScriptで中身を作るサイトなど)は、ブラウザで描画して読み直し、多く読めた方を採る"""
    try:
        found, status = crawl(entity)
        if status["pages"] < RENDER_MIN_PAGES and entity.get("official_url") and RENDER_OK:
            try:
                f2, s2 = crawl(entity, render=True)
                if s2["pages"] > status["pages"] or len(f2) > len(found):
                    s2["error"] = (s2["error"] + " 描画で再読").strip()
                    found, status = f2, s2
            except Exception as e:  # noqa: BLE001
                print(f"{entity['code']}: 描画での読み直しに失敗 {type(e).__name__}: {e}"[:200])
            finally:
                _close_sites()
        return found, status
    except Exception as e:  # noqa: BLE001
        status = {"code": entity["code"], "pref": entity["pref"], "name": entity["name"],
                  "official_url": entity["official_url"], "pages": 0,
                  "error": f"crash: {type(e).__name__}: {e}"[:200], **{k: 0 for k in KEYWORDS},
                  "final_url": "", "codes": ""}
        return [], status


def crawl(entity, render=False):
    code, name, base = entity["code"], entity["name"], entity["official_url"]
    found = []        # (kind, url, text, page_url, is_doc, external, strong)
    status = {"code": code, "pref": entity["pref"], "name": name, "official_url": base,
              "pages": 0, "error": "", **{k: 0 for k in KEYWORDS}, "final_url": "", "codes": ""}
    if not base:
        status["error"] = "公式URL不明"
        return found, status
    try:
        site = Site(base, render=render)
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
    # サイトマップ(robots.txt の Sitemap: 行と /sitemap.xml、索引形式は子も)から候補を足す
    def read_sitemaps():
        queue, done = [], set()
        try:
            rr = site._get(site.root + "/robots.txt")
            if rr.status_code == 200:
                queue += re.findall(r"(?im)^\s*sitemap:\s*(\S+)", rr.text)
        except Exception:  # noqa: BLE001
            pass
        queue.append(site.root + "/sitemap.xml")
        while queue and len(done) < 12:
            sm = queue.pop(0)
            if sm in done or not site.allowed(sm):
                continue
            done.add(sm)
            try:
                r = site._get(sm)
            except Exception:  # noqa: BLE001
                continue
            if r.status_code != 200 or "<loc>" not in r.text:
                continue
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
            if "<sitemapindex" in r.text:
                # 予算・入札・補助金に関係しそうな子サイトマップを先に読む
                locs.sort(key=lambda u: -max(score("", u).values(), default=0))
                queue += locs[:30]
                continue
            for loc in locs[:20000]:
                sc = score("", loc)
                if sc:
                    push(loc, max(sc.values()), 1)
    try:
        read_sitemaps()
    except Exception:  # noqa: BLE001
        pass

    # WordPress のサイトは内蔵の検索(/wp-json/wp/v2/search)で「予算」「入札」「補助金」のページを先に足す
    # (例: 根羽村は課のページの中に財政のリンクがあり、リンク文字だけでは辿れない)
    def read_wp_search():
        for q in ("予算", "入札", "補助金"):
            u = f"{site.root}/wp-json/wp/v2/search?per_page=20&search={quote(q)}"
            if not site.allowed(u):
                return
            r = site._get(u)
            if r.status_code != 200 or not r.text.lstrip().startswith("["):
                return
            for it in r.json():
                if isinstance(it, dict) and it.get("url"):
                    push(it["url"], 60, 1)
    try:
        read_wp_search()
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
        if len(doc.xpath(".//a[@href]")) < 15 and depth < 6:
            # メニューをJavaScriptで組み立てるサイト: スクリプト中のURLらしき文字列も候補にする
            for m in set(JS_URL.findall(r.text)):
                link = safe_join(r.url, m)
                if link and site.same_site(link) and not link.lower().split("?")[0].endswith(SKIP_EXT):
                    sc = score("", link)
                    push(link, (max(sc.values()) if sc else 1) - depth * 0.5, depth + 1)
        # <base href> があるページは、相対リンクをそこから解決する(無いと /a/b/a/b/... のような誤ったURLになる)
        base_href = r.url
        b = doc.find(".//base[@href]")
        if b is not None:
            base_href = safe_join(r.url, b.get("href", "").strip()) or r.url
        for a in doc.iterfind(".//a[@href]"):
            href = a.get("href", "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            link = safe_join(base_href, href)
            if not link:
                continue
            text = " ".join(a.text_content().split())[:200]
            low = link.lower().split("?")[0]
            if low.endswith(SKIP_EXT):
                continue
            sc = score(text, link)
            is_doc = looks_like_doc(link, text)
            internal = site.same_site(link)
            # 原本候補として記録: 文書ファイル、またはページ自体が該当種類らしいページ内の文書
            for kind, v in sc.items():
                strong = bool(STRONG[kind].search(text))
                if strong:
                    strong_found[kind] += 1
                ctx = page_sc.get(kind, 0)
                if (is_doc and (v >= 8 or ctx >= PAGE_CTX_MIN)) or strong or \
                        (not internal and kind == "bids" and EXTERNAL_BID.search(link)):
                    found.append((kind, link, text, r.url, is_doc, not internal, strong))
            if is_doc and not sc:
                for kind, v in page_sc.items():
                    if v >= PAGE_CTX_MIN:
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
        for found, st in ex.map(crawl_safe, ents):
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
