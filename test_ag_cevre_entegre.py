#!/usr/bin/env python3
"""ag_cevre ↔ ag_beyin ↔ noral_beyn ↔ decision entegrasyon testleri (sahte araçlarla)."""

import json
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeka  # noqa: E402

_GECICI = tempfile.mkdtemp(prefix="cevre_entegre_")
zeka.KOK = zeka.KLASOR = Path(_GECICI)          # nn_*.json gerçek zeka/ klasörüne yazılmasın
Path(_GECICI).mkdir(exist_ok=True)

import ag_beyin as agb  # noqa: E402
import ag_cevre as ac  # noqa: E402
import noral_beyn as nb  # noqa: E402
from decision import DecisionEngine  # noqa: E402
from test_ag_cevre import Saat, Sahte, arp_satir  # noqa: E402


def kapsam_yaz(root: Path, **ek):
    ayar = {"acik": True, "izin_aglari": ["192.168.1.0/24"], "nmap_hiz_tavan": 100}
    ayar.update(ek)
    (root / "ag_kapsam.json").write_text(json.dumps(ayar), encoding="utf-8")


def ag_kur(root: Path, **kapsam_ek):
    kapsam_yaz(root, **kapsam_ek)
    saat, sahte = Saat(), Sahte()
    ag = agb.AgBeyin(root, runner=sahte, clock=saat)
    ag._cevre = ac.CevreIzleyici(
        root, runner=sahte, clock=saat, kapsam_fn=ag._scope, ayar_fn=ag._kapsam_ayar,
        arac_bul=lambda ad: "/usr/bin/" + ad, arka_planda=False)
    return ag, sahte, saat


class _Ust(nb.NöralUstBeyn):
    """Ağır kurulum olmadan test için hafif üst beyin."""

    def __init__(self, ag=None):
        self.cfg = {}
        self.rng = random.Random(1)
        self.mlp = nb.NöralBeyn("test_entegre", [nb.SINYAL_BOYUT, nb.GIZLI_BOYUT, nb.CIKIS_BOYUT], seed=1)
        self.ag_beyin = ag
        self.epsilon = 0.0
        self.guven_esigi = 0.30
        self.marj_olcek = 0.15
        self.dogrulama_esigi = 0.35
        self.dogrulama = [0.0] * nb.CIKIS_BOYUT
        self.dogrulama_bağlam = {}
        self.redd_cooldown = [0] * nb.CIKIS_BOYUT
        self.redd_serisi = [0] * nb.CIKIS_BOYUT
        self.secim_sayilari = [0] * nb.CIKIS_BOYUT
        self.reddedilen_sayilari = [0] * nb.CIKIS_BOYUT
        self.odul_gecmisi = []
        self.samples = self.tik = 0
        self.eylem_bilgi = {}
        self._son_scan_odulu = 0.0
        self._son_scan_tik = 0
        self._scan_sinyal = None
        self.yakalanan = []

    def ogren(self, sinyal_vektor, komut_indeksi, odul, keşif=False):
        self.yakalanan.append((list(sinyal_vektor), komut_indeksi, odul))

    def eylem_ogren(self, *a, **k):
        pass


AG_IDX = nb.KOMUT_INDEKSI[nb.KOMUT_AG_TARA]


def test_cevre_modu_ayardan_gelir_ve_anlik_degisir():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        kapsam_yaz(root)
        ag = agb.AgBeyin(root)
        assert ag.cevre_modu is False                    # varsayılan: klasik
        kapsam_yaz(root, cevre_modu=True)
        os.utime(root / "ag_kapsam.json", (1, 2_000_000_000))
        assert ag.cevre_modu is True                     # restart gerekmeden
        assert agb.AgBeyin(root, cevre_modu=False).cevre_modu is False


def test_ag_tara_yalnizca_is_varken_uygun():
    with tempfile.TemporaryDirectory() as tmp:
        ag, sahte, saat = ag_kur(Path(tmp), cevre_modu=True)
        sahte.arp = arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
        ust = _Ust(ag)
        x = [0.0] * nb.SINYAL_BOYUT
        assert ust.komut_uygun_mu(AG_IDX, x) is True     # ilk süpürme vadeli
        for _ in range(40):                              # tüm işleri bitir
            saat.t += 15
            ag.scan_next_step(saat.t)
            if ag.next_due_in(saat.t) > 0:
                break
        assert ust.komut_uygun_mu(AG_IDX, x) is False    # yapılacak iş yok → maskeli
        assert nb.NöralUstBeyn.uygun_maske(ust, x)[AG_IDX] is False
        saat.t += ac.VARSAYILAN_AYAR["arp_aralik_sn"] + 1
        assert ust.komut_uygun_mu(AG_IDX, x) is True     # süpürme vakti gelince yeniden uygun
        assert _Ust(None).komut_uygun_mu(AG_IDX, x) is True   # ag_beyin yoksa eski davranış


def test_karar_baglaminda_ogrenir_ve_sessiz_tarama_cezalanir():
    ust = _Ust()
    bag = [0.1 * (i % 5) for i in range(nb.SINYAL_BOYUT)]
    ust.scan_sinyali_kaydet(bag)
    ust.scan_odulu_besle(0.6, 10)
    assert ust.yakalanan[-1][0] == bag and ust.yakalanan[-1][1] == AG_IDX
    ust.scan_odulu_besle(-0.02, 11)                      # kayıtlı sinyal yok → sıfır vektör
    assert ust.yakalanan[-1][0] == [0.0] * nb.SINYAL_BOYUT and ust._scan_sinyal is None


class _Jour:
    def __init__(self):
        self.kayit = []

    def log(self, kind, **kw):
        self.kayit.append((kind, kw))

    def tur(self, kind):
        return [kw for k, kw in self.kayit if k == kind]


class _UstSec:
    """DecisionEngine için sahte üst beyin: hep ag_tara seçer, sinyali kaydeder."""

    def __init__(self):
        self.sinyaller = []

    def sec(self, sinyal, epsilon=0.0):
        return nb.KOMUT_AG_TARA, AG_IDX, 1.0, "model"

    def komut_uygulanabilir_mi(self, idx, guven, kaynak):
        return True

    def komut_ayarla(self, komut, idx, sure=3):
        pass

    def scan_sinyali_kaydet(self, sinyal):
        self.sinyaller.append(list(sinyal))


def test_decision_olaylari_ve_sessizligi_gunlukler():
    with tempfile.TemporaryDirectory() as tmp:
        ag, sahte, saat = ag_kur(Path(tmp), cevre_modu=True)
        sahte.arp = (arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
                     + arp_satir("192.168.1.1", "de:ad:be:ef:00:99"))      # IP-MAC çakışması
        jour, ust = _Jour(), _UstSec()
        de = DecisionEngine(ust, None, None, None, None, {}, jour, None, ag)
        sinyal = [0.5] * nb.SINYAL_BOYUT
        saat.t += 1
        de.sec_override(sinyal, 0.0)
        assert de.ag_tara_calisti and ust.sinyaller[-1] == sinyal
        assert jour.tur("ag_tara_override_calisti") and not jour.tur("ag_tara_override_sessiz")
        olay = jour.tur("ag_cevre_olay")
        assert olay and olay[0]["tur"] == "ip_mac_cakisma" and "olay_t" in olay[0]
        # iş bitene kadar sür, sonra sessizlik
        for _ in range(30):
            saat.t += 15
            de.sec_override(sinyal, 0.0)
        n_cagri = len(sahte.cagrilar)
        saat.t += 20
        de.sec_override(sinyal, 0.0)
        assert jour.tur("ag_tara_override_sessiz")
        assert de.ag_tara_sonuc["probe_reward"] < 0 and len(sahte.cagrilar) == n_cagri


def test_summary_pasif_trafik_anahtarlarinda_cokmez():
    with tempfile.TemporaryDirectory() as tmp:
        ag, sahte, saat = ag_kur(Path(tmp), cevre_modu=True)
        ag.learn_traffic({"local_port": 22, "remote_ip": "192.168.1.5", "remote_port": 50000,
                          "protocol": "tcp", "state": "ESTABLISHED"})
        ozet = ag.summary()
        assert ozet["device_count"] == 0 and ozet["cevre"]["cihaz"] == 0
        sahte.arp = arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
        ag.scan_next_step(saat.t)
        assert ag.summary()["cevre"]["cihaz"] == 1
        assert ag.data["last_scan"]["probe"] == "arp_supurme"
        # çevre modunda günlük 5 tarama sınırı devreye girmez; iş yoksa sessiz
        assert ag.cevre_baglanti_gozlemi({"remote_ip": "8.8.8.8", "local_port": 22,
                                          "remote_port": 50000}) == []


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            print("ok", ad)
    print("ag_cevre entegrasyon testleri: ALL PASSED")
