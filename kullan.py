"""Kullan — komut kullanımı öğretmeni (nesnel doğrulayıcı, LLM'siz).

Organizmanın HANGİ komutu NE ZAMAN kullanacağını öğrendiği modül.
Öğretmen dışarıdan verilmiş bir kural tablosu değildir: dosya sistemi
ve dpkg'nin kendisidir. Bir hedef kurulur ("şu dosyayı bul", "şu dosya
hangi pakette", "şu dizinde ne var", "şu dosya kaç satır", "şu dizge
dosyada var mı"). Organizma beyaz listeden bir komut seçer (cmd:find,
cmd:ls, cmd:grep ...). Komutun çıktısı hedefi gerçekten karşılıyorsa
+6 enerji ödülü verilir; karşılamıyorsa ödül yok (maliyet zaten
harcanmıştır).

Beyin özellik-bazlı olarak şöyle öğrenir:
    (gorev:DOSYA_BUL, cmd:find) → +6

"Ne zaman" sorusu kendiliğinden ortaya çıkar: açken eat uygun olduğu
için organizma yemeğe gider, tokkken iş eylemlerine yönelir.

Güvenlik:
  * yalnızca salt-okunur komutlar (which, file, find, ls, wc, grep,
    head, tail, stat, du, dpkg, apt-cache, ps, pgrep, systemctl, ip, df)
  * nmap/ping yalnızca AG_TARA hedeflerinde, argv modülde kurulur;
    kapsam kilidi ag_kapsam.json'dur — VARSAYILAN RED (Faz 0)
  * BENI_TARA (Katman 1+2): kendini tarama — 127.0.0.1'de port/servis
    keşfi (nmap -sV), ss ve curl kapıları; zemin gerçeği /proc socket
    tablosu (komutlardan bağımsız, judge-time); ayrı bayrak:
    ben_tarama — VARSAYILAN RED
  * argümanlar liste olarak geçirilir (shell yok)
  * desenler dosya içeriğinden, yollar dosya sisteminden gelir;
    kullanıcı girdisi asla doğrudan komuta sızmaz
  * find/grep yalnızca güvenli köklerle sınırlıdır
  * cwd = /tmp: göreli ad argümanları yanlışlıkla hedefi bulamaz
"""

import hashlib
import ipaddress
import json
import os
import platform
import random
import re
import shlex
import subprocess
import time
from pathlib import Path

import golge
import komut_tehlike as komut_tehlike_mod
from journal import Journal

ROOT = Path(__file__).resolve().parent

# Beyaz liste — yalnızca salt-okunur komutlar.
# ps/pgrep (süreç), systemctl (servis; yalnızca okuyan alt komutlar),
# ip/df (ağ/disk) — argv her zaman bu modülde kurulur.
BEYAZ = ("which", "file", "find", "ls", "wc", "grep", "head", "tail",
         "stat", "du", "dpkg", "apt-cache", "ps", "pgrep", "systemctl",
         "ip", "df", "zcat", "nmap", "ping", "ss", "curl",
         # Yeni ağ keşif komutları (salt-okunur):
         "traceroute", "host", "whois", "ifconfig", "arp",
         # talep.py hazir BEYAZ adayları (judge_var=True) — sistemde var,
         # kurulum gerekmez; yalnızca _harita + _dogrula eklenir
         "nstat", "lnstat", "netstat", "resolveip",
         "lsof", "pstree",
         "tree",
         "realpath", "readlink",
         "lsblk",
         "xz", "bzip2", "zstd",
         # Aşama 6 (Debian yönetimi): sistem bilgisi + bütünlük + ham
         # bayt okuma — hepsi salt-okunur, argv yine modülde kurulur
         "lscpu", "free", "uname",
         "md5sum", "sha256sum",
         "hexdump", "xxd",
         # Ağ keşif (AG_TARA / BENI_TARA) — salt-okunur, ag_kapsam.json
         # kapsam kilidiyle sınırlı; kurulum insanda.
         # traceroute talep.py üzerinden talep edilir (BEYAZ'da değil,
         # sistemde kurulu olmayabilir); dig/nslookup BEYAZ'da.
         "dig", "nslookup")

# ---------- AG_TARA (Faz 0): kapsam kilidi — VARSAYILAN RED ----------
# Yetki tek dosyadan: ag_kapsam.json. Dosya yok/bozuk/acik:false →
# tarama hiç üretilmez; kapı (_harita) ve yargı (_dogrula) her ip'yi
# ayrıca _ag_ip_izinli ile teyit eder (savunma derinliği).
AG_KAPSAM_DOSYA = "ag_kapsam.json"
AG_CANLI_DURUMLAR = ("REACHABLE", "STALE", "DELAY", "PROBE")   # ARP: canlı
AG_OLU_DURUMLAR = ("INCOMPLETE", "FAILED")                     # ARP: ölü
AG_VARSAYILAN = {
    "nmap_hiz_tavan": 100,         # --max-rate: yavaş tarama
    "nmap_hedef_zaman_asimi": "5s",
    "ping_paket": 2,               # -c
    "ping_bekle_sn": 1,            # -W (her yanıtlama bekleme, sn)
    "ayni_hedef_aralik_sn": 15,    # aynı host'a soğuma
}

# ---------- BENI_TARA (Katman 1+2): kendini bil ----------
# Kendi port/servis haritası (nmap -sV) + ss/curl kapıları. Zemin
# gerçeği /proc/net/tcp(+6) LISTEN satırlarıdır — kapı komutlarından
# bağımsız, judge-time okunur (AG_TARA'daki ARP ile aynı doktrin).
# ZAMAN BÜTÇESİ: sahada ölçüldü — `--version-intensity 0`'lı -sV en yavaş
# aralıklarda (4097-8192: 5355/5432/6379/7070, 8193-16384: 10000) 6-7s'de
# bitiyor; intensiz -sV yavaş servislerde 20s+ (hatta --host-timeout 18s
# nmap'i probe ortasında kesmiyor → Python TimeoutExpired → "çalıştırılamadı").
# Yani bu hedef tipine özel alt süreç bütçesi (BENI_KOMUT_SURE), küresel
# ZAMAN_ASIMI değil. --host-timeout artık Graceful yedek: tablo basılamazsa
# çıktı boş kalır → yargı False verir (ödül uydurulmaz, sadece deneme israfı).
BENI_IP = "127.0.0.1"
BENI_ARALIKLAR = ("1-4096", "4097-8192", "8193-16384",
                  "16385-32768", "32769-65535")
BENI_KOMUT_SURE = 20          # saniye; nmap --host-timeout'undan büyük olmalı

# find/grep'in gezeceği güvenli kökler (sanal FS ve ağ yok).
GUVENLI_KOKLER = ("/usr/bin", "/usr/sbin", "/etc", "/usr/share/doc",
                  "/home/emrah/Genel/core/world")

SERVIS_ONBELLEK_SN = 300   # servis listesi yenileme aralığı

ZAMAN_ASIMI = 8        # komut zaman aşımı (saniye)
ODUL = 6.0             # hedefi karşılayan komut ödülü
ODUL_HELP = 4.0        # komutun --help'ından ne işe yaradığını öğrenme ödülü
MALIYET = 0.5          # her deneme bedava değil
# AELAAN sert duvarı (golge.py): yasaklı sınıf bir komut ÖNERİLDİĞİNDE
# beyne ek ceza. gain = -KAPI_CEZA → hem enerji düşer hem reward
# negatifleşir: "bu kapıya bir daha yaklaşma" için çift sinyal.
# Yalnızca engel=True (yasaklı) için; atlandi (mod atlaması) cezasızdır.
KAPI_CEZA = 5.0
# zincir hedeflerinde ara veri ödülü (Aşama 2). MALIYET'ten yüksek
# OLMALI: eski 1.0, bedel sonrası net −1.0 yapıyordu → veri üreten doğru
# ilk adım (ps → wc) cezalandırılıyor, beyin ondan kaçıyordu (zincir %7).
# 3.0 → net +1.0: başarısızlık −2.0, ara adım +1.0, tamamlama +4.0.
# Böylece beyin "veri üret" adımını gerçekten öğrenir.
ILERLEME = 3.0
ZINCIR_TIPLERI = ("SUREC_SAY", "DOSYA_SAY")
# Not (Aşama 1): zincir komut haritası artık ayrı bir sabit değil —
# eylemler() maskeyi HER hedef için _harita()’dan alır (tek doğruluk
# kaynağı). Eski ZINCIR_KOMUT, zincir dışı hedeflerde harita dışı seçim
# ["true"] (no-op) çalıştırıp deneme bütçesini israf ediyordu; canlı
# ölçüm (690 bin deneme) ölü alanı %40 buldu → maske globalleştirildi.
DOSYA_TAVANI = 8000    # önbellek üst sınırı
ARA_TAVAN = 512 * 1024  # ara bellek (son stdout) — zincir hedefleri (Aşama 2)
CWD = "/tmp"


def ozet(cikti, n=60):
    """Çıktının ilk anlamlı satırı (gözlem kısaltması)."""
    for satir in cikti.splitlines():
        s = satir.strip()
        if s:
            return s[:n]
    return "(boş)"


def _surec_say(ad):
    """Bağımsız öğretmen: /proc'ta comm == ad kaç süreç? (ps DEĞİL.)"""
    n = 0
    try:
        girdiler = os.listdir("/proc")
    except OSError:
        return 0
    for g in girdiler:
        if not g.isdigit():
            continue
        try:
            with open("/proc/%s/comm" % g, encoding="utf-8") as f:
                if f.read().strip() == ad:
                    n += 1
        except OSError:
            continue
    return n


def _dizin_say(dizin):
    """Bağımsız öğretmen: dosya sayısı — find -P ile AYNI tanımla.

    Sembolik bağlantılar sayılmaz ve takip edilmez (find `-type f` gibi);
    aksi halde find çıktısıyla doğrulayıcı asla eşleşmez.
    """
    n = 0
    try:
        for d, alt, dosyalar in os.walk(dizin):
            alt[:] = [a for a in alt
                      if not os.path.islink(os.path.join(d, a))]
            for f in dosyalar:
                if not os.path.islink(os.path.join(d, f)):
                    n += 1
    except OSError:
        return -1
    return n


class Kullan:
    """Komut kullanımı öğretmeni: hedef kurar, çıktıyı yargılar."""

    def __init__(self, cfg, root=ROOT):
        self.cfg = cfg or {}
        self.root = Path(root)
        k = self.cfg.get("kullan", {}) if isinstance(self.cfg, dict) else {}
        self.aktif = bool(k.get("aktif", True))
        self.hedef = None
        self.denemeler = 0
        self.hedef_deneme = 0   # aktif hedef üzerindeki deneme (token 1|2|3+)
        self.ara = ""           # son çıktının ara belleği (zincir, Aşama 2)
        self.dogrular = 0
        self.yanlislar = 0
        self._dosyalar = None
        self._doclar = None   # /usr/share/doc alt dizinleri (DOSYA_SAY)
        self._servisler = []
        self._servis_zaman = 0.0
        self._paketler = None     # kurulu paket adları (PAKET_VERSIYON)
        self._paket_zaman = 0.0
        # AELAAN kapısı (golge.py): beyin komutları gölge modundan geçer.
        # GOLGE_LOG ortam değişkeni: "" → kapı logu KAPALI (test kirliliği
        # yok); canlıda varsayılan golge_log.jsonl (çevrimdışı incele/rapor
        # kanıtı — main.py kullan_engel kayıtlarıyla eşleşir).
        _glog = os.environ.get("GOLGE_LOG", str(golge.LOG))
        self._kapi = golge.Kapi(log=(_glog or None), zaman_asimi=ZAMAN_ASIMI)
        self._son_kap = None   # en son kapı sonucu (uygula() engel okur)
        # AG_TARA (Faz 0): kapsam kilidi canlı izlenir (dosya değişince
        # anında geçerli — restart gerekmez) + soğuma + az-denenmiş öncelik
        self._ag_kapsam = {"acik": False, "izin": []}
        self._ag_kapsam_damga = None   # (mtime_ns, boyut); yoksa None
        self._ag_son = {}          # ip → son hedef kurulumu (soğuma)
        self._ag_denemeleri = {}   # ip → kaç kez hedef oldu (least-tried)
        # BENI_TARA: keşif uzayı port aralığı (aynı sayım mekanizması)
        self._ben_son = {}         # aralık → son hedef kurulumu (soğuma)
        self._ben_denemeleri = {}  # aralık → kaç kez hedef oldu (least-tried)
        # Komut tehlike skoru modeli (komut çalıştırılmadan önce sorulur):
        #   "bu komutu çalıştırırsam ölürüm mü?" → engelle / ceza / çalıştır
        self._komut_tehlike = komut_tehlike_mod.KomutTehlike()
        self._komut_tehlike.load()
        self._komut_tehlike_esik = 0.80   # bu üzeri komut engellenir
        self._komut_tehlike_ceza_esik = 0.50  # bu üzeri ceza verilir (ama çalıştırılır)
        _jour_yol = cfg.get("stage", {}).get("journal", "journal.jsonl")
        self.jour = Journal(ROOT / _jour_yol, quiet=False)

    def birak(self):
        """İnkâr hakkı (Aşama 4): aktif hedefi bedelsiz terk et.

        Ceza/ödül burada DEĞİL beynde verilir (veto ödülü: erken bırakma
        −1, geç bırakma +1 → beyin "ne zaman hayır diyeceğini" öğrenir).
        Deneme sayacı da sıfırlanır ki yeni hedef temiz başlasın; zincir
        tamponu (ara) da bırakılır — yarım iş taşınmaz.
        """
        tip = (self.hedef or {}).get("tip")
        self.hedef = None
        self.hedef_deneme = 0
        self.ara = ""
        return tip

    # ---------- hedef üretimi ----------

    def don(self):
        """Periyodik bakım: hedefi tazele."""
        if not self.aktif:
            return
        yeni = self._hedef_kur()
        if yeni:
            self.hedef = yeni
            self.hedef_deneme = 0
            self.ara = ""   # ara belleğin TTL'si: yeni hedefe geçince sıfır

    def _hedef_kur(self):
        tipler = ["DOSYA_BUL", "PAKET_SOR", "DIZIN_LISTE",
                  "DOSYA_OKU", "METIN_ARA", "SUREC_SOR", "SERVIS_SOR",
                  "DISK_SOR", "AG_SOR", "SUREC_SAY", "DOSYA_SAY",
                  "DOSYA_OLC", "PAKET_VERSIYON", "AG_TARA", "BENI_TARA",
                  "SISTEM_SOR", "DOSYA_OZET", "DOSYA_HAM",
                  "KONFIG_OKU", "LOG_OKU", "PORTA_DINLE"]
        random.shuffle(tipler)
        kurucular = {"DOSYA_BUL": self._h_dosya_bul,
                     "PAKET_SOR": self._h_paket_sor,
                     "DIZIN_LISTE": self._h_dizin_liste,
                     "DOSYA_OKU": self._h_dosya_oku,
                     "METIN_ARA": self._h_metin_ara,
                     "SUREC_SOR": self._h_surec_sor,
                     "SERVIS_SOR": self._h_servis_sor,
                     "DISK_SOR": self._h_disk_sor,
                     "AG_SOR": self._h_ag_sor,
                     "SUREC_SAY": self._h_surec_say,
                     "DOSYA_SAY": self._h_dosya_say,
                     "DOSYA_OLC": self._h_dosya_olc,
                     "PAKET_VERSIYON": self._h_paket_versiyon,
                     "AG_TARA": self._h_ag_tara,
                     "BENI_TARA": self._h_beni_tara,
                     "SISTEM_SOR": self._h_sistem_sor,
                     "DOSYA_OZET": self._h_dosya_ozet,
                     "DOSYA_HAM": self._h_dosya_ham,
                     "KONFIG_OKU": self._h_konfig_oku,
                     "LOG_OKU": self._h_log_oku,
                     "PORTA_DINLE": self._h_porta_dinle}
        for tip in tipler:
            try:
                h = kurucular[tip]()
            except OSError:
                h = None
            if h:
                return h
        return None

    def _dosya_listesi(self):
        if self._dosyalar is None:
            ds = []
            for kok in GUVENLI_KOKLER:
                if len(ds) >= DOSYA_TAVANI:
                    break
                try:
                    for d, _alt, files in os.walk(kok):
                        for f in files:
                            p = os.path.join(d, f)
                            try:
                                if (not os.path.islink(p)
                                        and os.path.isfile(p)):
                                    ds.append(p)
                            except OSError:
                                pass
                        if len(ds) >= DOSYA_TAVANI:
                            break
                except OSError:
                    pass
            self._dosyalar = ds
        return self._dosyalar

    def _h_dosya_bul(self):
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            yol = random.choice(ds)
            ad = os.path.basename(yol)
            kok = next((k for k in GUVENLI_KOKLER
                        if yol.startswith(k + "/")), None)
            if kok and not ad.startswith("-"):
                return {"tip": "DOSYA_BUL", "ad": ad, "kok": kok}
        return None

    def _h_paket_sor(self):
        aday = [p for p in self._dosya_listesi()
                if p.startswith(("/etc/", "/usr/share/"))]
        random.shuffle(aday)
        for p in aday[:6]:
            ad = os.path.basename(p)
            if ad.startswith("-"):
                continue
            for v in dict.fromkeys((
                    p,
                    p.replace("/usr/bin/", "/bin/", 1),
                    p.replace("/usr/sbin/", "/sbin/", 1))):
                ok, cikti, _h = self._kos(["dpkg", "-S", v])
                if ok and ":" in cikti:
                    paket = cikti.split(":", 1)[0].strip()
                    if paket:
                        return {"tip": "PAKET_SOR", "yol": v,
                                "paket": paket}
        return None

    def _h_dizin_liste(self):
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            d = os.path.dirname(random.choice(ds))
            if not any(d.startswith(k + "/") for k in GUVENLI_KOKLER):
                continue
            try:
                icindekiler = os.listdir(d)
            except OSError:
                continue
            if icindekiler:
                return {"tip": "DIZIN_LISTE", "dizin": d,
                        "icindekiler": icindekiler[:20]}
        return None

    def _h_dosya_oku(self):
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            p = random.choice(ds)
            try:
                boyut = os.path.getsize(p)
                if not (0 < boyut <= 50 * 1024 * 1024):
                    continue
                with open(p, "rb") as f:
                    # baş ve SON ayrı okunur: 256KB kırpması büyük dosyada
                    # ornek_son'u ortadan alırdı → tail asla doğrulayamazdı
                    bas_veri = f.read(128 * 1024)
                    if boyut > 128 * 1024:
                        f.seek(-128 * 1024, os.SEEK_END)
                    else:
                        f.seek(0)
                    son_veri = f.read(128 * 1024)
            except OSError:
                continue
            # gz (2026-10-15): gzip sihirbaytı tespiti → ÖRNEKLER ÇÖZÜLMÜŞ
            # halinden okunur. Eski davranış: sıkıştırılmış baytlar NUL
            # filtresinden geçip düz metin sanılıyor, wc -l gzip binary'nin
            # newline sayısını veriyor ve "hedefi karşıladı" oluyordu
            # (journal: wc -l README.gz → 7 ✓). Doğru kapı zcat'tir.
            sikistirilmis = bas_veri[:2] == b"\x1f\x8b"
            if sikistirilmis:
                try:
                    import gzip
                    with gzip.open(p, "rb") as g:
                        bas_veri = g.read(128 * 1024)
                    with gzip.open(p, "rb") as g:
                        # son örnek için baştan sona tara (dosyalar küçük)
                        tum = g.read()
                    son_veri = tum[-128 * 1024:]
                except (OSError, EOFError):
                    continue
            if b"\x00" in bas_veri or b"\x00" in son_veri:
                continue
            kosul = lambda s: 6 <= len(s.strip()) <= 120 and \
                re.search(r"[A-Za-z0-9]", s)
            bas_sat = bas_veri.decode("utf-8", "replace").splitlines()
            son_sat = son_veri.decode("utf-8", "replace").splitlines()
            # ornek_bas/ornek_son: head/tail bu satırları ÇIKTIYA
            # basınca "dosyayı gerçekten okudu" nesnel kanıtlanır
            # (wc sayı kanıtı verir; üçü de aynı gerçeğin kapısı).
            bas = [s.strip() for s in bas_sat[:10] if kosul(s)]
            son = [s.strip() for s in son_sat[-10:] if kosul(s)]
            if not (bas or son):
                continue
            return {"tip": "DOSYA_OKU", "yol": p,
                    "ornek_bas": random.choice(bas) if bas else None,
                    "ornek_son": random.choice(son) if son else None,
                    "sikistirilmis": sikistirilmis}
        return None

    def _h_metin_ara(self):
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            p = random.choice(ds)
            try:
                with open(p, "rb") as f:
                    veri = f.read(4096)
                if b"\x00" in veri:
                    continue
                satirlar = veri.decode("utf-8", "replace").splitlines()
                if len(satirlar) < 12:
                    continue
                sec = random.choice(satirlar[10:]).strip()
                if len(sec) >= 4 and re.search(r"[A-Za-z0-9]", sec):
                    return {"tip": "METIN_ARA", "yol": p,
                            "kalip": sec[:24]}
            except OSError:
                continue
        return None

    # ---------- eylemler ----------

    def eylemler(self):
        """Beynin seçebileceği eylem ailesi.

        Artık BEYAZ whitelist'e bağlı değil: /bin, /usr/bin, /sbin,
        /usr/sbin'den çalıştırılabilirleri tarar, kara listedekileri
        çıkarır. Bu sayede organizma binlerce komutu keşfedebilir;
        zararlı olanları komut_tehlike modeli engeller/cezalandırır.
        """
        if not self.aktif:
            return []
        h = self.hedef
        if h:
            harita = self._harita(h)
            if harita:
                return ["cmd:" + c for c in harita]
        # Hedef yok veya harita yok: sistemdeki tüm çalıştırılabilirler
        komutlar = self._sistem_komutlarini_tara()
        return ["cmd:" + c for c in komutlar]

    def _sistem_komutlarini_tara(self):
        """/bin, /usr/bin, /sbin, /usr/sbin'den çalıştırılabilirleri topla.

        Tüm çalıştırılabilirler döner; zararlı olanları komut_tehlike
        modeli engeller/cezalandırır (kara liste yok, sadece model).
        """
        komutlar = set()
        for d in ("/bin", "/usr/bin", "/sbin", "/usr/sbin"):
            try:
                for ad in os.listdir(d):
                    yol = os.path.join(d, ad)
                    if os.path.isfile(yol) and os.access(yol, os.X_OK):
                        komutlar.add(ad)
            except OSError:
                pass
        return sorted(komutlar)
    def _canli_adlar(self):
        """Canlı kullanıcı süreci adları (/proc; cmdline boş çekirdek
        parçaları hariç — surec organıyla aynı dışlama)."""
        adlar = set()
        try:
            girdiler = os.listdir("/proc")
        except OSError:
            return []
        for g in girdiler:
            if not g.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % g, "r") as f:
                    if not f.read(1):
                        continue
                with open("/proc/%s/comm" % g, "r") as f:
                    ad = f.read().strip()
            except OSError:
                continue
            if ad and len(ad) <= 15:
                adlar.add(ad)
        return sorted(adlar)

    def _h_surec_sor(self):
        """'X süreci çalışıyor mu?' — doğrulayıcı: /proc'un kendisi."""
        adlar = self._canli_adlar()
        if not adlar:
            return None
        n = random.randint(0, len(adlar) - 1)
        return {"tip": "SUREC_SOR", "ad": adlar[n]}

    def _h_surec_say(self):
        """ZİNCİR hedefi (Aşama 2): 'X kaç süreç?' — tek komut
        sayıyı veremez: ara adım (ps/pgrep → pid listesi) + son adım
        (wc, stdin = ara bellek). Doğrulayıcı bağımsız /proc sayımı."""
        adlar = self._canli_adlar()
        if not adlar:
            return None
        ad = adlar[random.randint(0, len(adlar) - 1)]
        if _surec_say(ad) < 1:
            return None
        return {"tip": "SUREC_SAY", "ad": ad}

    def _h_dosya_say(self):
        """ZİNCİR hedefi (Aşama 2): 'Şu dizinde kaç dosya?' —
        doğrulayıcı bağımsız os.walk. Küçük dizin seçilir ki find
        çıktısı ara belleğe (ARA_TAVAN) sığsın."""
        for _ in range(6):
            d = self._doc_dizini()
            if not d:
                return None
            n = _dizin_say(d)
            if 1 <= n <= 3000:
                return {"tip": "DOSYA_SAY", "dizin": d}
        return None

    def _doc_dizini(self):
        """/usr/share/doc alt dizinleri (tek yükleme, GUVENLI_KOKLER'de)."""
        if self._doclar is None:
            try:
                self._doclar = [d for d in
                                sorted(os.listdir("/usr/share/doc"))
                                if not d.startswith(".")]
            except OSError:
                self._doclar = []
        if not self._doclar:
            return None
        return "/usr/share/doc/" + random.choice(self._doclar)

    # ---------- yeni hedef üreticileri (Aşama 1: eylem uzayı zenginliği) ----

    def _h_dosya_olc(self):
        """’Bu dosya kaç byte?’ — doğrulayıcı: bağımsız getsize.
        stat / wc -c / du -sb üç farklı yol, tek gerçek (zemin gerçeği)."""
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            p = random.choice(ds)
            try:
                boyut = os.path.getsize(p)
            except OSError:
                continue
            if 0 < boyut <= 10 * 1024 ** 3:
                return {"tip": "DOSYA_OLC", "yol": p, "boyut": boyut}
        return None

    # ---------- Aşama 6: Debian yönetimi hedefleri -------------------------

    def _h_sistem_sor(self):
        """'Sistemin cpu/bellek/çekirdek durumu ne?' — üç konu, üç kapı.

        Doğrulayıcı bağımsız kaynak (judge-time): os.cpu_count /
        /proc/meminfo / platform.release — komut çıktısı değil kernel gerçeği.
        """
        konu = random.choice(("cpu", "bellek", "cekirdek"))
        if konu == "cpu":
            n = os.cpu_count()
            if not n:
                return None
            return {"tip": "SISTEM_SOR", "konu": "cpu", "cekirdek": n}
        if konu == "bellek":
            try:
                with open("/proc/meminfo", "r") as f:
                    ilk = f.readline()
                kb = int(ilk.split()[1])
            except (OSError, ValueError, IndexError):
                return None
            if kb < 1024:
                return None
            return {"tip": "SISTEM_SOR", "konu": "bellek", "kb": kb}
        surum = platform.release()
        if not surum:
            return None
        return {"tip": "SISTEM_SOR", "konu": "cekirdek", "surum": surum}

    def _h_dosya_ozet(self):
        """'Bu dosyanın özeti ne?' — md5sum / sha256sum (bütünlük).

        Doğrulayıcı: hashlib dosyanın KENDİSİNİ judge-time okur.
        Boyut sınırı: 5MB — hash 8s zaman aşımına sığmalı.
        """
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            p = random.choice(ds)
            try:
                boyut = os.path.getsize(p)
            except OSError:
                continue
            if 0 < boyut <= 5 * 1024 * 1024:
                return {"tip": "DOSYA_OZET", "yol": p}
        return None

    def _h_dosya_ham(self):
        """'İlk baytlar ne?' — hexdump / xxd (ham içerik okuma).

        Doğrulayıcı: dosyanın ilk 8 baytı judge-time okunur; hex
        gösterimi (hexdump '7f 45..' / xxd '7F45 4C46') çıktıda
        bulunmalı — boşluk/atlamalar temizlenerek karşılaştırılır.
        """
        ds = self._dosya_listesi()
        for _ in range(8):
            if not ds:
                return None
            p = random.choice(ds)
            try:
                with open(p, "rb") as f:
                    ilk = f.read(8)
            except OSError:
                continue
            if len(ilk) == 8:
                return {"tip": "DOSYA_HAM", "yol": p}
        return None

    def _h_konfig_oku(self):
        """'Bu config dosyasının içeriği ne?' — /etc altındaki
        yapılandırma dosyalarını okur. Sistemin nasıl ayarlandığını
        öğretir: /etc/fstab, /etc/hostname, /etc/resolv.conf vb.

        Doğrulayıcı: dosyayı doğrudan okur, çıktıyla karşılaştırır.
        """
        adaylar = [
            "/etc/hostname", "/etc/resolv.conf", "/etc/fstab",
            "/etc/hosts", "/etc/os-release", "/etc/group",
            "/etc/passwd", "/etc/shells", "/etc/issue",
            "/etc/timezone", "/etc/default/locale",
        ]
        import os as _os
        secim = []
        for p in adaylar:
            try:
                if _os.path.isfile(p) and _os.path.getsize(p) > 0 \
                        and _os.path.getsize(p) < 4096:
                    secim.append(p)
            except OSError:
                continue
        if not secim:
            return None
        yol = random.choice(secim)
        return {"tip": "KONFIG_OKU", "yol": yol}

    def _h_log_oku(self):
        """'Son log kayıtları ne?' — /var/log altındaki log dosyaları.
        Sistem ne yapıyor, hata var mı — organizma bunu öğrenir.

        Doğrulayıcı: dosyayı doğrudan okur, son N satırı karşılaştırır.
        """
        adaylar = [
            "/var/log/syslog", "/var/log/auth.log",
            "/var/log/dmesg", "/var/log/kern.log",
            "/var/log/bootstrap.log", "/var/log/alternatives.log",
        ]
        import os as _os
        secim = []
        for p in adaylar:
            try:
                if _os.path.isfile(p) and _os.path.getsize(p) > 0 \
                        and _os.access(p, _os.R_OK):
                    secim.append(p)
            except OSError:
                continue
        if not secim:
            return None
        yol = random.choice(secim)
        return {"tip": "LOG_OKU", "yol": yol}

    def _h_porta_dinle(self):
        """'Hangi portlar dinleniyor?' — ss -tlnp çıktısı.
        Açık portlar = dışa açık servisler; güvenlik bağlamı.

        Doğrulayıcı: /proc/net/tcp'den LISTEN (durum 0A) port sayısı.
        """
        # /proc/net/tcp'de en az bir LISTEN var mı?
        try:
            with open("/proc/net/tcp", "r") as f:
                for satir in f.readlines()[1:]:
                    if " 0A " in satir:  # durum 0A = LISTEN
                        return {"tip": "PORTA_DINLE"}
        except OSError:
            pass
        return None

    def _paket_listesi(self):
        """Kurulu paket adları (dpkg-query; önbellekli; yoksa boş liste)."""
        import time as _t
        simdi = _t.time()
        if self._paketler and \
                simdi - self._paket_zaman < SERVIS_ONBELLEK_SN:
            return self._paketler
        try:
            r = subprocess.run(
                ["dpkg-query", "-W", "-f=${Package}\n"],
                capture_output=True, text=True, errors="replace",
                timeout=15, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return []
        adlar = [s.strip() for s in r.stdout.splitlines() if s.strip()]
        self._paketler = adlar
        self._paket_zaman = simdi
        return adlar

    def _h_paket_versiyon(self):
        """’Kurulu X paketinin sürümü nedir?’ — doğrulayıcı: dpkg-query
        kendisi. dpkg -s ile apt-cache policy aynı gerçeği söyler →
        iki kapılı gerçek seçim (eski PAKET_SOR’da tek kapı vardı)."""
        adlar = self._paket_listesi()
        if not adlar:
            return None
        paket = adlar[random.randint(0, len(adlar) - 1)]
        try:
            r = subprocess.run(
                ["dpkg-query", "-W", "-f=${Version}", paket],
                capture_output=True, text=True, errors="replace",
                timeout=10, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None
        surum = (r.stdout or "").strip()
        if not surum:
            return None
        return {"tip": "PAKET_VERSIYON", "paket": paket, "surum": surum}

    def _servis_listesi(self):
        """Kurulu servis birimleri (kısa önbellekli; yoksa boş liste)."""
        simdi = 0.0
        try:
            import time as _t
            simdi = _t.time()
        except ImportError:
            pass
        if (self._servisler and
                simdi - self._servis_zaman < SERVIS_ONBELLEK_SN):
            return self._servisler
        try:
            r = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all",
                 "--no-legend", "--no-pager", "--plain"],
                capture_output=True, text=True, errors="replace",
                timeout=10, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return []
        birimler = [s.split()[0] for s in r.stdout.splitlines()
                    if s.split() and s.split()[0].endswith(".service")]
        self._servisler = birimler
        self._servis_zaman = simdi
        return birimler

    def _servis_durumu(self, birim):
        """Zemin gerçeği: systemctl is-active (öğretmenin ta kendisi)."""
        try:
            r = subprocess.run(
                ["systemctl", "is-active", birim],
                capture_output=True, text=True, errors="replace",
                timeout=10, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None
        b = (r.stdout or "").strip().split()
        return b[0] if b else None

    def _h_servis_sor(self):
        """'X servisi aktif mi?' — doğrulayıcı: systemctl is-active."""
        birimler = self._servis_listesi()
        if not birimler:
            return None
        u = random.randint(0, len(birimler) - 1)
        durum = self._servis_durumu(birimler[u])
        if not durum:
            return None
        return {"tip": "SERVIS_SOR", "birim": birimler[u],
                "beklenen": durum}

    def _disk_listesi(self):
        """Gerçek disk bağlama noktaları (/dev/sd|nvme|vd|mmcblk|mapper)."""
        noktalar = []
        try:
            with open("/proc/mounts", encoding="utf-8") as f:
                satirlar = f.read().splitlines()
        except OSError:
            return []
        for s in satirlar:
            alan = s.split()
            if len(alan) < 2:
                continue
            kaynak, hedef = alan[0], alan[1]
            if re.match(r"^/dev/(sd[a-z]|nvme\d+n\d+|vd[a-z]|mmcblk\d+|"
                        r"hd[a-z]|mapper/)", kaynak):
                noktalar.append(hedef.replace("\\040", " "))
        return noktalar

    def _h_disk_sor(self):
        """'X diskinde durum ne?' — doğrulayıcı: df'nin kendi çıktısı."""
        noktalar = self._disk_listesi()
        if not noktalar:
            return None
        n = random.randint(0, len(noktalar) - 1)
        return {"tip": "DISK_SOR", "birim": noktalar[n]}

    def _arayuz_listesi(self):
        """Ağ arayüzleri (ip -o link; başaramazsa salt geri dönüş)."""
        try:
            r = subprocess.run(
                ["ip", "-o", "link", "show"],
                capture_output=True, text=True, errors="replace",
                timeout=10, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return ["lo"]
        adlar = []
        for s in r.stdout.splitlines():
            m = re.match(r"^\d+:\s+([A-Za-z0-9_.@-]+):", s)
            if m:
                adlar.append(m.group(1).split("@")[0])
        return adlar or ["lo"]

    def _h_ag_sor(self):
        """'X arayüzü ne durumda?' — doğrulayıcı: ip'nin kendi çıktısı."""
        adlar = self._arayuz_listesi()
        a = random.randint(0, len(adlar) - 1)
        return {"tip": "AG_SOR", "arayuz": adlar[a]}

    # ---------- AG_TARA: kapsam kilidi + zemin gerçeği (Faz 0/1) ----------

    def _kapsam_damgasi(self):
        """Kapsam dosyası imzası: (mtime_ns, boyut); dosya yoksa None."""
        try:
            st = (self.root / AG_KAPSAM_DOSYA).stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _kapsam_yukle(self):
        """ag_kapsam.json oku — VARSAYILAN RED (deny-by-default).

        Dosya yok / bozuk / acik:false / izin_aglari boş → ağ taraması
        kapalıdır: AG_TARA hedefi hiç üretilmez, kapı hiç açılmaz.
        Yetki SADECE bu dosyadan gelir — başka kaynak yok, pazarlık yok.
        """
        yol = self.root / AG_KAPSAM_DOSYA
        try:
            ham = json.loads(yol.read_text(encoding="utf-8"))
            if not isinstance(ham, dict) or not ham.get("acik"):
                return {"acik": False, "izin": []}
            izin = []
            for cidr in (ham.get("izin_aglari") or []):
                try:
                    izin.append(ipaddress.ip_network(str(cidr), strict=False))
                except ValueError:
                    continue   # tek kötü CIDR tüm kapsamı bozmaz
            if not izin:
                return {"acik": False, "izin": []}
        except (OSError, ValueError, TypeError):
            return {"acik": False, "izin": []}
        kapsam = dict(AG_VARSAYILAN)
        for anahtar in ("nmap_hiz_tavan", "ping_paket", "ping_bekle_sn",
                        "ayni_hedef_aralik_sn"):
            try:
                kapsam[anahtar] = int(ham[anahtar])
            except (KeyError, TypeError, ValueError):
                kapsam[anahtar] = AG_VARSAYILAN[anahtar]
        asama = str(ham.get("nmap_hedef_zaman_asimi",
                            AG_VARSAYILAN["nmap_hedef_zaman_asimi"]))
        kapsam["nmap_hedef_zaman_asimi"] = (
            asama if re.fullmatch(r"\d+[smh]", asama)
            else AG_VARSAYILAN["nmap_hedef_zaman_asimi"])
        # BENI_TARA anahtarları — deny-by-default: bayrak yalnız literal
        # True açar ("false"/1/bool("...") gibi değerler asla açamaz)
        kapsam["ben_tarama"] = ham.get("ben_tarama") is True
        try:
            port = int(ham.get("ben_http_port", 0))
        except (TypeError, ValueError):
            port = 0
        kapsam["ben_http_port"] = port if 0 <= port <= 65535 else 0
        zaman = str(ham.get("ben_zaman_asimi", "18s"))
        kapsam["ben_zaman_asimi"] = (
            zaman if re.fullmatch(r"\d+[smh]", zaman) else "18s")
        kapsam["acik"] = True
        kapsam["izin"] = izin
        return kapsam

    def _ag_kapali(self):
        """Kapsam reddediyorsa AG_TARA ne üretilir ne de kazanır.

        Dosya canlı izlenir: idari red (acik:false / dosya silme) anında
        geçerlidir — jeneratör, kapı ve yargı kilitlenir, restart gerekmez.
        """
        damga = self._kapsam_damgasi()
        if damga != self._ag_kapsam_damga:
            self._ag_kapsam = self._kapsam_yukle()
            self._ag_kapsam_damga = damga
        return not self._ag_kapsam.get("acik")

    def _ag_ip_izinli(self, ip):
        """ip allowlist'te mi? (hataya kapalı: ne pazarlık ne istisna.)"""
        if self._ag_kapali():
            return False
        try:
            adrs = ipaddress.ip_address(ip)
        except ValueError:
            return False
        try:
            return any(adrs in ag for ag in self._ag_kapsam.get("izin", []))
        except TypeError:   # sürüm karışımı (v6 vs v4) → kapsam dışı
            return False

    def _ag_adaylar(self):
        """Kapsamdaki tarama adayları.

        Döngü arayüzü ARP kanıtı üretemez → 127/8'de tek aday 127.0.0.1
        (16M host'luk sweep anlamsız). 1024'ten büyük ağlar kapsamda
        kalabilir ama tarama adayı yapılmaz — sweep bütçesi taşmaz.
        """
        if self._ag_kapali():   # kapsamı tazeler (canlı red) + kilit
            return []
        adaylar = []
        for ag in self._ag_kapsam.get("izin", []):
            if ag.is_loopback:
                adaylar.append("127.0.0.1")
            elif ag.num_addresses <= 1024:
                adaylar.extend(str(h) for h in ag.hosts())
        return adaylar

    def _ag_komsu_satiri(self, ip):
        """Kernel ARP komşu satırı (kernel'den, komut kapılarından bağımsız)."""
        try:
            r = subprocess.run(["ip", "neigh", "show", ip],
                               capture_output=True, text=True,
                               errors="replace", timeout=4, cwd=CWD)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return None
        for satir in (r.stdout or "").splitlines():
            if satir.strip().startswith(ip + " "):
                return satir
        return None

    def _ag_gercek(self, ip):
        """Zemin gerçeği (nötr öğretmen): kapı komutlarından BAĞIMSIZ.

        LAN: kernel ARP komşu tablosu — lladdr + REACHABLE/STALE/DELAY/
        PROBE → canlı, INCOMPLETE/FAILED → ölü. Döngü: arayüzün kendi
        durumu (ARP kanıtı yok). Kanıt yok → None: yargı False verir,
        yani emin olunmadan kazanç yok. _dogrula JUDGE-TIME çağırır:
        nmap/ping zaten ARP tablosunu tazeler → iddiaları anında teyit
        edilir (hücum → kanıt döngüsü; ödül yine uydurulmaz).
        """
        try:
            adrs = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if adrs.is_loopback:
            try:
                r = subprocess.run(["ip", "-o", "link", "show", "lo"],
                                   capture_output=True, text=True,
                                   errors="replace", timeout=4, cwd=CWD)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                return None
            return bool(re.search(r"<[^>]*\bUP\b[^>]*>", r.stdout or ""))
        satir = self._ag_komsu_satiri(ip)
        if not satir:
            return None
        par = satir.split()
        if any(d in par for d in AG_OLU_DURUMLAR):
            return False
        if "lladdr" in par and any(d in par for d in AG_CANLI_DURUMLAR):
            return True
        return None

    # ---------- BENI_TARA yardımcıları (Katman 1+2) ----------

    def _ben_tarama_acik(self):
        """BENI_TARA kapısı: master anahtar (acik) + bayrak (ben_tarama).

        VARSAYILAN RED: ben_tarama yoksa/false ise kendini tarama hiç
        üretilmez. Ayrıca 127.0.0.1 allowlist teyidi _harita ve
        _h_beni_tara'da ayrı ayrı yapılır (savunma derinliği).
        """
        if self._ag_kapali():          # kapsamı tazeler + kilit
            return False
        try:
            return bool(self._ag_kapsam.get("ben_tarama", False))
        except (AttributeError, TypeError, ValueError):
            return False

    def _ben_dinleme(self):
        """Kernel socket zemin gerçeği: dinleyen TCP port kümesi | None.

        /proc/net/tcp + tcp6, durum 0A = LISTEN — kapı komutlarından
        bağımsız (nmap/ss/curl ne derse desin GERÇEK budur; AG'deki
        ARP doktriniyle aynı). Hiçbir dosya okunamazsa None: yargı
        asla True veremez — kanıtsız kazanç yok.
        """
        portlar, okundu = set(), False
        for yol in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                with open(yol) as f:
                    satirlar = f.read().splitlines()[1:]
            except OSError:
                continue
            okundu = True
            for s in satirlar:
                p = s.split()
                if len(p) < 4 or p[3] != "0A":
                    continue          # 0A = LISTEN
                try:
                    portlar.add(int(p[1].rsplit(":", 1)[1], 16))
                except (ValueError, IndexError):
                    continue
        return portlar if okundu else None

    def _ben_http_port(self):
        """curl kapısının portu — iddia değil idari bilgi (ag_kapsam)."""
        try:
            return int(self._ag_kapsam.get("ben_http_port", 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _ss_dinleme(cikti):
        """ss çıktısından dinleyen port kümesi (yerel adres:port).

        'state listening' filtresiyle satır = iddia; port alınamazsa
        satır yok sayılır (boş küme eşitliği yakalar).
        """
        portlar = set()
        for s in cikti.splitlines():
            for tok in s.split():
                # yerel adres ilk "adres:port"tur; peer "*:*" rakam değil
                if ":" in tok and tok.rsplit(":", 1)[1].isdigit():
                    portlar.add(int(tok.rsplit(":", 1)[1]))
                    break
        return portlar

    def _h_ag_tara(self):
        """AG_TARA — kapsam içindeki bir host ('bu host canlı mı?').

        Aday seçimi: allowlist ∩ soğuma yok ∩ AZ DENENMİŞ (count-based
        keşif — elle yazılmış dal yok). komsu_var: 'ip neigh' kapısı
        yalnızca komşu satırı VARKEN açılır (DOSYA_OKU örnek kapısı
        gibi) — kanıtsız kapı hiç sorulmaz. Gerçek gerçeklik hedefe
        gömülmez; _dogrula anında kernel'den okur.
        """
        if self._ag_kapali():
            return None
        try:
            simdi = time.time()
            aralik = float(self._ag_kapsam.get(
                "ayni_hedef_aralik_sn", AG_VARSAYILAN["ayni_hedef_aralik_sn"]))
            adaylar = [ip for ip in self._ag_adaylar()
                       if self._ag_ip_izinli(ip)
                       and simdi - self._ag_son.get(ip, 0.0) >= aralik]
            if not adaylar:
                return None
            az = min(self._ag_denemeleri.get(ip, 0) for ip in adaylar)
            havuz = [ip for ip in adaylar
                     if self._ag_denemeleri.get(ip, 0) == az]
            ip = random.choice(havuz)
        except (ValueError, KeyError, TypeError):
            return None
        self._ag_son[ip] = simdi
        self._ag_denemeleri[ip] = self._ag_denemeleri.get(ip, 0) + 1
        komsu = False
        if not ipaddress.ip_address(ip).is_loopback:
            komsu = self._ag_komsu_satiri(ip) is not None
        return {"tip": "AG_TARA", "ip": ip, "komsu_var": komsu}

    def _h_beni_tara(self):
        """BENI_TARA — kendini tarama (Katman 1: port/servis keşfi).

        Hedef hep 127.0.0.1; KEŞİF alanı port aralığıdır: least-tried +
        soğuma ile aralıklar sırayla gezilir — aynı sayım mekanizması,
        elle yazılmış dal yok. Zemin gerçeği _ben_dinleme() (/proc);
        kapılar nmap -sV / ss / curl. ben_tarama kapalıysa hiç üretilmez.
        """
        if not self._ben_tarama_acik():
            return None
        if not self._ag_ip_izinli(BENI_IP):
            return None
        try:
            aralik_sn = float(self._ag_kapsam.get(
                "ayni_hedef_aralik_sn",
                AG_VARSAYILAN["ayni_hedef_aralik_sn"]))
            simdi = time.time()
            adaylar = [a for a in BENI_ARALIKLAR
                       if simdi - self._ben_son.get(a, 0.0) >= aralik_sn]
            if not adaylar:
                return None
            az = min(self._ben_denemeleri.get(a, 0) for a in adaylar)
            havuz = [a for a in adaylar
                     if self._ben_denemeleri.get(a, 0) == az]
            aralik = random.choice(havuz)
        except (ValueError, KeyError, TypeError):
            return None
        self._ben_son[aralik] = simdi
        self._ben_denemeleri[aralik] = self._ben_denemeleri.get(aralik, 0) + 1
        return {"tip": "BENI_TARA", "ip": BENI_IP, "aralik": aralik}

    # ---------- uygulama + nesnel ödül ----------

    def uygula(self, eylem):
        komut = eylem.split(":", 1)[-1]

        # ---- --help öğrenme: komutun ne işe yaradığını öğren ----------
        # eylem = "help:ls" → komut = "ls" ama eylem prefix'i "help:" olur
        if eylem.startswith("help:"):
            help_komut = komut
            basarili, aciklama = self._komut_tehlike.help_ogren(help_komut)
            if basarili:
                obs = "help:%s -> %s" % (help_komut, aciklama)
                self.jour.log("komut_help_ogren", komut=help_komut,
                              aciklama=aciklama)
                return {"obs": obs, "gain": ODUL_HELP, "cost": MALIYET,
                        "kind": "act", "dogru": True,
                        "argv": [help_komut, "--help"],
                        "komut_tehlike": 0.0,
                        "komut_ceza": False,
                        "komut_aciklama": aciklama}
            else:
                obs = "help:%s -> hata: %s" % (help_komut, aciklama)
                self.jour.log("komut_help_hata", komut=help_komut,
                              hata=aciklama)
                return {"obs": obs, "gain": 0.0, "cost": MALIYET,
                        "kind": "act", "dogru": False,
                        "argv": [help_komut, "--help"],
                        "komut_tehlike": 0.1,
                        "komut_ceza": False}

        # ---- Komut tehlike skoru (kendi kendini geliştiren sistem) ----
        # Komutu çalıştırmadan önce modeli sor: "bu komut tehlikeli mi?"
        # _ZARAR_TABLO'da olmayan komutlar varsayılan güvenli kabul edilir
        # (skor 0.1) ki ls/cat/ps gibi binlerce komut cezalandırılmasın.
        if komut in self._ZARAR_TABLO:
            _skor = self._komut_tehlike.tahmin(
                komut=komut,
                zarar_tipi=self._zarar_tipi(komut),
                enerji_etkisi=self._enerji_etkisi(komut),
                olum_olasiligi=self._olum_olasiligi(komut),
            )
        else:
            _skor = 0.1  # bilinmeyen komut: varsayılan güvenli
        if _skor >= self._komut_tehlike_esik:
            # Çok tehlikeli: çalıştır ama sert ceza ver (organizma öğrenmeli,
            # engellenmez — özgür keşif)
            _komut_tehlike_ceza = True
            _ceza_miktari = -10.0
        elif _skor >= self._komut_tehlike_ceza_esik:
            # Orta tehlikeli: çalıştır ama ceza ver
            _komut_tehlike_ceza = True
            _ceza_miktari = -5.0
        else:
            _komut_tehlike_ceza = False
            _ceza_miktari = 0.0

        if not self.hedef:
            self.don()
        if not self.hedef:
            return {"obs": "hedef kurulamadı", "gain": 0.0,
                    "cost": MALIYET, "kind": "act", "dogru": False}
        argv = self._argv_kur(komut)
        # komut bütçesi: BENI_TARA'nın -sV probe'ları ölçüldü ~14s
        # sürüyor (smb 139/445 + cevapsız soket) → bu tipe özel süre;
        # diğer tipler küresel ZAMAN_ASIMI'nda kalır
        sure = BENI_KOMUT_SURE if self.hedef["tip"] == "BENI_TARA" \
            else ZAMAN_ASIMI
        self._son_kap = None   # (test yolu: mock _kos eski kapı sonucu bırakmasın)
        ok, cikti, hata = self._kos(argv, sure=sure)
        kap = self._son_kap
        if kap is not None and not kap["calisti"]:
            # KAPI: komut alt sürece HİÇ gitmedi — yasaklı duvar (engel)
            # ya da mod dışı atlanma. Ara belleğe dokunulmaz (zincir
            # tamponu korunur), yargıç çalışmaz (çıktı yok → sahte ödül
            # yok). engel → sert ceza (KAPI_CEZA); atlandi → ölç, ceza
            # verme (golge doktrini: atla = mod kararı, ihlal değil).
            tip = self.hedef["tip"]
            deneme = self.hedef_deneme + 1
            self.denemeler += 1
            self.hedef_deneme = deneme
            duraklama = deneme >= 3
            if deneme >= 3:
                self.don()
            engel = bool(kap["engel"])
            gain = -KAPI_CEZA if engel else 0.0
            bas = "kapı engelledi" if engel else "kapı atladı"
            obs = "%s (%s): $ %s → %s" % (
                bas, tip, " ".join(argv), ozet(kap["neden"] or ""))
            return {"obs": obs, "gain": gain, "cost": MALIYET,
                    "kind": "act", "dogru": False, "argv": argv,
                    "deneme": deneme, "duraklama": duraklama,
                    "engel": engel}
        # ara bellek: bu adımın ÇIKTISI bir sonraki adımın girdisi olur
        # (wc/head dosyasız → stdin); TTL = hedef döngüsü (don'da sıfır)
        # tampon_dolu: ilerleme ödülü yalnızca İLK veri üretimine (gating)
        tampon_dolu = bool(self.ara.strip())
        self.ara = (cikti or "")[:ARA_TAVAN]
        dogru = self._dogrula(cikti, argv)
        self.denemeler += 1
        self.hedef_deneme += 1
        if dogru:
            self.dogrular += 1
            gain, bas = ODUL, "hedefi karşıladı"
        else:
            self.yanlislar += 1
            gain, bas = 0.0, "karşılamadı"
            if (self.hedef["tip"] in ZINCIR_TIPLERI
                    and cikti.strip() and argv[0] != "wc"):
                # ilerleme sinyali (Aşama 2): zincirde SAYMA adımı dışındaki
                # (veri üreten: ps/pgrep/find/ls/head) her dolu çıktı bir ara
                # adımdır. Eski kural (not isdigit) tek PID'li ps çıktısını
                # ("1234") yanlışlıkla sayı iddiası sanıp ilerleme sayılmıyordu
                # → SUREC_SAY neredeyse hiç ara adım alamıyordu. Oysa tek PID
                # de wc'ye girdi olur. Yalnızca wc'nin sayı iddiası yargılanır:
                # yanlış sayı (ör. boş tampondan wc → "0") ilerleme değil,
                # başarısızlıktır → ödül yok, bedel yine ödenir.
                # TAMPON GATING (2026-10-15): ölçüldü ki üretim döngüsü
                # ödülle besleniyordu (head 738 deneme/0 kazanç, yine de
                # ILERLEME topladı; 3. denemede kazanma %36-61). Tampon
                # doluyken veri üretmek ödülsüz → beyin tek mantıklı
                # hamleyi (wc ile bitirmeyi) seçmek zorunda.
                if tampon_dolu:
                    gain, bas = 0.0, "ara bellek zaten dolu"
                else:
                    gain, bas = ILERLEME, "ara veri üretti"
        obs = "%s (%s): $ %s → %s" % (
            bas, self.hedef["tip"], " ".join(argv),
            ozet(cikti or hata))
        # hedef başına deneme sınırı: eski küresel %3 sayacı hedefi
        # yanlış anda tazeliyordu; sayaç artık hedefe bağlı → deneme
        # tokenı iyi tanımlanır. don() sıfırlamadan ÖNCE okunur ki
        # yanıtta doğru sıra kalsın.
        deneme = self.hedef_deneme
        # duraklama (Faz 1 kanıtı): hedef 3 denemede karşılanamadı →
        # main bunu kullan_duraklama olarak jurnale döker (çevrimdışı
        # yeniden eğitimin hammaddesi: ölü kapı / ölçüm gürültüsü)
        duraklama = (not dogru and deneme >= 3)
        if dogru or self.hedef_deneme >= 3:
            self.don()
        # Orta/yüksek tehlikeliyse ceza uygula (organizma öğrenmeli:
        # komutu çalıştırınca enerji kaybı yaşar, ama engellenmez)
        if _komut_tehlike_ceza:
            gain = max(gain + _ceza_miktari, -20.0)
            obs = "%s [tehlikeli komut cezası: %.2f]" % (obs, _skor)
        return {"obs": obs, "gain": gain, "cost": MALIYET,
                "kind": "act", "dogru": dogru, "argv": argv,
                "deneme": deneme, "duraklama": duraklama,
                "komut_tehlike": _skor,
                "komut_ceza": _komut_tehlike_ceza,
                "komut_tip": komut_tehlike_mod._komut_tipi(komut)}

    # ---------- komut tehlike profili yardımcıları ----------

    _ZARAR_TABLO = {
        "rm": ("dosya_silme", -60, 0.9),
        "rmdir": ("dosya_silme", -40, 0.6),
        "dd": ("disk_yazma", -80, 0.95),
        "mkfs": ("dosya_sistemi", -100, 1.0),
        "fdisk": ("disk_bolumleme", -70, 0.85),
        "mount": ("dosya_sistemi", -30, 0.4),
        "umount": ("dosya_sistemi", -30, 0.4),
        "shutdown": ("sistem_kontrolu", -100, 1.0),
        "reboot": ("sistem_kontrolu", -100, 1.0),
        "init": ("sistem_kontrolu", -90, 0.9),
        "halt": ("sistem_kontrolu", -100, 1.0),
        "poweroff": ("sistem_kontrolu", -100, 1.0),
        "insmod": ("cekirdek_modulu", -70, 0.8),
        "modprobe": ("cekirdek_modulu", -60, 0.7),
        "rmmod": ("cekirdek_modulu", -70, 0.8),
        "chmod": ("izin_degistirme", -40, 0.5),
        "chown": ("izin_degistirme", -40, 0.5),
        "kill": ("surec_sonlandirma", -50, 0.7),
        "pkill": ("surec_sonlandirma", -50, 0.7),
        "killall": ("surec_sonlandirma", -50, 0.7),
        "iptables": ("ag_güvenliği", -60, 0.6),
        "docker": ("konteyner", -50, 0.6),
        "curl": ("ag_islemi", -10, 0.1),
        "wget": ("ag_islemi", -10, 0.1),
        "nc": ("ag_islemi", -30, 0.3),
        "ncat": ("ag_islemi", -30, 0.3),
        "tee": ("yazma_islemi", -20, 0.2),
    }

    def _zarar_tipi(self, komut):
        return self._ZARAR_TABLO.get(komut, ("bilinmeyen", 0, 0.0))[0]

    def _enerji_etkisi(self, komut):
        return self._ZARAR_TABLO.get(komut, ("bilinmeyen", 0, 0.0))[1]

    def _olum_olasiligi(self, komut):
        return self._ZARAR_TABLO.get(komut, ("bilinmeyen", 0, 0.0))[2]

    # ---------- argüman kurulumu (yalnızca hedef bilgisinden) ----------

    def _harita(self, h):
        """Hedef tipi → gerçek argv haritası (tek doğruluk kaynağı).

        eylemler() maskeyi bu haritadan, uygula() argv’yi buradan alır.
        Ölçüm (2026-10-14, 690 bin canlı deneme) sonrası ölü girişler
        silindi: haritada yalnızca doğrulanabilir komutlar var (ör.
        DISK_SOR’da df dışında 13 komut hiç kazanamadı → sunulmuyor).
        """
        tip = h["tip"]

        if tip == "DOSYA_BUL":
            ad, kok = h["ad"], h["kok"]
            yol = os.path.join(kok, ad)
            return {"find": ["find", kok, "-name", ad],
                    "ls": ["ls", kok],
                    "which": ["which", ad],
                    "file": ["file", ad],
                    "dpkg": ["dpkg", "-S", ad],
                    "apt-cache": ["apt-cache", "show", ad],
                    "realpath": ["realpath", yol],
                    "readlink": ["readlink", yol]}
        if tip == "PAKET_SOR":
            yol = h["yol"]
            return {"dpkg": ["dpkg", "-S", yol]}
        if tip == "DIZIN_LISTE":
            d = h["dizin"]
            return {"ls": ["ls", d],
                    "find": ["find", d, "-maxdepth", "1"],
                    "dpkg": ["dpkg", "-S", d],
                    "tree": ["tree", d]}
        if tip == "DOSYA_OKU":
            yol = h["yol"]
            # kapılar ÖRNEK varlığına göre açılır: doğrulanamayan kapı
            # maskede sunulursa deneme bütçesi israfıdır (ölü alan).
            if h.get("sikistirilmis"):
                # gz tek kapılı: wc -l gzip binary'nin newline sayısını
                # verir (yanlış gerçek), head/tail sıkıştırılmış baytı
                # basar → hepsi yanlış kapı. Doğru kapı: çözerek oku.
                return {"zcat": ["zcat", yol],
                        "xz": ["xz", "-dc", yol],
                        "bzip2": ["bzip2", "-dc", yol],
                        "zstd": ["zstd", "-dc", yol]}
            harita = {"wc": ["wc", "-l", yol]}
            if h.get("ornek_bas"):
                harita["head"] = ["head", "-n", "10", yol]
            if h.get("ornek_son"):
                harita["tail"] = ["tail", "-n", "10", yol]
            return harita
        if tip == "SUREC_SAY":
            # zincir hedefi: tek komut SAYIYI veremez. ps/pgrep → pid
            # listesi (ara adım); wc dosyasız → stdin = ara bellek.
            # pgrep tek başına pid bastığından zincirsiz geçemez.
            # head DÜŞTÜ (2026-10-15 ölçümü, 333 deneme/0 kazanç): pid
            # listesinin ilk satırını verir, sayı asla doğru olamaz.
            # wc KAPISI TAMPON DOLUYKEN (2026-10-16 ölçümü, yeni dönem):
            # bos tamponda wc -l "0" basar → gercek (>=1) asla eslesmez.
            # DOSYA_SAY'de wc-ile-baslamak 1541 dongude %4.6 kazandi;
            # SUREC_SAY'de "wc→wc→1==1" tesaduf kanali %71 gorunuyordu
            # ama uretici adimli yollar %89-90 — kanal tesadufu degil
            # dogru iliskiyi ogretiyordu. Artik uretim oncesi wc SUNULMAZ.
            ad = h["ad"]
            harita = {"ps": ["ps", "-C", ad, "-o", "pid="],
                      "pgrep": ["pgrep", "-x", ad]}
            if (self.ara or "").strip():
                harita["wc"] = ["wc", "-l"]   # dosya YOK → stdin
            return harita
        if tip == "DOSYA_SAY":
            # head DÜŞTÜ (2026-10-15 ölçümü, 405 deneme/0 kazanç).
            # ls kalan (2026-10-16: duz doc dizinlerinde find ile esit
            # %71/74) — tuzak degil, canli kapidir.
            # wc kapisi bos tamponda kapali: "0" iddiasi gercek (1..3000)
            # ile hic eslesmez — 1541 dongu/57 kazanc (%4.6) olcu dustu.
            d = h["dizin"]
            harita = {"find": ["find", d, "-type", "f"],
                      "ls": ["ls", d]}
            if (self.ara or "").strip():
                harita["wc"] = ["wc", "-l"]   # tampon dolu → stdin
            return harita
        if tip == "SUREC_SOR":
            ad = h["ad"]
            return {"ps": ["ps", "-C", ad, "-o", "comm="],
                    "pgrep": ["pgrep", "-x", ad],
                    "lsof": ["lsof", "-c", ad],
                    "pstree": ["pstree", ad]}
        if tip == "SERVIS_SOR":
            u = h["birim"]
            # eski "ps" girişi ölçümde hiç kazanamadı (comm ≠ durum) → düştü
            return {"systemctl": ["systemctl", "is-active", u]}
        if tip == "DISK_SOR":
            m = h["birim"]
            return {"df": ["df", "-h", m],
                    "lsblk": ["lsblk"]}
        if tip == "AG_SOR":
            a = h["arayuz"]
            return {"ip": ["ip", "addr", "show", a],
                    "nstat": ["nstat"],
                    "lnstat": ["lnstat"],
                    "netstat": ["netstat", "-i"],
                    "resolveip": ["resolveip", "-n", a],
                    "dig": ["dig", "+short", a],
                    "nslookup": ["nslookup", a]}
        if tip == "DOSYA_OLC":
            yol = h["yol"]
            return {"stat": ["stat", "-c", "%s", yol],
                    "wc": ["wc", "-c", yol],
                    "du": ["du", "-sb", yol]}
        if tip == "PAKET_VERSIYON":
            paket = h["paket"]
            return {"dpkg": ["dpkg", "-s", paket],
                    "apt-cache": ["apt-cache", "policy", paket]}
        if tip == "AG_TARA":
            # KAPSAM KİLİDİ: kapı yalnızca allowlist'teki ip'de açılır;
            # argv yine modülde kurulur (dış girdi yok, shell yok).
            ip = h.get("ip", "")
            if not self._ag_ip_izinli(ip):
                return {}          # kapsam dışı → hiçbir kapı yok
            k = self._ag_kapsam
            harita = {
                "nmap": ["nmap", "-sn", "-n",
                         "--host-timeout",
                         str(k.get("nmap_hedef_zaman_asimi",
                                   AG_VARSAYILAN["nmap_hedef_zaman_asimi"])),
                         "--max-rate",
                         str(k.get("nmap_hiz_tavan",
                                   AG_VARSAYILAN["nmap_hiz_tavan"])),
                         ip],
                "ping": ["ping",
                         "-c", str(k.get("ping_paket",
                                         AG_VARSAYILAN["ping_paket"])),
                         "-W", str(k.get("ping_bekle_sn",
                                         AG_VARSAYILAN["ping_bekle_sn"])),
                         ip],
                "traceroute": ["traceroute", "-n", "-w", "2", "-q", "1", ip],
            }
            if h.get("komsu_var"):   # kanıt varsa ARP kapısı da açık
                harita["ip"] = ["ip", "neigh", "show", ip]
            return harita

        if tip == "BENI_TARA":
            # KAPSAM KİLİDİ (ben_tarama): kapalıyken kapı bile yok
            if not self._ben_tarama_acik() or not self._ag_ip_izinli(BENI_IP):
                return {}
            k = self._ag_kapsam
            aralik = h.get("aralik") or BENI_ARALIKLAR[0]
            harita = {
                # port tarama + servis keşfi. intensity 0: en hafif sürüm
                # probe'ları — sahada 6-7s (intensiz 20s+ oluyor, --host-
                # timeout probe ortasında kesmiyor); yargı yine de yalnız
                # açık port kümesiyle (kernel /proc) karşılaştırılır
                "nmap": ["nmap", "-sV", "--version-intensity", "0",
                         "-Pn", "-n", "-p", aralik,
                         "--host-timeout",
                         str(k.get("ben_zaman_asimi", "18s")),
                         BENI_IP],
                # dinleyen portların anlık kümesi (kernel'e en yakın kapı)
                "ss": ["ss", "-Htan", "state", "listening"],
                "traceroute": ["traceroute", "-n", "-w", "2", "-q", "1",
                               BENI_IP],
            }
            port = self._ben_http_port()
            if 0 < port < 65536:
                harita["curl"] = ["curl", "-s", "-o", "/dev/null",
                                  "-w", "%{http_code}", "--max-time", "5",
                                  "http://%s:%d/" % (BENI_IP, port)]
            return harita
        if tip == "SISTEM_SOR":
            # Aşama 6: Debian'ı yönetme — cpu/bellek/çekirdek durumu.
            # Her konu için yalnızca doğrulanabilir kapılar sunulur.
            konu = h.get("konu")
            if konu == "cpu":
                # lscpu tam çıktısı 4KB kota sınırını aşabilir (Türkçe
                # locale da "CPU(s)" yerine farklı başlık basabilir).
                # lscpu (tam çıktı ~1-2KB <4KB kota); judge "CPU(s): N"
                # satırını doğrular. "--parse=CPU"/nproc eski regresyon
                # (333+405 deneme → 0 kazanç; test _harita=={"lscpu":["lscpu"]}).
                return {"lscpu": ["lscpu"]}
            if konu == "bellek":
                return {"free": ["free"]}
            return {"uname": ["uname", "-r"]}
        if tip == "DOSYA_OZET":
            # bütünlük: iki hash kapısı, tek gerçektir (hashlib judge)
            yol = h["yol"]
            return {"md5sum": ["md5sum", yol],
                    "sha256sum": ["sha256sum", yol]}
        if tip == "DOSYA_HAM":
            # ham bayt: çıktı 64 baytla sınırlı (zaman aşımı/gürültü yok)
            yol = h["yol"]
            return {"hexdump": ["hexdump", "-C", "-n", "64", yol],
                    "xxd": ["xxd", "-l", "64", yol]}
        if tip == "KONFIG_OKU":
            yol = h["yol"]
            return {"head": ["head", "-n", "10", yol],
                    "tail": ["tail", "-n", "10", yol],
                    "grep": ["grep", "-c", ".", yol]}
        if tip == "LOG_OKU":
            yol = h["yol"]
            return {"tail": ["tail", "-n", "10", yol],
                    "head": ["head", "-n", "5", yol]}
        if tip == "PORTA_DINLE":
            return {"ss": ["ss", "-tlnp"],
                    "ps": ["ps", "-eo", "pid=,comm="]}
        # METIN_ARA
        yol, kalip = h["yol"], h["kalip"]
        # kalip dosyanın KENDİ satırıdır: yalnızca içeriğe bakabilenler
        # kazanabilir. dpkg/wc geçmişte "korelasyon tuzağıyla" kazanıyordu
        # (kalip yolla çakışınca) — beceri değil gürültü, haritadan düştü.
        return {"grep": ["grep", "-nF", "--", kalip, yol],
                "head": ["head", "-n", "10", yol]}

    def _argv_kur(self, komut):
        # uygula() kapısı: harita tek kaynak; maske dışı seçim ["true"]
        return self._harita(self.hedef).get(komut, ["true"])

    # ---------- nesnel öğretmen ----------

    def _dogrula(self, cikti, argv=None):
        """Çıktı hedefi karşılıyor mu? (kural tablosu yok: dosya sistemi
        ve dpkg'nin kendi çıktısı yargılar.)"""
        h = self.hedef
        if not h or not cikti.strip():
            return False
        tip = h["tip"]

        if tip == "DOSYA_BUL":
            ad, kok = h["ad"], h["kok"]
            for satir in cikti.splitlines():
                for tok in satir.replace(":", " ").split():
                    t = tok.rstrip(",;")
                    if os.path.basename(t) == ad and (
                            (t.startswith(kok + "/") and os.path.isfile(t))
                            or (t == ad and os.path.isfile(
                                os.path.join(kok, ad)))):
                        return True
            return False

        if tip == "PAKET_SOR":
            yol = h["yol"]
            for satir in cikti.splitlines():
                s = satir.strip()
                if ":" not in s:
                    continue
                # dpkg -S çoklu sahipte virgülle listeler:
                #   "coreutils: /usr/bin/ls, /bin/ls" → her aday eşit midir?
                # çoklu mimaride sonek var:
                #   "libnpth0:amd64: /usr/share/doc/..." → mimariyi atla
                _paket, yollar = s.split(":", 1)
                if ":" in yollar:
                    _mimari, yollar = yollar.split(":", 1)
                for aday in yollar.split(","):
                    if aday.strip() == yol:
                        return True
            return False

        if tip == "DIZIN_LISTE":
            d = h["dizin"]
            kume = set(h["icindekiler"])
            bulunan = set()
            for satir in cikti.splitlines():
                for tok in satir.replace(":", " ").split():
                    t = tok.rstrip("/,;")
                    b = os.path.basename(t)
                    if b in kume and (not t.startswith("/")
                                      or os.path.dirname(t) == d):
                        bulunan.add(b)
            return len(bulunan) >= max(1, len(kume) // 2)

        if tip == "DOSYA_OKU":
            # üç kapı, tek gerçek: wc sayı kanıtı; head/tail içerik kanıtı
            # (ornek_bas / ornek_son satırı gerçekten basmalı)
            argv0 = (argv or [None])[0]
            if h.get("sikistirilmis") and argv0 not in ("zcat", "xz", "bzip2", "zstd"):
                # savunma katmanı: sıkıştırılmış dosyada doğrulayıcı ASLA
                # sıkıştırılmış baytın sayısını/kırıntısını gerçek kabul etmez
                # (maske zaten ["true"] verir; bu, son kapı).
                return False
            if argv0 in ("zcat", "xz", "bzip2", "zstd"):
                # sıkıştırılmış dosya: çözülmüş çıktı ÖRNEK satırı içermeli
                n = h.get("ornek_bas") or h.get("ornek_son")
                return bool(n) and n in cikti
            if argv0 == "head":
                n = h.get("ornek_bas")
                return bool(n) and n in cikti
            if argv0 == "tail":
                n = h.get("ornek_son")
                return bool(n) and n in cikti
            ad = os.path.basename(h["yol"])
            for satir in cikti.splitlines():
                m = re.match(r"^\s*\d+\s+(\S.*)$", satir)
                if m and os.path.basename(m.group(1).strip()) == ad:
                    return True
            return False

        if tip == "METIN_ARA":
            return h["kalip"] in cikti

        if tip == "SUREC_SAY":
            ad = h["ad"]
            try:
                sayi = int(cikti.strip())
            except ValueError:
                return False      # sayı değil → zincir henüz tamamlanmadı
            gercek = _surec_say(ad)
            return gercek >= 1 and sayi == gercek

        if tip == "DOSYA_SAY":
            try:
                sayi = int(cikti.strip())
            except ValueError:
                return False
            gercek = _dizin_say(h["dizin"])
            return gercek >= 1 and sayi == gercek

        if tip == "SUREC_SOR":
            ad = h["ad"]
            # pgrep yalnızca PID basar: rakam çıktısı = "var" cevabı
            if argv and argv[0] == "pgrep":
                bos = cikti.split()
                return bool(bos) and all(t.isdigit() for t in bos)
            # lsof -c ad / pstree ad: işlem adı veya PID'li çıktı içermeli
            if argv and argv[0] in ("lsof", "pstree"):
                return ad in cikti
            for satir in cikti.splitlines():
                if satir.strip() == ad:
                    return True
            return False

        if tip == "SERVIS_SOR":
            bek = h["beklenen"]   # zemin gerçeği: systemctl is-active
            for satir in cikti.splitlines():
                s = satir.strip()
                if s.split() and s.split()[0] == bek:
                    return True
                if "Active:" in s:
                    alan = s.replace(":", " : ").split()
                    for i, tok in enumerate(alan):
                        if tok == "Active" and i + 1 < len(alan) \
                                and alan[i + 1] == bek:
                            return True
            return False

        if tip == "DISK_SOR":
            m = h["birim"]
            if argv and argv[0] == "lsblk":
                # lsblk: blok cihaz listesi, mount noktası veya cihaz adı geçmeli
                return m in cikti
            return m in cikti and "%" in cikti

        if tip == "AG_SOR":
            a = h["arayuz"]
            argv0 = (argv or [None])[0]
            if argv0 == "nstat":
                # nstat: SNMP ağ sayaçları, "anahtar: sayı" satırları
                return bool(re.search(r"^\w+:\s+\d+", cikti, re.MULTILINE))
            if argv0 == "lnstat":
                # lnstat: /proc/net istatistikleri, sayısal sütunlu satırlar
                return bool(re.search(r"\d+\s+\d+", cikti))
            if argv0 == "netstat":
                # netstat -i: arayüz tablosu, arayüz adı veya başlık geçmeli
                return a in cikti or "Kernel" in cikti or "Iface" in cikti
            if argv0 == "resolveip":
                # resolveip: hostname→IP çözümü, IPv4 adresi geçmeli
                return bool(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", cikti))
            if argv0 in ("dig", "nslookup"):
                # dig +short / nslookup: çözümlenmiş IPv4 adresi geçmeli
                return bool(re.search(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", cikti))
            # varsayılan: ip addr show a
            if a not in cikti:
                return False
            return ("inet" in cikti or "link/" in cikti
                    or "state" in cikti or "LOOPBACK" in cikti)

        if tip == "DOSYA_OLC":
            # bağımsız öğretmen: getsize (komutların üçü de aynı sayıya
            # çıkmalı — stat %s / wc -c / du -sb)
            try:
                gercek = os.path.getsize(h["yol"])
            except OSError:
                return False
            m = re.search(r"\d+", cikti)
            return bool(m) and int(m.group(0)) == gercek

        if tip == "SISTEM_SOR":
            # Aşama 6: zemin gerçeği judge-time okunur (kernel /proc).
            konu = h.get("konu")
            if konu == "cpu":
                # lscpu --parse=CPU: başında # yorum satırları, son satır
                # sadece rakam (cpu thread sayısı). nproc da sadece rakam.
                # Her iki çıktı da os.cpu_count() ile karşılaştırılır.
                # Eski "lscpu" tam çıktısı (CPU(s): N) da desteklenir.
                n = os.cpu_count()
                if not n:
                    return False
                # nproc / lscpu --parse son satırı: sadece rakam
                satirlar = [s.strip() for s in cikti.splitlines()
                            if s.strip() and not s.strip().startswith("#")]
                if satirlar:
                    # nproc: tek satır, cpu sayısı
                    if len(satirlar) == 1 and satirlar[0].isdigit():
                        return int(satirlar[0]) == n
                    # lscpu --parse=CPU: N satır (her biri 0..N-1 id'si)
                    if all(s.isdigit() for s in satirlar):
                        return len(satirlar) == n
                # lscpu tam çıktısı: "CPU(s):\s*N"
                return bool(re.search(r"CPU\(s\):\s*%d\b" % n, cikti))
            if konu == "bellek":
                # free: "Mem:  <toplam> ..." (kB) — /proc/meminfo MemTotal
                m = re.search(r"^Mem:\s+(\d+)", cikti, re.MULTILINE)
                try:
                    with open("/proc/meminfo", "r") as f:
                        gercek = int(f.readline().split()[1])
                except (OSError, ValueError, IndexError):
                    return False
                return bool(m) and int(m.group(1)) == gercek
            # cekirdek: uname -r == platform.release (kernel sürümü)
            return cikti.strip() == platform.release()

        if tip == "DOSYA_OZET":
            # bütünlük: hash dosyanın kendisinden judge-time hesaplanır
            yol = h["yol"]
            argv0 = (argv or [None])[0]
            if argv0 == "md5sum":
                hsh = hashlib.md5()
            elif argv0 == "sha256sum":
                hsh = hashlib.sha256()
            else:
                return False
            try:
                with open(yol, "rb") as f:
                    for parca in iter(lambda: f.read(65536), b""):
                        hsh.update(parca)
            except OSError:
                return False
            return hsh.hexdigest() in cikti

        if tip == "DOSYA_HAM":
            # ilk 8 baytın hex gösterimi çıktıda bulunmalı (hexdump
            # "7f 45 4c 46" / xxd "7F45 4C46" — noktalama atılınca aynı)
            argv0 = (argv or [None])[0]
            if argv0 not in ("hexdump", "xxd"):
                return False
            try:
                with open(h["yol"], "rb") as f:
                    ilk = f.read(8)
            except OSError:
                return False
            if len(ilk) < 8:
                return False
            duz = re.sub(r"[^0-9a-fA-F]", "", cikti).lower()
            return ilk.hex() in duz

        if tip == "PAKET_VERSIYON":
            # sürüm dizesi dpkg-query'den geldi; dpkg -s / apt-cache
            # policy aynı gerçeği basmalı
            return h["surum"] in cikti

        if tip == "AG_TARA":
            ip = h.get("ip", "")
            if not self._ag_ip_izinli(ip):
                return False   # kapsam dışı: asla kazanamaz (kapı da kapalı)
            gercek = self._ag_gercek(ip)   # judge-time zemin gerçeği
            if gercek is None:
                return False   # kanıt yok → emin olunmadan kazanç yok
            argv0 = (argv or [None])[0]
            if argv0 == "nmap":
                if gercek:
                    return ("Host is up" in cikti
                            and re.search(r"\b" + re.escape(ip) + r"\b",
                                          cikti) is not None)
                # ölü host'ta ip yazılmayabilir: kanıt "0 hosts up"
                return ("Host seems down" in cikti
                        or "0 hosts up" in cikti)
            if argv0 == "ping":
                if gercek:
                    return re.search(r"bytes from " + re.escape(ip) + r"\b",
                                     cikti) is not None
                return ("0 received" in cikti
                        or "100% packet loss" in cikti)
            if argv0 == "ip":
                # kapı yalnızca komşu satırı varken açıldı; satır GERÇEĞİ
                # yansıtmalı — aynı tablonun kendisi (SERVIS_SOR'daki
                # is-active ile aynı tasarım: öğretmen = kapının kaynağı)
                satir = next((s for s in cikti.splitlines()
                              if s.strip().startswith(ip + " ")), None)
                if not satir:
                    return False
                par = satir.split()
                if gercek:
                    return ("lladdr" in par
                            and any(d in par for d in AG_CANLI_DURUMLAR))
                return any(d in par for d in AG_OLU_DURUMLAR)
            if argv0 == "traceroute":
                # traceroute: hedef IP çıktıda geçmeli (en az bir hop)
                return ip in cikti
            return False

        if tip == "BENI_TARA":
            # Zemin gerçeği: /proc LISTEN seti — kapı komutundan bağımsız
            gercek = self._ben_dinleme()
            if gercek is None:
                return False      # kanıt yok → emin olunmadan kazanç yok
            argv0 = (argv or [None])[0]
            if argv0 == "nmap":
                # her satır bir iddia: open ⇔ kernel'de LISTEN;
                # closed/filtered ⇔ değil.
                iddialar = re.findall(r"^(\d+)/tcp\s+(\S+)", cikti, re.M)
                if not iddialar:
                    # Normal bitiş + boş tablo = "aralıkta açık port yok"
                    # iddiası (kernel yine usta: o aralıkta gerçekten
                    # dinleyen varsa False). "Nmap done" yoksa çıktı yarım
                    # (timeout/kill) → kanıt yok → False.
                    if "Nmap done" not in cikti:
                        return False
                    try:
                        a, b = (int(x) for x in
                                argv[argv.index("-p") + 1].split("-", 1))
                    except (ValueError, IndexError):
                        return False
                    return not any(a <= p <= b for p in gercek)
                return all((durum == "open") == (int(p) in gercek)
                           for p, durum in iddialar)
            if argv0 == "ss":
                # iki görünüm eşitliği: ss iddia seti == kernel seti
                iddia = self._ss_dinleme(cikti)
                return bool(iddia) and iddia == gercek
            if argv0 == "curl":
                # iki görünüm: HTTP 200 (sunucu) + o port kernel'de LISTEN
                port = self._ben_http_port()
                return port != 0 and port in gercek \
                    and cikti.strip() == "200"
            if argv0 == "traceroute":
                # traceroute: kendine (127.0.0.1) yönelik çıktı geçmeli
                return BENI_IP in cikti
            return False

        if tip == "KONFIG_OKU":
            # Config dosyası: head/tail çıktısı dosyanın içeriğinden
            # gelir. grep -c '.' toplam satır sayısıdır. Doğrulayıcı:
            # dosyayı doğrudan oku, satır sayısını karşılaştır.
            try:
                with open(h["yol"], "r", errors="replace") as f:
                    gercek_satir = len(f.readlines())
            except OSError:
                return False
            argv0 = (argv or [None])[0]
            if argv0 == "grep":
                # grep -c '.' → satır sayısı
                m = re.match(r"(\d+)", cikti.strip())
                return bool(m) and int(m.group(1)) == gercek_satir
            # head/tail: çıktıdaki her satır dosyada var olmalı
            cikti_satir = [s for s in cikti.splitlines() if s.strip()]
            if not cikti_satir:
                return False
            try:
                with open(h["yol"], "r", errors="replace") as f:
                    icerik = f.read()
            except OSError:
                return False
            return all(s in icerik for s in cikti_satir)

        if tip == "LOG_OKU":
            # Log dosyası: tail son N satır, head ilk N satır.
            # Doğrulayıcı: dosyayı doğrudan oku, satırları karşılaştır.
            try:
                with open(h["yol"], "r", errors="replace") as f:
                    tum_satir = f.readlines()
            except OSError:
                return False
            if not tum_satir:
                return False
            argv0 = (argv or [None])[0]
            if argv0 == "tail":
                # son 10 satır: dosyadan doğrudan oku
                gercek = [s.rstrip("\n") for s in tum_satir[-10:]]
            elif argv0 == "head":
                # ilk 5 satır
                gercek = [s.rstrip("\n") for s in tum_satir[:5]]
            else:
                return False
            cikti_satir = [s for s in cikti.splitlines() if s.strip()]
            # Çıktı, gerçeğin son kısmıyla eşleşmeli
            return (len(cikti_satir) > 0
                    and all(any(cs in gs or gs in cs
                                for gs in gercek)
                            for cs in cikti_satir))

        if tip == "PORTA_DINLE":
            # Port dinleme: ss -tlnp çıktısında LISTEN satırları var mı?
            # Doğrulayıcı: /proc/net/tcp'den LISTEN (durum 0A) sayısı.
            argv0 = (argv or [None])[0]
            if argv0 == "ss":
                # ss çıktısında LISTEN var mı?
                return "LISTEN" in cikti and cikti.strip() != ""
            if argv0 == "ps":
                # ps süreç listesi: her zaman bir şey döner
                # ama port bilgisi vermez → yanlış kapı
                return False
            return False

        return False

    def _kos(self, argv, sure=None):
        # stdin = ara bellek (zincir Aşama 2): dosya argv'li komutlar
        # girdiyi görmezden gelir; dosyasız wc/head/grep bu tamponu okur.
        # AELAAN kapısı (golge.py): komut gölge modundan geçer — okuma
        # çalışır, yıkıcı "atlandi" (mod kararı), yasaklı ASLA başlamaz
        # (engel). Sonuç _son_kap'ta: uygula() engel cezasını oradan okur.
        # Fail-closed: kapı çökerse komut çalışmaz, öğrenme durmaz ama
        # hiçbir alt süreç doğrudan çağrılmaz.
        self._son_kap = None
        try:
            res = self._kapi.calistir({
                "komut": " ".join(shlex.quote(a) for a in argv),
                "hedef": (self.hedef or {}).get("tip"),
                "stdin": self.ara or "",
                "sure": sure or ZAMAN_ASIMI})
        except Exception:      # noqa: BLE001 — kapı hatası = kapalı kapı
            return False, "", "(kapı hatası)"
        self._son_kap = res
        if not res["calisti"]:
            return False, "", res["neden"] or ("(kapı: %s)" % res["sinif"])
        return (res["rc"] == 0, res["cikti"] or "",
                (res["hata"] or "").strip())

    # ---------- rapor ----------

    def rapor(self):
        return {"denemeler": self.denemeler, "dogru": self.dogrular,
                "yanlis": self.yanlislar,
                "hedef": (self.hedef or {}).get("tip")}
