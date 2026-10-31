#!/usr/bin/env python3
# =============================================================================
# TAULER «LA TdG AMPLIADA» EN DIRECTE — 21.10.2026
#
# Corre a GitHub Actions (repo públic latdg/tauler, sense límit de minuts)
# cada 15 minuts. Calcula els blocs que no depenen de Google Sheets i els
# fusiona amb els que publica l'Apps Script (LaTdGampliada.gs):
#
#   python viu/tauler_viu.py calcula   -> consulta les fonts i ho desa a /tmp
#   python viu/tauler_viu.py fusiona   -> barreja amb dades/darrer.json i escriu
#                                         darrer.json, AAAA-MM-DD.json i dies.json
#
# FASE 1: piezòmetres (10,6 km), carburants i índex UV.
# FASE 3 (21.10.2026): l'aviació no comercial, del registre del vigilant d'aeronaus a GitHub.
# FASE 2 (21.10.2026): trànsit (incidències del SCT), riu Daró (directament de
#   l'ACA, sense passar pel Google Sheet), qualitat de l'aire prevista i el
#   clima en context (Open-Meteo). El clima només es calcula un cop al dia,
#   perquè la reanàlisi ERA5 canvia d'un dia per l'altre.
#
# Els darrers valors bons es guarden a dades/viu.json: així, encara que
# l'Apps Script sobreescrigui darrer.json sense aquests blocs, es tornen a
# posar a cada execució. Si una font falla, es manté el valor que ja hi havia.
# =============================================================================

import calendar
import html
import json
import math
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Madrid")
ARREL = Path(__file__).resolve().parent.parent
DADES = ARREL / "dades"
TMP = Path("/tmp/tauler_viu.json")
MEMORIA = DADES / "viu.json"          # darrers valors bons dels blocs vius
CAPCALERES = {
    "User-Agent": "LaTdG-tauler/1.0 (+https://latdg.github.io/tauler/)",
    "Accept": "application/json",
}

BISBAL = (41.9597, 3.0386)


def num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def arrodoneix(x):
    """Com Math.round de JavaScript (les meitats, cap amunt)."""
    return int(math.floor(x + 0.5))


def coma(x, decimals):
    return f"{x:.{decimals}f}".replace(".", ",")


def ara():
    return dt.datetime.now(TZ)


# -----------------------------------------------------------------------------
# PIEZÒMETRES (port de PIEZOMETRES.js, radi 10,6 km)
# -----------------------------------------------------------------------------
PIEZO_URL = "https://analisi.transparenciacatalunya.cat/resource/6899-hrme.json"
PIEZO_RADI_KM = 10.6
PIEZO_DIES = 800
PIEZO_TOLERANCIA_ANY = 60


def distancia_km(lat1, lon1, lat2, lon2):
    rad = math.pi / 180
    dlat, dlon = (lat2 - lat1) * rad, (lon2 - lon1) * rad
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(dlon / 2) ** 2)
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def piezometres():
    inici = (ara() - dt.timedelta(days=PIEZO_DIES)).strftime("%Y-%m-%d")
    dlat = PIEZO_RADI_KM / 111.32
    dlon = PIEZO_RADI_KM / (111.32 * math.cos(BISBAL[0] * math.pi / 180))
    where = (f"data >= '{inici}T00:00:00'"
             f" AND latitud between {BISBAL[0] - dlat:.5f} and {BISBAL[0] + dlat:.5f}"
             f" AND longitud between {BISBAL[1] - dlon:.5f} and {BISBAL[1] + dlon:.5f}")
    params = {
        "$select": "data,codi_estaci,estaci,massa_d_aigua,municipi,"
                   "cota_del_nivell_piezom_tric,fond_ria_aigua_m,latitud,longitud",
        "$where": where,
        "$order": "data ASC",
        "$limit": "50000",
    }
    r = requests.get(PIEZO_URL, params=params, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    files = r.json()
    if not isinstance(files, list):
        raise ValueError("la resposta no és una llista de mesures")

    per_codi = {}
    for f in files:
        codi = str(f.get("codi_estaci") or "").strip()
        data = str(f.get("data") or "")[:10]
        cota = num(f.get("cota_del_nivell_piezom_tric"))
        lat, lon = num(f.get("latitud")), num(f.get("longitud"))
        if not codi or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data) or None in (cota, lat, lon):
            continue
        d = distancia_km(BISBAL[0], BISBAL[1], lat, lon)
        if d > PIEZO_RADI_KM:
            continue
        e = per_codi.setdefault(codi, {
            "nom": str(f.get("estaci") or codi).strip(),
            "municipi": str(f.get("municipi") or "").strip(),
            "massa": str(f.get("massa_d_aigua") or "").strip(),
            "distancia": round(d, 1),
            "lat": lat, "lon": lon,
            "perData": {},
        })
        # Si un dia té més d'una mesura, es queda la darrera.
        e["perData"][data] = {"data": data, "cota": cota, "fondaria": num(f.get("fond_ria_aigua_m"))}

    estacions = []
    for e in per_codi.values():
        mesures = [e["perData"][k] for k in sorted(e["perData"])]
        if not mesures:
            continue
        darrera = mesures[-1]
        anterior = mesures[-2] if len(mesures) >= 2 else None

        objectiu = dt.date.fromisoformat(darrera["data"]) - dt.timedelta(days=365)
        fa_un_any, millor = None, math.inf
        for m in mesures[:-1]:
            dif = abs((dt.date.fromisoformat(m["data"]) - objectiu).days)
            if dif <= PIEZO_TOLERANCIA_ANY and dif < millor:
                fa_un_any, millor = m, dif

        estacions.append({
            "nom": e["nom"], "municipi": e["municipi"], "massa": e["massa"],
            "distancia": e["distancia"], "lat": e["lat"], "lon": e["lon"],
            "data": darrera["data"], "cota": darrera["cota"], "fondaria": darrera["fondaria"],
            "dataAnterior": anterior["data"] if anterior else None,
            "varAnterior": round(darrera["cota"] - anterior["cota"], 2) if anterior else None,
            "dataFaUnAny": fa_un_any["data"] if fa_un_any else None,
            "varFaUnAny": round(darrera["cota"] - fa_un_any["cota"], 2) if fa_un_any else None,
        })

    estacions.sort(key=lambda x: x["distancia"])
    return {"radi": PIEZO_RADI_KM, "estacions": estacions} if estacions else None


# -----------------------------------------------------------------------------
# CARBURANTS (port de taulerCarburants_)
# -----------------------------------------------------------------------------
CARBURANTS_URL = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
                  "PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/17")
CARBURANTS_MUNICIPIS = re.compile(r"bisbal|corca|forallac|cruilles|ullastret")
CARBURANTS_C66 = re.compile(r"celra|bordils|juia|sant marti vell|palafrugell|mont-ras|montras|regencos|begur|\bpera\b")
CARBURANTS_NOMS = [
    ("Gasolina 95 E5", "Gasolina 95"),
    ("Gasolina 95 E5 Premium", "Gasolina 95 prèmium"),
    ("Gasolina 95 E10", "Gasolina 95 E10"),
    ("Gasolina 98 E5", "Gasolina 98"),
    ("Gasolina 98 E10", "Gasolina 98 E10"),
    ("Gasolina Renovable", "Gasolina renovable"),
    ("Gasoleo A", "Gasoil A"),
    ("Gasoleo Premium", "Gasoil prèmium"),
    ("Gasoleo B", "Gasoil B (agrícola)"),
    ("Diesel Renovable", "Dièsel renovable"),
    ("Biodiesel", "Biodièsel"),
    ("Bioetanol", "Bioetanol"),
    ("Gases licuados del petroleo", "GLP (autogàs)"),
    ("Gas Natural Comprimido", "Gas natural comprimit (GNC)"),
    ("Gas Natural Licuado", "Gas natural liquat (GNL)"),
    ("Hidrogeno", "Hidrogen"),
    ("Adblue", "AdBlue"),
]
PETITES = {"de", "del", "dels", "la", "les", "el", "els", "i", "y", "a"}


def norm(s):
    t = unicodedata.normalize("NFD", str(s or ""))
    t = "".join(c for c in t if not ("̀" <= c <= "ͯ"))
    return re.sub(r"\s+", " ", t).lower().strip()


def text_bonic(s):
    t = re.sub(r"\s+", " ", str(s or "")).strip()
    art = re.match(r"^(.*)\s+\((LA|EL|LES|ELS|L')\)$", t, re.I)
    if art:
        t = art.group(2) + ("" if art.group(2).endswith("'") else " ") + art.group(1)
    sortida = []
    for i, w in enumerate(t.lower().split(" ")):
        if re.match(r"^[dl]'", w):
            sortida.append((w[0].upper() if i == 0 else w[0]) + "'" + w[2:3].upper() + w[3:])
        elif i > 0 and w in PETITES:
            sortida.append(w)
        else:
            sortida.append(w[:1].upper() + w[1:])
    return " ".join(sortida)


def carburants():
    r = requests.get(CARBURANTS_URL, headers=CAPCALERES, timeout=120)
    r.raise_for_status()
    dades = r.json()
    llista = dades.get("ListaEESSPrecio")
    if not isinstance(llista, list):
        raise ValueError("la resposta no porta la llista de benzineres")

    estacions = []
    for e in llista:
        m = norm(e.get("Municipio"))
        local = bool(CARBURANTS_MUNICIPIS.search(m))
        if local or CARBURANTS_C66.search(m):
            estacions.append({"e": e, "lat": num(e.get("Latitud")),
                              "lon": num(e.get("Longitud (WGS84)")), "local": local})
    if not estacions:
        return None

    # Seguint la carretera, d'oest (Celrà) a est (Palafrugell).
    estacions.sort(key=lambda x: x["lon"] or 0)

    camps = {k for x in estacions for k in x["e"]
             if k.startswith("Precio ") and num(x["e"][k]) is not None}
    ordre = [norm(a) for a, _ in CARBURANTS_NOMS]

    def posicio(k):
        b = norm(k.replace("Precio ", "", 1))
        return ordre.index(b) if b in ordre else 999

    llista_camps = sorted(camps, key=lambda k: (posicio(k), k))
    carburants_ = []
    for k in llista_camps:
        i = posicio(k)
        carburants_.append({
            "nom": CARBURANTS_NOMS[i][1] if i != 999 else k.replace("Precio ", "", 1),
            "preus": [num(x["e"].get(k)) for x in estacions],
        })

    f = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})", str(dades.get("Fecha") or ""))
    data = (f"{int(f[1]):02d}.{int(f[2]):02d}.{f[3]} a les {int(f[4]):02d}.{f[5]} h") if f else ""

    def nom_rotul(x):
        rotul = str(x["e"].get("Rótulo") or "").strip()
        return rotul.upper() if len(rotul) <= 4 else text_bonic(rotul)

    return {
        "data": data,
        "estacions": [{
            "nom": nom_rotul(x),
            "municipi": text_bonic(x["e"].get("Municipio")),
            "adreca": text_bonic(x["e"].get("Dirección")),
            "horari": str(x["e"].get("Horario") or "").strip(),
            "lat": x["lat"], "lon": x["lon"], "local": x["local"],
        } for x in estacions],
        "carburants": carburants_,
    }


# -----------------------------------------------------------------------------
# TRÀNSIT (FASE 2): incidències del Servei Català de Trànsit al Baix Empordà.
# Port d'obtenirDadesIncidenciesViaries() del guió (mateix canal RSS i filtre).
# -----------------------------------------------------------------------------
TRANSIT_URL = "http://www.gencat.cat/transit/opendata/incidenciesRSS.xml"
MUNICIPIS_BAIX_EMPORDA = [
    "Albons", "Begur", "Bellcaire d'Empordà", "Bisbal d'Empordà", "Calonge",
    "Sant Antoni", "Castell-Platja d'Aro", "Castell d'Aro", "Colomers", "Corçà",
    "Cruïlles", "Monells", "Sant Sadurní de l'Heura", "Foixà", "Fontanilles",
    "Forallac", "Garrigoles", "Gualta", "Jafre", "Mont-ras", "Palafrugell",
    "Palamós", "Palau-sator", "Pals", "Parlavà", "La Pera", "Regencós", "Rupià",
    "Sant Feliu de Guíxols", "Santa Cristina d'Aro", "Serra de Daró",
    "Tallada d'Empordà", "Torrent", "Torroella de Montgrí", "Ullastret", "Ullà",
    "Ultramort", "Vall-llobrega", "Verges", "Vilopriu",
]


def norm_be(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    t = "".join(c for c in t if not ("̀" <= c <= "ͯ"))
    return re.sub(r"[‘’`´']", "'", t)


PATRONS_BAIX_EMPORDA = [(norm_be(m), re.compile(r"\b" + re.escape(norm_be(m)) + r"\b"))
                        for m in MUNICIPIS_BAIX_EMPORDA]


def te_municipi_baix_emporda(text):
    net = norm_be(text)
    for nom, patro in PATRONS_BAIX_EMPORDA:
        if not patro.search(net):
            continue
        if nom == "calonge" and "calonge de segarra" in net:
            continue
        return True
    return False


def neteja_text(t):
    t = re.sub(r"<[^>]+>", " ", str(t or ""))
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def llegeix_rss(contingut):
    fi = contingut.rfind(b"</rss>")
    if fi != -1:
        contingut = contingut[:fi + 6]
    try:
        arrel = ET.fromstring(contingut)
        canal = arrel.find("channel")
        canal = canal if canal is not None else arrel
        return [{"title": it.findtext("title") or "", "description": it.findtext("description") or ""}
                for it in canal.findall("item")]
    except ET.ParseError:
        # Com al guió: si l'XML està mal format, es llegeix element a element.
        text = contingut.decode("utf-8", errors="replace")

        def camp(bloc, nom):
            m = re.search(rf"<{nom}\b[^>]*>([\s\S]*?)</{nom}>", bloc, re.I)
            if not m:
                return ""
            return re.sub(r"\]\]>\s*$", "", re.sub(r"^\s*<!\[CDATA\[", "", m.group(1))).strip()

        return [{"title": camp(b, "title"), "description": camp(b, "description")}
                for b in re.findall(r"<item\b[^>]*>([\s\S]*?)</item>", text, re.I)]


def incidencies():
    r = requests.get(TRANSIT_URL, headers={**CAPCALERES, "Accept": "application/rss+xml, application/xml"},
                     timeout=60)
    r.raise_for_status()
    resultat = []
    for item in llegeix_rss(r.content):
        if not te_municipi_baix_emporda(item["title"] + " " + item["description"]):
            continue
        # "CARRETERA | MUNICIPI | Sentit... | Punt km. X-Y | HH:MM"
        parts = [p.strip() for p in neteja_text(item["description"]).split("|")]
        parts += [""] * (5 - len(parts))
        resultat.append({
            "municipi": parts[1],
            "titol": neteja_text(item["title"]),
            "carretera": parts[0],
            "km": re.sub(r"^Punt km\.?\s*", "", parts[3], flags=re.I),
            "sentit": parts[2],
        })
    return resultat   # una llista buida també és una dada: «cap incidència»


# -----------------------------------------------------------------------------
# RIU DARÓ (FASE 2): directament de l'ACA (estació 170221-002, la Bisbal),
# sense passar pel Google Sheet. Mitjana de cada hora de les darreres 12 h.
# -----------------------------------------------------------------------------
RIU_ESTACIO = "170221-002"
RIU_SENSOR_NIVELL = "170221-002-ANA001"   # cm
RIU_SENSOR_CABAL = "CALC001204"           # m³/s
RIU_URL = f"https://aplicacions.aca.gencat.cat/aetr/vishid/v2/chart/public/rivergauges/{RIU_ESTACIO}"


def data_aca(t):
    """Marca de temps de l'ACA -> hora de Madrid."""
    s = str(t).strip()
    if re.fullmatch(r"\d{12,13}", s):                       # mil·lisegons
        return dt.datetime.fromtimestamp(int(s) / (1000 if len(s) == 13 else 1), TZ)
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d.astimezone(TZ) if d.tzinfo else d.replace(tzinfo=TZ)


def riu():
    fi = dt.datetime.now(dt.timezone.utc)
    inici = fi - dt.timedelta(hours=26)   # 21.10.2026: 26 h, perquè el registre horari no perdi cap hora
    formata = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    r = requests.get(RIU_URL, params={"from": formata(inici), "to": formata(fi)},
                     headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    dades = r.json()

    def serie(sensor):
        sortida = []
        for t, v in (dades.get(sensor) or {}).items():
            valor = num(v)
            if valor is None:
                continue
            try:
                sortida.append((data_aca(t), valor))
            except ValueError:
                continue
        return sorted(sortida)

    nivell, cabal = serie(RIU_SENSOR_NIVELL), serie(RIU_SENSOR_CABAL)
    if not nivell and not cabal:
        raise ValueError("l'ACA no ha retornat cap lectura")

    # Mitjana per hora (la més recent primer, com feia el guió).
    hores = {}
    for clau, llista in (("cabal", cabal), ("nivell", nivell)):
        for moment, valor in llista:
            h = moment.replace(minute=0, second=0, microsecond=0)
            hores.setdefault(h, {"cabal": [], "nivell": []})[clau].append(valor)
    mitjana = lambda v: round(sum(v) / len(v), 3) if v else None
    ordenades = sorted(hores, reverse=True)[:12]   # el tauler continua mostrant les 12 darreres
    llista_hores = [{"hora": h.strftime("%H.00 h"),
                     "cabal": mitjana(hores[h]["cabal"]),
                     "nivell": mitjana(hores[h]["nivell"])} for h in ordenades]

    # Text: la darrera lectura.
    darrer = max(nivell[-1:] + cabal[-1:], key=lambda x: x[0])[0]
    quan = f"A les {darrer.strftime('%H.%M')} h d'avui" if darrer.date() == ara().date() \
        else f"El {darrer.strftime('%d.%m.%Y')} a les {darrer.strftime('%H.%M')} h"
    trossos = []
    if cabal:
        trossos.append(f"un cabal de {coma(cabal[-1][1], 3)} m³/s")
    if nivell:
        cm = nivell[-1][1]
        trossos.append(f"un nivell de {coma(cm, 0) if cm == int(cm) else coma(cm, 1)} cm ({coma(cm / 100, 2)} m)")
    text = f"{quan} el riu Daró porta {' i '.join(trossos)}."

    # 21.10.2026: totes les hores amb lectures (mitjana i màxim), per al registre
    # horari del riu (dades/riu/AAAA-MM-DD.json). No va al tauler.
    maxim = lambda v: round(max(v), 3) if v else None
    historic = [{"dia": h.strftime("%Y-%m-%d"), "hora": h.strftime("%H.00"),
                 "cabal": mitjana(hores[h]["cabal"]), "cabalMax": maxim(hores[h]["cabal"]),
                 "nivell": mitjana(hores[h]["nivell"]), "nivellMax": maxim(hores[h]["nivell"]),
                 "lectures": max(len(hores[h]["cabal"]), len(hores[h]["nivell"]))} for h in sorted(hores)]

    return {"text": text, "hores": llista_hores, "_historic": historic}


# -----------------------------------------------------------------------------
# OPEN-METEO: ÍNDEX UV, AIRE PREVIST (FASE 2) I CLIMA EN CONTEXT (FASE 2)
# Port d'OpenMeteoTaulerLaTdG.js, amb els mateixos textos.
# -----------------------------------------------------------------------------
OM_BASE = {"latitude": BISBAL[0], "longitude": BISBAL[1], "timezone": "Europe/Madrid"}
OM_AIRE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OM_AIRE_VARIABLES = ("european_aqi,european_aqi_pm2_5,european_aqi_pm10,"
                     "european_aqi_nitrogen_dioxide,european_aqi_ozone,dust,uv_index")
_om_aire = {}


def om_aire():
    """Una sola consulta de qualitat de l'aire per execució (també porta l'UV)."""
    if "dades" not in _om_aire:
        r = requests.get(OM_AIRE_URL, params={**OM_BASE, "forecast_days": 1, "hourly": OM_AIRE_VARIABLES},
                         headers=CAPCALERES, timeout=30)
        r.raise_for_status()
        _om_aire["dades"] = r.json()
    return _om_aire["dades"]


def categoria_uv(v):
    if v < 3:
        return "baix"
    if v < 6:
        return "moderat"
    if v < 8:
        return "alt"
    if v < 11:
        return "molt alt"
    return "extrem"


def uv():
    errors = []
    for nom in ("previsió", "qualitat de l'aire"):
        try:
            if nom == "previsió":
                r = requests.get("https://api.open-meteo.com/v1/forecast",
                                 params={**OM_BASE, "forecast_days": 1, "daily": "uv_index_max", "hourly": "uv_index"},
                                 headers=CAPCALERES, timeout=30)
                r.raise_for_status()
                d = r.json()
            else:
                d = om_aire()
            hores = (d.get("hourly") or {}).get("time", [])
            valors = (d.get("hourly") or {}).get("uv_index", [])
            parells = [(h, v) for h, v in zip(hores, valors) if v is not None]
            maxim = ((d.get("daily") or {}).get("uv_index_max") or [None])[0]
            if maxim is None and parells:
                maxim = max(v for _, v in parells)
            if maxim is None:
                errors.append(f"{nom}: sense UV")
                continue

            valor = arrodoneix(maxim)
            altes = [int(h[11:13]) for h, v in parells if v >= 3]
            proteccio = f"entre les {min(altes)} i les {max(altes) + 1} h" if altes else ""
            return {"valor": valor, "categoria": categoria_uv(valor), "proteccio": proteccio}
        except Exception as e:  # es prova la font següent
            errors.append(f"{nom}: {e}")
    raise RuntimeError("; ".join(errors))


def categoria_aire(v):
    if v <= 20:
        return "bona"
    if v <= 40:
        return "raonablement bona"
    if v <= 60:
        return "moderada"
    if v <= 80:
        return "dolenta"
    if v <= 100:
        return "molt dolenta"
    return "extremadament dolenta"


OM_POLS_AVIS_UG = 50
OM_NOMS_CONTAMINANTS = {
    "european_aqi_ozone": "l'ozó",
    "european_aqi_pm2_5": "les partícules fines (PM2,5)",
    "european_aqi_pm10": "les partícules en suspensió (PM10)",
    "european_aqi_nitrogen_dioxide": "el diòxid de nitrogen",
}


def aire_previst():
    h = om_aire().get("hourly") or {}
    temps, aqi = h.get("time"), h.get("european_aqi")
    if not isinstance(temps, list) or not isinstance(aqi, list):
        raise ValueError("Open-Meteo no ha retornat l'índex de l'aire")

    # Hores de dia (de 7 a 22 h): el màxim i el contaminant que el fa pujar.
    maxim, i_max, pols = -1, -1, 0
    pols_llista = h.get("dust") or []
    for i, t in enumerate(temps):
        hora = int(str(t)[11:13])
        if hora < 7 or hora > 22:
            continue
        v = num(aqi[i]) if i < len(aqi) else None
        if v is not None and v > maxim:
            maxim, i_max = v, i
        p = num(pols_llista[i]) if i < len(pols_llista) else None
        if p is not None and p > pols:
            pols = p
    if i_max < 0:
        return None

    dominant, millor = "", -1
    for k, nom in OM_NOMS_CONTAMINANTS.items():
        llista = h.get(k) or []
        v = num(llista[i_max]) if i_max < len(llista) else None
        if v is not None and v > millor:
            millor, dominant = v, nom

    return (categoria_aire(maxim) + f" (índex europeu {arrodoneix(maxim)})" +
            (f", sobretot per {dominant}" if maxim > 40 and dominant else "") +
            (". Pols africana en suspensió" if pols >= OM_POLS_AVIS_UG else "") + ".")


# --- El clima en context (reanàlisi ERA5, des del 1940) ---
OM_ANY_INICI = 1940
OM_RETARD_ERA5_DIES = 6
OM_NORMAL_INICI, OM_NORMAL_FI = 1991, 2020
OM_ANYS_MINIM_DESTACAT = 5
OM_MESOS_ARTICLE = ["", "el gener", "el febrer", "el març", "l'abril", "el maig", "el juny",
                    "el juliol", "l'agost", "el setembre", "l'octubre", "el novembre", "el desembre"]


def om_maj(t):
    return t[:1].upper() + t[1:]


def om_num(v, dec):
    return coma(arrodoneix(v * 10 ** dec) / 10 ** dec, dec)


def om_data(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}"


def om_ratio_text(r):
    if r >= 2.75:
        return f"unes {arrodoneix(r)} vegades més"
    if r >= 1.75:
        return "el doble"
    if r >= 1.5:
        return f"un {arrodoneix((r - 1) * 100)} % més"
    if r <= 0.15:
        return "gairebé res"
    if r <= 0.4:
        return f"només una part petita (un {arrodoneix(r * 100)} %)"
    return "la meitat"


def om_des_de(anys, per_any, valor, f):
    res = {"mes": None, "menys": None}
    if valor is None or not math.isfinite(valor):
        return res
    ordenats = sorted(anys, reverse=True)
    any_actual = ordenats[0] + 1 if ordenats else 0
    any_mes = next((a for a in ordenats if f(per_any[a]) >= valor), None)
    any_menys = next((a for a in ordenats if f(per_any[a]) <= valor), None)
    if any_mes is None:
        res["mes"] = f"des que hi ha registres, el {OM_ANY_INICI}"
    elif any_actual - any_mes >= OM_ANYS_MINIM_DESTACAT:
        res["mes"] = f"des del {any_mes}"
    if any_menys is None:
        res["menys"] = f"des que hi ha registres, el {OM_ANY_INICI}"
    elif any_actual - any_menys >= OM_ANYS_MINIM_DESTACAT:
        res["menys"] = f"des del {any_menys}"
    return res


def om_normal(per_any, f):
    v = [f(per_any[a]) for a in per_any if OM_NORMAL_INICI <= a <= OM_NORMAL_FI]
    v = [x for x in v if math.isfinite(x)]
    return sum(v) / len(v) if len(v) >= 20 else 0


def clima():
    avui = ara()
    fi_era5 = (avui - dt.timedelta(days=OM_RETARD_ERA5_DIES)).strftime("%Y-%m-%d")
    r = requests.get("https://archive-api.open-meteo.com/v1/archive",
                     params={**OM_BASE, "start_date": f"{OM_ANY_INICI}-01-01", "end_date": fi_era5,
                             "daily": "precipitation_sum,temperature_2m_mean"},
                     headers=CAPCALERES, timeout=180)
    r.raise_for_status()
    dies = r.json().get("daily") or {}
    temps, pluja = dies.get("time"), dies.get("precipitation_sum")
    if not isinstance(temps, list) or not isinstance(pluja, list):
        raise ValueError("Open-Meteo no ha retornat la sèrie històrica")
    temp = dies.get("temperature_2m_mean") or []

    nan = float("nan")
    serie = []
    for i, t in enumerate(temps):
        p = num(pluja[i]) if i < len(pluja) else None
        if p is None:
            continue
        tt = num(temp[i]) if i < len(temp) else None
        serie.append({"data": t, "any": int(t[:4]), "mes": int(t[5:7]), "dia": int(t[8:10]),
                      "p": p, "t": tt if tt is not None else nan})
    if len(serie) < 3650:
        raise ValueError("sèrie històrica massa curta")

    frases = []
    darrer = serie[-1]
    ranking_pluja = ranking_temp = False

    # 1. RÀNQUING DEL MES ACABAT (els primers dies de mes, quan ja és complet).
    mes_ant = 12 if avui.month == 1 else avui.month - 1
    any_mes_ant = avui.year - 1 if avui.month == 1 else avui.year
    ultim_dia = calendar.monthrange(any_mes_ant, mes_ant)[1]
    mes_complet = darrer["any"] > any_mes_ant or (darrer["any"] == any_mes_ant and (
        darrer["mes"] > mes_ant or (darrer["mes"] == mes_ant and darrer["dia"] >= ultim_dia)))

    if avui.day <= 14 and mes_complet:
        per_any = {}
        for x in serie:
            if x["mes"] != mes_ant:
                continue
            o = per_any.setdefault(x["any"], {"p": 0.0, "t": 0.0, "n": 0})
            o["p"] += x["p"]
            if math.isfinite(x["t"]):
                o["t"] += x["t"]
                o["n"] += 1
        actual = per_any.get(any_mes_ant)
        if actual:
            mes_nom = OM_MESOS_ARTICLE[mes_ant]
            anys = [a for a in per_any if a < any_mes_ant]

            fp = om_des_de(anys, per_any, actual["p"], lambda o: o["p"])
            normal_p = om_normal(per_any, lambda o: o["p"])
            if fp["mes"] is not None:
                ranking_pluja = True
                frases.append(f"{om_maj(mes_nom)} ha estat el més plujós a la Bisbal {fp['mes']}, amb uns "
                              f"{arrodoneix(actual['p'])} litres per metre quadrat" +
                              (f" (el normal és de {arrodoneix(normal_p)})" if normal_p else "") + ".")
            elif fp["menys"] is not None and normal_p >= 15:
                ranking_pluja = True
                frases.append(f"{om_maj(mes_nom)} ha estat el més sec a la Bisbal {fp['menys']}, amb només uns "
                              f"{arrodoneix(actual['p'])} litres per metre quadrat (el normal és de "
                              f"{arrodoneix(normal_p)}).")

            if actual["n"]:
                mitjana_t = lambda o: o["t"] / o["n"] if o["n"] else nan
                t_actual = actual["t"] / actual["n"]
                fp_t = om_des_de(anys, per_any, t_actual, mitjana_t)
                normal_t = om_normal(per_any, mitjana_t)
                dif = t_actual - normal_t if normal_t else 0
                inici = "I també" if ranking_pluja else om_maj(mes_nom)
                if fp_t["mes"] is not None:
                    ranking_temp = True
                    frases.append(f"{inici} ha estat el més calorós {fp_t['mes']}" +
                                  (f", {om_num(dif, 1)} graus per sobre del normal" if normal_t else "") + ".")
                elif fp_t["menys"] is not None:
                    ranking_temp = True
                    frases.append(f"{inici} ha estat el més fresc {fp_t['menys']}" +
                                  (f", {om_num(-dif, 1)} graus per sota del normal" if normal_t else "") + ".")

    # 2. DARRERS 30 DIES COMPARATS AMB EL NORMAL (mateixes dates, 1991-2020).
    fi = len(serie) - 1
    ultims30 = serie[fi - 29:fi + 1]
    p30 = sum(x["p"] for x in ultims30)
    t30v = [x["t"] for x in ultims30 if math.isfinite(x["t"])]
    t30 = sum(t30v) / len(t30v) if t30v else nan
    claus = {(x["mes"], x["dia"]) for x in ultims30}
    normals = {}
    for x in serie:
        if x["any"] < OM_NORMAL_INICI or x["any"] > OM_NORMAL_FI or (x["mes"], x["dia"]) not in claus:
            continue
        # La finestra pot creuar el canvi d'any: s'assigna a l'any del final de la finestra.
        any_finestra = x["any"] + 1 if (x["mes"] > darrer["mes"] or
                                        (x["mes"] == darrer["mes"] and x["dia"] > darrer["dia"])) else x["any"]
        o = normals.setdefault(any_finestra, {"p": 0.0, "t": 0.0, "n": 0})
        o["p"] += x["p"]
        if math.isfinite(x["t"]):
            o["t"] += x["t"]
            o["n"] += 1
    llista = [o for o in normals.values() if o["n"] >= 25]
    fins = om_data(darrer["data"])
    if len(llista) >= 20:
        normal_p30 = sum(o["p"] for o in llista) / len(llista)
        normal_t30 = sum(o["t"] / o["n"] for o in llista) / len(llista)
        ratio = p30 / normal_p30 if normal_p30 > 0 else 1
        if not ranking_pluja and normal_p30 >= 10 and (ratio >= 1.5 or ratio <= 0.5):
            frases.append(f"En els darrers 30 dies amb dades (fins al {fins}) ha plogut {om_ratio_text(ratio)}"
                          f" del que és habitual en aquestes dates: uns {arrodoneix(p30)} litres per metre "
                          f"quadrat, quan el normal és de {arrodoneix(normal_p30)}.")
        if not ranking_temp and math.isfinite(t30) and abs(t30 - normal_t30) >= 1.5:
            frases.append(f"Les darreres setmanes han estat {om_num(abs(t30 - normal_t30), 1)} graus " +
                          ("més càlides" if t30 > normal_t30 else "més fresques") +
                          " del que és habitual en aquestes dates.")

    # 3. RATXA SECA: dies seguits sense cap dia de 5 litres o més.
    ratxa = 0
    for x in reversed(serie):
        if x["p"] >= 5:
            break
        ratxa += 1
    if ratxa >= 30:
        frases.append(f"Fins al {fins}, feia {ratxa} dies que a la Bisbal no plovia 5 litres o més en un sol dia.")

    return frases[:3] or None   # sense res destacable, el bloc no surt


# -----------------------------------------------------------------------------
# AVIACIÓ NO COMERCIAL (21.10.2026): del registre del vigilant d'aeronaus, que
# ara corre a GitHub (repo latdg/vigilant-aeronaus, branca dades), en lloc del
# Google Sheet. Hi entren les aeronaus no comercials de la zona d'avisos d'avui.
# -----------------------------------------------------------------------------
AERONAUS_URL = "https://raw.githubusercontent.com/latdg/vigilant-aeronaus/dades/registre/{dia}.json"


def aeronaus():
    r = requests.get(AERONAUS_URL.format(dia=ara().strftime("%Y-%m-%d")), headers=CAPCALERES, timeout=30)
    if r.status_code == 404:
        return []          # encara no hi ha cap pas avui
    r.raise_for_status()
    sortida = [{
        "hora": f["hora"],
        "matricula": f.get("matricula") or "—",
        "model": f.get("model", ""),
        "descripcio": f.get("descripcio", ""),
        "categoria": f.get("categoria", ""),
        "altitud": f.get("altitud"),
        "velocitat": f.get("velocitat"),
        "ubicacio": f.get("ubicacio", ""),
        "lat": f.get("lat"),
        "lon": f.get("lon"),
    } for f in r.json() if f.get("alerta") and f.get("clau") != "comercial"]
    return sorted(sortida, key=lambda x: x["hora"])


# -----------------------------------------------------------------------------
# POL·LEN (21.10.2026): previsió setmanal del PIA per a Girona (de dilluns a
# diumenge, <date><start>…</start>). Quan ja es té la d'aquesta setmana no es
# torna a consultar; a partir de dilluns es mira cada hora fins que surt la
# nova. A la pràctica, una consulta bona per setmana.
# -----------------------------------------------------------------------------
POLLEN_URL = "https://aerobiologia.cat/api/v0/forecast/girona/ca/xml"
POLLEN_SETMANA = ""   # dia d'inici de la setmana de la previsió llegida


def pollen():
    r = requests.get(POLLEN_URL, headers={"User-Agent": CAPCALERES["User-Agent"], "Accept": "application/xml, text/xml, */*"}, timeout=60)
    r.raise_for_status()
    arrel = ET.fromstring(r.content)

    noms = {}
    for grup in ("pollens", "spores"):
        for t in arrel.findall(f"taxons/{grup}/*"):
            noms[t.tag] = t.get("ca") or t.tag
    actual = {v.text: v.get("ca") or v.text for v in arrel.findall("legend/current/value")}
    tendencia = {v.text: v.get("ca") or v.text for v in arrel.findall("legend/forecast/value")}

    global POLLEN_SETMANA
    report = arrel.find("report")
    if report is None or report.find("current") is None:
        return None
    POLLEN_SETMANA = (report.findtext("date/start") or "").strip()
    linies = []
    for grup in ("pollens", "spores"):
        for taxo in report.findall(f"current/{grup}/*"):
            valor = (taxo.text or "").strip()
            if valor == "0" or not valor:
                continue
            text = f"{noms.get(taxo.tag, taxo.tag)}: {actual.get(valor, valor)}"
            prev = report.find(f"forecast/{grup}/{taxo.tag}")
            if prev is not None and tendencia.get((prev.text or "").strip()):
                text += f" (tendència: {tendencia[prev.text.strip()].lower()})"
            linies.append(text)
    # 21.10.2026: es diu de quina setmana és la previsió.
    def dma(iso):
        try:
            return dt.date.fromisoformat(iso).strftime("%d.%m.%Y")
        except ValueError:
            return ""
    inici, fi = dma(POLLEN_SETMANA), dma((report.findtext("date/end") or "").strip())
    cap = f"Previsió per a la setmana del {inici} al {fi}: " if inici and fi else ""
    if not linies:
        return cap + "nivells nuls a totes les categories mesurades"
    return cap + ", ".join(linies) + "."


# -----------------------------------------------------------------------------
# PUNTS DE RECÀRREGA (21.10.2026): abans a l'Apps Script. Un cop per setmana
# s'ajunten tres fonts, sense repetir punts a menys de 150 m:
#   1. ICAEN (dades obertes de la Generalitat, estacions semiràpides o més).
#   2. Registre estatal del MITERD (fitxer DATEX II de la DGT, molt gran).
#   3. OpenStreetMap (punts que hi afegeixi qualsevol, també La TdG).
# Si el registre estatal falla, es torna a provar l'endemà.
# -----------------------------------------------------------------------------
RECARREGA_VERSIO = "5-municipis-gestor"
RECARREGA_MUNICIPIS = [
    {"nom": "La Bisbal d'Empordà", "codi": "170221", "ine": "17022",
     "termes": ["bisbal d'emporda", "bisbal de l'emporda", "bisbal de ampurdan", "bisbal d'ampurdan", "bisbal del ampurdan", "castell d'emporda"]},
    {"nom": "Forallac", "codi": "179026", "ine": "17902",
     "termes": ["forallac", "vulpellac", "peratallada", "fonteta", "canapost", "sant climent de peralta", "santa susanna de peralta"]},
    {"nom": "Corçà", "codi": "170577", "ine": "17057",
     "termes": ["corca", "casavells", "matajudaica", "cassa de pelras"]},
    {"nom": "Cruïlles, Monells i Sant Sadurní de l'Heura", "codi": "179011", "ine": "17901",
     "termes": ["cruilles", "monells", "sant sadurni de l'heura"]},
    {"nom": "Ullastret", "codi": "172057", "ine": "17205", "termes": ["ullastret"]},   # 31.10.2026
]
RECARREGA_ICAEN_URL = "https://analisi.transparenciacatalunya.cat/resource/tb2m-m33b.json"
RECARREGA_NAP_URL = "https://infocar.dgt.es/datex2/v3/miterd/EnergyInfrastructureTablePublication/electrolineras.xml"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
CONNECTORS = {
    "iec62196t2": "Tipus 2", "iec62196t2combo": "CCS2", "iec62196t1": "Tipus 1", "iec62196t1combo": "CCS1",
    "iec62196t3a": "Tipus 3A", "iec62196t3c": "Tipus 3C", "chademo": "CHAdeMO", "domestic": "Schuko",
    "domesticf": "Schuko", "domestice": "endoll domèstic", "teslar": "Tesla", "teslas": "Tesla",
    "type2": "Tipus 2", "type2combo": "CCS2", "type1": "Tipus 1", "type1combo": "CCS1", "schuko": "Schuko",
    "teslasupercharger": "Tesla",
}
RECARREGA_NAP_FALLAT = False


def norm_minuscules(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn").replace("’", "'")


def format_normal(t):
    t = str(t or "").strip()
    if t and t == t.upper():
        t = t.lower()
        t = t[:1].upper() + t[1:]
    return t


def km_coma(x):
    return str(round(x, 1)).replace(".0", "").replace(".", ",")


def recarrega_icaen():
    codis = ",".join(f"'{m['codi']}'" for m in RECARREGA_MUNICIPIS)
    r = requests.get(RECARREGA_ICAEN_URL, params={"$limit": 500, "$where": f"codimun in({codis})"}, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    llocs = []
    for f in r.json():
        mun = next((m for m in RECARREGA_MUNICIPIS if m["codi"] == str(f.get("codimun", ""))), None)
        if not mun:
            continue
        nom = str(f.get("designaci_descriptiva") or "").strip()
        if re.fullmatch(r"[A-Z0-9]{10,}", nom):
            nom = ""
        adreca = re.sub(r"[,\s]+$", "", str(f.get("adre_a") or "").strip())
        if re.match(r"^[A-Z0-9]{4}\+[A-Z0-9]{2,3}\b", adreca):
            adreca = ""
        linia = "- " + (nom or "Punt de recàrrega")
        if adreca and adreca != nom:
            linia += f" ({adreca})"
        parts = []
        conn = [CONNECTORS.get(re.sub(r"[^a-z0-9]", "", c.lower()), c.strip()) for c in re.split(r"[+,;/]", str(f.get("tipus_connexi") or "")) if c.strip()]
        conn = list(dict.fromkeys(c.replace("MENNEKES.M", "Tipus 2").replace("MENNEKES", "Tipus 2") for c in conn))
        if conn:
            parts.append(", ".join(conn))
        try:
            kw = float(str(f.get("kw") or "").replace(",", "."))
            if kw > 0:
                parts.append(f"{km_coma(kw)} kW")
        except ValueError:
            pass
        vel = str(f.get("tipus_velocitat") or "").strip().lower()
        if vel:
            parts.append("recàrrega " + vel.replace("semirapid", "semiràpida").replace("rapid", "ràpida").replace("superràpida", "superràpida"))
        if f.get("acces"):
            parts.append("accés amb " + str(f["acces"]).strip().lower())
        gestor = re.sub(r"^Institut Català d'Energia\s*-\s*", "", str(f.get("promotor_gestor") or ""), flags=re.I).strip()
        # 31.10.2026: si el gestor és l'ajuntament, n'hi ha prou amb «gestor: ajuntament»
        # (el municipi ja surt al títol).
        if re.match(r"^ajuntament\b", gestor, flags=re.I):
            gestor = "ajuntament"
        if gestor:
            parts.append("gestor: " + gestor)
        if parts:
            linia += ": " + ", ".join(parts)
        llocs.append({"m": mun["nom"], "n": nom or adreca, "t": linia + ".", "la": num(f.get("latitud")), "lo": num(f.get("longitud"))})
    return llocs


def recarrega_nap():
    global RECARREGA_NAP_FALLAT
    try:
        r = requests.get(RECARREGA_NAP_URL, headers={"User-Agent": CAPCALERES["User-Agent"]}, timeout=600)
        r.raise_for_status()
        text = r.content.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"⚠️ recàrrega: registre estatal no disponible ({e})", file=sys.stderr)
        RECARREGA_NAP_FALLAT = True
        return []

    def valors(xml, etiqueta):
        return [html.unescape(re.sub(r"<[^>]+>", " ", v)).strip()
                for v in re.findall(rf"<(?:[\w-]+:)?{etiqueta}\b[^>]*>([\s\S]*?)</(?:[\w-]+:)?{etiqueta}>", xml)]

    def etiquetada(xml, et):
        m = re.search(et + r"\s*:\s*([^<]+)", xml, re.I)
        return html.unescape(m.group(1)).strip() if m else ""

    llocs, vistos, llegits = [], set(), 0
    for m in re.finditer(r"<(?:[\w-]+:)?energyInfrastructureSite\b[\s\S]*?</(?:[\w-]+:)?energyInfrastructureSite>", text):
        llegits += 1
        bloc = m.group(0)
        municipi_text = etiquetada(bloc, "Municipio")
        if not municipi_text:
            continue
        prov = norm_minuscules(etiquetada(bloc, "Provincia"))
        if prov and "girona" not in prov and "gerona" not in prov:
            continue
        mn = norm_minuscules(municipi_text)
        mun = next((x for x in RECARREGA_MUNICIPIS if any(t in mn for t in x["termes"])), None)
        if not mun:
            continue
        operador_bloc = (re.search(r"<(?:[\w-]+:)?operator\b[\s\S]*?</(?:[\w-]+:)?operator>", bloc) or [""])[0] if re.search(r"<(?:[\w-]+:)?operator\b", bloc) else ""
        sense_op = bloc.replace(operador_bloc, " ") if operador_bloc else bloc
        noms = valors(sense_op, "name")
        nom = noms[0] if noms else ""
        operador = (valors(operador_bloc, "name") or [""])[0] if operador_bloc else ""
        adreca = etiquetada(bloc, "Direcci[oó]n")
        codis = valors(bloc, "connectorType")
        tipus = list(dict.fromkeys(CONNECTORS.get(re.sub(r"[^a-z0-9]", "", c.lower()), c) for c in codis if c))
        pot = max([float(v) for v in valors(bloc, "maxPowerAtSocket") if re.fullmatch(r"[\d.]+", v)] or [0])
        if pot > 1000:
            pot /= 1000
        horari = (re.search(r"<(?:[\w-]+:)?operatingHours\b[\s\S]*?</(?:[\w-]+:)?operatingHours>", bloc) or [""])[0] if re.search(r"operatingHours", bloc) else ""
        obert24 = bool(re.search(r"openAllHours|24\s*h", horari, re.I))
        la = num((valors(bloc, "latitude") or [""])[0])
        lo = num((valors(bloc, "longitude") or [""])[0])
        mid = re.search(r'\bid="([^"]+)"', bloc)
        clau = mid.group(1) if mid else f"{mun['nom']}|{nom}|{adreca}"
        if clau in vistos:
            continue
        vistos.add(clau)
        linia = "- " + (format_normal(nom) or "Punt de recàrrega")
        if adreca:
            linia += f" ({format_normal(adreca)})"
        parts = []
        if codis:
            parts.append(f"{len(codis)} connector{'s' if len(codis) > 1 else ''}" + (f" ({', '.join(tipus)})" if tipus else ""))
        if pot > 0:
            parts.append(f"fins a {km_coma(pot)} kW")
        if obert24:
            parts.append("obert 24 hores")
        if operador:
            parts.append("operador: " + operador)
        if parts:
            linia += ": " + ", ".join(parts)
        llocs.append({"m": mun["nom"], "n": nom, "t": linia + ".", "la": la, "lo": lo})
    if llegits == 0:
        print("⚠️ recàrrega: el registre estatal no té cap punt reconegut (format canviat?)", file=sys.stderr)
        RECARREGA_NAP_FALLAT = True
    print(f"· recàrrega: registre estatal, {llegits} punts llegits, {len(llocs)} de la zona")
    return llocs


def recarrega_osm():
    llocs = []
    for mun in RECARREGA_MUNICIPIS:
        q = (f'[out:json][timeout:90];area["ine:municipio"="{mun["ine"]}"]->.a;'
             'nwr["amenity"="charging_station"](area.a);out center tags;')
        dades = None
        # El servidor d'Overpass sovint va saturat (502): es reintenta amb esperes creixents.
        for espera in (0, 15, 45, 90):
            time.sleep(espera)
            for url in OVERPASS:
                try:
                    r = requests.get(url, params={"data": q}, headers={"User-Agent": CAPCALERES["User-Agent"]}, timeout=150)
                    if r.ok and r.text.lstrip().startswith("{"):
                        dades = r.json()
                        break
                except Exception:
                    continue
            if dades is not None:
                break
        if dades is None:
            global RECARREGA_NAP_FALLAT
            RECARREGA_NAP_FALLAT = True     # es tornarà a provar l'endemà
            print(f"⚠️ recàrrega: OpenStreetMap no respon ({mun['nom']})", file=sys.stderr)
            continue
        for e in dades.get("elements", []):
            t = e.get("tags", {})
            la = e.get("lat", (e.get("center") or {}).get("lat"))
            lo = e.get("lon", (e.get("center") or {}).get("lon"))
            nom = t.get("name") or t.get("brand") or ""
            adreca = " ".join(x for x in [t.get("addr:street", ""), t.get("addr:housenumber", "")] if x)
            linia = "- " + (nom or "Punt de recàrrega")
            if adreca:
                linia += f" ({adreca})"
            parts = []
            sockets = [(k.split(":")[1], v) for k, v in t.items() if re.fullmatch(r"socket:[^:]+", k)]
            if sockets:
                tipus = list(dict.fromkeys(CONNECTORS.get(re.sub(r"[^a-z0-9]", "", k.lower()), k) for k, _ in sockets))
                parts.append(", ".join(tipus))
            if t.get("capacity"):
                parts.append(f"{t['capacity']} places")
            op = t.get("operator") or t.get("network") or ""
            if op and op != nom:
                parts.append("operador: " + op)
            if t.get("opening_hours") == "24/7":
                parts.append("obert 24 hores")
            if parts:
                linia += ": " + ", ".join(parts)
            llocs.append({"m": mun["nom"], "n": nom or adreca, "t": linia + ".", "la": la, "lo": lo})
    return llocs


def recarrega():
    global RECARREGA_NAP_FALLAT
    RECARREGA_NAP_FALLAT = False
    totes = []
    try:
        totes = recarrega_icaen()
    except Exception as e:
        print(f"⚠️ recàrrega: ICAEN ({e})", file=sys.stderr)
    for llista in (recarrega_nap(), recarrega_osm()):
        for p in llista:
            if not any(distancia_km(p["la"], p["lo"], q["la"], q["lo"]) * 1000 < 150
                       for q in totes if None not in (p["la"], p["lo"], q["la"], q["lo"])):
                totes.append(p)
    if not totes:
        return None
    text = []
    for mun in RECARREGA_MUNICIPIS:
        del_mun = sorted((l for l in totes if l["m"] == mun["nom"]), key=lambda l: norm_minuscules(l["n"]))
        if del_mun:
            text.append(mun["nom"] + "\n" + "\n".join(l["t"] for l in del_mun))
        else:   # 31.10.2026: tots els municipis hi surten, també els que no en tenen cap
            text.append(mun["nom"] + "\n- Cap punt de recàrrega registrat.")
    return "\n\n".join(text)


# -----------------------------------------------------------------------------
# BLOCS DE WEBS (21.10.2026): aire, Pla Alfa, sequera, refugis, BORME i
# subhastes. Els calcula el bucle dels bots (latdg/bots, TaulerWebsGitHub.gs)
# cada hora amb el codi de l'Apps Script i els deixa a la branca «tauler-webs».
# -----------------------------------------------------------------------------
TAULER_WEBS_URL = "https://raw.githubusercontent.com/latdg/bots/tauler-webs/webs.json"
BLOCS_WEBS = ("aire", "plaAlfa", "sequera", "refugis", "borme", "subhastes")


def blocs_webs():
    r = requests.get(TAULER_WEBS_URL, params={"v": int(ara().timestamp())}, headers=CAPCALERES, timeout=30)
    r.raise_for_status()
    blocs = r.json().get("blocs") or {}
    return {k: blocs[k] for k in BLOCS_WEBS if k in blocs}


# -----------------------------------------------------------------------------
# NECROLÒGIQUES (31.10.2026): les defuncions que el bucle dels bots prepara per al
# guió (branca «dades-guio» de latdg/bots: Mémora i Diari de Girona ja creuats, els
# últims 5 dies). El tauler les acumula a dades/necrologiques.json (historial).
# -----------------------------------------------------------------------------
NECRO_URL = "https://raw.githubusercontent.com/latdg/bots/dades-guio/dades-guio.json"
NECRO_CAMPS = ("nom", "edat", "dataMort", "vetlla", "ceremonia", "dataFuneral", "detall", "biografia")


def necrologiques():
    r = requests.get(NECRO_URL, params={"v": int(ara().timestamp())}, headers=CAPCALERES, timeout=30)
    r.raise_for_status()
    llista = r.json().get("defuncions")
    if not isinstance(llista, list):
        raise ValueError("sense defuncions")
    return [{k: str(x.get(k) or "").strip() for k in ("clau",) + NECRO_CAMPS} for x in llista if x.get("nom")]


def desa_necrologiques(noves, dia):
    cami = DADES / "necrologiques.json"
    arxiu = llegeix(cami, {})
    per_clau = {x["clau"] or x["nom"].upper(): x for x in (arxiu.get("llista") or [])}
    for x in noves:
        clau = x["clau"] or x["nom"].upper()
        vell = per_clau.get(clau)
        if vell:
            vell.update({k: v for k, v in x.items() if v})    # un camp buit no esborra el que ja hi havia
        else:
            per_clau[clau] = {**x, "vist": dia}
    def ordre(x):
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", x.get("dataMort") or x.get("dataFuneral") or "")
        return (f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}" if m else x.get("vist", ""), x.get("nom", ""))
    llista = sorted(per_clau.values(), key=ordre, reverse=True)
    escriu(cami, {"actualitzat": ara().isoformat(), "llista": llista})
    print(f"✅ necrològiques: {len(noves)} al guió, {len(llista)} a l'historial")


# -----------------------------------------------------------------------------
# INCIDÈNCIES (31.10.2026): la informació dels avisadors d'incidències (projecte
# «alertes» de latdg/apps-script) per als blocs i mapes del tauler. Es consulten
# les MATEIXES fonts públiques que fa servir l'avisador, amb els mateixos filtres;
# aquí no s'envia cap avís ni es toca l'estat de l'avisador. Si una font falla,
# el bloc conserva la darrera consulta bona (amb la seva hora, «consultat»).
#   · Avisos meteorològics: AEMET (CAP, zona Empordà) i Meteocat (SMP, la còpia
#     que en desa l'avisador: branca «tauler-alertes» de latdg/bots; cap consulta
#     més a Meteocat, que té la quota limitada).
#   · Protecció Civil (plans activats), Bombers (actuacions a menys de 25 km),
#     balises V16 (DGT), talls de llum (e-distribución), talls d'aigua de Forallac
#     (Veolia), terratrèmols (IGN) i cabals del Daró i del Ter (ACA).
# -----------------------------------------------------------------------------
MUN_ZONA = {"17022": "la Bisbal d'Empordà", "17057": "Corçà", "17902": "Forallac",
            "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura", "17205": "Ullastret"}
RADI_ZONA_KM = 25          # el «voltant» per a Bombers i balises V16 (més o menys, la comarca)


def es_zona(municipi):
    """Els cinc municipis (com l'avisador: «d'Empordà» per no confondre la Bisbal)."""
    net = re.sub(r"\s+", " ", norm_be(municipi)).strip()
    return (bool(re.search(r"bisbal d' ?emporda", net)) or net in ("corca", "forallac", "ullastret")
            or "cruilles" in net)


def municipi_bonic(t):
    t = re.sub(r"^(.*),\s*(la|el|les|els)$", r"\2 \1", str(t or "").strip(), flags=re.I)
    net = re.sub(r"\s+", " ", norm_be(t)).strip()
    if re.search(r"bisbal d' ?emporda", net):
        return MUN_ZONA["17022"]
    if "cruilles" in net:
        return MUN_ZONA["17901"]
    if net == "corca":
        return "Corçà"
    return text_bonic(t)


def dh(d):
    """datetime -> «31.10.2026 a les 16.20 h» (hora de Madrid)."""
    d = d.astimezone(TZ)
    return f"{d.strftime('%d.%m.%Y')} a les {d.strftime('%H.%M')} h"


def rumb(lat1, lon1, lat2, lon2):
    rad = math.pi / 180
    y = math.sin((lon2 - lon1) * rad) * math.cos(lat2 * rad)
    x = (math.cos(lat1 * rad) * math.sin(lat2 * rad) -
         math.sin(lat1 * rad) * math.cos(lat2 * rad) * math.cos((lon2 - lon1) * rad))
    graus = (math.atan2(y, x) / rad + 360) % 360
    return ["al nord", "al nord-est", "a l'est", "al sud-est", "al sud", "al sud-oest",
            "a l'oest", "al nord-oest"][round(graus / 45) % 8]


def coord(v):
    x = num(v)
    return round(x, 5) if x not in (None, 0) else None


def anterior(nom):
    """El darrer valor bo d'un bloc (de dades/viu.json)."""
    return (llegeix(MEMORIA, {}).get("blocs") or {}).get(nom)


def arcgis(url, params, timeout=60):
    r = requests.get(url, params={"f": "json", **params}, headers=CAPCALERES, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    if d.get("error"):
        raise ValueError(str(d["error"])[:200])
    if not isinstance(d.get("features"), list):
        raise ValueError("la resposta no porta la llista d'elements")
    return d["features"]


# --- AVISOS METEOROLÒGICS ----------------------------------------------------
AEMET_RSS = "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAZ691703_RSS.xml"
AEMET_FENOMENS = {
    "PR": ("pluges", "🌧️"), "NE": ("nevades", "🌨️"), "VI": ("vent", "💨"), "TO": ("tempestes", "⛈️"),
    "AT": ("calor (temperatures màximes)", "🌡️"), "BT": ("fred (temperatures mínimes)", "❄️"),
    "CO": ("fenòmens costaners", "🌊"), "VS": ("pols en suspensió", "🌫️"), "AL": ("allaus", "🏔️"),
    "GA": ("galerna", "💨"), "RI": ("rissaga", "🌊"), "NI": ("boira", "🌫️"), "DH": ("desglaç", "💧"),
}
AEMET_PARAMETRES = {
    "P1": "Precipitació acumulada en una hora", "P2": "Precipitació acumulada en 12 hores",
    "NV": "Acumulació de neu en 24 hores", "RM": "Ratxes màximes", "TA": "Temperatura màxima",
    "TI": "Temperatura mínima", "CO": "Fenòmens costaners", "VI": "Visibilitat", "NI": "Visibilitat",
}
AEMET_NIVELLS = {"amarillo": ("groc", "groc"), "naranja": ("taronja", "taronja"), "rojo": ("vermell", "roig")}
METEO_RANG = {"groc": 1, "taronja": 2, "roig": 3}
SMP_URL = "https://raw.githubusercontent.com/latdg/bots/tauler-alertes/smp.json"
SOFTCATALA_URL = "https://www.softcatala.org/apertium/json/translate"


def tradueix(text):
    r = requests.post(SOFTCATALA_URL, data={"langpair": "es|ca", "q": text, "markUnknown": "no"},
                      headers={"User-Agent": CAPCALERES["User-Agent"]}, timeout=30)
    r.raise_for_status()
    t = ((r.json() or {}).get("responseData") or {}).get("translatedText")
    if not t:
        raise ValueError("Softcatalà: resposta sense traducció")
    return re.sub(r"\*(?=\w)", "", str(t)).strip()


def periode_text(ini, fi):
    ini, fi = ini.astimezone(TZ), fi.astimezone(TZ)
    if ini.date() == fi.date():
        return f"El {ini.strftime('%d.%m.%Y')}, de {ini.strftime('%H.%M')} a {fi.strftime('%H.%M')} h"
    return f"Del {dh(ini)} al {dh(fi)}"


def aemet_avisos(traduccions):
    r = requests.get(AEMET_RSS, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=60)
    r.raise_for_status()
    canal = ET.fromstring(r.content).find("channel")
    links = [(it.findtext("link") or "").strip() for it in (canal.findall("item") if canal is not None else [])[:30]]
    avisos = []
    for link in [l for l in links if l.lower().endswith(".xml")]:
        rc = requests.get(link, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=60)
        rc.raise_for_status()      # llista incompleta: millor conservar la consulta anterior
        arrel = ET.fromstring(rc.content)
        ns = arrel.tag[1:arrel.tag.index("}")] if arrel.tag.startswith("{") else ""
        q = (lambda n: f"{{{ns}}}{n}") if ns else (lambda n: n)
        infos = arrel.findall(q("info"))
        if not infos:
            continue
        info = next((i for i in infos if (i.findtext(q("language")) or "").lower().startswith("es")), infos[0])
        params = {(p.findtext(q("valueName")) or "").strip(): (p.findtext(q("value")) or "").strip()
                  for p in info.findall(q("parameter"))}
        codi = info.find(q("eventCode"))
        fen = ((codi.findtext(q("value")) if codi is not None else "") or "").split(";")
        nivell = params.get("AEMET-Meteoalerta nivel", "").lower()
        par = params.get("AEMET-Meteoalerta parametro", "").split(";") + ["", "", ""]
        try:
            ini = dt.datetime.fromisoformat((info.findtext(q("onset")) or "").strip())
            fi = dt.datetime.fromisoformat((info.findtext(q("expires")) or "").strip())
        except ValueError:
            continue
        # Vigent (com l'avisador): groc o més, no caducat i no és el missatge de retirada.
        if (nivell not in AEMET_NIVELLS or (info.findtext(q("severity")) or "") == "Minor"
                or fi <= dt.datetime.now(dt.timezone.utc) or (fi - ini).total_seconds() <= 60):
            continue
        nom, icona = AEMET_FENOMENS.get(fen[0], ((fen[1] if len(fen) > 1 else "").lower() or "fenomen advers", "⚠️"))
        valor = par[2] if re.search(r"\d", par[2]) else ""
        comentari = (info.findtext(q("description")) or "").strip()
        inici_par = f"{par[1]}: {par[2]}" if par[1] and par[2] else ""
        if inici_par and comentari.startswith(inici_par):
            comentari = comentari[len(inici_par):].lstrip(" .")
        traduit = False
        if comentari:
            if comentari in traduccions:
                comentari, traduit = traduccions[comentari], True
            else:
                try:
                    t = tradueix(comentari)
                    traduccions[comentari] = t
                    comentari, traduit = t, True
                except Exception as e:
                    print(f"   AEMET: sense traducció ({e})", file=sys.stderr)
        prob = params.get("AEMET-Meteoalerta probabilidad", "")
        enviat = (arrel.findtext(q("sent")) or "").strip()
        avisos.append({
            "id": (arrel.findtext(q("identifier")) or "").strip(),
            "codi": fen[0], "fenomen": nom, "icona": icona,
            "nivell": AEMET_NIVELLS[nivell][0], "gravetat": AEMET_NIVELLS[nivell][1],
            "dia": ini.astimezone(TZ).strftime("%Y-%m-%d"), "inici": ini.isoformat(), "fi": fi.isoformat(),
            "quan": periode_text(ini, fi),
            "parametre": (AEMET_PARAMETRES.get(par[0]) or par[1]) if valor else "", "valor": valor,
            "probabilitat": "més del 70%" if re.search(r"mayor\s*70", prob, re.I) else prob,
            "comentari": comentari, "traduit": traduit,
            "emes": dh(dt.datetime.fromisoformat(enviat)) if enviat else "",
        })
    # El mateix avís pot venir repetit (actualitzacions): un per fenomen, paràmetre i inici.
    unics = {}
    for a in avisos:
        k = (a["codi"], a["parametre"], a["inici"])
        if k not in unics or METEO_RANG[a["gravetat"]] > METEO_RANG[unics[k]["gravetat"]]:
            unics[k] = a
    return sorted(unics.values(), key=lambda a: (a["inici"], -METEO_RANG[a["gravetat"]], a["fenomen"]))


class _RegistreTraduccions(dict):
    """Diccionari de traduccions que recorda l'original de cada text traduït."""
    def __init__(self, base, originals):
        super().__init__(base)
        self.originals = originals
        for o, t in base.items():
            originals[t] = o

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self.originals[v] = k

    def __getitem__(self, k):
        v = super().__getitem__(k)
        self.originals[v] = k
        return v


def avisos_meteo():
    vell = anterior("avisosMeteo") or {}
    sortida = {"consultat": ara().isoformat()}
    # AEMET (les traduccions ja fetes es reaprofiten: el text de l'AEMET no canvia gaire).
    traduccions = {}
    for a in (vell.get("aemet") or []):
        if a.get("traduit") and a.get("original"):
            traduccions[a["original"]] = a["comentari"]
    try:
        originals = {}
        llista = aemet_avisos(_RegistreTraduccions(traduccions, originals))
        for a in llista:
            a["original"] = originals.get(a["comentari"], "")
        sortida["aemet"] = llista
        sortida["aemetConsultat"] = ara().isoformat()
    except Exception as e:
        print(f"   AEMET: {e}", file=sys.stderr)
        sortida["aemet"] = vell.get("aemet")
        sortida["aemetConsultat"] = vell.get("aemetConsultat")
    # Meteocat (SMP): la còpia que desa l'avisador.
    try:
        r = requests.get(SMP_URL, params={"v": int(ara().timestamp())}, headers=CAPCALERES, timeout=30)
        if r.status_code == 404:
            sortida["meteocat"] = None
        else:
            r.raise_for_status()
            d = r.json()
            avui = ara().strftime("%Y-%m-%d")
            d["grups"] = [g for g in (d.get("grups") or []) if str(g.get("dia", "")) >= avui]
            sortida["meteocat"] = d
    except Exception as e:
        print(f"   Meteocat (SMP): {e}", file=sys.stderr)
        sortida["meteocat"] = vell.get("meteocat")
    if sortida.get("aemet") is None and sortida.get("meteocat") is None and not vell:
        raise ValueError("cap font d'avisos disponible")
    return sortida



# --- PROTECCIÓ CIVIL ---------------------------------------------------------
PC_URL = "https://analisi.transparenciacatalunya.cat/resource/wj9c-j6vf.json"
PC_TERMES = ["baix emporda", "bisbal d'emporda", "corca", "forallac", "cruilles", "monells",
             "sant sadurni de l'heura", "ullastret"]
PC_RISCOS = {"INFOCAT": "incendis forestals", "INUNCAT": "inundacions", "NEUCAT": "nevades",
             "VENTCAT": "vent fort", "ALLAUCAT": "allaus", "SISMICAT": "sismes",
             "TRANSCAT": "transport de mercaderies perilloses", "PROCICAT": "riscos sense pla específic",
             "PLASEQCAT": "accidents a la indústria química", "AEROCAT": "accidents aeris",
             "CAMCAT": "contaminació marina"}


def pc_zona(text):
    net = norm_be(text)
    return any(t in net for t in PC_TERMES)


def pc_gravetat(fase):
    f = norm_be(fase)
    if "prealerta" in f:
        return "groc"
    if "alerta" in f:
        return "taronja"
    if "emergencia" in f:
        return "roig"
    return "taronja"


def proteccio_civil():
    r = requests.get(PC_URL, params={"$limit": 100}, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    sortida = []
    for p in r.json():
        desc = re.sub(r"\s+", " ", str(p.get("descripcio") or "")).strip()
        zona = pc_zona(desc)
        frases = re.findall(r"[^.;]+[.;]?\s*", desc) or [desc]
        if zona:
            frases = [f for f in frases if pc_zona(f)] or frases
        text = " ".join(f.strip() for f in frases).strip()
        if len(text) > 400:
            text = re.sub(r"\s+\S*$", "", text[:397]) + "…"
        acr = str(p.get("plaacronim") or "").upper()
        quan = ""
        if p.get("fasedatahora"):
            try:
                d = dt.datetime.fromisoformat(str(p["fasedatahora"]).replace("Z", "+00:00"))
                quan = dh(d if d.tzinfo else d.replace(tzinfo=TZ))   # sense zona: hora local
            except ValueError:
                quan = str(p["fasedatahora"])
        pdf = p.get("comunicatpdf")
        if isinstance(pdf, dict):
            pdf = pdf.get("url")
        sortida.append({
            "pla": acr or str(p.get("planom") or "Pla de Protecció Civil"),
            "nom": str(p.get("planom") or ""), "risc": PC_RISCOS.get(acr, ""),
            "fase": str(p.get("plafase") or ""), "gravetat": pc_gravetat(p.get("plafase")),
            "des": quan, "zona": zona, "text": text, "pdf": str(pdf or ""),
        })
    sortida.sort(key=lambda x: (not x["zona"], -METEO_RANG.get(x["gravetat"], 1), x["pla"]))
    return {"consultat": ara().isoformat(), "plans": sortida}


# --- BOMBERS -----------------------------------------------------------------
BOMBERS_URL = ("https://services7.arcgis.com/ZCqVt1fRXwwK6GF4/arcgis/rest/services/"
               "ACTUACIONS_URGENTS_online_PRO_AMB_FASE_VIEW/FeatureServer/0/query")


def bombers():
    # Un rectangle d'uns 40 km al voltant de la Bisbal; després, el radi exacte.
    caixa = f"{BISBAL[1] - 0.45},{BISBAL[0] - 0.35},{BISBAL[1] + 0.45},{BISBAL[0] + 0.35}"
    features = arcgis(BOMBERS_URL, {
        "where": "1=1", "geometry": caixa, "geometryType": "esriGeometryEnvelope", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "returnGeometry": "true", "outSR": "4326",
        "outFields": "MUNICIPI_DPX,COM_FASE,TAL_DESC_ALARMA1,TAL_DESC_ALARMA2,ACT_NUM_VEH,ACT_DAT_ACTUACIO,ESRI_OID"})
    sortida = []
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        lat, lon = coord(g.get("y")), coord(g.get("x"))
        nostre = es_zona(a.get("MUNICIPI_DPX"))
        km = distancia_km(*BISBAL, lat, lon) if lat is not None and lon is not None else None
        if not nostre and (km is None or km > RADI_ZONA_KM):
            continue
        desc = str(a.get("TAL_DESC_ALARMA2") or a.get("TAL_DESC_ALARMA1") or "").strip()
        inici = a.get("ACT_DAT_ACTUACIO")
        vehicles = num(a.get("ACT_NUM_VEH"))
        sortida.append({
            "municipi": municipi_bonic(a.get("MUNICIPI_DPX")), "fase": str(a.get("COM_FASE") or ""),
            "descripcio": desc, "incendi": bool(re.search(r"incendi|foc|fum|vegetacio", norm_be(desc))),
            "vehicles": int(vehicles) if vehicles else None,
            "inici": dh(dt.datetime.fromtimestamp(inici / 1000, TZ)) if isinstance(inici, (int, float)) else "",
            "ms": inici if isinstance(inici, (int, float)) else 0,
            "lat": lat, "lon": lon, "km": round(km, 1) if km is not None else None, "nostre": nostre,
        })
    sortida.sort(key=lambda x: (not x["nostre"], -x["ms"]))
    return {"consultat": ara().isoformat(), "radi": RADI_ZONA_KM, "actuacions": sortida}


# --- BALISES V16 -------------------------------------------------------------
V16_URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
V16_RUMBS = {"north": "nord", "northeast": "nord-est", "east": "est", "southeast": "sud-est", "south": "sud",
             "southwest": "sud-oest", "west": "oest", "northwest": "nord-oest", "norte": "nord",
             "noreste": "nord-est", "este": "est", "sureste": "sud-est", "sur": "sud",
             "suroeste": "sud-oest", "oeste": "oest", "noroeste": "nord-oest"}


def v16_camp(xml, etiqueta):
    m = re.search(r"<(?:[\w-]+:)?" + etiqueta + r"(?:\s[^>]*)?>([^<]*)<", xml)
    return m.group(1).strip() if m else ""


def balises_v16():
    r = requests.get(V16_URL, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=120)
    r.raise_for_status()
    trossos = re.split(r'<(?:[\w-]+:)?situation\s+id="', r.content.decode("utf-8", errors="replace"))
    if len(trossos) < 2:
        raise ValueError("el feed no conté cap incidència")
    totes, sortida = 0, []
    for t in trossos[1:]:
        if not re.match(r"V16", v16_camp(t, "situationRecordCreationReference"), re.I):
            continue
        totes += 1
        lat, lon = coord(v16_camp(t, "latitude")), coord(v16_camp(t, "longitude"))
        municipi, prov = v16_camp(t, "municipality"), v16_camp(t, "province")
        de_girona = not prov or "giron" in norm_be(prov)
        nostre = de_girona and es_zona(municipi)
        km = distancia_km(*BISBAL, lat, lon) if lat is not None and lon is not None else None
        if not nostre and (km is None or km > RADI_ZONA_KM):
            continue
        orientacio = ""
        for camp in ("tpegDirection", "tpegDirectionRoad", "directionBoundOnLinearSection", "directionBound", "orientation"):
            o = V16_RUMBS.get(re.sub(r"bound$", "", re.sub(r"[^a-z]", "", v16_camp(t, camp).lower())), "")
            if o:
                orientacio = o
                break
        kmp = num(v16_camp(t, "kilometerPoint"))
        inici = v16_camp(t, "overallStartTime")
        try:
            inici = dh(dt.datetime.fromisoformat(inici.replace("Z", "+00:00"))) if inici else ""
        except ValueError:
            pass
        sortida.append({"via": v16_camp(t, "roadName"), "pk": coma(kmp, 1) if kmp is not None else "",
                        "municipi": municipi_bonic(municipi), "orientacio": orientacio, "inici": inici,
                        "lat": lat, "lon": lon, "km": round(km, 1) if km is not None else None, "nostre": nostre})
    # Amb el servei en marxa sempre n'hi ha alguna a Espanya: si no, ha canviat el format.
    if not totes:
        raise ValueError("cap balisa V16 a tot Espanya (possible canvi de format del feed)")
    sortida.sort(key=lambda x: (not x["nostre"], x["km"] if x["km"] is not None else 999))
    return {"consultat": ara().isoformat(), "espanya": totes, "balises": sortida}


# --- TALLS DE LLUM -----------------------------------------------------------
LLUM_URL = "https://dpa-portalgis.enel.com/server/rest/services/Hosted/ESP_Prod_power_cut_View/FeatureServer/0/query"


def data_llum(text):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})", str(text or ""))
    return f"{int(m[1]):02d}.{int(m[2]):02d}.{m[3]} a les {int(m[4]):02d}.{m[5]} h" if m else str(text or "").strip()


def talls_llum():
    where = ("UPPER(municipality) LIKE '%BISBAL%EMPORD%' OR UPPER(municipality) LIKE '%FORALLAC%'"
             " OR UPPER(municipality) LIKE 'COR%' OR UPPER(municipality) LIKE '%CRU%LLES%'"
             " OR UPPER(municipality) LIKE '%ULLASTRET%'")
    features = arcgis(LLUM_URL, {
        "where": where, "returnGeometry": "false",
        "outFields": "municipality,service_des_ca,des_cause_ca,cod_cause,affected_client,"
                     "interruption_date,reposition_date,update_time,latitude,longitude,cd_code"})
    sortida = []
    for f in features:
        a = f.get("attributes") or {}
        if not es_zona(a.get("municipality")) or not a.get("cd_code"):
            continue
        causa = str(a.get("des_cause_ca") or "").strip()
        sortida.append({
            "municipi": municipi_bonic(a.get("municipality")),
            "servei": str(a.get("service_des_ca") or "").strip(), "causa": causa,
            "avaria": str(a.get("cod_cause") or "") == "A" or "avaria" in norm_be(causa),
            "abonats": a.get("affected_client") if isinstance(a.get("affected_client"), (int, float)) else None,
            "inici": data_llum(a.get("interruption_date")), "reposicio": data_llum(a.get("reposition_date")),
            "actualitzat": data_llum(a.get("update_time")),
            "lat": coord(a.get("latitude")), "lon": coord(a.get("longitude")),
        })
    return {"consultat": ara().isoformat(), "talls": sortida}


# --- TALLS D'AIGUA (Forallac, Veolia) ----------------------------------------
AIGUA_URL = ("https://services3.arcgis.com/5VitVYyVLQYnzXCo/arcgis/rest/services/"
             "Cierres_webPublicas_v/FeatureServer/0/query")


def talls_aigua():
    features = arcgis(AIGUA_URL, {
        "where": "COD_MUNI IN ('17902') AND CI_ESTADO IN ('4AP','5EC')", "returnGeometry": "true", "outSR": "4326",
        "outFields": "CI_ID,CI_FH_INI_PREV,CI_FH_FIN_PREV,CI_DIRECCION,CI_CALLES,CI_ESTADO,CI_MOTIVO,COD_MUNI",
        "orderByFields": "CI_FH_INI_PREV"})
    sortida = []
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if a.get("CI_ID") in (None, ""):
            continue
        p = lambda xs: [[round(y, 5), round(x, 5)] for x, y in xs]
        if "x" in g and "y" in g:
            geom = {"tipus": "punt", "coords": [round(g["y"], 5), round(g["x"], 5)]}
        elif g.get("paths"):
            geom = {"tipus": "linia", "coords": [p(c) for c in g["paths"]]}
        elif g.get("rings"):
            geom = {"tipus": "poligon", "coords": [p(c) for c in g["rings"]]}
        else:
            geom = None
        adreca = str(a.get("CI_DIRECCION") or "").strip()
        adreca = "" if adreca.lower() == "null" else re.sub(r"^(.*?),\s*\d{5}\b.*$", r"\1", adreca).strip()
        carrers = str(a.get("CI_CALLES") or "").strip()
        ini = dt.datetime.fromtimestamp(a["CI_FH_INI_PREV"] / 1000, TZ) if isinstance(a.get("CI_FH_INI_PREV"), (int, float)) else None
        fi = dt.datetime.fromtimestamp(a["CI_FH_FIN_PREV"] / 1000, TZ) if isinstance(a.get("CI_FH_FIN_PREV"), (int, float)) else None
        sortida.append({
            "encurs": str(a.get("CI_ESTADO")) == "5EC", "avaria": str(a.get("CI_MOTIVO")) == "AVE",
            "adreca": adreca, "carrers": "" if carrers.lower() == "null" else carrers,
            "quan": periode_text(ini, fi) if ini and fi else (f"A partir del {dh(ini)}" if ini else ""),
            "geom": geom,
        })
    return {"consultat": ara().isoformat(), "talls": sortida}


# --- TERRATRÈMOLS (IGN) ------------------------------------------------------
SISMES_URL = "https://www.ign.es/ign/RssTools/sismologia.xml"
SISMES_RADI_KM = 300       # el mapa: Catalunya, el Pirineu i el golf de Lleó
SISMES_DIES = 30           # el canal en dona 10; el tauler n'acumula 30
SISMES_CODIS = {"GI": "Girona", "B": "Barcelona", "L": "Lleida", "T": "Tarragona", "FRA": "França",
                "AND": "Andorra", "HU": "Osca"}


def sisme_lloc(text):
    t, zona = str(text or "").strip(), ""
    m = re.match(r"^(.*)\.([A-Z]{1,3})$", t)
    if m:
        t, zona = m[1].strip(), SISMES_CODIS.get(m[2], m[2])
    direccio = ""
    m = re.match(r"^([NSEW]{1,3})\s+(.+)$", t)
    if m:
        direccio, t = m[1].replace("W", "O"), m[2]
    nom = text_bonic(t)
    if direccio:
        de = ("de " + nom[0].lower() + nom[1:] if re.match(r"^(La|Les) ", nom) else
              "del " + nom[3:] if nom.startswith("El ") else "dels " + nom[4:] if nom.startswith("Els ") else
              "d'" + nom if re.match(r"^[AEIOUÀÈÉÍÒÓÚH]", nom, re.I) else "de " + nom)
        nom = ("a l'" if direccio[0] in "EO" else "al ") + direccio + " " + de
    return nom + (f" ({zona})" if zona else "")


def terratremols():
    r = requests.get(SISMES_URL, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=60)
    r.raise_for_status()
    geo = "{http://www.w3.org/2003/01/geo/wgs84_pos#}"
    canal = ET.fromstring(r.content).find("channel")
    if canal is None:
        raise ValueError("el canal RSS no té l'element channel")
    nous = {}
    for it in canal.findall("item"):
        enllac = (it.findtext("link") or it.findtext("guid") or "").strip()
        desc = (it.findtext("description") or "").strip()
        mid = re.search(r"evid=([A-Za-z0-9]+)", enllac)
        m = re.search(r"magnitud\s+([\d.,]+)\s+en\s+(.+?)\s+en la fecha\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+"
                      r"(\d{1,2}):(\d{2}):(\d{2})", desc, re.I)
        lat, lon = num(it.findtext(geo + "lat")), num(it.findtext(geo + "long"))
        if not mid or not m or lat is None or lon is None:
            continue
        km = distancia_km(*BISBAL, lat, lon)
        if km > SISMES_RADI_KM:
            continue
        mag = num(m[1])
        d = dt.datetime(int(m[5]), int(m[4]), int(m[3]), int(m[6]), int(m[7]), int(m[8]), tzinfo=dt.timezone.utc)
        nous[mid[1]] = {
            "id": mid[1], "magnitud": mag, "lloc": sisme_lloc(m[2]), "iso": d.isoformat(), "data": dh(d),
            "lat": round(lat, 4), "lon": round(lon, 4), "km": round(km), "rumb": rumb(*BISBAL, lat, lon),
            "enllac": enllac.replace("http:", "https:", 1),
            # Els llindars d'avís de l'avisador: M 2,5 a menys de 50 km, o M 4 a menys de 150 km.
            "avis": (km < 50 and mag >= 2.5) or (km < 150 and mag >= 4),
        }
    limit = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=SISMES_DIES)).isoformat()
    vell = {x["id"]: x for x in ((anterior("terratremols") or {}).get("llista") or [])}
    vell.update(nous)
    llista = sorted((x for x in vell.values() if x["iso"] >= limit), key=lambda x: x["iso"], reverse=True)
    return {"consultat": ara().isoformat(), "dies": SISMES_DIES, "radi": SISMES_RADI_KM, "llista": llista}


# --- CABALS DEL DARÓ I DEL TER (ACA) -----------------------------------------
# Les mateixes estacions i els mateixos llindars oficials de l'avisador. L'ACA no
# té cap estació al tram de Gualta: la del Daró aigües avall és la de Serra de
# Daró, tocant a Gualta.
RIUS_ESTACIONS = [
    {"codi": "170221-002", "riu": "Daró", "lloc": "la Bisbal d'Empordà",
     "llindars": [7.0, 15.0, 75.0, 150.0, 684.0, 1225.0]},
    {"codi": "171910-001", "riu": "Daró", "lloc": "Serra de Daró (tocant a Gualta)",
     "llindars": [4.3, 15.0, 75.0, 150.0, 684.0, 1225.0]},
    {"codi": "170792-002", "riu": "Ter", "lloc": "Girona",
     "llindars": [27.0, 45.0, 225.0, 450.0, 1825.0, 2792.0]},
    {"codi": "170558-002", "riu": "Ter", "lloc": "Colomers",
     "llindars": [29.0, 45.0, 225.0, 450.0, 1938.0, 3040.0]},
    {"codi": "171997-002", "riu": "Ter", "lloc": "Torroella de Montgrí",
     "llindars": [36.0, 55.0, 275.0, 550.0, 1938.0, 3040.0]},
]
RIUS_ESTATS = ["normalitat", "activació", "moderat", "alt", "molt alt", "excepcional", "excepcional (graó superior)"]


def rius():
    fi = dt.datetime.now(dt.timezone.utc)
    formata = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sortida, errors = [], 0
    for e in RIUS_ESTACIONS:
        try:
            r = requests.get(RIU_URL.replace(RIU_ESTACIO, e["codi"]),
                             params={"from": formata(fi - dt.timedelta(hours=25)), "to": formata(fi)},
                             headers=CAPCALERES, timeout=60)
            r.raise_for_status()
            dades = r.json() or {}
        except Exception as ex:
            print(f"   riu {e['codi']}: {ex}", file=sys.stderr)
            errors += 1
            continue
        claus = list(dades)
        cabal_k = next((k for k in claus if k.upper().startswith("CALC")), None)
        nivell_k = next((k for k in claus if k.upper().endswith("ANA001")), None) or \
            next((k for k in claus if "ANA" in k.upper()), None)
        if not (cabal_k or nivell_k):
            print(f"   riu {e['codi']}: sensors desconeguts {claus[:6]}", file=sys.stderr)
            continue

        def serie(k):
            s = []
            for t, v in ((dades.get(k) or {}).items() if k else []):
                x = num(v)
                if x is None:
                    continue
                try:
                    s.append((data_aca(t), x))
                except ValueError:
                    pass
            return sorted(s)

        cabal, nivell = serie(cabal_k), serie(nivell_k)
        if not cabal and not nivell:
            continue
        darrer = max(cabal[-1:] + nivell[-1:], key=lambda x: x[0])[0]
        q = cabal[-1][1] if cabal else None
        # Tendència: respecte de fa unes 3 hores.
        tend = None
        if cabal:
            abans = [v for t, v in cabal if t <= cabal[-1][0] - dt.timedelta(hours=3)]
            if abans:
                tend = round(q - abans[-1], 3)
        estat = None
        if q is not None:
            estat = 0
            for i, l in enumerate(e["llindars"]):
                if q >= l:
                    estat = i + 1
        # Mitjana per hora de les darreres 24 h (per a la gràfica petita).
        hores = {}
        for t, v in cabal:
            hores.setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(v)
        sortida.append({
            "codi": e["codi"], "riu": e["riu"], "lloc": e["lloc"],
            "cabal": round(q, 3) if q is not None else None,
            "nivell": round(nivell[-1][1], 1) if nivell else None,
            "hora": darrer.strftime("%H.%M") + " h" + ("" if darrer.date() == ara().date() else " del " + darrer.strftime("%d.%m.%Y")),
            "tendencia": tend, "estat": RIUS_ESTATS[estat] if estat is not None else None, "grao": estat,
            "llindarActivacio": e["llindars"][0],
            "serie": [round(sum(v) / len(v), 3) for h, v in sorted(hores.items())][-24:],
        })
    if not sortida:
        raise ValueError("cap estació amb dades")
    return {"consultat": ara().isoformat(), "estacions": sortida}


# -----------------------------------------------------------------------------
# CALCULA I FUSIONA
# -----------------------------------------------------------------------------
FUNCIONS = {
    "piezometres": piezometres,
    "carburants": carburants,
    "uv": uv,
    "incidencies": incidencies,
    "riu": riu,
    "airePrevist": aire_previst,
    "clima": clima,
    "aeronaus": aeronaus,
    "pollen": pollen,
    "recarrega": recarrega,
    "necrologiques": necrologiques,
    # 31.10.2026: incidències (la informació dels avisadors).
    "avisosMeteo": avisos_meteo,
    "proteccioCivil": proteccio_civil,
    "bombers": bombers,
    "v16": balises_v16,
    "tallsLlum": talls_llum,
    "tallsAigua": talls_aigua,
    "terratremols": terratremols,
    "rius": rius,
}
UN_COP_AL_DIA = {"clima"}
# 21.10.2026: cada quants minuts com a mínim es torna a consultar un bloc.
CADA_MINUTS = {"pollen": 60, "recarrega": 7 * 24 * 60, "necrologiques": 60}


def llegeix(cami, defecte):
    try:
        return json.loads(cami.read_text(encoding="utf-8"))
    except Exception:
        return defecte


def escriu(cami, dades):
    cami.parent.mkdir(parents=True, exist_ok=True)
    cami.write_text(json.dumps(dades, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def calcula():
    avui = ara().strftime("%Y-%m-%d")
    memoria = llegeix(MEMORIA, {})
    fets = memoria.get("dies") or {}

    moments = memoria.get("moments") or {}
    resultat = {}
    nous_moments = {}
    for nom, fn in FUNCIONS.items():
        if nom in UN_COP_AL_DIA and fets.get(nom) == avui:
            print(f"· {nom}: ja calculat avui")
            continue
        # Pol·len (21.10.2026): un cop es té la previsió d'aquesta setmana, no es
        # torna a mirar fins dilluns; a partir de dilluns, cada hora fins que surt la nova.
        if nom == "pollen":
            dilluns = (ara() - dt.timedelta(days=ara().weekday())).strftime("%Y-%m-%d")
            if moments.get("pollen_setmana", "") >= dilluns:
                continue
        # 31.10.2026: amb Ullastret, la recàrrega es torna a calcular ja (sense esperar la setmana).
        if nom == "recarrega" and moments.get("recarrega_versio") != RECARREGA_VERSIO:
            moments.pop(nom, None)
            nous_moments["recarrega_versio"] = RECARREGA_VERSIO
        if nom in CADA_MINUTS and moments.get(nom):
            try:
                fa = (ara() - dt.datetime.fromisoformat(moments[nom])).total_seconds() / 60
                if fa < CADA_MINUTS[nom]:
                    continue
            except ValueError:
                pass
        try:
            resultat[nom] = fn()   # None vol dir «aquest bloc avui no surt»
            print(f"✅ {nom}" if resultat[nom] is not None else f"— {nom}: sense dades (el bloc no surt)")
            if nom in CADA_MINUTS:
                moment = ara()
                # Si el registre estatal ha fallat, la recàrrega es torna a provar l'endemà.
                if nom == "recarrega" and RECARREGA_NAP_FALLAT:
                    moment -= dt.timedelta(minutes=CADA_MINUTS[nom] - 24 * 60)
                nous_moments[nom] = moment.isoformat()
                if nom == "pollen" and POLLEN_SETMANA:
                    nous_moments["pollen_setmana"] = POLLEN_SETMANA
        except Exception as e:
            print(f"❌ {nom}: {e}", file=sys.stderr)
    try:
        webs = blocs_webs()
        resultat.update(webs)
        print(f"✅ blocs de webs: {', '.join(webs) or 'cap'}")
    except Exception as e:
        print(f"❌ blocs de webs: {e}", file=sys.stderr)
    if nous_moments:
        resultat["_moments"] = nous_moments
    TMP.write_text(json.dumps(resultat, ensure_ascii=False), encoding="utf-8")


def fusiona():
    vius = llegeix(TMP, {})
    moment = ara()
    dia = moment.strftime("%Y-%m-%d")

    # Memòria dels darrers valors bons de cada bloc viu.
    memoria = llegeix(MEMORIA, {})
    blocs_vius = memoria.get("blocs") or {}
    dies = memoria.get("dies") or {}
    moments = memoria.get("moments") or {}
    moments.update(vius.pop("_moments", None) or {})
    # Registre horari del riu: un fitxer per dia, s'hi afegeixen o s'actualitzen les hores.
    if isinstance(vius.get("riu"), dict) and vius["riu"].get("_historic"):
        per_dia = {}
        for h in vius["riu"].pop("_historic"):
            per_dia.setdefault(h.pop("dia"), []).append(h)
        for d, noves in per_dia.items():
            cami = DADES / "riu" / f"{d}.json"
            registre = {x["hora"]: x for x in llegeix(cami, [])}
            registre.update({x["hora"]: x for x in noves})
            escriu(cami, [registre[k] for k in sorted(registre)])
        cami_dies = DADES / "riu" / "dies.json"
        llista = sorted(set(llegeix(cami_dies, [])) | set(per_dia), reverse=True)[:400]
        escriu(cami_dies, llista)

    # 31.10.2026: les necrològiques no van al bloc del dia, sinó al seu historial.
    if isinstance(vius.get("necrologiques"), list):
        desa_necrologiques(vius.pop("necrologiques"), dia)
    vius.pop("necrologiques", None)

    for nom, valor in vius.items():
        blocs_vius[nom] = valor
        dies[nom] = dia
    escriu(MEMORIA, {"blocs": blocs_vius, "dies": dies, "moments": moments})

    base = llegeix(DADES / "darrer.json", {})
    blocs = dict(base.get("blocs") or {})
    # Si la base és d'ahir, les aeronaus «d'avui» encara són les d'ahir.
    if base.get("dia") != dia:
        blocs.pop("aeronaus", None)

    for nom, valor in blocs_vius.items():
        if valor is None:
            blocs.pop(nom, None)
        else:
            blocs[nom] = valor

    dades = {
        "dia": dia,
        "generat": moment.strftime("%d.%m.%Y a les %H.%M h"),
        "blocs": blocs,
    }
    # 21.10.2026: es conserva quan l'Apps Script va consultar cada bloc de webs
    # (publicarTaulerTdG decideix així si li toca tornar-lo a consultar).
    if base.get("actualitzat"):
        dades["actualitzat"] = base["actualitzat"]
    escriu(DADES / f"{dia}.json", dades)
    escriu(DADES / "darrer.json", dades)

    llista_dies = llegeix(DADES / "dies.json", [])
    if dia not in llista_dies:
        llista_dies.append(dia)
    escriu(DADES / "dies.json", sorted(set(llista_dies), reverse=True))
    print(f"✅ Tauler fusionat ({dia}): {', '.join(blocs)}")


if __name__ == "__main__":
    ordre = sys.argv[1] if len(sys.argv) > 1 else ""
    if ordre == "calcula":
        calcula()
    elif ordre == "fusiona":
        fusiona()
    else:
        print("Ús: tauler_viu.py calcula | fusiona")
        sys.exit(1)
