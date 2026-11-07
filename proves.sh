set +e
UA="LaTdG-tauler/1.0 (+https://latdg.github.io/tauler/)"
echo "### robots"; curl -sS -A "$UA" https://www.meteoclimatic.net/robots.txt | head -30
for r in ESCAT17 ESCAT1700 ESCAT; do echo "### feed $r"; curl -sS -A "$UA" -o /tmp/$r.xml -w "%{http_code} %{size_download}\n" "https://www.meteoclimatic.net/feed/rss/$r"; done
python3 - <<'PY'
import re, html
t = open('/tmp/ESCAT17.xml', encoding='utf-8', errors='replace').read()
items = re.findall(r'<item>(.*?)</item>', t, re.S)
print("items", len(items))
for it in items:
    tit = re.search(r'<title>(.*?)</title>', it, re.S).group(1)
    if re.search(r'bisbal|cor[çc]|forallac|vulpellac|peratallada|canapost|cru[iï]lles|monells|sadurn|ullastret|fonteta|sant climent|casavells|cassa de pelras|matajudaica|rupi', tit, re.I):
        print("==", html.unescape(tit))
        print(re.sub(r'\s+', ' ', html.unescape(it))[:900])
print("--- primer ítem:")
print(re.sub(r'\s+', ' ', html.unescape(items[0]))[:1200] if items else t[:800])
PY
echo "### avís legal"; curl -sS -A "$UA" https://www.meteoclimatic.net/index/aviso_legal 2>/dev/null | python3 -c "import sys,re,html;t=sys.stdin.read();t=re.sub(r'<[^>]+>',' ',t);t=html.unescape(re.sub(r'\s+',' ',t));i=t.lower().find('dato');print(t[max(0,i-300):i+1500])"
