"""meta_ogrenme.py — Öğrenmeyi Öğrenme (Meta-Learning) organi.

Organizmaya kendi hiperparametrelerini (öğrenme hızı lr ve keşif oranı
epsilon) kendi ayarlama yeteneği verir.

Sabit lr=0.1 her fazda optimal değildir:
  · tehlike (düşük enerji / yüksek açlık / acı) → kararlılık gerektirir,
    düşük lr, düşük epsilon (riflenen davranış)
  · açlık → öğrenmeyi agresifleştir
  · rahatlama → konsolidasyon, lr'u yavaşlat, epsilon'ı indir

Ödül trendi negatifse (performans düşüyor) organizma daha çok keşfetmeye
ve agresif öğrenmeye geçer; pozitifse yavaşlar ve kazanılanı pekiştirir.

Her bağlam (tehlike / açlık / rahatlama / uyku) için ayrı ayrı ödül penceresi
tutulur, böylece aynı lr her zaman değil, o anki iç durum için uygun lr
kullanılır.

Geliştirmeler (2026-10-26):
  · EMA (exponential moving average) tabanlı trend: 50/50 pencere yerine
    son iki ödül arasındaki farkın EMA'sı alınır → gürültülü tek tik'ler
    trendleri daha az yanıltır.
  · Volatilite dampening: trend işarı sık değişiyorsa / çok yüksekse
    lr/epsilon değişiklikleri yavaşlatılır (1.0'a doğru çekilir).
  · Meta-bellek: her bağlam için başarılı lr/epsilon çarpanları hatırlanır;
    aynı bağlam tekrarlandığında önceki deneyimle başlangıç noktası seçilir.
  · Tek denetleyici prensibi: meta_ogrenme brain.lr'i / brain.epsilon'ı doğrudan
    set etmez, yalnızca `meta_lr_carpan` / `meta_eps_carpan` çarpanlarını
    yazar. Gerçek çarpım `brain.update_dynamic_params(drives)` içinde
    (temel durum duyarlı lr/ε ile) uygulanır. İki denetleyici aynı değeri
    yazıp ezer.

Entegrasyon: main.py'deki her `mind.learn()` çağrısından sonra
`meta.guncelle(odul, drives, tik)` çağrılır. Bu, `brain.meta_lr_carpan` ve
`brain.meta_eps_carpan`'ı günceller; `decide()` ve sonraki `learn()`
bu yeni değerleri `update_dynamic_params` üzerinden kullanır.
"""

from collections import deque


class MetaOgrenme:
    """Ödül trendi ve iç bağlama göre lr/epsilon'ı kendisi Tayin eder."""

    BAĞLAMLAR = ("tehlike", "aclik", "rahatlama", "uyku")

    def __init__(self, brain, pencere=100, lim=None):
        self.brain = brain
        self.pencere = int(pencere)

        # Bağlama özel ödül pencereleri (son N tik)
        self.odul_gecmisi = {b: deque(maxlen=self.pencere)
                             for b in self.BAĞLAMLAR}
        self.odul_trend = {b: 0.0 for b in self.BAĞLAMLAR}  # -1..1 (pencere)
        self.ema_trend = {b: 0.0 for b in self.BAĞLAMLAR}   # -1..1 (EMA)
        self.ema_alpha = 0.20                                 # EMA yumuşatma
        self.volatilite = {b: 0.0 for b in self.BAĞLAMLAR}   # trend şiddeti

        # Uyku (konsolidasyon) override bayrağı
        self._uyku_aktif = False

        # Başlangıç (doğum) değerleri — beyinden kopyalanır
        self.lr_base = float(getattr(brain, "lr_base", 0.12))
        self.epsilon_base = float(getattr(brain, "epsilon", 0.35))
        self.lr_min = float(getattr(brain, "lr_min", 0.01))
        self.lr_max = float(getattr(brain, "lr_max", 0.40))
        self.eps_min = float(getattr(brain, "eps_min", 0.02))
        self.eps_max = float(getattr(brain, "eps_max", 0.70))

        # Meta-bellek: baglam -> {"lr_carpan": x, "eps_carpan": y,
        #                          "basari": z, "n": sayi}
        self.meta_memory = {
            b: {"lr_carpan": 1.0, "eps_carpan": 1.0, "basari": 0.0, "n": 0}
            for b in self.BAĞLAMLAR
        }

        self.tik = 0
        self.son_baglam = None

        # --- Yeni: komut doğrulama skorları (kullan._dogrula / _kos) ---
        # body.ogren() → meta_ogrenme.transfer() bağlantısı:
        # _dogrula doğrulama sonuçları ve komut tehlike skorları
        # meta_ogrenmeye aktarılır → öğrenme birikir.
        self.son_dogrulama = None     # son _dogrula sonucu (True/False)
        self.son_tehlike = None       # son komut_tehlike skoru (0..1)
        self.son_komut_tip = None     # son komut tipi (READ/EXEC/MODIFY/NETWORK)
        self.dogrulama_gecmensi = deque(maxlen=50)  # son 50 doğrulama

        # --- Uzuv LIM: kaynak limit izleyicisi ---
        # CPU/RAM/disk baskısı → adaptif ceza çarpanı
        self.lim = lim  # uzuv.LIM instance (None olabilir)

    # ------ komut doğrulama skorlarını transfer et ------
    # body.ogren() → meta_ogrenme.transfer() bağlantısı:
    # _dogrula/_kos skorları meta_öğrenmenin kaynak baskı ve
    # keşif analizine entegre edilir → öğrenme birikir.

    def transfer(self, dogru=None, komut_tehlike=None, komut_tip=None):
        """Komut doğrulama skorlarını meta-öğrenmeye aktar.

        Parameters
        ----------
        dogru : bool or None
            Komut çıkısının hedefi karşılayıp karşılamadığı (_dogrula).
        komut_tehlike : float or None
            Komut tehlike skoru (_kos → _komut_tehlike.tahmin).
        komut_tip : str or None
            Komut tipi: READ / EXEC / MODIFY / NETWORK.
        """
        if dogru is not None:
            self.son_dogrulama = bool(dogru)
            self.dogrulama_gecmensi.append(1.0 if dogru else 0.0)
        if komut_tehlike is not None:
            self.son_tehlike = float(komut_tehlike)
        if komut_tip is not None:
            self.son_komut_tip = komut_tip

    # -------------------------------------------------------------- uyku
    def uyku_basla(self):
        """Uyku (konsolidasyon) başladığında çağrılır: agresif lr/epsilon."""
        self._uyku_aktif = True

    def uyku_bitir(self):
        """Uyku sonrası normal öğrenmeye dön: trendleri sıfırla (yeni periyod)."""
        self._uyku_aktif = False
        for b in self.BAĞLAMLAR:
            self.odul_trend[b] = 0.0
            self.ema_trend[b] = 0.0
            self.volatilite[b] = 0.0

    # -------------------------------------------------------------- bağlam
    def _baglam(self, drives):
        """Anlık iç durumu 'tehlike'/'aclik'/'rahatlama'/'uyku' olarak sınıflastır.

        drives.hayatta_kalpa_modu / uyari_modu (homeostaz) kancalarını okur.
        """
        # Uyku override (konsolidasyon sırasında tüm trend çarpanları yer değil.
        if self._uyku_aktif:
            return "uyku"

        # Homeostaz sinyalleri: drives.hayatta_kalma / uyari_modu
        if bool(getattr(drives, "hayatta_kalma_modu", False)):
            return "tehlike"           # hayatta kalmaya zorunlu
        if bool(getattr(drives, "uyari_modu", False)):
            return "aclik"             # uyarı = agresif keşif

        try:
            energy = float(getattr(drives, "energy", 50.0))
            hunger = float(getattr(drives, "hunger", 30.0))
        except (TypeError, ValueError):
            energy, hunger = 50.0, 30.0

        _pain = getattr(drives, "pain", 0.0)
        try:
            pain = float(_pain() if callable(_pain) else _pain)
        except (TypeError, ValueError):
            pain = 0.0
        pain = max(0.0, min(1.0, pain))

        in_danger = bool(getattr(drives, "in_danger", False))

        # Kritik: can tehlikesi / acı / çökük enerji / kritik açlık
        if in_danger or pain > 0.5 or energy < 30.0 or hunger > 85.0:
            return "tehlike"
        # Açlık odaklı: enerji orta/aşağı veya açlık orta/yüksek
        if energy < 60.0 or hunger > 50.0:
            return "aclik"
        # Diğer durumlar: rahatlama / konsolidasyon
        return "rahatlama"

    # -------------------------------------------------------------- güncelle
    def guncelle(self, odul, drives, tik):
        """Her tikte bir çağrılır: ödülü kaydeder ve lr/epsilon'ı ayarlar.

        Parametreler
        ----------
        odul : float
            Bu tikte elde edilen gerçek sistem ödülü.
        drives : Drives
            İç güdüler (enerji, açlık, acı, in_danger, hayatta_kalma_modu).
        tik : int
            Ana döngü tik sayacı.
        """
        self.tik = int(tik)
        baglam = self._baglam(drives)
        self.son_baglam = baglam
        o = float(odul)
        self.odul_gecmisi[baglam].append(o)

        # ---- EMA trend (sadece aktif bağlam için güncellenir) ----
        penc = self.odul_gecmisi[baglam]
        if len(penc) >= 2:
            lst = list(penc)
            diff = lst[-1] - lst[-2]
            # Ödül skali yaklaşık -50 .. +60; diff'yi -1..1'e sıkıştır
            scaled = max(-1.0, min(1.0, diff / 40.0))
            self.ema_trend[baglam] = (
                self.ema_alpha * scaled
                + (1.0 - self.ema_alpha) * self.ema_trend[baglam]
            )
            # Volatilite: |EMA trend| yüksekse ortam kararsız → değişiklikleri yavaşlat
            self.volatilite[baglam] = abs(self.ema_trend[baglam])

        # Her bağlam için trend (pencere) ve hiperparametreyi ayarla
        for bc in self.BAĞLAMLAR:
            penc_bc = self.odul_gecmisi[bc]
            if len(penc_bc) < 20:
                continue
            self._ayarla(bc)

    def _ayarla(self, baglam):
        """Trend ve bağlama göre tek bir bağlamın lr/epsilon çarpanlarını Tayin eder.

        brain.lr / brain.epsilon'i doğrudan set etmez; bunun yerine
        brain.meta_lr_carpan / brain.meta_eps_carpan yazar. Bu değerler
        brain.update_dynamic_params() ile temel lr/ε üzerine çarpılır.
        """

        brain = self.brain
        trend = self.ema_trend[baglam]      # EMA tabanlı trend (-1..1)
        vol = self.volatilite[baglam]       # 0..1 arası volatilite

        # ---- Bağlam bağlamsal çarpanları ----
        if baglam == "uyku":
            ctx_lr, ctx_eps = 1.7, 1.5
        elif baglam == "tehlike":
            ctx_lr, ctx_eps = 0.6, 0.6
        elif baglam == "aclik":
            ctx_lr, ctx_eps = 1.3, 1.1
        else:  # rahatlama
            ctx_lr, ctx_eps = 0.85, 0.9

        # ---- Trend çarpanı ----
        if trend < -0.05:
            t_lr, t_eps = 1.25, 1.30     # performans düşüyor: agresif
        elif trend > 0.05:
            t_lr, t_eps = 0.80, 0.85     # iyileşiyor: sakinleş
        else:
            t_lr, t_eps = 1.00, 1.00

        # ---- Volatilite dampening ----
        # Ortam çok kararsızsa (vol > 0.7) değişiklikleri yarıya böl;
        # orta seyonda %75 uygula.
        if vol > 0.70:
            damp = 0.50
        elif vol > 0.40:
            damp = 0.75
        else:
            damp = 1.00

        # ---- Komut doğrulama skorları (transfer → meta_ogrenme) ----
        # _dogrula başarısı düşükse → daha fazla keşif (epsilon artar);
        # tehlike skoru yüksekse → daha temkinli öğrenme (lr azalır).
        if self.dogrulama_gecmensi and len(self.dogrulama_gecmensi) >= 5:
            dogruluk = sum(self.dogrulama_gecmensi) / len(
                self.dogrulama_gecmensi)
            if dogruluk < 0.5:
                t_eps *= 1.25          # doğru komut seçilemiyor → keşfet
            elif dogruluk > 0.7:
                t_eps *= 0.90          # iyi öğreniyor → daha tutuk

        if self.son_tehlike is not None and self.son_tehlike > 0.7:
            t_lr *= 0.85               # tehlikeli komut → daha dikkatli

        # ---- Uzuv LIM: kaynak baskısı → daha dikkatli ----
        if self.lim:
            ceza = self.lim.adaptif_ceza()
            if ceza > 1.0:
                t_lr *= 0.90
                t_eps *= 1.10

        lr_target = self.lr_base * ctx_lr * t_lr
        eps_target = self.epsilon_base * ctx_eps * t_eps

        # Hedef çarpanı 1.0 ile interpolasyonla damp'le
        lr_carpan = 1.0 + damp * (lr_target / self.lr_base - 1.0)
        eps_carpan = 1.0 + damp * (eps_target / self.epsilon_base - 1.0)

        # Güvenlik sınırları (carpan aşırı sapmasın)
        brain.meta_lr_carpan = max(0.25, min(4.0, lr_carpan))
        brain.meta_eps_carpan = max(0.25, min(4.0, eps_carpan))

        # ---- Meta-bellek: hangi çarpan hangi bağlamda ne kadar başarılı? ----
        mem = self.meta_memory[baglam]
        mem["n"] += 1
        mem["basari"] = 0.9 * mem["basari"] + 0.1 * trend
        mem["lr_carpan"] = brain.meta_lr_carpan
        mem["eps_carpan"] = brain.meta_eps_carpan

    # -------------------------------------------------------------- sorgular
    def durum(self):
        """Güncel meta-öğrenme durumu (günlük / inceleme için)."""
        return {
            "tik": self.tik,
            "baglam": self.son_baglam,
            "uyku_aktif": self._uyku_aktif,
            "lr": round(float(getattr(self.brain, "lr", self.lr_base)), 4),
            "epsilon": round(float(getattr(self.brain, "epsilon",
                                           self.epsilon_base)), 4),
            "meta_lr_carpan": round(
                float(getattr(self.brain, "meta_lr_carpan", 1.0)), 4),
            "meta_eps_carpan": round(
                float(getattr(self.brain, "meta_eps_carpan", 1.0)), 4),
            "trend_ema": {b: round(v, 3) for b, v in self.ema_trend.items()},
            "trend_pencere": {b: round(v, 3) for b, v in self.odul_trend.items()},
            "volatilite": {b: round(v, 3) for b, v in self.volatilite.items()},
            "meta_memory": {
                b: {
                    "lr": round(m["lr_carpan"], 3),
                    "eps": round(m["eps_carpan"], 3),
                    "basari": round(m["basari"], 3),
                    "n": m["n"],
                }
                for b, m in self.meta_memory.items()
            },
            "pencere_boyutlari": {
                b: len(p) for b, p in self.odul_gecmisi.items()
            },
            # ---- Yeni: komut doğrulama & LIM transfer skorları ----
            "dogrulama_skoru": (
                round(sum(self.dogrulama_gecmensi) / len(self.dogrulama_gecmensi), 3)
                if self.dogrulama_gecmensi else None
            ),
            "son_tehlike": round(self.son_tehlike, 3)
                if self.son_tehlike is not None else None,
            "son_komut_tip": self.son_komut_tip,
            "lim_durum": self.lim.durum() if self.lim else None,
        }
