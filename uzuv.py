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
