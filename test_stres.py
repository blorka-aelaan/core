#!/usr/bin/env python3
"""Stres testi: coklu tik, rastgele ogrenme, bellek sinirlari ve determinizm.

Kontroller:
 1) working_memory asla working_max'i gecmez
 2) episodic deque maxlen'i saygilir
 3) AGIRLIK_TAVAN kirmasi: buyuk odullerin weight'i tavanlarda kalir
 4) usage, (ozellik x eylem) uzayi ile sinirli (sonsuz buyumaz)
 5) Drives homeostaz her zaman 0..1 arasinda
 6) Ayni seed + ayni olay dizisi -> tamamen ayni durum (deterministik replay)
 7) Farkli seed farkli yolculuk olusturur
Calistirma: python3 test_stres.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain as B
import drives as D

hata = []


def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)
    else:
        print("  ok: %s" % mesaj[:70])


cfg = {"metabolism": {"energy_start": 100.0, "energy_cap": 150.0,
                      "energy_decay_per_tick": 1.0, "hunger_start": 10.0,
                      "hunger_growth_per_tick": 1.0,
                      "eat_hunger_relief": 10.0, "pain_threshold": 30.0}}
ACTIONS = B.ACTIONS


def seri_no(seed):
    """Ayni seed ile calistirilan tek stres senaryosu; son durum dondurulur."""
    rng = random.Random(seed)
    dr = D.Drives(cfg)
    mind = B.Brain(seed=seed)
    for _ in range(300):
        dr.tick()
        mind.working_sindir()
        mind.update_dynamic_params(dr)
        stim = "L|%s|e:%d|h:%d" % (rng.choice(["kok", "oda"]),
                                   int(dr.energy // 10), int(dr.hunger // 10))
        feasible = [a for a in ACTIONS if rng.random() > 0.2]
        if not feasible:
            feasible = list(ACTIONS)
        act = mind.decide(stim, feasible)
        mind.working_remember(stim, act)
        reward = rng.uniform(-5, 10)
        mind.learn(stim, act, reward,
                   r_merak=rng.uniform(0, 2) if rng.random() < 0.3 else 0.0)
        if dr.energy <= 0:
            dr.energy = cfg["metabolism"]["energy_start"]
    return dr, mind


# 1-5) tek calisma sinirlari
dr, mind = seri_no(7)
kontrol(len(mind.working_memory) <= mind.working_max,
        "working_memory siniri: %d" % len(mind.working_memory))
kontrol(len(mind.episodic) <= mind.episodic.maxlen,
        "episodic maxlen: %d" % len(mind.episodic))
maks = max(mind.w.values()) if mind.w else 0.0
kontrol(maks <= B.AGIRLIK_TAVAN + 1e-6,
        "agirlik tavaninda: max=%.2f" % maks)
kontrol(len(mind.usage) <= 120 + len([1 for v in mind.usage.values()
                                     if v >= B.Brain.PRUNE_USAGE_MIN]),
        "usage sinirli: %d girdi" % len(mind.usage))
# KANITLI girdiler tavanı aşabilir (2026-10-22 düzeltmesi): tavan
# gürültüyü keser, kanıtı kesmez. Ama sertleştirilmiş üst sınır asla
# aşılmaz.
kontrol(len(mind.usage) <= B.Brain.USAGE_TAVAN_KALAN,
        "usage sert ust siniri asildi: %d" % len(mind.usage))
kontrol(0.0 <= dr.homeostaz_puani() <= 1.0, "homeostaz 0..1 araliginda")

# 6) deterministik replay: ayni seed, ayni olay dizisi
dr1, m1 = seri_no(42)
dr2, m2 = seri_no(42)
kontrol(dict(m1.w) == dict(m2.w), "deterministik: ayni seed => ayni w")
kontrol(list(m1.episodic) == list(m2.episodic),
        "deterministik: ayni seed => ayni episodic")
kontrol(m1.usage == m2.usage, "deterministik: ayni seed => ayni usage")
kontrol(dr1.energy == dr2.energy and dr1.hunger == dr2.hunger,
        "deterministik: ayni drives durumu")

# 7) farkli seed farkli acilim
_, m3 = seri_no(7)
_, m4 = seri_no(99)
farki = (dict(m3.w) != dict(m4.w)
         or list(m3.episodic) != list(m4.episodic)
         or m3.usage != m4.usage)
kontrol(farki, "farkli seed farkli olusturur")

if hata:
    print("\nHATA (%d):" % len(hata))
    for h in hata:
        print("  - %s" % h)
    raise SystemExit(1)
print("\nSTRES TESTI: TUMU GECTI")