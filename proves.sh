set +e
O="Origin: https://latdg.github.io"
H=$(date -u -d '-30 min' +%H); M=$(( ($(date -u -d '-30 min' +%M)/6)*6 )); M=$(printf %02d $M); D=$(date -u -d '-30 min' +%Y/%m/%d)
echo "### METEOCAT radar $D $H:$M"
curl -sS -o /tmp/m.png -D - -H "$O" "https://static-m.meteo.cat/tiles/radar/$D/$H/$M/07/000/000/064/000/000/080.png" | head -20; file /tmp/m.png
python3 -c "
from PIL import Image; im=Image.open('/tmp/m.png'); print(im.mode, im.size, im.info.keys());
im=im.convert('RGBA'); from collections import Counter; c=Counter(im.getdata()); print(c.most_common(25))" 2>&1 | head -5
echo "### METEOCAT z8?"; curl -sS -o /dev/null -w "%{http_code}\n" "https://static-m.meteo.cat/tiles/radar/$D/$H/$M/08/000/000/129/000/000/160.png"
echo "### EUMETSAT LI"
curl -sS -D - -o /tmp/li.png -H "$O" "https://view.eumetsat.int/geoserver/wms?service=WMS&version=1.3.0&request=GetMap&layers=mtg_fd:li_afa&styles=&crs=EPSG:3857&bbox=0,4900000,600000,5400000&width=256&height=256&format=image/png&transparent=true" | head -15; file /tmp/li.png
curl -sS "https://view.eumetsat.int/geoserver/mtg_fd/li_afa/ows?service=WMS&request=GetCapabilities&version=1.3.0" | grep -o '<Dimension[^<]*</Dimension>' | head -3 | cut -c1-300
echo "### RAINVIEWER"
curl -sS -H "$O" -D - -o /tmp/rv.json https://api.rainviewer.com/public/weather-maps.json | grep -i "access-control\|HTTP"; head -c 400 /tmp/rv.json; echo
P=$(python3 -c "import json;d=json.load(open('/tmp/rv.json'));print(d['host']+d['radar']['past'][-1]['path'])")
curl -sS -H "$O" -D - -o /dev/null "$P/256/7/64/47/2/0_1.png" | grep -i "access-control\|HTTP"
echo "### REE PVPC"
T=$(TZ=Europe/Madrid date +%Y-%m-%d)
curl -sS -D - -H "$O" "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real?start_date=${T}T00:00&end_date=${T}T23:59&time_trunc=hour" -o /tmp/ree.json | grep -i "access-control\|HTTP"
python3 -c "
import json;d=json.load(open('/tmp/ree.json'))
for x in d.get('included',[]): print(x['type'], x['attributes'].get('title'), len(x['attributes']['values']), x['attributes']['values'][:2])" 2>&1 | head
echo "### XEMA estacions"
curl -sS "https://analisi.transparenciacatalunya.cat/resource/yqwd-vj5e.json?\$where=nom_municipi%20in('Bisbal%20d''Empord%C3%A0,%20la','Forallac','Cor%C3%A7%C3%A0','Cru%C3%AFlles,%20Monells%20i%20Sant%20Sadurn%C3%AD%20de%20l''Heura','Ullastret')" | head -c 1500; echo
curl -sS "https://analisi.transparenciacatalunya.cat/resource/yqwd-vj5e.json?\$limit=2000" -o /tmp/est.json; python3 -c "
import json,math;d=json.load(open('/tmp/est.json'));print(len(d), d[0].keys())
r=[]
for e in d:
  la,lo=float(e['latitud']),float(e['longitud']);k=math.hypot((la-41.9597)*111,(lo-3.0386)*83)
  if k<25: r.append((round(k,1),e['codi_estacio'],e['nom_estacio'],e.get('nom_municipi'),e.get('codi_estat_ema'),e.get('data_fi')))
for x in sorted(r): print(x)"
echo "### XEMA dades ahir (precipitació, var 35) a UB? "
Y=$(TZ=Europe/Madrid date -d yesterday +%Y-%m-%d)
curl -sS "https://analisi.transparenciacatalunya.cat/resource/nzvn-apee.json?\$where=codi_variable='35'%20AND%20data_lectura%3E='${Y}T00:00:00'&\$limit=5" | head -c 800; echo
curl -sS "https://analisi.transparenciacatalunya.cat/resource/nzvn-apee.json?\$select=max(data_lectura)" ; echo
curl -sS "https://analisi.transparenciacatalunya.cat/resource/7bvh-jvq2.json?\$select=max(data_lectura)" ; echo
curl -sS "https://analisi.transparenciacatalunya.cat/resource/7bvh-jvq2.json?\$limit=3" | head -c 600; echo
echo "### FIRMS public 24h CSV"
curl -sS -o /dev/null -w "%{http_code}\n" https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Europe_24h.csv
