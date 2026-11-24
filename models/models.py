# =============================================================================
# MODELS DE PREVISIÓ — La TdG ampliada · 24.11.2026
#
# Baixa d'Open-Meteo les previsions de diversos models numèrics (Météo-France,
# DWD, ECMWF, NOAA, KNMI, DMI, Met Office…) i les desa per a la pàgina
# latdg.github.io/tauler/models/:
#
#   index.json      la llista de models amb dades i la sèrie horària de 7 dies
#                   a la Bisbal d'Empordà de cada model (per a la comparativa)
#   g_<model>.json  una graella de punts sobre la província de Girona (4 dies, hora a
#                   hora) per pintar el mapa del model
#
# Els models que no donen dades a la Bisbal (el seu domini no hi arriba) queden
# fora sols. Si la graella d'un model falla, es manté la de l'última vegada.
#
# Ús: python models/models.py <carpeta de sortida>
# =============================================================================
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

API = "https://api.open-meteo.com/v1/forecast"
ZONA = ZoneInfo("Europe/Madrid")
BISBAL = (41.9600, 3.0386)

# id d'Open-Meteo, nom curt, organisme, resolució, grup
MODELS = [
    ("meteofrance_arome_france_hd", "AROME HD", "Météo-France", "1,5 km", "regional"),
    ("meteofrance_arome_france", "AROME", "Météo-France", "2,5 km", "regional"),
    ("dmi_harmonie_arome_europe", "HARMONIE (DMI)", "DMI (Dinamarca)", "2 km", "regional"),
    ("knmi_harmonie_arome_europe", "HARMONIE (KNMI)", "KNMI (Països Baixos)", "5,5 km", "regional"),
    ("italia_meteo_arpae_icon_2i", "ICON-2I", "ItaliaMeteo", "2,2 km", "regional"),
    ("icon_d2", "ICON-D2", "DWD (Alemanya)", "2,2 km", "regional"),
    ("icon_eu", "ICON-EU", "DWD (Alemanya)", "7 km", "regional"),
    ("meteofrance_arpege_europe", "ARPEGE", "Météo-France", "11 km", "regional"),
    ("ecmwf_ifs", "ECMWF IFS", "ECMWF (Centre Europeu)", "9 km", "global"),
    ("ecmwf_aifs025_single", "ECMWF AIFS (IA)", "ECMWF (Centre Europeu)", "25 km", "global"),
    ("gfs_global", "GFS", "NOAA (EUA)", "13 km", "global"),
    ("ukmo_global_deterministic_10km", "UKMO", "Met Office (Regne Unit)", "10 km", "global"),
    ("gem_global", "GEM", "ECCC (Canadà)", "15 km", "global"),
]

# Variables (nom d'Open-Meteo → clau curta i decimals)
VARS = [
    ("temperature_2m", "t", 1),
    ("precipitation", "p", 1),
    ("wind_speed_10m", "v", 0),
    ("cloud_cover", "n", 0),
]
VARS_PUNT = VARS + [("wind_gusts_10m", "r", 0)]
# 24.11.2026: el mapa baixa també la direcció del vent, per a les fletxes
VARS_GRAELLA = VARS + [("wind_direction_10m", "d", 0)]

# Graella del mapa: tota la província de Girona, cada 0,1° (uns 8-11 km).
# 24.11.2026: abans només el Baix Empordà (cada 0,06°). Són 162 punts per model:
# Open-Meteo els compta com 162 consultes, i per això es fa cada 6 hores i amb
# pauses entre models (límit gratuït: 600 per minut i 10.000 per dia).
LATS = [round(41.65 + 0.1 * i, 2) for i in range(9)]     # 41.65 … 42.45
LONS = [round(1.70 + 0.1 * j, 2) for j in range(18)]     # 1.70 … 3.40
HORES_MAPA = 96
HORES_PUNT = 168


def baixa(params, intents=4):
    for i in range(intents):
        try:
            r = requests.get(API, params=params, timeout=60)
            if r.status_code == 400:   # petició no vàlida per al model: no cal repetir-la
                raise ValueError(f"HTTP 400: {r.text[:200]}")
            if r.status_code == 429 or r.status_code >= 500:
                raise RuntimeError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except ValueError:
            raise
        except Exception as e:  # noqa: BLE001
            print(f"  intent {i + 1}: {e}")
            if i == intents - 1:
                raise
            time.sleep(15 * (i + 1))


def arrodoneix(v, dec):
    if v is None:
        return None
    return round(v, dec) if dec else int(round(v))


def index_ara(temps):
    """Índex de l'hora actual (hora local, arrodonida avall) dins la llista de temps."""
    ara = datetime.now(ZONA).strftime("%Y-%m-%dT%H:00")
    for i, t in enumerate(temps):
        if t >= ara:
            return i
    return len(temps)


def retalla_nuls(series, n):
    """Últim índex (exclusiu) on alguna sèrie té dada."""
    fi = 0
    for s in series:
        for i in range(min(n, len(s)) - 1, -1, -1):
            if s[i] is not None:
                fi = max(fi, i + 1)
                break
    return fi


def punt_bisbal():
    """Una sola consulta amb tots els models per al punt de la Bisbal."""
    ids = [m[0] for m in MODELS]
    j = baixa({
        "latitude": BISBAL[0], "longitude": BISBAL[1],
        "hourly": ",".join(v[0] for v in VARS_PUNT),
        "models": ",".join(ids), "timezone": "Europe/Madrid", "forecast_days": 8,
    })
    h = j["hourly"]
    i0 = index_ara(h["time"])
    temps = h["time"][i0:i0 + HORES_PUNT]
    sortida = {}
    for mid in ids:
        series = {}
        for nom, clau, dec in VARS_PUNT:
            s = h.get(f"{nom}_{mid}") or []
            series[clau] = [arrodoneix(x, dec) for x in s[i0:i0 + HORES_PUNT]]
        fi = retalla_nuls([series["t"], series["p"]], len(temps))
        if fi < 6:   # el model no arriba a la Bisbal
            print(f"  {mid}: sense dades a la Bisbal")
            continue
        sortida[mid] = {k: v[:fi] for k, v in series.items()}
        print(f"  {mid}: {fi} hores")
    return temps[0] if temps else None, sortida


def graella(mid):
    lats, lons = [], []
    for la in LATS:
        for lo in LONS:
            lats.append(la)
            lons.append(lo)
    params = {
        "latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)),
        "hourly": ",".join(v[0] for v in VARS_GRAELLA),
        "models": mid, "timezone": "Europe/Madrid", "forecast_days": 5,
    }
    try:
        j = baixa(params)
    except ValueError as e:
        # ICON-2I: el seu domini no cobreix tota la graella; queda només a la comparativa
        if "No data" in str(e):
            raise
        print(f"  {e}: es torna a provar amb 3 dies")
        params["forecast_days"] = 3
        j = baixa(params)
    if isinstance(j, dict):
        j = [j]
    temps = j[0]["hourly"]["time"]
    i0 = index_ara(temps)
    n = min(HORES_MAPA, len(temps) - i0)
    dades = {}
    for nom, clau, dec in VARS_GRAELLA:
        # [hora][punt]
        dades[clau] = [[arrodoneix(loc["hourly"][nom][i0 + h], dec) for loc in j] for h in range(n)]
    # fins on hi ha dades (els models regionals s'acaben abans)
    fi = 0
    for h in range(n):
        if any(x is not None for x in dades["t"][h]):
            fi = h + 1
    if fi < 3:
        raise RuntimeError("graella sense dades")
    return {
        "model": mid,
        "generat": datetime.now(ZONA).strftime("%Y-%m-%dT%H:%M"),
        "inici": temps[i0],
        "lats": LATS, "lons": LONS,
        "dades": {k: v[:fi] for k, v in dades.items()},
    }


def main():
    sortida = sys.argv[1] if len(sys.argv) > 1 else "sortida-models"
    os.makedirs(sortida, exist_ok=True)
    print("Punt de la Bisbal…")
    inici, bisbal = punt_bisbal()
    models = []
    for mid, nom, font, res, grup in MODELS:
        if mid not in bisbal:
            continue
        print(f"Graella {mid}…")
        fitxer = os.path.join(sortida, f"g_{mid}.json")
        te_graella = False
        try:
            g = graella(mid)
            with open(fitxer, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, separators=(",", ":"))
            te_graella = True
            print(f"  {len(g['dades']['t'])} hores")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR: {e}")
            te_graella = os.path.exists(fitxer)   # es queda la de l'última vegada
        models.append({"id": mid, "nom": nom, "font": font, "res": res, "grup": grup,
                       "graella": te_graella})
        time.sleep(25)   # Open-Meteo limita les consultes per minut (600)
    if not models:
        print("Cap model amb dades: no es toca res")
        sys.exit(1)
    index = {
        "generat": datetime.now(ZONA).strftime("%Y-%m-%dT%H:%M"),
        "inici": inici,
        "models": models,
        "bisbal": bisbal,
    }
    with open(os.path.join(sortida, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    # neteja graelles de models que ja no hi són
    vius = {f"g_{m['id']}.json" for m in models}
    for fit in os.listdir(sortida):
        if fit.startswith("g_") and fit not in vius:
            os.remove(os.path.join(sortida, fit))
    print(f"Fet: {len(models)} models")


if __name__ == "__main__":
    main()
