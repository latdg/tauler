# =============================================================================
# MOBILITAT I TURISME (TELEFONIA MÒBIL) — La TdG · 27.10.2026
# Estadística experimental de l'INE «Medició del turisme a partir de telèfons
# mòbils». Els turistes són persones que passen almenys una nit fora del seu
# municipi habitual. Taules (CSV de l'INE, que s'actualitzen cada mes):
#   53001  turistes de la resta de l'Estat per municipi de destinació i origen
#   52048  turistes estrangers per municipi de destinació i país de residència
#   53463  veïns del municipi que fan turisme a la resta de l'Estat (destinació)
#   52052  veïns del municipi que viatgen a l'estranger (país de destinació)
# (Les dades de mobilitat diària del Ministeri de Transports no es poden baixar
# des de GitHub: el servidor ho prohibeix.)
# Desa dades/turisme.json. Les taules que no es poden baixar queden marcades.
# =============================================================================
import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

ARREL = Path(__file__).resolve().parent.parent
SORTIDA = ARREL / "dades" / "turisme.json"
CAPCALERES = {"User-Agent": "Mozilla/5.0 (LaTdG-redaccio; latdg@laguait.cat)"}
URLS = ["https://www.ine.es/jaxiT3/files/t/es/csv_bdsc/{t}.csv", "https://www.ine.es/jaxiT3/files/t/es/csv_bd/{t}.csv",
        "https://www.ine.es/jaxiT3/files/t/es/csv_c/{t}.csv", "https://www.ine.es/jaxiT3/files/t/es/csv/{t}.csv"]
MUNICIPIS = {"17022": "la Bisbal d'Empordà", "17057": "Corçà", "17902": "Forallac", "17901": "Cruïlles, Monells i Sant Sadurní de l'Heura"}
TAULES = {
    "53001": {"clau": "nacionals", "rol": "desti", "nom": "Turistes de la resta de l'Estat que hi arriben"},
    "52048": {"clau": "estrangers", "rol": "desti", "nom": "Turistes estrangers que hi arriben"},
    "53463": {"clau": "veinsEstat", "rol": "origen", "nom": "Veïns que fan turisme a la resta de l'Estat"},
    "52052": {"clau": "veinsEstranger", "rol": "origen", "nom": "Veïns que viatgen a l'estranger"},
}


def numero(t):
    t = (t or "").strip().replace(".", "").replace(",", ".")
    try:
        return int(float(t))
    except ValueError:
        return None   # «""»: dada secreta (massa pocs casos) o sense dada


def periode(t):
    m = re.match(r"(\d{4})M(\d{2})", t or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def llegeix(taula):
    """Torna (url, capçalera, files dels quatre municipis) llegint el CSV per trossos."""
    errors = []
    for plantilla in URLS:
        url = plantilla.format(t=taula)
        try:
            r = requests.get(url, headers=CAPCALERES, timeout=(20, 900), stream=True)
            if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
                errors.append(f"{url}: {r.status_code}")
                continue
            def desxifra(l):
                # Els CSV de l'INE arriben en UTF-8 (amb BOM); si no ho són, en ISO-8859-15.
                try:
                    return l.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return l.decode("iso-8859-15")
            linies = (desxifra(l) for l in r.iter_lines())
            lector = csv.reader(linies, delimiter=";")
            cap = [c.lstrip("﻿") for c in next(lector)]
            files = [f for f in lector if any(re.match(rf"^{c}\b", x or "") for x in f for c in MUNICIPIS)]
            return url, cap, files, errors
        except Exception as err:
            errors.append(f"{url}: {type(err).__name__}")
    return None, None, [], errors


def llocs(detall, darrers):
    """El nivell més detallat que hi hagi (província o país), ordenat pels darrers 12 mesos."""
    if not detall:
        return []
    fons = max(n for n, _ in detall)
    return sorted(([nom, sum(s.get(m, 0) for m in darrers)] for (n, nom), s in detall.items() if n == fons),
                  key=lambda x: -x[1])[:15]


def llocs_anys(detall):
    """27.10.2026: d'on vénen, any per any (any natural; el primer i l'últim poden ser incomplets)."""
    if not detall:
        return {}
    fons = max(n for n, _ in detall)
    anys = sorted({m[:4] for (n, _), s in detall.items() if n == fons for m in s})
    return {a: sorted(([nom, sum(v for m, v in s.items() if m.startswith(a))] for (n, nom), s in detall.items() if n == fons),
                      key=lambda x: -x[1])[:15] for a in anys}


def processa(taula, info):
    url, cap, files, errors = llegeix(taula)
    if not url:
        print(taula, "no disponible:", errors)
        return {"ok": False, "nom": info["nom"], "errors": errors}
    i_per = next(i for i, c in enumerate(cap) if c.lower().startswith("periodo"))
    i_tot = len(cap) - 1
    i_conc = next((i for i, c in enumerate(cap) if c.lower().startswith("concepto")), None)
    i_mun = next(i for i, c in enumerate(cap) if "municipio" in c.lower())
    altres = [i for i in range(len(cap)) if i not in (i_per, i_tot, i_conc, i_mun)]   # origen / destinació (jerarquia)
    per_mun = {}
    for c in MUNICIPIS:
        total = defaultdict(int)
        detall = defaultdict(lambda: defaultdict(int))
        for f in files:
            if len(f) <= i_tot or not re.match(rf"^{c}\b", f[i_mun] or ""):
                continue
            if i_conc is not None and f[i_conc] and not f[i_conc].lower().startswith("turista"):
                continue
            ym, v = periode(f[i_per]), numero(f[i_tot])
            if not ym or v is None:
                continue
            parts = [f[i].strip() for i in altres if f[i].strip()]
            if not parts or re.match(r"^(total|todos)", parts[-1], re.I):
                total[ym] = max(total[ym], v)          # el total (nacional o de tots els països)
            else:
                detall[(len(parts), parts[-1])][ym] += v   # per nivell (comunitat/província, continent/país)
        if not total:
            continue
        mesos = sorted(total)
        darrers = mesos[-12:]
        abans = [f"{int(m[:4]) - 1}{m[4:]}" for m in darrers]
        per_mun[c] = {
            "serie": [[m, total[m]] for m in mesos],
            "darrerMes": mesos[-1],
            "periode": [darrers[0], darrers[-1]],
            "total12": sum(total[m] for m in darrers),
            "totalAbans12": sum(total.get(m, 0) for m in abans) if all(m in total for m in abans) else None,
            "llocs": llocs(detall, darrers),
            "llocsAnys": llocs_anys(detall),
        }
    print(taula, url, "→", {c: (d["total12"], d["darrerMes"]) for c, d in per_mun.items()})
    return {"ok": True, "nom": info["nom"], "rol": info["rol"], "url": url, "municipis": per_mun}


def main():
    sortida = {"generat": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "font": "INE, estadística experimental «Medición del turismo a partir de teléfonos móviles»",
               "municipis": MUNICIPIS, "taules": {}}
    for t, info in TAULES.items():
        sortida["taules"][info["clau"]] = {"taula": t, **processa(t, info)}
    SORTIDA.write_text(json.dumps(sortida, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
