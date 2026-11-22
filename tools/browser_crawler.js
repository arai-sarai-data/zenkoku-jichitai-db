// 海外からのアクセスを断る自治体サイトを、日本国内のブラウザ(自治体サイトのページ上)で巡回する。
// crawler/discover.py と同じ判定規則。同一サイト内のみ、1リクエストごとに WAIT ミリ秒空ける。
// 使い方: 自治体のトップページを開いた状態で、このコードを実行 → window.__mfdb に結果が溜まる。
(() => {
  const WAIT = 2000, MAX_PAGES = 300, TIME_BUDGET = 25 * 60 * 1000;
  const KEYWORDS = {
    budget: ["当初予算", "予算書", "予算の概要", "予算概要", "予算案", "予算説明書", "予算に関する説明書", "予算・決算", "予算", "財政状況", "財政"],
    bids: ["入札結果", "落札結果", "契約結果", "入札・契約", "入札契約", "入札及び契約", "入札情報", "落札", "随意契約", "契約情報", "入札"],
    pref_muni_budget: ["市町村当初予算", "市町村の当初予算", "市町村予算", "市町村の予算", "市町村財政", "財政要覧", "市町村の財政"],
    grants: ["補助金", "助成金", "補助制度", "助成制度", "支援制度", "奨励金", "交付金", "給付金", "補助", "助成"],
  };
  const STRONG = {
    budget: /当初予算|(令和|平成)\s*[0-9０-９元]+\s*年度\s*(一般会計)?(補正)?予算|予算(書|の概要|概要|案|説明書|に関する説明書|の状況|について|編成|資料|のあらまし|のポイント)|財政状況(の公表|公表)/,
    bids: /(入札|落札|契約)(結果|状況|情報の公表)|入札・契約/,
    grants: /(補助金|助成金|奨励金|支援制度|補助制度|助成制度)/,
    pref_muni_budget: /市(区)?町村.{0,6}(当初予算|予算(の概要|状況|規模))|財政要覧|市(区)?町村財政(の状況|の概要|状況)/,
  };
  const NAV_HINT = /(くらし|事業者|ビジネス|産業|行政|市政|町政|村政|区政|県政|財政|組織|分類|カテゴリ|一覧|sitemap|サイトマップ)/;
  const EXTERNAL_BID = /(ppi|nyusatsu|e-?bid|denshi|choutatsu|chotatsu|cals|e-?nyu|keiyaku|efftis)/i;
  const SKIP_EXT = /\.(jpe?g|png|gif|mp4|mp3|ics|css|js)$/i;
  const DOC_EXT = /\.(pdf|xlsx|xls|csv|docx|doc|zip)$/i;
  const URLHINT = { budget: /yosan|zaisei/i, bids: /nyusatsu|nyuusatsu|keiyaku|rakusatsu/i, grants: /hojo|josei|shien/i, pref_muni_budget: /shichoson|sityouson|shichouson|zaisei/i };

  function score(text, url) {
    const s = {};
    for (const [kind, words] of Object.entries(KEYWORDS)) {
      let v = 0;
      words.forEach((w, i) => { if (text.includes(w)) v = Math.max(v, 10 - i * 0.5); });
      if (STRONG[kind].test(text)) v += 5;
      if (URLHINT[kind].test(url)) v += 2;
      if (v) s[kind] = v;
    }
    return s;
  }

  const st = window.__mfdb = { done: false, pages: 0, found: [], codes: {}, started: Date.now(), error: "" };
  const origin = location.origin;
  const seen = new Set();
  const heap = [];   // [prio, url, depth]
  const strongFound = Object.fromEntries(Object.keys(KEYWORDS).map(k => [k, 0]));
  const push = (u, prio, depth) => {
    u = u.split("#")[0];
    if (seen.has(u) || !u.startsWith(origin)) return;
    seen.add(u); heap.push([prio, u, depth]);
  };
  const pop = () => { heap.sort((a, b) => b[0] - a[0]); return heap.shift(); };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const decode = async (res) => {
    const buf = await res.arrayBuffer();
    const head = new TextDecoder("latin1").decode(buf.slice(0, 4096));
    let enc = (head.match(/charset\s*=\s*["']?\s*([\w-]+)/i) || [])[1] || ((res.headers.get("content-type") || "").match(/charset=([\w-]+)/i) || [])[1] || "utf-8";
    enc = enc.toLowerCase();
    if (/shift.?jis|sjis|windows-31j/.test(enc)) enc = "shift_jis";
    try { return new TextDecoder(enc).decode(buf); } catch (e) { return new TextDecoder("utf-8").decode(buf); }
  };

  // 巡回結果を圧縮し、GitHub の Issue 作成画面へ(URLの#以降に入れて)移動する。投稿は移動先で mfdb_submit を実行
  window.__mfdbSend = async (code, name, cap = 150) => {
    const per = {};
    const dec = u => { try { return decodeURI(u); } catch (e) { return u; } };
    const rows = st.found.filter(f => f[6] || f[4]).sort((a, b) => b[6] - a[6])
      .filter(f => (per[f[0]] = (per[f[0]] || 0) + 1) <= cap)
      .map(f => [f[0], dec(f[1]), f[2].slice(0, 100), dec(f[3]), f[4], f[5], f[6]]);
    const payload = JSON.stringify({ code, name, final_url: location.origin, pages: st.pages, codes: st.codes, found: rows });
    const gz = await new Response(new Blob([payload]).stream().pipeThrough(new CompressionStream("gzip"))).arrayBuffer();
    let bin = ""; new Uint8Array(gz).forEach(b => bin += String.fromCharCode(b));
    location.href = "https://github.com/arai-sarai-data/zenkoku-jichitai-db/issues/new?title=" +
      encodeURIComponent(`browser-crawl ${code} ${name}`) + "#" + btoa(bin);
    return { rows: rows.length };
  };
  push(location.href, 100, 0);
  push(origin + "/", 99, 0);
  // JavaScriptで画面を組み立てるサイト向け: 表示中のページ(描画後)のリンクも起点にする
  for (const a of document.querySelectorAll("a[href]")) {
    let link; try { link = new URL(a.getAttribute("href"), location.href).href; } catch (e) { continue; }
    if (!link.startsWith(origin) || SKIP_EXT.test(link.toLowerCase().split("?")[0])) continue;
    const text = (a.textContent || "").replace(/\s+/g, " ").trim();
    const sc = score(text, link);
    const v = Math.max(0, ...Object.values(sc)) + (NAV_HINT.test(text) ? 3 : 0);
    push(link, v || 1, 1);
  }
  (async () => {
    try {
      const sm = await fetch(origin + "/sitemap.xml");
      if (sm.ok) {
        const t = await sm.text();
        (t.match(/<loc>\s*([^<\s]+)\s*<\/loc>/g) || []).slice(0, 5000).forEach(m => {
          const u = m.replace(/<\/?loc>/g, "").trim(); const sc = score("", u);
          const v = Math.max(0, ...Object.values(sc)); if (v) push(u, v, 1);
        });
      }
    } catch (e) {}
    while (heap.length && st.pages < MAX_PAGES && Date.now() - st.started < TIME_BUDGET) {
      const [, url, depth] = pop();
      await sleep(WAIT);
      let res;
      try { res = await fetch(url, { redirect: "follow" }); } catch (e) { st.codes.err = (st.codes.err || 0) + 1; continue; }
      st.codes[res.status] = (st.codes[res.status] || 0) + 1;
      if (!(res.headers.get("content-type") || "").includes("html")) continue;
      const html = await decode(res);
      st.pages++;
      const doc = new DOMParser().parseFromString(html, "text/html");
      const base = doc.createElement("base"); base.href = res.url; doc.head.appendChild(base);
      const pageSc = score((doc.title || "").trim(), res.url);
      for (const a of doc.querySelectorAll("a[href]")) {
        const href = a.getAttribute("href").trim();
        if (!href || /^(mailto:|tel:|javascript:)/i.test(href)) continue;
        let link; try { link = new URL(href, res.url).href; } catch (e) { continue; }
        const low = link.toLowerCase().split("?")[0];
        if (SKIP_EXT.test(low)) continue;
        const text = (a.textContent || "").replace(/\s+/g, " ").trim().slice(0, 200);
        const sc = score(text, link);
        const isDoc = DOC_EXT.test(low);
        const internal = link.startsWith(origin);
        for (const [kind, v] of Object.entries(sc)) {
          const strong = STRONG[kind].test(text);
          if (strong) strongFound[kind]++;
          const ctx = pageSc[kind] || 0;
          if ((isDoc && (v >= 8 || ctx >= 8)) || strong || (!internal && kind === "bids" && EXTERNAL_BID.test(link)))
            st.found.push([kind, link, text, res.url, isDoc ? 1 : 0, internal ? 0 : 1, strong ? 1 : 0]);
        }
        if (isDoc && !Object.keys(sc).length)
          for (const [kind, v] of Object.entries(pageSc)) if (v >= 8) st.found.push([kind, link, text, res.url, 1, internal ? 0 : 1, 0]);
        if (internal && !isDoc && depth < 6) {
          let prio = 0;
          for (const [kind, v] of Object.entries(sc)) {
            const have = strongFound[kind]; const w = have === 0 ? 1.5 : (have < 10 ? 1.0 : 0.3);
            prio = Math.max(prio, v * w);
          }
          if (NAV_HINT.test(text)) prio += 3;
          if (prio > 0 || depth < 1) push(link, prio - depth * 0.5, depth + 1);
        }
      }
    }
    // 重複除去
    const uniq = new Map();
    for (const f of st.found) { const k = f[0] + "\t" + f[1]; if (!uniq.has(k) || (f[6] && !uniq.get(k)[6])) uniq.set(k, f); }
    st.found = [...uniq.values()];
    st.done = true;
  })().catch(e => { st.error = String(e); st.done = true; });
  return "started";
})();
