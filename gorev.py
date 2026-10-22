"""Tezgâh — görev organı: Debian klasör envanteri.

Organizmaya iş verilir: kaynak köklerinin (varsayılan /usr/share/doc,
/etc) altındaki klasörleri tek tek inceler ve her klasör için bir
envanter satırı yazar: ad + dosya sayısı + karakter.

Okuma VE yazma zorunludur — ham sayım (tek `find`) iş sayılmaz; her
kalem iki alt süreç demektir, yani gerçek CPU harcar. Süre dolarsa ve
hedefe ulaşılmadıysa görev cezası (enerji şoku) doğar; şok mevcut
güvenlik kuyruğuna girer, uygulanıp uygulanmayacağına güvenlik beyni
karar verir. Böylece "iş yapmazsan ceza alırsın" kuralı ikinci bir
irade gerektirmez — mevcut öğrenilmiş model uygular.
"""
import json
import time
from pathlib import Path

import dizin as DIZIN_MOD
from katalog import Katalog, norm


class Hedef:
    """Bir uzun vadeli hedef: aciklama + oncelik + adim listesi.

    oncelik buyuk olan hedef yigindan once cikar (HedefYigin).
    """
    def __init__(self, kim, oncelik=0, adimlar=None, t=0.0):
        self.kim = kim                # hedef aciklamasi (or. "dizin: /etc taranacak")
        self.oncelik = int(oncelik)   # buyuk = once
        self.adimlar = list(adimlar or [])  # UzunVadePlan adim sozlukleri
        self.adim_i = 0
        self.olusturulma = float(t)
        self.durum = "aktif"          # aktif | tamamlandi | ertelendi


class HedefYigin:
    """Oncelikli hedef yigı: en yuksek oncelikli hedef en tepedir."""

    def __init__(self):
        self._liste = []

    def push(self, hedef):
        self._liste.append(hedef)
        self._liste.sort(key=lambda h: -h.oncelik)

    def pop(self):
        return self._liste.pop(0) if self._liste else None

    def peek(self):
        return self._liste[0] if self._liste else None

    def bos(self):
        return len(self._liste) == 0

    def __len__(self):
        return len(self._liste)


class UzunVadePlan:
    """Bir hedefin adim adim gerceklestirilecegi uzun vadeli plani."""

    def __init__(self, hedef, adimlar=None):
        self.hedef = hedef
        self.adimlar = list(adimlar or [])
        self.i = 0

    def bir_adim(self):
        if self.i >= len(self.adimlar):
            return None
        adim = self.adimlar[self.i]
        self.i += 1
        return adim

    def bitti(self):
        return self.i >= len(self.adimlar)


class Tezgah:
    def __init__(self, cfg, body, jour):
        self.cfg = cfg or {}
        self.body = body
        self.jour = jour
        self.baslangic = None      # görevin başladığı tik
        self.kuyruk = []           # incelenecek klasör yolları
        self.teslim = 0            # yazılan kalem sayısı
        self.ceza_verildi = False  # bu görev için ceza doğdu mu
        self.yapilan = set()      # envanterlenmiş klasörler (tekrar yok)
        self.tamamlandi = False   # tüm kaynaklar tarandı, iş kalmadı
        self.son_ilerleme = None  # son ceza anının gerçek ilerlemesi
        self.katalog = (body.world / "katalog" / "envanter.jsonl")
        self.dosyalar = (body.world / "katalog" / "dosyalar.jsonl")
        # Katalog deposu: SQLite (tekrar imkânsız, sorgulanabilir).
        # JSONL dosyaları artık DIŞA AKTARIM'dır (denetim için korunur).
        self.depo = Katalog(body.world / "katalog" / "katalog.db")
        self._goc_yap()
        # Önceki yaşamların yaptığı iş kalıcı hafızada: yeni doğuş
        # aynı klasörleri tekrar tekrar yazmaz (ölüm öğrenmeyi silmez).
        self.yapilan |= self._katalogdan_oku()
        # Öğrenilmiş dünya modeli: "bu dosya adı hangi ailede olur?"
        # Kaynak modeli kendi dosyasında (dizin_kaynak.json); eski tek
        # dizin.json varsa ona düşülür.
        self.dizin = DIZIN_MOD.Dizin([])
        import zeka
        yuklendi = self.dizin.load(zeka.yol("dizin_kaynak.json"))
        if not yuklendi:
            yuklendi = self.dizin.load(zeka.yol("dizin.json"))
        self.dizin_yok = not yuklendi
        self.dizin_agirlik = self.dizin.agirlik
        # konum egzersizi sayaçları
        self.konum = 0
        self.konum_deneme = 0
        self.konum_top1 = 0
        self.yenilenen = 0        # tazeleme (yeniden tarama) sayısı
        self.derinleme = 0        # derinleşen tarama turu sayısı
        self.kuyruk_bos = 0       # "incelenecek klasör kalmadı" sayısı
        self.nedir_ogrenilen = 0  # "nedir?" ile öğrenilen komut sayısı
        self.derinlik = int(self.cfg.get("derinlik", 3))
        self.erisilemez = set()    # "okunamadı" bilinen dizinler
        self.erisilemez_yeni = 0
        # ---------- Yeni: hedef yigini + uzun vadeli planlama ----------
        self.hedef_yigin = HedefYigin()     # oncelikli hedef yigini
        self.aktif_plan = None              # su an yurutulen UzunVadePlan
        self.plan_sayaci = 0                # plan icinde yurutulen adim sayisi

    def hedef_ekle(self, kim, oncelik=0, adimlar=None, t=None):
        """Yeni bir hedefi yigina ekler. Buyuk oncelik once islenir.

        adimlar: {"eylem": "katalog_tara", "klasor": "..."} gibi UzunVadePlan
        adim sozlukleri. Plan, plan_adimi_yurut() ile adim adim yurutulur.
        """
        h = Hedef(kim, oncelik=oncelik, adimlar=adimlar, t=t or 0.0)
        self.hedef_yigin.push(h)
        self.jour.log("hedef_ekle", kim=kim, oncelik=oncelik,
                      adim_sayisi=len(h.adimlar),
                      yigin_derinligi=len(self.hedef_yigin))
        return h

    def plan_baslat(self):
        """Yigindan en oncelikli hedefi ceker; UzunVadePlan olusturur."""
        hedef = self.hedef_yigin.pop()
        if hedef is None:
            self.aktif_plan = None
            return None
        self.aktif_plan = UzunVadePlan(hedef, hedef.adimlar)
        self.jour.log("plan_baslat", kim=hedef.kim, oncelik=hedef.oncelik,
                      adim_sayisi=len(hedef.adimlar))
        return self.aktif_plan

    def plan_adimi_yurut(self):
        """Aktif plandin bir sonraki adimini yurutur; plan bitince yigindan
        yeni hedef ceker. Donus: calistir_bir() gibi bir obs sozlugu veya None
        (yigit bossa is yok)."""
        if self.aktif_plan is None or self.aktif_plan.bitti():
            self.plan_baslat()
            if self.aktif_plan is None:
                return None
        adim = self.aktif_plan.bir_adim()
        self.plan_sayaci += 1
        eylem = adim.get("eylem") if isinstance(adim, dict) else None
        if eylem == "katalog_tara":
            klasor = adim.get("klasor") or ""
            if klasor and klasor not in self.kuyruk and klasor not in self.yapilan:
                self.kuyruk.insert(0, klasor)
            return self.calistir_bir(0)
        if eylem == "konum":
            return self.konum_bir()
        if eylem == "bekle":
            return {"obs": "plan: bekle", "kind": "plan", "novel": 0,
                    "gain": 0}
        # bilinmeyen adim: gecis
        return {"obs": "plan adim atlandi: %s" % eylem, "kind": "plan",
                "novel": 0, "gain": 0}

    def plan_rapor(self):
        """Hedef yigini ve aktif planin guncel durumu (gozlem/denetim icin)."""
        return {
            "yigin": [{"kim": h.kim, "oncelik": h.oncelik,
                       "adim": len(h.adimlar), "durum": h.durum}
                      for h in self.hedef_yigin._liste],
            "aktif_plan": ({"kim": self.aktif_plan.hedef.kim,
                            "adim": self.aktif_plan.i,
                            "toplam": len(self.aktif_plan.adimlar)}
                           if self.aktif_plan else None),
            "kuyruk_uzunlugu": len(self.kuyruk),
            "bitti_mi": self.bitti_mi(),
        }

    # ---------- Faz 2: konum tahmini (dizin modeliyle iş) ----------

    def reload_dizin(self):
        """Uyku eğitimi sonrası dizin modelini tazele (Z1 — bayat-ağırlık
        koruması). load() yeniden girişlidir: iki kaynak da okunamazsa
        eski model aynen kalır (dizin_yok False'a çekilmez)."""
        import zeka
        if self.dizin.load(zeka.yol("dizin_kaynak.json")) or \
                self.dizin.load(zeka.yol("dizin.json")):
            self.dizin_yok = False
            self.dizin_agirlik = self.dizin.agirlik
            return True
        return False

    def konum_aktif(self):
        # Katalog BİTTİĞİNDE de konum yapılabilir — hatta en anlamlı
        # zamanı o: keşif bitti, şimdi elindeki bilgi işe yarıyor mu?
        return (not self.dizin_yok
                and self.konum < int(self.cfg.get("konum_egzersizi", 0))
                and self._katalog_sayisi() >= 100)

    def _katalog_sayisi(self):
        """Katalogdaki dosya satırı sayısı (dosya sayısı değil satır)."""
        return self.depo.dosya_sayisi()

    def _katalog_adlari(self):
        """Kendi katalogundan dosya adları (kendi öğrendiği dünya)."""
        return self.depo.adlar()

    # ---------- Faz 3: "nedir?" — Debian beyiniyle tanışma ----------

    def nedir_bir(self, beyin):
        """Rastgele çalıştırılabilir aday seç → BEYNİNE sor → bilemezse
        GERÇEK `dpkg -S` ile doğrula ve ÖĞREN (kendi kendine öğretim).

        Ödül haritası: "biliyordu" ucuza gelir, "öğrendim" pahalıdır —
        organizma merakla bilmediği şeylere yönelir, ekonomi kuran
        doğrulamayı seçer.
        """
        import paket as P
        satir = self.depo.rastgele_calistirilabilir()
        if not satir:
            return {"obs": "nedir için katalogda çalıştırılabilir dosya yok",
                    "kind": "nedir", "novel": 0, "gain": 0}
        yol, ad = satir
        kaynak, bilgi = beyin.nedir(ad)
        if kaynak == "kesin":
            return {"obs": "biliyordu: %s → %s (%s)"
                           % (ad, bilgi["paket"], bilgi.get("bolum", "?")),
                    "kind": "nedir", "novel": 0, "gain": 1,
                    "dogru": True}
        # bilmiyor ya da tahminde → GERÇEK öğretmen: dpkg (salt-okunur)
        # usrmerge: dpkg .list dosyaları hâlâ /bin /sbin yazar; katalog ise
        # /usr/bin /usr/sbin çözümler. Bulamazsa eski yol alternatiflerini dene.
        adaylar = [yol]
        if yol.startswith("/usr/bin/"):
            adaylar.append("/bin/" + yol[len("/usr/bin/"):])
        elif yol.startswith("/usr/sbin/"):
            adaylar.append("/sbin/" + yol[len("/usr/sbin/"):])
        gercek = None
        for aday in adaylar:
            ok, out, _err = self.body._calistir(
                ["dpkg", "-S", aday], cap=2048, ayrik=True)
            if ok and out.strip():
                ilk = out.splitlines()[0]
                if ":" in ilk:
                    gercek = ilk.split(":", 1)[0].strip().split(",")[0].strip()
                    break
        # 2026-10-19 Z3 ölçümü: risk modeli %95-4 sınıf dengesizliğinde
        # her dosyayı "veri" saydı (bash bile). Eğitim seti dengelenmeden
        # bağlama YOK — yargıç dpkg'dir, tek obs kalır (envanter dışı).
        if not gercek:
            return {"obs": "dpkg de bulamadı: %s" % ad,
                    "kind": "nedir", "novel": 0, "gain": 1}
        pb = beyin.paket_bilgi.get(gercek, {})
        beyin.bilgi_ekle(yol, gercek, pb.get("bolum", ""),
                         pb.get("aciklama", ""))
        beyin.ogren(P.ozellikler(ad), gercek)
        self.nedir_ogrenilen += 1
        if self.nedir_ogrenilen % 10 == 0:
            beyin.save()
        if kaynak == "tahmin" and bilgi.get("paket") == gercek:
            obs = "tahmini tuttu: %s → %s (model doğru)" % (ad, gercek)
            gain = 3
            dogru = True
        else:
            obs = ("öğrendi: %s → %s%s"
                   % (ad, gercek,
                      " — tahmini bozdu: %s" % bilgi.get("paket")
                      if kaynak == "tahmin" else ""))
            gain = 6
            dogru = kaynak == "tahmin" and bilgi.get("paket") == gercek
        return {"obs": obs, "kind": "nedir", "novel": 0, "gain": gain,
                "dogru": dogru}

    def konum_bir(self):
        """Bir dosyanın yerini tahmin et ve doğrula (1-3 alt süreç).

        Model ilk 3 aileyi önerir; organizma SADECE oraları tarar.
        Bulursa ödül kazanır → modelin bilgisi işe yaramıyorsa
        denemeler hep ıskalıyor ve katalog işi daha cazip hale gelir.
        """
        aday = int(self.cfg.get("konum_aday", 500))
        adlar = self._katalog_adlari()
        if not adlar:
            return {"obs": "konum için katalog boş", "kind": "is",
                    "novel": 0, "gain": 0}
        import random
        rng = random.Random(len(adlar) + self.konum_deneme)
        ad = rng.choice(adlar[:aday])
        sira = self.dizin.sirala(DIZIN_MOD.ozellikler(ad))
        aileler = [a for a in sira[:3] if a and a != "/"]
        self.konum_deneme += 1
        bulunan = None
        for sira_i, aile in enumerate(aileler[:3]):
            ok, out, _err = self.body._calistir(
                ["find", aile, "-maxdepth", "3", "-type", "f",
                 "-name", ad], cap=65536, ayrik=True)
            if ok and ad in out:
                bulunan = aile
                if sira_i == 0:
                    self.konum_top1 += 1
                break
        self.konum += 1
        if bulunan:
            obs = ("konum bulundu: %s → %s (ilk tahmin %s)"
                   % (ad, bulunan, aileler[0] if aileler else "-"))
            gain = int(self.cfg.get("odul_enerji", 8))
        else:
            obs = ("konum ıskalandı: %s (bakılan: %s)"
                   % (ad, ", ".join(aileler[:3]) or "-"))
            gain = 2
        self.jour.log("konum", ad=ad, basarili=bool(bulunan),
                      top1=(bulunan == (aileler[0] if aileler else None)),
                      aileler=aileler[:3],
                      deneme=self.konum_deneme, basarili_sayi=self.konum)
        return {"obs": obs, "kind": "is", "novel": 0, "gain": gain,
                "konum_basarili": bool(bulunan)}

    def _goc_yap(self):
        """Eski/akan JSONL katalogu SQLite'a taşı.

        Her doğuşta çalışır: içe aktarım idempotenttir (PRIMARY KEY aynı
        satırı iki kez almaz) ve ~0.5 sn sürer. Böylece çalışan eski
        organizmanın JSONL'e yazdığı kalemler kaybolmaz.
        """
        if not self.katalog.exists():
            self._supheli_temizle()
            return
        sonuc = self.depo.ice_aktar(str(self.katalog), str(self.dosyalar))
        if sonuc.get("yeni_klasor") or sonuc.get("yeni_dosya"):
            self.jour.log("katalog_goc", **sonuc)
        self._supheli_temizle()

    def _supheli_temizle(self):
        """Çöp satırları ("find: ... Permission denied" vb.) her doğuşta sil.

        Dışarıdan yazma YAPILMAZ: çalışan organizmanın WAL'ı bozulur.
        Temizliği yaşamın kendisi yapar.
        """
        try:
            silinen = self.depo.supheli_temizle()
        except Exception:
            return 0
        if silinen:
            # NOT: _goc_yap, yapilan doldurulmadan ÖNCE çalışır; temizlik
            # veritabanında olur, _katalogdan_oku() zaten temiz veriyi okur.
            self.jour.log("katalog_temizlendi", silinen=silinen,
                          not_="stderr karışmış çöp satırlar")
        return silinen

    def _jsonl_aktar(self):
        """Denetim için JSONL dışa aktarımı (SQLite tek gerçek kaynak)."""
        try:
            self.depo.jsonl_aktar(str(self.katalog), str(self.dosyalar))
        except OSError:
            pass

    def _katalogdan_oku(self):
        """Var olan envanterden biten klasörleri topla."""
        return self.depo.yapilanlar()

    # ---------- görev durumu ----------

    def aktif(self, tik):
        if not self.cfg.get("aktif", True):
            return False
        if self.baslangic is None:
            self.baslangic = tik
            self.jour.log("gorev_basladi",
                           hedef=self.cfg.get("hedef", 0),
                           sure=self.cfg.get("sure_tik", 0),
                           kaynaklar=self.cfg.get("kaynaklar", []))
        return True

    def hedef(self):
        return int(self.cfg.get("hedef", 0))

    def ilerleme(self, tik):
        gecen = 0 if self.baslangic is None else tik - self.baslangic
        return {"teslim": self.teslim, "hedef": self.hedef(),
                "gecen_tik": gecen,
                "kalan_tik": max(0, int(self.cfg.get("sure_tik", 0))
                                 - gecen),
                "yuzde": round(100.0 * self.teslim
                                / max(1, self.hedef()), 1),
                "klasor": len(self.yapilan), "kuyruk": len(self.kuyruk),
                "derinlik": self.derinlik, "derinleme": self.derinleme,
                "yenilenen": self.yenilenen, "kuyruk_bos": self.kuyruk_bos,
                "erisilemez": len(self.erisilemez)}

    def hedef_ulasildi(self):
        """Bu yaşamın hedefine ulaşıldı mı? (ceza ölçümü için)"""
        h = self.hedef()
        return bool(h) and self.teslim >= h

    def bitti_mi(self):
        """Tezgâh eylemi sunulmaya devam etmeli mi?

        DİKKAT: burada `hedef` KULLANILMAZ. `hedef` per-yaşam hedefidir ve
        ceza ölçümünü durdurur; görevi kalıcı olarak kapatmaz. 23:33'te
        gorev.json'daki hedef 600→20 düşürüldüğünde, 505 klasör kataloglanmış
        bir organizmada `bitti_mi()` bir daha hiç False olmadı: görev
        18 saat sessizce durdu, beyin boşta kalan `go:katalog` yürüyüşünde
        döngüye girdi. Sunumu durduran tek şey GERÇEK tükenmedir
        (`tamamlandi`: bütçe doldu ya da tavan derinlikte de yeni klasör
        çıkmadı).
        """
        return self.tamamlandi

    # ---------- ceza ----------

    def sure_kontrol(self, tik):
        """Süre doldu ve hedefe ulaşılmadıysa True → ceza doğar."""
        if self.baslangic is None or self.hedef_ulasildi() or self.tamamlandi:
            return False
        if tik - self.baslangic < int(self.cfg.get("sure_tik", 0)):
            return False
        # ceza doğdu; süre yeniden başlar (organizma toparlanıp devam eder)
        # Rapor dürüst olsun: sayacı sıfırlamadan ÖNCEki durumu sakla
        self.son_ilerleme = self.ilerleme(tik)
        self.baslangic = tik
        self.ceza_verildi = True
        return True

    # ---------- iş ----------

    def _haric_mi(self, yol):
        """Sanal/canlı dosya sistemleri ve gizli ölçüm yolları dışarıda."""
        if yol.startswith(str(self.body.world)):
            return True
        for h in self.cfg.get("haric", []):
            if yol == h or yol.startswith(h.rstrip("/") + "/"):
                return True
        return False

    def _duvar_listesi(self, kok, sinir):
        """Duvar modu: kokun ALTINDAKİ tüm klasörler (derinlik sınırlı).

        `find -maxdepth N -type d` tek alt süreçte yüzlerce klasörü verir;
        her biri sonra tek tek işlenir (her kalem = gerçek CPU).

        Derinlik `self.derinlik`'tir (kuyruk tükendiğinde DERİNLEŞİR),
        `self.cfg["derinlik"]` sabit tavan değildir.
        """
        derinlik = int(self.derinlik)
        # `-prune` ŞART: `-not -path` yalnızca ÇIKTIYI filtreler, find
        # dışlanan ağaca inmeyi DENEMEYE devam eder. Sonuç: /proc, /sys,
        # /run içine yüzlerce "Permission denied" stderr gürültüsü ve
        # boşa CPU. -prune ağacı hiç inmeye çalışmaz.
        #   find KOK \( -path A -o -path A/* -o ... \) -prune -o -type d -print
        args = ["find", kok, "-mindepth", "1", "-maxdepth", str(derinlik)]
        dislanan = [h for h in self.cfg.get("haric", []) if h]
        if self.cfg.get("tum_haric", True):
            dislanan.append(str(self.body.world))
        if dislanan:
            args.append("(")
            for i, h in enumerate(dislanan):
                if i:
                    args.append("-o")
                args += ["-path", h, "-o", "-path", h.rstrip("/") + "/*"]
            args.append(")")
            args += ["-prune", "-o", "-type", "d", "-print"]
        else:
            args += ["-type", "d"]
        # AYRIK: stderr ayrı gelir. `find` erişilemeyen dizinleri
        # "find: '/root': Permission denied" diye stderr'e yazar; bunlar
        # yol DEĞİLDİR ve kuyruğa girmemelidir.
        ok, out, err = self.body._calistir(args, cap=262144, ayrik=True)
        self._erisilemezleri_isle(err)
        if not ok:
            return []
        ham = []
        for satir in out.splitlines():
            yol = satir.strip()
            # savunma: yol mutlak olmalı ve tohumun altında olmalı
            if not yol.startswith("/") or not yol.startswith(kok.rstrip("/")):
                continue
            if not yol or yol in self.yapilan:
                continue
            if self._haric_mi(yol):
                continue
            ham.append(yol)
        # Çeşitlilik: tek dalda batmasın (kaynak açlığı). Klasörler annelerine
        # göre gruplanır, sonra gruplar dönüşümlü boşaltılır → kuyruk makineyi
        # geniş kapsar, /boot/grub içinde tükenmez.
        gruplar = {}
        for yol in ham:
            anne = yol.rsplit("/", 1)[0] or "/"
            gruplar.setdefault(anne, []).append(yol)
        sira = list(gruplar.values())
        # büyük dal önce açılsın (daha çok dosya orada)
        sira.sort(key=len, reverse=True)
        bu = []
        i = 0
        while len(bu) < sinir * 4:
            eklendi = False
            for lst in sira:
                if i < len(lst):
                    bu.append(lst[i])
                    eklendi = True
                    if len(bu) >= sinir * 4:
                        break
            if not eklendi:
                break
            i += 1
        return bu

    def _erisilemezleri_isle(self, err):
        """find stderr'inden "Permission denied" yollarını topla.

        Bunlar kataloglanamaz ama "olduğu" bilinir: katalog kendi kör
        noktasını bilmelidir (0 dosya ≠ okunamadı).
        """
        yeni = 0
        for satir in (err or "").splitlines():
            if "Permission denied" not in satir:
                continue
            parca = satir.split(":", 2)
            if len(parca) < 3:
                continue
            yol = parca[1].strip().strip("'")
            if not yol.startswith("/") or yol in self.yapilan:
                continue
            # dışlanan ağaçların içindeki erişim hataları ilginç değildir
            # (/proc/1/fd gibi): sayım şişer ve anlam taşımaz.
            if self._haric_mi(yol):
                continue
            self.erisilemez.add(yol)
            yeni += 1
        if yeni:
            self.erisilemez_yeni += yeni
            self.jour.log("katalog_erisilemez", adet=yeni,
                          toplam=len(self.erisilemez),
                          ornek=sorted(self.erisilemez)[:3])
        return yeni

    def _klasorleri_tara(self):
        """Kaynak köklerin altındaki YENİ klasörleri sıraya al.

        Kaynaklar DÖNÜŞÜMLÜ karıştırılır: ilk kaynak kuyruğu doldurup
        diğerlerini aç bırakmaz (kaynak açlığı).
        """
        azami = int(self.cfg.get("azami_klasor", 0))
        if azami and len(self.yapilan) >= azami:
            self.tamamlandi = True   # bütçe doldu → kalıcı dur
            return
        sinir = int(self.cfg.get("klasor_siniri", 40))
        # TAZELEME: "yapıldı" damgası kalıcıdır ama dünya değişir; her N
        # kalemde bir eski klasör bilerek yeniden taranır (dosya sinyalleri
        # güncellenir: mod/x/shebang, yeni dosyalar). Maliyet: aynı find.
        oran = int(self.cfg.get("tazeleme_oran", 0))
        if oran and self.teslim and self.teslim % oran == 0:
            yol = self.depo.rastgele_klasor()
            if yol and yol not in self.kuyruk:
                self.kuyruk.append(yol)
                self.yenilenen = self.yenilenen + 1
                self.jour.log("tazeleme", klasor=yol,
                              sayac=self.teslim)
                return
        duvar = self.cfg.get("tarama", "tepe") == "duvar"
        tavan = int(self.cfg.get("derinlik_tavan", 8))
        deneme = max(1, int(self.cfg.get("arama_deneme", 3)))
        # KENDİ KENDİNİ İYİLEŞTİRME: kuyruk boşaldı ama bütçe hâlâ duruyor
        # demektir taranacak klasör kalmadı demektir DEĞİLDİR — sadece
        # `derinlik` sınırına dayandık. Bir kademe daha derine in.
        # (Eskiden burada doğrudan tamamlandı=True idi: görev 505 klasörde
        #  kendini kapatıp organizmayı boş döngüye bırakıyordu.)
        for tur in range(deneme):
            listeler = []
            for kok in self.cfg.get("kaynaklar", []):
                if duvar:
                    bu = self._duvar_listesi(kok, sinir)
                else:
                    ok, out, _err = self.body._calistir(
                        ["ls", "-F", kok], ayrik=True)
                    bu = []
                    if ok:
                        for satir in out.splitlines():
                            s = satir.strip()
                            if s.endswith("/") and "/" not in s[:-1]:
                                yol = "%s/%s" % (kok.rstrip("/"), s[:-1])
                                if (yol not in self.yapilan and yol not in bu
                                        and not self._haric_mi(yol)):
                                    bu.append(yol)
                if bu:
                    listeler.append(bu)
            # sırayla birer tane al → kaynaklar adil dönüşür
            i = 0
            while len(self.kuyruk) < sinir:
                eklendi = False
                for lst in listeler:
                    if i < len(lst):
                        self.kuyruk.append(lst[i])
                        eklendi = True
                        if len(self.kuyruk) >= sinir:
                            break
                if not eklendi:      # tüm listeler tükendi → çık
                    break
                i += 1
            if self.kuyruk:
                return
            # Hâlâ yeni klasör yok: duvar modda bir kademe daha derinleş
            if not duvar or self.derinlik >= tavan:
                self.jour.log("tarama_bitti", sebep=("derinlik_tavani"
                                                      if duvar else "tepe"),
                              derinlik=self.derinlik,
                              klasor=len(self.yapilan),
                              deneme=tur + 1)
                break
            self.derinlik += 1
            self.derinleme += 1
            self.jour.log("derinlesti", derinlik=self.derinlik,
                          tur=self.derinleme, klasor=len(self.yapilan))
        if not self.kuyruk:
            # Gerçekten bitti: bütçe doldu VEYA tavan derinlikte de yeni
            # klasör çıkmadı. Organizma işsiz kalmasın diye tazeleme
            # varsa kuyruk boş bırakma; ama hedef/bütçe gerçekten bittiyse
            # kon dur.
            azami = int(self.cfg.get("azami_klasor", 0))
            if azami and len(self.yapilan) >= azami:
                self.tamamlandi = True
            elif not int(self.cfg.get("tazeleme_oran", 0)):
                self.tamamlandi = True   # başka iş de yok → katalogla uymaz
            else:
                self.jour.log("tarama_durdu", sebep="tazelemeye_gecil",
                              derinlik=self.derinlik,
                              klasor=len(self.yapilan))

    def _dosya_kayitlari(self, yol_listesi, zaman=None):
        """Dizin haritasının dosya katmanı: yol, klasör, ad, uzantı, boyut.

        Bu tablo Faz 2'nin (katalogdan kendini eğiten model) veri
        tabanıdır: "hangi dosya nerede" bilgisi burada birikir.
        """
        if not yol_listesi:
            return 0
        return self.depo.dosya_yaz(yol_listesi)

    def calistir_bir(self, tik):
        """Bir kalemlik iş: sıradaki klasörü oku, envantere yaz."""
        if not self.kuyruk:
            self._klasorleri_tara()
            if not self.kuyruk:
                self.kuyruk_bos += 1
                # GÖZLEMLENEBİLİRLİK: bu olay sayıca izlenmeli. Sessizce
                # dönmek yerine kayda geçer (bkz. "kuyruk_bos" sayacı).
                self.jour.log("kuyruk_bos", tur=self.kuyruk_bos,
                              derinlik=self.derinlik,
                              derinleme=self.derinleme,
                              klasor=len(self.yapilan),
                              bitti=self.tamamlandi)
                return {"obs": "incelenecek klasör kalmadı",
                        "kind": "is", "novel": 0, "gain": 0}
        klasor = self.kuyruk.pop(0)
        self.yapilan.add(klasor)

        # OKUMA (tek alt süreç): find her dosya için "boyut<TAB>mod<TAB>yol"
        # basar → satır sayısı = dosya sayısı, boyutların toplamı = karakter.
        # (Klasörün kendi boyutu DEĞER dosyaların toplamı.)
        # Tavan yüksek: büyük klasörler sessizce kırpılmasın.
        # %m (izin bitleri) Faz 3 için bedava geliyor: yürütülebilirlik
        # ayrı bir alt süreç gerektirmiyor.
        ok, out, err = self.body._calistir(
            ["find", klasor, "-maxdepth", "1", "-type", "f",
             "-printf", "%s\\t%m\\t%p\\n"], cap=262144, ayrik=True)
        self._erisilemezleri_isle(err)
        dosya = 0
        karakter = 0
        yol_listesi = []
        # find başarısız/boş çıktıysa bu dizin "okunamadı" olabilir:
        # 0 dosya ile erişilemezliği ayırmadan katalog yanlış bilgi verir.
        durum = "ok" if ok else "erisilemez"
        if ok:
            for satir in out.splitlines():
                parca = satir.split("\t", 2)
                if len(parca) != 3 or not parca[0].isdigit():
                    continue
                dosya += 1
                karakter += int(parca[0])
                yol_listesi.append((parca[2], int(parca[0]), None, parca[1]))
        # 3) YAZMA: klasör özeti + DOSYA KATMANI (dizin haritası)
        #    envanter.jsonl: ad + dosya sayısı + karakter
        #    dosyalar.jsonl : her dosya için yol/klasör/ad/uzantı/boyut
        kayit = {"klasor": klasor, "dosya": dosya, "karakter": karakter,
                 "t": round(time.time(), 3)}
        if durum != "ok":
            kayit["durum"] = durum
        try:
            # PRIMARY KEY: aynı klasör ikinci kez "yeni" sayılamaz; kayıt
            # tazelenir ve sayac artar → dedup veritabanı seviyesinde.
            yeni, onceki = self.depo.klasor_yaz(klasor, dosya, karakter,
                                                durum=durum)
            self._dosya_kayitlari(yol_listesi, zaman=kayit["t"])
            self.teslim += 1
            if not yeni:
                self.jour.log("katalog_tekrar", klasor=klasor,
                              onceki_karakter=onceki, karakter=karakter)
            # JSONL dışa aktarımı seyrek (şeffaflık için, her 25 kalemde)
            if self.teslim % 25 == 0:
                self._jsonl_aktar()
            self.jour.log("katalog_kalem", **kayit)
            ek = "" if yeni else " (tazeleme)"
            if durum != "ok":
                ek = " (ERİŞİLEMEZ — okunamadı, boş DEĞİL)"
            obs = ("envanter: %s → %d dosya, %d karakter (%d/%d)%s"
                   % (klasor, dosya, karakter, self.teslim,
                      self.hedef(), ek))
        except OSError as e:
            obs = "katalog yazılamadı: %s" % e
        return {"obs": obs, "kind": "is", "novel": 0,
                "gain": int(self.cfg.get("odul_enerji", 8))}