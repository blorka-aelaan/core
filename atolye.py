"""CORE atolye — organizmanın YAZILABİLİR kum havuzu (Sahne 0: substrate).

Burada organizma kendi dünyasını GERÇEKTEN kurar: nesne yaratır, taşır,
okur, siler. Eylemlerin kalıcı sonucu var — kota (kıtlık) ve bozulma
(decay: bakılmayan nesne bozulur). Dünya, bizim enumerate etmediğimiz
durumları üretebilir (aşırı üretim → kotaya çarpma → değerli nesne silme
ikilemi gibi). Bu, 3. sütunun (karmaşık-sonuçlu dünya) çekirdeği.

Sahne 0 substrate: atölye var, dokunulabilir, evrilir (bozulma), ve basit
bir dünya modeli TAHMİN edip sürprizi (prediction error) ölçer.
Sahne 1 (merak ödülü): eylemin dünya modeline yaşattığı sürpriz öz-ödül
(intrinsic reward) olur — ama sürpriz |Δ − E[Δ|eylem]|: eylemin KENDİ
beklenen değişiminden sapma (eylem-koşullu öğrenilmiş tahmin). Dünya'nın
değişimi değil, BEKLENMEYEN değişimi ödüllendirilir: her yarat "+1 adet"
ürettiği için tekrarlanabilir eylem sürpriz üretmez (ödül tarlası kapalı).
Sahne 2 (araç-kompozisyonu): `kur` iki nesneyi birleştirir → araç doğar;
araç tek eylemde kuvveti kadar iş yapar (`guc` = toplu onarım), yorulur,
tükenir. Kurallar tablo değil kompozisyon cebri: kuvvet = malzeme (bayt/64),
seviye = en derin parça + 1 (araçtan araç olur). Organizma bu ekonomiyi
merak sinyaliyle keşfeder; asıl kazanç enerji tasarrufudur (N onarım → 1
eylem), ödül değil — merak hâlâ sürprizden, tavanlı.

Sahne 2b (sayım-tabanlı keşif): ablasyon ölçümü gösterdi ki araç
doğumlarının %96'sı orta bant `random.choice`'dan geliyordu, "icat
gereksinimden doğar" dalı ise 0 kez tetiklenmişti (ölü kod) — keşif,
ihtiyaç reflekslerinden değil, politikanın cömertliğinden doğuyordu.
Yerine tek genel mekanizma: eylem sayımları (.kesif.json). Serbest
bantta en az denenmiş iş seçilir (UCB-benzeri kapalı döngü); "kur araç
doğurur" bilgisi koda YAZILMAZ, sayımın düşüklüğüyle kur kendiliğinden
ilk kararlarda denenir. Keşif artık dünyadan (sayım/nadirlik) doğar,
koddan değil.

İlke: güvenli — yalnızca atolye/ altında, yol kilidi (_safe) ile; host'a
dokunma yok. Diğer organlar gibi: beyin "şu işi yap" der, bu organ
argümanı dünya durumundan KENDİ seçer.

Dünya modeli (Sahne 0-1): pasif tazedede naive tahmin (önceki durum);
eylem kapısında (eylem()) tahmin eylem-koşulludur — her eylemin tipik Δ'si
geçmişten öğrenilir (.beklenen.json), sürpriz = |gerçek Δ − beklenen Δ|.
Sahne 2b'de uygulanamaz iş SEÇİLMEZ (serbest adaylar kapıdan geçer) ve
erken dönüş (no-op) sayıma girmez — sayımlar "gerçekten denenmiş iş"dir.
"""
import json
import random
from pathlib import Path


class Atolye:
    KOTA = 24            # aynı anda en fazla nesne (gerçek kıtlık)
    # Bozulma eşiği SANIYE cinsinden tutulur; __init__'te tick_seconds'a
    # bölünerek tik sayısına dönüştürülür. Böylece body.json'da
    # tick_seconds değiştiğinde bozulma ritmi fiilen kaymazb
    # (eski sabit 600 tik = 0.4s × 600 = 240 saniye ≈ 4 dakikaydı).
    BOZULMA_SN = 240     # bu kadar saniye bakılmazsa nesne bozulur (decay)
                         # 240 sn ≈ 4 dk: 0.4s/tik × 600 tik karşılığı
                         # ziyaret ritmi (12 nesne × ~2.5 dk) üstünde
                         # olmalı — 60 tikle içerik hiç yaşayamadan
                         # çürüyordu (2026-10-19 ölçümü: 12/12 nesne
                         # tamamen "?" idi, atölye sıfır bilgi taşıyordu)
    REFLEKS_ESIK = 8     # refleks üst üste bu kadar tur sürerse 1 tur
                         # serbest banda bırakılır (açmaz koruması —
                         # bkz. sec_is: canlıda 8.5 saatlik "bak" kiliti)
    AD_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789_"
    # dünya modelinin ölçtüğü bileşenler + Sahne 1 merak ayarları
    # Sahne 2: "arac" = kalan kuvveti olan araç sayısı (kompozisyon ekonomisi
    # de dünyanın bir parçası — araç yapımı/yorulması sürpriz üretir)
    VEK_ANAHTAR = ("adet", "bozuk", "boyut", "duzenli", "arac")
    MERAK_OLCEK = 1.0    # sürpriz 1 birim → 1.0 öz-ödül
    MERAK_TAVAN = 1.5    # tek eylemde azami merak — kasıtlı küçük:
                         # merak fısıltıdır, bağırış değil; küçük tutmak
                         # yarat/sil döngüsüyle ödül tarlalığını kapatır
                         # (her eylem gerçek enerji de yakar → kendiliğinden
                         # kısılır). Keşif bonusu (+3) atölyeye HAZIRAN VERİLMEZ.

    def __init__(self, world_kok, journal, politika="sayim", tick_seconds=0.4):
        self.kok = Path(world_kok) / "atolye"
        self.kok.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        # Bozulma eşiğini tik sayısına dönüştür (tick_seconds'a bağımlı).
        # Minimum 60 tik: çok hızlı tick'te bile eşik saçma küçülmesin.
        self.BOZULMA = max(60, int(round(self.BOZULMA_SN / max(tick_seconds, 0.01))))
        self.durum_yolu = self.kok / ".durum.json"
        self.nesneler = self._durum_yukle()
        # Bozulma (decay) içeriği DÜNYADA ezer ("?" yazar). Orijinal
        # içerik kaybolursa onarım sahte kalır (okunan zaten "?") —
        # dünya geri dönüşsüz biçimde çöplenir. Bu yüzden bozulma
        # ANINDA orijinal içerik .yedek/<ad> altına alınır; onarım
        # diskten değil, YEDEKTEN geri yükler. Yedek dosyaları
        # .durum.json'da sayılmaz (web nesne listesini oradan okur).
        self.yedek_kok = self.kok / ".yedek"
        self.yedek_kok.mkdir(parents=True, exist_ok=True)
        # ESKİ DÜNYA DÜZELTMESİ: sahte onarım (içeriği okuyup geri yazma)
        # "?" dolu dosyaları "bozuk" işaretlemeden bırakmıştı → kayıt
        # sağlıklı görünürken içerik çöptü (canlıda 15 nesne). Yükleme
        # sırasında içerik denetlenir: "?" dolu dosya bozuk işaretlenir
        # (yedek varsa onarılabilir, yoksa kurtarılamaz → ölü).
        self._icerik_denetle()
        # Politika kolu (Sahne 2b):
        #   "sayim" (varsayılan, prod): serbest bantta en az denenmiş
        #     eylem — keşif, elle yazılmış daldan değil sayımdan gelir.
        #   "eski"  (ölçüm kontrolü): Sahne 2'nin iki el yazması dalı
        #     (rastgele orta bant + gereksinimden icat) — prod değil.
        #   "yok"   (ablasyon): keşif tamamen kapalı, saf need-driven
        #     (deterministik 'tasi') — teşhis kanıtı için ölçülür.
        #   "surpriz"(ölçüm kolu, opt-in): sayım skoru + son sürpriz (EMA)
        #     — "sürpriz iç seçimi değiştirir mi?"nın A/B kolu. Sürpriz
        #     sıfırsa skor = 1/sqrt(1+say) → argmin say = birebir "sayim"
        #     davranışı (ablasyon dürüst: merak sakinleşince kol kapanır).
        if politika not in ("sayim", "eski", "yok", "surpriz"):
            raise ValueError("bilinmeyen politika: %r" % (politika,))
        self.politika = politika
        # Sahne 2b eylem sayımları — AYRI dosya: .durum.json web/okuyucu
        # için nesne listesi (nesne adı → kayıt) olarak kalır, biçimi
        # değişmez (özel anahtar koysak veri.js onu nesne sayardı).
        self.kesif_yolu = self.kok / ".kesif.json"
        self.is_say = self._kesif_yukle()
        # Sahne 1: eylem-koşullu BEKLENEN değişim (her eylemin tipik Δ'si)
        # — sürpriz bu tahminden sapmadır, ham |Δ| değil (bkz. eylem()).
        self.beklenen_yolu = self.kok / ".beklenen.json"
        self.beklenen = self._beklenen_yukle()
        # dünya modeli: son gözlenen durum + naive tahmin (Sahne 0)
        self.model = {"son": None, "surpriz": 0.0}
        self.tik = 0            # son tik (tikla her tikte tazeler)
        self.refleks_ust = 0    # üst üste refleks turu (sec_is açmaz koruması)
        # "surpriz" ölçüm kolunun bellek içi EMA'sı (kalıcı DEĞİL:
        # yeniden açılışta 0 → kol doğal olarak sayım davranışına döner)
        self.son_surpriz = {}

    # ---------- kalıcı durum ----------

    def _durum_yukle(self):
        try:
            with open(self.durum_yolu, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _durum_kaydet(self):
        tmp = self.durum_yolu.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.nesneler, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.durum_yolu)

    def _kesif_yukle(self):
        """Sahne 2b eylem sayımları — bozuk/eksikse sıfırdan başla."""
        try:
            with open(self.kesif_yolu, encoding="utf-8") as f:
                veri = json.load(f)
            return veri if isinstance(veri, dict) else {}
        except (OSError, ValueError):
            return {}

    def _kesif_kaydet(self):
        tmp = self.kesif_yolu.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.is_say, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.kesif_yolu)

    def _beklenen_yukle(self):
        """Sahne 1 tahmin modeli: eylem → {say, ort} (beklenen Δ'si).

        Şekilsiz/bozuk kayıt atılır — model yeniden öğrenilir, sürpriz
        yalan söylemez. Kalıcıdır: yeniden açılışta öğrenilmiş tahmin
        taşınır (ESKI_AD mantığı gibi).
        """
        try:
            with open(self.beklenen_yolu, encoding="utf-8") as f:
                veri = json.load(f)
        except (OSError, ValueError):
            return {}
        temiz = {}
        if isinstance(veri, dict):
            for is_, k in veri.items():
                if (isinstance(k, dict) and isinstance(k.get("say"), int)
                        and isinstance(k.get("ort"), list)
                        and len(k["ort"]) == len(self.VEK_ANAHTAR)):
                    temiz[is_] = k
        return temiz

    def _beklenen_kaydet(self):
        tmp = self.beklenen_yolu.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.beklenen, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.beklenen_yolu)

    # ---------- yol kilidi (host'a sıçrama yok) ----------

    def _guvenli_ad(self, ad):
        """Adı güvenli karakterlere indirger (None: kullanılamaz)."""
        ad = "".join(c for c in str(ad).lower() if c in self.AD_SAFE)[:32]
        if not ad or ad.startswith("."):
            return None
        return ad

    def _safe(self, ad):
        ad = self._guvenli_ad(ad)
        if ad is None:
            return None
        cand = (self.kok / ad).resolve()
        try:
            cand.relative_to(self.kok.resolve())
        except ValueError:
            return None
        return cand

    # ---------- yedek (bozulan içeriğin kurtarılması) ----------

    def _yedek_yolu(self, ad):
        """Nesnenin yedek dosya yolu (güvenli ad → .yedek/<ad>)."""
        ad = self._guvenli_ad(ad)
        if ad is None:
            return None
        return self.yedek_kok / ad

    def _yedekle(self, ad, icerik):
        """Orijinal içeriği yedeğe yaz. Başarısız olursa False."""
        y = self._yedek_yolu(ad)
        if y is None:
            return False
        try:
            y.write_text(icerik, encoding="utf-8")
            return True
        except OSError:
            return False

    def _yedekten_yukle(self, ad):
        """Yedekten orijinal içeriği getir (yoksa None).

        Yedek dosyası okunamazsa None döner — onarım YEDEK YOKSA
        yapılmaz (içerik uydurulmaz: "?" satırı gerçek içerik sanılıp
        dünyaya yazılmamalıdır).
        """
        y = self._yedek_yolu(ad)
        if y is None or not y.exists():
            return None
        try:
            return y.read_text(encoding="utf-8")
        except OSError:
            return None

    def _yedek_sil(self, ad):
        """Nesne silindi/kuruldu → yedeği de temizle (hayalet yedek yığılması)."""
        y = self._yedek_yolu(ad)
        if y is None:
            return
        try:
            y.unlink()
        except OSError:
            pass

    # ---------- gözlem / dünya modeli ----------

    def saglik(self):
        """0..1: iyi bakılmış (bozuk olmayan) nesne oranı."""
        if not self.nesneler:
            return 0.0
        bozuk = sum(1 for v in self.nesneler.values() if v.get("bozuk"))
        return round((len(self.nesneler) - bozuk) / len(self.nesneler), 3)

    def durum_vek(self):
        """Dünya modelinin gördüğü durum vektörü (tahmin girdisi)."""
        bozuk = sum(1 for v in self.nesneler.values() if v.get("bozuk"))
        duzenli = sum(1 for ad in self.nesneler
                      if ad.startswith("grup_"))  # yapı (tasi)
        # Sahne 2: kullanılabilir araç (kuvveti olan, bozuk olmayan)
        arac = sum(1 for v in self.nesneler.values()
                   if v.get("tur") == "arac"
                   and v.get("kuvvet", 0) > 0
                   and not v.get("bozuk"))
        toplam = 0
        for ad in self.nesneler:
            try:
                toplam += (self.kok / ad).stat().st_size
            except OSError:
                pass
        return {"adet": len(self.nesneler), "bozuk": bozuk,
                "boyut": toplam // 64, "duzenli": duzenli,
                "arac": arac, "saglik": self.saglik()}

    def tikla(self, tik):
        """Her tik: bozulma uygula + dünya modelini tahmin et/sürpriz ölç.

        Bozulma: BOZULMA tik boyunca bakılmayan nesne bozuk sayılır
        (içeriği 'kaybolur'). Dünyayı statik olmaktan çıkarır — dikkat
        bütçesi gerektirir (gerçek sonuç, elle yazılmadı).
        """
        self.tik = tik
        degisti = False
        for ad, v in self.nesneler.items():
            if (not v.get("bozuk")
                    and (tik - v.get("son_bakim", tik)) >= self.BOZULMA):
                p = self.kok / ad
                bozuldu = False
                try:  # içeriğin gerçekten bozulması (gerçek sonuç)
                    if p.exists():
                        # GERİ DÖNÜŞSÜZLÜK YOK: orijinal içerik önce
                        # yedeğe alınır. Yedek alınamazsa bozma YAPILMAZ —
                        # onarımın nereyi geri yükleyeceği bilinmiyorsa
                        # dünya sahte bir onarımla (içerik "?" kalır) sahte
                        # iyileşme üretmemelidir.
                        onceki = p.read_text(encoding="utf-8")
                        if self._yedekle(ad, onceki):
                            p.write_text("?" * (p.stat().st_size or 1),
                                         encoding="utf-8")
                            bozuldu = True
                except OSError:
                    pass
                if bozuldu:
                    v["bozuk"] = True
                    degisti = True
        if degisti:
            self._durum_kaydet()
        # dünya modeli: naive tahmin → sürpriz (Sahne 1'in ham ödülü)
        simdi = self.durum_vek()
        on = self.model["son"]
        if on is not None:
            self.model["surpriz"] = float(sum(
                abs(simdi[k] - on[k]) for k in self.VEK_ANAHTAR))
        self.model["son"] = simdi
        return simdi

    # ---------- eylemler (organ parametreyi KENDİ seçer) ----------

    def sec_is(self):
        """Organın kendi politikası: dünya durumundan sıradaki işi seç.

        Beyin "atolye" der; bu organ NE yapacağına kendi karar verir
        (katalogla/konum deseni). İki katman:

        1. İhtiyaç refleksleri (her kol aynı): bozuk → onar (araçla
           toplu: guc, yoksa bak); kotada birleştir (kur: içerik +
           malzeme korunur, araç doğar); yarım dolu altı → yarat.
           Bunlar homeostazi — keşif değil. Ama refleks dünya
           sağlığını REFLEKS_ESIK tur üst üste sağlayamadıysa (onarım
           arzı < decay talebi → sıfır-bozuk şartlı serbest bant hiç
           açılmıyor; canlıda 8.5 saatlik kilit) bir tur serbest
           banda bırakır: sabır bitti, karar yine sayımın.
        2. Serbest bant (orta bant) → KEŞİF, politika koluna bağlı;
           adaylar önce UYGULANABİLİRLİK kapısından geçer (uygulanamaz
           iş hiç seçilmez → no-op sayıma düşmez, keşif kilitlenmez):
           - "sayim" (prod): en az denenmiş eylem — sayımlar (is_say)
             besler; "kur araç doğurur" bilgisi KODA YAZILMADI, kur
             sayımın düşüklüğüyle ilk kararlarda kendiliğinden denenir
             → keşif dünyadan (nadirlik) doğar. Eşitlikte rastgelelik
             yalnız bağ bozar, seçim üretmez.
           - "eski" (ölçüm kontrolü): rastgele orta band + icat dalı.
           - "yok" (ablasyon): deterministik 'tasi' — keşif kapalı.
        """
        # Hayalet temizliği (gerçek dünya tutarlılığı — 2026-10-19
        # canlı dersi): çift-süreç penceresinde .durum.json'a kayıt
        # geri yazılmış ama dosyası silinmişti → sec_is "bozuk var"
        # derken guc "onarılacak yok" diyordu: 151 dakika süren
        # no-op döngüsü (82 guc/15dk, saglik 0.889'da kilit). yarat()
        # aynı temizliği yapıyordu ama sec_is ona hiç uğramıyordu.
        # Karar ÖNCESİ dünya gerçeğiyle hizalanır: dosyası olmayan
        # kayıt dünya değildir, silinir (diske de yazılır).
        hayalet = [a for a in self.nesneler if not (self.kok / a).exists()]
        for a in hayalet:
            del self.nesneler[a]
        if hayalet:
            self._durum_kaydet()
        # bozuk listesine existence koşulu (savunma derinliği: yukarıdaki
        # temizlik bile atlasa guc asla "yok" demez) + KURTARILABİLİRLİK
        # koşulu: yedek yok ve içerik "?" ise onarım imkânı YOK (ölü
        # nesne). Ölü nesneler onarım listesinde tutulursa refleks sonsuza
        # dek "bak" seçer, hiçbir iş yapmadan enerji yakar (dürüstlük
        # yerine sahte iyileşme döngüsü). Ölüler "sil" ile temizlenir.
        bozuk = [a for a, v in self.nesneler.items()
                 if v.get("bozuk") and (self.kok / a).exists()]
        olu = [a for a in bozuk if not self._onarilabilir(a)]
        olu = [a for a in olu if (self.kok / a).exists()]
        bozuk = [a for a in bozuk if a not in olu]
        arac = [a for a, v in self.nesneler.items()
                if v.get("tur") == "arac" and v.get("kuvvet", 0) > 0
                and not v.get("bozuk")]
        if olu and not bozuk:
            # Onarılacak canlı nesne yok, sadece ölü var → ölüleri temizle
            # (kota da açılır, dünya çöpten kurtulur).
            return "sil"
        if bozuk:
            # Açmaz koruması (Sahne 2b canlısı): onarım arzı decay
            # talebini karşılamıyorsa refleks dünya sağlığını asla
            # kuramaz → sıfır-bozuk şartlı serbest bant hiç açılmaz,
            # keşif kilitlenir (ölçüm: 8.5 saat kesintisiz bak).
            # Refleks REFLEKS_ESIK tur üst üste sürdüyse bir tur
            # serbest banda bırakılır — karar yine sayımın (en az
            # denenmiş iş). "kur araç doğurur" gibi alan bilgisi hâlâ
            # KODA YAZILMADI; yalnızca sabır tükenmesi var.
            if self.politika == "sayim":
                self.refleks_ust += 1
                if self.refleks_ust >= self.REFLEKS_ESIK:
                    self.refleks_ust = 0
                    return self._serbest_sec()
            if arac:
                return "guc"  # araçla toplu onarım
            if (self.politika == "eski" and len(bozuk) >= 3
                    and len(self.nesneler) >= 2):
                # "eski" kontrol kolu: gereksinimden icat yatırımı.
                # Ablasyon ölçümünde 0 kez tetiklendi (ölü kod) —
                # "sayim" bunu bilinçli taşımaz: keşif sayımdan gelir.
                return "kur"
            return "bak"
        self.refleks_ust = 0   # dünya onarıldı → sabır sayacı sıfırla
        if len(self.nesneler) >= self.KOTA:
            return "kur"   # silmeden önce birleştir (içerik + malzeme kalır)
        if len(self.nesneler) < self.KOTA // 2:
            return "yarat"    # dünya boş → kur (deneyimini yaz)
        # serbest bant: büyü / düzenle / birleştir — keşif buradan geçer
        return self._serbest_sec()

    def _tasi_hedefleri(self):
        """tasi'nin bugünkü geçerli hedefleri: ham nesne + hedef ad boş.

        Önek BİR KEZ eklenir (grup_x → grup_grup_x DEĞİL); üst üste
        grup taşıma ve ad çakışması kapalı kapıdır — no-op hem keşif
        şişmesine yol açmaz hem de adlar 32-char sınırında ezilmez.
        """
        mevcut = [a for a in self.nesneler if (self.kok / a).exists()]
        if len(mevcut) < 2:
            return []
        hedefler = []
        for a in mevcut:
            if a.startswith("grup_"):
                continue
            y = self._safe("grup_" + a)
            if y is not None and not y.exists():
                hedefler.append(a)
        return hedefler

    def _serbest_adaylar(self):
        """Uygulanabilir serbest işler — uygulanamaz iş SEÇİLMEZ.

        Kapı aday SEÇİMİNDEDİR: eylem() no-op'a düşmez, sayımlar
        "denenmiş iş" anlamını korur ve keşif geçersiz bir işe asla
        takılmaz (en az denenmiş ∩ uygulanabilir = canlı döngü).
        """
        mevcut = [a for a in self.nesneler if (self.kok / a).exists()]
        adaylar = []
        if self._tasi_hedefleri():
            adaylar.append("tasi")
        if len(mevcut) < self.KOTA:
            adaylar.append("yarat")
        if len(mevcut) >= 2:
            adaylar.append("kur")
        return adaylar or ["bak"]  # defo: sürdürme (serbest bant
                                    # 0 nesneye inmez — yine de kapalı)

    def _serbest_sec(self):
        """Serbest bandın kararı — politika koluna göre (sec_is'ten
        ayrıldı: kaçış da, normal keşif de aynı sayım kapısından geçer;
        tüm kollar uygulanabilirlik adaylarından seçilir)."""
        adaylar = self._serbest_adaylar()
        if self.politika == "yok":
            # ablasyon: keşif kapalı, deterministik tasi — tasi'nin
            # bugün karşılığı yoksa (hepsi zaten grup_x) yapı işine
            # değil ihtiyaç işine düşer: yarat/kur/bak, rastgelelik yok.
            return "tasi" if "tasi" in adaylar else adaylar[0]
        if self.politika == "eski":
            return random.choice(adaylar)
        if self.politika == "surpriz":
            # ölçüm kolu (opt-in — prod "sayim" değişmez): UCB benzeri
            # skor = (1 + son sürpriz EMA) / sqrt(1 + deneme sayısı).
            # SÜRPRİZ SIFIRSA (merak sakinleşti / EMA boş) skor
            # 1/sqrt(1+say) → argmin say = birebir "sayim" kararı:
            # kolun tabanı sayım davranışıdır, elle yazılmış bilgi yok.
            return max(adaylar,
                       key=lambda a: ((1.0 + self.son_surpriz.get(a, 0.0))
                                      / (1.0 + self.is_say.get(a, 0)) ** 0.5,
                                      random.random()))
        # "sayim": sayım-tabanlı merak — en az denenmiş işi seç.
        en_az = min(self.is_say.get(a, 0) for a in adaylar)
        dengeler = [a for a in adaylar if self.is_say.get(a, 0) == en_az]
        return random.choice(dengeler)

    def eylem(self, is_, icerik=""):
        """Sahne 1 tek kapısı: işi çalıştır, öz-ödülü sürprizden biç.

        Merak = eylemin dünya modeline yaşattığı ÖZ-KAYNAKLI sürpriz
        (self-caused prediction error): gerçek Δ − eylemin ÖĞRENİLMİŞ
        BEKLENEN Δ'si (.beklenen.json). Sürpriz = beklenmeyen değişim:
        tekrarlanabilir eylem (her yarat "+1 adet") sürpriz üretmez —
        ödül tarlası kapalı. Pasif bozulma sürprizi bu kapıdan ödül
        almaz. Enerjiye gitmez (merak ≠ kalori); doğrudan öğrenme
        sinyaline eklenir. no-op (dünyaya dokunmayan erken dönüş)
        sayıma girmez: sayımlar "gerçekten denenmiş iş" demektir;
        beklentiye de işlemez, sürpriz/ödül üretmez (tek kapı dürüstlüğ).
        """
        on = self.durum_vek()
        res = {"yarat": lambda: self.yarat(icerik),
               "bak": self.bak, "tasi": self.tasi,
               "sil": self.sil, "kur": self.kur,
               "guc": self.guc}[is_]()
        # Sahne 2b: her çalışma sayılır — ihtiyaç refleksi de, serbest
        # bant keşfi de. Sayımlar sec_is'in keşif tercihini besler ve
        # kalıcıdır (.kesif.json): "bugüne kadar neyi ne kadar yaptım?"
        if not res.get("bos"):
            self.is_say[is_] = self.is_say.get(is_, 0) + 1
            self._kesif_kaydet()
        simdi = self.durum_vek()
        delta = {k: simdi[k] - on[k] for k in self.VEK_ANAHTAR}
        bos_mu = bool(res.get("bos"))
        # Sahne 1 (eylem-koşullu tahmin): beklenen Δ = eylemin geçmişteki
        # tipik etkisi (koşullu ortalama, .beklenen.json); ilk denemede
        # naive tahmin (değişim yok) — sürpriz ilk görülen şeydedir.
        kayit = self.beklenen.get(is_)
        if kayit is None:
            ort, n = [0.0] * len(self.VEK_ANAHTAR), 0
        else:
            ort, n = list(kayit["ort"]), kayit["say"]
        bek = list(ort)   # güncelleme ÖNCESİ beklenti (kayıt/diyagnoz)
        taban = float(kayit.get("taban", 0.0)) if kayit else 0.0
        if bos_mu:
            # no-op tek kapı dürüstlüğü: sayımda olduğu gibi beklentiye de
            # işlemez — kota-reddi/adi-no-op'un Δ=0'sı "tipik etkiyi"
            # saptırmasın; sürpriz de yok (dünyaya dokunulmadı).
            surpriz, odul = 0.0, 0.0
        else:
            if kayit is None:
                surpriz = float(sum(abs(delta[k]) for k in self.VEK_ANAHTAR))
            else:
                surpriz = float(sum(abs(delta[k] - kayit["ort"][i])
                                    for i, k in enumerate(self.VEK_ANAHTAR)))
            # Sahne 1c — alışkanlaşma (habituation): ÖDÜL yalnızca sürprizin
            # eylemin KENDİ sürpriz tabanını (EMA) AŞAN kısmı. Değişken Δ'lı
            # eylemler (kur: her seferinde farklı boyut, yarat: değişken
            # içerik) için |Δ−E[Δ]| asla sıfırlanır — ama bu artık
            # ÖDÜLLENMEZ: taban eylemin kendi geçmişinden öğrenilir
            # (.beklenen.json "taban"), çeşit kapanır. Elle yazılmış eşik
            # yok; yalnız eylemin alışılmadık derecede BÜYÜK sürprizi
            # (yeni durum, beklenmeyen bozulma) tam ödül alır.
            fazla = max(0.0, surpriz - taban)
            odul = round(min(self.MERAK_TAVAN, fazla * self.MERAK_OLCEK), 2)
            for i, k in enumerate(self.VEK_ANAHTAR):
                ort[i] += (delta[k] - ort[i]) / (n + 1)
            yeni_taban = taban + 0.15 * (surpriz - taban)
            self.beklenen[is_] = {"say": n + 1,
                                  "ort": [round(x, 4) for x in ort],
                                  "taban": round(yeni_taban, 4)}
            self._beklenen_kaydet()
            # "surpriz" ölçüm kolunun EMA'sı (no-op güncellemez)
            self.son_surpriz[is_] = (0.5 * self.son_surpriz.get(is_, surpriz)
                                     + 0.5 * surpriz)
        # model tazelenir: sürpriz yalnız eylemin kendi izini taşısın
        # (pasif bozulma sürprizi tikla'da ölçülür, ödül değil)
        self.model["son"] = simdi
        res["merak"] = odul
        res["is"] = is_
        res["surpriz"] = surpriz
        res["taban"] = round(taban, 4)
        # novel asla 1 olmaz: main'de novel*3 keşif bonusu tekrarlanabilir
        # bir eylemde ÖDÜL TARLASI doğururdu (yarat→sil→yarat). Atölyenin
        # tek dili merak'tır — keşif bonusu gerçek keşiflere (ilk ziyaret,
        # ilk kutu) saklıdır.
        res["novel"] = 0
        self.journal.log("merak", islem=is_, surpriz=round(surpriz, 4),
                         odul=odul, saglik=self.saglik(),
                         taban=round(taban, 4),
                         nesne=len(self.nesneler),
                         obs=res.get("obs", "")[:60],
                         bos=bos_mu,
                         # ölçüm alanları (veri.js bu alanları yok sayar):
                         # dlt = gözlenen Δ, bek = güncelleme öncesi E[Δ]
                         # → bileşen-bazlı rezidü analizi (boyut gürültüsü,
                         #   bağlam-koşullu beklenti kanıtı) bu alandan
                         dlt=[delta[k] for k in self.VEK_ANAHTAR],
                         bek=bek)
        return res

    def yarat(self, icerik=""):
        """Yeni nesne yarat. İçerik: organizmanın son gözlemi (deneyimini
        'yazması'). Kota doluysa reddet → kıtlık gerçek hissedilsin."""
        bos = [ad for ad in self.nesneler if not (self.kok / ad).exists()]
        for ad in bos:  # bozulmuş/kayıp kayıtları temizle
            del self.nesneler[ad]
        if bos:
            # hayalet temizliği hemen diske: kota GERÇEĞİ kalıcı olmalı —
            # erken dönüşte (kota hâlâ dolu) temizlik yalnız bellekte
            # kalırsa yeniden açılışta sahte doluluk geri gelir.
            self._durum_kaydet()
        if len(self.nesneler) >= self.KOTA:
            return {"obs": "atölye dolu (kota=%d)" % self.KOTA,
                    "kind": "atolye", "novel": 0, "gain": 0, "bos": 1}
        ad = "n%02d_%s" % (len(self.nesneler),
                           "".join(random.choice("abcdef0123456789")
                                   for _ in range(4)))
        p = self._safe(ad)
        if p is None:
            return {"obs": "atölye ad güvenliği", "kind": "atolye",
                    "novel": 0, "bos": 1}
        p.write_text(str(icerik)[:400], encoding="utf-8")
        self._yedek_sil(ad)   # yeni nesne: eski yedek (varsa) temizlenir
        self.nesneler[ad] = {"son_bakim": self.tik, "bozuk": False}
        self._durum_kaydet()
        return {"obs": "nesne yaratıldı: %s (%d bayt)" % (ad, p.stat().st_size),
                "kind": "atolye", "novel": 1, "gain": 0}

    def _kurtarilabilir(self, ad):
        """Bu nesnenin onarım kaynağı var mı? (yedek dosyası)"""
        y = self._yedek_yolu(ad)
        return y is not None and y.exists()

    def _onarilabilir(self, ad):
        """Onarım GERÇEKTEN mümkün mü?

        - yedek varsa → evet (orijinal içerik geri yüklenir)
        - yedek yoksa ama içerik sağlam → evet (bayrak uydurma, düzeltilir)
        - yedek yok ve içerik "?" → HAYIR: içerik kalıcı olarak kayboldu
          (ölü nesne — onarım denemesi boşa enerji harcar)
        """
        if self._kurtarilabilir(ad):
            return True
        try:
            disk = (self.kok / ad).read_text(encoding="utf-8")
        except OSError:
            return False
        return not self._bozulmus_mu(disk)

    def _icerik_denetle(self):
        """Kayıt ↔ disk gerçeğini hizala (eski sahte onarım izlerini temizle).

        Sahte onarım (içeriği okuyup geri yazma) "?" dolu dosyaları
        "bozuk" işaretlemeden bırakmıştı → kayıt sağlıklı görünürken
        içerik çöptü (canlıda 15 nesne). Denetim:
        - içerik "?" dolu → bozuk işaretle (yedek varsa onarılabilir,
          yoksa kurtarılamaz → "ölü" nesne: onarım döngüsünü tıkayamaz)
        - bozuk işaretli ama içerik sağlam → bayrak eski/uydurma, düzelt
        Sonuç diske yazılır (saglik/durum_vek gerçeği görsün).
        """
        degisti = False
        for ad, v in self.nesneler.items():
            p = self.kok / ad
            try:
                if not p.exists():
                    continue
                icerik = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if self._bozulmus_mu(icerik):
                if not v.get("bozuk"):
                    v["bozuk"] = True
                    degisti = True
            elif v.get("bozuk"):
                # içerik sağlam → bayrak uydurma/eski; düzelt (malzeme
                # zaten sağlamdı, onarım gerekmiyor)
                v["bozuk"] = False
                degisti = True
        if degisti:
            self._durum_kaydet()

    def _bozulmus_mu(self, icerik):
        """İçerik decay izi mi? (yalnız "?" karakterlerinden oluşur)"""
        return bool(icerik) and set(icerik) == {"?"}

    def _onar(self, ad):
        """Bozuk nesneyi onar. Dönüş: "gercek" | "bayrak" | None.

        - "gercek": orijinal içerik YEDEKTEN geri yüklendi (içerik
          gerçekten kurtuldu — diskte artık "?" yok).
        - "bayrak": içerik zaten sağlam (bayrak eski/uydurma bozulma)
          → sadece bozuk işareti düzeltilir, malzeme zaten sağlamdı.
        - None: kurtarma imkânı YOK (yedek yok, içerik "?" → içerik
          gerçekten kayboldu). Onarım YAPILMAZ: uydurma iyileşme yok.
        """
        p = self.kok / ad
        yedek = self._yedekten_yukle(ad)
        if yedek is not None:
            try:
                p.write_text(yedek, encoding="utf-8")
            except OSError:
                return None
            self._yedek_sil(ad)
            return "gercek"
        try:
            disk = p.read_text(encoding="utf-8")
        except OSError:
            return None
        if self._bozulmus_mu(disk):
            return None         # kayboldu: onarılamaz (dürüstçe bozuk kalır)
        return "bayrak"         # içerik sağlam: sadece bayrak eski

    def bak(self):
        """Bak (oku + tazele → bozulmayı önle). Bozuk varsa öncelik onlar:
        onarım bir iştir, rastgele okuma değil. Onarım malzemeyi KORUR:
        içerik tam yazılır (guc ile aynı tam tur — [:80] kesik yok) ve
        yazım hatası eylemi çökertmez (guc'un try/except kapısı).

        ONARIM GERÇEKTİR: bozulan içerik diskte "?" olmuştur; onarım
        diski okuyup geri yazmak sahte onarımdır (içerik "?" kalır).
        Bu yüzden onarım YEDEKTEN yükler (.yedek/<ad>). Yedek yoksa
        nesne bozuk kalır (uydurma onarım yok) — durum dürüstçe raporlanır.
        """
        bozuklar = [a for a, v in self.nesneler.items()
                    if (self.kok / a).exists() and v.get("bozuk")
                    and self._onarilabilir(a)]
        saglam = [a for a, v in self.nesneler.items()
                  if (self.kok / a).exists() and not v.get("bozuk")]
        aday = bozuklar or saglam   # onarım öncelikli (sonuç-odaklı)
        if not aday:
            return {"obs": "atölye boş", "kind": "atolye", "novel": 0,
                    "bos": 1}
        ad = random.choice(aday)
        p = self.kok / ad
        if self.nesneler[ad].get("bozuk"):
            # gerçek onarım: orijinal içerik yedeğten (yoksa kurtarma
            # imkânı yoksa nesne bozuk kalır — uydurma iyileşme yok)
            if self._onar(ad) is not None:
                self.nesneler[ad]["bozuk"] = False
        try:
            icerik = p.read_text(encoding="utf-8")   # tam içerik: malzeme
        except OSError:
            icerik = "(kayıp)"
        self.nesneler[ad]["son_bakim"] = self.tik
        self._durum_kaydet()
        return {"obs": "bakıldı %s: %s" % (ad, icerik[:40]),
                "kind": "atolye", "novel": 0, "gain": 0}

    def tasi(self):
        """Yeniden düzenle: bir nesneyi grup-literaline taşı (yapı kurma).

        Önek BİR KEZ eklenir: hedef zaten grup_ ise üstüne tekrar
        eklenmez (grup_grup_x yok — yapı yığılmaz, adlar 32-char
        sınırında ezilmez). Ham hedef yoksa kapı kapalıdır (no-op →
        sayıma girmez, keşif şişmez).
        """
        adaylar = self._tasi_hedefleri()
        if not adaylar:
            return {"obs": "düzenlenecek ham nesne yok (en az 2 nesne + "
                           "ham hedef)", "kind": "atolye", "bos": 1}
        ad = random.choice(adaylar)
        p = self.kok / ad
        y = self._safe("grup_" + ad)
        if y is None or y.exists():  # ad çakışması (nadir)
            return {"obs": "taşınamadı: grup_" + ad, "kind": "atolye",
                    "bos": 1}
        try:
            p.rename(y)
        except OSError as e:
            return {"obs": "taşıma hatası: %s" % e, "kind": "atolye",
                    "bos": 1}
        yeni_ad = y.name
        self.nesneler[yeni_ad] = self.nesneler.pop(ad)
        self.nesneler[yeni_ad]["son_bakim"] = self.tik
        # yedek de yeni adla taşınır (yoksa onarım kaynağı kaybolur)
        yed_eski = self._yedek_yolu(ad)
        yed_yeni = self._yedek_yolu(yeni_ad)
        if yed_eski is not None and yed_yeni is not None and yed_eski.exists():
            try:
                yed_eski.rename(yed_yeni)
            except OSError:
                pass
        self._durum_kaydet()
        return {"obs": "taşındı: %s → %s" % (ad, yeni_ad),
                "kind": "atolye", "novel": 1}

    def sil(self):
        """Nesne sil (kota aç). Önce ÖLÜ nesneler (kurtarılamayan "?"
        içerikli, yedeksiz) temizlenir — onarılamayacakları için dünyada
        tutmanın anlamı yok, sadece bozuk sayısını şişirirler. Sonra
        bozuk/boş nesneler, en son normal nesneler."""
        olu = [a for a, v in self.nesneler.items()
               if v.get("bozuk") and (self.kok / a).exists()
               and not self._onarilabilir(a)]
        bozuk = [a for a, v in self.nesneler.items()
                 if v.get("bozuk") and (self.kok / a).exists()
                 and a not in olu]
        hepsi = [a for a in self.nesneler if (self.kok / a).exists()]
        aday = olu or bozuk or hepsi
        if not aday:
            return {"obs": "silinecek yok", "kind": "atolye", "bos": 1}
        ad = random.choice(aday)
        try:
            (self.kok / ad).unlink()
        except OSError:
            pass
        self._yedek_sil(ad)      # silinen nesnenin yedeği de gider
        self.nesneler.pop(ad, None)
        self._durum_kaydet()
        return {"obs": "silindi: %s (kota açıldı)" % ad, "kind": "atolye"}

    # ---------- Sahne 2: araç-kompozisyonu ----------

    def kur(self):
        """Kompozisyon: iki nesneyi birleştir → araç.

        Malzeme ekonomisi (tablo değil, cebir): kuvvet = toplam boyut
        (bayt/64, en az 1), seviye = en derin parça + 1 (araçtan araç
        olur). İçerik birikir (parça içerikleri tek dosyada korunur).
        Kota doluysa silmek yerine birleştir — kıtlık yaratıcı olur.
        Malzeme dürüstlüğü: parça içerikleri TAM olarak korunur (kesme
        yok); kuvvet = GERÇEK korunan bayt/64 — kaybolan malzeme
        sayılmaz, "bedava kuvvet" doğmaz.
        """
        mevcut = [a for a in self.nesneler if (self.kok / a).exists()]
        if len(mevcut) < 2:
            return {"obs": "birleştirilecek en az 2 nesne",
                    "kind": "atolye", "bos": 1}
        # en büyük iki parçayı al (malzeme verimliliği — sonuç odaklı)
        iki = sorted(mevcut, key=lambda a: (self.kok / a).stat().st_size)[-2:]
        pa, pb = self.kok / iki[0], self.kok / iki[1]
        # Parça içeriği: bozuk parça diskte "?" olmuştur → YEDEKTEN
        # okunur (yoksa araca "?" bulaşır, malzeme kalıcı olarak çöpe
        # gider ve araç da bir daha onarılamaz).
        parcalar = []
        for a in iki:
            yed = self._yedekten_yukle(a)
            if yed is not None:
                parcalar.append(yed)
                continue
            try:
                parcalar.append((self.kok / a).read_text(encoding="utf-8"))
            except OSError:
                parcalar.append("")
        icerik = "".join(parcalar)
        # malzeme dürüstlüğü: içerik KESİLMEZ (docstring'in sözü), kuvvet
        # GERÇEK korunan bayttan sayılır — kesilip sayılsaydı ertelenmiş
        # malzeme (bedava kuvvet) doğardı.
        boyut = len(icerik.encode("utf-8"))
        kuvvet = max(1, boyut // 64)
        seviye = 1 + max(self.nesneler[a].get("seviye", 0) for a in iki)
        ad = "arac_v%d_%s" % (seviye, "".join(
            random.choice("abcdef0123456789") for _ in range(4)))
        p = self._safe(ad)
        if p is None or p.exists():
            return {"obs": "atölye ad güvenliği", "kind": "atolye", "bos": 1}
        # önce parçaları kaldır, sonra aracı yaz (tek süreç: yarış yok)
        for a in iki:
            try:
                (self.kok / a).unlink()
            except OSError:
                pass
            self.nesneler.pop(a, None)
        p.write_text(icerik, encoding="utf-8")
        # parça yedekleri araca taşınır: araç da bozulabilir, onarımın
        # kaynağı olmazsa aracın malzemesi kalıcı olarak çöpe gider.
        # Yedek = aracın TAM içeriği (parça yedekleri değil: onarım
        # aracın bütününü geri yükler).
        yedek_ad = self._yedek_yolu(ad)
        if yedek_ad is not None:
            try:
                yedek_ad.write_text(icerik, encoding="utf-8")
            except OSError:
                pass
            for a in iki:
                self._yedek_sil(a)
        self.nesneler[ad] = {"son_bakim": self.tik, "bozuk": False,
                             "tur": "arac", "kuvvet": kuvvet,
                             "seviye": seviye}
        self._durum_kaydet()
        return {"obs": "kuruldu: %s (seviye %d, kuvvet %d; %s + %s)"
                % (ad, seviye, kuvvet, iki[0], iki[1]),
                "kind": "atolye", "novel": 0}

    def guc(self):
        """Aracı kullan: kuvvet kadar bozuk nesneyi TEK eylemde onar.

        Araç yorulur (kuvvet −onarım sayısı); kuvveti biten araç tükenir
        (silinir) — araç da bir kaynaktır, sonsuz değil. Asıl kazanç
        enerji tasarrufu (N bak yerine 1 eylem), ödül değil: merak hâlâ
        sürprizden, tavanlı.
        """
        araclar = [a for a, v in self.nesneler.items()
                   if (self.kok / a).exists() and v.get("tur") == "arac"
                   and v.get("kuvvet", 0) > 0 and not v.get("bozuk")]
        if not araclar:
            return {"obs": "kullanılacak araç yok (önce kur)",
                    "kind": "atolye", "bos": 1}
        # Onarım hedefi kuralı bak ile aynı: var olan HER bozuk nesne
        # (bozuk araç zaten araclar listesinde değil — eski "a not in
        # araclar" koşulu ölü koddu, asıl niyet buydu).
        bozuklar = [a for a, v in self.nesneler.items()
                    if (self.kok / a).exists() and v.get("bozuk")
                    and self._onarilabilir(a)]
        if not bozuklar:
            return {"obs": "onarılacak bozuk yok", "kind": "atolye",
                    "bos": 1}
        ad = max(araclar, key=lambda a: self.nesneler[a]["kuvvet"])
        arac = self.nesneler[ad]
        adet = min(arac["kuvvet"], len(bozuklar))
        basarili = 0
        bayrak = 0
        for b in bozuklar[:adet]:
            # gerçek onarım: orijinal içerik YEDEKTEN (diskteki "?"
            # değil). Kurtarılamayan nesne atlanır (uydurma onarım yok)
            # — araç kuvveti de harcanmaz (dürüstlük: kuvvet = yapılan
            # GERÇEK onarım).
            sonuc = self._onar(b)
            if sonuc is None:
                continue
            self.nesneler[b]["bozuk"] = False
            self.nesneler[b]["son_bakim"] = self.tik
            if sonuc == "gercek":
                basarili += 1
            else:
                bayrak += 1
        if not basarili and not bayrak:
            # hiçbir onarım tutmadı → araç yorulmadı, iş de yapılmadı
            # (no-op: sayıma girmez) — bak ile aynı dürüstlük kapısı
            return {"obs": "araç %s: onarım tutmadı" % ad,
                    "kind": "atolye", "novel": 0, "bos": 1}
        # kuvvet = GERÇEKTEN yapılan onarım (docstring'in sözü: "kuvvet
        # −onarım sayısı" — tutmayan deneme aracı yormaz)
        arac["kuvvet"] -= basarili
        arac["son_bakim"] = self.tik
        tukendi = arac["kuvvet"] <= 0
        if tukendi:  # araç tükendi: hem dosya hem kayıt gider
            try:
                (self.kok / ad).unlink()
            except OSError:
                pass
            self._yedek_sil(ad)     # tükenen aracın yedeği de gider
            del self.nesneler[ad]
        self._durum_kaydet()
        return {"obs": "araç %s: %d onarıldı%s" %
                (ad, basarili, " (araç tükendi)" if tukendi else ""),
                "kind": "atolye", "novel": 0}
