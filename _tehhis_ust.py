"""Teşhis: journal içindeki üst beyin olaylarını say.

Kullanım: python3 _tehhis_ust.py > /tmp/tehhis.txt 2>&1
"""
import collections
import json

OV = "ust_beyn_override"
SF = "ust_beyn_sifirla"
RED = "ust_beyn_reddedildi"

ov = collections.Counter()
red = collections.Counter()
links = []
budanan = []
n = 0
with open("journal.jsonl", errors="replace") as f:
    for line in f:
        if "ust_beyn" not in line:
            continue
        try:
            k = json.loads(line)
        except Exception:
            continue
        e = k.get("kind") or k.get("ad") or k.get("e") or k.get("tur") or ""
        n += 1
        if e == OV:
            ov[k.get("komut")] += 1
        elif e == SF:
            links.append(k.get("links"))
            budanan.append(k.get("budanan"))
        elif e == RED:
            red[(k.get("komut"), k.get("gerekce"))] += 1

print("ust beyin event sayisi:", n)
print("override:", ov.most_common())
print("sifirla calisma:", len(links))
if links:
    print("link ilk/son:", links[:5], links[-5:])
    print("link min/max/ort:", min(links), max(links),
          round(sum(links) / len(links), 1))
if budanan:
    print("budanan ilk/son:", budanan[:5], budanan[-5:])
    print("budanan ort:", round(sum(budanan) / len(budanan), 1),
          "toplam:", sum(budanan))
print("reddedildi:", red.most_common(12))
