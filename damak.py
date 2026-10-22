"""Damak — isim-ödül tahmin organı (eğitilebilir, taşınabilir).

İsimden özellik çıkarır (kategori birleşimi + bucket'lar); her özellik için
toplamalı etki (delta) öğrenir:

    tahmin = global_ortalama + aktif özelliklerin delta ortalaması

Delta'lar (gerçek − tahmin) hatasına göre eğilir (çevrimiçi, saf Python).
Kural özelliklerle temsil edilebilirse hata sıfıra iner; numpy gerekmez.
Kayıt: damak.json (atomik).

  damak = Damak(); damak.load(); damak.tahmin(ozellikler(isim, cfg))
"""
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ozellikler(name, cfg, path=None):
    """İsim → özellik anahtarları (kategori birleşimi + bucket'lar).

    path verilirse **derinlik** özelliği de eklenir (kutular düzeni):
    derin klasör = büyük ödül bilgisi böyle öğrenilir.
    """
    sonek = cfg["kutu"]["sonek"]
    govde = name[:-len(sonek)] if name.endswith(sonek) else name
    tip = ("sayi" if govde.isdigit()
           else "harf" if govde.isalpha() else "karisik")
    feats = ["c=%s|%d" % (tip, len(govde))]           # kategori birleşimi
    if tip == "sayi":
        top = sum(int(c) for c in govde)
        feats.append("rt5:%d" % (top // 5))           # ince kova (eşikler için)
        feats.append("rt:%d" % (top // 10))           # kaba kova (genel eğilim)
        feats.append("rt_tek" if top % 2 else "rt_cift")
    elif tip == "harf":
        top = sum(ord(c) - 96 for c in govde)
        feats.append("ht20:%d" % (top // 20))         # ince kova
        feats.append("ht:%d" % (top // 40))           # kaba kova
        feats.append("ht_yuksek" if top > 120 else "ht_dusuk")
    if path:
        prefix = cfg["kutu"]["dir"] + "/"
        r = path[len(prefix):] if path.startswith(prefix) else path
        feats.append("d=%d" % max(0, r.count("/")))
    return feats


class Damak:
    def __init__(self, lr=0.2, yumusatma=500.0):
        self.lr = lr                 # başlangıç adım oranı
        self.k = yumusatma           # adım yumuşaması (n/500)
        self.n = {}                  # özellik -> [sayım, delta]
        self.global_n = 0
        self.global_sum = 0.0
        self.samples = 0
        self._disk_mtime = None      # yükleme anındaki dosya zamanı

    def ogren(self, feats, odul):
        pred = self.tahmin(feats)
        err = float(odul) - pred
        n_f = max(1, len(feats))
        for f in feats:
            s = self.n.setdefault(f, [0, 0.0])
            # TABAN (kullanici notu): etkin hiz ~step/n_f oldugundan
            # 1/(1+n/500) tampansiz cok erken sonuyor; kurallar sonradan
            # degisirse (--kurallar) model cok yavas uyum sagliyordu.
            step = max(self.lr / (1.0 + s[0] / self.k), 0.01)
            s[1] += step * err / n_f
            s[0] += 1
        self.global_n += 1
        self.global_sum += float(odul)
        self.samples += 1

    def tahmin(self, feats):
        if self.global_n:
            base = self.global_sum / self.global_n
        else:
            base = 0.0
        deltas = [self.n[f][1] for f in feats if f in self.n]
        if not deltas:
            return base
        return base + sum(deltas) / len(deltas)

    def sec(self, isimler, cfg, epsilon=0.0):
        """Adaylar arasından en yüksek tahminli (keşif payı ile) seç.

        Adaylar düz isim YA DA tam yol olabilir. Yol gelirse isim olarak
        son parça kullanılır ve derinlik (d=) özelliği de katılır; böylece
        seçim, öğrenmede (ogren) kullanılan özelliklerle birebir aynıdır.
        (Eski sürüm tam yolu isim sanıyordu → 'karisik' kovası → hiçbir
        öğrenilmiş özellik eşleşmiyor, tüm adaylar eşit çıkıyordu.)
        Eşitlikte ilk eleman değil, rastgele biri seçilir.
        """
        if not isimler:
            return None
        if random.random() < epsilon:
            return random.choice(isimler)

        def puan(n):
            ad = n.rsplit("/", 1)[-1]
            return self.tahmin(
                ozellikler(ad, cfg, path=n if "/" in n else None))

        skorlar = [(puan(n), n) for n in isimler]
        en = max(p for p, _ in skorlar)
        return random.choice([n for p, n in skorlar if p == en])

    # ---------- kalıcı kayıt ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("damak.json"))
        # HARİCİ EĞİTİM KORUMASI: model bu süreçte yüklendikten sonra
        # dışarıdan (egit.py) yeniden eğitildiyse üzerine yazma —
        # aksi halde yaşayan organizma her çıkışta yeni eğitimi ezer.
        if self._disk_mtime is not None and path.exists():
            if abs(path.stat().st_mtime - self._disk_mtime) > 1e-6:
                return False
        tmp = path.with_name(path.name + ".tmp")
        data = {"samples": self.samples,
                "global": [self.global_n, self.global_sum],
                "buckets": self.n}
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))
        self._disk_mtime = path.stat().st_mtime
        return True

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("damak.json"))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.samples = int(data.get("samples", 0))
        g = data.get("global", [0, 0.0])
        self.global_n, self.global_sum = int(g[0]), float(g[1])
        self.n = {f: [int(v[0]), float(v[1])]
                  for f, v in data.get("buckets", {}).items()}
        self._disk_mtime = path.stat().st_mtime
        return True