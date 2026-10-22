import json
import glob
import os

snaps = []
for p in glob.glob("arsiv/**/brain*.json", recursive=True) + glob.glob("arsiv/*brain*.json"):
    try:
        data = json.load(open(p, encoding="utf-8"))
    except Exception:
        continue
    links = data.get("links", [])
    if not isinstance(links, list):
        continue
    zayif = sum(1 for l in links
                if isinstance(l, list) and len(l) > 2
                and abs(float(l[2])) < 0.02)
    snaps.append((os.path.getmtime(p), len(links), zayif, p))

snaps.sort()
print("arsiv beyin anlik sayisi:", len(snaps))
for t, n, z, p in snaps:
    print(f"{n:6d} link  {z:5d} zayif  {os.path.basename(p)}")
