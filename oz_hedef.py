"""oz_hedef.py — Özgür Hedef Üretimi & Keşir Motoru.

Organizmaya "içsel merak" — yani dışarıdaki ödülden bağımsız,
sürenlilik, keşif ve novelty tabanlı hedefleme yeteneği verir.

Altyapı:
  1. Mevcut drive/energy durumundan "surprise/novelty" skoru çıkar
  2. Mevcut hedeflere (gorev.json/tezgah) ekstra "keşir hedefi" ekle
  3. Bu hedefi main.py metabolism/energy döngüsüne modüle entegrasyonu
"""

from pathlib import Path
from collections import deque
import numpy as np


class OzHedef:
    """
    Özgür hedef motoru.

    MLP beyninin activation'ını ve reward trendini kullanarak,
    organizma "ne öğrenmemişim, keşfettiğimi" sorusuna cevap verir.
    """

    def __init__(self, brain, drives, pencere=50):
        """
        Parametreler
        ----------
        brain : brain_mod.Brain
            Mevcut beyın referansı; lr/epsilon ve internal state için.
        drives : drives_mod.Drives
            İç güdüler (enerji, açlık, pain, in_danger).
        pencere : int
            Ödül/trend pencere boyutu.
        """
        self.brain = brain
        self.drives = drives
        self.pencere = pencere

        # Ödül/keşif geçmişi
        self.odul_gecmisi = deque(maxlen=pencere)
        self.keşif_skoru = 0.0  # 0..1 aralığında, 1 = tamamen yeni/astek

        # Hedef deposu: (hedef_tipi, güçlük, bek ожидание ödül)
        self.hedef_deposu = []

        # Bağlam geçmişi
        self.son_baglam = "rahatlama"
        self.baglam_trend = {b: 0.0 for b in ["tehlike", "aclik", "rahatlama"]}

    def guncelle(self, odul, tick):
        """
        Her tikte çağrılır: ödülü kaydeder, keşif skorunu günceller.

        Parametreler
        ----------
        odul : float
            Bu tick elde edilen sistem ödülü.
        tick : int
            Ana döngü tik sayacı.
        """
        self.odul_gecmisi.append(float(odul))
        self._hesapla_baglam()
        self._hesapla_keşif_skoru()
        # Hedef deposuna yeni keşif hedefi ekle ihtiyacı varsa
        self._yeni_hedef_uret()

    def _hesapla_baglam(self):
        """Anlık iç durumunu tehlike/acık/rahatlama olarak sınıflandır."""
        try:
            energy = float(getattr(self.drives, "energy", 50.0))
            hunger = float(getattr(self.drives, "hunger", 30.0))
        except (TypeError, ValueError):
            energy, hunger = 50.0, 30.0
        _pain = getattr(self.drives, "pain", 0.0)
        try:
            pain = float(_pain() if callable(_pain) else _pain)
        except (TypeError, ValueError):
            pain = 0.0
        pain = max(0.0, min(1.0, pain))
        in_danger = bool(getattr(self.drives, "in_danger", False))

        if in_danger or pain > 0.5 or energy < 30.0 or hunger > 85.0:
            baglam = "tehlike"
        elif energy < 60.0 or hunger > 50.0:
            baglam = "aclik"
        else:
            baglam = "rahatlama"
        self.son_baglam = baglam
        # Trendi kaydet (basit: son N ödül ortalaması değişimi)
        penc = self.odul_gecmisi
        if len(penc) >= 10:
            n = len(penc) // 2
            onceki = sum(list(penc)[:n]) / n
            son = sum(list(penc)[n:]) / n
            aralik = son - onceki
            self.baglam_trend[baglam] = max(-1.0, min(1.0, aralik / max(1.0, abs(onceki) + 0.1)))
        else:
            self.baglam_trend[baglam] = 0.0

    def _hesapla_keşif_skoru(self):
        """Keşif skoru: performans düşürürse ve/context tehlikesi yoksa artar."""
        trend = self.baglam_trend[self.son_baglam]
        # Performans iyilirse (pozitif trend) keşif azalır
        # Performans Worsens (negatif trend) keşif artar
        if trend < -0.05:
            # Ödül çöküyor ve tehlikede değilsek → keşfet
            self.keşif_skoru = min(1.0, abs(trend) * 5.0)
        elif trend > 0.05:
            # Ödül artıyor → mevcut yolunda, keşif azalt
            self.keşif_skoru = max(0.0, 1.0 - abs(trend) * 3.0)
        else:
            # Kararlı → orta seviye keşif (sennaliyet)
            self.keşif_skoru = 0.3

    def _yeni_hedef_uret(self):
        """Keşif skoru yüksek olduğunda yeni bir hedef deposu ekle."""
        if self.keşif_skoru < 0.4:
            return  # Keşif yetersiz, hedef üretme

        # Tehlikedeyseniz keşir farklı: güvenli keşifler
        if self.son_baglam == "tehlike":
            # Tehlikeli koşullarda: sadece "gör/sense" veya "rest" hefleri
            yeni = {"tip": "keşif_guvenli", "aciklama": "tehlikeli ortamda duyarlılık artır"}
            self.hedef_deposu.append(yeni)
        else:
            # Güvenli koşullarda: novel/complex hedefler
            # Örneğin: yeni bir komut dene, yeni bir yol bul, etc.
            novel_commands = ["katalogla", "guvenli_mod", "kapat_ag", "nest"]
            # Random(ya da trenden etkilenerek) bir "novel" hedef seç
            idx = np.random.choice(len(novel_commands))
            yeni = {
                "tip": "novel_eylem",
                "aciklama": f"Yeni eylem dene: {novel_commands[idx]}",
                "eylem": novel_commands[idx],
            }
            self.hedef_deposu.append(yeni)

    def mevcut_hedef(self):
        """
        Kullanılabilir bir hedef döndürür, deposudan çıkARMADAN (peek).

        Hedef eyleme geçirildiğinde main.py'de `hedef_secildi(eylem)` ile
        deposudan temizlenir.

        Dönen
        ------
        dict or None
            {"tip": str, "aciklama": str, "eylem": str | None}
        """
        if self.hedef_deposu:
            return self.hedef_deposu[0]
        return None

    def hedef_secildi(self, eylem):
        """
        Belirtilen eylem seçildiğinde hedef deposundan temizler.

        Aynı hedefin sürekli tekrarlanmasını engeller; eylem gerçekten
        seçildiğinde (mind.decide tarafından) bir kez tüketilir.
        """
        if self.hedef_deposu and self.hedef_deposu[0].get("eylem") == eylem:
            self.hedef_deposu.pop(0)
            return True
        return False

    def durum(self):
        """Güncel oz_hedef durumu raporu."""
        return {
            "keşif_skoru": round(self.keşif_skoru, 3),
            "baglam": self.son_baglam,
            "trend": {b: round(v, 3) for b, v in self.baglam_trend.items()},
            "hedef_sayisi": len(self.hedef_deposu),
            "odul_ortalamasi": round(sum(self.odul_gecmisi) / max(1, len(self.odul_gecmisi)), 3),
        }
