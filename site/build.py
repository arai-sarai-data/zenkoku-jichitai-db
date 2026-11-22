"""公開サイト(静的HTML)を data/ から作る。GitHub Pages で配信する。

言語: 日本語(ルート) / English(en/) / 中文(zh/) / 한국어(ko/)
ページ(各言語):
  index.html          検索・注目ランキング・都道府県一覧
  r/<指標>.html        ランキング(全国の市区町村・都道府県)。並べ替え・県で絞り込み・Xで共有
  p/<県コード>.html     県内の団体一覧(主な数字と原本の収録状況)
  m/<団体コード>.html    団体ページ: 主な数字と全国順位、決算カード、当初予算・入札結果・補助金の原本リンク
  about.html          出典・注意事項
  data/search.json    検索用の団体一覧(共通)

方針: 表示するものは必ず原本(役所が公開したファイルやページ)へのリンクを付ける。原本を示せないものは載せない。
      ランキングは公開された数字をそのまま並べるだけで、良し悪しの評価はしない(どの自治体にも同じ扱い)。
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
LINKS_PER_KIND = 60
SITE_NAME = {"ja": "全国自治体 予算・入札・補助金データベース", "en": "Japan Local Government Finance Database",
             "zh": "日本地方政府预算·招标·补助金数据库", "ko": "일본 지자체 예산·입찰·보조금 데이터베이스"}
LANGS = ["ja", "en", "zh", "ko"]
PREFIX = {"ja": "", "en": "en/", "zh": "zh/", "ko": "ko/"}
HTML_LANG = {"ja": "ja", "en": "en", "zh": "zh-Hans", "ko": "ko"}
LANG_NAME = {"ja": "日本語", "en": "English", "zh": "中文", "ko": "한국어"}

T = {
    "ja": dict(
        tagline="全国の自治体のお金の使い方を、役所が公開した原本付きで。",
        lead="全国 {total:,} 団体（47都道府県・1,741市区町村）の決算・当初予算・入札/契約結果・補助金を、原本へのリンクと一緒に調べて比べられます。",
        search="自治体名で検索（例: 甲府市 / Kofu）", by_pref="都道府県から探す", rankings="ランキング", see_all="すべて見る",
        coverage="収録状況", kessan_cov="決算の主な数字", budget="当初予算", bids="入札・契約結果", grants="補助金・助成金",
        found="収録", notfound="未収録", source="原本", page="掲載元", more="ほか {n} 件", rank="全国順位（高い順）",
        of="{n} 団体中", higher="高い順", lower="低い順", municipality="団体", governments="団体", pref="都道府県", value="値",
        all_prefs="すべての都道府県", share="Xで共有", official="公式サイト", main_numbers="主な数字（{y}年度決算）",
        kessan_src="出典: 総務省「市町村別決算状況調」「都道府県決算状況調」（普通会計）。数字をクリックすると原本のExcelを開きます。",
        cards="決算カード（総務省・原本PDF）", year_page="{y}年度（{p}ページ）",
        not_found_link="この団体の公式サイトから{label}の原本はまだ見つかっていません。", check_official="公式サイトでご確認ください。",
        pref_budget="この団体の公式サイトでは見つかっていません。県がまとめた市町村の予算資料に含まれている場合があります。",
        handling="原本の扱い", rule_free="自由利用（出典を明記すれば複製・公開できる）。原本のコピーと読み取った文字も公開しています。",
        rule_partial="一部のページ・データだけ自由利用。原本はリンクのみ載せています。",
        rule_consult="転載・複製には事前の相談などが必要。原本はリンクのみ載せています。",
        rule_unknown="利用ルールを確認できていません。原本はリンクのみ載せています。", rule_link="この団体の利用ルール",
        collected="収集日: {d} ・ 巡回ページ数: {p}", footer="表示している数字・情報には、すべて役所が公開した原本へのリンクを付けています。正確な内容は必ず原本でご確認ください。",
        about="出典と注意事項", top="トップ", municipalities="市区町村", prefectures="都道府県", per_capita="住民1人あたり",
        unit_yen="円", population="人口", nodata="データなし", pos_note="全国の中での位置（左ほど低く、右ほど高い）",
        compare="同じ県の市区町村の平均", home_rank_title="数字で見る全国の自治体", lang_note="",
        share_text="{name}の{metric}は全国{rank}位（{n}団体中）", rank_share="{title}【全国{n}団体】",
        top_by="{metric}が高い自治体", m_count="市区町村 {n}", p_count="都道府県 {n}", link_lang_note="",
    ),
    "en": dict(
        tagline="How Japan's local governments spend money — with links to the original documents.",
        lead="Search and compare settlements, initial budgets, procurement results and subsidies for all {total:,} local governments in Japan (47 prefectures and 1,741 municipalities), each linked to the original documents published by the government.",
        search="Search by name (e.g. Kofu / 甲府市)", by_pref="Browse by prefecture", rankings="Rankings", see_all="See all",
        coverage="Coverage", kessan_cov="Key settlement figures", budget="Initial budget", bids="Procurement / contract results",
        grants="Subsidies and grants", found="Available", notfound="Not found", source="Original", page="Found on",
        more="{n} more", rank="National rank (highest first)", of="of {n}", higher="Highest first", lower="Lowest first", municipality="Government", governments="governments",
        pref="Prefecture", value="Value", all_prefs="All prefectures", share="Share on X", official="Official website",
        main_numbers="Key figures (FY{y} settlement)",
        kessan_src="Source: Ministry of Internal Affairs and Communications, settlement surveys of municipalities and prefectures (ordinary accounts). Click a figure to open the original Excel file.",
        cards="Settlement cards (MIC, original PDF)", year_page="FY{y} (page {p})",
        not_found_link="Original {label} documents have not yet been found on this government's website.",
        check_official="Please check the official website.",
        pref_budget="Not found on this government's website. The prefecture's compilation of municipal budgets may include it.",
        handling="Use of original documents", rule_free="Free to reuse with attribution. Copies of the originals and extracted text are also published.",
        rule_partial="Only some pages or data are free to reuse. Originals are linked only.",
        rule_consult="Reprinting or copying requires prior consultation. Originals are linked only.",
        rule_unknown="Usage rules could not be confirmed. Originals are linked only.", rule_link="This government's usage rules",
        collected="Collected: {d} · pages crawled: {p}",
        footer="Every figure and item on this site links to the original document published by the government. Always check the original for accuracy. Documents linked from this site are in Japanese.",
        about="Sources and notes", top="Home", municipalities="Municipalities", prefectures="Prefectures", per_capita="per resident",
        unit_yen="yen", population="Population", nodata="No data", pos_note="Position among all governments (left = lower, right = higher)",
        compare="Average of municipalities in the prefecture", home_rank_title="Japan's local governments in numbers",
        lang_note="Names of documents and pages are shown in Japanese, as published.",
        share_text="{name}: {metric} ranks No.{rank} of {n} in Japan", rank_share="{title} [{n} governments in Japan]",
        top_by="Highest {metric}", m_count="{n} municipalities", p_count="{n} prefectures",
        link_lang_note="Linked documents are in Japanese.",
    ),
    "zh": dict(
        tagline="日本各地方政府如何花钱——附政府公开的原始文件链接。",
        lead="可查询并比较日本全部 {total:,} 个地方政府（47个都道府县、1,741个市区町村）的决算、当初预算、招标/合同结果和补助金，均附原始文件链接。",
        search="按名称搜索（例：甲府市 / Kofu）", by_pref="按都道府县浏览", rankings="排行榜", see_all="查看全部",
        coverage="收录情况", kessan_cov="决算主要数据", budget="当初预算", bids="招标·合同结果", grants="补助金·资助",
        found="已收录", notfound="未收录", source="原始文件", page="来源页面", more="另有 {n} 项", rank="全国排名（从高到低）",
        of="共 {n} 个", higher="从高到低", lower="从低到高", municipality="地方政府", governments="个地方政府", pref="都道府县", value="数值",
        all_prefs="全部都道府县", share="分享到X", official="官方网站", main_numbers="主要数据（{y}年度决算）",
        kessan_src="来源：日本总务省「市町村别决算状况调查」「都道府县决算状况调查」（普通会计）。点击数字可打开原始Excel。",
        cards="决算卡（总务省·原始PDF）", year_page="{y}年度（第{p}页）",
        not_found_link="尚未在该政府官网找到{label}的原始文件。", check_official="请查看官方网站。",
        pref_budget="未在该政府官网找到。县汇编的市町村预算资料中可能包含。",
        handling="原始文件的处理", rule_free="可自由使用（注明出处即可复制·公开）。同时公开原始文件副本和提取的文字。",
        rule_partial="仅部分页面·数据可自由使用。原始文件仅提供链接。", rule_consult="转载·复制需事先协商。原始文件仅提供链接。",
        rule_unknown="未能确认使用规则。原始文件仅提供链接。", rule_link="该政府的使用规则",
        collected="收集日：{d} · 访问页数：{p}", footer="本站显示的所有数字和信息均附有政府公开的原始文件链接。请务必以原始文件为准。链接的文件为日语。",
        about="出处与注意事项", top="首页", municipalities="市区町村", prefectures="都道府县", per_capita="人均",
        unit_yen="日元", population="人口", nodata="无数据", pos_note="在全国中的位置（越左越低，越右越高）",
        compare="同县市区町村平均", home_rank_title="用数字看日本地方政府", lang_note="文件和页面名称按原文以日语显示。",
        share_text="{name}的{metric}全国排名第{rank}（共{n}个）", rank_share="{title}【全国{n}个】",
        top_by="{metric}较高的地方政府", m_count="市区町村 {n}", p_count="都道府县 {n}", link_lang_note="链接的文件为日语。",
    ),
    "ko": dict(
        tagline="일본 지자체의 예산 사용을, 관공서가 공개한 원본과 함께.",
        lead="일본 전체 {total:,}개 지자체(47개 도도부현·1,741개 시구정촌)의 결산·당초예산·입찰/계약 결과·보조금을 원본 링크와 함께 조회하고 비교할 수 있습니다.",
        search="이름으로 검색 (예: 甲府市 / Kofu)", by_pref="도도부현별로 찾기", rankings="랭킹", see_all="전체 보기",
        coverage="수록 현황", kessan_cov="결산 주요 수치", budget="당초예산", bids="입찰·계약 결과", grants="보조금·조성금",
        found="수록", notfound="미수록", source="원본", page="게재 페이지", more="외 {n}건", rank="전국 순위 (높은 순)",
        of="{n}개 중", higher="높은 순", lower="낮은 순", municipality="지자체", governments="개 지자체", pref="도도부현", value="값",
        all_prefs="모든 도도부현", share="X에 공유", official="공식 사이트", main_numbers="주요 수치 ({y}년도 결산)",
        kessan_src="출처: 일본 총무성 「시정촌별 결산상황조사」「도도부현 결산상황조사」(보통회계). 숫자를 클릭하면 원본 Excel이 열립니다.",
        cards="결산카드 (총무성·원본 PDF)", year_page="{y}년도 ({p}페이지)",
        not_found_link="이 지자체의 공식 사이트에서 {label} 원본을 아직 찾지 못했습니다.", check_official="공식 사이트에서 확인해 주세요.",
        pref_budget="이 지자체의 공식 사이트에서는 찾지 못했습니다. 현이 정리한 시정촌 예산 자료에 포함되어 있을 수 있습니다.",
        handling="원본의 취급", rule_free="자유 이용 가능(출처 표기 시 복제·공개 가능). 원본 사본과 추출한 텍스트도 공개합니다.",
        rule_partial="일부 페이지·데이터만 자유 이용 가능. 원본은 링크만 게재합니다.",
        rule_consult="전재·복제에는 사전 상담 등이 필요. 원본은 링크만 게재합니다.",
        rule_unknown="이용 규칙을 확인하지 못했습니다. 원본은 링크만 게재합니다.", rule_link="이 지자체의 이용 규칙",
        collected="수집일: {d} · 순회 페이지 수: {p}", footer="이 사이트의 모든 수치와 정보에는 관공서가 공개한 원본 링크가 있습니다. 정확한 내용은 반드시 원본에서 확인하세요. 링크된 문서는 일본어입니다.",
        about="출처 및 주의사항", top="홈", municipalities="시구정촌", prefectures="도도부현", per_capita="주민 1인당",
        unit_yen="엔", population="인구", nodata="데이터 없음", pos_note="전국에서의 위치(왼쪽일수록 낮고 오른쪽일수록 높음)",
        compare="같은 현 시구정촌 평균", home_rank_title="숫자로 보는 일본 지자체", lang_note="문서·페이지 이름은 원문대로 일본어로 표시합니다.",
        share_text="{name}의 {metric}은(는) 전국 {rank}위 ({n}개 중)", rank_share="{title} [전국 {n}개]",
        top_by="{metric}이(가) 높은 지자체", m_count="시구정촌 {n}", p_count="도도부현 {n}", link_lang_note="링크된 문서는 일본어입니다.",
    ),
}

# ランキングの指標。kind: ratio(そのまま) / per_capita(千円→住民1人あたり円) / count
METRICS = [
    dict(key="fiscal_power", col=["財政力指数"], kind="ratio", fmt="{:.2f}",
         name={"ja": "財政力指数", "en": "Fiscal strength index", "zh": "财政力指数", "ko": "재정력지수"},
         title={"ja": "財政力指数ランキング（自前の税収でまかなえる度合い）", "en": "Fiscal strength index ranking",
                "zh": "财政力指数排行榜（自有税收的充足程度）", "ko": "재정력지수 랭킹 (자체 세수로 충당하는 정도)"},
         note={"ja": "1を超えると、標準的な行政サービスを自前の税収でまかなえる（地方交付税の交付を受けない）水準です。",
               "en": "Above 1.0 means the government can fund standard services from its own tax revenue (no local allocation tax grant).",
               "zh": "超过1表示可以用自有税收负担标准行政服务（不接受地方交付税）。",
               "ko": "1을 넘으면 표준적인 행정 서비스를 자체 세수로 충당할 수 있는 수준입니다(지방교부세 미교부)."}),
    dict(key="future_burden", col=["健全化判断比率/将来負担比率", "将来負担比率"], kind="ratio", fmt="{:.1f}%",
         name={"ja": "将来負担比率", "en": "Future burden ratio", "zh": "将来负担比率", "ko": "장래부담비율"},
         title={"ja": "将来負担比率ランキング（将来払う借金などの重さ）", "en": "Future burden ratio ranking",
                "zh": "将来负担比率排行榜（未来需偿还债务等的负担）", "ko": "장래부담비율 랭킹 (앞으로 갚을 빚 등의 부담)"},
         note={"ja": "地方債の残高など将来払う負担が、標準的な年間収入の何%にあたるか。早期健全化基準は市町村350%・都道府県400%。負担がない団体は数字が出ないため載せていません。",
               "en": "Future liabilities such as outstanding bonds as a percentage of standard annual revenue. Early-warning threshold: 350% for municipalities, 400% for prefectures. Governments with no net burden have no figure and are not listed.",
               "zh": "地方债余额等未来负担相当于标准年收入的百分比。早期健全化标准：市町村350%、都道府县400%。无负担的团体没有数值，未列入。",
               "ko": "지방채 잔액 등 장래 부담이 표준적인 연간 수입의 몇 %인지. 조기건전화 기준은 시정촌 350%, 도도부현 400%. 부담이 없는 단체는 수치가 없어 게재하지 않았습니다."}),
    dict(key="debt_service", col=["健全化判断比率/実質公債費比率", "実質公債費比率"], kind="ratio", fmt="{:.1f}%",
         name={"ja": "実質公債費比率", "en": "Real debt service ratio", "zh": "实质公债费比率", "ko": "실질공채비비율"},
         title={"ja": "実質公債費比率ランキング（毎年の借金返済の重さ）", "en": "Real debt service ratio ranking",
                "zh": "实质公债费比率排行榜（每年偿还债务的负担）", "ko": "실질공채비비율 랭킹 (매년 빚 상환의 부담)"},
         note={"ja": "毎年の借金返済などが標準的な収入の何%か（3年平均）。18%以上で新たな借金に国などの許可が必要、25%以上で早期健全化の対象です。",
               "en": "Annual debt service as a percentage of standard revenue (3-year average). At 18% or more new borrowing needs approval; 25% triggers early fiscal soundness measures.",
               "zh": "每年偿债等占标准收入的百分比（3年平均）。18%以上新借债需批准，25%以上为早期健全化对象。",
               "ko": "매년 빚 상환 등이 표준 수입의 몇 %인지(3년 평균). 18% 이상이면 신규 차입에 허가가 필요하고 25% 이상이면 조기건전화 대상입니다."}),
    dict(key="rigidity", col=["経常収支比率"], kind="ratio", fmt="{:.1f}%",
         name={"ja": "経常収支比率", "en": "Ordinary balance ratio", "zh": "经常收支比率", "ko": "경상수지비율"},
         title={"ja": "経常収支比率ランキング（自由に使えるお金の少なさ）", "en": "Ordinary balance ratio ranking (fiscal rigidity)",
                "zh": "经常收支比率排行榜（可自由支配资金的多少）", "ko": "경상수지비율 랭킹 (자유롭게 쓸 수 있는 돈의 적음)"},
         note={"ja": "人件費・扶助費・借金返済など毎年必ず出ていくお金が、毎年入る一般財源の何%か。高いほど新しい事業に回せるお金が少ない状態です。",
               "en": "Fixed costs such as personnel, welfare and debt service as a percentage of recurring general revenue. Higher means less money left for new projects.",
               "zh": "人工费、扶助费、偿债等每年固定支出占经常性一般财源的百分比。越高可用于新项目的资金越少。",
               "ko": "인건비·부조비·빚 상환 등 매년 반드시 나가는 돈이 매년 들어오는 일반재원의 몇 %인지. 높을수록 새 사업에 쓸 돈이 적습니다."}),
    dict(key="debt_pc", col=["地方債現在高"], kind="per_capita", fmt="{:,.0f}",
         name={"ja": "住民1人あたりの地方債残高", "en": "Outstanding local bonds per resident", "zh": "人均地方债余额", "ko": "주민 1인당 지방채 잔액"},
         title={"ja": "住民1人あたりの借金（地方債残高）ランキング", "en": "Local bond debt per resident ranking",
                "zh": "人均债务（地方债余额）排行榜", "ko": "주민 1인당 빚(지방채 잔액) 랭킹"},
         note={"ja": "地方債の現在高（普通会計）を住民基本台帳人口で割った値です。", "en": "Outstanding local bonds (ordinary accounts) divided by registered population.",
               "zh": "地方债现有额（普通会计）除以住民基本台账人口。", "ko": "지방채 현재고(보통회계)를 주민기본대장 인구로 나눈 값입니다."}),
    dict(key="savings_pc", col=["積立金現在高"], kind="per_capita", fmt="{:,.0f}",
         name={"ja": "住民1人あたりの貯金（積立金）", "en": "Reserve funds per resident", "zh": "人均储备金（积立金）", "ko": "주민 1인당 저금(적립금)"},
         title={"ja": "住民1人あたりの貯金（積立金残高）ランキング", "en": "Reserve funds per resident ranking",
                "zh": "人均储备金（积立金余额）排行榜", "ko": "주민 1인당 저금(적립금 잔액) 랭킹"},
         note={"ja": "財政調整基金・減債基金・その他特定目的基金の現在高を住民基本台帳人口で割った値です。",
               "en": "Fiscal adjustment, debt reduction and other special-purpose funds divided by registered population.",
               "zh": "财政调整基金、减债基金及其他特定目的基金余额除以住民基本台账人口。",
               "ko": "재정조정기금·감채기금·기타 특정목적기금 현재고를 주민기본대장 인구로 나눈 값입니다."}),
    dict(key="spend_pc", col=["歳出総額", "令和6年度/歳出"], kind="per_capita", fmt="{:,.0f}",
         name={"ja": "住民1人あたりの歳出", "en": "Expenditure per resident", "zh": "人均岁出", "ko": "주민 1인당 세출"},
         title={"ja": "住民1人あたりの歳出（1年間に使ったお金）ランキング", "en": "Annual expenditure per resident ranking",
                "zh": "人均岁出（一年支出）排行榜", "ko": "주민 1인당 세출(1년간 쓴 돈) 랭킹"},
         note={"ja": "1年間の歳出総額（普通会計）を住民基本台帳人口で割った値です。人口が少なく面積が広い団体ほど高くなりやすい傾向があります。",
               "en": "Total annual expenditure (ordinary accounts) divided by registered population. Tends to be higher in sparsely populated, large-area governments.",
               "zh": "全年岁出总额（普通会计）除以住民基本台账人口。人口少、面积大的团体往往较高。",
               "ko": "1년간 세출 총액(보통회계)을 주민기본대장 인구로 나눈 값입니다. 인구가 적고 면적이 넓은 단체일수록 높아지는 경향이 있습니다."}),
]
KIND_KEYS = ["budget", "bids", "grants"]
OLD_KEY_ITEMS = ["歳入総額", "歳出総額", "実質収支", "地方税", "地方交付税", "人件費", "扶助費", "公債費", "普通建設事業費",
                 "民生費", "教育費", "土木費"]

CSS = """
:root{--fg:#17181c;--muted:#61646e;--line:#e4e5ea;--accent:#0b57d0;--accent2:#e8590c;--bg:#fff;--card:#f6f7fb;--chip:#eef0f5;
--good:#0f9d58;--bar:#0b57d0}
@media (prefers-color-scheme:dark){:root{--fg:#ececf1;--muted:#a1a4ad;--line:#2d2f36;--accent:#8ab4f8;--accent2:#ffa94d;--bg:#121316;--card:#1b1d22;--chip:#24262d;--bar:#8ab4f8}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP","Noto Sans SC","Noto Sans KR",sans-serif;color:var(--fg);background:var(--bg);line-height:1.7}
.wrap{max-width:1080px;margin:0 auto;padding:0 18px}
header.top{background:linear-gradient(120deg,#0b57d0,#7b2ff7 60%,#e8590c);color:#fff}
header.top .wrap{display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding-top:12px;padding-bottom:12px}
header.top a{color:#fff;text-decoration:none}.brand{font-weight:800;font-size:1.05rem;flex:1}
.langs a{opacity:.85;margin-left:10px;font-size:.88rem}.langs a.cur{opacity:1;font-weight:700;text-decoration:underline}
.hero{background:linear-gradient(120deg,#0b57d0,#7b2ff7 60%,#e8590c);color:#fff;padding:26px 0 34px}
.hero h1{font-size:clamp(1.5rem,4vw,2.3rem);line-height:1.3;margin:.2em 0}.hero p{opacity:.95;max-width:780px}
main{padding:10px 0 30px}
h1{font-size:1.65rem;margin:.6em 0 .2em;line-height:1.35}h2{font-size:1.2rem;margin:1.8em 0 .6em;padding-left:10px;border-left:5px solid var(--accent2)}
a{color:var(--accent)}.muted{color:var(--muted);font-size:.9rem}
table{border-collapse:collapse;width:100%;font-size:.93rem}th,td{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}
th{font-size:.85rem;color:var(--muted);cursor:pointer;user-select:none;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{display:inline-block;padding:1px 9px;border-radius:99px;background:var(--chip);font-size:.8rem;margin-right:4px}
.ok{background:#d9f2e3;color:#14532d}.ng{background:#fde2e1;color:#7f1d1d}
@media (prefers-color-scheme:dark){.ok{background:#173d29;color:#bbf7d0}.ng{background:#4a1d1d;color:#fecaca}}
input[type=search],select{font-size:1.05rem;padding:11px 13px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--fg)}
input[type=search]{width:100%}.hero input[type=search]{border:0;box-shadow:0 6px 24px rgba(0,0,0,.18)}
ul.res{list-style:none;padding:0;margin:6px 0;background:var(--bg);border-radius:10px}ul.res li{padding:6px 12px;border-bottom:1px solid var(--line)}
ul.res a{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px}.grid a{padding:6px 10px;background:var(--card);border-radius:8px;text-decoration:none}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border-radius:14px;padding:14px 16px}.card h3{margin:0 0 6px;font-size:1rem}
.card ol{margin:0;padding-left:1.4em}.card li{padding:2px 0}.card .v{float:right;font-variant-numeric:tabular-nums;color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.kpi{background:var(--card);border-radius:14px;padding:12px 14px}.kpi .lab{font-size:.85rem;color:var(--muted)}
.kpi .big{font-size:1.55rem;font-weight:800;font-variant-numeric:tabular-nums}.kpi .rk{font-size:.85rem}
.bar{position:relative;height:8px;background:var(--line);border-radius:99px;margin:8px 0 2px}
.bar i{position:absolute;top:-4px;width:4px;height:16px;border-radius:2px;background:var(--accent2)}
.bar b{position:absolute;top:-3px;width:2px;height:14px;background:var(--muted);opacity:.6}
.btn{display:inline-block;padding:7px 14px;border-radius:99px;background:#111;color:#fff !important;text-decoration:none;font-size:.88rem;font-weight:600}
@media (prefers-color-scheme:dark){.btn{background:#f2f2f2;color:#111 !important}}
.stats{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px}.stats div{background:rgba(255,255,255,.14);padding:8px 14px;border-radius:12px}
.stats b{display:block;font-size:1.35rem}
.tools{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0}
tr.hl td{background:rgba(232,89,12,.08)}
table.sortable td:first-child,table.sortable th:first-child{width:7em}
footer{border-top:1px solid var(--line);margin-top:40px;padding:16px 0 30px}
"""

SORT_JS = """
document.querySelectorAll('table.sortable th').forEach((th,i)=>th.addEventListener('click',()=>{
const t=th.closest('table'),b=t.tBodies[0],rows=[...b.rows],asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
rows.sort((a,c)=>{const x=a.cells[i].dataset.v??a.cells[i].innerText,y=c.cells[i].dataset.v??c.cells[i].innerText;
const nx=parseFloat(x),ny=parseFloat(y);const r=(!isNaN(nx)&&!isNaN(ny))?nx-ny:x.localeCompare(y,'ja');return asc?r:-r});
rows.forEach(r=>b.appendChild(r))}));
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def url_ok(u):
    return bool(u) and str(u).startswith(("http://", "https://"))


def num(v):
    if v is None:
        return None
    s = str(v).replace(",", "").replace("△", "-").replace("▲", "-").strip()
    try:
        return float(s)
    except ValueError:
        return None


def read_csv(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


class Ctx:
    """言語ごとの表示の道具"""

    def __init__(self, lang, names_en, pref_en):
        self.lang, self.t, self.names_en, self.pref_en = lang, T[lang], names_en, pref_en

    def name(self, code, ja):
        if self.lang == "ja":
            return ja
        en = self.names_en.get(code)
        return f"{en}（{ja}）" if en and self.lang in ("zh", "ko") else (f"{en} ({ja})" if en else ja)

    def short(self, code, ja):
        return ja if self.lang == "ja" else (self.names_en.get(code) or ja)

    def pref(self, pc, ja):
        return ja if self.lang == "ja" else (self.pref_en.get(pc) or ja)

    def kind(self, k):
        return self.t[k]


def page(ctx, title, body, depth, path, desc=""):
    """depth: 言語のルートからの深さ。path: 言語ルートからの相対パス(言語切替のリンク用)"""
    lang = ctx.lang
    up = "../" * depth
    root_up = up + ("../" if lang != "ja" else "")   # サイトのルート
    langs = "".join(f'<a class="{"cur" if l == lang else ""}" href="{root_up}{PREFIX[l]}{path}" hreflang="{HTML_LANG[l]}">{LANG_NAME[l]}</a>'
                    for l in LANGS)
    alt = "".join(f'<link rel="alternate" hreflang="{HTML_LANG[l]}" href="{root_up}{PREFIX[l]}{path}">' for l in LANGS)
    sn = SITE_NAME[lang]
    d = esc(desc or ctx.t["tagline"])
    return f"""<!doctype html><html lang="{HTML_LANG[lang]}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} | {esc(sn)}</title><meta name="description" content="{d}">
<meta property="og:title" content="{esc(title)} | {esc(sn)}"><meta property="og:description" content="{d}">
<meta property="og:type" content="website"><meta name="twitter:card" content="summary">{alt}
<link rel="stylesheet" href="{root_up}style.css"></head><body>
<header class="top"><div class="wrap"><a class="brand" href="{up}index.html">{esc(sn)}</a><nav class="langs">{langs}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="wrap muted">{esc(ctx.t["footer"])} <a href="{up}about.html">{esc(ctx.t["about"])}</a></footer>
<script>{SORT_JS}</script></body></html>"""


def share_btn(ctx, text):
    t = json.dumps(text, ensure_ascii=False)
    return (f'<a class="btn" href="#" onclick="window.open(\'https://x.com/intent/post?text=\'+encodeURIComponent({esc(t)})'
            f'+\'&url=\'+encodeURIComponent(location.href),\'_blank\',\'noopener\');return false">𝕏 {esc(ctx.t["share"])}</a>')


def load_kessan():
    """直近年度の決算表から {code: {列名: (値, 原本URL)}} と年度を返す"""
    base = ROOT / "data" / "kessan"
    out = defaultdict(dict)
    if not base.exists():
        return out, None
    years = sorted([d.name for d in base.iterdir() if d.is_dir() and d.name.isdigit()], reverse=True)
    if not years:
        return out, None
    y = years[0]
    for f in sorted((base / y).glob("*.csv")):
        for r in read_csv(f):
            code = (r.get("団体コード") or "")[:6]
            if not code:
                continue
            src = r.get("原本URL", "")
            for c, v in r.items():
                if c in ("団体コード", "団体名", "原本URL") or v in ("", "-", None):
                    continue
                last = c.split("/")[-1]
                for key in (c, last):
                    if key not in out[code]:
                        out[code][key] = (v, src)
    return out, y


def compute_metrics(master, kessan):
    """{metric_key: {code: (値, 原本URL)}}。市区町村と都道府県を分けて順位を付ける"""
    pop = {}
    for m in master:
        v = kessan.get(m["code"], {}).get("住民基本台帳登載人口")
        if v and num(v[0]):
            pop[m["code"]] = num(v[0])
    # 都道府県の人口は県内市区町村の合計
    for m in master:
        if m["kind"] == "都道府県":
            s = sum(p for c, p in pop.items() if c[:2] == m["code"][:2] and c != m["code"])
            if s:
                pop[m["code"]] = s
    vals = {}
    for met in METRICS:
        d = {}
        for m in master:
            kd = kessan.get(m["code"], {})
            hit = next((kd[c] for c in met["col"] if c in kd), None)
            if not hit:
                continue
            v = num(hit[0])
            if v is None:
                continue
            if met["kind"] == "per_capita":
                p = pop.get(m["code"])
                if not p:
                    continue
                v = v * 1000 / p
            d[m["code"]] = (v, hit[1])
        vals[met["key"]] = d
    return vals, pop


def ranks(vals, master_kind):
    """{metric: {code: (順位, 母数)}}  市区町村どうし・都道府県どうしで高い順に順位"""
    out = {}
    for k, d in vals.items():
        rk = {}
        for group in ("muni", "pref"):
            codes = [c for c in d if (master_kind[c] == "都道府県") == (group == "pref")]
            codes.sort(key=lambda c: -d[c][0])
            n = len(codes)
            prev, prev_rank = None, 0
            for i, c in enumerate(codes, 1):
                r = prev_rank if d[c][0] == prev else i
                rk[c] = (r, n)
                prev, prev_rank = d[c][0], r
        out[k] = rk
    return out


def fmt_metric(met, v, ctx):
    s = met["fmt"].format(v)
    return s + (" " + ctx.t["unit_yen"] if met["kind"] == "per_capita" else "")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    (OUT / "style.css").write_text(CSS, encoding="utf-8")
    (OUT / "data").mkdir()

    master = read_csv(ROOT / "data" / "master.csv")
    master_kind = {m["code"]: m["kind"] for m in master}
    names_en = {r["code"]: r["name_en"] for r in read_csv(ROOT / "data" / "names_en.csv") if r.get("name_en")}
    pref_en = {c[:2]: n for c, n in names_en.items() if master_kind.get(c) == "都道府県"}
    status, links, retrieved, policy = {}, defaultdict(lambda: defaultdict(list)), {}, {}
    for p in (ROOT / "data" / "status").glob("*.csv"):
        for r in read_csv(p):
            status[r["code"]] = r
    for p in (ROOT / "data" / "links").glob("*.csv"):
        for r in read_csv(p):
            if url_ok(r.get("url")):      # line:// などアプリ専用のリンクは載せない
                links[r["code"]][r["kind"]].append(r)
            retrieved[r["code"]] = r.get("retrieved", "")
    for p in (ROOT / "data" / "policy").glob("*.csv"):
        for r in read_csv(p):
            policy[r["code"]] = r
    kessan, kyear = load_kessan()
    vals, pop = compute_metrics(master, kessan)
    rk = ranks(vals, master_kind)
    cards = defaultdict(list)
    for r in read_csv(ROOT / "data" / "kessan" / "cards.csv"):
        cards[r["団体コード"]].append((r["年度"], r["PDF"], r["ページ"]))
    for v in cards.values():
        v.sort(reverse=True)
    pref_budget = defaultdict(list)
    for code, kinds in links.items():
        for r in kinds.get("pref_muni_budget", []):
            if r.get("strong") == "1":
                pref_budget[code[:2]].append(r)
    by_pref = defaultdict(list)
    for m in master:
        by_pref[m["code"][:2]].append(m)
    pref_name = {pc: ms[0]["pref"] for pc, ms in by_pref.items()}
    # 県内平均(市区町村のみ)
    pref_avg = {}
    for met in METRICS:
        d = vals[met["key"]]
        acc = defaultdict(list)
        for c, (v, _) in d.items():
            if master_kind[c] != "都道府県":
                acc[c[:2]].append(v)
        pref_avg[met["key"]] = {pc: sum(a) / len(a) for pc, a in acc.items() if a}
    # 指標ごとの全国の範囲(位置の棒グラフ用、外れ値に引っ張られないよう 2〜98 パーセンタイル)
    span = {}
    for met in METRICS:
        xs = sorted(v for c, (v, _) in vals[met["key"]].items() if master_kind[c] != "都道府県")
        if xs:
            lo, hi = xs[int(len(xs) * .02)], xs[int(len(xs) * .98) - 1]
            span[met["key"]] = (lo, hi if hi > lo else lo + 1)

    # 検索データ(共通)
    (OUT / "data" / "search.json").write_text(json.dumps(
        [[m["code"], m["pref"], m["name"], names_en.get(m["code"], "")] for m in master], ensure_ascii=False), encoding="utf-8")

    for lang in LANGS:
        ctx = Ctx(lang, names_en, pref_en)
        t = ctx.t
        base = OUT / PREFIX[lang]
        for sub in ("m", "p", "r"):
            (base / sub).mkdir(parents=True, exist_ok=True)

        # ---- 団体ページ
        for m in master:
            code = m["code"]
            st = status.get(code, {})
            pc = code[:2]
            disp = ctx.name(code, m["name"])
            group_n = "pref" if m["kind"] == "都道府県" else "muni"
            body = [f'<p class="muted"><a href="../p/{pc}.html">{esc(ctx.pref(pc, m["pref"]))}</a></p><h1>{esc(disp)}</h1>',
                    f'<p>{esc(t["official"])}: <a href="{esc(m["official_url"])}" rel="noopener">{esc(m["official_url"])}</a></p>']
            if t["lang_note"]:
                body.append(f'<p class="muted">{esc(t["lang_note"])}</p>')
            # 主な数字(全国順位付き)
            kp = []
            share_best = None
            for met in METRICS:
                hit = vals[met["key"]].get(code)
                if not hit:
                    continue
                v, src = hit
                r, n = rk[met["key"]][code]
                bar = ""
                if group_n == "muni" and met["key"] in span:
                    lo, hi = span[met["key"]]
                    pos = max(0, min(100, (v - lo) / (hi - lo) * 100))
                    avg = pref_avg[met["key"]].get(pc)
                    apos = max(0, min(100, (avg - lo) / (hi - lo) * 100)) if avg is not None else None
                    bar = (f'<div class="bar" title="{esc(t["pos_note"])}"><i style="left:calc({pos:.1f}% - 2px)"></i>'
                           + (f'<b style="left:{apos:.1f}%" title="{esc(t["compare"])}"></b>' if apos is not None else "") + "</div>"
                           + (f'<div class="muted">{esc(t["compare"])}: {esc(fmt_metric(met, avg, ctx))}</div>' if avg is not None else ""))
                kp.append(f'<div class="kpi"><div class="lab">{esc(met["name"][lang])}</div>'
                          f'<div class="big"><a href="{esc(src)}" rel="noopener" style="color:inherit;text-decoration:none">{esc(fmt_metric(met, v, ctx))}</a></div>'
                          f'<div class="rk">{esc(t["rank"])}: <a href="../r/{met["key"]}.html#c{code}"><b>{r:,}</b></a> / {n:,}</div>{bar}</div>')
                if share_best is None or r / n < share_best[0]:
                    share_best = (r / n, met, r, n)
            if kp:
                body.append(f'<h2>{esc(t["main_numbers"].format(y=kyear))}</h2><div class="kpis">{"".join(kp)}</div>'
                            f'<p class="muted">{esc(t["kessan_src"])}</p>')
                if share_best:
                    _, met, r, n = share_best
                    body.append("<p>" + share_btn(ctx, t["share_text"].format(name=ctx.short(code, m["name"]), metric=met["name"][lang], rank=r, n=n)) + "</p>")
            cs = cards.get(code, [])
            if cs:
                body.append(f'<p>{esc(t["cards"])}: ' + "、".join(
                    f'<a href="{esc(pdf)}#page={pg}" rel="noopener">{esc(t["year_page"].format(y=y, p=pg))}</a>' for y, pdf, pg in cs[:5]) + "</p>")
            # 原本リンク
            for kind in KIND_KEYS:
                label = t[kind]
                items = sorted(links[code][kind], key=lambda r: (r["strong"] != "1", r["is_document"] != "1", r["link_text"]))
                mark = f'<span class="chip ok">{esc(t["found"])}</span>' if items else f'<span class="chip ng">{esc(t["notfound"])}</span>'
                body.append(f"<h2>{esc(label)} {mark}</h2>")
                if items:
                    if t["link_lang_note"]:
                        body.append(f'<p class="muted">{esc(t["link_lang_note"])}</p>')
                    body.append(f'<table><tr><th>{esc(t["source"])}</th><th>{esc(t["page"])}</th></tr>')
                    for r in items[:LINKS_PER_KIND]:
                        tx = r["link_text"] or r["url"]
                        body.append(f'<tr><td><a href="{esc(r["url"])}" rel="noopener">{esc(tx)}</a></td>'
                                    f'<td><a href="{esc(r["found_on"])}" rel="noopener" class="muted">{esc(t["page"])}</a></td></tr>')
                    body.append("</table>")
                    if len(items) > LINKS_PER_KIND:
                        body.append(f'<p class="muted">{esc(t["more"].format(n=len(items) - LINKS_PER_KIND))}</p>')
                elif kind == "budget" and pref_budget.get(pc):
                    body.append(f"<p>{esc(t['pref_budget'])}</p><ul>")
                    for r in pref_budget[pc][:10]:
                        body.append(f'<li><a href="{esc(r["url"])}" rel="noopener">{esc(r["link_text"] or r["url"])}</a>（{esc(r["name"])}）</li>')
                    body.append("</ul>")
                else:
                    body.append(f'<p class="muted">{esc(t["not_found_link"].format(label=label))} '
                                f'<a href="{esc(m["official_url"])}">{esc(t["check_official"])}</a></p>')
            pol = policy.get(code, {})
            rule = t.get("rule_" + (pol.get("reuse") or "unknown"), t["rule_unknown"])
            src = f' <a href="{esc(pol["policy_url"])}" rel="noopener">{esc(t["rule_link"])}</a>' if pol.get("policy_url") else ""
            body.append(f'<h2>{esc(t["handling"])}</h2><p>{esc(rule)}{src}</p>')
            if st:
                body.append(f'<p class="muted">{esc(t["collected"].format(d=retrieved.get(code, ""), p=st.get("pages", "")))}</p>')
            (base / "m" / f"{code}.html").write_text(page(ctx, disp, "".join(body), 1, f"m/{code}.html"), encoding="utf-8")

        # ---- ランキング
        for met in METRICS:
            d = vals[met["key"]]
            for_title = met["title"][lang]
            secs = []
            for group, label in (("muni", t["municipalities"]), ("pref", t["prefectures"])):
                codes = [c for c in d if (master_kind[c] == "都道府県") == (group == "pref")]
                codes.sort(key=lambda c: rk[met["key"]][c][0])
                rows = []
                for c in codes:
                    v, src = d[c]
                    r, n = rk[met["key"]][c]
                    mm = next(x for x in by_pref[c[:2]] if x["code"] == c)
                    rows.append(f'<tr id="c{c}" data-p="{c[:2]}"><td class="num" data-v="{r}">{r:,}</td>'
                                f'<td><a href="../m/{c}.html">{esc(ctx.short(c, mm["name"]))}</a></td>'
                                f'<td>{esc(ctx.pref(c[:2], mm["pref"]))}</td>'
                                f'<td class="num" data-v="{v}"><a href="{esc(src)}" rel="noopener" style="color:inherit">{esc(fmt_metric(met, v, ctx))}</a></td></tr>')
                if rows:
                    secs.append(f'<h2>{esc(label)}（{len(rows):,}）</h2><table class="sortable" data-g="{group}"><thead><tr>'
                                f'<th>{esc(t["rank"])}</th><th>{esc(t["municipality"])}</th><th>{esc(t["pref"])}</th>'
                                f'<th>{esc(met["name"][lang])}</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
            opts = "".join(f'<option value="{pc}">{esc(ctx.pref(pc, pref_name[pc]))}</option>' for pc in sorted(pref_name))
            nmuni = sum(1 for c in d if master_kind[c] != "都道府県")
            body = (f'<h1>{esc(for_title)}</h1><p>{esc(met["note"][lang])}</p>'
                    f'<p class="muted">{esc(t["kessan_src"])} ({kyear})</p>'
                    f'<div class="tools"><select id="pf"><option value="">{esc(t["all_prefs"])}</option>{opts}</select>'
                    f'{share_btn(ctx, t["rank_share"].format(title=for_title, n=f"{nmuni:,}"))}</div>' + "".join(secs) +
                    """<script>const pf=document.getElementById('pf');pf.addEventListener('change',()=>{document.querySelectorAll('tr[data-p]').forEach(tr=>{tr.style.display=(!pf.value||tr.dataset.p===pf.value)?'':'none'})});
if(location.hash){const r=document.querySelector(location.hash);if(r){r.classList.add('hl');r.scrollIntoView({block:'center'})}}</script>""")
            (base / "r" / f"{met['key']}.html").write_text(page(ctx, for_title, body, 1, f"r/{met['key']}.html", met["note"][lang]), encoding="utf-8")

        # ---- 県ページ
        for pc, ms in sorted(by_pref.items()):
            head = (f'<tr><th>{esc(t["municipality"])}</th><th>{esc(t["population"])}</th>'
                    + "".join(f'<th>{esc(met["name"][lang])}</th>' for met in METRICS[:4])
                    + "".join(f"<th>{esc(t[k])}</th>" for k in KIND_KEYS) + "</tr>")
            rows = []
            for m in ms:
                c = m["code"]
                cells = "".join(
                    (f'<td class="num" data-v="{vals[met["key"]][c][0]}">{esc(met["fmt"].format(vals[met["key"]][c][0]))}</td>'
                     if c in vals[met["key"]] else '<td class="num" data-v="-1e18">—</td>') for met in METRICS[:4])
                chips = "".join(f'<td data-v="{1 if links[c][k] else 0}"><span class="chip {"ok" if links[c][k] else "ng"}">'
                                f'{esc(t["found"] if links[c][k] else t["notfound"])}</span></td>' for k in KIND_KEYS)
                p = pop.get(c)
                rows.append(f'<tr><td><a href="../m/{c}.html">{esc(ctx.short(c, m["name"]))}</a></td>'
                            f'<td class="num" data-v="{p or 0}">{f"{p:,.0f}" if p else "—"}</td>{cells}{chips}</tr>')
            title = ctx.pref(pc, pref_name[pc])
            body = f'<h1>{esc(title)}</h1><table class="sortable"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'
            (base / "p" / f"{pc}.html").write_text(page(ctx, title, body, 1, f"p/{pc}.html"), encoding="utf-8")

        # ---- トップ
        total = len(master)
        cov = {k: sum(1 for m in master if links[m["code"]][k]) for k in KIND_KEYS}
        kcov = sum(1 for m in master if kessan.get(m["code"]))
        rank_cards = []
        for met in METRICS:
            d = vals[met["key"]]
            codes = sorted((c for c in d if master_kind[c] != "都道府県"), key=lambda c: rk[met["key"]][c][0])[:5]
            items = "".join(
                f'<li><a href="m/{c}.html">{esc(ctx.short(c, next(x["name"] for x in by_pref[c[:2]] if x["code"] == c)))}</a>'
                f'<span class="v">{esc(fmt_metric(met, d[c][0], ctx))}</span></li>' for c in codes)
            rank_cards.append(f'<div class="card"><h3><a href="r/{met["key"]}.html">{esc(met["title"][lang])}</a></h3>'
                              f'<ol>{items}</ol><p class="muted" style="margin:.4em 0 0"><a href="r/{met["key"]}.html">{esc(t["see_all"])} →</a></p></div>')
        prefs = "".join(f'<a href="p/{pc}.html">{esc(ctx.pref(pc, n))}</a>' for pc, n in sorted(pref_name.items()))
        covtxt = (f'<tr><td>{esc(t["kessan_cov"])}</td><td class="num">{kcov:,} / {total:,}</td></tr>'
                  + "".join(f'<tr><td>{esc(t[k])}</td><td class="num">{cov[k]:,} / {total:,}</td></tr>' for k in KIND_KEYS))
        hero = (f'<section class="hero"><div class="wrap"><h1>{esc(t["tagline"])}</h1><p>{esc(t["lead"].format(total=total))}</p>'
                f'<input type="search" id="q" placeholder="{esc(t["search"])}" autocomplete="off"><ul class="res" id="res"></ul>'
                f'<div class="stats"><div><b>{total:,}</b>{esc(t["governments"])}</div>'
                + "".join(f'<div><b>{cov[k] / total * 100:.0f}%</b>{esc(t[k])}</div>' for k in KIND_KEYS) + "</div></div></section>")
        index_body = (f'<h2>{esc(t["home_rank_title"])}</h2><div class="cards">{"".join(rank_cards)}</div>'
                      f'<h2>{esc(t["by_pref"])}</h2><div class="grid">{prefs}</div>'
                      f'<h2>{esc(t["coverage"])}</h2><table>{covtxt}</table>'
                      """<script>
let D=[];fetch('""" + ("../" if lang != "ja" else "") + """data/search.json').then(r=>r.json()).then(j=>D=j);
const q=document.getElementById('q'),res=document.getElementById('res'),L='""" + lang + """';
q.addEventListener('input',()=>{const s=q.value.trim().toLowerCase();res.innerHTML='';if(!s)return;
D.filter(x=>(x[1]+x[2]+' '+x[3]).toLowerCase().includes(s)).slice(0,30).forEach(x=>{const li=document.createElement('li');
const a=document.createElement('a');a.href='m/'+x[0]+'.html';a.textContent=(L==='ja'?x[1]+' '+x[2]:(x[3]||x[2])+'（'+x[1]+' '+x[2]+'）');
li.appendChild(a);res.appendChild(li)})});
</script>""")
        idx = page(ctx, t["top"], index_body, 0, "index.html")
        idx = idx.replace('<main class="wrap">', hero + '<main class="wrap">', 1)
        (base / "index.html").write_text(idx, encoding="utf-8")

        # ---- 出典と注意事項
        about = {
            "ja": """<h1>出典と注意事項</h1><h2>出典</h2><ul>
<li>決算: 総務省「市町村別決算状況調」「都道府県決算状況調」（各ページに原本Excelへのリンクがあります）</li>
<li>決算カード: 総務省「決算カード」（PDF。各団体のページから該当ページを開けます）</li>
<li>当初予算・入札/契約結果・補助金: 各自治体の公式サイト（各リンクが原本です）</li>
<li>自治体の一覧と読み: 総務省の決算状況調の団体コード、「全国地方公共団体コード」。公式サイトのURLは Wikidata を参考にしています</li></ul>
<h2>ランキングについて</h2><ul><li>公開された数字をそのまま並べたもので、良し悪しを評価するものではありません。人口や面積、産業などの事情で数字は大きく変わります。</li>
<li>住民1人あたりの数字は、住民基本台帳人口で割って計算しています。都道府県の人口は県内市区町村の合計です。</li></ul>
<h2>注意事項</h2><ul>
<li>原本の置き場は自動で探しているため、見落としや関係のないリンクが含まれることがあります。</li>
<li>正確な内容は必ず原本でご確認ください。原本が移動・削除されている場合があります。</li>
<li>収集は各サイトの robots.txt に従い、同じサイトへのアクセスには間隔を空けています。</li>
<li>原本のコピーは、利用ルールで自由利用とされている自治体の分だけ公開しています。</li></ul>""",
            "en": """<h1>Sources and notes</h1><h2>Sources</h2><ul>
<li>Settlements: Ministry of Internal Affairs and Communications (MIC), settlement surveys of municipalities and prefectures (each page links to the original Excel file)</li>
<li>Settlement cards: MIC settlement cards (PDF; each government's page opens the relevant page)</li>
<li>Initial budgets, procurement results and subsidies: each government's official website (every link points to the original)</li>
<li>List of governments and English names: MIC government codes and their official kana readings, romanized automatically (Hepburn). Official website URLs are based on Wikidata.</li></ul>
<h2>About the rankings</h2><ul><li>Rankings simply order published figures; they are not judgments. Figures vary widely with population, area and local industry.</li>
<li>Per-resident figures use the Basic Resident Register population. Prefecture populations are the sum of their municipalities.</li></ul>
<h2>Notes</h2><ul><li>Documents are located automatically, so some may be missing or unrelated.</li>
<li>Always check the original documents (in Japanese). Originals may have moved or been removed.</li>
<li>Crawling follows each site's robots.txt and spaces out requests.</li>
<li>Copies of originals are published only for governments whose usage rules allow free reuse.</li></ul>""",
            "zh": """<h1>出处与注意事项</h1><h2>出处</h2><ul>
<li>决算：日本总务省「市町村别决算状况调查」「都道府县决算状况调查」（各页附原始Excel链接）</li>
<li>决算卡：总务省「决算卡」（PDF）</li><li>当初预算·招标/合同结果·补助金：各地方政府官网（每个链接均为原始文件）</li>
<li>地方政府名称的英文：根据总务省「全国地方公共团体代码」的假名读音自动转换为罗马字（黑本式）。官网URL参考Wikidata。</li></ul>
<h2>关于排行榜</h2><ul><li>排行榜只是按公开数字排序，并非评价好坏。数字受人口、面积、产业等影响很大。</li>
<li>人均数字以住民基本台账人口计算。都道府县人口为辖内市区町村之和。</li></ul>
<h2>注意事项</h2><ul><li>原始文件为自动查找，可能有遗漏或无关链接。</li><li>请务必以原始文件（日语）为准。</li>
<li>收集遵守各网站robots.txt并间隔访问。</li><li>仅公开使用规则允许自由使用的地方政府的原始文件副本。</li></ul>""",
            "ko": """<h1>출처 및 주의사항</h1><h2>출처</h2><ul>
<li>결산: 일본 총무성 「시정촌별 결산상황조사」「도도부현 결산상황조사」(각 페이지에 원본 Excel 링크)</li>
<li>결산카드: 총무성 「결산카드」(PDF)</li><li>당초예산·입찰/계약 결과·보조금: 각 지자체 공식 사이트(각 링크가 원본)</li>
<li>지자체 이름의 영문 표기: 총무성 「전국지방공공단체코드」의 가나 읽기를 자동으로 로마자(헵번식)로 변환. 공식 사이트 URL은 Wikidata 참고.</li></ul>
<h2>랭킹에 대하여</h2><ul><li>공개된 수치를 그대로 나열한 것으로, 좋고 나쁨을 평가하는 것이 아닙니다. 인구·면적·산업 등에 따라 수치가 크게 달라집니다.</li>
<li>주민 1인당 수치는 주민기본대장 인구로 계산했습니다. 도도부현 인구는 관내 시구정촌의 합계입니다.</li></ul>
<h2>주의사항</h2><ul><li>원본은 자동으로 찾기 때문에 누락이나 관계없는 링크가 있을 수 있습니다.</li><li>정확한 내용은 반드시 원본(일본어)에서 확인하세요.</li>
<li>수집은 각 사이트의 robots.txt를 따르고 접속 간격을 둡니다.</li><li>원본 사본은 이용 규칙상 자유 이용이 허용된 지자체의 것만 공개합니다.</li></ul>""",
        }[lang]
        (base / "about.html").write_text(page(ctx, t["about"], about, 0, "about.html"), encoding="utf-8")

    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site: {len(master)} 団体 × {len(LANGS)} 言語, 決算 {kcov}, 英語名 {len(names_en)}, "
          + ", ".join(f"{m['key']} {len(vals[m['key']])}" for m in METRICS) + ", "
          + ", ".join(f"{k} {v}" for k, v in cov.items()))


if __name__ == "__main__":
    main()
