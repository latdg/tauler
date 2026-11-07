# Neteja dels dies desats — La TdG · 07.11.2026
# Deixa només els darrers 7 dies (avui i els sis anteriors) al selector «Dia»
# i esborra els fitxers dels dies més vells. No toca la resta de dades
# (riu, pluja, cinemes, necrològiques, aeronaus...).
#
# Ús: python neteja_dies.py <carpeta de dades> <fitxer|carpeta>
#   fitxer  -> cada dia és dades/AAAA-MM-DD.json   (La TdG ampliada)
#   carpeta -> cada dia és dades/AAAA-MM-DD/       (La TdG redacció)
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DIES_A_GUARDAR = 7

dades = Path(sys.argv[1])
mode = sys.argv[2]
avui = datetime.now(ZoneInfo("Europe/Madrid")).date()
limit = (avui - timedelta(days=DIES_A_GUARDAR - 1)).isoformat()
es_dia = re.compile(r"^\d{4}-\d{2}-\d{2}$")

esborrats = []
for cami in sorted(dades.iterdir()):
    nom = cami.stem if mode == "fitxer" else cami.name
    if mode == "fitxer" and (not cami.is_file() or cami.suffix != ".json"):
        continue
    if mode == "carpeta" and not cami.is_dir():
        continue
    if es_dia.match(nom) and nom < limit:
        shutil.rmtree(cami) if cami.is_dir() else cami.unlink()
        esborrats.append(nom)

fitxer_dies = dades / "dies.json"
dies = json.loads(fitxer_dies.read_text(encoding="utf-8"))
queden = sorted({d for d in dies if d >= limit}, reverse=True)
if queden != dies:
    fitxer_dies.write_text(json.dumps(queden, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

print(f"Dies esborrats: {', '.join(esborrats) or 'cap'} · queden: {', '.join(queden)}")
