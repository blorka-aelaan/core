"""ag_cevre.py — Ağ çevresi izleyici: MAC kaydı, anomali tespiti, olay güdümlü tarama.

Tasarım (Emrah'ın tarifi):
  1. `arp-scan` ile çevre sakin ve ucuz biçimde yoklanır; cihazlar MAC adresiyle
     kaydedilir ve sınıflandırılır (pc, mobile, tv, yazici, ag_cihazi, iot ...).
  2. Yeni (hiç görülmemiş) her cihaz, farklı araç/aşamalarla (nmap hızlı, tam TCP,
     güvenli NSE betikleri, ad çözümleme) BİR KEZ kapsamlı taranır ve sonuç kaydedilir.
  3. Bilinen cihazlar tekrar tekrar taranmaz. Yalnızca olay olursa yeniden bakılır:
       - yeni/değişmiş MAC-IP eşleşmesi, ağ geçidi MAC'i değişimi, ARP çakışması,
       - uzun süre kayıp olup dönen cihaz,
       - bilinen bir cihazdan kendisine gelen anormal istek (tarama benzeri trafik),
       - tanınmayan bir IP'den bağlantı.
     Ciddi olaylar KOMPLE (tam) tarama başlatır: agresif ARP süpürmesi + tüm çevrimiçi
     cihazlara derin tarama.
  4. Yapılacak iş yokken hiçbir şey yapmaz (`due_in` > 0): sürekli tekrar yok.

Güvenlik:
  * Kapsam kilidi: hedefler her zaman `kapsam_fn()` (ag_kapsam.json) ağlarının içinde
    olmak zorundadır; kapsam dışı IP için hiçbir komut üretilmez.
  * Komutlar sabit listeden ve argv olarak kurulur (shell yok).
  * Ağdan gelen metinler (banner, hostname, vendor) veridir; kısaltılır, kontrol
    karakterleri temizlenir ve hiçbir yerde komut/talimat olarak yorumlanmaz.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

SURUM = 1
MAX_CIHAZ = 1024
MAX_OLAY = 50
MAX_CIHAZ_OLAY = 30
MAX_IS = 256
MAX_METIN = 200

VARSAYILAN_AYAR: Dict[str, Any] = {
    "arp_aralik_sn": 300,          # ucuz ARP süpürmesi aralığı
    "arp_retry": 3,                # uyuyan/yavaş cihazları kaçırmamak için (gerçek ağda 2'de 2-3 cihaz kaçtı)
    "arp_timeout_ms": 300,
    "taban_supurme_sayisi": 3,     # taban çizgisi bu kadar süpürmeden sonra tamam sayılır
    "arp_sudo": False,             # True: `sudo -n arp-scan` (sudoers girdisi gerekir)
    "arp_arayuz": None,            # örn. "eth0"; None: arp-scan seçer
    "asama_min_aralik_sn": 10,     # iki derin tarama aşaması arası asgari süre
    "is_saatlik_azami": 20,        # saatte başlatılabilecek yeni derin iş sayısı
    "tam_bekleme_sn": 1800,        # iki komple tarama arası asgari süre
    "uzun_yokluk_sn": 7 * 24 * 3600,
    "ip_degisim_pencere_sn": 600,
    "kok_tarama": False,           # True: UDP + işletim sistemi aşamaları (raw soket gerekir)
    "nmap_hiz": 200,               # paket/sn (nmap_hiz_tavan ile sınırlanır)
    "hata_bekleme_sn": 600,        # araç hatasında yeniden deneme beklemesi
    "yuksek_susturma_sn": 21600,   # aynı ciddi olay bu süre içinde tekrar komple tarama başlatmaz
}

ASAMALAR_TEMEL = ("hizli", "tam_tcp", "nse", "isim")
ASAMALAR_KOK = ("udp", "os")
ASAMA_ZAMAN_ASIMI = {"hizli": 150, "tam_tcp": 960, "nse": 240, "isim": 20,
                     "udp": 660, "os": 150}
NSE_BETIKLERI = "banner,http-title,ssh-hostkey,smb-os-discovery,ssl-cert"

# Ciddi olaylar komple tarama tetikler.
YUKSEK_OLAYLAR = ("gecit_mac_degisti", "ip_mac_cakisma", "ip_mac_degisim_suphesi",
                  "tarama_benzeri_istek")

_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_ARP_SATIR = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*(.*)$")
_DUP_RE = re.compile(r"\(DUP:\s*(\d+)\)")
_KONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


# --------------------------------------------------------------------------
# Yardımcılar
# --------------------------------------------------------------------------

def temiz_metin(deger: Any, sinir: int = MAX_METIN) -> str:
    """Ağdan gelen metni güvenli veriye çevirir (kısalt, kontrol karakteri sil)."""
    return _KONTROL_RE.sub(" ", str(deger or ""))[:sinir].strip()


def olay_alanlari(olay: Dict[str, Any]) -> Dict[str, Any]:
    """Olayı journal.log(**alanlar) için güvenli hale getirir (journal'ın `t` alanı çakışmasın)."""
    return {("olay_t" if k in ("t", "kind") else k): v for k, v in olay.items()}


def mac_normalize(mac: Any) -> Optional[str]:
    m = str(mac or "").strip().lower().replace("-", ":")
    return m if _MAC_RE.match(m) else None


def rastgele_mac_mi(mac: str) -> bool:
    """Yerel yönetimli (locally administered) bit: telefonların özel/rastgele MAC'i."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


def arp_ayristir(metin: str) -> List[Dict[str, Any]]:
    """`arp-scan --plain` çıktısını ayrıştırır: IP, MAC, üretici, DUP sayısı."""
    kayitlar: List[Dict[str, Any]] = []
    for satir in (metin or "").splitlines():
        m = _ARP_SATIR.match(satir.strip())
        if not m:
            continue
        ip, mac, geri = m.group(1), mac_normalize(m.group(2)), m.group(3)
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            continue
        if mac is None:
            continue
        dup = _DUP_RE.search(geri)
        uretici = temiz_metin(_DUP_RE.sub("", geri))
        if uretici.lower().startswith("(unknown"):
            uretici = ""   # arp-scan OUI'de bulamadı; sahte "üretici" metni kaydetme
        kayitlar.append({"ip": ip, "mac": mac, "uretici": uretici,
                         "dup": int(dup.group(1)) if dup else 1})
    return kayitlar


def nmap_xml_ayristir(xml_text: str) -> Dict[str, Dict[str, Any]]:
    """nmap XML → {ip: {portlar, os, mac, uretici, betikler}}. Hatalıysa ValueError."""
    if "<!ENTITY" in (xml_text or ""):
        raise ValueError("XML varlık tanımı reddedildi")
    try:
        kok = ET.fromstring(xml_text or "")
    except ET.ParseError as hata:
        raise ValueError("nmap XML hatası: %s" % hata) from hata
    sonuc: Dict[str, Dict[str, Any]] = {}
    for host in kok.findall("host"):
        durum = host.find("status")
        if durum is not None and durum.get("state") not in (None, "up"):
            continue
        ip = mac = uretici = None
        for adres in host.findall("address"):
            if adres.get("addrtype") == "ipv4":
                ip = adres.get("addr")
            elif adres.get("addrtype") == "mac":
                mac = mac_normalize(adres.get("addr"))
                uretici = temiz_metin(adres.get("vendor"))
        if not ip:
            continue
        portlar: List[Dict[str, Any]] = []
        betikler: Dict[str, str] = {}
        for port in host.findall("./ports/port"):
            st = port.find("state")
            if st is None or st.get("state") != "open":
                continue
            sv = port.find("service")
            try:
                numara = int(port.get("portid", "0"))
            except ValueError:
                continue
            portlar.append({
                "port": numara, "proto": temiz_metin(port.get("protocol"), 8),
                "servis": temiz_metin(sv.get("name") if sv is not None else "", 40),
                "urun": temiz_metin(sv.get("product") if sv is not None else "", 80),
                "surum": temiz_metin(sv.get("version") if sv is not None else "", 40),
            })
            for betik in port.findall("script"):
                betikler["%s/%s" % (numara, temiz_metin(betik.get("id"), 40))] = \
                    temiz_metin(betik.get("output"))
        for betik in host.findall("./hostscript/script"):
            betikler[temiz_metin(betik.get("id"), 40)] = temiz_metin(betik.get("output"))
        os_ad = None
        eslesme = host.find("./os/osmatch")
        if eslesme is not None:
            os_ad = temiz_metin(eslesme.get("name"), 80)
        sonuc[ip] = {"portlar": portlar, "os": os_ad, "mac": mac,
                     "uretici": uretici, "betikler": betikler}
    return sonuc


# Sınıflandırma: açık-kaynak OUI üretici adı + portlar + ad ipuçları (sezgisel).
_URETICI_IPUCLARI: Tuple[Tuple[str, str, float], ...] = (
    ("raspberry", "sbc", 3.0), ("espressif", "iot", 3.0), ("tuya", "iot", 3.0),
    ("shelly", "iot", 3.0), ("sonoff", "iot", 3.0), ("itead", "iot", 3.0),
    ("roku", "tv", 3.0), ("vizio", "tv", 3.0), ("hisense", "tv", 3.0),
    ("tcl", "tv", 2.0), ("lg electronics", "tv", 1.5), ("sony", "tv", 1.0),
    ("hp inc", "yazici", 1.0), ("canon", "yazici", 2.0), ("epson", "yazici", 2.0),
    ("brother", "yazici", 2.5), ("xerox", "yazici", 2.5), ("lexmark", "yazici", 2.5),
    ("tp-link", "ag_cihazi", 2.0), ("zyxel", "ag_cihazi", 2.5),
    ("ubiquiti", "ag_cihazi", 2.5), ("netgear", "ag_cihazi", 2.0),
    ("d-link", "ag_cihazi", 2.0), ("mikrotik", "ag_cihazi", 3.0),
    ("tenda", "ag_cihazi", 2.5), ("cisco", "ag_cihazi", 2.0),
    ("arris", "ag_cihazi", 2.0), ("technicolor", "ag_cihazi", 2.5),
    ("xiaomi", "mobile", 1.5), ("oneplus", "mobile", 3.0), ("oppo", "mobile", 3.0),
    ("vivo", "mobile", 2.5), ("realme", "mobile", 3.0), ("motorola", "mobile", 2.0),
    ("huawei", "mobile", 1.0), ("samsung", "mobile", 1.0), ("google", "mobile", 0.8),
    ("apple", "mobile", 1.0),
    ("intel", "pc", 2.0), ("realtek", "pc", 1.5), ("dell", "pc", 2.5),
    ("lenovo", "pc", 2.5), ("asustek", "pc", 2.0), ("gigabyte", "pc", 2.5),
    ("micro-star", "pc", 2.5), ("msi", "pc", 2.0), ("giga-byte", "pc", 2.5), ("hewlett", "pc", 1.0),
    ("acer", "pc", 2.5), ("microsoft", "pc", 1.5), ("vmware", "pc", 2.0),
    ("qemu", "pc", 2.0), ("virtualbox", "pc", 2.0),
)
_AD_IPUCLARI: Tuple[Tuple[str, str, float], ...] = (
    ("iphone", "mobile", 4.0), ("ipad", "mobile", 4.0), ("android", "mobile", 4.0),
    ("galaxy", "mobile", 3.0), ("pixel", "mobile", 3.0), ("redmi", "mobile", 3.0),
    ("tv", "tv", 3.0), ("bravia", "tv", 4.0), ("roku", "tv", 4.0),
    ("chromecast", "tv", 4.0), ("printer", "yazici", 4.0), ("laserjet", "yazici", 4.0),
    ("router", "ag_cihazi", 3.0), ("laptop", "pc", 3.0), ("desktop", "pc", 3.0),
    ("macbook", "pc", 4.0), ("imac", "pc", 4.0), ("raspberry", "sbc", 4.0),
)
_PORT_IPUCLARI: Dict[int, Tuple[str, float]] = {
    62078: ("mobile", 4.0),                 # iPhone/iPad lockdown servisi
    8008: ("tv", 2.0), 8009: ("tv", 2.5),   # Chromecast / Android TV
    8001: ("tv", 2.0), 8002: ("tv", 2.0),   # Samsung akıllı TV
    3000: ("tv", 1.0), 3001: ("tv", 1.5),   # LG webOS
    9100: ("yazici", 3.0), 631: ("yazici", 3.0), 515: ("yazici", 2.0),
    3389: ("pc", 3.0), 445: ("pc", 1.5), 135: ("pc", 2.0), 139: ("pc", 1.0),
    548: ("pc", 2.0),                       # AFP (macOS)
    554: ("iot", 2.0),                      # RTSP (kamera)
    53: ("ag_cihazi", 1.5), 1900: ("ag_cihazi", 0.5),
    52869: ("ag_cihazi", 2.0), 37215: ("ag_cihazi", 2.0), 7547: ("ag_cihazi", 2.0),  # router UPnP/TR-069
}


def siniflandir(uretici: str, mac: str, portlar: List[int], hostname: str = "",
                servisler: Optional[List[str]] = None) -> Tuple[str, float, List[str]]:
    """Sezgisel sınıf: (sinif, guven 0..1, ipuclari). Kesinlik iddia etmez."""
    puan: Dict[str, float] = {}
    ipuclari: List[str] = []

    def ekle(sinif: str, deger: float, neden: str) -> None:
        puan[sinif] = puan.get(sinif, 0.0) + deger
        ipuclari.append(neden)

    u = (uretici or "").lower()
    for anahtar, sinif, deger in _URETICI_IPUCLARI:
        if anahtar in u:
            ekle(sinif, deger, "uretici:%s" % anahtar)
    ad = (hostname or "").lower()
    for anahtar, sinif, deger in _AD_IPUCLARI:
        if anahtar in ad:
            ekle(sinif, deger, "ad:%s" % anahtar)
    for p in portlar:
        if p in _PORT_IPUCLARI:
            sinif, deger = _PORT_IPUCLARI[p]
            ekle(sinif, deger, "port:%d" % p)
    for s in servisler or []:
        sl = s.lower()
        if "airplay" in sl or "googlecast" in sl or "raop" in sl:
            ekle("tv", 2.0, "servis:%s" % sl)
        if "ipp" in sl or "printer" in sl:
            ekle("yazici", 3.0, "servis:%s" % sl)
    if mac and rastgele_mac_mi(mac):
        ekle("mobile", 1.5, "rastgele_mac")
    if not puan:
        return "bilinmiyor", 0.0, ipuclari
    en = max(puan.items(), key=lambda kv: kv[1])
    toplam = sum(puan.values())
    guven = round(min(1.0, en[1] / 6.0) * (en[1] / toplam), 2)
    return en[0], guven, ipuclari[:12]


# --------------------------------------------------------------------------
# İzleyici
# --------------------------------------------------------------------------

class CevreIzleyici:
    """MAC anahtarlı cihaz kaydı + olay güdümlü tarama zamanlayıcısı."""

    def __init__(
        self,
        root: Path | str,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.time,
        kapsam_fn: Optional[Callable[[], Tuple[List[str], Optional[str]]]] = None,
        ayar_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        arac_bul: Optional[Callable[[str], Optional[str]]] = None,
        arka_planda: bool = True,
    ) -> None:
        self.root = Path(root)
        self.yol = self.root / "zeka" / "ag_cevre.json"
        self.runner = runner
        self.clock = clock
        self.kapsam_fn = kapsam_fn or (lambda: ([], "kapsam tanimli degil"))
        self.ayar_fn = ayar_fn or (lambda: {})
        self.arac_bul = arac_bul or (lambda ad: shutil.which(ad, path=SAFE_PATH))
        self.arka_planda = arka_planda
        self.veri = self._yukle()
        self._is_thread: Optional[threading.Thread] = None
        self._is_sonuc: Optional[Any] = None
        self._is_bilgi: Optional[Dict[str, Any]] = None
        self._pencere: Dict[str, deque] = {}          # ip -> (t, yerel_port)
        self._yabanci_son: Dict[str, float] = {}      # ip -> son uyarı zamanı
        self._zorla_son: float = 0.0                  # son zorlanan süpürme zamanı

    # ------------------------------------------------------------ kalıcılık
    @staticmethod
    def _bos() -> Dict[str, Any]:
        return {"surum": SURUM, "cihazlar": {}, "ip_mac": {}, "gecit": {},
                "is_kuyrugu": [], "olaylar": [], "taban_cizgisi": False,
                "son_supurme": 0.0, "son_tam": 0.0, "son_asama": 0.0,
                "is_baslangiclari": [], "tam_bekliyor": None,
                "hata_bitis": 0.0, "son_hata": None, "is_no": 0,
                "yuksek_son": {}, "taban_sayac": 0}

    def _yukle(self) -> Dict[str, Any]:
        if not self.yol.exists():
            return self._bos()
        try:
            ham = json.loads(self.yol.read_text(encoding="utf-8"))
            if not isinstance(ham, dict) or ham.get("surum") != SURUM:
                raise ValueError("sema")
            for anahtar, deger in self._bos().items():
                ham.setdefault(anahtar, deger)
            return ham
        except (OSError, ValueError):
            try:  # bozuk dosyayı kanıt olarak sakla
                self.yol.rename(self.yol.with_name(
                    "%s.bozuk.%d" % (self.yol.name, int(time.time()))))
            except OSError:
                pass
            return self._bos()

    def kaydet(self) -> bool:
        try:
            self.yol.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.yol.with_name("%s.%d.tmp" % (self.yol.name, os.getpid()))
            tmp.write_text(json.dumps(self.veri, ensure_ascii=False, sort_keys=True),
                           encoding="utf-8")
            os.replace(tmp, self.yol)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------ ayar / kapsam
    def ayar(self) -> Dict[str, Any]:
        a = dict(VARSAYILAN_AYAR)
        try:
            ham = self.ayar_fn() or {}
        except Exception:
            ham = {}
        for anahtar, varsayilan in VARSAYILAN_AYAR.items():
            if anahtar in ham and ham[anahtar] is not None:
                try:
                    a[anahtar] = type(varsayilan)(ham[anahtar]) \
                        if varsayilan is not None and not isinstance(varsayilan, bool) \
                        else ham[anahtar]
                except (TypeError, ValueError):
                    pass
            elif anahtar in ham:
                a[anahtar] = ham[anahtar]
        a["arp_aralik_sn"] = max(30, int(a["arp_aralik_sn"]))
        a["nmap_hiz"] = max(10, min(int(a["nmap_hiz"]), int(ham.get("nmap_hiz_tavan", 1000) or 1000)))
        return a

    def _kapsamda(self, ip: str, aglar: List[str]) -> bool:
        try:
            adres = ipaddress.ip_address(ip)
            return any(adres in ipaddress.ip_network(a) for a in aglar)
        except ValueError:
            return False

    # ------------------------------------------------------------ zamanlama
    def _is_calisiyor(self) -> bool:
        return self._is_thread is not None and self._is_thread.is_alive()

    def due_in(self, now: Optional[float] = None) -> float:
        """Yapılacak iş varsa 0, yoksa en erken ne zaman iş çıkacağı (sn)."""
        now = self.clock() if now is None else float(now)
        v = self.veri
        if self._is_sonuc is not None:
            return 0.0
        if self._is_calisiyor():
            return 5.0
        aglar, hata = self.kapsam_fn()
        if hata or not aglar:
            return 600.0
        bekleme = max(0.0, float(v.get("hata_bitis", 0.0)) - now)
        if bekleme > 0:
            return bekleme
        a = self.ayar()
        adaylar: List[float] = []
        adaylar.append(max(0.0, v["son_supurme"] + a["arp_aralik_sn"] - now))
        if v.get("tam_bekliyor"):
            adaylar.append(max(0.0, v["son_tam"] + a["tam_bekleme_sn"] - now))
        if v["is_kuyrugu"]:
            adaylar.append(self._is_icin_bekleme(now, a))
        return min(adaylar)

    def _is_icin_bekleme(self, now: float, a: Dict[str, Any]) -> float:
        v = self.veri
        asama_bekle = max(0.0, v["son_asama"] + a["asama_min_aralik_sn"] - now)
        son_saat = [t for t in v["is_baslangiclari"] if now - t < 3600]
        devam_eden = any(int(j.get("asama", 0)) > 0 for j in v["is_kuyrugu"])
        if len(son_saat) >= a["is_saatlik_azami"] and not devam_eden and not any(
                j.get("tur") == "tam" for j in v["is_kuyrugu"]):
            return max(0.0, min(son_saat) + 3600 - now)
        return asama_bekle

    # ------------------------------------------------------------ ana adım
    def adim(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Bir iş yapar: biten arka plan işini işle > süpürme > derin aşama > sessiz."""
        now = self.clock() if now is None else float(now)
        v = self.veri
        aglar, hata = self.kapsam_fn()
        if hata or not aglar:
            return self._hata(now, hata or "kapsam bos")
        if self._is_sonuc is not None:
            return self._is_isle(now, aglar)
        if self._is_calisiyor():
            return self._sessiz(now, "cevre_calisiyor", odul=0.0)
        if now < float(v.get("hata_bitis", 0.0)):
            return self._sessiz(now, "cevre_hata_bekleme", odul=0.0)
        a = self.ayar()
        tam_vakti = bool(v.get("tam_bekliyor")) and now - v["son_tam"] >= a["tam_bekleme_sn"]
        if tam_vakti:
            return self._tam_tarama(now, aglar, a)
        if now - v["son_supurme"] >= a["arp_aralik_sn"]:
            return self._supurme(now, aglar, a)
        if v["is_kuyrugu"] and self._is_icin_bekleme(now, a) <= 0:
            sonuc = self._is_baslat(now, aglar, a)
            if sonuc is not None:
                return sonuc
        return self._sessiz(now, "cevre_sessiz", odul=-0.02)

    # ------------------------------------------------------------ sonuç kayıtları
    def _sessiz(self, now: float, probe: str, odul: float) -> Dict[str, Any]:
        return {"ok": True, "noop": True, "t": now, "step": 0, "probe": probe,
                "hosts": self._cevrimici_sayi(), "ports": 0, "probe_reward": odul,
                "olaylar": []}

    def _hata(self, now: float, neden: str) -> Dict[str, Any]:
        a = self.ayar()
        self.veri["hata_bitis"] = now + a["hata_bekleme_sn"]
        self.veri["son_hata"] = {"t": now, "neden": temiz_metin(neden, 300)}
        self.kaydet()
        return {"ok": False, "t": now, "reason": temiz_metin(neden, 300), "step": 0,
                "probe": "cevre", "hosts": 0, "ports": 0, "probe_reward": 0.0,
                "olaylar": []}

    def _cevrimici_sayi(self) -> int:
        return sum(1 for c in self.veri["cihazlar"].values() if c.get("cevrimici"))

    def _olay(self, tur: str, siddet: str, now: float, mac: Optional[str] = None,
              ip: Optional[str] = None, **ayrinti: Any) -> Dict[str, Any]:
        yuksek = siddet == "yuksek" or tur in YUKSEK_OLAYLAR
        tekrar = False
        if yuksek:
            # Aynı olay (aynı IP/MAC çifti) susturma süresi içinde yeniden gelirse kayda
            # düşer ama tekrar komple tarama başlatmaz: kalıcı ama zararsız bir çakışma
            # (ör. proxy-ARP yapan menzil genişletici, sanal arayüz) tarama döngüsüne
            # dönüşmesin. Ayrıntı (MAC'ler) değişirse yeni olaydır.
            anahtar = "|".join(str(x) for x in (
                tur, ip, mac, ayrinti.get("maclar", ""), ayrinti.get("onceki_mac", "")))
            son = self.veri["yuksek_son"].get(anahtar)
            if son is not None and now - float(son) < self.ayar()["yuksek_susturma_sn"]:
                tekrar, siddet = True, "dusuk"
            else:
                self.veri["yuksek_son"][anahtar] = now
                if len(self.veri["yuksek_son"]) > 200:
                    for eski in sorted(self.veri["yuksek_son"], key=self.veri["yuksek_son"].get)[:100]:
                        del self.veri["yuksek_son"][eski]
        olay = {"t": now, "tur": tur, "siddet": siddet, "mac": mac, "ip": ip}
        if tekrar:
            olay["tekrar"] = True
        olay.update({k: temiz_metin(v) if isinstance(v, str) else v
                     for k, v in ayrinti.items()})
        self.veri["olaylar"].append(olay)
        del self.veri["olaylar"][:-MAX_OLAY]
        if mac and mac in self.veri["cihazlar"]:
            kayit = self.veri["cihazlar"][mac]["olaylar"]
            kayit.append({"t": now, "tur": tur, "siddet": siddet})
            del kayit[:-MAX_CIHAZ_OLAY]
        if yuksek and not tekrar:
            self.veri["tam_bekliyor"] = {"neden": tur, "ip": ip, "mac": mac, "t": now}
        return olay

    # ------------------------------------------------------------ çalıştırma
    def _yurut(self, argv: List[str], zaman_asimi: int) -> Any:
        try:
            return self.runner(argv, cwd=str(self.root), capture_output=True,
                               text=True, timeout=zaman_asimi, check=False)
        except subprocess.TimeoutExpired:
            return SimpleNamespace(returncode=124, stdout="", stderr="zaman asimi")
        except OSError as hata:
            return SimpleNamespace(returncode=127, stdout="", stderr=str(hata))

    def _arka_planda_baslat(self, argv: List[str], zaman_asimi: int,
                            bilgi: Dict[str, Any]) -> None:
        self._is_sonuc = None
        self._is_bilgi = bilgi

        def calis() -> None:
            self._is_sonuc = self._yurut(argv, zaman_asimi)

        if self.arka_planda:
            self._is_thread = threading.Thread(target=calis, daemon=True,
                                               name="ag_cevre_is")
            self._is_thread.start()
        else:
            calis()

    # ------------------------------------------------------------ ARP süpürmesi
    def _arp_argv(self, aglar: List[str], a: Dict[str, Any], agresif: bool) -> Optional[List[str]]:
        arp = self.arac_bul("arp-scan")
        if not arp:
            return None
        retry = int(a["arp_retry"]) + (3 if agresif else 0)
        zaman = int(a["arp_timeout_ms"]) * (2 if agresif else 1)
        argv = [arp, "--plain", "--retry=%d" % retry, "--timeout=%d" % zaman]
        if a.get("arp_arayuz"):
            argv += ["--interface", temiz_metin(a["arp_arayuz"], 20)]
        argv += list(aglar)  # --localnet yerine kapsam CIDR'leri: kilidin dışına çıkılamaz
        if a.get("arp_sudo"):
            argv = ["sudo", "-n"] + argv
        return argv

    def _varsayilan_gecit(self) -> Optional[str]:
        ip = self.arac_bul("ip")
        if not ip:
            return None
        sonuc = self._yurut([ip, "-4", "route", "show", "default"], 5)
        if sonuc.returncode != 0:
            return None
        m = re.search(r"default via (\d{1,3}(?:\.\d{1,3}){3})", sonuc.stdout or "")
        return m.group(1) if m else None

    def _supurme(self, now: float, aglar: List[str], a: Dict[str, Any],
                 agresif: bool = False, tam: bool = False) -> Dict[str, Any]:
        argv = self._arp_argv(aglar, a, agresif)
        if argv is None:
            return self._hata(now, "arp-scan bulunamadi (apt install arp-scan)")
        sonuc = self._yurut(argv, 90 if agresif else 45)
        if sonuc.returncode != 0:
            ipucu = ""
            hata_metni = (sonuc.stderr or "")
            kucuk = hata_metni.lower()
            if "password is required" in kucuk or "not in the sudoers" in kucuk \
                    or "not allowed" in kucuk or "sudo:" in kucuk:
                ipucu = " (sudo -n reddetti: sudoers'a TAM komut satırı için NOPASSWD girdisi gerekir)"
            elif "root" in kucuk or "permission" in kucuk or "operation not permitted" in kucuk:
                ipucu = " (yetki: `sudo setcap cap_net_raw+ep $(readlink -f $(which arp-scan))` veya arp_sudo)"
            return self._hata(now, "arp-scan basarisiz: %s%s" % (
                temiz_metin(hata_metni, 160), ipucu))
        kayitlar = [k for k in arp_ayristir(sonuc.stdout)
                    if self._kapsamda(k["ip"], aglar)]
        gecit_ip = self._varsayilan_gecit()
        yeni, olaylar = self._birlestir(kayitlar, now, gecit_ip)
        self.veri["son_supurme"] = now
        # Taban çizgisi tek süpürmeyle kurulmaz: ilk turda uyuyan cihazlar kaçabilir ve
        # sonradan görünmeleri "yeni cihaz" alarmı olmasın. Agresif süpürme de sayılır.
        self.veri["taban_sayac"] = int(self.veri.get("taban_sayac", 0)) + 1
        self.veri["taban_cizgisi"] = self.veri["taban_sayac"] >= max(1, int(a["taban_supurme_sayisi"]))
        self._kuyruk_temizle()
        self.kaydet()
        odul = min(1.0, 0.4 * yeni + 0.8 * len(olaylar))
        return {"ok": True, "t": now, "step": 3 if tam else 1,
                "probe": "arp_tam_supurme" if tam else "arp_supurme",
                "networks": list(aglar), "hosts": len(kayitlar), "ports": 0,
                "yeni_cihaz": yeni, "probe_reward": float(odul),
                "olaylar": olaylar, "noop": False}

    # ------------------------------------------------------------ kayıt birleştirme
    def _birlestir(self, kayitlar: List[Dict[str, Any]], now: float,
                   gecit_ip: Optional[str]) -> Tuple[int, List[Dict[str, Any]]]:
        v = self.veri
        a = self.ayar()
        olaylar: List[Dict[str, Any]] = []
        yeni = 0
        ip_macler: Dict[str, set] = {}
        mac_ipler: Dict[str, set] = {}
        for k in kayitlar:
            ip_macler.setdefault(k["ip"], set()).add(k["mac"])
            mac_ipler.setdefault(k["mac"], set()).add(k["ip"])
        gorulen = set(mac_ipler)

        for ip, macler in ip_macler.items():
            if len(macler) > 1:
                olaylar.append(self._olay("ip_mac_cakisma", "yuksek", now, ip=ip,
                                          maclar=",".join(sorted(macler))))
        for k in kayitlar:
            if k["dup"] > 1 and len(ip_macler.get(k["ip"], ())) == 1:
                olaylar.append(self._olay("arp_dup_yaniti", "orta", now,
                                          mac=k["mac"], ip=k["ip"], adet=k["dup"]))

        for mac, ipler in mac_ipler.items():
            kayit = next(k for k in kayitlar if k["mac"] == mac)
            cihaz = v["cihazlar"].get(mac)
            ilk_kez = cihaz is None
            if ilk_kez:
                cihaz = {
                    "mac": mac, "uretici": kayit["uretici"],
                    "ilk_gorulme": now, "son_gorulme": now, "gorulme_sayisi": 0,
                    "ipler": {}, "son_ip": None, "cevrimici": True,
                    "rastgele_mac": rastgele_mac_mi(mac),
                    "guven": "yeni", "sinif": "bilinmiyor", "sinif_guven": 0.0,
                    "sinif_ipuclari": [], "acik_portlar": [], "os": None,
                    "hostname": "", "betikler": {}, "derin_tamamlandi": 0.0,
                    "derin_asamalar": {}, "gorulen_yerel": [], "olaylar": [],
                }
                v["cihazlar"][mac] = cihaz
                yeni += 1
                self._kuyruga_ekle("derin", mac, sorted(ipler)[0], "yeni_cihaz", 2, now)
                if v["taban_cizgisi"]:
                    olaylar.append(self._olay("yeni_cihaz", "orta", now, mac=mac,
                                              ip=sorted(ipler)[0],
                                              uretici=kayit["uretici"]))
            else:
                yokluk = now - float(cihaz.get("son_gorulme", now))
                if yokluk >= a["uzun_yokluk_sn"]:
                    olaylar.append(self._olay("uzun_yokluktan_dondu", "orta", now,
                                              mac=mac, ip=sorted(ipler)[0],
                                              yokluk_sn=int(yokluk)))
                    self._kuyruga_ekle("derin", mac, sorted(ipler)[0], "uzun_yokluk", 3, now)
            if str(cihaz.get("uretici", "")).lower().startswith("(unknown"):
                cihaz["uretici"] = ""   # eski sürümün sahte "üretici" kayıtları
            cihaz["son_gorulme"] = now
            cihaz["gorulme_sayisi"] = int(cihaz.get("gorulme_sayisi", 0)) + 1
            cihaz["cevrimici"] = True
            if kayit["uretici"]:
                cihaz["uretici"] = kayit["uretici"]
            for ip in ipler:
                kayit_ip = cihaz["ipler"].setdefault(ip, {"ilk": now, "son": now})
                kayit_ip["son"] = now
            cihaz["son_ip"] = sorted(ipler)[0]

            for ip in ipler:
                onceki = v["ip_mac"].get(ip)
                if onceki and onceki != mac and len(ip_macler.get(ip, ())) == 1:
                    onceki_cihaz = v["cihazlar"].get(onceki)
                    taze = onceki_cihaz is not None and \
                        now - float(onceki_cihaz.get("son_gorulme", 0)) < a["ip_degisim_pencere_sn"]
                    if onceki in gorulen:
                        olaylar.append(self._olay(
                            "ip_mac_degisim_suphesi", "yuksek", now, mac=mac, ip=ip,
                            onceki_mac=onceki))
                    elif taze:
                        olaylar.append(self._olay("ip_yeni_mac", "orta", now, mac=mac,
                                                  ip=ip, onceki_mac=onceki))
                v["ip_mac"][ip] = mac
            if len(ipler) >= 4 and (gecit_ip is None or gecit_ip not in ipler):
                olaylar.append(self._olay("mac_cok_ip", "orta", now, mac=mac,
                                          ip=sorted(ipler)[0], ip_sayisi=len(ipler)))
            self._sinifla(cihaz)

        for mac, cihaz in v["cihazlar"].items():
            if mac not in gorulen:
                cihaz["cevrimici"] = False

        if gecit_ip:
            gecit_mac = v["ip_mac"].get(gecit_ip)
            eski = v.get("gecit") or {}
            if gecit_mac:
                if eski.get("ip") == gecit_ip and eski.get("mac") and eski["mac"] != gecit_mac:
                    olaylar.append(self._olay("gecit_mac_degisti", "yuksek", now,
                                              mac=gecit_mac, ip=gecit_ip,
                                              onceki_mac=eski["mac"]))
                v["gecit"] = {"ip": gecit_ip, "mac": gecit_mac}
                for m_, c_ in v["cihazlar"].items():
                    c_["gecit"] = (m_ == gecit_mac)
                    if c_["gecit"]:
                        self._sinifla(c_)
        olaylar.extend(self._yetim_isler(now, mac_ipler, a))
        self._sinir_uygula()
        return yeni, olaylar

    def _yetim_isler(self, now: float, mac_ipler: Dict[str, set],
                     a: Dict[str, Any]) -> List[Dict[str, Any]]:
        """MAC'siz işleri (tanınmayan IP) süpürmede bulunan MAC'e bağlar.

        ARP'a hiç yanıt vermeyen ama bizimle konuşan bir IP şüphelidir (sahte kaynak,
        NAT ya da gizlenmiş cihaz): olay üretilir ve iş düşürülür.
        """
        olaylar: List[Dict[str, Any]] = []
        kalan = []
        for j in self.veri["is_kuyrugu"]:
            if j.get("mac") is not None:
                kalan.append(j)
                continue
            mac = next((m for m, ipler in mac_ipler.items() if j.get("ip") in ipler), None)
            if mac is not None:
                j["mac"] = mac
                kalan.append(j)
            elif now - float(j.get("t", now)) > 2 * a["arp_aralik_sn"]:
                olaylar.append(self._olay("ip_arp_yanitsiz", "orta", now, ip=j.get("ip"),
                                          neden=j.get("neden")))
            else:
                kalan.append(j)
        self.veri["is_kuyrugu"] = kalan
        return olaylar

    def _sinir_uygula(self) -> None:
        c = self.veri["cihazlar"]
        if len(c) <= MAX_CIHAZ:
            return
        silinecek = sorted((m for m, d in c.items() if d.get("guven") != "supheli"),
                           key=lambda m: float(c[m].get("son_gorulme", 0)))
        for m in silinecek[:len(c) - MAX_CIHAZ]:
            del c[m]
        self.veri["ip_mac"] = {ip: m for ip, m in self.veri["ip_mac"].items() if m in c}

    def _sinifla(self, cihaz: Dict[str, Any]) -> None:
        if cihaz.get("gecit"):   # varsayılan ağ geçidi: sezgiye gerek yok
            cihaz["sinif"], cihaz["sinif_guven"] = "ag_cihazi", 1.0
            cihaz["sinif_ipuclari"] = ["varsayilan_gecit"]
            return
        portlar = [p["port"] for p in cihaz.get("acik_portlar", [])]
        sinif, guven, ipuclari = siniflandir(
            cihaz.get("uretici", ""), cihaz["mac"], portlar, cihaz.get("hostname", ""))
        cihaz["sinif"], cihaz["sinif_guven"], cihaz["sinif_ipuclari"] = sinif, guven, ipuclari

    # ------------------------------------------------------------ iş kuyruğu
    def _kuyruga_ekle(self, tur: str, mac: Optional[str], ip: str, neden: str,
                      oncelik: int, now: float) -> bool:
        kuyruk = self.veri["is_kuyrugu"]
        for is_ in kuyruk:
            # Aynı cihaz için tek iş: derin ve tam aynı aşamaları koşar, yalnızca
            # öncelikleri farklıdır; ikisi birden istenirse "tam" kazanır.
            if is_.get("mac") == mac and is_.get("ip") == ip:
                is_["oncelik"] = min(int(is_.get("oncelik", 9)), oncelik)
                if tur == "tam":
                    is_["tur"] = "tam"
                return False
        if len(kuyruk) >= MAX_IS:
            return False
        self.veri["is_no"] = int(self.veri.get("is_no", 0)) + 1
        kuyruk.append({"id": self.veri["is_no"], "tur": tur, "mac": mac, "ip": ip,
                       "neden": neden, "oncelik": oncelik, "asama": 0, "t": now})
        return True

    def _kuyruk_temizle(self) -> None:
        """Kuyrukta olup artık kayıtta olmayan (silinmiş) cihaz işlerini at."""
        c = self.veri["cihazlar"]
        self.veri["is_kuyrugu"] = [j for j in self.veri["is_kuyrugu"]
                                   if j.get("mac") is None or j["mac"] in c]

    def _asamalar(self, a: Dict[str, Any]) -> List[str]:
        return list(ASAMALAR_TEMEL) + (list(ASAMALAR_KOK) if a.get("kok_tarama") else [])

    def _siradaki_is(self) -> Optional[Dict[str, Any]]:
        v = self.veri
        adaylar = []
        for j in v["is_kuyrugu"]:
            mac = j.get("mac")
            cihaz = v["cihazlar"].get(mac) if mac else None
            if mac is None:
                continue  # önce ARP ile MAC'e bağlanmalı (bkz. _yetim_isler)
            cevrimici = bool(cihaz and cihaz.get("cevrimici"))
            devam = int(j.get("asama", 0)) > 0
            if cevrimici or devam:
                adaylar.append(j)
        if not adaylar:
            return None
        return sorted(adaylar, key=lambda j: (-int(int(j.get("asama", 0)) > 0),
                                              int(j.get("oncelik", 9)), j["id"]))[0]

    def _is_baslat(self, now: float, aglar: List[str], a: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        v = self.veri
        is_ = self._siradaki_is()
        if is_ is None:
            return None
        asamalar = self._asamalar(a)
        idx = int(is_.get("asama", 0))
        if idx >= len(asamalar):
            self._is_bitir(is_, now)
            return None
        asama = asamalar[idx]
        ip = is_.get("ip")
        if not ip or not self._kapsamda(ip, aglar):
            v["is_kuyrugu"] = [j for j in v["is_kuyrugu"] if j["id"] != is_["id"]]
            self._olay("kapsam_disi_hedef_reddedildi", "orta", now, ip=ip)
            self.kaydet()
            return self._sessiz(now, "cevre_kapsam_disi", odul=0.0)
        argv, zaman = self._asama_argv(asama, ip, is_, a)
        if idx == 0:
            v["is_baslangiclari"].append(now)
            v["is_baslangiclari"] = [t for t in v["is_baslangiclari"] if now - t < 3600]
        if argv is None:  # araç yok / koşul sağlanmıyor → aşamayı atla
            self._asama_kaydet(is_, asama, ip, now, "atlandi", None)
            self.kaydet()
            return self._sessiz(now, "cevre_asama_atlandi", odul=0.0)
        self._arka_planda_baslat(argv, zaman, {"is": is_["id"], "asama": asama,
                                               "ip": ip, "t": now})
        v["son_asama"] = now
        if self._is_sonuc is not None:   # eşzamanlı mod (test)
            return self._is_isle(now, aglar)
        return self._sessiz(now, "cevre_asama_basladi", odul=0.0)

    def _asama_argv(self, asama: str, ip: str, is_: Dict[str, Any],
                    a: Dict[str, Any]) -> Tuple[Optional[List[str]], int]:
        zaman = ASAMA_ZAMAN_ASIMI.get(asama, 120)
        hiz = str(int(a["nmap_hiz"]))
        nmap = self.arac_bul("nmap")
        taban = ["-Pn", "-n", "-T3", "--max-retries", "1", "-oX", "-"]
        if asama == "hizli" and nmap:
            return [nmap, "-sT", "-sV", "--version-light", "--top-ports", "1000",
                    "--max-rate", hiz, "--host-timeout", "120s"] + taban + [ip], zaman
        if asama == "tam_tcp" and nmap:
            return [nmap, "-sT", "-p-", "--max-rate", hiz, "--host-timeout", "900s"] \
                + taban + [ip], zaman
        if asama == "nse" and nmap:
            mac = is_.get("mac")
            cihaz = self.veri["cihazlar"].get(mac) if mac else None
            portlar = sorted({p["port"] for p in (cihaz or {}).get("acik_portlar", [])
                              if p.get("proto") in ("tcp", "")})[:100]
            if not portlar:
                return None, zaman
            return [nmap, "-sT", "-sV", "-p", ",".join(str(p) for p in portlar),
                    "--script", NSE_BETIKLERI, "--host-timeout", "240s"] + taban + [ip], zaman
        if asama == "udp" and nmap:
            return [nmap, "-sU", "--top-ports", "50", "--host-timeout", "600s"] \
                + taban + [ip], zaman
        if asama == "os" and nmap:
            return [nmap, "-O", "--osscan-limit", "--host-timeout", "120s"] \
                + taban + [ip], zaman
        if asama == "isim":
            avahi = self.arac_bul("avahi-resolve")
            if avahi:
                return [avahi, "-a", ip], zaman
            getent = self.arac_bul("getent")
            if getent:
                return [getent, "hosts", ip], zaman
        return None, zaman

    # ------------------------------------------------------------ iş sonucu
    def _is_isle(self, now: float, aglar: List[str]) -> Dict[str, Any]:
        sonuc, bilgi = self._is_sonuc, self._is_bilgi or {}
        self._is_sonuc, self._is_thread, self._is_bilgi = None, None, None
        v = self.veri
        is_ = next((j for j in v["is_kuyrugu"] if j["id"] == bilgi.get("is")), None)
        if is_ is None or sonuc is None:
            return self._sessiz(now, "cevre_is_kayip", odul=0.0)
        asama, ip = bilgi["asama"], bilgi["ip"]
        cihaz = v["cihazlar"].get(is_.get("mac") or "")
        yeni_port = 0
        durum = "tamam"
        if sonuc.returncode != 0:
            durum = "zaman_asimi" if sonuc.returncode == 124 else "hata"
        elif cihaz is not None:
            try:
                yeni_port = self._asama_uygula(cihaz, asama, ip, sonuc.stdout or "")
                self._sinifla(cihaz)   # port/ad bilgisi geldikçe sınıf iş bitmeden güncellensin
            except ValueError as hata:
                durum = "ayristirma_hatasi"
                self._olay("tarama_cikti_hatasi", "dusuk", now, mac=cihaz["mac"],
                           ip=ip, asama=asama, hata=str(hata))
        self._asama_kaydet(is_, asama, ip, now, durum, sonuc)
        ilk_tamam = False
        asamalar = self._asamalar(self.ayar())
        if int(is_.get("asama", 0)) >= len(asamalar):
            ilk_tamam = self._is_bitir(is_, now)
        v["son_asama"] = now
        self.kaydet()
        odul = min(1.0, 0.1 * yeni_port + (0.3 if ilk_tamam else 0.0))
        return {"ok": durum in ("tamam", "atlandi"), "t": now, "step": 2,
                "probe": "nmap_%s" % asama if asama not in ("isim",) else "ad_cozumleme",
                "networks": list(aglar), "hosts": self._cevrimici_sayi(),
                "ports": yeni_port, "yeni_port": yeni_port, "asama": asama,
                "asama_durumu": durum, "hedef": ip, "probe_reward": float(odul),
                "olaylar": [], "noop": False,
                "reason": None if durum in ("tamam", "atlandi") else "%s:%s" % (asama, durum)}

    def _asama_kaydet(self, is_: Dict[str, Any], asama: str, ip: str, now: float,
                      durum: str, sonuc: Optional[Any]) -> None:
        is_["asama"] = int(is_.get("asama", 0)) + 1
        cihaz = self.veri["cihazlar"].get(is_.get("mac") or "")
        if cihaz is not None:
            cihaz["derin_asamalar"][asama] = {"t": now, "durum": durum, "ip": ip}

    def _is_bitir(self, is_: Dict[str, Any], now: float) -> bool:
        v = self.veri
        cihaz = v["cihazlar"].get(is_.get("mac") or "")
        ilk = False
        if cihaz is not None:
            ilk = float(cihaz.get("derin_tamamlandi", 0.0)) == 0.0
            cihaz["derin_tamamlandi"] = now
            cihaz["guven"] = "bilinen" if cihaz.get("guven") in ("yeni", None) else cihaz["guven"]
            self._sinifla(cihaz)
        v["is_kuyrugu"] = [j for j in v["is_kuyrugu"] if j["id"] != is_["id"]]
        return ilk

    def _asama_uygula(self, cihaz: Dict[str, Any], asama: str, ip: str, cikti: str) -> int:
        """Aşama çıktısını cihaz kaydına işler; yeni açık port sayısını döndürür."""
        yeni = 0
        if asama in ("hizli", "tam_tcp", "nse", "udp", "os"):
            ayrik = nmap_xml_ayristir(cikti).get(ip)
            if ayrik is None:
                return 0
            mevcut = {(p["port"], p["proto"]): p for p in cihaz["acik_portlar"]}
            for p in ayrik["portlar"]:
                anahtar = (p["port"], p["proto"])
                if anahtar not in mevcut:
                    yeni += 1
                    cihaz["acik_portlar"].append(p)
                else:
                    for alan in ("servis", "urun", "surum"):
                        if p.get(alan):
                            mevcut[anahtar][alan] = p[alan]
            cihaz["acik_portlar"].sort(key=lambda p: (p["proto"], p["port"]))
            del cihaz["acik_portlar"][512:]
            if ayrik.get("os"):
                cihaz["os"] = ayrik["os"]
            if ayrik.get("uretici") and not cihaz.get("uretici"):
                cihaz["uretici"] = ayrik["uretici"]
            for ad, deger in ayrik.get("betikler", {}).items():
                cihaz["betikler"][ad] = deger
            if len(cihaz["betikler"]) > 40:
                for ad in sorted(cihaz["betikler"])[40:]:
                    del cihaz["betikler"][ad]
        elif asama == "isim":
            ham = (cikti or "").strip().splitlines()
            if ham:
                parcalar = ham[0].split()
                ad = parcalar[-1] if len(parcalar) >= 2 else ""
                cihaz["hostname"] = temiz_metin(ad, 80)
        return yeni

    # ------------------------------------------------------------ komple tarama
    def _tam_tarama(self, now: float, aglar: List[str], a: Dict[str, Any]) -> Dict[str, Any]:
        """Ciddi olay: agresif ARP süpürmesi + tüm çevrimiçi cihazlara derin tarama."""
        v = self.veri
        tetik = v.get("tam_bekliyor") or {}
        v["tam_bekliyor"] = None
        v["son_tam"] = now
        sonuc = self._supurme(now, aglar, a, agresif=True, tam=True)
        if not sonuc.get("ok"):
            return sonuc
        eklenen = 0
        for mac, cihaz in v["cihazlar"].items():
            if cihaz.get("cevrimici") and cihaz.get("son_ip"):
                oncelik = 0 if (tetik.get("mac") == mac or tetik.get("ip") == cihaz["son_ip"]) else 1
                # tam taramada önceki derin sonuçlar yenilensin
                cihaz["derin_asamalar"] = {}
                cihaz["derin_tamamlandi"] = float(cihaz.get("derin_tamamlandi", 0.0))
                if self._kuyruga_ekle("tam", mac, cihaz["son_ip"], "tam_tarama:%s" % tetik.get("neden"), oncelik, now):
                    eklenen += 1
        if tetik.get("ip") and not tetik.get("mac") and self._kapsamda(tetik["ip"], aglar):
            mac_t = v["ip_mac"].get(tetik["ip"])   # agresif süpürme az önce kaydetmiş olabilir
            self._kuyruga_ekle("tam", mac_t, tetik["ip"],
                               "tam_tarama:%s" % tetik.get("neden"), 0, now)
        eklenen = sum(1 for j in v["is_kuyrugu"] if j.get("tur") == "tam")  # yükseltilenler dahil
        sonuc["tam_tarama"] = {"neden": tetik.get("neden"), "is_sayisi": eklenen}
        sonuc["probe_reward"] = float(min(1.0, sonuc.get("probe_reward", 0.0) + 0.5))
        self.kaydet()
        return sonuc

    # ------------------------------------------------------------ dış olaylar
    def dis_olay(self, tur: str, ip: Optional[str] = None, siddet: str = "orta",
                 now: Optional[float] = None, **ayrinti: Any) -> Dict[str, Any]:
        """Dışarıdan gelen olay (ör. anormal istek). Ciddi olay komple tarama bekletir."""
        now = self.clock() if now is None else float(now)
        mac = self.veri["ip_mac"].get(ip) if ip else None
        olay = self._olay(tur, siddet, now, mac=mac, ip=ip, **ayrinti)
        aglar, hata = self.kapsam_fn()
        if ip and not hata and self._kapsamda(ip, aglar) and siddet != "yuksek":
            self._kuyruga_ekle("derin", mac, ip, tur, 1, now)
            if mac is None and now - self._zorla_son >= 60:
                # MAC'siz iş ARP süpürmesiyle bağlanır: süpürmeyi şimdi vadeli yap
                self._zorla_son = now
                self.veri["son_supurme"] = min(
                    float(self.veri["son_supurme"]), now - self.ayar()["arp_aralik_sn"])
        self.kaydet()
        return olay

    def baglanti_gozlemi(self, conn: Dict[str, Any], now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Pasif bağlantı gözleminden anormal istek tespiti (yalnızca gelen istekler)."""
        now = self.clock() if now is None else float(now)
        ip = str(conn.get("remote_ip", ""))
        aglar, hata = self.kapsam_fn()
        if hata or not self._kapsamda(ip, aglar):
            return []
        try:
            yerel = int(conn.get("local_port", 0))
            uzak = int(conn.get("remote_port", 0))
        except (TypeError, ValueError):
            return []
        if not (0 < yerel < 32768 <= uzak):   # gelen istek sezgisi: biz dinleyici
            return []
        v = self.veri
        olaylar: List[Dict[str, Any]] = []
        mac = v["ip_mac"].get(ip)
        if mac is None:
            if now - self._yabanci_son.get(ip, 0.0) >= 3600:
                self._yabanci_son[ip] = now
                olaylar.append(self.dis_olay("yabanci_baglanti", ip=ip, siddet="orta",
                                             now=now, yerel_port=yerel))
            return olaylar
        pencere = self._pencere.setdefault(ip, deque(maxlen=64))
        pencere.append((now, yerel))
        while pencere and now - pencere[0][0] > 60:
            pencere.popleft()
        if len({p for _, p in pencere}) >= 8:
            pencere.clear()
            olaylar.append(self.dis_olay("tarama_benzeri_istek", ip=ip, siddet="yuksek",
                                         now=now, yerel_port_sayisi=8))
            return olaylar
        cihaz = v["cihazlar"].get(mac)
        if cihaz is not None:
            gorulen = cihaz.setdefault("gorulen_yerel", [])
            yas = now - float(cihaz.get("ilk_gorulme", now))
            if yerel not in gorulen:
                if gorulen and yas >= 3600:
                    olaylar.append(self.dis_olay("yeni_hizmet_istegi", ip=ip, siddet="dusuk",
                                                 now=now, yerel_port=yerel))
                gorulen.append(yerel)
                del gorulen[:-64]
        return olaylar

    # ------------------------------------------------------------ rapor
    def ozet(self) -> Dict[str, Any]:
        v = self.veri
        siniflar: Dict[str, int] = {}
        for c in v["cihazlar"].values():
            siniflar[c.get("sinif", "bilinmiyor")] = siniflar.get(c.get("sinif", "bilinmiyor"), 0) + 1
        return {
            "cihaz": len(v["cihazlar"]), "cevrimici": self._cevrimici_sayi(),
            "kuyruk": len(v["is_kuyrugu"]), "taban_cizgisi": bool(v["taban_cizgisi"]),
            "son_supurme": v["son_supurme"], "siniflar": siniflar,
            "tam_bekliyor": bool(v.get("tam_bekliyor")),
            "son_olay": (v["olaylar"][-1] if v["olaylar"] else None),
            "son_hata": v.get("son_hata"),
        }
