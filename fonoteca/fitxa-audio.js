/* =============================================================================
   LA TdG — FITXA D'ÀUDIO COMPARTIDA (07.11.2026)
   -----------------------------------------------------------------------------
   Una sola fitxa per a cada àudio (títol de l'acte, qui parla, data, tipus,
   municipi, lloc i descripció), desada a dades/fonoteca.json de latdg/tauler
   a través del Worker latdg-agenda (amb la clau dels llamps).

   La fan servir tres pàgines, i totes tres llegeixen i desen la mateixa fitxa:
     · el publicador (latdg.github.io/redaccio/publicador/): en afegir un àudio;
     · la pàgina de l'àudio publicat (latdg.github.io/audio/);
     · La TdG fonoteca (latdg.github.io/tauler/fonoteca/), que té el seu editor.

   Clau de cada fitxa: el nom del fitxer comprimit (el mateix que fan servir el
   publicador d'Apps Script, la branca «fitxers» de latdg/media i l'inventari
   de la fonoteca): 20261103 Èric Vigo.mp3 → 20261103_Eric_Vigo.mp3.
   ============================================================================= */
(function () {
  "use strict";

  const WORKER = "https://latdg-agenda.ignasicorney.workers.dev";
  const CATALEG = "https://raw.githubusercontent.com/latdg/tauler/main/dades/fonoteca.json";
  const INVENTARI = "https://latdg.github.io/media/f/inventari.json";
  const FONOTECA_AUDIOS = "https://latdg.github.io/media/f/";
  const COMPRIMITS = "https://latdg.github.io/media/a/";

  const CATEGORIES = [
    ["declaracions", "🗣️", "Declaracions"],
    ["entrevistes", "🎤", "Entrevistes"],
    ["debats", "🏛️", "Plens i debats"],
    ["conferencies", "🎓", "Conferències i xerrades"],
    ["actes", "🎉", "Actes i celebracions"],
    ["musica", "🎶", "Música"],
    ["altres", "📁", "Altres"]
  ];
  const MUNICIPIS = ["La Bisbal d'Empordà", "Corçà", "Forallac", "Cruïlles, Monells i Sant Sadurní de l'Heura",
    "Ullastret", "Consell Comarcal del Baix Empordà", "Girona"];

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const dataCa = iso => iso ? String(iso).split("-").reverse().join(".") : "";

  /* ----- El mateix nom que nomComprimit_() del publicador d'Apps Script ----- */
  function nomComprimit(fitxer) {
    const base = String(fitxer || "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
    const net = base.normalize("NFD").replace(/[̀-ͯ]/g, "")
      .replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._-]+/, "") || "media";
    return net + ".mp3";
  }
  const EXT_AUDIO = /\.(mp3|wav|ogg|oga|m4a|aac|flac|opus|wma|amr)$/i;
  const esAudio = nom => EXT_AUDIO.test(String(nom || "").trim());

  /* 20261103evigo.mp3 → 2026-11-03 */
  function dataDelNom(nom) {
    let m = String(nom || "").match(/(20\d\d)[-_.]?([01]\d)[-_.]?([0-3]\d)/);
    if (m && +m[2] >= 1 && +m[2] <= 12 && +m[3] >= 1 && +m[3] <= 31) return `${m[1]}-${m[2]}-${m[3]}`;
    m = String(nom || "").match(/([0-3]\d)[-_.]([01]\d)[-_.](20\d\d)/);
    if (m && +m[2] >= 1 && +m[2] <= 12) return `${m[3]}-${m[2]}-${m[1]}`;
    return "";
  }

  /* ----- Format de la descripció: **negreta**, *cursiva*, __subratllat__ ----- */
  function trossosMarca(t) {
    const surt = [], estil = { b: false, i: false, u: false };
    let buf = "";
    const tanca = () => { if (buf) surt.push({ t: buf, ...estil }); buf = ""; };
    for (let k = 0; k < t.length; k++) {
      if (t.startsWith("**", k)) { tanca(); estil.b = !estil.b; k++; continue; }
      if (t.startsWith("__", k)) { tanca(); estil.u = !estil.u; k++; continue; }
      if (t[k] === "*") { tanca(); estil.i = !estil.i; continue; }
      buf += t[k];
    }
    tanca();
    return surt;
  }
  function marcaAHtml(text) {
    return String(text || "").replace(/\r\n/g, "\n").split(/\n\s*\n/).map(x => x.trim()).filter(Boolean)
      .map(par => "<p>" + trossosMarca(par).map(x => {
        let h = esc(x.t).replace(/\n/g, "<br>");
        if (x.u) h = "<u>" + h + "</u>";
        if (x.i) h = "<i>" + h + "</i>";
        if (x.b) h = "<b>" + h + "</b>";
        return h;
      }).join("") + "</p>").join("");
  }
  function htmlAMarca(el) {
    const paragrafs = [];
    let trossos = [];
    const tancaPar = () => {
      let t = "";
      trossos.forEach(x => {
        if (x.t === "\n") { t += "\n"; return; }
        const m = x.t.match(/^(\s*)([\s\S]*?)(\s*)$/);
        if (!m[2]) { t += x.t; return; }
        t += m[1] + (x.b ? "**" : "") + (x.i ? "*" : "") + (x.u ? "__" : "") + m[2] +
          (x.u ? "__" : "") + (x.i ? "*" : "") + (x.b ? "**" : "") + m[3];
      });
      t = t.replace(/\*\*\*\*/g, "").replace(/____/g, "").replace(/ /g, " ").replace(/[ \t]+/g, " ").replace(/ *\n */g, "\n").trim();
      if (t) paragrafs.push(t);
      trossos = [];
    };
    const camina = (node, est) => {
      if (node.nodeType === 3) { if (node.nodeValue) trossos.push({ t: node.nodeValue, ...est }); return; }
      if (node.nodeType !== 1) return;
      const tag = node.tagName, st = node.style || {};
      if (tag === "BR") { trossos.push({ t: "\n" }); return; }
      const e = { ...est };
      if (tag === "B" || tag === "STRONG" || /^(bold|[6-9]00)$/.test(st.fontWeight || "")) e.b = true;
      if (tag === "I" || tag === "EM" || st.fontStyle === "italic") e.i = true;
      if (tag === "U" || /underline/.test((st.textDecoration || "") + (st.textDecorationLine || ""))) e.u = true;
      const bloc = /^(P|DIV|LI|H\d)$/.test(tag);
      if (bloc) tancaPar();
      node.childNodes.forEach(c => camina(c, e));
      if (bloc) tancaPar();
    };
    el.childNodes.forEach(c => camina(c, { b: false, i: false, u: false }));
    tancaPar();
    return paragrafs.join("\n\n");
  }

  /* ----- Estils de l'editor (una sola vegada per pàgina) ----- */
  function posaEstils() {
    if (document.getElementById("fitxaAudioEstils")) return;
    const st = document.createElement("style");
    st.id = "fitxaAudioEstils";
    st.textContent = `
.fa-camps{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin:10px 0}
.fa-camps label,.fa-camps .fa-desc{display:flex;flex-direction:column;gap:4px;font-size:.85rem;color:#6b6b66}
.fa-camps .ample{grid-column:1 / -1}
.fa-camps input,.fa-camps select{font:inherit;font-size:1rem;color:#1d1d1b;padding:7px 9px;border:1px solid #e3e1db;border-radius:8px;background:#fff;min-width:0;width:100%;box-sizing:border-box}
.fa-barra{display:flex;gap:4px;flex-wrap:wrap}
.fa-barra button{font:inherit;font-size:.9rem;background:#fff;color:#1d1d1b;border:1px solid #e3e1db;border-radius:6px;padding:3px 10px;min-width:34px;cursor:pointer}
.fa-barra button.on{background:#f6e6e1;border-color:#b4462c;color:#b4462c}
.fa-text{min-height:110px;padding:10px 12px;border:1px solid #e3e1db;border-radius:8px;background:#fff;color:#1d1d1b;font-size:1rem;line-height:1.55;outline:none;overflow-wrap:anywhere;overflow:auto}
.fa-text:focus{border-color:#1d1d1b}
.fa-text p{margin:0 0 .9em}
.fa-text:empty::before{content:attr(data-ph);color:#6b6b66}`;
    document.head.appendChild(st);
  }
  try { document.execCommand("defaultParagraphSeparator", false, "p"); document.execCommand("styleWithCSS", false, false); } catch (e) {}

  /* ----- Editor d'una fitxa dins d'un contenidor -----
     editor(caixa, fitxa) pinta els camps i retorna { valors(), omple(f) }. */
  function editor(caixa, fitxa) {
    posaEstils();
    if (!document.getElementById("faMunicipis")) {
      const dl = document.createElement("datalist");
      dl.id = "faMunicipis";
      dl.innerHTML = MUNICIPIS.map(m => `<option value="${esc(m)}">`).join("");
      document.body.appendChild(dl);
    }
    caixa.innerHTML = `<div class="fa-camps">
      <label class="ample">Títol de l'acte <input type="text" data-c="titol" placeholder="Presentació del pressupost municipal, ple de novembre…"></label>
      <label>Qui parla (separats per comes) <input type="text" data-c="qui" placeholder="Nom Cognom, Nom Cognom"></label>
      <label>Data <input type="date" data-c="data"></label>
      <label>Tipus <select data-c="categoria">${CATEGORIES.map(c => `<option value="${c[0]}">${c[1]} ${c[2]}</option>`).join("")}</select></label>
      <label>Municipi <input type="text" data-c="municipi" list="faMunicipis" placeholder="La Bisbal d'Empordà…"></label>
      <label>Lloc <input type="text" data-c="lloc" placeholder="Sala de plens, Teatre…"></label>
      <div class="fa-desc ample">Descripció
        <div class="fa-barra">
          <button type="button" data-cmd="bold" title="Negreta (Ctrl+B)"><b>N</b></button>
          <button type="button" data-cmd="italic" title="Cursiva (Ctrl+I)"><i>C</i></button>
          <button type="button" data-cmd="underline" title="Subratllat (Ctrl+U)"><u>S</u></button>
          <button type="button" data-cmd="removeFormat" title="Treu el format del que hagis seleccionat">✕ format</button>
        </div>
        <div class="fa-text" contenteditable="true" spellcheck="true" lang="ca" data-ph="Context: de què parla, en quin acte… Cada Intro és un paràgraf nou."></div>
      </div>
    </div>`;
    const c = n => caixa.querySelector(`[data-c="${n}"]`);
    const text = caixa.querySelector(".fa-text"), barra = caixa.querySelector(".fa-barra");
    barra.addEventListener("mousedown", e => { if (e.target.closest("button[data-cmd]")) e.preventDefault(); });
    barra.addEventListener("click", e => {
      const b = e.target.closest("button[data-cmd]");
      if (!b) return;
      if (!text.contains(document.getSelection().anchorNode)) text.focus();
      document.execCommand(b.dataset.cmd, false, null);
    });
    text.addEventListener("paste", e => {
      e.preventDefault();
      document.execCommand("insertText", false, (e.clipboardData || window.clipboardData).getData("text/plain").replace(/\r\n/g, "\n"));
    });
    document.addEventListener("selectionchange", () => {
      const n = document.getSelection().anchorNode, dins = n && text.contains(n);
      barra.querySelectorAll("button[data-cmd]").forEach(b =>
        b.classList.toggle("on", !!dins && b.dataset.cmd !== "removeFormat" && document.queryCommandState(b.dataset.cmd)));
    });
    const omple = f => {
      f = f || {};
      c("titol").value = f.titol || "";
      c("qui").value = (Array.isArray(f.qui) ? f.qui : [f.qui].filter(Boolean)).join(", ");
      c("data").value = f.data || "";
      c("categoria").value = CATEGORIES.some(x => x[0] === f.categoria) ? f.categoria : "declaracions";
      c("municipi").value = f.municipi || "";
      c("lloc").value = f.lloc || "";
      text.innerHTML = marcaAHtml(f.descripcio || "");
    };
    omple(fitxa);
    return {
      omple,
      camp: c,
      valors: () => ({
        titol: c("titol").value.trim(),
        qui: c("qui").value.split(",").map(x => x.trim()).filter(Boolean),
        data: c("data").value || "",
        categoria: c("categoria").value,
        municipi: c("municipi").value.trim(),
        lloc: c("lloc").value.trim(),
        descripcio: htmlAMarca(text)
      })
    };
  }

  /* ----- Worker ----- */
  async function crida(pin, cos) {
    const r = await fetch(WORKER, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin, ...cos }) });
    let d = {};
    try { d = await r.json(); } catch (e) {}
    if (!r.ok || !d.ok) {
      const err = new Error(d.error || ("HTTP " + r.status));
      err.conflicte = r.status === 409;
      err.clau = r.status === 401 || r.status === 403;
      throw err;
    }
    return d;
  }
  const llegeix = pin => crida(pin, { accio: "fonoteca-llegeix" });

  /* Desa (o substitueix) les fitxes donades, conservant-ne la resta de camps
     (destacat, amagat…). Si algú ha desat entremig, ho torna a provar. */
  async function desaFitxes(pin, fitxes) {
    for (let intent = 0; intent < 3; intent++) {
      const d = await llegeix(pin);
      const audios = ((d.fonoteca || {}).audios || []).slice();
      fitxes.forEach(f => {
        const i = audios.findIndex(x => x.fitxer === f.fitxer);
        const abans = i >= 0 && !audios[i].eliminat ? audios[i] : {};
        const nova = { destacat: false, amagat: false, ...abans, ...f, revisar: false };
        delete nova.eliminat;
        if (i >= 0) audios[i] = nova; else audios.push(nova);
      });
      try { return await crida(pin, { accio: "fonoteca-desa", fonoteca: { audios }, sha: d.sha }); }
      catch (e) { if (!e.conflicte || intent === 2) throw e; }
    }
  }

  async function baixaJson(url) {
    const r = await fetch(url + "?v=" + Date.now(), { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  window.FitxaAudio = {
    WORKER, CATALEG, INVENTARI, FONOTECA_AUDIOS, COMPRIMITS, CATEGORIES,
    esc, dataCa, nomComprimit, esAudio, dataDelNom, marcaAHtml, htmlAMarca,
    editor, crida, llegeix, desaFitxes, baixaJson
  };
})();
