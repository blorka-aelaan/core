"""egit_olum.py — ölüm nedeni modelini eğit ve DEĞERLENDİR.

  python3 egit_olum.py                 # eğit + ağırlık taraması + hold-out raporu
  python3 egit_olum.py --ornek 300     # ölüm başına daha çok gürültülü gözlem
  python3 egit_olum.py --rapor         # sadece değerlendirme (olum.json oku)

Veri katalogdaki 20 ölüm nedeninden GÜRÜLTÜLÜ gözlemle üretilir
(olum.gozlem_uret: her sinyal `kayip` olasılıkla düşer).

ÖLÇÜM İKİ ŞEYDİR:
  1. KATEGORİ (öğrenilen tek başlık): fiziki/yazilimsal/donanimsal/dis.
     Hold-out, HIÇ GÖRÜLMEMİŞ nedenlerde ölçülür → ezber değil genelleme.
     Baseline = hold-out'un en kalabalık kategorisi (majority).
  2. STRATEJİ (kategoriden TÜRETİLMİŞ): kacin/azalt/sinirla. Tahmin edilen
     kategori → strateji haritası; gerçek strateji katalog etiketi. Baseline
     = hold-out'un en yaygın stratejisi. Strateji başarısı = kategori
     başarısının türetilmiş hali olduğu için AYNI anda raporlanır — ayrıca
     bağımsız bir "önlenebilirlik kafası" ÖLÇÜLMEZ, çünkü o öğrenilebilir
     bir hedef değildi (sinyallerden değil, sebep türünden çıkar).

Bölme AD-AYRİK'tir (egit_risk.py ile aynı): paylaşılan sinyaller
(SIGKILL, bellek, cekirdek, belirti…) sayesinde model ezber değil,
özellik→kategori bağını öğrenir. Bu asıl genelleme testidir.
"""
import argparse
import random
from collections import Counter
from pathlib import Path

import olum as O

ROOT = Path(__file__).resolve().parent


def gozlem_seti(adlar, ornek, rng, kayip):
    """Verilen nedenlerden (ad, gozlem) çiftleri üret."""
    cift = []
    for ad in adlar:
        for _ in range(ornek):
            cift.append((ad, O.gozlem_uret(ad, rng, kayip=kayip)))
    return cift


def degerlendir(model, ciftler):
    """(kategori-dogru, orani, strateji-dogru, orani, karisimlar).

    Strateji: tahmin edilen kategoriden türetilir vs katalog etiketi.
    """
    kat_dogru = str_dogru = 0
    karisim = Counter()
    for ad, g in ciftler:
        feats = O.ozellikler(g)
        kat_tah, _ = model.kategori_tahmin(feats)
        str_tah = O.strateji_kategori(kat_tah)
        kat_ger = O.kategori_of(ad)
        str_ger = O.strateji_of(ad)
        if kat_tah == kat_ger:
            kat_dogru += 1
        else:
            karisim["%s→%s" % (kat_ger, kat_tah)] += 1
        if str_tah == str_ger:
            str_dogru += 1
    n = max(1, len(ciftler))
    return (kat_dogru, 100.0 * kat_dogru / n,
            str_dogru, 100.0 * str_dogru / n, karisim)


def baseline(ciftler, alani):
    """Hold-out majority-baseline: `alani` (kategori_of / strateji_of)."""
    say = Counter(alani(ad) for ad, _ in ciftler)
    en = say.most_common(1)[0]
    n = max(1, len(ciftler))
    return en[0], 100.0 * en[1] / n


def loo_degerlendir(ornek, kayip, seed, agirlik=1.8):
    """Leave-one-cause-out: her neden birer birer dışarıda bırakılır.

    Tek rastgele bölme (4 neden) aşırı gürültülüdür — hold-out'un kategori
    karışımı şansa bağlı. BURADA 20 kat vardır: her kat, 19 nedenden öğrenip
    HİÇ GÖRÜLMEMİŞ tek nedeni teşhis eder; sonuçların ortalaması stabil
    gerçek genelleme ölçümüdür.
    """
    adlar = sorted(O._ADI)
    kat_dogru = str_dogru = 0
    toplam = 0
    kat_toplam = Counter()   # kategori → gözlem sayısı
    kat_dogru_say = Counter()  # kategori → doğru teşhis sayısı
    karisim = Counter()
    for i, ad in enumerate(adlar):
        m = O.Olum(agirlik=agirlik)
        digerleri = [a for a in adlar if a != ad]
        for a in digerleri:
            rng = random.Random(seed * 1000 + i)
            for _ in range(ornek):
                m.ogren(O.ozellikler(O.gozlem_uret(a, rng, kayip=kayip)),
                        O.kategori_of(a))
        # dışarıda bırakılan nedeni gürültülü gözlemlerle teşhis et
        rng_t = random.Random(seed * 1000 + i + 777)
        kat_ger = O.kategori_of(ad)
        str_ger = O.strateji_of(ad)
        for _ in range(ornek * 2):
            g = O.gozlem_uret(ad, rng_t, kayip=kayip)
            kat_tah, _ = m.kategori_tahmin(O.ozellikler(g))
            toplam += 1
            kat_toplam[kat_ger] += 1
            if kat_tah == kat_ger:
                kat_dogru += 1
                kat_dogru_say[kat_ger] += 1
            else:
                karisim["%s→%s" % (kat_ger, kat_tah)] += 1
            if O.strateji_kategori(kat_tah) == str_ger:
                str_dogru += 1
    n = max(1, toplam)
    return (kat_dogru, 100.0 * kat_dogru / n,
            str_dogru, 100.0 * str_dogru / n,
            kat_toplam, kat_dogru_say, karisim)



def main():
    ap = argparse.ArgumentParser(description="ölüm modeli eğitimi")
    ap.add_argument("--ornek", type=int, default=120,
                    help="ölüm başına eğitim gözlemi (varsayılan 120)")
    ap.add_argument("--kayip", type=float, default=0.25,
                    help="her sinyalin düşme olasılığı (gürültü)")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--rapor", action="store_true",
                    help="sadece olum.json oku ve değerlendir")
    args = ap.parse_args()

    adlar = sorted(O._ADI)
    if len(adlar) < 4:
        raise SystemExit("katalog boş/çok küçük: %d neden" % len(adlar))

    rng = random.Random(args.seed)
    rng.shuffle(adlar)
    bolme = max(1, int(len(adlar) * 0.8))
    tr_ad = set(adlar[:bolme])
    test_ad = [a for a in adlar if a not in tr_ad]
    # hold-out hiç gözlenmemişse (çok küçük katalog) tüm nedenleri test et
    if not test_ad:
        test_ad = adlar

    model = O.Olum()
    if args.rapor:
        if not model.load():
            raise SystemExit("olum.json yok — önce eğit")
        tr_ad, test_ad = set(adlar), adlar
        print("=== RAPOR (olum.json yüklendi, örnek=%d) ===" % model.ornek)
    else:
        egitim = gozlem_seti(sorted(tr_ad), args.ornek, rng, args.kayip)
        # ağırlık taraması: eğitim ayrı, ölçüm hold-out üzerinde
        print("ağırlık taraması (hold-out %d neden):" % len(test_ad))
        h_test = gozlem_seti(test_ad, 60,
                             random.Random(args.seed + 5), args.kayip)
        en_iyi = None
        for agirlik in (0.15, 0.3, 0.45, 0.6, 0.9, 1.3, 1.8):
            m = O.Olum(agirlik=agirlik)
            for ad, g in egitim:
                m.ogren(O.ozellikler(g), O.kategori_of(ad))
            _, ky, _, sy, _ = degerlendir(m, h_test)
            print("  ağırlık %.2f → kategori %%%.1f | strateji %%%.1f"
                  % (agirlik, ky, sy))
            if en_iyi is None or ky > en_iyi[1]:
                en_iyi = (agirlik, ky, m)
        model = en_iyi[2]
        model.save()

        say = Counter(O.kategori_of(a) for a in tr_ad)
        print("=== ÖLÜM MODELİ (katalogdan kendini eğitti) ===")
        print("neden: %d → eğitim %d / hold-out %d (ad-ayrık)"
              % (len(adlar), len(tr_ad), len(test_ad)))
        print("kategori dağılımı (eğitim): %s"
              % ", ".join("%s=%d" % kv for kv in say.most_common()))
        print("seçilen ağırlık: %.2f" % model.agirlik)

    # ---- hold-out raporu (baseline'larla birlikte) ----
    h_test = gozlem_seti(test_ad, 80,
                         random.Random(args.seed + 9), args.kayip)
    kd, ky, sd, sy, karisim = degerlendir(model, h_test)
    kat_b, kat_by = baseline(h_test, O.kategori_of)
    str_b, str_by = baseline(h_test, O.strateji_of)
    print("KATEGORİ   : %d/%d = %%%.1f   (majority-baseline %%%.1f '%s')"
          % (kd, len(h_test), ky, kat_by, kat_b))
    print("STRATEJİ   : %d/%d = %%%.1f   (majority-baseline %%%.1f '%s')"
          % (sd, len(h_test), sy, str_by, str_b))
    print("  → strateji kategoriden türetilir; lift = %+.1f puan"
          % (sy - str_by))
    if karisim:
        print("en sık karışanlar:", karisim.most_common(6))

    # ---- leave-one-cause-out: stabil genelleme ölçümü (20 kat) ----
    loo_k, loo_ky, loo_s, loo_sy, loo_top, loo_dog, loo_kar = \
        loo_degerlendir(args.ornek, args.kayip, args.seed, model.agirlik)
    print("--- leave-one-cause-out (her neden birer kez dışarıda; %d kat) ---"
          % len(O._ADI))
    print("KATEGORİ   : %%%.1f   | STRATEJİ : %%%.1f" % (loo_ky, loo_sy))
    for kat in O.KATEGORILER:
        if loo_top[kat]:
            print("  %-11s recall %3d/%3d = %%%.1f"
                  % (kat, loo_dog[kat], loo_top[kat],
                     100.0 * loo_dog[kat] / loo_top[kat]))
    print("  en sık karışan (LOO):", loo_kar.most_common(5))

    # ---- zincir & strateji dağılımı (eğitimin değil, katalogun) ----
    zincirli = sum(1 for a in O._ADI if len(O.zincir(a)) > 1)
    strsay = Counter(O.strateji_of(a) for a in O._ADI)
    print("zincir: %d/%d neden bir öncülle bağlanıyor (nedensellik)"
          % (zincirli, len(adlar)))
    print("strateji dağılımı: %s"
          % ", ".join("%s=%d" % kv for kv in strsay.most_common()))
    print("→ olum.json yazıldı (%d özellik-sınıf çifti)" % len(model.sayac))


if __name__ == "__main__":
    main()

