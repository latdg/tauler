# =============================================================================
# PALS DE COBERTURA DEL 112 — La TdG · 24.11.2026
# Punts senyalitzats on hi ha cobertura de mòbil per trucar al 112 (CAT112,
# Departament d'Interior; dades obertes de la Generalitat, conjunt u4c3-bcwc).
# Cada pal porta una matrícula que diu a l'operador on és qui truca.
# Baixa tots els de Catalunya (el mapa del tauler s'obre a la nostra zona) i
# els desa a dades/pals112.json. Un cop al mes.
# =============================================================================
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "pals112.json"
API = "https://analisi.transparenciacatalunya.cat/resource/u4c3-bcwc.json"
VISTA = "https://analisi.transparenciacatalunya.cat/api/views/u4c3-bcwc.json"
CAPCALERES = {"User-Agent": "LaTdG-tauler (https://latdg.github.io/tauler/)"}


def nom_i_zona(ressenya):
    """«Sta. Llúcia de l'Arboç (LES GAVARRES)» → («Santa Llúcia de l'Arboç», «les Gavarres»)."""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", ressenya or "")
    nom, zona = (m.group(1), m.group(2)) if m else (ressenya or "", "")
    nom = re.sub(r"\bSta\.\s*", "Santa ", nom)
    nom = re.sub(r"\bSt\.\s*", "Sant ", nom)
    zona = zona.strip().lower()
    zona = " ".join(p if p in ("les", "els", "la", "el", "de", "del", "d'") else "-".join(t.capitalize() for t in p.split("-")) for p in zona.split())
    return nom.strip(), zona


def main():
    r = requests.get(API, params={"$limit": 5000},
                     headers=CAPCALERES, timeout=60)
    r.raise_for_status()
    files = r.json()
    if not files:
        sys.exit("No s'ha trobat cap pal: no es toca el fitxer.")
    actualitzat = None
    try:
        ts = requests.get(VISTA, headers=CAPCALERES, timeout=60).json().get("rowsUpdatedAt")
        if ts:
            actualitzat = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    except Exception as err:
        print("No s'ha pogut llegir la data del registre:", err)

    pals = []
    for f in files:
        geo = f.get("the_geom") or {}
        coords = geo.get("coordinates") or []
        if len(coords) != 2:
            continue
        nom, zona = nom_i_zona(f.get("ressenya", ""))
        pals.append({
            "matricula": re.sub(r"^MATR[IÍ]CULA\s*", "", f.get("matricula", ""), flags=re.I).strip(),
            "nom": nom,
            "zona": zona,
            "lat": round(coords[1], 6),
            "lon": round(coords[0], 6),
        })
    pals.sort(key=lambda p: p["matricula"])
    print(f"{len(pals)} pals a Catalunya")

    SORTIDA.write_text(json.dumps({
        "generat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actualitzatFont": actualitzat,
        "font": "CAT112, Departament d'Interior i Seguretat Pública",
        "pals": pals,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Desat", SORTIDA)


if __name__ == "__main__":
    main()
