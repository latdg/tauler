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
RECARREGA_MUNICIPIS = [
    {"nom": "La Bisbal d'Empordà", "codi": "170221", "ine": "17022",
     "termes": ["bisbal d'emporda", "bisbal de l'emporda", "bisbal de ampurdan", "bisbal d'ampurdan", "bisbal del ampurdan", "castell d'emporda"]},
    {"nom": "Corçà", "codi": "170577", "ine": "17057",
     "termes": ["corca", "casavells", "matajudaica", "cassa de pelras"]},
    {"nom": "Forallac", "codi": "179026", "ine": "17902",
     "termes": ["forallac", "vulpellac", "peratallada", "fonteta", "canapost", "sant climent de peralta", "santa susanna de peralta"]},
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
}
UN_COP_AL_DIA = {"clima"}
# 21.10.2026: cada quants minuts com a mínim es torna a consultar un bloc.
CADA_MINUTS = {"pollen": 60, "recarrega": 7 * 24 * 60}


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
