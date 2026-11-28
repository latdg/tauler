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
# 28.11.2026: index.json porta també
#   ens   les probabilitats per dies del conjunt ECMWF ENS (51 escenaris) a la Bisbal
#   sol   l'hora de sortida i de posta del sol de cada dia (per a l'índex de postes)
# i cada model hi afegeix l'energia per a tempestes (CAPE) i els núvols baixos, mitjans
# i alts; la graella del mapa porta també el CAPE (capa «Tempesta»).
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
API_ENS = "https://ensemble-api.open-meteo.com/v1/ensemble"
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
# 28.11.2026: variables noves. Si un model no en dona alguna, Open-Meteo la torna buida;
# si la petició fallés per culpa seva, es torna a fer sense (com abans).
EXTRA_PUNT = [("cape", "c", 0), ("cloud_cover_low", "nb", 0),
              ("cloud_cover_mid", "nm", 0), ("cloud_cover_high", "na", 0)]
EXTRA_GRAELLA = [("cape", "c", 0)]

# Graella del mapa: tota la província de Girona, cada 0,1° (uns 8-11 km).
# 24.11.2026: abans només el Baix Empordà (cada 0,06°). Són 162 punts per model:
# Open-Meteo els compta com 162 consultes, i per això es fa cada 6 hores i amb
# pauses entre models (límit gratuït: 600 per minut i 10.000 per dia).
LATS = [round(41.65 + 0.1 * i, 2) for i in range(9)]     # 41.65 … 42.45
LONS = [round(1.70 + 0.1 * j, 2) for j in range(18)]     # 1.70 … 3.40
HORES_MAPA = 96
HORES_PUNT = 168


def baixa(params, intents=4, url=API):
    for i in range(intents):
        try:
            r = requests.get(url, params=params, timeout=60)
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
    variables = VARS_PUNT + EXTRA_PUNT
    params = {
        "latitude": BISBAL[0], "longitude": BISBAL[1],
        "hourly": ",".join(v[0] for v in variables),
        "models": ",".join(ids), "timezone": "Europe/Madrid", "forecast_days": 8,
    }
    try:
        j = baixa(params)
    except ValueError as e:
        print(f"  {e}: es torna a provar sense les variables noves")
        variables = VARS_PUNT
        params["hourly"] = ",".join(v[0] for v in variables)
        j = baixa(params)
    h = j["hourly"]
    i0 = index_ara(h["time"])
    temps = h["time"][i0:i0 + HORES_PUNT]
    sortida = {}
    for mid in ids:
        series = {}
        for nom, clau, dec in variables:
            s = h.get(f"{nom}_{mid}") or []
            series[clau] = [arrodoneix(x, dec) for x in s[i0:i0 + HORES_PUNT]]
        fi = retalla_nuls([series["t"], series["p"]], len(temps))
        if fi < 6:   # el model no arriba a la Bisbal
            print(f"  {mid}: sense dades a la Bisbal")
            continue
        # les variables noves que el model no dona no s'hi desen (la pàgina ho entén)
        sortida[mid] = {k: v[:fi] for k, v in series.items()
                        if k in ("t", "p", "v", "n", "r") or any(x is not None for x in v[:fi])}
        print(f"  {mid}: {fi} hores")
    return temps[0] if temps else None, sortida


def graella(mid):
    try:
        return graella_amb(mid, VARS_GRAELLA + EXTRA_GRAELLA)
    except ValueError as e:
        if "No data" in str(e):
            raise
        print(f"  {e}: es torna a provar sense el CAPE")
        return graella_amb(mid, VARS_GRAELLA)


def graella_amb(mid, variables):
    lats, lons = [], []
    for la in LATS:
        for lo in LONS:
            lats.append(la)
            lons.append(lo)
    params = {
        "latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)),
        "hourly": ",".join(v[0] for v in variables),
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
    for nom, clau, dec in variables:
        # [hora][punt]
        dades[clau] = [[arrodoneix((loc["hourly"].get(nom) or [None] * (i0 + n))[i0 + h], dec) for loc in j] for h in range(n)]
    # el CAPE, només si el model en dona
    if "c" in dades and not any(x is not None for fila in dades["c"] for x in fila):
        del dades["c"]
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


def percentil(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    a, b = int(k), min(int(k) + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (k - a)


def membres(h, nom):
    """Les sèries de tots els escenaris d'una variable (control + «_memberNN»)."""
    return [s for k, s in h.items() if k == nom or k.startswith(nom + "_member")]


def ens_bisbal():
    """28.11.2026: probabilitats per dies del conjunt ECMWF ENS (51 escenaris) a la Bisbal.
    Cada variable es demana a part: si n'hi ha alguna que el conjunt no dona, la resta hi és igualment."""
    series, temps = {}, None
    for nom in ("precipitation", "temperature_2m", "wind_gusts_10m"):
        try:
            j = baixa({"latitude": BISBAL[0], "longitude": BISBAL[1], "hourly": nom,
                       "models": "ecmwf_ifs025", "timezone": "Europe/Madrid", "forecast_days": 8}, url=API_ENS)
            h = j["hourly"]
            m = [s for s in membres(h, nom) if any(x is not None for x in s)]
            if m:
                series[nom], temps = m, h["time"]
                print(f"  ENS {nom}: {len(m)} escenaris")
        except Exception as e:  # noqa: BLE001
            print(f"  ENS {nom}: {e}")
        time.sleep(3)
    if "precipitation" not in series or not temps:
        return None
    i0 = index_ara(temps)
    dies = {}
    for i in range(i0, len(temps)):
        dies.setdefault(temps[i][:10], []).append(i)
    claus = list(dies)
    sortida = []
    for n_dia, d in enumerate(claus):
        hores = dies[d]
        if n_dia > 0 and len(hores) < 24:
            continue
        pct = lambda vals, cond: round(100 * sum(1 for v in vals if cond(v)) / len(vals)) if vals else None
        # pluja de cada escenari al dia (només els escenaris amb dades a totes les hores)
        pl = [sum(s[i] for i in hores) for s in series["precipitation"] if all(s[i] is not None for i in hores)]
        if not pl:
            continue
        fila = {"d": d, "n": len(pl), "resta": n_dia == 0 and len(hores) < 24,
                "p1": pct(pl, lambda v: v >= 1), "p10": pct(pl, lambda v: v >= 10),
                "pmed": round(percentil(pl, .5), 1), "p90": round(percentil(pl, .9), 1)}
        rx = [max(s[i] for i in hores) for s in series.get("wind_gusts_10m", []) if all(s[i] is not None for i in hores)]
        fila["r50"] = pct(rx, lambda v: v >= 50)
        fila["r70"] = pct(rx, lambda v: v >= 70)
        mn = [min(s[i] for i in hores) for s in series.get("temperature_2m", []) if all(s[i] is not None for i in hores)]
        fila["g0"] = pct(mn, lambda v: v < 0)
        sortida.append(fila)
    return {"model": "ECMWF ENS", "membres": len(series["precipitation"]), "dies": sortida} if sortida else None


def sol_bisbal():
    """28.11.2026: hora de sortida i de posta del sol a la Bisbal (8 dies)."""
    j = baixa({"latitude": BISBAL[0], "longitude": BISBAL[1], "daily": "sunrise,sunset",
               "timezone": "Europe/Madrid", "forecast_days": 8})
    d = j["daily"]
    return [{"d": t, "surt": s[11:16], "pon": p[11:16]} for t, s, p in zip(d["time"], d["sunrise"], d["sunset"])]


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
    # 28.11.2026: si el conjunt ENS o el sol fallen, la resta de la pàgina va igual
    print("Conjunt ECMWF ENS…")
    try:
        ens = ens_bisbal()
        if ens:
            index["ens"] = ens
            print(f"  {len(ens['dies'])} dies")
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR: {e}")
    try:
        index["sol"] = sol_bisbal()
    except Exception as e:  # noqa: BLE001
        print(f"  sol: ERROR: {e}")
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
