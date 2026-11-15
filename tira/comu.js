// =============================================================================
// TIRA DE TITULARS — codi comú (15.11.2026)
//
// El fan servir La TdG ampliada (index.html, la tira «Últimes notícies») i la
// pàgina de gestió tauler/tira/, perquè totes dues vegin exactament les
// mateixes notícies.
//
// · candidats(): els titulars de La TdG (titulars.json) i la premsa local i
//   generalista del darrer resum de La TdG redacció.
// · carregaTria(): la tria feta a mà a tauler/tira/ (dades/tira.json).
// · aplica(candidats, tria): el que surt a la tira: canvia el text de les
//   notícies editades, treu les notícies i els mitjans amagats, hi posa les
//   notícies afegides a mà i deixa la premsa generalista en un màxim de 10.
// =============================================================================
(() => {
  const BASE = "https://latdg.github.io/redaccio/dades/";
  const TRIA = "https://raw.githubusercontent.com/latdg/tauler/main/dades/tira.json";
  const MAX_GEN = 10;
  const NOMS_GEN = [
    [/vilaweb/, "VilaWeb"], [/naciodigital/, "Nació Digital"], [/^ara\.cat$/, "Ara"], [/elperiodico/, "El Periódico"],
    [/lavanguardia/, "La Vanguardia"], [/elpais/, "El País"], [/elnacional/, "El Nacional"], [/rac1/, "RAC1"],
    [/elmon/, "El Món"], [/cadenaser/, "Cadena SER"], [/3cat|ccma/, "3Cat"], [/europapress/, "Europa Press"],
    [/elpuntavui/, "El Punt Avui"], [/rtve/, "RTVE"], [/catradio/, "Catalunya Ràdio"], [/elmundo/, "El Mundo"],
    [/eldiario/, "elDiario.es"], [/acn\.cat/, "ACN"], [/msn\.com/, "MSN"], [/diaridegirona/, "Diari de Girona"]
  ];
  const nomMitja = n => { const t = String(n).toLowerCase(); const m = NOMS_GEN.find(([rx]) => rx.test(t)); return m ? m[1] : n; };
  const obtenir = async (url, text) => { const r = await fetch(url, { cache: "no-cache" }); if (!r.ok) throw new Error(r.status); return text ? r.text() : r.json(); };
  // Clau d'una notícia: el titular en minúscules i sense espais de més.
  const avuiISO = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };
  const clau = titol => String(titol || "").toLowerCase().replace(/\s+/g, " ").trim();

  function premsaDelResum(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const RX = /^\s*((?:\d️?⃣)+)\s*(.+)$/s;
    const blocs = {}; let actual = null;
    Array.from(doc.body.childNodes).forEach(node => {
      const text = (node.textContent || "").trim();
      if (node.nodeType === 1 && node.tagName === "DIV" && text.length < 200) {
        const m = text.match(RX);
        if (m) { const t = m[2].trim().toUpperCase(); actual = /^PREMSA LOCAL/.test(t) ? "local" : /^PREMSA GENERALISTA/.test(t) ? "gen" : null; if (actual) blocs[actual] = ""; return; }
      }
      if (!actual) return;
      if (node.nodeType === 1 && node.tagName === "BR") blocs[actual] += "\n";
      else if (node.nodeType === 1) blocs[actual] += (node.innerHTML || "").replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "");
      else blocs[actual] += node.textContent || "";
    });
    const fora = {};
    Object.entries(blocs).forEach(([cl, txt]) => {
      const llista = []; let mitja = "";
      const linies = txt.split("\n").map(x => x.trim()).filter(Boolean);
      linies.forEach((l, i) => {
        const m = l.match(/^▶\s*(.+?):\s*$/);
        if (m) { mitja = m[1].trim(); return; }
        const n = l.match(/^•\s*(?:\d{2}\.\d{2}\.\d{4}\s*[—–-]\s*)?(.+)$/);
        if (n && mitja && !/^No s.han trobat/i.test(n[1])) {
          const seg = linies[i + 1] || "";
          llista.push({ mitja, titol: n[1].trim(), url: /^https?:\/\//.test(seg) ? seg : "" });
        }
      });
      const vist = new Set();
      fora[cl] = llista.filter(x => { const k = clau(x.titol); if (vist.has(k)) return false; vist.add(k); return true; });
    });
    return fora;
  }

  async function candidats() {
    let dies = [];
    try { dies = (await obtenir(BASE + "dies.json")).slice().sort().reverse(); } catch (e) { return null; }
    let tdg = [], premsa = { local: [], gen: [] }, dia = "";
    for (const d of dies.slice(0, 3)) {
      if (!tdg.length) { try { const t = await obtenir(BASE + d + "/titulars.json"); tdg = (t.titulars || []).filter(Boolean).map(x => ({ mitja: "La TdG", titol: x, url: "" })); } catch (e) {} }
      if (!premsa.local.length && !premsa.gen.length) { try { premsa = Object.assign({ local: [], gen: [] }, premsaDelResum(await obtenir(BASE + d + "/resum.html", true))); dia = d; } catch (e) {} }
      if (tdg.length && (premsa.local.length || premsa.gen.length)) break;
    }
    const marca = grup => x => Object.assign({}, x, { grup, clau: clau(x.titol) });
    return {
      dia,
      tdg: tdg.map(marca("tdg")),
      local: premsa.local.map(marca("local")),
      gen: premsa.gen.map(x => Object.assign({}, x, { mitja: nomMitja(x.mitja) })).map(marca("gen"))
    };
  }

  async function carregaTria() {
    try { return normal(await obtenir(TRIA + "?v=" + Date.now())); } catch (e) { return normal(null); }
  }
  const normal = t => ({
    amagats: (t && Array.isArray(t.amagats) ? t.amagats : []).filter(x => x && x.clau),
    editats: (t && Array.isArray(t.editats) ? t.editats : []).filter(x => x && x.clau && x.titol),
    mitjansAmagats: (t && Array.isArray(t.mitjansAmagats) ? t.mitjansAmagats : []).filter(Boolean),
    afegits: (t && Array.isArray(t.afegits) ? t.afegits : []).filter(x => x && x.titol && (!x.fins || x.fins >= avuiISO())),
    actualitzat: (t && t.actualitzat) || null
  });

  // Què surt a la tira. Cada element porta «surt» (true/false) i, si no surt, el motiu.
  function aplica(c, tria) {
    const amagats = new Set(tria.amagats.map(x => x.clau));
    const mitjans = new Set(tria.mitjansAmagats.map(m => m.toLowerCase()));
    const editats = new Map(tria.editats.map(e => [e.clau, e]));
    const decideix = x0 => {
      const e = editats.get(x0.clau);
      const x = e ? Object.assign({}, x0, { titol: e.titol, original: x0.titol, ...(e.mitja != null && e.mitja !== "" ? { mitja: e.mitja } : {}) }) : x0;
      if (amagats.has(x.clau)) return Object.assign({}, x, { surt: false, motiu: "amagada" });
      if (x.grup !== "tdg" && mitjans.has(String(x.mitja).toLowerCase())) return Object.assign({}, x, { surt: false, motiu: "mitjà amagat" });
      return Object.assign({}, x, { surt: true });
    };
    const tdg = c.tdg.map(decideix), local = c.local.map(decideix);
    let n = 0;
    const gen = c.gen.map(decideix).map(x => {
      if (!x.surt) return x;
      n++;
      return n > MAX_GEN ? Object.assign({}, x, { surt: false, motiu: "fora del límit de " + MAX_GEN }) : x;
    });
    const afegits = tria.afegits.map(x => ({ mitja: x.mitja || "", titol: x.titol, url: x.url || "", grup: "afegit", id: x.id, surt: true }));
    return { afegits, tdg, local, gen };
  }

  // La llista final, en l'ordre de la tira: afegides a mà, La TdG, premsa.
  function tira(r) {
    const surt = l => l.filter(x => x.surt);
    return [surt(r.afegits).concat(surt(r.tdg)), surt(r.local).concat(surt(r.gen))];
  }

  window.TiraTdG = { candidats, carregaTria, aplica, tira, clau, MAX_GEN };
})();
