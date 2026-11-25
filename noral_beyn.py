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
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import zeka


class NöralBeyn:
    def __init__(self, ad: str, katmanlar: list[int], lr: float = 0.15,
                 momentum: float = 0.9, gizli_aktivasyon: str = "sigmoid",
                 çıkış_aktivasyon: str = "sigmoid", kayıp: str = "mse",
                 l2: float = 0.0, kaydet_aralığı: int = 10,
                 seed: Optional[int] = None):
        self.ad = ad
        self.katmanlar = list(katmanlar)
        self.lr = lr
        self.momentum = momentum
        self.gizli = gizli_aktivasyon        # "sigmoid" | "tanh"
        self.çıkış_akt = çıkış_aktivasyon    # "sigmoid" | "tanh"
        self.kayıp = kayıp                   # "mse" | "ce"
        self.l2 = l2
        self.kaydet_aralığı = max(1, kaydet_aralığı)
        self._rng = random.Random(seed)      # tekrarlanabilirlik: seedli başlatma
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
            w = [[self._rng.uniform(-limit, limit) for _ in range(nout)]
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

    @staticmethod
    def _softmax(logits: list[float]) -> list[float]:
        """Sayısal olarak kararlı softmax (çıkış katmanı bazlı, vektör boyutunda)."""
        if not logits:
            return []
        m = max(logits)
        exps = [math.exp(v - m) for v in logits]
        s = sum(exps)
        if s <= 0.0:
            return [1.0 / len(logits)] * len(logits)
        return [e / s for e in exps]

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
            z = [bj + sum(map(mul, aktif, kol))
                 for bj, kol in zip(b, wt)]
            if akt_türü == "softmax":
                aktif = self._softmax(z)
            else:
                f = math.tanh if akt_türü == "tanh" else self._sigmoid
                aktif = [f(v) for v in z]
            akt.append(aktif)
        self.aktivasyonlar = akt
        return aktif

    def geri_yayılış(self, hedef: list[float]) -> float:
        with self._kilit:
            return self._geri_yayılış_iç(hedef)

    def _geri_yayılış_iç(self, hedef: list[float]) -> float:
        if not self.aktivasyonlar:
            raise RuntimeError("Geri yayılıştan önce ileri_geçiş çağrılmalıdır.")
        çıkış = self.aktivasyonlar[-1]
        if len(hedef) != len(çıkış):
            raise ValueError("hedef boyutu %d, beklenen %d"
                             % (len(hedef), len(çıkış)))

        if self.kayıp == "ce":
            # softmax+CE (ve sigmoid+BCE) ile tutarlı: -dL/dz = t - y.
            delta = [t - y for t, y in zip(hedef, çıkış)]
            kayip_degeri = -sum(
                t * math.log(max(y, 1e-12)) for t, y in zip(hedef, çıkış)
            ) / max(1, len(çıkış))
        elif self.çıkış_akt == "softmax":
            # MSE + softmax: -dL/dz_i = y_i * ((t_i - y_i) + sum_j (y_j - t_j) y_j)
            sapma = sum((y_j - t_j) * y_j for y_j, t_j in zip(çıkış, hedef))
            delta = [y * ((t - y) + sapma) for y, t in zip(çıkış, hedef)]
            kayip_degeri = sum((t - y) ** 2 for t, y in zip(hedef, çıkış)) / max(
                1, len(çıkış)
            )
        elif self.çıkış_akt == "tanh":
            delta = [(t - y) * (1.0 - y * y) for t, y in zip(hedef, çıkış)]
            kayip_degeri = sum((t - y) ** 2 for t, y in zip(hedef, çıkış)) / max(
                1, len(çıkış)
            )
        else:
            delta = [(t - y) * y * (1.0 - y) for t, y in zip(hedef, çıkış)]
            kayip_degeri = sum((t - y) ** 2 for t, y in zip(hedef, çıkış)) / max(
                1, len(çıkış)
            )

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
        self.hız_geçmişi.append(kayip_degeri)
        return kayip_degeri

    # ------------------------------------------------------------ eğitim / kayıt / sağlık
    def backward(self, giriş: list[float], hedef: list[float], **kw) -> float:
        """Geriye uyumluluk: TinyMLP.backward alias'i.

        Test kodları `mlp.backward` referans alabilir; bu metot
        ileri+geri geçişi çalıştırır.
        """
        self._ileri_geçiş_iç(giriş)
        return self._geri_yayılış_iç(hedef)

    def öğren(self, giriş: list[float], hedef: list[float],
              diske_yaz: Optional[bool] = None):
        """Tek örnek öğren. diske_yaz=None → her `kaydet_aralığı` adımda yazar."""
        with self._kilit:
            self.backward(giriş, hedef)
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

    @property
    def W1(self):
        return self.ağırlıklar[0]

    @property
    def b1(self):
        return self.çeşitler[0]

    @property
    def W2(self):
        return self.ağırlıklar[1]

    @property
    def b2(self):
        return self.çeşitler[1]

    @property
    def n_out(self):
        return len(self.ağırlıklar[-1]) if self.ağırlıklar else 0

    @property
    def n_in(self):
        return len(self.ağırlıklar[0]) if self.ağırlıklar else 0

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
            "son_kayip": self.hız_geçmişi[-1] if self.hız_geçmişi else 0.0,
            "öğrenme_sayısı": self.adım,
            "sağlık": self.saglik(),
        }

    def tahmin(self, giriş: list[float]) -> list[float]:
        """İleri geçiş yapıp çıktı olasılıklarını döner (ağırlık güncellemez)."""
        with self._kilit:
            çıkışlar = self._ileri_geçiş_iç(list(giriş))
            # Son katman aktivasyonları çıktıdır; kopyala ki dışarıdan bozulmasın.
            return list(çıkışlar) if çıkışlar else []

    def predict(self, giriş: list[float]) -> list[float]:
        """`tahmin` alias'i (test ve dış arayüz uyumluluğu için)."""
        return self.tahmin(giriş)


# =====================================================================
# ÜST BEYİN (pure Python) — ust_beyn.py'ndaki NumPy bağımlılığı buraya taşındı.
# =====================================================================

# ----------------------------------------------------------------- Komutlar
KOMUT_YOK = None
KOMUT_ACIL_DINLEN = "acil_dinlen"
KOMUT_ACIL_YEM = "acil_yem"
KOMUT_KAPAT_AG = "kapat_ag"
KOMUT_KISITLA_DOSYA = "kisitla_dosya"
KOMUT_GUVENLI_MOD = "guvenli_mod"
KOMUT_SIFIRLA = "sifirla"
KOMUT_ASM_OGREN = "asm_ogren"
KOMUT_KOD_DUZENLE = "kod_duzenle"
KOMUT_GOSSIP = "gossip"
KOMUT_COCUK_OLUSTUR = "cocuk_olustur"
KOMUT_AG_TARA = "ag_tara"

KOMUTLAR = [
    KOMUT_YOK,
    KOMUT_ACIL_DINLEN,
    KOMUT_ACIL_YEM,
    KOMUT_KAPAT_AG,
    KOMUT_KISITLA_DOSYA,
    KOMUT_GUVENLI_MOD,
    KOMUT_SIFIRLA,
    KOMUT_ASM_OGREN,
    KOMUT_KOD_DUZENLE,
    KOMUT_GOSSIP,
    KOMUT_COCUK_OLUSTUR,
    KOMUT_AG_TARA,
]

KOMUT_INDEKSI = {k: i for i, k in enumerate(KOMUTLAR)}

SINYAL_BOYUT = 48
GIZLI_BOYUT = 16
CIKIS_BOYUT = len(KOMUTLAR)  # 12
SINYAL_SURUMU = 3
UST_MODEL_SURUMU = 4
AGIRLIK_YERLESIMI = "giris_cikis"   # W1[girdi][gizli], W2[gizli][çıktı] (NöralBeyn yerel düzeni)

IDX_ENERJI = 0
IDX_ACLIK = 1
IDX_ACI = 2
IDX_SIKILMA = 3
IDX_TEHLIKE = 4
IDX_CANLI = 5
IDX_ANA_BEYIN = 6
IDX_DAMAK = 12
IDX_GUVENLIK = 15
IDX_EKSIK = 17
IDX_ANOMALI = 19
IDX_SOK_BEKLIYOR = 20
IDX_MESAJ_VAR = 21
IDX_SOK_MIKTAR = 22
IDX_OLUM_RISK = 23
IDX_DUNYA_BOZUK = 24
IDX_SURPRIZ = 25
IDX_GOREV = 26


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# =====================================================================
# VSA (Vektör Sembolik Mimari / Hyperdimensional Computing) Yardımcıları
# =====================================================================

def vektor_normalize(v: list[float]) -> list[float]:
    """Vektörü L2 ile normalize eder. Sıfır vektörü geri döndürür."""
    norm = sum(x * x for x in v) ** 0.5
    if norm <= 1e-12:
        return [0.0] * len(v)
    return [x / norm for x in v]


def kosinus_benzerligi(v1: list[float], v2: list[float]) -> float:
    """İki vektör arasındaki kosinüs benzerliği (-1 .. 1)."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    nokta = sum(a * b for a, b in zip(v1, v2))
    norm1 = sum(a * a for a in v1) ** 0.5
    norm2 = sum(b * b for b in v2) ** 0.5
    if norm1 <= 1e-12 or norm2 <= 1e-12:
        return 0.0
    return nokta / (norm1 * norm2)


def kavram_bagla(v1: list[float], v2: list[float]) -> list[float]:
    """İki bağımsız kavramı eleman bazlı çarpar (Binding).
    
    Örnek: V_CPU_YUKSEK ⊗ V_AG_AKTIF = "Dışarıdan Ağ Saldırısı" kavramı.
    Çıktı aynı boyutta kalır veNormalize edilir.
    """
    if len(v1) != len(v2):
        n = min(len(v1), len(v2))
        v1 = v1[:n]
        v2 = v2[:n]
    return vektor_normalize([a * b for a, b in zip(v1, v2)])


def kavram_birlestir(v1: list[float], v2: list[float]) -> list[float]:
    """İki kavramı eleman bazlı toplar (Bundling / Süperpozisyon).
    
    Aynı anda gerçekleşen olayları tek bir sahnede toplar.
    Çıktı aynı boyutta kalır ve Normalize edilir.
    """
    if len(v1) != len(v2):
        n = min(len(v1), len(v2))
        v1 = v1[:n]
        v2 = v2[:n]
    return vektor_normalize([a + b for a, b in zip(v1, v2)])


# ---------------------------------------------------------------- Zamansal kanallar
# MLP girişi (zamansal_kanal=True iken): [ S_t (SINYAL_BOYUT) | ΔS (SINYAL_BOYUT) | E_{t-1} (CIKIS_BOYUT) ].
# Üç katman AYRI slotlardadır; "seviye" (S_t), "değişim" (ΔS) ve "niyet" (E) birbirine
# karışmaz. Varsayılan kapalıdır: MLP girişi eskisi gibi ham S_t (48) kalır.
GIRIS_BOYUT_ZAMANSAL = 2 * SINYAL_BOYUT + CIKIS_BOYUT
DELTA_KAZANC = 1.0   # ΔS yavaş değişen sinyallerde küçük kalırsa buradan ölçeklenir


def zamansal_delta(s_t: List[float], onceki_ham: Optional[List[float]],
                   kazanc: float = DELTA_KAZANC) -> List[float]:
    """ΔS = S_t - S_{t-1} (HAM vektörler). Normalize EDİLMEZ: büyüklük bilgisi korunur.

    İlk tikte (önceki yok) ya da boyut uyuşmazsa sıfır vektör döner. [-1, 1]'e kırpılır.
    """
    n = len(s_t)
    if onceki_ham is None or len(onceki_ham) != n:
        return [0.0] * n
    return [max(-1.0, min(1.0, kazanc * (float(a) - float(b))))
            for a, b in zip(s_t, onceki_ham)]


def paralel_vektor(s_t: List[float], onceki_ham: Optional[List[float]] = None) -> List[float]:
    """Benzerlik/anahtar amaçlı birim vektör: bundle(norm(S_t), norm(ΔS)).

    Yalnızca kosinüs karşılaştırması içindir (kavram hafızası vb.); MLP girişi DEĞİLDİR,
    çünkü normalizasyon mutlak seviye bilgisini yok eder.
    """
    delta = vektor_normalize(zamansal_delta(s_t, onceki_ham, kazanc=1.0))
    return kavram_birlestir(vektor_normalize(list(s_t)), delta)


# ---------------------------------------------------------------- Sahne anahtarı
# Sinyaller [0,1]'de ve çoğu pozitif: ham kosinüs her çifti ~1.0 gösterir (ortak taban).
# Benzerlik, her boyutu KENDİ geçmişine göre standartlaştırılmış (z-skor) sahne üzerinde
# hesaplanır: sahne = [ z (48) | Δ (48) ]. MLP girişi (ham S_t) bundan etkilenmez.
SAHNE_BOYUT = 2 * SINYAL_BOYUT
KAVRAM_ESIK_BIRLESTIR = 0.80   # aynı sahne sayılma eşiği (yazarken)
KAVRAM_ESIK_SEZGI = 0.60       # sezgi için komşu sayılma eşiği (okurken)
KAVRAM_K = 5                   # sezgide kaç en yakın sahne oy verir
KAVRAM_SAYI_TAVAN = 64         # prototip ortalaması bu sayıdan sonra yavaşça kayar
KAVRAM_ODUL_OLU = 0.05         # |ödül| bunun altındaysa "nötr" işaret sınıfı
SEZGI_KAZANC = 0.15            # p_maskeli'ye eklenen sezgi önyargısı ölçeği
SEZGI_LAMBDA = 0.25            # az kanıtta sezgiyi 0'a çeken büzülme
SURPRIZ_OLCEK = 4.0            # tahmin hatası (σ cinsinden L2) -> [0,1] doygunluk ölçeği


def _kirp(v: float, sinir: float) -> float:
    return -sinir if v < -sinir else (sinir if v > sinir else v)


class WelfordNormalizer:
    """Koşan Welford ortalaması/σ'sı ile boyut başına z-skor (saf Python).

    * `isinma` örnekten önce 0 vektörü döner (σ henüz anlamsız).
    * σ, `std_taban` ile tabanlanır. Gerçek journal'da (202 ust_ogren, boşta dönem) canlı
      boyutların σ'sı 1e-4..9e-3: 0.05 gibi bir taban gerçek varyasyonu boğuyor (sahne
      benzerliği >0.6 oranı %14 -> %30). 1e-3 (sensör çözünürlüğü mertebesi) ölü boyuttaki
      1e-5'lik titremenin ±3'e şişmesini engeller, gerçek sapmayı korur. Ölçüm: ızgara
      taban∈{1e-4,1e-3,3e-3,1e-2}; 1e-3 en ayrıştırıcı ve gürültüde en az şişen seçimdi.
    * `pencere` sonrası unutmalı (üstel) Welford: dağılım kayarsa istatistik izler.
    * ±`kirp` σ kırpması (aykırı değer koruması).
    """

    def __init__(self, boyut: int, pencere: int = 5000, isinma: int = 20,
                 std_taban: float = 1e-3, kirp: float = 3.0) -> None:
        self.boyut = int(boyut)
        self.pencere = max(2, int(pencere))
        self.isinma = max(2, int(isinma))
        self.std_taban = float(std_taban)
        self.kirp = float(kirp)
        self.n = 0
        self.mean = [0.0] * self.boyut
        self.m2 = [0.0] * self.boyut

    def _n_etkin(self) -> int:
        return min(self.n, self.pencere)

    def donustur(self, x: List[float]) -> List[float]:
        """İstatistiği DEĞİŞTİRMEDEN z-skor (geçmiş bir vektörü yeniden anahtarlamak için)."""
        if len(x) != self.boyut or self.n < self.isinma:
            return [0.0] * self.boyut
        payda = max(1, self._n_etkin() - 1)
        z: List[float] = []
        for i, val in enumerate(x):
            val = float(val)
            if not math.isfinite(val):
                z.append(0.0)
                continue
            std = max((self.m2[i] / payda) ** 0.5, self.std_taban)
            z.append(_kirp((val - self.mean[i]) / std, self.kirp))
        return z

    def guncelle_ve_donustur(self, x: List[float]) -> List[float]:
        if len(x) != self.boyut:
            return [0.0] * self.boyut
        self.n += 1
        n_e = self._n_etkin()
        unut = 1.0 - 1.0 / self.pencere if self.n > self.pencere else 1.0
        for i, val in enumerate(x):
            val = float(val)
            if not math.isfinite(val):
                val = self.mean[i]
            delta = val - self.mean[i]
            self.mean[i] += delta / n_e
            delta2 = val - self.mean[i]
            self.m2[i] = self.m2[i] * unut + delta * delta2
        return self.donustur(x)

    def to_dict(self) -> Dict[str, Any]:
        return {"n": self.n, "mean": [round(v, 6) for v in self.mean],
                "m2": [round(v, 6) for v in self.m2]}

    def from_dict(self, d: Dict[str, Any]) -> bool:
        try:
            mean = [float(v) for v in d["mean"]]
            m2 = [float(v) for v in d["m2"]]
            if len(mean) != self.boyut or len(m2) != self.boyut:
                return False
            if not all(math.isfinite(v) for v in mean + m2):
                return False
            self.n, self.mean, self.m2 = max(0, int(d["n"])), mean, m2
            return True
        except (KeyError, TypeError, ValueError):
            return False


class CokOlcekliDelta:
    """Δ = EMA_hızlı(z) − EMA_yavaş(z). Tek kare farkı yerine 'ivme ve yön'.

    z zaten σ biriminde olduğundan çıktı da σ cinsindendir; ±`kirp`'e kırpılır.
    İlk örnekte iki EMA da o örnekle başlatılır (sıfırdan başlatma sahte ivme üretirdi).
    hızlı≈son 3 tik, yavaş≈son 20 tik.
    """

    def __init__(self, boyut: int, hizli: float = 0.3, yavas: float = 0.05,
                 kirp: float = 3.0) -> None:
        self.boyut, self.hizli, self.yavas, self.kirp = int(boyut), hizli, yavas, kirp
        self.ema_h: Optional[List[float]] = None
        self.ema_y: Optional[List[float]] = None

    def guncelle(self, z: List[float]) -> List[float]:
        if self.ema_h is None or self.ema_y is None or len(z) != self.boyut:
            self.ema_h, self.ema_y = list(z), list(z)
            return [0.0] * self.boyut
        a, b = self.hizli, self.yavas
        for i, v in enumerate(z):
            self.ema_h[i] = a * v + (1.0 - a) * self.ema_h[i]
            self.ema_y[i] = b * v + (1.0 - b) * self.ema_y[i]
        return [_kirp(h - y, self.kirp) for h, y in zip(self.ema_h, self.ema_y)]

    def to_dict(self) -> Dict[str, Any]:
        return {"h": [round(v, 6) for v in self.ema_h or []],
                "y": [round(v, 6) for v in self.ema_y or []]}

    def from_dict(self, d: Dict[str, Any]) -> bool:
        try:
            h = [float(v) for v in d["h"]]
            y = [float(v) for v in d["y"]]
            if not h and not y:
                return True
            if len(h) != self.boyut or len(y) != self.boyut:
                return False
            self.ema_h, self.ema_y = h, y
            return True
        except (KeyError, TypeError, ValueError):
            return False


class SahneTakipcisi:
    """Ham S_t -> (z, Δ, sahne). Tik başına BİR kez `guncelle`; geri kalan her şey `sahne_bak`."""

    def __init__(self, boyut: int = SINYAL_BOYUT, delta_agirlik: float = 1.0) -> None:
        self.boyut = int(boyut)
        self.delta_agirlik = float(delta_agirlik)
        self.norm = WelfordNormalizer(self.boyut)
        self.delta = CokOlcekliDelta(self.boyut)

    def guncelle(self, s: List[float]) -> Tuple[List[float], List[float], List[float]]:
        z = self.norm.guncelle_ve_donustur(s)
        d = self.delta.guncelle(z)
        return z, d, list(z) + [self.delta_agirlik * v for v in d]

    def sahne_bak(self, s: List[float]) -> List[float]:
        """Mutasyonsuz: eski bir ham vektörü bugünkü istatistikle anahtarlar (Δ bilinmez -> 0)."""
        return self.norm.donustur(s) + [0.0] * self.boyut

    def to_dict(self) -> Dict[str, Any]:
        return {"norm": self.norm.to_dict(), "delta": self.delta.to_dict()}

    def from_dict(self, d: Dict[str, Any]) -> bool:
        try:
            return bool(self.norm.from_dict(d["norm"]) and self.delta.from_dict(d["delta"]))
        except (KeyError, TypeError):
            return False


class DunyaDeltaModeli:
    """(bağlam, UYGULANAN komut) -> beklenen sonraki-tik Δz. Tablolu, üstel ortalama.

    Mevcut `dunya_modeli` beklenen ÖDÜLÜ tutar; bu model beklenen DEĞİŞİMİ tutar. Hamle
    sonrası gerçek Δz ile beklenen Δz arasındaki fark "hamlem işe yaramadı / dünya beklediğim
    gibi tepki vermedi" sinyalidir. Kendine gönderme döngüsünü kırmak için sürpriz boyutu
    (IDX_SURPRIZ) hataya katılmaz.
    """

    def __init__(self, boyut: int = SINYAL_BOYUT, alfa: float = 0.1,
                 dislanan: Tuple[int, ...] = (IDX_SURPRIZ,), azami_anahtar: int = 512) -> None:
        self.boyut, self.alfa = int(boyut), float(alfa)
        self.dislanan = set(dislanan)
        self.azami_anahtar = int(azami_anahtar)
        self.ort: Dict[str, List[float]] = {}
        self.sayi: Dict[str, int] = {}

    @staticmethod
    def _anahtarlar(bag: str, komut: int) -> Tuple[str, str]:
        return "%s|%d" % (bag, komut), "*|%d" % komut

    def tahmin(self, bag: str, komut: int) -> List[float]:
        a, b = self._anahtarlar(bag, komut)
        if self.sayi.get(a, 0) >= 3:
            return self.ort[a]
        if b in self.ort:
            return self.ort[b]
        return [0.0] * self.boyut

    def guncelle_ve_hata(self, bag: str, komut: int, gercek_dz: List[float]) -> float:
        """Hatayı (σ cinsinden L2) ÖNCE hesaplar, sonra modeli günceller."""
        if len(gercek_dz) != self.boyut:
            return 0.0
        bek = self.tahmin(bag, komut)
        hata = math.sqrt(sum((g - b) ** 2 for i, (g, b) in enumerate(zip(gercek_dz, bek))
                             if i not in self.dislanan))
        for anahtar in self._anahtarlar(bag, komut):
            n = self.sayi.get(anahtar, 0) + 1
            if anahtar not in self.ort and len(self.ort) >= self.azami_anahtar:
                continue
            self.sayi[anahtar] = n
            a = max(self.alfa, 1.0 / n)
            ort = self.ort.setdefault(anahtar, [0.0] * self.boyut)
            for i, g in enumerate(gercek_dz):
                ort[i] += a * (g - ort[i])
        return hata

    @staticmethod
    def hata_surprize(hata: float) -> float:
        return 1.0 - math.exp(-max(0.0, hata) / SURPRIZ_OLCEK)

    def to_dict(self) -> Dict[str, Any]:
        return {"ort": {k: [round(v, 5) for v in vec] for k, vec in self.ort.items()},
                "sayi": dict(self.sayi)}

    def from_dict(self, d: Dict[str, Any]) -> bool:
        try:
            ort = {str(k): [float(v) for v in vec] for k, vec in d["ort"].items()}
            if any(len(v) != self.boyut or not all(math.isfinite(x) for x in v)
                   for v in ort.values()):
                return False
            self.ort = ort
            self.sayi = {str(k): int(v) for k, v in (d.get("sayi") or {}).items() if k in ort}
            return True
        except (KeyError, TypeError, ValueError, AttributeError):
            return False


def _softmax_python(logits: List[float]) -> List[float]:
    if not logits:
        return []
    m = max(logits)
    exps = [math.exp(v - m) for v in logits]
    s = sum(exps)
    if s <= 0.0:
        return [1.0 / len(logits)] * len(logits)
    return [e / s for e in exps]


# ----------------------------------------------------------------- Sinyal toplayıcı (pure Python)
def topla_sinyalleri(drives, mind, dam, guv, surec,
                     door_msgs=None, olum=None, context="start",
                     feats_damak=None, E=None, H=None,
                     sarsinti=0.0, yemek_var=False,
                     gorev_aktif=False, surpriz=0.0,
                     dunya_bozuk=False, olum_feats=None,
                     cpu_yuk=0.0, proses_norm=0.0,
                     disk_yuzde_norm=0.0, bellek_yuzde_norm=0.0,
                     usb_cihaz_norm=0.0, usb_keşif_bonusu=0.0,
                     ag_baglanti_norm=0.0, insan_var=False,
                     sistem_saati_norm=0.0,
                     disk_baski=0.0, bellek_baski=0.0,
                     beden_baski=0.0, asm_ogren=False,
                     shock_pending=0.0, mesaj_var=0.0, shock_miktar=0.0,
                     onceki_sinyal: Optional[List[float]] = None,
                     onceki_niyet: Optional[List[float]] = None) -> List[float]:
    """Tüm alt sistemlerden tek bir SINYAL_BOYUT'luk vektör üretir (pure Python)."""
    e_cap = max(1.0, float(getattr(drives, "energy_cap", 150.0)))
    energy = _clamp01(float(getattr(drives, "energy", 50)) / e_cap)
    hunger = _clamp01(float(getattr(drives, "hunger", 10)) / 100.0)
    pain = _clamp01(float(drives.pain())) if hasattr(drives, "pain") else 0.0
    sikilma = _clamp01(float(getattr(drives, "sikilma", 0.0)))
    in_danger = 1.0 if getattr(drives, "in_danger", False) else 0.0
    alive = 1.0 if getattr(drives, "alive", True) else 0.0

    if mind is not None:
        try:
            feats = mind.features("")
            scores = [sum(mind._get(f, a) for f in feats) for a in mind.ACTIONS]
            srt = sorted(scores, reverse=True) if scores else [0.0, 0.0]
            brain_max = float(srt[0])
            brain_min = float(srt[-1])
            brain_marj = float(srt[0] - srt[1]) if len(srt) > 1 else 0.0
            brain_eps = float(getattr(mind, "epsilon", 0.35))
            brain_lr = float(getattr(mind, "lr", 0.12))
            brain_links = float(len(getattr(mind, "w", {}))) / 1000.0
        except Exception:
            brain_max = brain_min = brain_marj = 0.0
            brain_eps = brain_lr = 0.0
            brain_links = 0.0
    else:
        brain_max = brain_min = brain_marj = 0.0
        brain_eps = brain_lr = 0.0
        brain_links = 0.0

    if dam is not None and feats_damak:
        try:
            dam_tahmin = float(dam.tahmin(feats_damak))
            dam_base = float(dam.global_sum / max(1, dam.global_n))
            dam_dens = float(min(dam.samples, 10000)) / 10000.0
        except Exception:
            dam_tahmin = dam_base = dam_dens = 0.0
    else:
        dam_tahmin = dam_base = dam_dens = 0.0

    if guv is not None:
        try:
            guv_karar, guv_puan = guv.karar_ver(
                float(E or getattr(drives, "energy", 50)),
                float(H or getattr(drives, "hunger", 10)),
                float(sarsinti), bool(yemek_var))
            guv_karar_v = 1.0 if guv_karar == "uygula" else 0.0
        except Exception:
            guv_karar_v = 0.0
            guv_puan = 0.0
    else:
        guv_karar_v = 0.0
        guv_puan = 0.0

    if surec is not None:
        eksik_n = float(len(getattr(surec, "eksik", [])))
        yeni_n = float(len(getattr(surec, "yeni", [])))
        toplam = float(getattr(surec, "ornek", 1) or 1)
        anomaly = (eksik_n + yeni_n) / max(1.0, toplam)
        anomaly = _clamp01(max(anomaly, float(getattr(surec, "degisim_skoru", 0.0))))
    else:
        eksik_n = 0.0
        yeni_n = 0.0
        anomaly = 0.0

    olum_risk = 0.0
    if olum is not None and olum_feats is not None:
        try:
            _skorlar = olum.kategori_skor(list(olum_feats))
            if _skorlar:
                _en_iyi = max(_skorlar.values())
                if _en_iyi > -1e8:
                    _sk = list(_skorlar.values())
                    _m = max(_sk)
                    _p = [math.exp(v - _m) for v in _sk]
                    _ps = sum(_p)
                    _p = [v / max(1e-12, _ps) for v in _p]
                    olum_risk = _clamp01(max(_p))
        except Exception:
            olum_risk = 0.0

    dunya_bozuk_v = 1.0 if dunya_bozuk else 0.0
    surpriz_v = _clamp01(surpriz / 5.0)
    gorev_v = 1.0 if gorev_aktif else 0.0

    mood = getattr(drives, "mood", None) or {}
    mood_mutluluk = float(mood.get("mutluluk", 0.5))
    mood_korku = float(mood.get("korku", 0.0))
    mood_merak = float(mood.get("merak", 0.3))

    ctx_map = {"start": 0, "door": 1, "act": 2, "eat": 3,
               "console": 4, "rest": 5}
    ctx_vec = [0.0] * 6
    if context in ctx_map:
        ctx_vec[ctx_map[context]] = 1.0

    cpu_yuk = _clamp01(cpu_yuk)
    proses_norm = _clamp01(proses_norm)
    disk_yuzde_norm = _clamp01(disk_yuzde_norm)
    bellek_yuzde_norm = _clamp01(bellek_yuzde_norm)
    usb_cihaz_norm = _clamp01(usb_cihaz_norm)
    usb_keşif_bonusu = _clamp01(usb_keşif_bonusu)
    ag_baglanti_norm = _clamp01(ag_baglanti_norm)
    sistem_saati_norm = _clamp01(sistem_saati_norm)
    disk_baski = _clamp01(disk_baski)
    bellek_baski = _clamp01(bellek_baski)
    beden_baski = _clamp01(beden_baski)
    insan_var_v = 1.0 if insan_var else 0.0
    asm_ogren_v = 1.0 if asm_ogren else 0.0

    v = [
        energy, hunger, pain, sikilma, in_danger, alive,
        brain_max, brain_min, brain_marj,
        brain_eps, brain_lr, brain_links,
        dam_tahmin, dam_base, dam_dens,
        guv_karar_v, guv_puan,
        eksik_n / 10.0, yeni_n / 10.0, anomaly,
        shock_pending, mesaj_var, shock_miktar,
        olum_risk,
        dunya_bozuk_v, surpriz_v, gorev_v,
    ] + ctx_vec + [mood_mutluluk, mood_korku, mood_merak,
                   cpu_yuk, proses_norm,
                   disk_yuzde_norm, bellek_yuzde_norm,
                   usb_cihaz_norm, usb_keşif_bonusu,
                   ag_baglanti_norm, insan_var_v,
                   sistem_saati_norm,
                   disk_baski, bellek_baski, beden_baski,
                   asm_ogren_v]

    while len(v) < SINYAL_BOYUT:
        v.append(0.0)
    s_t = v[:SINYAL_BOYUT]

    # onceki_sinyal / onceki_niyet geriye dönük uyumluluk için kabul edilir ama KULLANILMAZ:
    # her zaman HAM S_t döner. Zamansal kanallar (ΔS, E_{t-1}) NöralUstBeyn.zamansal_guncelle()
    # içinde hesaplanır; benzerlik anahtarı için paralel_vektor() vardır.
    return s_t


# =====================================================================
# NöralUstBeyn — Pure Python üst beyin (UstBeyn arayüzü, NumPy yok)
# =====================================================================

class NöralUstBeyn:
    """NöralBeyn MLP'yi sarmalayan pure-Python üst beyin.

    Tüm karar mantığı (action masking, güven eşiği, doğrulama puanı,
    override ömrü, ASM entegrasyonu, kalıcılık) burada pure Python ile
    uygulanmıştır. ust_beyn.py'deki NumPy bağımlılığı buradan kaldırıldı.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None,
                 root: Optional[Path] = None,
                 seed: int = 7,
                 ag_beyin: Any = None,
                 zamansal_kanal: bool = False) -> None:
        self.cfg = cfg or {}
        self.root = Path(root or Path(__file__).resolve().parent)
        self.seed = 7 if seed is None else seed
        self.rng = random.Random(self.seed)
        self.ag_beyin = ag_beyin
        self._son_scan_odulu = 0.0
        self._son_scan_tik = 0
        self._scan_sinyal: Optional[List[float]] = None
        # Öz hedef köprüsü (hedef_kopru.HedefKopru): organism.py bağlar; None ise etkisiz.
        self.hedef_kopru: Any = None
        self.last_hedef_kopru: Optional[Dict[int, float]] = None

        # Zamansal kanal (ΔS + E_{t-1}) MLP girişine ayrı slotlar olarak eklenir. Varsayılan kapalı.
        self.zamansal_kanal = bool(zamansal_kanal or self.cfg.get("zamansal_kanal", False))
        self.giris_boyutu = GIRIS_BOYUT_ZAMANSAL if self.zamansal_kanal else SINYAL_BOYUT
        self.mlp = NöralBeyn(
            "ust", [self.giris_boyutu, GIZLI_BOYUT, CIKIS_BOYUT],
            lr=0.15, momentum=0.9, seed=self.seed,
            çıkış_aktivasyon="softmax", kayıp="ce",
        )

        self.epsilon = 0.15
        self.epsilon_min = 0.05
        self.epsilon_max = 0.60
        self.epsilon_decay = 0.99985
        self.eps_base = 0.15
        self.eps_sikilma_karani = 0.4
        self.eps_agri_karani = 0.7

        self.guven_esigi = 0.45
        self.marj_olcek = 0.15
        self.kanit_çarpanı = 0.35
        self.dogrulama_esigi = 0.35

        self.dogrulama = [0.0] * CIKIS_BOYUT
        self.dogrulama_bağlam: Dict[Tuple[int, str], float] = {}

        self.sure = 0
        self.sure_azami = 0
        self.son_komut = KOMUT_YOK
        self.son_idx = 0
        self.reddedilen = 0

        self.RED_SERI_MAKS = 1
        self.redd_serisi = [0] * CIKIS_BOYUT
        self.redd_cooldown = [0] * CIKIS_BOYUT

        self.sifirla_son_tik = 0
        self.SIFIRLA_ARALIK = 10
        self.sifirla_noop_serisi = 0

        self.samples = 0
        self.tik = 0
        self.secim_sayilari = [0] * CIKIS_BOYUT
        self.reddedilen_sayilari = [0] * CIKIS_BOYUT
        self.odul_gecmisi: List[float] = []
        self.kisa_hafiza: deque = deque(maxlen=64)
        self.hata_kategorisi: Dict[str, int] = {}
        self.journal = SimpleNamespace(log=lambda *args, **kwargs: None)
        self.last_confidence = 0.0
        self.last_komut_idx = KOMUT_INDEKSI[KOMUT_YOK]

        self.dunya_modeli: Dict[str, Dict[int, List[float]]] = {}
        self.kimlik = {
            "ad": "Aelaan",
            "ilkeler": ["kanita_bagli_ogrenme", "once_hayatta_kalma", "guvenlik_sinirlari"],
        }
        self.deger_profili = {
            "hayatta_kalma": 1.0,
            "kanit": 0.9,
            "kesif": 0.35,
            "otonomi": 0.6,
        }
        self.mizac = {"temkin": 0.35, "merak": 0.35, "sebat": 0.5}
        self.uzun_hafiza = {
            "toplam_sonuc": 0,
            "olumlu_sonuc": 0,
            "olumsuz_sonuc": 0,
            "odul_toplami": 0.0,
            "komutlar": {},
        }
        self.ozben_modeli = {
            "durum": "hazir",
            "istikrar": 0.0,
            "hata_orani": 0.0,
            "ortalama_odul": 0.0,
            "guven_duyarliligi": 0.0,
        }

        self._asm_öğrenici: Any = None
        # ---------- Yeni: VSA (Vektör Sembolik Mimari) Zamansal Bağlam ----------
        self.onceki_sinyal: Optional[List[float]] = None   # S_{t-1}
        self.onceki_niyet: Optional[List[float]] = None    # E_{t-1} (önceki çıktı dağılımı, CIKIS_BOYUT)
        self.son_delta: List[float] = [0.0] * SINYAL_BOYUT  # bu tikin ΔS'i (ham S_t - ham S_{t-1})
        self.son_niyet: List[float] = [0.0] * CIKIS_BOYUT   # bu tikin E_{t-1}'i (tik başında dondurulur)
        self.son_paralel: Optional[List[float]] = None      # benzerlik anahtarı (MLP girişi değil)
        # ---------- Yeni: Kavram Hafızası (Associative Memory) ----------
        # {"sinyal": [48 float], "komut": int, "odul": float, "etiket": str}
        self.kavram_prototipi: List[Dict[str, Any]] = []
        self.kavram_max = 256
        # ---------- Sahne anahtarı (z-skor + çok ölçekli Δ), sezgi ve ΔS dünya modeli ----------
        # zamansal_v2: MLP'nin ΔS/E slotlarına çok ölçekli Δ (÷3) ve UYGULANAN eylemin
        # one-hot'unu verir. Yalnızca zamansal_kanal açıkken anlamlıdır; kapalıysa eski sözleşme.
        self.zamansal_v2 = bool(self.cfg.get("zamansal_v2", False))
        self.surpriz_dunya_delta = bool(self.cfg.get("surpriz_dunya_delta", True))
        self.sahne_takip = SahneTakipcisi()
        self.dunya_delta = DunyaDeltaModeli()
        self.son_z: List[float] = [0.0] * SINYAL_BOYUT
        self.son_delta_z: List[float] = [0.0] * SINYAL_BOYUT   # EMA_hızlı − EMA_yavaş (σ)
        self.son_sahne: List[float] = [0.0] * SAHNE_BOYUT
        self.son_eylem_onehot: List[float] = [0.0] * CIKIS_BOYUT   # t-1'de UYGULANAN komut
        self.son_tahmin_hatasi = 0.0     # σ cinsinden L2: gerçek Δz − beklenen Δz
        self.son_surpriz = 0.0           # [0,1]; sonraki tikin IDX_SURPRIZ girdisini besler
        self.last_sezgi: Optional[Dict[int, float]] = None
        self._sahne_onbellek: deque = deque(maxlen=8)   # (ham S tuple, sahne): ogren() için
        self._bekleyen_gecis: Optional[Dict[str, Any]] = None

        self.eylem_katalogu = {
            "bilgi_topla": {"risk": 0.15, "cost": 0.20, "gain": 0.75, "requires_verification": False},
            "dosya_tara": {"risk": 0.25, "cost": 0.30, "gain": 0.85, "requires_verification": False},
            "network_tara": {"risk": 0.45, "cost": 0.50, "gain": 0.90, "requires_verification": True},
            "asm_ogren": {"risk": 0.55, "cost": 0.65, "gain": 0.95, "requires_verification": True},
            "komut_ver": {"risk": 0.70, "cost": 0.55, "gain": 0.80, "requires_verification": True},
            "dogrula": {"risk": 0.10, "cost": 0.30, "gain": 0.85, "requires_verification": False},
        }
        self.eylem_bilgi: Dict[str, Dict[str, Any]] = {}

        self._load()
        self._mlp_girisini_uydur()

    # --------------------------------------------------------------- Bağlam

    def baglam_anahtari(self, sinyal_vektor: List[float]) -> str:
        if sinyal_vektor is None:
            return "genel"
        x = list(sinyal_vektor)
        if len(x) <= IDX_ACLIK:
            return "genel"
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                   (len(x) > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0 if len(x) > IDX_MESAJ_VAR else False)
        bit = (1 if acik else 0) | (2 if tehlike else 0) | (4 if mesaj else 0)
        return "b%d" % bit

    def komut_baglam_anahtari(self, komut_idx: int,
                              sinyal_vektor: List[float]) -> str:
        """Komuta özgü bağlam anahtarı — kanıt biriktirmenin anahtarı.

        Genel bit maskesi (açlık|tehlike|mesaj) kanıtı yanlış yere böler.
        Örnek: "acil_yem" yalnızca açlıktadir; tehlike/mesaj onun ön
        koşulu değildir. Kanıt, komutun ön koşulu üzerinden
        sınıflandırılmalıdır.
        """
        if sinyal_vektor is None:
            return f"{komut_idx}:genel"
        x = list(sinyal_vektor)
        if len(x) <= IDX_ACLIK:
            return f"{komut_idx}:genel"
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                   (len(x) > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0 if len(x) > IDX_MESAJ_VAR else False)
        sok = (float(x[IDX_SOK_BEKLIYOR]) > 0.0 if len(x) > IDX_SOK_BEKLIYOR else False)
        ki = KOMUT_INDEKSI
        if komut_idx == ki[KOMUT_ACIL_YEM]:
            return f"{komut_idx}:acik" if acik else f"{komut_idx}:acik_yok"
        if komut_idx in (ki[KOMUT_ACIL_DINLEN], ki[KOMUT_GUVENLI_MOD]):
            return f"{komut_idx}:tehlike" if tehlike else f"{komut_idx}:tehlike_yok"
        if komut_idx == ki[KOMUT_KAPAT_AG]:
            return f"{komut_idx}:tehlike" if (tehlike or sok) else f"{komut_idx}:sakin"
        if komut_idx == ki[KOMUT_KISITLA_DOSYA]:
            return f"{komut_idx}:tehlike" if (mesaj or tehlike) else f"{komut_idx}:sakin"
        if komut_idx == ki[KOMUT_AG_TARA]:
            return f"{komut_idx}:genel"
        # Bağlamdan bağımsız komutlar.
        return f"{komut_idx}:genel"

    def komut_uygun_mu(self, komut_idx: int,
                       sinyal_vektor: List[float]) -> bool:
        if sinyal_vektor is None:
            return True
        x = list(sinyal_vektor)
        if len(x) <= IDX_ACLIK:
            return True
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                   (len(x) > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0 if len(x) > IDX_MESAJ_VAR else False)
        sok = (float(x[IDX_SOK_BEKLIYOR]) > 0.0 if len(x) > IDX_SOK_BEKLIYOR else False)
        ki = KOMUT_INDEKSI
        if komut_idx == ki[KOMUT_ACIL_YEM]:
            return acik
        if komut_idx in (ki[KOMUT_ACIL_DINLEN], ki[KOMUT_GUVENLI_MOD]):
            return tehlike
        if komut_idx == ki[KOMUT_KAPAT_AG]:
            return tehlike or sok
        if komut_idx == ki[KOMUT_KISITLA_DOSYA]:
            return mesaj or tehlike
        if komut_idx == ki[KOMUT_AG_TARA]:
            # Yalnızca yapılacak tarama işi varsa uygun (ag_beyin.next_due_in <= 0).
            # Eskiden "her zaman uygun"du ve ödüllü tarama sürekli tekrarlanıyordu.
            if getattr(self, "ag_beyin", None) is None:
                return True
            return self.scan_hazir_mi()
        return True

    # --------------------------------------------------------------- Zamansal kanallar
    def zamansal_guncelle(self, s_ham: List[float]) -> None:
        """Tik başına BİR kez, sec()'ten ÖNCE çağrılır. `s_ham` HAM S_t olmalıdır.

        ΔS'i hesaplar, E_{t-1}'i (önceki tikte sec()'in ürettiği dağılım) dondurur ve ham
        S_t'yi bir sonraki tik için saklar. Saklanan hep ham vektördür.
        """
        s = [float(v) for v in s_ham]
        if len(s) != SINYAL_BOYUT:
            return
        onceki = getattr(self, "onceki_sinyal", None)
        self.son_delta = zamansal_delta(s, onceki)
        niyet = getattr(self, "onceki_niyet", None)
        if niyet is None or len(niyet) != CIKIS_BOYUT:
            niyet = [0.0] * CIKIS_BOYUT
        self.son_niyet = [float(v) for v in niyet]
        self.son_paralel = paralel_vektor(s, onceki)   # eski anahtar; hafıza artık son_sahne kullanır
        self.onceki_sinyal = s
        self._sahne_guncelle(s)

    # --------------------------------------------------------------- Sahne / sürpriz
    def _takip(self) -> SahneTakipcisi:
        tr = getattr(self, "sahne_takip", None)       # test/yan sınıflar __init__'i atlayabilir
        if tr is None:
            tr = self.sahne_takip = SahneTakipcisi()
        return tr

    def _dunya_delta_al(self) -> DunyaDeltaModeli:
        dm = getattr(self, "dunya_delta", None)
        if dm is None:
            dm = self.dunya_delta = DunyaDeltaModeli()
        return dm

    def _sahne_guncelle(self, s: List[float]) -> None:
        """z-skor, çok ölçekli Δ ve sahne anahtarı; önceki tikin hamlesinin tahmin hatası."""
        z, d, sahne = self._takip().guncelle(s)
        self.son_z, self.son_delta_z, self.son_sahne = z, d, sahne
        if getattr(self, "_sahne_onbellek", None) is None:
            self._sahne_onbellek = deque(maxlen=8)
        self._sahne_onbellek.append((tuple(s), sahne))

        bek = getattr(self, "_bekleyen_gecis", None)
        if bek is not None and bek.get("eylem") is not None and len(bek["z"]) == len(z):
            gercek = [_kirp(a - b, 3.0) for a, b in zip(z, bek["z"])]
            hata = self._dunya_delta_al().guncelle_ve_hata(bek["bag"], bek["eylem"], gercek)
            self.son_tahmin_hatasi = float(hata)
            self.son_surpriz = DunyaDeltaModeli.hata_surprize(hata)
            oh = [0.0] * CIKIS_BOYUT
            if 0 <= bek["eylem"] < CIKIS_BOYUT:
                oh[bek["eylem"]] = 1.0
            self.son_eylem_onehot = oh
        else:
            self.son_tahmin_hatasi, self.son_surpriz = 0.0, 0.0
            self.son_eylem_onehot = [0.0] * CIKIS_BOYUT
        self._bekleyen_gecis = {"z": list(z), "bag": self.baglam_anahtari(s), "eylem": None}

    def eylem_uygulandi(self, komut_idx: int) -> None:
        """Bu tikte GERÇEKTEN uygulanan komut (reddedilme/ε-keşif sonrası). decision.idx_ust'u verin.

        sec()'in softmax dağılımı yerine bu kullanılır: model 'şunu istedim' dese de
        reddedilen/keşfedilen hamle farklı olabilir ve dünya onun sonucuna tepki verir.
        """
        bek = getattr(self, "_bekleyen_gecis", None)
        if bek is not None:
            bek["eylem"] = int(komut_idx)

    def _sahne_icin(self, x: List[float]) -> List[float]:
        """Ham S_t (48) -> sahne (96). Bu tikin vektörüyse önbellekteki (Δ'lı) sahne, değilse
        bugünkü istatistikle mutasyonsuz anahtar (Δ=0)."""
        if len(x) == SAHNE_BOYUT:
            return [float(v) for v in x]
        anahtar = tuple(float(v) for v in x)
        for ham, sahne in reversed(getattr(self, "_sahne_onbellek", None) or ()):
            if ham == anahtar:
                return sahne
        return self._takip().sahne_bak([float(v) for v in x])

    def _mlp_girisini_uydur(self) -> None:
        """MLP'nin giriş katmanını `giris_boyutu` ile eşitler (yüklemeden sonra çağrılır).

        NöralBeyn kendi `nn_ust.json` dosyasındaki `katmanlar`ı istenen boyutun ÜSTÜNE yazar;
        zamansal kanal açılıp kapanınca boyut kaydı ile gerçek ağırlıklar ayrışırdı. Büyürken
        yeni giriş satırları sıfırdan başlar (mevcut davranış korunur), küçülürken fazla
        zamansal satırlar bırakılır.
        """
        g = getattr(self, "giris_boyutu", SINYAL_BOYUT)
        W1 = self.mlp.ağırlıklar[0]
        if len(W1) == SINYAL_BOYUT and g == GIRIS_BOYUT_ZAMANSAL:
            self.mlp.ağırlıklar[0] = [list(r) for r in W1] + [
                [0.0] * len(W1[0]) for _ in range(g - len(W1))]
        elif len(W1) == GIRIS_BOYUT_ZAMANSAL and g == SINYAL_BOYUT:
            self.mlp.ağırlıklar[0] = [list(r) for r in W1][:SINYAL_BOYUT]
        if len(self.mlp.ağırlıklar[0]) == g and self.mlp.katmanlar[0] != g:
            self.mlp.katmanlar[0] = g
            self.mlp._hız_sıfırla()
            self.mlp._transpoze_güncelle()

    def _mlp_girisi(self, x: List[float], zamansal: bool = True) -> List[float]:
        """MLP girişi. Kanal kapalıysa x aynen döner (eski davranış)."""
        if not getattr(self, "zamansal_kanal", False):
            return x
        if zamansal and getattr(self, "zamansal_v2", False):
            # v2: ΔS = çok ölçekli Δ (σ, ÷3 -> [-1,1]); E = UYGULANAN eylemin one-hot'u.
            d = [v / 3.0 for v in (getattr(self, "son_delta_z", None) or [0.0] * SINYAL_BOYUT)]
            e = getattr(self, "son_eylem_onehot", None) or [0.0] * CIKIS_BOYUT
        elif zamansal:
            d = getattr(self, "son_delta", None) or [0.0] * SINYAL_BOYUT
            e = getattr(self, "son_niyet", None) or [0.0] * CIKIS_BOYUT
        else:
            d, e = [0.0] * SINYAL_BOYUT, [0.0] * CIKIS_BOYUT
        return list(x) + list(d) + list(e)

    # --------------------------------------------------------------- Kavram Hafızası (sahne)
    # Prototip = {"sahne": [96], "komut": int, "odul": float, "sayi": int, "son_tik": int}.
    # Anahtar ham S_t DEĞİL, z-skorlu sahne [z | Δ]; ödül hafızaya HAM (süssüz) yazılır.
    @staticmethod
    def _odul_sinifi(odul: float) -> int:
        return 1 if odul > KAVRAM_ODUL_OLU else (-1 if odul < -KAVRAM_ODUL_OLU else 0)

    def kavram_hafizasi_sorgula(self, sinyal_vektor: List[float],
                                komut_idx: int) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Aynı komutun en benzer sahne prototipi. (benzerlik, prototip); eşik uygulanmaz.

        `sinyal_vektor` ham S_t (48) ya da sahne (96) olabilir. Karar için `kavram_sezgi`.
        """
        protos = getattr(self, "kavram_prototipi", None)
        if not protos:
            return 0.0, None
        sahne = self._sahne_icin(list(sinyal_vektor))
        if len(sahne) != SAHNE_BOYUT:
            return 0.0, None
        en_s, en_p = 0.0, None
        for proto in protos:
            if proto.get("komut") != komut_idx:
                continue
            b = kosinus_benzerligi(sahne, proto["sahne"])
            if b > en_s:
                en_s, en_p = b, proto
        return en_s, en_p

    def kavram_kaydet(self, sinyal_vektor: List[float],
                      komut_idx: int, odul: float,
                      etiket: Optional[str] = None) -> None:
        """Sahneyi ödülüyle hafızaya yazar.

        Aynı komut + benzerlik > 0.80 + AYNI ödül işareti (olumlu / nötr / olumsuz) ise sayıyla
        ağırlıklı ortalamayla birleştirir; aksi halde yeni prototip açar. Olumlu ve olumsuz
        durumlar artık tek centroidde erimez. Kapasite dolunca en düşük |ödül|·sayı'lı
        (eşitlikte en eski) prototip atılır. Isınma tiklerinde (sahne ≈ 0) kayıt yapılmaz.
        """
        sahne = self._sahne_icin(list(sinyal_vektor))
        if len(sahne) != SAHNE_BOYUT or sum(v * v for v in sahne) < 1e-9:
            return
        odul = float(odul)
        sinif = self._odul_sinifi(odul)
        tik = int(getattr(self, "tik", 0))
        protos = getattr(self, "kavram_prototipi", None)
        if protos is None:
            protos = self.kavram_prototipi = []

        en_s, en_p = 0.0, None
        for proto in protos:
            if proto.get("komut") != komut_idx:
                continue
            if self._odul_sinifi(float(proto.get("odul", 0.0))) != sinif:
                continue
            b = kosinus_benzerligi(sahne, proto["sahne"])
            if b > en_s:
                en_s, en_p = b, proto

        if en_p is not None and en_s > KAVRAM_ESIK_BIRLESTIR:
            n = min(int(en_p.get("sayi", 1)), KAVRAM_SAYI_TAVAN)
            en_p["sahne"] = [(e * n + y) / (n + 1) for e, y in zip(en_p["sahne"], sahne)]
            en_p["odul"] = (float(en_p["odul"]) * n + odul) / (n + 1)
            en_p["sayi"] = int(en_p.get("sayi", 1)) + 1
            en_p["son_tik"] = tik
            if etiket:
                en_p["etiket"] = etiket
            return

        protos.append({"sahne": list(sahne), "komut": int(komut_idx), "odul": odul,
                       "etiket": etiket or "", "sayi": 1, "son_tik": tik})
        if len(protos) > self.kavram_max:
            # Yeni eklenen hariç; en düşük |ödül|·sayı, eşitlikte en eski.
            kurban = min(range(len(protos) - 1),
                         key=lambda i: (abs(float(protos[i]["odul"])) * int(protos[i].get("sayi", 1)),
                                        int(protos[i].get("son_tik", 0))))
            protos.pop(kurban)

    def kavram_sezgi(self, sinyal_vektor: List[float], maske: Optional[List[bool]] = None,
                     k: int = KAVRAM_K, esik: float = KAVRAM_ESIK_SEZGI) -> Dict[int, float]:
        """Sezgi: bu sahneye en çok benzeyen k sahneden, HER komut için beklenen ödül.

        Tüm komutların prototipleri komşu olabilir ("bu sahnede hangi komut ne getirdi").
        Komşu oyu = (benzerlik−eşik)/(1−eşik) · min(sayı, 8); kanıt azsa λ ile 0'a büzülür.
        Döner: {komut_idx: [-1,1] beklenen ödül}; yalnızca maskeli-uygun, `yok` hariç komutlar.
        """
        protos = getattr(self, "kavram_prototipi", None)
        if not protos:
            return {}
        sahne = self._sahne_icin(list(sinyal_vektor))
        if len(sahne) != SAHNE_BOYUT:
            return {}
        komsular = []
        for proto in protos:
            b = kosinus_benzerligi(sahne, proto["sahne"])
            if b > esik:
                komsular.append((b, proto))
        komsular.sort(key=lambda t: -t[0])
        yok = KOMUT_INDEKSI[KOMUT_YOK]
        toplam: Dict[int, float] = {}
        agirlik: Dict[int, float] = {}
        for b, proto in komsular[:max(1, int(k))]:
            c = int(proto["komut"])
            if c == yok or (maske is not None and not maske[c]):
                continue
            w = (b - esik) / (1.0 - esik) * min(int(proto.get("sayi", 1)), 8)
            toplam[c] = toplam.get(c, 0.0) + w * float(proto["odul"])
            agirlik[c] = agirlik.get(c, 0.0) + w
        return {c: toplam[c] / (agirlik[c] + SEZGI_LAMBDA) for c in toplam}

    def uygun_maske(self, sinyal_vektor: List[float],
                    yok_da_maskeli: bool = True) -> List[bool]:
        maske = [False] * CIKIS_BOYUT
        for i in range(CIKIS_BOYUT):
            if yok_da_maskeli and i == KOMUT_INDEKSI[KOMUT_YOK]:
                continue
            if self.redd_cooldown[i] > 0:
                self.redd_cooldown[i] = max(0, self.redd_cooldown[i] - 1)
                continue
            if self.komut_uygun_mu(i, sinyal_vektor):
                maske[i] = True
        if not any(maske):
            maske[KOMUT_INDEKSI[KOMUT_YOK]] = True
        return maske

    def _guven_hesapla(self, probs: List[float], idx: int) -> float:
        if len(probs) < 2:
            return float(probs[idx]) if idx < len(probs) else 0.0
        p1 = float(probs[idx])
        rakip = [float(p) for j, p in enumerate(probs) if j != idx]
        p2 = max(rakip) if rakip else 0.0
        marj = max(0.0, p1 - p2)
        return float(min(1.0, marj / self.marj_olcek))

    def _kaydet_hata(self, kategori: str, komut_indeksi: int,
                     sinyal_vektor: Optional[List[float]]) -> None:
        if sinyal_vektor is None or len(sinyal_vektor) <= IDX_ACLIK:
            baglam = "genel"
        else:
            x = sinyal_vektor
            acik = float(x[IDX_ACLIK]) > 0.5
            tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                       (len(x) > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
            baglam = "acik" if acik else ("tehlike" if tehlike else "sakin")
        key = f"{kategori}:{baglam}:{self.komut_adi(komut_indeksi)}"
        self.hata_kategorisi[key] = self.hata_kategorisi.get(key, 0) + 1
        if len(self.hata_kategorisi) > 32:
            for _ in range(len(self.hata_kategorisi) - 32):
                self.hata_kategorisi.pop(next(iter(self.hata_kategorisi)))

    def komut_adi(self, indeks: int) -> Optional[str]:
        return KOMUTLAR[indeks] if 0 <= indeks < CIKIS_BOYUT else KOMUT_YOK

    def _dogrulama_puani(self, komut_idx: int,
                         sinyal_vektor: Optional[List[float]] = None) -> float:
        if sinyal_vektor is not None:
            anahtar = (int(komut_idx),
                       self.komut_baglam_anahtari(komut_idx, sinyal_vektor))
            if anahtar in self.dogrulama_bağlam:
                return self.dogrulama_bağlam[anahtar]
            return 0.0
        return self.dogrulama[komut_idx]

    def komut_kanit_puani(self, komut_idx: int,
                          sinyal_vektor: List[float]) -> float:
        if self.komut_her_kosulda_gecerli_mi(komut_idx):
            return self.dogrulama[komut_idx]
        anahtar = (int(komut_idx),
                   self.komut_baglam_anahtari(komut_idx, sinyal_vektor))
        return self.dogrulama_bağlam.get(anahtar, 0.0)

    def komut_her_kosulda_gecerli_mi(self, komut_idx: int) -> bool:
        return False

    def _hedef_oncelik_puani(self, sinyal_vektor: List[float],
                             komut_idx: int) -> float:
        x = list(sinyal_vektor)
        if len(x) <= IDX_ACLIK:
            return 0.0
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                   (len(x) > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
        enerji = float(x[IDX_ENERJI]) if len(x) > IDX_ENERJI else 0.5
        ki = KOMUT_INDEKSI
        if komut_idx == ki[KOMUT_ACIL_YEM] and acik:
            return 1.0
        if komut_idx in (ki[KOMUT_ACIL_DINLEN], ki[KOMUT_GUVENLI_MOD]) and tehlike:
            return 1.0
        if komut_idx == ki[KOMUT_KAPAT_AG] and tehlike:
            return 0.8
        if komut_idx == ki[KOMUT_KISITLA_DOSYA] and (tehlike or enerji < 0.35):
            return 0.7
        if komut_idx == ki[KOMUT_YOK] and not acik and not tehlike:
            return 0.2
        return 0.0

    def _dunya_model_tahmini(self, sinyal_vektor: List[float],
                             komut_idx: int) -> float:
        x = list(sinyal_vektor)
        bag = self.baglam_anahtari(x)
        entry = self.dunya_modeli.get(bag, {})
        history = entry.get(int(komut_idx), [])
        if not history:
            return 0.0
        return float(sum(history) / max(1, len(history)))

    def _dunya_model_guncelle(self, sinyal_vektor: List[float],
                              komut_idx: int, odul: float) -> None:
        x = list(sinyal_vektor)
        bag = self.baglam_anahtari(x)
        entry = self.dunya_modeli.setdefault(bag, {})
        history = entry.setdefault(int(komut_idx), [])
        history.append(float(odul))
        if len(history) > 16:
            history.pop(0)

    def _uzun_hafizayi_guncelle(self, komut_idx: int, odul: float) -> None:
        memory = self.uzun_hafiza
        memory["toplam_sonuc"] += 1
        memory["odul_toplami"] += float(odul)
        if odul > 0.0:
            memory["olumlu_sonuc"] += 1
        elif odul < 0.0:
            memory["olumsuz_sonuc"] += 1
        name = self.komut_adi(komut_idx) or "yok"
        if name not in memory["komutlar"] and len(memory["komutlar"]) >= 128:
            memory["komutlar"].pop(next(iter(memory["komutlar"])))
        result = memory["komutlar"].setdefault(name, {"sayi": 0, "odul_toplami": 0.0})
        result["sayi"] += 1
        result["odul_toplami"] += float(odul)

    def _ozben_durumu(self, sinyal_vektor: Optional[List[float]] = None) -> Dict[str, Any]:
        odul_gec = self.odul_gecmisi
        if not odul_gec:
            avg_reward = 0.0
            fail_rate = 0.0
            rejection_rate = 0.0
            danger = 0.0
        else:
            n = len(odul_gec)
            avg_reward = sum(odul_gec) / n
            fail_rate = sum(1 for v in odul_gec if v < 0) / n
            rejection_rate = self.reddedilen / max(1, self.tik)
            danger = 0.0
        if avg_reward > 0.1 and fail_rate < 0.2 and rejection_rate < 0.3:
            durum = "stabil"
            istikrar = 0.7 + min(0.2, avg_reward)
        elif avg_reward < -0.05 or fail_rate > 0.4 or rejection_rate > 0.45 or danger > 0.75:
            durum = "kritik"
            istikrar = 0.2 + max(-0.2, avg_reward)
        else:
            durum = "kararsiz"
            istikrar = 0.5 + avg_reward * 0.25
        self.ozben_modeli = {
            "durum": durum,
            "istikrar": float(max(0.0, min(1.0, istikrar))),
            "hata_orani": float(max(0.0, min(1.0, fail_rate + rejection_rate * 0.4))),
            "ortalama_odul": float(avg_reward),
            "guven_duyarliligi": float(max(0.0, min(1.0, 1.0 - istikrar))),
        }
        return self.ozben_modeli

    def eylem_katalogunu_yukle(self) -> Dict[str, Dict[str, Any]]:
        return {k: dict(v) for k, v in self.eylem_katalogu.items()}

    def eylem_uygulanabilir_mi(self, eylem_adi: str,
                               sinyal_vektor: List[float]) -> bool:
        if eylem_adi not in self.eylem_katalogu:
            return False
        x = list(sinyal_vektor)
        if eylem_adi == "bilgi_topla":
            return True
        if eylem_adi == "dosya_tara":
            return len(x) > 0 and (len(x) <= IDX_GOREV or float(x[IDX_GOREV]) > 0.1)
        if eylem_adi == "network_tara":
            tehlike = (len(x) > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
            mesaj = (len(x) > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
            return (not tehlike) or mesaj
        if eylem_adi == "asm_ogren":
            sik = float(x[IDX_SIKILMA]) if len(x) > IDX_SIKILMA else 0.0
            gorev = float(x[IDX_GOREV]) if len(x) > IDX_GOREV else 0.0
            return sik > 0.25 or gorev > 0.25
        if eylem_adi == "komut_ver":
            tehlike = (len(x) > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
            mesaj = (len(x) > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
            return tehlike or mesaj
        if eylem_adi == "dogrula":
            return len(x) > 0
        return True

    def eylem_degeri(self, eylem_adi: str, sinyal_vektor: List[float]) -> float:
        meta = self.eylem_katalogu.get(eylem_adi)
        if meta is None:
            return 0.0
        x = list(sinyal_vektor)
        risk = float(meta.get("risk", 0.0))
        cost = float(meta.get("cost", 0.0))
        gain = float(meta.get("gain", 0.0))
        if eylem_adi == "asm_ogren":
            sik = float(x[IDX_SIKILMA]) if len(x) > IDX_SIKILMA else 0.0
            gorev = float(x[IDX_GOREV]) if len(x) > IDX_GOREV else 0.0
            gain += 0.50 * sik + 0.50 * gorev
            if sik > 0.0:
                risk *= max(0.60, 1.0 - 0.35 * min(1.0, sik))
        if eylem_adi == "network_tara":
            mesaj = float(x[IDX_MESAJ_VAR]) if len(x) > IDX_MESAJ_VAR else 0.0
            gain += 0.10 * mesaj
            if self.ag_beyin is not None:
                try:
                    if hasattr(self.ag_beyin, "next_due_in") and self.ag_beyin.next_due_in() <= 0:
                        gain += 0.15
                    son_scan = self.ag_beyin.data.get("last_scan", {})
                    if son_scan.get("ok", False):
                        gain += 0.10
                except Exception:
                    pass
        if eylem_adi == "komut_ver":
            tehlike = float(x[IDX_TEHLIKE]) if len(x) > IDX_TEHLIKE else 0.0
            gain += 0.12 * tehlike
        deger = gain - risk - (cost * 0.5)
        return float(max(0.0, min(1.0, deger)))

    def en_iyi_eylem_sec(self, sinyal_vektor: List[float]) -> Tuple[str, float, bool]:
        adaylar = []
        for eylem_adi in self.eylem_katalogu:
            if self.eylem_uygulanabilir_mi(eylem_adi, sinyal_vektor):
                adaylar.append((eylem_adi, self.eylem_degeri(eylem_adi, sinyal_vektor)))
        if not adaylar:
            return ("bilgi_topla", 0.0, False)
        eylem_adi, puan = max(adaylar, key=lambda item: item[1])
        return (eylem_adi, float(puan), True)

    def _eylem_komut_hint(self, sinyal_vektor: List[float]) -> int:
        eylem_adi, puan, uygun = self.en_iyi_eylem_sec(sinyal_vektor)
        if not uygun:
            return KOMUT_INDEKSI[KOMUT_YOK]
        x = list(sinyal_vektor)
        tehlike = (len(x) > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
        mesaj = (len(x) > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
        acik = (len(x) > IDX_ACLIK and float(x[IDX_ACLIK]) > 0.5)
        ki = KOMUT_INDEKSI
        if eylem_adi == "asm_ogren":
            return ki[KOMUT_ASM_OGREN]
        if eylem_adi == "network_tara":
            return ki[KOMUT_AG_TARA]
        if eylem_adi == "komut_ver":
            return ki[KOMUT_GUVENLI_MOD] if tehlike or mesaj else ki[KOMUT_ACIL_DINLEN]
        if eylem_adi == "dosya_tara":
            return ki[KOMUT_KISITLA_DOSYA]
        if eylem_adi == "dogrula":
            return ki[KOMUT_YOK]
        if eylem_adi == "bilgi_topla":
            return ki[KOMUT_YOK]
        return ki[KOMUT_YOK]

    def eylem_ogren(self, eylem_adi: str, odul: float,
                    sinyal_vektor: Optional[List[float]] = None,
                    maliyet: float = 0.0) -> float:
        if eylem_adi not in self.eylem_katalogu:
            return 0.0
        odul = max(-1.0, min(1.0, float(odul)))
        mevcut = self.eylem_bilgi.get(eylem_adi, {"puan": 0.0, "deneme": 0, "basarili": 0})
        mevcut["deneme"] = int(mevcut.get("deneme", 0)) + 1
        mevcut["puan"] = float(max(0.0, min(1.0, mevcut.get("puan", 0.0) + odul * 0.20)))
        if odul > 0:
            mevcut["basarili"] = int(mevcut.get("basarili", 0)) + 1
        self.eylem_bilgi[eylem_adi] = mevcut
        return float(mevcut["puan"])

    @property
    def W1(self):
        return self.mlp.ağırlıklar[0]

    @property
    def b1(self):
        return self.mlp.çeşitler[0]

    @property
    def W2(self):
        return self.mlp.ağırlıklar[1]

    @property
    def b2(self):
        return self.mlp.çeşitler[1]

    @property
    def n_out(self):
        return len(self.mlp.ağırlıklar[-1]) if self.mlp.ağırlıklar else 0

    @property
    def n_in(self):
        return len(self.mlp.ağırlıklar[0]) if self.mlp.ağırlıklar else 0

    # --------------------------------------------------------------- sec()

    def sec(self, sinyal_vektor: List[float],
            epsilon: Optional[float] = None) -> Tuple[Optional[str], int, float, str]:
        if epsilon is None:
            epsilon = self.epsilon

        x = [float(v) for v in sinyal_vektor]
        self.last_hedef_kopru = None
        probs = self.mlp.predict(self._mlp_girisi(x))
        if probs is None or len(probs) == 0:
            probs = [1.0 / CIKIS_BOYUT] * CIKIS_BOYUT
        # E_t: bu tikin niyeti; bir sonraki tikte zamansal_guncelle() E_{t-1} olarak dondurur.
        self.onceki_niyet = [float(p) for p in probs]

        ki = KOMUT_INDEKSI
        if self.rng.random() < epsilon:
            # Keşif: yalnızca UYGUN komutlar arasında deneme yapılır.
            # Uygunsuz komutları keşfetmek kanıt toplamayı gecikştirir
            # (onlar komut_uygulanabilir_mi'de kesif_gecersi ile
            # reddedilir, hiçbir ödül/kanıt üretmez).
            maske = self.uygun_maske(x)
            _adaylar = [i for i in range(CIKIS_BOYUT)
                        if maske[i] and i != ki[KOMUT_YOK]]
            if not _adaylar:
                _adaylar = [i for i in range(CIKIS_BOYUT)
                            if i != ki[KOMUT_YOK]]
            if not _adaylar:
                _adaylar = list(range(CIKIS_BOYUT))
            idx = self.rng.choice(_adaylar)
            gv = float(min(1.0, probs[idx] * 0.5))
            gv = min(gv, max(0.0, self.dogrulama_esigi * 0.9))
            self.last_confidence = float(gv)
            self.last_komut_idx = idx
            self.kisa_hafiza.append({
                "komut": KOMUTLAR[idx], "idx": int(idx),
                "confidence": float(gv),
                "baglam": self.baglam_anahtari(x),
                "source": "kesif",
            })
            return KOMUTLAR[idx], idx, gv, "kesif"

        maske = self.uygun_maske(x)
        uygunlar = [i for i in range(CIKIS_BOYUT) if maske[i]
                    and i != ki[KOMUT_YOK]]
        if not uygunlar:
            uygunlar = [i for i in range(CIKIS_BOYUT) if i != ki[KOMUT_YOK]]
            idx = int(self.rng.choice(uygunlar))
            p_maskeli = [1.0 / len(uygunlar) if i in uygunlar else 0.0
                         for i in range(CIKIS_BOYUT)]
            p_maskeli[ki[KOMUT_YOK]] = 0.0
            toplam = 1.0
        else:
            p_maskeli = [probs[i] if maske[i] else 0.0
                         for i in range(CIKIS_BOYUT)]
            toplam = float(sum(p_maskeli))
            if toplam <= 0.0:
                p_maskeli = [1.0 if maske[i] else 0.0 for i in range(CIKIS_BOYUT)]
                toplam = float(sum(p_maskeli))
            p_maskeli = [p / toplam for p in p_maskeli]

            tool_name, tool_score, tool_ok = self.en_iyi_eylem_sec(x)
            tool_idx = self._eylem_komut_hint(x)
            if (tool_ok and tool_idx != ki[KOMUT_YOK] and maske[tool_idx]):
                tool_bias = 0.12 + 0.18 * max(0.0, min(1.0, tool_score))
                p_maskeli[tool_idx] += tool_bias
                p_maskeli = [p / float(sum(p_maskeli)) for p in p_maskeli]

            # Öz hedef köprüsü: hedef çekimi/vetosu olasılığa küçük bias olarak eklenir.
            # Maskelenmiş (uygunsuz) komutlara ve `yok`a dokunmaz; hata karar akışını bozmaz.
            kopru = getattr(self, "hedef_kopru", None)   # test/yan sınıflar __init__'i atlayabilir
            if kopru is not None:
                try:
                    kb = kopru.bias(maske)
                except Exception:
                    kb = {}
                kb = {i: b for i, b in kb.items()
                      if 0 <= i < CIKIS_BOYUT and maske[i] and i != ki[KOMUT_YOK]}
                if kb:
                    for i, b in kb.items():
                        p_maskeli[i] = max(0.0, p_maskeli[i] + b)
                    toplam_k = float(sum(p_maskeli))
                    if toplam_k > 0.0:
                        p_maskeli = [p / toplam_k for p in p_maskeli]
                        self.last_hedef_kopru = kb

            # Sahne sezgisi: k-en-yakın sahneden komut başına beklenen ödül, olasılığa önyargı.
            # Ödülü sonradan süslemek yerine KARARDA kullanılır; hafızaya yazılan ödül ham kalır
            # (eski +0.2·proto_ödül geri besleme döngüsü yok).
            self.last_sezgi = None
            try:
                sz = self.kavram_sezgi(x, maske)
            except Exception:
                sz = {}
            if sz:
                for i, b in sz.items():
                    p_maskeli[i] = max(0.0, p_maskeli[i] + SEZGI_KAZANC * b)
                toplam_s = float(sum(p_maskeli))
                if toplam_s > 0.0:
                    p_maskeli = [p / toplam_s for p in p_maskeli]
                    self.last_sezgi = sz

            idx = int(max(range(CIKIS_BOYUT), key=lambda i: p_maskeli[i]))

        p_guven = p_maskeli
        safety_conf = float(self._guven_hesapla(p_guven, idx))
        hedef_bonus = self._hedef_oncelik_puani(x, idx)
        dunya_bonus = self._dunya_model_tahmini(x, idx)
        self._ozben_durumu(x)
        ozben_ayari = self.ozben_modeli.get("istikrar", 0.5)
        if self.ozben_modeli.get("durum") == "kritik":
            ozben_ayari *= 0.5
        elif self.ozben_modeli.get("durum") == "kararsiz":
            ozben_ayari *= 0.8
        confidence = min(1.0, safety_conf + 0.18 * hedef_bonus + 0.12 * max(0.0, dunya_bonus))
        confidence *= 0.7 + 0.3 * max(0.0, min(1.0, ozben_ayari))
        self.last_confidence = confidence
        self.last_komut_idx = idx
        self.kisa_hafiza.append({
            "komut": KOMUTLAR[idx], "idx": int(idx),
            "confidence": confidence,
            "baglam": self.baglam_anahtari(x),
            "source": "model",
            "hedef_bonus": hedef_bonus,
            "dunya_bonus": dunya_bonus,
            "sezgi": ({str(i): round(v, 3) for i, v in self.last_sezgi.items()}
                      if getattr(self, "last_sezgi", None) else None),
            "self_state": self.ozben_modeli,
        })
        return (KOMUTLAR[idx], idx, confidence, "model")

    # --------------------------------------------------------------- Güvenlik

    def komut_uygulanabilir_mi(self, komut_idx: int, guven: float,
                               kaynak: str = "model",
                               sinyal_vektor: Optional[List[float]] = None) -> Tuple[bool, str]:
        ki = KOMUT_INDEKSI
        if komut_idx == ki[KOMUT_YOK]:
            return True, "yok"
        if kaynak == "kesif":
            if (sinyal_vektor is not None
                    and not self.komut_uygun_mu(komut_idx, sinyal_vektor)):
                return False, "kesif_gecersiz"
            return True, "kesif_deneme"

        cooldown_kaldi = self.redd_cooldown[komut_idx]
        if cooldown_kaldi > 0:
            self.redd_cooldown[komut_idx] = max(0, cooldown_kaldi - 1)
            guven_esik = self.guven_esigi * 0.4
            dogrulama_esik = self.dogrulama_esigi * 0.4
        else:
            guven_esik = self.guven_esigi
            dogrulama_esik = self.dogrulama_esigi

        if sinyal_vektor is not None:
            if not self.komut_uygun_mu(komut_idx, sinyal_vektor):
                self.redd_serisi[komut_idx] += 1
                if self.redd_serisi[komut_idx] >= self.RED_SERI_MAKS:
                    self.redd_cooldown[komut_idx] = 5
                return False, "kosul_saglanmadi"
        if guven < guven_esik:
            self.redd_serisi[komut_idx] += 1
            if self.redd_serisi[komut_idx] >= self.RED_SERI_MAKS:
                self.redd_cooldown[komut_idx] = 5
            return False, "guven_yetersiz"
        puan = self._dogrulama_puani(komut_idx, sinyal_vektor)
        if puan < dogrulama_esik:
            self.redd_serisi[komut_idx] += 1
            if self.redd_serisi[komut_idx] >= self.RED_SERI_MAKS:
                self.redd_cooldown[komut_idx] = 5
            return False, "dogrulanmadi"
        self.redd_serisi[komut_idx] = 0
        self.redd_cooldown[komut_idx] = 0
        return True, "onaylandi"

    # --------------------------------------------------------------- Öğren

    def ogren(self, sinyal_vektor: List[float], komut_indeksi: int,
              odul: float, keşif: bool = False, zamansal: bool = True) -> None:
        ki = KOMUT_INDEKSI
        x = [float(v) for v in sinyal_vektor]
        odul = max(-1.0, min(1.0, float(odul)))
        self._uzun_hafizayi_guncelle(komut_indeksi, odul)

        hedef = [0.0] * CIKIS_BOYUT
        if komut_indeksi == ki[KOMUT_YOK] and odul >= 0.0:
            self.secim_sayilari[komut_indeksi] += 1
            self.redd_serisi[komut_indeksi] = 0
            self.redd_cooldown[komut_indeksi] = 0
            self.samples += 1
            self.tik += 1
            self.odul_gecmisi.append(odul)
            if len(self.odul_gecmisi) > 512:
                self.odul_gecmisi.pop(0)
            if self.epsilon > self.epsilon_min:
                self.epsilon *= self.epsilon_decay
            return

        if odul < 0.0:
            self._kaydet_hata("neg_odul", komut_indeksi, sinyal_vektor)

        if odul >= 0.0:
            # Sabit hedef (asla 0'dan başlangıçta sıfır marj): modelin
            # öğrenmesine başlangıçtan itibaren hareket verecek.
            guc = min(1.0, 0.55 + 0.40 * odul)
            # Aksiyon maskelemesi: hedefin geri kalanı yalnızca UYGUN
            # komutlara dağıtılır; uygunsuz komutlar hedef 0 alır.
            maske = self.uygun_maske(x)
            digerler = [i for i in range(CIKIS_BOYUT)
                        if i != komut_indeksi and maske[i]]
            if not digerler:
                hedef[komut_indeksi] = 1.0
            else:
                _agirlikli = []
                for i in digerler:
                    # Kanit, komutun ön koşulu bağlamında aranır
                    # (acil_yem -> "acik", acil_dinlen -> "tehlike").
                    _p = self.komut_kanit_puani(i, x)
                    _agirlikli.append((i, _p))
                _toplam_agirlik = sum(_p for _, _p in _agirlikli)
                if _toplam_agirlik > 0.0:
                    _taban = 0.05
                    _agirlikli2 = [(i, _p + _taban) for i, _p in _agirlikli]
                    _t2 = sum(_p for _, _p in _agirlikli2)
                    for i, _p in _agirlikli2:
                        hedef[i] = (1.0 - guc) * (_p / _t2)
                else:
                    pay = (1.0 - guc) / len(digerler)
                    for i in digerler:
                        hedef[i] = pay
            hedef[komut_indeksi] = guc
        else:
            # Ceza: seçilen sınıf bastırılır (0.08 * |odul>); kalan kütme,
            # bağlamdaki kanıt puanlarına oranla diğer *uygun* sınıflara
            # dağıtılır. Böylece alakasız uygun komutlara yanlış pozitif
            # hedef sinyali gitmez; kanıt yoksa dağıtım eşit kalır.
            hedef[komut_indeksi] = 0.08 * abs(odul)
            maske_c = self.uygun_maske(x)
            digerler = [i for i in range(CIKIS_BOYUT)
                        if i != komut_indeksi and maske_c[i]]
            if digerler:
                _taban = 0.05
                _agirlikli = [
                    (i, self.komut_kanit_puani(i, x) + _taban) for i in digerler
                ]
                _toplam = sum(_p for _, _p in _agirlikli)
                _kitle = 1.0 - hedef[komut_indeksi]
                for i, _p in _agirlikli:
                    hedef[i] = _kitle * (_p / _toplam)
            else:
                hedef[komut_indeksi] = 1.0

        self._dunya_model_guncelle(x, komut_indeksi, odul)
        self.mlp.öğren(self._mlp_girisi(x, zamansal), hedef)
        # ---------- Kavram hafızası: z-skorlu SAHNE + HAM ödül (süssüz) ----------
        self.kavram_kaydet(x, komut_indeksi, odul, etiket="ogren")
        self.secim_sayilari[komut_indeksi] += 1
        self.samples += 1
        self.tik += 1

        _agirlik = 2.0 if keşif else 1.0
        if odul > 0.0:
            self.dogrulama[komut_indeksi] = min(
                2.0, self.dogrulama[komut_indeksi]
                + odul * self.kanit_çarpanı * _agirlik)
            _anahtar = (komut_indeksi,
                        self.komut_baglam_anahtari(komut_idx=komut_indeksi, sinyal_vektor=x))
            self.dogrulama_bağlam[_anahtar] = min(
                2.0, self.dogrulama_bağlam.get(_anahtar, 0.0)
                + odul * self.kanit_çarpanı * _agirlik)
        else:
            self.dogrulama[komut_indeksi] = max(
                0.0, self.dogrulama[komut_indeksi] + odul * 0.02)
            _anahtar_neg = (komut_indeksi,
                            self.komut_baglam_anahtari(komut_idx=komut_indeksi, sinyal_vektor=x))
            self.dogrulama_bağlam[_anahtar_neg] = max(
                0.0, self.dogrulama_bağlam.get(_anahtar_neg, 0.0)
                + odul * 0.02)

        self.odul_gecmisi.append(odul)
        if len(self.odul_gecmisi) > 512:
            self.odul_gecmisi.pop(0)
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    def reddedildi_ogren(self, sinyal_vektor: List[float],
                         komut_indeksi: int) -> int:
        ki = KOMUT_INDEKSI
        if komut_indeksi == ki[KOMUT_YOK]:
            return 0
        self._kaydet_hata("reddedildi", komut_indeksi, sinyal_vektor)
        self.reddedilen += 1
        self.reddedilen_sayilari[komut_indeksi] += 1
        self.redd_serisi[komut_indeksi] += 1
        if self.redd_serisi[komut_indeksi] >= self.RED_SERI_MAKS:
            self.redd_cooldown[komut_indeksi] = 5
            self.redd_serisi[komut_indeksi] = 0
        self.tik += 1
        return 0

    # --------------------------------------------------------------- Ömür

    def komut_ayarla(self, komut: str, komut_idx: int, sure: int = 3) -> None:
        self.son_komut = komut
        self.son_idx = komut_idx
        self.sure = max(0, int(sure))
        self.sure_azami = max(self.sure_azami, self.sure)

    def azalt_sure(self) -> int:
        if self.sure > 0:
            self.sure -= 1
            if self.sure == 0:
                self.son_komut = KOMUT_YOK
        return self.sure

    def aktif_komut(self) -> Optional[str]:
        if self.sure > 0:
            return self.son_komut
        return KOMUT_YOK

    # --------------------------------------------------------------- ASM Öğrenme

    def asm_sistemi(self) -> Any:
        if self._asm_öğrenici is not None:
            return self._asm_öğrenici
        from uzuv.asm_ogren import (
            AssemblyLearner, Emulator, LearningState, CURRICULUM, OPS,
        )
        from uzuv.asm_uzuv import AsmUzuv
        asm = AsmUzuv(root=self.root)
        durum_yol = self.root / "uzuv" / "asm_ogren.json"
        durum = LearningState(durum_yol)
        durum.load()
        emulator = Emulator()
        asm_rng = random.Random(self.seed ^ 0xA5A5A5A5)
        self._asm_öğrenici = AssemblyLearner(
            asm, durum, CURRICULUM, OPS, emulator, asm_rng
        )
        return self._asm_öğrenici

    def asm_öğren(self, dakika: float = 1.0, nn_ana: Any = None,
                  stim_ust: Any = None) -> Dict[str, Any]:
        learner = self.asm_sistemi()
        history_start = len(learner.state.history)
        primitives_before = sum(len(v) for v in learner.state.primitives.values())
        dakika = max(0.0, float(dakika))
        learner.run(dakika, nn_ana=nn_ana, stim_features=stim_ust)
        st = learner.state
        session = st.history[history_start:]
        return {
            "toplam_gorev": st.total_tasks,
            "maks_seviye": st.max_level,
            "primtik": sum(len(v) for v in st.primitives.values()),
            "oturum_gorev": len(session),
            "oturum_cozulen": sum(bool(item.get("cozuldu")) for item in session),
            "yeni_primtik": sum(len(v) for v in st.primitives.values()) - primitives_before,
            "basarisiz_kumbara": sum(len(s) for s in st.failures.values()),
        }

    def asm_rapor(self) -> None:
        learner = self.asm_sistemi()
        learner.report()

    def asm_kod_dene(self, kod: str, hedef: Dict[str, Any],
                     başlangıç: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        learner = self.asm_sistemi()
        asm = learner.asm
        if başlangıç is None:
            başlangıç = {r: 0 for r in learner.emulator.registers}
        return asm.tahmin_dene(kod, hedef, başlangıç)

    def asm_istatistik(self) -> Dict[str, Any]:
        if self._asm_öğrenici is None:
            return {"hazır": False}
        learner = self.asm_sistemi()
        st = learner.state
        return {
            "hazır": True,
            "toplam_gorev": st.total_tasks,
            "maks_seviye": st.max_level,
            "primtik": sum(len(v) for v in st.primitives.values()),
            "baglam": len(st.weights.records),
        }

    def asm_ornek_coz(self, egitim: Any, dogrulama: Any,
                      seviye: int = 1, azami_komut: Optional[int] = None,
                      butce: int = 10000, zaman_asimi: float = 10.0) -> Dict[str, Any]:
        sonuc = self.asm_sistemi().solve_examples(
            egitim, dogrulama,
            level=seviye,
            max_length=azami_komut,
            budget=butce,
            timeout_seconds=zaman_asimi,
        )
        return {
            "cozuldu": sonuc.solved,
            "program": sonuc.program,
            "deneme": sonuc.attempts,
            "emulator_uyusmazligi": sonuc.emulator_mismatch,
            "zaman_asimi": sonuc.timed_out,
        }

    # --------------------------------------------------------------- Tarama (ag_beyin)

    def scan_hazir_mi(self, now: Optional[float] = None) -> bool:
        if self.ag_beyin is None:
            return False
        try:
            return self.ag_beyin.next_due_in(now) <= 0.0
        except Exception:
            return False

    def scan_calistir(self, now: float) -> Optional[Dict[str, Any]]:
        if self.ag_beyin is None:
            return None
        if not self.scan_hazir_mi(now):
            return None
        try:
            sonuc = self.ag_beyin.scan_next_step(now)
            if sonuc and sonuc.get("ok"):
                self._son_scan_odulu = float(sonuc.get("probe_reward", 0.0))
                self._son_scan_tik = int(self.tik)
                self.journal.log(
                    "ag_tara_adim",
                    step=sonuc.get("step"),
                    probe=sonuc.get("probe"),
                    hosts=sonuc.get("hosts"),
                    ports=sonuc.get("ports"),
                    reward=self._son_scan_odulu,
                )
            return sonuc
        except Exception as e:
            self.journal.log("ag_tara_hata", hata=str(e)[:200])
            return None

    def scan_sinyali_kaydet(self, sinyal_vektor: List[float]) -> None:
        """Taramayı seçtiren karar anındaki sinyali sakla (ödül o bağlama yazılsın)."""
        self._scan_sinyal = [float(v) for v in sinyal_vektor]

    def scan_odulu_besle(self, odul: float, tik: int) -> None:
        if odul is None:
            odul = 0.0
        odul = max(-1.0, min(1.0, float(odul)))
        self.eylem_ogren("network_tara", odul)
        komut_idx = KOMUT_INDEKSI[KOMUT_AG_TARA]
        # Gerçek karar bağlamı varsa onunla öğren; sıfır vektör "her zaman tara"
        # öğretiyordu (ağ, ne zaman taranacağını değil, taramanın iyi olduğunu öğreniyordu).
        x = self._scan_sinyal
        self._scan_sinyal = None
        if x is None or len(x) != SINYAL_BOYUT:
            x = [0.0] * SINYAL_BOYUT
        if getattr(self, "zamansal_kanal", False):
            self.ogren(x, komut_idx, odul, zamansal=False)   # tarama bağlamında ΔS/E yok -> sıfır kanal
        else:
            self.ogren(x, komut_idx, odul)
        self._son_scan_odulu = odul
        self._son_scan_tik = int(tik)

    def scan_ozeti(self) -> Dict[str, Any]:
        if self.ag_beyin is None:
            return {"ag_beyin_yok": True}
        ss = self.ag_beyin.data.get("scan_state", {})
        last = self.ag_beyin.data.get("last_scan", {})
        return {
            "step": int(ss.get("step", 1)),
            "live_hosts": len(ss.get("live_hosts", [])),
            "last_networks": ss.get("last_networks", []),
            "scan_hazir": self.scan_hazir_mi(),
            "son_scan_ok": bool(last.get("ok", False)),
            "son_scan_probe": last.get("probe"),
            "son_scan_hosts": last.get("hosts", 0),
            "son_scan_ports": last.get("ports", 0),
            "son_scan_odul": float(last.get("probe_reward", 0.0)),
            "ust_son_odul": self._son_scan_odulu,
            "ust_son_tik": self._son_scan_tik,
        }

    # --------------------------------------------------------------- Kalıcılık

    def save(self) -> None:
        yol = self.root / "zeka" / "ust_beyn.json"
        yol.parent.mkdir(parents=True, exist_ok=True)
        w1, b1 = self.mlp.ağırlıklar[0], self.mlp.çeşitler[0]
        w2, b2 = self.mlp.ağırlıklar[1], self.mlp.çeşitler[1]
        if not self._agirlik_sekli_gecerli(w1, b1, w2, b2,
                                           getattr(self, "giris_boyutu", SINYAL_BOYUT)):
            # Bozuk ağırlığı asla diske yazma: diskteki dosya sağlam olabilir.
            self.journal.log("ust_beyn_kayit_atlandi", neden="agirlik_sekli_gecersiz")
            return
        data = {
            "surum": UST_MODEL_SURUMU,
            "giris_boyutu": getattr(self, "giris_boyutu", SINYAL_BOYUT),
            # NöralBeyn'in yerel düzeni: W1[girdi][gizli], W2[gizli][çıktı]. Eski NumPy
            # dosyalarında düzen [çıktı][girdi] idi ve bu anahtar yoktu.
            "agirlik_yerlesimi": AGIRLIK_YERLESIMI,
            "W1": w1,
            "b1": b1,
            "W2": w2,
            "b2": b2,
            "samples": self.samples,
            "tik": self.tik,
            "epsilon": self.epsilon,
            "secim_sayilari": self.secim_sayilari,
            "dogrulama": self.dogrulama,
            "mizac": self.mizac,
            "kisa_hafiza": list(self.kisa_hafiza),
            "hata_kategorisi": self.hata_kategorisi,
            "last_confidence": self.last_confidence,
            "last_komut_idx": self.last_komut_idx,
            "dunya_modeli": self.dunya_modeli,
            # Sahne hafızası eskiden diske HİÇ yazılmıyordu: her yeniden başlatmada sıfırlanıyordu.
            "sahne_takip": self._takip().to_dict(),
            "dunya_delta": self._dunya_delta_al().to_dict(),
            "kavram_prototipi": [
                {"sahne": [round(float(v), 4) for v in p["sahne"]], "komut": int(p["komut"]),
                 "odul": round(float(p["odul"]), 5), "sayi": int(p.get("sayi", 1)),
                 "son_tik": int(p.get("son_tik", 0)), "etiket": str(p.get("etiket", ""))}
                for p in (getattr(self, "kavram_prototipi", None) or [])],
            "ozben_modeli": self.ozben_modeli,
            "kimlik": self.kimlik,
            "deger_profili": self.deger_profili,
            "uzun_hafiza": self.uzun_hafiza,
            "dogrulama_baglam": {
                "%d|%s" % (k[0], k[1]): v
                for k, v in self.dogrulama_bağlam.items()
            },
            "guven_esigi": self.guven_esigi,
            "marj_olcek": self.marj_olcek,
            "kanit_çarpani": self.kanit_çarpanı,
            "dogrulama_esigi": self.dogrulama_esigi,
            "sure_azami": self.sure_azami,
            "reddedilen": self.reddedilen,
            # MLP eğitim sözleşmesi (aktivasyon/kayıp/lr vb.) üst-beyn dosyasında
            # taşınır; nn_*.json (NöralBeyn.kaydet) ile ayrı sorumluluk sınırı
            # korunur ve yükleme sözleşmesi bozulmaz.
            "mlp_cfg": {
                "lr": self.mlp.lr,
                "momentum": self.mlp.momentum,
                "aktivasyon": self.mlp.gizli,
                "çıkış_aktivasyon": self.mlp.çıkış_akt,
                "kayıp": self.mlp.kayıp,
                "l2": self.mlp.l2,
            },
        }
        if self._asm_öğrenici is not None:
            self._asm_öğrenici.state.save()
        tmp = yol.with_name(yol.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(yol))

    @staticmethod
    def _agirlik_sekli_gecerli(w1: Any, b1: Any, w2: Any, b2: Any,
                               giris: int = SINYAL_BOYUT) -> bool:
        """W1[girdi][gizli], b1[gizli], W2[gizli][çıktı], b2[çıktı] ve sonlu değerler."""
        try:
            if len(w1) != giris or len(b1) != GIZLI_BOYUT:
                return False
            if len(w2) != GIZLI_BOYUT or len(b2) != CIKIS_BOYUT:
                return False
            if any(len(r) != GIZLI_BOYUT for r in w1):
                return False
            if any(len(r) != CIKIS_BOYUT for r in w2):
                return False
            for tablo in (w1, w2):
                for satir in tablo:
                    if not all(math.isfinite(float(v)) for v in satir):
                        return False
            return all(math.isfinite(float(v)) for v in list(b1) + list(b2))
        except (TypeError, ValueError):
            return False

    def _agirliklari_yukle(self, data: Dict[str, Any], yol: Path) -> bool:
        """Ağırlıkları doğrulayarak yükler. Uyumsuzsa KARANTİNAYA alır, taze ağırlıkla sürer.

        Eski (NumPy, [çıktı][girdi], ReLU+softmax) dosyalar ve şekli bozuk dosyalar
        sessizce pad/kes edilmez: bu, ağın bozulmasına ve bozuk hâlin diske yazılmasına
        yol açıyordu. Öğrenilmiş durumun geri kalanı (kanıt, hafıza, sayaçlar) yine yüklenir.
        """
        W1, b1 = data.get("W1") or [], data.get("b1") or []
        W2, b2 = data.get("W2") or [], data.get("b2") or []
        if data.get("agirlik_yerlesimi") == AGIRLIK_YERLESIMI:
            try:  # çıktı sayısı büyüdüyse (yeni komut) yeni sütunlar sıfırdan başlar
                if W2 and len(W2[0]) < CIKIS_BOYUT:
                    ek = CIKIS_BOYUT - len(W2[0])
                    W2 = [list(r) + [0.0] * ek for r in W2]
                    b2 = list(b2) + [0.0] * (CIKIS_BOYUT - len(b2))
                elif W2 and len(W2[0]) > CIKIS_BOYUT:
                    W2 = [list(r)[:CIKIS_BOYUT] for r in W2]
                    b2 = list(b2)[:CIKIS_BOYUT]
            except TypeError:
                pass
            # Giriş boyutu değiştiyse (zamansal kanal açıldı/kapandı) öğrenilmiş ağ atılmaz:
            # büyürken yeni giriş satırları SIFIRDAN başlar (ağın mevcut davranışı bozulmaz),
            # küçülürken fazladan zamansal satırlar bırakılır.
            _g = getattr(self, "giris_boyutu", SINYAL_BOYUT)
            try:
                if W1 and len(W1) == SINYAL_BOYUT and _g == GIRIS_BOYUT_ZAMANSAL:
                    W1 = [list(r) for r in W1] + [[0.0] * GIZLI_BOYUT
                                                  for _ in range(_g - len(W1))]
                elif W1 and len(W1) == GIRIS_BOYUT_ZAMANSAL and _g == SINYAL_BOYUT:
                    W1 = [list(r) for r in W1][:SINYAL_BOYUT]
            except TypeError:
                pass
            if self._agirlik_sekli_gecerli(W1, b1, W2, b2, _g):
                self.mlp.ağırlıklar = [[[float(v) for v in r] for r in W1],
                                       [[float(v) for v in r] for r in W2]]
                self.mlp.çeşitler = [[float(v) for v in b1], [float(v) for v in b2]]
                self.mlp._hız_sıfırla()
                self.mlp._transpoze_güncelle()
                return True
            neden = "sekil_gecersiz"
        else:
            neden = "eski_duzen" if W1 else "agirlik_yok"
        if W1 or W2:
            self._agirlik_karantina(data, yol, neden)
        self.journal.log("ust_beyn_agirlik_karantina", neden=neden)
        return False

    def _agirlik_karantina(self, data: Dict[str, Any], yol: Path, neden: str) -> None:
        """Uyumsuz ağırlıkları silmeden yanına kaydet (kanıt/geri dönüş için)."""
        try:
            hedef = yol.with_name("ust_beyn.agirlik_%s_%d.json" % (neden, int(time.time())))
            tmp = hedef.with_name(hedef.name + ".tmp")
            tmp.write_text(json.dumps({
                "neden": neden, "surum": data.get("surum"),
                "samples": data.get("samples"),
                "W1": data.get("W1"), "b1": data.get("b1"),
                "W2": data.get("W2"), "b2": data.get("b2"),
            }, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(hedef))
        except OSError:
            pass

    def _load(self) -> int:
        yol = self.root / "zeka" / "ust_beyn.json"
        if not yol.exists():
            return 0
        try:
            data = json.loads(yol.read_text(encoding="utf-8"))
            # Eski NumPy ağırlıkları _agirliklari_yukle içinde karantinaya alınır ve ağ taze
            # başlar; eski modele özgü enerji ×3.0 telafisi bu yüzden anlamsızdır (ayrıca
            # yeni düzende yanlış eksene uygulanıyordu) ve kaldırıldı.
            self._agirliklari_yukle(data, yol)

            # Kaydedilen MLP sözleşmesini uygula (eski dosyalar constructor
            # varsayılanına devam eder).
            mlp_cfg = data.get("mlp_cfg") or {}
            for _attr in ("lr", "momentum", "l2"):
                if _attr in mlp_cfg:
                    try:
                        setattr(self.mlp, _attr, float(mlp_cfg[_attr]))
                    except (TypeError, ValueError):
                        pass
            for _attr, _gecerli in (
                ("gizli", ("sigmoid", "tanh")),
                ("çıkış_akt", ("sigmoid", "tanh", "softmax")),
                ("kayıp", ("mse", "ce")),
            ):
                if _attr in mlp_cfg and str(mlp_cfg[_attr]) in _gecerli:
                    setattr(self.mlp, _attr, str(mlp_cfg[_attr]))

            self.samples = int(data.get("samples", 0))
            self.tik = int(data.get("tik", 0))
            self.epsilon = float(data.get("epsilon", self.epsilon))
            secim = data.get("secim_sayilari", None)
            if secim is not None:
                if len(secim) > CIKIS_BOYUT:
                    secim = secim[:CIKIS_BOYUT]
                elif len(secim) < CIKIS_BOYUT:
                    secim = secim + [0] * (CIKIS_BOYUT - len(secim))
                self.secim_sayilari = [int(v) for v in secim]
            dogr = data.get("dogrulama", None)
            if dogr is not None:
                if len(dogr) > CIKIS_BOYUT:
                    dogr = dogr[:CIKIS_BOYUT]
                elif len(dogr) < CIKIS_BOYUT:
                    dogr = dogr + [0.0] * (CIKIS_BOYUT - len(dogr))
                self.dogrulama = [float(v) for v in dogr]
            self.kisa_hafiza = deque(maxlen=64)
            for _item in data.get("kisa_hafiza", []):
                if isinstance(_item, dict):
                    self.kisa_hafiza.append(_item)
            self.hata_kategorisi = dict(data.get("hata_kategorisi", {}))
            self.last_confidence = float(data.get("last_confidence", 0.0))
            self.last_komut_idx = int(
                data.get("last_komut_idx", KOMUT_INDEKSI[KOMUT_YOK]))
            self.dunya_modeli = {}
            for bag, vals in (data.get("dunya_modeli") or {}).items():
                try:
                    parsed = {}
                    for k, v in (vals or {}).items():
                        parsed[int(k)] = [float(x) for x in v]
                    self.dunya_modeli[bag] = parsed
                except Exception:
                    continue
            # Sahne durumu: yalnızca tamamı geçerliyse yüklenir (yarım yüklenmiş z-skor
            # istatistiği ile eski prototipler birbirini bozar); aksi halde taze başlar.
            _tr = SahneTakipcisi()
            if _tr.from_dict(data.get("sahne_takip") or {}):
                _protos = []
                for _p in data.get("kavram_prototipi") or []:
                    try:
                        _sh = [float(v) for v in _p["sahne"]]
                        if len(_sh) == SAHNE_BOYUT and all(math.isfinite(v) for v in _sh):
                            _protos.append({"sahne": _sh, "komut": int(_p["komut"]),
                                            "odul": float(_p["odul"]),
                                            "sayi": max(1, int(_p.get("sayi", 1))),
                                            "son_tik": int(_p.get("son_tik", 0)),
                                            "etiket": str(_p.get("etiket", ""))})
                    except (KeyError, TypeError, ValueError):
                        continue
                self.sahne_takip = _tr
                self.kavram_prototipi = _protos[-self.kavram_max:]
                _dm = DunyaDeltaModeli()
                if _dm.from_dict(data.get("dunya_delta") or {}):
                    self.dunya_delta = _dm
            self.ozben_modeli = data.get("ozben_modeli", {
                "durum": "hazir", "istikrar": 0.0, "hata_orani": 0.0,
                "ortalama_odul": 0.0, "guven_duyarliligi": 0.0,
            })
            loaded_identity = data.get("kimlik") or {}
            self.kimlik["ad"] = "Aelaan"
            self.kimlik["ilkeler"] = loaded_identity.get(
                "ilkeler", self.kimlik["ilkeler"])
            self.deger_profili.update(data.get("deger_profili") or {})
            loaded_memory = data.get("uzun_hafiza") or {}
            self.uzun_hafiza["toplam_sonuc"] = max(0,
                int(loaded_memory.get("toplam_sonuc", 0)))
            self.uzun_hafiza["olumlu_sonuc"] = max(0,
                int(loaded_memory.get("olumlu_sonuc", 0)))
            self.mizac.update(data.get("mizac") or {})
            self.uzun_hafiza["olumsuz_sonuc"] = max(0,
                int(loaded_memory.get("olumsuz_sonuc", 0)))
            self.uzun_hafiza["odul_toplami"] = float(
                loaded_memory.get("odul_toplami", 0.0))
            self.uzun_hafiza["komutlar"] = {
                str(ad): {"sayi": max(0, int(veri.get("sayi", 0))),
                          "odul_toplami": float(veri.get("odul_toplami", 0.0))}
                for ad, veri in (loaded_memory.get("komutlar") or {}).items()
                if isinstance(veri, dict)
            }
            self.dogrulama_bağlam = {}
            for _k, _v in (data.get("dogrulama_baglam") or {}).items():
                try:
                    _idx_s, _bag = str(_k).split("|", 1)
                    self.dogrulama_bağlam[(int(_idx_s), _bag)] = float(_v)
                except (TypeError, ValueError):
                    continue
            if "guven_esigi" in data:
                self.guven_esigi = float(data["guven_esigi"])
            if "marj_olcek" in data:
                self.marj_olcek = float(data["marj_olcek"])
            if "kanit_çarpani" in data:
                self.kanit_çarpanı = float(data["kanit_çarpani"])
            if "dogrulama_esigi" in data:
                self.dogrulama_esigi = float(data["dogrulama_esigi"])
            self.sure_azami = data.get("sure_azami", 0)
            self.reddedilen = data.get("reddedilen", 0)
            return self.samples
        except Exception:
            return 0
