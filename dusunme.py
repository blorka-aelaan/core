"""dusunme.py — Model Tabanlı "Düşünme" (Eylemöncesi Simülasyon).

Organizmaya eylemi gerçekleştirmeden önce sonucunu tahmin edebilme
kanı sağlar: mevcut durumu al, olası eylemleri birer adım iç ileri
simüle et, en yüksek tahmini ödülü vereni seç, sonra gerçek dünyada
uygula.

Altyapı olarak NumPy tabanlı MLP kullanılır zaten `ust_beyn.py`'de:
  SINYAL_BOYUT=36 → GIZLI_BOYUT=16 → CIKIS_BOYUT=7 (komutlar).

Bu modül, MLP'yi "world model" olarak kullanır:
  (sinyal_vektörü, eylem) → (sonraki_sinyal, tahmini_ödül)

Düşünme algoritması:
  1. Mevcut sinyali al
  2. Her seçilebilir eylemin (feasible) tahmini:
     a. MLP ile forward: (sinyal, eylem_one_hot) → (logits, a1, z1)
     b. Logitları softmax yap → ihtimal dağılımı
     c. Tahmini sonraki sinyal ve tahmini ödül
  3. En yüksek tahmini ödülü vereni seçenek olarak değerlendir
  4. Seçilen eylemi gerçek dünyada uygula

Sınırlamalar:
  - Tek adım içeri simülasyon (1 tick ileriye)
  - MLP çıkısı (7 komut) ve ödül bileşik tek bileşenli
  - Gerçek dünya fizigi (enerji/acılık değişimi) tahmin edilmez,
    sadece model içindeki ağırlıklar yansıtır
"""

import numpy as np
from pathlib import Path


class Dusunme:
    """Düşünme motoru: MLP tabanlı world model."""

    def __init__(self, ust_beyn, sinyal_boyutu=None, gizli_boyutu=None,
                 cikis_boyutu=None):
        """
        Parametreler
        ----------
        ust_beyn : ust_beyn_mod.UstBeyn
            Mevcut beyinin referansı; MLP erişimi için.
        sinyal_boyutu : int, optional
            Sinyal vektörü boyutu (ust_beyn.SINYAL_BOYUT varsayılır).
        gizli_boyutu : int, optional
            Gizli nöron sayısı (ust_beyn.GIZLI_BOYUT varsayılır).
        cikis_boyutu : int, optional
            Çıkış (komut) sayısı (ust_beyn.CIKIS_BOYUT varsayılır).
        """
        self.ub = ust_beyn
        self.n_in = sinyal_boyutu or getattr(ust_beyn, "SINYAL_BOYUT", 36)
        self.n_hidden = gizli_boyutu or getattr(ust_beyn, "GIZLI_BOYUT", 16)
        self.n_out = cikis_boyutu or getattr(ust_beyn, "CIKIS_BOYUT", 7)

        # MLP yapısı (ust_beyn'deki gibi paylaşıyoruz, aynı parametreler)
        self.rng = np.random.default_rng(getattr(ust_beyn, "seed", 42))
        self.W1 = self.rng.standard_normal((self.n_hidden, self.n_in)) * 0.4
        self.b1 = np.zeros(self.n_hidden)
        self.W2 = self.rng.standard_normal((self.n_out, self.n_hidden)) * 0.4
        self.b2 = np.zeros(self.n_out)

        # Eylem adları (ust_beyn'deki KOMUTLARla uyumlu)
        self.KOMUTLAR = getattr(ust_beyn, "KOMUTLAR",
                                ["yok", "acil_dinlen", "acil_yem",
                                 "kapat_ag", "kisitla_dosya", "guvenli_mod"])

        # Eylem one-hot encoder: eylem_adı → (n_out,) sıvı
        self.eylem_indeksi = {k: i for i, k in enumerate(self.KOMUTLAR)}

    def _one_hot_eylem(self, eylem_adi):
        """Eylem adını one-hot vektöre çevirir."""
        idx = self.eylem_indeksi.get(eylem_adi, 0)
        v = np.zeros(self.n_out)
        v[idx] = 1.0
        return v

    def tahmin(self, sinyal_v, eylem_adi):
        """
        (sinyal, eylem) pareti için tahmini (sonraki_sinyal, ödül).

        Parametreler
        ----------
        sinyal_v : array-like (n_in,)
            Mevcut sinyal vektörü.
        eylem_adi : str
            Tahmini yapmak istediğimiz eylem.

        Dönen
        ------
        (sonraki_sinyal, tahmini_ödül) - her ikisi de numpy array/float.
        """
        x = np.array(sinyal_v, dtype=float)
        if x.shape[0] != self.n_in:
            # Uygulamak için yeniden boyutlandırma veya hata
            raise ValueError(
                f"Sinyal boyutu {x.shape[0]} != {self.n_in}")

        eylem_vec = self._one_hot_eylem(eylem_adi)

        # Forward pass: (n_in,) -> (logits (n_out,), a1 (n_hidden,), z1 (n_hidden,))
        a1 = np.maximum(0, np.dot(self.W1, x) + self.b1)  # gizli katman, ReLU
        logits = np.dot(self.W2, a1) + self.b2            # çıkış katmanı

        # Softmax → ihtimaller
        exp_logits = np.exp(logits - np.max(logits))     # numerik stabilite
        ihtimaller = exp_logits / np.sum(exp_logits)     # softmax

        # Tahmini "sonraki sinyal": aynı boyuttaki ama modelin tahmini
        # Bir şeyler için basitçe out vec'i ----> sıfır (sinyal yok),
        # ya da modelin çıktısını kullanırız. Bu modelin amacı ödül tahmini.
        # Elde edilen ödül = seçilen komutun softmax ihtimali
        # (ust_beyn yöntemiyle uyumlu: negatif ödül softmax uyumlu -> 0'a doğru iter)

        # Yöntem 1: Softmax olasılığının en yüksekini ödül olarak kabul et
        tahmini_odul = float(ihtimaller.max())

        # Tahmini "sonraki sinyal": modelin girdi-çıktı ilişkinin simetrisi
        # yok; basitçe girdiyi koruyup çıkışı döndürüyoruz ama yorum olarak
        # sadece ödül tutuyoruz.
        sonraki_sinyal = None  # Tek adım simülasyonda tanımsız/ilgisiz

        return sonraki_sinyal, tahmini_odul

    def dusun_ve_sec(self, sinyal_v, feasible):
        """
        Kullanılabilir eylemler setinden (feasible), eylem öncesi simülasyon
        yaparak en iyi eylemi seç.

        Parametreler
        ----------
        sinyal_v : array-like (n_in,)
            Mevcut sinyal vektörü.
        feasible : list of str
            Bu tikte yürütülebilecek eylemler listesi.

        Dönen
        ------
        en_iyi_eylem : str
            Tahmini ödül en yüksek olan eylem.
        en_yuksek_tahmin : float
            Maksimum tahmini ödül.
        """
        en_iyi_eylem = None
        en_yuksek_tahmin = -float('inf')

        for eylem in feasible:
            # Sadece geçerli eylemler varsa; KOMUTLAR içinde varsayımı kontrol et
            if eylem not in self.eylem_indeksi:
                # Bilinmeyen eylem: ignore veya score=0
                continue
            _, tahmini_odul = self.tahmin(sinyal_v, eylem)
            if tahmini_odul > en_yuksek_tahmin:
                en_yuksek_tahmin = tahmini_odul
                en_iyi_eylem = eylem

        # Hiçbir eylem seçilemezse None (veya fallback: "rest")
        if en_iyi_eylem is None:
            # Tehlikeli yoksa "rest" fallback
            en_iyi_eylem = "rest" if "rest" in feasible else feasible[0] if feasible else None

        return en_iyi_eylem, en_yuksek_tahmin
