"""paket.py — Debian beyini: "bu dosya ne, ne işe yarar?"

Kaynak: dpkg'ın KENDİ veritabanı (dış etiket yok — Debian zaten
kendini etiketlemiş):

    /var/lib/dpkg/status       → paket → bölüm, açıklama, öncelik
    /var/lib/dpkg/info/*.list  → paket → sahip olduğu dosyalar

İki organ:

  1) BİLGİ TABANI (sorgulanabilir, kesin): `/usr/bin/grep` hangi
     paketten, `grep` ne işe yarar — dpkg'nin kendi cevabı.
  2) ÖĞRENEN MODEL (genelleme): bilinmeyen dosya adı → en olası paket
     (ad-ayrık hold-out ile doğrulanır). Komut kaslarının temeli.

Saf stdlib; kayıt: zeka/paket.json (dizin/risk ailesi Laplace modeli).
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

DPKT_STATUS = "/var/lib/dpkg/status"
DPKT_INFO = "/var/lib/dpkg/info"

# Model yalnızca OPERATÖR alanını öğrenir: komut satırında çalıştırılan
# dosyalar (/usr/bin, /usr/sbin). 400K dosyalık tam harita yerine ~5K
# komut — öğrenme sorunu burada anlamlı ("bu adayı çalıştırsam ne olur?").
KOMUT_ALANLARI = ("/usr/bin/", "/usr/sbin/", "/bin/", "/sbin/")


def _alanli(yol):
    return any(yol == a[:-1] or yol.startswith(a) for a in KOMUT_ALANLARI)


def durum_oku(yol=DPKT_STATUS):
    """dpkg status → {paket: {bolum, aciklama, oncelik}}."""
    paketler = {}
    ad = None
    kayit = {}
    try:
        f = open(yol, encoding="utf-8", errors="replace")
    except OSError:
        return paketler
    with f:
        for satir in f:
            if not satir.strip():
                if ad:
                    paketler[ad] = kayit
                ad, kayit = None, {}
                continue
            if not satir.startswith(" "):
                if satir.startswith("Package: "):
                    ad = satir[9:].strip()
                elif satir.startswith("Section: "):
                    kayit["bolum"] = satir[9:].strip()
                elif satir.startswith("Priority: "):
                    kayit["oncelik"] = satir[10:].strip()
                elif satir.startswith("Description: "):
                    kayit["aciklama"] = satir[13:].strip()
    if ad:
        paketler[ad] = kayit
    return paketler


def komut_dosyalari(kok=DPKT_INFO):
    """Komut alanındaki dosyalar → [(dosya_yolu, paket)] (.list)."""
    esleme = []
    try:
        listeler = sorted(Path(kok).glob("*.list"))
    except OSError:
        return esleme
    for lp in listeler:
        paket = lp.name[:-len(".list")]
        try:
            with open(lp, encoding="utf-8", errors="replace") as f:
                for satir in f:
                    yol = satir.strip()
                    if yol and _alanli(yol):
                        esleme.append((yol, paket))
        except OSError:
            continue
    return esleme


def komut_adi(yol):
    return str(yol).strip().rsplit("/", 1)[-1]


def ozellikler(ad):
    """Komut adı → özellikler (dizin/risk ailesi + kelime parçalama)."""
    ad = str(ad)
    feats = ["ad=%s" % ad.lower()]
    feats.append("onek=%s" % ad[:3].lower())
    feats.append("ad%d" % (len(ad) // 3))
    feats.append("rakam" if any(c.isdigit() for c in ad) else "harfsiz")
    for ayirac in ("-", "_", "."):
        if ayirac in ad:
            for kel in ad.split(ayirac):
                if kel:
                    feats.append("kel=%s" % kel.lower())
            break
    return feats


class Paket:
    """Dosya adı → paket frekans modeli (Laplace; risk/dizin ailesi)."""

    def __init__(self, agirlik=0.9, oncelik=1.0):
        self.agirlik = agirlik
        self.oncelik = oncelik
        self.sayac = {}     # (ozellik, paket) -> adet
        self.toplam = {}    # paket -> adet
        self.ornek = 0
        # bilgi tabanı (kesin): ad → {paket, bolum, aciklama}
        self.bilgi = {}
        self.paket_bilgi = {}   # paket → {bolum, aciklama}

    def ogren(self, feats, paket):
        self.toplam[paket] = self.toplam.get(paket, 0) + 1
        for f in feats:
            self.sayac[(f, paket)] = self.sayac.get((f, paket), 0) + 1
        self.ornek += 1

    def _log(self, feats, paket):
        if not self.ornek:
            return -1e9
        n = self.toplam.get(paket, 0)
        if n <= 0:
            return -1e9
        import math
        toplam = 0.0
        for f in feats:
            toplam += (self.sayac.get((f, paket), 0) + 1) / (n + 2)
        return self.oncelik * math.log(n / self.ornek) + toplam * self.agirlik

    def skorlar(self, feats):
        return {p: self._log(feats, p) for p in self.toplam}

    def tahmin(self, feats):
        s = self.skorlar(feats)
        if not s:
            return None, s
        return max(s, key=s.get), s

    def sirala(self, feats, n=None):
        s = self.skorlar(feats)
        kira = [p for p, _ in sorted(s.items(), key=lambda kv: -kv[1])]
        return kira[:n] if n else kira

    # ---------- bilgi tabanı sorgusu ----------

    def bilgi_ekle(self, ad, paket, bolum="", aciklama=""):
        self.bilgi[komut_adi(ad)] = {"paket": paket, "bolum": bolum,
                                     "aciklama": aciklama}
        self.paket_bilgi[paket] = {"bolum": bolum, "aciklama": aciklama}

    def nedir(self, ad):
        """Komut adı → (kaynak, bilgi). Kaynak: 'kesin' | 'tahmin' | None.

        Önce kesin dpkg haritası; yoksa öğrenilen modelin tahmini —
        kaynak açıkça 'tahmin' (karıştırma yok, dürüstlük şart).
        """
        ad = komut_adi(ad)
        b = self.bilgi.get(ad)
        if b:
            return "kesin", b
        tah, _ = self.tahmin(ozellikler(ad))
        if tah:
            pb = self.paket_bilgi.get(tah, {})
            return "tahmin", {"paket": tah, "bolum": pb.get("bolum", ""),
                              "aciklama": pb.get("aciklama", "")}
        return None, {}

    # ---------- kalıcı kayıt ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("paket.json"))
        tmp = path.with_name(path.name + ".tmp")
        veri = {"surum": 1, "agirlik": self.agirlik, "oncelik": self.oncelik,
                "ornek": self.ornek, "toplam": self.toplam,
                "sayac": {"%s\t%s" % k: v for k, v in self.sayac.items()},
                "bilgi": self.bilgi, "paket_bilgi": self.paket_bilgi}
        tmp.write_text(json.dumps(veri, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))
        return True

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("paket.json"))
        if not path.exists():
            return False
        try:
            veri = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.agirlik = float(veri.get("agirlik", self.agirlik))
        self.oncelik = float(veri.get("oncelik", self.oncelik))
        self.ornek = int(veri.get("ornek", 0))
        self.toplam = {k: int(v) for k, v in
                       veri.get("toplam", {}).items()}
        self.sayac = {tuple(k.split("\t", 1)): int(v)
                      for k, v in veri.get("sayac", {}).items()}
        self.bilgi = veri.get("bilgi", {})
        self.paket_bilgi = veri.get("paket_bilgi", {})
        return True

