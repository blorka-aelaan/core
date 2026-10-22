"""Dizin modeli — katalogdan kendini eğiten dünya bilgisi.

envanter/dosyalar.jsonl'deki HER DOSYA satırı kendi etiketini taşır:
ad → boyut kovası (küçük/orta/büyük) ve → kaynak kökü (/usr/share/doc,
/etc ...). Dış etiket yoktur: saf kendinden gözetimli öğrenme.

Ne işe yarar: "büyük dosya arıyorum" ya da "X adlı bir dosya nerede
olur?" sorusuna OLASILIK döndürür → `find /` yerine akıllı daraltma,
yani arama ekonomisi (daha az CPU → kaynak cezasıyla birleşir).

Saf Python: özellik frekansı + Laplace yumuşatması. Kayıt: dizin.json.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

BOYUT_KOVASI = [("kucuk", 10 * 1024), ("orta", 1024 * 1024),
                ("buyuk", 1 << 62)]


def boyut_kovasi(boyut):
    for ad, ust in BOYUT_KOVASI:
        if boyut < ust:
            return ad
    return "buyuk"


def ozellikler(ad):
    """Dosya adından çıkan basit, yorumlanabilir özellikler."""
    feats = ["uzanti=" + (ad[ad.rfind("."):].lower()
                          if "." in ad[1:] else "-")]
    feats.append("ad%d" % (len(ad) // 4))
    feats.append("rakam" if any(c.isdigit() for c in ad) else "harfsiz")
    feats.append("noktali" if "." in ad else "noktasiz")
    onek = ad[:3].lower()
    feats.append("onek=" + onek)
    return feats


def kaynak_koku(klasor):
    """Sınıf = arama için ANLAMLI aile: '/etc' ve '/usr/share' gibi.

    Veriye baktık: /etc altındaki her klasör ayrı sınıf olsaydı model
    'hangi klasör' tahmin etmeye çalışır (işe yaramaz, %50). Oysa
    arama ekonomisi için 'hangi AİLE' bilgisi yeter: /usr altında
    ağaç derindir (2 bileşen), /etc sığdır (1 bileşen).
    """
    parcalar = [p for p in klasor.split("/") if p]
    if not parcalar:
        return "/"
    if parcalar[0] == "usr" and len(parcalar) >= 2:
        return "/usr/" + parcalar[1]
    return "/" + parcalar[0]


class Dizin:
    """Sınıf frekansı modeli (Laplace): ozellik → sinif sayacı."""

    def __init__(self, siniflar=(), agirlik=0.15, oncelik=1.0):
        self.siniflar = list(siniflar)
        self.agirlik = agirlik      # özellik baskısı (göreve göre ayarlanır)
        self.oncelik = oncelik      # sınıf önceliğinin ağırlığı
        self.sayac = {}      # (özellik, sinif) -> adet
        self.toplam = {}    # sinif -> adet
        self.ornek = 0

    def klonla(self, agirlik):
        d = Dizin(self.siniflar, agirlik=agirlik, oncelik=self.oncelik)
        d.sayac = dict(self.sayac)
        d.toplam = dict(self.toplam)
        d.ornek = self.ornek
        return d

    def ogren(self, feats, sinif):
        self.toplam[sinif] = self.toplam.get(sinif, 0) + 1
        for f in feats:
            self.sayac[(f, sinif)] = self.sayac.get((f, sinif), 0) + 1
        self.ornek += 1

    def _log_olasilik(self, feats, sinif):
        """Sınıfın log olasılığı: özellik frekansı (Laplace) + hafif öncelik.

        Ağırlık dengeyi kurar: yumuşak ağırlık nadir sınıfları eziyor
        (kaynak görevinde top-1 %29), sert ağırlık boyut görevini
        bozuyordu (%87 → %60). Tek sabit yerine görev başına seçilir
        (egit_dizin.py taraması).
        """
        if self.ornek == 0:
            return 0.0
        toplam_sayi = self.toplam.get(sinif, 0)
        if toplam_sayi <= 0:
            return -1e9
        import math
        toplam = 0.0
        for f in feats:
            toplam += (self.sayac.get((f, sinif), 0) + 1) / \
                      (toplam_sayi + 2)          # Laplace
        return self.oncelik * math.log(toplam_sayi / self.ornek) \
            + toplam * self.agirlik

    def tahmin(self, feats):
        """En olası sınıf + sınıf skorları."""
        skorlar = {s: self._log_olasilik(feats, s) for s in self.siniflar}
        en = max(skorlar, key=skorlar.get)
        return en, skorlar

    def sirala(self, feats):
        """Sınıfları olasılık sırasıyla döndür (en olasıdan)."""
        _, skorlar = self.tahmin(feats)
        return [s for s, _ in sorted(skorlar.items(),
                                    key=lambda kv: -kv[1])]

    # ---------- kalıcı kayıt ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("dizin.json"))
        tmp = path.with_name(path.name + ".tmp")
        # agirlik/oncelik de yazılır: seçilen ağırlık görev başına değişiyor,
        # kaydetmezsek model canlıya YANLIŞ ayarla yüklenirdi (sessiz).
        veri = {"surum": 2, "agirlik": self.agirlik, "oncelik": self.oncelik,
                "siniflar": self.siniflar, "ornek": self.ornek,
                "toplam": self.toplam,
                "sayac": {"%s\t%s" % k: v for k, v in self.sayac.items()}}
        tmp.write_text(json.dumps(veri, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("dizin.json"))
        if not path.exists():
            return False
        try:
            veri = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.agirlik = float(veri.get("agirlik", self.agirlik))
        self.oncelik = float(veri.get("oncelik", self.oncelik))
        self.siniflar = veri.get("siniflar", [])
        self.ornek = int(veri.get("ornek", 0))
        self.toplam = {k: int(v) for k, v in
                       veri.get("toplam", {}).items()}
        self.sayac = {tuple(k.split("\t", 1)): int(v) for k, v in
                      veri.get("sayac", {}).items()}
        return True


def egit(dosyalar_jsonl, sinif_tipi="boyut", karistir=None):
    """katalogdan eğit → (model, egitim satırları listesi)."""
    import random
    if karistir is None:
        karistir = random.Random(7)
    satirlar = []
    try:
        with open(dosyalar_jsonl, encoding="utf-8") as f:
            for satir in f:
                try:
                    satirlar.append(json.loads(satir))
                except ValueError:
                    pass
    except OSError:
        return None, []
    if not satirlar:
        return None, []
    if sinif_tipi == "boyut":
        siniflar = [ad for ad, _ in BOYUT_KOVASI]
        etiket = lambda r: boyut_kovasi(r.get("boyut", 0))
    else:                      # kaynak kökü
        kokler = sorted(set(kaynak_koku(r.get("klasor", ""))
                            for r in satirlar))
        siniflar = kokler[:12]    # en çok 12 sınıf (RAM ölçüsü)
        etiket = lambda r: kaynak_koku(r.get("klasor", ""))
    karistir.shuffle(satirlar)
    bolme = int(len(satirlar) * 0.8)
    egitim, test = satirlar[:bolme], satirlar[bolme:]
    d = Dizin(siniflar)
    for r in egitim:
        d.ogren(ozellikler(r.get("ad", "")), etiket(r))
    return (d, test)