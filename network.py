"""CORE network — dışa yönlü ağ istemcisi.

Organizmanın dış sunuculara bağlanması, mesaj göndermesi,
heartbeat/keepalive ve otomatik yeniden bağlanmayı sağlar.
"""
import json
import socket
import threading
import time
from collections import deque


class NetworkClient:
    """TCP istemci: otomatik yeniden bağlanma, heartbeat ve kuyruk."""

    def __init__(self, host, port, queue, journal,
                 token=None, reconnect_interval=5.0,
                 heartbeat_interval=30.0, timeout=5.0,
                 max_reconnects=0):
        self.host = host
        self.port = int(port)
        self.queue = queue
        self.journal = journal
        self.token = token
        self.reconnect_interval = reconnect_interval
        self.heartbeat_interval = heartbeat_interval
        self.timeout = timeout
        self.max_reconnects = max_reconnects

        self._stop = threading.Event()
        self._sock = None
        self._lock = threading.Lock()
        self._send_q = deque()
        self._send_lock = threading.Lock()
        self._recv_thread = None
        self._send_thread = None
        self._hb_thread = None
        self._reconnect_count = 0
        self._connected = False
        self._stats = {
            "connects": 0,
            "disconnects": 0,
            "sent": 0,
            "received": 0,
            "bytes_out": 0,
            "bytes_in": 0,
            "errors": 0,
        }

    # --------------------------------------------------------------- başlat
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.journal.log("network_start", host=self.host, port=self.port)

    def _run(self):
        while not self._stop.is_set():
            if self._connect():
                self._start_workers()
                self._wait_until_disconnect()
                self._stop_workers()
                self._disconnect()
                if self._stop.is_set():
                    break
                if self.max_reconnects > 0 and \
                        self._reconnect_count >= self.max_reconnects:
                    self.journal.log("network_max_reconnects",
                                     count=self._reconnect_count)
                    break
                self._reconnect_count += 1
                self.journal.log("network_reconnect",
                                 attempt=self._reconnect_count,
                                 interval=self.reconnect_interval)
                self._stop.wait(self.reconnect_interval)
            else:
                if self._stop.is_set():
                    break
                self._stop.wait(self.reconnect_interval)

    def _connect(self):
        try:
            sock = socket.create_connection((self.host, self.port),
                                            timeout=self.timeout)
            sock.settimeout(self.timeout)
            with self._lock:
                self._sock = sock
                self._connected = True
            self._stats["connects"] += 1
            self.journal.log("network_connect", host=self.host,
                             port=self.port)
            if self.token:
                self.send({"type": "auth", "token": self.token})
            return True
        except OSError as e:
            with self._lock:
                self._stats["errors"] += 1
            self.journal.log("network_connect_error", note=str(e))
            return False

    def _start_workers(self):
        self._recv_thread = threading.Thread(target=self._recv_loop,
                                             daemon=True)
        self._send_thread = threading.Thread(target=self._send_loop,
                                             daemon=True)
        self._hb_thread = threading.Thread(target=self._heartbeat_loop,
                                           daemon=True)
        self._recv_thread.start()
        self._send_thread.start()
        self._hb_thread.start()

    def _stop_workers(self):
        pass

    def _wait_until_disconnect(self):
        while self._connected and not self._stop.is_set():
            self._stop.wait(0.5)

    def _disconnect(self):
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self._connected = False
        self._stats["disconnects"] += 1
        self.journal.log("network_disconnect", host=self.host,
                         port=self.port)

    # --------------------------------------------------------------- gönderme
    def send(self, obj):
        """JSON-serializabilir bir nesneyi kuyruğa ekler ve göndermeye çalışır."""
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        with self._send_lock:
            self._send_q.append(line)
        self._try_send()

    def _try_send(self):
        with self._send_lock:
            while self._send_q and self._connected:
                line = self._send_q.popleft()
                try:
                    data = line.encode("utf-8")
                    with self._lock:
                        if self._sock:
                            self._sock.sendall(data)
                            self._stats["sent"] += 1
                            self._stats["bytes_out"] += len(data)
                except OSError:
                    with self._lock:
                        self._stats["errors"] += 1
                        self._connected = False
                    break

    # --------------------------------------------------------------- döngüler
    def _recv_loop(self):
        buf = ""
        while self._connected and not self._stop.is_set():
            try:
                with self._lock:
                    sock = self._sock
                if sock is None:
                    break
                data = sock.recv(4096)
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
                try:
                    obj = json.loads(line)
                except ValueError:
                    obj = {"type": "raw", "payload": line}
                with self._lock:
                    self._stats["received"] += 1
                self.queue.put(("network_inbox", obj))
                self.journal.log("network_inbox", msg=str(obj)[:500])
        with self._lock:
            self._connected = False

    def _send_loop(self):
        while self._connected and not self._stop.is_set():
            self._try_send()
            self._stop.wait(0.1)

    def _heartbeat_loop(self):
        while self._connected and not self._stop.is_set():
            self._stop.wait(self.heartbeat_interval)
            if self._connected and not self._stop.is_set():
                self.send({"type": "ping", "ts": time.time()})

    # --------------------------------------------------------------- dışa görünen API
    def stop(self):
        self._stop.set()
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None
            self._connected = False

    def stats(self):
        with self._lock:
            return dict(self._stats, connected=self._connected,
                        reconnects=self._reconnect_count,
                        queue_len=len(self._send_q))


def send_once(host, port, obj, token=None, timeout=5.0):
    """Tek bir mesaj gönderip bağlantıyı kapatır."""
    try:
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.settimeout(timeout)
        if token:
            s.sendall((json.dumps({"type": "auth", "token": token}) + "\n").encode("utf-8"))
            s.recv(4096)
        s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
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
    except OSError as e:
        return json.dumps({"type": "error", "error": str(e)})