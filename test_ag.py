"""AG_TARA (Faz 0+1): kapsam kilidi + nmap/ping/ip kapıları + duraklama.

Kontroller (fixture'lar 2026-10-15 canlı yakalamadan: nmap/ping/ip):
1) BEYAZ'a nmap/ping eklendi
2) Kapsam VARSAYILAN RED: dosya yok / bozuk / acik:false → tarama yok
3) Allowlist teyidi: kapsam içi ✓, dışı ✗, v6 ✗, bozuk ip ✗;
   idari red (dosya değişimi) ANINDA geçerli — restart gerekmez
4) Aday üretimi: 192.168.1.0/24 (254) + 127.0.0.1 (döngü tek aday),
   soğuma aynı ip'yi ikinci seçimde dışlar (least-tried + cooldown)
5) _harita kapıları: nmap/ping/traceroute argv'si hız/süre limitli; 'ip' kapısı
   yalnızca komsu_var (kanıt) varken; kapsam dışı → kapı YOK
6) _dogrula fixture'ları: nmap/ping/ip çıktıları zemin gerçeğiyle
   eşleşince kazanç; uyuşmazlık/kanıt yoksa asla kazanç
7) maske = {cmd:nmap, cmd:ping[, cmd:ip][, cmd:traceroute]}; _hedef_kur AG_TARA üretir
8) duraklama: 3. başarısızlık → duraklama kanıtı + hedef tazelenir;
   başarıda duraklama YOK, ödül ODUL
9) kapsam kilitliyken uygula ["true"] çalıştırır (nmap ASLA çalışmaz)
10) canlı uçtan uca: gerçek nmap/ping/ip → ODUL (ağ yoksa atlanır)
11) BENI_TARA kapsamı: ben_tarama VARSAYILAN RED (ayrı bayrak);
    port aralıkları least-tried + soğuma ile keşfedilir
12) _harita BENI argv'leri (nmap -sV / ss / curl) + maske tek kaynaktan;
    ben_tarama kapalıyken kapı YOK; _hedef_kur BENI üretir
13) _dogrula BENI: nmap/ss/curl iddiaları /proc LISTEN zemin gerçeğiyle
    eşitlenir; kanıt yoksa (/proc okunamaz) asla kazanç
14) canlı uçtan uca: gerçek nmap -sV/ss/curl → ODUL (/proc yoksa atlanır)
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, "/home/emrah/Genel/core")
os.environ["GOLGE_LOG"] = ""   # kapı günlüğü testlerde kapalı (kirlilik yok)
import kullan as K

# ---- canlı yakalama fixture'ları (2026-10-15, gerçek çıktılar) ----
NMAP_CANLI = """Starting Nmap 7.97SVN ( https://nmap.org ) at 2026-10-15 15:11 +0300
Nmap scan report for 192.168.1.1
Host is up (0.00042s latency).
Nmap done: 1 IP address (1 host up) scanned in 0.02 seconds"""

NMAP_OLU = """Starting Nmap 7.97SVN ( https://nmap.org ) at 2026-10-15 15:11 +0300
Note: Host seems down. If it is really up, but blocking our ping probes, try -Pn
Nmap done: 1 IP address (0 hosts up) scanned in 3.00 seconds"""

PING_CANLI = """PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.
64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=3.41 ms
64 bytes from 192.168.1.1: icmp_seq=2 ttl=64 time=3.18 ms

--- 192.168.1.1 ping statistics ---
2 packets transmitted, 2 received, 0% packet loss, time 1002ms
rtt min/avg/max/mdev = 3.180/3.294/3.408/0.114 ms"""

PING_OLU = """PING 192.168.1.250 (192.168.1.250) 56(84) bytes of data.
From 192.168.1.3 icmp_seq=1 Destination Host Unreachable

--- 192.168.1.250 ping statistics ---
2 packets transmitted, 0 received, +1 errors, 100% packet loss, time 1002ms"""

NEIGH_CANLI = "192.168.1.1 dev eno1 lladdr d8:4a:2b:1b:1a:2b REACHABLE"
NEIGH_OLU = "192.168.1.250 dev eno1  INCOMPLETE"

# BENI_TARA fixture'ları (2026-10-15 canlı: nmap -sV 127.0.0.1 + ss -Htan)
NMAP_BENI = """Starting Nmap 7.97SVN ( https://nmap.org ) at 2026-10-15 16:05 +03
Nmap scan report for localhost (127.0.0.1)
Host is up (0.000086s latency).
Not shown: 997 closed tcp ports (reset)
PORT    STATE SERVICE       VERSION
22/tcp  open  ssh           OpenSSH 8.4p1 Debian 5+deb11u7 (protocol 2.0)
139/tcp open  netbios-ssn   Samba smbd 4
445/tcp open  microsoft-ds  Samba smbd 4
Service Info: OS: Linux; CPE: cpe:/o:linux:linux_kernel

Nmap done: 1 IP address (1 host up) scanned in 11.29 seconds"""

SS_BENI = """0\t50\t0.0.0.0:22\t0.0.0.0:*\tusers:((\"sshd\",pid=700,fd=3))
0\t50\t0.0.0.0:139\t0.0.0.0:*\tusers:((\"smbd\",pid=800,fd=4))
0\t50\t0.0.0.0:445\t0.0.0.0:*\tusers:((\"smbd\",pid=800,fd=5))
0\t5\t127.0.0.1:8080\t0.0.0.0:*\tusers:((\"python3\",pid=1234,fd=14))"""


def yeni_kullan():
    return K.Kullan({})   # gerçek kök: ag_kapsam.json mevcut (açık)


# 1) BEYAZ büyüdü: nmap/ping
for c in ("nmap", "ping", "ip"):
    assert c in K.BEYAZ, "BEYAZ eksik: " + c
print("1 BEYAZ: nmap/ping/ip mevcut OK")


# 2) kapsam VARSAYILAN RED: dosya yok / bozuk / acik:false
bos = tempfile.mkdtemp(prefix="ag_kapsam_")
k = K.Kullan({}, root=bos)
assert k._ag_kapali() is True, "dosya yokken açık olmamalı"
assert k._h_ag_tara() is None, "dosya yokken hedef üretilmemeli"
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    f.write("{bozuk json")
assert K.Kullan({}, root=bos)._ag_kapali() is True, "bozuk dosya → kapalı"
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": False, "izin_aglari": ["10.0.0.0/24"]}, f)
k = K.Kullan({}, root=bos)
assert k._ag_kapali() is True, "acik:false → kapalı"
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": True, "izin_aglari": []}, f)
assert K.Kullan({}, root=bos)._ag_kapali() is True, "boş allowlist → kapalı"
print("2 kapsam: dosya yok/bozuk/acik:false/boş izin → RED OK")


# 3) allowlist teyidi + canlı idari red (restartsiz kilit)
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": True, "izin_aglari": ["10.0.0.0/24"],
               "ayni_hedef_aralik_sn": 0}, f)
k = K.Kullan({}, root=bos)
assert not k._ag_kapali()
assert k._ag_ip_izinli("10.0.0.5") is True
assert k._ag_ip_izinli("192.168.1.1") is False   # sadece 10.0.0.0/24
assert k._ag_ip_izinli("8.8.8.8") is False
assert k._ag_ip_izinli("fe80::1") is False        # v6 ∉ v4 kapsamı
assert k._ag_ip_izinli("yanlis-ip") is False
kreal = yeni_kullan()
assert kreal._ag_ip_izinli("192.168.1.1") is True   # gerçek kapsam
assert kreal._ag_ip_izinli("127.0.0.1") is True
assert kreal._ag_ip_izinli("8.8.8.8") is False
# idari red: dosya anında değişir → anında kilit (restart GEREKMEZ)
time.sleep(0.01)
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": False, "izin_aglari": ["10.0.0.0/24"]}, f)
assert k._ag_kapali() is True, "canlı red işlemedi"
assert k._ag_ip_izinli("10.0.0.5") is False
assert k._h_ag_tara() is None
print("3 allowlist + canlı idari red (restartsiz) OK")


# 4) aday üretimi + soğuma + least-tried
k = yeni_kullan()
adaylar = k._ag_adaylar()
assert len(adaylar) == 255, len(adaylar)          # 254 + 127.0.0.1
assert "127.0.0.1" in adaylar and "127.0.0.2" not in adaylar
h1 = k._h_ag_tara()
assert h1 and h1["tip"] == "AG_TARA" and h1["ip"] in adaylar
assert isinstance(h1["komsu_var"], bool)
h2 = k._h_ag_tara()
assert h2 and h2["ip"] != h1["ip"], "soğuma aynı ip'yi ikinci seçime bırakmamalı"
h3 = k._h_ag_tara()
assert h3 and h3["ip"] not in (h1["ip"], h2["ip"])
print("4 adaylar (255) + soğuma + least-tried OK")


# 5) _harita kapıları: hız limiti + örnek kapısı (komsu_var) + kapsam dışı
k = yeni_kullan()
h = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
harita = k._harita(h)
assert set(harita) == {"nmap", "ping", "ip", "traceroute"}, harita
nm = harita["nmap"]
assert nm[0] == "nmap" and "-sn" in nm and "-n" in nm and nm[-1] == "192.168.1.1"
assert "--max-rate" in nm and "--host-timeout" in nm
assert nm[nm.index("--max-rate") + 1].isdigit()          # hız tavanı sayı
pg = harita["ping"]
assert pg[0] == "ping" and "-c" in pg and "-W" in pg and pg[-1] == "192.168.1.1"
assert harita["ip"] == ["ip", "neigh", "show", "192.168.1.1"]
# kanıt yokken ARP kapısı hiç sorulmaz (örnek kapısı mantığı)
h2 = dict(h, komsu_var=False)
assert set(k._harita(h2)) == {"nmap", "ping", "traceroute"}, k._harita(h2)
# kapsam dışı / kapsam kilitli → HİÇ kapı yok (argv ["true"]'ye düşer)
assert k._harita({"tip": "AG_TARA", "ip": "8.8.8.8",
                  "komsu_var": True}) == {}
kbos = K.Kullan({}, root=bos)
assert kbos._harita({"tip": "AG_TARA", "ip": "192.168.1.1",
                     "komsu_var": True}) == {}
print("5 kapılar: nmap/ping argv limitli, ip kanıtlı, kapsam dışı kapalı OK")


# 6) _dogrula: gerçek çıktı fixture'ları × zemin gerçeği
k = yeni_kullan()
k.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
k._ag_gercek = lambda ip: True        # zemin: CANLI
assert k._dogrula(NMAP_CANLI, ["nmap"]) is True
assert k._dogrula(NMAP_OLU, ["nmap"]) is False      # canlı diyip ölüler gibi
assert k._dogrula(PING_CANLI, ["ping"]) is True
assert k._dogrula(PING_OLU, ["ping"]) is False
assert k._dogrula(NEIGH_CANLI, ["ip"]) is True
k._ag_gercek = lambda ip: False       # zemin: ÖLÜ
assert k._dogrula(NMAP_OLU, ["nmap"]) is True
assert k._dogrula(NMAP_CANLI, ["nmap"]) is False    # ölü diyip canlı gibi
assert k._dogrula(PING_OLU, ["ping"]) is True
assert k._dogrula(PING_CANLI, ["ping"]) is False
# ip kapısı ölü kanıtı: hedef de ÖLÜ host'un ip'si olmalı (fixture eşleşmesi)
k.hedef = dict(k.hedef, ip="192.168.1.250")
assert k._dogrula(NEIGH_OLU, ["ip"]) is True
k.hedef = dict(k.hedef, ip="192.168.1.1")
assert k._dogrula(NEIGH_CANLI, ["ip"]) is False     # lladdr+REACHABLE ≠ ölü
k._ag_gercek = lambda ip: None        # kanıt yok → emin olunmadan kazanç yok
for cikti, argv in ((NMAP_CANLI, ["nmap"]), (PING_CANLI, ["ping"]),
                    (NEIGH_CANLI, ["ip"])):
    assert k._dogrula(cikti, argv) is False
# kapsam dışı ip asla kazanamaz (gerçek ne olursa olsun)
k.hedef = {"tip": "AG_TARA", "ip": "8.8.8.8", "komsu_var": True}
k._ag_gercek = lambda ip: True
assert k._dogrula(NMAP_CANLI, ["nmap"]) is False
print("6 yargı: nmap/ping/ip × canlı/ölü/kanıt-yok + kapsam dışı OK")


# 7) maske tek kaynaktan + _hedef_kur AG_TARA üretir
k = yeni_kullan()
k.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
assert set(k.eylemler()) == {"cmd:nmap", "cmd:ping", "cmd:ip", "cmd:traceroute"}, k.eylemler()
k.hedef = dict(k.hedef, komsu_var=False)
assert set(k.eylemler()) == {"cmd:nmap", "cmd:ping", "cmd:traceroute"}, k.eylemler()
# telafi: diğer tüm kurucular None dönerse AG_TARA sıradaki hedef
k = yeni_kullan()
for ad in ("_h_dosya_bul", "_h_paket_sor", "_h_dizin_liste", "_h_dosya_oku",
           "_h_metin_ara", "_h_surec_sor", "_h_servis_sor", "_h_disk_sor",
           "_h_ag_sor", "_h_surec_say", "_h_dosya_say", "_h_dosya_olc",
           "_h_paket_versiyon", "_h_beni_tara", "_h_dosya_ozet", "_h_dosya_ham",
           "_h_sistem_sor", "_h_konfig_oku", "_h_log_oku", "_h_porta_dinle"):
    setattr(k, ad, lambda: None)
h = k._hedef_kur()
assert h and h["tip"] == "AG_TARA", h
print("7 maske {nmap,ping[,ip]} + _hedef_kur AG_TARA üretimi OK")


# 8) duraklama kanıtı: 3. başarısızlık → duraklama + tazeleme; başarıda yok
k = yeni_kullan()
k.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
k._kos = lambda argv, sure=None: (True, NMAP_OLU, "")   # çıktı "ölü" derken…
k._ag_gercek = lambda ip: True               # …zemin "canlı" diyor → uyuşmazlık
r1 = k.uygula("cmd:nmap")
assert r1["dogru"] is False and r1["gain"] == 0.0 and r1["deneme"] == 1
assert not r1["duraklama"], r1
r2 = k.uygula("cmd:nmap")
assert r2["deneme"] == 2 and not r2["duraklama"]
r3 = k.uygula("cmd:nmap")
assert r3["deneme"] == 3 and r3["duraklama"] is True, r3   # 3'te takılma
assert k.hedef_deneme == 0, "don() hedefi tazelemeli"
# başarı: duraklama YOK, ödül tam
k.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
k._kos = lambda argv, sure=None: (True, NMAP_CANLI, "")
k._ag_gercek = lambda ip: True
r = k.uygula("cmd:nmap")
assert r["dogru"] is True and r["gain"] == K.ODUL and r["duraklama"] is False, r
print("8 duraklama: 3. başarısızlıkta kanıt, başarıda temiz OK")


# 9) kapsam kilitliyken uygula: argv ["true"], nmap ASLA çalışmaz
kbos = K.Kullan({}, root=bos)   # bos'ta dosya acik:false (3. test)
kbos.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1", "komsu_var": True}
r = kbos.uygula("cmd:nmap")     # gerçek _kos: yalnızca "true" koşar
assert r["argv"] == ["true"], r
assert r["dogru"] is False and r["gain"] == 0.0
print("9 kilitli kapsamda uygula → ['true'] (nmap hiç koşmaz) OK")


# 10) canlı uçtan uca: gerçek nmap/ping/ip → ODUL (ağ yoksa atlanır)
k = yeni_kullan()
if k._ag_gercek("192.168.1.1") is not True:
    print("10 UÇTAN UCA ATLANDI — 192.168.1.1 erişilebilir değil")
else:
    for komut in ("cmd:nmap", "cmd:ping", "cmd:ip"):
        k.hedef = {"tip": "AG_TARA", "ip": "192.168.1.1",
                   "komsu_var": True}
        k.hedef_deneme = 0
        k.ara = ""
        r = k.uygula(komut)   # gerçek alt süreç (nmap/ping/ip)
        assert r["dogru"] is True, (komut, r)
        assert r["gain"] == K.ODUL, (komut, r)
    print("10 canlı uçtan uca: nmap/ping/ip üçü de kazandı OK")


# 11) BENI_TARA kapsamı: VARSAYILAN RED + aralık keşfi (least-tried + soğuma)
for c in ("ss", "curl"):
    assert c in K.BEYAZ, "BEYAZ eksik: " + c
bos = tempfile.mkdtemp(prefix="ag_kapsam_")
k = K.Kullan({}, root=bos)          # ben_tarama YOK → varsayılan red
assert k._ben_tarama_acik() is False
assert k._h_beni_tara() is None
assert k._harita({"tip": "BENI_TARA", "ip": "127.0.0.1"}) == {}
with open(os.path.join(bos, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": True, "izin_aglari": ["127.0.0.0/8"],
               "ben_tarama": True}, f)
k = K.Kullan({}, root=bos)
assert k._ben_tarama_acik() is True
uretilen = []
for _ in range(len(K.BENI_ARALIKLAR)):
    h = k._h_beni_tara()
    assert h and h["tip"] == "BENI_TARA" and h["ip"] == "127.0.0.1"
    uretilen.append(h["aralik"])
assert sorted(uretilen) == sorted(K.BENI_ARALIKLAR), uretilen  # her aralık 1×
assert k._h_beni_tara() is None      # hepsi soğumada → hedef yok
print("11 BENI kapsam: varsayılan red + aralık least-tried dolaşımı OK")


# 12) _harita BENI kapıları (argv) + maske tek kaynaktan + _hedef_kur üretimi
k = yeni_kullan()
hb = {"tip": "BENI_TARA", "ip": "127.0.0.1", "aralik": "1-4096"}
hm = k._harita(hb)
assert "-sV" in hm["nmap"] and "-Pn" in hm["nmap"] and "-n" in hm["nmap"]
assert hm["nmap"][hm["nmap"].index("-p") + 1] == "1-4096"
assert hm["nmap"][-1] == "127.0.0.1"         # döngü; dış IP asla yok
assert hm["ss"][:3] == ["ss", "-Htan", "state"]
assert hm["curl"][-1].startswith("http://127.0.0.1:")
k.hedef = hb
assert set(k.eylemler()) == {"cmd:nmap", "cmd:ss", "cmd:curl", "cmd:traceroute"}, k.eylemler()
# ben_http_port=0 → curl kapısı YOK (maske tek kaynaktan; temp kök:
# _ag_kapali her çağrıda kapsamı dosyadan tazeler → monkeypatch boştur)
bos2 = tempfile.mkdtemp(prefix="ag_kapsam_")
with open(os.path.join(bos2, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": True, "izin_aglari": ["127.0.0.0/8"],
               "ben_tarama": True, "ben_http_port": 0}, f)
k2 = K.Kullan({}, root=bos2)
assert set(k2._harita(hb)) == {"nmap", "ss", "traceroute"}, k2._harita(hb)
# ben_tarama:false (açık kapsam) → kapı YOK
bos3 = tempfile.mkdtemp(prefix="ag_kapsam_")
with open(os.path.join(bos3, "ag_kapsam.json"), "w") as f:
    json.dump({"acik": True, "izin_aglari": ["127.0.0.0/8"],
               "ben_tarama": False}, f)
k3 = K.Kullan({}, root=bos3)
assert k3._harita(hb) == {}
# telafi: diğer tüm kurucular None → BENI_TARA sıradaki hedef
k = yeni_kullan()
for ad in ("_h_dosya_bul", "_h_paket_sor", "_h_dizin_liste", "_h_dosya_oku",
           "_h_metin_ara", "_h_surec_sor", "_h_servis_sor", "_h_disk_sor",
           "_h_ag_sor", "_h_surec_say", "_h_dosya_say", "_h_dosya_olc",
           "_h_paket_versiyon", "_h_ag_tara", "_h_dosya_ozet", "_h_dosya_ham",
           "_h_sistem_sor", "_h_konfig_oku", "_h_log_oku", "_h_porta_dinle"):
    setattr(k, ad, lambda: None)
hb2 = k._hedef_kur()
assert hb2 and hb2["tip"] == "BENI_TARA", hb2
print("12 BENI kapı argv'leri + maske {nmap,ss[,curl]} + _hedef_kur OK")


# 13) _dogrula BENI: iddialar /proc LISTEN zemin gerçeğiyle eşitlenecek
k = yeni_kullan()
k.hedef = {"tip": "BENI_TARA", "ip": "127.0.0.1", "aralik": "1-4096"}
k._ben_tarama_acik()   # kapsamı yükle — gerçek akıştaki sıra (harita → judge)
KERN = {22, 139, 445, k._ben_http_port()}    # 8080 (canlı kök)
k._ben_dinleme = lambda: set(KERN)           # zemin gerçeği sabitlenir
assert k._dogrula(NMAP_BENI, ["nmap"]) is True   # canlı fixture: üçü de open
assert k._dogrula(NMAP_BENI + "\n9999/tcp open  unknown",
                  ["nmap"]) is False          # kernel'de olmayan "open" → yalan
assert k._dogrula(NMAP_BENI.replace("445/tcp open", "445/tcp closed"),
                  ["nmap"]) is False          # kernel'de açık porta "closed" → yalan
assert k._dogrula("Nmap done: 1 IP address scanned in 0.00 seconds",
                  ["nmap"]) is False          # argv'de aralık yok → False
# boş tablo + normal bitiş = "aralıkta açık port yok" iddiası
assert k._dogrula("Nmap done: 1 IP address scanned in 0.00 seconds",
                  ["nmap", "-p", "40000-40010"]) is True   # orada dinleyen yok
assert k._dogrula("Nmap done: 1 IP address scanned in 0.00 seconds",
                  ["nmap", "-p", "1-4096"]) is False      # aralıkta dinleyen var
assert k._dogrula("Killed", ["nmap", "-p", "40000-40010"]) is False  # yarım çıktı
assert k._dogrula(SS_BENI, ["ss"]) is True      # iki görünüm eşitliği
assert k._dogrula(SS_BENI.replace("0.0.0.0:139", "0.0.0.0:9999"),
                  ["ss"]) is False             # eksik + sahte iddia
assert k._dogrula(SS_BENI + "\n0\t5\t0.0.0.0:9999\t0.0.0.0:*",
                  ["ss"]) is False             # fazladan iddia
assert k._dogrula("200", ["curl"]) is True     # 200 + o port kernel'de LISTEN
assert k._dogrula("000", ["curl"]) is False    # sunucu yok
k._ben_dinleme = lambda: set(KERN) - {8080}    # o port artık LISTEN değil
assert k._dogrula("200", ["curl"]) is False
k._ben_dinleme = lambda: None                  # kanıt yok → asla kazanç
for argv, cikti in ((["nmap"], NMAP_BENI), (["ss"], SS_BENI), (["curl"], "200")):
    assert k._dogrula(cikti, argv) is False
print("13 BENI yargı: nmap/ss/curl × eşleşme/uyuşmazlık/kanıt yok OK")


# 14) canlı uçtan uca BENI: gerçek nmap -sV/ss/curl → ODUL (/proc okunuyorsa)
k = yeni_kullan()
if k._ben_dinleme() is None:
    print("14 BENI UÇTAN UCA ATLANDI — /proc/net/tcp okunamıyor")
else:
    for komut in ("cmd:nmap", "cmd:ss", "cmd:curl"):
        k.hedef = {"tip": "BENI_TARA", "ip": "127.0.0.1", "aralik": "1-4096"}
        k.hedef_deneme = 0
        k.ara = ""
        r = k.uygula(komut)   # gerçek alt süreç (BENI_KOMUT_SURE bütçesi)
        assert r["dogru"] is True, (komut, r)
        assert r["gain"] == K.ODUL, (komut, r)
        assert not r["duraklama"], r
    print("14 canlı uçtan uca: nmap -sV/ss/curl üçü de kazandı OK")


print("TEST_AG: TÜMÜ GEÇTİ")