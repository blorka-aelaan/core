"""CORE journal — şeffaflık katmanı.

Organizmanın gördüğü her uyaran, verdiği her karar ve yediği her enerji
append-only bir günlüğe yazılır. Gözlem asla organizmaya karışmaz.
"""
import json
import time
from pathlib import Path


class Journal:
    def __init__(self, path, quiet=False):
        self.path = str(path)
        self.quiet = quiet

    def log(self, kind, **data):
        rec = {"t": round(time.time(), 3), "kind": kind}
        rec.update(data)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if not self.quiet:
            stamp = time.strftime("%H:%M:%S")
            print("[%s] %-8s %s" % (stamp, kind, _brief(data)), flush=True)


def _brief(data, limit=220):
    text = json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def replay(path):
    """Günlüğü baştan oynat: python3 journal.py replay [journal.jsonl]"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                stamp = time.strftime("%H:%M:%S", time.localtime(rec["t"]))
                kind = rec.pop("kind", "?")
                rec.pop("t", None)
                print("[%s] %-8s %s" % (stamp, kind, _brief(rec)))
    except FileNotFoundError:
        print("günlük yok:", path)


def arsivle(path="journal.jsonl"):
    """Günlüğü tarihli arşive taşı, yerine boş bırak (aynı disk → atomik).

    Canlı süreç için güvenli: Journal.log dosyayı her çağrıda 'a' modunda
    yeniden açar; taşımadan sonraki ilk yazı yeni günlüğü yaratır.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return None
    d = p.parent / "arsiv"
    d.mkdir(exist_ok=True)
    hedef = d / ("%s_%s.jsonl" % (p.stem,
                                  time.strftime("%Y%m%d_%H%M%S")))
    p.replace(hedef)
    return str(hedef)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        replay(sys.argv[2] if len(sys.argv) > 2 else "journal.jsonl")
    elif len(sys.argv) > 1 and sys.argv[1] == "arsivle":
        hedef = arsivle(sys.argv[2] if len(sys.argv) > 2
                        else "journal.jsonl")
        print("arşivlendi → %s" % hedef if hedef else "günlük boş/yok")
    else:
        print("kullanım: python3 journal.py replay|arsivle [journal.jsonl]")