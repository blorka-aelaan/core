"""olcum_zincir --karsilastir denetim sagligi.

Iki bug birden yakalandi (2026-10-18):
  1. TABAN okumasi: olcum_zincir_taban.json metrikleri "tip" altinda;
     eski kod yalnizca duz formu arayinca TUM tip karsilastirmalari
     sessizce atlanir, arac her kosulda "belirgin fark yok" basardi.
  2. Pencere uyumsuzlugu: taban son-60000 kayitta olculmusken arac tum
     jurnalle karsilastiriyordu — eski patolojili donem bugu eziyor,
     sahte "regresyon" cikiyordu. Simdi --karsilastir pencereyi tabana
     esitliyor.
"""
import io
import sys
import contextlib
sys.path.insert(0, "/home/emrah/Genel/core")
import olcum_zincir as O


def _sozluk(basari, pencere=60000):
    """--taban ile yazilan dosya bicimi ("tip" altinda metrikler)."""
    return {
        "toplam_kayit": pencere,
        "toplam_oturum": 100,
        "tip": {t: {"oturum": 50, "oturum_basari": basari,
                    "wc_ilk": 0.09, "bilinen_yol": 0.80,
                    "israf": 0.14, "ilk_karisim": {}}
                for t in O.ZINCIR_TIPLERI},
        "yol_basari": {"ls->wc": {"basari": 0.93, "n": 100}},
    }


def _sade(basari):
    """Olculen sozluk (tip metrikleri dolu)."""
    return _sozluk(basari, pencere=0)


def _sessiz(func, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        sonuc = func(*a)
    return sonuc, buf.getvalue()


def test_dosya_tabani_tip_okunur():
    """'tip' sarili dosya tabaninda metrikler gorulur (eski: atlanirdi)."""
    fark, cikti = _sessiz(O.taban_karsilastir, _sade(0.56), _sozluk(0.74))
    assert fark is True, "basari 0.74->0.56 dususu gorulmeli"
    assert "DOSYA_SAY" in cikti and "!!" in cikti, cikti


def test_esitlikte_fark_yok():
    fark, _cikti = _sessiz(O.taban_karsilastir, _sade(0.74), _sozluk(0.74))
    assert fark is False


def test_duz_eski_taban_hala_calisir():
    """Eski sabit TABAN bicimi (duz, 'kayit_sayisi') da okunmali."""
    duz = {"kayit_sayisi": 200000,
           "DOSYA_SAY": {"oturum_basari": 0.55, "wc_ilk": 0.12,
                         "bilinen_yol": 0.47, "israf": 0.61},
           "SUREC_SAY": {"oturum_basari": 0.55, "wc_ilk": 0.12,
                         "bilinen_yol": 0.47, "israf": 0.61},
           "yol_basari": {"ls->wc": 0.969}}
    fark, cikti = _sessiz(O.taban_karsilastir, _sade(0.70), duz)
    assert fark is True
    assert "YOL ls->wc" in cikti, "duz yol_basari tabani da karsilastirilmali"


def test_pencere_esitleme():
    """--karsilastir, taban penceresine gore son-N'e sinirlanmali."""
    assert O._taban_pencere(_sozluk(0.7, pencere=60000)) == 60000
    assert O._taban_pencere({"kayit_sayisi": 200000}) == 200000
    assert O._taban_pencere({"yok": 1}) == 0
    assert O._taban_pencere(None) == 0


test_dosya_tabani_tip_okunur()
test_esitlikte_fark_yok()
test_duz_eski_taban_hala_calisir()
test_pencere_esitleme()
print("OLCUM_ZINCIR DENETIM: 4/4 OK")