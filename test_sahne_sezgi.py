#!/usr/bin/env python3
"""Sahne anahtarı (z-skor + çok ölçekli Δ), sahne hafızası, sezgi ve ΔS sürprizi.

Yakaladığı hatalar (gerçek journal ölçümünden):
  * ham kosinüs her çifti ~1.0 gösteriyordu (ortak pozitif taban)
  * komut başına tek centroid: en fazla 12 prototip, olumlu/olumsuz durum birbirine eriyordu
  * sezgi ödülü sonradan süslüyor ve hafızaya geri yazılıyordu (geri besleme döngüsü)
  * tek kare ΔS ~5e-5: ağa görünmezdi
  * E_{t-1} uygulanan eylem değil softmax dağılımıydı; tahmin hatası yoktu
  * kavram hafızası diske yazılmıyordu
"""

import math
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeka  # noqa: E402

_T = tempfile.mkdtemp(prefix="sahne_sezgi_")


def taze_kok():
    kok = Path(tempfile.mkdtemp(dir=_T))
    (kok / "zeka").mkdir()
    zeka.KOK = zeka.KLASOR = kok / "zeka"
    return kok


import noral_beyn as nb  # noqa: E402

S, C, SB = nb.SINYAL_BOYUT, nb.CIKIS_BOYUT, nb.SAHNE_BOYUT
YOK = nb.KOMUT_INDEKSI[nb.KOMUT_YOK]


def beyin(**cfg):
    return nb.NöralUstBeyn(cfg, root=taze_kok(), seed=3)


def sinyal(rng, taban=0.7, oynak=(0, 1, 2, 3, 4, 5), genlik=0.2):
    """Pozitif ortak tabanlı sinyal: sadece birkaç boyut oynar (gerçek journal'a benzer)."""
    v = [taban] * S
    for i in oynak:
        v[i] = taban + rng.uniform(-genlik, genlik)
    return v


# ------------------------------------------------------------------ Welford
def test_welford_isinma_sifir_sonra_ortalama_etrafinda():
    w = nb.WelfordNormalizer(S)
    rng = random.Random(1)
    for _ in range(w.isinma - 1):
        assert w.guncelle_ve_donustur(sinyal(rng)) == [0.0] * S
    for _ in range(200):
        z = w.guncelle_ve_donustur(sinyal(rng))
    assert all(abs(v) <= 3.0 for v in z)
    # ölü boyut (sabit 0.7) z=0
    assert z[10] == 0.0


def test_welford_kosinus_ortak_tabani_yok_eder():
    rng = random.Random(2)
    ham = [sinyal(rng) for _ in range(300)]
    w = nb.WelfordNormalizer(S)
    zs = [w.guncelle_ve_donustur(v) for v in ham]
    ham_c = sorted(nb.kosinus_benzerligi(ham[i], ham[i + 50]) for i in range(100, 250))
    z_c = sorted(nb.kosinus_benzerligi(zs[i], zs[i + 50]) for i in range(100, 250))
    assert ham_c[len(ham_c) // 2] > 0.99, "ham kosinüs ortak tabana yapışıyor"
    assert abs(z_c[len(z_c) // 2]) < 0.35, "z-skor ayrıştırmalı"


def test_welford_donustur_mutasyonsuz_ve_nan_guvenli():
    w = nb.WelfordNormalizer(S)
    rng = random.Random(3)
    for _ in range(50):
        w.guncelle_ve_donustur(sinyal(rng))
    n, mean = w.n, list(w.mean)
    w.donustur(sinyal(rng))
    assert w.n == n and w.mean == mean
    kotu = sinyal(rng)
    kotu[0] = float("nan")
    z = w.guncelle_ve_donustur(kotu)
    assert all(math.isfinite(v) for v in z)
    assert w.donustur([0.0] * (S - 1)) == [0.0] * S          # boyut uyuşmazlığı


def test_welford_unutmali_pencere_kaymayi_izler():
    w = nb.WelfordNormalizer(1, pencere=50, isinma=5)
    rng = random.Random(4)
    for _ in range(300):
        w.guncelle_ve_donustur([0.2 + rng.uniform(-0.01, 0.01)])
    for _ in range(300):
        z = w.guncelle_ve_donustur([0.8 + rng.uniform(-0.01, 0.01)])
    assert abs(w.mean[0] - 0.8) < 0.05 and abs(z[0]) < 1.5


# ------------------------------------------------------------------ çok ölçekli Δ
def test_delta_ema_yavas_surusu_tek_kareden_cok_daha_gorunur():
    # Yavaş, sabit eğim: tek kare farkı mikroskobik, EMA_hızlı−EMA_yavaş eğimin BAŞLANGICINDA
    # belirgin. Δ "değişim"dir: rejim yeni normal olunca söner, seviyeyi z taşır (iş bölümü).
    tr = nb.SahneTakipcisi()
    rng = random.Random(5)
    tek, ema, z_son = [], [], 0.0
    onceki = None
    for t in range(200):
        v = [0.5] * S
        v[0] = 0.5 + (0.0002 * max(0, t - 100)) + rng.uniform(-1e-5, 1e-5)   # t>100: yavaş artış
        z, d, _ = tr.guncelle(v)
        if 102 <= t <= 125 and onceki is not None:
            tek.append(abs(v[0] - onceki))
            ema.append(abs(d[0]))
        onceki, z_son = v[0], z[0]
    assert max(tek) < 1e-3
    assert max(ema) > 1.0 and sum(ema) / len(ema) > 0.5, "çok ölçekli Δ ağa görünür olmalı"
    assert z_son > 2.0, "seviye bilgisi z'de kalır"


def test_delta_ilk_ornek_sifir_ve_kirpilir():
    d = nb.CokOlcekliDelta(2)
    assert d.guncelle([1.0, 2.0]) == [0.0, 0.0]            # sıfırdan başlatma sahte ivme üretmez
    out = d.guncelle([3.0, -3.0])
    assert all(abs(v) <= 3.0 for v in out) and out[0] > 0 > out[1]


# ------------------------------------------------------------------ kavram hafızası
def sahne(i, deger=1.0):
    v = [0.0] * SB
    v[i] = deger
    return v


def test_kavram_ayni_isaretli_birlestirir_zit_isaretli_ayirir():
    u = beyin()
    u.kavram_kaydet(sahne(0), 3, +0.8)
    u.kavram_kaydet(sahne(0), 3, +0.6)            # aynı sahne, aynı işaret -> birleşir
    assert len(u.kavram_prototipi) == 1 and u.kavram_prototipi[0]["sayi"] == 2
    assert abs(u.kavram_prototipi[0]["odul"] - 0.7) < 1e-9     # (0.8*1+0.6)/2 ağırlıklı ort.
    u.kavram_kaydet(sahne(0), 3, -0.9)            # aynı sahne, ZIT işaret -> yeni prototip
    assert len(u.kavram_prototipi) == 2
    u.kavram_kaydet(sahne(1), 3, +0.7)            # farklı sahne -> yeni prototip
    assert len(u.kavram_prototipi) == 3


def test_kavram_notr_odul_notrle_birlesir_dolmayi_onler():
    u = beyin()
    for _ in range(20):
        u.kavram_kaydet(sahne(5), 4, 0.0)         # idle benzeri tekrar: tek prototip
    assert len(u.kavram_prototipi) == 1 and u.kavram_prototipi[0]["sayi"] == 20


def test_kavram_kapasite_dusuk_odul_sayi_atilir_en_eskisi_degil():
    u = beyin()
    u.kavram_max = 4
    u.kavram_kaydet(sahne(0), 1, 0.9)             # eski AMA değerli
    for i in range(1, 4):
        u.kavram_kaydet(sahne(i), 1, 0.0)         # sıradan
    u.kavram_kaydet(sahne(10), 1, 0.5)            # kapasiteyi aşar
    assert len(u.kavram_prototipi) == 4
    kalan = [p["sahne"].index(1.0) for p in u.kavram_prototipi]
    assert 0 in kalan, "en eski ama |ödül|·sayı yüksek anı silinmemeli"
    assert 10 in kalan, "yeni eklenen silinmemeli"


def test_kavram_isinma_sifir_sahneyi_yazmaz():
    u = beyin()
    u.kavram_kaydet([0.0] * SB, 2, 0.5)
    assert u.kavram_prototipi == []


def test_kavram_256_prototip_gercekten_dolabilir():
    u = beyin()
    rng = random.Random(7)
    for k in range(400):
        v = [rng.gauss(0, 1) for _ in range(SB)]
        u.kavram_kaydet(v, k % 12, 0.5)
    assert len(u.kavram_prototipi) == u.kavram_max == 256   # eski tasarımda ≤12'de takılırdı


# ------------------------------------------------------------------ sezgi
def test_sezgi_tum_komutlardan_beklenen_odulu_cikarir():
    u = beyin()
    s = sahne(0)
    u.kavram_kaydet(s, 3, +0.9)
    u.kavram_kaydet(s, 5, -0.8)
    sz = u.kavram_sezgi(s)
    assert sz[3] > 0.2 and sz[5] < -0.2
    assert YOK not in sz
    maske = [True] * C
    maske[5] = False
    assert 5 not in u.kavram_sezgi(s, maske)             # uygunsuz komuta dokunmaz
    assert u.kavram_sezgi(sahne(40)) == {}               # benzer sahne yok -> sezgi yok


def test_sezgi_az_kanitta_buzulur():
    u = beyin()
    u.kavram_kaydet(sahne(0), 3, 1.0)
    tek = u.kavram_sezgi(sahne(0))[3]
    for _ in range(8):
        u.kavram_kaydet(sahne(0), 3, 1.0)
    cok = u.kavram_sezgi(sahne(0))[3]
    assert 0 < tek < cok <= 1.0


def test_sec_sezgi_karari_etkiler_ve_hafizaya_susleme_yazmaz():
    u = beyin()
    rng = random.Random(11)
    for _ in range(60):
        u.zamansal_guncelle(sinyal(rng))
    x = sinyal(rng)
    u.zamansal_guncelle(x)
    sh = u._sahne_icin(x)
    maske = u.uygun_maske(x)
    adaylar = [i for i in range(C) if maske[i] and i != YOK]
    iyi, kotu = adaylar[0], adaylar[1]
    for _ in range(8):
        u.kavram_kaydet(sh, iyi, +1.0)
        u.kavram_kaydet(sh, kotu, -1.0)
    sz = u.kavram_sezgi(x, maske)
    assert sz[iyi] > 0 > sz[kotu]
    # ödül hafızaya HAM yazılır: sezgi ödül eklemez (geri besleme yok)
    odul_once = [p["odul"] for p in u.kavram_prototipi]
    u.sec(x, epsilon=0.0)
    assert [p["odul"] for p in u.kavram_prototipi] == odul_once
    assert u.last_sezgi is not None and u.last_sezgi[iyi] > 0


def test_organism_kaynagi_odulu_susleme_yapmiyor():
    kaynak = (Path(__file__).resolve().parent / "organism.py").read_text(encoding="utf-8")
    assert "0.2 * proto_odul" not in kaynak
    assert "kavram_hafizasi_sorgula" not in kaynak


# ------------------------------------------------------------------ ΔS sürpriz / uygulanan eylem
def _ogret(u, rng, tur=40, eylem=3):
    for _ in range(tur):
        x = sinyal(rng, genlik=0.02)
        x[7] = 0.30 + (0.1 if eylem == 3 else 0.0)      # eylem 3'ün tutarlı etkisi
        u.zamansal_guncelle(x)
        u.eylem_uygulandi(eylem)
    return u


def test_surpriz_ogrenilmis_hamlede_dusuk_beklenmedikte_yuksek():
    u = beyin()
    rng = random.Random(21)
    # Eylem 3: dünya her tik 7. boyutu alternatif iki değer arasında oynatsın (öğrenilebilir)
    for t in range(120):
        x = sinyal(rng, genlik=0.01)
        x[7] = 0.30 if t % 2 == 0 else 0.60
        u.zamansal_guncelle(x)
        u.eylem_uygulandi(3)
    sakin = u.son_surpriz
    # beklenmedik: dünya ani sıçrama yapar
    x = sinyal(rng, genlik=0.01)
    x[7] = 0.30
    x[8] = 0.05
    u.zamansal_guncelle(x)
    u.eylem_uygulandi(3)
    x = sinyal(rng, genlik=0.01)
    x[7] = 0.60
    x[8] = 0.95                                            # hiç görülmemiş büyük değişim
    u.zamansal_guncelle(x)
    assert u.son_surpriz > sakin + 0.1, (sakin, u.son_surpriz)
    assert 0.0 <= u.son_surpriz <= 1.0


def test_eylem_bildirilmezse_surpriz_sifir_ve_onehot_uygulanan():
    u = beyin()
    rng = random.Random(22)
    for _ in range(30):
        u.zamansal_guncelle(sinyal(rng))
    assert u.son_surpriz == 0.0 and u.son_eylem_onehot == [0.0] * C
    u.eylem_uygulandi(5)
    u.zamansal_guncelle(sinyal(rng))
    assert u.son_eylem_onehot[5] == 1.0 and sum(u.son_eylem_onehot) == 1.0


def test_surpriz_boyutu_hataya_katilmaz_kendine_gonderme_yok():
    m = nb.DunyaDeltaModeli()
    hata = m.guncelle_ve_hata("b0", 3, [0.0] * nb.IDX_SURPRIZ + [3.0] + [0.0] * (S - nb.IDX_SURPRIZ - 1))
    assert hata == 0.0


def test_organism_surpriz_beslemesi_ve_uygulanan_eylem_baglantisi():
    from types import SimpleNamespace
    from organism import Organism

    o = Organism.__new__(Organism)
    o.atolye = SimpleNamespace(model={"surpriz": 0.4})
    o.ust = beyin()
    o.ust.son_surpriz = 0.5
    assert abs(o._surpriz_ust() - 2.5) < 1e-12            # max(0.4, 5*0.5); ÷5 -> IDX_SURPRIZ=0.5
    o.ust.son_surpriz = 0.01
    assert abs(o._surpriz_ust() - 0.4) < 1e-12            # atölye alt sınır kalır
    o.ust.surpriz_dunya_delta = False
    o.ust.son_surpriz = 0.9
    assert abs(o._surpriz_ust() - 0.4) < 1e-12            # kapatılabilir

    kaynak = (Path(__file__).resolve().parent / "organism.py").read_text(encoding="utf-8")
    i = kaynak.index("self.decision.sec_override(stim_ust")
    pencere = kaynak[i:i + 600]
    assert '"eylem_uygulandi"' in pencere and "_eu(self.decision.idx_ust)" in pencere, \
        "uygulanan komut sec_override'dan hemen sonra bildirilmeli (reddedilme sonrası idx)"


# ------------------------------------------------------------------ MLP sözleşmesi
def test_v2_kapaliyken_eski_slotlar_v2_aciksa_ema_ve_onehot():
    kapali = nb.NöralUstBeyn({"zamansal_kanal": True}, root=taze_kok(), seed=3)
    kapali.son_delta, kapali.son_niyet = [0.1] * S, [0.2] * C
    kapali.son_delta_z, kapali.son_eylem_onehot = [3.0] * S, [1.0] * C
    g = kapali._mlp_girisi([0.5] * S)
    assert g[S:2 * S] == [0.1] * S and g[2 * S:] == [0.2] * C

    acik = nb.NöralUstBeyn({"zamansal_kanal": True, "zamansal_v2": True}, root=taze_kok(), seed=3)
    acik.son_delta_z = [3.0] * S
    acik.son_eylem_onehot = [0.0] * C
    acik.son_eylem_onehot[4] = 1.0
    g = acik._mlp_girisi([0.5] * S)
    assert g[S:2 * S] == [1.0] * S and g[2 * S + 4] == 1.0 and sum(g[2 * S:]) == 1.0


def test_ham_s_t_sozlesmesi_korunur_mlp_ham_girer():
    u = beyin()
    x = [0.3] * S
    assert u._mlp_girisi(x) == x                          # kanal kapalı: aynen ham


# ------------------------------------------------------------------ kalıcılık
def test_kalicilik_sahne_hafizasi_yeniden_baslatmada_korunur():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    rng = random.Random(31)
    for t in range(80):
        x = sinyal(rng)
        u.zamansal_guncelle(x)
        u.eylem_uygulandi(t % 5 + 1)
        u.ogren(x, t % 5 + 1, 0.5 if t % 3 else -0.4)
    n_proto, n_norm, dm = len(u.kavram_prototipi), u.sahne_takip.norm.n, len(u.dunya_delta.ort)
    assert n_proto > 5
    u.save()
    v = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert len(v.kavram_prototipi) == n_proto
    assert v.sahne_takip.norm.n == n_norm and len(v.dunya_delta.ort) == dm
    x = sinyal(rng)
    u.zamansal_guncelle(x)
    v.zamansal_guncelle(x)
    assert all(abs(a - b) < 1e-3 for a, b in zip(u.son_z, v.son_z))


def test_kalicilik_bozuk_sahne_verisi_taze_baslar():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    rng = random.Random(32)
    for t in range(30):
        x = sinyal(rng)
        u.zamansal_guncelle(x)
        u.ogren(x, 2, 0.5)
    u.save()
    yol = kok / "zeka" / "ust_beyn.json"
    import json
    d = json.loads(yol.read_text(encoding="utf-8"))
    d["sahne_takip"]["norm"]["mean"] = [0.0] * (S - 1)        # boyutu bozuk
    yol.write_text(json.dumps(d), encoding="utf-8")
    v = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert v.kavram_prototipi == [] and v.sahne_takip.norm.n == 0


def test_yan_sinif_init_atlasa_da_calisir():
    """test_ust_beyn'deki gibi __init__'i atlayan sınıflar yeni alanlar olmadan da çalışmalı."""
    class Yan(nb.NöralUstBeyn):
        def __init__(self):
            self.kavram_prototipi = []
            self.kavram_max = 256
            self.tik = 0
    y = Yan()
    y.kavram_kaydet([0.5] * S, 2, 0.5)                         # 48'lik ham -> mutasyonsuz anahtar
    y.kavram_kaydet(sahne(0), 2, 0.5)
    assert len(y.kavram_prototipi) >= 1
    assert isinstance(y.kavram_sezgi(sahne(0)), dict)
    y.eylem_uygulandi(3)                                       # _bekleyen_gecis yok: sessiz


if __name__ == "__main__":
    ok = 0
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            ok += 1
            print("  ok:", ad)
    print("SAHNE/SEZGI: TUMU GECTI (%d)" % ok)
