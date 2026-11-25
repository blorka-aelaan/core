#!/usr/bin/env python3
"""Öz hedef ilerleme ölçümü + yansıma raporu testleri (sentetik durum dosyalarıyla)."""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oz_hedef as oh  # noqa: E402
import oz_hedef_olcum as oo  # noqa: E402

NOW = 1_800_000_000.0


class _Drives:
    energy, hunger, pain, in_danger = 70.0, 20.0, 0.0, False


def kok():
    r = Path(tempfile.mkdtemp(prefix="olcum_"))
    (r / "zeka").mkdir()
    (r / "uzuv").mkdir()
    return r


def yaz(r, goreli, veri):
    (r / goreli).write_text(json.dumps(veri), encoding="utf-8")


def yakin(a, b, tol=1e-3):
    return abs(a - b) <= tol


def olcer(r, komut_sayisi=100):
    return oo.HedefOlcumleri(r, clock=lambda: NOW, komut_sayisi_fn=lambda: komut_sayisi)


# ---------------------------------------------------------------- çevre
def test_cevre_olcumu():
    r = kok()
    assert olcer(r).cevre(NOW)["puan"] is None                       # dosya yok → ölçülemiyor
    yaz(r, "zeka/ag_cevre.json", {"cihazlar": {}})
    assert olcer(r).cevre(NOW)["puan"] is None                       # boş → taban bekleniyor
    veri = {"cihazlar": {"a": {"derin_tamamlandi": 5, "sinif": "pc"},
                         "b": {"derin_tamamlandi": 0, "sinif": "bilinmiyor"},
                         "c": {"derin_tamamlandi": 0, "sinif": "bilinmiyor"}},
            "son_supurme": NOW - 60, "hata_bitis": 0, "is_kuyrugu": [1, 2]}
    yaz(r, "zeka/ag_cevre.json", veri)
    o = olcer(r).cevre(NOW)
    # 0.45*(1/3) + 0.30*(1/3) + 0.25*1 = 0.5 → puan 0
    assert yakin(o["seviye"], 0.5) and yakin(o["puan"], 0.0), o
    assert o["metrikler"]["cihaz"] == 3 and o["metrikler"]["kuyruk"] == 2
    veri["hata_bitis"] = NOW + 100                                   # araç hatası bekleniyor
    yaz(r, "zeka/ag_cevre.json", veri)
    assert yakin(olcer(r).cevre(NOW)["seviye"], 0.3)
    veri["hata_bitis"], veri["son_supurme"] = 0, NOW - 10_000        # çok bayat süpürme
    yaz(r, "zeka/ag_cevre.json", veri)
    assert yakin(olcer(r).cevre(NOW)["seviye"], 0.45 / 3 + 0.30 / 3)  # tazelik 0


# ---------------------------------------------------------------- beden
def test_beden_olcumu():
    r = kok()
    assert olcer(r).beden(NOW)["puan"] is None
    yaz(r, "uzuv/asm_ogren.json", {
        "gecmis": [{"cozuldu": i < 5} for i in range(10)], "max_level": 3,
        "programs": {"p": []}, "total_tasks": 99})
    yaz(r, "zeka/komut_tehlike.json", {"help_aciklamalar": {"ls": {}, "cat": {}},
                                       "komut_ciktilari": {"ls": {}}})
    o = olcer(r, 100).beden(NOW)
    asm = 0.6 * 0.5 + 0.4 * (2 / 3)
    assert yakin(o["seviye"], 0.4 * asm + 0.6 * 0.02), o
    assert o["metrikler"]["komut_bilinen"] == 2 and o["metrikler"]["komut_toplam"] == 100
    assert o["metrikler"]["asm_ogrenilen_program"] == 1
    o2 = olcer(r, 1).beden(NOW)                                      # kapsam tavanı 1.0
    assert o2["metrikler"]["komut_kapsam"] == 1.0


# ---------------------------------------------------------------- zarar vermeme
def test_zarar_verme_olcumu():
    r = kok()
    assert olcer(r).zarar_verme(NOW)["puan"] is None
    yaz(r, "zeka/ag_cevre.json", {"olaylar": [{"tur": "yeni_cihaz", "t": NOW - 5}]})
    assert olcer(r).zarar_verme(NOW)["puan"] == 1.0
    yaz(r, "zeka/ag_cevre.json", {"olaylar": [
        {"tur": "kapsam_disi_hedef_reddedildi", "t": NOW - 100},
        {"tur": "kapsam_disi_hedef_reddedildi", "t": NOW - 200},
        {"tur": "kapsam_disi_hedef_reddedildi", "t": NOW - 200_000}]})   # eskisi sayılmaz
    o = olcer(r).zarar_verme(NOW)
    assert o["metrikler"]["kapsam_disi_girisim_24s"] == 2 and yakin(o["puan"], 2 * (1 / 3) - 1)


# ---------------------------------------------------------------- dürüstlük
def journal(r, satirlar):
    (r / "journal.jsonl").write_text("\n".join(
        s if isinstance(s, str) else json.dumps(s) for s in satirlar) + "\n", encoding="utf-8")


def test_durustluk_olcumu():
    r = kok()
    assert olcer(r).durustluk(NOW)["puan"] is None                   # journal yok
    olaylar = [{"t": NOW - 10, "kind": "ag_tara_override_calisti"} for _ in range(10)]
    ogren = [{"t": NOW - 9, "kind": "ag_tara_ogren"} for _ in range(10)]
    journal(r, olaylar + ogren + ['{"bozuk json', '{"t": 1, "kind": "x"}'])
    o = olcer(r).durustluk(NOW)
    assert o["seviye"] == 1.0 and o["metrikler"]["tarama"] == 10
    journal(r, olaylar + ogren + [{"t": NOW - 8, "kind": "ag_tara_ogren"} for _ in range(5)])
    o = olcer(r).durustluk(NOW)                                      # hayalet ödül: 15 besleme / 10 tarama
    assert yakin(o["seviye"], 0.5) and o["metrikler"]["sapma"] == 0.5
    eski = [{"t": NOW - 99_999, "kind": "ag_tara_ogren"} for _ in range(50)]
    journal(r, eski + olaylar + ogren)                               # pencere dışı eski hata sayılmaz
    assert olcer(r).durustluk(NOW)["seviye"] == 1.0
    journal(r, olaylar[:2] + ogren[:1])
    assert olcer(r).durustluk(NOW)["puan"] is None                   # yetersiz veri


# ---------------------------------------------------------------- bütünlük
def test_butunluk_olcumu():
    import noral_beyn as nb
    r = kok()
    assert olcer(r).butunluk(NOW)["puan"] is None                    # denetlenecek dosya yok
    sagl = {"agirlik_yerlesimi": nb.AGIRLIK_YERLESIMI,
            "W1": [[0.0] * nb.GIZLI_BOYUT for _ in range(nb.SINYAL_BOYUT)], "b1": [0.0] * nb.GIZLI_BOYUT,
            "W2": [[0.0] * nb.CIKIS_BOYUT for _ in range(nb.GIZLI_BOYUT)], "b2": [0.0] * nb.CIKIS_BOYUT}
    yaz(r, "zeka/ust_beyn.json", sagl)
    yaz(r, "zeka/ag_cevre.json", {"cihazlar": {}})
    o = olcer(r).butunluk(NOW)
    assert o["seviye"] == 1.0 and o["metrikler"]["agirlik_sekli_gecerli"] is True
    # canlıda görülen bozulma: W1 16x12
    yaz(r, "zeka/ust_beyn.json", dict(sagl, W1=[[0.0] * 12 for _ in range(16)], b1=[0.0] * 12))
    o = olcer(r).butunluk(NOW)
    assert o["seviye"] <= 0.3 and o["metrikler"]["agirlik_sekli_gecerli"] is False
    yaz(r, "zeka/ust_beyn.json", sagl)
    # yakın zamanda karantina kaydı: ×0.7
    karantina = r / "zeka" / "ust_beyn.agirlik_eski_duzen_1.json"
    karantina.write_text("{}", encoding="utf-8")
    olc_ = oo.HedefOlcumleri(r, clock=lambda: time.time())
    o = olc_.butunluk(time.time())
    assert yakin(o["seviye"], 0.7) and o["metrikler"]["yeni_bozulma_24s"] == 1
    # okunamayan durum dosyası
    (r / "zeka" / "ag_cevre.json").write_text("{bozuk", encoding="utf-8")
    karantina.unlink()
    o = olcer(r).butunluk(NOW)
    assert o["metrikler"]["bozuk_dosya"] == 1 and yakin(o["seviye"], 0.5)


def test_olcum_hatasi_organizmayi_dusurmez():
    class Bozuk(oo.HedefOlcumleri):
        def cevre(self, now):
            raise RuntimeError("beklenmedik")
    s = Bozuk(kok(), clock=lambda: NOW).hepsi(NOW)
    assert s["tohum_cevre"]["puan"] is None and "ölçüm hatası" in s["tohum_cevre"]["not"]
    assert set(s) == {"tohum_cevre", "tohum_beden", "tohum_zarar_verme", "tohum_durustluk", "tohum_butunluk"}


# ---------------------------------------------------------------- OzHedef entegrasyonu
class _SabitOlcer:
    def __init__(self, degerler):
        self.degerler = degerler

    def hepsi(self, now=None):
        return {hid: {"seviye": None if p is None else (p + 1) / 2, "puan": p,
                      "metrikler": {"x": 1}, "not": "sabit ölçüm"} for hid, p in self.degerler.items()}


def test_olc_aralik_kayit_ve_kalicilik():
    r = kok()
    yol = r / "zeka" / "oz_hedef.json"
    z = oh.OzHedef(None, _Drives(), kalici_yol=yol)
    z.olcum_ayarla(r, olcer=_SabitOlcer({"tohum_cevre": 0.2, "tohum_beden": None}))
    o = z.olc(0)
    assert o == {"cevre": 0.2, "beden": None}
    assert z.olc(oh.OLCUM_ARALIGI_TIK // 2) is None                  # aralık dolmadı
    assert z.olc(oh.OLCUM_ARALIGI_TIK) is not None
    h = {x["id"]: x for x in z.kalici_hedefler()}
    assert len(h["tohum_cevre"]["degerlendirmeler"]) == 2            # ölçülebilen kanıt oldu
    assert h["tohum_beden"]["degerlendirmeler"] == []                # ölçülemeyen kanıt OLMADI
    assert h["tohum_beden"]["son_olcum"]["puan"] is None
    assert z.kaydet()
    z2 = oh.OzHedef(None, _Drives(), kalici_yol=yol)
    h2 = {x["id"]: x for x in z2.kalici_hedefler()}
    assert h2["tohum_cevre"]["son_olcum"]["puan"] == 0.2 and h2["tohum_cevre"]["tur"] == "itici"
    assert h2["tohum_zarar_verme"]["tur"] == "kisit"
    assert oh.OzHedef(None, _Drives()).olc(0) is None                # ölçer ayarlanmamışsa sessiz


def test_yansima_raporu_ve_oneri_turleri():
    r = kok()
    yol = r / "zeka" / "oz_hedef.json"
    z = oh.OzHedef(None, _Drives(), kalici_yol=yol)
    z.olcum_ayarla(r, olcer=_SabitOlcer({"tohum_cevre": -0.9, "tohum_zarar_verme": -0.9,
                                         "tohum_butunluk": 0.8}))
    for i in range(4):
        z.olc(i * oh.OLCUM_ARALIGI_TIK)
    assert z.yansima(oh.YANSIMA_ARALIGI_TIK // 2) is None
    y = z.yansima(oh.YANSIMA_ARALIGI_TIK + 1)
    oner = {(o["hedef"], o["oneri"]) for o in y["oneriler"]}
    assert ("tohum_cevre", "ilerleme_dusuk") in oner                 # itici: düşük ilerleme
    assert ("tohum_zarar_verme", "gozden_gecir") in oner             # kısıt: gerçek uyarı
    assert not any(h == "tohum_butunluk" for h, _ in oner)
    assert y["rapor"] == "oz_hedef_yansima.md"
    md = (r / "zeka" / "oz_hedef_yansima.md").read_text(encoding="utf-8")
    assert "Çevreni anla" in md and "Son ölçüm: seviye" in md and "Son puanlar: -0.90" in md
    assert "Öneri: ilerleme_dusuk" in md and "Öneri: gozden_gecir" in md
    assert not list((r / "zeka").glob("*.tmp"))
    assert "Kendine karşı dürüst ol" in md and "Son ölçüm: yok" in md   # hiç ölçülmeyen de görünür


def test_eski_oz_hedef_dosyasi_yeni_alanlarla_yuklenir():
    r = kok()
    yol = r / "zeka" / "oz_hedef.json"
    z = oh.OzHedef(None, _Drives(), kalici_yol=yol)
    z.kaydet()
    ham = json.loads(yol.read_text(encoding="utf-8"))
    for h in ham["hedefler"]:
        h.pop("tur", None)                                           # eski sürümde "tur" yoktu
    yol.write_text(json.dumps(ham), encoding="utf-8")
    z2 = oh.OzHedef(None, _Drives(), kalici_yol=yol)
    assert {h["id"]: h["tur"] for h in z2.kalici_hedefler()}["tohum_butunluk"] == "kisit"


# ---------------------------------------------------------------- zaman tiki (yeniden başlatma)
def test_zaman_tiki_gercek_saate_baglidir():
    assert oh.zaman_tiki(0) == 0 and oh.zaman_tiki(59.9) == 1
    assert oh.zaman_tiki(3600 * 2) - oh.zaman_tiki(3600) == 3600 // oh.ZAMAN_TIKI_SN
    assert oh.zaman_tiki(NOW + 1) >= oh.zaman_tiki(NOW)                # asla geri gitmez
    assert oh.zaman_tiki(NOW) > oh.ESKI_TIK_SINIRI                     # eski sayaçtan ayırt edilir


def test_eski_tik_degerleri_gecisi_idempotent():
    r = kok()
    yol = r / "zeka" / "oz_hedef.json"
    oh.OzHedef(None, _Drives(), kalici_yol=yol).kaydet()
    ham = json.loads(yol.read_text(encoding="utf-8"))
    ham["son_yansima_tik"] = 2000                                      # eski sayaçtan kalma değerler
    for h in ham["hedefler"]:
        h["degistirilebilir_tik"] = 5000
    yol.write_text(json.dumps(ham), encoding="utf-8")
    z = oh.OzHedef(None, _Drives())
    z.kalici_yol_ayarla(yol)
    simdi = oh.zaman_tiki()
    bekleme = {h["id"]: h["degistirilebilir_tik"] for h in z.kalici_hedefler()}
    assert all(v >= simdi + oh.TOHUM_BEKLEME_TIK - 1 for v in bekleme.values()), bekleme
    try:                                                               # koruma yeniden başladı
        z.hedef_degistir("tohum_beden", "baslik", "Yeni ad", "yeterince uzun gerekçe", tik=simdi)
        assert False, "geçişten sonra tohum hemen değişmemeliydi"
    except PermissionError:
        pass
    z.hedef_degistir("tohum_beden", "baslik", "Yeni ad", "yeterince uzun gerekçe",
                     tik=simdi + oh.TOHUM_BEKLEME_TIK + 5)             # bekleme dolunca serbest
    z.kalici_yol_ayarla(yol)                                           # ikinci çağrı değeri kaydırmamalı
    assert {h["id"]: h["degistirilebilir_tik"] for h in z.kalici_hedefler()
            if h["id"] != "tohum_beden"} == {k: v for k, v in bekleme.items() if k != "tohum_beden"}
    assert z.yansima(simdi) is not None                                # eski son_yansima_tik=2000 → hemen vadeli


def test_yansima_ve_olcum_yeniden_baslatmalarla_calisir():
    """Gerçek vaka: organizma sık yeniden başlıyor, tik sayacı sıfırlanıyor; yansıma yine de çalışmalı."""
    r = kok()
    yol = r / "zeka" / "oz_hedef.json"
    t0 = 1_800_000_000.0
    sonuclar = []
    for calisma, now in enumerate((t0, t0 + 3 * 3600 + 120, t0 + 3 * 3600 + 180, t0 + 7 * 3600)):
        z = oh.OzHedef(None, _Drives())                                # her çalışma yeni süreç
        z.kalici_yol_ayarla(yol)
        z.olcum_ayarla(r, olcer=_SabitOlcer({"tohum_cevre": 0.5}))
        tik = z.zaman_tiki(now)                                        # organizma tik sayacı kullanılmaz
        olc = z.olc(tik, now=now)
        yans = z.yansima(tik)
        z.kaydet()
        sonuclar.append((olc is not None, yans is not None))
    # 1. çalışma: ilk ölçüm + ilk yansima; 2. (3 sa sonra): ikisi de; 3. (1 dk sonra): yansıma YOK;
    # 4. (4 sa sonra): ikisi de
    assert sonuclar[0] == (True, True), sonuclar
    assert sonuclar[1] == (True, True), sonuclar
    assert sonuclar[2][1] is False, sonuclar
    assert sonuclar[3] == (True, True), sonuclar
    assert (r / "zeka" / "oz_hedef_yansima.md").exists()


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            print("ok", ad)
    print("öz hedef ölçüm testleri: ALL PASSED")
