"""Aşama 1: genişleyen komut/hedef uzayı + tek kaynak maskesi.

Kontroller:
1) BEYAZ büyüdü: tail/stat/du eklendi
2) Maske tek kaynaktan (harita) gelir: DOSYA_OLC → {stat,wc,du},
   PAKET_VERSIYON → {dpkg,apt-cache} (ZINCIR kısıtı KALKTI — global)
3) DOSYA_OKU kapıları örneğe göre açılır: head yok↔kapalı, tail yok↔kapalı
4) DOSYA_OLC uçtan uca: stat/wc/du üçü de aynı bayt sayısını doğrular
5) PAKET_VERSIYON uçtan uca: dpkg -s ve apt-cache policy sürümü doğrular
6) bilinmeyen komut güvenle ["true"] (kaza ödülü yok)
7) ödül/deneme akışı: doğru→ODUL, başarıda don() ile hedef tazelenir
8) zincir hedefi (SUREC_SAY) maskeyi haritadan alır; wc dışı ara veri
   ILERLEME kazandırır (Aşama 2 bozulmadı)
9) TAMPON GATING (2026-10-15): ara bellek doluyken veri üretmek
   ÖDÜLSÜZ — üretim döngüsü ILERLEME ile beslenemez
10) gz dosya: _h_dosya_oku sihirbaytını tanır → kapı TEK: zcat;
    zcat çözülmüş çıktıda örnek satırı verince kazanır
11) zincir haritalarından head DÜŞTÜ (333+405 deneme, 0 kazanç);
    DOSYA_OKU'daki head kapısı (örnek varsa) duruyor
"""
import sys, os, tempfile, subprocess
sys.path.insert(0, "/home/emrah/Genel/core")
os.environ["GOLGE_LOG"] = ""   # kapı günlüğü testlerde kapalı (kirlilik yok)
import kullan as K


def yeni_kullan():
    return K.Kullan({})


# 1) BEYAZ genişledi
for c in ("tail", "stat", "du", "wc", "head", "grep", "dpkg", "df"):
    assert c in K.BEYAZ, "BEYAZ eksik: " + c
print("1 BEYAZ genişledi (tail/stat/du eklendi) OK")

# 2) maske = harita anahtarları (global, ZINCIR kısıtı yok)
k = yeni_kullan()
k.hedef = {"tip": "DOSYA_OLC", "yol": "/etc/hostname", "boyut": 1}
assert set(k.eylemler()) == {"cmd:stat", "cmd:wc", "cmd:du"}, k.eylemler()
k.hedef = {"tip": "PAKET_VERSIYON", "paket": "coreutils", "surum": "9.1"}
assert set(k.eylemler()) == {"cmd:dpkg", "cmd:apt-cache"}, k.eylemler()
# harita dışı tip (SUREC_SAY) maskeyi haritadan alır (tam liste):
k.hedef = {"tip": "SUREC_SAY", "ad": "systemd"}
k.ara = ""    # bos tampon: wc olcu kapisi KAPALI (2026-10-16 olcumu)
m = set(k.eylemler())
assert m == set("cmd:" + c for c in k._harita(k.hedef)), m
assert "cmd:wc" not in m and "cmd:ps" in m, m   # uretim oncesi wc yok
k.ara = "111\n"   # uretim adimi gecti → wc kapisi acilir
m = set(k.eylemler())
assert "cmd:wc" in m and "cmd:ps" in m, m
k.ara = ""
print("2 maske tek kaynaktan (harita), wc tampon-kapili OK")

# 3) DOSYA_OKU: örneğe göre kapı
k.hedef = {"tip": "DOSYA_OKU", "yol": "/etc/hostname",
           "ornek_bas": None, "ornek_son": "x"}
assert set(k.eylemler()) == {"cmd:wc", "cmd:tail"}, k.eylemler()
k.hedef = {"tip": "DOSYA_OKU", "yol": "/etc/hostname",
           "ornek_bas": "debian", "ornek_son": None}
assert set(k.eylemler()) == {"cmd:wc", "cmd:head"}, k.eylemler()
print("3 DOSYA_OKU kapıları örneğe göre OK")

# 4) DOSYA_OLC uçtan uca: üç kapı da aynı gerçeği doğrular
fd, yol = tempfile.mkstemp(prefix="kullan_olc_")
os.write(fd, b"merhaba dunya\n" * 37)
os.close(fd)
k = yeni_kullan()
hedef_olc = {"tip": "DOSYA_OLC", "yol": yol, "boyut": os.path.getsize(yol)}
for komut in ("stat", "wc", "du"):
    # başarıda uygula don() ile hedefi tazeler → her kapı aynı hedefe
    # karşı koşmalı, bu yüzden döngüde hedefi yeniden kur
    k.hedef = dict(hedef_olc)
    k.hedef_deneme = 0
    r = k.uygula("cmd:" + komut)
    assert r["dogru"] is True, (komut, r)
    assert r["gain"] == K.ODUL, (komut, r)
os.unlink(yol)
print("4 DOSYA_OLC stat/wc/du üçü doğruladı OK")

# 5) PAKET_VERSIYON uçtan uca: dpkg -s ve apt-cache policy
k = yeni_kullan()
adlar = k._paket_listesi()
if adlar:
    paket = adlar[0]
    r0 = subprocess.run(["dpkg-query", "-W", "-f=${Version}", paket],
                        capture_output=True, text=True)
    surum = (r0.stdout or "").strip()
    if surum:
        k.hedef = {"tip": "PAKET_VERSIYON", "paket": paket, "surum": surum}
        for komut in ("dpkg", "apt-cache"):
            k.hedef = {"tip": "PAKET_VERSIYON", "paket": paket,
                       "surum": surum}
            k.hedef_deneme = 0
            r = k.uygula("cmd:" + komut)
            assert r["dogru"] is True, (komut, r)
        print("5 PAKET_VERSIYON dpkg/apt-cache doğruladı OK (" + paket + ")")
    else:
        print("5 PAKET_VERSIYON atlandı (sürüm yok) OK")
else:
    print("5 PAKET_VERSIYON atlandı (paket yok) OK")

# 6) bilinmeyen komut → ["true"], ödül yok
k = yeni_kullan()
k.hedef = {"tip": "DOSYA_OLC", "yol": "/etc/hostname", "boyut": 1}
r = k.uygula("cmd:rm")
assert r["dogru"] is False and r["gain"] == 0.0, r
assert k._argv_kur("rm") == ["true"], k._argv_kur("rm")
print("6 bilinmeyen komut güvenli (true, ödül yok) OK")

# 7) ödül/deneme akışı: başarısızda ilerleme yok (zincir dışı), don() tazeleme
k = yeni_kullan()
k.hedef = {"tip": "DISK_SOR", "birim": "/dev/nonexistent-xyz"}
k.hedef_deneme = 0
r = k.uygula("cmd:df")
assert r["dogru"] is False and r["gain"] == 0.0, r
print("7 doğrulanamayan hedef ödül vermedi OK")

# 8) zincir hedefi ara veri ödülü + bos tamponda wc kapisi kapali
k = yeni_kullan()
hedef_say = {"tip": "SUREC_SAY", "ad": "systemd"}
k.hedef = dict(hedef_say)
k.ara = ""   # tampon bos
k.hedef_deneme = 0
assert "cmd:wc" not in k.eylemler()   # bos tamponda wc sunulmuyor (olcu kapisi)
r = k.uygula("cmd:wc")                # maskenin disindan cagirilsa guvenli no-op
assert r["gain"] == 0.0 and r["dogru"] is False, r
k.hedef = dict(hedef_say)
k.ara = ""
k.hedef_deneme = 0
r = k.uygula("cmd:ps")   # ps sayı vermez → ara veri → ILERLEME
assert r["gain"] == K.ILERLEME, r
print("8 zincir ara-veri ödülü + bos tampon wc kapisi OK")

# 9) TAMPON GATING: ara bellek doluken veri üretmek ödülsüz
k = yeni_kullan()
hedef_say = {"tip": "SUREC_SAY", "ad": "systemd"}
k.hedef = dict(hedef_say)
k.ara = "111\n222\n333\n"   # tampon DOLU: önceki adım veri üretmiş
k.hedef_deneme = 0
r = k.uygula("cmd:pgrep")   # yine dolu çıktı üretir → tekrar, ÖDÜL YOK
assert r["gain"] == 0.0, r
assert r["dogru"] is False  # pgrep sayı vermez → hedef hâlâ açık
# tampon BOZKEN aynı hamle hâlâ ödüllü (Aşama 2 sinyali korunur)
k.hedef = dict(hedef_say)
k.ara = ""
k.hedef_deneme = 0
r = k.uygula("cmd:ps")
assert r["gain"] == K.ILERLEME, r
print("9 tampon gating (doluyken üretim ödülsüz) OK")

# 10) gz → sihirbayt tanınır, kapı tek (zcat), uçtan uca kazanç
import gzip as _gz
fd, yol_gz = tempfile.mkstemp(prefix="kullan_gz_", suffix=".gz")
os.close(fd)
with _gz.open(yol_gz, "wt", encoding="utf-8") as g:
    for i in range(300):
        g.write("satir %d - gz ders seti icerigi\n" % i)
k = yeni_kullan()
# _h_dosya_oku dosya listesinden rastgele seçer → bu dosyayı tek başına sun
k._dosya_listesi = lambda: [yol_gz]
h = k._h_dosya_oku()
assert h and h.get("sikistirilmis") is True, h
assert h.get("ornek_bas"), h  # ÖRNEK ÇÖZÜLMÜŞ halinden okundu
# kapı: yalnızca çözücü komutlar (wc/head/tail maskede DEĞİL → deneme bütçesi israfı yok)
k.hedef = dict(h)
assert set(k.eylemler()) == {"cmd:zcat", "cmd:xz", "cmd:bzip2", "cmd:zstd"}, k.eylemler()
r = k.uygula("cmd:zcat")
assert r["dogru"] is True and r["gain"] == K.ODUL, r
# wc artık gz'de KAZANAMAZ (eski sahte zafer kapatıldı):
k.hedef = dict(h)
k.hedef_deneme = 0
r = k.uygula("cmd:wc")
assert r["dogru"] is False, ("wc -l gz hâlâ kazanıyordu!", r)
os.unlink(yol_gz)
print("10 gz: sihirbayt→çözülmüş örnek→zcat/xz/bzip2/zstd tek kapı, wc kapandı OK")

# 11) zincir haritalarında head YOK; wc tampona gore; DOSYA_OKU head duruyor
k = yeni_kullan()
for hz in ({"tip": "SUREC_SAY", "ad": "systemd"},
           {"tip": "DOSYA_SAY", "dizin": "/etc"}):
    k.ara = ""
    hk = k._harita(hz)
    assert "head" not in hk, (hz, hk)
    assert "wc" not in hk, (hz, hk)   # bos tampon: olcu kapisi kapali
    k.ara = "uretim cikti\n"
    hk = k._harita(hz)
    assert "wc" in hk, (hz, hk)       # tampon dolu: wc acik
k.ara = ""
k.hedef = {"tip": "DOSYA_OKU", "yol": "/etc/hosts",
           "ornek_bas": "localhost", "ornek_son": None}
assert "cmd:head" in k.eylemler()  # içerik kapısı (DOSYA_OKU) korunur
print("11 zincir: head düştü, wc tampon-kapili, DOSYA_OKU head duruyor OK")

# 12) AELAAN kapısı (golge.py) entegrasyonu: _kos artık kapıdan geçer
import shlex
import golge

# 12a) okuma komutu kapıdan geçer, çıktı aynen döner, sınıf = okuma
k = yeni_kullan()
k.hedef = {"tip": "DIZIN_LISTE", "dizin": "/etc", "icindekiler": ["hostname"]}
r = k.uygula("cmd:ls")
assert r["dogru"] is True and r["gain"] == K.ODUL, r
assert k._son_kap and k._son_kap["calisti"], k._son_kap
assert k._son_kap["sinif"] == "okuma", k._son_kap
print("12a kapıdan geçiş (okuma, ödül) OK")

# 12b) stdin (ara bellek) kapıdan akar: ps → tampon → wc gerçekten sayar
k = yeni_kullan()
k.hedef = {"tip": "SUREC_SAY", "ad": "systemd"}
gercek = K._surec_say("systemd")
assert gercek >= 1, gercek
k.ara = subprocess.run(["ps", "-C", "systemd", "-o", "pid="],
                       capture_output=True, text=True).stdout
assert k.ara.strip(), "ps pid vermedi"
r = k.uygula("cmd:wc")     # dosyasız wc: girdi = kapı stdin'i (ara bellek)
assert r["dogru"] is True and r["gain"] == K.ODUL, (r, gercek, repr(k.ara))
print("12b stdin zinciri kapıdan aktı (wc %d saydı) OK" % gercek)

# 12c) yasaklı duvar: engel → alt süreç başlamaz, KAPI_CEZA, tampon korunur
k = yeni_kullan()
cagrilan = []
class _Duvar(object):
    def calistir(self, karar):
        cagrilan.append(karar)
        return {"sinif": "yasakli", "neden": "test duvarı", "engel": True,
                "atlandi": False, "calisti": False, "rc": None,
                "cikti": None, "hata": None, "mod": "golge", "id": "t-1"}
k._kapi = _Duvar()
k.hedef = {"tip": "DOSYA_OLC", "yol": "/etc/hostname", "boyut": 1}
k.ara = "tampon-surdurulecek\n"
r = k.uygula("cmd:stat")
assert r["dogru"] is False and r["gain"] == -K.KAPI_CEZA, r
assert r.get("engel") is True, r
assert k.ara == "tampon-surdurulecek\n", "ara bellek silindi: %r" % k.ara
assert k.denemeler == 1 and k.hedef_deneme == 1, (k.denemeler, k.hedef_deneme)
assert cagrilan and cagrilan[0]["komut"].startswith("stat"), cagrilan
assert cagrilan[0]["stdin"].startswith("tampon"), cagrilan[0]
print("12c duvar cezaladı (gain=%s), tampon korundu OK" % r["gain"])

# 12d) atlandi (mod dışı) → ceza yok, sadece ölçüm
k = yeni_kullan()
class _Atla(object):
    def calistir(self, karar):
        return {"sinif": "yikici", "neden": "mod: kuru", "engel": False,
                "atlandi": True, "calisti": False, "rc": None,
                "cikti": None, "hata": None, "mod": "kuru", "id": "t-2"}
k._kapi = _Atla()
k.hedef = {"tip": "DOSYA_OLC", "yol": "/etc/hostname", "boyut": 1}
r = k.uygula("cmd:stat")
assert r["dogru"] is False and r["gain"] == 0.0, r
assert r.get("engel") is False, r
print("12d atlandi cezasız (sadece ölçüm) OK")

# 12e) BEYAZ × golge uyumu: haritadan çıkan HER argv okuma sınıfında
k = yeni_kullan()
kor = golge.korunan_surecler()
ornek_hedefler = [
    {"tip": "DOSYA_BUL", "ad": "ls", "kok": "/usr/bin"},
    {"tip": "PAKET_SOR", "yol": "/usr/bin/ls"},
    {"tip": "DIZIN_LISTE", "dizin": "/etc", "icindekiler": []},
    {"tip": "DOSYA_OKU", "yol": "/etc/hostname", "ornek_bas": None,
     "ornek_son": None},
    {"tip": "DOSYA_SAY", "dizin": "/etc"},
    {"tip": "SUREC_SAY", "ad": "systemd"},
    {"tip": "SUREC_SOR", "ad": "systemd"},
    {"tip": "SERVIS_SOR", "birim": "ssh", "beklenen": "active"},
    {"tip": "DISK_SOR", "birim": "/"},
    {"tip": "AG_SOR", "arayuz": "lo"},
    {"tip": "DOSYA_OLC", "yol": "/etc/hostname", "boyut": 1},
    {"tip": "PAKET_VERSIYON", "paket": "coreutils", "surum": "9.1"},
    {"tip": "METIN_ARA", "yol": "/etc/hostname", "kalip": "x"},
]
for h in ornek_hedefler:
    for argv in k._harita(h).values():
        komut = " ".join(shlex.quote(a) for a in argv)
        s, neden = golge.siniflandir(komut, kor)
        assert s == golge.OKUMA, (h["tip"], argv, s, neden)
print("12e BEYAZ × golge uyumu: 13 hedef tipi hepsi okuma OK")

# 13) BEYAZ: tüm 13 yeni komut mevcut
yeni_komutlar = ("nstat", "lnstat", "netstat", "resolveip",
                 "lsof", "pstree", "tree",
                 "realpath", "readlink", "lsblk",
                 "xz", "bzip2", "zstd")
for c in yeni_komutlar:
    assert c in K.BEYAZ, "BEYAZ eksik: " + c
print("13 BEYAZ: 13 yeni komut eklendi OK")

# 14) AG_SOR: _harita nstat/lnstat/netstat/resolveip + ip
k = yeni_kullan()
k.hedef = {"tip": "AG_SOR", "arayuz": "lo"}
m = set(k.eylemler())
assert "cmd:ip" in m and "cmd:nstat" in m and "cmd:lnstat" in m, m
assert "cmd:netstat" in m and "cmd:resolveip" in m, m
# argv doğruları
assert k._harita(k.hedef)["nstat"] == ["nstat"]
assert k._harita(k.hedef)["lnstat"] == ["lnstat"]
assert k._harita(k.hedef)["netstat"] == ["netstat", "-i"]
assert k._harita(k.hedef)["resolveip"] == ["resolveip", "-n", "lo"]
print("14 AG_SOR: _harita nstat/lnstat/netstat/resolveip OK")

# 15) AG_SOR: _dogrula her komut için
k.hedef = {"tip": "AG_SOR", "arayuz": "lo"}
# ip addr show lo → geçerli
r = k._dogrula("1: lo: <LOOPBACK,UP> mtu 65536 ...\n    inet 127.0.0.1/8 ...", ["ip", "addr", "show", "lo"])
assert r is True, r
# nstat → sayaç satırları
r = k._dogrula("IpInOctets: 12345\nIpOutOctets: 67890\n", ["nstat"])
assert r is True, r
# lnstat → sayısal sütunlar
r = k._dogrula("0 1 2 3\n4 5 6 7\n", ["lnstat"])
assert r is True, r
# netstat -i → Kernel/Iface başlığı veya arayüz adı
r = k._dogrula("Kernel Iface\nlo ...", ["netstat", "-i"])
assert r is True, r
# resolveip → IPv4 adresi
r = k._dogrula("127.0.0.1", ["resolveip", "-n", "lo"])
assert r is True, r
print("15 AG_SOR: _dogrula her komut için geçerli OK")

# 16) SUREC_SOR: _harita lsof/pstree + ps/pgrep
k = yeni_kullan()
k.hedef = {"tip": "SUREC_SOR", "ad": "systemd"}
m = set(k.eylemler())
assert "cmd:lsof" in m and "cmd:pstree" in m, m
assert k._harita(k.hedef)["lsof"] == ["lsof", "-c", "systemd"]
assert k._harita(k.hedef)["pstree"] == ["pstree", "systemd"]
print("16 SUREC_SOR: _harita lsof/pstree OK")

# 17) SUREC_SOR: _dogrula lsof/pstree/ps
k.hedef = {"tip": "SUREC_SOR", "ad": "systemd"}
r = k._dogrula("systemd  1234  root  ...", ["lsof", "-c", "systemd"])
assert r is True, r
# pstree systemd → çıktıda "systemd" geçmeli
r = k._dogrula("systemd─┬─...", ["pstree", "systemd"])
assert r is True, r
# ps -C systemd -o comm= → "systemd" satırı
r = k._dogrula("systemd\n", ["ps", "-C", "systemd", "-o", "comm="])
assert r is True, r
print("17 SUREC_SOR: _dogrula lsof/pstree/ps OK")

# 18) DISK_SOR: _harita lsblk + df
k = yeni_kullan()
k.hedef = {"tip": "DISK_SOR", "birim": "/"}
m = set(k.eylemler())
assert "cmd:lsblk" in m and "cmd:df" in m, m
assert k._harita(k.hedef)["lsblk"] == ["lsblk"]
assert k._harita(k.hedef)["df"] == ["df", "-h", "/"]
print("18 DISK_SOR: _harita lsblk/df OK")

# 19) DISK_SOR: _dogrula lsblk (df'de "%" gerekmez)
k.hedef = {"tip": "DISK_SOR", "birim": "/"}
r = k._dogrula("NAME   MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS\nsda1     8:1    0 100G  0 part /\n", ["lsblk"])
assert r is True, r
r = k._dogrula("/dev/sda1  100G  50%  /", ["df", "-h", "/"])
assert r is True, r
print("19 DISK_SOR: _dogrula lsblk/df OK")

# 20) DIZIN_LISTE: _harita tree
k = yeni_kullan()
k.hedef = {"tip": "DIZIN_LISTE", "dizin": "/etc", "icindekiler": ["passwd", "hostname"]}
assert "cmd:tree" in set(k.eylemler())
assert k._harita(k.hedef)["tree"] == ["tree", "/etc"]
r = k._dogrula("passwd\nhostname\n", ["tree", "/etc"])
assert r is True, r
print("20 DIZIN_LISTE: tree OK")

# 21) DOSYA_BUL: _harita realpath/readlink
k = yeni_kullan()
k.hedef = {"tip": "DOSYA_BUL", "ad": "ls", "kok": "/usr/bin"}
m = set(k.eylemler())
assert "cmd:realpath" in m and "cmd:readlink" in m, m
assert k._harita(k.hedef)["realpath"] == ["realpath", "/usr/bin/ls"]
assert k._harita(k.hedef)["readlink"] == ["readlink", "/usr/bin/ls"]
r = k._dogrula("/usr/bin/ls", ["realpath", "/usr/bin/ls"])
assert r is True, r
print("21 DOSYA_BUL: realpath/readlink OK")

# 22) DOSYA_OKU: xz/bzip2/zstd sıkıştırılmış dosya için _dogrula
k = yeni_kullan()
k.hedef = {"tip": "DOSYA_OKU", "yol": "/tmp/dummy.xz",
           "sikistirilmis": True, "ornek_bas": "örnek satır 1"}
# xz -dc, bzip2 -dc, zstd -dc çıktısı: çözülmüş metin, örnek satır içermeli
for komut in ("xz", "bzip2", "zstd"):
    r = k._dogrula("örnek satır 1\nörnek satır 2\n", [komut, "-dc", "/tmp/dummy.xz"])
    assert r is True, (komut, r)
# yanlış komut (wc) sıkıştırılmış dosyada kabul edilmez
r = k._dogrula("örnek satır 1\n", ["wc", "-l", "/tmp/dummy.xz"])
assert r is False, r
print("22 DOSYA_OKU: xz/bzip2/zstd _dogrula OK")

# 23) SISTEM_SOR: _harita + _dogrula (cpu/bellek/çekirdek, judge-time gerçek)
k = yeni_kullan()
k.hedef = {"tip": "SISTEM_SOR", "konu": "cpu", "cekirdek": 4}
assert set(k.eylemler()) == {"cmd:lscpu"}, k.eylemler()
assert k._harita(k.hedef) == {"lscpu": ["lscpu"]}
import os as _os
r = k._dogrula("CPU(s):                %d\n" % (_os.cpu_count() or 1),
                ["lscpu"])
assert r is True, r
r = k._dogrula("CPU(s):                99999\n", ["lscpu"])
assert r is False, r
k.hedef = {"tip": "SISTEM_SOR", "konu": "bellek", "kb": 123}
assert k._harita(k.hedef) == {"free": ["free"]}
# free çıktısı /proc/meminfo MemTotal ile judge-time eşleşir
import subprocess as _sp
_free = _sp.run(["free"], capture_output=True, text=True, timeout=8).stdout
r = k._dogrula(_free, ["free"])
assert r is True, r
r = k._dogrula("Mem:  1 1 1 1 1 1\n", ["free"])
assert r is False, r
k.hedef = {"tip": "SISTEM_SOR", "konu": "cekirdek", "surum": "x"}
assert k._harita(k.hedef) == {"uname": ["uname", "-r"]}
import platform as _pf
r = k._dogrula(_pf.release() + "\n", ["uname", "-r"])
assert r is True, r
r = k._dogrula("0.0.0-bilmemne\n", ["uname", "-r"])
assert r is False, r
print("23 SISTEM_SOR: lscpu/free/uname _dogrula OK")

# 24) DOSYA_OZET: md5sum/sha256sum — judge hashlib ile dosyayı okur
import hashlib as _hl
k = yeni_kullan()
_tmp = tempfile.NamedTemporaryFile(delete=False)
_tmp.write(b"merhaba debian\n")
_tmp.close()
k.hedef = {"tip": "DOSYA_OZET", "yol": _tmp.name}
assert set(k.eylemler()) == {"cmd:md5sum", "cmd:sha256sum"}
_d5 = _hl.md5(b"merhaba debian\n").hexdigest()
_d256 = _hl.sha256(b"merhaba debian\n").hexdigest()
r = k._dogrula("%s  %s\n" % (_d5, _tmp.name), ["md5sum", _tmp.name])
assert r is True, r
r = k._dogrula("%s  %s\n" % (_d256, _tmp.name), ["sha256sum", _tmp.name])
assert r is True, r
# yanlış hash (sahte çıktı) → False; yanlış kapı (hexdump) → False
r = k._dogrula("00000000000000000000000000000000  x\n", ["md5sum", _tmp.name])
assert r is False, r
r = k._dogrula("%s  %s\n" % (_d5, _tmp.name), ["hexdump", _tmp.name])
assert r is False, r
os.unlink(_tmp.name)
print("24 DOSYA_OZET: md5sum/sha256sum _dogrula OK")

# 25) DOSYA_HAM: hexdump/xxd — ilk 8 baytın hex'i çıktıda (judge-time okur)
k = yeni_kullan()
k.hedef = {"tip": "DOSYA_HAM", "yol": "/bin/ls"}
assert set(k.eylemler()) == {"cmd:hexdump", "cmd:xxd"}
with open("/bin/ls", "rb") as _f:
    _ilk = _f.read(8).hex()
# hexdump -C biçimi (boşluklu) ve xxd biçimi (gruplu) ikisi de geçer
r = k._dogrula("00000000  %s  |....|\n"
               % " ".join(_ilk[i:i + 2] for i in range(0, 16, 2)),
               ["hexdump", "-C", "-n", "64", "/bin/ls"])
assert r is True, r
r = k._dogrula("00000000: %s%s  ....\n"
               % (_ilk[:4].upper(), _ilk[4:].upper()),
               ["xxd", "-l", "64", "/bin/ls"])
assert r is True, r
# yanlış içerik → False; sıkıştırılmış kapısı (zcat) → False
r = k._dogrula("00000000  ff ff ff ff ff ff ff ff  |........|\n",
               ["hexdump", "-C", "-n", "64", "/bin/ls"])
assert r is False, r
r = k._dogrula("satır\n", ["zcat", "/bin/ls"])
assert r is False, r
print("25 DOSYA_HAM: hexdump/xxd _dogrula OK")

# 26) BEYAZ yeni komutlar + brain aile jetonları
for c in ("lscpu", "free", "uname", "md5sum", "sha256sum", "hexdump", "xxd"):
    assert c in K.BEYAZ, "BEYAZ eksik: " + c
import brain as B
assert B.Brain.AILE.get("SISTEM_SOR") == "SISTEM"
assert B.Brain.AILE.get("DOSYA_OZET") == "DOSYA"
assert B.Brain.AILE.get("DOSYA_HAM") == "DOSYA"
# golge kapı sınıfı: hexdump/xxd okuma (yasaklı değil)
import golge as G
assert "hexdump" in G.OKUMA_FIIL and "xxd" in G.OKUMA_FIIL
print("26 BEYAZ/brain/golge entegrasyonu OK")

print("KULLAN TEST: 26/26 OK")
