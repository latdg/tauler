// =============================================================================
// MARCADOR «Futbol → La TdG» — 09.11.2026
// La FCF bloqueja els servidors (Google, GitHub, Cloudflare), però no el teu
// navegador. Aquest marcador, tocat a qualsevol pàgina de www.fcf.cat, demana a
// la mateixa API de la FCF els partits i les classificacions dels quatre grups
// (Atlètic Bisbalenc; Monells A i La Pera; Monells B; La Pera femení) i baixa
// el fitxer futbol-tdg.json, que s'envia al bot latdg_infos o es puja a
// latdg.github.io/tauler/esports/. La pàgina d'esports en fa la versió
// «javascript:» per desar-la com a adreça d'interès.
// =============================================================================
(async () => {
  if (!/(^|\.)fcf\.cat$/.test(location.hostname)) {
    alert("Obre primer www.fcf.cat (qualsevol pàgina) i torna a tocar el marcador.");
    return;
  }
  const GRUPS = ["58161863", "58161891", "58161893", "58162320"];
  const CAMPS = ["CODACTA", "JORNADA", "CODEQUIPO_CASA", "NOMBRE_CASA", "ESCUDO_CASA", "CODEQUIPO_FUERA",
    "NOMBRE_FUERA", "ESCUDO_FUERA", "CAMPO", "GOLES_CASA", "GOLES_FUERA", "COMIENZO1", "CERRADA", "ESTADO"];
  const json = async u => { const r = await fetch(u, { cache: "no-store" }); if (!r.ok) throw new Error(u.split("?")[0].split("/").pop() + " " + r.status); return r.json(); };
  const sortida = { tipus: "latdg-fcf", versio: 1, generat: new Date().toISOString(), grups: {} };
  try {
    for (const g of GRUPS) {
      const [p, c] = await Promise.all([json("/api/competition/partidos?grupId=" + g), json("/api/competition/classificacio?grupId=" + g)]);
      const font = (p && p.partidos) || {}, partidos = {};
      for (const j of Object.keys(font)) {
        if (Array.isArray(font[j])) partidos[j] = font[j].map(m => Object.fromEntries(CAMPS.map(k => [k, m[k] ?? null])));
      }
      if (!Object.keys(partidos).length) throw new Error("el grup " + g + " no té partits");
      const files = ((c && c.data) || []).map(f => ({
        position: f.position, points: f.points, played: f.played, won: f.won, drawn: f.drawn, lost: f.lost,
        goalsFor: f.goalsFor, goalsAgainst: f.goalsAgainst,
        team: { name: f.team && f.team.name, logo: f.team && f.team.logo, teamId: f.team && f.team.teamId },
        form: (f.form || []).map(x => ({ date: x.date, result: x.result }))
      }));
      sortida.grups[g] = { partidos: { partidos }, classificacio: { data: files } };
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(sortida)], { type: "application/json" }));
    a.download = "futbol-tdg.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 4000);
    alert("Fet: s'ha baixat futbol-tdg.json.\nEnvia'l al bot latdg_infos o puja'l a la pàgina d'esports del tauler.");
  } catch (e) {
    alert("No s'ha pogut baixar el futbol de la FCF: " + e.message);
  }
})();
