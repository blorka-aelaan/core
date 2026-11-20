"""dusunme.py — deneyimlerden tek-adımlı ödül tahmini.

Her eylemden sonraki gerçek ödülü kaydeder; benzer durumlarda aday
eylemlerin beklenen ödülünü tahmin eder. Tahminler yalnızca tanılama ve
ölçüm için kullanılır; canlı kararları değiştirmez.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class Dusunme:
    """Bağlam/eylem başına ödül ortalaması tutan açıklanabilir model.

    Yeni (Faz 4): durum geçiş takibi (Markov zinciri).
    (onceki_context, eylem) çiftinden sonraki context'in dağılımını
    kaydeder; bu sayede bir eylemin sonraki durumu tehlikeli mi tahmin
    edilebilir.
    """

    SURUM = 2   # 2: durum geçiş takibi eklendi
    ONSEL_GUCU = 3.0
    ODUL_DEGISKENLIK_OLCEGI = 5.0
    ODUL_ALT = -50.0
    ODUL_UST = 80.0

    def __init__(self, ust_beyn, path=None):
        self.ub = ust_beyn
        self.path = Path(path or Path(__file__).resolve().parent
                         / "zeka" / "dusunme.json")
        self.baglam: Dict[Tuple[int, ...], Dict[str, dict]] = {}
        self.eylem: Dict[str, dict] = {}
        self.samples = 0

        # --- Yeni: durum geçiş takibi (Markov zinciri) ---
        # (onceki_anahtar, eylem) -> { sonraki_anahtar: sayi }
        self.gecis: Dict[Tuple[Tuple[int, ...], str], Dict[Tuple[int, ...], int]] = {}
        # (onceki_anahtar, eylem) -> toplam geçiş sayısı
        self.gecis_toplam: Dict[Tuple[Tuple[int, ...], str], int] = {}

    @staticmethod
    def _sinirla(deger: float) -> float:
        try:
            return max(0.0, min(1.0, float(deger)))
        except (ValueError, TypeError):
            # Beklenmeyen tipte bir değer gelirse güvenli varsayılan değer dön
            return 0.0

    @classmethod
    def baglam_anahtari(cls, sinyal_v) -> Tuple[int, ...]:
        """Ödül tahmini için temel yaşam/tehlike sinyallerini kovala."""
        if len(sinyal_v) < 27:
            raise ValueError("Sinyal vektörü en az 27 değer içermeli")
        energy = cls._sinirla(sinyal_v[0])
        hunger = cls._sinirla(sinyal_v[1])
        boredom = cls._sinirla(sinyal_v[3])
        return (
            min(3, int(energy * 4)),
            min(3, int(hunger * 4)),
            int(cls._sinirla(sinyal_v[2]) >= 0.5),
            min(2, int(boredom * 3)),
            int(cls._sinirla(sinyal_v[4]) >= 0.5),
            int(cls._sinirla(sinyal_v[20]) >= 0.5),
            int(cls._sinirla(sinyal_v[21]) >= 0.5),
            int(cls._sinirla(sinyal_v[26]) >= 0.5),
        )

    @staticmethod
    def _ekle(istatistik: dict, odul: float) -> None:
        n = int(istatistik.get("n", 0)) + 1
        ort = float(istatistik.get("ortalama", 0.0))
        m2 = float(istatistik.get("m2", 0.0))
        delta = odul - ort
        ort += delta / n
        m2 += delta * (odul - ort)
        istatistik.update(n=n, ortalama=ort, m2=m2)

    def observe(self, sinyal_v, eylem: str, gercek_odul: float) -> None:
        """Gerçekleşmiş eylem sonucunu modele ekle."""
        if not isinstance(eylem, str) or not eylem:
            raise ValueError("Eylem boş olmayan bir metin olmalı")
        odul = float(gercek_odul)
        if not math.isfinite(odul):
            raise ValueError("Ödül sonlu bir sayı olmalı")
        odul = max(self.ODUL_ALT, min(self.ODUL_UST, odul))
        anahtar = self.baglam_anahtari(sinyal_v)
        baglam_eylemleri = self.baglam.setdefault(anahtar, {})
        self._ekle(baglam_eylemleri.setdefault(eylem, {}), odul)
        self._ekle(self.eylem.setdefault(eylem, {}), odul)
        self.samples += 1

    def observe_gecis(self, onceki_sinyal_v, eylem: str, sonraki_sinyal_v) -> None:
        """(onceki_context, eylem) -> sonraki_context geçişini kaydet.

        Markov zinciri için: eylemden sonra hangi bağlama geçildiğini
        sayar. Daha sonra tahmin_sonraki_sinyal() ile bu dağılımdan
        en olası sonraki bağlam çıkarılır.
        """
        onceki_anahtar = self.baglam_anahtari(onceki_sinyal_v)
        sonraki_anahtar = self.baglam_anahtari(sonraki_sinyal_v)
        gecis_anahtar = (onceki_anahtar, eylem)

        sonrakiler = self.gecis.setdefault(gecis_anahtar, {})
        sonrakiler[sonraki_anahtar] = sonrakiler.get(sonraki_anahtar, 0) + 1
        self.gecis_toplam[gecis_anahtar] = self.gecis_toplam.get(gecis_anahtar, 0) + 1

    def tahmin(self, sinyal_v, eylem: str) -> Tuple[None, Optional[float]]:
        """(sonraki_durum, beklenen_ödül); bilinmeyen eylem None döner."""
        genel = self.eylem.get(eylem)
        if not genel:
            return None, None
        yerel = self.baglam.get(self.baglam_anahtari(sinyal_v), {}).get(eylem)
        if not yerel:
            return None, float(genel["ortalama"])
        n = int(yerel["n"])
        agirlik = n / (n + self.ONSEL_GUCU)
        tahmin = (agirlik * float(yerel["ortalama"])
                  + (1.0 - agirlik) * float(genel["ortalama"]))
        return None, tahmin

    # ------------------------------------------------- Faz 4: durum tahmini

    def tahmin_sonraki_sinyal(
        self, sinyal_v, eylem: str
    ) -> Tuple[Optional[Tuple[int, ...]], Optional[float]]:
        """(sonraki_context_anahtari, olasilik) döndürür.

        (onceki_context, eylem) çifti için gözlenen en olası sonraki
        bağlamı ve olasılığını döner. Geçiş yoksa (None, None).
        """
        onceki_anahtar = self.baglam_anahtari(sinyal_v)
        gecis_anahtar = (onceki_anahtar, eylem)
        sonrakiler = self.gecis.get(gecis_anahtar)
        if not sonrakiler:
            return None, None
        toplam = self.gecis_toplam.get(gecis_anahtar, 1)
        en_iyi_anahtar = max(sonrakiler, key=sonrakiler.get)
        olasilik = sonrakiler[en_iyi_anahtar] / toplam
        return en_iyi_anahtar, round(float(olasilik), 3)

    def tehlike_tahmini(
        self, sinyal_v, eylem: str, drives
    ) -> Tuple[Optional[float], Optional[str]]:
        """Eylemin sonraki durumu tehlike getirecek mi tahmin et.

        Döner: (tehlike_olasiligi, aciklama). Bilinmiyorsa (None, None).
        Tehlike: sonraki bağlamın enerji kova L (düşük) veya açlık kova A
        (yüksek) olması.
        """
        sonraki_anahtar, olasilik = self.tahmin_sonraki_sinyal(sinyal_v, eylem)
        if sonraki_anahtar is None:
            return None, None

        # sonraki_anahtar[0] = energy kova (0=L,1=M,2=H,3=critical)
        # sonraki_anahtar[1] = hunger kova (0=T,1=O,2=A,3=kritik)
        enerji_kova = sonraki_anahtar[0]
        acililik_kova = sonraki_anahtar[1]

        tehlike = 0.0
        nedenler = []
        if enerji_kova == 0:  # L = düşük enerji
            tehlike += 0.4 * olasilik
            nedenler.append("düşük_enerji")
        if acililik_kova >= 2:  # A = yüksek açlık
            tehlike += 0.4 * olasilik
            nedenler.append("yüksek_açlık")

        # Drives ile çapraz kontrol: şu an zaten tehlikedeyse daha ciddi
        if getattr(drives, "in_danger", False):
            tehlike = min(1.0, tehlike + 0.2)
            nedenler.append("zaten_tehlikede")

        tehlike = max(0.0, min(1.0, tehlike))
        aciklama = ", ".join(nedenler) if nedenler else "tehlike_yok"
        return round(float(tehlike), 3), aciklama

    def guven(self, sinyal_v, eylem: str) -> float:
        """Örnek desteği ve gözlenen ödül tutarlılığından güven puanı üret."""
        yerel = self.baglam.get(self.baglam_anahtari(sinyal_v), {}).get(eylem)
        if not yerel:
            return 0.0
        n = int(yerel["n"])
        destek = n / (n + self.ONSEL_GUCU)
        varyans = max(0.0, float(yerel.get("m2", 0.0)) / max(1, n - 1))
        tutarlilik = math.exp(
            -math.sqrt(varyans) / self.ODUL_DEGISKENLIK_OLCEGI
        )
        return self._sinirla(destek * tutarlilik)

    def dusun_ve_sec(self, sinyal_v, feasible) -> Tuple[Optional[str], Optional[float]]:
        """Yalnızca deneyimi olan adaylar içinden en yüksek tahmini döndür."""
        en_iyi = None
        en_yuksek = None
        for eylem in dict.fromkeys(feasible):
            _, tahmin = self.tahmin(sinyal_v, eylem)
            if tahmin is not None and (en_yuksek is None or tahmin > en_yuksek):
                en_iyi, en_yuksek = eylem, tahmin
        return en_iyi, en_yuksek

    def save(self) -> None:
        """Modeli atomik JSON değişimiyle kalıcılaştır."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Geçiş verisini serileştirilebilir formata çevir:
        # ((anahtar_tuple, eylem), {sonraki_anahtar: sayi}) ->
        # {"anahtar": [...], "eylem": "...", "sonrakiler": {"[...]": n}}
        gecis_serial = {}
        for (onceki_anahtar, eylem), sonrakiler in self.gecis.items():
            gecis_key = json.dumps(
                [list(onceki_anahtar), eylem], ensure_ascii=False
            )
            gecis_serial[gecis_key] = {
                "sonrakiler": {
                    json.dumps(list(k), ensure_ascii=False): v
                    for k, v in sonrakiler.items()
                },
                "toplam": self.gecis_toplam.get((onceki_anahtar, eylem), 0),
            }

        veri = {
            "surum": self.SURUM,
            "samples": self.samples,
            "eylem": self.eylem,
            "baglam": [
                {"anahtar": list(anahtar), "eylemler": eylemler}
                for anahtar, eylemler in self.baglam.items()
            ],
            "gecis": gecis_serial,
        }
        fd, gecici = tempfile.mkstemp(
            prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, allow_nan=False)
                f.write("\n")
            os.replace(gecici, self.path)
        except BaseException:
            try:
                os.unlink(gecici)
            except FileNotFoundError:
                pass
            raise

    def load(self) -> bool:
        """Model yoksa False; bozuk veya uyumsuz modelde açıkça hata ver."""
        if not self.path.exists():
            return False
        with self.path.open(encoding="utf-8") as f:
            veri = json.load(f)
        if veri.get("surum") != self.SURUM:
            # Eski sürüm model (SURUM=1): geçiş verisi yok, boş başlat
            if veri.get("surum") == 1:
                self.samples = int(veri.get("samples", 0))
                self.eylem = veri.get("eylem", {})
                self.baglam = {
                    tuple(int(x) for x in satir["anahtar"]): satir["eylemler"]
                    for satir in veri.get("baglam", [])
                }
                self.gecis = {}
                self.gecis_toplam = {}
                return True
            raise ValueError("Desteklenmeyen dusunme model surumu")
        self.samples = int(veri["samples"])
        self.eylem = veri["eylem"]
        self.baglam = {
            tuple(int(x) for x in satir["anahtar"]): satir["eylemler"]
            for satir in veri["baglam"]
        }
        # Geçiş verisini geri yükle
        self.gecis = {}
        self.gecis_toplam = {}
        for gecis_key, veri_degeri in veri.get("gecis", {}).items():
            parsed_key = json.loads(gecis_key)
            onceki_anahtar = tuple(int(x) for x in parsed_key[0])
            eylem = parsed_key[1]
            gecis_anahtar = (onceki_anahtar, eylem)
            sonrakiler = {}
            for sonraki_key, sayi in veri_degeri.get("sonrakiler", {}).items():
                sonraki_anahtar = tuple(int(x) for x in json.loads(sonraki_key))
                sonrakiler[sonraki_anahtar] = int(sayi)
            self.gecis[gecis_anahtar] = sonrakiler
            self.gecis_toplam[gecis_anahtar] = int(veri_degeri.get("toplam", 0))
        return True

