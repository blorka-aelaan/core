"""test_olum.py — olum.py mekaniklerini düz assert'lerle doğrular.

  python3 test_olum.py

Bu testler SEMANTİKTEN bağımsız değildir — aksine, kararlaştırılan doktrini
kilitlerler: (a) iz ASLA öz değildir (ezber crutch'u), (b) strateji
öğrenilmez, kategoriden TÜRETİLİR (STRATEJI haritası), (c) her katalog
kaydının strateji etiketi haritayla TUTARLI olmalı.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import olum as O


def test_katalog_butunluk():
    adlar = [k["ad"] for k in O.KATALOG]
    assert len(adlar) == len(set(adlar)), "yinelenen katalog adı"
    for k in O.KATALOG:
        assert k["kategori"] in O.KATEGORILER, k["ad"]
        assert k["sinyal"] in O.SINYALLER, k["ad"]
        assert k["kaynak"] in O.KAYNAKLAR, k["ad"]
        assert k["kim"] in O.KIMLER, k["ad"]
        assert k["siddet"] in O.SIDDETLER, k["ad"]
        assert k["belirti"] in O.BELIRTILER, k["ad"]
        assert k["onbelirti"] in O.ONBELIRTILER, k["ad"]
        assert k.get("onlem"), k["ad"]
        assert k.get("mekanizma"), k["ad"]


def test_strateji_doktrinle_tutarli():
    # her katalog etiketi = kategorisinin harita stratejisi
    for k in O.KATALOG:
        assert k["strateji"] == O.STRATEJI[k["kategori"]], \
            "%s: %s != %s" % (k["ad"], k["strateji"], O.STRATEJI[k["kategori"]])
    # harita doktrinin kendisi: yazılım kaçınır, fizik/silikon azaltır, dış sinirlar
    assert O.STRATEJI["yazilimsal"] == "kacin"
    assert O.STRATEJI["fiziki"] == "azalt"
    assert O.STRATEJI["donanimsal"] == "azalt"
    assert O.STRATEJI["dis"] == "sinirla"


def test_iz_asla_oz_degil():
    # iz, OZ_ALANLAR'da olmamalı; gozlem_uret ve ozellikler iz üretmemeli
    assert "iz" not in O.OZ_ALANLAR
    g = O.gozlem_uret("SEGFAULT", random.Random(0), kayip=0.0)
    assert "iz" not in g
    assert all(not f.startswith("iz=") for f in O.ozellikler(g))


def test_zincir_oncul_biliniyor():
    for k in O.KATALOG:
        for oc in k["oncul"]:
            assert oc in O._ADI or oc in O.ONCUL_DURUM, \
                "%s → bilinmeyen öncül %s" % (k["ad"], oc)


def test_zincir_oncul_adimi():
    z = O.zincir("ZAMAN_ASIMI")
    assert "ZAMAN_ASIMI" in z and "CPU_THROTTLE" in z, z
    assert O.zincir("RAM_ECC_HATASI") == ["RAM_ECC_HATASI"]


def test_ozellikler_eksik_alan_atlanir():
    feats = O.ozellikler({"sinyal": "SIGKILL", "iz": None, "kim": "cekirdek"})
    assert "sinyal=SIGKILL" in feats and "kim=cekirdek" in feats


def test_gozlem_uret_kayip():
    g0 = O.gozlem_uret("SEGFAULT", random.Random(0), kayip=0.0)
    assert g0.get("sinyal") == "SIGSEGV" and g0.get("belirti") == "catlanma"
    # kayip=1.0 → rng.random() < 1.0 her zaman → tüm alanlar düşer
    assert O.gozlem_uret("SEGFAULT", random.Random(0), kayip=1.0) == {}
    assert O.gozlem_uret("YOK_BOYLE", random.Random(0)) == {}


def test_onlem_mekanizma_dolu():
    for k in O.KATALOG:
        assert O.onlem(k["ad"]) == k["onlem"]
        assert O.mekanizma(k["ad"]) == k["mekanizma"]


def test_olum_ogren_tahmin_et():
    m = O.Olum(agirlik=1.5)
    # tek bir net sinyal öbeği ver → o kategoriye yapışsın
    for _ in range(50):
        m.ogren(["kim=donanim", "belirti=bozulma"], "donanimsal")
        m.ogren(["kim=kullanici", "sinyal=SIGTERM"], "dis")
    kat, skor = m.kategori_tahmin(["kim=donanim", "belirti=bozulma"])
    assert kat == "donanimsal", (kat, skor)
    kat2, _ = m.kategori_tahmin(["kim=kullanici", "sinyal=SIGTERM"])
    assert kat2 == "dis"
    assert set(skor) == set(O.KATEGORILER), skor


def test_strateji_kategoriden_turetilir():
    # strateji bağımsız bir başlık değil: kategori → harita
    assert O.strateji_kategori("yazilimsal") == "kacin"
    assert O.strateji_kategori("fiziki") == "azalt"
    assert O.strateji_kategori("donanimsal") == "azalt"
    assert O.strateji_kategori("dis") == "sinirla"
    # tani(): tahmin edilen kategori neyse strateji ondan gelir
    m = O.Olum(agirlik=2.0)
    for _ in range(50):
        m.ogren(["kim=cekirdek", "belirti=catlanma"], "yazilimsal")
    kat, strateji, _ = m.tani({"kim": "cekirdek", "belirti": "catlanma"})
    assert kat == "yazilimsal" and strateji == "kacin", (kat, strateji)


def test_strateji_of_katalog_etiketi():
    assert O.strateji_of("SEGFAULT") == "kacin"
    assert O.strateji_of("RAM_ECC_HATASI") == "azalt"
    assert O.strateji_of("KULLANICI_KILL") == "sinirla"
    assert O.strateji_of("YOK") == ""


def test_tani_uc_deger_doner():
    m = O.Olum()
    assert m.load(), "olum.json yok — önce: python3 egit_olum.py"
    kat, strateji, skor = m.tani({"sinyal": "SIGKILL", "kaynak": "bellek",
                                  "kim": "cekirdek", "siddet": "kademeli"})
    assert kat in O.KATEGORILER, kat
    assert strateji == O.STRATEJI[kat]
    assert set(skor) == set(O.KATEGORILER), skor


def test_save_load_roundtrip():
    m = O.Olum(agirlik=0.9)
    m.ogren(["kim=fizik"], "fiziki")
    m.ogren(["kim=donanim"], "donanimsal")
    yol = Path("/tmp/_olum_test.json")
    m.save(yol)
    m2 = O.Olum()
    assert m2.load(yol), "load başarısız"
    assert m2.agirlik == 0.9 and m2.ornek == m.ornek
    assert m2.sayac == m.sayac and m2.toplam == m.toplam
    assert m2.kategori_tahmin(["kim=fizik"])[0] == \
        m.kategori_tahmin(["kim=fizik"])[0]
    yol.unlink()


def main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    gecen = 0
    for ad, fn in tests:
        try:
            fn()
            gecen += 1
            print("  [GEÇTİ] %s" % ad)
        except AssertionError as e:
            print("  [KALDI] %s → %s" % (ad, e))
        except Exception as e:  # noqa: BLE001
            print("  [HATA]  %s → %r" % (ad, e))
    print("%d/%d test geçti" % (gecen, len(tests)))
    return 0 if gecen == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())

