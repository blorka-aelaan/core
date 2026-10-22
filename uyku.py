"""uyku - konsolidasyon (evrim) organi.

Yasarken biriken deneyim periyodik olarak modellere geri akar:
  * guvenlik : zeka/guvenlik_veri.jsonl (yasarken verilen sok kararlari)
  * paket    : dpkg durumu (ogretmen disaridan; canli ogrenme korunur)
  * dizin    : world/katalog/katalog.db (kendi tarama sonuclari)
  * uzuv     : uzuv_veri.jsonl (Faz 2 surec verisi, ESIKLI artis)
               + uzuv.jsonl (insan etiket defteri, aninda oncelik)
  * hatira   : journal learn kaydi (stim, action, R) -> beyin replay
               (Asama 4: surec ici deneyim tekrari, ESIKLI BAYT artisi)
  * konsolide: beyin agirlik budamasi (Asama 5: esik alti zayif
               baglantilar surec ici silinir, icguduler korunur)

Uyku karari objektiftir - kural degil, olcum:
  * guvenlik : veri satir sayisi son egitimden beri ARTTIYSA
  * paket    : /var/lib/dpkg/status degistiyse ya da model bayattiysa
  * dizin    : katalog.db son egitimden beri buyuduyse
  * uzuv     : veri UZUV_ESIK kadar buyuduyse / arsiv dondu ise /
               insan defteri degistiyse (damga)
  * hatira   : jurnal HATIRA_ESIK BAYT buyuduyse / dondu ise / bayattiysa
  * konsolide: damgasiz/verisiz -> yalnizca bayattiysa (periyodik, 6 saat)

Tek uyku = tek egitim (en acil olan). Egitim senkron calisir: organizma
bu sirada "nefesini tutar" (tikler durur) ve uyandiginda daha bilgili
olur. Evrim dongusu: YASA -> deneyim biriktir -> UYU -> model tazelenir.

Basarisiz egitim "yapildi" SAYILMAZ: son basarili zaman/veri/damga
korunur, hata kaydedilir ve ustel geri cekilme uygulanir (10dk, 20dk, ...
en fazla 6 saat). Boylece cokmus bir hat organizmayi surekli dondurmaz.

  python3 uyku.py           # gerekiyorsa tek uyku yap
  python3 uyku.py --zorla   # bayatlik/geri cekilmeyi atla, simdi uyut

Kaynak ASCII-only tutulur (dosya yazan araclar Unicode'u bozabiliyor).
"""

import json
import os
import subprocess
import time
from pathlib import Path

import zeka

ROOT = Path(__file__).resolve().parent

# egitim hatlari: ad -> (komut, dayanik_saniye)
HATLAR = {
    "guvenlik": (["python3", "egit_guvenlik.py", "--ornek", "20000",
                  "--deneyim"], 120),
    "dizin": (["python3", "egit_dizin.py"], 300),
    "dizin_kaynak": (["python3", "egit_dizin.py", "--kaynak"], 300),
    "paket": (["python3", "egit_paket.py"], 300),
    "uzuv": (["python3", "egit_uzuv.py"], 600),
    # hatira (Asama 4): subprocess DEGIL surec-ici replay - komut yok;
    # uyu() beyni alip brain.hatira() ile learn kayitlarini oynar
    "hatira": (None, 0),
    # konsolide (Asama 5): surec-ici BUDAMA - komut yok; uyu() beyni
    # alip brain.konsolide() ile esik altindaki zayif baglantilari siler
    # (icguduler korunur). Damgasiz/verisiz: yalnizca bayatlikla tetiklenir.
    "konsolide": (None, 0),
}

# Eski (Turkce karakterli) anahtar adlari -> yeni ASCII ad. Kaynak ASCII
# kalsin diye kacis dizisi kullanilir. uyku.json ve body.json bunlarla
# yazilmis olabilir; yuklenirken otomatik tasinir.
ESKI_AD = {"hat\u0131ra": "hatira"}

# uzuv verisi her 3 dakikada bir buyur -> egitim ESIKLI (her kontrolde
# donguye girmesin): sayi son egitimden beri UZUV_ESIK kadar arttiysa
# ya da arsiv donusu (yariya inme) varsa uyut.
UZUV_ESIK = 1000

# hatira (Asama 4): jurnal bu kadar BAYT buyudugunde uyanik ruya -
# learn satirlari (R ile) beyne yeniden oynanir (deneyim tekrari)
HATIRA_ESIK = 2000000

# basarisiz egitim sonrasi geri cekilme (saniye): ilk 10dk, sonra x2,
# tavan 6 saat. Basarili egitim sayaci sifirlar.
HATA_BEKLEME = 600
HATA_TAVAN = 6 * 3600


def _ad_duzelt(ad):
    return ESKI_AD.get(ad, ad)


def _rapor_satiri(cikti):
    """egit_* stdout'undan tek dogruluk satiri (Z2 - olcum kor noktasi):
    uyku egitiminin METRIGI journal'a girer; kod/sure degil, dogruluk
    tarihsel olur (dogru X/Y | top-1/top-3 | MAE). Bulunamazsa None.
    Mock/test stdout'u (str disi) guvenle ele alinir."""
    try:
        if not isinstance(cikti, str):
            return None
        anahtar = ("doğruluk", "dogruluk", "top-1", "top-3", "MAE",
                   "başarı", "basari")
        for satir in reversed(cikti.splitlines()):
            s = satir.strip()
            if "%" in s and any(a in s for a in anahtar):
                return s[:160]
    except Exception:
        pass
    return None


class Uyku:
    def __init__(self, cfg):
        u = cfg.get("uyku", {})
        self.periyot = int(u.get("periyot", 200))         # baz periyot (tik)
        self.periyot_min = int(u.get("periyot_min",
                                  max(10, self.periyot // 2)))
        self.periyot_max = int(u.get("periyot_max",
                                     self.periyot * 3))
        self.min_enerji = float(u.get("min_enerji", 50))  # tok & dinc
        self.max_ac = float(u.get("max_ac", 50))
        ham = u.get("tazele_saat", {"guvenlik": 1, "paket": 4,
                                    "dizin": 2,
                                    "dizin_kaynak": 2,
                                    "uzuv": 4,
                                    "hatira": 6,
                                    "konsolide": 6})
        self.tazele = {_ad_duzelt(k): float(v) for k, v in ham.items()}
        self.son = {}    # ad -> {"t","veri","damga"} (+ hata_t/hata_say/...)
        self.load()

    def periyot_icin(self, drives=None):
        """Ic denge (homeostaz) ve deneyim aciligina duyarl dinamik uyku
        periyodu (tik cinsinden).

        Homeostaz dusukse organizm zayif/acik -> deneyim acil, konsolidasyon
        la onemli -> periyot kisalir (daha sik uyku). Homeostaz yüksekse
        organizm iyi -> periyot uzunalar (daha az uyku, daha fazla canli
        calisma). Sinirlar [periyot_min, periyot_max].
        """
        h = 0.5
        if drives is not None:
            hp = getattr(drives, "homeostaz_puani", None)
            try:
                h = float(hp()) if callable(hp) else float(
                    getattr(drives, "homeostaz", 0.5))
            except Exception:
                h = 0.5
            h = max(0.0, min(1.0, h))
        # h = 0 (kritik) -> periyot_min (cok sik uyku); h = 1 (mukemmel)
        # -> periyot_max (az uyku, daha fazla canli calisma)
        p = int(self.periyot_min + (self.periyot_max - self.periyot_min) * h)
        return max(self.periyot_min, min(self.periyot_max, p))

    # ---- bayatlik olcutleri (ucuz stat; ogrenci durmaz) ----
    def _damga(self, ad):
        """Kaynak degisiklik damgasi: veri kaynagi ne zaman oynadi."""
        if ad == "paket":
            y = Path("/var/lib/dpkg/status")
        elif ad == "guvenlik":
            y = zeka.yol("guvenlik_veri.jsonl")
        elif ad == "uzuv":
            # dikkat: uzuv_veri.jsonl her 3 dakikada bir oynar -> damga
            # OLARAK yalnizca insan etiket defteri sayilir (aninda egitim)
            y = ROOT / "uzuv.jsonl"
        elif ad == "hatira":
            # damgasiz: olcut jurnal bayt buyumesi (veri_artti)
            return 0.0
        elif ad == "konsolide":
            # damgasiz: olcum beyin agirlik tablosu (brain.json) degil,
            # agirligin kendisi -> yalnizca periyodik bayatlikla tetiklenir
            return 0.0
        else:  # dizin / dizin_kaynak
            y = ROOT / "world" / "katalog" / "katalog.db"
        try:
            return float(y.stat().st_mtime)
        except OSError:
            return 0.0

    @staticmethod
    def _veri_sayisi(ad):
        """Deneyim birikimi (artis = ogrenme).

        guvenlik/uzuv: satir sayisi. hatira: jurnal BAYT boyu (stat,
        ucuz; 20MB'lik dosyayi her kontrolde satir satir saymaz).
        """
        if ad == "hatira":
            try:
                return (ROOT / "journal.jsonl").stat().st_size
            except OSError:
                return 0
        if ad == "guvenlik":
            y = zeka.yol("guvenlik_veri.jsonl")
        elif ad == "uzuv":
            y = ROOT / "uzuv_veri.jsonl"
        else:
            return 0
        try:
            with open(y, encoding="utf-8") as f:
                return sum(1 for s in f if s.strip())
        except OSError:
            return 0

    def karar(self, now=None, zorla=False):
        """Siradaki uyku - en acil olan. None = su an gerekmez."""
        now = now or time.time()
        aday = []
        for ad in HATLAR:
            kayit = self.son.get(ad, {})
            # basarisiz egitim sonrasi geri cekilme (zorla atlar)
            if not zorla and kayit.get("hata_t") is not None:
                bekle = float(kayit.get("hata_bekle", HATA_BEKLEME))
                if now - float(kayit["hata_t"]) < bekle:
                    continue
            damga = self._damga(ad)
            veri = self._veri_sayisi(ad)
            t = float(kayit.get("t", 0))
            onceki = int(kayit.get("veri", -1))
            if ad == "uzuv":
                # veri dosyasi her 3 dakikada bir oynar -> gunluk artis
                # tetiklemez; ESIKLI: sayi UZUV_ESIK kadar buyudugunde
                # ya da arsiv donusu (yariya inme) tek seferlik egitim.
                # Insan defteri damgasi her zaman aninda tetikler.
                veri_artti = (onceki < 0 or veri > onceki + UZUV_ESIK
                              or (onceki > 0 and veri < onceki // 2))
            elif ad == "hatira":
                # jurnal BUYUMESI (bayt): deneyim yeterince biriktiyse
                # ya da jurnal arsivlenip dondu ise (geriye taze learn
                # satiri kalmadiysa) uyanik ruya
                veri_artti = (onceki < 0 or veri > onceki + HATIRA_ESIK
                              or (onceki > 0 and veri < onceki // 2))
            else:
                veri_artti = (ad == "guvenlik" and veri > onceki)
            kaynak_degisti = damga > float(kayit.get("damga", 0)) + 1
            bayatti = (now - t) > self.tazele.get(ad, 4) * 3600
            if zorla or veri_artti or kaynak_degisti or bayatti:
                # oncelik: deneyim artisi (0) bayatliktan (1) degerlidir;
                # ayni grupta EN ESKI egitilen (hic egitilmemis t=0 dahil)
                # once gelir: -(yas) kucuk = yas buyuk
                oncelik = (0 if veri_artti else 1, -(now - t))
                aday.append((oncelik, ad, damga, veri))
        if not aday:
            return None
        aday.sort(key=lambda x: x[0])
        _p, ad, damga, veri = aday[0]
        return {"ad": ad, "damga": damga, "veri": veri}

    def uyu(self, karar, beyn=None):
        """Tek uykuda tek egitim (senkron; tikler durur - nefes tutma).

        hatira ve konsolide hatlari surec-icidir: beyin bellekte yasar;
        hatira journal learn kayitlarini (stim, action, R) guncel
        agirliklarla yeniden oynar (Asama 4 - deneyim tekrari), konsolide
        ise esik altindaki zayif baglantilari budar (Asama 5). Diger
        hatlar subprocess'tir.

        Donus: {"ad","kod","sure"[, "ornek"]}. kod==0 basari; -1 hata/
        zaman asimi; -2 atlandi (hatira/konsolide icin beyin verilmedi).
        Basari disinda son basarili durum KORUNUR ve geri cekilme baslar.
        """
        ad = karar["ad"]
        komut, azami = HATLAR[ad]
        t0 = time.time()
        ornek = None
        if komut is None:
            if beyn is None:
                kod = -2        # surec-ici hat icin beyin yok: yapilmadi
            else:
                try:
                    if ad == "konsolide":
                        ornek = beyn.konsolide()  # esik tabanli budama; canli konsolidasyon main.py'de koru_ust=300 ile
                    else:
                        ornek = beyn.hatira(ROOT / "journal.jsonl")
                    kod = 0
                except Exception:
                    kod = -1
        else:
            try:
                p = subprocess.run(komut, cwd=str(ROOT),
                                   capture_output=True,
                                   text=True, timeout=azami)
                kod = p.returncode
                if kod == 0:
                    # Z2: egitim METRIGI journal'a (kod/sure + dogruluk
                    # satiri) — stdout kaybolmaz, tarihsel olur
                    _r = _rapor_satiri(getattr(p, "stdout", ""))
                    if _r:
                        self._rapor = _r
            except (OSError, subprocess.TimeoutExpired):
                kod = -1
        sure = round(time.time() - t0, 1)
        if kod == 0:
            # egitim bitiminde damgayi YENIDEN oku: egitim sirasinda da
            # kaynak oynamis olabilir (tazelik siniri sonraki uyku icin)
            self.son[ad] = {"t": time.time(),
                            "veri": max(karar["veri"],
                                        self._veri_sayisi(ad)),
                            "damga": self._damga(ad)}
        else:
            kayit = dict(self.son.get(ad, {}))
            say = int(kayit.get("hata_say", 0)) + 1
            kayit["hata_say"] = say
            kayit["hata_t"] = time.time()
            kayit["hata_kod"] = kod
            kayit["hata_bekle"] = min(HATA_BEKLEME * 2 ** (say - 1),
                                      HATA_TAVAN)
            self.son[ad] = kayit
        self.save()
        sonuc = {"ad": ad, "kod": kod, "sure": sure}
        if ornek is not None:
            sonuc["ornek"] = ornek
        # Z2: egitim dogrulugu da journal'a (tarihsel metrik kanali)
        rapor = getattr(self, "_rapor", None)
        if rapor:
            sonuc["rapor"] = rapor
            self._rapor = None
        return sonuc

    def save(self):
        yol = zeka.kayit("uyku.json")
        tmp = yol.with_name("%s.%d.tmp" % (yol.name, os.getpid()))
        tmp.write_text(json.dumps({"son": self.son}, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(yol))

    def load(self):
        try:
            veri = json.loads(zeka.yol("uyku.json").read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.son = {_ad_duzelt(k): v for k, v in veri.get("son", {}).items()}
        return True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="konsolidasyon (uyku) tek basina")
    ap.add_argument("--zorla", action="store_true")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "body.json").read_text(encoding="utf-8"))
    u = Uyku(cfg)
    k = u.karar(zorla=args.zorla)
    if not k:
        print("uyku gerekmiyor (deneyim taze, modeller genc)")
    else:
        print("uyku: %s" % k["ad"])
        print(u.uyu(k))


