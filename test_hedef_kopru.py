#!/usr/bin/env python3
"""Öz hedef → komut seçimi köprüsü testleri."""

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeka  # noqa: E402

_T = Path(tempfile.mkdtemp(prefix="kopru_"))
zeka.KOK = zeka.KLASOR = _T                    # nn_*.json gerçek zeka/ klasörüne yazılmasın

import hedef_kopru as hk  # noqa: E402
import noral_beyn as nb  # noqa: E402
import oz_hedef as oh  # noqa: E402
from decision import DecisionEngine  # noqa: E402

KOMUTLAR = list(nb.KOMUTLAR)
IDX = {k: i for i, k in enumerate(KOMUTLAR)}
NOW = 1_800_000_000.0


class Saat:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class _D:
    energy, hunger, pain, in_danger = 70.0, 20.0, 0.0, False


def oz_kur(seviyeler, ayarlar=None, taze=True):
    """Ölçülmüş seviyelerle öz hedef (ölçüm zamanı NOW)."""
    z = oh.OzHedef(None, _D())
    for hid, sev in seviyeler.items():
        z.kalici.hedefler[hid]["son_olcum"] = {
            "tik": 1, "zaman": NOW if taze else NOW - 10 * 3600, "seviye": sev,
            "puan": None if sev is None else 2 * sev - 1, "metrikler": {}, "not": ""}
    if ayarlar is not None:
        z.kalici.ayarlar = ayarlar
    return z


def kopru_kur(seviyeler, saat=None, ayarlar=None, taze=True, gecmis_sn=10_000):
    saat = saat or Saat()
    z = oz_kur(seviyeler, ayarlar, taze)
    k = z.kopru_olustur(KOMUTLAR)
    k.clock = saat
    for ad in k.son_secim:                      # başlangıç soğumasını geçmiş say
        k.son_secim[ad] = saat() - gecmis_sn
    return k, z, saat


def hepsi_acik():
    return [True] * len(KOMUTLAR)


# ---------------------------------------------------------------- modül mantığı
def test_itici_cekim_aciliyetle_orantili():
    k, _, _ = kopru_kur({"tohum_beden": 0.2, "tohum_cevre": 0.9})
    asm = k.komut_bias("asm_ogren")["bias"]
    assert abs(asm - 0.10 * 0.8) < 1e-4, asm                        # azami × katsayı × (1-0.2)
    ag = k.komut_bias("ag_tara")["bias"]
    assert abs(ag - 0.10 * 1.0 * (1 - 0.9)) < 1e-4, ag              # doymuş hedef az çeker
    assert asm > ag > 0
    k2, _, _ = kopru_kur({"tohum_beden": 0.9})
    assert k2.komut_bias("asm_ogren")["bias"] < asm                 # seviye arttıkça çekim düşer


def test_yuksek_etkili_komutlar_asla_olumlu_cekim_almaz():
    k, _, _ = kopru_kur({"tohum_beden": 0.0, "tohum_cevre": 0.0, "tohum_butunluk": 1.0,
                         "tohum_zarar_verme": 1.0})
    for ad in hk.YUKSEK_ETKILI:
        assert k.komut_bias(ad)["bias"] <= 0.0, ad
    k2, _, _ = kopru_kur({"tohum_beden": 0.0, "tohum_butunluk": 0.1, "tohum_zarar_verme": 0.1})
    for ad in hk.YUKSEK_ETKILI:
        assert k2.komut_bias(ad)["bias"] < 0.0, ad                  # vetoda olumsuz


def test_kisit_vetosu_ve_destegi():
    k, _, _ = kopru_kur({"tohum_cevre": 0.0, "tohum_zarar_verme": 0.2, "tohum_butunluk": 0.1})
    ag = k.komut_bias("ag_tara")
    assert ag["bias"] < 0 and "zarar_verme:veto" in ag["etkenler"]    # çekimi geçecek kadar güçlü veto
    assert k.komut_bias("kod_duzenle")["bias"] < 0
    assert k.komut_bias("guvenli_mod")["bias"] > 0 and k.komut_bias("kisitla_dosya")["bias"] > 0
    assert "butunluk:destek" in k.komut_bias("guvenli_mod")["etkenler"]
    # eşiğin üstünde veto yok
    k2, _, _ = kopru_kur({"tohum_zarar_verme": 0.9, "tohum_butunluk": 0.9})
    assert k2.komut_bias("kod_duzenle")["bias"] == 0 and k2.komut_bias("guvenli_mod")["bias"] == 0


def test_soguma_ve_baslangic_korumasi():
    saat = Saat()
    k, _, _ = kopru_kur({"tohum_beden": 0.0}, saat=saat)
    tam = k.komut_bias("asm_ogren")["bias"]
    k.secim_bildir("asm_ogren")
    assert k.komut_bias("asm_ogren")["bias"] == 0.0                 # seçildi: hemen sıfır
    saat.t += hk.YENILENME_SN["asm_ogren"] / 2
    assert abs(k.komut_bias("asm_ogren")["bias"] - tam / 2) < 1e-4  # doğrusal toparlanma
    saat.t += hk.YENILENME_SN["asm_ogren"]
    assert abs(k.komut_bias("asm_ogren")["bias"] - tam) < 1e-4
    # yeni kurulan köprü (yeniden başlatma): hemen çekim yok
    z = oz_kur({"tohum_beden": 0.0})
    yeni_saat = Saat()
    yeni = z.kopru_olustur(KOMUTLAR, clock=yeni_saat)
    assert yeni.komut_bias("asm_ogren")["bias"] == 0.0              # kurulur kurulmaz çekim yok
    yeni_saat.t += hk.YENILENME_SN["asm_ogren"]
    assert yeni.komut_bias("asm_ogren")["bias"] > 0.0               # soğuma dolunca çekim başlar
    assert k.secim_sayilari["asm_ogren"] == 1


def test_olcum_yok_veya_bayat_ise_veto_yok_ve_ort_cekim():
    k, _, _ = kopru_kur({"tohum_zarar_verme": 0.0, "tohum_butunluk": 0.0}, taze=False)
    assert k.komut_bias("ag_tara")["bias"] > 0                      # bayat ölçüm veto etmez
    assert abs(k.komut_bias("asm_ogren")["bias"] - 0.10 * hk.BILINMEYEN_ACILIYET) < 1e-4
    assert k.komut_bias("kod_duzenle")["bias"] == 0.0
    k2, _, _ = kopru_kur({})                                        # hiç ölçüm yok
    assert abs(k2.komut_bias("asm_ogren")["bias"] - 0.10 * hk.BILINMEYEN_ACILIYET) < 1e-4


def test_maske_ve_kapatma_anahtari():
    k, _, _ = kopru_kur({"tohum_beden": 0.0})
    maske = hepsi_acik()
    maske[IDX["asm_ogren"]] = False
    maske[IDX[nb.KOMUT_YOK]] = True
    b = k.bias(maske)
    assert IDX["asm_ogren"] not in b and IDX[nb.KOMUT_YOK] not in b   # maskeli/pasif komuta dokunmaz
    kapali, _, _ = kopru_kur({"tohum_beden": 0.0}, ayarlar={"kopru": {"acik": False}})
    assert kapali.bias(hepsi_acik()) == {} and kapali.komut_bias("asm_ogren")["bias"] == 0
    sinirli, _, _ = kopru_kur({"tohum_beden": 0.0}, ayarlar={"kopru": {"azami_bias": 9.0}})
    assert sinirli.ayar()["azami_bias"] == hk.AZAMI_BIAS_SINIRI     # aşırı ayar kırpılır
    bozuk, _, _ = kopru_kur({"tohum_beden": 0.0}, ayarlar={"kopru": {"azami_bias": "x", "acik": 5}})
    assert bozuk.ayar() == hk.VARSAYILAN_AYAR                       # bozuk ayar varsayılana düşer


# ---------------------------------------------------------------- ayar kalıcılığı
def test_ayarlar_kalicidir():
    yol = _T / "ayar" / "oz_hedef.json"
    z = oh.OzHedef(None, _D(), kalici_yol=yol)
    z.kalici.ayarlar = {"kopru": {"acik": False}}
    assert z.kaydet()
    z2 = oh.OzHedef(None, _D(), kalici_yol=yol)
    assert z2.kopru_ayar() == {"acik": False}
    assert z2.kopru_olustur(KOMUTLAR).ayar()["acik"] is False


# ---------------------------------------------------------------- üst beyin entegrasyonu
def duz_ust(kopru=None):
    kok = Path(tempfile.mkdtemp(dir=_T))
    (kok / "zeka").mkdir()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    # tüm ağırlıklar sıfır → çıkışlar eşit → olasılıklar düz (kopru kararı belirleyebilir)
    u.mlp.ağırlıklar = [[[0.0] * nb.GIZLI_BOYUT for _ in range(nb.SINYAL_BOYUT)],
                        [[0.0] * nb.CIKIS_BOYUT for _ in range(nb.GIZLI_BOYUT)]]
    u.mlp.çeşitler = [[0.0] * nb.GIZLI_BOYUT, [0.0] * nb.CIKIS_BOYUT]
    u.mlp._transpoze_güncelle()
    u.hedef_kopru = kopru
    return u


def test_sec_kopru_kazanani_degistirir():
    x = [0.0] * nb.SINYAL_BOYUT
    taban = duz_ust().sec(x, epsilon=0.0)
    k, _, _ = kopru_kur({"tohum_beden": 0.0})
    u = duz_ust(k)
    komut, idx, guven, kaynak = u.sec(x, epsilon=0.0)
    assert komut == "asm_ogren", (komut, taban)                     # düz olasılıkta köprü kazanır
    assert taban[0] != "asm_ogren"
    assert u.last_hedef_kopru and u.last_hedef_kopru[idx] > 0
    # köprü kapalı ya da yok: davranış değişmez
    assert duz_ust(None).sec(x, epsilon=0.0)[0] == taban[0]
    kapali, _, _ = kopru_kur({"tohum_beden": 0.0}, ayarlar={"kopru": {"acik": False}})
    assert duz_ust(kapali).sec(x, epsilon=0.0)[0] == taban[0]
    # soğumadaki komut çekilmez (kazanan başka bir hedefin çektiği komut olabilir)
    k.secim_bildir("asm_ogren")
    assert duz_ust(k).sec(x, epsilon=0.0)[0] != "asm_ogren"


def test_sec_kopru_hatasi_karari_bozmaz():
    class Bozuk:
        def bias(self, maske):
            raise RuntimeError("beklenmedik")
    x = [0.0] * nb.SINYAL_BOYUT
    taban = duz_ust().sec(x, epsilon=0.0)
    assert duz_ust(Bozuk()).sec(x, epsilon=0.0)[0] == taban[0]


def test_sec_kesif_yolunda_kopru_etkisiz():
    k, _, _ = kopru_kur({"tohum_beden": 0.0})
    u = duz_ust(k)
    x = [0.0] * nb.SINYAL_BOYUT
    u.sec(x, epsilon=1.0)                                           # saf keşif
    assert u.last_hedef_kopru is None


# ---------------------------------------------------------------- decision entegrasyonu
class _Jour:
    def __init__(self):
        self.kayit = []

    def log(self, kind, **kw):
        self.kayit.append((kind, kw))

    def tur(self, kind):
        return [kw for k, kw in self.kayit if k == kind]


def test_decision_sec_bildirir_ve_gunluklar():
    k, _, saat = kopru_kur({"tohum_beden": 0.0})

    class Ust:
        hedef_kopru = k
        last_hedef_kopru = {IDX["asm_ogren"]: 0.08}

        def sec(self, sinyal, epsilon=0.0):
            return "asm_ogren", IDX["asm_ogren"], 0.9, "model"

        def komut_uygulanabilir_mi(self, idx, guven, kaynak):
            return True

        def komut_ayarla(self, komut, idx, sure=3):
            pass

    jour = _Jour()
    de = DecisionEngine(Ust(), None, None, None, None, {}, jour, None, None)
    ncek = k.komut_bias("asm_ogren")["bias"]
    k.komut_bias("asm_ogren")
    k.bias(hepsi_acik())                                            # aciklama dolsun
    de.sec_override([0.0] * nb.SINYAL_BOYUT, 0.0)
    ol = jour.tur("oz_hedef_kopru")
    assert len(ol) == 1 and ol[0]["komut"] == "asm_ogren" and ol[0]["bias"] == 0.08
    assert "beden:+1.00" in ol[0]["etkenler"]
    assert k.secim_sayilari["asm_ogren"] == 1                       # soğuma başladı
    assert k.komut_bias("asm_ogren")["bias"] == 0.0 and ncek > 0


def test_decision_kopru_olmadan_ve_hatada_calisir():
    class Ust:
        def sec(self, sinyal, epsilon=0.0):
            return "ag_tara", IDX["ag_tara"], 0.9, "model"

        def komut_uygulanabilir_mi(self, idx, guven, kaynak):
            return True

        def komut_ayarla(self, komut, idx, sure=3):
            pass

    jour = _Jour()
    de = DecisionEngine(Ust(), None, None, None, None, {}, jour, None, None)
    de.sec_override([0.0], 0.0)                                     # kopru yok: sessiz
    assert not jour.tur("oz_hedef_kopru")

    class BozukKopru:
        def secim_bildir(self, komut):
            raise RuntimeError("x")

        def aciklama(self, komut):
            return {}

    u = Ust()
    u.hedef_kopru, u.last_hedef_kopru = BozukKopru(), {IDX["ag_tara"]: 0.1}
    de2 = DecisionEngine(u, None, None, None, None, {}, jour, None, None)
    de2.sec_override([0.0], 0.0)
    assert jour.tur("oz_hedef_kopru_hata")                          # hata günlüğe düşer, akış sürer


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            print("ok", ad)
    print("öz hedef köprüsü testleri: ALL PASSED")
