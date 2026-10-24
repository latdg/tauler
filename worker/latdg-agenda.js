// =============================================================================
// WORKER «latdg-agenda» — La TdG · 24.10.2026
//
// 1) AGENDA D'ACTES: desa dades/agenda.json del repo públic latdg/tauler des
//    de la pàgina latdg.github.io/tauler/agenda/.
// 2) NOTÍCIES DEL GUIÓ (afegit el 24.10.2026): desa les notícies de cada dia
//    al repo PRIVAT latdg/noticies (dies/AAAA-MM-DD.json), des de la pàgina
//    latdg.github.io/redaccio/noticies/. El guió les llegeix d'aquí mateix.
//
// 3) ESPORTS (afegit el 24.10.2026): desa els partits i classificacions que
//    s'entren a mà (dades/esports-manual.json del repo latdg/tauler) des de la
//    pàgina latdg.github.io/tauler/esports/.
//
// Sempre amb la mateixa clau que els llamps.
//
// Variables secretes del Worker (Settings > Variables and Secrets):
//   PIN       la clau (la mateixa que el Worker latdg-llamps)
//   GH_TOKEN  testimoni de GitHub (fine-grained) amb permís «Contents: Read and
//             write» sobre latdg/tauler i latdg/noticies
//
// Peticions (POST, JSON, sempre amb «pin»):
//   { accio: "llegeix" }                          → agenda
//   { accio: "desa", agenda, sha }                → desa l'agenda
//   { accio: "noticies-dies" }                    → { dies: ["2026-10-27", …] }
//   { accio: "noticies-llegeix", dia }            → { noticies: [...], sha }
//   { accio: "noticies-desa", dia, noticies, sha } → desa (o esborra si és buit)
//   { accio: "esports-llegeix" }                  → { manual, sha }
//   { accio: "esports-desa", manual, sha }        → desa dades/esports-manual.json
// Si algú altre ha desat entremig (el sha no coincideix), respon 409.
// =============================================================================

const AGENDA = { repo: "latdg/tauler", cami: "dades/agenda.json" };
const NOTICIES_REPO = "latdg/noticies";
const ESPORTS = { repo: "latdg/tauler", cami: "dades/esports-manual.json" };
const EQUIPS_ESPORTS = ["atletic_bisbalenc", "monells_a", "monells_b", "la_pera", "la_pera_femeni", "sol_girones", "sol_girones_sots25"];
const ORIGENS = ["https://latdg.github.io"];

export default {
  async fetch(req, env) {
    const origen = req.headers.get("Origin") || "";
    const cors = {
      "Access-Control-Allow-Origin": ORIGENS.includes(origen) ? origen : ORIGENS[0],
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin"
    };
    const resposta = (dades, estat = 200) =>
      new Response(JSON.stringify(dades), { status: estat, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" } });

    if (req.method === "OPTIONS") return new Response(null, { headers: cors });
    if (req.method !== "POST") return resposta({ ok: false, error: "Només POST" }, 405);

    let cos;
    try { cos = await req.json(); } catch (e) { return resposta({ ok: false, error: "JSON no vàlid" }, 400); }

    // Una mica de fre contra qui provi claus a l'atzar.
    if (!cos || String(cos.pin || "") !== String(env.PIN || "\u0000")) {
      await new Promise(r => setTimeout(r, 1500));
      return resposta({ ok: false, error: "La clau no és correcta." }, 401);
    }

    const gh = github(env.GH_TOKEN);

    try {
      // ---------------- AGENDA ----------------
      if (cos.accio === "llegeix") {
        const { dades, sha } = await gh.llegeix(AGENDA.repo, AGENDA.cami, { actes: [] });
        return resposta({ ok: true, agenda: dades, sha });
      }

      if (cos.accio === "desa") {
        const actes = netejaActes(cos.agenda && cos.agenda.actes);
        if (!actes) return resposta({ ok: false, error: "Hi ha actes amb dades que no són vàlides." }, 400);
        const agenda = {
          actualitzat: new Date().toISOString(),
          actes: actes.sort((a, b) => (a.data + (a.hora || "99")).localeCompare(b.data + (b.hora || "99")))
        };
        const sha = await gh.desa(AGENDA.repo, AGENDA.cami, agenda, cos.sha, "Agenda d'actes (" + actes.length + " actes)", "La TdG (agenda)");
        return resposta({ ok: true, agenda, sha });
      }

      // ---------------- NOTÍCIES ----------------
      if (cos.accio === "noticies-dies") {
        const llista = await gh.llista(NOTICIES_REPO, "dies");
        const dies = llista.map(f => f.name.replace(/\.json$/, "")).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
        return resposta({ ok: true, dies });
      }

      if (cos.accio === "noticies-llegeix") {
        const dia = String(cos.dia || "");
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dia)) return resposta({ ok: false, error: "Dia no vàlid." }, 400);
        const { dades, sha } = await gh.llegeix(NOTICIES_REPO, "dies/" + dia + ".json", { noticies: [] });
        return resposta({ ok: true, dia, noticies: dades.noticies || [], actualitzat: dades.actualitzat || null, sha });
      }

      if (cos.accio === "noticies-desa") {
        const dia = String(cos.dia || "");
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dia)) return resposta({ ok: false, error: "Dia no vàlid." }, 400);
        const noticies = netejaNoticies(cos.noticies);
        if (!noticies) return resposta({ ok: false, error: "Hi ha notícies que no són vàlides." }, 400);
        const cami = "dies/" + dia + ".json";
        if (!noticies.length) {
          await gh.esborra(NOTICIES_REPO, cami, cos.sha, "Notícies del " + dia + " esborrades", "La TdG (redacció)");
          return resposta({ ok: true, dia, noticies: [], sha: null });
        }
        const dades = { dia, actualitzat: new Date().toISOString(), noticies };
        const sha = await gh.desa(NOTICIES_REPO, cami, dades, cos.sha, "Notícies del " + dia + " (" + noticies.length + ")", "La TdG (redacció)");
        return resposta({ ok: true, dia, noticies, actualitzat: dades.actualitzat, sha });
      }

      // ---------------- ESPORTS ----------------
      if (cos.accio === "esports-llegeix") {
        const { dades, sha } = await gh.llegeix(ESPORTS.repo, ESPORTS.cami, { equips: {} });
        return resposta({ ok: true, manual: dades, sha });
      }

      if (cos.accio === "esports-desa") {
        const manual = netejaEsports(cos.manual);
        if (!manual) return resposta({ ok: false, error: "Hi ha dades d'esports que no són vàlides." }, 400);
        const sha = await gh.desa(ESPORTS.repo, ESPORTS.cami, manual, cos.sha, "Esports: canvis fets a mà", "La TdG (esports)");
        return resposta({ ok: true, manual, sha });
      }

      return resposta({ ok: false, error: "Acció desconeguda" }, 400);
    } catch (e) {
      if (e.conflicte) return resposta({ ok: false, error: "Algú ha canviat aquestes dades mentrestant. Torna-les a carregar.", conflicte: true }, 409);
      return resposta({ ok: false, error: String(e.message || e) }, 502);
    }
  }
};

// -----------------------------------------------------------------------------
// GitHub (API de continguts)
// -----------------------------------------------------------------------------
function github(token) {
  const crida = (repo, cami, opcions = {}) => fetch("https://api.github.com/repos/" + repo + cami, {
    ...opcions,
    headers: {
      "Authorization": "Bearer " + token,
      "Accept": "application/vnd.github+json",
      "User-Agent": "latdg-agenda",
      ...(opcions.headers || {})
    }
  });

  async function shaActual(repo, cami) {
    const r = await crida(repo, "/contents/" + cami + "?ref=main");
    if (r.status === 404) return null;
    if (!r.ok) throw new Error("GitHub " + r.status);
    return (await r.json()).sha;
  }

  return {
    async llegeix(repo, cami, perDefecte) {
      const r = await crida(repo, "/contents/" + cami + "?ref=main");
      if (r.status === 404) return { dades: perDefecte, sha: null };
      if (!r.ok) throw new Error("GitHub " + r.status + (r.status === 404 || r.status === 403 ? " (revisa el permís del testimoni)" : ""));
      const d = await r.json();
      const bytes = Uint8Array.from(atob(d.content.replace(/\n/g, "")), c => c.charCodeAt(0));
      return { dades: JSON.parse(new TextDecoder().decode(bytes)), sha: d.sha };
    },

    async llista(repo, carpeta) {
      const r = await crida(repo, "/contents/" + carpeta + "?ref=main");
      if (r.status === 404) return [];
      if (!r.ok) throw new Error("GitHub " + r.status);
      const d = await r.json();
      return Array.isArray(d) ? d : [];
    },

    async desa(repo, cami, dades, shaPagina, missatge, autor) {
      const actual = await shaActual(repo, cami);
      if (actual && shaPagina !== actual) { const e = new Error("conflicte"); e.conflicte = true; throw e; }
      const text = JSON.stringify(dades, null, 1) + "\n";
      const bytes = new TextEncoder().encode(text);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const r = await crida(repo, "/contents/" + cami, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: missatge, content: btoa(bin), branch: "main",
          ...(actual ? { sha: actual } : {}),
          committer: { name: autor, email: "41898282+github-actions[bot]@users.noreply.github.com" }
        })
      });
      if (!r.ok) throw new Error("GitHub " + r.status + ": " + (await r.text()).slice(0, 200));
      return (await r.json()).content.sha;
    },

    async esborra(repo, cami, shaPagina, missatge, autor) {
      const actual = await shaActual(repo, cami);
      if (!actual) return;
      if (shaPagina !== actual) { const e = new Error("conflicte"); e.conflicte = true; throw e; }
      const r = await crida(repo, "/contents/" + cami, {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: missatge, sha: actual, branch: "main",
          committer: { name: autor, email: "41898282+github-actions[bot]@users.noreply.github.com" }
        })
      });
      if (!r.ok) throw new Error("GitHub " + r.status + ": " + (await r.text()).slice(0, 200));
    }
  };
}

// -----------------------------------------------------------------------------
// Validació
// -----------------------------------------------------------------------------
function netejaActes(llista) {
  if (!Array.isArray(llista) || llista.length > 3000) return null;
  const surt = [];
  for (const a of llista) {
    if (!a || typeof a !== "object") return null;
    const x = {
      id: String(a.id || "").slice(0, 20) || Math.random().toString(36).slice(2, 12),
      data: String(a.data || ""),
      hora: String(a.hora || "").trim().slice(0, 20),
      municipi: String(a.municipi || "").trim().slice(0, 80),
      text: String(a.text || "").trim().slice(0, 3000)
    };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(x.data) || !x.text) return null;
    surt.push(x);
  }
  return surt;
}

function netejaNoticies(llista) {
  if (!Array.isArray(llista) || llista.length > 40) return null;
  const surt = [];
  for (const n of llista) {
    if (!n || typeof n !== "object") return null;
    const x = {
      id: String(n.id || "").slice(0, 20) || Math.random().toString(36).slice(2, 12),
      titol: String(n.titol || "").trim().slice(0, 200),
      text: String(n.text || "").replace(/\r\n/g, "\n").trim().slice(0, 20000)
    };
    if (!x.text && !x.titol) continue;   // les caixes buides no es desen
    surt.push(x);
  }
  return surt;
}

function netejaEsports(m) {
  if (!m || typeof m !== "object" || !m.equips || typeof m.equips !== "object") return null;
  const t = (v, n) => String(v ?? "").trim().slice(0, n);
  const sortida = { nota: t(m.nota, 500), equips: {} };
  for (const id of Object.keys(m.equips)) {
    if (!EQUIPS_ESPORTS.includes(id)) return null;
    const e = m.equips[id] || {};
    const partits = Array.isArray(e.partits) ? e.partits : [];
    const cls = Array.isArray(e.classificacio) ? e.classificacio : [];
    if (partits.length > 300 || cls.length > 40) return null;
    const ne = {
      partits: partits.map(p => ({
        id: t(p.id, 20) || Math.random().toString(36).slice(2, 12),
        competicio: t(p.competicio, 80), grup: t(p.grup, 80), jornada: t(p.jornada, 20),
        data: t(p.data, 10), hora: t(p.hora, 5), localVisitant: t(p.localVisitant, 10),
        rival: t(p.rival, 120), resultat: t(p.resultat, 20), estat: t(p.estat, 30),
        camp: t(p.camp, 200), nota: t(p.nota, 300), substitueix: t(p.substitueix, 40)
      })).filter(p => /^\d{4}-\d{2}-\d{2}$/.test(p.data) || p.substitueix),
      classificacio: cls.map(f => ({
        pos: Number(f.pos) || "", equip: t(f.equip, 120),
        pj: Number(f.pj) || 0, pg: Number(f.pg) || 0, pe: Number(f.pe) || 0, pp: Number(f.pp) || 0,
        pf: Number(f.pf) || 0, pc: Number(f.pc) || 0, punts: f.punts === "" || f.punts == null ? "" : Number(f.punts) || 0
      })).filter(f => f.equip)
    };
    if (e.classificacioActualitzada) ne.classificacioActualitzada = t(e.classificacioActualitzada, 40);
    sortida.equips[id] = ne;
  }
  return sortida;
}
