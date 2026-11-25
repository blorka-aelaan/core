#!/usr/bin/env python3
"""Sezgi gerçekten ödülü öngörüyor mu?  (journal.jsonl'daki ust_ogren satırları üzerinde)

Yöntem (prequential = geleceğe bakmaz):
  her satır t için, hafıza yalnızca t-bosluk'a kadar olan satırları bilirken
  kavram_sezgi(sahne_t)[komut_t] sorulur; SONRA satır t hafızaya yazılır.

Ölçü: AUC = rastgele seçilen bir ÖDÜLLÜ satırın sezgisinin, rastgele seçilen bir NÖTR satırın
sezgisinden yüksek olma olasılığı.  0.5 = şans.  Üç yöntem aynı satırlarda kıyaslanır:
  sahne  : gerçek kod (z-skor + Δ sahnesi, birleştirmeli prototip hafızası)
  ham    : eski gösterim (ham S_t kosinüsü, k-en-yakın)  -> ortak taban yüzünden zayıf olmalı
  komut  : sahneden bağımsız, komutun şimdiye kadarki ortalama ödülü (eski 'komut başına centroid')
Permütasyon: ödüller satırlar arasında karıştırılıp aynı işlem tekrarlanır -> p-değeri.

Çalıştır:   python olcum_sezgi.py                (journal.jsonl)
            python olcum_sezgi.py --sentetik     (boru hattı kendi kendini sınar)
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import noral_beyn as nb  # noqa: E402

YOK = nb.KOMUT_INDEKSI[nb.KOMUT_YOK]
OLU = nb.KAVRAM_ODUL_OLU


class Bellek(nb.NöralUstBeyn):
    """__init__'i atlayan hafif sarmalayıcı: yalnızca kavram_* yöntemleri kullanılır."""

    def __init__(self):
        self.kavram_prototipi = []
        self.kavram_max = 256
        self.tik = 0


class HamKNN:
    """Eski gösterim: ham S_t kosinüsü, birleştirmesiz, aynı k / eşik / ağırlık kuralı."""

    def __init__(self):
        self.kayit = []

    def sorgu(self, s, komut):
        kom = []
        for v, c, o in self.kayit:
            b = nb.kosinus_benzerligi(s, v)
            if b > nb.KAVRAM_ESIK_SEZGI:
                kom.append((b, c, o))
        kom.sort(key=lambda t: -t[0])
        top = ag = 0.0
        for b, c, o in kom[:nb.KAVRAM_K]:
            if c != komut or c == YOK:
                continue
            w = (b - nb.KAVRAM_ESIK_SEZGI) / (1 - nb.KAVRAM_ESIK_SEZGI)
            top += w * o
            ag += w
        return None if ag == 0 else top / (ag + nb.SEZGI_LAMBDA)

    def ekle(self, s, c, o):
        self.kayit.append((list(s), c, o))


def auc(poz, neg):
    if not poz or not neg:
        return None
    g = 0.0
    for a in poz:
        for b in neg:
            g += 1.0 if a > b else (0.5 if a == b else 0.0)
    return g / (len(poz) * len(neg))


def tabakali_auc(degerler, odul, komut, satirlar_idx):
    """KOMUT İÇİ AUC: yalnızca aynı komutun ödüllü/nötr satırları karşılaştırılır; komutlar
    çift sayısıyla ağırlıklanır. Komut kimliği (ve ona bağlı taban) etkisizleşir."""
    toplam = agir = 0.0
    for c in {komut[i] for i in satirlar_idx}:
        poz = [degerler[i] for i in satirlar_idx if komut[i] == c and odul[i] > OLU]
        neg = [degerler[i] for i in satirlar_idx if komut[i] == c and abs(odul[i]) <= OLU]
        if poz and neg:
            toplam += auc(poz, neg) * len(poz) * len(neg)
            agir += len(poz) * len(neg)
    return (toplam / agir, agir) if agir else (None, 0)


def tabakali_rapor(cikti, odul, komut):
    ortak = [i for i, c in enumerate(cikti) if all(v is not None for v in c)]
    sonuc = {}
    for k, ad in enumerate(("sahne", "ham", "komut")):
        sonuc[ad] = tabakali_auc([c[k] for c in cikti], odul, komut, ortak)
    return sonuc, ortak


def bootstrap_fark(cikti, odul, komut, ortak, tekrar, rnd):
    """Satırları yeniden örnekleyip tabakalı AUC farkı (sahne−komut, sahne−ham) için %95 aralık."""
    fark = {"komut": [], "ham": []}
    for _ in range(tekrar):
        ornek = [rnd.choice(ortak) for _ in ortak]
        # tekrar eden satırları ayrı indekslerle tut (aynı değerler, aynı komut)
        d = {ad: [cikti[i][k] for i in ornek] for k, ad in enumerate(("sahne", "ham", "komut"))}
        o = [odul[i] for i in ornek]
        kk = [komut[i] for i in ornek]
        idx = list(range(len(ornek)))
        a = {ad: tabakali_auc(d[ad], o, kk, idx)[0] for ad in d}
        if None in a.values():
            continue
        fark["komut"].append(a["sahne"] - a["komut"])
        fark["ham"].append(a["sahne"] - a["ham"])
    out = {}
    for ad, v in fark.items():
        v.sort()
        out[ad] = (v[int(.025 * (len(v) - 1))], v[len(v) // 2], v[int(.975 * (len(v) - 1))]) if v else None
    return out


def sahneleri_hazirla(satirlar):
    tr = nb.SahneTakipcisi()
    return [tr.guncelle(r["sinyal"])[2] for r in satirlar]


def gecis(satirlar, sahneler, odul, bosluk):
    """Prequential tek geçiş. Döner: satır başına (sahne, ham, komut) sezgi değerleri (None=bilinmiyor)."""
    bel, ham, ort = Bellek(), HamKNN(), {}
    cikti = []
    for t, r in enumerate(satirlar):
        c = int(r["idx"])
        j = t - bosluk
        if j >= 0:                                   # hafıza yalnızca t-bosluk'a kadarını bilir
            cj = int(satirlar[j]["idx"])
            if cj != YOK:
                bel.tik = j
                bel.kavram_kaydet(sahneler[j], cj, odul[j])
                ham.ekle(satirlar[j]["sinyal"], cj, odul[j])
                n, s = ort.get(cj, (0, 0.0))
                ort[cj] = (n + 1, s + odul[j])
        if c == YOK:
            cikti.append((None, None, None))
            continue
        sz = bel.kavram_sezgi(sahneler[t]).get(c)
        hz = ham.sorgu(satirlar[t]["sinyal"], c)
        n, s = ort.get(c, (0, 0.0))
        kz = (s / n) if n else None
        cikti.append((sz, hz, kz))
    return cikti


def rapor(cikti, odul, ad=""):
    sonuc = {}
    for k, ad_k in enumerate(("sahne", "ham", "komut")):
        # ortak kapsam: üç yöntem de bir değer üretmiş satırlar (adil kıyas)
        pass
    ortak = [i for i, c in enumerate(cikti) if all(v is not None for v in c)]
    for k, ad_k in enumerate(("sahne", "ham", "komut")):
        poz = [cikti[i][k] for i in ortak if odul[i] > OLU]
        neg = [cikti[i][k] for i in ortak if abs(odul[i]) <= OLU]
        sonuc[ad_k] = (auc(poz, neg), len(poz), len(neg))
    kap = {ad_k: sum(1 for c in cikti if c[k] is not None) for k, ad_k in enumerate(("sahne", "ham", "komut"))}
    return sonuc, kap, len(ortak)


def sentetik(n=600, gurultu=0.02, seed=3, mod="sahne"):
    """mod='sahne': ödül SAHNEYE bağlı (durum=1 iken komut 3 ödüllü).
    mod='komut': ödül yalnızca KOMUTA bağlı (komut 3 hep %50 ödüllü, sahneden bağımsız)."""
    r = random.Random(seed)
    satir = []
    for _ in range(n):
        d = r.randrange(2)
        v = [0.6] * nb.SINYAL_BOYUT
        for i in range(6):
            v[i] = 0.5 + r.uniform(-gurultu, gurultu)
        v[0] += 0.12 * d
        v[1] -= 0.10 * d
        c = r.randrange(1, 6)
        if mod == "sahne":
            o = 0.4 if (d == 1 and c == 3) else 0.0
        else:
            o = 0.4 if (c == 3 and r.random() < 0.5) else 0.0
        satir.append({"sinyal": v, "idx": c, "odul": o})
    return satir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--journal", default="journal.jsonl")
    ap.add_argument("--perm", type=int, default=50, help="permütasyon sayısı")
    ap.add_argument("--bosluk", type=int, default=20, help="komşu tik sızıntısını kesen gecikme")
    ap.add_argument("--sentetik", nargs="?", const="sahne", choices=["sahne", "komut"])
    ap.add_argument("--boot", type=int, default=300, help="bootstrap tekrarı")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    if a.sentetik:
        satirlar = sentetik(mod=a.sentetik)
        print("SENTETİK veri (mod=%s)\n" % a.sentetik)
    else:
        satirlar = []
        for l in open(a.journal, encoding="utf-8"):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("kind") == "ust_ogren" and len(d.get("sinyal", [])) == nb.SINYAL_BOYUT:
                satirlar.append(d)
    odul = [float(r["odul"]) for r in satirlar]
    poz = sum(o > OLU for o in odul)
    neg = sum(o < -OLU for o in odul)
    print(f"satır {len(satirlar)} | ödüllü(+) {poz} | olumsuz(−) {neg} | nötr {len(odul) - poz - neg}")
    if poz < 5:
        print("Ödüllü satır < 5: AUC anlamsız olur. Daha fazla ödüllü veri biriktirin.")
        return
    sahneler = sahneleri_hazirla(satirlar)

    for bosluk in sorted({0, a.bosluk}):
        cikti = gecis(satirlar, sahneler, odul, bosluk)
        sonuc, kap, nortak = rapor(cikti, odul)
        print(f"\n--- bosluk={bosluk} tik (hafıza t-{bosluk}'e kadarını bilir) | ortak kapsam {nortak} satır ---")
        for ad_k in ("sahne", "ham", "komut"):
            au, p, n = sonuc[ad_k]
            print(f"  {ad_k:6s} AUC = {('%.3f' % au) if au is not None else '  -  '}   (ödüllü {p}, nötr {n}; "
                  f"tüm satırlarda kapsam {kap[ad_k]}/{len(satirlar)})")

    komut = [int(r["idx"]) for r in satirlar]
    cikti = gecis(satirlar, sahneler, odul, a.bosluk)
    sonuc, ortak = tabakali_rapor(cikti, odul, komut)
    print(f"\n=== KOMUT İÇİ (tabakalı) AUC, bosluk={a.bosluk}: komut kimliği sabitlenir ===")
    for ad in ("sahne", "ham", "komut"):
        au, agir = sonuc[ad]
        print(f"  {ad:6s} {('%.3f' % au) if au is not None else '  -  '}   (karşılaştırılan ödüllü×nötr çifti: {int(agir)})")
    if sonuc["sahne"][0] is None:
        print("Aynı komutta hem ödüllü hem nötr satır yok: komut içi analiz yapılamaz.")
        return
    rnd = random.Random(a.seed)
    bf = bootstrap_fark(cikti, odul, komut, ortak, a.boot, rnd)
    for ad in ("komut", "ham"):
        if bf[ad]:
            lo, md, hi = bf[ad]
            print(f"  fark sahne−{ad:5s}: medyan {md:+.3f}  %95 aralık [{lo:+.3f}, {hi:+.3f}]"
                  + ("   <- 0'ı içermiyor" if lo > 0 or hi < 0 else "   <- 0'ı içeriyor (belirsiz)"))
    # permütasyon: ödüller YALNIZCA AYNI KOMUT İÇİNDE karıştırılır (komut-ödül ilişkisi korunur)
    gercek = sonuc["sahne"][0]
    nul = []
    for _ in range(a.perm):
        p = list(odul)
        for c in set(komut):
            ix = [i for i in range(len(komut)) if komut[i] == c]
            v = [odul[i] for i in ix]
            rnd.shuffle(v)
            for i, x in zip(ix, v):
                p[i] = x
        au = tabakali_rapor(gecis(satirlar, sahneler, p, a.bosluk), p, komut)[0]["sahne"][0]
        if au is not None:
            nul.append(au)
    if nul:
        nul.sort()
        pdeg = (1 + sum(1 for x in nul if x >= gercek)) / (1 + len(nul))
        print(f"\nKomut-içi permütasyon ({len(nul)} tekrar): AUC medyan {nul[len(nul)//2]:.3f}, "
              f"%95 üst {nul[int(.95 * (len(nul) - 1))]:.3f}")
        print(f"Gerçek komut-içi AUC(sahne) = {gercek:.3f}   p ≈ {pdeg:.3f}")
        print("Yorum: sahne komut kimliğinden BAĞIMSIZ bilgi taşıyorsa AUC > 0.5 ve p küçük olur.")


if __name__ == "__main__":
    main()
