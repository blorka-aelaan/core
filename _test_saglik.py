#!/usr/bin/env python3
"""brain.py sağlık sinyali yeni metotları için hızlı test."""
import sys, tempfile, os
sys.path.insert(0, '.')
import brain as B

hata = []

def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)
    else:
        print("  ok: %s" % mesaj[:70])

b = B.Brain(seed=1)

# 1) Eğitim yoksa nötr (Normal, 75)
puan, idx = b.uretsaglik_sinyeli({'komut': 'nmap', 'dogru': True})
kontrol(puan == 75, "eğitim yoksa nötr puan: %s" % puan)
kontrol(idx == 1, "eğitim yoksa Normal sınıf: %s" % B.SINIFLAR[idx])

# 2) Eğitim ekle
b.ogren_saglik({'komut': 'nmap', 'dogru': True, 'surpriz': 0}, 140, 'Mükemmel')
b.ogren_saglik({'komut': 'nmap', 'dogru': True, 'surpriz': 0}, 135, 'Mükemmel')
b.ogren_saglik({'komut': 'nmap', 'dogru': False, 'surpriz': 1}, 20, 'Ölüm Tehlikesi')
b.ogren_saglik({'komut': 'nmap', 'dogru': False, 'surpriz': 1}, 15, 'Ölüm Tehlikesi')

# 3) Eğitimli durum tahmini
puan, idx = b.uretsaglik_sinyeli({'komut': 'nmap', 'dogru': True, 'surpriz': 0})
kontrol(puan > 100, "nmap başarı yüksek puan: %s" % puan)
kontrol(B.SINIFLAR[idx] == 'Mükemmel', "nmap başarı sınıf: %s" % B.SINIFLAR[idx])

puan, idx = b.uretsaglik_sinyeli({'komut': 'nmap', 'dogru': False, 'surpriz': 1})
kontrol(puan < 40, "nmap başarısız düşük puan: %s" % puan)
kontrol(B.SINIFLAR[idx] == 'Ölüm Tehlikesi', "nmap başarısız sınıf: %s" % B.SINIFLAR[idx])

# 4) Bilinmeyen durum -> nötr
puan, idx = b.uretsaglik_sinyeli({'komut': 'curl', 'dogru': True, 'surpriz': 0})
kontrol(puan == 75, "bilinmeyen durum nötr: %s" % puan)
kontrol(idx == 1, "bilinmeyen durum Normal: %s" % B.SINIFLAR[idx])

# 5) save/load kalıcılık
yol = tempfile.mktemp(suffix='.json')
b.save(yol)
b2 = B.Brain(seed=2)
b2.load(yol)
puan, idx = b2.uretsaglik_sinyeli({'komut': 'nmap', 'dogru': True, 'surpriz': 0})
kontrol(puan > 100, "load sonrası puan korundu: %s" % puan)
kontrol(len(b2.saglik_egitim) == 4, "load sonrası eğitim kayıt sayısı: %s" % len(b2.saglik_egitim))
os.remove(yol)

if hata:
    print("\nHATA (%d):" % len(hata))
    for h in hata:
        print("  - %s" % h)
    raise SystemExit(1)
print("\nSAĞLIK SİNYALİ TESTLERİ: TÜMÜ GECTI")
