"""talep hattı testi: tespit + golge eleme + rapor + KURULUM YOK."""
import json
import os
import sys
import tempfile

sys.path.insert(0, "/home/emrah/Genel/core")
import talep


class Sahte:
    """Bağımlılıkları taklit eder — gerçek sisteme dokunmaz."""

    def __init__(self, var_olanlar, kurulu, aday):
        self.var_olanlar = var_olanlar
        self.kurulu = kurulu
        self.aday = aday


# 1) tespit: kurulu / eksik-aday / depoda-yok ayrımı
def test_tespit():
    # traceroute ve nload BEYAZ'da degiller, bu yüzden talep listesine girer
    s = Sahte({"nstat"}, {"iproute2"}, {"traceroute", "nload"})
    eski = (talep._which, talep._dpkg_kurulu, talep._apt_aday)
    talep._which = lambda k: k in s.var_olanlar
    talep._dpkg_kurulu = lambda p: p in s.kurulu
    talep._apt_aday = lambda p: p in s.aday
    try:
        v = talep.tara()
        durum = {t["komut"]: t["durum"] for t in
                 [dict(komut=k, durum=d) for k, d in
                  [(x["komut"], x["durum"]) for x in
                   v.get("talep", [])]]}
        # nstat: var → talep listesinde YOK (zaten_var)
        # traceroute: yok, paketi depoda aday → talep edilebilir
        # nload: yok, paketi depoda aday → talep edilebilir
        komutlar = [t["komut"] for t in v["talep"]]
        assert "traceroute" in komutlar, komutlar
        assert "nload" in komutlar, komutlar
        assert "nstat" not in komutlar, komutlar
        # iproute2 kurulu ama nstat binary'si yok (sahte): durum
        # "paket_kurulu_ama_yok" — talep listesine girmez
        print("1 tespit: var/kurulu/aday ayrımı OK")
    finally:
        talep._which, talep._dpkg_kurulu, talep._apt_aday = eski


# 2) golge duvarı: yasaklı sınıf asla talep edilmez
def test_golge():
    eski = list(talep.ADAY_KOMUTLAR)
    try:
        talep.ADAY_KOMUTLAR.append(
            ("passwd", "passwd", "OKUMA", "test", False))
        eski2 = (talep._which, talep._dpkg_kurulu, talep._apt_aday)
        talep._which = lambda k: False
        talep._dpkg_kurulu = lambda p: False
        talep._apt_aday = lambda p: True
        try:
            v = talep.tara()
            komutlar = [t["komut"] for t in v["talep"]]
            redler = [r["komut"] for r in v["red"]]
            assert "passwd" not in komutlar, komutlar
            assert "passwd" in redler, redler
            print("2 golge: yasaklı sınıf elendi OK")
        finally:
            talep._which, talep._dpkg_kurulu, talep._apt_aday = eski2
    finally:
        talep.ADAY_KOMUTLAR[:] = eski


# 3) rapor + json yazımı: KURULUM YOK, sadece öneri metni
def test_rapor():
    veri = {"talep": [{"komut": "lsof", "paket": "lsof",
                       "hedef_tipi": "SUREC_SOR",
                       "gerekce": "açık dosya", "judge_var": True,
                       "kurulum_onerisi": "sudo apt-get install -y lsof"}],
            "red": [], "t": 0}
    with tempfile.TemporaryDirectory() as td:
        eski_md, eski_json = talep.TALEP_MD, talep.TALEP_JSON
        from pathlib import Path
        talep.TALEP_MD = Path(td) / "talepler.md"
        talep.TALEP_JSON = Path(td) / "talep.json"
        try:
            talep.kaydet(veri)
            md = talep.raporla(veri)
            assert os.path.exists(md)
            icerik = open(md, encoding="utf-8").read()
            assert "lsof" in icerik and "sudo apt-get install -y lsof" in icerik
            # rapor KURULUM YAPIYOR mu? hayır — sadece metin
            assert "apt-get install" in icerik  # öneri metni var
            d = json.load(open(talep.TALEP_JSON, encoding="utf-8"))
            assert d["talep"][0]["komut"] == "lsof"
            print("3 rapor: md + json yazildi, kurulum yok OK")
        finally:
            talep.TALEP_MD, talep.TALEP_JSON = eski_md, eski_json


test_tespit()
test_golge()
test_rapor()
print("TALEP HATTI: 3/3 OK")
