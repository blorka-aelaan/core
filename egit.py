"""Egitim hatti - duysal sahte dongude damak egitimi + hold-out rapor.

  python3 egit.py                    # 50000 tadim egit + rapor + damak.json
  python3 egit.py --ornek 200000     # daha derin egitim
  python3 egit.py --rapor            # sadece degerlendirme (damak.json oku)
  python3 egit.py --kurallar x.json  # farkli kural setiyle calis

Dongu duysaldir: her adim bir "gorme + tadim" - isim uretilir (kutu
grameri), damak tahmin eder, ground truth (kural motoru) okunur, guncellenir.
Egitim maliyetsizdir; gercek hayatta secim baskisi olacak.

HOLD-OUT: isimlerin %10'u (crc32(isim) % 10 == 0) HIC egitime girmez;
degerlendirme yalnizca bu bolumden isim uretir. Boylece "gorulmemis isim"
iddiasi seed'e degil, isme baglidir (cakisma imkansiz).

TABANLAR: rapor, ogrenmeyi yalin yontemlerle kiyaslar - global ortalama
tahmini (MAE), rastgele secim (regret), sans duzeyi (top-3).

NOT: bu surumden once egitilmis damak.json tum isimleri gormus olabilir;
durust rakamlar icin yeniden egitin (python3 egit.py).

Kaynak ASCII-only tutulur (dosya yazan araclar Unicode'u bozabiliyor).
"""
import argparse
import itertools
import json
import random
import time
import zlib
from pathlib import Path

import damak as D
import kutu_uretici as K

ROOT = Path(__file__).resolve().parent
BOLUM_MOD = 10      # her 10 isimden biri hold-out


def holdout_mu(name):
    """Isim hold-out bolumunde mi? (kararli: yalnizca isme bagli)"""
    return zlib.crc32(name.encode("utf-8")) % BOLUM_MOD == 0


def isim_uret(rng, cfg):
    k = cfg["kutu"]
    govde = K._govde(rng, rng.choice(k["govde_uzunluklar"]),
                     rng.choice(k["govde_tipleri"]))
    return govde + k["sonek"]


def bolumlu_isim(rng, cfg, holdout, deneme=10000):
    """Istenen bolumden (egitim / hold-out) isim uret (red ornekleme)."""
    for _ in range(deneme):
        n = isim_uret(rng, cfg)
        if holdout_mu(n) == holdout:
            return n
    raise RuntimeError("isim uzayi cok kucuk: %s bolumu icin isim uretilemedi"
                       % ("hold-out" if holdout else "egitim"))


def egit(cfg, adet, seed=7, kaydet=True):
    """Modeli egit. kaydet=False: diske yazma (test/ablasyon icin).

    NOT (2026-10-18): save() zeka.kayit('damak.json') = GERCEK model
    dosyasi. Testler kaydet=False vermezse her test kosusu 50000'luk
    canli modeli kucuk egitimle cokertir (test_uyku_egit EgitTest,
    500 ornek/37 kova ile yakalandi).
    """
    rng = random.Random(seed)
    d = D.Damak()
    t0 = time.time()
    for _ in range(adet):
        name = bolumlu_isim(rng, cfg, holdout=False)
        feats = D.ozellikler(name, cfg)
        gercek = K.odul_hesapla(name, cfg)   # "tadim": ground truth
        d.ogren(feats, gercek)
    dt = time.time() - t0
    if kaydet:
        d.save()
    return d, dt


def _tip(govde):
    return "sayi" if govde.isdigit() else "harf" if govde.isalpha() else "karisik"


def degerlendir(cfg, d, adet=3000, seed=99):
    """Hold-out: egitimde HIC kullanilmamis isimlerde tahmin dogrulugu.

    Rapor tekrarlanabilir: damak.sec() global random kullandigi icin
    degerlendirme boyunca global durum sabit tohumlanir, sonra geri
    yuklenir.
    """
    rng = random.Random(seed)
    kategoriler = [(u, t)
                   for u in cfg["kutu"]["govde_uzunluklar"]
                   for t in cfg["kutu"]["govde_tipleri"]]
    gercek_k = {k: [] for k in kategoriler}
    tahmin_k = {k: [] for k in kategoriler}
    sonek = cfg["kutu"]["sonek"]
    taban = (d.global_sum / d.global_n) if d.global_n else 0.0
    mae = 0.0
    mae_taban = 0.0
    benzersiz = set()
    for _ in range(adet):
        name = bolumlu_isim(rng, cfg, holdout=True)
        benzersiz.add(name)
        feats = D.ozellikler(name, cfg)
        gercek = K.odul_hesapla(name, cfg)
        tah = d.tahmin(feats)
        mae += abs(tah - gercek)
        mae_taban += abs(taban - gercek)
        govde = name[:-len(sonek)] if name.endswith(sonek) else name
        key = (len(govde), _tip(govde))
        gercek_k.setdefault(key, []).append(gercek)
        tahmin_k.setdefault(key, []).append(tah)

    # grup kaybi (regret): 10 adaylik gruplarda secim kalitesi
    rng2 = random.Random(seed + 1)
    regret = regret_rastgele = 0.0
    top3_isabet = 0
    top3_sans = 0.0
    grup_sayisi = 0
    durum = random.getstate()
    random.seed(seed + 2)
    try:
        for _ in range(adet // 10):
            adaylar = list(dict.fromkeys(
                bolumlu_isim(rng2, cfg, holdout=True) for _ in range(10)))
            gercekler = {n: K.odul_hesapla(n, cfg) for n in adaylar}
            secilen = d.sec(adaylar, cfg, epsilon=0.0)
            degerler = sorted(gercekler.values(), reverse=True)
            k = len(degerler)
            regret += degerler[0] - gercekler[secilen]
            regret_rastgele += degerler[0] - sum(degerler) / k
            # beraberlik dostu top-3: secilenin odulu 3. en iyiden kotu degil
            if gercekler[secilen] >= degerler[min(2, k - 1)]:
                top3_isabet += 1
            top3_sans += min(3, k) / float(k)
            grup_sayisi += 1
    finally:
        random.setstate(durum)

    g = max(1, grup_sayisi)
    mae /= adet
    mae_taban /= adet
    satirlar = []
    means_g = {k: sum(gercek_k[k]) / max(1, len(gercek_k[k]))
               for k in kategoriler}
    means_p = {k: sum(tahmin_k[k]) / max(1, len(tahmin_k[k]))
               for k in kategoriler}
    # ikili uyum: beraberlikler serbest, gerisi yon olarak ayni olmali
    sira_dogru = True
    for a, b in itertools.combinations(kategoriler, 2):
        dg = means_g[a] - means_g[b]
        if abs(dg) < 0.5:      # gercek beraberlik (or. 8-sayi = 8-harf)
            continue
        if dg * (means_p[a] - means_p[b]) <= 0:
            sira_dogru = False
    gercek_sira = sorted(kategoriler, key=lambda k: means_g[k])
    tahmin_sira = sorted(kategoriler, key=lambda k: means_p[k])
    for u, t in sorted(kategoriler):
        gg = gercek_k[(u, t)]
        pp = tahmin_k[(u, t)]
        satirlar.append("%d-%-6s gercek ort %5.1f   tahmin ort %5.1f"
                        % (u, t, sum(gg) / max(1, len(gg)),
                           sum(pp) / max(1, len(pp))))
    rapor = {
        "ornek_adet": adet,
        "holdout_benzersiz": len(benzersiz),
        "mae": round(mae, 2),
        "mae_taban": round(mae_taban, 2),
        "kategori_siralamasi_dogru": sira_dogru,
        "gercek_sira": gercek_sira,
        "tahmin_sira": tahmin_sira,
        "secim_regret": round(regret / g, 2),
        "regret_rastgele": round(regret_rastgele / g, 2),
        "top3_isabet": round(100.0 * top3_isabet / g, 1),
        "top3_sans": round(100.0 * top3_sans / g, 1),
    }
    return rapor, satirlar


def rapor_bas(d, dt, rapor, satirlar):
    print("=== EGITIM ===")
    print("tadim: %d   sure: %.1fs   kova: %d   ornek: %d"
          % (d.samples, dt, len(d.n), d.samples))
    print("=== HOLD-OUT DEGERLENDIRME (egitimde hic gorulmemis isimler) ===")
    print("hold-out ornek: %d (benzersiz isim: %d)"
          % (rapor["ornek_adet"], rapor["holdout_benzersiz"]))
    print("MAE (ortalama mutlak hata): %s   [taban: global ortalama %s]"
          % (rapor["mae"], rapor["mae_taban"]))
    print("kategori siralamasi: %s"
          % ("DOGRU" if rapor["kategori_siralamasi_dogru"] else "YANLIS"))
    print("secim regret (10 adayda kayip): %s   [taban: rastgele secim %s]"
          % (rapor["secim_regret"], rapor["regret_rastgele"]))
    print("top-3 isabet: %%%s   [taban: sans %%%s]"
          % (rapor["top3_isabet"], rapor["top3_sans"]))
    for s in satirlar:
        print("  " + s)
    print("gercek sira: %s" % rapor["gercek_sira"])
    print("tahmin sira: %s" % rapor["tahmin_sira"])


def main():
    ap = argparse.ArgumentParser(description="damak egitim hatti")
    ap.add_argument("--ornek", type=int, default=50000)
    ap.add_argument("--rapor", action="store_true",
                    help="sadece degerlendirme")
    ap.add_argument("--kurallar", default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    cfg = K.load_cfg(args.kurallar)
    d = D.Damak()
    if args.rapor:
        if not d.load():
            raise SystemExit("damak.json yok - once egitim yap")
        dt = 0.0
    else:
        d, dt = egit(cfg, args.ornek, seed=args.seed)
    rapor, satirlar = degerlendir(cfg, d)
    rapor_bas(d, dt, rapor, satirlar)
    rapor["kova_sayisi"] = len(d.n)
    rapor["tadim"] = d.samples
    yol = ROOT / "damak_rapor.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("-> damak modeli + %s yazildi" % yol.name)


if __name__ == "__main__":
    main()



