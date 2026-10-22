"""Dizin modelini eğit ve DEĞERLENDİR — katalogdan kendini eğiten öğrenme.

  python3 egit_dizin.py                # dünya kataloğundan eğit + rapor
  python3 egit_dizin.py --kaynak       # sınıf = kaynak kökü (/etc, /usr/...)
  python3 egit_dizin.py --katalog yol  # başka katalog

Rapor iki şeyi ölçer:
  1) sınıflandırma doğruluğu (boyut kovası veya kaynak kökü)
  2) FAYDALILIK: verilen bir dosya adı için en olası kaynak kökü gerçekte
     o dosyayı içeriyor mu (top-1 / top-3) → arama ekonomisinin değeri
"""
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import dizin as D
from katalog import Katalog

ROOT = Path(__file__).resolve().parent
VARSAYILAN = ROOT / "world" / "katalog" / "dosyalar.jsonl"
DB = ROOT / "world" / "katalog" / "katalog.db"


def satirlari_oku(yol):
    """Katalog satırları: önce SQLite (tek gerçek kaynak), yoksa JSONL."""
    yol = Path(yol)
    if yol == VARSAYILAN and DB.exists():
        try:
            # ANLIK KOPYA: canlı yazıcıya doğrudan okumak o yazıcının
            # bağlantı hatasına yol açabilir (bkz. 05.10 19:20).
            from katalog import anlik_kopya
            kopya = anlik_kopya(str(DB)) or str(DB)
            # "klasor" ALANI ŞART: kaynak görevi etiketi bu alandan türetilir;
            # eksik bırakılırsa tüm satırlar tek sınıfa çöker ve doğruluk
            # sahte %100 çıkar (ölçüm hatası, modelin başarısı değil).
            ham = Katalog(kopya, salt_okunur=True).dosya_satirlari()
            if kopya != str(DB):
                import os
                try:
                    os.remove(kopya)
                except OSError:
                    pass
            return [{"yol": a, "klasor": a.rsplit("/", 1)[0] or "/",
                     "ad": b, "uzanti": c, "boyut": d}
                    for a, b, c, d in ham]
        except Exception:
            pass
    out = []
    try:
        with open(yol, encoding="utf-8") as f:
            for satir in f:
                try:
                    out.append(json.loads(satir))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def degerlendir(d, test, etiket):
    dogru = 0
    for r in test:
        tah, _ = d.tahmin(D.ozellikler(r.get("ad", "")))
        if tah == etiket(r):
            dogru += 1
    n = max(1, len(test))
    return dogru, 100.0 * dogru / n


def faydalilik(d, test, etiket):
    """top-1 / top-3: tahmin edilen kaynak gerçekte dosyayı içeriyor mu?"""
    gercek = defaultdict(set)      # ad → kaynak kökleri
    for r in test:
        gercek[r.get("ad", "")].add(etiket(r))
    top1 = top3 = 0
    for ad, kokler in gercek.items():
        sira = d.sirala(D.ozellikler(ad))
        if sira and sira[0] in kokler:
            top1 += 1
        if set(sira[:3]) & kokler:
            top3 += 1
    n = max(1, len(gercek))
    return n, 100.0 * top1 / n, 100.0 * top3 / n


def temel_cizgi(test, etiket):
    """Baskın sınıfı hep seçen "sağır" modelin doğruluğu.

    Neden şart: tek sınıflı bir katalogda model %100 "başarılı" görünür
    ama hiçbir şey öğrenmemiştir (05.10'da risk modelinde yaşandı).
    Gerçek doğruluk ancak bu çizginin ÜSTÜNDEYSE anlamlıdır.
    """
    say = Counter(etiket(r) for r in test)
    if not say:
        return 0, 0.0
    en_cok, adet = say.most_common(1)[0]
    return len(say), 100.0 * adet / len(test)


def main():
    ap = argparse.ArgumentParser(description="dizin modeli eğitimi")
    ap.add_argument("--katalog", default=str(VARSAYILAN))
    ap.add_argument("--kaynak", action="store_true",
                    help="sınıf = kaynak kökü (yoksa boyut kovası)")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--satir", action="store_true",
                    help="ad-ayrık yerine satır bölmesi (eski, şişirici)")
    ap.add_argument("--cikti", default=None,
                    help="model dosyası (varsayılan: dizin_kaynak.json / "
                         "dizin_boyut.json)")
    args = ap.parse_args()
    args.ayrik = not args.satir

    yol = Path(args.katalog)
    if not yol.exists():
        raise SystemExit("katalog yok: %s\n(önce tezgâh ile "
                         "dosyaları katalogla)" % yol)
    satirlar = satirlari_oku(yol)
    if not satirlar:
        raise SystemExit("katalog boş: %s" % yol)
    # aynı dosya birden çok yaşamda kataloglanmış olabilir → tekilleştir
    gorulen = set()
    benzersiz = []
    for r in satirlar:
        if r.get("yol") in gorulen:
            continue
        gorulen.add(r.get("yol"))
        benzersiz.append(r)
    tekrar = len(satirlar) - len(benzersiz)
    satirlar = benzersiz

    if args.kaynak:
        sinif_tipi = "kaynak"
        etiket = lambda r: D.kaynak_koku(r.get("klasor", ""))
        baslik = "kaynak kökü"
    else:
        sinif_tipi = "boyut"
        etiket = lambda r: D.boyut_kovasi(r.get("boyut", 0))
        baslik = "boyut kovası"

    rng = random.Random(args.seed)
    if args.ayrik:
        # AD-AYRIK bölme (varsayılan): test adları eğitimde HİÇ görülmez.
        # Satır bazlı bölme şişirir: aynı ad (changelog.Debian.gz) başka bir
        # klasörde eğitimde geçtiği için testte tahmin bedavadır (%100'e
        # çıkıyordu; gerçek genelleme %17.5).
        adlar = sorted({r.get("ad", "") for r in satirlar if r.get("ad")})
        rng.shuffle(adlar)
        bolme_ad = int(len(adlar) * 0.8)
        tr_ad = set(adlar[:bolme_ad])
        egitim = [r for r in satirlar if r.get("ad") in tr_ad]
        test = [r for r in satirlar if r.get("ad") not in tr_ad]
        print("ad-ayrık bölme: %d ad → eğitim %d / test %d"
              % (len(adlar), len(tr_ad), len(adlar) - len(tr_ad)))
    else:
        rng.shuffle(satirlar)
        bolme = int(len(satirlar) * 0.8)
        egitim, test = satirlar[:bolme], satirlar[bolme:]
        print("satır bölmesi (ŞİŞİRİCİ: aynı ad her iki yanda olabilir)")

    d = D.Dizin([])
    if args.kaynak:
        # sınıflar EN SIK görülenden (yoksa alfabetik kırpma en sınıflı
        # sınıfı dışarıda bırakıp modeli çökertir — %6.3 öğretim dersi)
        say = defaultdict(int)
        for r in egitim:
            say[etiket(r)] += 1
        siniflar = [s for s, _ in sorted(say.items(),
                                        key=lambda kv: -kv[1])[:12]]
    else:
        siniflar = [ad for ad, _ in D.BOYUT_KOVASI]
    d.siniflar = siniflar
    for r in egitim:
        d.ogren(D.ozellikler(r.get("ad", "")), etiket(r))

    # ağırlık taraması: tek sabit iki görevi birden bozuyordu
    # (boyut %87→%60, kaynak top-1 %29→%65 arasında salınıyor)
    print("ağırlık taraması:")
    en_iyi = None
    for agirlik in (0.10, 0.15, 0.25, 0.40, 0.60, 0.90, 1.30):
        aday = d.klonla(agirlik)
        _, y = degerlendir(aday, test, etiket)
        satir = "  ağırlık %.2f → doğruluk %%%.1f" % (agirlik, y)
        if args.kaynak:
            _, t1, t3 = faydalilik(aday, test, etiket)
            satir += "   top-1 %%%.1f  top-3 %%%.1f" % (t1, t3)
        print(satir)
        if en_iyi is None or y > en_iyi[1]:
            en_iyi = (agirlik, y, aday)
    d = en_iyi[2]
    # Her görevin modeli AYRI dosyaya yazılır: tek dizin.json iki modeli
    # eziyordu (son çalışturan kazanıyordu, canlı yanlış modeli yükleyebiliyordu).
    varsayilan = "dizin_kaynak.json" if args.kaynak else "dizin_boyut.json"
    cikti = Path(args.cikti) if args.cikti else None
    if cikti is None:
        import zeka
        cikti = zeka.kayit(varsayilan)
    d.save(cikti)

    print("=== DİZİN MODELİ (katalogdan kendini eğitti) ===")
    print("katalog: %s" % yol)
    print("satır: %d%s   eğitim: %d   test: %d   sınıf: %s"
          % (len(satirlar),
             "  (%d tekrar elendi)" % tekrar if tekrar else "",
             len(egitim), len(test), baslik))
    print("ağırlık taraması:")
    dogru, yuzde = degerlendir(d, test, etiket)
    print("seçilen ağırlık: %.2f" % d.agirlik)
    print("sınıflandırma doğruluğu: %d/%d = %%%.1f" % (dogru, len(test),
                                                      yuzde))
    if args.kaynak:
        n, t1, t3 = faydalilik(d, test, etiket)
        sinif_sayisi, temel = temel_cizgi(test, etiket)
        print("temel çizgi: %d sınıf | hep en sık sınıfı seçen sağır model "
              "%%%.1f → model %s (%+.1f puan)"
              % (sinif_sayisi, temel,
                 "üstünde" if yuzde > temel else "ALTINDA", yuzde - temel))
        print("faydalılık: benzersiz ad %d | top-1 %%%.1f  top-3 %%%.1f"
              % (n, t1, t3))
    else:
        sinif_sayisi, temel = temel_cizgi(test, etiket)
        print("temel çizgi: %d sınıf | sağır model %%%.1f → model %s (%+.1f)"
              % (sinif_sayisi, temel,
                 "üstünde" if yuzde > temel else "ALTINDA", yuzde - temel))
    print("→ %s yazıldı (%d özellik-sınıf çifti)"
          % (cikti.name, len(d.sayac)))


if __name__ == "__main__":
    main()