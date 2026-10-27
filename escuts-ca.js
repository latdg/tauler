// =============================================================================
// ESCUTS AL COSTAT DELS MUNICIPIS — La TdG · 27.10.2026
// (el mateix fitxer és a latdg/tauler i a latdg/redaccio, com dates-ca.js)
//
// A cada publicació (notícia, fila, targeta, paràgraf…) que cita la Bisbal
// d'Empordà, Corçà, Forallac o Cruïlles, Monells i Sant Sadurní de l'Heura,
// posa l'escut petit del municipi davant de la primera menció. També al
// contingut que arriba després (les fonts es carreguen a poc a poc).
// No confon la Bisbal d'Empordà amb la Bisbal de Falset ni la del Penedès.
// Els escuts són a la carpeta escuts/ del mateix lloc que aquest fitxer.
// =============================================================================
(function () {
  const BASE = (document.currentScript && document.currentScript.src || "").replace(/[^/]*$/, "") + "escuts/";
  const MUNICIPIS = [
    { codi: "17022", fitxer: "17022.svg", nom: "la Bisbal d'Empordà",
      rx: /\bBISBAL(?!\s+(?:DE\s+FALSET|DEL\s+PENED[EÈ]S))/i },
    { codi: "17057", fitxer: "17057.svg", nom: "Corçà", rx: /\bCOR[ÇC][ÀA](?![\p{L}])/iu },
    { codi: "17902", fitxer: "17902.svg", nom: "Forallac", rx: /\bFORALLAC\b/i },
    { codi: "17901", fitxer: "17901.png", nom: "Cruïlles, Monells i Sant Sadurní de l'Heura", rx: /\bCRU[ÏI]LLES\b/i }
  ];
  const SALTA = /^(SCRIPT|STYLE|TEXTAREA|INPUT|SELECT|OPTION|CODE|NOSCRIPT|TITLE|BUTTON|SVG)$/;
  // On no es posa cap escut: on ja n'hi ha (triadors, fitxes), mapes i capçaleres.
  const NO = ".tria-mun, .leaflet-container, header, nav, .capcalera, [data-sense-escuts]";
  // La «publicació»: l'element més proper que fa d'unitat (una notícia, una fila…).
  const UNITAT = "li, tr, article, details, .targeta, .tg-item, p, h2, h3, h4, figcaption, dd, td, section";

  // Una «línia»: en els textos fets amb <br> (el resum de la redacció), cada
  // notícia és el tros entre dos <br>. Se n'identifica pel primer node.
  const LINIES = new WeakMap();
  function iniciLinia(node) {
    let n = node;
    while (n.previousSibling && n.previousSibling.nodeName !== "BR") n = n.previousSibling;
    return n;
  }
  function unitat(node) {
    const el = node.parentElement;
    if (!el) return null;
    if (el.querySelector(":scope > br")) return { linia: iniciLinia(node) };
    return el.closest(UNITAT) || el;
  }
  function jaTe(u, codi) {
    if (!u) return true;
    if (u.linia) return (LINIES.get(u.linia) || new Set()).has(codi);
    const fets = (u.dataset.escuts || "").split(",");
    if (fets.includes(codi)) return true;
    const sel = `img[src*="escuts/${codi}."]`;
    if (u.querySelector(sel)) return true;
    // Capçaleres que ja duen l'escut al costat (p. ex. les fitxes dels resultats electorals).
    return !!(u.parentElement && u.parentElement.querySelector(`:scope > ${sel}`));
  }
  function marca(u, codi) {
    if (u.linia) { const c = LINIES.get(u.linia) || new Set(); c.add(codi); LINIES.set(u.linia, c); }
    else u.dataset.escuts = ((u.dataset.escuts || "") + "," + codi).replace(/^,/, "");
  }
  function icona(m) {
    const img = document.createElement("img");
    img.src = BASE + m.fitxer;
    img.alt = "";
    img.title = m.nom;
    img.className = "escut-mun";
    img.setAttribute("aria-hidden", "true");
    img.style.cssText = "height:1.05em;width:auto;vertical-align:-0.17em;margin:0 .22em 0 0;display:inline";
    img.onerror = () => img.remove();
    return img;
  }
  // La primera menció del municipi que no formi part d'una adreça web.
  function busca(rx, t) {
    const g = new RegExp(rx.source, rx.flags.includes("g") ? rx.flags : rx.flags + "g");
    let r;
    while ((r = g.exec(t))) {
      const a = t.lastIndexOf(" ", r.index) + 1, b = t.indexOf(" ", r.index);
      const paraula = t.slice(a, b === -1 ? t.length : b);
      if (!/:\/\/|www\.|\.(cat|com|es|org|net)\b|[\/_-]$/i.test(paraula) && !/[\/_-]/.test(t[r.index - 1] || "")) return r;
    }
    return null;
  }
  function tracta(text) {
    const p = text.parentElement;
    if (!p || SALTA.test(p.tagName) || p.isContentEditable || p.closest(NO) || p.closest("a[href]") && /^https?:/.test(p.closest("a[href]").textContent.trim())) return;
    const u = unitat(text);
    for (const m of MUNICIPIS) {
      if (jaTe(u, m.codi)) continue;
      const r = busca(m.rx, text.nodeValue);
      if (!r) continue;
      // Si va precedit de «la », l'escut va davant de l'article.
      let ini = r.index;
      const art = text.nodeValue.slice(0, ini).match(/\b(la|La|LA)\s+$/);
      if (m.codi === "17022" && art) ini -= art[0].length;
      const resta = text.splitText(ini);
      p.insertBefore(icona(m), resta);
      marca(u, m.codi);
      tracta(resta);           // pot citar-ne un altre més endavant
      return;
    }
  }
  const RX_RAPID = /bisbal|cor[çc][àa]|forallac|cru[ïi]lles/i;
  function recorre(arrel) {
    if (!arrel) return;
    if (arrel.nodeType === 3) { if (RX_RAPID.test(arrel.nodeValue)) tracta(arrel); return; }
    if (arrel.nodeType !== 1 || SALTA.test(arrel.tagName)) return;
    const w = document.createTreeWalker(arrel, NodeFilter.SHOW_TEXT, {
      acceptNode: n => RX_RAPID.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
    });
    const nodes = [];
    while (w.nextNode()) nodes.push(w.currentNode);
    nodes.forEach(tracta);
  }

  let pendent = new Set(), programat = false;
  const obs = new MutationObserver(muts => {
    muts.forEach(m => m.addedNodes.forEach(n => pendent.add(n)));
    if (!programat) {
      programat = true;
      requestAnimationFrame(() => {
        programat = false;
        obs.disconnect();
        const ara = pendent; pendent = new Set();
        ara.forEach(n => { if (n.isConnected) recorre(n); });
        obs.observe(document.body, { childList: true, subtree: true });
      });
    }
  });
  function inicia() {
    recorre(document.body);
    obs.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", inicia); else inicia();
})();
