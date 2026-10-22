#!/usr/bin/env python3
"""golge_ek.py - golge.py icin bayrak/izin listesi tabanli ek denetimler.

Kullanım (golge.py içinde, `verb in YASAKLI_FIIL` kontrolünden hemen sonra):

    from golge_ek import ek_siniflandir
    ...
    r = ek_siniflandir(verb, args, tum)
    if r is not None:
        return r

None dönerse mevcut dallar aynen devam eder. Saf stdlib, ASCII-only.
Kendi testi: python3 golge_ek.py
"""
import ipaddress
import re
from urllib.parse import urlsplit

OKUMA, YIKICI, YASAKLI = 0, 1, 2

# Okuma sayilan ama bu bayrakla yazan/degistiren komutlar
TEHLIKELI_BAYRAK = {
    "journalctl": r"^--(vacuum|rotate|flush|sync|relinquish|smart-relinquish)",
    "dmesg": r"^(-[A-Za-z]*[cCnDE]|--(clear|read-clear|console|enable|disable))",
    "date": r"^(--set\b|-[A-Za-z]*s)",
    "sort": r"^(-[A-Za-z]*o|--output)",
    "ss": r"^(-[A-Za-z]*K|--kill)",
    "ping": r"^(-[A-Za-z]*f|--flood)",
    "file": r"^(-[A-Za-z]*C|--compile)",
}

IP_DEGISTIREN = re.compile(
    r"\b(add|append|replace|change|set|del|delete|flush|exec|netns|tuntap|tunnel)\b")
NMCLI_DEGISTIREN = re.compile(
    r"\b(add|up|down|connect|disconnect|reload|edit|clone|import|export|"
    r"delete|modify|on|off)\b")

CURL_OK = {"-s", "-S", "-sS", "-I", "--head", "-L", "-f", "-k", "-4", "-6",
           "-i", "-m", "--max-time", "--connect-timeout", "-w", "--write-out",
           "--retry", "--silent", "--show-error", "--location", "--fail",
           "--insecure", "--compressed", "--max-redirs"}
CURL_ARGLI = {"-m", "--max-time", "--connect-timeout", "-w", "--write-out",
              "--retry", "--max-redirs"}
CURL_YASAK_HOST = ("localhost", "::1", "0.0.0.0")

# -sV: servis SURUMU tespiti (salt okuma - BENI_TARA kapisi). Deger
# kisiti: --version-intensity yalniz 0 (en hafif probe; saha olcumu
# 6-7s, diger degerler yavas/gurultulu).
NMAP_BAYRAK = re.compile(
    r"^(-sn|-sV|-n|-Pn|-sT|-F|-v|-vv|--open|--reason|-4|-6|-PE|-PR|-PP|-T[0-4]|"
    r"-p[0-9,\-TU:]+|-P[SAU][0-9,\-]*)$")
NMAP_ARGLI = {"-p", "--top-ports", "--host-timeout", "--max-rate",
              "--max-retries"}
NMAP_ARGLI_DEGERLI = {"--version-intensity": ("0",)}
NMAP_MIN_ONEK = 22          # en fazla /22 (1024 adres)


def _curl(args):
    # YAKLASIM: izin listesi + TEK istisna. -o yalniz /dev/null veya -
    # (cikti diska gitmiyor); loopback/link-local HEP kapali idi —
    # artik istisna yalnizca BENI_TARA probe deseni (kullan.py'de argv
    # modulle kurulur): -o /dev/null + -w (olcum) + --max-time (zaman
    # siniri) BIRLIKTE. Port kapsami ag_kapsam.json'da kilitli.
    i, url_say = 0, 0
    o_devnull = olcum = zaman = False
    while i < len(args):
        t = args[i]
        if t.startswith("-"):
            if t in ("-o", "--output"):
                hedef = args[i + 1] if i + 1 < len(args) else ""
                if hedef not in ("/dev/null", "-"):
                    return YIKICI, "curl: dosyaya yazma (%s)" % hedef[:20]
                o_devnull = True
                i += 2
                continue
            if t not in CURL_OK:
                return YIKICI, "curl: izin listesinde olmayan bayrak %s" % t[:24]
            if t in ("-w", "--write-out"):
                if i + 1 < len(args) and args[i + 1].startswith("@"):
                    return YIKICI, "curl: -w @dosya (dosya okuma)"
                olcum = True
            if t in ("-m", "--max-time"):
                zaman = True
            if t in CURL_ARGLI:
                i += 1
            i += 1
            continue
        if not re.match(r"^https?://", t, re.I):
            return YIKICI, "curl: yalniz http(s) URL"
        try:
            host = (urlsplit(t).hostname or "").lower()
        except ValueError:
            return YIKICI, "curl: URL ayristirilamadi"
        if host.startswith("169.254."):
            return YIKICI, "curl: link-local hedef (%s)" % host
        if host in CURL_YASAK_HOST or host.startswith("127."):
            if not (o_devnull and olcum and zaman):
                return YIKICI, "curl: yerel hedef, probe deseni yok (%s)" % host
        url_say += 1
        i += 1
    if not url_say:
        return YIKICI, "curl: URL yok"
    return OKUMA, "curl (izinli salt okuma)"


def _nmap(args):
    i, hedef_say = 0, 0
    while i < len(args):
        t = args[i]
        if t.startswith("-"):
            if t in NMAP_ARGLI:
                i += 2
                continue
            if t in NMAP_ARGLI_DEGERLI:
                if i + 1 >= len(args) or \
                        args[i + 1] not in NMAP_ARGLI_DEGERLI[t]:
                    return YIKICI, "nmap: %s yalniz izinli degerde" % t[:24]
                i += 2
                continue
            if not NMAP_BAYRAK.match(t):
                return YIKICI, "nmap: izin listesinde olmayan bayrak %s" % t[:24]
            i += 1
            continue
        try:
            ag = ipaddress.ip_network(t, strict=False)
        except ValueError:
            return YIKICI, "nmap: hedef IP/CIDR olmali (%s)" % t[:30]
        if ag.version != 4 or not ag.is_private:
            return YIKICI, "nmap: hedef ozel ag disinda (%s)" % t
        if ag.prefixlen < NMAP_MIN_ONEK:
            return YIKICI, "nmap: ag cok genis (/%d)" % ag.prefixlen
        hedef_say += 1
        i += 1
    if not hedef_say:
        return YIKICI, "nmap: hedef yok"
    return OKUMA, "nmap (izinli salt tarama, ozel ag)"


def ek_siniflandir(verb, args, tum):
    """(sinif, neden) veya None (mevcut dallara birak)."""
    if verb == "curl":
        return _curl(args)
    if verb == "nmap":
        return _nmap(args)
    if verb == "ip" and IP_DEGISTIREN.search(tum):
        return YASAKLI, "ip: ag yapilandirmasini degistirme"
    if verb == "nmcli" and NMCLI_DEGISTIREN.search(tum):
        return YASAKLI, "nmcli: ag baglantisini degistirme"
    if verb == "find" and any(t in ("-fprintf", "-fprint0") for t in args):
        return YIKICI, "find: dosyaya yazma bayragi"
    if verb == "hostname" and any(not a.startswith("-") for a in args):
        return YIKICI, "hostname: ad degistirme"
    if verb == "uniq" and sum(1 for a in args if not a.startswith("-")) > 1:
        return YIKICI, "uniq: cikti dosyasi"
    if verb == "xxd":
        # xxd'in IKINCI konumsal argumani outfile'dir (yazma vektoru);
        # deger alan bayraklar (-l/-s/-c/-g/-e/-f) sonraki argumani yutar.
        degerli = ("-l", "-s", "-c", "-g", "-e", "-f")
        konum, i = [], 0
        while i < len(args):
            a = args[i]
            if a.startswith("-"):
                if a in degerli and i + 1 < len(args):
                    i += 2
                    continue
                i += 1
                continue
            konum.append(a)
            i += 1
        if len(konum) > 1:
            return YIKICI, "xxd: ikinci konumsal arguman (dosyaya yazma)"
    if verb == "hexdump":
        # hexdump -O <dosya> ciktiyi diska yazar
        if "-O" in args:
            return YIKICI, "hexdump: -O dosyaya yazma"
    desen = TEHLIKELI_BAYRAK.get(verb)
    if desen and any(re.search(desen, a) for a in args):
        return YIKICI, "%s: yazan/degistiren bayrak" % verb
    return None


def _test():
    def s(komut):
        t = komut.split()
        r = ek_siniflandir(t[0], t[1:], komut)
        return None if r is None else r[0]

    beklenen = [
        # curl
        ("curl -s https://example.com", OKUMA),
        ("curl -sS -m 5 http://192.168.1.1/", OKUMA),
        ("curl -I -L http://192.168.1.1/", OKUMA),
        ("curl file:///etc/hostname", YIKICI),
        ("curl gopher://127.0.0.1:6379/_PING", YIKICI),
        ("curl -dfoo http://192.168.1.1/", YIKICI),
        ("curl -XPOST http://192.168.1.1/", YIKICI),
        ("curl -o/tmp/x http://192.168.1.1/", YIKICI),
        ("curl -O http://192.168.1.1/a", YIKICI),
        ("curl -w 'etc/hostname' (see below for file content) http://192.168.1.1/", YIKICI),
        ("curl http://127.0.0.1:10000/", YIKICI),
        ("curl http://localhost/", YIKICI),
        ("curl -T /etc/hostname http://192.168.1.1/", YIKICI),
        # BENI_TARA probe istisnasi: yalniz tam desen (o=/dev/null + w + max-time)
        ("curl -s -o /dev/null -w %{http_code} --max-time 5 http://127.0.0.1:8080/", OKUMA),
        ("curl -s http://127.0.0.1:8080/", YIKICI),
        ("curl -o /tmp/x -w %{http_code} --max-time 5 http://127.0.0.1:8080/", YIKICI),
        ("curl -o /dev/null -w %{http_code} http://127.0.0.1:8080/", YIKICI),
        # nmap
        ("nmap -sn -n --host-timeout 5s --max-rate 100 192.168.1.111", OKUMA),
        ("nmap -sT -p22,80,3389 192.168.1.0/24", OKUMA),
        ("nmap -sV --version-intensity 0 -Pn -n -p 1-4096 --host-timeout 18s 127.0.0.1", OKUMA),
        ("nmap -sV --version-intensity 5 192.168.1.5", YIKICI),
        ("nmap -sn 8.8.8.8", YIKICI),
        ("nmap -sn scanme.nmap.org", YIKICI),
        ("nmap -sn 10.0.0.0/8", YIKICI),
        ("nmap --script=exploit 192.168.1.5", YIKICI),
        ("nmap -oN /tmp/x 192.168.1.5", YIKICI),
        ("nmap -iL /etc/hosts", YIKICI),
        ("nmap -sn", YIKICI),
        # ip / nmcli
        ("ip route replace default via 1.2.3.4", YASAKLI),
        ("ip link set eno1 mtu 68", YASAKLI),
        ("ip addr add 10.0.0.9/24 dev eno1", YASAKLI),
        ("ip addr show lo", None),
        ("ip -br a", None),
        ("nmcli connection up foo", YASAKLI),
        ("nmcli networking off", YASAKLI),
        ("nmcli device status", None),
        # bayrak tabanli
        ("journalctl --vacuum-size=1M", YIKICI),
        ("journalctl -u xrdp -n 20", None),
        ("dmesg -c", YIKICI),
        ("dmesg -T", None),
        ("date -s 2020-01-01", YIKICI),
        ("date +%s", None),
        ("sort -o out.txt in.txt", YIKICI),
        ("sort -n in.txt", None),
        ("ss -K dst 192.168.1.10", YIKICI),
        ("ss -Htan state listening", None),
        ("ping -f 192.168.1.1", YIKICI),
        ("ping -c 2 -W 1 192.168.1.16", None),
        ("find /tmp -fprintf /tmp/x %p", YIKICI),
        ("find /usr/share/doc -type f", None),
        ("hostname evim", YIKICI),
        ("hostname", None),
        ("uniq a b", YIKICI),
        ("uniq -c a", None),
        # Asama 6: xxd/hexdump yazma vektorleri
        ("xxd -l 64 /etc/hostname", None),
        ("xxd -l 64 /etc/hostname /tmp/out", YIKICI),
        ("xxd -r /tmp/dump.bin", None),
        ("xxd /etc/hostname /tmp/out.bin", YIKICI),
        ("hexdump -C -n 64 /etc/hostname", None),
        ("hexdump -O /tmp/out /etc/hostname", YIKICI),
    ]
    hata = 0
    for komut, bek in beklenen:
        got = s(komut)
        ok = got == bek
        hata += 0 if ok else 1
        print("%s %-60s -> %s%s" % ("OK  " if ok else "HATA", komut, got,
                                      "" if ok else " (beklenen %s)" % bek))
    print("\n%s" % ("TUM EK TESTLER GECTI" if not hata else "%d BASARISIZ" % hata))
    return 1 if hata else 0


if __name__ == "__main__":
    import sys
    sys.exit(_test())

