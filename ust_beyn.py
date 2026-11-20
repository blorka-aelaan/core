"""ust_beyn.py — Üst (Genel) Beyin: NumPy MLP tabanlı gerçek öğrenen yapay zeka.

Mimari:
  36 giriş (sinyal vektörü) → 16 gizli nöron (ReLU) → 7 çıkış (softmax)

Sinyal toplayıcı: pure Python.
MLP (nöron/ağırlık işlemleri): NumPy.

Çıkış sınıfları:
  0: yok (override yok)
  1: acil_dinlen
  2: acil_yem
  3: kapat_ag
  4: kisitla_dosya
  5: guvenli_mod
  6: sifirla
  7: asm_ogren
  8: kod_duzenle
  9: gossip
  10: cocuk_olustur
  11: ag_tara

Öğrenme: çevrimiçi (online). Her tikte bir karar alınır, ardından
gerçek sonuç (ödül) ogren() ile beyine geri verilir ve ağırlıklar
backprop ile güncellenir. Epsilon-greedy keşif ile yeni stratejiler
denenmeye devam eder.

Ödül sinyali: tek bileşenli enerji farkı DEĞİL — bileşik ödül:
  - enerji değişimi (ölçeklenmiş)
  - acı / kurtuluş
  - güvenlik uygulama (saldırı engelleme)
  - dosya kısıtlama / ağ kapatma (görev başarısı)
  - hayatta kalma
Negatif ödül softmax uyumludur: hedef vektörü asla negatif değil,
onun yerine "doğru sınıfın olasılığı düşürülür" (sıfır-sum hedef).

Güvenlik: eğitilmemiş/keşif komutları canlı sistemde etkili olmaz.
Komut yalnızca güven eşiğini geçerse uygulanır; aksi halde
KOMUT_YOK'a düşer.

Kayıt: zeka/ust_beyn.json
"""

import json
import os
import random
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, List

import numpy as np

from uzuv import asm_ogren

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------- Komutlar
KOMUT_YOK = None
KOMUT_ACIL_DINLEN = "acil_dinlen"
KOMUT_ACIL_YEM = "acil_yem"
KOMUT_KAPAT_AG = "kapat_ag"
KOMUT_KISITLA_DOSYA = "kisitla_dosya"
KOMUT_GUVENLI_MOD = "guvenli_mod"
KOMUT_SIFIRLA = "sifirla"  # Feature #2: World Model + reset komutu
KOMUT_ASM_OGREN = "asm_ogren"  # Yeni: ASM (x86-64) program öğrenme eylemi
# Yeni: Yapısal evrim (Aşama 7)
KOMUT_KOD_DUZENLE = "kod_duzenle"  # Kendi kodunu düzenle
KOMUT_GOSSIP = "gossip"             # P2P durum paylaşımı
KOMUT_COCUK_OLUSTUR = "cocuk_olustur"  # Çoğaltma / çocuk yarat
KOMUT_AG_TARA = "ag_tara"           # Yeni: Ağ keşif tarama (ag_beyin entegrasyonu)

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
CIKIS_BOYUT = len(KOMUTLAR)  # 13
SINYAL_SURUMU = 3
UST_MODEL_SURUMU = 4

# Sinyal vektörü indeks sabitleri (topla_sinyalleri ile aynı sırada)
# 0 enerji, 1 açlık, 2 acı, 3 sıkılma, 4 tehlike, 5 canlı,
# 6-8 beyin max/min/marj, 9-11 beyin eps/lr/bağlantı,
# 12-14 damak, 15-16 güvenlik, 17-19 süreç (eksik/yeni/anomali),
# 20 şok bekliyor, 21 mesaj var, 22 şok miktarı, 23 ölüm riski,
# 24 dünya bozuk, 25 sürpriz, 26 görev, 27-32 bağlam (6 slot)
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
IDX_BAGLAM = 27
# ---------- Yeni: Beden duyuları (Aşama 1) ----------
IDX_MOOD_MUTLULUK = 33
IDX_MOOD_KORKU = 34
IDX_MOOD_MERAK = 35
IDX_CPU_YUK = 36
IDX_PROSES_NORM = 37
IDX_DISK_YUZDE = 38
IDX_BELLEK_YUZDE = 39
IDX_USB_CIHAZ = 40
IDX_USB_KEŞIF = 41
IDX_AG_BAGLANTI = 42
IDX_INSAN_VAR = 43
IDX_SISTEM_SAATI = 44
IDX_DISK_BASKI = 45
IDX_BELLEK_BASKI = 46
IDX_BEDEN_BASKI = 47


# --------------------------------------------------------------- NumPy MLP
class TinyMLP:
    """NumPy tabanlı çok küçük MLP: giriş → gizli(ReLU) → çıkış(softmax)."""

    def __init__(self, n_in, n_hidden, n_out, seed=None):
        # Yerel RNG: global np.random.seed() diğer modülleri bozuyordu
        self.rng = np.random.default_rng(seed)
        self.n_in = n_in
        self.n_hidden = n_hidden
        self.n_out = n_out
        self.W1 = self.rng.standard_normal((n_hidden, n_in)) * 0.4
        self.b1 = np.zeros(n_hidden)
        self.W2 = self.rng.standard_normal((n_out, n_hidden)) * 0.4
        self.b2 = np.zeros(n_out)
        # Momentum
        self.VW1 = np.zeros((n_hidden, n_in))
        self.Vb1 = np.zeros(n_hidden)
        self.VW2 = np.zeros((n_out, n_hidden))
        self.Vb2 = np.zeros(n_out)

    def genislet(self, yeni_n_out):
        """Çıkış katmanını genişletir (yeni nöronlar için rastgele ağırlık)."""
        if yeni_n_out <= self.n_out:
            return
        delta = yeni_n_out - self.n_out
        # Yeni W2 satırları: (delta, n_hidden)
        yeni_W2 = self.rng.standard_normal((delta, self.n_hidden)) * 0.4
        self.W2 = np.vstack([self.W2, yeni_W2])
        # Yeni b2: (delta,)
        yeni_b2 = np.zeros(delta)
        self.b2 = np.concatenate([self.b2, yeni_b2])
        # Momentum matrisleri genişlet
        yeni_VW2 = np.zeros((delta, self.n_hidden))
        self.VW2 = np.vstack([self.VW2, yeni_VW2])
        yeni_Vb2 = np.zeros(delta)
        self.Vb2 = np.concatenate([self.Vb2, yeni_Vb2])
        self.n_out = yeni_n_out

    def forward(self, x):
        """x: (n_in,) → (logits, a1, z1)"""
        z1 = self.W1 @ x + self.b1
        a1 = np.maximum(0.0, z1)  # ReLU
        z2 = self.W2 @ a1 + self.b2
        return z2, a1, z1

    def predict(self, x):
        logits, _, _ = self.forward(x)
        return _softmax(logits)

    def backward(self, x, hedef_vektor, lr=0.05, momentum=0.9):
        """hedef_vektor: (n_out,) one-hot scaled by reward"""
        logits, a1, z1 = self.forward(x)
        probs = _softmax(logits)

        d2 = probs - hedef_vektor  # (n_out,)
        d1 = (self.W2.T @ d2) * (z1 > 0)  # (n_hidden,)

        # Momentumlu güncelleme
        self.VW2 = momentum * self.VW2 - lr * np.outer(d2, a1)
        self.W2 += self.VW2
        self.Vb2 = momentum * self.Vb2 - lr * d2
        self.b2 += self.Vb2

        self.VW1 = momentum * self.VW1 - lr * np.outer(d1, x)
        self.W1 += self.VW1
        self.Vb1 = momentum * self.Vb1 - lr * d1
        self.b1 += self.Vb1

        return probs


def _softmax(logits):
    m = np.max(logits)
    exps = np.exp(logits - m)
    return exps / np.sum(exps)


# --------------------------------------------------------------- Üst Beyin
class UstBeyn:
    """Gerçek öğrenen üst beyin (NumPy MLP).

    Alt sistemlerden gelen 36 boyutlu sinyal vektörünü alır ve bir
    override komutu seçer. Sonuç (ödül) ogren() ile geri verildiğinde
    MLP ağırlıkları backprop ile güncellenir.

    Normal zamanda "yok" (komut 0) seçilir, override gerekmediğinde
    alt beyinler serbestçe davranır.

    Güvenlik ağı: bir komutun canlıda uygulanabilmesi için (a) modelin
    o sınıfa verdiği olasılık 'guven_esigi' üstünde olmalı VE (b) komut
    daha önce olumlu ödülle desteklenmiş olmalı ('dogrulanmis'). Aksi
    halde komut reddedilir ve KOMUT_YOK'a düşülür — eğitilmemiş rastgele
    bir 'kapat_ag'/'acil_yem' canlı sistemi bozamaz.
    """

    eylem_katalogu = {
        "bilgi_topla": {"risk": 0.15, "cost": 0.20, "gain": 0.75, "requires_verification": False},
        "dosya_tara": {"risk": 0.25, "cost": 0.30, "gain": 0.85, "requires_verification": False},
        "network_tara": {"risk": 0.45, "cost": 0.50, "gain": 0.90, "requires_verification": True},
        "asm_ogren": {"risk": 0.55, "cost": 0.65, "gain": 0.95, "requires_verification": True},
        "komut_ver": {"risk": 0.70, "cost": 0.55, "gain": 0.80, "requires_verification": True},
        "dogrula": {"risk": 0.10, "cost": 0.30, "gain": 0.85, "requires_verification": False},
    }
    eylem_bilgi = {}

    def __init__(self, cfg, root=None, seed=7, ag_beyin=None):
        self.cfg = cfg or {}
        self.root = Path(root or ROOT)
        self.seed = 7 if seed is None else seed
        self.rng = random.Random(self.seed)
        # --- ag_beyin entegrasyonu ---
        self.ag_beyin = ag_beyin  # AgBeyin örneği (ağ keşif orkestrasyonu)
        self._son_scan_odulu = 0.0  # Son tarama ödülü (ust.ogren ile beslenir)
        self._son_scan_tik = 0  # Son tarama tik'i

        self.mlp = TinyMLP(
            SINYAL_BOYUT, GIZLI_BOYUT, CIKIS_BOYUT, seed=self.seed
        )

        self.epsilon = 0.15
        self.epsilon_min = 0.05
        self.epsilon_max = 0.60
        # Sönümleme yavaş: model güven eşiğine ulaşmadan keşif
        # tükenirse sistem kilitlenir (keşif kanıtı da biter).
        self.epsilon_decay = 0.99985
        # ---------- Yeni: Dinamik epsilon parametreleri ----------
        self.eps_base = 0.15      # taban keşif oranı
        self.eps_sikilma_karani = 0.4   # sıkılma arttıkça epsilon artışı
        self.eps_agri_karani = 0.7      # acı arttıkça epsilon azalışı (hayatta kalma öncelikli)

        # Güvenlik ağı: komut uygulanmadan önce geçmesi gereken eşik.
        # Güven artık MARJ tabanlıdır (bkz. _guven_hesapla): modelin
        # en iyi seçimi ile ikinci en iyisi arasındaki fark, normalize
        # edilmiş hâlde. 0.30 marj = "belirgin bir tercih var" demektir.
        # (Ham olasılık eşiği kullanılırsa 7 sınıflı softmax'te model
        #  asla 0.30'u geçemez — her karar 'guven_yetersiz' ile
        #  reddedilir ve sistem kilitlenir.)
        self.guven_esigi = 0.45
        # Marj ölçeği: hangi marj değeri "güven 1.0" sayılır?
        # 0.15 marj → normalize 1.0 (belirgin tercih eşiği).
        self.marj_olcek = 0.15
        # Kanıt ölçeği: tek bir olumlu ödül, doğrulama puanına ne kadar
        # ekler? doğrulama_esigi ile eşleşmeli — ödül≈1.0 iken tek
        # kanıt eşiği doldurabilmeli (kanıt_çarpanı = doğrulama_esigi).
        self.kanit_çarpanı = 0.35
        # Komutun 'öğrenilmiş ve doğrulanmış' sayılması için gereken
        # birikimli olumlu ödül eşiği
        self.dogrulama_esigi = 0.35
        # Ödül tabanlı güven puanı (her komut için birikimli).
        #
        # DİKKAT: Bu puan GLOBAL'dir — bir komut bir bağlamda işe
        # yaradıysa başka bağlamda da "doğrulanmış" sayılır. Bu,
        # "kapat_ag" gibi her koşulda işe yarayan komutlar için sorun
        # DEĞİLDİR, ama bağlama bağlı komutlar (acil_yem yalnızca
        # açlıkta işe yarar) için yanlış onay üretir: model açlık
        # olmadığında da acil_yem'i onaylayabilir.
        #
        # Çözüm: aşağıda `dogrulama_bağlam` ile BAĞLAM BAZLI puan
        # tutulur; güvenlik ağı önce bağlamsal puanı, yetmezse global
        # puanı kontrol eder.
        self.dogrulama = [0.0] * CIKIS_BOYUT
        # Bağlam bazlı doğrulama puanı.
        # anahtar: (komut_idx, baglam_anahtarı) → puan
        # Bağlam, komutun ANLAMLI olduğu durumu özetler: açlık var mı,
        # tehlike var mı, mesaj var mı... Böylece "acil_yem" yalnızca
        # açlık bağlamında doğrulanmış sayılır.
        self.dogrulama_bağlam = {}
        # Override ömrü: kaç tik boyunca komut etkili kalsın
        self.sure = 0
        self.sure_azami = 0
        self.son_komut = KOMUT_YOK
        self.son_idx = 0
        # Komut reddedilme (eşik altı) sayacı — günlük için
        self.reddedilen = 0

        # Kilitlenme kırıcı: ardışık reddetme ve sıfırla-no-op takibi
        self.RED_SERI_MAKS = 1            # kaç ardışık reddedilmede cooldown başlar
        self.redd_serisi = [0] * CIKIS_BOYUT   # komut bazlı ardışık reddetme sayısı
        self.redd_cooldown = [0] * CIKIS_BOYUT # komut bazlı cooldown kalan tik

        # Sıfırla (sifirla) cooldown ve zamanlama
        self.sifirla_son_tik = 0
        self.SIFIRLA_ARALIK = 10  # en az 10 tik sonra yeniden sıfırla
        self.sifirla_noop_serisi = 0

        self.samples = 0
        self.tik = 0
        self.secim_sayilari = [0] * CIKIS_BOYUT
        # Reddedilen karar sayıları (kilitlenme teşhisi ve şeffaflık)
        self.reddedilen_sayilari = [0] * CIKIS_BOYUT
        # Son kalite ölçümü: ödül geçmişi (replay için)
        self.odul_gecmisi = []
        # Kısa hafıza: son kararlar ve güven skorları; bu, doğru seçimleri
        # daha iyi değerlendirmek için kararların bağlamını tutar.
        self.kisa_hafiza = deque(maxlen=64)
        # Hata kategorisi: reddedilme/negatif ödül gibi olayların bağlam
        # içindeki dağılımını kaydeder; sistem kendi neyi yanlış yaptığını
        # öğrenebilir.
        self.hata_kategorisi = {}
        self.journal = SimpleNamespace(log=lambda *args, **kwargs: None)
        self.last_confidence = 0.0
        self.last_komut_idx = KOMUT_INDEKSI[KOMUT_YOK]
        # Dünya modeli: bağlam bazlı geçmiş ödül örüntülerini hatırlar.
        # Bu, bir komutun sadece "güvenli" değil, "bu bağlamda faydalı"
        # olduğunu da değerlendirmesini sağlar.
        self.dunya_modeli = {}
        # Özbenlik modeli: sistemin kendi istikrarını, kırılganlığını ve
        # karar güveni için gereken yeniden ayarlamayı anlaması.
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
        # Özbenlik modeli: sistemin kendi istikrarını, kırılganlığını ve
        # karar güveni için gereken yeniden ayarlamayı anlaması.
        self.ozben_modeli = {
            "durum": "hazir",
            "istikrar": 0.0,
            "hata_orani": 0.0,
            "ortalama_odul": 0.0,
            "guven_duyarliligi": 0.0,
        }

        # ------------------------------------------------- ASM öğrenme alt sistemi
        # Lazy başlatılır (ilk asm_* çağrısında), normal işletmede ağır olmaz.
        self._asm_öğrenici = None

        # Üst beyin, sadece asm_ogren değil, tüm eylem türlerini bilir:
        # bilgi toplama, dosya/ağ tarama, çözüm üretme ve doğrulama.
        self.eylem_katalogu = {
            "bilgi_topla": {
                "risk": 0.15, "cost": 0.20, "gain": 0.75,
                "requires_verification": False,
            },
            "dosya_tara": {
                "risk": 0.25, "cost": 0.30, "gain": 0.85,
                "requires_verification": False,
            },
            "network_tara": {
                "risk": 0.45, "cost": 0.50, "gain": 0.90,
                "requires_verification": True,
            },
            "asm_ogren": {
                "risk": 0.55, "cost": 0.65, "gain": 0.95,
                "requires_verification": True,
            },
            "komut_ver": {
                "risk": 0.70, "cost": 0.55, "gain": 0.80,
                "requires_verification": True,
            },
            "dogrula": {
                "risk": 0.10, "cost": 0.30, "gain": 0.85,
                "requires_verification": False,
            },
        }
        self.eylem_bilgi = {}

        self._load()

    # ------------------------------------------------- Yeni: Dinamik epsilon
    def update_dynamic_params(self, drives):
        """Enerji, acı ve sıkılmaya göre epsilon'ı dinamik ayarla.

        - Düşük enerji / acı (yaşama tehlikesi): epsilon düşer (daha az keşif,
          daha çok riflenen eylem).
        - Yüksek sıkılma: epsilon rises (rutin kırılmalı).
        - Homeostaz düşükse: epsilon sınırlıdır (survival first).
        """
        e_cap = max(1.0, float(getattr(drives, "energy_cap", 150)))
        e_ratio = max(0.0, min(1.0, float(getattr(drives, "energy", 50)) / e_cap))
        _pain = getattr(drives, "pain", 0.0)
        pain_raw = _pain() if callable(_pain) else _pain
        pain = float(pain_raw) if isinstance(pain_raw, (int, float)) else 0.0
        pain = max(0.0, min(1.0, pain))
        sik = max(0.0, min(1.0, float(getattr(drives, "sikilma", 0.0))))

        # epsilon: acıda çok düşük (hayatta kalma > keşif), sıkıldığında yüksel
        eps_target = self.eps_base * (1.0 + self.eps_sikilma_karani * sik) * (
            1.0 - self.eps_agri_karani * pain
        )
        # Homeostaz düşükse epsilon'ı daha da kısıtla (survival first)
        eps_target *= 0.85 + 0.3 * self.mizac["merak"]
        h = getattr(drives, "homeostaz_puani", lambda: 0.5)
        if callable(h):
            h = h()
        h_value = float(h) if isinstance(h, (int, float)) else 0.5
        if h_value < 0.45:
            eps_target *= 0.5  # uyarı modunda keşif yarım

        self.epsilon = max(self.epsilon_min, min(self.epsilon_max, eps_target))

    # ------------------------------------------------- Yeni: Yapısal evrim (Aşama 7)
    def genislet(self, yeni_komutlar):
        """MLP çıkış katmanını dinamik olarak genişletir.

        Yeni komutlar eklendiğinde çıkış nöron sayısı artar: W2, b2 ve
        ilgili takip dizileri genişletilir. Yeni ağırlıklar küçük
        rastgele değerle başlatılır (sıfırdan başlayan yeni eylem,
        eski bilgiyi bozmaz).

        Parametreler
        ----------
        yeni_komutlar : list[str]
            Eklenecek komut adları (zaten varsa atlanır).

        Döner
        -----
        eklenen : list[str]
            Gerçekten eklenen komut adları.
        """
        eklenen = []
        for ad in yeni_komutlar:
            if ad in KOMUT_INDEKSI:
                continue
            # Yeni komutu kaydet
            yeni_idx = len(KOMUTLAR)
            KOMUTLAR.append(ad)
            KOMUT_INDEKSI[ad] = yeni_idx
            eklenen.append(ad)

        if not eklenen:
            return eklenen

        n_eski = self.mlp.n_out if hasattr(self.mlp, "n_out") else CIKIS_BOYUT
        n_yeni = len(KOMUTLAR)
        delta = n_yeni - n_eski

        # MLP'i genişlet
        self.mlp.genislet(n_yeni)

        # CIKIS_BOYUT'u güncelle (modül sabiti)
        globals()["CIKIS_BOYUT"] = n_yeni

        # Takip dizilerini genişlet
        eski_dogrulama = self.dogrulama
        self.dogrulama = [0.0] * n_yeni
        self.dogrulama[:n_eski] = eski_dogrulama

        eski_redd_serisi = self.redd_serisi
        self.redd_serisi = [0] * n_yeni
        self.redd_serisi[:n_eski] = eski_redd_serisi

        eski_redd_cooldown = self.redd_cooldown
        self.redd_cooldown = [0] * n_yeni
        self.redd_cooldown[:n_eski] = eski_redd_cooldown

        eski_secim = self.secim_sayilari
        self.secim_sayilari = [0] * n_yeni
        self.secim_sayilari[:n_eski] = eski_secim

        eski_reddedilen = self.reddedilen_sayilari
        self.reddedilen_sayilari = [0] * n_yeni
        self.reddedilen_sayilari[:n_eski] = eski_reddedilen

        self.journal.log("beyin_genislet", eklenen=eklenen,
                         onceki_n_out=n_eski, yeni_n_out=n_yeni)
        return eklenen


        """Enerji, acı ve sıkılmaya göre epsilon'ı dinamik ayarla.

        - Düşük enerji / acı (yaşama tehlikesi): epsilon düşer (daha az keşif,
          daha çok riflenen eylem).
        - Yüksek sıkılma: epsilon rises (rutin kırılmalı).
        - Homeostaz düşükse: epsilon sınırlıdır (survival first).
        """
        e_cap = max(1.0, float(getattr(drives, "energy_cap", 150)))
        e_ratio = max(0.0, min(1.0, float(getattr(drives, "energy", 50)) / e_cap))
        _pain = getattr(drives, "pain", 0.0)
        pain = float(_pain() if callable(_pain) else _pain)
        pain = max(0.0, min(1.0, pain))
        sik = max(0.0, min(1.0, float(getattr(drives, "sikilma", 0.0))))

        # epsilon: acıda çok düşük (hayatta kalma > keşif), sıkıldığında yüksel
        eps_target = self.eps_base * (1.0 + self.eps_sikilma_karani * sik) * (
            1.0 - self.eps_agri_karani * pain
        )
        # Homeostaz düşükse epsilon'ı daha da kısıtla (survival first)
        h = getattr(drives, "homeostaz_puani", lambda: 0.5)
        if callable(h):
            h = h()
        if h < 0.45:
            eps_target *= 0.5  # uyarı modunda keşif yarım

        self.epsilon = max(self.epsilon_min, min(self.epsilon_max, eps_target))

    # --------------------------------------------------------------- Bağlam
    def baglam_anahtari(self, sinyal_vektor):
        """Durumun GENEL bağlam özeti (bit maskesi).

        1 = açlık, 2 = tehlike, 4 = mesaj var.

        Bu anahtar DURUMUN kendisini özetler; hangi komut için
        anlamlı olduğu komuta göre değişir (bkz.
        komut_baglam_anahtari). Kanıt biriktirme KESİNLİKLE
        komut_baglam_anahtari ile yapılır.
        """
        x = np.asarray(sinyal_vektor, dtype=float)
        if x.size <= IDX_ACLIK:
            return "genel"
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0
                   or (x.size > IDX_OLUM_RISK
                       and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0
                 if x.size > IDX_MESAJ_VAR else False)
        bit = (1 if acik else 0) | (2 if tehlike else 0) | (4 if mesaj else 0)
        return "b%d" % bit

    def komut_baglam_anahtari(self, komut_idx, sinyal_vektor):
        """Komuta ÖZGÜ bağlam anahtarı — kanıt biriktirmenin anahtarı.

        NEDEN komuta özgü? Genel bit maskesi (açlık|tehlike|mesaj)
        kanıtı YANLIŞ YERE böler. Örnek: "acil_yem" yalnızca
        AÇLIKTA anlamlıdır; tehlike/mesaj durumu onun ön
        koşulu değildir. Genel maskeyle kanıt "b1" (açlık) ve
        "b3" (açlık+tehlike) arasında bölünürdü → açlıkta bile
        "tehlike bağlamında kanıt yok" denir → komut sürekli
        "dogrulanmadi" ile reddedilir (gözlenen: 300 kez).

        Doğru ilke: kanıt, komutun ÖN KOŞULU üzerinden
        sınıflandırılmalıdır. "acil_yem"in ön koşulu "açlık"tır;
        o koşul sağlandığında, tehlike/mesaj olsun olmasın,
        toplanan kanıt geçerlidir.

          * acil_yem     → "acik"        (yalnızca açlık)
          * acil_dinlen  → "tehlike"     (yalnızca tehlike)
          * guvenli_mod  → "tehlike"     (yalnızca tehlike)
          * kapat_ag     → "tehlike|sok" (tehlike veya sok bekliyor)
          * kisitla_dosya→ "mesaj|tehlike"
          * yok          → bağlamdan bağımsız (pasif)
        """
        x = np.asarray(sinyal_vektor, dtype=float)
        if x.size <= IDX_ACLIK:
            return "genel"
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0
                   or (x.size > IDX_OLUM_RISK
                       and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0
                 if x.size > IDX_MESAJ_VAR else False)
        sok = (float(x[IDX_SOK_BEKLIYOR]) > 0.0
               if x.size > IDX_SOK_BEKLIYOR else False)
        if komut_idx == KOMUT_INDEKSI[KOMUT_ACIL_YEM]:
            # Ön koşul sağlanmıyorsa AYRI anahtar: açlık yokken
            # toplanan (ya da toplanması gereken) kanıt, açlık
            # bağlamına TAŞINMAZ.
            return "acik" if acik else "acik_yok"
        if komut_idx in (KOMUT_INDEKSI[KOMUT_ACIL_DINLEN],
                         KOMUT_INDEKSI[KOMUT_GUVENLI_MOD]):
            return "tehlike" if tehlike else "tehlike_yok"
        if komut_idx == KOMUT_INDEKSI[KOMUT_KAPAT_AG]:
            return "tehlike" if (tehlike or sok) else "sakin"
        if komut_idx == KOMUT_INDEKSI[KOMUT_KISITLA_DOSYA]:
            return "tehlike" if (mesaj or tehlike) else "sakin"
        if komut_idx == KOMUT_INDEKSI[KOMUT_AG_TARA]:
            return "genel"  # Ağ tarama her zaman anlamlı (kapsam kilidi ag_beyin'de)
        # Bağlamdan bağımsız komutlar.
        return "genel"

    def _dunya_model_tahmini(self, sinyal_vektor, komut_idx):
        """Geçmiş bağlamlarda aynı komutun ortalama ödülünü döndürür."""
        x = np.asarray(sinyal_vektor, dtype=float)
        bag = self.baglam_anahtari(x)
        entry = self.dunya_modeli.get(bag, {})
        history = entry.get(int(komut_idx), [])
        if not history:
            return 0.0
        return float(sum(history) / max(1, len(history)))

    def _dunya_model_guncelle(self, sinyal_vektor, komut_idx, odul):
        """Dünya modelini, gerçek sonuçla birlikte günceller."""
        x = np.asarray(sinyal_vektor, dtype=float)
        bag = self.baglam_anahtari(x)
        entry = self.dunya_modeli.setdefault(bag, {})
        history = entry.setdefault(int(komut_idx), [])
        history.append(float(odul))
        if len(history) > 16:
            history.pop(0)

    def _uzun_hafizayi_guncelle(self, komut_idx, odul):
        """Gerçek sonuçları sınırlı boyutlu, ömür boyu özetler."""
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

    def kendini_tanimla(self):
        """Aelaan'ın kimliğini ve iç değerlendirmesini döndürür."""
        return {
            "kimlik": dict(self.kimlik),
            "deger_profili": dict(self.deger_profili),
            "mizac": dict(self.mizac),
            "ozben_modeli": dict(self.ozben_modeli),
            "uzun_hafiza": {
                **self.uzun_hafiza,
                "komutlar": {ad: dict(veri) for ad, veri in self.uzun_hafiza["komutlar"].items()},
            },
        }

    def _hedef_oncelik_puani(self, sinyal_vektor, komut_idx):
        """İçsel hedef hiyerarşisi: hayatta kalma > enerji > keşif."""
        x = np.asarray(sinyal_vektor, dtype=float)
        if x.size <= IDX_ACLIK:
            return 0.0
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                   (x.size > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
        enerji = float(x[IDX_ENERJI]) if x.size > IDX_ENERJI else 0.5

        if komut_idx == KOMUT_INDEKSI[KOMUT_ACIL_YEM] and acik:
            return 1.0
        if komut_idx in (KOMUT_INDEKSI[KOMUT_ACIL_DINLEN],
                         KOMUT_INDEKSI[KOMUT_GUVENLI_MOD]) and tehlike:
            return 1.0
        if komut_idx == KOMUT_INDEKSI[KOMUT_KAPAT_AG] and tehlike:
            return 0.8
        if komut_idx == KOMUT_INDEKSI[KOMUT_KISITLA_DOSYA] and (tehlike or enerji < 0.35):
            return 0.7
        if komut_idx == KOMUT_INDEKSI[KOMUT_YOK] and not acik and not tehlike:
            return 0.2
        return 0.0

    def _ozben_durumu(self, sinyal_vektor=None):
        """Kendi istikrarını, hata oranını ve güven duyarlılığını çıkarır."""
        x = np.asarray(sinyal_vektor, dtype=float) if sinyal_vektor is not None else None
        recent = self.odul_gecmisi[-24:] if self.odul_gecmisi else []
        avg_reward = float(sum(recent) / max(1, len(recent))) if recent else 0.0
        fail_rate = float(sum(1 for r in recent if r < 0.0) / max(1, len(recent))) if recent else 0.0
        rejection_count = sum(self.reddedilen_sayilari)
        rejection_rate = float(rejection_count / max(1, self.tik))
        danger = 0.0
        if x is not None and x.size > IDX_TEHLIKE:
            danger = float(max(x[IDX_TEHLIKE], x[IDX_OLUM_RISK] if x.size > IDX_OLUM_RISK else 0.0))
        lifetime = self.uzun_hafiza["toplam_sonuc"]
        lifetime_failure = self.uzun_hafiza["olumsuz_sonuc"] / max(1, lifetime)
        fail_rate = max(fail_rate, 0.5 * lifetime_failure)
        boredom = float(x[IDX_SIKILMA]) if x is not None and x.size > IDX_SIKILMA else 0.0
        self.mizac = {
            "temkin": float(max(0.0, min(1.0, 0.25 + 0.45 * fail_rate + 0.3 * rejection_rate))),
            "merak": float(max(0.0, min(1.0, 0.2 + 0.55 * boredom + 0.25 * (1.0 - lifetime_failure) - 0.3 * danger))),
            "sebat": float(max(0.0, min(1.0, 0.4 + 0.4 * (1.0 - fail_rate) + 0.2 * max(0.0, avg_reward)))),
        }
        if avg_reward > 0.25 and fail_rate < 0.2 and rejection_rate < 0.25 and danger < 0.5:
            durum = "stabil"
            istikrar = 0.8 + min(0.2, avg_reward)
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

    def komut_kanit_puani(self, komut_idx, sinyal_vektor):
        """Komutun BU bağlamdaki kanıt puanı (tek kaynak).

        Hem doğrulama kontrolü hem de kanıt-ağırlıklı pay dağılımı
        BU fonksiyonu kullanır — böylece ikisi ASLA tutarsız
        olamaz (aynı kanıta bakıp farklı sonuç çıkarma hatası).
        """
        if self.komut_her_kosulda_gecerli_mi(komut_idx):
            return self.dogrulama[komut_idx]
        anahtar = (int(komut_idx),
                   self.komut_baglam_anahtari(komut_idx, sinyal_vektor))
        return self.dogrulama_bağlam.get(anahtar, 0.0)

    # --------------------------------------------------------------- Uygunluk
    def komut_uygun_mu(self, komut_idx, sinyal_vektor):
        """Komut BU bağlamda anlamlı/uygulanabilir mi?

        Her komutun kendine ait bir ön koşulu vardır:
          * acil_yem     → ancak AÇLIK varken (yoksa boşuna dene)
          * acil_dinlen  → ancak TEHLİKE varken
          * guvenli_mod  → ancak TEHLİKE varken
          * kapat_ag     → ancak saldırı/tehlike varken
          * kisitla_dosya→ ancak mesaj/ölüm riski varken
          * yok          → her koşulda

        Bu kontrol güvenlik ağının ÖNÜNDE çalışır: koşulu sağlanmayan
        bir komut, geçmişte doğrulanmış olsa bile UYGULANMAMALIDIR
        (durum uyumsuzluğu). Aksi halde "acil_dinlen" tehlike
        olmadığı bir anda doğrulanmış olduğu için onaylanır ve
        sistem gereksiz yere kilitlenir.
        """
        x = np.asarray(sinyal_vektor, dtype=float)
        if x.size <= IDX_ACLIK:
            return True
        acik = float(x[IDX_ACLIK]) > 0.5
        tehlike = (float(x[IDX_TEHLIKE]) > 0.0
                   or (x.size > IDX_OLUM_RISK
                       and float(x[IDX_OLUM_RISK]) > 0.0))
        mesaj = (float(x[IDX_MESAJ_VAR]) > 0.0
                 if x.size > IDX_MESAJ_VAR else False)
        sok = (float(x[IDX_SOK_BEKLIYOR]) > 0.0
               if x.size > IDX_SOK_BEKLIYOR else False)
        if komut_idx == KOMUT_INDEKSI[KOMUT_ACIL_YEM]:
            return acik
        if komut_idx in (KOMUT_INDEKSI[KOMUT_ACIL_DINLEN],
                         KOMUT_INDEKSI[KOMUT_GUVENLI_MOD]):
            return tehlike
        if komut_idx == KOMUT_INDEKSI[KOMUT_KAPAT_AG]:
            return tehlike or sok
        if komut_idx == KOMUT_INDEKSI[KOMUT_KISITLA_DOSYA]:
            return mesaj or tehlike
        if komut_idx == KOMUT_INDEKSI[KOMUT_AG_TARA]:
            # Ağ taraması her zaman kullanılabilir; ag_beyin kapsam kilidi
            # ve oran sınırlamasını kendi içerisinde yönetir.
            return True
        return True

    def _eylem_komut_hint(self, sinyal_vektor):
        """En iyi araç eylemini, canlı sistemde kullanabileceği komuta çevirir.

        Bu dönüşüm, katalogun sadece "meta" olarak kalmasını önler. Eylem
        seçimleri gerçek karar sürecine küçük ama faydalı bir önyargı olarak
        eklenir: örneğin asm öğrenim önerisi, asm_ogren komutunu işaretler.
        """
        eylem_adi, puan, uygun = self.en_iyi_eylem_sec(sinyal_vektor)
        if not uygun:
            return KOMUT_INDEKSI[KOMUT_YOK]
        x = np.asarray(sinyal_vektor, dtype=float)
        tehlike = (x.size > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
        mesaj = (x.size > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
        acik = (x.size > IDX_ACLIK and float(x[IDX_ACLIK]) > 0.5)
        if eylem_adi == "asm_ogren":
            return KOMUT_INDEKSI[KOMUT_ASM_OGREN]
        if eylem_adi == "network_tara":
            # ag_beyin entegrasyonu: network_tara → KOMUT_AG_TARA
            # Gerçek tarama işlemi ag_beyin.scan_next_step() ile yürütülür.
            return KOMUT_INDEKSI[KOMUT_AG_TARA]
        if eylem_adi == "komut_ver":
            return KOMUT_INDEKSI[KOMUT_GUVENLI_MOD] if tehlike or mesaj else KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]
        if eylem_adi == "dosya_tara":
            return KOMUT_INDEKSI[KOMUT_KISITLA_DOSYA]
        if eylem_adi == "dogrula":
            return KOMUT_INDEKSI[KOMUT_YOK]
        if eylem_adi == "bilgi_topla":
            return KOMUT_INDEKSI[KOMUT_YOK]
        return KOMUT_INDEKSI[KOMUT_YOK]

    def eylem_katalogunu_yukle(self):
        """Üst beynin araç katalogunu döndürür."""
        return {k: dict(v) for k, v in self.eylem_katalogu.items()}

    def eylem_uygulanabilir_mi(self, eylem_adi, sinyal_vektor):
        """Bir eylemin bu bağlamda uygun olup olmadığını değerlendirir."""
        if eylem_adi not in self.eylem_katalogu:
            return False
        x = np.asarray(sinyal_vektor, dtype=float)
        if eylem_adi == "bilgi_topla":
            return True
        if eylem_adi == "dosya_tara":
            return x.size > 0 and (x.size <= IDX_GOREV or float(x[IDX_GOREV]) > 0.1)
        if eylem_adi == "network_tara":
            tehlike = (x.size > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
            mesaj = (x.size > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
            return (not tehlike) or mesaj
        if eylem_adi == "asm_ogren":
            sik = float(x[IDX_SIKILMA]) if x.size > IDX_SIKILMA else 0.0
            gorev = float(x[IDX_GOREV]) if x.size > IDX_GOREV else 0.0
            return sik > 0.25 or gorev > 0.25
        if eylem_adi == "komut_ver":
            tehlike = (x.size > IDX_TEHLIKE and float(x[IDX_TEHLIKE]) > 0.0)
            mesaj = (x.size > IDX_MESAJ_VAR and float(x[IDX_MESAJ_VAR]) > 0.0)
            return tehlike or mesaj
        if eylem_adi == "dogrula":
            return x.size > 0
        return True

    def eylem_degeri(self, eylem_adi, sinyal_vektor):
        """Eylemin bağlamdaki değerini hesaplar: bilgi kazancı - risk - maliyet."""
        meta = self.eylem_katalogu.get(eylem_adi)
        if meta is None:
            return 0.0
        x = np.asarray(sinyal_vektor, dtype=float)
        risk = float(meta.get("risk", 0.0))
        cost = float(meta.get("cost", 0.0))
        gain = float(meta.get("gain", 0.0))
        if eylem_adi == "asm_ogren":
            sik = float(x[IDX_SIKILMA]) if x.size > IDX_SIKILMA else 0.0
            gorev = float(x[IDX_GOREV]) if x.size > IDX_GOREV else 0.0
            # ASM öğrenimi, sıkılma/görev baskısı yüksekken gerçek değer
            # taşır; aksi halde genel "doğrula" eylemi çok önde çıkabilir.
            gain += 0.50 * sik + 0.50 * gorev
            # Dinamik risk azaltma: sıkıldıkça (sik>0) riski düşür; boşta
            # daha da riski azalt, ancak minimum %40 oranında.
            if sik > 0.0:
                risk *= max(0.60, 1.0 - 0.35 * min(1.0, sik))
        if eylem_adi == "network_tara":
            mesaj = float(x[IDX_MESAJ_VAR]) if x.size > IDX_MESAJ_VAR else 0.0
            gain += 0.10 * mesaj
            # ag_beyin entegrasyonu: tarama hazırsa gain'i artır,
            # son scan okuyulu/başarılıysa ek bonus.
            if self.ag_beyin is not None:
                try:
                    if self.ag_beyin.next_due_in() <= 0:
                        gain += 0.15  # Tarama ventana açık
                    son_scan = self.ag_beyin.data.get("last_scan", {})
                    if son_scan.get("ok", False):
                        gain += 0.10  # Önceki tarama başarılı
                except Exception:
                    pass
        if eylem_adi == "komut_ver":
            tehlike = float(x[IDX_TEHLIKE]) if x.size > IDX_TEHLIKE else 0.0
            gain += 0.12 * tehlike
        deger = gain - risk - (cost * 0.5)
        return float(max(0.0, min(1.0, deger)))

    def en_iyi_eylem_sec(self, sinyal_vektor):
        """Bu bağlam için en uygun ve en değerli eylemi döndürür."""
        adaylar = []
        for eylem_adi in self.eylem_katalogu:
            if self.eylem_uygulanabilir_mi(eylem_adi, sinyal_vektor):
                adaylar.append((eylem_adi, self.eylem_degeri(eylem_adi, sinyal_vektor)))
        if not adaylar:
            return ("bilgi_topla", 0.0, False)
        eylem_adi, puan = max(adaylar, key=lambda item: item[1])
        return (eylem_adi, float(puan), True)

    def eylem_ogren(self, eylem_adi, odul, sinyal_vektor=None, maliyet=0.0):
        """Eylem başarısını hafızada kaydeder; üst beyin bu bilgiyi sonraki kararında kullanır."""
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

    # --------------------------------------------------------------- ag_beyin entegrasyonu

    def scan_hazir_mi(self, now: Optional[float] = None) -> bool:
        """ag_beyin scansı şu anda yapılabilir mi? (oran sınırı + kapsam kilidi)"""
        if self.ag_beyin is None:
            return False
        try:
            return self.ag_beyin.next_due_in(now) <= 0.0
        except Exception:
            return False

    def scan_calistir(self, now: float) -> Optional[Dict[str, Any]]:
        """ag_beyin üzerinden bir tarama adımı çalıştırır ve sonucu döndürür.

        Returns scan sonucu dict'i veya None (scan zaten devam ediyorsa / hazır değilse).
        """
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

    def scan_odulu_besle(self, odul: float, tik: int) -> None:
        """Tarama sonucundan elde edilen ödülü ust_beyn öğrenme sistemine besler.

        Bu sayede MLP, 'network_tara' eylemini gerçek sonuçlara göre
        değerlendirir ve daha sonraki kararlarında uygun zaman seçer.
        """
        if odul is None:
            odul = 0.0
        odul = max(-1.0, min(1.0, float(odul)))
        # eylem_bilgi üzerinden 'network_tara' için kanıt biriktir
        self.eylem_ogren("network_tara", odul)
        # MLP üzerinden doğrudan öğren: ağ tarama sonucu için
        # nötr (sıfır) sinyal vektörü kullanılır — gerçek karar bağlamı
        # yok, yalnızca eylem-ödül ilişkisi öğretilir.
        komut_idx = KOMUT_INDEKSI[KOMUT_AG_TARA]
        self.ogren(np.zeros(SINYAL_BOYUT, dtype=float), komut_idx, odul)
        self._son_scan_odulu = odul
        self._son_scan_tik = int(tik)

    def scan_ozeti(self) -> Dict[str, Any]:
        """ag_beyin scan durumu özeti (raporlama / web paneli için)."""
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

    def _dogrulama_puani(self, komut_idx, sinyal_vektor=None):
        """Komutun mevcut bağlamdaki doğrulama puanı.

        NEDEN önce bağlamsal? Bağlamsal kanıt varsa o DAHA
        GÜÇLÜDÜR: "acil_yem" tehlike bağlamında doğrulanmışsa,
        açlık bağlamındaki global puana bakmak yanlış olurdu.

        NEDEN bağlam yoksa global'e düşülmüyor? Bir komutun
        kanıtı BAĞLAMA BAĞLIDIR. "acil_yem" açlıkta doğrulandıysa,
        o kanıt tehlike bağlamında "acil_yem'i onayla" demek
        DEĞİLDİR — sadece "acil_yem bazı durumlarda işe yarar"
        demektir. Global puana düşmek, tam olarak bu hatayı
        (yanlış bağlamda onay) üretirdi.

        if komut_idx == KOMUT_INDEKSI[KOMUT_ASM_OGREN]:
            return float(x[IDX_ENERJI]) > 0.2 and not tehlike
        Bu yüzden kural şudur:
          * Bağlam için KAYIT varsa  → bağlamsal puan (güçlü kanıt)
          * Aksi → 0 (kanıt yok, onaylanmaz)

        Böylece yanlış bağlamda onay üretmek yapısal olarak
        imkânsız hâle gelir.
        """
        if sinyal_vektor is not None:
            anahtar = (int(komut_idx),
                       self.komut_baglam_anahtari(komut_idx, sinyal_vektor))
            if anahtar in self.dogrulama_bağlam:
                return self.dogrulama_bağlam[anahtar]
            # Bu komut için bu bağlamda HİÇ kanıt toplanmamış.
            # Bağlama bağlı bir komut ise global puan KULLANILMAZ
            # (yanlış bağlamda onayı engelle).
            return 0.0
        return self.dogrulama[komut_idx]

    def komut_her_kosulda_gecerli_mi(self, komut_idx):
        """Komut HER koşulda geçerli mi (ön koşulu yok mu)?

        Sifirla komutu kaldırıldığından artık hiçbir komut
        koşulsuz geçerli değil — tüm komutların bir ön koşulu vardır.
        """
        return False

    def uygun_maske(self, sinyal_vektor, yok_da_maskeli=True):
        """Bu bağlamda UYGUN olan komutların boolean maskesi.

        NEDEN MASKE? RL'de "action masking" standarttır: durumda
        geçersiz olan eylemler OLASILIK DAĞILIMINDAN ÇIKARILIR.
        Burada bu, iki kritik sorunu tek hamlede çözer:

          1) MARJ TAVANI: Uygunsuz komut (ör. açlık yokken
             "acil_yem") yüksek olasılıkta kalıp sürekli "ikinci
             en iyi" olarak marjı tavanlar. Model hiçbir kararında
             eşiği geçemez → KİLİTLENME. Maske, uygun komutlar
             arasındaki GERÇEK marjı ortaya çıkarır.

          2) ÖĞRENME HEDEFİ: Maske olmadan `ogren()` hedefi tüm
             sınıflara pay dağıtır; uygunsuz komutlar da pay
             alıp yüksek kalır. Maskeli hedef, uygunsuz komutun
             o DURUMDA hedefini 0 yapar → model duruma bağlı
             doğru eşlemeyi öğrenir.

        "yok" her zaman maskelenir (model kararı olamaz — pasif
        kilitlenme koruması).
        """
        maske = np.zeros(CIKIS_BOYUT, dtype=bool)
        for i in range(CIKIS_BOYUT):
            if yok_da_maskeli and i == KOMUT_INDEKSI[KOMUT_YOK]:
                continue
            # Kilitlenme kırıcı: cooldown'da olan komutları geçici
            # dışla (diğer komutların denenebilmesi için).
            if self.redd_cooldown[i] > 0:
                self.redd_cooldown[i] -= 1
                continue
            if self.komut_uygun_mu(i, sinyal_vektor):
                maske[i] = True
        if not maske.any():
            # Hiçbir komut bu bağlamda uygun değil: "yok" güvenli varsayılan.
            # Pasif kilitlenme koruması: sec() model kararında "yok'u asla
            # seçmez (bkz. sec()), bu yüzden burada "yok'a düşmek
            # kilitlenmeye yol açmaz.
            maske[KOMUT_INDEKSI[KOMUT_YOK]] = True
        return maske


    # --------------------------------------------------------------- Komut seç
    def _guven_hesapla(self, probs, idx):
        """Karar güvenini 'marj' (marjin) olarak hesaplar.

        NEDEN MARJ? Ham softmax olasılığı, sınıf sayısına bağlı
        kırılgan bir ölçüttür. 7 sınıflı bir softmax'te rastgele seçim
        zaten 1/7 ≈ 0.143 olasılık verir; model bir komutu "tercih"
        etse bile olasılığı ancak ~0.30-0.35'e çıkar. Eşiği ham
        olasılıkla ölçmek, modelin kaç sınıflı olduğuna göre
        kilitlenme/gevşeme yaratır (denemede tüm kararlar
        'guven_yetersiz' ile reddedildi).

        MARJ = p(en iyi) - p(ikinci en iyi). Bu:
          * sınıf sayısından BAĞIMSIZDIR (7 sınıf da olsa 20 de olsa
            "belirgin tercih" aynı marjı gerektirir),
          * doğrudan "model gerçekten bir şeyi tercih etti mi?" sorusunu
            yanıtlar,
          * 0'a yakınsa → belirsizlik (reddet), yüksekse → net tercih.

        Dönen değer 0..1 aralığına normalize edilir.
        """
        probs = np.asarray(probs, dtype=float)
        if probs.size < 2:
            return float(probs[idx]) if idx < probs.size else 0.0
        p1 = float(probs[idx])
        rakip = [float(p) for j, p in enumerate(probs) if j != idx]
        p2 = max(rakip) if rakip else 0.0
        marj = max(0.0, p1 - p2)
        # MARJ_OLCEK: marj 0.15 → "belirgin tercih" (normalize 1.0)
        return float(min(1.0, marj / self.marj_olcek))

    def _kaydet_hata(self, kategori, komut_indeksi, sinyal_vektor):
        """Bağlam bazlı hata kategorisini kaydeder."""
        x = np.asarray(sinyal_vektor, dtype=float) if sinyal_vektor is not None else None
        if x is None or x.size <= IDX_ACLIK:
            baglam = "genel"
        else:
            acik = float(x[IDX_ACLIK]) > 0.5
            tehlike = (float(x[IDX_TEHLIKE]) > 0.0 or
                       (x.size > IDX_OLUM_RISK and float(x[IDX_OLUM_RISK]) > 0.0))
            baglam = "acik" if acik else ("tehlike" if tehlike else "sakin")
        key = f"{kategori}:{baglam}:{self.komut_adi(komut_indeksi)}"
        self.hata_kategorisi[key] = self.hata_kategorisi.get(key, 0) + 1
        if len(self.hata_kategorisi) > 32:
            for _ in range(len(self.hata_kategorisi) - 32):
                self.hata_kategorisi.pop(next(iter(self.hata_kategorisi)))

    def sec(self, sinyal_vektor, epsilon=None):
        """Sinyal vektörüne göre komut seçer.

        Döndürür: (komut_adı, komut_indeksi, güven_skor_0_1, kaynak)

        kaynak: "model" (softmax argmax) veya "kesif" (epsilon-greedy).
        güven: model kararında seçilen sınıfın softmax olasılığı;
               keşif kararında da aynı sınıfın olasılığı (rastgele
               seçim bir tercih DEĞİL — güveni düşük olmalı ki
               doğrulama eşiğine erişmesin).

        Not: 'keşif' kararları güvenlik ağından geçmez (onlar zaten
        eğitilmemiştir). Uygulama kararı main.py'de 'sec' sonucunun
        güvenine göre verilir.
        """
        if epsilon is None:
            epsilon = self.epsilon

        x = np.array(sinyal_vektor, dtype=float)
        probs = self.mlp.predict(x)

        if self.rng.random() < epsilon:
            # Keşif: rastgele seçim → güven kasıtlı olarak düşük tutulur.
            # (Rastgele seçim bir tercih DEĞİLDİR; doğrulama eşiğine
            # erişebilirse model keşifle de "onay" alır ve kanıt
            # sahteleşir.)
            #
            # "yok" (pasif) SINIFI KEŞİFTE SEÇİLMEZ.
            #
            # NEDEN? "yok" uygulandığında hiçbir şey olmaz, hiçbir
            # ödül üretilmez ve hiçbir kanıt toplanmaz — keşif
            # bütçesi (epsilon) boşa harcanır. Dahası: keşif tek
            # mekanizmadır (kanıt burada birikir), "yok"a harcanan
            # her deneme, gerçek bir komutun kanıtını geciktirir.
            #
            # NOT: Uygunsuz komutlar (koşulu sağlanmayanlar) keşifte
            # DENENMEYE DEVAM EDER. Çünkü keşif tam da "bunu
            # denemediğimi bilmiyorum" demektir; maskeyi keşfe
            # uygulamak kanıt toplama yolunu kapatabilirdi
            # (ör. nötr durumda yalnızca "kapat_ag" denenirdi).
            _adaylar = [i for i in range(CIKIS_BOYUT)
                        if i != KOMUT_INDEKSI[KOMUT_YOK]]
            if not _adaylar:
                _adaylar = list(range(CIKIS_BOYUT))
            idx = self.rng.choice(_adaylar)
            # Keşif güveni DOĞRULAMA eşiğinin altında kalmalıdır:
            # rastgele tercih kanıt sayılmaz.
            gv = float(min(1.0, probs[idx] * 0.5))
            gv = min(gv, max(0.0, self.dogrulama_esigi * 0.9))
            self.last_confidence = float(gv)
            self.last_komut_idx = idx
            self.kisa_hafiza.append({
                "komut": KOMUTLAR[idx],
                "idx": int(idx),
                "confidence": float(gv),
                "baglam": self.baglam_anahtari(np.asarray(sinyal_vektor, dtype=float)),
                "source": "kesif",
            })
            return KOMUTLAR[idx], idx, gv, "kesif"

        # MODEL KARARI — ACTION MASKING ile.
        #
        # NEDEN? Argmax her zaman uygunsuz bir komut olabilir
        # (ör. tehlike yokken "acil_dinlen"). Bu komut güvenlik
        # ağında reddedilir ve sistem boşa tik kaybeder. Daha kötüsü:
        # uygunsuz komut yüksek olasılıkta kalıp sürekli "ikinci en
        # iyi" olarak marjı tavanlar → model HİÇBİR kararında güven
        # eşiğini geçemez → KİLİTLENME.
        #
        # ÇÖZÜM: uygun olmayan komutlar olasılık dağılımından
        # ÇIKARILIR (maske). Böylece:
        #   * marj, UYGUN komutlar arasındaki gerçek farkı ölçer,
        #   * model, uygun komutu olumlu ödülle ödüllendirildikçe
        #     olasılığı yükselir ve marj eşiğini geçer.
        #
        # Model CEZALANDIRILMAZ (gradyan yok) — sadece doğru
        # davranışa YÖNLENDİRİLİR ("yönlendirme değil ceza").
        maske = self.uygun_maske(x)
        uygunlar = [i for i in range(CIKIS_BOYUT) if maske[i]
                    and i != KOMUT_INDEKSI[KOMUT_YOK]]
        if not uygunlar:
            # Hiçbir non-"yok" komut bu bağlamda uygun değil: tüm
            # non-"yok" komutlardan rastgele seç (argmax uniform
            # dağılımda her zaman ilk indeksi döner → acil_dinlen
            # gibi komut sonsuza dek seçilirdi).
            uygunlar = [i for i in range(CIKIS_BOYUT)
                        if i != KOMUT_INDEKSI[KOMUT_YOK]]
            idx = int(self.rng.choice(uygunlar))
            p_maskeli = np.full(CIKIS_BOYUT, 1.0 / len(uygunlar),
                                dtype=float)
            p_maskeli[KOMUT_INDEKSI[KOMUT_YOK]] = 0.0
            toplam = 1.0
        else:
            # Maskeli olasılıklar: uygun olmayanlar sıfırlanır ve
            # kalanlar yeniden normalize edilir.
            p_maskeli = np.where(maske, probs, 0.0)
            toplam = float(p_maskeli.sum())
            if toplam <= 0.0:
                # Tüm olasılık uygunsuz komutlarda toplanmış (olası
                # değil ama savunma gereği): uygun olanlar eşit dağıtılır.
                p_maskeli = maske.astype(float)
                toplam = float(p_maskeli.sum())
            p_maskeli = p_maskeli / toplam

            # Eylem katalogu, gerçek karar akışına ek fayda olarak bağlanır:
            # araç önerisi, uygun ve güvenli komuta öngörülü bir önyargı verir.
            # Bu, katalogun “yalnızca bilgi” olarak kalmasını engeller.
            tool_name, tool_score, tool_ok = self.en_iyi_eylem_sec(x)
            tool_idx = self._eylem_komut_hint(x)
            if tool_ok and tool_idx != KOMUT_INDEKSI[KOMUT_YOK] and maske[tool_idx]:
                tool_bias = 0.12 + 0.18 * max(0.0, min(1.0, tool_score))
                p_maskeli[tool_idx] += tool_bias
                p_maskeli = p_maskeli / float(p_maskeli.sum())
                self.kisa_hafiza.append({
                    "komut": KOMUTLAR[tool_idx],
                    "idx": int(tool_idx),
                    "confidence": float(tool_bias),
                    "baglam": self.baglam_anahtari(x),
                    "source": "tool_bias",
                    "tool_name": tool_name,
                    "tool_score": float(tool_score),
                })
            idx = int(np.argmax(p_maskeli))

        # Marj NORMALİZE EDİLMİŞ dağılımdan hesaplanır.
        #
        # NEDEN? Argmax da normalize edilmiş dağılımdan
        # seçiliyor; marj da aynı dağılımdan gelmeli (tutarlılık).
        # Normalize edilmemiş (maskelenmiş) dağılımda toplam
        # 1'den küçüktür: maske %70 olasılık kütle elediyse marj
        # 0.7 ile çarpılır → yapay olarak küçük görünür → model
        # eşiği zor geçer. Bu, maskenin ÇÖZMEYE çalıştığı
        # "marj tavanlanması" sorununun ta kendisidir.
        #
        # Normalize edilmiş dağılımda p1-p2, DAĞILIM İÇİNDEKİ
        # gerçek farkı ölçer: "uygun komutlar arasında ne kadar
        # belirgin bir tercih var?"
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
            "komut": KOMUTLAR[idx],
            "idx": int(idx),
            "confidence": confidence,
            "baglam": self.baglam_anahtari(np.asarray(sinyal_vektor, dtype=float)),
            "source": "model",
            "hedef_bonus": hedef_bonus,
            "dunya_bonus": dunya_bonus,
            "self_state": self.ozben_modeli,
        })
        return (KOMUTLAR[idx], idx, confidence, "model")

    # --------------------------------------------------------------- Güvenlik
    def komut_uygulanabilir_mi(self, komut_idx, guven, kaynak="model",
                               sinyal_vektor=None):
        """Override komutu canlıda uygulanmalı mı?

        Komut 0 (yok) her zaman uygulanabilir.
        'kesif' kararları UYGULANIR — öğrenmenin motoru odur; aksi
        halde hiçbir komut doğrulanamaz ve sistem kilitlenir
        (keşif reddedilir → ödül yok → doğrulama puanı artmaz →
        komut hep reddedilir). Keşif komutları yalnızca davranış
        kısıtlaması yapar (ağ/console kapatma, dinlen, yemek) —
        sistemi bozamaz; yanlışsa ödülle cezalandırılır.
        'model' kararları ise iki eşiği geçmek zorundadır: güven
        eşiği (belirsizlik) ve doğrulama eşiği (kanıtlanmış fayda).

        NOT: 'guven' değeri artık ham softmax olasılığı DEĞİL, marj
        tabanlı normalize güvendir (bkz. _guven_hesapla): en iyi
        seçim ile ikinci en iyi arasındaki fark / marj_olcek.

        `sinyal_vektor` verilirse doğrulama kontrolü BAĞLAMSAL
        yapılır: komut, yalnızca kendisinin geçerli olduğu bağlamda
        kanıtlanmışsa onaylanır.
        """
        if komut_idx == KOMUT_INDEKSI[KOMUT_YOK]:
            return True, "yok"
        if kaynak == "kesif":
            # Keşif komutları bağlamsal olarak geçerli olmalı:
            # tehlike yokken "acil_dinlen" keşifle de çalıştırılmamalı,
            # aksi halde enerji boşa harcanır ve sistem sürekli
            # "dinleniyor" moduna girer.
            if sinyal_vektor is not None and not self.komut_uygun_mu(
                    komut_idx, sinyal_vektor):
                return False, "kesif_gecersiz"
            return True, "kesif_deneme"
        # Kilitlenme kırıcı (deadlock breaker): aynı komut ardışık olarak
        # RED_SERI_MAKS kez reddedilirse, eşikleri geçici olarak düşürerek
        # cold-startı kırmaya çalışır. Doğrulama puanı 0'dan başladığı için
        # şartlı reddetme sonsuza dek sürerdi ve sistem kilitlenirdi.
        cooldown_kaldi = self.redd_cooldown[komut_idx]
        if cooldown_kaldi > 0:
            self.redd_cooldown[komut_idx] = max(0, cooldown_kaldi - 1)
            guven_esik = self.guven_esigi * 0.4
            dogrulama_esik = self.dogrulama_esigi * 0.4
        else:
            guven_esik = self.guven_esigi
            dogrulama_esik = self.dogrulama_esigi
        # ÖN KOŞUL KONTROLÜ: komutun bu bağlamda anlamlı olup
        # olmadığı. Koşul sağlanmıyorsa komut doğrulanmış olsa bile
        # UYGULANMAZ (durum uyumsuzluğu). "acil_dinlen" tehlike
        # yokken onaylanmamalıdır.
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
        # Başarılı onay: redd sayacını ve cooldown'ı sıfırla.
        self.redd_serisi[komut_idx] = 0
        self.redd_cooldown[komut_idx] = 0
        return True, "onaylandi"

    # --------------------------------------------------------------- Öğren
    def ogren(self, sinyal_vektor, komut_indeksi, odul, keşif=False):
        """Gerçek sonuç (ödül) ile MLP ağırlıklarını günceller.

        Softmax uyumu: hedef vektörü ASLA negatif olmaz ve TOPLAMI 1'dir
        (geçerli bir çapraz-entropy hedefi). Pozitif ödül seçilen sınıfın
        hedefini 1'e çeker; negatif ödül ise seçilen sınıfın HEDEFİNİ
        0'a indirip (sıfır-sum) kalan sınıflara EŞİT paylaştırır —
        böylece "bu komut iyi değil" bilgisi de matematiksel olarak
        geçerli bir hedef olur.

        ÖNEMLİ: negatif ödülde seçilen sınıfın hedefi 0'a çekilirken
        "diğer sınıflara eşit pay" verilir. Bu, modelin seçilen
        komuttan KAÇINMASINI öğretir ama hangi komutun SEÇİLECEĞİ
        söylemez; bu yüzden keşif (epsilon) keşfi sürdürür ve
        doğrulama puanı yalnızca olumlu ödülle artar.

        ÖNEMLİ: BU FONKSİYON YALNIZCA GERÇEK BİR SONUÇ OLDUĞUNDA
        çağrılmalıdır. Komut uygulanmadıysa (güven eşiği / doğrulama
        eşiği) gerçek ödül YOKTUR ve buraya negatif ceza yazmak
        ÖLÜMCÜL KİLİTLENMEye yol açar:
            model komut önerir → eşik geçilmez → ceza → model o
            komuttan kaçınır → başka komut da öneremez → hiç ödül →
            hiçbir şey öğrenilemez → eşik asla geçilemez.
        Bu döngüyü kırmak için reddedilen kararlar için
        `reddedildi_ogren()` kullanılır (aşağıda).
        """
        x = np.array(sinyal_vektor, dtype=float)
        odul = max(-1.0, min(1.0, float(odul)))
        self._uzun_hafizayi_guncelle(komut_indeksi, odul)

        hedef = np.zeros(CIKIS_BOYUT, dtype=float)
        if komut_indeksi == KOMUT_INDEKSI[KOMUT_YOK] and odul >= 0.0:
            # "YOK" SINIFI = PASİF VARSAYILAN.
            #
            # "Yok" bir EYLEM DEĞİLDİR; sadece "komut yok" durumudur.
            # Ödülü 0 (nötr gözlem) olduğu için HİÇBİR GRADYANT
            # UYGULANMAZ.
            #
            # NEDEN? Çünkü hedef vektörü her zaman "seçilen sınıfın
            # lehine" şekillenir. "Yok" seçildiğinde seçilen sınıf 0'a
            # çekilip diğerleri eşit paylaştırılırsa, modelin ÖĞRENDİĞİ
            # "acil_yem" olasılığı da geri çekilir:
            #     acil_yem  → hedef 0.52  (ödül)
            #     yok       → hedef 0.00  (nötr)  ← ÇELİŞKİ
            # Bu çelişki, modelin hiçbir komutu öğrenememesine yol
            # açıyordu (denemede olasılık 0.15'te tıkandı).
            #
            # Doğru davranış: nötr bir gözlemde model GÜNCELLENMEZ.
            # "Yok" ne ödüllendirilir ne cezalandırılır — pasif kalır
            # (bu, "yok"un baskın sınıf olarak pekiştirilmemesi
            # ilkesiyle birebir uyumludur).
            #
            # Model "yok"ta argmax'a kilitlenirse bu, "hiçbir şey
            # denemiyor" demektir; bu durum keşif (epsilon) ile
            # kırılır ve keşif kararları gerçek ödül üretir.
            #
            # YAPISAL KORUMA: sec() model kararında "yok"u ASLA
            # seçmez (bkz. sec()). Yani bu pasiflik yalnızca olasılık
            # dağılımında kalır ve davranışı kilitlemez.
            self.secim_sayilari[komut_indeksi] += 1
            # Başarılı (uygulanan + ödüllü) komutun ardışık reddetme
            # serisini sıfırla → tekrar denenebilir.
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
            # ÖDÜL → seçilen sınıfı hedefle (yumuşak etiket).
            #
            # TAVAN ÖNEMLİ: softmax çıktısı hedefe YAKINSAYAR. Hedef
            # marjı (guc - pay = 2*guc - 1) marj_olcek * guven_esigi
            # (= 0.15*0.30 = 0.045) değerinden BÜYÜK olmalı, yoksa
            # modelin marjı asimptotik olarak eşiğin altında kalır
            # ve eşik ASLA geçilemez — kilitlenme.
            #
            # ESKİ DEĞER (0.30 + 0.55*odul) HATALIYDI:
            #   ödül 0.4 → guc 0.52 → hedef marjı 0.04 < 0.045 ✗
            #   ödül 0.3 → guc 0.465 → hedef marjı -0.07 (TERS yön!) ✗
            # Yani düşük ödüllü bir komut, modele TERS yönde
            # öğretirdi.
            #
            # YENİ DEĞER (0.55 + 0.40*odul):
            #   ödül 0.0 → guc 0.55 → hedef marjı 0.10 (normalize 0.67) ✓
            #   ödül 0.1 → guc 0.59 → hedef marjı 0.18 (normalize 1.00) ✓
            #   ödül 0.4 → guc 0.71 → hedef marjı 0.42 (normalize 1.00) ✓
            #   ödül 1.0 → guc 0.95 → hedef marjı 0.90 (normalize 1.00) ✓
            # Hedef marjı HER ZAMAN pozitif ve eşiğin üstünde kalır.
            guc = 0.55 + 0.40 * odul
            # ACTION MASKING: hedef yalnızca UYGUN komutlara dağıtılır.
            # Uygunsuz komutlar (bu durumda geçersiz olan eylemler)
            # hedef 0 alır → model duruma bağlı doğru eşlemeyi
            # öğrenir ve uygunsuz komutların olasılığı DÜŞER.
            # Bu, marjı yükseltir (kilitlenmeyi kırar) ve yanlış
            # bağlamda komut önerilmesini engeller.
            maske = self.uygun_maske(x)
            digerler = [i for i in range(CIKIS_BOYUT)
                        if i != komut_indeksi and maske[i]]
            if not digerler:
                # Durum uyumsuzluğu: öğrenilecek uygun alternatif
                # yok. Bu durumda hedefi mevcut haliyle bırak
                # (tek sınıflı hedef geçersiz olurdu).
                hedef[komut_indeksi] = 1.0
            else:
                # KANIT AĞIRLIKLI PAY DAĞITIMI.
                #
                # NEDEN? "Diğerlerine eşit pay" verildiğinde, seçilen
                # komut ile seçilmeyen arasındaki HEDEF farkı sadece
                # guc - pay kadar kalır. Ödül 0.4 iken guc=0.52,
                # pay=0.48 → hedef marjı 0.04. Model bunu asimptotik
                # olarak öğrense bile marj eşiğini (0.15) ZOR geçer
                # ya da hiç geçemez → kilitlenme.
                #
                # ÇÖZÜM: pay, o bağlamda olumlu kanıtı OLAN uygun
                # komutlara yoğunlaşır. Kanıtı olmayan uygun
                # komutlar (ör. henüz denenmemiş komutlar) minimum
                # pay alır. Böylece:
                #   * seçilen komut HEDEFTE belirgin biçimde öne çıkar,
                #   * marj gerçekten büyür,
                #   * model "şu komut işe yarar, şu komut işe yaramaz"
                #     ayrımını ÖĞRENİR (yönlendirme, ceza değil).
                _agirlikli = []
                for i in digerler:
                    # Kanıt, komutun ÖN KOŞULU bağlamında aranır
                    # (acil_yem → "acik", acil_dinlen → "tehlike").
                    # Genel bit maskesi kanıtı yanlış yere bölerdi.
                    _p = self.komut_kanit_puani(i, x)
                    _agirlikli.append((i, _p))
                _toplam_agirlik = sum(_p for _, _p in _agirlikli)
                if _toplam_agirlik > 0.0:
                    # Kanıtı olanlara ağırlıklı pay; kanıtı olmayanlar
                    # minimum (taban) pay alır.
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
            # ceza → seçilen sınıf "olmamalı"; kalanı paylaştır.
            # SIFIR-SUM: hedef[secilen] ≈ 0, kalanın toplamı ≈ 1.
            #
            # ÖNEMLİ: ceza ŞİDDETİ ödülün büyüklüğüne bağlıdır.
            # (Eski kodda `guc = 0.05 + 0.25*abs(odul)` hesaplanıyordu
            # ama HİÇ KULLANILMIYORDU — tüm negatif ödüller aynı
            # (hedef 0) etkiyi yapıyordu, ceza büyüklüğü ölüydü.)
            # Şimdi: hafif ceza → hedef ~0 (tam kaçınma değil, sadece
            # itilme), sert ceza → hedef 0'a çeker.
            hedef[komut_indeksi] = 0.08 * abs(odul)
            # ACTION MASKING (ceza dalı): pay yalnızca uygun
            # komutlara dağıtılır.
            maske_c = self.uygun_maske(x)
            digerler = [i for i in range(CIKIS_BOYUT)
                        if i != komut_indeksi and maske_c[i]]
            # "Diğerlerine eşit pay" → hangi komuta kaçınacağımızı
            # ÖĞRETMEZ; model yalnızca "seçilenden kaçın" öğrenir.
            # Bu, marj güvenini yükseltemez → kilitlenme.
            #
            # DÜZELTME: ceza alınan BAĞLAMDA olumlu kanıtı olan
            # komutlara daha fazla pay verilir. Böylece model
            # "acil_yem burada işe yaramadı, ama acil_dinlen işe
            # yarar" diyebilir — yani hem kaçınma hem YÖNLENDİRME
            # öğrenilir ve marj (p1-p2) büyür.
            _agirlikli = []
            for i in digerler:
                _p = self.komut_kanit_puani(i, x)
                _agirlikli.append((i, _p))
            _toplam_agirlik = sum(_p for _, _p in _agirlikli)
            if _toplam_agirlik > 0.0:
                for i, _p in _agirlikli:
                    hedef[i] = (1.0 - hedef[komut_indeksi]) * (_p / _toplam_agirlik)
            elif digerler:
                pay = (1.0 - hedef[komut_indeksi]) / len(digerler)
                for i in digerler:
                    hedef[i] = pay
            else:
                # Uygun alternatif yok: hedef tek sınıfa toplanır
                # (geçersiz hedef vektörü oluşmaz).
                hedef[komut_indeksi] = 1.0

        self._dunya_model_guncelle(x, komut_indeksi, odul)
        self.mlp.backward(x, hedef, lr=0.05)
        self.secim_sayilari[komut_indeksi] += 1
        self.samples += 1
        self.tik += 1

        # Doğrulama puanı: olumlu ödül komutu 'güvenilir' yapar.
        # Negatif ödül puana hafifçe dokunur (tabanı korur); cezanın
        # asıl etkisi gradyandadır (hedef ~0 → olasılık düşer).
        #
        # KEŞİF KANITI: keşif (epsilon) kararları RASTGELE seçilmiş
        # olsa da komut GERÇEKTEN uygulandı ve gerçek bir ödül
        # üretti — bu, model kararından daha güçlü bir kanıttır
        # (seçilme şansı yok, sadece sonuç vardır). Bu yüzden
        # keşif kanıtı doğrulama puanına 1.5 kat katkı verir.
        _agirlik = 2.0 if keşif else 1.0
        if odul > 0.0:
            self.dogrulama[komut_indeksi] = min(
                2.0, self.dogrulama[komut_indeksi]
                + odul * self.kanit_çarpanı * _agirlik)
            # Bağlamsal puan: aynı kanıt, yalnızca komutun GEÇERLİ
            # olduğu bağlamda birikir. Anahtar komuta ÖZGÜDÜR
            # (acil_yem → "acik", acil_dinlen → "tehlike") — genel
            # bit maskesi kanıtı açlık/tehlike arasında böler ve
            # komut "dogrulanmadi" ile sürekli reddedilirdi.
            _anahtar = (komut_indeksi,
                        self.komut_baglam_anahtari(komut_indeksi, x))
            self.dogrulama_bağlam[_anahtar] = min(
                2.0, self.dogrulama_bağlam.get(_anahtar, 0.0)
                + odul * self.kanit_çarpanı * _agirlik)
        else:
            # Negatif ödül: komut bu bağlamda işe yaramadı.
            # Global puan hafifçe düşer (taban 0'da durur).
            self.dogrulama[komut_indeksi] = max(
                0.0, self.dogrulama[komut_indeksi] + odul * 0.02)
            # BAĞLAMSAL puan da düşmeli. Aksi halde komut, işe
            # yaramadığı bir bağlamda "doğrulanmış" kalır ve
            # güvenlik ağı onu o bağlamda onaylar — bu tam olarak
            # bağlam farkındalığını bozan tutarsızlıktır.
            # Negatif kanıt, o bağlamdaki kanıtı zayıflatır.
            _anahtar_neg = (komut_indeksi,
                            self.komut_baglam_anahtari(komut_indeksi, x))
            self.dogrulama_bağlam[_anahtar_neg] = max(
                0.0, self.dogrulama_bağlam.get(_anahtar_neg, 0.0)
                + odul * 0.02)

        self.odul_gecmisi.append(odul)
        if len(self.odul_gecmisi) > 512:
            self.odul_gecmisi.pop(0)

        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

    # ------------------------------------------------- Reddedilen karar öğrenmesi
    def reddedildi_ogren(self, sinyal_vektor, komut_indeksi):
        """Reddedilen (eşiği geçemeyen) bir karar için ÖĞRENME SİNYALİ.

        NEDEN VAR? "Komut uygulanmadı" demektir; dolayısıyla gerçek bir
        sonuç (ödül) YOKTUR. Olmayan bir olaydan ders çıkarılamaz
        (Epistemik dürüstlük ilkesi). Buna rağmen modelin bir şey
        öğrenmesi gerekir — aksi halde ÖLÜMCÜL KİLİTLENME döngüsü
        oluşur:

            model komut önerir → güven eşiği geçilmez → CEZA verilir
            → model o komuttan kaçınmayı öğrenir → başka komutu da
            güvenle öneremez → hiç ödül → hiçbir şey öğrenilemez
            → eşik ASLA geçilemez.

        Bu döngü 200 tiklik denemede gerçekleşti: 186 model kararının
        tamamı 'guven_yetersiz' ile reddedildi ve hiçbiri doğrulanamadı.

        ÇÖZÜM: Reddedilen karar "hatalı" DEĞİLDİR — sadece HENÜZ
        KANITLANMAMIŞTIR. Bu yüzden:

          1. Doğrulama puanı DÜŞÜRÜLMEZ (kanıt yok, kanıt yok).
          2. Negatif ceza UYGULANMAZ (uydurma sonuç olurdu).
          3. Model, reddedilen komutun olasılığını düşürmek yerine
             TUTAR — böylece aynı komutu tekrar önerir, keşif/uygulama
             döngüsü devam eder ve komut gerçekten denendiğinde
             ödül gelir.
          4. Puan yalnızca "denenmiş ve işe yaramamış" komutlarda
             düşer (bkz. ogren() negatif ödül dalı).

        Bu, güven eşiğini bir "engel" olmaktan çıkarıp bir
        "kanıt kapısı"na dönüştürür: eşiği geçemeyen komut ölmez,
        sadece henüz kanıtlanmamış sayılır.
        """
        if komut_indeksi == KOMUT_INDEKSI[KOMUT_YOK]:
            return 0
        self._kaydet_hata("reddedildi", komut_indeksi, sinyal_vektor)
        self.reddedilen_sayilari[komut_indeksi] += 1
        self.redd_serisi[komut_indeksi] += 1
        if self.redd_serisi[komut_indeksi] >= self.RED_SERI_MAKS:
            # Aynı komut ardışık olarak RED_SERI_MAKS kez reddedildi:
            # bir süre dışarıda tut (diğer komutlar denensin).
            self.redd_cooldown[komut_indeksi] = 5
            self.redd_serisi[komut_indeksi] = 0
        self.tik += 1
        return 0

    # --------------------------------------------------------------- Ömür
    def komut_ayarla(self, komut, komut_idx, sure=3):
        """Override komutunu ayarla ve ömrünü başlat."""
        self.son_komut = komut
        self.son_idx = komut_idx
        self.sure = max(0, int(sure))
        self.sure_azami = max(self.sure_azami, self.sure)

    def azalt_sure(self):
        """Her tikte override ömrünü bir azaltır."""
        if self.sure > 0:
            self.sure -= 1
            if self.sure == 0:
                self.son_komut = KOMUT_YOK
        return self.sure

    def aktif_komut(self):
        """Ömrü bitmemiş aktif override komutu (yoksa KOMUT_YOK)."""
        if self.sure > 0:
            return self.son_komut
        return KOMUT_YOK

    # --------------------------------------------------------------- ASM Öğrenme
    def asm_sistemi(self):
        """Assembly öğrenme organını lazy başlatır ve döndürür.

        ``uzuv.asm_ogren`` modülü (beam search + x86-64 emülatör + gerçek
        makine doğrulaması) üst beyinle bağlanır. Normal işletmede bu
        sistem başlatılmaz; ilk ``asm_*`` çağrısında oluşur ve thereafter
        önbellekte tutulur.
        """
        if self._asm_öğrenici is not None:
            return self._asm_öğrenici
        from uzuv.asm_ogren import (  # lazy import: circular-import riski yok
            AssemblyLearner,
            Emulator,
            LearningState,
            CURRICULUM,
            OPS,
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

    def asm_öğren(self, dakika=1.0, nn_ana=None, stim_ust=None):
        """Assembly öğrenme döngüsünü ``dakika`` sürece çalıştırır.

        Gerçek makinede doğrulanarak x86-64 program çözümleri üretir ve
        kalıcı duruma (``uzuv/asm_ogren.json``) yazar.

        nn_ana ve stim_ust verildiğinde beam search araması nöral beyin
        tarafından yönlendirilir (hibrit öğrenme).
        """
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

    def asm_rapor(self):
        """Assembly öğrenme özetini konsola yazar."""
        learner = self.asm_sistemi()
        learner.report()

    def asm_kod_dene(self, kod, hedef, başlangıç=None):
        """Tek assembly kodunu gerçek makinede doğrular.

        ``hedef``: {yazmac: değer, ...} sözlüğü (rsp hariç).
        Dönen: {'dogru': bool, 'surpriz': float, 'fark': {...}}
        """
        learner = self.asm_sistemi()
        asm = learner.asm
        if başlangıç is None:
            başlangıç = {r: 0 for r in learner.emulator.registers}
        return asm.tahmin_dene(kod, hedef, başlangıç)

    def asm_istatistik(self):
        """Assembly öğrenme istatistiklerini döndürür (yazma işlemi yok)."""
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

    def asm_ornek_coz(
        self,
        egitim,
        dogrulama,
        seviye=1,
        azami_komut=None,
        butce=10000,
        zaman_asimi=10.0,
    ):
        """Verilen girdi/çıktı örneklerinden program arar ve ayrı örneklerde doğrular."""
        sonuc = self.asm_sistemi().solve_examples(
            egitim,
            dogrulama,
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

    # --------------------------------------------------------------- Kalıcılık
    def save(self):
        yol = self.root / "zeka" / "ust_beyn.json"
        yol.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "surum": UST_MODEL_SURUMU,
            "W1": self.mlp.W1.tolist(),
            "b1": self.mlp.b1.tolist(),
            "W2": self.mlp.W2.tolist(),
            "b2": self.mlp.b2.tolist(),
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
            "ozben_modeli": self.ozben_modeli,
            "kimlik": self.kimlik,
            "deger_profili": self.deger_profili,
            "uzun_hafiza": self.uzun_hafiza,
            # Bağlam bazlı doğrulama puanları.
            # JSON'da anahtar (komut_idx, baglam) çifti → DİZİ
            # dönüştürülür, çünkü JSON nesne anahtarı tuple olamaz.
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
        }
        # ASM öğrenme durumu (varsa) üst beyin kayıtına eşlik eder.
        if self._asm_öğrenici is not None:
            self._asm_öğrenici.state.save()

        tmp = yol.with_name(yol.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(yol))

    def _load(self):
        yol = self.root / "zeka" / "ust_beyn.json"
        if not yol.exists():
            return 0
        try:
            data = json.loads(yol.read_text(encoding="utf-8"))
            model_surumu = int(data.get("surum", 1))
            W2 = np.array(data["W2"], dtype=float)
            b2 = np.array(data["b2"], dtype=float)
            # Eski kayıtta sifirla (7. çıktı) varsa ve CIKIS_BOYUT=6 ise,
            # sondaki satırı/elemanı kes — sifirla komutu kaldırıldı.
            if W2.shape[0] > CIKIS_BOYUT:
                W2 = W2[:CIKIS_BOYUT, :]
                b2 = b2[:CIKIS_BOYUT]
            elif W2.shape[0] < CIKIS_BOYUT:
                # Model eski (6 çıktı) ama sifirla eklendi → sıfır padding
                pad = CIKIS_BOYUT - W2.shape[0]
                W2 = np.vstack([W2, np.zeros((pad, W2.shape[1]))])
                b2 = np.concatenate([b2, np.zeros(pad)])
            W1 = np.array(data["W1"], dtype=float)
            if model_surumu < UST_MODEL_SURUMU:
                W1[:, IDX_ENERJI] *= 3.0
            # Yeni SINYAL_BOYUT (48) ile eski W1 (36 sütun) arasında boyut uyuşmazlığı varsa sıfırla doldur
            if W1.shape[1] < SINYAL_BOYUT:
                pad_cols = SINYAL_BOYUT - W1.shape[1]
                W1 = np.hstack([W1, np.zeros((W1.shape[0], pad_cols))])
            elif W1.shape[1] > SINYAL_BOYUT:
                W1 = W1[:, :SINYAL_BOYUT]
            self.mlp.W1 = W1
            self.mlp.b1 = np.array(data["b1"], dtype=float)
            self.mlp.W2 = W2
            self.mlp.b2 = b2
            self.samples = data.get("samples", 0)
            self.tik = data.get("tik", 0)
            self.epsilon = data.get("epsilon", self.epsilon)
            secim = data.get("secim_sayilari", None)
            if secim is not None:
                if len(secim) > CIKIS_BOYUT:
                    secim = secim[:CIKIS_BOYUT]
                elif len(secim) < CIKIS_BOYUT:
                    # Eski kayıt (6 elemanlı, sifirla eksik) → sıfır padding
                    secim = secim + [0] * (CIKIS_BOYUT - len(secim))
            self.secim_sayilari = secim or [0] * CIKIS_BOYUT
            dogr = data.get("dogrulama", None)
            if dogr is not None:
                if len(dogr) > CIKIS_BOYUT:
                    dogr = dogr[:CIKIS_BOYUT]
                elif len(dogr) < CIKIS_BOYUT:
                    # Eski kayıt (6 elemanlı, sifirla eksik) → sıfır padding
                    dogr = dogr + [0.0] * (CIKIS_BOYUT - len(dogr))
            self.dogrulama = dogr or [0.0] * CIKIS_BOYUT
            self.kisa_hafiza = deque(maxlen=64)
            for _item in data.get("kisa_hafiza", []):
                if isinstance(_item, dict):
                    self.kisa_hafiza.append(_item)
            self.hata_kategorisi = dict(data.get("hata_kategorisi", {}))
            self.last_confidence = float(data.get("last_confidence", 0.0))
            self.last_komut_idx = int(data.get("last_komut_idx", KOMUT_INDEKSI[KOMUT_YOK]))
            self.dunya_modeli = {}
            for bag, vals in (data.get("dunya_modeli") or {}).items():
                try:
                    parsed = {}
                    for k, v in (vals or {}).items():
                        parsed[int(k)] = [float(x) for x in v]
                    self.dunya_modeli[bag] = parsed
                except Exception:
                    continue
            self.ozben_modeli = data.get("ozben_modeli", {
                "durum": "hazir",
                "istikrar": 0.0,
                "hata_orani": 0.0,
                "ortalama_odul": 0.0,
                "guven_duyarliligi": 0.0,
            })
            loaded_identity = data.get("kimlik") or {}
            self.kimlik["ad"] = "Aelaan"
            self.kimlik["ilkeler"] = loaded_identity.get("ilkeler", self.kimlik["ilkeler"])
            self.deger_profili.update(data.get("deger_profili") or {})
            loaded_memory = data.get("uzun_hafiza") or {}
            self.uzun_hafiza["toplam_sonuc"] = max(0, int(loaded_memory.get("toplam_sonuc", 0)))
            self.uzun_hafiza["olumlu_sonuc"] = max(0, int(loaded_memory.get("olumlu_sonuc", 0)))
            self.mizac.update(data.get("mizac") or {})
            self.uzun_hafiza["olumsuz_sonuc"] = max(0, int(loaded_memory.get("olumsuz_sonuc", 0)))
            self.uzun_hafiza["odul_toplami"] = float(loaded_memory.get("odul_toplami", 0.0))
            self.uzun_hafiza["komutlar"] = {
                str(ad): {"sayi": max(0, int(veri.get("sayi", 0))),
                          "odul_toplami": float(veri.get("odul_toplami", 0.0))}
                for ad, veri in (loaded_memory.get("komutlar") or {}).items()
                if isinstance(veri, dict)
            # Bağlam bazlı puanlar geri yüklenir. ESKİ kayıtlarda bu
            }
            # alan YOKTUR → geriye dönük uyum için boş bırakılır
            # (global puan kullanılır, davranış bozulmaz).
            self.dogrulama_bağlam = {}
            for _k, _v in (data.get("dogrulama_baglam") or {}).items():
                try:
                    _idx_s, _bag = str(_k).split("|", 1)
                    self.dogrulama_bağlam[(int(_idx_s), _bag)] = float(_v)
                except (TypeError, ValueError):
                    continue
            # Yalnızca VAR OLAN alanlar yüklenir; eski kayıtta eksik
            # olan alanlar (yeni eşikler) varsayılanı korur.
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

    def komut_adi(self, indeks):
        return KOMUTLAR[indeks] if 0 <= indeks < CIKIS_BOYUT else KOMUT_YOK


# --------------------------------------------------------------- Sinyal Toplama (pure Python)
def _clamp01(x):
    return max(0.0, min(1.0, float(x)))


def topla_sinyalleri(drives, mind, dam, guv, surec,
                     door_msgs, olum=None, context="start",
                     feats_damak=None, E=None, H=None,
                     sarsinti=0.0, yemek_var=False,
                     gorev_aktif=False, surpriz=0.0,
                     dunya_bozuk=False, olum_feats=None,
                     # ---------- Yeni: Beden duyuları (Aşama 1) ----------
                     cpu_yuk=0.0, proses_norm=0.0,
                     disk_yuzde_norm=0.0, bellek_yuzde_norm=0.0,
                     usb_cihaz_norm=0.0, usb_keşif_bonusu=0.0,
                     ag_baglanti_norm=0.0, insan_var=False,
                     sistem_saati_norm=0.0,
                     disk_baski=0.0, bellek_baski=0.0,
                     beden_baski=0.0):
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
            scores = [sum(mind._get(f, a) for f in feats)
                      for a in mind.ACTIONS]
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
        anomaly = _clamp01(max(
            anomaly,
            float(getattr(surec, "degisim_skoru", 0.0)),
        ))
    else:
        eksik_n = yeni_n = anomaly = 0.0

    shock_pending = 0.0
    mesaj_var = 0.0
    shock_miktar = 0.0
    if door_msgs:
        mesaj_var = 1.0
        for m in list(door_msgs):
            if isinstance(m, str) and m.startswith("shock:"):
                shock_pending = 1.0
                try:
                    shock_miktar = min(1.0,
                                       float(m.split(":", 1)[1]) / 100.0)
                except Exception:
                    shock_miktar = 0.5

    olum_risk = 0.0
    if olum is not None and olum_feats:
        # Olum riski: model EĞİTİLMİŞSE ve GEÇERLİ bir özellik
        # vektörü (ölüm anında görülen sinyaller) varsa kategorilerin
        # en güçlü log-olasılığı. Özellik vektörü YOKSA risk 0'dır:
        # ölüm modeli yalnızca ölüm anı sinyallerinden beslenir;
        # mevcut durumdan "ölüm riski" uydurmak yanlış yönlendirme
        # yaratır (sinyal kirliliği). Eğitilmemiş modelde skorlar
        # -1e9'dur -> risk 0.
        #
        # NORMALİZASYON: log-olasılıklar >1 olabilir; doğrudan
        # (skor+5)/5 ölçeği 1.0'a clamp olur ve hep "yüksek risk"
        # üretirdi. Doğru ölçek: softmax olasılıkları üzerinden en
        # büyük OLASILIK (belirsizlik de düşük risk verir).
        try:
            _skorlar = olum.kategori_skor(list(olum_feats))
            if _skorlar:
                _en_iyi = max(_skorlar.values())
                if _en_iyi > -1e8:
                    _sk = np.array(list(_skorlar.values()), dtype=float)
                    _p = np.exp(_sk - _sk.max())
                    _p = _p / max(1e-12, float(_p.sum()))
                    olum_risk = _clamp01(float(_p.max()))
        except Exception:
            olum_risk = 0.0

    dunya_bozuk_v = 1.0 if dunya_bozuk else 0.0
    surpriz_v = _clamp01(surpriz / 5.0)
    gorev_v = 1.0 if gorev_aktif else 0.0

    # ---------- Yeni: Duygu sinyalleri (Aşama 6) ----------
    mood = getattr(drives, "mood", None) or {}
    mood_mutluluk = float(mood.get("mutluluk", 0.5))
    mood_korku = float(mood.get("korku", 0.0))
    mood_merak = float(mood.get("merak", 0.3))

    ctx_map = {"start": 0, "door": 1, "act": 2, "eat": 3,
               "console": 4, "rest": 5}
    ctx_vec = [0.0] * 6
    if context in ctx_map:
        ctx_vec[ctx_map[context]] = 1.0

    # ---------- Yeni: Beden duyuları (Aşama 1) ----------
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
    return v[:SINYAL_BOYUT]


# --------------------------------------------------------------- Testler
if __name__ == "__main__":
    import olum as olum_mod
    import tempfile

    hata = []

    def kontrol(kosul, mesaj):
        if not kosul:
            hata.append(mesaj)

    class _D:
        energy = 100.0
        hunger = 50.0
        sikilma = 0.2
        in_danger = False
        alive = True

        def pain(self):
            return 0.1

    # 1) sinyal vektörü boyutu ve [0,1] aralığı
    v = topla_sinyalleri(_D(), None, None, None, None, [])
    kontrol(len(v) == SINYAL_BOYUT,
            "sinyal boyutu %d != %d" % (len(v), SINYAL_BOYUT))
    kontrol(all(0.0 <= x <= 1.0 for x in v),
            "sinyal [0,1] disinda: %s" %
            [x for x in v if not (0.0 <= x <= 1.0)])

    # 2) özellik vektörü YOKSA ölüm riski 0
    b = olum_mod.Olum()
    b.ogren(["sinyal=yok", "kaynak=guc", "kim=cekirdek",
             "siddet=ani", "belirti=aniden_kesildi",
             "onbelirti=evet"], "fiziki")
    b.ogren(["sinyal=yok", "kaynak=guc", "kim=cekirdek",
             "siddet=ani", "belirti=aniden_kesildi",
             "onbelirti=evet"], "yazilimsal")
    v2 = topla_sinyalleri(_D(), None, None, None, None, [],
                          olum=b, olum_feats=None)
    kontrol(v2[IDX_OLUM_RISK] == 0.0,
            "ozellik yokken olum riski 0 olmali: %s" % v2[IDX_OLUM_RISK])

    # 3) geçerli özellikle risk (0,1] aralığında
    feats = olum_mod.ozellikler({"sinyal": "yok", "kaynak": "guc",
                                  "kim": "cekirdek", "siddet": "ani",
                                  "belirti": "aniden_kesildi",
                                  "onbelirti": "evet"})
    v3 = topla_sinyalleri(_D(), None, None, None, None, [],
                          olum=b, olum_feats=feats)
    kontrol(0.0 < v3[IDX_OLUM_RISK] <= 1.0,
            "gecerli ozellikle olum riski (0,1] degil: %s" %
            v3[IDX_OLUM_RISK])

    # 4) eğitilmemiş model (ornek=0) risk üretmez
    bos = olum_mod.Olum()
    v4 = topla_sinyalleri(_D(), None, None, None, None, [],
                          olum=bos, olum_feats=feats)
    kontrol(v4[IDX_OLUM_RISK] == 0.0,
            "egitilmemis model risk uretmemeli: %s" % v4[IDX_OLUM_RISK])

    if hata:
        print("HATA (%d):" % len(hata))
        for h in hata:
            print("  -", h)
        raise SystemExit(1)
    print("ust_beyn sinyal testleri: TUMU GECTI")
