set +e
pip install -q pillow
python3 - <<'PY'
import urllib.request, io, datetime as dt
from collections import Counter
from PIL import Image
c = Counter(); ok = 0; mida=Counter()
ara = dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
for h in range(0, 24*30, 3):
    t = ara - dt.timedelta(hours=h+1)
    for x, y in ((64, 80), (65, 80), (64, 79), (65, 79)):
        u = f"https://static-m.meteo.cat/tiles/radar/{t:%Y/%m/%d/%H}/00/07/000/000/{x:03d}/000/000/{y:03d}.png"
        try:
            d = urllib.request.urlopen(u, timeout=20).read()
        except Exception as e:
            continue
        ok += 1
        im = Image.open(io.BytesIO(d)); mida[(im.mode, im.size)] += 1
        for p in im.convert("RGBA").getdata():
            if p[3] > 0: c[p] += 1
print("tessel·les", ok, mida)
for p, n in sorted(c.items(), key=lambda x: -x[1])[:60]: print("%02x%02x%02x a=%d" % p[:3] + (p[3],) if False else "#%02x%02x%02x a=%d n=%d" % (p[0],p[1],p[2],p[3],n))
PY
