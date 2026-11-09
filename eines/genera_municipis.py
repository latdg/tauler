"""Genera dades/municipis_baix_emporda.geojson: els termes municipals detallats (OpenStreetMap)."""
import json, sys, requests
Q = ('[out:json][timeout:180];relation["boundary"="administrative"]["admin_level"="7"]["name"="Baix Empordà"];'
     'map_to_area->.c;relation(area.c)["boundary"="administrative"]["admin_level"="8"];out geom;')
for url in ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]:
    try:
        r = requests.post(url, data={"data": Q}, timeout=240, headers={"User-Agent": "LaTdG-tauler/1.0"})
        r.raise_for_status(); d = r.json(); break
    except Exception as e:
        print("Overpass", url, e)
else:
    sys.exit(1)

def anells(rel, rols):
    trossos = [[(round(p["lon"], 6), round(p["lat"], 6)) for p in m["geometry"]]
               for m in rel["members"] if m["type"] == "way" and m.get("role", "") in rols and m.get("geometry")]
    sortida = []
    while trossos:
        a = trossos.pop(0)
        while a[0] != a[-1]:
            for i, t in enumerate(trossos):
                if t[0] == a[-1]: a += t[1:]; break
                if t[-1] == a[-1]: a += t[::-1][1:]; break
            else:
                break
            trossos.pop(i)
        if a[0] == a[-1] and len(a) > 3:
            sortida.append([list(p) for p in a])
    return sortida

feats = []
for rel in d["elements"]:
    nom = rel.get("tags", {}).get("name")
    ext = anells(rel, ("outer", ""))
    if not nom or not ext:
        continue
    forats = anells(rel, ("inner",))
    feats.append({"type": "Feature", "properties": {"nom": nom, "ine": rel["tags"].get("ine:municipio", "")},
                  "geometry": {"type": "MultiPolygon", "coordinates": [[a] + forats for a in ext]}})
print(len(feats), sorted(f["properties"]["nom"] for f in feats))
json.dump({"type": "FeatureCollection", "features": feats},
          open("dades/municipis_baix_emporda.geojson", "w", encoding="utf-8"), ensure_ascii=False)
