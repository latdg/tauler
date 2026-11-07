import json, sys, time, subprocess, os, threading
sys.path.insert(0, "web/viu")
import tauler_viu
os.makedirs("captures", exist_ok=True)
pa = tauler_viu.pluja_ahir()
print("plujaAhir:", json.dumps(pa, ensure_ascii=False)[:800])
d = json.load(open("web/dades/darrer.json"))
d["blocs"]["plujaAhir"] = pa
json.dump(d, open("web/dades/darrer.json", "w"), ensure_ascii=False)
srv = subprocess.Popen([sys.executable, "-m", "http.server", "8000", "-d", "web"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    for nom, url, mida, espera in [("radar", "http://localhost:8000/radar/", (1100, 900), 45),
                                    ("radar-mobil", "http://localhost:8000/radar/?incrustat=1", (390, 520), 35)]:
        pg = b.new_page(viewport={"width": mida[0], "height": mida[1]})
        pg.on("console", lambda m, n=nom: print(f"[{n}] {m.type}: {m.text}"[:400]))
        pg.on("pageerror", lambda e, n=nom: print(f"[{n}] ERROR: {e}"[:400]))
        pg.on("requestfailed", lambda r, n=nom: print(f"[{n}] FAILED {r.url[:150]} {r.failure}"))
        pg.goto(url); time.sleep(espera)
        print(f"[{nom}] resum:", pg.inner_text("#resum"), "|", pg.inner_text("#hora"), "|", pg.inner_text("#fontText")[:120])
        pg.screenshot(path=f"captures/{nom}.png")
        # Moment de la franja amb més pluja
        pg.close()
    pg = b.new_page(viewport={"width": 1000, "height": 900})
    pg.on("console", lambda m: m.type in ("error", "warning") and print(f"[tauler] {m.type}: {m.text}"[:400]))
    pg.on("pageerror", lambda e: print(f"[tauler] ERROR: {e}"[:400]))
    pg.goto("http://localhost:8000/"); time.sleep(15)
    print("nav:", pg.inner_text("#nav")[:2000].replace("\n", " · "))
    for n in ["Radar 3D", "Pluja d'ahir", "Focus de calor", "Preu de la llum", "Verdor"]:
        s = pg.locator(f'section[data-nom="{n}"]')
        if not s.count():
            print("NO HI ÉS:", n); continue
        s.first.scroll_into_view_if_needed(); time.sleep(12 if n in ("Radar 3D", "Verdor") else 4)
        print(f"== {n}:", s.first.inner_text()[:700].replace("\n", " | "))
        s.first.screenshot(path=f"captures/bloc-{n.replace(' ', '_').replace(chr(39), '')}.png")
    b.close()
srv.terminate()
