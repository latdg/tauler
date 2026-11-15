# Logotips de les benzineres — La TdG · 15.11.2026
# Baixa una vegada la icona de cada marca i la desa a carburants/logos/<marca>.png,
# perquè el tauler la mostri al costat de cada benzinera sense dependre de
# serveis de fora quan algú mira la pàgina. Només baixa les que falten.
# Si una marca no té icona, el tauler hi posa la inicial.
# 15.11.2026: fora Servioil i GM Oil (els seus webs donaven icones que no
# eren la marca); Petrem, de petrem.com, sí que és la seva. Cepsa ja surt amb el logotip de Moeve.
# El d'Esclatoil («OiL») és retallat de la pàgina de benzineres de BonpreuEsclat
# (no el de Bonpreu); com que ja existeix, aquest script no el toca.
# Aneu Oil, Petrolis Independents, Condis i Zona Zero (retallat del rètol de
# Palafrugell; no és Gasolineras Zero) i Regencós Oil (del rètol), afegits a mà
# el 15.11.2026.
import os
import struct
import requests

DESTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logos")

# marca (com la reconeix el tauler) -> dominis on provar, per ordre
MARQUES = {
    "repsol": ["repsol.es", "repsol.com"],
    "shell": ["shell.es", "shell.com"],
    "bp": ["bp.com"],
    "q8": ["q8.es", "q8.com"],
    "galp": ["galp.com"],
    "moeve": ["moeve.es", "moeveglobal.com"],
    "cepsa": ["cepsa.es", "cepsa.com"],
    "condis": ["condis.es"],
    "esclatoil": ["esclatoil.com", "bonpreuesclat.cat"],
    "petrolis": ["petrolisindependents.com", "petro7.cat"],
    "ballenoil": ["ballenoil.es"],
    "bonarea": ["bonarea.com"],
    "petrocat": ["petrocat.cat"],
    "aneuoil": ["aneuoil.com", "aneuoil.es"],
    "zonazero": ["zonazero.es", "zonazero.cat"],
    "petrem": ["petrem.com"],
    "eroski": ["eroski.es"],
    "carrefour": ["carrefour.es"],
}


def mida_png(dades):
    if dades[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    return struct.unpack(">II", dades[16:24])


def baixa(domini):
    url = f"https://www.google.com/s2/favicons?domain={domini}&sz=128"
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (La TdG)"})
    if r.status_code != 200:
        return None
    amplada, alcada = mida_png(r.content)
    # La icona per defecte (un globus petit) no ens serveix.
    if amplada < 32 or alcada < 32:
        return None
    return r.content


def main():
    os.makedirs(DESTI, exist_ok=True)
    for marca, dominis in MARQUES.items():
        fitxer = os.path.join(DESTI, f"{marca}.png")
        if os.path.exists(fitxer):
            continue
        for d in dominis:
            try:
                img = baixa(d)
            except requests.RequestException as e:
                print(f"{marca}: {d} no respon ({e})")
                continue
            if img:
                with open(fitxer, "wb") as f:
                    f.write(img)
                print(f"{marca}: desat des de {d}")
                break
        else:
            print(f"{marca}: sense icona (sortirà la inicial)")


if __name__ == "__main__":
    main()
