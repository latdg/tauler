"""Genera dades/baix_emporda.geojson: el límit oficial de la comarca (OpenStreetMap)."""
import json, sys, requests
Q = '[out:json][timeout:120];relation["boundary"="administrative"]["admin_level"="7"]["name"="Baix Empordà"];out geom;'
for url in ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]:
    try:
        r = requests.post(url, data={"data": Q}, timeout=180, headers={"User-Agent": "LaTdG-tauler/1.0"})
        r.raise_for_status(); d = r.json(); break
    except Exception as e:
        print("Overpass", url, e)
else:
    sys.exit(1)
rel = d["elements"][0]
trossos = [[(round(p["lon"], 6), round(p["lat"], 6)) for p in m["geometry"]]
           for m in rel["members"] if m["type"] == "way" and m.get("role") in ("outer", "") and m.get("geometry")]
anells = []
while trossos:
    anell = trossos.pop(0)
    while anell[0] != anell[-1]:
        for i, t in enumerate(trossos):
            if t[0] == anell[-1]: anell += t[1:]; break
            if t[-1] == anell[-1]: anell += t[::-1][1:]; break
        else:
            break
        trossos.pop(i)
    if anell[0] == anell[-1] and len(anell) > 3:
        anells.append([list(p) for p in anell])
print("Anells:", len(anells), [len(a) for a in anells])
json.dump({"type": "Feature", "properties": {"nom": "Baix Empordà", "font": "OpenStreetMap"},
           "geometry": {"type": "MultiPolygon", "coordinates": [[a] for a in anells]}},
          open("dades/baix_emporda.geojson", "w", encoding="utf-8"), ensure_ascii=False)
