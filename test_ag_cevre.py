#!/usr/bin/env python3
"""ag_cevre.py testleri — sahte arp-scan/nmap ile (gerçek ağ trafiği yok)."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import ag_cevre as ac

AGLAR = ["192.168.1.0/24"]


class Saat:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Sahte:
    """arp-scan / ip / nmap / avahi taklidi. Her çağrıyı kaydeder."""

    def __init__(self):
        self.arp = ""
        self.nmap_portlari = {}      # ip -> [(port, servis)]
        self.cagrilar = []

    def __call__(self, argv, **kw):
        self.cagrilar.append(list(argv))
        ad = Path(argv[0]).name
        if ad == "arp-scan":
            return SimpleNamespace(returncode=0, stdout=self.arp, stderr="")
        if ad == "ip":
            return SimpleNamespace(returncode=0, stdout="default via 192.168.1.1 dev eth0\n", stderr="")
        if ad == "nmap":
            ip = argv[-1]
            portlar = self.nmap_portlari.get(ip, [])
            if "-p-" in argv:
                portlar = portlar + [(49152, "unknown")] if portlar else portlar
            return SimpleNamespace(returncode=0, stdout=self.xml(ip, portlar), stderr="")
        if ad in ("avahi-resolve", "getent"):
            return SimpleNamespace(returncode=0, stdout="%s\ttest-cihaz.local\n" % argv[-1], stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="bilinmeyen")

    @staticmethod
    def xml(ip, portlar):
        p = "".join(
            '<port protocol="tcp" portid="%d"><state state="open"/><service name="%s"/></port>' % (n, s)
            for n, s in portlar)
        return ('<?xml version="1.0"?><nmaprun><host><status state="up"/>'
                '<address addr="%s" addrtype="ipv4"/><ports>%s</ports></host></nmaprun>' % (ip, p))

    def arp_cagrilari(self):
        return [c for c in self.cagrilar if Path(c[0]).name == "arp-scan"]

    def nmap_cagrilari(self):
        return [c for c in self.cagrilar if Path(c[0]).name == "nmap"]


def arp_satir(ip, mac, uretici="Vendor"):
    return "%s\t%s\t%s\n" % (ip, mac, uretici)


def kur(tmp, ayar=None, araclar=("arp-scan", "ip", "nmap", "avahi-resolve", "getent")):
    saat, sahte = Saat(), Sahte()
    izle = ac.CevreIzleyici(
        Path(tmp), runner=sahte, clock=saat,
        kapsam_fn=lambda: (list(AGLAR), None),
        ayar_fn=lambda: dict(ayar or {}),
        arac_bul=lambda ad: "/usr/bin/" + ad if ad in araclar else None,
        arka_planda=False,
    )
    return izle, sahte, saat


def hepsini_bitir(izle, saat, sinir=60):
    """Sessiz kalana kadar adim() çağırır; her çağrı arasında zaman ilerler."""
    sonuclar = []
    for _ in range(sinir):
        saat.t += 15
        s = izle.adim()
        sonuclar.append(s)
        if s.get("noop") and not izle.veri["is_kuyrugu"]:
            break
    return sonuclar


# ---------------------------------------------------------------- ayrıştırıcılar
def test_arp_ve_nmap_ayristirma():
    cikti = ("192.168.1.1\t00:bb:cc:00:00:01\tTP-LINK TECHNOLOGIES\n"
             "192.168.1.9\t00:BB:CC:00:00:09\t(Unknown: locally administered) (DUP: 2)\n"
             "bozuk satir\n192.168.1.300\t00:bb:cc:00:00:10\tx\n")
    k = ac.arp_ayristir(cikti)
    assert [x["ip"] for x in k] == ["192.168.1.1", "192.168.1.9"], k
    assert k[1]["mac"] == "00:bb:cc:00:00:09" and k[1]["dup"] == 2
    x = ('<nmaprun><host><status state="up"/><address addr="192.168.1.5" addrtype="ipv4"/>'
         '<address addr="00:BB:CC:00:00:05" addrtype="mac" vendor="Acme"/>'
         '<ports><port protocol="tcp" portid="22"><state state="open"/>'
         '<service name="ssh" product="OpenSSH&#10;evil" version="9.2"/>'
         '<script id="ssh-hostkey" output="abc"/></port>'
         '<port protocol="tcp" portid="23"><state state="closed"/></port></ports></host></nmaprun>')
    r = ac.nmap_xml_ayristir(x)["192.168.1.5"]
    assert [p["port"] for p in r["portlar"]] == [22] and r["mac"] == "00:bb:cc:00:00:05"
    assert "\n" not in r["portlar"][0]["urun"]            # kontrol karakteri temizlendi
    assert ac.temiz_metin("a\x1b[31mb\x07") == "a [31mb"
    try:                                                   # geçersiz XML: çökmez, ValueError
        ac.nmap_xml_ayristir("<nmaprun>\x07</nmaprun>")
        assert False
    except ValueError:
        pass
    assert r["betikler"]["22/ssh-hostkey"] == "abc"
    try:
        ac.nmap_xml_ayristir('<!DOCTYPE x [<!ENTITY a "b">]><nmaprun/>')
        assert False
    except ValueError:
        pass


def test_gercek_arp_scan_cikti_bicimi_ve_yetki_ipucu():
    # Gerçek `arp-scan --plain` çıktısının biçimi (sekmeli; MAC'ler uydurma)
    cikti = ("192.168.1.1\t00:bb:cc:1b:1a:2b\t(Unknown)\n"
             "192.168.1.4\t94:de:80:00:00:01\tGIGA-BYTE TECHNOLOGY CO.,LTD.\n"
             "192.168.1.11\t86:11:55:00:00:02\t(Unknown: locally administered)\n"
             "192.168.1.5\t84:16:f9:00:00:03\tTP-LINK TECHNOLOGIES CO.,LTD.\n")
    k = ac.arp_ayristir(cikti)
    assert [x["ip"] for x in k] == ["192.168.1.1", "192.168.1.4", "192.168.1.11", "192.168.1.5"]
    assert k[0]["uretici"] == "" and k[2]["uretici"] == ""          # (Unknown...) üretici sayılmaz
    assert k[1]["uretici"].startswith("GIGA-BYTE")
    with tempfile.TemporaryDirectory() as tmp:
        saat, sahte = Saat(), Sahte()
        izle = ac.CevreIzleyici(Path(tmp), runner=lambda argv, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="sudo: a password is required"),
            clock=saat, kapsam_fn=lambda: (list(AGLAR), None),
            ayar_fn=lambda: {"arp_sudo": True}, arac_bul=lambda ad: "/usr/sbin/" + ad,
            arka_planda=False)
        s = izle.adim()
        assert not s["ok"] and "NOPASSWD" in s["reason"]
        ilk = izle._arp_argv(AGLAR, izle.ayar(), False)
        assert ilk[:3] == ["sudo", "-n", "/usr/sbin/arp-scan"] and ilk[-1] == "192.168.1.0/24"


def test_siniflandirma():
    assert ac.siniflandir("(Unknown: locally administered)", "da:a1:19:00:00:01", [62078])[0] == "mobile"
    assert ac.siniflandir("Samsung Electronics", "00:bb:cc:00:00:01", [8001, 8002])[0] == "tv"
    assert ac.siniflandir("HP Inc", "00:bb:cc:00:00:02", [9100, 631])[0] == "yazici"
    assert ac.siniflandir("Intel Corporate", "00:bb:cc:00:00:03", [3389, 445])[0] == "pc"
    assert ac.siniflandir("TP-LINK", "00:bb:cc:00:00:04", [53, 80])[0] == "ag_cihazi"
    assert ac.siniflandir("", "00:bb:cc:00:00:05", [])[0] == "bilinmiyor"
    assert ac.siniflandir("x", "00:bb:cc:00:00:06", [], hostname="Emrahs-iPhone")[0] == "mobile"


# ---------------------------------------------------------------- akış
def test_taban_cizgisi_derin_tarama_ve_sessizlik():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = (arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
                     + arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel Corporate"))
        sahte.nmap_portlari = {"192.168.1.1": [(53, "domain"), (80, "http")],
                               "192.168.1.20": [(445, "microsoft-ds"), (3389, "ms-wbt-server")]}
        assert izle.due_in() == 0                       # ilk süpürme hemen
        s1 = izle.adim()
        assert s1["probe"] == "arp_supurme" and s1["yeni_cihaz"] == 2 and s1["ok"]
        assert not [o for o in s1["olaylar"] if o["tur"] == "yeni_cihaz"], "taban çizgisinde alarm olmamalı"
        assert len(izle.veri["is_kuyrugu"]) == 2        # her yeni cihaz derin taranacak
        hepsini_bitir(izle, saat)
        c = izle.veri["cihazlar"]["00:bb:cc:00:00:20"]
        assert c["guven"] == "bilinen" and c["derin_tamamlandi"] > 0
        assert {p["port"] for p in c["acik_portlar"]} >= {445, 3389, 49152}   # hızlı + tam TCP birleşti
        assert c["sinif"] == "pc" and c["hostname"] == "test-cihaz.local"
        assert izle.veri["cihazlar"]["00:bb:cc:00:00:01"]["sinif"] == "ag_cihazi"
        assert not izle.veri["is_kuyrugu"]
        # YAPILACAK İŞ YOK: bilinen cihazlar tekrar tekrar taranmaz
        n_nmap, n_arp = len(sahte.nmap_cagrilari()), len(sahte.arp_cagrilari())
        assert izle.due_in() > 0
        for _ in range(5):
            saat.t += 20                                # süpürme aralığından kısa
            s = izle.adim()
            assert s["noop"] and s["probe_reward"] < 0  # boşa çağrı küçük ceza alır
        assert len(sahte.nmap_cagrilari()) == n_nmap and len(sahte.arp_cagrilari()) == n_arp


def test_yeni_cihaz_sadece_kendisi_taranir():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp, ayar={"taban_supurme_sayisi": 1})
        sahte.arp = arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
        sahte.nmap_portlari = {"192.168.1.1": [(80, "http")], "192.168.1.30": [(8009, "castv2")]}
        izle.adim()
        hepsini_bitir(izle, saat)
        onceki = len(sahte.nmap_cagrilari())
        saat.t += 400                                   # süpürme vakti
        sahte.arp += arp_satir("192.168.1.30", "00:bb:cc:00:00:30", "Google")
        s = izle.adim()
        assert s["probe"] == "arp_supurme" and s["yeni_cihaz"] == 1
        yeni_olay = [o for o in s["olaylar"] if o["tur"] == "yeni_cihaz"]
        assert len(yeni_olay) == 1 and yeni_olay[0]["mac"] == "00:bb:cc:00:00:30"
        hepsini_bitir(izle, saat)
        hedefler = {c[-1] for c in sahte.nmap_cagrilari()[onceki:]}
        assert hedefler == {"192.168.1.30"}, hedefler    # eski cihaz yeniden taranmadı
        assert izle.veri["cihazlar"]["00:bb:cc:00:00:30"]["sinif"] == "tv"


def test_gecit_mac_degisimi_komple_tarama_tetikler():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = (arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
                     + arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel"))
        izle.adim()
        hepsini_bitir(izle, saat)
        saat.t += 400
        sahte.arp = (arp_satir("192.168.1.1", "de:ad:be:ef:00:01", "Unknown")
                     + arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel"))
        s = izle.adim()
        turler = {o["tur"] for o in s["olaylar"]}
        assert "gecit_mac_degisti" in turler, turler
        assert izle.veri["tam_bekliyor"] is not None
        # komple tarama: agresif ARP + TÜM çevrimiçi cihazlara derin iş
        saat.t += ac.VARSAYILAN_AYAR["tam_bekleme_sn"] + 1
        onceki_arp = len(sahte.arp_cagrilari())
        s2 = izle.adim()
        assert s2["probe"] == "arp_tam_supurme" and s2["tam_tarama"]["is_sayisi"] >= 2
        agresif = sahte.arp_cagrilari()[onceki_arp]
        assert "--retry=%d" % (ac.VARSAYILAN_AYAR["arp_retry"] + 3) in agresif   # varsayılan + 3
        assert {j["tur"] for j in izle.veri["is_kuyrugu"]} == {"tam"}
        # tam tarama bekleme süresi içinde ikinci kez tetiklenmez
        izle.veri["tam_bekliyor"] = {"neden": "x", "ip": None, "mac": None, "t": saat.t}
        saat.t += 60
        s3 = izle.adim()
        assert s3.get("probe") != "arp_tam_supurme"


def test_ip_mac_cakisma_ve_dup():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = (arp_satir("192.168.1.1", "00:bb:cc:00:00:01")
                     + arp_satir("192.168.1.1", "de:ad:be:ef:00:99"))
        s = izle.adim()
        assert "ip_mac_cakisma" in {o["tur"] for o in s["olaylar"]}
        assert izle.veri["tam_bekliyor"]["neden"] == "ip_mac_cakisma"


def test_ayni_cakisma_tekrar_komple_tarama_baslatmaz():
    """Gerçek vaka: 192.168.1.7 iki (rastgele) MAC ile yanıt veriyor; kalıcıysa döngü olmasın."""
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = (arp_satir("192.168.1.4", "94:de:80:00:00:01", "GIGA-BYTE")
                     + arp_satir("192.168.1.7", "2e:a9:7c:00:2d:b3", "(Unknown: locally administered)")
                     + arp_satir("192.168.1.7", "22:9d:9b:66:f1:72", "(Unknown: locally administered) (DUP: 2)"))
        s1 = izle.adim()
        o1 = [o for o in s1["olaylar"] if o["tur"] == "ip_mac_cakisma"]
        assert len(o1) == 1 and o1[0]["siddet"] == "yuksek" and not o1[0].get("tekrar")
        assert izle.veri["tam_bekliyor"]["neden"] == "ip_mac_cakisma"
        saat.t += ac.VARSAYILAN_AYAR["tam_bekleme_sn"] + 1
        s2 = izle.adim()                                # komple tarama çalışır
        assert s2["probe"] == "arp_tam_supurme"
        olaylar2 = [o for o in s2["olaylar"] if o["tur"] == "ip_mac_cakisma"]
        assert olaylar2 and olaylar2[0].get("tekrar") and olaylar2[0]["siddet"] == "dusuk"
        assert izle.veri["tam_bekliyor"] is None        # tam tarama kendi kendini yeniden tetiklemedi
        # aynı çakışma sonraki süpürmelerde de sessiz kalır
        izle.veri["is_kuyrugu"] = []
        saat.t += 400
        s3 = izle.adim()
        assert s3["probe"] == "arp_supurme" and izle.veri["tam_bekliyor"] is None
        # susturma süresi dolunca yeniden değerlendirilir
        saat.t += ac.VARSAYILAN_AYAR["yuksek_susturma_sn"] + 1
        s4 = izle.adim()
        assert izle.veri["tam_bekliyor"] is not None
        # çakışmanın MAC kümesi değişirse yeni olaydır
        izle.veri["tam_bekliyor"] = None
        saat.t += 400
        sahte.arp += arp_satir("192.168.1.7", "de:ad:be:ef:00:07", "(Unknown: locally administered)")
        izle.adim()
        assert izle.veri["tam_bekliyor"] is not None


def test_taban_cizgisi_uyuyan_cihazlari_yanlis_alarm_yapmaz():
    """Gerçek vaka: ilk süpürme 6 cihaz buldu, elle 9 görünüyordu."""
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = (arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
                     + arp_satir("192.168.1.4", "94:de:80:00:00:04", "GIGA-BYTE"))
        izle.adim()                                      # 1. süpürme
        assert not izle.veri["taban_cizgisi"]
        saat.t += 400
        sahte.arp += arp_satir("192.168.1.11", "86:11:55:00:00:11", "(Unknown: locally administered)")
        s2 = izle.adim()                                 # telefon sonradan göründü (2. süpürme)
        assert s2["probe"] == "arp_supurme" and s2["yeni_cihaz"] == 1
        assert not [o for o in s2["olaylar"] if o["tur"] == "yeni_cihaz"], "taban döneminde alarm olmamalı"
        saat.t += 400
        s3 = izle.adim()                                 # 3. süpürme: taban tamam
        assert izle.veri["taban_cizgisi"]
        saat.t += 400
        sahte.arp += arp_satir("192.168.1.30", "00:bb:cc:00:00:30", "Acme")
        s4 = izle.adim()
        assert [o["tur"] for o in s4["olaylar"] if o["tur"] == "yeni_cihaz"] == ["yeni_cihaz"]


def test_gecit_sinifi_asama_sinifi_ve_eski_kayit_gecisi():
    """Gerçek vaka: .1 router üreticisiz ama portlu; GIGA-BYTE adı; eski '(Unknown)' kaydı."""
    assert ac.siniflandir("GIGA-BYTE TECHNOLOGY CO.,LTD.", "94:de:80:00:00:04", [])[0] == "pc"
    assert ac.siniflandir("", "d8:4a:2b:00:00:01", [21, 53, 80, 139, 443, 52869])[0] == "ag_cihazi"
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        # eski sürümden kalma kayıt: üretici "(Unknown)"
        sahte.arp = (arp_satir("192.168.1.1", "d8:4a:2b:00:00:01", "(Unknown)")
                     + arp_satir("192.168.1.30", "00:bb:cc:00:00:30", "(Unknown)"))
        sahte.nmap_portlari = {"192.168.1.30": [(9100, "jetdirect")]}
        izle.adim()
        gw = izle.veri["cihazlar"]["d8:4a:2b:00:00:01"]
        assert gw["sinif"] == "ag_cihazi" and gw["sinif_guven"] == 1.0 and gw["uretici"] == ""
        assert gw["sinif_ipuclari"] == ["varsayilan_gecit"]
        yazici = izle.veri["cihazlar"]["00:bb:cc:00:00:30"]
        assert yazici["sinif"] == "bilinmiyor"
        # ilk aşama (hızlı) biter bitmez, iş bitmeden sınıf güncellenir
        for _ in range(10):
            saat.t += 15
            izle.adim()
            if yazici["acik_portlar"]:
                break
        assert yazici["derin_tamamlandi"] == 0.0 and yazici["sinif"] == "yazici"
    with tempfile.TemporaryDirectory() as tmp:       # eski kayıt dosyası yeni koda yüklenir
        izle, sahte, saat = kur(tmp)
        izle.veri["cihazlar"]["00:bb:cc:00:00:40"] = {
            "mac": "00:bb:cc:00:00:40", "uretici": "(Unknown)", "ilk_gorulme": 1, "son_gorulme": 1,
            "gorulme_sayisi": 1, "ipler": {}, "son_ip": None, "cevrimici": False, "guven": "bilinen",
            "sinif": "bilinmiyor", "sinif_guven": 0.0, "sinif_ipuclari": [], "acik_portlar": [],
            "os": None, "hostname": "", "betikler": {}, "derin_tamamlandi": 5.0, "derin_asamalar": {},
            "gorulen_yerel": [], "olaylar": [], "rastgele_mac": False}
        sahte.arp = arp_satir("192.168.1.40", "00:bb:cc:00:00:40", "(Unknown)")
        izle.adim()
        assert izle.veri["cihazlar"]["00:bb:cc:00:00:40"]["uretici"] == ""


def test_olay_guduslu_baglanti_gozlemi():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel")
        izle.adim()
        hepsini_bitir(izle, saat)
        conn = lambda ip, lp: {"remote_ip": ip, "local_port": lp, "remote_port": 50000}
        assert izle.baglanti_gozlemi(conn("8.8.8.8", 22), saat.t) == []          # kapsam dışı: yok say
        assert izle.baglanti_gozlemi({"remote_ip": "192.168.1.20", "local_port": 50000,
                                      "remote_port": 22}, saat.t) == []          # biz istemciyiz
        ol = izle.baglanti_gozlemi(conn("192.168.1.77", 22), saat.t)             # tanınmayan IP
        assert [o["tur"] for o in ol] == ["yabanci_baglanti"]
        assert izle.baglanti_gozlemi(conn("192.168.1.77", 22), saat.t + 5) == []  # 1 saat susturma
        assert any(j["ip"] == "192.168.1.77" for j in izle.veri["is_kuyrugu"])
        # bilinen cihazdan tarama benzeri istek (60 sn içinde 8 farklı yerel port)
        tum = []
        for p in range(20, 30):
            tum += izle.baglanti_gozlemi(conn("192.168.1.20", p), saat.t + p)
        assert "tarama_benzeri_istek" in {o["tur"] for o in tum}
        assert izle.veri["tam_bekliyor"]["neden"] == "tarama_benzeri_istek"


def test_tanimayan_ip_arp_ile_baglanir_ve_taranir():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = arp_satir("192.168.1.1", "00:bb:cc:00:00:01", "TP-LINK")
        sahte.nmap_portlari = {"192.168.1.77": [(22, "ssh")]}
        izle.adim()
        hepsini_bitir(izle, saat)
        # tanınmayan IP bizimle konuşuyor ve ARP'ta görünüyor
        sahte.arp += arp_satir("192.168.1.77", "00:bb:cc:00:00:77", "Raspberry Pi")
        saat.t += 30
        izle.baglanti_gozlemi({"remote_ip": "192.168.1.77", "local_port": 22, "remote_port": 50000}, saat.t)
        assert izle.due_in() == 0                       # süpürme öne alındı
        s = izle.adim()
        assert s["probe"] == "arp_supurme"
        assert izle.veri["cihazlar"]["00:bb:cc:00:00:77"]["son_ip"] == "192.168.1.77"
        assert all(j["mac"] for j in izle.veri["is_kuyrugu"])       # MAC'siz iş kalmadı
        hepsini_bitir(izle, saat)
        c = izle.veri["cihazlar"]["00:bb:cc:00:00:77"]
        assert c["derin_tamamlandi"] > 0 and any(p["port"] == 22 for p in c["acik_portlar"])
        # ARP'a hiç yanıt vermeyen IP: olay üretilir, iş düşer
        saat.t += 4000
        izle.baglanti_gozlemi({"remote_ip": "192.168.1.88", "local_port": 22, "remote_port": 50001}, saat.t)
        saat.t += 700
        s = izle.adim()
        assert "ip_arp_yanitsiz" in {o["tur"] for o in s["olaylar"]}
        assert not [j for j in izle.veri["is_kuyrugu"] if j["ip"] == "192.168.1.88"]


def test_arka_plan_nmap_dongu_bloklamaz():
    import threading
    import time as _t
    with tempfile.TemporaryDirectory() as tmp:
        saat, sahte = Saat(), Sahte()
        birak = threading.Event()
        asil = sahte.__call__

        def yavas(argv, **kw):
            if Path(argv[0]).name == "nmap":
                birak.wait(5)                           # uzun süren tarama taklidi
            return asil(argv, **kw)

        izle = ac.CevreIzleyici(Path(tmp), runner=yavas, clock=saat,
                                kapsam_fn=lambda: (list(AGLAR), None),
                                arac_bul=lambda ad: "/usr/bin/" + ad, arka_planda=True)
        sahte.arp = arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel")
        sahte.nmap_portlari = {"192.168.1.20": [(445, "microsoft-ds")]}
        izle.adim()
        saat.t += 15
        bas = _t.time()
        s = izle.adim()                                 # aşamayı başlatır, BEKLEMEZ
        assert _t.time() - bas < 1.0 and s["noop"] and s["probe"] == "cevre_asama_basladi"
        saat.t += 15
        assert izle.adim()["probe"] == "cevre_calisiyor"   # çalışırken yeni iş açmaz
        assert izle.due_in() > 0
        birak.set()
        izle._is_thread.join(5)
        saat.t += 15
        s = izle.adim()                                 # biten işi işler
        assert s["step"] == 2 and s["asama"] == "hizli" and s["ok"]
        assert any(p["port"] == 445 for p in izle.veri["cihazlar"]["00:bb:cc:00:00:20"]["acik_portlar"])


def test_kapsam_kilidi():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        o = izle.dis_olay("test", ip="10.0.0.5")
        assert not izle.veri["is_kuyrugu"], "kapsam dışı IP için iş açılmamalı"
        # kayıtlı bir cihaz için kuyruğa zorla kapsam dışı IP'li iş koy: reddedilmeli
        izle.veri["cihazlar"]["00:bb:cc:00:00:99"] = {
            "mac": "00:bb:cc:00:00:99", "cevrimici": True, "acik_portlar": [], "derin_asamalar": {},
            "olaylar": [], "ipler": {}, "uretici": "", "hostname": "", "betikler": {}}
        izle.veri["is_kuyrugu"].append({"id": 99, "tur": "derin", "mac": "00:bb:cc:00:00:99",
                                        "ip": "10.0.0.5", "neden": "x", "oncelik": 0, "asama": 0, "t": 0})
        izle.veri["son_supurme"] = saat.t               # süpürme vakti değil
        izle.adim()
        assert not izle.veri["is_kuyrugu"] and not sahte.nmap_cagrilari()
        assert any(x["tur"] == "kapsam_disi_hedef_reddedildi" for x in izle.veri["olaylar"])
    with tempfile.TemporaryDirectory() as tmp:         # kapsam kapalıyken hiçbir şey yapılmaz
        saat, sahte = Saat(), Sahte()
        i2 = ac.CevreIzleyici(Path(tmp), runner=sahte, clock=saat,
                              kapsam_fn=lambda: ([], "ag_kapsam.json taramayi acmiyor"),
                              arac_bul=lambda ad: "/usr/bin/" + ad, arka_planda=False)
        s = i2.adim()
        assert not s["ok"] and not sahte.cagrilar and i2.due_in() > 0


def test_arac_yok_hatasi_geri_cekilir():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp, araclar=("ip",))
        s = izle.adim()
        assert not s["ok"] and "arp-scan" in s["reason"]
        assert izle.due_in() > 0 and not sahte.arp_cagrilari()
        n = len(sahte.cagrilar)
        saat.t += 30
        assert izle.adim()["noop"] and len(sahte.cagrilar) == n     # bekleme süresince yeniden denemez


def test_saatlik_is_siniri():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp, ayar={"is_saatlik_azami": 2, "arp_aralik_sn": 99999})
        sahte.arp = "".join(arp_satir("192.168.1.%d" % (10 + i), "00:bb:cc:00:01:%02x" % i) for i in range(5))
        izle.adim()
        for _ in range(80):
            saat.t += 15
            izle.adim()
        tamamlanan = [c for c in izle.veri["cihazlar"].values() if c["derin_tamamlandi"] > 0]
        assert len(tamamlanan) == 2, len(tamamlanan)    # saatte 2 iş; kalanlar bekliyor
        assert izle.due_in() > 0


def test_kalicilik_ve_bozuk_dosya():
    with tempfile.TemporaryDirectory() as tmp:
        izle, sahte, saat = kur(tmp)
        sahte.arp = arp_satir("192.168.1.20", "00:bb:cc:00:00:20", "Intel")
        izle.adim()
        hepsini_bitir(izle, saat)
        yol = Path(tmp) / "zeka" / "ag_cevre.json"
        assert yol.exists() and not list(yol.parent.glob("*.tmp"))
        izle2, _, _ = kur(tmp)
        assert "00:bb:cc:00:00:20" in izle2.veri["cihazlar"]
        yol.write_text("{bozuk", encoding="utf-8")
        izle3, _, _ = kur(tmp)
        assert izle3.veri["cihazlar"] == {} and list(yol.parent.glob("ag_cevre.json.bozuk.*"))


if __name__ == "__main__":
    for ad, fn in sorted(globals().items()):
        if ad.startswith("test_") and callable(fn):
            fn()
            print("ok", ad)
    print("ag_cevre testleri: ALL PASSED")
