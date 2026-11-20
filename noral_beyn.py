"""CORE Nöral Beyn v2 — pure Python (tensor yok, sadece math/random).

Çok katmanlı perceptron (MLP), geri yayılımla öğrenir.
Ağırlıklar zeka/nn_*.json dosyalarında kalıcı olarak saklanır.
Uyku sırasında konsolidasyon yapılır (uykuda `kaydet()` çağır).

v2 farkları:
  * momentum gerçekten kullanılıyor (sönümlü biçim: etkin adım ≈ lr kalır)
  * ileri/geri geçiş list-comprehension + map(mul) + transpoze önbelleği ile hızlı
  * her örnekte değil, `kaydet_aralığı` adımda bir diske atomik olarak yazar
  * bozuk dosya sessizce ezilmez: `.bozuk` olarak yedeklenir
  * gerçek MSE ve gerçek öğrenme sayacı (adım)
  * isteğe bağlı: tanh gizli/çıkış katmanı, çapraz-entropi kaybı, L2
Varsayılanlar eski dosyalarla uyumludur (sigmoid + mse).
"""
from collections import deque
import json
import math
from operator import mul
import os
import random
import threading
from typing import Optional

import zeka


class NöralBeyn:
    def __init__(self, ad: str, katmanlar: list[int], lr: float = 0.15,
                 momentum: float = 0.9, gizli_aktivasyon: str = "sigmoid",
                 çıkış_aktivasyon: str = "sigmoid", kayıp: str = "mse",
                 l2: float = 0.0, kaydet_aralığı: int = 10):
        self.ad = ad
        self.katmanlar = list(katmanlar)
        self.lr = lr
        self.momentum = momentum
        self.gizli = gizli_aktivasyon        # "sigmoid" | "tanh"
        self.çıkış_akt = çıkış_aktivasyon    # "sigmoid" | "tanh"
        self.kayıp = kayıp                   # "mse" | "ce"
        self.l2 = l2
        self.kaydet_aralığı = max(1, kaydet_aralığı)
        self.yol = zeka.yol(f"nn_{ad}.json")

        self.ağırlıklar: list[list[list[float]]] = []
        self.çeşitler: list[list[float]] = []
        self._w_transpoze: list[list[tuple[float, ...]]] = []
        self._vw: list[list[list[float]]] = []
        self._vb: list[list[float]] = []

        self.hız_geçmişi: deque[float] = deque(maxlen=200)  # kayıp geçmişi
        self.adım = 0
        self.aktivasyonlar: list[list[float]] = []
        self._kilit = threading.RLock()
        self._son_girişler: deque[list[float]] = deque(maxlen=64)

        self._yükle()
        self._hız_sıfırla()
        self._transpoze_güncelle()

    # ------------------------------------------------------------ yükleme / başlatma
    def _doğrula(self, veri: dict):
        kat = veri["katmanlar"]
        w, b = veri["ağırlıklar"], veri["çeşitler"]
        if len(kat) < 2 or len(w) != len(kat) - 1 or len(b) != len(w):
            raise ValueError("katman sayısı uyuşmuyor")
        for l in range(len(w)):
            if len(w[l]) != kat[l] or len(b[l]) != kat[l + 1]:
                raise ValueError("ağırlık boyutu uyuşmuyor")
            if any(len(satır) != kat[l + 1] for satır in w[l]):
                raise ValueError("ağırlık satırı uyuşmuyor")

    def _yükle(self):
        try:
            ham = self.yol.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._başlat()
            return
        try:
            veri = json.loads(ham)
            self.katmanlar = veri.get("katmanlar", self.katmanlar)
            if veri.get("ağırlıklar"):
                self._doğrula(veri)
                self.ağırlıklar = veri["ağırlıklar"]
                self.çeşitler = veri["çeşitler"]
            else:
                self._başlat()
                return
        except (ValueError, KeyError, TypeError):
            os.replace(str(self.yol), str(self.yol) + ".bozuk")
            self._başlat()
            return

        self.lr = veri.get("lr", self.lr)
        self.momentum = veri.get("momentum", self.momentum)
        self.gizli = veri.get("aktivasyon", "sigmoid")
        self.çıkış_akt = veri.get("çıkış_aktivasyon", "sigmoid")
        self.kayıp = veri.get("kayıp", self.kayıp)
        self.l2 = veri.get("l2", self.l2)
        geçmiş = veri.get("hız_geçmişi", [])
        self.hız_geçmişi = deque(geçmiş[-200:], maxlen=200)
        self.adım = veri.get("adım", len(geçmiş))

    def _başlat(self):
        self.ağırlıklar = []
        self.çeşitler = []
        for l in range(len(self.katmanlar) - 1):
            nin, nout = self.katmanlar[l], self.katmanlar[l + 1]
            # Uniform dağılım için standart Xavier sınırı
            limit = (6.0 / (nin + nout)) ** 0.5
            w = [[random.uniform(-limit, limit) for _ in range(nout)]
                 for _ in range(nin)]
            b = [0.0 for _ in range(nout)]
            self.ağırlıklar.append(w)
            self.çeşitler.append(b)
        self.hız_geçmişi.clear()
        self.adım = 0

    def _hız_sıfırla(self):
        with self._kilit:
            self._vw = [[[0.0 for _ in row] for row in w] for w in self.ağırlıklar]
            self._vb = [[0.0 for _ in row] for row in self.çeşitler]

    def _transpoze_güncelle(self):
        self._w_transpoze = [list(zip(*w)) for w in self.ağırlıklar]

    # ------------------------------------------------------------ aktivasyonlar
    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >= 0:
            return 1.0 / (1.0 + math.exp(-x))
        ex = math.exp(x)
        return ex / (1.0 + ex)

    @staticmethod
    def _sigmoid_türev(y: float) -> float:
        return y * (1.0 - y)

    @property
    def çekirdekler(self) -> list[list[float]]:
        return self.aktivasyonlar[1:]

    # ------------------------------------------------------------ ileri / geri geçiş
    def ileri_geçiş(self, giriş: list[float]) -> list[float]:
        with self._kilit:
            return self._ileri_geçiş_iç(giriş)

    def _ileri_geçiş_iç(self, giriş: list[float]) -> list[float]:
        if len(giriş) != self.katmanlar[0]:
            raise ValueError("giriş boyutu %d, beklenen %d"
                             % (len(giriş), self.katmanlar[0]))
        aktif = list(giriş)
        akt = [aktif]
        son = len(self.ağırlıklar) - 1
        for l, (wt, b) in enumerate(zip(self._w_transpoze, self.çeşitler)):
            akt_türü = self.çıkış_akt if l == son else self.gizli
            f = math.tanh if akt_türü == "tanh" else self._sigmoid
            aktif = [f(bj + sum(map(mul, aktif, kol)))
                     for bj, kol in zip(b, wt)]
            akt.append(aktif)
        self.aktivasyonlar = akt
        return aktif

    def geri_yayılış(self, hedef: list[float]):
        with self._kilit:
            self._geri_yayılış_iç(hedef)

    def _geri_yayılış_iç(self, hedef: list[float]):
        if not self.aktivasyonlar:
            raise RuntimeError("Geri yayılıştan önce ileri_geçiş çağrılmalıdır.")
        çıkış = self.aktivasyonlar[-1]
        if len(hedef) != len(çıkış):
            raise ValueError("hedef boyutu %d, beklenen %d"
                             % (len(hedef), len(çıkış)))

        if self.kayıp == "ce":
            delta = [t - y for t, y in zip(hedef, çıkış)]
        elif self.çıkış_akt == "tanh":
            delta = [(t - y) * (1.0 - y * y) for t, y in zip(hedef, çıkış)]
        else:
            delta = [(t - y) * y * (1.0 - y) for t, y in zip(hedef, çıkış)]

        mse = sum((t - y) ** 2 for t, y in zip(hedef, çıkış)) / max(1, len(çıkış))

        L = len(self.ağırlıklar)
        tanh_gizli = self.gizli == "tanh"
        deltalar: list[list[float]] = [[] for _ in range(L)]
        deltalar[-1] = delta
        for l in range(L - 2, -1, -1):
            d_s = deltalar[l + 1]
            deltalar[l] = [
                sum(map(mul, d_s, satır)) * (1.0 - y * y if tanh_gizli else y * (1.0 - y))
                for satır, y in zip(self.ağırlıklar[l + 1], self.aktivasyonlar[l + 1])
            ]

        lr, m, l2 = self.lr, self.momentum, self.l2
        k = (1.0 - m) * lr  # sönümlü momentum
        for l in range(L):
            W, VW = self.ağırlıklar[l], self._vw[l]
            B, VB = self.çeşitler[l], self._vb[l]
            d = deltalar[l]
            for i, (a, satır, vs) in enumerate(zip(self.aktivasyonlar[l], W, VW)):
                yv = [m * v + k * (dj * a - l2 * w)
                      for v, dj, w in zip(vs, d, satır)]
                VW[i] = yv
                W[i] = [w + v for w, v in zip(satır, yv)]
            VB[:] = [m * v + k * dj for v, dj in zip(VB, d)]
            B[:] = [b + v for b, v in zip(B, VB)]

        self._transpoze_güncelle()
        self.hız_geçmişi.append(mse)

    # ------------------------------------------------------------ eğitim / kayıt / sağlık
    def öğren(self, giriş: list[float], hedef: list[float],
              diske_yaz: Optional[bool] = None):
        """Tek örnek öğren. diske_yaz=None → her `kaydet_aralığı` adımda yazar."""
        with self._kilit:
            self._ileri_geçiş_iç(giriş)
            self._geri_yayılış_iç(hedef)
            self.adım += 1
            self._son_girişler.append(list(giriş))
            if diske_yaz is None:
                diske_yaz = self.adım % self.kaydet_aralığı == 0
            if diske_yaz:
                self.kaydet()

    def kaydet(self):
        """Ağırlıkları ve durumu geçici dosya üzerinden atomik olarak diske yazar."""
        with self._kilit:
            veri = {
                "ad": self.ad,
                "katmanlar": self.katmanlar,
                "lr": self.lr,
                "momentum": self.momentum,
                "aktivasyon": self.gizli,
                "çıkış_aktivasyon": self.çıkış_akt,
                "kayıp": self.kayıp,
                "l2": self.l2,
                "adım": self.adım,
                "hız_geçmişi": list(self.hız_geçmişi),
                "ağırlıklar": self.ağırlıklar,
                "çeşitler": self.çeşitler,
            }
            geçici_yol = str(self.yol) + ".tmp"
            with open(geçici_yol, "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False)
            os.replace(geçici_yol, str(self.yol))

    def saglik(self, girişler: Optional[list[list[float]]] = None,
               eşik: float = 0.01) -> Optional[dict]:
        """Çökme (collapse) ölçüsü: farklı girişlerde çıkışlar hiç değişmiyorsa
        ağ girişe bakmıyor demektir.

        `girişler` verilmezse son öğrenilen ≤64 giriş kullanılır. Örnek sayısı
        8'den azsa None döner. `çökmüş` = tüm çıkışların std'si `eşik` altında.
        Bekleyen geri yayılışı bozmamak için `aktivasyonlar` geri yüklenir.
        """
        with self._kilit:
            örn = list(girişler) if girişler is not None else list(self._son_girişler)
            if len(örn) < 8:
                return None
            eski = self.aktivasyonlar
            try:
                çıktılar = [self._ileri_geçiş_iç(g) for g in örn]
            finally:
                self.aktivasyonlar = eski
        n, k = len(çıktılar), len(çıktılar[0])
        ort = [sum(c[j] for c in çıktılar) / n for j in range(k)]
        std = [(sum((c[j] - ort[j]) ** 2 for c in çıktılar) / n) ** 0.5
               for j in range(k)]
        return {"örnek": n,
                "çıkış_ort": [round(x, 4) for x in ort],
                "çıkış_std": [round(x, 4) for x in std],
                "çökmüş": max(std) < eşik}

    def rapor(self) -> dict:
        return {
            "ad": self.ad,
            "katmanlar": self.katmanlar,
            "lr": self.lr,
            "son_mse": self.hız_geçmişi[-1] if self.hız_geçmişi else 0.0,
            "öğrenme_sayısı": self.adım,
            "sağlık": self.saglik(),
        }
