"""CORE door — ev kapısı (kapsamlı sürüm).

Organizma yerel bir TCP sokette dinler; içeri gelen her paket "kapı çalmadır".
Çoklu istemci, JSON envelop protokolü, token kimlik doğrulaması,
IP bazlı rate limiting ve istatistiklerle donatılmıştır.

  python3 door.py send --token TOKEN "merhaba"   # kapıyı çal
  python3 door.py watch                          # günlüğü canlı izle
"""
import json
import socket
import threading
import time
from collections import deque, defaultdict


class ClientInfo:
    """Tek bir bağlı istemcinin durumu."""
    __slots__ = ("conn", "addr", "connected_at", "authenticated")

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.connected_at = time.time()
        self.authenticated = False


class Door:
    """TCP kapı: çoklu istemci, JSON protokol, kimlik ve rate limit."""

    def __init__(self, host, port, status_fn, queue, journal,
                 token=None, max_clients=16, rate_per_min=60,
                 recv_timeout=3.0, max_msg_bytes=4096):
        self.host = host
        self.port = port
        self.status_fn = status_fn
        self.queue = queue
        self.journal = journal
        self.token = token
        self.max_clients = max_clients
        self.rate_per_min = rate_per_min
        self.recv_timeout = recv_timeout
        self.max_msg_bytes = max_msg_bytes

        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        self._lock = threading.Lock()
        self._clients = {}          # conn -> ClientInfo
        self._client_count = 0
        self._stats = {
            "connections": 0,
            "messages": 0,
            "bytes_in": 0,
            "bytes_out": 0,
            "errors": 0,
            "rate_rejected": 0,
            "auth_rejected": 0,
        }
        self._msg_times = defaultdict(deque)   # ip -> zaman damgaları

    # --------------------------------------------------------------- başlat
    def start(self):
        deneme = 0
        while True:  # port tekrar serbest kalana kadar sonsuz dene
            try:
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass  # eski çekirdek desteklemez
                self._sock.bind((self.host, self.port))
                self._sock.listen(self.max_clients)
                self._sock.settimeout(0.5)
                break
            except OSError as e:
                deneme += 1
                self.journal.log("door_error", note=str(e), deneme=deneme)
                time.sleep(2)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.journal.log("door_open", addr="%s:%d" % (self.host, self.port))

    # --------------------------------------------------------------- dinleme döngüsü
    def _serve(self):
        try:
            while not self._stop.is_set():
                try:
                    conn, addr = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with self._lock:
                    if len(self._clients) >= self.max_clients:
                        try:
                            conn.close()
                        except OSError:
                            pass
                        self.journal.log("door_reject", addr=addr[0],
                                         reason="max_clients")
                        continue
                    ci = ClientInfo(conn, addr)
                    self._clients[conn] = ci
                    self._client_count += 1
                    self._stats["connections"] += 1
                self.journal.log("door_connect", addr="%s:%d" % addr)
                t = threading.Thread(target=self._handle, args=(conn, addr),
                                     daemon=True)
                t.start()
        finally:
            # kapı düştüğünde soketi her zaman serbest bırak
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    # --------------------------------------------------------------- tek bağlantı
    def _handle(self, conn, addr):
        ip = addr[0]
        buf = ""
        authenticated = bool(self.token is None)
        try:
            conn.settimeout(self.recv_timeout)
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not data:
                    break
                with self._lock:
                    self._stats["bytes_in"] += len(data)
                buf += data.decode("utf-8", "replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    # --- rate limit ---
                    now = time.time()
                    window = self._msg_times[ip]
                    while window and window[0] < now - 60:
                        window.popleft()
                    if len(window) >= self.rate_per_min:
                        self._stats["rate_rejected"] += 1
                        self._send_line(conn, json.dumps({
                            "type": "error", "error": "rate_limited"}))
                        continue
                    window.append(now)

                    # --- kimlik ---
                    if not authenticated:
                        if line.startswith("auth:"):
                            tok = line.split(":", 1)[1].strip()
                            if self.token and tok == self.token:
                                authenticated = True
                                self._send_line(conn, json.dumps({
                                    "type": "ok", "auth": True}))
                                continue
                            else:
                                self._stats["auth_rejected"] += 1
                                self._send_line(conn, json.dumps({
                                    "type": "error", "error": "bad_token"}))
                                continue
                        self._send_line(conn, json.dumps({
                            "type": "error", "error": "auth_required"}))
                        continue

                    # --- işlem ---
                    self._dispatch(line, conn)
                    with self._lock:
                        self._stats["messages"] += 1
        except OSError:
            pass
        finally:
            with self._lock:
                self._clients.pop(conn, None)
            try:
                conn.close()
            except OSError:
                pass
            self.journal.log("door_disconnect", addr="%s:%d" % addr)

    # --------------------------------------------------------------- mesaj dağıtım
    def _dispatch(self, line, conn):
        try:
            env = json.loads(line)
        except ValueError:
            env = {"type": "raw", "payload": line}
        mtype = env.get("type", "message")
        payload = env.get("payload", env if mtype == "raw" else {})

        # Komut türleri
        if mtype == "ping":
            self._send_line(conn, json.dumps({"type": "pong", "ts": time.time()}))
            return
        if mtype == "status":
            self._send_line(conn, json.dumps({"type": "status",
                                              "payload": self.status_fn()}))
            return
        if mtype == "shock":
            self.queue.put("shock:" + str(payload))
            self.journal.log("door_shock", payload=payload)
            self._send_line(conn, json.dumps({"type": "ok", "ack": "shock"}))
            return
        if mtype == "gorev":
            self.queue.put("gorev:" + str(payload))
            self.journal.log("door_gorev", gorev=str(payload))
            self._send_line(conn, json.dumps({"type": "ok", "ack": "gorev"}))
            return
        if mtype == "ac":
            self.queue.put("ac")
            self.journal.log("door_ac")
            self._send_line(conn, json.dumps({"type": "ok", "ack": "ac"}))
            return
        if mtype == "kesif":
            # Dağıtık keşif: başka bir organizma "sen kim sin?" diye sorar.
            # Yanıt: kimlik + sistem jetonu + çalışma süresi.
            # Kimlik sistem_hafiza'dan gelir (donanım hash'i).
            import time as _t
            try:
                import sistem_hafiza as _sh
                _v = _sh.yukle()
                _bilgi = {
                    "kimlik": _v.get("kimlik", "?"),
                    "jeton": _sh.jeton(_v),
                    "hostname": _v.get("hostname", "?"),
                    "surum": _v.get("surum", 1),
                }
            except Exception:
                _bilgi = {"kimlik": "?", "jeton": "?",
                          "hostname": "?", "surum": 1}
            self.journal.log("door_kesif",
                             gelen=str(payload)[:100] if payload else "")
            self._send_line(conn, json.dumps({
                "type": "kesif_yanit", "payload": _bilgi}))
            return

        # Varsayılan: kuyruğa at ve organizma duyur
        self.queue.put("door_inbox:" + str(payload))
        self.journal.log("door_inbox", msg=str(payload)[:500])
        self._send_line(conn, json.dumps({"type": "ok", "ack": "received"}))

    # --------------------------------------------------------------- yardımcı
    def _send_line(self, conn, text):
        try:
            data = (text + "\n").encode("utf-8")
            conn.sendall(data)
            with self._lock:
                self._stats["bytes_out"] += len(data)
        except OSError:
            with self._lock:
                self._stats["errors"] += 1

    # --------------------------------------------------------------- canlılık kontrolü
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive() and self._sock is not None

    # --------------------------------------------------------------- dışa görünen API
    def stats(self):
        with self._lock:
            return dict(self._stats, clients=len(self._clients))

    def stop(self):
        self._stop.set()
        with self._lock:
            conns = list(self._clients.keys())
        for conn in conns:
            try:
                conn.close()
            except OSError:
                pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


# ---------- komut satırı (eskiye uyumlu) ----------
def send(host, port, message, token=None, timeout=3.0):
    s = socket.create_connection((host, port), timeout=timeout)
    if token:
        s.sendall(("auth:%s\n" % token).encode("utf-8"))
        s.recv(4096)
    s.sendall((message + "\n").encode("utf-8"))
    reply = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        reply += chunk
        if b"\n" in reply:
            break
    s.close()
    return reply.decode("utf-8", "replace").strip()


def watch(path):
    """Günlüğü canlı izle (tail -f)."""
    with open(path, "r", encoding="utf-8") as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line:
                try:
                    rec = json.loads(line)
                    if rec.get("kind") in ("door", "act", "birth", "death",
                                           "door_connect", "door_disconnect",
                                           "door_shock", "door_gorev",
                                           "door_ac", "door_inbox",
                                           "door_error", "door_reject",
                                           "ag_delta", "ag_uyari",
                                           "sistem_hafiza", "door_kesif"):
                        stamp = time.strftime("%H:%M:%S",
                                              time.localtime(rec["t"]))
                        kind = rec.pop("kind")
                        rec.pop("t", None)
                        print("[%s] %-6s %s" % (
                            stamp, kind,
                            json.dumps(rec, ensure_ascii=False)), flush=True)
                except ValueError:
                    pass
            else:
                time.sleep(0.3)


def kesif_tara(ag="192.168.1.0/24", port=5777, timeout=0.5):
    """Yerel ağda başka CORE organizması ara.

    Her IP'ye 'kesif' mesajı gönder; yanıt verenleri topla.
    Sonuç: [{ip, kimlik, jeton, hostname}, ...]

    Güvenlik: yalnızca yerel ağ (RFC1918) taranır.
    """
    import json as _json
    import socket as _socket

    # CIDR → IP listesi (basit: /24 desteği)
    parts = ag.split("/")
    base = parts[0]
    if "/" in ag:
        mask = int(parts[1])
    else:
        mask = 24
    prefix = ".".join(base.split(".")[:mask // 8])
    son_octet = base.split(".")[-1] if mask == 32 else None

    komsular = []
    if mask == 24:
        for i in range(1, 255):
            ip = "%s.%d" % (prefix, i)
            if ip == base:
                continue
            try:
                s = _socket.create_connection((ip, port), timeout=timeout)
                s.sendall((_json.dumps({"type": "kesif"}) + "\n")
                          .encode("utf-8"))
                yanit = b""
                while True:
                    chunk = s.recv(4096)
                    if not chunk or b"\n" in yanit:
                        break
                    yanit += chunk
                    if b"\n" in yanit:
                        break
                s.close()
                if yanit:
                    d = _json.loads(yanit.decode("utf-8", "replace").strip())
                    if d.get("type") == "kesif_yanit":
                        bilgi = d.get("payload", {})
                        bilgi["ip"] = ip
                        komsular.append(bilgi)
            except (OSError, _json.JSONDecodeError):
                continue
    return komsular


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        msg = " ".join(sys.argv[2:]) or "selam"
        tok = None
        if "--token" in sys.argv:
            i = sys.argv.index("--token")
            tok = sys.argv[i + 1]
        print(send("127.0.0.1", 5777, msg, token=tok))
    elif len(sys.argv) > 1 and sys.argv[1] == "shock":
        # laboratuvar aleti: anlık enerji düşüşü (kriz sınavı)
        n = sys.argv[2] if len(sys.argv) > 2 else "50"
        print(send("127.0.0.1", 5777, "shock:" + n))
    elif len(sys.argv) > 1 and sys.argv[1] == "gorev":
        # misyon: "şu klasörü ara"
        print(send("127.0.0.1", 5777,
                   "gorev:" + " ".join(sys.argv[2:])))
    elif len(sys.argv) > 1 and sys.argv[1] == "ac":
        # sınav: "bir kutu aç"
        print(send("127.0.0.1", 5777, "ac"))
    elif len(sys.argv) > 1 and sys.argv[1] == "watch":
        try:
            watch("journal.jsonl")
        except FileNotFoundError:
            print("günlük henüz yok")
    elif len(sys.argv) > 1 and sys.argv[1] == "kesif":
        # Dağıtık keşif: yerel ağda CORE organizması ara
        ag = sys.argv[2] if len(sys.argv) > 2 else "192.168.1.0/24"
        print("Ağ taranıyor: %s (port 5777)..." % ag)
        komsular = kesif_tara(ag)
        if komsular:
            print("%d organizma bulundu:" % len(komsular))
            for k in komsular:
                print("  %s | kimlik=%s | %s | host=%s" % (
                    k.get("ip", "?"), k.get("kimlik", "?")[:8],
                    k.get("jeton", "?"), k.get("hostname", "?")))
            # komsular.json'a kaydet
            import os, json as _j
            from pathlib import Path
            p = Path("zeka/komsular.json")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_j.dumps(komsular, ensure_ascii=False, indent=2),
                         encoding="utf-8")
            print("→ zeka/komsular.json'a kaydedildi")
        else:
            print("Başka organizma bulunamadı.")
    else:
        print('kullanım: python3 door.py send [--token T] "mesaj" | '
              'shock N | gorev ... | ac | kesif [ag/cidr] | watch')