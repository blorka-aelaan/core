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
        self.decay_factor = 1.0  # sığınak vb. çarpanlar (main belirler)
        # Perde 1 — acı & kurtuluş: yaşamak istemek
        self.pain_threshold = float(m.get("pain_threshold", 30))
        self.pain_penalty = float(m.get("pain_penalty", 4.0))
        self.relief_bonus = float(m.get("relief_bonus", 8.0))
        # Perde 4 — sıkılma (Aşama 4): rutin doygunluğu. Yenilik söndürür,
        # rutin biriktirir; keşif baskısını beyin bu iç dürtüyle hisseder.
        self.sikilma = 0.0
        # ---------- Yeni: Homeostaz ----------
        # Homeostaz eşikleri: altındağı organize "hayatta kalma moduna" geçer.
        self.HOMEOSTAZ_KRITIK = 0.25    # altında: hayatta kalma modu
        self.HOMEOSTAZ_UYARI = 0.45     # altında: dikkat, keşif kısıtlı
        # Hayatta kalma modu sayacı (kaç tik süreceği)
        self.hayatta_kalma_tik = 0

    @property
    def alive(self):
        return self.energy > 0

    def pain(self):
        """Acı yoğunluğu 0..1: eşiğin altına ne kadar derin indi."""
        thr = self.pain_threshold
        if thr <= 0 or self.energy >= thr:
            return 0.0
        return max(0.0, (thr - self.energy) / thr)

    @property
    def in_danger(self):
        return self.energy < self.pain_threshold

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

    def sikilan(self, novelty):
        """Sıkılma güncelle (Aşama 4): yenilik doyurur, rutin bunaltır.

        novelty KESİRLİ olabilir (0..1): 1.0 tam yenilik (eski davranış
        aynen), 0.3 gibi değerler kısmi doygunluk (ör. küçük merak
        ödülü). Dönüş: 0..1 sıkılma — beyin keşif baskısını bundan alır.
        """
        if novelty > 0:
            self.sikilma = max(0.0, self.sikilma
                               - 0.20 * min(1.0, float(novelty)))
        else:
            self.sikilma = min(1.0, self.sikilma + 0.005)
        return self.sikilma

    def bins(self):
        eb = "L" if self.energy < 40 else ("M" if self.energy < 90 else "H")
        hb = "A" if self.hunger > 70 else ("O" if self.hunger > 30 else "T")
        return eb, hb

    def state(self):
        return {
            "energy": round(self.energy, 1),
            "hunger": round(self.hunger, 1),
            "alive": self.alive,
            # ---------- Yeni: Homeostaz durumu ----------
            "homeostaz": round(self.homeostaz_puani(), 2),
            "hayatta_kalma": self.hayatta_kalma_modu,
            "hayatta_kalma_tik": self.hayatta_kalma_tik,
        }
