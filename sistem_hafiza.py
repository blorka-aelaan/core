"""sistem_hafiza — sistemin sabit/yarı-sabit özelliklerini öğren ve sakla.

Organizma her başlatmada bunları sıfırdan keşfetmek zorunda kalmaz.
Dosya: zeka/sistem_hafiza.json  (atomik, her güncellemede yeniden yazılır)

Öğrenilenler:
  cpu      — çekirdek sayısı, mimari, model adı
  ram      — toplam RAM (KB), yaklaşık sınıf
  kernel   — kernel sürümü
  dagitim  — işletim sistemi adı + sürümü
  hostname — makine adı
  disk     — bağlı dosya sistemleri (/, /home vb.)
  ag       — ağ arayüzleri ve MAC adresleri (gizli tutulur: hash)
  guc      — batarya var mı? (laptop/masaüstü/sunucu tahmini)

Organizma main.py'de başlarken sistem_hafiza.yukle() ile okur;
bağlam jetonları brain.stimulus()'a geçirilir.
Her 24 saatte bir (uyku döngüsünde) sistem_hafiza.tazele() çağrılır:
sabit değerler (cpu, mimari) korunur, değişkenler (disk doluluk) güncellenir.

Kullanım:
    import sistem_hafiza
    sh = sistem_hafiza.yukle()          # varsa oku, yoksa öğren
    jetonu = sistem_hafiza.jeton(sh)    # beyin uyaran tokenı
"""
import hashlib
import json
import os
import platform
import re
import subprocess
import time
from pathlib import Path

import zeka

DOSYA = "sistem_hafiza.json"
GUNCELLEME_ARALIK = 86400   # 24 saat (saniye)
SURUM = 1


# ---------- yardımcı: sessiz komut çalıştır ----------

def _calistir(argv, timeout=8):
    """Komutu çalıştır, (ok, çıktı) döndür. Hata → ("", False)."""
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True,
            errors="replace", timeout=timeout,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "LC_ALL": "C"})
        return r.returncode == 0, r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


# ---------- öğrenme fonksiyonları ----------

def _cpu_ogren():
    """CPU bilgisi: çekirdek sayısı, mimari, model adı."""
    cekirdek = os.cpu_count() or 0
    mimari = platform.machine()           # x86_64, aarch64, ...

    # Model adı: /proc/cpuinfo
    model = ""
    try:
        with open("/proc/cpuinfo", "r", errors="replace") as f:
            for satir in f:
                if satir.startswith("model name"):
                    model = satir.split(":", 1)[1].strip()
                    break
    except OSError:
        pass

    # Frekans (MHz): ilk çekirdeğin max frekansı
    frekans_mhz = 0
    try:
        frek_yol = "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq"
        with open(frek_yol) as f:
            frekans_mhz = int(f.read().strip()) // 1000
    except (OSError, ValueError):
        ok, cikti = _calistir(["lscpu", "--parse=MAXMHZ"])
        if ok:
            satirlar = [s for s in cikti.splitlines()
                        if s.strip() and not s.startswith("#")]
            try:
                frekans_mhz = int(float(satirlar[0])) if satirlar else 0
            except (ValueError, IndexError):
                pass

    return {
        "cekirdek": cekirdek,
        "mimari": mimari,
        "model": model[:80] if model else "bilinmiyor",
        "frekans_mhz": frekans_mhz,
    }


def _ram_ogren():
    """RAM: toplam ve kullanılabilir (KB), sınıf etiketi."""
    toplam_kb = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for satir in f:
                if satir.startswith("MemTotal:"):
                    toplam_kb = int(satir.split()[1])
                    break
    except (OSError, ValueError):
        pass

    # Sınıf: yaklaşık GB
    gb = toplam_kb / (1024 * 1024)
    if gb < 2:
        sinif = "1gb"
    elif gb < 6:
        sinif = "4gb"
    elif gb < 14:
        sinif = "8gb"
    elif gb < 28:
        sinif = "16gb"
    elif gb < 56:
        sinif = "32gb"
    else:
        sinif = "64gb+"

    return {"toplam_kb": toplam_kb, "sinif": sinif}


def _disk_ogren():
    """Bağlı dosya sistemleri: bağlama noktası, toplam/kullanılan GB, tip."""
    # df bazen exit code 1 döner (bir mount noktasına erişemez) ama
    # stdout yine de dolu olur — çıktıyı kullan, exit code'a güvenme.
    _, cikti = _calistir(["df", "-PT", "--block-size=1M"])
    diskler = []
    if cikti:
        for satir in cikti.splitlines()[1:]:
            parcalar = satir.split()
            if len(parcalar) < 7:
                continue
            aygit, tip, toplam, kullan, bos, _, bagla = parcalar[:7]
            # Sahte dosya sistemlerini atla
            if tip in ("tmpfs", "devtmpfs", "sysfs", "proc",
                       "cgroup", "cgroup2", "pstore", "bpf",
                       "tracefs", "debugfs", "securityfs",
                       "fusectl", "mqueue", "hugetlbfs"):
                continue
            try:
                diskler.append({
                    "baglama": bagla,
                    "tip": tip,
                    "toplam_mb": int(toplam),
                    "kullan_mb": int(kullan),
                    "aygit": aygit,
                })
            except ValueError:
                continue
    return diskler


def _ag_ogren():
    """Ağ arayüzleri: ad, durum, IP (varsa). MAC hash'lenir (gizlilik)."""
    arayuzler = []
    ag_yolu = Path("/sys/class/net")
    if not ag_yolu.exists():
        return arayuzler

    for arayuz in sorted(ag_yolu.iterdir()):
        ad = arayuz.name
        if ad == "lo":
            continue
        # MAC → sha256'nın ilk 12 hex karakteri (geri alınamaz ama tanımlayıcı)
        mac_hash = ""
        try:
            mac = (arayuz / "address").read_text().strip()
            if mac and mac != "00:00:00:00:00:00":
                mac_hash = hashlib.sha256(mac.encode()).hexdigest()[:12]
        except OSError:
            pass

        # Operasyonel durum
        try:
            durum = (arayuz / "operstate").read_text().strip()
        except OSError:
            durum = "bilinmiyor"

        # IP adresi (varsa)
        ip = ""
        ok, cikti = _calistir(["ip", "-4", "addr", "show", ad])
        if ok:
            m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", cikti)
            if m:
                ip = m.group(1)

        arayuzler.append({
            "ad": ad,
            "durum": durum,
            "mac_hash": mac_hash,
            "ip": ip,
        })
    return arayuzler


def _guc_ogren():
    """Güç kaynağı: batarya var mı? → laptop/masaustu/sunucu tahmini."""
    pil_yolu = Path("/sys/class/power_supply")
    if pil_yolu.exists():
        for p in pil_yolu.iterdir():
            tip_dosya = p / "type"
            try:
                if tip_dosya.read_text().strip() == "Battery":
                    return "laptop"
            except OSError:
                pass
    # Güç adaptörü kontrolü
    try:
        for p in pil_yolu.iterdir():
            if "AC" in p.name or "Mains" in p.name:
                return "masaustu"
    except (OSError, NameError):
        pass
    return "sunucu"


def _dagitim_ogren():
    """Dağıtım adı ve sürümü: /etc/os-release'den."""
    bilgi = {"ad": "", "surum": "", "kod_adi": ""}
    try:
        with open("/etc/os-release", "r") as f:
            for satir in f:
                satir = satir.strip()
                if satir.startswith("PRETTY_NAME="):
                    bilgi["ad"] = satir.split("=", 1)[1].strip('"')
                elif satir.startswith("VERSION_CODENAME="):
                    bilgi["kod_adi"] = satir.split("=", 1)[1].strip('"')
                elif satir.startswith("VERSION_ID="):
                    bilgi["surum"] = satir.split("=", 1)[1].strip('"')
    except OSError:
        bilgi["ad"] = platform.system() + " " + platform.release()
    return bilgi


def _kurulu_paket_sayisi():
    """dpkg ile kaç paket kurulu."""
    ok, cikti = _calistir(["dpkg", "--get-selections"])
    if ok:
        return sum(1 for s in cikti.splitlines()
                   if "\tinstall" in s or s.endswith("install"))
    return 0


def _servis_haritasi():
    """Çalışan systemd servisleri → liste.

    systemctl list-units --type=service --state=running çıktısını
    ayrıştırır. Organizma "bu makinede nginx, postgresql, sshd çalışıyor"
    bilgisini taşır — SERVIS_SOR görevleri bu bağlamdan kazanır.
    """
    ok, cikti = _calistir(
        ["systemctl", "list-units", "--type=service",
         "--state=running", "--no-legend", "--no-pager"])
    servisler = []
    if ok and cikti:
        for satir in cikti.splitlines():
            parcalar = satir.split(None, 4)
            # Format: UNIT LOAD ACTIVE SUB DESCRIPTION
            # parcalar[2]="active", parcalar[3]="running"
            if len(parcalar) >= 4 and parcalar[3] == "running":
                servisler.append({
                    "ad": parcalar[0].replace(".service", ""),
                    "durum": "running",
                })
    return servisler


def _dinleyen_portlar():
    """Açık portlar: ss -tlnp çıktısından. Dışa açık servisler.

    Organizma "bu makine hangi portları dinliyor" bilir —
    güvenlik bağlamı (AG_SOR/BENI_TARA ile bağlantılı).
    """
    _, cikti = _calistir(["ss", "-tlnp"])
    portlar = []
    if cikti:
        for satir in cikti.splitlines()[1:]:
            parcalar = satir.split()
            if len(parcalar) < 4:
                continue
            # ss çıktısı: State Recv-Q Send-Q Local:Port Peer:Port Process
            # parcalar[0]="LISTEN", parcalar[3]="127.0.0.1:33927"
            durum = parcalar[0]
            yerel = parcalar[3]
            if durum == "LISTEN" and ":" in yerel:
                port_str = yerel.rsplit(":", 1)[-1]
                try:
                    portlar.append({"adres": yerel, "port": int(port_str)})
                except ValueError:
                    continue
    return portlar[:20]  # en çok 20 (bütçe)


# ---------- ana fonksiyonlar ----------

def ogren():
    """Sistemi tamamen öğren → sözlük döndür (diske YAZMAZ)."""
    # Benzersiz kimlik: makine donanımından üretilir (CPU model + RAM +
    # ilk disk seri no). Aynı donanımda aynı kalır, değişmez.
    kimlik_ham = ""
    cpu = _cpu_ogren()
    ram = _ram_ogren()
    kimlik_ham += cpu.get("model", "") + str(cpu.get("cekirdek", 0))
    kimlik_ham += str(ram.get("toplam_kb", 0))
    # /etc/machine-id varsa ekle (sistem bazında benzersiz)
    try:
        with open("/etc/machine-id") as f:
            kimlik_ham += f.read().strip()
    except OSError:
        pass
    kimlik = hashlib.sha256(kimlik_ham.encode()).hexdigest()[:16]

    return {
        "surum": SURUM,
        "kimlik": kimlik,
        "dogum": round(time.time()),
        "ilk_ogrenme": round(time.time()),
        "son_guncelleme": round(time.time()),
        "hostname": platform.node(),
        "kernel": platform.release(),
        "dagitim": _dagitim_ogren(),
        "cpu": cpu,
        "ram": ram,
        "disk": _disk_ogren(),
        "ag": _ag_ogren(),
        "guc": _guc_ogren(),
        "kurulu_paket": _kurulu_paket_sayisi(),
        "servisler": _servis_haritasi(),
        "dinleyen_portlar": _dinleyen_portlar(),
    }


def kaydet(veri, yol=None):
    """Atomik yaz: tmp → rename."""
    p = Path(yol or zeka.kayit(DOSYA))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(veri, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(str(tmp), str(p))


def yukle(yol=None):
    """Varsa oku, yoksa öğren ve kaydet. Her zaman sözlük döner."""
    p = Path(yol or zeka.yol(DOSYA))
    if p.exists():
        try:
            veri = json.loads(p.read_text(encoding="utf-8"))
            # 24 saatte bir dinamik alanları tazele (disk doluluk, ag ip)
            yas = time.time() - float(veri.get("son_guncelleme", 0))
            if yas > GUNCELLEME_ARALIK:
                veri = tazele(veri)
            return veri
        except (ValueError, OSError):
            pass
    # İlk öğrenme
    veri = ogren()
    kaydet(veri)
    return veri


def tazele(eski=None, yol=None):
    """Dinamik alanları güncelle; sabit alanları (cpu, dagitim) koru."""
    if eski is None:
        p = Path(yol or zeka.yol(DOSYA))
        try:
            eski = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            eski = {}

    # Sabit alanlar korunur, sadece değişkenler güncellenir
    yeni = dict(eski)
    yeni["son_guncelleme"] = round(time.time())
    yeni["kernel"] = platform.release()      # kernel güncellenmiş olabilir
    yeni["disk"] = _disk_ogren()             # doluluk değişir
    yeni["ag"] = _ag_ogren()                 # IP/durum değişebilir
    yeni["kurulu_paket"] = _kurulu_paket_sayisi()  # paket yüklenmiş olabilir
    yeni["servisler"] = _servis_haritasi()   # servis başlamış/durmuş olabilir
    yeni["dinleyen_portlar"] = _dinleyen_portlar()  # port açılmış/kapanmış
    kaydet(yeni)
    return yeni


def jeton(veri=None):
    """Beyin uyaran tokenı: 'makine:X86_8C_16GB_ssd' formatında.

    Brain.stimulus()'a sistem= parametresiyle geçirilir. Böylece
    organizma 'bu makinenin 8 çekirdeği var, 16GB RAM' bağlamıyla
    karar verir ve görev seçimini buna göre öğrenir.
    """
    if veri is None:
        veri = yukle()
    cpu = veri.get("cpu", {})
    ram = veri.get("ram", {})
    disk = veri.get("disk", [])
    guc = veri.get("guc", "")

    mimari = cpu.get("mimari", "?").upper()[:6]
    cekirdek = cpu.get("cekirdek", 0)
    ram_sinif = ram.get("sinif", "?")
    # Kök disk tipi (SSD/HDD tahmini — /sys/block üzerinden)
    kok_disk = next((d for d in disk if d.get("baglama") == "/"), {})
    disk_tip = _disk_ssd_mi(kok_disk.get("aygit", "")) or "disk"

    return "makine:%s_%dC_%s_%s_%s" % (
        mimari, cekirdek, ram_sinif, disk_tip, guc[:3])


def _disk_ssd_mi(aygit):
    """Kök disk SSD mi HDD mi? /sys/block üzerinden."""
    if not aygit:
        return "disk"
    # /dev/sda → sda, /dev/nvme0n1 → nvme0n1
    ad = Path(aygit).name
    # nvme → kesinlikle SSD
    if ad.startswith("nvme"):
        return "ssd"
    # rotational: 0=SSD, 1=HDD
    donme_yolu = Path("/sys/block/%s/queue/rotational" % ad)
    try:
        return "ssd" if donme_yolu.read_text().strip() == "0" else "hdd"
    except OSError:
        pass
    # Partition'dan device'a çık: sda1 → sda
    ana = re.sub(r"\d+$", "", ad)
    if ana != ad:
        donme_yolu2 = Path("/sys/block/%s/queue/rotational" % ana)
        try:
            return "ssd" if donme_yolu2.read_text().strip() == "0" else "hdd"
        except OSError:
            pass
    return "disk"


def ozet(veri=None):
    """İnsan okunabilir kısa özet (log/watch için)."""
    if veri is None:
        veri = yukle()
    cpu = veri.get("cpu", {})
    ram = veri.get("ram", {})
    disk = veri.get("disk", [])
    kok = next((d for d in disk if d.get("baglama") == "/"), {})
    return (
        "host=%s | %s %dC | ram=%s | disk=/:%dMB/%dMB | "
        "kernel=%s | dagitim=%s | paket=%d"
    ) % (
        veri.get("hostname", "?"),
        cpu.get("mimari", "?"), cpu.get("cekirdek", 0),
        ram.get("sinif", "?"),
        kok.get("kullan_mb", 0), kok.get("toplam_mb", 0),
        veri.get("kernel", "?"),
        veri.get("dagitim", {}).get("ad", "?"),
        veri.get("kurulu_paket", 0),
    )


if __name__ == "__main__":
    import sys
    if "--tazele" in sys.argv:
        v = tazele()
        print("Tazelendi:", ozet(v))
    else:
        v = ogren()
        kaydet(v)
        print(ozet(v))
        print("\nJeton:", jeton(v))
        print("\nTam veri kaydedildi:", zeka.kayit(DOSYA))
