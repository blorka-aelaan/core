"""Uzuv beyinini FAZ 2 verisinden eğit + DOĞRULA (comm-ayrık hold-out).

    python3 egit_uzuv.py           # eğit + rapor → zeka/uzuv.json
    python3 egit_uzuv.py --seed 7  # farklı bölme

Etiketler dışsal: ilk_etiket (dosya sistemi / dpkg) + insan defteri
(uzuv.jsonl). Aynı COMM hem eğitim hem testte OLMAYACAK — süreç adı
ezberi değil, genelleme ölçülür (egit_paket.py ile aynı disiplin).
Eğitim verisi: uzuv_veri.jsonl + arsiv/uzuv_*.jsonl (aidat, satır
sayısı değil benzersiz süreç — 3 dakikalık çekimler aynı süreçleri
tekrarlar, (comm, exe, kullanıcı, paket) ile tekilleştirilir).
"""
import argparse
import glob
import json
import random
from collections import Counter
from pathlib import Path

import uzuv as U

ROOT = Path(__file__).resolve().parent


def satirlari_oku():
    """Tüm uzuv verisini AKIŞKAN okur — ham satır listesi tutulmaz.

    Eski biçim: 20 arşiv × 21MB (~440MB JSON) tek tek json.loads ile
    `kayitlar` listesine yığılıyordu → ~2-3GB RSS → OOM kill (-9) ya da
    300sn timeout (-1); model saatlerce tazelenemiyordu (canlı log:
    uyku_bitti uzuv kod=-1/-9). Yeni biçim: her satır parse edilir
    edilmez (comm,exe,kullanici,paket) anahtarıyla tekilleştirilir;
    tekrar eden satır anında atılır. Tepe bellek ≈ benzersiz süreç
    sayısı (binlerce küçük dict) — dört-ciglik bir fark.

    Kaynak sırası: ESKİDEN YENİYE (arsiv/*, sonra canlı uzuv_veri.jsonl);
    "ilk görülen kazanır" — chronology bozulmaz.
    """
    gorulen = {}
    for yol in (sorted(glob.glob(str(ROOT / "arsiv" / "uzuv_*.jsonl")))
                + [str(U.VERI)]):
        try:
            with open(yol, encoding="utf-8") as f:
                for s in f:
                    s = s.strip()
                    if not s:
                        continue
                    try:
                        k = json.loads(s)
                    except ValueError:
                        continue
                    anahtar = (k.get("comm") or "", k.get("exe") or "",
                               k.get("kullanici") or "", k.get("paket") or "")
                    if anahtar not in gorulen:
                        gorulen[anahtar] = k
        except OSError:
            continue
    return list(gorulen.values())


def main():
    ap = argparse.ArgumentParser(description="uzuv beyini eğitimi")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--defter", default=None, help="alternatif etiket defteri")
    args = ap.parse_args()

    ham = satirlari_oku()
    if not ham:
        raise SystemExit("uzuv verisi yok — önce ag.py çalışsın")
    ornekler = ham   # akışkan tekilleme zaten uygulandı (satirlari_oku)
    defter = U.defter_oku(args.defter)
    for k in ornekler:
        k["_sinif"] = U.etiket(k, defter)
    sayim = Counter(k["_sinif"] for k in ornekler)
    print("=== UZUV BEYNİ (FAZ 2) ===")
    print("ham satır: %d → benzersiz süreç: %d (defter: %d etiket)"
          % (len(ham), len(ornekler), len(defter)))
    for s in U.SINIFLAR:
        print("  %-11s %6d" % (s, sayim.get(s, 0)))
    if not sayim.get("tehlikeli"):
        print("(tehlikeli sınıfı BOŞ — insan defteri henüz dolmadı: "
              "python3 uzuv.py etiketle ...)")

    # comm-ayrık bölme: comm adı her iki yanda olmayacak
    comms = sorted({(k.get("comm") or "?").lower() for k in ornekler})
    rng = random.Random(args.seed)
    rng.shuffle(comms)
    bolme = int(len(comms) * 0.8)
    tr_comm = set(comms[:bolme])
    egitim = [k for k in ornekler
              if (k.get("comm") or "?").lower() in tr_comm]
    test = [k for k in ornekler
            if (k.get("comm") or "?").lower() not in tr_comm]
    print("comm-ayrık: %d comm → eğitim %d / test %d"
          % (len(comms), len(egitim), len(test)))

    if not test:
        raise SystemExit("test kümesi boş — veri yetersiz")

    # ağırlık taraması (egit_paket ile aynı yöntem)
    print("ağırlık taraması:")
    en_iyi = None
    for agirlik in (0.3, 0.6, 0.9, 1.3, 1.8):
        m = U.Uzuv(agirlik=agirlik)
        for k in egitim:
            m.ogren(U.ozellikler(k), k["_sinif"])
        dogru = 0
        for k in test:
            if m.tahmin(U.ozellikler(k))[0] == k["_sinif"]:
                dogru += 1
        n = max(1, len(test))
        print("  ağırlık %.1f → doğruluk %%%.1f"
              % (agirlik, 100.0 * dogru / n))
        if en_iyi is None or dogru > en_iyi[0]:
            en_iyi = (dogru, agirlik)

    # en iyi ağırlıkla karışma matrisi
    _, agirlik = en_iyi
    m = U.Uzuv(agirlik=agirlik)
    for k in egitim:
        m.ogren(U.ozellikler(k), k["_sinif"])
    karisik = {a: Counter() for a in U.SINIFLAR}
    for k in test:
        tah = m.tahmin(U.ozellikler(k))[0]
        karisik[k["_sinif"]][tah] += 1
    print("karışma matrisi (satır=gerçek, sütun=tahmin):")
    bas = "            " + " ".join("%-11s" % s for s in U.SINIFLAR)
    print(bas)
    for a in U.SINIFLAR:
        print("  %-10s " % a + " ".join(
            "%-11d" % karisik[a].get(s, 0) for s in U.SINIFLAR))

    n = len(test)
    dogru = sum(karisik[a].get(a, 0) for a in U.SINIFLAR)
    en_sik = sayim.most_common(1)[0][0]
    sagir = sum(1 for k in test if k["_sinif"] == en_sik)
    print("=== SONUÇ ===")
    print("doğruluk: %d/%d = %%%.1f | temel çizgi (hep '%s'): %%%.1f → %s"
          % (dogru, n, 100.0 * dogru / n, en_sik, 100.0 * sagir / n,
             "üstünde" if dogru >= sagir else "ALTINDA"))

    # SON model: TÜM veriyle, en iyi ağırlıkla (hold-out ölçüm içindir;
    # canlı model tüm bilgiyle eğitilir — egit_paket disiplini)
    m = U.Uzuv(agirlik=agirlik)
    for k in ornekler:
        m.ogren(U.ozellikler(k), k["_sinif"])
    m.save()
    print("→ %s yazıldı (%d örnek)"
          % (U.zeka.kayit("uzuv.json"), m.ornek))


if __name__ == "__main__":
    main()
