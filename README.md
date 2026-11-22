# zenkoku-jichitai-db

全国の自治体（47都道府県＋1,741市区町村）の決算・予算・入札・補助金を、原本（役所が公開したPDFや公告ページ）付きで比べられる公開データベースを作るリポジトリ。

## stage0（段階0：データ源の確認）

GitHub Actions の `stage0-checks` を実行すると、次の3つを確認して `stage0/out/` に結果を保存する。

| スクリプト | 確認すること |
| --- | --- |
| `check_soumu.py` | 総務省の市町村別決算状況調（Excel）で全国の団体がそろうか、決算カードPDFが1ページ1団体か |
| `check_jgrants.py` | Jグランツの全制度数、対象地域の内訳、自治体独自制度の件数、公募要領が取れるか |
| `check_kkj.py` | 官公需情報ポータルの直近3か月の入札件数と、載っている市区町村の数 |

## collect（全国の原本収集）

GitHub Actions の `collect-originals` を実行すると、全国1,788団体（47都道府県＋1,741市区町村）の公式サイトを回る。

1. `crawler/build_master.py`：総務省の決算Excelから全市区町村の団体コードを取り、Wikidataから公式サイトURLを付ける
2. `crawler/discover.py`：各サイトで当初予算・入札/契約結果・補助金の原本の置き場を探す（robots.txtに従い、同じサイトへは2秒以上空ける）
3. `crawler/fetch_docs.py`：見つけたPDF・Excelを取得して文字を取り出す。文字が取れない画像PDFだけ原本を保存
4. `crawler/ocr.py`：画像PDFをOCR

結果：`data/links/`（原本の置き場）、`data/status/`（団体ごとの収集状況）、`data/docs/`（取得した原本の一覧）。原本コピーと文字データはReleaseに置く。

## saita（補助金の取りこぼし確認）

毎日、サイタくん（www.subsidy-support.tech）の補助金データを取り込み、自前の巡回結果と突き合わせる（`crawler/compare_saita.py`）。
確認用にだけ使い、データ自体は公開リポジトリやサイトには載せない（結果はActionsの成果物として30日保存）。
サイトに載せるのは、各自治体の原本から自前で取得した内容だけ。
