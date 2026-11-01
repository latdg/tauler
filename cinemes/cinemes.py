# =============================================================================
# CINEMES — La TdG · 01.11.2026
# La cartellera dels cinemes de la zona, en una sola llista de pel·lícules: cada
# pel·lícula una vegada, amb les sessions de tots els cinemes que la fan. És la
# mateixa lògica de cinemes-tele/app/.../Cinema.java.
#   - OCINE Girona i Platja d'Aro: l'API de la seva web d'entrades.
#   - Cinema Montgrí (Torroella): la portada i la fitxa de cada pel·lícula.
#   - Teatre Mundial (la Bisbal) i TeMePé (Palafrugell): l'agenda municipal, amb
#     les dades schema.org de cada sessió i el preu.
#   - Odeon Girona (Salt): la pàgina de pel·lícules, a través de Jina Reader.
# Una font que falla no atura les altres, i se'n conserven les darreres sessions.
# TMDB (TMDB_TOKEN, només a Actions) afegeix valoració, plataformes i pòster;
# sense token, la cartellera surt igual sense aquestes dades.
# Desa dades/cinemes.json i, per als pòsters que només arriben dins de l'API
# d'OCINE, dades/cinemes/*.jpg.
# =============================================================================
import base64
import io
import json
import os
import re
import unicodedata
import zlib
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from PIL import Image

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "cinemes.json"
POSTERS = ARREL / "dades" / "cinemes"
CAU_TMDB = ARREL / "cinemes" / "tmdb.json"
CAU_TRADUCCIONS = ARREL / "cinemes" / "traduccions.json"
UA_NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
UA_TDG = "Mozilla/5.0 (LaTdG-redaccio; latdg@laguait.cat)"
ZONA = ZoneInfo("Europe/Madrid")
DIES_ENDAVANT = 30
MAX_PROPERES = 8
POSTER_W = 342
TMDB = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
VIGENCIA_TMDB = 24 * 3600
TRADUCTOR = "https://api.softcatala.org/traductor/v1/translate"
ODEON = "https://odeonmulticines.com/odeon-girona/peliculas"
JINA = "https://r.jina.ai/"
DIES_CAT = ["dilluns", "dimarts", "dimecres", "dijous", "divendres", "dissabte", "diumenge"]
# Els noms de les plataformes, com a la tele: una sola «Netflix» encara que TMDB en doni diverses variants.
PLATAFORMES = {8: "Netflix", 1796: "Netflix", 175: "Netflix", 119: "Prime Video", 2100: "Prime Video", 337: "Disney+",
               1899: "Max", 384: "Max", 350: "Apple TV+", 2: "Apple TV+"}

ODEON_DIA = re.compile(r'<div class="day-(\d{4}-\d{2}-\d{2})')
ODEON_HORA = re.compile(r'data-time="(\d{2})(\d{2})"')
MONTGRI_FILM = re.compile(r'<h2><a href="(https://cinemamontgri\.cat/[^"]+)">(.*?)</a></h2>\s*<ul class="session-list">(.*?)</ul>', re.S)
MONTGRI_SESSIO = re.compile(r"<li>\s*([^\W\d_]+)\s+(\d{1,2})\s*·\s*(\d{1,2})[.:](\d{2})\s*(?:\(([^)]*)\))?")
LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S)


def cadena(o, clau):
    """El camp com a text, sense espais; "" si no hi és o és null."""
    v = o.get(clau) if isinstance(o, dict) else None
    return "" if v is None else str(v).strip()


def baixa_bytes(url, cos=None, maxim=4 * 1024 * 1024):
    """GET (o POST amb cos JSON) amb un límit de mida."""
    capcaleres = {"User-Agent": UA_TDG, "X-Return-Format": "html"} if url.startswith(JINA) \
        else {"User-Agent": UA_NAVEGADOR, "Accept-Language": "ca,es;q=0.8"}
    r = requests.post(url, json=cos, headers=capcaleres, timeout=(15, 45)) if cos is not None \
        else requests.get(url, headers=capcaleres, timeout=(15, 45))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {url}")
    if len(r.content) > maxim:
        raise RuntimeError(f"massa gran: {url}")
    return r.content


def baixa(url, cos=None, maxim=4 * 1024 * 1024):
    return baixa_bytes(url, cos, maxim).decode("utf-8", "replace")


def primer(s, regex):
    m = re.search(regex, s, re.S)
    return m.group(1).strip() if m else ""


def text(html):
    """Treu les etiquetes HTML i desfà les entitats."""
    t = unescape(re.sub(r"<[^>]+>", "", html))
    t = re.sub(r"[ \t\x0b\f\r\xa0]+", " ", t)
    return re.sub(r" *\n[ \n]*", "\n", t).strip()


def frase(s):
    return s[:1].upper() + s[1:].lower() if s and len(s) >= 2 else s


def titol_cas(t):
    """«BALANDRAU» -> «Balandrau»; un títol amb minúscules es deixa com és."""
    t = t.strip()
    if t != t.upper():
        return t
    b, inici = list(t.lower()), True
    for i, c in enumerate(b):
        if inici and c.isalpha():
            b[i] = c.upper()
            inici = False
        elif c in ".:-":
            inici = True
    return "".join(b)


def clau(titol):
    """«Cars (20 Aniversario)», «CARS (REESTRENO)», «Cinema. Cars» -> «cars»."""
    t = "".join(c for c in unicodedata.normalize("NFD", titol.lower()) if not unicodedata.category(c).startswith("M"))
    t = re.sub(r"^cinema\.\s*", "", t)
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"\b(v\.?o\.?s\.?e\.?|vose|vosc|vos|v\.?o\.?|3d|4d|atmos|imax)\b", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t or titol.lower()


def film(films, titol):
    """La pel·lícula d'aquest títol, nova o la que ja hi era d'un altre cinema."""
    k = clau(titol)
    if k not in films:
        films[k] = {"key": k, "titol": titol.strip(), "sinopsi": "", "durada": "", "genere": "", "edat": "", "director": "",
                    "actors": "", "estrena": "", "posterUrl": "", "posterJpeg": None, "posterDesat": "", "web": "",
                    "qualitat": 0, "sinopsiEs": False, "genereEs": False, "edatEs": False, "sessions": [], "tmdb": None}
    return films[k]


def completa(f, qualitat, titol="", sinopsi="", durada="", genere="", edat="", director="", actors="", estrena=""):
    """Omple els camps buits; amb qualitat més alta (2 = text en català, 1 = castellà), també substitueix els textos."""
    millor = qualitat > f["qualitat"]
    if millor and titol:
        f["titol"] = titol.strip()
    if sinopsi and (millor or not f["sinopsi"]):
        f["sinopsi"] = sinopsi.strip()
    if genere and (millor or not f["genere"]):
        f["genere"] = genere.strip()
        f["genereEs"] = qualitat == 1   # l'Odeon escriu en castellà
    if edat and (millor or not f["edat"]):
        f["edat"] = edat.strip()
        f["edatEs"] = qualitat == 1
    if not f["durada"] and durada:
        f["durada"] = re.sub(r"\D", "", durada).lstrip("0")   # OCINE posa 0 quan encara no la sap
    f["director"] = f["director"] or director.strip()
    f["actors"] = f["actors"] or actors.strip()
    if not f["estrena"] and re.match(r"\d{4}-\d{2}-\d{2}", estrena):
        f["estrena"] = estrena[:10]
    if millor:
        f["qualitat"] = qualitat


def sessio(cinema, data, hora, format_="", preu=""):
    return {"cinema": cinema, "data": data, "hora": hora, "format": format_, "preu": preu}


# ---------------------------------------------------------------- OCINE

def ocine_dades(f, p):
    actors = ", ".join(a for a in (cadena(p, k) for k in ("actor1", "actriu1", "actor2", "actriu2")) if a)
    completa(f, 2, cadena(p, "titol"), cadena(p, "sinopsis").replace("\r", ""), cadena(p, "durada"), cadena(p, "genereComercial"),
             cadena(p, "classificacio"), cadena(p, "director"), actors, cadena(p, "dataEstrena"))
    b64 = cadena(p, "poster")
    if f["posterJpeg"] is None and len(b64) > 1000:
        try:
            f["posterJpeg"] = base64.b64decode(b64)
        except ValueError:
            pass   # pòster il·legible


def format_ocine(desc):
    parts = [str(d).strip() for d in desc or []]
    return " ".join(d.replace("Sala ", "") for d in parts if d and d.lower() not in ("estàndar", "2d", "digital"))


def afegeix_sessions(f, cinema, ss, format_):
    for s in ss or []:
        if not isinstance(s, dict):
            continue
        data, hora = cadena(s, "data"), cadena(s, "hora")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
            f["sessions"].append(sessio(cinema, data, hora[:5], format_))


def ocine(base, nom, films):
    cos = {"token": "", "idioma": "ca", "urlWeb": base + "/?idioma=ca&nocap=1"}
    d = json.loads(baixa(base + "/api/v1/sessions", cos, 6 * 1024 * 1024))
    for p in d.get("pelicules") or []:
        try:
            fitxa = json.loads(baixa(f"{base}/api/v1/pelicula/{p['id']}?lang=ca", maxim=2 * 1024 * 1024))
        except Exception:
            fitxa = p
        f = film(films, cadena(fitxa, "titol") or cadena(p, "titol"))
        ocine_dades(f, fitxa)
        f["web"] = f["web"] or base + "/?idioma=ca"
        afegeix_sessions(f, nom, fitxa.get("sessions"), "")
        for s in fitxa.get("subPelicules") or []:
            afegeix_sessions(f, nom, s.get("sessions"), format_ocine(s.get("propietatsDesc")))
    # Estrenes properes: encara sense sessions, només la data
    for p in d.get("estrenes") or []:
        if cadena(p, "titol"):
            ocine_dades(film(films, cadena(p, "titol")), p)


# ---------------------------------------------------------------- Odeon

def format_odeon(f):
    parts = []
    for p in f.split():
        if p in ("2D", "DIGITAL"):
            continue
        # ATMOS -> Atmos, INFINITY -> Infinity; 3D, 4D i VOSE es queden en majúscules
        parts.append(p if re.fullmatch(r"\dD|VOSE|VO", p) else p[:1] + p[1:].lower())
    return " ".join(parts)


def odeon(films):
    html = baixa(JINA + ODEON)
    blocs = re.split(r'<div class="show-\d+ ', html)
    if len(blocs) < 2:
        raise RuntimeError("pàgina sense pel·lícules")
    for b in blocs[1:]:
        titol = titol_cas(re.sub(r"\s+\)", ")", re.sub(r"\(\s+", "(", text(primer(b, r"<h5>(.*?)</h5>")))))
        if not titol:
            continue
        f = film(films, titol)
        completa(f, 1, titol, "", primer(b, r"<span>(\d+) min</span>"), text(primer(b, r'genre-icon2?\.png"\s*>\s*<span>(.*?)</span>')),
                 text(primer(b, r'class="me-3 cal-icon" alt="([^"]*)"')))
        if not f["posterUrl"]:
            p = primer(b, r'src="(https://cdn\.odeonmulticines\.com/show-posters/[^"?]+)')
            if p:
                f["posterUrl"] = p + "?width=500"
        f["web"] = f["web"] or "https://odeonmulticines.com/odeon-girona"
        for dia in re.split(r'(?=<div class="day-\d{4}-\d{2}-\d{2})', b):
            md = ODEON_DIA.match(dia)
            if not md:
                continue
            format_ = format_odeon(primer(dia, r'data-format="([^"]*)"'))
            for mh in ODEON_HORA.finditer(dia):
                f["sessions"].append(sessio("Odeon Girona", md.group(1), f"{mh.group(1)}:{mh.group(2)}", format_))


# ---------------------------------------------------------------- Cinema Montgrí

def data_per_dia(ara, nom_dia, dia):
    """«Dissabte», 7 -> la data AAAA-MM-DD del proper dissabte dia 7 (o d'ahir), dins dels propers 60 dies."""
    nd, c = nom_dia.lower(), ara - timedelta(days=1)
    for _ in range(62):
        if c.day == dia and DIES_CAT[c.weekday()] == nd:
            return c.strftime("%Y-%m-%d")
        c += timedelta(days=1)
    return None


def camp(t, nom):
    """El camp d'una fitxa: la línia que segueix «Durada», «Direcció», etc."""
    m = re.search(r"(?m)^\s*" + re.escape(nom) + r"\s*:?\s*\n\s*(.+)$", t)
    return m.group(1).strip() if m else ""


def cos_fitxa(html):
    sense = re.sub(r"(?s)<script.*?</script>|<style.*?</style>", "", html)
    return text(re.sub(r"<(?:/p|br|/h\d|/li|/div|/dt|/dd)[^>]*>", "\n", sense))


def montgri_fitxa(f, url):
    html = baixa(url, maxim=2 * 1024 * 1024)
    cos = cos_fitxa(html)
    completa(f, 2, "", text(primer(html, r'<meta property="og:description" content="([^"]*)"')), camp(cos, "Durada"), camp(cos, "Gènere"),
             "", camp(cos, "Direcció"), camp(cos, "Repartiment"))
    if not f["posterUrl"] and f["posterJpeg"] is None:
        f["posterUrl"] = primer(html, r'<meta property="og:image" content="([^"]*)"')


def montgri(films, ara):
    html = baixa("https://cinemamontgri.cat/", maxim=2 * 1024 * 1024)
    fets = set()
    for m in MONTGRI_FILM.finditer(html):
        url, titol = m.group(1), text(m.group(2))
        if not titol:
            continue
        f = film(films, titol)
        nou = url not in fets
        fets.add(url)
        vistes = {s["data"] + s["hora"] for s in f["sessions"] if s["cinema"] == "Cinema Montgrí"}
        for ms in MONTGRI_SESSIO.finditer(m.group(3)):
            data = data_per_dia(ara, ms.group(1), int(ms.group(2)))
            if not data:
                continue
            hora = f"{int(ms.group(3)):02d}:{ms.group(4)}"
            if data + hora not in vistes:
                vistes.add(data + hora)
                f["sessions"].append(sessio("Cinema Montgrí", data, hora, ms.group(5) or ""))
        if nou:
            f["web"] = f["web"] or url
            try:
                montgri_fitxa(f, url)
            except Exception:
                pass   # sense fitxa: només el títol i les sessions


# ---------------------------------------------------------------- agendes municipals (Mundial, Palafrugell)

def agenda_fitxa(url, nom, films):
    html = baixa(url, maxim=2 * 1024 * 1024)
    titol = sinopsi = imatge = preu = ""
    sessions = []
    for m in LD.finditer(html):
        try:
            arrel = json.loads(m.group(1).strip(), strict=False)
        except ValueError:
            continue
        for o in arrel if isinstance(arrel, list) else [arrel]:
            if not isinstance(o, dict):
                continue
            if o.get("@type") == "Event":
                titol = titol or cadena(o, "name")
                sinopsi = sinopsi or cadena(o, "description")
                imatge = imatge or cadena(o, "image")
                inici = cadena(o, "startDate")
                if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", inici):
                    sessions.append((inici[:10], inici[11:16]))
            elif o.get("@type") == "Product" and not preu and isinstance(o.get("offers"), dict) and "price" in o["offers"]:
                try:
                    p = float(o["offers"]["price"])
                except (TypeError, ValueError):
                    p = -1
                if p == 0:
                    preu = "Gratuït"
                elif p > 0:
                    preu = (str(int(p)) if p == int(p) else f"{p:.2f}".replace(".", ",")) + " €"
    if not titol or not sessions:
        return
    titol = titol_cas(re.sub(r"(?i)^cinema\.\s*", "", titol))
    f = film(films, titol)
    cos = cos_fitxa(html)
    completa(f, 2, titol, sinopsi, primer(cos, r"Durada:\s*(\d+)"), primer(cos, r"Gènere:\s*([^\n]+)"), primer(cos, r"Qualificació:\s*([^\n]+)"),
             primer(cos, r"Direcció:\s*([^\n]+)"), primer(cos, r"Intèrprets:\s*([^\n]+)"))
    if not f["posterUrl"] and f["posterJpeg"] is None and imatge:
        f["posterUrl"] = imatge
    f["web"] = f["web"] or url
    for data, hora in sessions:
        if not any(y["cinema"] == nom and y["data"] == data and y["hora"] == hora for y in f["sessions"]):
            f["sessions"].append(sessio(nom, data, hora, "", preu))


def agenda_municipal(base, categoria, nom, films):
    llista = baixa(f"{base}/ca/programacio.html?ordre=data_propera_funcio&filtre_categories%5B%5D={categoria}&filtre_historic=0", maxim=2 * 1024 * 1024)
    urls = list(dict.fromkeys(re.findall(r'href="(' + re.escape(base) + r'/ca/programacio/c/\d+-[^"]+\.html)"', llista)))[:30]
    for url in urls:
        try:
            agenda_fitxa(url, nom, films)
        except Exception:
            pass   # una fitxa que falla no atura les altres


# ---------------------------------------------------------------- memòria dels cinemes que no responen

def recupera(fallats, films):
    """Les sessions de la cartellera anterior dels cinemes que han fallat; si ha fallat algun OCINE, també les estrenes."""
    try:
        vells = json.loads(SORTIDA.read_text(encoding="utf-8")).get("films") or []
    except (OSError, ValueError):
        return   # sense cartellera anterior: aquests cinemes no surten fins que tornin a respondre
    ocine_ha_fallat = bool(fallats & {"OCINE Girona", "OCINE Platja d'Aro"})
    for v in vells:
        ss = v.get("sessions") or []
        recuperades = [sessio(s.get("cinema", ""), s.get("data", ""), s.get("hora", ""), s.get("format", ""), s.get("preu", ""))
                       for s in ss if s.get("cinema") in fallats]
        if not recuperades and not (ocine_ha_fallat and not ss):
            continue
        f = film(films, v.get("titol", ""))
        # 2: el que es va desar ja era en català (traduït si calia)
        completa(f, 2, v.get("titol", ""), v.get("sinopsi", ""), v.get("durada", ""), v.get("genere", ""), v.get("edat", ""),
                 v.get("director", ""), v.get("actors", ""), v.get("estrena", ""))
        f["web"] = f["web"] or v.get("web", "")
        if v.get("poster", "").startswith("dades/cinemes/"):
            f["posterDesat"] = f["posterDesat"] or v["poster"]
        elif not f["posterUrl"]:
            f["posterUrl"] = v.get("poster", "")
        f["sessions"].extend(recuperades)


# ---------------------------------------------------------------- TMDB

def tmdb_get(token, cami, **params):
    r = requests.get(TMDB + cami, params=params, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, timeout=(15, 20))
    if r.status_code != 200:
        raise RuntimeError(f"TMDB HTTP {r.status_code}")
    return r.json()


def tmdb_cerca(token, f, idioma):
    """El resultat que millor s'hi assembla: mateix títol, l'any més proper a l'estrena, el més popular."""
    res = tmdb_get(token, "/search/movie", region="ES", language=idioma, query=re.sub(r"\([^)]*\)", "", f["titol"]).strip()).get("results") or []
    any_ref = int(f["estrena"][:4]) if f["estrena"] else datetime.now(ZONA).year
    igual = lambda o: f["key"] in (clau(o.get("title") or ""), clau(o.get("original_title") or ""))
    any_de = lambda o: int((o.get("release_date") or "0")[:4] or 0)

    def punts(o):
        p = (1000 if igual(o) else 0) + min(o.get("popularity") or 0, 200) / 10
        if any_de(o) > 0 and f["estrena"]:
            p -= abs(any_de(o) - any_ref) * 20
        return p
    millor = max(res, key=punts, default=None)
    # Sense títol igual, només si és d'aquest any o del passat: si no, millor res que una altra pel·lícula
    if millor and not igual(millor) and (any_de(millor) == 0 or abs(any_de(millor) - any_ref) > 1):
        return None
    return millor


def tmdb_poster(token, peli, d, castella):
    """El pòster en català si TMDB en té; si no, el de la versió en castellà; i si tampoc, el que dona per defecte."""
    try:
        ps = tmdb_get(token, f"/movie/{peli}/images", include_image_language="ca,es").get("posters") or []
        for llengua in ("ca", "es"):
            for p in ps:
                if p.get("iso_639_1") == llengua:
                    return p.get("file_path") or ""
    except Exception:
        pass   # sense la llista d'imatges: el pòster per defecte
    return castella.get("poster_path") or d.get("poster_path") or ""


def tmdb_consulta(token, f):
    tria = tmdb_cerca(token, f, "ca-ES") or tmdb_cerca(token, f, "es-ES")
    if not tria:
        return {}
    peli = tria["id"]
    d = tmdb_get(token, f"/movie/{peli}", language="ca-ES", append_to_response="watch/providers")
    castella = tmdb_get(token, f"/movie/{peli}", language="es-ES")
    sinopsi = d.get("overview") or ""
    sinopsi_es = not sinopsi and bool(castella.get("overview"))
    es = ((d.get("watch/providers") or {}).get("results") or {}).get("ES") or {}
    plataformes = []
    for tipus in ("flatrate", "free", "ads"):
        for p in es.get(tipus) or []:
            nom = PLATAFORMES.get(p.get("provider_id")) or re.sub(r"(?i)\s+(standard with ads|with ads|amazon channel|basic)$", "", p.get("provider_name") or "").strip()
            if nom and nom not in plataformes:
                plataformes.append(nom)
    return {"id": peli, "nota": d.get("vote_average") or 0, "vots": d.get("vote_count") or 0, "sinopsi": sinopsi or castella.get("overview") or "",
            "sinopsi_es": sinopsi_es, "poster": tmdb_poster(token, peli, d, castella), "plataformes": plataformes, "enllac": es.get("link") or ""}


def tmdb_enriqueix(films):
    """Valoració i plataformes (i la sinopsi o el pòster que faltin). Cada pel·lícula, un cop al dia com a molt."""
    token = os.environ.get("TMDB_TOKEN", "").strip()
    if not token:
        print("Sense TMDB_TOKEN: sense valoracions ni plataformes")
        return False
    try:
        desat = json.loads(CAU_TMDB.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        desat = {}
    nou, ara = {}, datetime.now(timezone.utc).timestamp()
    for f in films:
        r = desat.get(f["key"])
        if not r or ara - r.get("t", 0) > VIGENCIA_TMDB:
            try:
                r = {**tmdb_consulta(token, f), "t": ara}
            except Exception as e:
                print("TMDB:", f["titol"], type(e).__name__)
                if not r:
                    continue   # sense xarxa: es fa servir la darrera resposta, si n'hi ha
        nou[f["key"]] = r
        f["tmdb"] = r
        if not f["sinopsi"]:
            f["sinopsi"] = r.get("sinopsi", "")
            f["sinopsiEs"] = bool(r.get("sinopsi_es"))
        # El pòster de TMDB és més nítid que els dels cinemes: si n'hi ha, es fa servir aquest
        if r.get("poster"):
            f["posterJpeg"] = None
            f["posterDesat"] = ""
            f["posterUrl"] = TMDB_IMG + r["poster"]
    CAU_TMDB.write_text(json.dumps(nou, ensure_ascii=False, indent=0), encoding="utf-8")
    return True


# ---------------------------------------------------------------- traductor

class Traductor:
    """Del castellà al català amb Softcatalà. Cada text es tradueix una sola vegada: es desa a traduccions.json."""

    def __init__(self):
        try:
            self.desades = json.loads(CAU_TRADUCCIONS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.desades = {}

    def tradueix(self, castella):
        if not castella or not castella.strip():
            return castella
        if castella in self.desades:
            return self.desades[castella]
        try:
            r = requests.post(TRADUCTOR, data={"langpair": "es|ca", "markUnknown": "no", "q": castella}, timeout=(10, 20))
            catala = r.json()["responseData"]["translatedText"] if r.status_code == 200 else ""
        except (requests.RequestException, ValueError, KeyError, TypeError):
            catala = ""
        if not catala:
            return castella   # es tornarà a provar la vegada següent
        self.desades[castella] = catala
        return catala

    def desa(self):
        CAU_TRADUCCIONS.write_text(json.dumps(self.desades, ensure_ascii=False, indent=0), encoding="utf-8")


# ---------------------------------------------------------------- tot plegat

def desa_poster(f):
    """El pòster que només arriba dins de l'API d'OCINE, reduït a dades/cinemes/. Torna el camí, o "" si no es pot llegir."""
    nom = re.sub(r"[^a-z0-9]+", "-", f["key"]).strip("-") + f"-{zlib.crc32(f['posterJpeg']):08x}.jpg"
    desti = POSTERS / nom
    if not desti.exists():
        try:
            im = Image.open(io.BytesIO(f["posterJpeg"])).convert("RGB")
        except OSError:
            return ""
        if im.width > POSTER_W:
            im = im.resize((POSTER_W, round(im.height * POSTER_W / im.width)), Image.LANCZOS)
        POSTERS.mkdir(parents=True, exist_ok=True)
        im.save(desti, "JPEG", quality=85, optimize=True)
    return f"dades/cinemes/{nom}"


def segur(url):
    """Els enllaços i els pòsters venen de webs de fora: a la pàgina només hi va el que és https."""
    return url if url.startswith("https://") else ""


def propera(f, avui, hora):
    """La primera sessió que encara no ha començat; None si ja han passat totes."""
    return next((s for s in f["sessions"] if s["data"] > avui or (s["data"] == avui and s["hora"] >= hora)), None)


def main():
    ara = datetime.now(ZONA)
    films, errors, fallats = {}, [], set()
    fonts = [("OCINE Girona", lambda: ocine("https://tickets.ocinegirona.es", "OCINE Girona", films)),
             ("OCINE Platja d'Aro", lambda: ocine("https://tickets.ocineplatjadaro.es", "OCINE Platja d'Aro", films)),
             ("Odeon Girona", lambda: odeon(films)),
             ("Cinema Montgrí", lambda: montgri(films, ara)),
             ("Teatre Mundial", lambda: agenda_municipal("https://www.teatremundial.cat", "1000", "Teatre Mundial", films)),
             ("TeMePé Palafrugell", lambda: agenda_municipal("https://cultura.palafrugell.cat", "18", "TeMePé Palafrugell", films))]
    for nom, font in fonts:
        abans = sum(len(f["sessions"]) for f in films.values())
        try:
            font()
            print(nom, "→", sum(len(f["sessions"]) for f in films.values()) - abans, "sessions")
        except Exception as e:
            print(nom, "HA FALLAT:", e)
            errors.append(nom)
            fallats.add(nom)
    if fallats:
        recupera(fallats, films)
    if not films:
        # El workflow falla i es manté la darrera cartellera bona.
        raise SystemExit(f"Cap font ha respost: {errors}")

    avui, hora = ara.strftime("%Y-%m-%d"), ara.strftime("%H:%M")
    darrer = (ara + timedelta(days=DIES_ENDAVANT)).strftime("%Y-%m-%d")
    amb_sessions, properes = [], []
    for f in films.values():
        f["sessions"] = sorted((s for s in f["sessions"] if avui <= s["data"] <= darrer), key=lambda s: (s["data"], s["hora"], s["cinema"]))
        if f["sessions"]:
            if propera(f, avui, hora):
                amb_sessions.append(f)
        elif f["estrena"] > avui:
            properes.append(f)
    # Primer el que es pot veure abans (la propera sessió); a igualtat de dia, l'estrena més recent
    amb_sessions.sort(key=lambda f: f["estrena"], reverse=True)
    amb_sessions.sort(key=lambda f: propera(f, avui, hora)["data"])
    tots = amb_sessions + sorted(properes, key=lambda f: f["estrena"])[:MAX_PROPERES]

    amb_tmdb = tmdb_enriqueix(tots)
    # Tot en català: el que només ha arribat en castellà es tradueix (una vegada; queda desat)
    t = Traductor()
    for f in tots:
        if f["sinopsiEs"]:
            f["sinopsi"] = t.tradueix(f["sinopsi"])
        if f["genereEs"]:
            f["genere"] = frase(t.tradueix(f["genere"]))
        if f["edatEs"]:
            f["edat"] = frase(t.tradueix(f["edat"]))
    t.desa()

    llista = []
    for f in tots:
        poster = (desa_poster(f) if f["posterJpeg"] else f["posterDesat"]) or segur(f["posterUrl"])
        fila = {k: f[k] for k in ("key", "titol", "sinopsi", "durada", "genere", "edat", "director", "actors", "estrena")}
        fila.update(poster=poster, web=segur(f["web"]), sessions=f["sessions"])
        r = f["tmdb"] or {}
        if r.get("id"):
            fila.update(nota=r.get("nota", 0), vots=r.get("vots", 0), plataformes=r.get("plataformes", []), plataformesUrl=segur(r.get("enllac", "")))
        llista.append(fila)

    # Fora els pòsters que ja no fa servir cap pel·lícula
    usats = {x["poster"].rsplit("/", 1)[-1] for x in llista if x["poster"].startswith("dades/cinemes/")}
    for p in POSTERS.glob("*.jpg"):
        if p.name not in usats:
            p.unlink()

    SORTIDA.write_text(json.dumps({"generat": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ambTmdb": amb_tmdb, "errors": errors, "films": llista},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(llista), "pel·lícules;", "fonts que han fallat:", errors or "cap")


if __name__ == "__main__":
    main()
