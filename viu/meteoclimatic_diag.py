import re, html, requests, sys
from pathlib import Path
sys.path.insert(0, "viu")
out = []
for c in ["ESCAT1700000017100A", "ESCAT1700000017116A"]:
    r = requests.get(f"https://www.meteoclimatic.net/perfil/{c}", timeout=40,
                     headers={"User-Agent": "LaTdG-tauler/1.0 (+https://latdg.github.io/tauler/)", "Accept": "text/html", "Accept-Language": "es"})
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    out.append(f"=== {c} {r.status_code} {len(r.text)}")
    for k in ["ctualiza", "Total", "Precip", "Episodio"]:
        for m in re.finditer(k, t):
            out.append(f"[{k}] " + t[max(0, m.start() - 80): m.start() + 220])
    import tauler_viu as tv
    out.append("PARSE: " + repr(tv.meteoclimatic_fitxa(c)))
Path("dades/pluja/diag.txt").write_text("\n".join(out), encoding="utf-8")
