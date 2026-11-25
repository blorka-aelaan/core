"""Local network knowledge and bounded inventory learning."""

from __future__ import annotations

import fcntl
import ipaddress
import json
import math
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from ag_cevre import CevreIzleyici
from social_learning import SocialLearning

PORTS = (22, 23, 53, 80, 139, 443, 445, 554, 631, 3389, 8008, 8009,
         8080, 8443, 9100)
WINDOW_SECONDS = 24 * 60 * 60
MAX_SCANS_PER_WINDOW = 5
MAX_SCOPE_ADDRESSES = 512
MAX_PORT_SCAN_HOSTS = 256
SCAN_PROFILE_VERSION = 2
REFERENCE_REFRESH_SECONDS = 30 * 24 * 60 * 60
HELP_RETRY_SECONDS = 24 * 60 * 60
CONSOLIDATION_SECONDS = 6 * 60 * 60
REFERENCE_FILES = ("/etc/services", "/usr/share/nmap/nmap-services")
MAX_REFERENCE_BYTES = 2 * 1024 * 1024
PROBE_ACTIONS = ("nmap_tcp_ports", "avahi_browse", "ip_neigh")
PROBE_HELP = {
    "nmap_tcp_ports": ("--help",),
    "avahi_browse": ("--help",),
    "ip_neigh": ("-help",),
}
SKILL_LIMITS = {
    "nmap_tcp_ports": "Yalnizca kapsam icindeki yanit veren cihazlarda sabit TCP port kumesi.",
    "avahi_browse": "Yalnizca yerel mDNS/DNS-SD duyurularini okur.",
    "ip_neigh": "Yalnizca cekirdek komsu tablosunu okur; hedefe paket gondermez.",
}

PORT_KNOWLEDGE = {
    "udp/53": {
        "name": "DNS",
        "purpose": "Alan adi cozumleme",
        "hints": ["ag_gecidi_veya_dns_sunucusu"],
    },
    "udp/67": {
        "name": "DHCP",
        "purpose": "IPv4 istemcilere ag ayari dagitimi",
        "hints": ["ag_gecidi_veya_dhcp_sunucusu"],
    },
    "udp/68": {
        "name": "DHCP-client",
        "purpose": "IPv4 istemcinin DHCP yanitlarini almasi",
        "hints": ["dhcp_istemcisi"],
    },
    "udp/123": {
        "name": "NTP",
        "purpose": "Ag uzerinden saat esitleme",
        "hints": ["zaman_sunucusu_veya_istemci"],
    },
    "udp/1900": {
        "name": "SSDP",
        "purpose": "UPnP uyumlu ag ve medya cihazlarini duyurma",
        "hints": ["medya_veya_akilli_ev_cihazi"],
    },
    "udp/5353": {
        "name": "mDNS",
        "purpose": "Yerel agda servis ve cihaz adlarini duyurma",
        "hints": ["yerel_servis_veya_kisisel_cihaz"],
    },
    "tcp/22": {
        "name": "SSH",
        "purpose": "Guvenli uzak kabuk ve yonetim",
        "hints": ["bilgisayar_veya_sunucu", "ag_cihazi"],
    },
    "tcp/23": {
        "name": "Telnet",
        "purpose": "Eski, sifresiz uzak terminal; acik olmasi risk isaretidir",
        "hints": ["eski_ag_cihazi"],
    },
    "tcp/53": {
        "name": "DNS",
        "purpose": "Alan adi cozumleme",
        "hints": ["ag_gecidi_veya_dns_sunucusu"],
    },
    "tcp/80": {
        "name": "HTTP",
        "purpose": "Sifrelenmemis web arayuzu veya web servisi",
        "hints": ["web_arayuzlu_cihaz"],
    },
    "tcp/139": {
        "name": "NetBIOS",
        "purpose": "Eski Windows dosya ve yazici paylasimi",
        "hints": ["bilgisayar_veya_dosya_paylasimi"],
    },
    "tcp/443": {
        "name": "HTTPS",
        "purpose": "Sifreli web arayuzu veya web servisi",
        "hints": ["web_arayuzlu_cihaz"],
    },
    "tcp/445": {
        "name": "SMB",
        "purpose": "Windows/Linux dosya ve yazici paylasimi",
        "hints": ["bilgisayar_veya_dosya_paylasimi"],
    },
    "tcp/554": {
        "name": "RTSP",
        "purpose": "Ag kamerasi veya medya akis kontrolu",
        "hints": ["kamera_veya_medya_cihazi"],
    },
    "tcp/631": {
        "name": "IPP",
        "purpose": "Ag uzerinden yazdirma",
        "hints": ["yazici"],
    },
    "tcp/3389": {
        "name": "RDP",
        "purpose": "Windows uzak masaustu",
        "hints": ["windows_bilgisayar_veya_sunucu"],
    },
    "tcp/8008": {
        "name": "HTTP-alt",
        "purpose": "Bazi medya ve akilli ev cihazlarinin web servisi",
        "hints": ["medya_veya_akilli_ev_cihazi"],
    },
    "tcp/8009": {
        "name": "Cast",
        "purpose": "Bazi Google Cast uyumlu cihazlarda kontrol servisi",
        "hints": ["medya_veya_tv"],
    },
    "tcp/8080": {
        "name": "HTTP-alt",
        "purpose": "Alternatif HTTP web arayuzu veya proxy",
        "hints": ["web_arayuzlu_cihaz"],
    },
    "tcp/8443": {
        "name": "HTTPS-alt",
        "purpose": "Alternatif HTTPS web arayuzu",
        "hints": ["web_arayuzlu_cihaz"],
    },
    "tcp/9100": {
        "name": "JetDirect",
        "purpose": "Ham ag yazdirma servisi",
        "hints": ["yazici"],
    },
}

TOOL_KNOWLEDGE = {
    "nmap_host_discovery": {
        "tool": "nmap",
        "purpose": "Yerel kapsamda hangi IP adreslerinin yanit verdigini bulur",
        "usage": "nmap -sn",
        "mode": "automatic_bounded",
    },
    "nmap_tcp_ports": {
        "tool": "nmap",
        "purpose": "Bilinen TCP portlarinin acik/kapali durumunu kontrol eder",
        "usage": "nmap -sT -p <port-list>",
        "mode": "automatic_bounded",
    },
    "nmap_service_detection": {
        "tool": "nmap",
        "purpose": "Servis ve surum hakkinda ek aktif sorgular yapar",
        "usage": "nmap -sV",
        "mode": "knowledge_only",
    },
    "ping": {
        "tool": "ping",
        "purpose": "Bir IP adresinden ICMP yaniti alip erisilebilirligi kontrol eder",
        "usage": "ping -c 2 <scoped-ip>",
        "mode": "knowledge_only",
    },
    "traceroute": {
        "tool": "traceroute",
        "purpose": "Hedefe giden IP atlamalarini gosterir",
        "usage": "traceroute -n <scoped-ip>",
        "mode": "knowledge_only",
    },
    "avahi_browse": {
        "tool": "avahi-browse",
        "purpose": "mDNS/DNS-SD ile duyurulan yerel servisleri listeler",
        "usage": "avahi-browse --all --resolve --terminate",
        "mode": "automatic_optional",
    },
    "ip_neigh": {
        "tool": "ip",
        "purpose": "Cekirdegin komsu/ARP onbellegini pasif olarak gosterir",
        "usage": "ip neigh show",
        "mode": "automatic_optional",
    },
    "ss": {
        "tool": "ss",
        "purpose": "Bu bilgisayarin yerel soketlerini ve dinleyen portlarini gosterir",
        "usage": "ss -lnt",
        "mode": "knowledge_only",
    },
    "msf_db_status": {
        "tool": "msfconsole",
        "purpose": "Metasploit veritabaninin baglanti durumunu sorgular",
        "usage": "db_status",
        "mode": "manual_read_only",
    },
    "msf_hosts": {
        "tool": "msfconsole",
        "purpose": "Mevcut workspace veritabanindaki host kayitlarini listeler",
        "usage": "hosts",
        "mode": "manual_read_only",
    },
    "msf_services": {
        "tool": "msfconsole",
        "purpose": "Mevcut workspace veritabanindaki servis kayitlarini listeler",
        "usage": "services",
        "mode": "manual_read_only",
    },
    "msf_active_modules": {
        "tool": "msfconsole",
        "purpose": "Modul calistirma ve exploit komutlari otonom ag beyni kapsaminda degildir",
        "usage": None,
        "mode": "not_automated",
    },
}


def parse_nmap_xml(xml_text: str) -> Dict[str, list[int]]:
    """Return up IPv4 hosts and their open TCP ports from Nmap XML."""
    root = ET.fromstring(xml_text)
    hosts: Dict[str, list[int]] = {}
    for host in root.findall("host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue
        address = next(
            (item.get("addr") for item in host.findall("address")
             if item.get("addrtype") == "ipv4"),
            None,
        )
        if not address:
            continue
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.version != 4:
            continue
        open_ports = []
        for port in host.findall("./ports/port"):
            state = port.find("state")
            if (
                port.get("protocol") == "tcp"
                and state is not None
                and state.get("state") == "open"
            ):
                try:
                    open_ports.append(int(port.get("portid", "")))
                except ValueError:
                    continue
        hosts[str(ip)] = sorted(set(open_ports))
    return hosts


def parse_avahi_output(
    output: str, networks: Iterable[str]
) -> Dict[str, Dict[str, Any]]:
    """Parse resolved Avahi records and discard records outside scan scope."""
    allowed = [ipaddress.ip_network(network) for network in networks]
    services: Dict[str, Dict[str, Any]] = {}
    for line in output.splitlines():
        fields = line.split(";")
        if len(fields) < 9 or fields[0] != "=":
            continue
        try:
            ip = ipaddress.ip_address(fields[7])
        except ValueError:
            continue
        if ip.version != 4 or not any(ip in network for network in allowed):
            continue
        entry = services.setdefault(
            str(ip), {"hostname": "", "services": {}}
        )
        entry["hostname"] = fields[6][:100] or entry["hostname"]
        service_type = fields[4][:100]
        if service_type:
            entry["services"][service_type] = fields[3][:100]
    return services


def parse_ip_neigh(output: str, networks: Iterable[str]) -> Dict[str, list[int]]:
    """Return only IPv4 neighbors from the configured private scan scope."""
    allowed = [ipaddress.ip_network(network) for network in networks]
    found: Dict[str, list[int]] = {}
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            address = ipaddress.ip_address(fields[0])
        except ValueError:
            continue
        if (
            address.version == 4
            and any(address in network for network in allowed)
            and "FAILED" not in fields
        ):
            found[str(address)] = []
    return found


class AgBeyin:
    """Persist network facts and run at most five bounded scans per 24 hours."""

    def __init__(
        self,
        root: Path | str,
        runner: Callable[..., Any] = subprocess.run,
        clock: Callable[[], float] = time.time,
        cevre_modu: Optional[bool] = None,
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "zeka" / "ag_beyin.json"
        self.lock_path = self.root / "zeka" / "ag_beyin.lock"
        self.scope_path = self.root / "ag_kapsam.json"
        self.runner = runner
        self.clock = clock
        # cevre_modu: None → ag_kapsam.json'daki "cevre_modu" anahtarı (varsayılan: klasik)
        self._cevre_modu_arg = cevre_modu
        self._cevre: Optional[CevreIzleyici] = None
        self._kapsam_onbellek: tuple[float, Dict[str, Any]] = (-1.0, {})
        self.data = self._load()

    # ---------- Çevre modu: arp-scan + olay güdümlü tarama (bkz. ag_cevre.py) ----------
    def _kapsam_ayar(self) -> Dict[str, Any]:
        """ag_kapsam.json ham ayarı (değişiklik anında geçerli, mtime önbellekli)."""
        try:
            mtime = self.scope_path.stat().st_mtime
        except OSError:
            return {}
        if mtime != self._kapsam_onbellek[0]:
            try:
                ham = json.loads(self.scope_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                ham = {}
            self._kapsam_onbellek = (mtime, ham if isinstance(ham, dict) else {})
        return self._kapsam_onbellek[1]

    @property
    def cevre_modu(self) -> bool:
        if self._cevre_modu_arg is not None:
            return bool(self._cevre_modu_arg)
        return self._kapsam_ayar().get("cevre_modu") is True

    def _get_cevre(self) -> CevreIzleyici:
        if self._cevre is None:
            self._cevre = CevreIzleyici(
                self.root, runner=self.runner, clock=self.clock,
                kapsam_fn=self._scope, ayar_fn=self._kapsam_ayar,
            )
        return self._cevre

    def cevre_baglanti_gozlemi(self, conn_info: dict) -> list:
        """Pasif bağlantı gözleminden anormal istek tespiti (çevre modunda)."""
        if not self.cevre_modu:
            return []
        return self._get_cevre().baglanti_gozlemi(conn_info, self.clock())

    def _cevre_adim(self, now: float) -> Dict[str, Any]:
        sonuc = self._get_cevre().adim(now)
        if not sonuc.get("noop"):
            self.data["last_scan"] = {
                key: sonuc.get(key) for key in
                ("t", "ok", "probe", "hosts", "ports", "probe_reward", "step", "reason")
            }
            self.save()
        return sonuc

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return self._fresh_data()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("ag_beyin.json okunamadi: %s" % error) from error
        if not isinstance(data, dict) or data.get("schema") != 1:
            raise ValueError("ag_beyin.json semasi taninmiyor")
        data.setdefault("tools", {})
        data.setdefault("ports", {})
        data.setdefault("devices", {})
        data.setdefault("scans", [])
        for key, value in TOOL_KNOWLEDGE.items():
            data["tools"].setdefault(key, dict(value))
        for key, value in PORT_KNOWLEDGE.items():
            data["ports"].setdefault(key, dict(value))
        data.setdefault("probe_learning", {})
        data.setdefault("reference_learning", {})
        data.setdefault("skills", {})
        data.setdefault("social_learning", {"enabled": False, "peers": []})
        data.setdefault(
            "scan_state",
            {"step": 1, "live_hosts": [], "last_networks": [], "step_started_at": 0},
        )
        for action in PROBE_ACTIONS:
            data["skills"].setdefault(action, {
                "scope": SKILL_LIMITS[action],
                "source": "fixed_safe_adapter",
                "attempts": 0,
                "successes": 0,
                "failures": 0,
                "reward_total": 0.0,
            })
        return data

    @staticmethod
    def _fresh_data() -> Dict[str, Any]:
        return {
            "schema": 1,
            "tools": {key: dict(value) for key, value in TOOL_KNOWLEDGE.items()},
            "ports": {key: dict(value) for key, value in PORT_KNOWLEDGE.items()},
            "devices": {},
            "scans": [],
            "probe_learning": {},
            "reference_learning": {},
            "skills": {
                action: {
                    "scope": SKILL_LIMITS[action],
                    "source": "fixed_safe_adapter",
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "reward_total": 0.0,
                }
                for action in PROBE_ACTIONS
            },
            "social_learning": {"enabled": False, "peers": []},
            "scan_state": {
                "step": 1,
                "live_hosts": [],
                "last_networks": [],
                "step_started_at": 0,
            },
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name("%s.%d.tmp" % (self.path.name, os.getpid()))
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    # ---------- Yeni: Pasif trafik gözlemi (Ağ beyni öğrenme) ----------
    def learn_traffic(self, conn_info: dict) -> dict:
        """Pasif bir ağ bağlantısı gözlemini beyne kaydeder.

        conn_info anahtarları:
          - local_port: int
          - remote_ip: str
          - remote_port: int
          - protocol: "tcp" | "udp"
          - state: str (ör. ESTABLISHED, LISTEN)
          - bytes_sent: int
          - bytes_recv: int

        Döndürür: {"yeni_mi": bool, "cikarilan": str}
        """
        simdi = time.time()
        local_port = str(conn_info.get("local_port", "?"))
        remote_ip = str(conn_info.get("remote_ip", "?"))
        remote_port = str(conn_info.get("remote_port", "?"))
        protocol = str(conn_info.get("protocol", "tcp"))
        state = str(conn_info.get("state", "?"))

        # Anahtar: protokol:yerel_port:uzak_ip:uzak_port
        key = "%s:%s:%s:%s" % (protocol, local_port, remote_ip, remote_port)

        devices = self.data.setdefault("devices", {})
        yeni_mi = key not in devices

        if yeni_mi:
            devices[key] = {
                "key": key,
                "local_port": local_port,
                "remote_ip": remote_ip,
                "remote_port": remote_port,
                "protocol": protocol,
                "state": state,
                "bytes_sent": int(conn_info.get("bytes_sent", 0)),
                "bytes_recv": int(conn_info.get("bytes_recv", 0)),
                "gorulenme_sayisi": 1,
                "ilk_gorunme": simdi,
                "son_gorunme": simdi,
                "durum": "yeni",
                "kaynak": "pasif_gozlem",
            }
            cikarilan = "yeni_ag_trafigi"
        else:
            d = devices[key]
            d["gorulenme_sayisi"] = int(d.get("gorulenme_sayisi", 0)) + 1
            d["son_gorunme"] = simdi
            d["bytes_sent"] = int(d.get("bytes_sent", 0)) + int(conn_info.get("bytes_sent", 0))
            d["bytes_recv"] = int(d.get("bytes_recv", 0)) + int(conn_info.get("bytes_recv", 0))
            d["state"] = state
            if d.get("durum") == "yeni":
                d["durum"] = "bilinik"
            cikarilan = "bilinik_ag_trafigi"

        self.save()
        return {"yeni_mi": yeni_mi, "cikarilan": cikarilan, "key": key}

    def traffic_raporu(self) -> dict:
        devices = self.data.get("devices", {})
        yeni = [k for k, v in devices.items() if v.get("durum") == "yeni"]
        return {
            "toplam_baglanti": len(devices),
            "yeni_baglanti": len(yeni),
            "yeni_anahtarlar": yeni[:10],
        }

    def _scope(self) -> tuple[list[str], Optional[str]]:
        try:
            config = json.loads(self.scope_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], "ag_kapsam.json bulunamadi"
        except (OSError, ValueError) as error:
            return [], "ag_kapsam.json okunamadi: %s" % error
        if not isinstance(config, dict) or config.get("acik") is not True:
            return [], "ag_kapsam.json taramayi acmiyor"

        networks = []
        total_addresses = 0
        configured = config.get("izin_aglari", [])
        if not isinstance(configured, list):
            return [], "izin_aglari liste olmali"
        for raw in configured:
            try:
                network = ipaddress.ip_network(str(raw), strict=False)
            except ValueError:
                continue
            if (
                network.version != 4
                or not network.is_private
                or network.is_loopback
                or network.is_link_local
                or network.num_addresses > MAX_SCOPE_ADDRESSES
            ):
                continue
            if network.with_prefixlen in networks:
                continue
            total_addresses += network.num_addresses
            if total_addresses > MAX_SCOPE_ADDRESSES:
                return [], "yerel tarama kapsam siniri asildi"
            networks.append(network.with_prefixlen)
        if not networks:
            return [], "taranabilir ozel IPv4 laboratuvar agi yok"
        return networks, None

    def _recent_scans(self, now: float) -> list[dict[str, Any]]:
        recent = []
        for scan in self.data["scans"]:
            try:
                if now - float(scan["t"]) < WINDOW_SECONDS:
                    recent.append(scan)
            except (KeyError, TypeError, ValueError):
                continue
        return recent

    def next_due_in(self, now: Optional[float] = None) -> float:
        now = self.clock() if now is None else float(now)
        if self.cevre_modu:
            return self._get_cevre().due_in(now)
        recent = self._recent_scans(now)
        if not recent:
            return 0.0
        latest = max(recent, key=lambda scan: float(scan["t"]))
        if (
            not latest.get("ok")
            and int(latest.get("profile", 1)) < SCAN_PROFILE_VERSION
            and len(recent) < MAX_SCANS_PER_WINDOW
        ):
            return 0.0
        times = sorted(float(scan["t"]) for scan in recent)
        if len(times) >= MAX_SCANS_PER_WINDOW:
            return max(0.0, times[0] + WINDOW_SECONDS - now)
        return max(0.0, times[-1] + WINDOW_SECONDS / MAX_SCANS_PER_WINDOW - now)

    def scan_if_due(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        now = self.clock() if now is None else float(now)
        self.learn_local_knowledge(now)
        if self.next_due_in(now) > 0:
            return None

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"ok": False, "skipped": True, "reason": "tarama zaten calisiyor"}
            self.data = self._load()
            if self.next_due_in(now) > 0:
                return None
            return self.scan_next_step(now)

    def _scan(self, started_at: float) -> Dict[str, Any]:
        networks, scope_error = self._scope()
        if scope_error:
            return self._record_failure(started_at, scope_error)
        safe_path = "/usr/bin:/bin:/usr/sbin:/sbin"
        nmap = shutil.which("nmap", path=safe_path)
        if not nmap:
            return self._record_failure(started_at, "nmap bulunamadi")
        discovery_argv = [
            nmap, "-sn", "-n", "-T3", "--max-retries", "1",
            "--max-rate", "50", "--host-timeout", "5s", "-oX", "-",
        ] + networks
        try:
            discovery = self.runner(
                discovery_argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return self._record_failure(
                started_at, "%s: %s" % (type(error).__name__, error)
            )
        if discovery.returncode != 0:
            return self._record_failure(
                started_at, (discovery.stderr or "nmap host discovery failed")[:300]
            )
        try:
            hosts = parse_nmap_xml(discovery.stdout or "")
        except ET.ParseError as error:
            return self._record_failure(started_at, "nmap XML hatasi: %s" % error)

        scanned_hosts = sorted(
            hosts, key=lambda value: int(ipaddress.ip_address(value))
        )
        warnings = []
        candidates = []
        if scanned_hosts:
            candidates.append("nmap_tcp_ports")
        mdns_path = shutil.which("avahi-browse", path=safe_path)
        if mdns_path:
            candidates.append("avahi_browse")
        ip_path = shutil.which("ip", path=safe_path)
        if ip_path:
            candidates.append("ip_neigh")
        action = self._choose_probe(candidates)
        before = self._known_evidence()
        action_path = None
        if action is not None:
            action_path = {
                "nmap_tcp_ports": nmap,
                "avahi_browse": mdns_path,
                "ip_neigh": ip_path,
            }.get(action)
        if action and action_path:
            self._learn_tool_help(action, action_path, started_at, warnings)
        mdns_records: Dict[str, Dict[str, Any]] = {}
        neighbor_hosts: set[str] = set()
        action_verified = True
        if action == "avahi_browse" and mdns_path:
            try:
                mdns_result = self.runner(
                    [mdns_path, "--all", "--resolve", "--terminate"],
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                if mdns_result.returncode == 0:
                    mdns_records = parse_avahi_output(
                        mdns_result.stdout or "", networks
                    )
                    for ip in mdns_records:
                        hosts.setdefault(ip, [])
                else:
                    action_verified = False
                    warnings.append(
                        (mdns_result.stderr or "avahi-browse failed")[:200]
                    )
            except (OSError, subprocess.TimeoutExpired) as error:
                action_verified = False
                warnings.append(
                    ("%s: %s" % (type(error).__name__, error))[:200]
                )
        elif action == "ip_neigh" and ip_path:
            try:
                neighbor_result = self.runner(
                    [ip_path, "neigh", "show"],
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if neighbor_result.returncode == 0:
                    neighbors = parse_ip_neigh(
                        neighbor_result.stdout or "", networks
                    )
                    neighbor_hosts = set(neighbors)
                    for ip in neighbors:
                        hosts.setdefault(ip, [])
                else:
                    action_verified = False
                    warnings.append(
                        (neighbor_result.stderr or "ip neigh failed")[:200]
                    )
            except (OSError, subprocess.TimeoutExpired) as error:
                action_verified = False
                warnings.append(
                    ("%s: %s" % (type(error).__name__, error))[:200]
                )

        if action == "nmap_tcp_ports" and scanned_hosts:
            port_argv = [
                nmap, "-sT", "-Pn", "-n", "-T3", "--open",
                "--max-rate", "25", "--max-retries", "1",
                "--host-timeout", "8s", "-p",
                ",".join(str(port) for port in PORTS), "-oX", "-",
            ] + scanned_hosts[:MAX_PORT_SCAN_HOSTS]
            try:
                port_result = self.runner(
                    port_argv,
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                return self._record_failure(
                    started_at, "%s: %s" % (type(error).__name__, error),
                    hosts=hosts, probe=action,
                )
            if port_result.returncode != 0:
                return self._record_failure(
                    started_at,
                    (port_result.stderr or "nmap TCP port survey failed")[:300],
                    hosts=hosts, probe=action,
                )
            try:
                port_hosts = parse_nmap_xml(port_result.stdout or "")
            except ET.ParseError as error:
                return self._record_failure(
                    started_at, "nmap port XML hatasi: %s" % error,
                    hosts=hosts, probe=action,
                )
            for ip, ports in port_hosts.items():
                if ip in hosts:
                    hosts[ip] = ports

        reward = self._probe_reward(
            action, hosts, mdns_records, before, neighbor_hosts
        )
        if action:
            self._record_probe_result(
                action, reward, started_at, verified=action_verified
            )
        self._learn(
            hosts, networks, started_at, complete=True,
            mdns_records=mdns_records,
        )
        total_open = sum(len(ports) for ports in hosts.values())
        record = {
            "t": started_at,
            "ok": True,
            "networks": networks,
            "hosts": len(hosts),
            "ports": total_open,
            "port_scan_hosts": min(len(scanned_hosts), MAX_PORT_SCAN_HOSTS),
            "mdns_services": sum(
                len(record["services"]) for record in mdns_records.values()
            ),
            "warnings": warnings,
            "profile": SCAN_PROFILE_VERSION,
            "probe": action,
            "probe_reward": reward,
        }
        self.data["scans"].append(record)
        self.data["scans"] = self.data["scans"][-20:]
        self.data["last_scan"] = record
        self.save()
        return {"ok": True, **record}

    def scan_next_step(self, now: float) -> Dict[str, Any]:
        """Tarama sırasındaki bir sonraki adımdan bir tane yürütür.

        Adımlar (tarama_sirano eşleşir):
          1. Ağ keşfi (nmap -sn): canlı IP'leri bul, scan_state'e kaydet.
          2. Port taraması (nmap -sT -p...): adım1'deki canlı IP'lere port tarası.
          3. msfconsole safe recon (plan_only): gerçek yürütülmez, yalnızca plan kaydı.
        """
        if self.cevre_modu:
            return self._cevre_adim(now)
        state = self.data.setdefault(
            "scan_state",
            {"step": 1, "live_hosts": [], "last_networks": [], "step_started_at": 0},
        )
        step = int(state.get("step", 1))
        if step == 1:
            return self._step1_discovery(now, state)
        if step == 2:
            return self._step2_port_scan(now, state)
        if step == 3:
            return self._step3_msfconsole_plan(now, state)
        # Geçersiz durum → sıfırla ve başından başla
        state["step"] = 1
        state["live_hosts"] = []
        self.save()
        return self._step1_discovery(now, state)

    def _step1_discovery(self, started_at: float,
                         state: Dict[str, Any]) -> Dict[str, Any]:
        networks, scope_error = self._scope()
        if scope_error:
            return self._record_failure(started_at, scope_error)
        safe_path = "/usr/bin:/bin:/usr/sbin:/sbin"
        nmap = shutil.which("nmap", path=safe_path)
        if not nmap:
            return self._record_failure(started_at, "nmap bulunamadi")
        discovery_argv = [
            nmap, "-sn", "-n", "-T3", "--max-retries", "1",
            "--max-rate", "50", "--host-timeout", "5s", "-oX", "-",
        ] + networks
        try:
            discovery = self.runner(
                discovery_argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return self._record_failure(
                started_at, "%s: %s" % (type(error).__name__, error)
            )
        if discovery.returncode != 0:
            return self._record_failure(
                started_at, (discovery.stderr or "nmap host discovery failed")[:300]
            )
        try:
            hosts = parse_nmap_xml(discovery.stdout or "")
        except ET.ParseError as error:
            return self._record_failure(
                started_at, "nmap XML hatasi: %s" % error
            )
        scanned_hosts = sorted(
            hosts, key=lambda value: int(ipaddress.ip_address(value))
        )
        # Canlı hostleri scan_state'e kaydet
        state["live_hosts"] = scanned_hosts
        state["last_networks"] = networks
        state["step_started_at"] = started_at
        state["step"] = 2
        # Cihazları online olarak işaretle (port bilgisi henüz yok)
        self._learn(
            {ip: [] for ip in scanned_hosts},
            networks,
            started_at,
            complete=True,
        )
        record = {
            "t": started_at,
            "ok": True,
            "networks": networks,
            "hosts": len(scanned_hosts),
            "ports": 0,
            "port_scan_hosts": 0,
            "mdns_services": 0,
            "warnings": [],
            "profile": SCAN_PROFILE_VERSION,
            "probe": "nmap_tcp_ports",
            "probe_reward": float(len(scanned_hosts)),
            "step": 1,
        }
        self.data["scans"].append(record)
        self.data["scans"] = self.data["scans"][-20:]
        self.data["last_scan"] = record
        self.save()
        return {"ok": True, **record}

    def _step2_port_scan(self, started_at: float,
                         state: Dict[str, Any]) -> Dict[str, Any]:
        live_hosts = state.get("live_hosts", [])
        networks = state.get("last_networks", [])
        if not live_hosts:
            # Keşifte host bulunamadı → doğrudan adım 3'e geç
            state["step"] = 3
            self.save()
            return self._step3_msfconsole_plan(started_at, state)
        safe_path = "/usr/bin:/bin:/usr/sbin:/sbin"
        nmap = shutil.which("nmap", path=safe_path)
        if not nmap:
            return self._record_failure(started_at, "nmap bulunamadi")
        port_argv = [
            nmap, "-sT", "-p22,80,443,3389", "-n", "-T3", "--max-retries", "1",
            "--max-rate", "50", "--host-timeout", "5s", "-oX", "-",
        ] + live_hosts
        try:
            port_result = self.runner(
                port_argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return self._record_failure(
                started_at, "%s: %s" % (type(error).__name__, error)
            )
        if port_result.returncode != 0:
            return self._record_failure(
                started_at, (port_result.stderr or "nmap port scan failed")[:300]
            )
        try:
            port_hosts = parse_nmap_xml(port_result.stdout or "")
        except ET.ParseError as error:
            return self._record_failure(
                started_at, "nmap port XML hatasi: %s" % error
            )
        # Sadece adım1'de bulunan canlı IP'leri tut
        live_set = set(live_hosts)
        filtered = {ip: ports for ip, ports in port_hosts.items()
                    if ip in live_set}
        total_open = sum(len(ports) for ports in filtered.values())
        # Cihaz portlarını öğren
        self._learn(filtered, networks, started_at, complete=True)
        # Adım 3'e geç
        state["step"] = 3
        record = {
            "t": started_at,
            "ok": True,
            "networks": networks,
            "hosts": len(filtered),
            "ports": total_open,
            "port_scan_hosts": min(len(filtered), MAX_PORT_SCAN_HOSTS),
            "mdns_services": 0,
            "warnings": [],
            "profile": SCAN_PROFILE_VERSION,
            "probe": "nmap_tcp_ports",
            "probe_reward": float(total_open),
            "step": 2,
        }
        self.data["scans"].append(record)
        self.data["scans"] = self.data["scans"][-20:]
        self.data["last_scan"] = record
        self.save()
        return {"ok": True, **record}

    def _step3_msfconsole_plan(self, started_at: float,
                               state: Dict[str, Any]) -> Dict[str, Any]:
        networks = state.get("last_networks", [])
        # msfconsole safe recon: plan_only = true, gerçek süreç başlatılmaz
        record = {
            "t": started_at,
            "ok": True,
            "networks": networks,
            "hosts": len(state.get("live_hosts", [])),
            "ports": 0,
            "port_scan_hosts": 0,
            "mdns_services": 0,
            "warnings": [],
            "profile": SCAN_PROFILE_VERSION,
            "probe": "msfconsole_safe",
            "probe_reward": 1.0,
            "plan_only": True,
            "step": 3,
        }
        self.data["scans"].append(record)
        self.data["scans"] = self.data["scans"][-20:]
        self.data["last_scan"] = record
        # Sıfırla: sonraki tarama döngüsü adım 1'den başlar
        state["step"] = 1
        state["live_hosts"] = []
        state["last_networks"] = []
        state["step_started_at"] = 0
        self.save()
        return {"ok": True, **record}

    def learn_local_knowledge(
        self, observed_at: Optional[float] = None
    ) -> Dict[str, Any]:
        """Refresh local tool help and service-file facts without scanning the network."""
        observed_at = self.clock() if observed_at is None else float(observed_at)
        warnings: list[str] = []
        changed = self._learn_local_references(observed_at)
        tool_paths = {
            "nmap_tcp_ports": "nmap",
            "avahi_browse": "avahi-browse",
            "ip_neigh": "ip",
        }
        safe_path = "/usr/bin:/bin:/usr/sbin:/sbin"
        learned_tools = []
        for action, command in tool_paths.items():
            executable = shutil.which(command, path=safe_path)
            if executable and self._learn_tool_help(
                action, executable, observed_at, warnings
            ):
                learned_tools.append(command)
                changed = True
        try:
            social = SocialLearning(self.root, self.clock)
            exchange = social.exchange(self.data.get("skills", {}))
            social_state = {
                key: exchange[key]
                for key in ("enabled", "instance_id", "peers", "reports_received")
            }
            if social_state != self.data.get("social_learning"):
                self.data["social_learning"] = social_state
                changed = True
            self._social = social
        except (OSError, RuntimeError, ValueError) as error:
            warnings.append("sosyal ogrenme: %s: %s" % (
                type(error).__name__, str(error)[:160]
            ))
        consolidated = self._consolidate(observed_at)
        if consolidated:
            changed = True
        if changed:
            self.save()
        return {
            "changed": changed,
            "tools": learned_tools,
            "references": list(self.data.get("reference_learning", {})),
            "warnings": warnings,
            "consolidated": consolidated,
            "social": self.data.get("social_learning", {}),
        }

    def _consolidate(self, observed_at: float, force: bool = False) -> bool:
        """Compact duplicate metadata while keeping accumulated evidence intact."""
        state = self.data.setdefault("consolidation", {})
        last = float(state.get("last_at", 0) or 0)
        if not force and last > 0 and observed_at - last < CONSOLIDATION_SECONDS:
            return False
        self.data["scans"] = self.data.get("scans", [])[-20:]
        compacted_refs = 0
        for info in self.data.get("ports", {}).values():
            for key in ("reference_names", "reference_sources"):
                values = info.get(key)
                if isinstance(values, list):
                    unique = list(dict.fromkeys(str(value) for value in values))[:8]
                    compacted_refs += len(values) - len(unique)
                    info[key] = unique
        compacted_help = 0
        for tool in self.data.get("tools", {}).values():
            help_lines = tool.get("learned_help")
            if isinstance(help_lines, list):
                unique_lines = list(dict.fromkeys(str(line)[:180]
                                                  for line in help_lines))[:3]
                compacted_help += len(help_lines) - len(unique_lines)
                tool["learned_help"] = unique_lines
        state.update({
            "last_at": observed_at,
            "scans_kept": len(self.data["scans"]),
            "reference_duplicates_removed": compacted_refs,
            "help_duplicates_removed": compacted_help,
        })
        return True

    def _learn_local_references(self, observed_at: float) -> bool:
        """Learn names for the already bounded port set from local reference files."""
        registry = self.data.setdefault("reference_learning", {})
        allowed_ports = set(PORTS)
        changed_any = False
        for raw_path in REFERENCE_FILES:
            path = Path(raw_path)
            try:
                stat = path.stat()
                previous = registry.get(str(path), {})
                if (
                    previous.get("mtime") == stat.st_mtime
                    and previous.get("size") == stat.st_size
                ):
                    continue
                with path.open("rb") as source:
                    content = source.read(MAX_REFERENCE_BYTES + 1)
            except OSError as error:
                previous = registry.get(str(path), {})
                if observed_at - float(previous.get("read_at", 0) or 0) < HELP_RETRY_SECONDS:
                    continue
                registry[str(path)] = {
                    "read_at": observed_at,
                    "error": "%s: %s" % (type(error).__name__, str(error)[:160]),
                }
                changed_any = True
                continue

            truncated = len(content) > MAX_REFERENCE_BYTES
            text = content[:MAX_REFERENCE_BYTES].decode("utf-8", "replace")
            learned = 0
            for line in text.splitlines():
                fields = line.split()
                if len(fields) < 2 or fields[0].startswith("#"):
                    continue
                try:
                    port_text, protocol = fields[1].split("/", 1)
                    port = int(port_text)
                except (ValueError, IndexError):
                    continue
                if protocol.lower() != "tcp" or port not in allowed_ports:
                    continue
                key = "tcp/%d" % port
                info = self.data["ports"].setdefault(
                    key, {"name": "Bilinmeyen", "purpose": "Kayitli TCP portu"}
                )
                names = info.setdefault("reference_names", [])
                if fields[0] not in names:
                    names.append(fields[0])
                    learned += 1
                sources = info.setdefault("reference_sources", [])
                if str(path) not in sources:
                    sources.append(str(path))
                    changed_any = True
            registry[str(path)] = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
                "read_at": observed_at,
                "entries_learned": learned,
                "truncated": truncated,
            }
            changed_any = True
        return changed_any

    def _learn_tool_help(
        self,
        action: str,
        executable: str,
        observed_at: float,
        warnings: list[str],
    ) -> bool:
        """Read bounded help for a fixed, known-safe probe adapter only."""
        tool = self.data["tools"].get(action)
        flags = PROBE_HELP.get(action)
        if tool is None or flags is None:
            return False
        last_read = float(tool.get("learned_help_at", 0) or 0)
        if last_read > 0 and observed_at - last_read < REFERENCE_REFRESH_SECONDS:
            return False
        last_attempt = float(tool.get("learned_help_attempted_at", 0) or 0)
        if last_attempt > 0 and observed_at - last_attempt < HELP_RETRY_SECONDS:
            return False
        tool["learned_help_attempted_at"] = observed_at
        try:
            result = self.runner(
                [executable, *flags],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            warnings.append(("help %s: %s" % (
                action, type(error).__name__
            ))[:200])
            return True
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            warnings.append("help %s bos cikti" % action)
            return True
        tool["learned_help"] = [line[:180] for line in lines[:3]]
        tool["learned_help_at"] = observed_at
        tool["learned_from"] = executable
        skill = self.data.get("skills", {}).get(action)
        if skill is not None:
            skill["documentation"] = list(tool["learned_help"])
            skill["documentation_source"] = executable
            skill["documentation_at"] = observed_at
        return True

    def _known_evidence(self) -> Dict[str, set[str]]:
        return {
            "hosts": set(self.data["devices"]),
            "ports": {
                "%s/%s" % (ip, port)
                for ip, device in self.data["devices"].items()
                for port in device.get("ports", {})
            },
            "services": {
                "%s/%s" % (ip, service)
                for ip, device in self.data["devices"].items()
                for service in device.get("services", {})
            },
        }

    def _choose_probe(self, candidates: Iterable[str]) -> Optional[str]:
        """Choose the least-understood useful probe, then learn its measured yield."""
        actions = sorted(set(candidates) & set(PROBE_ACTIONS))
        if not actions:
            return None
        stats = self.data.setdefault("probe_learning", {})
        for action in actions:
            stats.setdefault(action, {"attempts": 0, "reward_total": 0.0})
        total = sum(int(stats[action].get("attempts", 0)) for action in actions)
        untried = [action for action in actions
                   if int(stats[action].get("attempts", 0)) == 0]
        if untried:
            return untried[0]
        def score(action: str) -> tuple[float, str]:
            local = stats[action]
            attempts = max(1, int(local["attempts"]))
            reward_total = float(local.get("reward_total", 0.0))
            prior = None
            social = getattr(self, "_social", None)
            if social is not None:
                prior = social.prior(
                    action, self.data.get("skills", {}).get(action, {})
                )
            weight = float(prior["weight"]) if prior else 0.0
            peer_reward = float(prior["mean_reward"]) if prior else 0.0
            mean_reward = (
                reward_total + peer_reward * weight
            ) / (attempts + weight)
            exploration = math.sqrt(
                2.0 * math.log(total + 1) / (attempts + weight)
            )
            validation = self.data.get("skills", {}).get(action, {})
            valid_rate = float(validation.get("successes", 0)) / max(
                1, int(validation.get("attempts", 0))
            )
            confidence_adjustment = (valid_rate - 0.5) * 0.5
            # Eğitilen tarama sırası: önceki adımlara küçük bir öncelik
            # bonusu vererek _choose_probe eğitilen sırayı (keşif → port
            # tarama) tercih etmeye zorlar.
            oncelik = self._sirala_onceligi(action)
            if oncelik < 10**9:
                mean_reward += 0.20 / oncelik  # adım 1 → +0.20, adım 2 → +0.10
            return mean_reward + exploration + confidence_adjustment, action

        return max(actions, key=score)

    @staticmethod
    def _probe_reward(
        action: Optional[str],
        hosts: Dict[str, list[int]],
        mdns_records: Dict[str, Dict[str, Any]],
        before: Dict[str, set[str]],
        neighbor_hosts: Optional[set[str]] = None,
    ) -> float:
        if action == "nmap_tcp_ports":
            new_ports = sum(
                1 for ip, ports in hosts.items()
                for port in ports if "%s/tcp/%s" % (ip, port) not in before["ports"]
            )
            return float(new_ports)
        if action == "avahi_browse":
            new_hosts = set(mdns_records) - before["hosts"]
            new_services = {
                "%s/%s" % (ip, service)
                for ip, data in mdns_records.items()
                for service in data.get("services", {})
            } - before["services"]
            new_names = sum(
                1 for ip, data in mdns_records.items()
                if data.get("hostname") and ip not in before["hosts"]
            )
            return float(3 * len(new_hosts) + 2 * len(new_services) + new_names)
        if action == "ip_neigh":
            return float(len((neighbor_hosts or set()) - before["hosts"]))
        return 0.0

    def _record_probe_result(
        self, action: str, reward: float, observed_at: float,
        verified: bool = True,
    ) -> None:
        stats = self.data.setdefault("probe_learning", {}).setdefault(
            action, {"attempts": 0, "reward_total": 0.0}
        )
        stats["attempts"] = int(stats.get("attempts", 0)) + 1
        stats["reward_total"] = float(stats.get("reward_total", 0.0)) + reward
        stats["last_reward"] = reward
        stats["last_used"] = observed_at
        skill = self.data.setdefault("skills", {}).setdefault(action, {
            "scope": SKILL_LIMITS[action],
            "source": "fixed_safe_adapter",
            "attempts": 0,
            "successes": 0,
            "failures": 0,
            "reward_total": 0.0,
        })
        skill["attempts"] = int(skill.get("attempts", 0)) + 1
        skill["successes"] = int(skill.get("successes", 0)) + int(verified)
        skill["failures"] = int(skill.get("failures", 0)) + int(not verified)
        skill["reward_total"] = float(skill.get("reward_total", 0.0)) + reward
        skill["last_verified"] = observed_at if verified else skill.get("last_verified")
        skill["confidence"] = skill["successes"] / skill["attempts"]

    def _record_failure(
        self,
        started_at: float,
        reason: str,
        hosts: Optional[Dict[str, list[int]]] = None,
        probe: Optional[str] = None,
        probe_verified: bool = False,
    ) -> Dict[str, Any]:
        if probe:
            self._record_probe_result(
                probe, 0.0, started_at, verified=probe_verified
            )
        if hosts:
            networks, _ = self._scope()
            self._learn(hosts, networks, started_at, complete=False)
        record = {
            "t": started_at,
            "ok": False,
            "reason": reason[:300],
            "networks": [],
            "hosts": len(hosts or {}),
            "ports": sum(len(ports) for ports in (hosts or {}).values()),
            "port_scan_hosts": 0,
            "profile": SCAN_PROFILE_VERSION,
            "probe": probe,
            "probe_reward": 0.0 if probe else None,
        }
        self.data["scans"].append(record)
        self.data["scans"] = self.data["scans"][-20:]
        self.data["last_scan"] = record
        self.save()
        return {"ok": False, **record}

    def _learn(
        self,
        hosts: Dict[str, list[int]],
        networks: Iterable[str],
        observed_at: float,
        complete: bool,
        mdns_records: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        scan_number = len(self.data["scans"]) + 1
        if complete:
            for device in self.data["devices"].values():
                device["online"] = False
        for ip, ports in hosts.items():
            device = self.data["devices"].setdefault(
                ip,
                {
                    "first_seen": observed_at,
                    "seen_count": 0,
                    "ports": {},
                },
            )
            device["last_seen"] = observed_at
            device["seen_count"] = int(device.get("seen_count", 0)) + 1
            device["online"] = True
            device["network"] = next(
                (network for network in networks
                 if ipaddress.ip_address(ip) in ipaddress.ip_network(network)),
                None,
            )
            for port in ports:
                key = "tcp/%d" % port
                evidence = device["ports"].setdefault(
                    key, {"first_seen": observed_at, "seen_count": 0}
                )
                evidence["last_seen"] = observed_at
                evidence["seen_count"] = int(evidence.get("seen_count", 0)) + 1
            mdns = (mdns_records or {}).get(ip, {})
            if mdns.get("hostname"):
                device["hostname"] = mdns["hostname"]
            for service_type, instance in mdns.get("services", {}).items():
                service = device.setdefault("services", {}).setdefault(
                    service_type,
                    {"instance": instance, "seen_count": 0},
                )
                service["instance"] = instance or service.get("instance", "")
                service["last_seen"] = observed_at
                service["seen_count"] = int(service.get("seen_count", 0)) + 1
            hints = set()
            for key in device["ports"]:
                hints.update(self.data["ports"].get(key, {}).get("hints", []))
            service_types = set(device.get("services", {}))
            if service_types & {"_googlecast._tcp", "_airplay._tcp", "_raop._tcp"}:
                hints.add("medya_veya_tv")
            if service_types & {"_companion-link._tcp", "_apple-mobdev2._tcp"}:
                hints.add("telefon_veya_tablet_olabilir")
            if service_types & {"_ipp._tcp", "_printer._tcp"}:
                hints.add("yazici")
            device["hints"] = sorted(hints)
            device["classification_note"] = (
                "Port ipuclari olasi rol onerir; telefon/TV/bilgisayar turu "
                "tek basina porttan kesinlestirilemez."
            )
            device["last_scan_number"] = scan_number

    def _sirala_onceligi(self, eylem: str) -> int:
        """Eğitilen tarama sırası içinde eylemin adım numarasını döndürür.

        Küçük numara = önce gerçekleşmesi gereken adım (daha yüksek öncelik).
        tarama_sirano yoksa veya eylem listede değilse → büyük sayı
        (önceliksiz, sıraya dahil edilmez).
        """
        sirano = self.data.get("tarama_sirano", {})
        adimlar = sirano.get("adimlar", []) if isinstance(sirano, dict) else []
        for adim in adimlar:
            if adim.get("eylem") == eylem:
                return int(adim.get("adim", 10**9))
        return 10**9

    def egit_sirano(self, dosya_yolu: str | Path) -> Dict[str, Any]:
        """Tarama stratejisini eğitim verisi dosyasından yükleyip beyne yaz.

        Bu metot komut yürütmez; yalnızca ag_beyin.json içindeki
        tarama_sirano, probe_learning ve skills tablosunu sıralı ödüllle
        tohumlar. Böylece _choose_probe eğitilen sırayı (önce ağ keşfi,
        sonra port taraması) tercih eder. plan_only:1 olan adımlar
        (ör. msfconsole safe recon) yalnızca plan olarak kaydedilir,
        gerçek süreç başlatılmaz — güvenlik için yürütülmez.
        """
        dosya = Path(dosya_yolu)
        try:
            veri = json.loads(dosya.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("ag_tarama_sirano okunamadı: %s" % error) from error

        adimlar = veri.get("adimlar")
        if not isinstance(adimlar, list) or not adimlar:
            raise ValueError("ag_tarama_sirano: 'adimlar' listesi gerekli")

        for adim in adimlar:
            for alan in ("adim", "isim", "eylem", "kosul", "beklenen_odul"):
                if alan not in adim:
                    raise ValueError(
                        "ag_tarama_sirano: adım eksik alan '%s'" % alan
                    )

        now = self.clock()
        probe_stats = self.data.setdefault("probe_learning", {})
        skills = self.data.setdefault("skills", {})

        for adim in adimlar:
            eylem = adim["eylem"]
            odul = float(adim.get("beklenen_odul", 0.0))
            plan_only = bool(adim.get("plan_only", False))

            # probe_learning: tek deneme, beklenien odul → _choose_probe'de bu
            # eylemin ortalama odulunu yüksek tutar (sıralı tercih).
            stats = probe_stats.setdefault(
                eylem, {"attempts": 0, "reward_total": 0.0}
            )
            stats["attempts"] = int(stats.get("attempts", 0)) + 1
            stats["reward_total"] = float(stats.get("reward_total", 0.0)) + odul
            stats["last_reward"] = odul
            stats["last_used"] = now

            # skills: aynı sıralı bilgiyi, plan_only bayrağıyla birlikte kaydet.
            skill = skills.setdefault(
                eylem,
                {
                    "scope": SKILL_LIMITS.get(
                        eylem, "ag_tarama_sirano eğitim verisinden gelen adım"
                    ),
                    "source": "ag_tarama_sirano",
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "reward_total": 0.0,
                },
            )
            skill["attempts"] = int(skill.get("attempts", 0)) + 1
            skill["successes"] = int(skill.get("successes", 0)) + 1
            skill["reward_total"] = float(skill.get("reward_total", 0.0)) + odul
            skill["confidence"] = skill["successes"] / skill["attempts"]
            skill["plan_only"] = plan_only
            skill["sirano_adim"] = int(adim.get("adim", 10**9))
            skill["sirano_amac"] = adim.get("isim", "")

        # Eğitilen sırayı kalıcı veri olarak yaz.
        self.data["tarama_sirano"] = {
            "surum": int(veri.get("surum", 1)),
            "aciklama": veri.get("aciklama", ""),
            "adimlar": [
                {
                    "adim": int(a.get("adim")),
                    "isim": a.get("isim"),
                    "eylem": a.get("eylem"),
                    "kosul": a.get("kosul"),
                    "beklenen_odul": float(a.get("beklenen_odul", 0.0)),
                    "plan_only": bool(a.get("plan_only", False)),
                    "sonraki": a.get("sonraki"),
                }
                for a in adimlar
            ],
        }

        self.save()
        return {
            "egitilen_adim_sayisi": len(adimlar),
            "eylemler": [a["eylem"] for a in adimlar],
            "plan_only_adimlar": [
                int(a["adim"]) for a in adimlar if a.get("plan_only")
            ],
        }

    def summary(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = self.clock() if now is None else float(now)
        recent = self._recent_scans(now)
        devices = []
        def _ip_sirasi(satir: Any) -> tuple:
            # devices sözlüğü, learn_traffic'in IP olmayan anahtarlarını da içerir
            try:
                return (0, int(ipaddress.ip_address(satir[0])))
            except ValueError:
                return (1, 0)

        for ip, device in sorted(
            ((k, v) for k, v in self.data["devices"].items()
             if _ip_sirasi((k, v))[0] == 0),
            key=_ip_sirasi,
        ):
            ports = []
            for key, evidence in sorted(device.get("ports", {}).items()):
                info = self.data["ports"].get(key, {})
                ports.append({
                    "port": key,
                    "name": info.get("name", "Bilinmeyen"),
                    "purpose": info.get("purpose", "Kayitli acik TCP portu"),
                    "seen_count": evidence.get("seen_count", 0),
                    "last_seen": evidence.get("last_seen"),
                })
            devices.append({
                "ip": ip,
                "online": bool(device.get("online")),
                "seen_count": device.get("seen_count", 0),
                "last_seen": device.get("last_seen"),
                "hints": device.get("hints", []),
                "ports": ports,
                "hostname": device.get("hostname"),
                "services": [
                    {
                        "type": service_type,
                        "instance": evidence.get("instance", ""),
                        "seen_count": evidence.get("seen_count", 0),
                        "last_seen": evidence.get("last_seen"),
                    }
                    for service_type, evidence
                    in sorted(device.get("services", {}).items())
                ],
                "classification_note": device.get("classification_note", ""),
            })
        return {
            "schedule": {
                "limit_per_24h": MAX_SCANS_PER_WINDOW,
                "completed_in_24h": len(recent),
                "next_in_seconds": self.next_due_in(now),
            },
            "device_count": len(devices),
            "online_count": sum(device["online"] for device in devices),
            "devices": devices,
            "tools": list(self.data["tools"].values()),
            "port_knowledge": [
                {"port": key, **value}
                for key, value in sorted(self.data["ports"].items())
            ],
            "skills": self.data.get("skills", {}),
            "reference_learning": self.data.get("reference_learning", {}),
            "last_scan": self.data.get("last_scan"),
            "probe_learning": self.data.get("probe_learning", {}),
            "social_learning": self.data.get("social_learning", {}),
            "consolidation": self.data.get("consolidation", {}),
            "cevre": self._get_cevre().ozet() if self.cevre_modu else None,
        }

    def stimulus_tokens(self) -> list[str]:
        """Return coarse evidence tokens for the existing symbolic brain."""
        online = [
            device for device in self.data["devices"].values()
            if device.get("online")
        ]
        if not online:
            return []
        tokens = ["ag_ciha:%s" % (
            "az" if len(online) < 3 else "orta" if len(online) < 10 else "cok"
        )]
        all_hints = {
            hint for device in online for hint in device.get("hints", [])
        }
        tokens.extend("ag_rol:" + hint for hint in sorted(all_hints))
        return tokens
