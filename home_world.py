"""Read-only, bounded observations of the local machine and approved web origins."""

from __future__ import annotations

import http.client
import ipaddress
import os
import platform
import shutil
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit


_MAX_SITES = 5
_USER_AGENT = "CORE-home-observer/1.0"


def _bucket(value: float, thresholds: tuple[float, ...], labels: tuple[str, ...]) -> str:
    for threshold, label in zip(thresholds, labels):
        if value < threshold:
            return label
    return labels[-1]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to a previously validated public IP address."""

    def __init__(self, host: str, address: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        raw = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


class HomeWorld:
    """Provide compact home-state features; external access is opt-in and GET-only."""

    def __init__(self, cfg=None, clock=time.monotonic):
        cfg = cfg if isinstance(cfg, dict) else {}
        self._clock = clock
        self.local_refresh_seconds = self._positive_number(
            cfg.get("local_refresh_seconds"), 10.0, maximum=3600.0
        )
        internet = cfg.get("internet")
        internet = internet if isinstance(internet, dict) else {}
        self.internet_enabled = internet.get("enabled") is True
        self.internet_refresh_seconds = self._positive_number(
            internet.get("refresh_seconds"), 3600.0, maximum=86400.0
        )
        self.timeout_seconds = self._positive_number(
            internet.get("timeout_seconds"), 2.0, maximum=5.0
        )
        raw_sites = internet.get("allowlist", [])
        self.allowlist = self._validated_sites(raw_sites) if self.internet_enabled else ()
        if not self.allowlist:
            self.internet_enabled = False

        self._lock = threading.Lock()
        self._local_at = None
        self._local = {}
        self._internet_at = None
        self._internet_results = []
        self._request_in_flight = False

    @staticmethod
    def _positive_number(value, default, maximum):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not 0 < number <= maximum:
            return default
        return number

    @staticmethod
    def _validated_sites(raw_sites):
        if not isinstance(raw_sites, list):
            return ()
        sites = []
        for raw in raw_sites[:_MAX_SITES]:
            if not isinstance(raw, str) or "\r" in raw or "\n" in raw:
                continue
            try:
                parsed = urlsplit(raw)
                host = parsed.hostname
                port = parsed.port
                if (parsed.scheme != "https" or not host
                        or parsed.username or parsed.password
                        or port not in (None, 443)
                        or parsed.path not in ("", "/")
                        or parsed.query or parsed.fragment):
                    continue
            except ValueError:
                continue
            # Only explicit DNS names are accepted; IP literals and local
            # names are never valid external-world entries.
            try:
                ipaddress.ip_address(host)
                continue
            except ValueError:
                pass
            if "." not in host or host.lower() in ("localhost",):
                continue
            sites.append(host.lower())
        return tuple(dict.fromkeys(sites))

    def _local_snapshot(self):
        os_token = "home:os:" + platform.system().lower()
        cpu = os.cpu_count() or 1
        cpu_bucket = _bucket(cpu, (2, 5), ("1", "2-4", "5+"))

        try:
            usage = shutil.disk_usage("/")
            free_ratio = usage.free / usage.total if usage.total else 0.0
            disk_bucket = _bucket(
                free_ratio, (0.05, 0.15), ("critical", "low", "ok")
            )
        except OSError:
            disk_bucket = "unknown"

        memory_total = memory_available = 0
        try:
            with open("/proc/meminfo", encoding="ascii") as f:
                for line in f:
                    key, _, value = line.partition(":")
                    if key in ("MemTotal", "MemAvailable"):
                        amount = int(value.strip().split()[0])
                        if key == "MemTotal":
                            memory_total = amount
                        else:
                            memory_available = amount
        except (OSError, ValueError, IndexError):
            pass
        if memory_total:
            ratio = memory_available / memory_total
            memory_bucket = _bucket(
                ratio, (0.05, 0.15), ("critical", "low", "ok")
            )
        else:
            memory_bucket = "unknown"

        try:
            interface_count = len(socket.if_nameindex())
            interface_bucket = _bucket(
                interface_count, (2, 4), ("1", "2-3", "4+")
            )
        except OSError:
            interface_bucket = "unknown"

        resource_token = "home:resources:%s-d%s-m%s-i%s" % (
            cpu_bucket, disk_bucket, memory_bucket, interface_bucket
        )
        return {
            "tokens": [os_token, resource_token],
            "cpu": cpu,
            "disk": disk_bucket,
            "memory": memory_bucket,
            "interfaces": interface_bucket,
        }

    def _public_address(self, host):
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(item[4][0] for item in addresses))
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError("host_not_public")
        return ips[0]

    def _fetch_site(self, host):
        address = self._public_address(host)
        conn = _PinnedHTTPSConnection(host, address, self.timeout_seconds)
        try:
            conn.request("GET", "/", headers={
                "Host": host,
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                "Connection": "close",
            })
            response = conn.getresponse()
            content_type = response.getheader("Content-Type") or ""
            return {
                "host": host,
                "status": int(response.status),
                "content_type": content_type.split(";", 1)[0][:40],
            }
        finally:
            conn.close()

    def _fetch_sites(self):
        results = []
        try:
            for host in self.allowlist:
                try:
                    results.append(self._fetch_site(host))
                except (OSError, ValueError, http.client.HTTPException,
                        ssl.SSLError) as exc:
                    results.append({"host": host, "error": type(exc).__name__})
        finally:
            with self._lock:
                self._internet_results = results
                self._internet_at = self._clock()
                self._request_in_flight = False

    def _schedule_internet_refresh(self, now):
        with self._lock:
            if (not self.internet_enabled or self._request_in_flight
                    or (self._internet_at is not None
                        and now - self._internet_at < self.internet_refresh_seconds)):
                return
            self._request_in_flight = True
        threading.Thread(
            target=self._fetch_sites,
            name="core-home-internet-observer",
            daemon=True,
        ).start()

    def observe(self):
        """Return cached compact observations; never blocks on external HTTP."""
        now = self._clock()
        if (self._local_at is None
                or now - self._local_at >= self.local_refresh_seconds):
            self._local = self._local_snapshot()
            self._local_at = now

        self._schedule_internet_refresh(now)
        with self._lock:
            results = list(self._internet_results)

        tokens = list(self._local.get("tokens", []))
        if not self.internet_enabled:
            tokens.append("internet:observation:disabled")
        elif not results:
            tokens.append("internet:observation:waiting")
        else:
            responses = [r for r in results if "status" in r]
            tokens.append("internet:observation:reachable" if responses
                          else "internet:observation:unreachable")
            if responses:
                status_classes = sorted({str(r["status"] // 100) + "xx"
                                         for r in responses})
                tokens.append("internet:http:" + "+".join(status_classes))

        return {
            "tokens": tokens,
            "local": dict(self._local),
            "internet": results,
            "internet_enabled": self.internet_enabled,
        }
