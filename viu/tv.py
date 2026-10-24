#!/usr/bin/env python3
# =============================================================================
# TV.JSON PER A LA PANTALLA D'INICI DE LA TV — 24.10.2026
#
# Pas nou del bucle «Tauler en directe» (tauler-viu.yml), just després de
# fusiona i d'esports. Escriu tv.json a l'arrel del repo, que GitHub Pages
# publica a https://latdg.github.io/tauler/tv.json. Fitxer petit (pocs KB).
#
#   python viu/tv.py
#
# Només llegeix: dades/darrer.json (UV màxim, Pla Alfa, trànsit), dades/agenda.json
# i el resum publicat de La TdG redacció (premsa local de les últimes 48 h).
# La temperatura, la previsió d'avui i demà i l'UV de l'hora actual són
# d'Open-Meteo, amb les mateixes coordenades que el tauler.
# No toca cap altre fitxer ni cap funció de tauler_viu.py.
#
# Avisos: de moment, Pla Alfa (nivell 1 o més) i trànsit (incidències del SCT).
# El riu Daró no en dona cap: el tauler no té llindar d'avís per al riu.
# Meteocat i Protecció Civil, més endavant.
#
# Si una font falla, es manté el que ja hi havia al tv.json anterior.
# =============================================================================

import datetime as dt
import html
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Madrid")
ARREL = Path(__file__).resolve().parent.parent
DADES = ARREL / "dades"
SORTIDA = ARREL / "tv.json"
CAPCALERES = {"User-Agent": "LaTdG-tauler/1.0 (+https://latdg.github.io/tauler/)"}
BISBAL = (41.9597, 3.0386)
REDACCIO = "https://latdg.github.io/redaccio/dades"

MAX_ACTES = 3
MAX_TITULARS = 10
MAX_TRANSIT = 5

# Codis WMO d'Open-Meteo
CEL = {
    0: "cel serè", 1: "gairebé serè", 2: "mig ennuvolat", 3: "ennuvolat",
    45: "boira", 48: "boira gebradora",
    51: "plugim feble", 53: "plugim", 55: "plugim intens",
    56: "plugim gelat", 57: "plugim gelat",
    61: "pluja feble", 63: "pluja", 65: "pluja forta",
    66: "pluja gelada", 67: "pluja gelada",
    71: "neu feble", 73: "neu", 75: "neu forta", 77: "neu granulada",
    80: "ruixats febles", 81: "ruixats", 82: "ruixats forts",
    85: "ruixats de neu", 86: "ruixats de neu forts",
    95: "tempesta", 96: "tempesta amb calamarsa", 99: "tempesta amb calamarsa",
}


def ara():
    return dt.datetime.now(TZ)


def data_ca(iso):
    """2026-10-24 -> 24.10.2026"""
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def llegeix(cami, defecte):
    try:
        return json.loads(Path(cami).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecte


def categoria_uv(v):
    # Els mateixos llindars que categoria_uv() del tauler
    if v < 3:
        return "baix"
    if v < 6:
        return "moderat"
    if v < 8:
        return "alt"
    if v < 11:
        return "molt alt"
    return "extrem"


def arrodoneix(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


# -----------------------------------------------------------------------------
# TEMPS: Open-Meteo (temperatura, previsió, UV actual) + UV màxim del tauler
# -----------------------------------------------------------------------------
def temps(blocs):
    r = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": BISBAL[0], "longitude": BISBAL[1], "timezone": "Europe/Madrid",
        "current": "temperature_2m,weather_code,uv_index",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,uv_index_max",
        "forecast_days": 2,
    }, headers=CAPCALERES, timeout=30)
    r.raise_for_status()
    d = r.json()
    actual = d.get("current") or {}
    dia = d.get("daily") or {}

    previsio = []
    for i, iso in enumerate(dia.get("time") or []):
        def camp(nom):
            valors = dia.get(nom) or []
            return valors[i] if i < len(valors) else None
        tmax, tmin, codi = camp("temperature_2m_max"), camp("temperature_2m_min"), camp("weather_code")
        pluja = camp("precipitation_probability_max")
        previsio.append({
            "dia": "avui" if i == 0 else "demà",
            "data": data_ca(iso),
            "cel": CEL.get(codi, ""),
            "max": arrodoneix(tmax) if tmax is not None else None,
            "min": arrodoneix(tmin) if tmin is not None else None,
            "pluja": pluja,                       # probabilitat màxima, %
        })

    uv_ara = actual.get("uv_index")
    uv_ara = arrodoneix(uv_ara) if uv_ara is not None else None
    # UV màxim del dia: el que ja calcula el tauler (bloc uv de darrer.json)
    uv_tauler = blocs.get("uv") or {}
    uv_max = uv_tauler.get("valor")
    if uv_max is None:
        valors = dia.get("uv_index_max") or [None]
        uv_max = arrodoneix(valors[0]) if valors[0] is not None else None

    t = actual.get("temperature_2m")
    return {
        "temperatura": round(t, 1) if t is not None else None,
        "cel": CEL.get(actual.get("weather_code"), ""),
        "previsio": previsio,
        "uv": {
            "ara": uv_ara,
            "araCategoria": categoria_uv(uv_ara) if uv_ara is not None else None,
            "max": uv_max,
            "maxCategoria": uv_tauler.get("categoria") or (categoria_uv(uv_max) if uv_max is not None else None),
        },
    }


# -----------------------------------------------------------------------------
# AGENDA: actes d'avui i demà de dades/agenda.json (màxim 3)
# -----------------------------------------------------------------------------
def agenda():
    avui = ara().date()
    dies = {avui.isoformat(): "avui", (avui + dt.timedelta(days=1)).isoformat(): "demà"}
    actes = llegeix(DADES / "agenda.json", {}).get("actes") or []

    def clau(a):
        h = re.match(r"(\d{1,2})[.:](\d{2})", str(a.get("hora") or ""))
        return (a.get("data") or "", (int(h.group(1)), int(h.group(2))) if h else (99, 99))

    # Els d'avui que ja han començat no hi surten; els que no tenen hora, sí
    hora_ara = (ara().hour, ara().minute)
    vigents = [a for a in actes if a.get("data") in dies
               and not (a["data"] == avui.isoformat() and clau(a)[1] != (99, 99) and clau(a)[1] < hora_ara)]
    triats = sorted(vigents, key=clau)[:MAX_ACTES]
    return [{
        "dia": dies[a["data"]],
        "data": data_ca(a["data"]),
        "hora": a.get("hora") or "",
        "municipi": a.get("municipi") or "",
        "text": a.get("text") or "",
    } for a in triats]


# -----------------------------------------------------------------------------
# AVISOS ACTIUS: Pla Alfa (nivell 1 o més) i trànsit
# -----------------------------------------------------------------------------
def avisos(blocs):
    resultat = []
    pla = str(blocs.get("plaAlfa") or "")
    for tros in pla.split("|"):
        m = re.match(r"\s*(.+?):\s*nivell\s+(\d+)\s*(?:\((.*)\))?", tros)
        if m and int(m.group(2)) >= 1:
            resultat.append({
                "tipus": "plaAlfa",
                "nivell": int(m.group(2)),
                "text": f"Pla Alfa nivell {m.group(2)} a {m.group(1).strip()}"
                        + (f" ({m.group(3).strip()})" if m.group(3) else ""),
            })
    for inc in (blocs.get("incidencies") or [])[:MAX_TRANSIT]:
        lloc = inc.get("carretera") or ""
        if inc.get("km"):
            lloc += f", km {inc['km']}"
        resultat.append({
            "tipus": "transit",
            "text": f"{inc.get('titol') or ''} — {lloc} ({inc.get('municipi') or ''})".strip(),
        })
    return resultat


# -----------------------------------------------------------------------------
# TITULARS: «Premsa local (últimes 48 hores)» del resum publicat de La TdG redacció
# -----------------------------------------------------------------------------
def titulars():
    dies = requests.get(f"{REDACCIO}/dies.json", headers=CAPCALERES, timeout=30)
    dies.raise_for_status()
    dia = (dies.json() or [None])[0]
    if not dia or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dia):
        raise ValueError("dies.json de redacció sense cap dia")
    r = requests.get(f"{REDACCIO}/{dia}/resum.html", headers=CAPCALERES, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    text = r.text
    inici = text.find("Premsa local (últimes 48 hores)")
    if inici < 0:
        raise ValueError("el resum no té la secció de premsa local")
    fi = text.find("<div", inici)
    seccio = text[inici:fi if fi > 0 else None]

    limit = ara().date() - dt.timedelta(days=2)
    vistos, resultat = set(), []
    for m in re.finditer(r"•\s*(\d{2})\.(\d{2})\.(\d{4})\s*—\s*(.+?)<br>", seccio):
        dd, mm, aaaa, titol = m.groups()
        if dt.date(int(aaaa), int(mm), int(dd)) < limit:
            continue
        titol = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", titol))).strip()
        if titol and titol.lower() not in vistos:
            vistos.add(titol.lower())
            resultat.append(titol)
        if len(resultat) >= MAX_TITULARS:
            break
    return resultat


def main():
    anterior = llegeix(SORTIDA, {})
    blocs = llegeix(DADES / "darrer.json", {}).get("blocs") or {}
    sortida = {}
    for nom, funcio in (("temps", lambda: temps(blocs)), ("agenda", agenda),
                        ("avisos", lambda: avisos(blocs)), ("titulars", titulars)):
        try:
            sortida[nom] = funcio()
        except Exception as e:  # es manté el valor anterior
            print(f"tv.json: {nom}: {e}")
            sortida[nom] = anterior.get(nom, [] if nom != "temps" else {})
    sortida["actualitzat"] = ara().strftime("%d.%m.%Y %H.%M")
    SORTIDA.write_text(json.dumps(sortida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"tv.json: {SORTIDA.stat().st_size} bytes")


if __name__ == "__main__":
    main()
