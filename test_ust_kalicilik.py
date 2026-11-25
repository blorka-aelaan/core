#!/usr/bin/env python3
"""Üst beyin ağırlık kalıcılığı: kaydet→yükle bozulmamalı, uyumsuz dosya karantinaya alınmalı."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zeka  # noqa: E402

_T = tempfile.mkdtemp(prefix="ust_kalicilik_")


def taze_kok():
    kok = Path(tempfile.mkdtemp(dir=_T))
    (kok / "zeka").mkdir()
    zeka.KOK = zeka.KLASOR = kok / "zeka"     # nn_*.json gerçek zeka/ klasörüne yazılmasın
    return kok


import noral_beyn as nb  # noqa: E402


def yol(kok):
    return kok / "zeka" / "ust_beyn.json"


def sekiller(u):
    w = u.mlp.ağırlıklar
    return (len(w[0]), len(w[0][0]), len(w[1]), len(w[1][0]))


DOGRU = (nb.SINYAL_BOYUT, nb.GIZLI_BOYUT, nb.GIZLI_BOYUT, nb.CIKIS_BOYUT)


def egit(u, adim=30):
    x = [0.0] * nb.SINYAL_BOYUT
    x[nb.IDX_ACLIK] = 1.0
    for _ in range(adim):
        u.ogren(x, nb.KOMUT_INDEKSI[nb.KOMUT_ACIL_YEM], 1.0)
    return x


def test_egitim_sekli_bozmaz():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert sekiller(u) == DOGRU
    egit(u, 40)
    assert sekiller(u) == DOGRU, sekiller(u)


def test_kaydet_yukle_ayni_ag():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    x = egit(u, 25)
    u.save()
    d = json.loads(yol(kok).read_text(encoding="utf-8"))
    assert d["agirlik_yerlesimi"] == nb.AGIRLIK_YERLESIMI
    u2 = nb.NöralUstBeyn({}, root=kok, seed=9)
    assert sekiller(u2) == DOGRU
    fark = max(abs(a - b) for a, b in zip(u.mlp.tahmin(x), u2.mlp.tahmin(x)))
    assert fark < 1e-12, fark
    assert u2.samples == u.samples and u2.secim_sayilari == u.secim_sayilari
    egit(u2, 20)                          # yüklendikten sonra eğitim de bozmamalı
    assert sekiller(u2) == DOGRU
    u2.save()
    assert sekiller(nb.NöralUstBeyn({}, root=kok, seed=1)) == DOGRU


def _eski_dosya(kok, w1_sekil, w2_sekil, yerlesim=None):
    d = {"surum": 4, "samples": 777, "tik": 888, "secim_sayilari": [5] * nb.CIKIS_BOYUT,
         "dogrulama": [0.5] * nb.CIKIS_BOYUT,
         "W1": [[0.1] * w1_sekil[1] for _ in range(w1_sekil[0])], "b1": [0.0] * w1_sekil[0],
         "W2": [[0.1] * w2_sekil[1] for _ in range(w2_sekil[0])], "b2": [0.0] * w2_sekil[0]}
    if yerlesim:
        d["agirlik_yerlesimi"] = yerlesim
    yol(kok).write_text(json.dumps(d), encoding="utf-8")


def test_eski_numpy_dosyasi_karantinaya_alinir():
    kok = taze_kok()
    _eski_dosya(kok, (nb.GIZLI_BOYUT, nb.SINYAL_BOYUT), (nb.CIKIS_BOYUT, nb.GIZLI_BOYUT))  # [çıktı][girdi]
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert sekiller(u) == DOGRU                                    # taze, geçerli ağırlık
    k = list((kok / "zeka").glob("ust_beyn.agirlik_eski_duzen_*.json"))
    assert len(k) == 1 and json.loads(k[0].read_text())["W1"]      # silinmedi, yanına alındı
    assert u.samples == 777 and u.secim_sayilari == [5] * nb.CIKIS_BOYUT   # diğer durum korundu
    egit(u, 10)
    u.save()
    assert sekiller(nb.NöralUstBeyn({}, root=kok, seed=1)) == DOGRU


def test_bozuk_sekil_karantinaya_alinir_ve_cokmez():
    kok = taze_kok()
    # canlı sistemde görülen bozulma: W1 16x12, W2 12x12
    _eski_dosya(kok, (16, 12), (12, 12))
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert sekiller(u) == DOGRU
    assert list((kok / "zeka").glob("ust_beyn.agirlik_eski_duzen_*.json"))
    # yerleşim işaretli ama şekil yanlış
    kok2 = taze_kok()
    _eski_dosya(kok2, (nb.SINYAL_BOYUT, 12), (12, nb.CIKIS_BOYUT), yerlesim=nb.AGIRLIK_YERLESIMI)
    u2 = nb.NöralUstBeyn({}, root=kok2, seed=3)
    assert sekiller(u2) == DOGRU
    assert list((kok2 / "zeka").glob("ust_beyn.agirlik_sekil_gecersiz_*.json"))


def test_bozuk_agirlik_diske_yazilmaz():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    egit(u, 5)
    u.save()
    once = yol(kok).read_bytes()
    u.mlp.ağırlıklar[0] = [row[:5] for row in u.mlp.ağırlıklar[0]]    # kasıtlı bozulma
    u.save()
    assert yol(kok).read_bytes() == once, "bozuk ağırlık sağlam dosyanın üzerine yazılmamalı"


def test_cikis_buyurse_yeni_sutunlar_sifirlanir():
    kok = taze_kok()
    u = nb.NöralUstBeyn({}, root=kok, seed=3)
    egit(u, 5)
    u.save()
    d = json.loads(yol(kok).read_text())
    d["W2"] = [r[:-1] for r in d["W2"]]            # bir komut önceki eğitim: 1 çıktı eksik
    d["b2"] = d["b2"][:-1]
    yol(kok).write_text(json.dumps(d), encoding="utf-8")
    u2 = nb.NöralUstBeyn({}, root=kok, seed=3)
    assert sekiller(u2) == DOGRU
    assert all(r[-1] == 0.0 for r in u2.mlp.ağırlıklar[1]) and u2.mlp.çeşitler[1][-1] == 0.0
    assert not list((kok / "zeka").glob("ust_beyn.agirlik_*"))     # karantina gerekmedi


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            print("ok", ad)
    print("üst beyin kalıcılık testleri: ALL PASSED")
