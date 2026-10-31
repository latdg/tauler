# =============================================================================
# EDAT DELS EDIFICIS — La TdG · 27.10.2026
# Cadastre (servei INSPIRE d'edificis, Direcció General del Cadastre). Per a
# cada un dels quatre municipis baixa el ZIP d'edificis, en llegeix l'any de
# construcció, l'ús, els habitatges i les plantes, i desa:
#   dades/edificis/<codi INE>.geojson  els edificis (polígons en WGS84) per al mapa
#   dades/edificis.json                el resum per municipi i per època
# El Cadastre ho actualitza cada pocs mesos: el workflow va un cop al mes.
# Crèdit obligatori: «Font: Direcció General del Cadastre».
# =============================================================================
import io
import json
import re
import unicodedata
import zipfile
from urllib.parse import unquote
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import requests
from pyproj import Transformer

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "edificis.json"
CARPETA = ARREL / "dades" / "edificis"
FEED = "https://www.catastro.hacienda.gob.es/INSPIRE/buildings/17/ES.SDGC.bu.atom_17.xml"
CAPCALERES = {"User-Agent": "Mozilla/5.0 (LaTdG-redaccio; latdg@laguait.cat)"}
# codi INE -> (nom, paraula per trobar-lo al feed del Cadastre)
MUNICIPIS = {
    "17022": ("la Bisbal d'Empordà", r"BISBAL D"),
    "17057": ("Corçà", r"^CORC?.?A$"),   # al Cadastre surt com «COR A» (la ç es perd)
    "17902": ("Forallac", r"FORALLAC"),
    "17901": ("Cruïlles, Monells i Sant Sadurní de l'Heura", r"CRUILLES"),
    "17205": ("Ullastret", r"ULLASTRET"),   # 31.10.2026
}
EPOQUES = [(0, 1900, "abans de 1900"), (1900, 1940, "1900-1939"), (1940, 1960, "1940-1959"), (1960, 1980, "1960-1979"),
           (1980, 2000, "1980-1999"), (2000, 2010, "2000-2009"), (2010, 9999, "des de 2010")]
USOS = {"1_residential": "Residencial", "2_agriculture": "Agrari", "3_industrial": "Industrial",
        "4_1_office": "Oficines", "4_2_retail": "Comercial", "4_3_publicServices": "Serveis públics"}
A_WGS84 = Transformer.from_crs("EPSG:25831", "EPSG:4326", always_xy=True)


def pla(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.upper()) if unicodedata.category(c) != "Mn")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def fill(el, nom):
    for x in el.iter():
        if local(x.tag) == nom:
            return x
    return None


def epoca(any_):
    for ini, fi, nom in EPOQUES:
        if ini <= any_ < fi:
            return nom
    return None


def anells(el):
    """Anells exteriors (posList) d'un edifici, passats a WGS84 i amb 6 decimals."""
    res = []
    for x in el.iter():
        if local(x.tag) == "exterior":
            pl = fill(x, "posList")
            if pl is None or not pl.text:
                continue
            v = [float(n) for n in pl.text.split()]
            xs, ys = v[0::2], v[1::2]
            lon, lat = A_WGS84.transform(xs, ys)
            res.append([[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)])
    return res


def processa(zf):
    noms = zf.namelist()
    nom_b = next(n for n in noms if n.lower().endswith(".building.gml"))
    nom_p = next((n for n in noms if n.lower().endswith(".buildingpart.gml")), None)

    plantes = defaultdict(int)   # id de l'edifici -> plantes sobre rasant (màxim de les parts)
    if nom_p:
        for _, el in ET.iterparse(io.BytesIO(zf.read(nom_p))):
            if local(el.tag) == "BuildingPart":
                gid = next((v for k, v in el.attrib.items() if local(k) == "id"), "")
                base = re.sub(r"_part\d+$", "", gid)
                n = fill(el, "numberOfFloorsAboveGround")
                if n is not None and (n.text or "").strip().isdigit():
                    plantes[base] = max(plantes[base], int(n.text))
                el.clear()

    edificis = []
    for _, el in ET.iterparse(io.BytesIO(zf.read(nom_b))):
        if local(el.tag) != "Building":
            continue
        gid = next((v for k, v in el.attrib.items() if local(k) == "id"), "")
        b = fill(el, "beginning")
        any_ = int(b.text[:4]) if b is not None and b.text and b.text[:4].isdigit() else None
        us = fill(el, "currentUse")
        hab = fill(el, "numberOfDwellings")
        cond = fill(el, "conditionOfConstruction")
        geo = anells(el)
        if geo:
            edificis.append({
                "ref": gid.replace("ES.SDGC.BU.", ""),
                "any": any_ if any_ and 1000 < any_ <= datetime.now().year else None,
                "us": USOS.get((us.text or "").strip(), (us.text or "").strip() or None) if us is not None else None,
                "hab": int(hab.text) if hab is not None and (hab.text or "").strip().isdigit() else 0,
                "plantes": plantes.get(gid) or None,
                "ruina": cond is not None and "ruin" in (cond.text or "").lower(),
                "geo": geo,
            })
        el.clear()
    return edificis


def resum(edificis):
    amb = [e for e in edificis if e["any"]]
    per_epoca = Counter(epoca(e["any"]) for e in amb)
    hab_epoca = Counter()
    for e in amb:
        hab_epoca[epoca(e["any"])] += e["hab"]
    antics = sorted(amb, key=lambda e: e["any"])[:5]
    return {
        "edificis": len(edificis),
        "ambAny": len(amb),
        "habitatges": sum(e["hab"] for e in edificis),
        "mediana": int(median([e["any"] for e in amb])) if amb else None,
        "epoques": [{"epoca": n, "edificis": per_epoca.get(n, 0), "habitatges": hab_epoca.get(n, 0)} for _, _, n in EPOQUES],
        "usos": Counter(e["us"] or "Altres" for e in edificis).most_common(),
        "mesAntics": [{"ref": e["ref"], "any": e["any"], "us": e["us"]} for e in antics],
        "any1900": sum(1 for e in amb if e["any"] == 1900),
        "ultims10anys": sum(1 for e in amb if e["any"] >= datetime.now().year - 10),
        "ruina": sum(1 for e in edificis if e["ruina"]),
        "plantesMax": max((e["plantes"] or 0) for e in edificis) if edificis else None,
    }


def main():
    feed = requests.get(FEED, headers=CAPCALERES, timeout=120)
    feed.raise_for_status()
    text = feed.content.decode("iso-8859-1")
    zips = re.findall(r'href="([^"]+/A\.ES\.SDGC\.BU\.\d+\.zip)"', text)
    CARPETA.mkdir(parents=True, exist_ok=True)
    sortida = {"generat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "font": "Direcció General del Cadastre (servei INSPIRE d'edificis)",
               "epoques": [n for _, _, n in EPOQUES], "municipis": {}}
    for codi, (nom, clau) in MUNICIPIS.items():
        nom_feed = lambda z: pla(unquote(z.split("/")[-2], encoding="latin-1")).split("-", 1)[-1].strip()
        url = next((z for z in zips if re.search(clau, nom_feed(z))), None)
        if not url:
            print("No trobat al feed:", nom, [z.split("/")[-2] for z in zips if nom_feed(z)[:2] == re.sub(r"[^A-Z]", "", clau)[:2]])
            continue
        actualitzat = None
        m = re.search(re.escape(url) + r".*?<updated>([^<]+)</updated>", text, re.S)
        if m:
            actualitzat = m.group(1)[:10]
        r = requests.get(url, headers=CAPCALERES, timeout=600)
        r.raise_for_status()
        edificis = processa(zipfile.ZipFile(io.BytesIO(r.content)))
        geo = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "properties": {k: e[k] for k in ("ref", "any", "us", "hab", "plantes") if e[k] not in (None, 0)} | ({"ruina": 1} if e["ruina"] else {}),
            "geometry": {"type": "MultiPolygon", "coordinates": [[a] for a in e["geo"]]} if len(e["geo"]) > 1
            else {"type": "Polygon", "coordinates": e["geo"]},
        } for e in edificis]}
        (CARPETA / f"{codi}.geojson").write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        sortida["municipis"][codi] = {"nom": nom, "actualitzatCadastre": actualitzat, "zip": url, **resum(edificis)}
        print(nom, len(edificis), "edificis; mediana", sortida["municipis"][codi]["mediana"])
    SORTIDA.write_text(json.dumps(sortida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
