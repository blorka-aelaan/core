"""CORE drives — iç güdüler.

Açlık ve enerji organizmanın kendi içinden gelen tek güçtür.
Hiçbir amaç dışarıdan verilmez; doymak ve hayatta kalmak yeterlidir.
"""


class Drives:
    def __init__(self, cfg):
        m = cfg["metabolism"]
        self.energy = float(m["energy_start"])
        self.energy_cap = float(m.get("energy_cap", 150))
        self.hunger = float(m.get("hunger_start", 10))
        self.decay = float(m["energy_decay_per_tick"])
        self.growth = float(m["hunger_growth_per_tick"])
        self.eat_relief = float(m["eat_hunger_relief"])
        self.eat_energy_ratio = max(
            0.0, min(1.0, float(m.get("eat_energy_ratio", 0.65)))
        )
        self.eat_hunger_threshold = max(
            0.0, float(m.get("eat_hunger_threshold", 40.0))
        )
        self.decay_factor = 1.0  # sığınak vb. çarpanlar (main belirler)
        # Perde 1 — acı & kurtuluş: yaşamak istemek
        self.pain_threshold = float(m.get("pain_threshold", 30))
        self.pain_penalty = float(m.get("pain_penalty", 4.0))
        self.relief_bonus = float(m.get("relief_bonus", 8.0))
        # Perde 4 — sıkılma (Aşama 4): rutin doygunluğu. Yenilik söndürür,
        # rutin biriktirir; keşif baskısını beyin bu iç dürtüyle hisseder.
        self.sikilma = 0.0
        # Keşif oranı: başlangıçta 0.35, sıkılma arttıkça yükselir (max 0.55)
        self.epsilon = float(m.get("epsilon_start", 0.35))
        # ---------- Yeni: Homeostaz ----------
        # Homeostaz eşikleri: altındağı organize "hayatta kalma moduna" geçer.
        self.HOMEOSTAZ_KRITIK = 0.25    # altında: hayatta kalma modu
        self.HOMEOSTAZ_UYARI = 0.45     # altında: dikkat, keşif kısıtlı
        # Hayatta kalma modu sayacı (kaç tik süreceği)
        self.hayatta_kalma_tik = 0
        # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
        # Bu bilgisayarın fiziksel durumu — organizmanın "bedeni"
        self.insan_var = False        # kimse kullanıyor mu?
        self.sistem_saati = 0         # sistemin açık kaldığı saat
        self.disk_yuzde = 0           # disk doluluk %
        self.bellek_yuzde = 0         # bellek doluluk %
        # ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
        self.usb_cihaz_sayisi = 0     # /sys/bus/usb/devices'teki cihaz sayisi
        self.usb_node_sayisi = 0      # /dev/bus/usb altindaki node sayisi
        # ---------- Yeni: USB keşif bonusu (merak artırıcı) (Aşama 11) ----------
        self.usb_keşif_bonusu = 0.0   # Yeni USB cihaz bulunduğunda merak artışı
        self.usb_keşif_süresi = 0     # Bonusun kaç tik daha geçerli kalacağı

    @property
    def alive(self):
        is_alive = self.energy > 0
        if not is_alive:
            print(f"DEBUG: Organizma ölü! Enerji: {self.energy}")
        return is_alive

    def pain(self):
        """Acı yoğunluğu 0..1: eşiğin altına ne kadar derin indi."""
        thr = self.pain_threshold
        if thr <= 0 or self.energy >= thr:
            return 0.0
        return max(0.0, (thr - self.energy) / thr)

    @property
    def in_danger(self):
        return self.energy < self.pain_threshold

    @property
    def needs_food(self):
        """Yemek, açlık veya düşük enerji gerçek bir ihtiyaca dönüştüğünde açılır."""
        return (
            self.energy <= self.pain_threshold
            or self.energy <= self.energy_cap * self.eat_energy_ratio
            or self.hunger >= self.eat_hunger_threshold
        )

    @property
    def safe_to_explore(self):
        """Keşif, enerji ve açlık güvenli aralıklardayken hızlandırılır."""
        e_cap = max(1.0, self.energy_cap)
        return (
            not self.in_danger
            and self.energy / e_cap >= 0.70
            and self.hunger <= 30.0
            and self.homeostaz_puani() >= 0.65
        )

    # ------------------------------------------------- Yeni: Homeostaz
    def homeostaz_puani(self):
        """Homeostaz (iç denge) puanı 0..1.

        1.0 = mükemmel denge (enerji yüksek, açlık düşük, acı yok).
        0.0 = kritik durum (enerji düşük, açlık yüksek, acı var).
        Ağırlıklar: enerji %40, açlık %30, acı %30.
        """
        e_cap = max(1.0, float(self.energy_cap))
        e_ratio = max(0.0, min(1.0, self.energy / e_cap))
        h_ratio = max(0.0, min(1.0, self.hunger / 100.0))  # açlık 0..100 ölçeği
        p = self.pain()  # 0..1
        # Açlık ve acı negatif etki, enerji pozitif
        return max(0.0, min(1.0, 0.40 * e_ratio + 0.30 * (1.0 - h_ratio) + 0.30 * (1.0 - p)))

    @property
    def hayatta_kalma_modu(self):
        """Homeostaz kritik seviyedeyse True: sadece hayatta kalma eylemleri."""
        return self.homeostaz_puani() < self.HOMEOSTAZ_KRITIK

    @property
    def uyari_modu(self):
        """Homeostaz uyarı seviyesindeyse True: keşif kısıtlı, riflenen eylem."""
        return self.homeostaz_puani() < self.HOMEOSTAZ_UYARI

    def update_hayatta_kalma(self):
        """Her tikte çağrılır: hayatta kalma modu sayacını günceller."""
        if self.hayatta_kalma_modu:
            self.hayatta_kalma_tik += 1
        else:
            # Moddan çıktığında sayacı yavaş sıfırla (histerezis)
            self.hayatta_kalma_tik = max(0, self.hayatta_kalma_tik - 1)

    # ------------------------------------------------- Mevcut metodlar (aşağıda değişiklik yok)
    def tick(self):
        """Kalp atışı: her tik metabolizma faturasıdır."""
        # açlık da faturayı büyütür: açken vücut daha hızlı yanar
        stress = 1.3 if self.hunger > 80 else 1.0
        self.energy -= self.decay * self.decay_factor * stress
        self.hunger += self.growth
        # Homeostaz güncelle
        self.update_hayatta_kalma()

    def spend(self, cost):
        self.energy -= cost

    def consume(self, gain, relief):
        """Yemek: enerji al, açlığı dindir.

        Gerçekte alınan enerji ve gerçek azalan açlık döner — ödül
        bu "gerçek" değerler üzerinden biçilir (tokken yemek boş).
        """
        before = self.energy
        self.energy = min(self.energy_cap, self.energy + gain)
        got = self.energy - before
        before_h = self.hunger
        self.hunger = max(0.0, self.hunger - relief)
        relief_done = before_h - self.hunger
        return got, relief_done

    def spark(self, amount):
        """Küçük kıvılcım (ör. kapıdan gelen ilgi)."""
        before = self.energy
        self.energy = min(self.energy_cap, self.energy + amount)
        return self.energy - before

    def beden_guncelle(self, insan_var: bool, sistem_saati: int, disk_yuzde: float, bellek_yuzde: float, usb_cihaz: int = 0, usb_node: int = 0):
        """Bu bilgisayarın beden durumunu günceller (Aşama 8).

        organizma bu bilgiyi kendi iç durumunu şekillendirmek için kullanır.
        """
        self.insan_var = bool(insan_var)
        self.sistem_saati = int(sistem_saati)
        self.disk_yuzde = float(disk_yuzde)
        self.bellek_yuzde = float(bellek_yuzde)
        self.usb_cihaz_sayisi = int(usb_cihaz)
        self.usb_node_sayisi = int(usb_node)

    def usb_yeni_cihaz_buldu(self):
        """Yeni bir USB cihazı algılandığında merak bonusunu artırır.

        Organizma cihazı keşfettiğinde merak puanı yükselir ve bu
        etki birkaç tik boyunca devam eder (eporan).
        """
        self.usb_keşif_bonusu = min(1.0, self.usb_keşif_bonusu + 0.30)
        self.usb_keşif_süresi = max(self.usb_keşif_süresi, 30)

    def ag_yeni_trafigi_buldu(self):
        """Yeni bir ağ trafiği deseni algılandığında merak bonusunu artırır.

        Organizma yeni bir port/IP kombinasyonu keşfettiğinde merak
        puanı yükselir ve bu etki birkaç tik boyunca devam eder.
        """
        self.usb_keşif_bonusu = min(1.0, self.usb_keşif_bonusu + 0.20)
        self.usb_keşif_süresi = max(self.usb_keşif_süresi, 20)

    def sikilan(self, novelty):
        """Sıkılma güncelle (Aşama 4): yenilik doyurur, rutin bunaltır.

        novelty KESİRLİ olabilir (0..1): 1.0 tam yenilik (eski davranış
        aynen), 0.3 gibi değerler kısmi doygunluk (ör. küçük merak
        ödülü). Dönüş: 0..1 sıkılma — beyin keşif baskısını bundan alır.

        Insan varlığını da dikkate alır: kimse kullanmıyorsa sıkılma daha
        hızlı artar; insan varsa organizma gözlemlemekle meşgul olur,
        sıkılma daha yavaş artar.
        """
        if novelty > 0:
            self.sikilma = max(0.0, self.sikilma
                               - 0.20 * min(1.0, float(novelty)))
        else:
            artis = 0.005
            if self.insan_var:
                artis *= 0.5  # insan varsa yavaş artar
            self.sikilma = min(1.0, self.sikilma + artis)
        return self.sikilma

    def bins(self):
        eb = "L" if self.energy < 40 else ("M" if self.energy < 90 else "H")
        hb = "A" if self.hunger > 70 else ("O" if self.hunger > 30 else "T")
        return eb, hb

    # ---------- Yeni: Duygu / ruh hali vektörü (Aşama 6) ----------
    def _mood_guncelle(self):
        """Her tikte çağrılır: güncel iç duruma göre mood'u yeniden hesaplar."""
        e_cap = max(1.0, float(self.energy_cap))
        e_ratio = max(0.0, min(1.0, self.energy / e_cap))
        h_ratio = max(0.0, min(1.0, self.hunger / 100.0))
        p = self.pain()
        sk = max(0.0, min(1.0, self.sikilma))
        # ---------- Yeni: Beden durumu etkisi (Aşama 8) ----------
        disk_baski = max(0.0, (self.disk_yuzde - 80.0) / 20.0)   # %80 üzeri baskı
        bellek_baski = max(0.0, (self.bellek_yuzde - 80.0) / 20.0)  # %80 üzeri baskı
        beden_baski = max(disk_baski, bellek_baski)  # en yüksek baskı etkili

        # ---------- Yeni: USB keşif bonusu etkisi (Aşama 11) ----------
        # Her tikte bonus azalır; süresi dolduğunda sıfırlanır.
        if self.usb_keşif_süresi > 0:
            self.usb_keşif_süresi -= 1
            if self.usb_keşif_süresi <= 0:
                self.usb_keşif_bonusu = 0.0
        else:
            self.usb_keşif_bonusu = max(0.0, self.usb_keşif_bonusu - 0.05)

        mutluluk = 0.5 * e_ratio + 0.3 * (1.0 - h_ratio) + 0.2 * (1.0 - p)
        mutluluk *= (1.0 - 0.3 * beden_baski)  # dolu beden mutluluğu azaltır
        korku = 0.6 * p + 0.4 * (1.0 - e_ratio) + 0.3 * beden_baski  # dolu beden korku artırır
        guven = self.homeostaz_puani() * (0.5 if not self.hayatta_kalma_modu else 0.2)
        merak = (1.0 - sk) * (0.5 + 0.5 * e_ratio) + 0.4 * self.usb_keşif_bonusu
        sikilma_norm = sk

        # ---------- Yeni: Sıkılma → keşif oranı artışı (Aşama 4) ----------
        # Sıkıldıkça (boredom) keşif (epsilon) artar, istikrarlı öğrenme de
        # maksimum %20 kadar hızlanır (lr=1.0 sabit).
        _t_eps = 1.0 + 0.8 * sk
        _t_lr = 1.2 - 0.2 * sk
        self.epsilon = min(0.55, self.epsilon * _t_eps)

        self.mood = {
            "mutluluk": round(max(0.0, min(1.0, mutluluk)), 3),
            "korku": round(max(0.0, min(1.0, korku)), 3),
            "guven": round(max(0.0, min(1.0, guven)), 3),
            "merak": round(max(0.0, min(1.0, merak)), 3),
            "sikilma": round(sikilma_norm, 3),
            # ---------- Yeni: Beden durumu ----------
            "disk_baski": round(disk_baski, 3),
            "bellek_baski": round(bellek_baski, 3),
            "beden_baski": round(beden_baski, 3),
            # ---------- Yeni: USB keşif bonusu (Aşama 11) ----------
            "usb_keşif_bonusu": round(self.usb_keşif_bonusu, 3),
        }
        _sirali = sorted(self.mood.items(), key=lambda kv: -kv[1])
        self.mood_dominant = _sirali[0][0] if _sirali else "mutluluk"
        return self.mood

    def mood_etki(self):
        """Duyguya dayalı lr ve epsilon çarpanı (0.5 .. 1.5)."""
        m = getattr(self, "mood", None) or self._mood_guncelle()
        t_lr = 1.0
        t_eps = 1.0
        if m["korku"] > 0.6:
            t_lr *= 0.75
            t_eps *= 0.80
        if m["mutluluk"] > 0.7:
            t_lr *= 0.85
            t_eps *= 0.85
        if m["merak"] > 0.6:
            t_eps *= 1.20
        if m["guven"] < 0.3:
            t_eps *= 1.15
        return max(0.5, min(1.5, t_lr)), max(0.5, min(1.5, t_eps))

    def state(self):
        self._mood_guncelle()
        return {
            "energy": round(self.energy, 1),
            "hunger": round(self.hunger, 1),
            "alive": self.alive,
            # ---------- Yeni: Homeostaz durumu ----------
            "homeostaz": round(self.homeostaz_puani(), 2),
            "hayatta_kalma": self.hayatta_kalma_modu,
            "hayatta_kalma_tik": self.hayatta_kalma_tik,
            # ---------- Yeni: Duygu ----------
            "mood": self.mood,
            "mood_dominant": self.mood_dominant,
            # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
            "insan_var": self.insan_var,
            "sistem_saati": self.sistem_saati,
            "disk_yuzde": self.disk_yuzde,
            "bellek_yuzde": self.bellek_yuzde,
            # ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
            "usb_cihaz_sayisi": self.usb_cihaz_sayisi,
            "usb_node_sayisi": self.usb_node_sayisi,
            # ---------- Yeni: USB keşif bonusu (Aşama 11) ----------
            "usb_keşif_bonusu": round(self.usb_keşif_bonusu, 3),
            "usb_keşif_süresi": self.usb_keşif_süresi,
        }

