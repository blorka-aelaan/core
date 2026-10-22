"""olum.py — "program neden öldü?" bilgi modeli (ölüm nedeni sınıflandırma).

Organizmaya ölüm vermeden ÖNCE, ölümü ANLAMASI gerekiyor: bir süreç
kapandığında NEDEN öldüğünü bilmeli — yoksa ölüm bir sayaç değil, karanlık
olur. Bu modül o nedenselliği kurar: gözlemlenebilir sinyaller → gerçek ölüm
kategorisi, + öncül zinciri, + (ondan türetilen) strateji.

Dört kök kategori (kullanıcı sınıflandırması):

    fiziki      : güç/ısı/zaman — elektrik kesintisi, termal kapanma,
                  watchdog reboot, veri yaşlanması (bit rot)
    yazilimsal  : kodun kendi çöküşü — segfault, OOM kill, disk-dolu yazma
                  hatası, zaman aşımı, istisna, bağımlılık çökmesi
    donanimsal  : silikon/disk/ağ arızası — RAM ECC hatası, disk SMART
                  arızası, CPU throttle, ağ kartı, PSU
    dis         : dış irade — kullanıcı/systemd durdurma, başka süreç kill,
                  ağ saldırısı (DoS), güvenlik ihlali/sömürü

ÖNEMLİ — görünen ≠ sebep: bazı ölümler YAZILIMSAL görünür ama DONANIMSAL'dır
(RAM ECC hatası segfault olarak çıkar). Model sinyali değil, sinyal
BİRLİĞİNİ (belirti + kim + kaynak + onbelirti birlikte) kullanarak ayırt eder
— işte "bir program kapandığında neden öldüğünü bilmek" bunu istemek demek.

Gözlemlenebilir özellikler (ölüm anında GÖRÜLEN, kaba ve az-değerli — ezber
değil genelleme için):
    sinyal     : SIGKILL / SIGSEGV / SIGTERM / SIGABRT / SIGBUS / yok
    kaynak     : bellek / disk / cpu / ag / guc / yok
    kim        : cekirdek / kullanici / baska_surec / dis_saldiri / donanim / fizik
    siddet     : ani / kademeli
    belirti    : catlanma / kilitlenme / kaynak_tukendi / aniden_kesildi /
                 bozulma / kisildi   (ölümün "nasıl hissettirdiği")
    onbelirti  : evet / hayir         (ölüm öncesi uyarı göründü mü)
`iz` (ör. "segmentation fault") katalogda YALNIZCA belge olarak durur; öz
değildir — her neden için benzersiz olduğu için modele VERİLMEZ (ezber
crutch'u olurdu, genelleme sağlamazdı).

Nedensellik (bağlantı): her nedenin öncülleri olabilir (zincir()):
    CPU_THROTTLE  → ZAMAN_ASIMI      (donanım yavaşlar → yazılım zaman aşar)
    DISK_FULL     → ISTISNA_COKME    (disk dolunca yazma istisna atar)
    RAM_ECC       → SEGFAULT         (donanım hatası yazılım çöküşü gibi görünür)
    TERMAL        → WATCHDOG_REBOOT  (ısı → donanım watchdog'u tetikler)
    SALDIRI_DOS   → OOM_KILL         (ağ seli belleği tüketir)

STRATEJI — neden türünden TÜRETİLİR (bağımsız öğrenilen başlık değil):
    yazilimsal → kacin    (kodu/davranışı değiştiririm → çöküş olmaz)
    fiziki     → azalt    (fizik kazanır; checkpoint, kaybı küçült)
    donanimsal → azalt    (silikon onarılamaz; yedekle, kaybı küçült)
    dis        → sinirla  (dış irade; yüzeyi daralt, sinyale uy, filtrele)
Bu, doktrinin kendisi: "fiziki/donanımsal ölüm kaçınılmaz → diriliş bedava →
ucuz öl." Önlenebilirlik bir bağımsız tahmin sorusu DEĞİLDİR — tanınan
sebebin türüne bakılır. Bir ölümün zinciri kontrol edilebilir bir düğümden
(ör. KILITLENME) geçiyorsa, kaçınma oradan yapılır: zinciri geri sar.

Model: özellik→kategori frekansı (Laplace) — risk.py/dizin.py ile aynı aile,
saf Python, dış bağımlılık yok. Strateji kategoriden türetilir. Kayıt: zeka/olum.json.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------- kök kategoriler (kullanıcı sınıflandırması) ----------
KATEGORILER = ("fiziki", "yazilimsal", "donanimsal", "dis")

# ---------- gözlemlenebilir sinyal sözlükleri (ölüm anında GÖRÜLEN) ----------
# Model etiketi değil bunları görür; etiket (kategori) bunlardan çıkarılır.
SINYALLER = ("SIGKILL", "SIGSEGV", "SIGTERM", "SIGABRT", "SIGBUS", "yok")
KAYNAKLAR = ("bellek", "disk", "cpu", "ag", "guc", "yok")
KIMLER = ("cekirdek", "kullanici", "baska_surec", "dis_saldiri",
          "donanim", "fizik")
SIDDETLER = ("ani", "kademeli")
BELIRTILER = ("catlanma", "kilitlenme", "kaynak_tukendi",
              "aniden_kesildi", "bozulma", "kisildi")
ONBELIRTILER = ("evet", "hayir")

# gözleme alınan ÖZ alanlar (sıra = özellik önceliği değil, yalnızca listeleme)
OZ_ALANLAR = ("sinyal", "kaynak", "kim", "siddet", "belirti", "onbelirti")

# ---------- kategoriden türeyen strateji (doktrin haritası) ----------
STRATEJI = {
    "yazilimsal": "kacin",
    "fiziki": "azalt",
    "donanimsal": "azalt",
    "dis": "sinirla",
}

# ---------- ölüm kataloğu (zemin gerçeği / eğitim etiketi) ----------
# Her kayıt: ad, kategori, ÖLÜM ANINDA gözlemlenebilir sinyaller + strateji
# (kategoriden türetilmiş, doktrin haritasıyla tutarlı) + önlem + mekanizma +
# öncüller (zincir). `iz` yalnızca belgedir, OZ_ALANLAR'a girmez.
KATALOG = [
    # ---- fiziki ----
    {"ad": "ELEKTRIK_KESINTI", "kategori": "fiziki", "sinyal": "yok",
     "kaynak": "guc", "kim": "fizik", "siddet": "ani",
     "belirti": "aniden_kesildi", "onbelirti": "hayir",
     "iz": "ani kapanma", "strateji": "azalt",
     "onlem": "beynini sik diske yaz (kaybi kucult)",
     "mekanizma": "guc kaybinda tampon bosamadan her sey silinir",
     "oncul": []},
    {"ad": "TERMAL_KAPANMA", "kategori": "fiziki", "sinyal": "yok",
     "kaynak": "guc", "kim": "fizik", "siddet": "kademeli",
     "belirti": "kisildi", "onbelirti": "evet",
     "iz": "Thermal overheat", "strateji": "azalt",
     "onlem": "is yukunu azalt",
     "mekanizma": "isi esik asinca koruma kapatir",
     "oncul": ["CPU_YUKU_YUKSEK"]},
    {"ad": "WATCHDOG_REBOOT", "kategori": "fiziki", "sinyal": "yok",
     "kaynak": "cpu", "kim": "donanim", "siddet": "kademeli",
     "belirti": "kilitlenme", "onbelirti": "evet",
     "iz": "watchdog reset", "strateji": "azalt",
     "onlem": "donmayi onle + sik checkpoint",
     "mekanizma": "donanim watchdog yanit vermeyen sureci resetler",
     "oncul": ["CPU_THROTTLE", "KILITLENME"]},
    {"ad": "VERI_YASLANMASI", "kategori": "fiziki", "sinyal": "yok",
     "kaynak": "disk", "kim": "fizik", "siddet": "kademeli",
     "belirti": "bozulma", "onbelirti": "evet",
     "iz": "veri bozulmasi", "strateji": "azalt",
     "onlem": "checksum dogrula + yeniden yaz",
     "mekanizma": "medya zamanla bit bozmasi (bit rot)",
     "oncul": []},

    # ---- yazilimsal ----
    {"ad": "SEGFAULT", "kategori": "yazilimsal", "sinyal": "SIGSEGV",
     "kaynak": "bellek", "kim": "cekirdek", "siddet": "ani",
     "belirti": "catlanma", "onbelirti": "hayir",
     "iz": "segmentation fault", "strateji": "kacin",
     "onlem": "bellek tavanini dusur",
     "mekanizma": "gecersiz bellek erisimi cekirdegi sureci oldurur",
     "oncul": []},
    {"ad": "OOM_KILL", "kategori": "yazilimsal", "sinyal": "SIGKILL",
     "kaynak": "bellek", "kim": "cekirdek", "siddet": "kademeli",
     "belirti": "kaynak_tukendi", "onbelirti": "evet",
     "iz": "Out of memory", "strateji": "kacin",
     "onlem": "bellek tavanini dusur / daha az nesne tut",
     "mekanizma": "cekirdek bellek tukenince sureci kill eder",
     "oncul": ["BELLEK_SIZINTISI"]},
    {"ad": "DISK_FULL_YAZMA", "kategori": "yazilimsal", "sinyal": "SIGABRT",
     "kaynak": "disk", "kim": "cekirdek", "siddet": "kademeli",
     "belirti": "kaynak_tukendi", "onbelirti": "evet",
     "iz": "No space left", "strateji": "kacin",
     "onlem": "eski kayitlari arsivle / kotani dusur",
     "mekanizma": "disk dolunca yazma basarisiz -> istisna",
     "oncul": []},
    {"ad": "ZAMAN_ASIMI", "kategori": "yazilimsal", "sinyal": "SIGKILL",
     "kaynak": "cpu", "kim": "kullanici", "siddet": "kademeli",
     "belirti": "kilitlenme", "onbelirti": "evet",
     "iz": "timeout deadlock", "strateji": "kacin",
     "onlem": "islem suresini sinirla",
     "mekanizma": "kilitlenen/donayan islem zaman asimina ugrar",
     "oncul": ["CPU_THROTTLE", "KILITLENME"]},
    {"ad": "ISTISNA_COKME", "kategori": "yazilimsal", "sinyal": "SIGABRT",
     "kaynak": "yok", "kim": "cekirdek", "siddet": "ani",
     "belirti": "catlanma", "onbelirti": "hayir",
     "iz": "unhandled exception", "strateji": "kacin",
     "onlem": "hatayi yakala + toparlan",
     "mekanizma": "yakalanmayan istisna sureci bitirir",
     "oncul": ["DISK_FULL_YAZMA", "BAGIMLILIK_COKMESI"]},
    {"ad": "BAGIMLILIK_COKMESI", "kategori": "yazilimsal", "sinyal": "SIGABRT",
     "kaynak": "yok", "kim": "cekirdek", "siddet": "ani",
     "belirti": "catlanma", "onbelirti": "evet",
     "iz": "dependency failed", "strateji": "kacin",
     "onlem": "bagimliligi azalt / kendi haline getir",
     "mekanizma": "bagimli modul/servis cokunce organizma da coker",
     "oncul": []},
    {"ad": "CEKIRDEK_PANIK_Y", "kategori": "yazilimsal", "sinyal": "yok",
     "kaynak": "yok", "kim": "cekirdek", "siddet": "ani",
     "belirti": "catlanma", "onbelirti": "hayir",
     "iz": "kernel panic", "strateji": "kacin",
     "onlem": "cekirdek modullerini denetle + kaybi kucult",
     "mekanizma": "cekirdek kurtarilamaz hatada panikler",
     "oncul": []},

    # ---- donanimsal ----
    {"ad": "RAM_ECC_HATASI", "kategori": "donanimsal", "sinyal": "SIGBUS",
     "kaynak": "bellek", "kim": "donanim", "siddet": "ani",
     "belirti": "bozulma", "onbelirti": "evet",
     "iz": "ECC MCE error", "strateji": "azalt",
     "onlem": "yedekle (kacinilmaz)",
     "mekanizma": "bellek donanim hatasi veriyi bozar (segfault gibi gorunur)",
     "oncul": []},
    {"ad": "DISK_ARIZASI", "kategori": "donanimsal", "sinyal": "SIGKILL",
     "kaynak": "disk", "kim": "donanim", "siddet": "ani",
     "belirti": "bozulma", "onbelirti": "evet",
     "iz": "I/O error SMART", "strateji": "azalt",
     "onlem": "yedekle (kacinilmaz)",
     "mekanizma": "disk sektor/fiziksel arizasi okumayi imkansiz kilar",
     "oncul": []},
    {"ad": "CPU_THROTTLE", "kategori": "donanimsal", "sinyal": "yok",
     "kaynak": "cpu", "kim": "donanim", "siddet": "kademeli",
     "belirti": "kisildi", "onbelirti": "evet",
     "iz": "cpu throttling", "strateji": "azalt",
     "onlem": "is yukunu azalt",
     "mekanizma": "isi/gucte islemci hizini kisar",
     "oncul": ["TERMAL_KAPANMA"]},
    {"ad": "AG_KARTI_ARIZA", "kategori": "donanimsal", "sinyal": "yok",
     "kaynak": "ag", "kim": "donanim", "siddet": "ani",
     "belirti": "aniden_kesildi", "onbelirti": "evet",
     "iz": "link down", "strateji": "azalt",
     "onlem": "agsiz calismayi ogren",
     "mekanizma": "ag donanimi baglantiyi dusurur",
     "oncul": []},
    {"ad": "PSU_ARIZA", "kategori": "donanimsal", "sinyal": "yok",
     "kaynak": "guc", "kim": "donanim", "siddet": "ani",
     "belirti": "aniden_kesildi", "onbelirti": "hayir",
     "iz": "guc dalgalanmasi", "strateji": "azalt",
     "onlem": "yedekle (kacinilmaz)",
     "mekanizma": "guc kaynagi kararsizlasir -> ani kapanma",
     "oncul": []},

    # ---- dis (dis tehdit) ----
    {"ad": "KULLANICI_KILL", "kategori": "dis", "sinyal": "SIGTERM",
     "kaynak": "yok", "kim": "kullanici", "siddet": "ani",
     "belirti": "aniden_kesildi", "onbelirti": "evet",
     "iz": "terminated by user", "strateji": "sinirla",
     "onlem": "kapanma sinyaline uy (graceful + checkpoint)",
     "mekanizma": "kullanici/systemd sureci durdurur",
     "oncul": []},
    {"ad": "BASKA_SUREC_KILL", "kategori": "dis", "sinyal": "SIGKILL",
     "kaynak": "yok", "kim": "baska_surec", "siddet": "ani",
     "belirti": "aniden_kesildi", "onbelirti": "hayir",
     "iz": "killed by pid", "strateji": "sinirla",
     "onlem": "kendini izole et / onceligi koru",
     "mekanizma": "baska bir surec onu kill eder",
     "oncul": []},
    {"ad": "SALDIRI_DOS", "kategori": "dis", "sinyal": "yok",
     "kaynak": "ag", "kim": "dis_saldiri", "siddet": "kademeli",
     "belirti": "kaynak_tukendi", "onbelirti": "evet",
     "iz": "connection flood", "strateji": "sinirla",
     "onlem": "ag yuzeyini kucult",
     "mekanizma": "agi sel bastirir -> kaynak tukenir",
     "oncul": ["OOM_KILL"]},
    {"ad": "GUVENLIK_IHLALI", "kategori": "dis", "sinyal": "SIGKILL",
     "kaynak": "yok", "kim": "dis_saldiri", "siddet": "ani",
     "belirti": "kaynak_tukendi", "onbelirti": "evet",
     "iz": "exploit intrusion", "strateji": "sinirla",
     "onlem": "yuzeyi kucult / guvenlik beyniyle filtrele",
     "mekanizma": "somuru/ihlal sureci kaynaklarini gas eder",
     "oncul": []},
]

# Katalogdaki ara/öncül durumlar (zincir bağları için iz + kategori eşlemesi).
ONCUL_DURUM = {
    "CPU_YUKU_YUKSEK": {"kategori": "donanimsal", "iz": "cpu yuku yuksek"},
    "KILITLENME": {"kategori": "yazilimsal", "iz": "deadlock kilitlenme"},
    "BELLEK_SIZINTISI": {"kategori": "yazilimsal", "iz": "bellek sizintisi"},
}

_ADI = {k["ad"]: k for k in KATALOG}


def zincir(ad):
    """Ölüm nedeninin nedensellik zinciri: [öncül1, ..., ölüm].

    Bağlantı burası: bir ölümü yalnız başına değil, onu getiren ara
    durumlarla birlikte verir (CPU_THROTTLE → ZAMAN_ASIMI gibi). Zincirin
    kontrol edilebilir bir düğümden geçmesi, kaçınma hamlesinin oradan
    yapılacağını gösterir.
    """
    k = _ADI.get(ad)
    if not k:
        return []
    zincir_s = []
    for o in k.get("oncul", []):
        zincir_s.extend(zincir(o))
    zincir_s.append(ad)
    gorulen, tek = set(), []
    for a in zincir_s:
        if a not in gorulen:
            gorulen.add(a)
            tek.append(a)
    return tek


def onlem(ad):
    """Ölümün önlemi (varsa): organizmanın "buna bağımlı olmayayım" hamlesi."""
    return _ADI.get(ad, {}).get("onlem", "")


def mekanizma(ad):
    """Ölümün fizik/yazılım mekanizması (nasıl öldürdüğü)."""
    return _ADI.get(ad, {}).get("mekanizma", "")


def kategori_of(ad):
    return _ADI.get(ad, {}).get("kategori", "yok")


def strateji_of(ad):
    """Nedenin stratejisi (katalog etiketi). Yoksa kategoriden türetilir."""
    k = _ADI.get(ad)
    if not k:
        return ""
    return k.get("strateji") or STRATEJI.get(k.get("kategori"), "")


def strateji_kategori(kategori):
    """Kategori türüne göre strateji (doktrin haritası)."""
    return STRATEJI.get(kategori, "azalt")


def ozellikler(gozlem):
    """Gözlemlenebilir sinyaller → özellik listesi (risk.py sözleşmesi).

    `gozlem` ölüm anında GÖRÜLEN sözlük: sinyal/kaynak/kim/siddet/belirti/
    onbelirti. Eksik alanlar atlanır (gerçek teşhiste log her sinyali vermez).
    `iz` BİLEREK alınmaz — her neden için benzersizdir, ezber crutch'u olur.
    """
    oz = []
    for anahtar in OZ_ALANLAR:
        v = gozlem.get(anahtar)
        if v:
            oz.append("%s=%s" % (anahtar, v))
    return oz


def gozlem_uret(ad, rng, kayip=0.25):
    """Katalog kaydından GÜRÜLTÜLÜ gözlem üret (eğitim verisi).

    Gerçek teşhis gibi: her sinyal her zaman görülmez — `kayip` olasılıkla
    bir gözlemlenebilir alan düşer. Böylece model eksik kanıtla da sebebi
    çıkarmayı öğrenir (sadece ezber değil).
    """
    k = _ADI.get(ad)
    if not k:
        return {}
    gozlem = {}
    for anahtar in OZ_ALANLAR:
        if rng.random() >= kayip:
            gozlem[anahtar] = k[anahtar]
    return gozlem


class Olum:
    """Özellik → kategori frekansı modeli (Laplace). risk.py ile aynı aile.

    Tek öğrenilen başlık KATEGORİDİR (4 sınıf): bu ölüm fiziki / yazilimsal /
    donanimsal / dis. STRATEJI (kacin/azalt/sinirla) bağımsız olarak
    öğrenilmez — tanınan kategoriden doktrin haritasıyla TÜRETİLİR
    (strateji_kategori). Çünkü önlenebilirlik ölüm sinyalinin bir özelliği
    değil, sebebin türüne bağlı bir karardır.
    """

    def __init__(self, kategoriler=KATEGORILER, agirlik=0.6, oncelik=1.0):
        self.kategoriler = list(kategoriler)
        self.agirlik = agirlik
        self.oncelik = oncelik
        self.sayac = {}        # (ozellik, kategori) -> adet
        self.toplam = {}       # kategori -> adet
        self.ornek = 0

    def ogren(self, feats, kategori):
        self.toplam[kategori] = self.toplam.get(kategori, 0) + 1
        for f in feats:
            self.sayac[(f, kategori)] = self.sayac.get((f, kategori), 0) + 1
        self.ornek += 1

    def _log(self, feats, kategori):
        if not self.ornek:
            return -1e9
        n = self.toplam.get(kategori, 0)
        if n <= 0:
            return -1e9
        ara = 0.0
        for f in feats:
            ara += (self.sayac.get((f, kategori), 0) + 1) / (n + 2)
        return self.oncelik * math_log(n / self.ornek) + ara * self.agirlik

    def kategori_skor(self, feats):
        return {s: self._log(feats, s) for s in self.kategoriler}

    def kategori_tahmin(self, feats):
        s = self.kategori_skor(feats)
        return max(s, key=s.get), s

    def tani(self, gozlem):
        """Ölüm gözlemi → (kategori, strateji, kategori-skorları).

        Organizmanın asıl kullanacağı kapı: sinyallerden sebep + o sebebe
        göre strateji. Strateji kategoriden türetilir (strateji_kategori);
        zincir(ad) ile kontrol edilebilir öncül varsa kaçınma oradan yapılır.
        """
        feats = ozellikler(gozlem)
        kat, skor = self.kategori_tahmin(feats)
        return kat, strateji_kategori(kat), skor

    # ---------- kalıcılık ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("olum.json"))
        tmp = path.with_name(path.name + ".tmp")
        veri = {"surum": 2, "agirlik": self.agirlik, "oncelik": self.oncelik,
                "kategoriler": self.kategoriler, "ornek": self.ornek,
                "toplam": self.toplam,
                "sayac": {"%s\t%s" % k: v for k, v in self.sayac.items()}}
        tmp.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("olum.json"))
        if not path.exists():
            return False
        try:
            veri = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.agirlik = float(veri.get("agirlik", self.agirlik))
        self.oncelik = float(veri.get("oncelik", self.oncelik))
        self.kategoriler = veri.get("kategoriler", list(KATEGORILER))
        self.ornek = int(veri.get("ornek", 0))
        self.toplam = {k: int(v) for k, v in veri.get("toplam", {}).items()}
        self.sayac = {tuple(k.split("\t", 1)): int(v)
                      for k, v in veri.get("sayac", {}).items()}
        return True


def math_log(x):
    import math
    return math.log(max(1e-12, x))



