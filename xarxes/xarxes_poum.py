# Xarxes de serveis del POUM de la Bisbal (plànols 4.1 aigua, 4.2.1 residuals, 4.2.2 pluvials,
# 4.3 electricitat, 4.4 gas; fulls a, b i c) -> dades/xarxes/17022.geojson.
# Els fulls van a escala 1/5.000 (A1 a 1/2.500 reduït a A3), nord amunt, i encaixen un sota
# l'altre (2.000 x 1.250 m); la posició es va ajustar sobre els edificis del Cadastre (18.11.2026).
# Ús (des de la carpeta xarxes/): python3 xarxes_poum.py <carpeta amb els PDF>
import sys,glob,json;sys.path.insert(0,'.')
import pymupdf as fitz, numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge
from pyproj import Transformer
from tx import make
W=Transformer.from_crs(25831,4326,always_xy=True)
U=(sys.argv[1] if len(sys.argv)>1 else 'pdf').rstrip('/')+'/'   # carpeta amb els PDF 4.1-4.4 del POUM
def fl(pat): return glob.glob(U+'*'+pat+'-*.pdf')[0]
def draw(fn):
    p=fitz.open(fn)[0]; M=p.rotation_matrix; out=[]
    for x in p.get_drawings():
        c=x.get('color'); w=x.get('width') or 0
        if not c or w<0.5: continue
        c=tuple(round(v,2) for v in c); r=x['rect']*M
        if not (28<r.x0 and r.x1<1163 and 15<r.y0 and r.y1<725): continue
        segs=[]
        for it in x['items']:
            if it[0]=='l': segs.append(((it[1]*M).x,(it[1]*M).y,(it[2]*M).x,(it[2]*M).y))
            elif it[0]=='c': segs.append(((it[1]*M).x,(it[1]*M).y,(it[4]*M).x,(it[4]*M).y))
        out.append((c,r,segs))
    return out
key=lambda s:tuple(round(v,1) for v in s)
# capa: (fitxer, color, xarxa, estat)
CAPES=[('4.1{L}',(0,0,1),'aigua','existent'),
 ('4.2.1{L}',(1,0,0),'residual','existent'),('4.2.1{L}',(1,0.49,0.49),'residual','estimada'),
 ('4.2.1{L}',(0.63,0.31,0),'residual','col·lector'),
 ('4.2.1{L}',(0,0.75,0),'unitaria','existent'),('4.2.1{L}',(0.68,1,0.64),'unitaria','estimada'),
 ('4.2.2{L}',(0,0,1),'pluvial','existent'),('4.2.2{L}',(0.01,1,1),'pluvial','estimada'),
 ('4.3{L}',(0,0,1),'electricitat','existent'),('4.4{L}',(0,0,0.75),'gas','existent')]
feats=[]; stats={}
for L in 'abc':
    f=make(L); cache={}
    D=lambda pat: cache.setdefault(pat, draw(fl(pat.format(L=L))))
    base=set(key(s) for c,r,ss in D('4.4{L}') if c in [(0,0,1),(1,0,0)] for s in ss)
    for pat,col,xa,est in CAPES:
        lines=[]; pous=[]
        for c,r,ss in D(pat):
            if c!=col: continue
            if len(ss)>=3 and r.width<10 and r.height<10: continue   # símbols (vàlvules, pous, CT...)
            for s in ss:
                if key(s) in base and col in [(0,0,1),(1,0,0)]: continue
                a=f([[s[0],s[1]],[s[2],s[3]]])
                if np.hypot(*(a[1]-a[0]))>0.05: lines.append(LineString(a))
        if lines:
            m=linemerge(MultiLineString(lines)); parts=list(m.geoms) if hasattr(m,'geoms') else [m]
            for g in parts:
                if g.length<4: continue
                g=g.simplify(0.3); xs,ys=W.transform(*g.xy)
                feats.append({"type":"Feature","properties":{"xarxa":xa,"estat":est,"full":L},
                  "geometry":{"type":"LineString","coordinates":[[round(x,6),round(y,6)] for x,y in zip(xs,ys)]}})
                stats[(xa,est)]=stats.get((xa,est),0)+g.length
        for p in pous:
            x,y=W.transform(*p); feats.append({"type":"Feature","properties":{"xarxa":xa,"estat":"pou","full":L},"geometry":{"type":"Point","coordinates":[round(x,6),round(y,6)]}})
            stats[(xa,'pous')]=stats.get((xa,'pous'),0)+1
json.dump({"type":"FeatureCollection","features":feats},open('../dades/xarxes/17022.geojson','w'),ensure_ascii=False,separators=(',',':'))
for k,v in sorted(stats.items()): print(k, round(v))
