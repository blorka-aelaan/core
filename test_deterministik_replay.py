#!/usr/bin/env python3
"""Deterministik replay testi: brain kayit/yukleme ve karar akisi.

Kontroller:
 1) save() yazip load() tekrar yuklediginde w/episodic/usage birebir geri doner
 2) Tekrarli load() kayitlari kopyalamaz (deterministik geri yukleme)
 3) Ayni seed ile olusturulmus iki beyin, ayni stimuli verildiğinde
    ayni karar dizisini uretir (decide deterministik)
Calistirma: python3 test_deterministik_replay.py
"""
import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain as B

hata = []


def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)
    else:
        print("  ok: %s" % mesaj[:70])


b1 = B.Brain(seed=3)
b1.learn("A|B", "eat", 1.0)
b1.learn("C|D", "wander", -1.0)
b1.learn("A|B", "eat", 2.0)
yol = Path(tempfile.mkdtemp()) / "replay_brain.json"
b1.save(yol)
veri = json.loads(Path(yol).read_text(encoding="utf-8"))

b2 = B.Brain(seed=3)
n = b2.load(yol)
kontrol(n == len(veri["links"]), "load() link sayisini dondurdu")
kontrol(dict(b2.w) == dict(b1.w), "load() sonrasi w birebir geri yuklendi")
kontrol(list(b2.episodic) == list(b1.episodic),
        "load() sonrasi episodic birebir geri yuklendi")
kontrol(b2.usage == b1.usage, "load() sonrasi usage geri yuklendi")

# Tekrarli load: episodic/usage kopyalanmaz
b2.load(yol)
kontrol(list(b2.episodic) == list(b1.episodic),
        "ikinci load() episodic'i kopyalamadi")
kontrol(b2.usage == b1.usage, "ikinci load() usage'i kopyalamadi")

# Karar akisi determinizm: ayni seed, ayni stim dizisi -> ayni secimler
feasible = list(B.ACTIONS)
b5 = B.Brain(seed=11)
b6 = B.Brain(seed=11)
stimler = ["s1|x", "s2|y", "s1|x", "s3|z"] * 12
secimler1 = [b5.decide(s, feasible) for s in stimler]
secimler2 = [b6.decide(s, feasible) for s in stimler]
kontrol(secimler1 == secimler2, "deterministik decide akisi: ayni secimler")

if hata:
    print("\nHATA (%d):" % len(hata))
    for h in hata:
        print("  - %s" % h)
    raise SystemExit(1)
print("\nDETERMINISTIK REPLAY TESTI: TUMU GECTI")