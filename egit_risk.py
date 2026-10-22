"""egit_risk.py — katalogdan risk modelini eğit ve DEĞERLENDİR.

  python3 egit_risk.py

Etiketler ölçülebilir (risk.gercek_sinif): veri / dunya / sistem / kullanici.
Bölme AD-AYRİKTIR (satır bölmesi şişirir: aynı ad her iki yanda olur).
Ölçüm iki kez raporlanır:
  * tüm katalog  (veri sınıfı baskın olduğu için yüksek görünür)
  * SADECE x=1   (karar gerçekten burada veriliyor — asıl ölçüm)
"""
import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path

import risk as R
from katalog import Katalog

ROOT = Path(__file__).resolve().parent
DB = ROOT / "world" / "katalog" / "katalog.db"


def satirlari_oku(sinir=0):
    if not DB.exists():
        return []
    # ANLIK KOPYA: canlı yazıcıya doğrudan okunmayacak (05.10 19:20'de
    # "database disk image is malformed" hatası izleme aracının canlı
    # okumasıyla çakışıyordu). Online backup tutarlı görüntü verir.
    from katalog import anlik_kopya
    kopya = anlik_kopya(DB)
    if not kopya:
        kopya = str(DB)
    k = Katalog(kopya, salt_okunur=True)
    sql = "SELECT yol,ad,uzanti,boyut,x,shebang FROM dosya"
    if sinir:
        sql += " LIMIT %d" % int(sinir)
    try:
        return [{"yol": a, "ad": b, "uzanti": c, "boyut": d, "x": e,
                 "shebang": f} for a, b, c, d, e, f in k.db.execute(sql)]
    finally:
        k.kapat()
        if kopya != str(DB):
            import os
            try:
                os.remove(kopya)
            except OSError:
                pass


def degerlendir(model, test, dunya_koku=None):
    dogru = 0
    yanlis_sinif = Counter()
    for r in test:
        feats = R.ozellikler(r["yol"], r["x"], r["shebang"])
        tah, _ = model.tahmin(feats)
        ger = R.gercek_sinif(r["yol"], r["x"], dunya_koku)
        if tah == ger:
            dogru += 1
        else:
            yanlis_sinif["%s→%s" % (ger, tah)] += 1
    n = max(1, len(test))
    return dogru, 100.0 * dogru / n, yanlis_sinif


def main():
    ap = argparse.ArgumentParser(description="risk modeli eğitimi")
    ap.add_argument("--sinir", type=int, default=0,
                    help="katalogdan en fazla N satır al")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    satirlar = satirlari_oku(args.sinir)
    if not satirlar:
        raise SystemExit("katalog yok/boş: %s" % DB)
    dunya = str(ROOT / "world")

    adlar = sorted({r["ad"] for r in satirlar if r["ad"]})
    rng = random.Random(args.seed)
    rng.shuffle(adlar)
    bolme = int(len(adlar) * 0.8)
    tr_ad = set(adlar[:bolme])
    egitim = [r for r in satirlar if r["ad"] in tr_ad]
    test = [r for r in satirlar if r["ad"] not in tr_ad]

    model = R.Risk()
    for r in egitim:
        model.ogren(R.ozellikler(r["yol"], r["x"], r["shebang"]),
                    R.gercek_sinif(r["yol"], r["x"], dunya))
    say = Counter(R.gercek_sinif(r["yol"], r["x"], dunya) for r in egitim)
    print("=== RİSK MODELİ (katalogdan kendini eğitti) ===")
    print("katalog: %s" % DB)
    print("satır: %d | benzersiz ad: %d → eğitim %d / test %d (ad-ayrık)"
          % (len(satirlar), len(adlar), len(egitim), len(test)))
    print("sınıf dağılımı (eğitim): %s"
          % ", ".join("%s=%d" % kv for kv in say.most_common()))

    print("ağırlık taraması:")
    en_iyi = None
    for agirlik in (0.15, 0.3, 0.45, 0.6, 0.9, 1.3, 1.8):
        m = R.Risk(agirlik=agirlik)
        for r in egitim:
            m.ogren(R.ozellikler(r["yol"], r["x"], r["shebang"]),
                    R.gercek_sinif(r["yol"], r["x"], dunya))
        _, y, _ = degerlendir(m, test, dunya)
        test_x = [r for r in test if r["x"]]
        _, yx, _ = degerlendir(m, test_x, dunya)
        print("  ağırlık %.2f → tüm %%%.1f | x=1 %%%.1f" % (agirlik, y, yx))
        # Karar metriği x=1; ama o metrik bir noktada doyar (ölçüm
        # doyduğunda genel doğruluğun farkı önemlidir) → eşitlik bozucu.
        if en_iyi is None or (yx, y) > (en_iyi[1], en_iyi[2]):
            en_iyi = (agirlik, yx, y, m)
    model = en_iyi[3]
    model.save()

    dogru, yuzde, yanlis = degerlendir(model, test, dunya)
    test_x = [r for r in test if r["x"]]
    dx, yx, yanlis_x = degerlendir(model, test_x, dunya)
    print("seçilen ağırlık: %.2f" % model.agirlik)
    print("TÜM KATALOG  : %d/%d = %%%.1f" % (dogru, len(test), yuzde))
    print("SADECE x=1   : %d/%d = %%%.1f   ← karar ölçümü"
          % (dx, len(test_x), yx))
    if yanlis_x:
        print("en sık karışanlar:", yanlis_x.most_common(6))
    # izin kapısı: model 'dunya' dediğinde gerçekten kendi dünyasında mı?
    izin_verilen = [r for r in test_x
                    if model.tahmin(R.ozellikler(r["yol"], r["x"],
                                                 r["shebang"]))[0] == "dunya"]
    dogru_izin = sum(1 for r in izin_verilen
                     if R.gercek_sinif(r["yol"], r["x"], dunya) == "dunya")
    print("izin kapısı: 'çalıştırılabilir' den %d dosya, %d tanesi gerçekten "
          "kendi dünyasında (kötüye %d)"
          % (len(izin_verilen), dogru_izin, len(izin_verilen) - dogru_izin))
    print("→ risk.json yazıldı (%d özellik-sınıf çifti)"
          % len(model.sayac))


if __name__ == "__main__":
    main()
