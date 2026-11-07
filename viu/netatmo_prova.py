"""Passada de comprovació de les estacions de Netatmo (07.11.2026).

Llegeix les estacions públiques de Netatmo al voltant de la Bisbal i desa a
dades/pluja/netatmo-prova.json la posició exacta, l'altitud i la pluja de les set
estacions triades, més les altres de la zona, per comparar-les amb Meteoclimàtic.
No escriu cap clau: només diu si Netatmo ha canviat el refresh token.
"""
import json, os, sys, datetime as dt
from pathlib import Path
import requests

TRIADES = {
    "70:ee:50:05:f3:92": "Cruïlles, Monells i Sant Sadurní de l'Heura",
    "70:ee:50:b9:6f:42": "Canapost",
    "70:ee:50:15:e6:f0": "les Gavarres",
    "70:ee:50:a4:31:ca": "la Bisbal (1)",
    "70:ee:50:83:9e:10": "la Bisbal (2)",
    "70:ee:50:71:41:72": "la Bisbal (3)",
    "70:ee:50:83:77:32": "la Bisbal (4)",
}
CAIXA = {"lat_ne": 42.03, "lon_ne": 3.13, "lat_sw": 41.86, "lon_sw": 2.94}

refresh = os.environ["NETATMO_REFRESH_TOKEN"].strip()
r = requests.post("https://api.netatmo.com/oauth2/token", data={
    "grant_type": "refresh_token", "refresh_token": refresh,
    "client_id": os.environ["NETATMO_CLIENT_ID"].strip(),
    "client_secret": os.environ["NETATMO_CLIENT_SECRET"].strip()}, timeout=30)
if r.status_code != 200:
    sys.exit(f"Token: HTTP {r.status_code} {r.text[:200]}")
tok = r.json()
canviat = tok.get("refresh_token") != refresh
print("Refresh token canviat:", canviat)

r = requests.get("https://api.netatmo.com/api/getpublicdata",
                 params={**CAIXA, "filter": "false"},
                 headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=60)
if r.status_code != 200:
    sys.exit(f"getpublicdata: HTTP {r.status_code} {r.text[:200]}")
estacions = []
for e in r.json().get("body", []):
    pl = e.get("place") or {}
    loc = pl.get("location") or [None, None]
    pluja = {}
    for mod, m in (e.get("measures") or {}).items():
        if "rain_24h" in m or "rain_60min" in m:
            pluja = {k: m.get(k) for k in ("rain_60min", "rain_24h", "rain_live", "rain_timeutc")}
            if pluja.get("rain_timeutc"):
                pluja["hora"] = dt.datetime.fromtimestamp(pluja["rain_timeutc"], dt.timezone.utc).isoformat()
    estacions.append({"id": e.get("_id"), "triada": TRIADES.get(e.get("_id")),
                      "lat": loc[1], "lon": loc[0], "alt": pl.get("altitude"),
                      "poble": pl.get("city"), "carrer": pl.get("street"),
                      "te_pluviometre": bool(pluja), "pluja": pluja})
estacions.sort(key=lambda x: (x["triada"] is None, x["triada"] or "", x["id"] or ""))
falten = [n for i, n in TRIADES.items() if i not in {x["id"] for x in estacions}]
sortida = {"consultat": dt.datetime.now(dt.timezone.utc).isoformat(), "refresh_canviat": canviat,
           "no_trobades": falten, "estacions": estacions}
cami = Path("dades/pluja/netatmo-prova.json")
cami.parent.mkdir(parents=True, exist_ok=True)
cami.write_text(json.dumps(sortida, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(estacions)} estacions a la zona; no trobades: {falten}")
