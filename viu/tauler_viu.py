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
# Si una font falla, es manté el valor que ja hi havia: mai es buida un bloc.
# =============================================================================

import json
import math
import re
import sys
import unicodedata
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Madrid")
ARREL = Path(__file__).resolve().parent.parent
DADES = ARREL / "dades"
TMP = Path("/tmp/tauler_viu.json")
CAPCALERES = {
    "User-Agent": "LaTdG-tauler/1.0 (+https://latdg.github.io/tauler/)",
    "Accept": "application/json",
}

BISBAL = (41.9597, 3.0386)

# Blocs que calcula aquest script (substitueixen els de l'Apps Script).
BLOCS_VIUS = ("piezometres", "carburants", "uv")


def num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def ara():
    return dt.datetime.now(TZ)


# -----------------------------------------------------------------------------
# PIEZÒMETRES (port de PiezometresTauler.gs, radi 10,6 km)
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
CARBURANTS_MUNICIPIS = re.compile(r"bisbal|corca|forallac|cruilles")
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
    t = "".join(c for c in t if not ("\u0300" <= c <= "\u036f"))
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
# ÍNDEX UV (Open-Meteo; si la previsió falla, el servei de qualitat de l'aire)
# -----------------------------------------------------------------------------
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
    base = {"latitude": BISBAL[0], "longitude": BISBAL[1],
            "timezone": "Europe/Madrid", "forecast_days": 1, "hourly": "uv_index"}
    fonts = [
        ("https://api.open-meteo.com/v1/forecast", {**base, "daily": "uv_index_max"}),
        ("https://air-quality-api.open-meteo.com/v1/air-quality", base),
    ]
    for url, params in fonts:
        try:
            r = requests.get(url, params=params, headers=CAPCALERES, timeout=30)
            r.raise_for_status()
            d = r.json()
            hores = d.get("hourly", {}).get("time", [])
            valors = d.get("hourly", {}).get("uv_index", [])
            parells = [(h, v) for h, v in zip(hores, valors) if v is not None]
            maxim = None
            if d.get("daily", {}).get("uv_index_max"):
                maxim = d["daily"]["uv_index_max"][0]
            if maxim is None and parells:
                maxim = max(v for _, v in parells)
            if maxim is None:
                continue

            valor = int(round(maxim))
            proteccio = ""
            altes = [int(h[11:13]) for h, v in parells if v >= 3]
            if altes:
                proteccio = f"entre les {min(altes)} i les {max(altes) + 1} h"
            return {"valor": valor, "categoria": categoria_uv(valor), "proteccio": proteccio}
        except Exception as e:  # es prova la font següent
            print(f"[uv] {url}: {e}", file=sys.stderr)
    return None


# -----------------------------------------------------------------------------
# CALCULA I FUSIONA
# -----------------------------------------------------------------------------
FUNCIONS = {"piezometres": piezometres, "carburants": carburants, "uv": uv}


def calcula():
    resultat = {}
    for nom, fn in FUNCIONS.items():
        try:
            valor = fn()
            if valor:
                resultat[nom] = valor
                print(f"✅ {nom}")
            else:
                print(f"— {nom}: sense dades")
        except Exception as e:
            print(f"❌ {nom}: {e}", file=sys.stderr)
    TMP.write_text(json.dumps(resultat, ensure_ascii=False), encoding="utf-8")


def llegeix(cami, defecte):
    try:
        return json.loads(cami.read_text(encoding="utf-8"))
    except Exception:
        return defecte


def escriu(cami, dades):
    cami.parent.mkdir(parents=True, exist_ok=True)
    cami.write_text(json.dumps(dades, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def fusiona():
    vius = llegeix(TMP, {})
    moment = ara()
    dia = moment.strftime("%Y-%m-%d")

    base = llegeix(DADES / "darrer.json", {})
    blocs = dict(base.get("blocs") or {})
    # Si la base és d'ahir, les aeronaus «d'avui» encara són les d'ahir.
    if base.get("dia") != dia:
        blocs.pop("aeronaus", None)

    for nom in BLOCS_VIUS:
        if nom in vius:
            blocs[nom] = vius[nom]   # si ha fallat, es queda el valor anterior

    dades = {
        "dia": dia,
        "generat": moment.strftime("%d.%m.%Y a les %H.%M h"),
        "blocs": blocs,
    }
    escriu(DADES / f"{dia}.json", dades)
    escriu(DADES / "darrer.json", dades)

    dies = llegeix(DADES / "dies.json", [])
    if dia not in dies:
        dies.append(dia)
    escriu(DADES / "dies.json", sorted(set(dies), reverse=True))
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
