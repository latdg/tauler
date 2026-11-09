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
import email.utils
import html
import json
import math
import os
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
    "Sant Antoni", "Castell-Platja d'Aro", "Castell d'Aro", "Platja d'Aro", "Colomers", "Corçà",
    "Cruïlles", "Monells", "Sant Sadurní de l'Heura", "Foixà", "Fontanilles",
    "Forallac", "Garrigoles", "Gualta", "Jafre", "Mont-ras", "Palafrugell",
    "Palamós", "Palau-sator", "Pals", "Parlavà", "La Pera", "Regencós", "Rupià",
    "Sant Feliu de Guíxols", "Santa Cristina d'Aro", "Serra de Daró",
    "Tallada d'Empordà", "Torrent", "Torroella de Montgrí", "Ullastret", "Ullà",
    "Ultramort", "Vall-llobrega", "Verges", "Vilopriu",
    # 09.11.2026: nuclis que no són cap de municipi (la llista només és la reserva
    # per a les incidències que no porten cap coordenada; vegeu dins_comarca).
    "Vulpellac", "Peratallada", "Canapost", "Fonteta", "Sant Climent de Peralta",
    "Casavells", "Castell d'Empordà", "Cassà de Pelràs", "Fitor", "Llofriu",
    "Calella de Palafrugell", "Llafranc", "Tamariu", "Estartit", "S'Agaró",
    "Sant Antoni de Calonge", "Sant Joan de Palamós", "Vila-romà", "Aiguablava", "Sa Riera",
    "Platja de Pals", "Sant Feliu de Boada", "Fontclara", "Llabià", "Sant Iscle d'Empordà",
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
        return [{"title": it.findtext("title") or "", "description": it.findtext("description") or "",
                 "pubDate": it.findtext("pubDate") or ""}
                for it in canal.findall("item")]
    except ET.ParseError:
        # Com al guió: si l'XML està mal format, es llegeix element a element.
        text = contingut.decode("utf-8", errors="replace")

        def camp(bloc, nom):
            m = re.search(rf"<{nom}\b[^>]*>([\s\S]*?)</{nom}>", bloc, re.I)
            if not m:
                return ""
            return re.sub(r"\]\]>\s*$", "", re.sub(r"^\s*<!\[CDATA\[", "", m.group(1))).strip()

        return [{"title": camp(b, "title"), "description": camp(b, "description"), "pubDate": camp(b, "pubDate")}
                for b in re.findall(r"<item\b[^>]*>([\s\S]*?)</item>", text, re.I)]


def incidencies():
    r = requests.get(TRANSIT_URL, headers={**CAPCALERES, "Accept": "application/rss+xml, application/xml"},
                     timeout=60)
    r.raise_for_status()
    resultat = []
    # 09.11.2026: el canal no porta la comarca, i el nom de la població no és fiable
    # (Trànsit va posar a «Platja d'Aro» una obra de la C-1412a, a la Segarra). Cada
    # incidència es queda o no segons on és: les coordenades del GML del mateix Servei
    # Català de Trànsit i els punts d'inici i final del DATEX2, dins del límit de la comarca.
    try:
        gml = registres_gml()
    except Exception as e:
        print("Incidències viàries: no s'ha pogut llegir el GML:", e)
        gml = []
    try:
        regs = registres_sct()
    except Exception as e:
        print("Incidències viàries: no s'ha pogut llegir el DATEX2:", e)
        regs = []
    for item in llegeix_rss(r.content):
        # "CARRETERA | MUNICIPI | Sentit... | Punt km. X-Y | HH:MM"
        parts = [p.strip() for p in neteja_text(item["description"]).split("|")]
        parts += [""] * (5 - len(parts))
        km = re.sub(r"^Punt km\.?\s*", "", parts[3], flags=re.I)
        punts = punts_incidencia(parts[0], km, gml, regs)
        dins = [dins_comarca(*pt) for pt in punts]
        if any(d is True for d in dins):
            pass                                   # algun punt cau dins de la comarca
        elif not te_municipi_baix_emporda(item["title"] + " " + item["description"]):
            continue                               # ni és dins ni porta cap nom de la comarca
        elif punts and None not in dins and min(km_a_comarca(*pt) for pt in punts) > 15:
            continue                               # el nom diu Baix Empordà, però és lluny (error de Trànsit)
        # Si només en coneixem un extrem (el GML en dona un sol punt) i és just fora,
        # o no hi ha cap coordenada, mana el nom de la població.
        # 09.11.2026: el municipi amb el nom oficial i l'article («LA TALLADA D'EMPORDÀ»).
        # Si el nom de Trànsit no és de la comarca però la incidència hi és (la GIV-6322,
        # que Trànsit posa a «l'Escala», és dins del terme d'Albons), mana el terme on cau.
        oficial = nom_oficial(parts[1])
        if not oficial:
            oficial = next((municipi_de_punt(*pt) for pt, d in zip(punts, dins) if d is True), None)
        resultat.append({
            "municipi": oficial.upper() if oficial else parts[1],
            "titol": neteja_text(item["title"]),
            "carretera": parts[0],
            "km": km,
            "sentit": neteja_sentit(parts[2]),   # 09.11.2026
            "inici": inici_incidencia(item.get("pubDate"), parts[4]),   # 02.11.2026
        })
    resultat = sense_duplicades(resultat)   # 09.11.2026
    # 02.11.2026: situa cada incidència al mapa amb el DATEX2 del mateix Servei Català
    # de Trànsit (al punt d'accés de la DGT), que dona els punts d'inici i de final.
    if resultat:
        try:
            situa_incidencies(resultat, regs)
        except Exception as e:
            print("Incidències viàries: no s'han pogut situar al mapa:", e)
    return resultat   # una llista buida també és una dada: «cap incidència»


SCT_GML_URL = "http://www.gencat.cat/transit/opendata/incidenciesGML.xml"
COMARCA_GEOJSON = DADES / "baix_emporda.geojson"   # límit oficial de la comarca (OpenStreetMap)
_ANELLS = None


def anells_comarca():
    global _ANELLS
    if _ANELLS is None:
        try:
            g = json.loads(COMARCA_GEOJSON.read_text(encoding="utf-8"))["geometry"]
            pols = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            _ANELLS = [pol[0] for pol in pols]
        except Exception as e:
            print("Límit de la comarca:", e)
            _ANELLS = []
    return _ANELLS


def dins_comarca(lat, lon):
    """True / False segons si el punt és dins del Baix Empordà; None si no hi ha límit."""
    anells = anells_comarca()
    if not anells:
        return None
    for anell in anells:
        dins = False
        for (x1, y1), (x2, y2) in zip(anell, anell[1:]):
            if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
                dins = not dins
        if dins:
            return True
    return False


MUNICIPIS_GEOJSON = DADES / "municipis_baix_emporda.geojson"   # els 36 termes detallats (OpenStreetMap)
NOMS_OSM = {"Castell d'Aro, Platja d'Aro i s'Agaró": "Castell-Platja d'Aro"}   # nom oficial que fem servir
_TERMES = None
# Noms com els escriu Trànsit -> nom oficial (09.11.2026)
ALIES_MUNICIPI = {"calonge": "Calonge i Sant Antoni", "sant antoni": "Calonge i Sant Antoni",
                  "castell d'aro": "Castell-Platja d'Aro", "platja d'aro": "Castell-Platja d'Aro",
                  "s'agaro": "Castell-Platja d'Aro", "cruilles": "Cruïlles, Monells i Sant Sadurní de l'Heura",
                  "monells": "Cruïlles, Monells i Sant Sadurní de l'Heura",
                  "sant sadurni de l'heura": "Cruïlles, Monells i Sant Sadurní de l'Heura"}


def termes():
    global _TERMES
    if _TERMES is None:
        try:
            fc = json.loads(MUNICIPIS_GEOJSON.read_text(encoding="utf-8"))
            _TERMES = []
            for f in fc["features"]:
                g = f["geometry"]
                pols = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
                nom = f["properties"]["nom"]
                nom = NOMS_OSM.get(nom, nom[:1].upper() + nom[1:])
                _TERMES.append((nom, pols))
        except Exception as e:
            print("Termes municipals:", e)
            _TERMES = []
    return _TERMES


def dins_anell(lat, lon, anell):
    dins = False
    for (x1, y1), (x2, y2) in zip(anell, anell[1:] + anell[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            dins = not dins
    return dins


def municipi_de_punt(lat, lon):
    """El terme municipal del Baix Empordà on cau el punt (o None)."""
    for nom, pols in termes():
        if any(dins_anell(lat, lon, pol[0]) and not any(dins_anell(lat, lon, h) for h in pol[1:]) for pol in pols):
            return nom
    return None


def sense_article(t):
    return re.sub(r"^(la |l'|el |els |les )", "", norm_be(t).strip())


def nom_oficial(nom):
    """«TALLADA D'EMPORDÀ» -> «La Tallada d'Empordà». None si no és cap municipi de la comarca."""
    n = sense_article(nom)
    for oficial, _ in termes():
        if sense_article(oficial) == n:
            return oficial
    return ALIES_MUNICIPI.get(n)


def km_a_comarca(lat, lon):
    """Distància aproximada (km) del punt al límit de la comarca."""
    return min(distancia_km(lat, lon, y, x) for anell in anells_comarca() for x, y in anell[::5])


def registres_gml():
    """Les incidències del GML del Servei Català de Trànsit, amb la seva coordenada."""
    r = requests.get(SCT_GML_URL, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    sortida = []
    for b in re.findall(r"<gml:featureMember>([\s\S]*?)</gml:featureMember>", text):
        c = re.search(r"<gml:coordinates[^>]*>\s*([-\d.]+),([-\d.]+)", b)
        def camp(nom):
            m = re.search(rf"<(?:\w+:)?{nom}>([^<]*)<", b)
            return m.group(1).strip() if m else ""
        if not c:
            continue
        ki, kf = num(camp("pk_inici")), num(camp("pk_fi"))
        kms = [k for k in (ki, kf) if k is not None]
        sortida.append({"via": nom_via(camp("carretera")), "km": (min(kms), max(kms)) if kms else None,
                        "punt": [float(c.group(2)), float(c.group(1))]})
    return sortida


def punts_incidencia(carretera, km, gml, regs):
    """Totes les coordenades conegudes d'una incidència (GML i DATEX2), per carretera i quilòmetres."""
    via, kr = nom_via(carretera), km_rss(km)
    if not kr:
        return []
    punts = [g["punt"] for g in gml if g["via"] == via and g["km"]
             and abs(g["km"][0] - kr[0]) < 0.05 and abs(g["km"][1] - kr[1]) < 0.05]
    for x in regs:
        if x["via"] == via and x["km"] and abs(x["km"][0] - kr[0]) < 0.5 and abs(x["km"][1] - kr[1]) < 0.5:
            punts += [p for p in (x["de"], x["a"]) if p]
    return punts


def neteja_sentit(t):
    """09.11.2026: «Sentit Ambdós sentits cap a HORARI DIÜRN» -> «ambdós sentits · horari diürn».
    Trànsit hi posa de vegades l'horari on hauria d'anar el destí."""
    t = re.sub(r"^\s*Sentit\s+", "", str(t or "").strip(), flags=re.I)
    base, _, desti = t.partition(" cap a ")
    base = re.sub(r"^Ambd[óo]s sentits$", "ambdós sentits", base.strip(), flags=re.I)
    desti = desti.strip()
    if not desti:
        return base
    if re.search(r"horari", desti, re.I):
        return f"{base} · {desti.lower()}"
    return f"{base} cap a {desti}"


def sense_duplicades(llista):
    """09.11.2026: una mateixa obra publicada dues vegades (mateix municipi, carretera,
    quilòmetres i tipus) surt una sola vegada: es queda la més recent."""
    def quan(i):
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4}) a les (\d{2})\.(\d{2})", i.get("inici") or "")
        return (m.group(3), m.group(2), m.group(1), m.group(4), m.group(5)) if m else ("",)
    triades = {}
    for i in llista:
        clau = (norm_be(i["municipi"]), norm_be(i["titol"]), norm_be(i["carretera"]), i["km"])
        if clau not in triades or quan(i) > quan(triades[clau]):
            triades[clau] = i
    return [i for i in llista if triades.get((norm_be(i["municipi"]), norm_be(i["titol"]), norm_be(i["carretera"]), i["km"])) is i]


def inici_incidencia(pub, hora):
    """Inici de la incidència: el pubDate del canal (com al bot d'alertes); si no, l'hora de la descripció."""
    try:
        if pub:
            return dh(email.utils.parsedate_to_datetime(pub))
    except (TypeError, ValueError, IndexError):
        pass
    m = re.search(r"(\d{1,2})[:.](\d{2})", str(hora or ""))
    return f"{ara().strftime('%d.%m.%Y')} a les {int(m.group(1)):02d}.{m.group(2)} h" if m else ""


SCT_DATEX_URL = "https://nap.dgt.es/datex2/sct/SituationPublication/all/content.xml"
TRAMS_CAU = DADES / "trams_transit.json"   # el traçat per carretera de cada tram, ja calculat


def nom_via(t):
    return re.sub(r"[^A-Z0-9]", "", str(t or "").upper())


def km_rss(t):
    x = [num(v) for v in re.findall(r"\d+(?:[.,]\d+)?", str(t or ""))]
    x = [v for v in x if v is not None]
    return (min(x), max(x)) if x else None


def registres_sct():
    r = requests.get(SCT_DATEX_URL, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=120)
    r.raise_for_status()
    text = r.content.decode("utf-8", errors="replace")
    sortida = []
    for t in re.findall(r"<(?:[\w-]+:)?situationRecord\b([\s\S]*?)</(?:[\w-]+:)?situationRecord>", text):
        via = nom_via(v16_camp(t, "roadNumber"))
        if not via:
            continue
        def punt(etiqueta):
            for bloc in re.findall(r"<(?:[\w-]+:)?" + etiqueta + r"\b[^>]*>([\s\S]*?)</(?:[\w-]+:)?" + etiqueta + ">", t):
                lat, lon = coord(v16_camp(bloc, "latitude")), coord(v16_camp(bloc, "longitude"))
                if lat is not None and lon is not None:
                    return [lat, lon]
            return None
        de, a = punt("from"), punt("to")
        if not de and not a:
            totes = re.findall(r"<(?:[\w-]+:)?latitude>([^<]+)<[\s\S]*?<(?:[\w-]+:)?longitude>([^<]+)<", t)
            pts = [[coord(x), coord(y)] for x, y in totes if coord(x) is not None and coord(y) is not None]
            de, a = (pts[0], pts[-1]) if pts else (None, None)
        pts = [p for p in (de, a) if p]
        if not pts or min(distancia_km(*BISBAL, *p) for p in pts) > 45:
            continue
        kms = [num(v) / 1000 for v in re.findall(r"<(?:[\w-]+:)?referencePointDistance>([^<]+)<", t) if num(v) is not None]
        # 02.11.2026: data de final prevista, quan el SCT l'informa
        fi = ""
        try:
            f = v16_camp(t, "overallEndTime")
            fi = dh(dt.datetime.fromisoformat(f.replace("Z", "+00:00"))) if f else ""
        except ValueError:
            pass
        sortida.append({"via": via, "de": de, "a": a, "km": (min(kms), max(kms)) if kms else None, "fi": fi})
    return sortida


def tram_per_carretera(de, a, cau):
    """El recorregut per carretera entre els dos punts (OSRM), desat a la memòria cau."""
    clau = f"{de[0]:.5f},{de[1]:.5f};{a[0]:.5f},{a[1]:.5f}"
    if clau in cau:
        return cau[clau]
    try:
        r = requests.get(f"https://router.project-osrm.org/route/v1/driving/{de[1]},{de[0]};{a[1]},{a[0]}",
                         params={"overview": "full", "geometries": "geojson"}, headers=CAPCALERES, timeout=30)
        r.raise_for_status()
        rutes = r.json().get("routes") or []
        linia = [[round(y, 5), round(x, 5)] for x, y in rutes[0]["geometry"]["coordinates"]] if rutes else None
        # Si la ruta fa una volta molt més llarga que la recta, millor no fer-la servir
        recta = distancia_km(*de, *a)
        if linia and rutes[0].get("distance", 0) / 1000 > max(3 * recta, recta + 5):
            linia = None
    except Exception as e:
        print("Ruta del tram:", e)
        return None
    cau[clau] = linia
    return linia


def situa_incidencies(resultat, regs=None):
    regs = regs if regs is not None else registres_sct()
    cau = llegeix(TRAMS_CAU, {})
    usats = set()
    for inc in resultat:
        via, kr = nom_via(inc.get("carretera")), km_rss(inc.get("km"))
        candidats = [(i, r) for i, r in enumerate(regs) if r["via"] == via and i not in usats]
        if not candidats:
            continue
        def encaix(ir):
            r = ir[1]
            if kr and r["km"]:
                return abs(r["km"][0] - kr[0]) + abs(r["km"][1] - kr[1])
            return 999
        i, r = min(candidats, key=encaix)
        usats.add(i)
        if r.get("fi"):
            inc["fi"] = r["fi"]
        if r["de"] and r["a"] and distancia_km(*r["de"], *r["a"]) > 0.05:
            inc["tram"] = [r["de"], r["a"]]
            linia = tram_per_carretera(r["de"], r["a"], cau)
            if linia:
                inc["linia"] = linia
        else:
            inc["punt"] = r["de"] or r["a"]
    # Només es guarden els trams que encara són vius
    vius = {f"{x['tram'][0][0]:.5f},{x['tram'][0][1]:.5f};{x['tram'][1][0]:.5f},{x['tram'][1][1]:.5f}"
            for x in resultat if x.get("tram")}
    try:
        TRAMS_CAU.write_text(json.dumps({k: v for k, v in cau.items() if k in vius}, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print("Memòria cau dels trams:", e)


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


# 31.10.2026: el visor de l'ACA (RIU_URL) no respon des de GitHub des del 22.10.2026
# (el bloc s'havia quedat aturat). Ara les lectures surten de l'API Sentilo de
# l'ACA (la mateixa que fa servir l'avisador), que sí que respon.
SENTILO = "https://aplicacions.aca.gencat.cat/sdim2/apirest"
_SENTILO_CATALEG = {}


def sentilo_sensors(component):
    """{"cabal": (proveïdor, sensor), "nivell": (...)} d'una estació d'aforament."""
    if not _SENTILO_CATALEG:
        r = requests.get(f"{SENTILO}/catalog", params={"componentType": "aforament"}, headers=CAPCALERES, timeout=60)
        r.raise_for_status()
        for pr in r.json().get("providers") or []:
            for se in pr.get("sensors") or []:
                desc = norm(se.get("description"))
                clau = "cabal" if "cabal" in desc else "nivell" if "nivell" in desc else None
                if clau:
                    _SENTILO_CATALEG.setdefault(se.get("component"), {}).setdefault(
                        clau, (pr.get("provider"), se.get("sensor"), se.get("unit") or ""))
    return _SENTILO_CATALEG.get(component) or {}


def sentilo_serie(sensor, hores=26):
    """[(datetime, valor)] de les darreres hores (mostres cada 15 minuts)."""
    if not sensor:
        return []
    pr, se, unitat = sensor
    r = requests.get(f"{SENTILO}/data/{pr}/{se}", params={"limit": hores * 4 + 8}, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    sortida = []
    for o in r.json().get("observations") or []:
        v, t = num(o.get("value")), o.get("time")
        if v is None or not isinstance(t, (int, float)):
            continue
        u = unitat.replace(" ", "").lower()
        if u == "l/s":
            v = v / 1000          # cabal sempre en m³/s
        elif u == "m":
            v = v * 100           # nivell sempre en cm
        sortida.append((dt.datetime.fromtimestamp(t / 1000, TZ), v))
    limit = ara() - dt.timedelta(hours=hores)
    return sorted(x for x in sortida if x[0] >= limit)


def riu():
    sensors = sentilo_sensors(RIU_ESTACIO)
    nivell, cabal = sentilo_serie(sensors.get("nivell")), sentilo_serie(sensors.get("cabal"))
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
        else f"{el_dia(darrer)} a les {darrer.strftime('%H.%M')} h"
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
RECARREGA_VERSIO = "6-manuals-mapa"
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
RECARREGA_PUNTS = []   # 05.11.2026: els punts amb coordenades, per al mapa del tauler

# 05.11.2026: punts afegits a mà per La TdG (no surten a cap registre).
# «lliure»: False si no són d'accés lliure.
RECARREGA_MANUALS = [
    {"m": "La Bisbal d'Empordà", "n": "Supermercat Amatller Origen", "la": 41.969722, "lo": 3.031667, "lliure": True,
     "t": "- Supermercat Amatller Origen: 2 punts de recàrrega, accessibles als clients."},
    {"m": "La Bisbal d'Empordà", "n": "Supermercat Mercadona", "la": 41.971111, "lo": 3.030833, "lliure": True,
     "t": "- Supermercat Mercadona: 4 punts de recàrrega, accessibles als clients."},
    {"m": "La Bisbal d'Empordà", "n": "Supermercat Condis", "la": 41.970000, "lo": 3.030278, "lliure": True,
     "t": "- Supermercat Condis: 3 punts de recàrrega, accessibles als clients."},
    {"m": "La Bisbal d'Empordà", "n": "Departament d'Agricultura, Ramaderia i Pesca (DARP)", "la": 41.953333, "lo": 3.035556, "lliure": False,
     "t": "- Departament d'Agricultura, Ramaderia i Pesca (DARP): 2 punts de recàrrega, no són de lliure accés."},
    # 08.11.2026: punt de l'Ajuntament de Forallac, posició mesurada in situ per La TdG
    # (41° 57' 33" N, 3° 3' 19" E). Substitueix el del registre («Punt de recàrrega: 2 places»),
    # que queda a menys de 150 m i, per tant, ja no surt.
    {"m": "Forallac", "n": "Ajuntament", "la": 41.959167, "lo": 3.055278, "lliure": True,
     "t": "- Ajuntament: 2 punts de recàrrega, accessibles."},
]
# 05.11.2026: posició corregida (segons Google Maps) dels punts que els registres
# situen malament. Clau: text que apareix a la línia del punt (sense accents, en minúscules).
RECARREGA_POSICIONS = {
    "romaguera": (42.002560, 3.066952),      # Ullastret, c. Josep Romaguera i Vila, 1
    "mas savalls": (41.957838, 2.993386),    # Sant Sadurní de l'Heura, c. Mas Savalls, 2
    "fusteria sais": (41.954532, 2.996086),  # Fusteria Sais
}


def recarrega_corregeix(llista):
    for p in llista:
        t = norm_minuscules(p.get("t", ""))
        for clau, (la, lo) in RECARREGA_POSICIONS.items():
            if clau in t:
                p["la"], p["lo"] = la, lo
    return llista


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
    global RECARREGA_NAP_FALLAT, RECARREGA_PUNTS
    RECARREGA_NAP_FALLAT = False
    # 05.11.2026: primer els punts afegits a mà; els dels registres que hi siguin
    # a menys de 150 m es consideren el mateix punt.
    totes = [dict(p) for p in RECARREGA_MANUALS]
    try:
        icaen = recarrega_corregeix(recarrega_icaen())
    except Exception as e:
        icaen = []
        print(f"⚠️ recàrrega: ICAEN ({e})", file=sys.stderr)
    a_prop = lambda p, ll: any(distancia_km(p["la"], p["lo"], q["la"], q["lo"]) * 1000 < 150
                               for q in ll if None not in (p["la"], p["lo"], q["la"], q["lo"]))
    # Els de l'ICAEN, com abans, només es comparen amb els afegits a mà.
    totes += [p for p in icaen if not a_prop(p, RECARREGA_MANUALS)]
    for llista in (recarrega_corregeix(recarrega_nap()), recarrega_corregeix(recarrega_osm())):
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
    RECARREGA_PUNTS = [{"m": p["m"], "n": p["n"], "t": p["t"][2:], "la": p["la"], "lo": p["lo"], "lliure": p.get("lliure", True)}
                       for p in totes if p.get("la") is not None and p.get("lo") is not None]
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
# 08.11.2026: noms de lloc que arriben mal escrits i s'han de dir d'una altra manera.
NECRO_CANVIS = (
    ("Parroquia Sant Julià I Santa Basilissa - Corçà", "Parroquia Sant Julià i Santa Basilissa de Corçà"),
    ("Parroquia Sant Julià I Santa Basilissa de Corçà", "Parroquia Sant Julià i Santa Basilissa de Corçà"),
)


def necro_corregeix(text):
    for vell, nou in NECRO_CANVIS:
        text = text.replace(vell, nou)
    return text


def necrologiques():
    r = requests.get(NECRO_URL, params={"v": int(ara().timestamp())}, headers=CAPCALERES, timeout=30)
    r.raise_for_status()
    llista = r.json().get("defuncions")
    if not isinstance(llista, list):
        raise ValueError("sense defuncions")
    return [{k: necro_corregeix(str(x.get(k) or "").strip()) for k in ("clau",) + NECRO_CAMPS} for x in llista if x.get("nom")]


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
    for x in per_clau.values():    # 08.11.2026: també a l'historial ja desat
        for k in NECRO_CAMPS:
            if isinstance(x.get(k), str):
                x[k] = necro_corregeix(x[k])
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
    if "castell-platja d'aro" in net or "castell platja d'aro" in net:
        return "Castell-Platja d'Aro"   # 02.11.2026: amb «Platja» en majúscula
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


def apostrofa(d):
    """«l'» davant de l'1 i de l'11 (dies que comencen per vocal), «el» davant de la resta."""
    return d.astimezone(TZ).day in (1, 11)


def el_dia(d):
    """«L'01.11.2026» o «El 02.11.2026» (inici de frase)."""
    return ("L'" if apostrofa(d) else "El ") + d.astimezone(TZ).strftime('%d.%m.%Y')


def periode_text(ini, fi):
    ini, fi = ini.astimezone(TZ), fi.astimezone(TZ)
    if ini.date() == fi.date():
        return f"{el_dia(ini)}, de {ini.strftime('%H.%M')} a {fi.strftime('%H.%M')} h"
    return (("De l'" if apostrofa(ini) else "Del ") + dh(ini) +
            (" a l'" if apostrofa(fi) else " al ") + dh(fi))


def aemet_avisos(traduccions):
    r = requests.get(AEMET_RSS, headers={**CAPCALERES, "Accept": "application/xml"}, timeout=60)
    r.raise_for_status()
    canal = ET.fromstring(r.content).find("channel")
    links = [(it.findtext("link") or "").strip() for it in (canal.findall("item") if canal is not None else [])[:30]]
    avisos = []
    # 05.11.2026: missatges de retirada o anul·lació (per no conservar un avís que l'AEMET ha tret).
    retirats = {"ids": set(), "codis": set()}
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
        tipus = (arrel.findtext(q("msgType")) or "").strip().lower()
        if tipus == "cancel" or (fi - ini).total_seconds() <= 60:
            for ref in (arrel.findtext(q("references")) or "").split():
                parts = ref.split(",")
                retirats["ids"].add(parts[1] if len(parts) > 1 else parts[0])
            retirats["codis"].add((fen[0], ini.astimezone(TZ).strftime("%Y-%m-%d")))
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
    return sorted(unics.values(), key=lambda a: (a["inici"], -METEO_RANG[a["gravetat"]], a["fenomen"])), retirats


def _solapen(a, b):
    try:
        return (dt.datetime.fromisoformat(a["inici"]) < dt.datetime.fromisoformat(b["fi"])
                and dt.datetime.fromisoformat(b["inici"]) < dt.datetime.fromisoformat(a["fi"]))
    except (KeyError, ValueError):
        return False


def conserva_aemet(nous, vells, retirats):
    """05.11.2026: un avís de l'AEMET es manté fins que n'han passat les hores, encara que
    desaparegui del canal RSS. Es treu si ha caducat, si l'AEMET l'ha retirat o anul·lat,
    o si un avís nou del mateix fenomen el substitueix (se solapen en el temps)."""
    ara_utc = dt.datetime.now(dt.timezone.utc)
    sortida = list(nous)
    for v in vells or []:
        try:
            if dt.datetime.fromisoformat(v["fi"]) <= ara_utc:
                continue
        except (KeyError, ValueError):
            continue
        if v.get("id") in retirats["ids"] or (v.get("codi"), v.get("dia")) in retirats["codis"]:
            continue
        if any(n.get("id") == v.get("id") or (n.get("codi") == v.get("codi") and _solapen(n, v)) for n in nous):
            continue
        sortida.append(v)
    return sorted(sortida, key=lambda a: (a["inici"], -METEO_RANG.get(a.get("gravetat"), 0), a.get("fenomen", "")))


def conserva_meteocat(nou, vell):
    """05.11.2026: els avisos de Meteocat (per dia) es mantenen fins que acaba el dia de
    l'avís, encara que la còpia de l'avisador ja no els porti. Si el mateix dia i fenomen
    torna a sortir, mana el nou."""
    avui = ara().strftime("%Y-%m-%d")
    grups = list(nou.get("grups") or [])
    claus = {(str(g.get("dia", "")), g.get("fenomen")) for g in grups}
    for g in ((vell or {}).get("grups") or []):
        if str(g.get("dia", "")) >= avui and (str(g.get("dia", "")), g.get("fenomen")) not in claus:
            grups.append(g)
    nou["grups"] = sorted(grups, key=lambda g: (str(g.get("dia", "")), -METEO_RANG.get(g.get("gravetat"), 0)))
    return nou


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
        llista, retirats = aemet_avisos(_RegistreTraduccions(traduccions, originals))
        for a in llista:
            a["original"] = originals.get(a["comentari"], "")
        sortida["aemet"] = conserva_aemet(llista, vell.get("aemet"), retirats)
        sortida["aemetConsultat"] = ara().isoformat()
    except Exception as e:
        print(f"   AEMET: {e}", file=sys.stderr)
        sortida["aemet"] = vell.get("aemet")
        sortida["aemetConsultat"] = vell.get("aemetConsultat")
    # Meteocat (SMP): la còpia que desa l'avisador.
    try:
        r = requests.get(SMP_URL, params={"v": int(ara().timestamp())}, headers=CAPCALERES, timeout=30)
        if r.status_code == 404:
            sortida["meteocat"] = conserva_meteocat({"consultat": vell["meteocat"].get("consultat"), "grups": []}, vell.get("meteocat")) if vell.get("meteocat") else None
        else:
            r.raise_for_status()
            d = r.json()
            avui = ara().strftime("%Y-%m-%d")
            d["grups"] = [g for g in (d.get("grups") or []) if str(g.get("dia", "")) >= avui]
            sortida["meteocat"] = conserva_meteocat(d, vell.get("meteocat"))
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


# --- TERRATRÈMOLS (IGN + EMSC, 01.11.2026) ------------------------------------------------------
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


SISMES_EMSC_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
SISMES_EMSC_REGIONS = {
    "PYRENEES": "Pirineus", "FRANCE": "França", "SPAIN": "Espanya", "SOUTHERN FRANCE": "sud de França",
    "WESTERN MEDITERRANEAN SEA": "Mediterrània occidental", "GULF OF LION": "golf de Lleó",
    "EASTERN PYRENEES": "Pirineus orientals", "PYRENEES-ORIENTALES, FRANCE": "Pirineus Orientals (França)",
    "CATALONIA, SPAIN": "Catalunya", "BALEARIC ISLANDS, SPAIN": "Illes Balears", "ANDORRA": "Andorra",
}


def sismes_emsc():
    """Terratrèmols de l'EMSC dels darrers 10 dies a menys de SISMES_RADI_KM (mateix format que els de l'IGN)."""
    inici = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S")
    r = requests.get(SISMES_EMSC_URL, headers=CAPCALERES, timeout=60, params={
        "format": "json", "limit": 500, "lat": BISBAL[0], "lon": BISBAL[1],
        "maxradius": round(SISMES_RADI_KM / 111.2, 2), "start": inici})
    if r.status_code == 204:
        return []
    r.raise_for_status()
    sortida = []
    for f in r.json().get("features", []):
        p = f.get("properties") or {}
        lat, lon, mag = num(p.get("lat")), num(p.get("lon")), num(p.get("mag"))
        unid = p.get("unid") or f.get("id")
        if not unid or lat is None or lon is None or mag is None or not p.get("time"):
            continue
        d = dt.datetime.fromisoformat(str(p["time"]).replace("Z", "+00:00"))
        km = distancia_km(*BISBAL, lat, lon)
        regio = str(p.get("flynn_region") or "").strip().upper()
        sortida.append({
            "id": "emsc:" + unid, "font": "EMSC", "magnitud": mag,
            "lloc": SISMES_EMSC_REGIONS.get(regio, regio.title()), "iso": d.isoformat(), "data": dh(d),
            "lat": round(lat, 4), "lon": round(lon, 4), "km": round(km), "rumb": rumb(*BISBAL, lat, lon),
            "enllac": "https://www.seismicportal.eu/eventdetails.html?unid=" + unid,
            "avis": (km < 50 and mag >= 2.5) or (km < 150 and mag >= 4),
        })
    return sortida


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
    # 01.11.2026: reforç amb l'EMSC (França, golf de Lleó, Mediterrània), com al bot
    # d'alertes. Els que l'IGN ja dona (menys de 90 s i 40 km de diferència) es descarten.
    try:
        for x in sismes_emsc():
            if not any(abs(dt.datetime.fromisoformat(y["iso"]).timestamp() - dt.datetime.fromisoformat(x["iso"]).timestamp()) <= 90
                       and distancia_km(y["lat"], y["lon"], x["lat"], x["lon"]) <= 40 for y in nous.values()):
                nous[x["id"]] = x
    except Exception as e:  # si l'EMSC no respon, el bloc continua només amb l'IGN
        print("Terratrèmols (EMSC):", e)
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
# -----------------------------------------------------------------------------
# PLUJA D'AHIR (07.11.2026): la precipitació del dia anterior a les estacions
# automàtiques del Meteocat (XEMA) del Baix Empordà, amb la de la Bisbal primer.
# Dels cinc municipis de referència, només la Bisbal en té una d'activa (la de
# Monells es va desmantellar el 2021). Dades obertes: lectures semihoràries.
# El dia meteorològic és de 00.00 a 24.00 h en temps universal, com al Meteocat.
# -----------------------------------------------------------------------------
XEMA_ESTACIONS_URL = "https://analisi.transparenciacatalunya.cat/resource/yqwd-vj5e.json"
XEMA_DADES_URL = "https://analisi.transparenciacatalunya.cat/resource/nzvn-apee.json"
XEMA_COMARCA = "10"           # Baix Empordà
XEMA_BISBAL = "DF"


def pluja_ahir():
    r = requests.get(XEMA_ESTACIONS_URL, params={"$where": f"codi_comarca='{XEMA_COMARCA}' AND codi_estat_ema='2'",
                                                 "$limit": 100}, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    estacions = {}
    for e in r.json():
        try:
            lat, lon = float(e["latitud"]), float(e["longitud"])
        except (KeyError, ValueError):
            continue
        estacions[e["codi_estacio"]] = {"codi": e["codi_estacio"], "nom": e.get("nom_estacio", ""),
                                        "municipi": e.get("nom_municipi", ""), "lat": lat, "lon": lon,
                                        "km": round(distancia_km(BISBAL[0], BISBAL[1], lat, lon), 1)}
    if not estacions:
        return None
    ahir = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).date()
    des, fins = f"{ahir}T00:00:00", f"{ahir + dt.timedelta(days=1)}T00:00:00"
    codis = ",".join(f"'{c}'" for c in estacions)
    r = requests.get(XEMA_DADES_URL, params={
        "$select": "codi_estacio, sum(valor_lectura) as mm, count(*) as n",
        "$where": f"codi_variable='35' AND codi_estacio in({codis}) AND data_lectura>='{des}' AND data_lectura<'{fins}'",
        "$group": "codi_estacio", "$limit": 100}, headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    llista = []
    for x in r.json():
        e = estacions.get(x.get("codi_estacio"))
        if not e:
            continue
        try:
            mm, n = float(x["mm"]), int(x["n"])
        except (KeyError, ValueError):
            continue
        llista.append({**e, "mm": round(mm, 1), "complet": n >= 46})
    if not llista:
        return None
    llista.sort(key=lambda e: (e["codi"] != XEMA_BISBAL, e["km"]))
    resultat = {"dia": ahir.strftime("%d.%m.%Y"), "estacions": llista}
    # 07.11.2026: les estacions de casa (Meteoclimàtic i la del Meteocat a la depuradora)
    try:
        resultat["properes"] = pluja_properes(next((e for e in llista if e["codi"] == XEMA_BISBAL), None))
    except Exception as ex:
        print(f"   Meteoclimàtic: {ex}", file=sys.stderr)
    return resultat


# --- PLUJA D'AHIR A LES ESTACIONS DE METEOCLIMÀTIC (07.11.2026) ----------------
# Meteoclimàtic no publica el total d'ahir. A la fitxa hi ha «Hoy», «Mes» i «Año»:
# «Año − Hoy» és la pluja acumulada fins a acabar el dia anterior, de manera que
# la resta entre el valor d'avui i el d'ahir dona exactament la pluja d'ahir.
# Cada consulta es desa a dades/pluja/meteoclimatic.json (deu dies). Si falta el
# valor d'ahir (o l'1 de gener, que l'any torna a zero), es pren el darrer «Hoy»
# que es va llegir ahir. L'«Episodio precipitación» (dies seguits de pluja) va de
# comprovació a la fitxa, però no diu quin dia va acabar l'episodi.
# Les fitxes donen la posició en graus i minuts (uns 1,5 km de marge): les que
# tenen un punt exacte el porten a «punt».
METEOCLIMATIC = [
    {"codi": "ESCAT1700000017100A", "nom": "la Bisbal · Terracotta Museu", "lloc": "la Bisbal d'Empordà",
     "punt": (41.960, 3.043)},   # la que publica Weather Underground (ILABIS21)
    {"codi": "ESCAT1700000017100B", "nom": "la Bisbal · Jesús Martí", "lloc": "la Bisbal d'Empordà",
     "punt": (41.954, 3.039)},   # la que publica Weather Underground (ILABIS19)
    # 08.11.2026: «punt» és una ubicació aproximada (arrodonida, per privacitat) que dona La TdG;
    # només les que en tenen surten al mapa.
    {"codi": "ESCAT1700000017100C", "nom": "la Bisbal · Antoni Ruiz", "lloc": "la Bisbal d'Empordà",
     "punt": (41.962, 3.040)},   # la que publica Weather Underground (ILABIS22, «les Voltes»)
    {"codi": "ESCAT1700000017116A", "nom": "Puig d'Arques (Gavarres)", "lloc": "Cruïlles, Monells i Sant Sadurní de l'Heura"},
]
METEOCLIMATIC_URL = "https://www.meteoclimatic.net/perfil/{}"
METEOCLIMATIC_REGISTRE = DADES / "pluja" / "meteoclimatic.json"
PLUJA_REGISTRE = None


# --- PLUJA D'AHIR A LES ESTACIONS DE NETATMO (07.11.2026) ----------------------
# API pública de Netatmo (getpublicdata) amb l'app «La TdG pluja» (secrets
# NETATMO_CLIENT_ID, NETATMO_CLIENT_SECRET i NETATMO_REFRESH_TOKEN). Dona la
# posició exacta i la pluja de les últimes 24 hores: la lectura feta just després
# de mitjanit (hora local) és la pluja d'ahir. Les estacions que no surten, que no
# tenen pluviòmetre o que no envien dades, no surten al bloc.
NETATMO = {
    "70:ee:50:05:f3:92": "Cruïlles, Monells i Sant Sadurní de l'Heura",
    "70:ee:50:b9:6f:42": "Canapost",
    "70:ee:50:15:e6:f0": "les Gavarres",
    "70:ee:50:a4:31:ca": "la Bisbal · sud",
    "70:ee:50:83:9e:10": "la Bisbal · centre",
    "70:ee:50:a4:73:e6": "la Bisbal · est",
    "70:ee:50:71:41:72": "la Bisbal · Netatmo",
    "70:ee:50:83:77:32": "Forallac (tocant a la Bisbal)",
}
NETATMO_CAIXA = {"lat_ne": 42.0, "lon_ne": 3.11, "lat_sw": 41.88, "lon_sw": 2.94}


def netatmo_properes(registre, avui, ahir):
    if not os.environ.get("NETATMO_REFRESH_TOKEN"):
        return []
    refresh = os.environ["NETATMO_REFRESH_TOKEN"].strip()
    r = requests.post("https://api.netatmo.com/oauth2/token", data={
        "grant_type": "refresh_token", "refresh_token": refresh,
        "client_id": os.environ.get("NETATMO_CLIENT_ID", "").strip(),
        "client_secret": os.environ.get("NETATMO_CLIENT_SECRET", "").strip()}, timeout=30)
    r.raise_for_status()
    tok = r.json()
    if tok.get("refresh_token") and tok["refresh_token"] != refresh:
        print("   ⚠️ Netatmo ha canviat el refresh token: cal actualitzar el secret NETATMO_REFRESH_TOKEN", file=sys.stderr)
    r = requests.get("https://api.netatmo.com/api/getpublicdata", params={**NETATMO_CAIXA, "filter": "false"},
                     headers={"Authorization": "Bearer " + tok["access_token"]}, timeout=60)
    r.raise_for_status()
    sortida = []
    for e in r.json().get("body", []):
        nom = NETATMO.get(e.get("_id"))
        if not nom:
            continue
        pluja = next((m for m in (e.get("measures") or {}).values() if "rain_24h" in m), None)
        loc = (e.get("place") or {}).get("location") or [None, None]
        dies = registre.setdefault("netatmo:" + e["_id"], {})
        if pluja and pluja.get("rain_timeutc") and pluja.get("rain_24h") is not None:
            h = dt.datetime.fromtimestamp(pluja["rain_timeutc"], dt.timezone.utc).astimezone(TZ)
            # La primera lectura després de mitjanit (fins a les 3 h) és la del dia anterior.
            if h.date() == avui and h.hour < 3:
                d = dies.get(ahir.isoformat())
                if not d or d.get("hora", "99") > h.strftime("%H.%M"):
                    dies[ahir.isoformat()] = {"mm": round(pluja["rain_24h"], 1), "hora": h.strftime("%H.%M")}
        for k in [k for k in dies if k < (avui - dt.timedelta(days=10)).isoformat()]:
            del dies[k]
        d = dies.get(ahir.isoformat())
        if not d or loc[1] is None:
            continue   # sense pluviòmetre o sense la dada d'ahir: fora del bloc
        sortida.append({"nom": nom, "lloc": (e.get("place") or {}).get("city") or "", "xarxa": "Netatmo",
                        "lat": round(loc[1], 5), "lon": round(loc[0], 5), "alt": (e.get("place") or {}).get("altitude"),
                        "exacte": True, "mm": d["mm"], "complet": d["hora"] < "02.00",   # 08.11.2026: abans de les 2 h, completa
                        "url": f"https://weathermap.netatmo.com/?stationid={e['_id']}&zoom=14"})
    return sortida


def meteoclimatic_fitxa(codi):
    import html as htmllib
    r = requests.get(METEOCLIMATIC_URL.format(codi), timeout=40,
                     headers={**CAPCALERES, "Accept": "text/html", "Accept-Language": "es"})
    r.raise_for_status()
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
    t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", t)))
    fitxa = {}
    m = re.search(r"(\d+)\s*[º°]\s*(\d+)'\s*([NS])\s+0*(\d+)\s*[º°]\s*(\d+)'\s*([EW])\s*-\s*(\d+)\s*m", t)
    if m:
        lat = int(m[1]) + int(m[2]) / 60
        lon = int(m[4]) + int(m[5]) / 60
        fitxa.update(lat=round(-lat if m[3] == "S" else lat, 4), lon=round(-lon if m[6] == "W" else lon, 4), alt=int(m[7]))
    m = re.search(r"actualizaci[oó]n\s*(\d\d)-(\d\d)-(\d{4})\s+(\d\d):(\d\d)\s*UTC", t)
    if m:
        fitxa["hora"] = dt.datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4]), int(m[5]), tzinfo=dt.timezone.utc).astimezone(TZ)
    # Les taules surten intercalades per files: «Total Hoy … Mes … Año … (*)»; a cada
    # fila, la pluja és l'últim número (la darrera columna).
    i = t.find("Total Hoy")
    f = t.find("(*)", i) if i >= 0 else -1
    if i >= 0 and f > i:
        tros = t[i + 6:f]
        m1 = re.search(r"\sMes\s", tros)
        m2 = re.search(r"\sA[ñn]o\s", tros)
        if m1 and m2 and m2.start() > m1.start():
            for clau, fila in (("hoy", tros[:m1.start()]), ("mes", tros[m1.start():m2.start()]), ("any", tros[m2.start():])):
                nums = re.findall(r"-?\d+(?:\.\d+)?", fila)
                if nums:
                    fitxa[clau] = float(nums[-1])
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*mm\s*\(\s*(\d+)\s*D[ií]a", t)
    if m:
        fitxa["episodi"] = {"mm": float(m[1].replace(",", ".")), "dies": int(m[2])}
    return fitxa


def pluja_properes(meteocat):
    registre = llegeix(METEOCLIMATIC_REGISTRE, {})
    avui = ara().date()
    ahir = avui - dt.timedelta(days=1)
    properes = []
    if meteocat:
        properes.append({"nom": "la Bisbal · depuradora", "lloc": "la Bisbal d'Empordà", "xarxa": "Meteocat",
                         "lat": meteocat["lat"], "lon": meteocat["lon"], "mm": meteocat["mm"],
                         "complet": meteocat["complet"], "exacte": True,
                         "url": "https://www.meteo.cat/observacions/xema/dades?codi=DF"})
    for e in METEOCLIMATIC:
        dies = registre.setdefault(e["codi"], {})
        fitxa = {}
        try:
            fitxa = meteoclimatic_fitxa(e["codi"])
        except Exception as ex:
            print(f"   Meteoclimàtic {e['codi']}: {ex}", file=sys.stderr)
        h = fitxa.get("hora")
        # Només compta una fitxa actualitzada fa menys de 3 hores.
        if h and (ara() - h).total_seconds() < 3 * 3600 and "any" in fitxa and "hoy" in fitxa:
            d = dies.setdefault(h.date().isoformat(), {})
            d["fins"] = round(fitxa["any"] - fitxa["hoy"], 1)
            d["hoy"] = max(d.get("hoy", 0), fitxa["hoy"])
            d["hora"] = h.strftime("%H.%M")
        if fitxa.get("lat") is not None:
            dies["_lloc"] = {"lat": fitxa["lat"], "lon": fitxa["lon"], "alt": fitxa.get("alt")}
        lloc = dict(dies.get("_lloc") or {})
        if e.get("punt"):
            lloc.update(lat=e["punt"][0], lon=e["punt"][1])
        a, b = dies.get(avui.isoformat(), {}), dies.get(ahir.isoformat(), {})
        mm, complet = None, False
        if "fins" in a and "fins" in b and not (avui.month == 1 and avui.day == 1) and a["fins"] >= b["fins"]:
            mm, complet = round(a["fins"] - b["fins"], 1), True
        elif "hoy" in b:
            # Darrera lectura d'ahir: completa si és de les 23 h o més tard.
            mm, complet = b["hoy"], b.get("hora", "00.00") >= "23.00"
        if mm is None:
            continue   # 07.11.2026: l'estació que no dona dades, fora del bloc
        properes.append({"nom": e["nom"], "lloc": e["lloc"], "xarxa": "Meteoclimàtic",
                         "lat": lloc.get("lat"), "lon": lloc.get("lon"), "alt": lloc.get("alt"), "exacte": False,
                         "aMapa": bool(e.get("punt")),
                         "mm": mm, "complet": complet, "episodi": fitxa.get("episodi"),
                         "url": METEOCLIMATIC_URL.format(e["codi"])})
        # Es guarden deu dies.
        for k in [k for k in dies if not k.startswith("_") and k < (avui - dt.timedelta(days=10)).isoformat()]:
            del dies[k]
    try:
        properes += netatmo_properes(registre, avui, ahir)
    except Exception as ex:
        print(f"   Netatmo: {ex}", file=sys.stderr)
    # El fitxer es desa a fusiona(): entre calcula() i fusiona() el workflow torna a
    # deixar el repositori com és a GitHub i s'esborraria.
    global PLUJA_REGISTRE
    PLUJA_REGISTRE = registre
    return properes


RIUS_ESTATS = ["normalitat", "activació", "moderat", "alt", "molt alt", "excepcional", "excepcional (graó superior)"]


def rius():
    sortida = []
    for e in RIUS_ESTACIONS:
        try:
            sensors = sentilo_sensors(e["codi"])
            cabal, nivell = sentilo_serie(sensors.get("cabal"), 25), sentilo_serie(sensors.get("nivell"), 25)
        except Exception as ex:
            print(f"   riu {e['codi']}: {ex}", file=sys.stderr)
            continue
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
        # Mitjana per hora (per a la gràfica petita de l'evolució).
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


# 04.11.2026: càmeres de la C-66 del Servei Català de Trànsit. Quan una càmera està
# desconnectada, el servidor no falla: torna una imatge grisa «IMATGES NO DISPONIBLES»
# (sempre la mateixa) i, per a un nom de càmera que no existeix, una altra de fixa.
# Es mira si la imatge és una d'aquestes i el tauler només mostra les càmeres actives.
CAMERES_TRANSIT = ["cb24", "cb25"]
CAMERA_URL = "https://mct.gencat.cat/mct2bo/TransitCamera?nom={}.jpg&visualitzacio=imatge"
CAMERA_NO_DISPONIBLE = {
    "ad18f7f85fe7a3bb9e5049163e301cb825b7e978",   # «IMATGES NO DISPONIBLES» (704×480)
    "de8a04543db1f6d115c9f8e4aa78b07f41c2e3aa",   # càmera inexistent (720×534)
}


def cameres():
    import hashlib
    resultat = {}
    for nom in CAMERES_TRANSIT:
        r = requests.get(CAMERA_URL.format(nom), headers=CAPCALERES, timeout=30)
        r.raise_for_status()   # si el servidor no respon, es manté l'estat anterior
        activa = (r.headers.get("Content-Type", "").startswith("image/")
                  and len(r.content) > 2000
                  and hashlib.sha1(r.content).hexdigest() not in CAMERA_NO_DISPONIBLE)
        resultat[nom] = activa
        print(f"  càmera {nom}: {'activa' if activa else 'desconnectada'}")
    return resultat


# -----------------------------------------------------------------------------
# CALCULA I FUSIONA
# -----------------------------------------------------------------------------
FUNCIONS = {
    "piezometres": piezometres,
    "carburants": carburants,
    "uv": uv,
    "incidencies": incidencies,
    "cameres": cameres,   # 04.11.2026
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
    "plujaAhir": pluja_ahir,   # 07.11.2026
}
UN_COP_AL_DIA = {"clima"}
# 21.10.2026: cada quants minuts com a mínim es torna a consultar un bloc.
CADA_MINUTS = {"pollen": 60, "recarrega": 7 * 24 * 60, "necrologiques": 60, "plujaAhir": 60}


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
            # 07.11.2026: la pluja d'ahir, just després de mitjanit (Netatmo)
            if nom == "plujaAhir" and moments[nom][:10] != ara().strftime("%Y-%m-%d"):
                moments[nom] = "2000-01-01T00:00:00+00:00"
            try:
                fa = (ara() - dt.datetime.fromisoformat(moments[nom])).total_seconds() / 60
                if fa < CADA_MINUTS[nom]:
                    continue
            except ValueError:
                pass
        try:
            resultat[nom] = fn()   # None vol dir «aquest bloc avui no surt»
            if nom == "recarrega" and resultat[nom] is not None:
                resultat["recarregaMapa"] = RECARREGA_PUNTS   # 05.11.2026: mapa del bloc
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
    if PLUJA_REGISTRE is not None:
        resultat["_meteoclimatic"] = PLUJA_REGISTRE   # 07.11.2026
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
    # 07.11.2026: lectures diàries de les estacions de Meteoclimàtic (pluja d'ahir)
    if isinstance(vius.get("_meteoclimatic"), dict):
        escriu(METEOCLIMATIC_REGISTRE, vius["_meteoclimatic"])
    vius.pop("_meteoclimatic", None)
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
