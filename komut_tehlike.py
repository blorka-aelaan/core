"""komut_tehlike.py — Komut tehlike skoru tahmini modeli.

Komut adı + zarar profili → tehlike skoru (0..1) tahmini.
Organizma komutu çalıştırmadan önce bu modeli sorar:
    "bu komutu çalıştırırsam ölürüm mü?" → uygula / bekle / iptal

Öğrenme: veri seti (data/komut_zarar.jsonl) üzerinden delta öğrenmesi.
Kayıt: zeka/komut_tehlike.json (atomik).

Özellik uzayı:
  - komut=<isim>            (tekil komut kimliği)
  - zarar=<tip>             (dosya_silme, disk_yazma, sistem_kontrolu, ...)
  - enerji=<kova>           (enerji_etkisi kova: -100, -70, ..., -10)
  - olum=<kova>             (olum_olasiligi kova: 1.0, 0.95, ..., 0.1)

Tahmin = global_ortalama + aktif özelliklerin delta ortalaması.
Hedef = olum_olasiligi (gerçekte bu komut ne kadar ölütür).

YENİ: --help öğrenme
  - help=<komut>            (komutun --help çıktısından çıkarılan anahtar kelime)
  - komut_aciklama=<metin>  (komutun --help'ından elde edilen kısa açıklama)

Model, --help çıktısını kaydeder ve organizma komutun ne işe
yaradığını öğrenebilir.

Kullanım:
    m = KomutTehlike(); m.load()
    skor = m.tahmin(komut="rm", zarar_tipi="dosya_silme",
                    enerji_etkisi=-60, olum_olasiligi=0.9)
    # skor ≈ 0.9 → çok tehlikeli
"""

import json
import os
from pathlib import Path

import zeka

ROOT = Path(__file__).resolve().parent
VERI_SETI = ROOT / "data" / "komut_zarar.jsonl"

# Enerji etkisi kova sınırları (artan mutlak değer)
ENERJI_KOVALARI = (-100, -70, -60, -50, -40, -30, -20, -10)

# Ölüm olasılığı kova sınırları
OLUM_KOVALARI = (1.0, 0.95, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)


def _kova(deger, sinirlar):
    """Değeri verilen sınırlar listesine göre kova anahtarına çevirir.

    sinirlar büyükten küçüğe sıralıdır; değere en yakın üst sınır seçilir.
    """
    for sinir in sinirlar:
        if deger <= sinir:
            return str(sinir)
    return str(sinirlar[-1])


def ozellikler(komut, zarar_tipi, enerji_etkisi, olum_olasiligi):
    """Komut ve zarar profilinden özellik anahtarları üretir."""
    uz = len(komut)
    if uz <= 4:
        uz_kova = "kisa"
    elif uz <= 7:
        uz_kova = "orta"
    else:
        uz_kova = "uzun"
    # Kategori: zarar_tipi'nin ilk bölümü (dosya, disk, sistem, ag, vb.)
    kat = zarar_tipi.split("_")[0] if "_" in zarar_tipi else zarar_tipi
    feats = [
        "komut=%s" % komut,
        "zarar=%s" % zarar_tipi,
        "enerji=%s" % _kova(float(enerji_etkisi), ENERJI_KOVALARI),
        "olum=%s" % _kova(float(olum_olasiligi), OLUM_KOVALARI),
        "uzunluk=%s" % uz_kova,
        "kategori=%s" % kat,
    ]
    return feats


def satir_oku(yol=VERI_SETI):
    """Veri setinden satır okuyup (özellikler, hedef) listesi döner."""
    ornekler = []
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if not satir:
                continue
            try:
                k = json.loads(satir)
            except ValueError:
                continue
            feats = ozellikler(
                k.get("komut", ""),
                k.get("zarar_tipi", ""),
                k.get("enerji_etkisi", 0),
                k.get("olum_olasiligi", 0),
            )
            hedef = float(k.get("olum_olasiligi", 0.0))
            ornekler.append((feats, hedef))
    return ornekler


class KomutTehlike:
    """Delta öğrenmeli komut tehlike skoru modeli."""

    def __init__(self, lr=0.2, yumusatma=500.0):
        self.lr = lr
        self.k = yumusatma
        self.n = {}            # özellik -> [sayım, delta]
        self.global_n = 0
        self.global_sum = 0.0
        self.samples = 0
        self.help_aciklamalar = {}   # komut -> {"aciklama": str, "ikinci_satir": str}
        self._disk_mtime = None

    def ogren(self, feats, hedef):
        pred = self.tahmin(feats)
        err = float(hedef) - pred
        n_f = max(1, len(feats))
        for f in feats:
            s = self.n.setdefault(f, [0, 0.0])
            step = max(self.lr / (1.0 + s[0] / self.k), 0.01)
            s[1] += step * err / n_f
            s[0] += 1
        self.global_n += 1
        self.global_sum += float(hedef)
        self.samples += 1

    def tahmin(self, komut=None, zarar_tipi=None,
               enerji_etkisi=None, olum_olasiligi=None,
               feats=None):
        """Tehlike skoru döner (0..1)."""
        if feats is None:
            feats = ozellikler(komut or "", zarar_tipi or "",
                               enerji_etkisi or 0, olum_olasiligi or 0)
        if self.global_n:
            base = self.global_sum / self.global_n
        else:
            base = 0.5
        deltas = [self.n[f][1] for f in feats if f in self.n]
        if not deltas:
            return base
        skor = base + sum(deltas) / len(deltas)
        return max(0.0, min(1.0, skor))

    # ---------- --help öğrenme ----------

    def _help_calistir(self, komut, bayrak, timeout=5):
        import subprocess
        try:
            r = subprocess.run([komut, bayrak],
                               capture_output=True, text=True,
                               errors="replace", timeout=timeout,
                               cwd="/tmp")
        except (FileNotFoundError, PermissionError, OSError,
                subprocess.TimeoutExpired):
            return None
        out = (r.stdout or "") + (r.stderr or "")
        if not out.strip():
            return None
        satirlar = [s.strip() for s in out.splitlines() if s.strip()]
        if not satirlar:
            return None
        return satirlar

    def help_ogren(self, komut, timeout=5):
        """<komut> --help'ını (veya -h')ı çalıştırıp çıktısın anahtar satırlarını kaydeder.

        Bazı komutlar --help yerine -h kullanır; her ikisini dener.
        Döner: (basarili, aciklama_str) — başarı True ise aciklama,
               False ise hata mesajı.
        """
        satirlar = self._help_calistir(komut, "--help", timeout)
        if satirlar is None:
            satirlar = self._help_calistir(komut, "-h", timeout)
        if satirlar is None:
            return False, "help_yok"
        aciklama = satirlar[0][:200]        # ilk satır: komutun ne yaptığı
        ikinci = satirlar[1][:200] if len(satirlar) > 1 else ""
        self.help_aciklamalar[komut] = {"aciklama": aciklama,
                                        "ikinci_satir": ikinci}
        return True, aciklama

    def help_acikla(self, komut):
        """<komut> için daha önce öğrenilmiş --help açıklamasını döner."""
        return self.help_aciklamalar.get(komut)

    # ---------- kayıt ----------

    def save(self, path=None):
        path = Path(path or zeka.kayit("komut_tehlike.json"))
        tmp = path.with_name(path.name + ".tmp")
        data = {
            "samples": self.samples,
            "global": [self.global_n, self.global_sum],
            "n": self.n,
            "help_aciklamalar": self.help_aciklamalar,
        }
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))
        self._disk_mtime = path.stat().st_mtime
        return True

    def load(self, path=None):
        path = Path(path or zeka.yol("komut_tehlike.json"))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.samples = int(data.get("samples", 0))
        g = data.get("global", [0, 0.5])
        self.global_n, self.global_sum = int(g[0]), float(g[1])
        self.n = {f: [int(v[0]), float(v[1])]
                  for f, v in data.get("n", {}).items()}
        self.help_aciklamalar = data.get("help_aciklamalar", {})
        self._disk_mtime = path.stat().st_mtime
        return True


def egit(veri_seti_yolu=VERI_SETI, adet=None, seed=7, kaydet=True, epoch=5):
    """Veri setinden modeli eğitir. adet=None → tüm veri kullanılır.

    epoch: kaç kez tekrarlanarak eğitileceği (tekrarla öğrenme).
    """
    import random
    rng = random.Random(seed)
    ornekler = satir_oku(veri_seti_yolu)
    if adet is not None and adet < len(ornekler):
        rng.shuffle(ornekler)
        ornekler = ornekler[:adet]
    m = KomutTehlike()
    for _ in range(epoch):
        rng.shuffle(ornekler)
        for feats, hedef in ornekler:
            m.ogren(feats, hedef)
    if kaydet:
        m.save()
    return m, len(ornekler)


def egit_komut_ayrik(veri_seti_yolu=VERI_SETI, test_oran=0.2, seed=7,
                     epoch=5, kaydet=True):
    """Komut bazlı hold-out: aynı komut hem eğitimde hem testte olmaz.

    Bu sayede model 'rm'yi görmüş olsa bile 'rmdir' gibi görünmediği
    komutu da tehlike olarak değerlendirebilir (genelleme testi).
    """
    import random
    from collections import defaultdict
    rng = random.Random(seed)
    ornekler = satir_oku(veri_seti_yolu)

    # Komut isimlerine göre grupla
    komutlara_gore = defaultdict(list)
    for feats, hedef in ornekler:
        komut = feats[0].split("=", 1)[1]  # "komut=rm" -> "rm"
        komutlara_gore[komut].append((feats, hedef))

    komutlar = sorted(komutlara_gore.keys())
    rng.shuffle(komutlar)
    bolme = int(len(komutlar) * (1 - test_oran))
    tr_komutlar = set(komutlar[:bolme])

    egitim = []
    test = []
    for komut, liste in komutlara_gore.items():
        if komut in tr_komutlar:
            egitim.extend(liste)
        else:
            test.extend(liste)

    m = KomutTehlike()
    for _ in range(epoch):
        rng.shuffle(egitim)
        for feats, hedef in egitim:
            m.ogren(feats, hedef)

    if kaydet:
        m.save()

    mae, dogru = degerlendir(m, test)
    print("Komut-ayrık hold-out: eğitim %d komut / test %d komut → MAE=%.3f, doğru=%.1f%%"
          % (len(tr_komutlar), len(komutlar) - len(tr_komutlar), mae, dogru))
    return m, len(egitim), len(test)


def degerlendir(m, test_ornekler):
    """MAE ve eşik üzeri doğru karar oranı döner."""
    hata = 0.0
    dogru = 0
    n = len(test_ornekler)
    for feats, hedef in test_ornekler:
        pred = m.tahmin(feats=feats)
        hata += abs(pred - hedef)
        # eşik 0.5: >=0.5 tehlikeli, <0.5 güvenli
        if (pred >= 0.5) == (hedef >= 0.5):
            dogru += 1
    return hata / max(1, n), 100.0 * dogru / max(1, n)


if __name__ == "__main__":
    import sys
    # Komut-ayrık hold-out (önerilen): aynı komut hem eğitimde hem testte olmaz
    m, n_tr, n_te = egit_komut_ayrik(epoch=5)
    print("Eğitim örnek: %d | Test örnek: %d → zeka/komut_tehlike.json" % (n_tr, n_te))

    # Klasik hold-out da karşılaştırma için
    tum = satir_oku()
    bolme = int(len(tum) * 0.8)
    m2, _ = egit(adet=bolme, epoch=5, kaydet=False)
    mae, dogru_yuzde = degerlendir(m2, tum[bolme:])
    print("Klasik hold-out: %d örnek → MAE=%.3f, doğru=%.1f%%"
          % (len(tum) - bolme, mae, dogru_yuzde))