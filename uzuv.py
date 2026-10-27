"""uzuv.py — Faz 2 uzuv beyini: "bu süreç ne?" sınıflandırması.

FAZ 1 (ag.py) ham gözlemi yazar; FAZ 2 burası: aynı veriden öğrenilmiş
bir model doğar. Kural TABLOSU YOK — etiketler dışsal öğretmenden gelir:

    govde      dosya sistemi  /proc/PID/exe yok (çekirdek ipliği)
    guvenli    dpkg           sistem dizini + dpkg'ye kayıtlı
    bilinmeyen dpkg yok       gölde dizin / dpkg'siz yol
    tehlikeli  İNSAN          uzuv.jsonl defteri: ... |sinif=tehlikeli

Model: özellik→sınıf frekansı (Laplace) — risk/guvenlik/dizin ailesi,
saf Python, dış bağımlılık yok. Eğitimi egit_uzuv.py yapar (uyku hattı
düzenli çalıştırır); ag.py canlı süreçleri bu modelle sınıflandırır —
gözlem Faz 2'de biter, aktüatör (karar) Faz 3'te organ oylamasıyla gelir.

Defter (human-in-the-loop, ders modelinin ikizi):
    evil /tmp/evil |sinif=tehlikeli    # belirli süreç
    bash *          |sinif=guvenli     # comm'un tüm exe varyantları

    python3 uzuv.py listele            # son çekimdeki bilinmeyenler
    python3 uzuv.py etiketle "x /tmp/x |sinif=tehlikeli"
Deftere yazılan etiket sonraki uyku eğitiminde öncelikli girer
(damga = defter mtime → uyku hattı anında tazeler).
"""
import json
import os
import shutil
from pathlib import Path

import zeka
from risk import Risk

ROOT = Path(__file__).resolve().parent
VERI = ROOT / "uzuv_veri.jsonl"     # FAZ 1 ham verisi (ag.py yazar)
DEFTER = ROOT / "uzuv.jsonl"        # insan etiket defteri
SINIFLAR = ("govde", "guvenli", "bilinmeyen", "tehlikeli")
ISARET = " |sinif="


def ozellikler(k):
    """Süreç kaydı → özellik listesi (risk.py ile aynı sözleşme)."""
    exe = k.get("exe") or ""
    arglar = (k.get("args") or "").split()
    ilk = arglar[0].rsplit("/", 1)[-1].lower() if arglar else "-"
    ad = exe.rsplit("/", 1)[-1]
    ag = k.get("ag") or {}
    return [
        "dizin=%s" % k.get("dizin", "?"),
        "paket=%s" % (k.get("paket") or "yok"),
        "comm=%s" % (k.get("comm", "?").lower()[:15]),
        "kullanici=%s" % k.get("kullanici", "?"),
        "ilk=%s" % ilk[:20],
        "uzanti=%s" % (ad[ad.rfind("."):].lower()
                       if "." in ad[1:] else "-"),
        "dinleyen=%d" % (1 if ag.get("dinleyen") else 0),
        "kurulu=%d" % (1 if (ag.get("kurulu") or 0) > 0 else 0),
        "argos=%d" % min(len(arglar) // 3, 4),
    ]


def defter_oku(yol=None):
    """İnsan etiket defteri → {(comm, exe): sinif}; exe '*' = tümü."""
    yol = Path(yol or DEFTER)
    etiketler = {}
    try:
        satirlar = yol.read_text(encoding="utf-8").splitlines()
    except OSError:
        return etiketler
    for s in satirlar:
        s = s.strip()
        if not s or s.startswith("#") or ISARET not in s:
            continue
        sol, sinif = s.rsplit(ISARET, 1)
        sinif = sinif.strip().split()[0] if sinif.strip() else ""
        if sinif not in SINIFLAR or " " not in sol:
            continue
        comm, exe = sol.split(None, 1)
        etiketler[(comm.lower(), exe)] = sinif
    return etiketler


def etiket(kayit, defter=None):
    """İnsan defteri > zayıf oto-etiket (öğretmen hiyerarşisi)."""
    if defter:
        comm = (kayit.get("comm") or "").lower()
        exe = kayit.get("exe") or ""
        s = defter.get((comm, exe)) or defter.get((comm, "*"))
        if s:
            return s
    return kayit.get("ilk_etiket") or "bilinmeyen"


class Uzuv(Risk):
    """Risk ailesinin uzuv sürümü — tek fark: uzuv.json kalıcılığı."""

    def __init__(self, siniflar=SINIFLAR, agirlik=0.6, oncelik=1.0):
        super().__init__(siniflar=tuple(siniflar), agirlik=agirlik,
                         oncelik=oncelik)

    def save(self, path=None):
        super().save(path if path is not None
                     else zeka.kayit("uzuv.json"))

    def load(self, path=None):
        return super().load(path if path is not None
                            else zeka.yol("uzuv.json"))


class LIM:
    """CPU / RAM / disk limit izleyicisi — meta_öğrenme için kaynak baskı analizi.

    Uzuv'ün dış uzuvu: komutun yaşam sistemindeki gerçek kaynak
    etkisini ölçer. meta_ogrenme bu verileri okur:

      · Yüksek kaynak tüketen komutlar için daha agresif ceza
      · Sistem boşta (düşük kullanım) daha tutuk / hızlı keşif
      · Yüksek I/O komutları için epsilon yükselt (geçici çökün)

    Platform bağımsız: /proc/meminfo yoksa 0; shutil.disk_usage her yerde.
    """

    # Varsayılan limitler (%) — 2026-10-27 (şu an)
    CPU_LIMIT = 70.0
    RAM_LIMIT = 75.0
    DISK_LIMIT = 85.0

    def __init__(self, cpu_limit=None, ram_limit=None, disk_limit=None):
        self.cpu_limit = float(cpu_limit or self.CPU_LIMIT)
        self.ram_limit = float(ram_limit or self.RAM_LIMIT)
        self.disk_limit = float(disk_limit or self.DISK_LIMIT)

    # --- anlık ölçümler ---

    def cpu_pct(self):
        """CPU kullanım yüzdesi (1 dk load average / cpu_count)."""
        try:
            load1, _, _ = os.getloadavg()
            ncpu = os.cpu_count() or 1
            return min(100.0, (load1 / ncpu) * 100.0)
        except (OSError, ValueError):
            return 0.0

    def ram_pct(self):
        """RAM kullanım yüzdesi (/proc/meminfo → MemTotal − MemAvailable)."""
        try:
            with open("/proc/meminfo", encoding="utf-8") as f:
                mem = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        mem[parts[0].strip()] = int(
                            parts[1].strip().split()[0])
                total = mem.get("MemTotal", 0)
                avail = mem.get("MemAvailable", mem.get("MemFree", 0))
                if total > 0:
                    return min(100.0, ((total - avail) / total) * 100.0)
        except (OSError, ValueError):
            pass
        return 0.0

    def disk_pct(self, path="/"):
        """Disk kullanım yüzdesi (shutil.disk_usage)."""
        try:
            u = shutil.disk_usage(path)
            if u.total > 0:
                return min(100.0, (u.used / u.total) * 100.0)
        except (OSError, ValueError):
            pass
        return 0.0

    # --- durum & adaptif ceza ---

    def durum(self):
        """Tüm limitlerin mevcut durumu."""
        return {
            "cpu_pct": round(self.cpu_pct(), 1),
            "ram_pct": round(self.ram_pct(), 1),
            "disk_pct": round(self.disk_pct(), 1),
            "cpu_limit": self.cpu_limit,
            "ram_limit": self.ram_limit,
            "disk_limit": self.disk_limit,
        }

    def adaptif_ceza(self):
        """Kaynak baskısına göre ceza çarpanı (1.0 = normal).

        Limit aşımında çarpan > 1.0; maksimum 5.0×.
        meta_ogrenme bu çarpanı lr/epsilon ayarlarında kullanır.
        """
        d = self.durum()
        f = 1.0
        for pct, lim in ((d["cpu_pct"], self.cpu_limit),
                         (d["ram_pct"], self.ram_limit),
                         (d["disk_pct"], self.disk_limit)):
            if pct > lim:
                f *= 1.0 + (pct - lim) / (100.0 - lim)
        return min(f, 5.0)


def son_cekim(yol=None):
    """Veri dosyasının son çekimindeki (sid) satırlar."""
    yol = Path(yol or VERI)
    try:
        with open(yol, encoding="utf-8") as f:
            ham = f.readlines()[-2000:]
    except OSError:
        return []
    kayitlar = []
    for s in ham:
        s = s.strip()
        if s:
            try:
                kayitlar.append(json.loads(s))
            except ValueError:
                continue
    if not kayitlar:
        return []
    sid = kayitlar[-1].get("sid")
    return [k for k in kayitlar if k.get("sid") == sid]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="uzuv beyini — defter & gözlem")
    ap.add_argument("komut", nargs="?", default="listele",
                    choices=["listele", "etiketle"])
    ap.add_argument("metin", nargs="?", default=None,
                    help='etiketle: "comm exe |sinif=tehlikeli"')
    ap.add_argument("--json", dest="jsoncikti", action="store_true",
                    help="listele: pano için TAM alanlı JSON çıktı")
    args = ap.parse_args()
    if args.komut == "etiketle":
        if not args.metin or ISARET not in args.metin:
            raise SystemExit('biçim: "comm exe |sinif=sinif" '
                             "(sınıflar: %s)" % ", ".join(SINIFLAR))
        sinif = args.metin.rsplit(ISARET, 1)[1].strip()
        if sinif not in SINIFLAR:
            raise SystemExit("geçersiz sınıf: %s (%s)" % (sinif, SINIFLAR))
        with open(DEFTER, "a", encoding="utf-8") as f:
            f.write(args.metin.strip() + "\n")
        print("deftere yazıldı → %s\n"
              "uyku hattı damga olarak görüp yeniden eğitecek." % DEFTER)
        raise SystemExit(0)
    # listele: son çekimdeki bilinmeyenler + model tahmini
    m = Uzuv()
    if not m.load():
        raise SystemExit("zeka/uzuv.json yok — önce: python3 egit_uzuv.py")
    defter = defter_oku()
    satirlar = son_cekim()
    if not satirlar:
        raise SystemExit("veri yok: %s" % VERI)
    bil = [k for k in satirlar if etiket(k, defter) == "bilinmeyen"]
    if args.jsoncikti:
        # pano (web) için: TAM alanlar — kısaltma yok, etiket birebir tutar
        print(json.dumps(
            [{"comm": k.get("comm") or "?", "exe": k.get("exe") or "-",
              "tahmin": m.tahmin(ozellikler(k))[0]} for k in bil],
            ensure_ascii=False))
        raise SystemExit(0)
    print("son çekim: %d süreç, %d bilinmeyen (defter: %d etiket)"
          % (len(satirlar), len(bil), len(defter)))
    for k in bil[:40]:
        tah = m.tahmin(ozellikler(k))[0]
        print("  %-16s %-32s → %s"
              % ((k.get("comm") or "?")[:16],
                 (k.get("exe") or "-")[:32], tah))
    if len(bil) > 40:
        print("  ... +%d" % (len(bil) - 40))
    print('etiketlemek için: python3 uzuv.py etiketle "COMM EXE |sinif=..."')
