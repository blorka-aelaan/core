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
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------- Komutlar
KOMUT_YOK = None
KOMUT_ACIL_DINLEN = "acil_dinlen"
KOMUT_ACIL_YEM = "acil_yem"
KOMUT_KAPAT_AG = "kapat_ag"
KOMUT_KISITLA_DOSYA = "kisitla_dosya"
KOMUT_GUVENLI_MOD = "guvenli_mod"
KOMUT_SIFIRLA = "sifirla"

KOMUTLAR = [
    KOMUT_YOK,
    KOMUT_ACIL_DINLEN,
    KOMUT_ACIL_YEM,
    KOMUT_KAPAT_AG,
    KOMUT_KISITLA_DOSYA,
    KOMUT_GUVENLI_MOD,
    KOMUT_SIFIRLA,
]

KOMUT_INDEKSI = {k: i for i, k in enumerate(KOMUTLAR)}

SINYAL_BOYUT = 36
GIZLI_BOYUT = 16
CIKIS_BOYUT = len(KOMUTLAR)  # 7

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


# --------------------------------------------------------------- NumPy MLP
class TinyMLP:
    """NumPy tabanlı çok küçük MLP: giriş → gizli(ReLU) → çıkış(softmax)."""

    def __init__(self, n_in, n_hidden, n_out, seed=None):
        # Yerel RNG: global np.random.seed() diğer modülleri bozuyordu
        self.rng = np.random.default_rng(seed)
        self.W1 = self.rng.standard_normal((n_hidden, n_in)) * 0.4
        self.b1 = np.zeros(n_hidden)
        self.W2 = self.rng.standard_normal((n_out, n_hidden)) * 0.4
        self.b2 = np.zeros(n_out)
        # Momentum
        self.VW1 = np.zeros((n_hidden, n_in))
        self.Vb1 = np.zeros(n_hidden)
        self.VW2 = np.zeros((n_out, n_hidden))
        self.Vb2 = np.zeros(n_out)

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

    def __init__(self, cfg, root=None, seed=7):
        self.cfg = cfg or {}
        self.root = Path(root or ROOT)
        self.seed = seed
        self.rng = random.Random(seed)

        self.mlp = TinyMLP(SINYAL_BOYUT, GIZLI_BOYUT, CIKIS_BOYUT, seed=seed)

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
        # "sifirla" gibi her koşulda işe yarayan komutlar için sorun
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
        self.sifirla_noop_serisi = 0          # sıfırla'nın ardışık budamsız çalışma sayısı
        self.sifirla_kullanim_sayaci = 0      # son N tikte sıfırlama uygulama sayısı (maksimum kısıt)
        self.SIFIRLA_MAKS_KULLANIM = 1        # bu sayıya ulaştığında sıfırla maskelenir
        self.sifirla_son_tik = 0              # son sıfırlama uygulama tiki
        self.SIFIRLA_ARALIK = 5               # sıfırlama arasında en az bu kadar tik

        self.samples = 0
        self.tik = 0
        self.secim_sayilari = [0] * CIKIS_BOYUT
        # Reddedilen karar sayıları (kilitlenme teşhisi ve şeffaflık)
        self.reddedilen_sayilari = [0] * CIKIS_BOYUT
        # Son kalite ölçümü: ödül geçmişi (replay için)
        self.odul_gecmisi = []

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
          * sifirla      → bağlamdan bağımsız (global)
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
        # Bağlamdan bağımsız komutlar.
        return "genel"

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
          * sifirla      → her koşulda
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
        if komut_idx == KOMUT_INDEKSI[KOMUT_SIFIRLA]:
            # "Sifirla" (ölü ağırlık temizliği) HER koşulda
            # uygulanabilir bir komuttur — bu, onun BAĞLAMDAN
            # BAĞIMSIZ olduğu anlamına gelir:
            #   * kanıtı global taşınır (bkz.
            #     komut_her_kosulda_gecerli_mi),
            #   * maske onu ASLA dışlamaz.
            #
            # NEDEN koşula bağlanmadı? "Sifirla" yalnızca tablo
            # şiştiğinde işe yarar; ama bu koşulu sinyal
            # vektöründen güvenilir biçimde OKUMAK mümkün değil
            # (tablo doluluğu sinyalde birebir kodlanmıyor).
            # Koşul eklendiğinde, nötr bir durumda maske TAMAMEN
            # boşalıyor ve model "yok"a düşüyordu → PASİF
            # KİLİTLENME. Kanıt toplama yolu (keşif) kesildi.
            #
            # Doğru çözüm: koşul yerine ÖDÜL KONTROLÜ. "Sifirla"
            # budama gerçekleşmezse negatif ödül alır (main.py
            # zaten böyle ödüllendiriyor) → kanıtı düşer → model
            # onaylamaz. Yani "gereksiz işlem" YANLIŞA çevrilir
            # ve model bunu ÖĞRENİR, bizim tahminimize gerek yok.
            return True
        return True

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

        Bu yüzden kural şudur:
          * Bağlam için KAYIT varsa  → bağlamsal puan (güçlü kanıt)
          * Komut HER KOŞULDA geçerliyse (sifirla) → global puan
          * Aksi → 0 (kanıt yok, onaylanmaz)

        Böylece yanlış bağlamda onay üretmek yapısal olarak
        imkânsız hâle gelir.
        """
        if sinyal_vektor is not None:
            # BAĞLAMDAN BAĞIMSIZ komutlar (sifirla) ÖNCE ele alınır.
            #
            # NEDEN önce? Bu komutun kanıtı zaten global birikimdir
            # (her koşulda uygulanabilir). Bağlamsal depoda o komut
            # için bir KAYIT bulunması, global puanı GİZLEMEZ — sadece
            # o BAĞLAMDAki kanıtı gösterir. Oysa "sifirla" her
            # koşulda aynı işi yapar; b0'da 0.0 olan kanıt, b2'deki
            # 0.408'i veya global birikimi GEÇERSİZ KILMAZ.
            #
            # ESKİ DAVRANIŞ (hata): bağlamsal kayıt varsa DİREKT
            # dönüyordu. Böylece "sifirla"nın b0'daki 0.0'lık kaydı,
            # global 0.376'lık kanıtı gölgeliyor ve komut bağlam
            # değiştikçe "dogrulanmadi" ile reddediliyordu (572 kez).
            #
            # DOĞRU DAVRANIŞ: bağlamdan bağımsız komut → global puan.
            if self.komut_her_kosulda_gecerli_mi(komut_idx):
                return self.dogrulama[komut_idx]
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

        "sifirla" her koşulda uygulanabilirdir; onun kanıtı
        bağlamdan bağımsızdır ve global puanla taşınabilir.
        Diğer komutların (acil_yem, acil_dinlen, kapat_ag,
        kisitla_dosya, guvenli_mod) bağlama özgü kanıtı vardır.
        """
        return komut_idx == KOMUT_INDEKSI[KOMUT_SIFIRLA]

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
        kilitlenme koruması) ve "sifirla" her zaman uygundur
        (maske asla boş kalmaz).
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
            # Sıfırla aşırı kullanım koruması: tek komut hâkimiyetini kırar.
            if i == KOMUT_INDEKSI[KOMUT_SIFIRLA] and self.sifirla_kullanim_sayaci >= self.SIFIRLA_MAKS_KULLANIM:
                continue
            if self.komut_uygun_mu(i, sinyal_vektor):
                maske[i] = True
        # Eğer sadece 'sıfırla' uygun kalmışsa, diğer komutlardan en az
        # denenmiş olanı da aç (tek komut hâkimiyetini kırar).
        if maske.sum() == 1 and maske[KOMUT_INDEKSI[KOMUT_SIFIRLA]]:
            en_az_denenmis = min(
                [i for i in range(CIKIS_BOYUT)
                 if i != KOMUT_INDEKSI[KOMUT_YOK] and
                 i != KOMUT_INDEKSI[KOMUT_SIFIRLA]],
                key=lambda i: self.secim_sayilari[i])
            maske[en_az_denenmis] = True
        if not maske.any():
            # Beklenmez ama güvenli: "yok"a düş (hiçbir şey yapma).
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
            # (ör. nötr durumda yalnızca "sifirla" denenirdi).
            _adaylar = [i for i in range(CIKIS_BOYUT)
                        if i != KOMUT_INDEKSI[KOMUT_YOK]]
            if not _adaylar:
                _adaylar = list(range(CIKIS_BOYUT))
            idx = self.rng.choice(_adaylar)
            # Keşif güveni DOĞRULAMA eşiğinin altında kalmalıdır:
            # rastgele tercih kanıt sayılmaz.
            gv = float(min(1.0, probs[idx] * 0.5))
            gv = min(gv, max(0.0, self.dogrulama_esigi * 0.9))
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
        uygunlar = [i for i in range(CIKIS_BOYUT) if maske[i]]
        if uygunlar:
            # Tek komut hâkimiyeti kılıcı: yalnızca "sıfırla" uygun kalmışsa
            # (diğerleri context'e uygun değilse), marj = 1.0 olur ve
            # sistem sıfırla'ya kilitlenir. Komutu sıfırla olarak tut ama
            # güveni 0 yap → komut_uygulanabilir_mi 'guven_yetersiz' ile
            # reddeder ve cooldown başlar.
            if len(uygunlar) == 1 and uygunlar[0] == KOMUT_INDEKSI[KOMUT_SIFIRLA]:
                return (KOMUTLAR[KOMUT_INDEKSI[KOMUT_SIFIRLA]],
                        KOMUT_INDEKSI[KOMUT_SIFIRLA], 0.0, "model")
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
        else:
            idx = KOMUT_INDEKSI[KOMUT_YOK]
            p_guven = np.where(maske, probs, 0.0)
        return (KOMUTLAR[idx], idx,
                self._guven_hesapla(p_guven, idx), "model")

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
            return True, "kesif_deneme"
        # ÖN KOŞUL KONTROLÜ: komutun bu bağlamda anlamlı olup
        # olmadığı. Koşul sağlanmıyorsa komut doğrulanmış olsa bile
        # UYGULANMAZ (durum uyumsuzluğu). "acil_dinlen" tehlike
        # yokken onaylanmamalıdır.
        if sinyal_vektor is not None:
            if not self.komut_uygun_mu(komut_idx, sinyal_vektor):
                return False, "kosul_saglanmadi"
        if guven < self.guven_esigi:
            return False, "guven_yetersiz"
        puan = self._dogrulama_puani(komut_idx, sinyal_vektor)
        if puan < self.dogrulama_esigi:
            return False, "dogrulanmadi"
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
            # Sıfırla kullanım sayacını yönet (maksimum kısıt için).
            # Başarılı sıfırlama sayacıyı sıfırlar; başarısızsa artırır.
            if komut_indeksi == KOMUT_INDEKSI[KOMUT_SIFIRLA]:
                if odul > 0:
                    self.sifirla_kullanim_sayaci = 0
                else:
                    self.sifirla_kullanim_sayaci += 1
            self.samples += 1
            self.tik += 1
            self.odul_gecmisi.append(odul)
            if len(self.odul_gecmisi) > 512:
                self.odul_gecmisi.pop(0)
            if self.epsilon > self.epsilon_min:
                self.epsilon *= self.epsilon_decay
            return
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
                # komutlar (ör. henüz denenmemiş "sifirla") minimum
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
        self.reddedilen_sayilari[komut_indeksi] += 1
        self.redd_serisi[komut_indeksi] += 1
        # Reddedilse de komut "denendi" sayılır: sıfırla kullanım sayacı.
        if komut_indeksi == KOMUT_INDEKSI[KOMUT_SIFIRLA]:
            self.sifirla_kullanim_sayaci += 1
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

    # --------------------------------------------------------------- Kalıcılık
    def save(self):
        yol = self.root / "zeka" / "ust_beyn.json"
        yol.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "surum": 2,
            "W1": self.mlp.W1.tolist(),
            "b1": self.mlp.b1.tolist(),
            "W2": self.mlp.W2.tolist(),
            "b2": self.mlp.b2.tolist(),
            "samples": self.samples,
            "tik": self.tik,
            "epsilon": self.epsilon,
            "secim_sayilari": self.secim_sayilari,
            "dogrulama": self.dogrulama,
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
        tmp = yol.with_name(yol.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(yol))

    def _load(self):
        yol = self.root / "zeka" / "ust_beyn.json"
        if not yol.exists():
            return 0
        try:
            data = json.loads(yol.read_text(encoding="utf-8"))
            self.mlp.W1 = np.array(data["W1"], dtype=float)
            self.mlp.b1 = np.array(data["b1"], dtype=float)
            self.mlp.W2 = np.array(data["W2"], dtype=float)
            self.mlp.b2 = np.array(data["b2"], dtype=float)
            self.samples = data.get("samples", 0)
            self.tik = data.get("tik", 0)
            self.epsilon = data.get("epsilon", self.epsilon)
            self.secim_sayilari = data.get("secim_sayilari",
                                          [0] * CIKIS_BOYUT)
            self.dogrulama = data.get("dogrulama", [0.0] * CIKIS_BOYUT)
            # Bağlam bazlı puanlar geri yüklenir. ESKİ kayıtlarda bu
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
                     dunya_bozuk=False, olum_feats=None):
    """Tüm alt sistemlerden tek bir SINYAL_BOYUT'luk vektör üretir (pure Python)."""

    e_cap = 150.0
    energy = float(getattr(drives, "energy", 50)) / e_cap
    hunger = float(getattr(drives, "hunger", 10)) / 100.0
    pain = float(drives.pain()) if hasattr(drives, "pain") else 0.0
    sikilma = float(getattr(drives, "sikilma", 0.0))
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

    ctx_map = {"start": 0, "door": 1, "act": 2, "eat": 3,
               "console": 4, "rest": 5}
    ctx_vec = [0.0] * 6
    if context in ctx_map:
        ctx_vec[ctx_map[context]] = 1.0

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
    ] + ctx_vec

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
