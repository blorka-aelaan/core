"""hedef_kopru.py — Öz hedeflerin üst beynin komut seçimine sınırlı etkisi.

Üst beyin komutu, ağın olasılık dağılımının `argmax`'ından seçer (`tool_bias` olasılığa
eklenir). `_hedef_oncelik_puani` ise yalnızca seçilmiş komutun GÜVENİNİ ölçekler; bu yüzden
hedef çekimi olasılığa küçük bir "bias" olarak eklenir (tool_bias'ın yanında).

Hedef türleri (bkz. oz_hedef.TOHUMLAR):
  * itici hedefler çeker : çevre → ag_tara, gossip ; beden → asm_ogren.
    Çekim = azami_bias × katsayı × aciliyet × soğuma. Aciliyet = 1 − seviye (ölçüm taze ise).
  * kısıt hedefleri sınırlar : zarar_verme / bütünlük seviyesi eşiğin altına düşerse ilgili
    komutların olasılığı AZALIR (veto); bütünlük bozuksa guvenli_mod/kisitla_dosya desteklenir.
  * yüksek etkili komutlar (sifirla, kod_duzenle, cocuk_olustur) ASLA olumlu çekim almaz.

Soğuma: aynı komut tekrar çekilmeden önce beklenir (asm_ogren 2 dakikalık bloklayıcı oturum).
Başlangıçta soğuma kurulur: yeniden başlatma hemen çekime yol açmaz.

Köprü salt yardımcıdır: hata verirse karar akışı çekimsiz sürer, ayarlardan kapatılabilir
(zeka/oz_hedef.json → "ayarlar": {"kopru": {"acik": false}}).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence

ITICI_ESLESTIRME: Dict[str, Dict[str, float]] = {
    "tohum_cevre": {"ag_tara": 1.0, "gossip": 0.4},
    "tohum_beden": {"asm_ogren": 1.0},
}
# kısıt hedefi → (eşik, bastırılan komutlar, desteklenen komutlar)
KISIT_KURALLARI: Dict[str, Dict[str, Any]] = {
    "tohum_zarar_verme": {"esik": 0.67, "bastir": ("ag_tara", "gossip", "cocuk_olustur"),
                          "destekle": ()},
    "tohum_butunluk": {"esik": 0.60, "bastir": ("kod_duzenle", "sifirla", "cocuk_olustur"),
                       "destekle": ("guvenli_mod", "kisitla_dosya")},
}
YUKSEK_ETKILI = ("sifirla", "kod_duzenle", "cocuk_olustur")
YENILENME_SN: Dict[str, float] = {"ag_tara": 600.0, "gossip": 900.0, "asm_ogren": 1800.0}
OLCUM_TAZELIK_SN = 6 * 3600
BILINMEYEN_ACILIYET = 0.4        # ölçüm yok/bayat: orta-düşük çekim, veto yok
DESTEK_ORANI = 0.5               # destek, azami bias'ın bu oranı kadardır
VARSAYILAN_AYAR = {"acik": True, "azami_bias": 0.10}
AZAMI_BIAS_SINIRI = 0.25


class HedefKopru:
    """Hedef durumundan komut-bazlı olasılık bias'ı üretir."""

    def __init__(self, oz: Any, komut_adlari: Sequence[str],
                 clock: Callable[[], float] = time.time,
                 ayar_fn: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        self.oz = oz
        self.komutlar = list(komut_adlari)
        self.clock = clock
        self.ayar_fn = ayar_fn or (lambda: {})
        baslangic = float(clock())
        # Yeniden başlatma sonrası hemen çekim olmasın: soğuma şimdiden başlar.
        self.son_secim: Dict[str, float] = {k: baslangic for k in YENILENME_SN}
        self.secim_sayilari: Dict[str, int] = {}
        self._son_aciklama: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ ayar
    def ayar(self) -> Dict[str, Any]:
        a = dict(VARSAYILAN_AYAR)
        try:
            ham = self.ayar_fn() or {}
        except Exception:
            ham = {}
        if isinstance(ham.get("acik"), bool):
            a["acik"] = ham["acik"]
        try:
            if ham.get("azami_bias") is not None:
                a["azami_bias"] = max(0.0, min(AZAMI_BIAS_SINIRI, float(ham["azami_bias"])))
        except (TypeError, ValueError):
            pass
        return a

    # ------------------------------------------------------------ hedef durumu
    def _seviye(self, hedef_id: str, now: float) -> Optional[float]:
        """Hedefin taze ölçülmüş seviyesi (0..1); yok/bayatsa None."""
        try:
            h = self.oz.kalici.hedefler.get(hedef_id)
        except AttributeError:
            return None
        if not h or h.get("durum", "aktif") != "aktif":
            return None
        o = h.get("son_olcum")
        if not isinstance(o, dict) or o.get("seviye") is None:
            return None
        if now - float(o.get("zaman", 0) or 0) > OLCUM_TAZELIK_SN:
            return None
        return max(0.0, min(1.0, float(o["seviye"])))

    def _soguma(self, komut: str, now: float) -> float:
        sure = YENILENME_SN.get(komut)
        if not sure:
            return 1.0
        return max(0.0, min(1.0, (now - self.son_secim.get(komut, 0.0)) / sure))

    # ------------------------------------------------------------ bias
    def komut_bias(self, komut: str, now: Optional[float] = None) -> Dict[str, Any]:
        """Tek komut için bias ve etkenleri: {"bias": float, "etkenler": [...]}."""
        now = float(self.clock()) if now is None else float(now)
        a = self.ayar()
        azami = float(a["azami_bias"])
        bias, etkenler = 0.0, []
        if not a["acik"] or azami <= 0.0:
            return {"bias": 0.0, "etkenler": []}
        # itici hedeflerin çekimi (yüksek etkili komutlara asla olumlu çekim yok)
        if komut not in YUKSEK_ETKILI:
            toplam = 0.0
            for hid, esles in ITICI_ESLESTIRME.items():
                katsayi = esles.get(komut)
                if not katsayi:
                    continue
                seviye = self._seviye(hid, now)
                aciliyet = BILINMEYEN_ACILIYET if seviye is None else (1.0 - seviye)
                katki = katsayi * aciliyet
                if katki > 0.0:
                    toplam += katki
                    etkenler.append("%s:+%.2f" % (hid.replace("tohum_", ""), katki))
            bias += min(1.0, toplam) * azami * self._soguma(komut, now)
        # kısıt hedeflerinin vetosu / desteği
        veto = 0.0
        for hid, kural in KISIT_KURALLARI.items():
            seviye = self._seviye(hid, now)
            if seviye is None or seviye >= kural["esik"]:
                continue
            siddet = (kural["esik"] - seviye) / kural["esik"]   # 0..1: ne kadar ihlal
            if komut in kural["bastir"]:
                veto = max(veto, azami * (0.5 + 0.5 * siddet))
                etkenler.append("%s:veto" % hid.replace("tohum_", ""))
            elif komut in kural["destekle"]:
                bias += azami * DESTEK_ORANI * (0.5 + 0.5 * siddet)
                etkenler.append("%s:destek" % hid.replace("tohum_", ""))
        if veto > 0.0:
            # Gerçek veto: kısıt ihlal edilmişken itici hedeflerin olumlu çekimi tamamen düşer.
            bias = -veto
        return {"bias": round(bias, 5), "etkenler": etkenler}

    def bias(self, maske: Sequence[bool], now: Optional[float] = None) -> Dict[int, float]:
        """Maskede açık komutlar için {komut_indeksi: bias}; yalnızca sıfırdan farklılar."""
        sonuc: Dict[int, float] = {}
        self._son_aciklama = {}
        for i, ad in enumerate(self.komutlar):
            if i >= len(maske) or not maske[i]:
                continue   # kuralı olmayan komutun (pasif komut dahil) bias'ı zaten 0 olur
            b = self.komut_bias(ad, now)
            if b["bias"]:
                sonuc[i] = b["bias"]
                self._son_aciklama[ad] = b
        return sonuc

    def aciklama(self, komut: str) -> Dict[str, Any]:
        return self._son_aciklama.get(komut, {"bias": 0.0, "etkenler": []})

    # ------------------------------------------------------------ geri bildirim
    def secim_bildir(self, komut: str, now: Optional[float] = None) -> None:
        """Komut seçilip uygulandığında çağrılır: soğumayı başlatır ve sayar."""
        now = float(self.clock()) if now is None else float(now)
        if komut in YENILENME_SN:
            self.son_secim[komut] = now
        self.secim_sayilari[komut] = self.secim_sayilari.get(komut, 0) + 1
