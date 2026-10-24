#!/usr/bin/env python3
# =============================================================================
# ESPORTS DE LA TdG A GITHUB — 24.10.2026
#
# Substitueix la lectura de les federacions que feia el projecte «esport»
# d'Apps Script (i el Google Sheet). Escriu dades/esports.json, que llegeixen:
#   · La TdG ampliada (bloc de partits i classificacions, pàgina esports/)
#   · el guió i l'avisador d'esports (Apps Script)
#
# Fonts:
#   · Futbol (FCF): a través del Worker propi latdg-fcf (la FCF respon 403 a
#     Google i a GitHub des del 22.10.2026).
#   · Bàsquet sènior, 2a FEB: feb.es (formulari ASP.NET, com feia l'Apps Script).
#   · El que s'entra a mà (sots-25 femení, Copa d'Espanya, Lliga Catalana,
#     amistosos, correccions): dades/esports-manual.json, que s'edita amb clau a
#     latdg.github.io/tauler/esports/ (Worker latdg-agenda).
#
# Si una font falla, l'equip conserva les dades de l'execució anterior.
#
#   python esports/esports.py            # llegeix tot i escriu dades/esports.json
#   python esports/esports.py --prova    # com l'anterior, però sense escriure
# =============================================================================

import datetime as dt
import html as htmlmod
import json
import os
import re
import sys
import time
import unicodedata
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Madrid")
ARREL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIDA = os.path.join(ARREL, "dades", "esports.json")
MANUAL = os.path.join(ARREL, "dades", "esports-manual.json")
WORKER_FCF = "https://latdg-fcf.ignasicorney.workers.dev/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

# Equips seguits. «full» és el nom de la pestanya que tenia al Sheet: el guió i
# l'avisador el continuen fent servir per trobar l'equip.
EQUIPS = [
    {"id": "atletic_bisbalenc", "nom": "Atlètic Bisbalenc", "esport": "Futbol", "font": "fcf",
     "categoria": "2a Catalana, grup 1", "competicio": "2a Catalana", "grup": "Grup 1",
     "grupId": "58161863", "codi": "33220"},
    {"id": "monells_a", "nom": "Monells A", "esport": "Futbol", "font": "fcf",
     "categoria": "4a Catalana, grup 2", "competicio": "4a Catalana", "grup": "Grup 2",
     "grupId": "58161891", "codi": "36200"},
    {"id": "monells_b", "nom": "Monells B", "esport": "Futbol", "font": "fcf",
     "categoria": "4a Catalana, grup 5", "competicio": "4a Catalana", "grup": "Grup 5",
     "grupId": "58161893", "codi": "54312692"},
    {"id": "la_pera", "nom": "La Pera", "esport": "Futbol", "font": "fcf",
     "categoria": "4a Catalana, grup 2", "competicio": "4a Catalana", "grup": "Grup 2",
     "grupId": "58161891", "codi": "36734"},
    {"id": "la_pera_femeni", "nom": "La Pera femení", "esport": "Futbol", "font": "fcf",
     "categoria": "2a Divisió femenina", "competicio": "2a Divisió femenina", "grup": "",
     "grupId": "58162320", "codi": "15549744"},
    {"id": "sol_girones", "nom": "Sol Gironès Bisbal Bàsquet", "esport": "Bàsquet", "font": "feb",
     "categoria": "2a FEB", "competicio": "2a FEB", "grup": "Lliga regular B"},
    {"id": "sol_girones_sots25", "nom": "Sol Gironès Bisbal Bàsquet sots-25 femení", "esport": "Bàsquet",
     "font": "manual", "categoria": "Copa Catalunya sots-25 femení", "competicio": "C.C. Sots-25 Femení",
     "grup": "U25 Femení 01"},
]

CAP_PARTITS = ["CLAU_PARTIT", "Equip", "Competició", "Grup", "Jornada", "Data", "Hora", "Local/Visitant",
               "Rival", "Resultat", "Estat", "Camp/Pavelló", "Font", "ID font", "Última actualització"]
CAP_CLASS_FUTBOL = ["Competició", "Grup", "Posició", "Equip", "PJ", "PG", "PE", "PP", "PF", "PC", "Punts",
                    "Ràtio / Racha", "Font", "Última actualització"]
CAP_CLASS_BASQUET = ["Competició", "Grup", "Posició", "Equip", "PJ", "PG", "PP", "PF", "PC", "DIF", "%", "Racha",
                     "Font", "Última actualització"]


# -----------------------------------------------------------------------------
# Utilitats
# -----------------------------------------------------------------------------
def ara():
    return dt.datetime.now(TZ)


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn").lower())


def text_html(s):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", str(s or "")))).strip()


def hora_neta(s):
    m = re.search(r"(\d{1,2})[:.](\d{2})", str(s or ""))
    if not m:
        return ""
    h = f"{int(m.group(1)):02d}:{m.group(2)}"
    return "" if h == "00:00" else h


def data_ca(iso):
    """'2026-10-24' -> '24/10/2026' (format que llegeixen el guió i l'avisador)."""
    if not iso:
        return ""
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def pct_ca(x):
    return f"{x * 100:.2f}".replace(".", ",") + "%"


def llegeix_json(cami, perdefecte):
    try:
        with open(cami, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return perdefecte


# -----------------------------------------------------------------------------
# FUTBOL — FCF (via Worker latdg-fcf)
# -----------------------------------------------------------------------------
_cache_fcf = {}


def fcf(tipus, grup_id):
    clau = (tipus, grup_id)
    if clau not in _cache_fcf:
        r = requests.get(WORKER_FCF, params={"tipus": tipus, "grupId": grup_id}, timeout=40,
                         headers={"User-Agent": UA})
        r.raise_for_status()
        _cache_fcf[clau] = r.json()
    return _cache_fcf[clau]


def ratxa_fcf(form):
    if not isinstance(form, list):
        return ""
    llista = []
    for f in form:
        if isinstance(f, dict):
            llista.append((str(f.get("date") or ""), str(f.get("result") or "").strip()))
        else:
            llista.append(("", str(f or "").strip()))
    return "-".join(r for _, r in sorted(llista) if r)


def num(v):
    try:
        f = float(str(v).replace(",", "."))
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return v


def llegeix_futbol(eq):
    dades = fcf("partidos", eq["grupId"])
    partits = []
    for jornada, llista in (dades or {}).items():
        if not isinstance(llista, list):
            continue
        for m in llista:
            casa, fora = str(m.get("CODEQUIPO_CASA")), str(m.get("CODEQUIPO_FUERA"))
            if eq["codi"] not in (casa, fora):
                continue
            local = casa == eq["codi"]
            mt = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]+(\d{2}):(\d{2}))?", str(m.get("COMIENZO1") or ""))
            jugat = str(m.get("CERRADA")) == "1"
            gc, gf = m.get("GOLES_CASA"), m.get("GOLES_FUERA")
            resultat = ""
            if jugat and gc is not None and gf is not None:
                resultat = f"{gc} - {gf}" if local else f"{gf} - {gc}"
            partits.append({
                "clau": "FCF-" + str(m.get("CODACTA") or ""),
                "competicio": eq["competicio"], "grup": eq["grup"], "jornada": str(jornada),
                "data": f"{mt.group(1)}-{mt.group(2)}-{mt.group(3)}" if mt else "",
                "hora": hora_neta(f"{mt.group(4)}:{mt.group(5)}") if mt and mt.group(4) else "",
                "localVisitant": "Local" if local else "Visitant",
                "rival": str(m.get("NOMBRE_FUERA") if local else m.get("NOMBRE_CASA") or "").strip(),
                "resultat": resultat, "estat": "Finalitzat" if jugat else "Programat",
                "camp": str(m.get("CAMPO") or "").strip(), "font": "FCF (via latdg-fcf)",
                "idFont": str(m.get("CODACTA") or ""),
            })
    if not partits:
        raise RuntimeError("la FCF no ha donat cap partit de l'equip")

    cls = fcf("classificacio", eq["grupId"]).get("data") or []
    files = []
    for r in cls:
        team = r.get("team") or {}
        files.append({
            "pos": num(r.get("position")), "equip": str(team.get("name") or "").strip(),
            "pj": num(r.get("played")), "pg": num(r.get("won")), "pe": num(r.get("drawn")),
            "pp": num(r.get("lost")), "pf": num(r.get("goalsFor")), "pc": num(r.get("goalsAgainst")),
            "punts": num(r.get("points")), "ratxa": ratxa_fcf(r.get("form")),
            "propi": str(team.get("teamId")) == eq["codi"],
        })
    return partits, {"tipus": "futbol", "files": files} if files else None


# -----------------------------------------------------------------------------
# BÀSQUET SÈNIOR — FEB (2a FEB, Lliga regular B)
# -----------------------------------------------------------------------------
FEB = {
    "url": "https://www.feb.es/segundafeb/Inicio.aspx?tabid=4",
    "urlClassificacio": "https://www.feb.es/segundafeb/Inicio.aspx?tabid=5",
    "temporada": "2026", "grup": "90000", "idBisbal": "1009441",
}

# ID de la FEB -> nom que es mostra (com a EQUIPS_FEB de l'Apps Script).
NOMS_FEB = {
    "1009133": "C.B. Zaragoza", "1010208": "Amics Castelló", "1008391": "Biele ISB",
    "1008985": "Logrobasket Logi", "1008636": "TQ-CB Prat", "1008899": "Lobe tu provincia Huesca la magia",
    "1010200": "Intermaquinas Benicarló", "1008978": "C.E. Bàsquet Llíria", "1010350": "Reina Proteínas Clavijo",
    "1010348": "Ciudad Molina Basket", "1010502": "Basket Cartagena", "1010351": "Proinbeni UPB Gandía",
    "1008706": "Class Bàsquet Sant Antoni", "1009441": "Sol Gironès Bisbal Bàsquet",
}

# Pavellons: [com el dona la FEB, com es mostra] (com a PAVELLONS_FEB de l'Apps Script).
PAVELLONS_FEB = {norm(a): b for a, b in [
    ("PABELLÓN SIGLO XXI - Zaragoza (Zaragoza)", "Pabellón Siglo XXI (Saragossa)"),
    ("PAVELLÓ MUNICIPAL D'ESPORTS - Bisbal d'Empordà, La (Girona)", "Pavelló Municipal d'Esports (la Bisbal d'Empordà)"),
    ("POL. MUNICIPAL DE AZPEITIA - Azpeitia (Guipúzcoa)", "Polideportivo Municipal de Azpeitia"),
    ("PAVELLO JOAN BUSQUETS (C.E.M. ESTRUCH) - Prat de Llobregat, El (Barcelona)", "Pavelló Joan Busquets - CEM Estruch (el Prat de Llobregat)"),
    ("PABELLON MUNICIPAL DE BENICARLO - Benicarló (Castellón)", "Pabellón Municipal de Benicarló"),
    ("Palacio de los Deportes de La Rioja - Logroño (La Rioja)", "Palacio de los Deportes de La Rioja (Logronyo)"),
    ("PALACIO DE LOS DEPORTES DE CARTAGENA - Cartagena (Murcia)", "Palacio de los Deportes de Cartagena"),
    ("Polideportivo Siroko Sa Pedrera - Sant Antoni de Portmany (Illes Balears)", "Polideportivo Siroko Sa Pedrera (Sant Antoni de Portmany)"),
    ("PAB MUNI CIUTAT CASTELLO - Castellón de la Plana/Castelló (Castellón)", "Pabellón Municipal Ciutat Castelló (Castelló de la Plana)"),
    ("0-POL. LOBETE - Logroño (La Rioja)", "Polideportivo Lobete (Logronyo)"),
    ("PALACIO MUNICIPAL DE LOS DEPORTES - Huesca (Huesca)", "Palacio Municipal de los Deportes (Osca)"),
    ("PABELLÓN PLA DEL ARC - Lliria (Valencia)", "Pabellón Pla del Arc (Llíria)"),
    ("PABELLON SERRERIAS - Molina de Segura (Murcia)", "Pabellón Serrerías (Molina de Segura)"),
    ("PABELLON MUNICIPAL DE GANDIA - Gandía (Valencia)", "Pabellón Municipal de Gandía"),
]}


def pavello_net(brut):
    t = re.sub(r"\s+", " ", str(brut or "")).strip()
    if not t:
        return ""
    return PAVELLONS_FEB.get(norm(t)) or re.sub(r"^\d+\s*-\s*", "", t)


def feb_seleccionat(h, id_select):
    s = re.search(r'<select[^>]*id="' + id_select + r'"[^>]*>([\s\S]*?)</select>', h)
    if not s:
        return ""
    opcions = re.findall(r"<option[^>]*>", s.group(1))
    for o in opcions:
        if re.search(r"selected", o, re.I):
            v = re.search(r'value="([^"]*)"', o)
            return v.group(1) if v else ""
    v = re.search(r'value="([^"]*)"', opcions[0]) if opcions else None
    return v.group(1) if v else ""


def feb_ocult(h, nom):
    m = re.search(r'<input[^>]*name="' + re.escape(nom) + r'"[^>]*value="([^"]*)"', h)
    return htmlmod.unescape(m.group(1)) if m else ""


def feb_postback(ses, h, target, canvis, url):
    payload = {
        "__EVENTTARGET": target, "__EVENTARGUMENT": "", "__LASTFOCUS": "",
        "__VIEWSTATE": feb_ocult(h, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": feb_ocult(h, "__VIEWSTATEGENERATOR"),
        "__EVENTVALIDATION": feb_ocult(h, "__EVENTVALIDATION"),
        "_ctl0:temporadasDropDownList": feb_seleccionat(h, "_ctl0_temporadasDropDownList") or FEB["temporada"],
        "_ctl0:gruposDropDownList": feb_seleccionat(h, "_ctl0_gruposDropDownList"),
        "_ctl0:jornadasDropDownList": feb_seleccionat(h, "_ctl0_jornadasDropDownList"),
    }
    payload.update(canvis)
    r = ses.post(url, data=payload, timeout=60, headers={"Referer": url})
    r.raise_for_status()
    return r.text


def feb_jornades(h):
    s = re.search(r'<select[^>]*id="_ctl0_jornadasDropDownList"[^>]*>([\s\S]*?)</select>', h)
    if not s:
        return []
    return [{"id": m.group(1), "num": int(m.group(2)),
             "data": f"{m.group(5)}-{m.group(4)}-{m.group(3)}" if m.group(3) else None}
            for m in re.finditer(r'<option[^>]*value="([^"]*)"[^>]*>\s*Jornada\s+(\d+)(?:\s*\((\d{2})/(\d{2})/(\d{4})\))?', s.group(1))]


def feb_partits_pagina(h):
    sortida = []
    for b in h.split('<div class="nodo">')[1:]:
        pid = re.search(r'class="wrap-resultado-info-ficha"\s+id="(\d+)"', b)
        f = re.search(r'class="fecha-label">\s*D.{1,3}a:\s*(\d{2})/(\d{2})/(\d{4})(?:\s*/\s*Hora:\s*(\d{1,2}):(\d{2}))?', b)
        loc = re.search(r'class="equipo local"[\s\S]*?Equipo\.aspx\?i=(\d+)"[^>]*>([^<]*)<', b)
        vis = re.search(r'class="equipo visitante"[\s\S]*?Equipo\.aspx\?i=(\d+)"[^>]*>([^<]*)<', b)
        if not (pid and f and loc and vis):
            continue
        resultat = None
        rb = re.search(r'<div class="resultado">([\s\S]*?)</div>', b)
        if rb and "noScore" not in rb.group(1):
            rm = re.search(r"(\d+)\s*-\s*(\d+)", re.sub(r"<[^>]*>", " ", rb.group(1)))
            if rm and not (int(rm.group(1)) == 0 and int(rm.group(2)) == 0):
                resultat = (int(rm.group(1)), int(rm.group(2)))
        camp = re.search(r'class="cancha"><label>Campo</label>\s*([^<]*)<', b)
        sortida.append({
            "id": pid.group(1), "data": f"{f.group(3)}-{f.group(2)}-{f.group(1)}",
            "hora": hora_neta(f"{f.group(4)}:{f.group(5)}") if f.group(4) else "",
            "local": (loc.group(1), htmlmod.unescape(loc.group(2)).strip()),
            "visitant": (vis.group(1), htmlmod.unescape(vis.group(2)).strip()),
            "camp": htmlmod.unescape(camp.group(1)).strip() if camp else "", "resultat": resultat,
        })
    return sortida


def feb_sessio():
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def llegeix_feb(eq):
    ses = feb_sessio()
    h = ses.get(FEB["url"], timeout=60).text
    h = feb_postback(ses, h, "_ctl0$gruposDropDownList", {"_ctl0:gruposDropDownList": FEB["grup"]}, FEB["url"])
    if feb_seleccionat(h, "_ctl0_gruposDropDownList") != FEB["grup"]:
        raise RuntimeError("la FEB no ha canviat al grup B")
    jornades = feb_jornades(h)
    if not jornades:
        raise RuntimeError("no hi ha la llista de jornades de la FEB")

    partits = []
    for j in jornades:
        if feb_seleccionat(h, "_ctl0_jornadasDropDownList") != j["id"]:
            time.sleep(0.25)
            h = feb_postback(ses, h, "_ctl0$jornadasDropDownList", {"_ctl0:jornadasDropDownList": j["id"]}, FEB["url"])
        for p in feb_partits_pagina(h):
            if FEB["idBisbal"] not in (p["local"][0], p["visitant"][0]):
                continue
            local = p["local"][0] == FEB["idBisbal"]
            rival_id, rival_nom = p["visitant"] if local else p["local"]
            res = ""
            if p["resultat"]:
                a, b = p["resultat"]
                res = f"{a} - {b}" if local else f"{b} - {a}"
            partits.append({
                "clau": "FEB-" + p["id"], "competicio": eq["competicio"], "grup": eq["grup"],
                "jornada": str(j["num"]), "data": p["data"], "hora": p["hora"],
                "localVisitant": "Local" if local else "Visitant",
                "rival": NOMS_FEB.get(rival_id) or rival_nom.title(),
                "resultat": res, "estat": "Finalitzat" if res else "Programat",
                "camp": pavello_net(p["camp"]), "font": "FEB (feb.es)", "idFont": p["id"],
            })
    if not partits:
        raise RuntimeError("la FEB no ha donat cap partit del Sol Gironès")

    # Classificació: la de la darrera jornada ja començada; si surt buida
    # (el dissabte d'una jornada), la de l'anterior.
    files = []
    try:
        ses2 = feb_sessio()
        url = FEB["urlClassificacio"]
        hc = ses2.get(url, timeout=60).text
        hc = feb_postback(ses2, hc, "_ctl0$gruposDropDownList", {"_ctl0:gruposDropDownList": FEB["grup"]}, url)
        js = feb_jornades(hc)
        avui = ara().date().isoformat()
        passades = [j for j in js if j["data"] and j["data"] <= avui]
        for j in reversed(passades[-2:]):
            if feb_seleccionat(hc, "_ctl0_jornadasDropDownList") != j["id"]:
                time.sleep(0.25)
                hc = feb_postback(ses2, hc, "_ctl0$jornadasDropDownList", {"_ctl0:jornadasDropDownList": j["id"]}, url)
            files = feb_classificacio(hc)
            if files:
                break
    except Exception as e:  # la classificació no ha de fer perdre el calendari
        print("  ⚠️ FEB classificació:", e)
    return partits, ({"tipus": "basquet", "files": files} if files else None)


def feb_classificacio(h):
    t = re.search(r'<table[^>]*class="tabla-estadistica"[^>]*>([\s\S]*?)</table>', h)
    if not t:
        return []
    ths = re.findall(r"<th[^>]*>[\s\S]*?</th>", t.group(1))
    mapa = {}
    for i, th in enumerate(ths):
        tt = re.search(r'title="([^"]*)"', th)
        mapa[norm(tt.group(1) if tt else text_html(th))] = i
    col = {k: mapa.get(v) for k, v in {"pos": "posicion", "equip": "equipo", "pj": "partidosjugados",
                                         "pg": "partidosganados", "pp": "partidosperdidos", "pf": "puntosafavor",
                                         "pc": "puntosencontra", "dif": "diferencia", "pct": "porcentaje",
                                         "racha": "racha"}.items()}
    cos = re.search(r"<tbody[^>]*>([\s\S]*?)</tbody>", t.group(1))
    files = []
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", cos.group(1) if cos else t.group(1)):
        cel = re.findall(r"<td[^>]*>[\s\S]*?</td>", tr)
        if col["equip"] is None or len(cel) <= col["equip"]:
            continue
        link = re.search(r'Equipo\.aspx\?i=(\d+)"[^>]*>([^<]*)<', cel[col["equip"]])
        if not link:
            continue
        val = lambda k: text_html(cel[col[k]]) if col[k] is not None and col[k] < len(cel) else ""
        files.append({
            "pos": num(val("pos")), "equip": NOMS_FEB.get(link.group(1)) or htmlmod.unescape(link.group(2)).strip(),
            "pj": num(val("pj")), "pg": num(val("pg")), "pp": num(val("pp")), "pf": num(val("pf")),
            "pc": num(val("pc")), "dif": num(val("dif")), "pct": val("pct"), "ratxa": val("racha"),
            "propi": link.group(1) == FEB["idBisbal"],
        })
    files.sort(key=lambda f: f["pos"] if isinstance(f["pos"], (int, float)) else 999)
    return files


def feb_pot_esperar(prev):
    """Cert si la FEB es va llegir bé fa menys d'una hora i avui el sènior no juga."""
    ok = (prev.get("estatFont") or {}).get("darrerOk")
    if not ok or not prev.get("partits"):
        return False
    try:
        fa = (ara() - dt.datetime.fromisoformat(ok)).total_seconds()
    except ValueError:
        return False
    avui = ara().date().isoformat()
    juga_avui = any(p.get("data") == avui and not p.get("manual") for p in prev.get("partits", []))
    return fa < 3600 and not juga_avui


# -----------------------------------------------------------------------------
# DADES MANUALS (dades/esports-manual.json)
# -----------------------------------------------------------------------------
def partit_manual(eq, m):
    res = str(m.get("resultat") or "").strip()
    res = re.sub(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", r"\1 - \2", res)
    return {
        "clau": "MAN-" + str(m.get("id") or ""), "competicio": m.get("competicio") or eq["competicio"],
        "grup": m.get("grup", eq["grup"]) or "", "jornada": str(m.get("jornada") or ""),
        "data": m.get("data") or "", "hora": hora_neta(m.get("hora")),
        "localVisitant": m.get("localVisitant") or "", "rival": (m.get("rival") or "").strip(),
        "resultat": res, "estat": m.get("estat") or ("Finalitzat" if re.match(r"^\d+ - \d+$", res) else "Programat"),
        "camp": (m.get("camp") or "").strip(), "font": "A mà", "idFont": str(m.get("id") or ""),
        "manual": True, "nota": (m.get("nota") or "").strip(),
    }


def classificacio_manual(eq, files):
    sortida = []
    for f in files or []:
        if not str(f.get("equip") or "").strip():
            continue
        pj, pg, pf, pc = (num(f.get(k)) for k in ("pj", "pg", "pf", "pc"))
        fila = {"pos": num(f.get("pos")), "equip": f["equip"].strip(), "pj": pj, "pg": pg,
                "pp": num(f.get("pp")), "pf": pf, "pc": pc, "punts": num(f.get("punts")), "ratxa": f.get("ratxa", "")}
        if eq["esport"] == "Bàsquet":
            fila["dif"] = (pf - pc) if isinstance(pf, (int, float)) and isinstance(pc, (int, float)) else ""
            fila["pct"] = pct_ca(pg / pj) if isinstance(pj, (int, float)) and pj else ""
        else:
            fila["pe"] = num(f.get("pe"))
        fila["propi"] = bool(f.get("propi")) or ("bisbal" in norm(fila["equip"]) if eq["esport"] == "Bàsquet" else False)
        sortida.append(fila)
    sortida.sort(key=lambda f: f["pos"] if isinstance(f["pos"], (int, float)) else 999)
    return {"tipus": "basquet" if eq["esport"] == "Bàsquet" else "futbol", "files": sortida} if sortida else None


# -----------------------------------------------------------------------------
# FORMAT «FULL» (el mateix que el Sheet, per al guió i l'avisador)
# -----------------------------------------------------------------------------
def files_full(eq, partits, quan):
    return [[p["clau"], eq["nom"], p["competicio"], p["grup"], p["jornada"], data_ca(p["data"]), p["hora"],
             p["localVisitant"], p["rival"], p["resultat"], p["estat"], p["camp"], p["font"], p["idFont"], quan]
            for p in partits]


def full_classificacio(eq, cls, quan):
    if not cls:
        return []
    font = "A mà" if eq["font"] == "manual" else ("FEB (feb.es)" if eq["font"] == "feb" else "FCF")
    if cls["tipus"] == "basquet":
        files = [[eq["competicio"], eq["grup"], f["pos"], f["equip"], f["pj"], f["pg"], f["pp"], f["pf"], f["pc"],
                  f.get("dif", ""), f.get("pct", ""), f.get("ratxa", "") or f.get("punts", ""), font, quan]
                 for f in cls["files"]]
        cap = list(CAP_CLASS_BASQUET)
        if eq["font"] == "manual":
            cap[11] = "Punts"
            for fila, f in zip(files, cls["files"]):
                fila[11] = f.get("punts", "")
        return [cap] + files
    return [CAP_CLASS_FUTBOL] + [[eq["competicio"], eq["grup"], f["pos"], f["equip"], f["pj"], f["pg"], f["pe"],
                                  f["pp"], f["pf"], f["pc"], f["punts"], f["ratxa"], font, quan] for f in cls["files"]]


# -----------------------------------------------------------------------------
# PRINCIPAL
# -----------------------------------------------------------------------------
def main():
    prova = "--prova" in sys.argv
    anterior = {e["id"]: e for e in llegeix_json(SORTIDA, {}).get("equips", [])}
    manual = llegeix_json(MANUAL, {}).get("equips", {})
    quan_iso = ara().isoformat(timespec="seconds")
    quan = ara().strftime("%d/%m/%Y %H:%M")
    sortida = []

    for eq in EQUIPS:
        print("·", eq["nom"])
        man = manual.get(eq["id"], {})
        partits, cls, estat = [], None, {"ok": True, "missatge": "", "quan": quan_iso}
        prev = anterior.get(eq["id"]) or {}
        try:
            if eq["font"] == "fcf":
                partits, cls = llegeix_futbol(eq)
            elif eq["font"] == "feb" and feb_pot_esperar(prev):
                # La FEB són unes 30 peticions: com a molt un cop cada hora, llevat
                # que avui hi hagi partit del sènior (llavors, cada vegada).
                partits = [p for p in prev.get("partits", []) if not p.get("manual")]
                cls = prev.get("classificacio")
                estat = dict(prev.get("estatFont") or estat)
                print("  (FEB llegida fa menys d'una hora: es reaprofita)")
            elif eq["font"] == "feb":
                partits, cls = llegeix_feb(eq)
        except Exception as e:
            print("  ⚠️", e)
            partits = [p for p in prev.get("partits", []) if not p.get("manual")]
            cls = prev.get("classificacio") if not prev.get("classificacioManual") else None
            estat = {"ok": False, "missatge": str(e)[:300], "quan": quan_iso,
                     "darrerOk": (prev.get("estatFont") or {}).get("darrerOk") or (prev.get("estatFont") or {}).get("quan")}
        if estat["ok"] and not (eq["font"] == "feb" and estat.get("darrerOk") and feb_pot_esperar(prev)):
            estat["darrerOk"] = quan_iso

        # Partits entrats a mà: s'afegeixen; si porten la mateixa clau que un
        # partit automàtic («substitueix»), el corregeixen.
        per_clau = {p["clau"]: p for p in partits}
        for m in man.get("partits", []):
            pm = partit_manual(eq, m)
            if m.get("substitueix") and m["substitueix"] in per_clau:
                base = per_clau[m["substitueix"]]
                for k in ("data", "hora", "camp", "resultat", "estat", "rival", "jornada"):
                    if pm.get(k):
                        base[k] = pm[k]
                base["corregit"] = True
            else:
                partits.append(pm)

        cls_manual = classificacio_manual(eq, man.get("classificacio"))
        if cls_manual and (eq["font"] == "manual" or not cls):
            cls = cls_manual
        partits.sort(key=lambda p: (p.get("data") or "9999", p.get("hora") or "99"))

        sortida.append({
            "id": eq["id"], "nom": eq["nom"], "esport": eq["esport"], "categoria": eq["categoria"],
            "competicio": eq["competicio"], "grup": eq["grup"], "font": eq["font"], "estatFont": estat,
            "partits": partits, "classificacio": cls, "classificacioManual": bool(cls_manual and cls is cls_manual),
            "classificacioActualitzada": man.get("classificacioActualitzada") if cls is cls_manual else quan_iso,
            "full": files_full(eq, partits, quan),
            "fullClassificacio": full_classificacio(eq, cls, quan),
        })
        print(f"  {len(partits)} partits, {len((cls or {}).get('files', []))} equips a la classificació"
              + ("" if estat["ok"] else " (dades anteriors)"))

    dades = {"actualitzat": quan_iso, "equips": sortida}
    if prova:
        print(json.dumps(dades, ensure_ascii=False)[:2000])
        return
    text = json.dumps(dades, ensure_ascii=False, indent=1)
    vell = None
    try:
        with open(SORTIDA, encoding="utf-8") as f:
            vell = json.load(f)
    except (OSError, ValueError):
        pass
    # No es reescriu si només canvia l'hora de l'actualització.
    if vell and _sense_hora(vell) == _sense_hora(dades):
        print("Sense canvis.")
        return
    with open(SORTIDA, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print("Escrit", SORTIDA)


def _sense_hora(d):
    c = json.loads(json.dumps(d))
    c.pop("actualitzat", None)
    for e in c.get("equips", []):
        e.pop("estatFont", None)
        e.pop("classificacioActualitzada", None)
        e["full"] = [f[:-1] for f in e.get("full", [])]
        e["fullClassificacio"] = [f[:-1] for f in e.get("fullClassificacio", [])]
    return c


if __name__ == "__main__":
    main()
