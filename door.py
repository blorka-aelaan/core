"""CORE door — ev kapısı.

Organizma yerel bir sokette dinler; içeri gelen her paket "kapı çalmadır".
Gelen mesaj uyaran olur, organizma durumunu yanıtlar.

  python3 door.py send "merhaba"   # kapıyı çal
  python3 door.py watch            # günlüğü canlı izle
"""
import json
import socket
import threading
import time


class Door:
    def __init__(self, host, port, status_fn, queue, journal):
        self.host = host
        self.port = port
        self.status_fn = status_fn
        self.queue = queue
        self.journal = journal
        self._stop = threading.Event()
        self._sock = None
        self._thread = None

    def start(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self.host, self.port))
            self._sock.listen(5)
            self._sock.settimeout(0.5)
        except OSError as e:
            # kapı açılamazsa organizma yine yaşar; kapı yok diye ölmez
            self._sock = None
            self.journal.log("door_error", note=str(e))
            return
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.journal.log("door_open", addr="%s:%d" % (self.host, self.port))

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                conn.settimeout(3)
                data = conn.recv(4096).decode("utf-8", "replace").strip()
                if data:
                    self.queue.put(data[:500])
                    reply = json.dumps(self.status_fn(),
                                       ensure_ascii=False) + "\n"
                    conn.sendall(reply.encode("utf-8"))
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass


def send(host, port, message):
    s = socket.create_connection((host, port), timeout=3)
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
                    if rec.get("kind") in ("door", "act", "birth", "death"):
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


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "send":
        msg = " ".join(sys.argv[2:]) or "selam"
        print(send("127.0.0.1", 5777, msg))
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
    else:
        print('kullanım: python3 door.py send "mesaj" | shock 50 | '
              'gorev kutular | ac | watch')