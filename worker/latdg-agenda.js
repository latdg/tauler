// =============================================================================
// WORKER «latdg-agenda» — La TdG · 24.10.2026
//
// Desa l'agenda d'actes (dades/agenda.json del repo latdg/tauler) des de la
// pàgina latdg.github.io/tauler/agenda/, amb la mateixa clau que els llamps.
//
// Variables secretes del Worker (Settings > Variables and Secrets):
//   PIN       la clau (la mateixa que el Worker latdg-llamps)
//   GH_TOKEN  testimoni de GitHub (fine-grained) amb permís «Contents: Read and
//             write» només sobre el repositori latdg/tauler
//
// Peticions (POST, JSON):
//   { pin, accio: "llegeix" }                 → { ok, agenda, sha }
//   { pin, accio: "desa", agenda, sha }       → { ok, agenda, sha }
// Si algú altre ha desat entremig (el sha no coincideix), respon 409 i la
// pàgina torna a carregar l'agenda abans de deixar desar.
// =============================================================================

const REPO = "latdg/tauler";
const FITXER = "dades/agenda.json";
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

    const gh = (cami, opcions = {}) => fetch("https://api.github.com/repos/" + REPO + cami, {
      ...opcions,
      headers: {
        "Authorization": "Bearer " + env.GH_TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "latdg-agenda",
        ...(opcions.headers || {})
      }
    });

    async function llegeix() {
      const r = await gh("/contents/" + FITXER + "?ref=main");
      if (r.status === 404) return { agenda: { actes: [] }, sha: null };
      if (!r.ok) throw new Error("GitHub " + r.status);
      const d = await r.json();
      const bytes = Uint8Array.from(atob(d.content.replace(/\n/g, "")), c => c.charCodeAt(0));
      return { agenda: JSON.parse(new TextDecoder().decode(bytes)), sha: d.sha };
    }

    try {
      if (cos.accio === "llegeix") {
        const { agenda, sha } = await llegeix();
        return resposta({ ok: true, agenda, sha });
      }

      if (cos.accio === "desa") {
        const actes = neteja(cos.agenda && cos.agenda.actes);
        if (!actes) return resposta({ ok: false, error: "Hi ha actes amb dades que no són vàlides." }, 400);

        const actual = await llegeix();
        if (actual.sha && cos.sha !== actual.sha)
          return resposta({ ok: false, error: "Algú ha canviat l'agenda mentrestant. Torna-la a carregar.", conflicte: true }, 409);

        const agenda = {
          actualitzat: new Date().toISOString(),
          actes: actes.sort((a, b) => (a.data + (a.hora || "99")).localeCompare(b.data + (b.hora || "99")))
        };
        const text = JSON.stringify(agenda, null, 1) + "\n";
        const bytes = new TextEncoder().encode(text);
        let bin = "";
        for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
        const b64 = btoa(bin);
        const r = await gh("/contents/" + FITXER, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: "Agenda d'actes (" + actes.length + " actes)",
            content: b64,
            branch: "main",
            ...(actual.sha ? { sha: actual.sha } : {}),
            committer: { name: "La TdG (agenda)", email: "41898282+github-actions[bot]@users.noreply.github.com" }
          })
        });
        if (!r.ok) throw new Error("GitHub " + r.status + ": " + (await r.text()).slice(0, 200));
        const d = await r.json();
        return resposta({ ok: true, agenda, sha: d.content.sha });
      }

      return resposta({ ok: false, error: "Acció desconeguda" }, 400);
    } catch (e) {
      return resposta({ ok: false, error: String(e.message || e) }, 502);
    }
  }
};

// Comprova cada acte i deixa només els camps coneguts. Retorna null si n'hi ha
// algun de dolent (la pàgina ja ho valida abans; això és per seguretat).
function neteja(llista) {
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
