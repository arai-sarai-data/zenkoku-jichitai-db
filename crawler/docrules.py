"""原本ファイル(PDF・Excel等)へのリンクかどうかの判定。外部ライブラリなしで使えるよう独立させている"""
import re

DOC_EXT = (".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".zip")
# 拡張子のないダウンロード用URL(例: /download/?t=LD&id=1&fid=2、/dl?q=xxx.pdf)でも、
# リンク文字が「(PDF：439KB)」のようにファイルを示していれば原本とみなす
DOC_HINT = re.compile(r"(PDF|ＰＤＦ|Excel|エクセル|EXCEL|xlsx?|Word|ワード|docx?|CSV|ZIP)\s*(形式|ファイル)?\s*[:：/／,，\s]*\s*(約|約\s*)?[\d.,，]+\s*(KB|MB|kB|Kb|キロ|ｷﾛ|バイト|B\b)"
                      r"|[（(\[［]\s*(PDF|ＰＤＦ|Excel|エクセル|Word|ワード|CSV|ZIP)\s*[)）\]］:：]", re.I)
DL_URL = re.compile(r"/(download|downloads|dl|file|files|attach|attachment|uploaded|material|getfile|fs)(/|\?|$)|[?&](fid|file_?id|filename|file|q)=", re.I)


DOC_TYPE_PATH = re.compile(r"/(pdf|xlsx?|excel|docx?|word|csv)/[\w\-]+/?$", re.I)


FILE_HANDLER = re.compile(r"/[\w\-]*((?<!pro)file|attach|upload)[\w\-]*(output|download|get|dl|view)[\w\-]*\.(ashx|aspx?|php|cgi|jsp)$|/[\w\-]*(output|download|get)[\w\-]*file[\w\-]*\.(ashx|aspx?|php|cgi|jsp)$", re.I)


def looks_like_doc(link, text=""):
    """文書ファイル(PDF・Excel等)へのリンクらしいか"""
    low = link.lower()
    path, _, query = low.partition("?")
    if path.endswith(DOC_EXT):
        return True
    if query and any(e in query for e in DOC_EXT):
        return True
    # 種類名のフォルダ＋番号のダウンロードURL(例: /Link/Pdf/7920、/file/xlsx/123)
    if DOC_TYPE_PATH.search(path):
        return True
    # ファイル出力用のプログラム(例: /common/UploadFileOutput.ashx?...&flid=7501、/cgi-bin/file_download.php?id=1)
    if FILE_HANDLER.search(path):
        return True
    return bool(DOC_HINT.search(text or "")) and bool(DL_URL.search(low) or query)
