#!/usr/bin/env python3
"""arabeyn.py — Ara Beyn: 8 beyin sağlık sinyalini toplar, sadece değişimi İletir.

Mimari:
  8 beyin → Ara Beyn → (sadece delta) → Üst Beyn

Ara Beyn, her beyin'den gelen 0-150 sağlık puanı ve sınıfını toplar.
Önceki tikle karşılaştırır; puan veya sınıf aynıysa susturur (gürültü filtresi).
Değişmişse Üst Beyine (callback ile) iletir.

Kayıt: zeka/arabeyn_sinyalleri.jsonl (isteğe bağlı)
"""

import json
import os
from pathlib import Path

import brain as B


class AraBeyn:
    """8 beyin sağlık sinyalinin toplayıcı ve delta filtresi katmanı."""

    def __init__(self, ust_callback=None, log_yol=None):
        """
        ust_callback: fonksiyon(beyin_adi, puan, sinif_idx, tick)
                      Değişiklik olduğunda çağrılır.
        log_yol:      Her sinyal güncellemesinin yazılacağı JSONL dosyası.
        """
        self.beyinler = {}            # {"ag": Brain, "damak": Brain, ...}
        # Nötr başlangıç: (Normal, 75) — ilk güncellemede gerçek değerle karşılaştırılır.
        self.son_sinyaller = {}       # {"beyin_adi": (puan, sinif_idx)}
        self.ust_callback = ust_callback
        self.log_yol = log_yol
        self.tarihce = []             # (tick, beyin_adi, puan, sinif_idx, degisti)

    def bagla(self, beyin_adi, beyin):
        """Bir beyni Ara Beyine bağlar."""
        self.beyinler[beyin_adi] = beyin
        self.son_sinyaller[beyin_adi] = (75, 1)  # nötr: Normal, 75

    def guncelle(self, beyin_adi, durum, tick):
        """Beyin sağlık sinyalini üretir; değişmişse Üst Beyine iletir.

        döner: True (degisti) / False (ayni)
        """
        if beyin_adi not in self.beyinler:
            return False

        beyin = self.beyinler[beyin_adi]
        puan, sinif_idx = beyin.uretsaglik_sinyeli(durum)

        onceki = self.son_sinyaller.get(beyin_adi)
        degisti = (onceki is None) or (onceki != (puan, sinif_idx))

        self.son_sinyaller[beyin_adi] = (puan, sinif_idx)
        self.tarihce.append((tick, beyin_adi, puan, sinif_idx, degisti))

        if degisti:
            # Üst Beyine delta ilet
            if self.ust_callback:
                self.ust_callback(beyin_adi, puan, sinif_idx, tick)

            # Kalıcı kayıt
            if self.log_yol:
                _yol = Path(self.log_yol)
                _yol.parent.mkdir(parents=True, exist_ok=True)
                with open(_yol, "a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "t": tick,
                        "beyin": beyin_adi,
                        "puan": puan,
                        "sinif": B.SINIFLAR[sinif_idx],
                        "sinif_idx": sinif_idx,
                        "degisti": True,
                    }, ensure_ascii=False) + "\n")

        return degisti

    def durum_raporu(self):
        """Tüm bağlı beyinlerin son sağlık durumunu döndürür."""
        return {
            ad: {"puan": p, "sinif": B.SINIFLAR[s] if s is not None else None}
            for ad, (p, s) in self.son_sinyaller.items()
        }


# --------------------------------------------------------------- Testler
if __name__ == "__main__":
    import tempfile

    hata = []

    def kontrol(kosul, mesaj):
        if not kosul:
            hata.append(mesaj)
        else:
            print("  ok: %s" % mesaj[:70])

    # 8 sahte beyin (brain örnekleri)
    b1 = B.Brain(seed=1)
    b2 = B.Brain(seed=2)

    ara = AraBeyn()
    ara.bagla("ag", b1)
    ara.bagla("damak", b2)

    # İlk güncelleme -> her zaman değişim sayılır
    b1.ogren_saglik({"komut": "nmap", "dogru": True}, 140, "Mükemmel")
    degisti = ara.guncelle("ag", {"komut": "nmap", "dogru": True, "surpriz": 0}, 10)
    kontrol(degisti, "ilk güncelleme değişim sayılır")

    # Aynı durum tekrarlandı -> değişim değil
    degisti2 = ara.guncelle("ag", {"komut": "nmap", "dogru": True, "surpriz": 0}, 20)
    kontrol(not degisti2, "ayın durum tekrarlandıysa değişim değil")

    # Farklı durum -> değişim
    b1.ogren_saglik({"komut": "nmap", "dogru": False, "surpriz": 1}, 15, "Ölüm Tehlikesi")
    degisti3 = ara.guncelle("ag", {"komut": "nmap", "dogru": False, "surpriz": 1}, 30)
    kontrol(degisti3, "farklı durum değişim sayılır")

    # Rapor
    rapor = ara.durum_raporu()
    kontrol("ag" in rapor, "raporda ag var")
    kontrol(rapor["ag"]["sinif"] == "Ölüm Tehlikesi", "rapor sınıfı doğru")

    if hata:
        print("\nHATA (%d):" % len(hata))
        for h in hata:
            print("  - %s" % h)
        raise SystemExit(1)
    print("\nARABEYN TESTLERİ: TÜMÜ GECTI")
