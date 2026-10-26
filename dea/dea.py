# =============================================================================
# DESFIBRIL·LADORS (DEA) — La TdG · 26.10.2026
# Registre de desfibril·ladors instal·lats a Catalunya fora de l'àmbit sanitari
# (Departament de Salut, dades obertes, conjunt wpud-ukyg). Baixa els dels
# quatre municipis i els desa a dades/dea.json per al tauler.
# Els que no porten coordenades es localitzen amb el geocodificador de l'ICGC
# (i queden marcats com a posició aproximada). Els que van en vehicles no van
# al mapa: es llisten a part.
# =============================================================================
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "dea.json"
API = "https://analisi.transparenciacatalunya.cat/resource/wpud-ukyg.json"
VISTA = "https://analisi.transparenciacatalunya.cat/api/views/wpud-ukyg.json"
GEOCODER = "https://eines.icgc.cat/geocodificador/cerca"
MUNICIPIS = {
    "17022": "la Bisbal d'Empordà",
    "17057": "Corçà",
    "17902": "Forallac",
    "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura",
}
CAPCALERES = {"User-Agent": "LaTdG-tauler (https://latdg.github.io/tauler/)"}


def net(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def adreca(r):
    via = " ".join(x for x in (net(r.get("tipus_via")), net(r.get("nom_via"))) if x)
    num = net(r.get("numero_via"))
    return (via + (", " + num if num else "")).strip(", ")


def horari(r):
    franges = []
    for k in sorted(r):
        m = re.fullmatch(r"dia_(\d+)", k)
        if not m:
            continue
        n = m.group(1)
        ini, fi = net(r.get(f"hora_inici_{n}")), net(r.get(f"hora_fi_{n}"))
        franges.append({"dia": net(r[k]), "inici": ini, "fi": fi})
    return franges


def geocodifica(text):
    try:
        g = requests.get(GEOCODER, params={"text": text, "size": 1}, headers=CAPCALERES, timeout=30)
        g.raise_for_status()
        f = (g.json().get("features") or [None])[0]
        if f:
            lon, lat = f["geometry"]["coordinates"][:2]
            return round(lat, 6), round(lon, 6)
    except Exception as err:
        print("Geocodificador:", text, err)
    return None


def main():
    codis = ",".join(f"'{c}'" for c in MUNICIPIS)
    r = requests.get(API, params={"$where": f"codi_municipi in({codis})", "$limit": 1000},
                     headers=CAPCALERES, timeout=120)
    r.raise_for_status()
    files = r.json()
    print(len(files), "registres als quatre municipis")
    try:
        act = requests.get(VISTA, headers=CAPCALERES, timeout=60).json().get("rowsUpdatedAt")
        actualitzat = datetime.fromtimestamp(act, timezone.utc).isoformat() if act else None
    except Exception:
        actualitzat = None

    fixos, vehicles = [], []
    for x in files:
        nom = net(x.get("nom_centre")).lstrip("- ").strip()
        d = {
            "num": net(x.get("numero_inscripcio")),
            "nom": nom,
            "adreca": adreca(x),
            "espai": net(x.get("espai_fisic")),
            "mun": net(x.get("codi_municipi")),
            "titular": net(x.get("titular")),
            "horari": horari(x),
        }
        if net(x.get("vehicle")).lower().startswith("s"):
            vehicles.append(d)
            continue
        lat, lon = x.get("latitud"), x.get("longitud")
        if lat and lon:
            d["lat"], d["lon"], d["aprox"] = round(float(lat), 6), round(float(lon), 6), False
        else:
            p = geocodifica(f"{d['adreca']}, {MUNICIPIS.get(d['mun'], '')}") if d["adreca"] else None
            time.sleep(1)
            if p:
                d["lat"], d["lon"], d["aprox"] = p[0], p[1], True
        fixos.append(d)

    ordre = list(MUNICIPIS)
    fixos.sort(key=lambda z: (ordre.index(z["mun"]) if z["mun"] in ordre else 9, z["nom"]))
    vehicles.sort(key=lambda z: (ordre.index(z["mun"]) if z["mun"] in ordre else 9, z["titular"]))
    SORTIDA.write_text(json.dumps({
        "generat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actualitzatFont": actualitzat,
        "municipis": MUNICIPIS,
        "font": "Registre de desfibril·ladors instal·lats a Catalunya fora de l'àmbit sanitari (Departament de Salut)",
        "fixos": fixos,
        "vehicles": vehicles,
        "mostraCrua": files[:3],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(fixos)} fixos ({sum(1 for f in fixos if f.get('aprox'))} localitzats amb l'ICGC, "
          f"{sum(1 for f in fixos if 'lat' not in f)} sense posició) i {len(vehicles)} en vehicles")


if __name__ == "__main__":
    main()
