"""test_uyku_egit.py - uyku.py ve egit.py duzeltmelerinin testleri.

  python3 test_uyku_egit.py

Gercek dosyalara/models'e dokunmaz: uyku testleri zeka'yi gecici dizin
saglayan bir taslakla degistirir, subprocess.run'i taklit eder.
Kaynak ASCII-only.
"""
import json
import tempfile
import time
import types
import unittest
from pathlib import Path

import brain
import uyku

try:
    import egit
    import damak as D
    import kutu_uretici as K
except ImportError:       # egit bagimliliklari yoksa egit testlerini atla
    egit = None


class TaslakZeka(object):
    def __init__(self, kok):
        self.kok = Path(kok)

    def yol(self, ad):
        return self.kok / ad

    def kayit(self, ad):
        return self.kok / ad


class UykuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kok = Path(self.tmp.name)
        self._eski = (uyku.ROOT, uyku.zeka, uyku.subprocess.run)
        uyku.ROOT = self.kok
        uyku.zeka = TaslakZeka(self.kok)
        (self.kok / "journal.jsonl").write_bytes(b"x" * 100)
        self.now = time.time()
        self.u = uyku.Uyku({})
        self._taze()

    def tearDown(self):
        uyku.ROOT, uyku.zeka, uyku.subprocess.run = self._eski
        self.tmp.cleanup()

    def _taze(self):
        """Tum hatlari 'az once basariyla egitildi' isaretle."""
        for ad in uyku.HATLAR:
            self.u.son[ad] = {"t": self.now,
                              "veri": self.u._veri_sayisi(ad),
                              "damga": self.u._damga(ad)}

    def test_taze_durumda_uyku_yok(self):
        self.assertIsNone(self.u.karar(now=self.now))

    def test_hatira_bayt_esigi(self):
        with open(self.kok / "journal.jsonl", "ab") as f:
            f.write(b"x" * (uyku.HATIRA_ESIK + 10))
        k = self.u.karar(now=self.now)
        self.assertIsNotNone(k)
        self.assertEqual(k["ad"], "hatira")

    def test_hatira_esik_altinda_tetiklenmez(self):
        with open(self.kok / "journal.jsonl", "ab") as f:
            f.write(b"x" * 1000)
        self.assertIsNone(self.u.karar(now=self.now))

    def test_oncelik_en_eski_once(self):
        self.u.son["guvenlik"]["t"] = self.now - 10 * 3600     # 1s tazelik
        self.u.son["paket"]["t"] = self.now - 100 * 3600       # 4s tazelik
        k = self.u.karar(now=self.now)
        self.assertEqual(k["ad"], "paket")

    def test_hic_egitilmemis_hat_once(self):
        self.u.son["paket"]["t"] = self.now - 100 * 3600
        del self.u.son["dizin"]
        k = self.u.karar(now=self.now)
        self.assertEqual(k["ad"], "dizin")

    def test_basarisiz_egitim_yapildi_sayilmaz(self):
        self.u.son["guvenlik"]["t"] = self.now - 10 * 3600
        eski_t = self.u.son["guvenlik"]["t"]
        uyku.subprocess.run = lambda *a, **k: types.SimpleNamespace(
            returncode=1)
        k = self.u.karar(now=self.now)
        self.assertEqual(k["ad"], "guvenlik")
        s = self.u.uyu(k)
        self.assertEqual(s["kod"], 1)
        self.assertEqual(self.u.son["guvenlik"]["t"], eski_t)   # korunur
        self.assertEqual(self.u.son["guvenlik"]["hata_say"], 1)
        # geri cekilme: hemen yeniden secilmez, zorla secilir
        simdi = time.time()
        self.assertIsNone(self.u.karar(now=simdi + 5))
        self.assertIsNotNone(self.u.karar(now=simdi + 5, zorla=True))
        # sure dolunca tekrar aday
        self.assertEqual(self.u.karar(now=simdi + 601)["ad"], "guvenlik")

    def test_ustel_geri_cekilme_ve_tavan(self):
        self.u.son["guvenlik"]["t"] = self.now - 10 * 3600
        uyku.subprocess.run = lambda *a, **k: types.SimpleNamespace(
            returncode=1)
        k = {"ad": "guvenlik", "damga": 0, "veri": 0}
        self.u.uyu(k)
        self.assertEqual(self.u.son["guvenlik"]["hata_bekle"], 600)
        self.u.uyu(k)
        self.assertEqual(self.u.son["guvenlik"]["hata_bekle"], 1200)
        for _ in range(10):
            self.u.uyu(k)
        self.assertEqual(self.u.son["guvenlik"]["hata_bekle"],
                         uyku.HATA_TAVAN)

    def test_basari_hata_sayacini_sifirlar(self):
        uyku.subprocess.run = lambda *a, **k: types.SimpleNamespace(
            returncode=1)
        k = {"ad": "guvenlik", "damga": 0, "veri": 0}
        self.u.uyu(k)
        uyku.subprocess.run = lambda *a, **k: types.SimpleNamespace(
            returncode=0)
        s = self.u.uyu(k)
        self.assertEqual(s["kod"], 0)
        self.assertNotIn("hata_t", self.u.son["guvenlik"])
        self.assertNotIn("hata_say", self.u.son["guvenlik"])

    def test_hatira_beyin_yoksa_yapildi_sayilmaz(self):
        s = self.u.uyu({"ad": "hatira", "damga": 0, "veri": 5}, None)
        self.assertEqual(s["kod"], -2)
        self.assertEqual(self.u.son["hatira"]["t"], self.now)   # korunur
        self.assertIn("hata_t", self.u.son["hatira"])

    def test_hatira_replay_calisir(self):
        beyin = types.SimpleNamespace(hatira=lambda yol: 7)
        t0 = time.time()
        s = self.u.uyu({"ad": "hatira", "damga": 0, "veri": 5}, beyin)
        self.assertEqual((s["kod"], s["ornek"]), (0, 7))
        self.assertGreaterEqual(self.u.son["hatira"]["t"], t0)
        self.assertNotIn("hata_t", self.u.son["hatira"])

    def test_hatira_istisnasi_dongu_cokertmez(self):
        def patla(yol):
            raise KeyError("bozuk kayit")
        s = self.u.uyu({"ad": "hatira", "damga": 0, "veri": 5},
                       types.SimpleNamespace(hatira=patla))
        self.assertEqual(s["kod"], -1)

    def test_eski_turkce_anahtar_tasinir(self):
        eski = "hat\u0131ra"
        (self.kok / "uyku.json").write_text(
            json.dumps({"son": {eski: {"t": 1, "veri": 2, "damga": 0}}}),
            encoding="utf-8")
        u = uyku.Uyku({"uyku": {"tazele_saat": {eski: 12}}})
        self.assertIn("hatira", u.son)
        self.assertNotIn(eski, u.son)
        self.assertEqual(u.tazele["hatira"], 12.0)


class KonsolideTest(unittest.TestCase):
    """Asama 5 - beyin agirlik budamasi (brain.konsolide) + uyku hatti.

    Beyin testleri bellek uzerinde calisir (kaynak dosyaya dokunmaz);
    uyku testleri zeka'yi gecici dizin saglayan taslakla degistirir.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kok = Path(self.tmp.name)
        self._eski = (uyku.ROOT, uyku.zeka)
        uyku.ROOT = self.kok
        uyku.zeka = TaslakZeka(self.kok)
        (self.kok / "journal.jsonl").write_bytes(b"x" * 100)
        self.now = time.time()
        self.u = uyku.Uyku({})
        self._taze()

    def _taze(self):
        """Tum hatlari 'az once basariyla egitildi' isaretle."""
        for ad in uyku.HATLAR:
            self.u.son[ad] = {"t": self.now,
                              "veri": self.u._veri_sayisi(ad),
                              "damga": self.u._damga(ad)}

    def tearDown(self):
        uyku.ROOT, uyku.zeka = self._eski
        self.tmp.cleanup()

    def _beyin(self):
        """Guclu / zayif / ezilmis-icgudulu ornek beyin."""
        b = brain.Brain()
        b.w[("gorev:GUC", "eat")] = 1.5           # guclu: korunur
        b.w[("gorev:ZAF", "wander")] = 0.005      # zayif: budanir
        b.w[("gorev:NEG", "console")] = -0.019    # zayif negatif: budanir
        b.w[("A", "eat")] = 0.001                 # icgudu ezilmis: KORUNUR
        b.usage[("A", "eat")] = 2                 # kullanım geçmişi var: PRUNE_USAGE_MIN'e uçar
        return b

    def test_konsolide_zayiflari_budar_icguduleri_korur(self):
        b = self._beyin()
        n = b.konsolide()
        self.assertEqual(n, 2)                    # yalnizca zayif ikili
        self.assertIn(("gorev:GUC", "eat"), b.w)
        self.assertIn(("A", "eat"), b.w)          # esik altinda olsa da
        self.assertNotIn(("gorev:ZAF", "wander"), b.w)
        self.assertNotIn(("gorev:NEG", "console"), b.w)

    def test_budama_davranisi_esik_kadar_oynatir(self):
        # notr budama: silinen baglantinin skora etkisi |w| kadardir,
        # esik alti bir baglanti karari praktikte degistirmez
        b = brain.Brain()
        b.w[("gorev:ZAF", "wander")] = 0.019      # esik hemen alti
        oncesi = b.score("gorev:ZAF", "wander")
        b.konsolide()
        self.assertLess(abs(oncesi - b.score("gorev:ZAF", "wander")), 0.02)

    def test_uyku_hatti_tanimli_ve_periyodik(self):
        self.assertEqual(uyku.HATLAR["konsolide"], (None, 0))
        self.assertEqual(self.u.tazele.get("konsolide"), 6.0)
        self.assertEqual(self.u._damga("konsolide"), 0.0)
        self.assertEqual(self.u._veri_sayisi("konsolide"), 0)
        # taze durumda UYKU YOK: veri/damga tetikleyicisi olmadigindan
        # yalnizca bayatlikla periyodik olarak secilir
        for ad in uyku.HATLAR:
            self.u.son[ad] = {"t": self.now,
                              "veri": self.u._veri_sayisi(ad),
                              "damga": self.u._damga(ad)}
        self.assertIsNone(self.u.karar(now=self.now))
        self.u.son["konsolide"]["t"] = self.now - 7 * 3600    # 6s tazelik
        k = self.u.karar(now=self.now)
        self.assertEqual(k["ad"], "konsolide")

    def test_uyu_surec_ici_cagirir(self):
        b = self._beyin()
        t0 = time.time()
        s = self.u.uyu({"ad": "konsolide", "damga": 0, "veri": 0}, b)
        self.assertEqual((s["kod"], s["ornek"]), (0, 2))
        self.assertGreaterEqual(self.u.son["konsolide"]["t"], t0)
        self.assertNotIn("hata_t", self.u.son["konsolide"])
        self.assertNotIn(("gorev:ZAF", "wander"), b.w)   # gercekten budandi
        self.assertIn(("A", "eat"), b.w)

    def test_konsolide_beyin_yoksa_yapildi_sayilmaz(self):
        s = self.u.uyu({"ad": "konsolide", "damga": 0, "veri": 0}, None)
        self.assertEqual(s["kod"], -2)
        self.assertEqual(self.u.son["konsolide"]["t"], self.now)  # korunur
        self.assertIn("hata_t", self.u.son["konsolide"])

    def test_konsolide_istisnasi_dongu_cokertmez(self):
        def patla():
            raise RuntimeError("bozuk beyin")
        s = self.u.uyu({"ad": "konsolide", "damga": 0, "veri": 0},
                       types.SimpleNamespace(konsolide=patla))
        self.assertEqual(s["kod"], -1)


@unittest.skipIf(egit is None, "egit bagimliliklari (damak/kutu_uretici) yok")
class EgitTest(unittest.TestCase):
    def setUp(self):
        self.cfg = K.load_cfg(None)

    def test_bolum_ayrik(self):
        import random
        rng = random.Random(1)
        egitim = set(egit.bolumlu_isim(rng, self.cfg, False)
                     for _ in range(1500))
        hold = set(egit.bolumlu_isim(rng, self.cfg, True)
                   for _ in range(1500))
        self.assertTrue(egitim)
        self.assertTrue(hold)
        self.assertFalse(egitim & hold)
        self.assertTrue(all(not egit.holdout_mu(n) for n in egitim))
        self.assertTrue(all(egit.holdout_mu(n) for n in hold))

    def test_degerlendirme_tekrarlanabilir_ve_tabanli(self):
        d, _ = egit.egit(self.cfg, 3000, seed=3, kaydet=False)
        r1, _ = egit.degerlendir(self.cfg, d, adet=500, seed=5)
        r2, _ = egit.degerlendir(self.cfg, d, adet=500, seed=5)
        self.assertEqual(r1, r2)
        for anahtar in ("mae_taban", "regret_rastgele", "top3_sans",
                        "holdout_benzersiz"):
            self.assertIn(anahtar, r1)

    def test_global_random_durumu_korunur(self):
        import random
        d, _ = egit.egit(self.cfg, 500, seed=3, kaydet=False)
        random.seed(123)
        beklenen = random.random()
        random.seed(123)
        egit.degerlendir(self.cfg, d, adet=200, seed=5)
        self.assertEqual(random.random(), beklenen)

    def test_kaydet_false_gercek_damagi_korumaz(self):
        """REGRESYON (2026-10-18): egit() varsayilan save() GERCEK
        zeka/damak.json'a yazardi — her test kosusu 50000'luk canli
        modeli 500 ornek/37 kova ile cokertiyordu (kayit: 02:50:39).
        kaydet=False GERCEK dosyaya hic dokunmali."""
        import zeka
        gercek = zeka.yol("damak.json")
        oncesi = (gercek.stat().st_mtime_ns, gercek.stat().st_size) \
            if gercek.exists() else None
        egit.egit(self.cfg, 300, seed=11, kaydet=False)
        sonrasi = (gercek.stat().st_mtime_ns, gercek.stat().st_size) \
            if gercek.exists() else None
        self.assertEqual(oncesi, sonrasi,
                         "kaydet=False gercek damak.json'a yazdi!")


if __name__ == "__main__":
    unittest.main(verbosity=2)


