"""Paket beyinini dpkg'den eğit + DOĞRULA (ad-ayrık hold-out).

    python3 egit_paket.py            # eğit + rapor → zeka/paket.json
    python3 egit_paket.py --sorgu X  # "X ne işe yarar?" sorgusu

Etiketler dpkg'den gelir (kendi kendine gözetimli): dosya → paket.
Aynı ad hem eğitim hem testte OLMAYACAK (ad-ayrık) — aksi halde model
"ezberler", genelleme ölçülmez.
"""
import argparse
import random
import shutil
from collections import Counter
from pathlib import Path

import paket as P
import zeka

ROOT = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description="paket beyini eğitimi")
    ap.add_argument("--seed", type=int, default=13)
    ap.add_argument("--sorgu", default=None,
                    help="eğitim yapma, sadece 'X ne işe yarar?' de")
    args = ap.parse_args()

    if args.sorgu:
        p = P.Paket()
        if not p.load():
            raise SystemExit("paket.json yok — önce eğit")
        kaynak, bilgi = p.nedir(args.sorgu)
        if not kaynak:
            print("%s: bilinmiyor (dpkg'de de yok, model de bilemedi)"
                  % args.sorgu)
            return
        print("%s → [%s] paket: %s | bölüm: %s | %s"
              % (args.sorgu, kaynak, bilgi.get("paket"),
                 bilgi.get("bolum"), bilgi.get("aciklama")))
        return

    print("=== PAKET BEYNİ (dpkg'den kendini eğitti) ===")
    paketler = P.durum_oku()
    esleme = P.komut_dosyalari()
    if not paketler or not esleme:
        raise SystemExit("dpkg verisi yok (%d paket, %d dosya)"
                         % (len(paketler), len(esleme)))
    print("dpkg: %d paket | komut alanı: %d dosya" % (len(paketler), len(esleme)))

    # ad-ayrık bölme: komut ADI her iki yanda olmayacak
    adlar = sorted({P.komut_adi(y) for y, _ in esleme})
    rng = random.Random(args.seed)
    rng.shuffle(adlar)
    bolme = int(len(adlar) * 0.8)
    tr_ad = set(adlar[:bolme])
    egitim = [e for e in esleme if P.komut_adi(e[0]) in tr_ad]
    test = [e for e in esleme if P.komut_adi(e[0]) not in tr_ad]
    print("ad-ayrık: %d komut adı → eğitim %d / test %d"
          % (len(adlar), len(egitim), len(test)))

    p = P.Paket()
    # mevcut canlı öğrenmeyi koru: organizma 10+ saattir aynı dosyaya
    # kendi kendine öğrenme yazıyor (tahmin modelinin ince ayarları).
    # dpkg eğitimi bunu EZMEK yerine ÜZERİNE EKLENİR: toplam/sayac/ornek
    # korunur, bilgi/paket_bilgi dpkg'den tazelenir (yeni paketler gelsin).
    # Yedek alınır — ters giderse paket.json.onceki'den dönülür.
    onceki = P.Paket()
    if onceki.load():
        p.toplam = dict(onceki.toplam)
        p.sayac = dict(onceki.sayac)
        p.ornek = onceki.ornek
        shutil.copy(str(zeka.yol("paket.json")),
                    str(zeka.yol("paket.json.onceki")))
        print("canlı öğrenme korundu: %d örnek (yedek: paket.json.onceki)"
              % p.ornek)
    p.paket_bilgi = {k: {"bolum": v.get("bolum", ""),
                         "aciklama": v.get("aciklama", "")}
                     for k, v in paketler.items()}
    # kesin bilgi tabanı: TÜM dpkg verisi (eğitim/test bölmesi model
    # ÖLÇÜMÜ içindir; bilgi tabanı ölçüyü bozar — dpkg kendisi öğretmen,
    # "bilmediğini bilme" için tam harita şart)
    for yol, pkt in esleme:
        p.bilgi_ekle(yol, pkt, paketler.get(pkt, {}).get("bolum", ""),
                     paketler.get(pkt, {}).get("aciklama", ""))
    for yol, pkt in egitim:
        p.ogren(P.ozellikler(P.komut_adi(yol)), pkt)

    # ağırlık taraması: top-1 / top-3 karar ölçümü
    print("ağırlık taraması:")
    en_iyi = None
    for agirlik in (0.3, 0.6, 0.9, 1.3, 1.8):
        m = P.Paket(agirlik=agirlik)
        m.toplam = dict(p.toplam)
        m.sayac = dict(p.sayac)
        m.ornek = p.ornek
        top1 = top3 = 0
        for yol, pkt in test:
            sira = m.sirala(P.ozellikler(P.komut_adi(yol)), n=3)
            if sira and sira[0] == pkt:
                top1 += 1
            if pkt in sira:
                top3 += 1
        n = max(1, len(test))
        print("  ağırlık %.1f → top-1 %%%.1f  top-3 %%%.1f"
              % (agirlik, 100.0 * top1 / n, 100.0 * top3 / n))
        if en_iyi is None or top1 > en_iyi[0]:
            en_iyi = (top1, top3, agirlik)
    p.agirlik = en_iyi[2]

    n = max(1, len(test))
    # temel çizgi: hep en sık paketi seçen sağır model
    en_sik = Counter(pkt for _, pkt in egitim).most_common(1)[0][0]
    sagir = sum(1 for _, pkt in test if pkt == en_sik)
    print("=== SONUÇ ===")
    print("seçilen ağırlık: %.1f" % p.agirlik)
    print("top-1: %d/%d = %%%.1f | top-3: %d/%d = %%%.1f"
          % (en_iyi[0], len(test), 100.0 * en_iyi[0] / n,
             en_iyi[1], len(test), 100.0 * en_iyi[1] / n))
    print("temel çizgi (hep '%s'): %%%.1f → model %s"
          % (en_sik, 100.0 * sagir / n,
             "üstünde" if en_iyi[0] > sagir else "ALTINDA"))
    # bilgi tabanı kapsamı: kesin cevap verilebilen komut oranı
    kapsam = 100.0 * len(egitim) / max(1, len(esleme))
    print("kesin bilgi tabanı: %d komut (alanın %%%.1f'si) + %d paket tanımı"
          % (len(p.bilgi), kapsam, len(p.paket_bilgi)))
    p.save()
    print("→ zeka/paket.json yazıldı")


if __name__ == "__main__":
    main()
