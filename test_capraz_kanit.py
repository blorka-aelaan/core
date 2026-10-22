#!/usr/bin/env python3
"""Çapraz (×) özelliklerin KANIT toplamaması — regresyon testi.

KÖK NEDEN 4 (2026-10-22): bağlam çaprazları kombinatoryal olarak üretilir
(N bağlam jetonu → N(N-1)/2 çift). `record_usage()` her çapraza otomatik
kanıt yazdığı için kanıt tablosu gürültüyle doluyordu. Ölçülen canlı beyin:
6.923 kullanım girdisinin 5.732'si (%82,8) çaprazdı; çapraz bağlantılar
8.427 linkin 6.374'ü (%75,7) idi.

Kanıt, budamanın TEK yaşam kaynağı olduğu için bu gürültü, ölü çapraz
bağlantıları "kanıtlı" görünerek koruyordu.

Kontroller:
1) record_usage() çapraz özelliklere kanıt YAZMAZ
2) normal (tekil) özellikler kanıt almaya DEVAM EDER
3) Çapraz bağlantı AĞIRLIKLARI korunur (skor nötr)
4) Eski brain.json'daki birikmiş çapraz kanıt load()da temizlenir
5) load() sonrası çapraz ağırlık korunur → skor değişmez
6) Temizlik sonrası zayıf çapraz bağlantılar budanabilir
7) save→load→load sabit nokta korunur (çapraz kanıt geri gelmez)

Çalıştırma: python3 test_capraz_kanit.py
"""
import json
import os
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


def gecici_yol():
    d = tempfile.mkdtemp(prefix="capraz_kanit_")
    return os.path.join(d, "brain.json")


# 2 bağlam jetonu → 1 çapraz. 3 jeton → 3 çapraz (kombinatoryal).
STIM2 = "gorev:say|son:hata"
STIM3 = "gorev:say|son:hata|ara:yok"
CAPRAZ2 = "gorev:say×son:hata"

# --- 1) record_usage() çapraza kanıt YAZMAZ ---
b = B.Brain(seed=1)
b.learn(STIM3, "eat", 1.0)
b.learn(STIM3, "eat", 1.0)
b.learn(STIM3, "eat", 1.0)
capraz_kayit = [k for k in b.usage if B.Brain._capraz_mi(k[0])]
kontrol(not capraz_kayit,
        "1) record_usage() caprazlara kanit yazmadi (%d)" % len(capraz_kayit))
kontrol(all(k[0] != CAPRAZ2 for k in b.usage),
        "1b) belirli capraz anahtari usage tablosunda yok")

# --- 2) normal (tekil) özellikler kanıt almaya DEVAM EDER ---
tekil = [k for k in b.usage if not B.Brain._capraz_mi(k[0])]
kontrol(len(tekil) == 3,
        "2) uc tekil ozellik kanit aldi: %d" % len(tekil))
kontrol(b.usage.get(("gorev:say", "eat"), 0) == 2,
        "2b) gorev:say sayaci 2 (ilk ogrenmede baglanti yazilmadan "
        "silindi): %s" % b.usage.get(("gorev:say", "eat")))
kontrol(b.usage.get(("son:hata", "eat"), 0) == 2,
        "2c) son:hata sayaci 2: %s" % b.usage.get(("son:hata", "eat")))
b.learn(STIM3, "eat", 1.0)
kontrol(b.usage.get(("gorev:say", "eat"), 0) == 3,
        "2d) tekil ozellik sayaci ARTIYOR (3): %s"
        % b.usage.get(("gorev:say", "eat")))
kontrol(not [k for k in b.usage if B.Brain._capraz_mi(k[0])],
        "2e) 4. ogrenmeden sonra da capraz kanit YOK")

# --- 3) çapraz bağlantı AĞIRLIKLARI korunur (skor nötr) ---
capraz_link = (CAPRAZ2, "eat")
kontrol(capraz_link in b.w,
        "3) capraz BAGLANTI yazildi: %.4f" % b.w.get(capraz_link, 0.0))
kontrol(abs(b.score(STIM3, "eat")) > 0,
        "3b) capraz skora katiliyor: %.4f" % b.score(STIM3, "eat"))

# --- 4/5) eski brain.json'daki birikmiş çapraz kanıt load()da temizlenir ---
eski = {
    "kural": "delta1",
    "links": [[CAPRAZ2, "eat", 1.5], ["gorev:say", "eat", 2.0]],
    "usage": [[CAPRAZ2, "eat", 9], ["gorev:say", "eat", 4]],
    "usage_tasma": [[CAPRAZ2, "eat", 300]],
    "episodic": [],
}
yol = gecici_yol()
Path(yol).write_text(json.dumps(eski, ensure_ascii=False), encoding="utf-8")

c = B.Brain()
c.load(yol)
kontrol(not [k for k in c.usage if B.Brain._capraz_mi(k[0])],
        "4) load() capraz usage girdilerini temizledi")
kontrol(not [k for k in c.usage_tasma if B.Brain._capraz_mi(k[0])],
        "4b) load() capraz usage_tasma girdilerini temizledi")
kontrol(c.usage.get(("gorev:say", "eat"), 0) == 4,
        "4c) normal kanit korundu: %s" % c.usage.get(("gorev:say", "eat")))
kontrol(c.w.get(capraz_link, 0.0) == 1.5,
        "5) capraz BAGLANTI AGIRLIGI korundu: %.4f" % c.w.get(capraz_link, 0.0))
kontrol(abs(c.score(STIM2, "eat") - 3.5) < 1e-9,
        "5b) skor degismedi (3.5): %.4f" % c.score(STIM2, "eat"))

# --- 6) temizlik sonrası zayıf çapraz bağlantılar budanabilir ---
zayif = B.Brain(seed=2)
zayif.w[capraz_link] = 0.01           # esik altı
zayif.w[("gorev:say", "eat")] = 2.0   # güçlü tekil → kalmalı
zayif.usage = {("gorev:say", "eat"): 5}
zayif.usage_tasma = {}
aday = zayif._budama_adayi(0.02)
kontrol(capraz_link in aday,
        "6) zayif capraz baglanti budama adayi oldu")
kontrol(("gorev:say", "eat") not in aday,
        "6b) guclu tekil baglanti korundu")

# --- 7) save→load→load sabit nokta (çapraz kanıt geri gelmez) ---
yol2 = gecici_yol()
d = B.Brain(seed=3)
d.learn(STIM3, "eat", 1.0)
d.save(yol2)
e = B.Brain()
e.load(yol2)
say1 = len(e.usage)
f = B.Brain()
f.load(yol2)
kontrol(len(f.usage) == say1,
        "7) save->load->load sabit nokta: %d == %d" % (say1, len(f.usage)))
kontrol(not [k for k in f.usage if B.Brain._capraz_mi(k[0])],
        "7b) yeniden yuklemede capraz kanit geri gelmedi")

if hata:
    print("\nHATA (%d):" % len(hata))
    for h in hata:
        print("  - %s" % h)
    raise SystemExit(1)
print("\nCAPRAZ KANIT REGRESYON: TUMU GECTI")
