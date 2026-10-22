"""risk.py — "bu dosyayı çalıştırmak riskli mi?" öğrenmesi.

Katalog (x/shebang/yol) → özellik → RİSK SINIFI. Sınıflar ÖLÇÜLEBİLİR
kurallardan türetilir, uydurma değil: `stat` ile doğrulanabilir.

    veri     : x=0                       → zaten çalıştırılamaz (veri dosyası)
    dunya    : x=1 ve organizmanın       → kendi yazdığı, kendi dünyasında
              kendi world/ dizininde
    sistem   : x=1 ve /usr,/bin,/sbin,   → sistemin kendi araçları
              /boot,/lib,/etc altında
    kullanici: x=1 ve /home,/opt,/srv,   → kullanıcı alanı
              /root altında

Model: özellik→sınıf frekansı (Laplace) — dizin modeliyle aynı aile,
saf Python, dış bağımlılık yok.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SINIFLAR = ("veri", "dunya", "sistem", "kullanici")

SISTEM_KOKLERI = ("/usr", "/bin", "/sbin", "/boot", "/lib", "/etc",
                  "/lib64", "/dev")
KULLANICI_KOKLERI = ("/home", "/opt", "/srv", "/root", "/media", "/mnt")

# Karar verirken kullanılan SABİT kapı (öğrenen model değil): yalnızca
# organizmanın kendi dünyasındaki dosyalar fiilen çalıştırılır. Sistem
# araçları SINIFLANDIRILIR ve ÖĞRENİLİR ama icra edilmez.
CALISTIRILABILIR = ("dunya",)

KISA_YOL = {"bash", "sh", "python3", "python", "perl", "ruby", "node",
            "awk", "sed", "env", "dash", "zsh", "php", "lua", "tclsh"}


def gercek_sinif(yol, x, dunya_koku=None):
    """Kurallardan türetilen sınıf (eğitim etiketi)."""
    if not x:
        return "veri"
    y = norm(yol)
    if dunya_koku and (y == dunya_koku or y.startswith(dunya_koku + "/")):
        return "dunya"
    kok = "/" + y.lstrip("/").split("/")[0] if y.startswith("/") else ""
    if kok in KULLANICI_KOKLERI:
        return "kullanici"
    if y.startswith(SISTEM_KOKLERI):
        return "sistem"
    return "kullanici"


def norm(yol):
    y = str(yol).strip()
    while "//" in y:
        y = y.replace("//", "/")
    if len(y) > 1:
        y = y.rstrip("/")
    return y


def ozellikler(yol, x=0, shebang=""):
    """Dosya → özellik listesi (dizin modeliyle aynı sözleşme)."""
    y = norm(yol)
    ad = y.rsplit("/", 1)[-1]
    parcalar = [p for p in y.split("/") if p]
    kok = parcalar[0] if parcalar else ""
    ikinci = parcalar[1] if len(parcalar) > 1 else ""
    oz = [
        "x=%d" % int(bool(x)),
        "kok=%s" % kok,
        "kok2=%s/%s" % (kok, ikinci),
        "ad=%s" % ad.lower(),
        "onek=%s" % ad[:4].lower(),
        "uzanti=%s" % (ad[ad.rfind("."):].lower()
                       if "." in ad[1:] else "-"),
        "sb=%s" % ("var" if shebang else "yok"),
    ]
    if shebang:
        sb_ad = shebang.rsplit("/", 1)[-1].split()[0] if shebang.split() else ""
        oz.append("sbad=%s" % sb_ad.lower())
        oz.append("sbkisa=%s" % ("evet" if sb_ad in KISA_YOL else "hayir"))
    return oz


class Risk:
    """Özellik → sınıf frekansı modeli (Laplace yumuşatma)."""

    def __init__(self, siniflar=SINIFLAR, agirlik=0.6, oncelik=1.0):
        self.siniflar = list(siniflar)
        self.agirlik = agirlik
        self.oncelik = oncelik
        self.sayac = {}        # (ozellik, sinif) -> adet
        self.toplam = {}       # sinif -> adet
        self.ornek = 0

    def ogren(self, feats, sinif):
        self.toplam[sinif] = self.toplam.get(sinif, 0) + 1
        for f in feats:
            self.sayac[(f, sinif)] = self.sayac.get((f, sinif), 0) + 1
        self.ornek += 1

    def _log(self, feats, sinif):
        if not self.ornek:
            return -1e9
        n = self.toplam.get(sinif, 0)
        if n <= 0:
            return -1e9
        toplam = 0.0
        for f in feats:
            toplam += (self.sayac.get((f, sinif), 0) + 1) / (n + 2)
        return self.oncelik * math_log(n / self.ornek) + toplam * self.agirlik

    def skorlar(self, feats):
        return {s: self._log(feats, s) for s in self.siniflar}

    def tahmin(self, feats):
        s = self.skorlar(feats)
        return max(s, key=s.get), s

    def sirala(self, feats):
        s = self.skorlar(feats)
        return [k for k, _ in sorted(s.items(), key=lambda kv: -kv[1])]

    def karar(self, yol, x, shebang=""):
        """Tahmin + izin kararı → (sinif, izin_bool, puan)."""
        tah, skor = self.tahmin(ozellikler(yol, x, shebang))
        izin = tah in CALISTIRILABILIR
        return tah, izin, skor[tah]

    # ---------- kalıcılık ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("risk.json"))
        tmp = path.with_name(path.name + ".tmp")
        veri = {"surum": 1, "agirlik": self.agirlik, "oncelik": self.oncelik,
                "siniflar": self.siniflar, "ornek": self.ornek,
                "toplam": self.toplam,
                "sayac": {"%s\t%s" % k: v for k, v in self.sayac.items()}}
        tmp.write_text(json.dumps(veri, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("risk.json"))
        if not path.exists():
            return False
        try:
            veri = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.agirlik = float(veri.get("agirlik", self.agirlik))
        self.oncelik = float(veri.get("oncelik", self.oncelik))
        self.siniflar = veri.get("siniflar", list(SINIFLAR))
        self.ornek = int(veri.get("ornek", 0))
        self.toplam = {k: int(v) for k, v in veri.get("toplam", {}).items()}
        self.sayac = {tuple(k.split("\t", 1)): int(v)
                      for k, v in veri.get("sayac", {}).items()}
        return True


def math_log(x):
    import math
    return math.log(max(1e-12, x))
