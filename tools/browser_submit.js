// GitHub の Issue 作成画面(URLの#に圧縮データ)で実行: 本文に入れて「Create」を押す
(async () => {
  const ta = document.querySelector('textarea[aria-label="Markdown value"]');
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  setter.call(ta, "MFDB-B64:" + location.hash.slice(1));
  ta.dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise(r => setTimeout(r, 800));
  [...document.querySelectorAll("button")].find(b => b.textContent.trim().startsWith("Create")).click();
  await new Promise(r => setTimeout(r, 5000));
  return location.href;
})();
