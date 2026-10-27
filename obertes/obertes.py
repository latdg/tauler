# =============================================================================
# SERVEIS I ENERGIA PER A LA TdG AMPLIADA — La TdG · 27.10.2026
# dades/serveis.json, amb:
#   farmacies  Farmàcies de guàrdia del Col·legi de Farmacèutics de Girona
#              (www.cofgi.org), de les poblacions de la zona
#   autoconsum Instal·lacions d'autoconsum elèctric (plaques solars…) per
#              municipi (2b4s-skfm), amb la data i la potència
#   consum     Consum d'energia elèctrica per municipi i sector (8idm-becu)
#   aigua      Preu de l'aigua per municipi (6st4-ptsi)
# Cada apartat es baixa per separat: si un falla, es manté el de la revisió anterior.
# =============================================================================
import html as htmlmod
import json
import re
import time
import traceback
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "serveis.json"
API = "https://analisi.transparenciacatalunya.cat/resource/{id}.json"
VISTA = "https://analisi.transparenciacatalunya.cat/api/views/{id}.json"
COFGI = "https://www.cofgi.org/farmacies/farmacies-de-guardia"
CAPCALERES = {"User-Agent": "Mozilla/5.0 (LaTdG-tauler; latdg@laguait.cat)"}
MUNICIPIS = {"17022": "la Bisbal d'Empordà", "17057": "Corçà", "17902": "Forallac",
             "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura"}
CODI6 = {"17022": "170221", "17057": "170577", "17902": "179026", "17901": "179011"}
# Poblacions de la zona per a les farmàcies de guàrdia (els quatre municipis i
# els veïns on sovint hi ha la de guàrdia més propera).
ZONA_FARMACIES = ["BISBAL", "CORCA", "FORALLAC", "VULPELLAC", "PERATALLADA", "CRUILLES", "MONELLS", "SANT SADURNI",
                  "PALAFRUGELL", "PALAMOS", "TORROELLA", "ESTARTIT", "VERGES", "ULLA", "PALS", "BEGUR", "CALONGE",
                  "SANT FELIU DE GUIXOLS", "CASSA DE LA SELVA", "CELRA", "LA PERA", "MONT-RAS", "REGENCOS", "TORRENT"]


def pla(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "").upper()) if unicodedata.category(c) != "Mn")


def num(v):
    t = str(v if v is not None else "").strip().replace(",", ".")
    try:
        f = float(t)
        return int(f) if f == int(f) else round(f, 3)
    except ValueError:
        return None


def codi_per_nom(nom):
    p = pla(nom)
    if "BISBAL" in p and "EMPORD" in p:
        return "17022"
    for c, k in (("17057", "CORCA"), ("17902", "FORALLAC"), ("17901", "CRUILLES")):
        if k in p:
            return c
    return None


def baixa(ident, where=None, select=None):
    files, pas = [], 5000
    while True:
        p = {"$limit": pas, "$offset": len(files), "$order": ":id"}
        if where:
            p["$where"] = where
        if select:
            p["$select"] = select
        for intent in range(5):
            try:
                r = requests.get(API.format(id=ident), params=p, headers=CAPCALERES, timeout=300)
                r.raise_for_status()
                break
            except Exception as err:
                print(f"{ident}: intent {intent + 1} fallit ({err})")
                time.sleep(30 * (intent + 1))
        else:
            raise RuntimeError(f"{ident}: el servidor no respon")
        lot = r.json()
        files += lot
        if len(lot) < pas:
            return files


def actualitzat(ident):
    try:
        t = requests.get(VISTA.format(id=ident), headers=CAPCALERES, timeout=60).json().get("rowsUpdatedAt")
        return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None
    except Exception:
        return None


def text(h):
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


# --- Farmàcies de guàrdia ------------------------------------------------------------
# El cercador del COFGi (formulari POST) dona les guàrdies d'un dia concret. Es
# demanen els set dies a partir d'avui, del grup de la Bisbal d'Empordà, i se'n
# queden les poblacions de la zona.
GRUP_BISBAL = "10010000000018"


def taula_farmacies(h):
    titol = re.search(r'pharmacies-of-guard-title">\s*([^<]+)<', h)
    t = re.search(r'<table[^>]*id="pharmacies-of-guard-data[^"]*"[^>]*>([\s\S]*?)</table>', h)
    if not t:
        return None, []
    files = []
    for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", t.group(1)):
        cel = re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)
        if not cel:
            continue
        vals = [text(c) for c in cel] + [""] * 5
        # Les capçaleres de la taula no quadren amb les cel·les (n'hi ha de buides):
        # l'ordre de les cel·les és farmàcia, població, horari, adreça i telèfon.
        files.append({"farmacia": vals[0], "poblacio": vals[1], "horari": vals[2], "adreca": vals[3], "telefon": vals[4]})
    return (text(titol.group(1)) if titol else ""), files


def farmacies():
    ses = requests.Session()
    ses.headers.update(CAPCALERES)
    r = ses.get(COFGI, timeout=60)
    r.raise_for_status()
    h = r.text
    camp_data = re.search(r'<input[^>]*type="date"[^>]*>', h)
    nom_data = re.search(r'name="([^"]+)"', camp_data.group(0)).group(1) if camp_data else "date"
    nom_mun = (re.search(r'<select[^>]*id="city-select"[^>]*name="([^"]+)"', h) or [None, "city"])[1]
    print(f"Farmàcies: camps del formulari «{nom_mun}» i «{nom_data}»")
    avui = datetime.now(timezone.utc).astimezone().date()
    from datetime import timedelta
    dies = []
    for n in range(7):
        dia = avui + timedelta(days=n)
        try:
            r = ses.post(COFGI, data={"city-group": GRUP_BISBAL, nom_mun: "0", nom_data: dia.isoformat()}, timeout=60)
            r.raise_for_status()
            titol, files = taula_farmacies(r.text)
        except Exception as err:
            print(f"Farmàcies {dia}: {err}")
            titol, files = None, []
        zona = [f for f in files if any(k in pla(f["poblacio"]) for k in ZONA_FARMACIES)]
        print(f"Farmàcies {dia}: {len(files)} de guàrdia; {len(zona)} a la zona · {titol}")
        dies.append({"data": dia.isoformat(), "titol": titol, "farmacies": zona})
        time.sleep(2)
    if not any(d["farmacies"] for d in dies):
        raise RuntimeError("cap dia amb farmàcies de guàrdia")
    return {"quan": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dies": dies, "font": COFGI}


# --- Autoconsum ----------------------------------------------------------------------
def autoconsum():
    f = baixa("2b4s-skfm", "comarca like '%Baix Empord%'",
              "codi_ine_municipi,municipi,data_d_inscripci,data_de_posada_en_servei,pot_ncia,tecnologia,secci_registre")
    per = {}
    for c, c6 in CODI6.items():
        seves = [x for x in f if x.get("codi_ine_municipi") == c6 or codi_per_nom(x.get("municipi")) == c]
        per_any = defaultdict(lambda: {"n": 0, "kw": 0.0})
        for x in seves:
            d = (x.get("data_de_posada_en_servei") or x.get("data_d_inscripci") or "")[:4]
            if d.isdigit():
                per_any[d]["n"] += 1
                per_any[d]["kw"] += num(x.get("pot_ncia")) or 0
        darreres = sorted(seves, key=lambda x: x.get("data_d_inscripci") or "", reverse=True)[:10]
        per[c] = {
            "n": len(seves), "kw": round(sum(num(x.get("pot_ncia")) or 0 for x in seves), 1),
            "tecnologia": Counter((x.get("tecnologia") or "Altres").capitalize() for x in seves).most_common(),
            "perAny": [[a, v["n"], round(v["kw"], 1)] for a, v in sorted(per_any.items()) if int(a) >= 2010],
            "darreres": [{"data": (x.get("data_d_inscripci") or "")[:10], "kw": num(x.get("pot_ncia")),
                          "tecnologia": (x.get("tecnologia") or "").capitalize()} for x in darreres],
        }
    return {"actualitzat": actualitzat("2b4s-skfm"), "municipis": per}


# --- Consum elèctric -----------------------------------------------------------------
def consum():
    f = baixa("8idm-becu", "comarca like '%BAIX EMPORD%' OR comarca like '%Baix Empord%'")
    per = {}
    for c in MUNICIPIS:
        seves = [x for x in f if str(x.get("cdmun", ""))[:5] == c or codi_per_nom(x.get("municipi")) == c]
        anys = sorted({int(x["any"]) for x in seves if str(x.get("any", "")).isdigit()})
        serie = []
        for a in anys:
            fa = [x for x in seves if int(x["any"]) == a]
            serie.append({"any": a, "total": round(sum(num(x.get("consum_kwh")) or 0 for x in fa)),
                          "sectors": {x.get("descripcio_sector") or "Altres": num(x.get("consum_kwh")) or 0 for x in fa}})
        per[c] = serie
    return {"actualitzat": actualitzat("8idm-becu"), "municipis": per}


# --- Preu de l'aigua -----------------------------------------------------------------
def aigua():
    codis = ",".join(f"'{c}'" for c in CODI6.values())
    f = baixa("6st4-ptsi", f"codi_municipi in({codis})")
    per = {}
    for c, c6 in CODI6.items():
        per[c] = sorted(({"any": int(x["any"]), "preu": num(x.get("preu_aigua")), "subministrament": num(x.get("subministrament")),
                          "canon": num(x.get("canon_aigua")), "clavegueram": num(x.get("clavegueram")),
                          "gestora": x.get("entitat_gestora_principal_subministrament"),
                          "gestio": x.get("gestio_subministrament"), "tarifesSocials": x.get("tarifes_socials")}
                         for x in f if x.get("codi_municipi") == c6), key=lambda z: z["any"])
    try:
        darrer = max(a["any"] for v in per.values() for a in v)
        # El preu és un camp de text i l'API no en pot fer la mitjana: es fa aquí.
        preus = [v for v in (num(x.get("preu_aigua")) for x in baixa("6st4-ptsi", f"any='{darrer}'", "preu_aigua")) if v]
        mitjana = {"any": darrer, "preu": round(sum(preus) / len(preus), 3), "municipis": len(preus)} if preus else None
    except Exception as err:
        print("Mitjana de Catalunya:", err)
        mitjana = None
    return {"actualitzat": actualitzat("6st4-ptsi"), "municipis": per, "catalunya": mitjana}


def main():
    anterior = json.loads(SORTIDA.read_text(encoding="utf-8")) if SORTIDA.exists() else {}
    sortida = {"generat": datetime.now(timezone.utc).isoformat(timespec="seconds"), "municipis": MUNICIPIS}
    for nom, funcio in [("farmacies", farmacies), ("autoconsum", autoconsum), ("consum", consum), ("aigua", aigua)]:
        try:
            sortida[nom] = funcio()
            # 27.10.2026: abans de les 9 h el Col·legi només dona la guàrdia en curs, i
            # no la de la nit que comença aquell vespre. Es conserven els dies que ja es
            # tenien de la revisió anterior i que ara no han vingut.
            if nom == "farmacies" and nom in anterior:
                nous = {d["data"] for d in sortida[nom]["dies"] if d["farmacies"]}
                vells = [d for d in anterior[nom].get("dies", []) if d["data"] not in nous and d.get("farmacies")]
                if vells:
                    tots = {d["data"]: d for d in sortida[nom]["dies"]}
                    tots.update({d["data"]: d for d in vells})
                    sortida[nom]["dies"] = [tots[k] for k in sorted(tots)][-10:]
            print(nom, "fet")
        except Exception:
            print(nom, "ha fallat:")
            traceback.print_exc()
            if nom in anterior:
                sortida[nom] = anterior[nom]
    SORTIDA.write_text(json.dumps(sortida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
