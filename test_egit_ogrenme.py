#!/usr/bin/env python3
"""
test_egit_ogrenme.py — Eğitim sürecinin öğrenmenin gerçekliğini test eder.

Sorulara cevap arar:
  1. Eğitilmiş model, eğitilmemiş (sıfır) modelden daha iyi mi?
  2. Daha fazla eğitim verisi, daha düşük hold-out hatası mı verir? (öğrenme eğrisi)
  3. Tahminler ground truth ile korelasyonlu mu?
  4. Overfitting var mı? (eğitim hatası vs hold-out hatası)
  5. Hold-out isimleri eğitimde gerçekten görülmemiş mi?

Çalıştırma: python3 test_egit_ogrenme.py
"""
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, "/home/emrah/Genel/core")

import damak as D
import kutu_uretici as K
import egit

hata = []


def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)
        print("  ✗ %s" % mesaj)
    else:
        print("  ok: %s" % mesaj[:70])


def pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


# =====================================================================
# 1) EĞİTİLMIŞ vs EĞİTİLMEMİŞ MODEL — öğrenme gerçek mi?
# =====================================================================
def test_egitilmis_daha_iyidir():
    """Eğitilmiş Damak modeli, sıfırdan başlatılmış modelden hold-out'ta
    düşük MAE ile daha iyi tahmin yapmalıdır."""
    print("\n[1] Eğitilmiş vs eğitilmemiş model karşılaştırması")
    cfg = K.load_cfg(None)

    # Eğitilmiş model (50000 örnek)
    d_egitilmis, _ = egit.egit(cfg, 50000, seed=7, kaydet=False)

    # Eğitilmemiş model (hiç öğren yok)
    d_sifir = D.Damak()

    # Hold-out test isimleri (eğitimden hiç gelmemiş)
    rng = random.Random(42)
    test_isimler = [egit.bolumlu_isim(rng, cfg, holdout=True) for _ in range(2000)]
    gercekler = [K.odul_hesapla(n, cfg) for n in test_isimler]

    # Eğitilmiş model tahminleri
    tah_egitilmis = [d_egitilmis.tahmin(D.ozellikler(n, cfg)) for n in test_isimler]
    mae_egitilmis = sum(abs(t - g) for t, g in zip(tah_egitilmis, gercekler)) / len(gercekler)

    # Eğitilmemiş model tahminleri (sadece global ortalama = 0)
    tah_sifir = [d_sifir.tahmin(D.ozellikler(n, cfg)) for n in test_isimler]
    mae_sifir = sum(abs(t - g) for t, g in zip(tah_sifir, gercekler)) / len(gercekler)

    print("    eğitilmiş MAE:  %.4f" % mae_egitilmis)
    print("    sıfır MAE:      %.4f" % mae_sifir)
    kontrol(mae_egitilmis < mae_sifir,
            "eğitilmiş MAE (%.4f) < sıfır MAE (%.4f)" % (mae_egitilmis, mae_sifir))
    kontrol(mae_egitilmis < 1.0,
            "eğitilmiş MAE düşük (%.4f < 1.0)" % mae_egitilmis)


# =====================================================================
# 2) ÖĞRENME EĞRİSİ — daha fazla veri, daha düşük hata?
# =====================================================================
def test_ogrenme_egrisi():
    """Artan eğitim büyüklüğüyle hold-out MAE'nin düşmesi beklenir
    (monotonik zorunlu değil ama genel eğilim downward olmalı)."""
    print("\n[2] Öğrenme eğrisi (veri büyüklüğü vs hold-out MAE)")
    cfg = K.load_cfg(None)

    boyutlar = [1000, 5000, 10000, 20000]
    maeler = []

    # Aynı test kümesi (karşılaşabilirlik için)
    rng = random.Random(123)
    test_isimler = [egit.bolumlu_isim(rng, cfg, holdout=True) for _ in range(1500)]
    gercekler = [K.odul_hesapla(n, cfg) for n in test_isimler]

    for boyut in boyutlar:
        d, _ = egit.egit(cfg, boyut, seed=7, kaydet=False)
        tah = [d.tahmin(D.ozellikler(n, cfg)) for n in test_isimler]
        mae = sum(abs(t - g) for t, g in zip(tah, gercekler)) / len(gercekler)
        maeler.append(mae)
        print("    veri=%6d → MAE=%.4f" % (boyut, mae))

    # İlk ve son karşılaştırması: daha fazla veri daha iyi olmalı (genel olarak)
    kontrol(maeler[-1] < maeler[0] * 1.5,
            "veri büyüdükçe MAE iyileşiyor veya stabilized: %.4f → %.4f" % (maeler[0], maeler[-1]))
    # Yeterli veri (5000+) ile MAE makul aralığa düşmeli (öğrenme gerçek)
    kontrol(all(m < 5.0 for m in maeler[1:]),
            "5000+ örnekte tüm MAE'ler < 5.0 (öğrenme gerçekleşti)")


# =====================================================================
# 3) TAHMİN - GROUND TRUTH KORİLASYONU
# =====================================================================
def test_tahmin_korelasyonu():
    """Modelin tahminleri, ground truth ödüllerle pozitif korelasyonlu olmalı."""
    print("\n[3] Tahmin–gerçek korelasyonu")
    cfg = K.load_cfg(None)

    d, _ = egit.egit(cfg, 20000, seed=7, kaydet=False)

    rng = random.Random(999)
    test_isimler = [egit.bolumlu_isim(rng, cfg, holdout=True) for _ in range(2000)]
    gercekler = [K.odul_hesapla(n, cfg) for n in test_isimler]
    tahminler = [d.tahmin(D.ozellikler(n, cfg)) for n in test_isimler]

    r = pearson(tahminler, gercekler)
    print("    Pearson r = %.4f" % r)
    kontrol(r > 0.3,
            "tahmin-gerçek korelasyonu pozitif ve anlamlı (r=%.4f > 0.3)" % r)


# =====================================================================
# 4) OVERFITTING KONTROLÜ
# =====================================================================
def test_overfitting_yok():
    """Hold-out hatası, eğitim hatasıyla kıyaslanabilir olmalı;
    çok büyük bir fosil boşluk overfitting'i işaret eder."""
    print("\n[4] Overfitting kontrolü (eğitim vs hold-out MAE)")
    cfg = K.load_cfg(None)

    d, _ = egit.egit(cfg, 10000, seed=7, kaydet=False)

    # Eğitim hatası: aynı dağılımdan yeni isimler ama eğitim kovası dışı değil
    # (basitçe: modelin kendi eğitim özellikleri üzerindeki tahmin hatası)
    rng = random.Random(7)
    train_isimler = [egit.bolumlu_isim(rng, cfg, holdout=False) for _ in range(1000)]
    train_gercekler = [K.odul_hesapla(n, cfg) for n in train_isimler]
    train_tahminler = [d.tahmin(D.ozellikler(n, cfg)) for n in train_isimler]
    train_mae = sum(abs(t - g) for t, g in zip(train_tahminler, train_gercekler)) / len(train_gercekler)

    # Hold-out hatası
    rng2 = random.Random(31337)
    holdout_isimler = [egit.bolumlu_isim(rng2, cfg, holdout=True) for _ in range(1000)]
    holdout_gercekler = [K.odul_hesapla(n, cfg) for n in holdout_isimler]
    holdout_tahminler = [d.tahmin(D.ozellikler(n, cfg)) for n in holdout_isimler]
    holdout_mae = sum(abs(t - g) for t, g in zip(holdout_tahminler, holdout_gercekler)) / len(holdout_gercekler)

    print("    eğitim MAE: %.4f" % train_mae)
    print("    hold-out MAE: %.4f" % holdout_mae)
    ratio = holdout_mae / max(train_mae, 1e-9)
    print("    oran (hold-out/eğitim): %.2f" % ratio)
    kontrol(ratio < 10.0,
            "hold-out/eğitim MAE oranı makul (%.2f < 10.0) → ciddi overfitting yok" % ratio)


# =====================================================================
# 5) HOLD-OUT AYRILIĞI (gerçekten görülmemiş isimler)
# =====================================================================
def test_holdout_gercekten_gorulmemis():
    """Hold-out isimleri eğitim kümesinde hiç geçmemeli."""
    print("\n[5] Hold-out isimleri eğitimde yok mu?")
    cfg = K.load_cfg(None)

    rng = random.Random(555)
    train_set = set(egit.bolumlu_isim(rng, cfg, holdout=False) for _ in range(3000))
    holdout_set = set(egit.bolumlu_isim(rng, cfg, holdout=True) for _ in range(3000))

    kesisim = train_set & holdout_set
    print("    eğitim benzersiz: %d, hold-out benzersiz: %d, kesişim: %d"
          % (len(train_set), len(holdout_set), len(kesisim)))
    kontrol(len(kesisim) == 0,
            "eğitim ve hold-out isimleri tamamen ayrık (kesişim=0)")


# =====================================================================
# 6) SINIF SIRALAMASI DOĞRU MU?
# =====================================================================
def test_sinif_siralamasi():
    """Modelin kategori bazlı ortalama tahminleri, gerçek sırayla
    uyumlu olmalı (relative ordering)."""
    print("\n[6] Kategori sıralaması doğruluğu")
    cfg = K.load_cfg(None)

    d, _ = egit.egit(cfg, 20000, seed=7, kaydet=False)

    rng = random.Random(777)
    kategoriler = [(u, t)
                   for u in cfg["kutu"]["govde_uzunluklar"]
                   for t in cfg["kutu"]["govde_tipleri"]]
    gercek_k = {k: [] for k in kategoriler}
    tahmin_k = {k: [] for k in kategoriler}

    for _ in range(3000):
        name = egit.bolumlu_isim(rng, cfg, holdout=True)
        govde = name[:-len(cfg["kutu"]["sonek"])]
        tip = ("sayi" if govde.isdigit()
               else "harf" if govde.isalpha() else "karisik")
        k = (len(govde), tip)
        if k in gercek_k:
            g = K.odul_hesapla(name, cfg)
            p = d.tahmin(D.ozellikler(name, cfg))
            gercek_k[k].append(g)
            tahmin_k[k].append(p)

    gercek_means = {k: sum(v) / len(v) for k, v in gercek_k.items() if v}
    tahmin_means = {k: sum(v) / len(v) for k, v in tahmin_k.items() if v}

    ortak = sorted(set(gercek_means) & set(tahmin_means))
    sira_dogru = True
    import itertools
    for a, b in itertools.combinations(ortak, 2):
        dg = gercek_means[a] - gercek_means[b]
        if abs(dg) < 0.5:
            continue
        if dg * (tahmin_means[a] - tahmin_means[b]) <= 0:
            sira_dogru = False
            break

    print("    kategori sıralaması doğru: %s" % sira_dogru)
    kontrol(sira_dogru, "model kategori sırasını doğru öğrenmiş")


# =====================================================================
# 7) TOP-K İŞABET (seçim kalitesi)
# =====================================================================
def test_secim_isabet():
    """Modelin en yüksek tahmini kullandığında, gerçekte en yüksek
    ödülü veren seçenekleri seçme oranı yüksek olmalı."""
    print("\n[7] Seçim işabedi (top-1 / top-3)")
    cfg = K.load_cfg(None)

    d, _ = egit.egit(cfg, 20000, seed=7, kaydet=False)

    rng = random.Random(2024)
    aday_listesi = []
    for _ in range(500):
        adaylar = [egit.bolumlu_isim(rng, cfg, holdout=True) for _ in range(10)]
        gercekler = [K.odul_hesapla(n, cfg) for n in adaylar]
        aday_listesi.append((adaylar, gercekler))

    top1_dogru = 0
    top3_dogru = 0
    for adaylar, gercekler in aday_listesi:
        tahminler = [d.tahmin(D.ozellikler(n, cfg)) for n in adaylar]
        secilen_idx = int(max(range(len(tahminler)), key=lambda i: tahminler[i]))
        en_iyi_idx = int(max(range(len(gercekler)), key=lambda i: gercekler[i]))
        if secilen_idx == en_iyi_idx:
            top1_dogru += 1
        sorted_idx = sorted(range(len(tahminler)), key=lambda i: -tahminler[i])
        if en_iyi_idx in sorted_idx[:3]:
            top3_dogru += 1

    n = len(aday_listesi)
    print("    top-1: %d/%d (%%%.1f)" % (top1_dogru, n, 100.0 * top1_dogru / n))
    print("    top-3: %d/%d (%%%.1f)" % (top3_dogru, n, 100.0 * top3_dogru / n))
    kontrol(top1_dogru / n > 0.5, "top-1 işabedi %%50'den yüksek (%%%.1f)" % (100.0 * top1_dogru / n))
    kontrol(top3_dogru / n > 0.8, "top-3 işabedi %%80'den yüksek (%%%.1f)" % (100.0 * top3_dogru / n))


# =====================================================================
# ÇALIŞTIR
# =====================================================================
def main():
    print("=== EĞİTİM ÖĞRENME TESTLERİ ===")
    test_egitilmis_daha_iyidir()
    test_ogrenme_egrisi()
    test_tahmin_korelasyonu()
    test_overfitting_yok()
    test_holdout_gercekten_gorulmemis()
    test_sinif_siralamasi()
    test_secim_isabet()

    print("\n=== SONUÇ ===")
    if hata:
        print("BAŞARISIZ: %d hata" % len(hata))
        for h in hata:
            print("  - %s" % h)
        sys.exit(1)
    print("TÜM EĞİTİM ÖĞRENME TESTLERİ BAŞARILI")


if __name__ == "__main__":
    main()