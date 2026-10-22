"""surec — bağışıklık sistemi: habitat (çalışan süreçler) tanınması.

/proc dosya sisteminden ucuz tarama (alt süreç yok). Her sürecin
görünme frekansını öğrenir; yüksek frekans = "kendim" (self).
Anomaliler objektiftir, kural listesi yok:
  * eksik: "kendim" saydığı ama şu an görünmeyen (habitat bozuldu)
  * yeni : daha önce hiç görülmemiş (ajan/merak)

Organizma kendi normalini kendi öğrenir — öğretmen ilkesi tutarlı.
Kalıcılık: zeka/surec.json (tmp + rename). Beyin uyaranı: sistem:EKSIK.
Eksik varsa metabolizma hızlanır: habitatı yaşam kaynağı gibi hisseder.
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class Surec:
    def __init__(self, cfg):
        s = cfg.get("surec", {})
        self.periyot = int(s.get("periyot", 50))     # her N tikte tara
        self.prag = float(s.get("prag", 0.6))        # "kendim" frekans eşiği
        self.azami_ad = int(s.get("azami_ad", 400))  # hafıza sınırı
        self.dusman = float(s.get("dusman_factor", 1.15))  # eksik→yanma
        self.adet = {}    # comm -> görünme sayısı
        self.kayip = {}   # comm -> üst üste kayıp örnek sayısı
        self.ornek = 0    # toplam örnek
        self.eksik = []   # son örnekte kaybolan "kendim"ler
        self.yeni = []    # ilk kez görülenler

    def tara(self):
        """ /proc'dan tarama: kullanıcı süreçleri (comm + cmdline).

        Çekirdek iş parçacıkları (cmdline boş, örn. kworker/*) izlenmez:
        dinamiktirler, "kendim" diye sahte eksik alarmları üretirler.
        """
        gorunen = set()
        try:
            girdiler = os.listdir("/proc")
        except OSError:
            return gorunen
        for g in girdiler:
            if not g.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % g, "r") as f:
                    if not f.read(1):      # boş cmdline = çekirdek parçası
                        continue
                with open("/proc/%s/comm" % g, "r") as f:
                    ad = f.read().strip()
            except OSError:
                continue  # süreç tam bu anda bitti
            if ad:
                gorunen.add(ad)
        return gorunen

    def ornekle(self):
        """Bir örnek al, frekansları güncelle, anomaliyi bul."""
        gorunen = self.tara()
        if not gorunen:
            # /proc okunamadı: anomali ilan etme, sessizce geç
            return {"eksik": [], "yeni": [], "toplam": len(self.adet)}
        return self.isle(gorunen)

    def isle(self, gorunen):
        """(test edilebilir çekirdek) verilen kümeyle öğren + anomali bul."""
        self.ornek += 1
        ilk = self.ornek == 1
        yeni = [] if ilk else [a for a in gorunen if a not in self.adet]
        for ad in gorunen:
            self.adet[ad] = self.adet.get(ad, 0) + 1
        # tüm kayıpları say: öncekileri bir artır, yeni kayıpları 1'den
        # başlat — alarm ancak üst üste 2 örnekte tetiklenir
        self.kayip = {ad: self.kayip.get(ad, 0) + 1
                      for ad in self.adet if ad not in gorunen}
        eksik = []
        if self.ornek >= 4:  # erken gürültüde anomali ilan etme
            esik = self.prag * self.ornek
            for ad, n in self.adet.items():
                if n < esik or ad in gorunen:
                    continue
                k = self.kayip.get(ad, 0)
                # tek örneklik yokluğa güvenme: yeniden başlayan servis,
                # sıradan kısa süreli kayıplar sahte alarm üretmesin
                if k >= 2:
                    eksik.append(ad)
        # hafıza sınırı: en seyrek görülenleri unut (eski hastalıklar
        # belleği şişirmesin); unutulanlar sonradan "yeni" olarak döner
        if len(self.adet) > self.azami_ad:
            fazla = len(self.adet) - self.azami_ad
            for ad, _n in sorted(self.adet.items(),
                                 key=lambda x: x[1])[:fazla]:
                del self.adet[ad]
                self.kayip.pop(ad, None)
        self.eksik = sorted(eksik)
        self.yeni = sorted(yeni)
        return {"eksik": self.eksik, "yeni": self.yeni,
                "toplam": len(self.adet)}

    def save(self):
        yol = ROOT / "zeka" / "surec.json"
        yol.parent.mkdir(exist_ok=True)
        tmp = yol.with_name("%s.%d.tmp" % (yol.name, os.getpid()))
        tmp.write_text(json.dumps(
            {"ornek": self.ornek,
             "adet": dict(sorted(self.adet.items()))},
            ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(yol))

    def load(self):
        yol = ROOT / "zeka" / "surec.json"
        if not yol.exists():
            return False
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.ornek = int(veri.get("ornek", 0))
        self.adet = {str(k): int(v)
                     for k, v in veri.get("adet", {}).items()}
        return True