#!/usr/bin/env python3
"""Kalıcı öz-hedef deposu + bayat ag_tara bayrağı düzeltmesi testleri."""

import json
import tempfile
from pathlib import Path

import oz_hedef as oh
import noral_beyn as ub
from decision import DecisionEngine


class _Drives:
    energy = 70.0
    hunger = 20.0
    pain = 0.0
    in_danger = False


def _oz(yol=None):
    return oh.OzHedef(None, _Drives(), kalici_yol=yol)


# ------------------------------------------------------------------ tohumlar
def test_tohumlar_gerekceli_ve_miras():
    z = _oz()
    h = z.kalici_hedefler()
    assert len(h) == 5
    for g in h:
        assert g["kaynak"] == "tohum" and g["miras"] is True
        assert len(g["gerekce"]) >= oh.MIN_GEREKCE and g["durum"] == "aktif"
    assert z.durum()["kalici"] == {"tohum": 5, "kendi": 0, "aktif": 5}


def test_tohum_degisikligi_bekleme_ve_gerekce():
    z = _oz()
    hid = "tohum_cevre"
    try:
        z.hedef_degistir(hid, "baslik", "Yeni başlık", "yeterince uzun gerekçe", tik=100)
        assert False, "bekleme süresi dolmadan değişmemeliydi"
    except PermissionError:
        pass
    try:
        z.hedef_degistir(hid, "baslik", "Yeni", "kısa", tik=oh.TOHUM_BEKLEME_TIK)
        assert False, "gerekçesiz değişmemeliydi"
    except ValueError:
        pass
    t = oh.TOHUM_BEKLEME_TIK + 10
    z.hedef_degistir(hid, "baslik", "Çevreni ve komşularını anla", "komşu kavramı eklendi", tik=t)
    g = next(x for x in z.kalici_hedefler() if x["id"] == hid)
    assert g["baslik"] == "Çevreni ve komşularını anla"
    assert g["degisiklikler"][-1]["eski"] == "Çevreni anla"
    # değişiklikten sonra bekleme süresi yeniden başlar
    try:
        z.hedef_degistir(hid, "durum", "beklemede", "tekrar değiştirme denemesi", tik=t + 1)
        assert False
    except PermissionError:
        pass


# ------------------------------------------------------------------ kendi hedefler
def test_kendi_hedef_kurallari():
    z = _oz()
    try:
        z.hedef_ekle("Komutları öğren", "", tik=1)
        assert False
    except ValueError:
        pass
    a = z.hedef_ekle("Debian komutlarını öğren", "bedenini tanımak için gerekli", tik=1, seviye="orta")
    b = z.hedef_ekle("debian komutlarını öğren", "aynı hedef tekrar eklenmemeli", tik=2)
    assert a == b and z.durum()["kalici"]["kendi"] == 1
    # kendi hedefte bekleme yok
    z.hedef_degistir(a, "seviye", "UZUN", "uzun vadeli olduğunu fark ettim", tik=3)
    for i in range(oh.MAX_KENDI_HEDEF - 1):
        z.hedef_ekle("hedef %d" % i, "sınır testi için gerekçe", tik=10 + i)
    try:
        z.hedef_ekle("fazla", "sınırı aşan hedef denemesi", tik=999)
        assert False
    except ValueError:
        pass


# ------------------------------------------------------------------ kalıcılık
def test_kalicilik_atomik_ve_tohum_korunur():
    with tempfile.TemporaryDirectory() as tmp:
        yol = Path(tmp) / "zeka" / "oz_hedef.json"
        z = _oz(yol)
        z.hedef_ekle("Ağı tanı", "komşuları ve cihazları ayırt etmek için", tik=5)
        t = oh.TOHUM_BEKLEME_TIK + 1
        z.hedef_degistir("tohum_beden", "gerekce", "değiştirilmiş gerekçe metni", "deneme için gerekçe", tik=t)
        assert z.kaydet() and yol.exists() and not list(yol.parent.glob("*.tmp"))
        z2 = _oz(yol)
        ids = {g["id"] for g in z2.kalici_hedefler()}
        assert "tohum_beden" in ids and any(i.startswith("kendi_") for i in ids)
        g = next(x for x in z2.kalici_hedefler() if x["id"] == "tohum_beden")
        assert g["gerekce"] == "değiştirilmiş gerekçe metni"  # tohum üzerine yazılmadı
        # koda sonradan eklenen tohum eksikse tamamlanır, mevcutlar korunur
        ham = json.loads(yol.read_text(encoding="utf-8"))
        ham["hedefler"] = [h for h in ham["hedefler"] if h["id"] != "tohum_cevre"]
        yol.write_text(json.dumps(ham), encoding="utf-8")
        z3 = _oz(yol)
        assert any(x["id"] == "tohum_cevre" for x in z3.kalici_hedefler())


def test_bozuk_dosya_yedeklenir_ve_cokmez():
    with tempfile.TemporaryDirectory() as tmp:
        yol = Path(tmp) / "oz_hedef.json"
        yol.write_text("{bozuk json", encoding="utf-8")
        z = _oz(yol)
        assert len(z.kalici_hedefler()) == 5
        assert list(Path(tmp).glob("oz_hedef.json.bozuk.*")), "bozuk dosya kanıt olarak saklanmalı"


# ------------------------------------------------------------------ yansıma
def test_yansima_sadece_oneri_uretir():
    z = _oz()
    assert z.yansima(10) is None  # vakti gelmedi
    hid = z.hedef_ekle("Deneme hedefi", "yansıma testi için gerekçe", tik=0)
    for t in (1, 2, 3):
        z.hedef_degerlendir(hid, -0.9, t, "kötü gitti")
    r = z.yansima(oh.YANSIMA_ARALIGI_TIK + 1)
    assert r is not None
    oneriler = {(o["hedef"], o["oneri"]) for o in r["oneriler"]}
    assert (hid, "gozden_gecir") in oneriler
    assert ("tohum_butunluk", "kanit_yok") in oneriler
    # öneri hiçbir şeyi değiştirmez
    assert next(x for x in z.kalici_hedefler() if x["id"] == hid)["durum"] == "aktif"
    assert z.yansima(oh.YANSIMA_ARALIGI_TIK + 2) is None  # aynı aralıkta tekrar yok


# ------------------------------------------------------------------ geriye uyum
def test_eski_arayuz_calisir():
    z = _oz()
    assert z.mevcut_hedef() is None
    # organism.py hedef_deposu'na doğrudan ekler
    z.hedef_deposu[oh.HedefSeviyesi.ACIL].append(
        {"tip": "acil_yem", "aciklama": "x", "eylem": "eat"})
    assert z.mevcut_hedef()["eylem"] == "eat"
    assert z.hedef_secildi("eat") is True and z.mevcut_hedef() is None
    d = z.durum()
    for k in ("keşif_skoru", "baglam", "trend", "hedef_sayisi", "hedef_toplam", "odul_ortalamasi"):
        assert k in d


# ------------------------------------------------------------------ bayat bayrak
class _Ust:
    def __init__(self, komutlar):
        self.komutlar = list(komutlar)
        self.beslenen = []

    def sec(self, sinyal, epsilon=0.0):
        k = self.komutlar.pop(0)
        return k, ub.KOMUT_INDEKSI[k], 1.0, "model"

    def komut_uygulanabilir_mi(self, idx, guven, kaynak):
        return True

    def komut_ayarla(self, komut, idx, sure=3):
        pass


class _Ag:
    def __init__(self):
        self.cagri = 0

    def scan_next_step(self, now):
        self.cagri += 1
        return {"ok": True, "step": 1, "probe": "nmap_tcp_ports",
                "hosts": 3, "ports": 0, "probe_reward": 1.0}


class _Jour:
    def __init__(self):
        self.kayit = []

    def log(self, kind, **kw):
        self.kayit.append((kind, kw))


def test_bayat_ag_tara_bayragi_sifirlanir():
    ust = _Ust([ub.KOMUT_AG_TARA, ub.KOMUT_YOK, ub.KOMUT_YOK, ub.KOMUT_AG_TARA])
    ag = _Ag()
    de = DecisionEngine(ust, None, None, None, None, {}, _Jour(), None, ag)
    de.sec_override([0.0], 0.0)
    assert de.ag_tara_calisti and de.ag_tara_sonuc is not None
    de.sec_override([0.0], 0.0)          # başka komut: eski sonuç GEÇERSİZ olmalı
    assert not de.ag_tara_calisti and de.ag_tara_sonuc is None
    de.sec_override([0.0], 0.0)
    assert not de.ag_tara_calisti
    de.sec_override([0.0], 0.0)          # yeniden tarama
    assert de.ag_tara_calisti and ag.cagri == 2


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
    print("öz-hedef kalıcı depo + bayat bayrak testleri: ALL PASSED")
