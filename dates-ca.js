// =============================================================================
// DATES SEMPRE EN dd.mm.aaaa — La TdG · 24.10.2026
// (el mateix fitxer és a latdg/tauler i a latdg/redaccio)
//
// 1. Qualsevol data que surti a la pàgina com 24/10/2026, 24-10-2026,
//    2026-10-24 o 4.9.2026 es mostra com 24.10.2026 (també la que arriba
//    després, de les fonts). No es toquen els camps on s'escriu.
// 2. Els camps de data (input type="date") mostren dd.mm.aaaa en lloc del
//    format del navegador (24/10/2026). S'hi pot escriure la data o triar-la
//    al calendari amb 📅. Per dins continuen donant AAAA-MM-DD.
// =============================================================================
(function () {
  const z = n => String(n).padStart(2, "0");
  const valida = (d, m, a) => d >= 1 && d <= 31 && m >= 1 && m <= 12 && a >= 1900 && a <= 2100;

  function normalitza(text) {
    return text
      // 24/10/2026, 24-10-2026, 4/9/2026, 4.9.2026
      .replace(/(^|[^\d\/.-])(\d{1,2})([\/.-])(\d{1,2})\3((?:19|20)\d\d)(?![\d\/-])/g, (t, ab, d, sep, m, a) =>
        valida(+d, +m, +a) ? ab + z(d) + "." + z(m) + "." + a : t)
      // 2026-10-24, 2026/10/24
      .replace(/(^|[^\d\/.-])((?:19|20)\d\d)([\/-])(\d{1,2})\3(\d{1,2})(?![\d\/-])/g, (t, ab, a, sep, m, d) =>
        valida(+d, +m, +a) ? ab + z(d) + "." + z(m) + "." + a : t);
  }

  const SALTA = /^(SCRIPT|STYLE|TEXTAREA|INPUT|SELECT|OPTION|CODE|NOSCRIPT)$/;
  function recorre(arrel) {
    if (!arrel) return;
    if (arrel.nodeType === 3) { tracta(arrel); return; }
    if (arrel.nodeType !== 1 || SALTA.test(arrel.tagName) || arrel.isContentEditable) return;
    const w = document.createTreeWalker(arrel, NodeFilter.SHOW_TEXT, {
      acceptNode: n => {
        const p = n.parentElement;
        if (!p || SALTA.test(p.tagName) || p.isContentEditable) return NodeFilter.FILTER_REJECT;
        return /\d[\/.-]\d/.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      }
    });
    const nodes = [];
    while (w.nextNode()) nodes.push(w.currentNode);
    nodes.forEach(tracta);
  }
  function tracta(n) {
    const p = n.parentElement;
    if (!p || SALTA.test(p.tagName) || p.isContentEditable) return;
    const nou = normalitza(n.nodeValue);
    if (nou !== n.nodeValue) n.nodeValue = nou;
  }

  // --- Camps de data ---
  const descValor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
  function campData(input) {
    if (input.dataset.dataCa) return;
    input.dataset.dataCa = "1";
    const vis = document.createElement("input");
    vis.type = "text";
    vis.placeholder = "dd.mm.aaaa";
    vis.inputMode = "numeric";
    vis.size = 10;
    vis.className = input.className;
    vis.setAttribute("aria-label", input.getAttribute("aria-label") || "Data (dd.mm.aaaa)");
    const boto = document.createElement("button");
    boto.type = "button";
    boto.textContent = "📅";
    boto.title = "Tria la data al calendari";
    boto.style.cssText = "background:none;border:0;padding:0 4px;cursor:pointer;font-size:1.1em;color:inherit";
    input.style.cssText += ";position:absolute;opacity:0;width:1px;height:1px;padding:0;border:0;pointer-events:none";
    input.tabIndex = -1;
    input.after(vis, boto);

    const pinta = () => { const v = descValor.get.call(input); vis.value = v ? v.split("-").reverse().join(".") : ""; };
    Object.defineProperty(input, "value", {
      configurable: true,
      get() { return descValor.get.call(this); },
      set(v) { descValor.set.call(this, v); pinta(); }
    });
    pinta();
    input.addEventListener("change", pinta);
    input.addEventListener("input", pinta);
    vis.addEventListener("change", () => {
      const t = vis.value.trim();
      let iso = "";
      if (t) {
        const m = t.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2}|\d{4})$/);
        if (!m || !valida(+m[1], +m[2], +(m[3].length === 2 ? "20" + m[3] : m[3]))) { pinta(); vis.focus(); return; }
        iso = (m[3].length === 2 ? "20" + m[3] : m[3]) + "-" + z(m[2]) + "-" + z(m[1]);
      }
      descValor.set.call(input, iso);
      pinta();
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    vis.addEventListener("keydown", e => { if (e.key === "Enter") vis.dispatchEvent(new Event("change")); });
    boto.addEventListener("click", () => { try { input.showPicker(); } catch (e) { input.style.pointerEvents = ""; input.focus(); input.click(); } });
    // disabled / required segueixen el camp original
    new MutationObserver(() => { vis.disabled = boto.disabled = input.disabled; }).observe(input, { attributes: true, attributeFilter: ["disabled"] });
    vis.disabled = boto.disabled = input.disabled;
  }
  function campsData(arrel) {
    if (arrel.nodeType !== 1) return;
    if (arrel.matches && arrel.matches('input[type="date"]')) campData(arrel);
    arrel.querySelectorAll && arrel.querySelectorAll('input[type="date"]').forEach(campData);
  }

  function inicia() {
    recorre(document.body);
    campsData(document.body);
    new MutationObserver(llista => llista.forEach(m => {
      if (m.type === "characterData") { tracta(m.target); return; }
      m.addedNodes.forEach(n => { recorre(n); campsData(n); });
    })).observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", inicia);
  else inicia();
})();
