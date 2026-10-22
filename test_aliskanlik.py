"""Aşama 6 — alışkanlaşma + sıkılma dinamiği regresyon testi.

Kontroller:
1) Atölye alışkanlaşması: değişken Δ'lı tekrar eden eylem (yarat) ödül
   tabanına oturur → ödül ~0'a iner (sonsuz ödül çeşmesi KAPALI)
2) Taban .beklenen.json'da kalıcı ("taban" alanı) — yeniden açılışta
   alışkanlık korunur
3) Gerçek anomali (tabanı büyük ölçüde aşan sürpriz) hâlâ tam ödül alır
   — alışkanlaşma keşfi öldürmez, yalnız rutin gürültüyü öldürür
4) drives.sikilan kesirli novelty: 1.0 eski davranış (−0.20), 0.4 kısmi
   (−0.08), 0 birikir
5) brain stimulus kademeli sıkılma jetonu: <0.33 yok, 0.33-0.66
   sikilma:1, >=0.66 sikilma:2 (eski hep-Y sinyali kalktı)

Kaynak ASCII-only değil (Türkçe yorumlar) — dosya UTF-8.
"""
import json
import sys
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, "/home/emrah/Genel/core")
from atolye import Atolye
import drives as D
import brain as B


class J:
    def __init__(self):
        self.kayitlar = []

    def log(self, kind, **k):
        self.kayitlar.append((kind, k))


# 1) alışkanlaşma: aynı eylem tekrarı ödül tabanına oturur
td = tempfile.mkdtemp(prefix="alisk_")
j = J()
a = Atolye(td, j, politika="yok")   # "yok": sec_is kullanılmaz, elle eylem
oduller = []
for i in range(40):
    r = a.eylem("yarat", "gözlem metni %d %s" % (i, "x" * (i * 7 % 64)))
    oduller.append(r["merak"])
ilk_odul = oduller[0]
son10 = oduller[-10:]
assert ilk_odul > 0, ilk_odul
assert max(abs(o) for o in son10) <= 0.01, ("ççeşit kapanmadı", oduller)
print("1 alışkanlaşma: ilk ödül %.2f → son10 max %.2f (çeşit kapandı)"
      % (ilk_odul, max(abs(o) for o in son10)))

# 2) taban kalıcı mı?
bek = json.loads((Path(td) / "atolye" / ".beklenen.json").read_text(
    encoding="utf-8"))
assert "taban" in bek.get("yarat", {}), bek.get("yarat")
assert bek["yarat"]["taban"] > 0.0, bek["yarat"]
a2 = Atolye(td, J(), politika="yok")
assert a2.beklenen["yarat"]["taban"] == bek["yarat"]["taban"]
print("2 sürpriz tabanı kalıcı: %.4f (yeniden yüklendi)"
      % bek["yarat"]["taban"])

# 3) anomali hâlâ ödül alır: kota dolu → sil (yer aç) + dev içerik (dev Δ)
kota_dolu = a.eylem("yarat", "y" * 100)
assert kota_dolu.get("bos") == 1 and kota_dolu["merak"] == 0.0, kota_dolu
r_sil = a.eylem("sil")           # adet −1: ilk sil sürpriz üretir
assert r_sil["merak"] > 0, r_sil
r_anom = a.eylem("yarat", "y" * 400)
assert r_anom["merak"] > 0.2, r_anom
print("3 anomali ödülü: sil %.2f · dev-içerik sürpriz %.2f → merak %.2f"
      % (r_sil["merak"], r_anom["surpriz"], r_anom["merak"]))

# 4) drives.sikilan kesirli novelty
d = D.Drives({"metabolism": {"energy_start": 100.0,
                             "energy_decay_per_tick": 1.0,
                             "hunger_start": 10.0,
                             "hunger_growth_per_tick": 1.0,
                             "eat_hunger_relief": 10.0}})
d.sikilma = 1.0
d.sikilan(1.0)
assert abs(d.sikilma - 0.80) < 1e-9, d.sikilma      # eski davranış: −0.20
d.sikilan(0.4)
assert abs(d.sikilma - 0.72) < 1e-9, d.sikilma      # kısmi: −0.08
d.sikilma = 0.0
for _ in range(10):
    d.sikilan(0)
assert abs(d.sikilma - 0.05) < 1e-9, d.sikilma      # birikim: +0.005×10
print("4 sikilan kesirli: 1.0→%.2f, 0.4→%.2f, 10×0→%.2f"
      % (0.80, 0.72, d.sikilma))

# 5) beyin kademeli sıkılma jetonu
class Dz:
    sikilma = 0.0
    def bins(self):
        return "H", "T"
    hunger = 10.0
    energy = 100.0


dz = Dz()
m = B.Brain()
for esik, beklenen in ((0.10, None), (0.40, "sikilma:1"),
                       (0.80, "sikilma:2")):
    dz.sikilma = esik
    stim = m.stimulus(dz, "ctx", "oda", "dosya")
    if beklenen is None:
        assert "sikilma:" not in stim, stim
    else:
        assert beklenen in stim, (beklenen, stim)
    assert "sikilma:Y" not in stim, ("eski jeton kalktı", stim)
print("5 beyin kademe jetonu: yok/sikilma:1/sikilma:2 OK")

shutil.rmtree(td, ignore_errors=True)
print("ALISKANLIK + SIKILMA: 5/5 OK")