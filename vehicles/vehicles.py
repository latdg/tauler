# =============================================================================
# VEHICLES NOUS MATRICULATS — La TdG · 01.11.2026
# Microdades mensuals de matriculacions de la DGT (un registre per vehicle, amb
# el municipi on està domiciliat). Per a cada mes i cada un dels cinc municipis:
# quants vehicles s'hi han matriculat, de quin tipus (turismes, motos,
# furgonetes...), amb quina energia (elèctrics, endollables, híbrids, benzina,
# dièsel), nous o importats de segona mà, i de particulars o d'empreses; i, per
# comparar, el percentatge de turismes elèctrics de tota la província.
# Desa dades/vehicles.json. Només baixa els mesos que encara no té.
# Format de la DGT: text d'amplada fixa (document MATRICULACIONES_MATRABA).
# =============================================================================
import datetime as dt
import io
import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "vehicles.json"
CAPCALERES = {"User-Agent": "Mozilla/5.0 (La TdG; latdg@laguait.cat)"}
URLS = ["https://www.dgt.es/microdatos/salida/{a}/{m}/vehiculos/matriculaciones/export_mensual_mat_{a}{mm}.zip",
        "https://www.dgt.es/microdatos/salida/{a}/{mm}/vehiculos/matriculaciones/export_mensual_mat_{a}{mm}.zip"]
INICI = (2024, 1)            # la primera vegada, des d'aquí (per comparar anys)
MUNICIPIS = {"17022": "la Bisbal d'Empordà", "17902": "Forallac", "17057": "Corçà",
             "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura", "17205": "Ullastret"}

# Amplades dels 69 camps, en ordre (document de la DGT).
AMPLADES = [("FEC_MATRICULA", 8), ("COD_CLASE_MAT", 1), ("FEC_TRAMITACION", 8), ("MARCA_ITV", 30), ("MODELO_ITV", 22),
            ("COD_PROCEDENCIA_ITV", 1), ("BASTIDOR_ITV", 21), ("COD_TIPO", 2), ("COD_PROPULSION_ITV", 1), ("CILINDRADA_ITV", 5),
            ("POTENCIA_ITV", 6), ("TARA", 6), ("PESO_MAX", 6), ("NUM_PLAZAS", 3), ("IND_PRECINTO", 2), ("IND_EMBARGO", 2),
            ("NUM_TRANSMISIONES", 2), ("NUM_TITULARES", 2), ("LOCALIDAD_VEHICULO", 24), ("COD_PROVINCIA_VEH", 2),
            ("COD_PROVINCIA_MAT", 2), ("CLAVE_TRAMITE", 1), ("FEC_TRAMITE", 8), ("CODIGO_POSTAL", 5), ("FEC_PRIM_MATRICULACION", 8),
            ("IND_NUEVO_USADO", 1), ("PERSONA_FISICA_JURIDICA", 1), ("CODIGO_ITV", 9), ("SERVICIO", 3),
            ("COD_MUNICIPIO_INE_VEH", 5), ("MUNICIPIO", 30), ("KW_ITV", 7), ("NUM_PLAZAS_MAX", 3), ("CO2_ITV", 5), ("RENTING", 1),
            ("COD_TUTELA", 1), ("COD_POSESION", 1), ("IND_BAJA_DEF", 1), ("IND_BAJA_TEMP", 1), ("IND_SUSTRACCION", 1),
            ("BAJA_TELEMATICA", 11), ("TIPO_ITV", 25), ("VARIANTE_ITV", 25), ("VERSION_ITV", 35), ("FABRICANTE_ITV", 70),
            ("MASA_ORDEN_MARCHA_ITV", 6), ("MASA_MAXIMA_TECNICA_ADMISIBLE_ITV", 6), ("CATEGORIA_HOMOLOGACION_EUROPEA_ITV", 4),
            ("CARROCERIA", 4), ("PLAZAS_PIE", 3), ("NIVEL_EMISIONES_EURO_ITV", 8), ("CONSUMO_WH_KM_ITV", 4),
            ("CLASIFICACION_REGLAMENTO_VEHICULOS_ITV", 4), ("CATEGORIA_VEHICULO_ELECTRICO", 4)]
POS = {}
_p = 0
for _n, _a in AMPLADES:
    POS[_n] = (_p, _p + _a)
    _p += _a


def camp(linia, nom):
    a, b = POS[nom]
    return linia[a:b].strip()


TIPUS = {"40": "turismes", "50": "motos", "51": "motos", "52": "motos", "53": "motos", "54": "motos",
         "90": "ciclomotors", "91": "ciclomotors", "92": "ciclomotors", "20": "furgonetes", "21": "furgonetes",
         "22": "furgonetes", "23": "furgonetes", "24": "furgonetes", "25": "furgonetes"}
PROPULSIO = {"0": "benzina", "1": "dièsel", "2": "elèctric"}
CATEGORIA = {"BEV": "elèctric", "PHEV": "endollable", "REEV": "endollable", "HEV": "híbrid"}


def energia(linia):
    cat = camp(linia, "CATEGORIA_VEHICULO_ELECTRICO").upper()
    if cat in CATEGORIA:
        return CATEGORIA[cat]
    return PROPULSIO.get(camp(linia, "COD_PROPULSION_ITV"), "altres")


def baixa_mes(a, m):
    for plantilla in URLS:
        url = plantilla.format(a=a, m=m, mm=f"{m:02d}")
        try:
            r = requests.get(url, headers=CAPCALERES, timeout=(30, 600))
        except requests.RequestException as e:
            print("  ", url, e)
            continue
        if r.status_code == 200 and r.content[:2] == b"PK":
            return url, r.content
        print("  ", url, r.status_code)
    return None, None


def processa(zip_bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    nom = next(n for n in z.namelist() if n.lower().endswith(".txt"))
    muni = defaultdict(lambda: {"total": 0, "nous": 0, "usats": 0, "empreses": 0,
                                "tipus": Counter(), "energia": Counter(), "energiaTurismes": Counter(), "marques": Counter()})
    girona = Counter()
    linies = dolentes = 0
    with z.open(nom) as f:
        for brut in f:
            linia = brut.decode("latin-1").rstrip("\r\n")
            if len(linia) < POS["COD_MUNICIPIO_INE_VEH"][1]:
                continue
            linies += 1
            codi = camp(linia, "COD_MUNICIPIO_INE_VEH")
            if not (codi.isdigit() and len(codi) == 5):
                dolentes += 1
                continue
            tipus = TIPUS.get(camp(linia, "COD_TIPO"), "altres")
            en = energia(linia)
            if codi.startswith("17") and tipus == "turismes":
                girona["turismes"] += 1
                if en in ("elèctric", "endollable"):
                    girona["electrics"] += 1
            if codi not in MUNICIPIS:
                continue
            d = muni[codi]
            d["total"] += 1
            d["nous" if camp(linia, "IND_NUEVO_USADO") == "N" else "usats"] += 1
            if camp(linia, "PERSONA_FISICA_JURIDICA") == "X":
                d["empreses"] += 1
            d["tipus"][tipus] += 1
            d["energia"][en] += 1
            if tipus == "turismes":
                d["energiaTurismes"][en] += 1
                d["marques"][camp(linia, "MARCA_ITV").title()] += 1
    if linies and dolentes / linies > 0.3:
        raise SystemExit(f"El format del fitxer no és l'esperat ({dolentes} de {linies} línies sense codi de municipi vàlid).")
    sortida = {}
    for codi, d in muni.items():
        sortida[codi] = {k: (dict(v) if isinstance(v, Counter) else v) for k, v in d.items()}
    return {"municipis": sortida, "girona": dict(girona), "linies": linies}


def main():
    try:
        dades = json.loads(SORTIDA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dades = {"mesos": {}}
    avui = dt.date.today()
    a, m = INICI
    nous = 0
    while (a, m) < (avui.year, avui.month):
        clau = f"{a}-{m:02d}"
        if clau not in dades["mesos"]:
            url, contingut = baixa_mes(a, m)
            if contingut:
                r = processa(contingut)
                dades["mesos"][clau] = {"municipis": r["municipis"], "girona": r["girona"]}
                nous += 1
                print(f"✓ {clau}: {r['linies']} vehicles a tot l'Estat; als nostres municipis: "
                      + ", ".join(f"{MUNICIPIS[c]} {v['total']}" for c, v in r["municipis"].items()))
            else:
                print(f"· {clau}: encara no publicat")
        m += 1
        if m > 12:
            a, m = a + 1, 1
    if not nous and "--forca" not in sys.argv:
        print("Cap mes nou.")
        return
    dades["mesos"] = dict(sorted(dades["mesos"].items()))
    dades["generat"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    dades["font"] = "Direcció General de Trànsit (DGT), microdades de matriculacions de vehicles"
    dades["url"] = "https://www.dgt.es/menusecundario/dgt-en-cifras/matraba-listados/matriculaciones-automoviles-mensual.html"
    SORTIDA.parent.mkdir(parents=True, exist_ok=True)
    SORTIDA.write_text(json.dumps(dades, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("Desat", SORTIDA)


if __name__ == "__main__":
    main()
