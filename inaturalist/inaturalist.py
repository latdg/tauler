# =============================================================================
# NATURA A PROP (iNaturalist) — La TdG · 31.10.2026
# Observacions de flora i fauna que la gent penja a iNaturalist dins dels cinc
# municipis (la Bisbal d'Empordà, Forallac, Corçà, Cruïlles, Monells i Sant
# Sadurní de l'Heura i Ullastret). Es demanen les del darrer any dins del
# requadre que els envolta i cadascuna s'assigna al seu municipi amb els límits
# municipals (llamps/girona.json). Desa dades/inaturalist.json per al tauler.
# Dades: API pública d'iNaturalist (sense clau). Llicències de les fotos: les que
# triï cada autor (es mostren amb el seu nom i l'enllaç a l'observació).
# =============================================================================
import json
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "inaturalist.json"
GEO = ARREL / "llamps" / "girona.json"
API = "https://api.inaturalist.org/v1/observations"
CAPCALERES = {"User-Agent": "LaTdG-tauler (https://latdg.github.io/tauler/; latdg@laguait.cat)"}
MUNICIPIS = {
    "17022": "la Bisbal d'Empordà",
    "17902": "Forallac",
    "17057": "Corçà",
    "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura",
    "17205": "Ullastret",
}
DIES = 365      # 31.10.2026: un any (en 90 dies en sortien poques)
RECENTS = 40          # observacions recents que es guarden per municipi
MAX_PAGINES = 25      # 200 per pàgina
GRUPS = {"Plantae": "🌿 Plantes", "Aves": "🐦 Ocells", "Insecta": "🦋 Insectes", "Fungi": "🍄 Fongs",
         "Mammalia": "🦊 Mamífers", "Reptilia": "🦎 Rèptils", "Amphibia": "🐸 Amfibis", "Arachnida": "🕷️ Aranyes",
         "Mollusca": "🐌 Mol·luscs", "Actinopterygii": "🐟 Peixos", "Animalia": "🐾 Altres animals",
         "Chromista": "🦠 Altres", "Protozoa": "🦠 Altres"}


# --- Límits municipals (TopoJSON sense quantitzar) ---------------------------
def poligons():
    g = json.loads(GEO.read_text(encoding="utf-8"))
    arcs = g["arcs"]

    def arc(i):
        a = arcs[i] if i >= 0 else list(reversed(arcs[~i]))
        return a

    def anell(llista):
        punts = []
        for i in llista:
            a = arc(i)
            punts.extend(a if not punts else a[1:])
        return punts

    surt = {}
    for geo in g["objects"]["municipis"]["geometries"]:
        codi = str(geo.get("id"))
        if codi not in MUNICIPIS:
            continue
        if geo["type"] == "Polygon":
            surt[codi] = [[anell(r) for r in geo["arcs"]]]
        elif geo["type"] == "MultiPolygon":
            surt[codi] = [[anell(r) for r in p] for p in geo["arcs"]]
    return surt


def dins_anell(x, y, anell):
    d = False
    j = len(anell) - 1
    for i in range(len(anell)):
        xi, yi = anell[i][0], anell[i][1]
        xj, yj = anell[j][0], anell[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            d = not d
        j = i
    return d


def municipi_de(lon, lat, polis):
    for codi, multi in polis.items():
        for p in multi:
            if p and dins_anell(lon, lat, p[0]) and not any(dins_anell(lon, lat, forat) for forat in p[1:]):
                return codi
    return None


def requadre(polis):
    xs = [pt[0] for m in polis.values() for p in m for r in p for pt in r]
    ys = [pt[1] for m in polis.values() for p in m for r in p for pt in r]
    return min(xs), min(ys), max(xs), max(ys)


# --- iNaturalist -------------------------------------------------------------
def baixa(bbox):
    x0, y0, x1, y1 = bbox
    d1 = (datetime.now(timezone.utc) - timedelta(days=DIES)).date().isoformat()
    totes, id_max = [], None
    for pagina in range(MAX_PAGINES):
        params = {"swlat": y0, "swlng": x0, "nelat": y1, "nelng": x1, "d1": d1, "per_page": 200,
                  "order_by": "id", "order": "desc", "locale": "ca", "geoprivacy": "open"}
        if id_max:
            params["id_below"] = id_max
        for intent in range(3):
            r = requests.get(API, params=params, headers=CAPCALERES, timeout=60)
            if r.status_code == 429:
                time.sleep(30)
                continue
            r.raise_for_status()
            break
        res = r.json().get("results") or []
        if not res:
            break
        totes.extend(res)
        id_max = res[-1]["id"]
        time.sleep(1.2)   # iNaturalist demana menys d'una consulta per segon
        if len(res) < 200:
            break
    return totes


def fitxa(o):
    t = o.get("taxon") or {}
    foto = ((o.get("photos") or [{}])[0].get("url") or "").replace("/square.", "/small.")
    return {
        "id": o["id"], "data": o.get("observed_on") or "", "url": o.get("uri") or f"https://www.inaturalist.org/observations/{o['id']}",
        "nom": (t.get("preferred_common_name") or "").strip(), "cientific": t.get("name") or "",
        "rang": t.get("rank") or "", "grup": GRUPS.get(t.get("iconic_taxon_name") or "", "🐾 Altres"),
        "foto": foto, "autor": ((o.get("user") or {}).get("name") or (o.get("user") or {}).get("login") or "").strip(),
        "lloc": (o.get("place_guess") or "").strip()[:80], "qualitat": o.get("quality_grade") or "",
        "amenacada": bool(t.get("threatened")), "introduida": bool(t.get("introduced")),
    }


def main():
    polis = poligons()
    falten = [c for c in MUNICIPIS if c not in polis]
    if falten:
        print("⚠️ Sense límits per a:", falten)
    obs = baixa(requadre(polis))
    print("Observacions al requadre:", len(obs))
    per = {c: [] for c in MUNICIPIS}
    for o in obs:
        loc = o.get("location") or ""
        if "," not in loc:
            continue
        lat, lon = (float(x) for x in loc.split(","))
        c = municipi_de(lon, lat, polis)
        if c:
            per[c].append(fitxa(o))
    sortida = {"actualitzat": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dies": DIES,
               "font": "https://www.inaturalist.org", "municipis": {}}
    for c, llista in per.items():
        llista.sort(key=lambda x: (x["data"], x["id"]), reverse=True)
        especies = Counter((x["cientific"], x["nom"], x["grup"]) for x in llista if x["rang"] in ("species", "subspecies", "variety"))
        grups = Counter(x["grup"] for x in llista)
        sortida["municipis"][c] = {
            "nom": MUNICIPIS[c], "observacions": len(llista), "especies": len(especies),
            "observadors": len({x["autor"] for x in llista if x["autor"]}),
            "grups": grups.most_common(),
            "mesVistes": [{"cientific": k[0], "nom": k[1], "grup": k[2], "n": n} for k, n in especies.most_common(12)],
            "destacades": [x for x in llista if x["amenacada"]][:10],
            "recents": llista[:RECENTS],
        }
        print(f"{MUNICIPIS[c]}: {len(llista)} observacions, {len(especies)} espècies")
    SORTIDA.parent.mkdir(parents=True, exist_ok=True)
    SORTIDA.write_text(json.dumps(sortida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
