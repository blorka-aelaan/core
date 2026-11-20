"""neden.py — karar neden/kanıt üretimi.

Organizmanın 'neden bu eylemi seçti?' sorusuna cevap veren
açıklama motoru. Her tikte decide() sonrası çağrılır ve şu bilgiler
journal'a 'kind: neden' olarak yazilir:

  * Seçilen eylem ve güven skoru
  * Hangi özelliklerin ne kadar etkili olduğu (özellik katkısı)
  * Geçmişteki benzer deneyimler (aynı stimül-eylem çifti)
  * Beklenen ödül (dusunme modelinden)
  * Tehlike tahmini (dusunme modelinden)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class NedenUretici:
    """Karar açıklama üretir."""

    def __init__(self, mind: Any, dusun: Any = None):
        self.mind = mind
        self.dusun = dusun

    def ozellik_katkisi(
        self, stim: str, act: str, top_n: int = 3
    ) -> List[Tuple[str, float]]:
        """Stimül içerisindeki özelliklerin eyleme katkılarını sıralar.

        stim '|' ile ayrılmış özellikler içerir. Her özellik için
        mind.w[(özellik, eylem)] ağırlığı okunur ve mutlak değere göre
        sıralanır.
        """
        if not hasattr(self.mind, "w") or not hasattr(self.mind, "features"):
            return []
        ozellikler = self.mind.features(stim)
        katkilar: List[Tuple[str, float]] = []
        for oz in ozellikler:
            w = self.mind.w.get((oz, act), 0.0)
            katkilar.append((oz, float(w)))
        # Mutlak değere göre sırala, en büyük top_n'i al
        katkilar.sort(key=lambda kv: abs(kv[1]), reverse=True)
        return katkilar[:top_n]

    def gecmis_deneyim(
        self, stim: str, act: str
    ) -> Optional[Dict[str, Any]]:
        """Aynı (stimül, eylem) çifti için geçmiş deneyim özeti."""
        if not hasattr(self.mind, "usage"):
            return None
        kullan = self.mind.usage.get((stim, act), 0)
        if kullan == 0:
            return None
        # Ortalama ağırlık / puan
        w = self.mind.w  # type: ignore[attr-defined]
        agirliklar = [
            v for (oz, a), v in w.items() if a == act and oz in self.mind.features(stim)  # type: ignore[attr-defined]
        ]
        ort_w = sum(agirliklar) / len(agirliklar) if agirliklar else 0.0
        return {
            "kullanim_sayisi": kullan,
            "ortalama_agirlik": round(ort_w, 4),
        }

    def uret(
        self,
        tik: int,
        stim: str,
        act: str,
        guven: float,
        reward: float,
        dusunme_tahmini: Optional[float] = None,
        dusunme_guven: Optional[float] = None,
        tehlike_olasilik: Optional[float] = None,
        tehlike_aciklama: Optional[str] = None,
        context: str = "act",
    ) -> Dict[str, Any]:
        """Tam neden kaydı oluşturur ve döndürür.

        Çağıran, bu döndürülen sözlüğü journal'a loglar.
        """
        ozellikler = self.ozellik_katkisi(stim, act)
        gecmis = self.gecmis_deneyim(stim, act)

        kayit: Dict[str, Any] = {
            "kind": "neden",
            "t": tik,
            "context": context,
            "eylem": act,
            "guven": round(float(guven), 3),
            "gercek_odul": round(float(reward), 4),
            "ozellik_katkilari": [
                {"ozellik": oz, "agirlik": round(w, 4)} for oz, w in ozellikler
            ],
            "gecmis_deneyim": gecmis,
        }

        if dusunme_tahmini is not None:
            kayit["dusunme_tahmini_odul"] = round(float(dusunme_tahmini), 4)
        if dusunme_guven is not None:
            kayit["dusunme_guven"] = round(float(dusunme_guven), 3)
        if tehlike_olasilik is not None:
            kayit["tehlike_olasiligi"] = round(float(tehlike_olasilik), 3)
            kayit["tehlike_aciklama"] = tehlike_aciklama or "tehlike_yok"

        return kayit