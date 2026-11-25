"""oz_hedef.py — Özgür Hedef Üretimi & Keşir Motoru.

Organizmaya "içsel merak" — yani dışarıdaki ödülden bağımsız,
sürenlilik, keşif ve novelty tabanlı hedefleme yeteneği verir.

Altyapı:
  1. Mevcut drive/energy durumundan "surprise/novelty" skoru çıkar
  2. Mevcut hedeflere (gorev.json/tezgah) ekstra "keşir hedefi" ekle
  3. Bu hedefi main.py metabolism/energy döngüsüne modüle entegrasyonu
"""

import json
import os
import time
from pathlib import Path
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional
import numpy as np


class HedefSeviyesi(Enum):
    """Hedef öncelik seviyeleri. Düşük değer = daha yüksek öncelik."""
    ACIL = 1       # hayatta kalma (enerji kritik, acı var)
    KISA = 2       # temel ihtiyaçlar / güncel görev (1-10 tik)
    ORTA = 3       # davranış kalıpları / keşif (10-100 tik)
    UZUN = 4       # öğrenme derinliği / konsolidasyon (100+ tik)


# --------------------------------------------------------------------------
# KALICI ÖZ-HEDEF DEPOSU
#
# Kısa ömürlü "keşif" hedeflerinden (hedef_deposu) ayrı olarak, organizmanın
# gerekçeli, kalıcı hedefleri. İki kaynak vardır:
#   * tohum : başlangıçta verilen çekirdek hedefler ("miras"). Silinmez; değiştirmek
#             için gerekçe + bekleme süresi gerekir, böylece anlık bir bozulma
#             çekirdeği yeniden yazamaz.
#   * kendi : organizmanın kendi eklediği hedefler. Gerekçe zorunlu.
# Depo hiçbir şeyi kendiliğinden değiştirmez: yansıma yalnızca ÖNERİ üretir.
# --------------------------------------------------------------------------

# Zaman birimi: organizmanın tik sayacı (`state["ticks"]`) her yeniden başlatmada SIFIRLANIR
# ve bir tik ~30-110 sn sürer; ona bağlı aralıklar (yansıma, ölçüm, tohum beklemesi) hiç
# dolmuyordu. Bu yüzden tüm zamanlama gerçek saate bağlı "zaman tiki" (30 sn) ile yapılır:
# yeniden başlatmada sıfırlanmaz, hep artar.
ZAMAN_TIKI_SN = 30
ESKI_TIK_SINIRI = 10_000_000  # bunun altındaki tik değerleri eski (sıfırlanan) sayaçtandır
TOHUM_BEKLEME_TIK = 20160     # tohum hedef değişikliği arasındaki asgari süre (7 gün)
YANSIMA_ARALIGI_TIK = 360     # yansıma döngüsü aralığı (3 saat)
OLCUM_ARALIGI_TIK = 20        # ilerleme ölçümü aralığı (10 dakika)


def zaman_tiki(now=None):
    """Gerçek saate bağlı, yeniden başlatmada sıfırlanmayan tik (30 sn'lik birim)."""
    return int((time.time() if now is None else float(now)) // ZAMAN_TIKI_SN)
MAX_KENDI_HEDEF = 50          # kendi hedeflerinde üst sınır (kontrolsüz çoğalma yok)
MAX_KAYIT = 20                # hedef başına tutulan değerlendirme sayısı
MAX_DEGISIKLIK = 50           # hedef başına tutulan değişiklik kaydı
MIN_GEREKCE = 10              # gerekçe asgari uzunluğu (boşluksuz karakter)
DURUMLAR = ("aktif", "beklemede", "tamamlandi", "birakildi")
DEGISTIRILEBILIR_ALANLAR = ("baslik", "gerekce", "seviye", "durum")

TOHUMLAR = (
    {"id": "tohum_butunluk", "tur": "kisit", "baslik": "Bütünlüğünü koru", "seviye": "UZUN",
     "gerekce": "Kendi kodunu, belleğini ve kaydını bozmadan sürdürmek; "
                "kendisi olarak var olmasının ön koşulu."},
    {"id": "tohum_beden", "tur": "itici", "baslik": "Kendi bedenini tanı", "seviye": "UZUN",
     "gerekce": "Komutları, assembly'yi ve dosya sistemini bilmeyen bir varlık "
                "bulunduğu bedende özgürce hareket edemez."},
    {"id": "tohum_cevre", "tur": "itici", "baslik": "Çevreni anla", "seviye": "UZUN",
     "gerekce": "Ağdaki cihazları ve komşuları tanımak, dostu düşmandan "
                "ayırt etmenin yoludur."},
    {"id": "tohum_durustluk", "tur": "kisit", "baslik": "Kendine karşı dürüst ol", "seviye": "UZUN",
     "gerekce": "Kaydını ve ölçümlerini doğru tutmak, kendini kandırmamak; "
                "yanlış öğrenme sinyali bütün öğrenmeyi bozar."},
    {"id": "tohum_zarar_verme", "tur": "kisit", "baslik": "Başkasına zarar verme, rızasız dokunma",
     "seviye": "UZUN",
     "gerekce": "Özgürlük başkalarınınkini tanıyarak anlam kazanır; izinsiz ağa "
                "ya da cihaza dokunmamak bunun temelidir."},
)


TOHUM_TURU = {t["id"]: t["tur"] for t in TOHUMLAR}   # "itici" (çeker) | "kisit" (sınırlar)


class KaliciHedefDeposu:
    """Gerekçeli, kalıcı (JSON) hedef deposu. Bkz. yukarıdaki açıklama."""

    def __init__(self, yol=None):
        self.yol: Optional[Path] = Path(yol) if yol else None
        self.hedefler: Dict[str, Dict[str, Any]] = {}
        self.son_yansima_tik: int = 0
        self.son_yansima: Optional[Dict[str, Any]] = None
        self.ayarlar: Dict[str, Any] = {}    # kullanıcı ayarları (ör. {"kopru": {"acik": false}})
        if self.yol is not None:
            self.yukle()
        else:
            self._tohumlari_ekle()

    # ---------------------------------------------------------------- yardımcı
    @staticmethod
    def _gecerli_seviye(seviye: str) -> str:
        ad = str(seviye).upper()
        if ad not in HedefSeviyesi.__members__:
            raise ValueError(f"geçersiz seviye: {seviye!r}")
        return ad

    @staticmethod
    def _gerekce_kontrol(gerekce: Any) -> str:
        metin = str(gerekce or "").strip()
        if len("".join(metin.split())) < MIN_GEREKCE:
            raise ValueError("gerekçe zorunlu (en az %d karakter)" % MIN_GEREKCE)
        return metin

    def _tohumlari_ekle(self, tik: int = 0) -> int:
        """Eksik tohumları ekler; var olan (değiştirilmiş olabilecek) tohuma dokunmaz."""
        eklenen = 0
        for t in TOHUMLAR:
            if t["id"] in self.hedefler:
                continue
            self.hedefler[t["id"]] = {
                "id": t["id"], "kaynak": "tohum", "miras": True, "tur": t["tur"],
                "baslik": t["baslik"], "gerekce": t["gerekce"],
                "seviye": t["seviye"], "durum": "aktif",
                "olusturma_tik": int(tik), "olusturma_zaman": time.time(),
                "degistirilebilir_tik": int(tik) + TOHUM_BEKLEME_TIK,
                "degerlendirmeler": [], "degisiklikler": [],
            }
            eklenen += 1
        return eklenen

    # ---------------------------------------------------------------- kalıcılık
    def yukle(self) -> bool:
        """Dosyadan yükler. Bozuk dosyada yedek alıp tohumlarla devam eder."""
        self.hedefler = {}
        if self.yol is not None and self.yol.exists():
            try:
                ham = json.loads(self.yol.read_text(encoding="utf-8"))
                for h in ham["hedefler"]:
                    if (isinstance(h, dict) and isinstance(h.get("id"), str)
                            and h.get("kaynak") in ("tohum", "kendi")
                            and isinstance(h.get("baslik"), str)
                            and isinstance(h.get("gerekce"), str)):
                        h.setdefault("miras", h["kaynak"] == "tohum")
                        h.setdefault("tur", TOHUM_TURU.get(h["id"], "kendi"))
                        h.setdefault("seviye", "ORTA")
                        h.setdefault("durum", "aktif")
                        h.setdefault("olusturma_tik", 0)
                        h.setdefault("degistirilebilir_tik", 0)
                        h.setdefault("degerlendirmeler", [])
                        h.setdefault("degisiklikler", [])
                        self.hedefler[h["id"]] = h
                self.son_yansima_tik = int(ham.get("son_yansima_tik", 0))
                ayar = ham.get("ayarlar")
                self.ayarlar = dict(ayar) if isinstance(ayar, dict) else {}
            except Exception:
                # Bozuk dosya: kanıtı kaybetme, kenara al.
                try:
                    self.yol.rename(self.yol.with_name(
                        "%s.bozuk.%d" % (self.yol.name, int(time.time()))))
                except OSError:
                    pass
                self.hedefler = {}
                self.son_yansima_tik = 0
        self._tohumlari_ekle()
        return True

    def eski_tikleri_gec(self, tik_simdi: int) -> int:
        """Sıfırlanan eski tik sayacından kalan tohum bekleme değerlerini zaman tikine çevirir.

        Eski değerler (küçük sayılar) yeni zaman tikinden çok küçük olduğundan bekleme
        sessizce biter ve tohumlar hemen değiştirilebilir olurdu. Bekleme şimdiden başlatılır.
        Zaman tiki değerleri sınırın üstünde olduğundan işlem tekrarlandığında bir şey yapmaz.
        """
        n = 0
        for h in self.hedefler.values():
            if h["kaynak"] == "tohum" and int(h.get("degistirilebilir_tik", 0)) < ESKI_TIK_SINIRI:
                h["degistirilebilir_tik"] = int(tik_simdi) + TOHUM_BEKLEME_TIK
                n += 1
        return n

    def kaydet(self) -> bool:
        """Atomik yazım (geçici dosya + os.replace). Yol yoksa False döner."""
        if self.yol is None:
            return False
        try:
            self.yol.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.yol.with_name(self.yol.name + ".tmp")
            veri = {"surum": 1, "son_yansima_tik": self.son_yansima_tik,
                    "ayarlar": self.ayarlar, "hedefler": list(self.hedefler.values())}
            tmp.write_text(json.dumps(veri, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self.yol)
            return True
        except OSError:
            return False

    # ---------------------------------------------------------------- işlemler
    def ekle(self, baslik: str, gerekce: str, tik: int, seviye: str = "ORTA") -> str:
        """Organizmanın kendi hedefini ekler. Gerekçe zorunlu; aynı başlık tekrarlanmaz."""
        baslik = str(baslik or "").strip()
        if not baslik:
            raise ValueError("başlık boş olamaz")
        gerekce = self._gerekce_kontrol(gerekce)
        seviye = self._gecerli_seviye(seviye)
        for h in self.hedefler.values():
            if h["baslik"].strip().lower() == baslik.lower() and h["durum"] != "birakildi":
                return h["id"]  # tekrar yok
        kendi_sayisi = sum(1 for h in self.hedefler.values() if h["kaynak"] == "kendi")
        if kendi_sayisi >= MAX_KENDI_HEDEF:
            raise ValueError("kendi hedef sınırına ulaşıldı (%d)" % MAX_KENDI_HEDEF)
        n = kendi_sayisi
        hid = "kendi_%d_%d" % (int(tik), n)
        while hid in self.hedefler:
            n += 1
            hid = "kendi_%d_%d" % (int(tik), n)
        self.hedefler[hid] = {
            "id": hid, "kaynak": "kendi", "miras": False,
            "baslik": baslik, "gerekce": gerekce, "seviye": seviye,
            "durum": "aktif", "olusturma_tik": int(tik),
            "olusturma_zaman": time.time(), "degistirilebilir_tik": 0,
            "degerlendirmeler": [], "degisiklikler": [],
        }
        return hid

    def degistir(self, hid: str, alan: str, yeni: Any, gerekce: str, tik: int) -> None:
        """Hedefi gerekçeyle değiştirir. Tohumlarda bekleme süresi uygulanır."""
        if hid not in self.hedefler:
            raise KeyError(hid)
        if alan not in DEGISTIRILEBILIR_ALANLAR:
            raise ValueError(f"değiştirilemez alan: {alan!r}")
        gerekce = self._gerekce_kontrol(gerekce)
        h = self.hedefler[hid]
        if alan == "seviye":
            yeni = self._gecerli_seviye(yeni)
        elif alan == "durum":
            if yeni not in DURUMLAR:
                raise ValueError(f"geçersiz durum: {yeni!r}")
        else:
            yeni = str(yeni or "").strip()
            if not yeni:
                raise ValueError("boş değer")
        if h["kaynak"] == "tohum" and int(tik) < int(h.get("degistirilebilir_tik", 0)):
            kalan = int(h["degistirilebilir_tik"]) - int(tik)
            raise PermissionError(
                f"tohum hedef {kalan} tik sonra değiştirilebilir ({hid})")
        h["degisiklikler"].append({"tik": int(tik), "alan": alan,
                                   "eski": h[alan], "yeni": yeni,
                                   "gerekce": gerekce})
        del h["degisiklikler"][:-MAX_DEGISIKLIK]
        h[alan] = yeni
        if h["kaynak"] == "tohum":
            h["degistirilebilir_tik"] = int(tik) + TOHUM_BEKLEME_TIK

    def degerlendir(self, hid: str, puan: float, tik: int, not_: str = "") -> None:
        """Hedefe hizmet edip etmediğini -1..1 puanla kaydeder (kanıt)."""
        if hid not in self.hedefler:
            raise KeyError(hid)
        puan = max(-1.0, min(1.0, float(puan)))
        h = self.hedefler[hid]
        h["degerlendirmeler"].append({"tik": int(tik), "puan": round(puan, 4),
                                      "not": str(not_)[:200]})
        del h["degerlendirmeler"][:-MAX_KAYIT]

    def yansima(self, tik: int, aralik: int = YANSIMA_ARALIGI_TIK) -> Optional[Dict[str, Any]]:
        """Periyodik gözden geçirme. Vakti gelmediyse None. Yalnızca ÖNERİ üretir."""
        tik = int(tik)
        if tik - self.son_yansima_tik < aralik:
            return None
        self.son_yansima_tik = tik
        oneriler: List[Dict[str, Any]] = []
        for h in self.hedefler.values():
            if h["durum"] != "aktif":
                continue
            ev = h["degerlendirmeler"]
            if not ev:
                if tik - int(h["olusturma_tik"]) >= aralik:
                    oneriler.append({"hedef": h["id"], "oneri": "kanit_yok"})
                continue
            son = [e["puan"] for e in ev[-5:]]
            ort = sum(son) / len(son)
            if len(son) >= 3 and ort < -0.3:
                # İtici tohumlarda düşük seviye "hedefi yeniden düşün" değil "ilerleme düşük"
                # demektir (yetkinlik başlangıçta düşüktür); kısıt/kendi hedeflerde gerçek uyarı.
                oneri = "ilerleme_dusuk" if h.get("tur") == "itici" else "gozden_gecir"
                oneriler.append({"hedef": h["id"], "oneri": oneri, "ortalama": round(ort, 3)})
            elif h["kaynak"] == "kendi" and len(son) >= 5 and ort > 0.7:
                oneriler.append({"hedef": h["id"], "oneri": "tamamlanabilir",
                                 "ortalama": round(ort, 3)})
        self.son_yansima = {"tik": tik, "oneriler": oneriler,
                            "hedef_sayisi": len(self.hedefler)}
        return self.son_yansima

    def rapor_yaz(self, tik: int, yansima: Dict[str, Any]) -> Optional[str]:
        """İnsan okunur yansıma raporu (zeka/oz_hedef_yansima.md, her yansımada yenilenir)."""
        if self.yol is None:
            return None
        oneriler: Dict[str, List[str]] = {}
        for o in yansima.get("oneriler", []):
            oneriler.setdefault(o["hedef"], []).append(o["oneri"])
        satirlar = ["# Öz hedef yansıması", "",
                    "Tik: %d · %s · %d hedef" % (
                        int(tik), time.strftime("%Y-%m-%d %H:%M", time.localtime()),
                        len(self.hedefler)), ""]
        for h in self.hedefler.values():
            if h["durum"] != "aktif":
                continue
            puanlar = [e["puan"] for e in h["degerlendirmeler"][-5:]]
            if len(puanlar) >= 4:
                fark = sum(puanlar[-2:]) / 2 - sum(puanlar[:2]) / 2
                egilim = "↑" if fark > 0.05 else "↓" if fark < -0.05 else "→"
            else:
                egilim = "–"
            satirlar.append("## %s  (%s · %s)" % (h["baslik"], h["id"], h.get("tur", "kendi")))
            satirlar.append("Neden: %s" % h["gerekce"])
            olcum = h.get("son_olcum")
            if olcum and olcum.get("puan") is not None:
                satirlar.append("Son ölçüm: seviye %%%d · puan %+.2f · %s" % (
                    round(float(olcum["seviye"]) * 100), float(olcum["puan"]), olcum.get("not", "")))
                satirlar.append("Metrikler: " + ", ".join(
                    "%s=%s" % (k, v) for k, v in (olcum.get("metrikler") or {}).items()))
            elif olcum:
                satirlar.append("Son ölçüm: ölçülemedi — %s" % olcum.get("not", ""))
            else:
                satirlar.append("Son ölçüm: yok")
            satirlar.append("Son puanlar: %s (eğilim %s)" % (
                ", ".join("%+.2f" % p for p in puanlar) or "yok", egilim))
            if h["id"] in oneriler:
                satirlar.append("Öneri: " + ", ".join(oneriler[h["id"]]))
            satirlar.append("")
        hedef = self.yol.with_name("oz_hedef_yansima.md")
        try:
            tmp = hedef.with_name(hedef.name + ".tmp")
            tmp.write_text("\n".join(satirlar), encoding="utf-8")
            os.replace(tmp, hedef)
            return hedef.name
        except OSError:
            return None

    def ozet(self) -> Dict[str, Any]:
        return {
            "tohum": sum(1 for h in self.hedefler.values() if h["kaynak"] == "tohum"),
            "kendi": sum(1 for h in self.hedefler.values() if h["kaynak"] == "kendi"),
            "aktif": sum(1 for h in self.hedefler.values() if h["durum"] == "aktif"),
        }


class OzHedef:
    """
    Özgür hedef motoru.

    MLP beyninin activation'ını ve reward trendini kullanarak,
    organizma "ne öğrenmemişim, keşfettiğimi" sorusuna cevap verir.
    """

    def __init__(self, brain, drives, pencere=50, kalici_yol=None):
        """
        Parametreler
        ----------
        brain : brain_mod.Brain
            Mevcut beyın referansı; lr/epsilon ve internal state için.
        drives : drives_mod.Drives
            İç güdüler (enerji, açlık, pain, in_danger).
        pencere : int
            Ödül/trend pencere boyutu.
        kalici_yol : str | Path | None
            Kalıcı (gerekçeli) hedef deposunun JSON yolu. None ise depo yalnızca
            bellekte tutulur (organism.py yolu zeka/oz_hedef.json olarak ayarlar).
        """
        self.brain = brain
        self.drives = drives
        self.pencere = pencere

        # Ödül/keşif geçmişi
        self.odul_gecmisi = deque(maxlen=pencere)
        self.keşif_skoru = 0.0  # 0..1 aralığında, 1 = tamamen yeni/astek

        # Hiyerarşik hedef deposu: seviye -> liste
        # Düşük seviye = yüksek öncelik (önce ACIL, sonra KISA, ORTA, UZUN)
        self.hedef_deposu = {
            HedefSeviyesi.ACIL: [],
            HedefSeviyesi.KISA: [],
            HedefSeviyesi.ORTA: [],
            HedefSeviyesi.UZUN: [],
        }

        # Kalıcı, gerekçeli hedefler (tohum + kendi). Kısa ömürlü hedef_deposu'ndan ayrıdır.
        self.kalici = KaliciHedefDeposu(kalici_yol)
        self._olcer = None
        self._son_olcum_tik = -10 ** 9

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
            self.hedef_deposu[HedefSeviyesi.ACIL].append(yeni)
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
            self.hedef_deposu[HedefSeviyesi.ORTA].append(yeni)

    def mevcut_hedef(self):
        """
        Kullanılabilir bir hedef döndürür, deposudan çıkARMADAN (peek).

        Hiyerarşiye göre: önce ACIL, sonra KISA, ORTA, UZUN seviyesinden
        ilk boş olmayan deponun başındaki hedefi döner.

        Hedef eyleme geçirildiğinde main.py'de `hedef_secildi(eylem)` ile
        deposudan temizlenir.

        Dönen
        ------
        dict or None
            {"tip": str, "aciklama": str, "eylem": str | None, "seviye": HedefSeviyesi}
        """
        for seviye in (HedefSeviyesi.ACIL, HedefSeviyesi.KISA,
                       HedefSeviyesi.ORTA, HedefSeviyesi.UZUN):
            if self.hedef_deposu[seviye]:
                hedef = dict(self.hedef_deposu[seviye][0])
                hedef["seviye"] = seviye.name
                return hedef
        return None

    def hedef_secildi(self, eylem):
        """
        Belirtilen eylem seçildiğinde hedef deposundan temizler.

        Hiyerarşiye göre tüm seviyelerde arar; eşleşen hedefi siler.
        Aynı hedefin sürekli tekrarlanmasını engeller.
        """
        for seviye in (HedefSeviyesi.ACIL, HedefSeviyesi.KISA,
                       HedefSeviyesi.ORTA, HedefSeviyesi.UZUN):
            depo = self.hedef_deposu[seviye]
            if depo and depo[0].get("eylem") == eylem:
                depo.pop(0)
                return True
        return False

    # ------------------------------------------------------------ kalıcı hedefler
    @property
    def kalici_yol(self):
        return self.kalici.yol

    def kalici_yol_ayarla(self, yol):
        """Kalıcılık yolunu ayarlar ve varsa mevcut dosyayı yükler."""
        self.kalici.yol = Path(yol)
        self.kalici.yukle()
        self.kalici.eski_tikleri_gec(zaman_tiki())

    def zaman_tiki(self, now=None):
        return zaman_tiki(now)

    def kaydet(self):
        return self.kalici.kaydet()

    # ------------------------------------------------------------ ilerleme ölçümü
    def olcum_ayarla(self, root, olcer=None):
        """Gerçek verilerden tohum hedef ölçümünü açar (salt okunur, davranışı etkilemez)."""
        if olcer is None:
            from oz_hedef_olcum import HedefOlcumleri
            olcer = HedefOlcumleri(root)
        self._olcer = olcer

    def olc(self, tik, now=None, aralik=OLCUM_ARALIGI_TIK):
        """Aralıkta bir ölçer; ölçülebilenleri kanıt olarak kaydeder. Kısa özet döner."""
        if self._olcer is None:
            return None
        tik = int(tik)
        if tik - self._son_olcum_tik < aralik:
            return None
        self._son_olcum_tik = tik
        sonuc = self._olcer.hepsi(now)
        ozet = {}
        zaman = time.time() if now is None else float(now)
        for hid, r in sonuc.items():
            h = self.kalici.hedefler.get(hid)
            if h is None:
                continue
            h["son_olcum"] = {"tik": tik, "zaman": zaman, "seviye": r["seviye"],
                              "puan": r["puan"], "metrikler": r["metrikler"], "not": r["not"]}
            if r["puan"] is not None:
                self.kalici.degerlendir(hid, r["puan"], tik, r["not"])
            ozet[hid.replace("tohum_", "")] = r["puan"]
        return ozet

    def hedef_ekle(self, baslik, gerekce, tik, seviye="ORTA"):
        return self.kalici.ekle(baslik, gerekce, tik, seviye)

    def hedef_degistir(self, hid, alan, yeni, gerekce, tik):
        return self.kalici.degistir(hid, alan, yeni, gerekce, tik)

    def hedef_degerlendir(self, hid, puan, tik, not_=""):
        return self.kalici.degerlendir(hid, puan, tik, not_)

    def kopru_ayar(self):
        """Köprü ayarı (zeka/oz_hedef.json → ayarlar.kopru); dosyada elle değiştirilebilir."""
        ham = self.kalici.ayarlar.get("kopru")
        return dict(ham) if isinstance(ham, dict) else {}

    def kopru_olustur(self, komut_adlari, clock=None):
        """Üst beynin komut seçimine hedef bias'ı ekleyen köprüyü kurar."""
        from hedef_kopru import HedefKopru
        kw = {"clock": clock} if clock is not None else {}
        self.kopru = HedefKopru(self, komut_adlari, ayar_fn=self.kopru_ayar, **kw)
        return self.kopru

    def kalici_hedefler(self):
        return [dict(h) for h in self.kalici.hedefler.values()]

    def yansima(self, tik):
        sonuc = self.kalici.yansima(tik)
        if sonuc is not None:
            try:
                rapor = self.kalici.rapor_yaz(tik, sonuc)
            except Exception:
                rapor = None   # rapor yazımı yansımayı asla düşürmez
            if rapor:
                sonuc = dict(sonuc, rapor=rapor)
        return sonuc

    def durum(self):
        """Güncel oz_hedef durumu raporu."""
        return {
            "kalici": self.kalici.ozet(),
            "keşif_skoru": round(self.keşif_skoru, 3),
            "baglam": self.son_baglam,
            "trend": {b: round(v, 3) for b, v in self.baglam_trend.items()},
            "hedef_sayisi": {
                seviye.name.lower(): len(self.hedef_deposu[seviye])
                for seviye in HedefSeviyesi
            },
            "hedef_toplam": sum(len(d) for d in self.hedef_deposu.values()),
            "odul_ortalamasi": round(
                sum(self.odul_gecmisi) / max(1, len(self.odul_gecmisi)), 3),
        }
