"""HTMLを正しい文字コードで読む(Shift_JIS・EUC-JPの自治体サイトが多いため)。"""
import re

from lxml import html as lxml_html

_META = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I)
_XMLDECL = re.compile(r"^\s*<\?xml[^>]*\?>", re.I)
ALIASES = {"shift-jis": "cp932", "shift_jis": "cp932", "sjis": "cp932", "x-sjis": "cp932", "windows-31j": "cp932",
           "euc-jp": "euc_jp", "x-euc-jp": "euc_jp", "iso-2022-jp": "iso2022_jp"}


def detect_encoding(content: bytes, header_ct: str = "", apparent: str = "") -> str:
    m = _META.search(content[:4096])
    if m:
        enc = m.group(1).decode("ascii", "ignore").lower()
    else:
        m2 = re.search(r"charset=([\w\-]+)", header_ct or "", re.I)
        enc = (m2.group(1).lower() if m2 else "") or (apparent or "utf-8").lower()
    return ALIASES.get(enc, enc)


def parse_html(resp):
    """requests の Response から lxml の文書を作る(文字化けしないように)"""
    enc = detect_encoding(resp.content, resp.headers.get("Content-Type", ""), resp.apparent_encoding or "")
    try:
        text = resp.content.decode(enc, errors="replace")
    except LookupError:
        text = resp.content.decode("utf-8", errors="replace")
    text = _XMLDECL.sub("", text)
    return lxml_html.fromstring(text, base_url=resp.url)
