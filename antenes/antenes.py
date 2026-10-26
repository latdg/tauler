# =============================================================================
# ANTENES DE TELEFONIA MÒBIL — La TdG · 26.10.2026
# Baixa de l'API pública de Celda (celda.elies.site, dades d'Infoantenas del
# Ministeri) els emplaçaments dels quatre municipis i les seves fitxes (bandes
# i mesures d'exposició) i ho desa a dades/antenes.json per al tauler.
# Celda refà les dades el primer cap de setmana de cada mes: n'hi ha prou
# d'executar-ho un cop al mes. Límit de l'API: 60 consultes per minut.
# =============================================================================
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "antenes.json"
GEO = ARREL / "llamps" / "girona.json"

API = "https://celda.elies.site/api/emplazamientos"
MUNICIPIS = {
    "17022": "la Bisbal d'Empordà",
    "17057": "Corçà",
    "17902": "Forallac",
    "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura",
}
COSTAT_KM = 3.0          # cel·les de la graella de consultes
PAUSA = 1.2              # segons entre consultes (menys de 60 per minut)
CAPCALERES = {"Accept": "application/json", "User-Agent": "LaTdG-tauler (https://latdg.github.io/tauler/)"}

sessio = requests.Session()
sessio.headers.update(CAPCALERES)
consultes = 0


def get(url, params=None):
    global consultes
    for intent in range(4):
        consultes += 1
        r = sessio.get(url, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(65 if r.status_code == 429 else 20)
            continue
        r.raise_for_status()
        time.sleep(PAUSA)
        return r.json()
    raise RuntimeError(f"No s'ha pogut llegir {url} {params}")


def caixa_municipis():
    """Rectangle que conté els quatre municipis (del TopoJSON de llamps/)."""
    g = json.loads(GEO.read_text(encoding="utf-8"))
    t = g.get("transform")
    arcs = []
    for arc in g["arcs"]:
        x = y = 0
        punts = []
        for p in arc:
            if t:
                x += p[0]; y += p[1]
                punts.append((x * t["scale"][0] + t["translate"][0], y * t["scale"][1] + t["translate"][1]))
            else:
                punts.append((p[0], p[1]))
        arcs.append(punts)

    def indexs(a):
        if isinstance(a, int):
            yield a if a >= 0 else ~a
        else:
            for b in a:
                yield from indexs(b)

    xs, ys = [], []
    for geo in g["objects"]["municipis"]["geometries"]:
        if geo.get("id") in MUNICIPIS:
            for i in indexs(geo["arcs"]):
                for lon, lat in arcs[i]:
                    xs.append(lon); ys.append(lat)
    marge = 0.01
    return min(ys) - marge, min(xs) - marge, max(ys) + marge, max(xs) + marge


def cerca(lat, lon, costat_km, trobats):
    """Consulta una cel·la; si n'hi ha més de 50, la parteix en quatre."""
    radi = math.ceil(costat_km / math.sqrt(2) * 1000) + 100
    d = get(API, {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "radio": f"{radi}m", "limite": 50})
    for e in d.get("emplazamientos", []):
        trobats[e["clave"]] = e
    if d.get("hayMas") and costat_km > 0.4:
        dlat = costat_km / 4 / 111.32
        dlon = costat_km / 4 / (111.32 * math.cos(math.radians(lat)))
        for sl in (-1, 1):
            for so in (-1, 1):
                cerca(lat + sl * dlat, lon + so * dlon, costat_km / 2, trobats)
    return d


def main():
    s, o, n, e = caixa_municipis()
    lat_mig = (s + n) / 2
    pas_lat = COSTAT_KM / 111.32
    pas_lon = COSTAT_KM / (111.32 * math.cos(math.radians(lat_mig)))
    trobats, versio, fecha, licencies = {}, None, None, None
    lat = s + pas_lat / 2
    while lat - pas_lat / 2 < n:
        lon = o + pas_lon / 2
        while lon - pas_lon / 2 < e:
            d = cerca(lat, lon, COSTAT_KM, trobats)
            versio, fecha, licencies = d.get("version"), d.get("fecha"), d.get("licencias")
            lon += pas_lon
        lat += pas_lat

    nostres = [x for x in trobats.values() if (x.get("municipio") or {}).get("codigo") in MUNICIPIS]
    print(f"{len(trobats)} emplaçaments a la zona, {len(nostres)} dels quatre municipis ({consultes} consultes)")
    if not nostres:
        sys.exit("No s'ha trobat cap emplaçament: no es toca el fitxer.")

    # Fitxes: cada lot en porta fins a 128; es baixa un sol cop cada lot.
    lots = {}
    for x in nostres:
        if x.get("ficha") and x["ficha"] not in lots:
            try:
                lots[x["ficha"]] = {f["clave"]: f for f in get(x["ficha"]).get("fichas", [])}
            except Exception as err:
                print("No s'ha pogut llegir el lot", x["ficha"], err)
                lots[x["ficha"]] = {}

    emplacaments = []
    for x in nostres:
        fitxa = lots.get(x.get("ficha"), {}).get(x["clave"], {})
        bandes_api = {b["compania"]: b.get("mhz", []) for b in x.get("bandas", [])}
        operadors = []
        estacions = fitxa.get("estaciones") or [{"compania": c} for c in x.get("companias", [])]
        for est in estacions:
            op = est.get("compania")
            mhz = sorted({b["mhz"] for b in est.get("bandas", []) if b.get("mhz")} or set(bandes_api.get(op, [])))
            mesures = est.get("medidasDeExposicion")
            registre = next((og.get("url") for og in est.get("origenes", []) if og.get("url")), None)
            operadors.append({
                "op": op,
                "mhz": mhz,
                "senseLlegir": bool(est.get("bandasSinLeer")),
                # null: Celda encara no ha llegit les mesures; []: el registre no en publica cap.
                "mesures": None if mesures is None else [
                    {"m": round(m["distanciaMetros"]), "az": round(m["acimutGrados"]), "uw": m["microvatiosPorCm2"]} for m in mesures],
                "registre": registre,
            })
        emplacaments.append({
            "clau": x["clave"],
            "lat": x["posicion"]["latitud"],
            "lon": x["posicion"]["longitud"],
            "mun": x["municipio"]["codigo"],
            "adreca": fitxa.get("direccion", ""),
            "estat": x.get("estado"),
            "operadors": operadors,
            "enllac": x.get("enlace"),
        })
    emplacaments.sort(key=lambda z: (list(MUNICIPIS).index(z["mun"]), z["adreca"]))

    SORTIDA.write_text(json.dumps({
        "generat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versioCelda": versio,
        "dataCelda": fecha,
        "municipis": MUNICIPIS,
        "credit": "Origen de los datos: Ministerio para la Transformación Digital y de la Función Pública (Infoantenas)",
        "licencies": licencies,
        "emplacaments": emplacaments,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Desat", SORTIDA)


if __name__ == "__main__":
    main()
