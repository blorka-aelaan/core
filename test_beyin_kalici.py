#!/usr/bin/env python3
"""Beyin kalıcılığı + dinamik öğrenme parametreleri regresyon testi.

Kontroller:
1) brain.json'a bağlantılar + episodic + usage yazılır
2) load() bunların HEPSİNİ geri yükler (kayıp yok)
3) Tekrarlanan load() deterministiktir (kayıt kopyalanmaz)
4) Bozuk/eksik alanlar doğuşu iptal etmez (eski brain.json uyumu)
5) Drives.pain GERÇEK metodu ile update_dynamic_params çalışır
   (düşük enerji → epsilon düşer, lr düşer)
6) Düz sayı pain (test sahtesi) de kabul edilir
7) Eksik dosya / bozuk JSON load()u çökertmez

Çalıştırma: python3 test_beyin_kalici.py
"""
import json
import os
import sys
import tempfile
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


def gecici_yol():
    d = tempfile.mkdtemp(prefix="beyin_kalici_")
    return os.path.join(d, "brain.json")


# --- 1) save() episodic + usage + links yazıyor mu? ---
yol = gecici_yol()
b = B.Brain(seed=1)
b.learn("A|B", "eat", 1.0)
b.learn("A|C", "wander", 0.5)
b.learn("A|B", "eat", 2.0)
b.save(yol)
veri = json.loads(Path(yol).read_text(encoding="utf-8"))
kontrol("episodic" in veri, "save() episodic alanini yazdi")
kontrol("usage" in veri, "save() usage alanini yazdi")
kontrol(len(veri.get("episodic", [])) == len(b.episodic),
        "save() episodic sayisi dogru: %s" % len(veri.get("episodic", [])))
kontrol(len(veri.get("usage", [])) == len(b.usage),
        "save() usage sayisi dogru: %s" % len(veri.get("usage", [])))
kontrol(veri.get("kural") == "delta1", "save() kural etiketi korundu")

# --- 2) load() HEPSINI geri yüklüyor mu? ---
c = B.Brain()
yuklenen = c.load(yol)
kontrol(yuklenen == len(veri["links"]), "load() link sayisini dondurdu")
kontrol(len(c.w) == len(b.w), "load() baglantilari geri yukledi")
kontrol(list(c.episodic) == list(b.episodic),
        "load() episodic bellegi birebir geri yukledi")
kontrol(c.usage == b.usage, "load() usage sayaclarini birebir geri yukledi")
# Episodik hatıra gerçekten hatırlanıyor mu?
hatira = c.episodic_recall("A|B")
kontrol(hatira in ("eat", "wander"),
        "load() sonrasi episodic hatirlama calisiyor: %s" % hatira)
# Alışkanlık boostu geri yüklendi mi?
kontrol(abs(c.familiarity_boost("A|B", "eat")
             - b.familiarity_boost("A|B", "eat")) < 1e-9,
        "load() sonrasi aliskanlik boostu korundu")

# --- 3) Tekrarlanan load() deterministik (kayıt kopyalanmaz) ---
c.load(yol)
kontrol(len(c.episodic) == len(b.episodic),
        "ikinci load() episodic'i kopyalamadi: %s" % len(c.episodic))
kontrol(c.usage == b.usage, "ikinci load() usage'i kopyalamadi")

# --- 4) Eski brain.json (episodic/usage alanı YOK) uyumu ---
# Not: Brain.w doğuşta INSTINCTS ile dolu gelir. INSTINCTS'ta OLMAYAN
# bir anahtar seçilir ki yükleme gerçekten yeni bağlantı eklesin.
_eski_beklenen = len(B.Brain.INSTINCTS) + 1
eski = gecici_yol()
Path(eski).write_text(json.dumps(
    {"links": [["X_test", "eat", 1.5]], "allowed": [], "kural": "delta1"}),
    encoding="utf-8")
d = B.Brain()
d.load(eski)
kontrol(len(d.w) == _eski_beklenen,
        "eski brain.json yuklendi: %s" % len(d.w))
kontrol(d.w.get(("X_test", "eat")) is not None,
        "eski brain.json linki geri geldi")
kontrol(len(d.episodic) == 0, "eski brain.json episodic bos")
kontrol(len(d.usage) == 0, "eski brain.json usage bos")
# Bozuk alanlar doğuşu iptal etmez
bozuk = gecici_yol()
Path(bozuk).write_text(json.dumps(
    {"links": [["X_test", "eat", 1.5]], "episodic": [["bozuk"]],
     "usage": [["tek", "eleman"]]}), encoding="utf-8")
e = B.Brain()
e.load(bozuk)
kontrol(len(e.w) == _eski_beklenen,
        "bozuk episodic/usage alanlari baglantilari bozmadi: %s" % len(e.w))
kontrol(len(e.episodic) == 0, "bozuk episodic kaydi atlandi")
kontrol(len(e.usage) == 0, "bozuk usage kaydi atlandi")

# --- 5) Drives.pain GERCEK metodu ile update_dynamic_params ---
cfg = {"metabolism": {"energy_start": 100.0, "energy_decay_per_tick": 1.0,
                       "hunger_start": 10.0, "hunger_growth_per_tick": 1.0,
                       "eat_hunger_relief": 10.0, "energy_cap": 150.0,
                       "pain_threshold": 30.0}}
dr = D.Drives(cfg)
kontrol(callable(dr.pain), "Drives.pain bir metot")
m = B.Brain(seed=2)
m.update_dynamic_params(dr)
lr_yuksek, eps_yuksek = m.lr, m.epsilon
# Enerjiyi acı eşiğinin ALTINA indir → acı 1.0 → epsilon düşmeli
dr.energy = 0.0
m.update_dynamic_params(dr)
kontrol(m.epsilon < eps_yuksek,
        "dusuk enerjide epsilon dustu: %.3f -> %.3f"
        % (eps_yuksek, m.epsilon))
kontrol(m.lr < lr_yuksek,
        "dusuk enerjide lr dustu: %.3f -> %.3f" % (lr_yuksek, m.lr))
kontrol(m.epsilon >= m.eps_min, "epsilon eps_min'in altina dusmedi")
kontrol(m.lr >= m.lr_min, "lr lr_min'in altina dusmedi")
# Aynı durum ikinci kez: sonuç aynı (deterministik)
m2 = B.Brain(seed=2)
m2.update_dynamic_params(dr)
kontrol(abs(m2.epsilon - m.epsilon) < 1e-12,
        "dusuk enerji yolu deterministik")
kontrol(abs(m2.lr - m.lr) < 1e-12, "dusuk enerji lr yolu deterministik")

# --- 6) Düz sayı pain (test sahtesi) de kabul edilir ---
class _DuzPain:
    energy = 0.0
    energy_cap = 150.0
    sikilma = 0.0
    pain = 0.5          # düz sayı, metot değil


m3 = B.Brain(seed=2)
m3.update_dynamic_params(_DuzPain())
kontrol(m3.epsilon < m3.epsilon_base,
        "duz sayi pain ile epsilon dustu: %.3f" % m3.epsilon)

# --- 6b) usage SINIRSIZ BÜYÜMEZ ---
# usage, işlem sayısıyla değil ÖZELLİK×EYLEM uzayıyla sınırlıdır.
# 2000 öğrenme sonrası da ~300 girdi değil, sabit bir boyut kalır.
_g = B.Brain(seed=1)
for _i in range(2000):
    _g.learn("A|B", "eat", 1.0)
kontrol(len(_g.usage) <= 10,
        "2000 ayni ogrenmede usage buyumedi: %s" % len(_g.usage))
_g2 = B.Brain(seed=1)
for _i in range(2000):
    _g2.learn("C|D|%d" % (_i % 20), "eat", 1.0)
kontrol(len(_g2.usage) <= 50,
        "2000 cesitli ogrenmede usage buyumedi: %s" % len(_g2.usage))

# --- 7) Eksik dosya / bozuk JSON load()u çökertmez ---
yok = B.Brain()
kontrol(yok.load("/tmp/olmayan_beyin_12345.json") == 0,
        "eksik dosya load() hatasi vermedi")
bozuk_yol = gecici_yol()
Path(bozuk_yol).write_text("{bozuk json", encoding="utf-8")
kontrol(B.Brain().load(bozuk_yol) == 0, "bozuk JSON load() hatasi vermedi")

if hata:
    print("\nHATA (%d):" % len(hata))
    for h in hata:
        print("  - %s" % h)
    raise SystemExit(1)
print("\nBEYIN KALICILIK + DINAMIK PARAMETRE: TUMU GECTI")
