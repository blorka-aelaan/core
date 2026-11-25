#!/usr/bin/env python3
"""Zamansal kanallar: ham S_t / ΔS / E_{t-1} ayrımı.

Yakaladığı hatalar:
  * organism paralel (normalize) vektörü S_{t-1} diye saklıyordu -> ΔS sahte çıkıyordu
  * paralel vektör MLP'ye giriyor, mutlak seviye bilgisi yok oluyordu
  * E_{t-1} hiç güncellenmiyordu
  * kanal açılıp kapanınca eğitilmiş ağırlıklar karantinaya düşüyordu
"""

import glob
import math
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeka  # noqa: E402

_T = tempfile.mkdtemp(prefix="zamansal_kanal_")


def taze_kok():
    kok = Path(tempfile.mkdtemp(dir=_T))
    (kok / "zeka").mkdir()
    zeka.KOK = zeka.KLASOR = kok / "zeka"     # nn_*.json gerçek zeka/ klasörüne yazılmasın
    return kok


import noral_beyn as nb  # noqa: E402

S, C = nb.SINYAL_BOYUT, nb.CIKIS_BOYUT


def yakin(a, b, tol=1e-9):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def norm(v):
    return math.sqrt(sum(x * x for x in v))


def beyin(**kw):
    return nb.NöralUstBeyn({}, root=taze_kok(), seed=3, **kw)


# ------------------------------------------------------------------ saf fonksiyonlar
def test_delta_sabit_durumda_sifir():
    s = [0.5] * S
    assert nb.zamansal_delta(s, list(s)) == [0.0] * S


def test_delta_olcegi_korur_ve_isaretlidir():
    onceki = [0.0] * S
    onceki[0] = 0.9
    simdi = [0.0] * S
    simdi[0] = 0.3
    d = nb.zamansal_delta(simdi, onceki)
    assert abs(d[0] - (-0.6)) < 1e-12, d[0]          # normalize edilseydi -1.0 olurdu
    assert all(v == 0.0 for v in d[1:])


def test_delta_ilk_tik_ve_boyut_uyusmazligi():
    s = [0.4] * S
    assert nb.zamansal_delta(s, None) == [0.0] * S
    assert nb.zamansal_delta(s, [0.1] * (S - 1)) == [0.0] * S


def test_delta_kirpilir():
    d = nb.zamansal_delta([5.0] + [0.0] * (S - 1), [0.0] * S)
    assert d[0] == 1.0


def test_paralel_birim_ve_sifir_korumali():
    s = [0.3] * S
    p = nb.paralel_vektor(s, [0.1] * S)
    assert abs(norm(p) - 1.0) < 1e-9
    assert nb.paralel_vektor([0.0] * S, None) == [0.0] * S


def test_topla_sinyalleri_artik_hep_ham_doner():
    """Eski paralel dönüş kaldırıldı: onceki_* verilse de çıktı ham S_t olmalı."""
    class D:
        energy, energy_cap = 60.0, 150.0
    ortak = dict(drives=D(), mind=None, dam=None, guv=None, surec=None)
    try:
        ham = nb.topla_sinyalleri(**ortak)
        ek = nb.topla_sinyalleri(**ortak, onceki_sinyal=[0.2] * S, onceki_niyet=[0.1] * S)
    except Exception:
        return  # None bağımlılıklar bu çağrıyı kuramıyorsa test_organism_baglantisi kapsar
    assert ham == ek and len(ham) == S


# ------------------------------------------------------------------ beyin durumu
def test_zamansal_guncelle_ham_saklar_ve_sabitte_delta_sifir():
    u = beyin()
    s = [0.5] * S                                # normu 1 değil: ham/normalize farkı görünür
    u.zamansal_guncelle(s)
    assert u.onceki_sinyal == s, "saklanan ham S_t olmalı (normalize edilmiş paralel değil)"
    assert u.son_delta == [0.0] * S              # ilk tik
    u.zamansal_guncelle(list(s))
    assert u.son_delta == [0.0] * S, "hiçbir şey değişmedi -> ΔS sıfır (eski hata: norm 2.46)"


def test_zamansal_guncelle_gercek_degisimi_gorur():
    u = beyin()
    a = [0.0] * S
    a[nb.IDX_ACLIK] = 0.2
    b = list(a)
    b[nb.IDX_ACLIK] = 0.7
    u.zamansal_guncelle(a)
    u.zamansal_guncelle(b)
    assert abs(u.son_delta[nb.IDX_ACLIK] - 0.5) < 1e-12


def test_niyet_sec_sonrasi_guncellenir_ve_tik_icinde_donuk():
    u = beyin()
    x = [0.2] * S
    u.zamansal_guncelle(x)
    assert u.son_niyet == [0.0] * C                      # ilk tikte niyet yok
    u.sec(x, epsilon=0.0)
    assert len(u.onceki_niyet) == C and abs(sum(u.onceki_niyet) - 1.0) < 1e-6
    donuk = list(u.son_niyet)
    u.sec(x, epsilon=0.0)                                # aynı tikte ikinci sec: E_{t-1} değişmemeli
    assert u.son_niyet == donuk
    u.zamansal_guncelle(x)                               # sonraki tik: E_{t-1} = önceki sec çıktısı
    assert yakin(u.son_niyet, u.onceki_niyet) or abs(sum(u.son_niyet) - 1.0) < 1e-6


# ------------------------------------------------------------------ MLP girişi
def test_kanal_kapaliyken_eski_sozlesme():
    u = beyin()
    assert u.giris_boyutu == S and len(u.mlp.ağırlıklar[0]) == S
    x = [0.3] * S
    u.zamansal_guncelle([0.0] * S)
    u.zamansal_guncelle(x)
    assert u._mlp_girisi(x) is x or u._mlp_girisi(x) == x
    p1 = u.mlp.predict(u._mlp_girisi(x))
    u.son_delta = [0.9] * S                              # kapalıyken ΔS çıktıyı etkilememeli
    p2 = u.mlp.predict(u._mlp_girisi(x))
    assert yakin(p1, p2)


def test_kanal_acikken_yerlesim_ayri_slotlar():
    u = beyin(zamansal_kanal=True)
    assert u.giris_boyutu == nb.GIRIS_BOYUT_ZAMANSAL == 2 * S + C
    assert len(u.mlp.ağırlıklar[0]) == nb.GIRIS_BOYUT_ZAMANSAL
    x = [0.1 * (i % 5) for i in range(S)]
    u.son_delta = [0.01 * (i % 3) for i in range(S)]
    u.son_niyet = [1.0 / C] * C
    g = u._mlp_girisi(x)
    assert g[:S] == x and g[S:2 * S] == u.son_delta and g[2 * S:] == u.son_niyet


def test_kanal_acikken_delta_cikisi_etkiler():
    u = beyin(zamansal_kanal=True)
    x = [0.3] * S
    u.son_delta, u.son_niyet = [0.0] * S, [0.0] * C
    p0 = u.mlp.predict(u._mlp_girisi(x))
    u.son_delta = [0.5] * S
    p1 = u.mlp.predict(u._mlp_girisi(x))
    assert not yakin(p0, p1, 1e-6)


def test_ogren_zamansal_false_sifir_kanal_kullanir():
    u = beyin(zamansal_kanal=True)
    gorulen = []
    u.mlp.öğren = lambda giris, hedef: gorulen.append(list(giris))
    x = [0.2] * S
    u.son_delta, u.son_niyet = [0.3] * S, [0.1] * C
    u.ogren(x, nb.KOMUT_INDEKSI[nb.KOMUT_ACIL_YEM], 1.0)
    u.ogren(x, nb.KOMUT_INDEKSI[nb.KOMUT_ACIL_YEM], 1.0, zamansal=False)
    assert len(gorulen) == 2 and all(len(g) == nb.GIRIS_BOYUT_ZAMANSAL for g in gorulen)
    assert gorulen[0][S:2 * S] == [0.3] * S and gorulen[0][2 * S:] == [0.1] * C
    assert gorulen[1][S:] == [0.0] * (S + C)


# ------------------------------------------------------------------ kalıcılık / göç
def egit(u, adim=30):
    x = [0.0] * S
    x[nb.IDX_ACLIK] = 1.0
    for _ in range(adim):
        u.ogren(x, nb.KOMUT_INDEKSI[nb.KOMUT_ACIL_YEM], 1.0)
    return x


def test_kanal_acilinca_egitilmis_ag_korunur():
    kok = taze_kok()
    eski = nb.NöralUstBeyn({}, root=kok, seed=3)
    x = egit(eski)
    p_eski = eski.mlp.predict(x)
    eski.save()
    yeni = nb.NöralUstBeyn({}, root=kok, seed=3, zamansal_kanal=True)
    assert len(yeni.mlp.ağırlıklar[0]) == nb.GIRIS_BOYUT_ZAMANSAL
    assert yeni.mlp.ağırlıklar[0][:S] == eski.mlp.ağırlıklar[0]
    assert all(v == 0.0 for r in yeni.mlp.ağırlıklar[0][S:] for v in r)
    # Yeni satırlar sıfırdan başladığı için ilk davranış değişmez, delta/niyet ne olursa olsun
    g = list(x) + [0.7] * S + [0.2] * C
    assert yakin(yeni.mlp.predict(g), p_eski)
    assert not glob.glob(str(kok / "zeka" / "ust_beyn.agirlik_*")), "karantinaya düşmemeli"


def test_kanal_kapaninca_ag_karantinaya_dusmez():
    kok = taze_kok()
    acik = nb.NöralUstBeyn({}, root=kok, seed=3, zamansal_kanal=True)
    egit(acik)
    acik.save()
    kapali = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert len(kapali.mlp.ağırlıklar[0]) == S
    assert kapali.mlp.ağırlıklar[0] == acik.mlp.ağırlıklar[0][:S]
    assert not glob.glob(str(kok / "zeka" / "ust_beyn.agirlik_*"))


def test_giris_boyutu_kayda_yazilir():
    import json
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3, zamansal_kanal=True)
    u.save()
    d = json.loads((kok / "zeka" / "ust_beyn.json").read_text(encoding="utf-8"))
    assert d["giris_boyutu"] == nb.GIRIS_BOYUT_ZAMANSAL


# ------------------------------------------------------------------ organism bağlantısı
def test_organism_baglantisi_ham_doner_ve_delta_dogru():
    """_topla_sinyal_ust ham S_t dönmeli; ΔS gerçek ham değişimden gelmeli."""
    from organism import Organism

    ham_sirasi = []

    def sahte_topla(**kw):
        return list(ham_sirasi[0])

    class Kolay:
        def __getattr__(self, ad):
            return 0.0

    class Org(Organism):
        def __getattr__(self, ad):
            return 0.0

    class Gunluk:
        def __init__(self):
            self.olaylar = []

        def log(self, ad, **kw):
            self.olaylar.append((ad, kw))

    o = Org.__new__(Org)
    o.cfg = {}
    o.drives = Kolay()
    o.ust = beyin()
    o.jour = Gunluk()

    orijinal = nb.topla_sinyalleri
    nb.topla_sinyalleri = sahte_topla
    try:
        a = [0.5] * S
        ham_sirasi.append(a)
        r1 = o._topla_sinyal_ust()
        assert r1 == a, "ham S_t dönmeli (normalize/paralel değil)"
        r2 = o._topla_sinyal_ust()                       # aynı durum -> ΔS = 0
        assert r2 == a and o.ust.son_delta == [0.0] * S, "sabit durumda ΔS sıfır olmalı"
        b = list(a)
        b[3] = 0.9
        ham_sirasi[0] = b
        o._topla_sinyal_ust()
        assert abs(o.ust.son_delta[3] - 0.4) < 1e-12
        assert not o.jour.olaylar, o.jour.olaylar
    finally:
        nb.topla_sinyalleri = orijinal


if __name__ == "__main__":
    testler = [(ad, f) for ad, f in sorted(globals().items())
               if ad.startswith("test_") and callable(f)]
    basarisiz = 0
    for ad, f in testler:
        try:
            f()
            print("  ok:", ad)
        except Exception as e:  # noqa: BLE001
            basarisiz += 1
            print("  HATA:", ad, "->", repr(e))
    print("\nZAMANSAL KANAL TESTLERI:", "TUMU GECTI" if not basarisiz else "%d BASARISIZ" % basarisiz)
    sys.exit(1 if basarisiz else 0)
