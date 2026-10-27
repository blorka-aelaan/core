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


# ---------- arşiv rotasyonu ve retansiyonu ----------
#
# SORUN (ölçülen 2026-10-22): arsiv/ 1,9 GB'a ve 1725 dosyaya çıktı;
# günlük üretim ~142 MB -> yillik ~50 GB. Rotasyon (yeni dosya acma)
# vardi ama RETANSYON (eskiyi silme) yoktu -> disk sonsuza dek dolar.
#
# POLITIKA:
#   * dosya bazli: max_gun gunden eski dosyalar silinir
#   * toplam bazli: toplam boyut toplam_mb ustune cikarsa en eski
#     dosyalar silinir (tarih sirasi gore)
#   * asla: canli dosya (journal.jsonl, golge_log.jsonl) silinmez
#   * korunur: en az korunacak dosya (yeniler) saklanir
import re

# Arsiv dosya adi deseni: <ad>_<YYYYMMDD>_<HHMMSS>.jsonl
ARSIV_AD_DESEN = re.compile(
    r"^(?P<ad>.+)_(?P<tarih>\d{8})_(?P<saat>\d{6})\.jsonl$")


def arsiv_temizle(dizin="arsiv", max_gun=30, toplam_mb=2048,
                  korunacak=50, simdi=None):
    """Arsivdeki eski dosyalari sil (retansiyon). Doner: silinen sayisi.

    max_gun: bu gunden eski dosyalar silinir (None -> kapali)
    toplam_mb: toplam arsiv boyutu siniri (None -> kapali)
    korunacak: en az bu kadar dosya SAKLANIR (yeniler silinmez)
    """
    d = Path(dizin)
    if not d.exists():
        return 0
    now = simdi or time.time()
    dosyalar = []
    for f in d.iterdir():
        if not f.is_file():
            continue
        m = ARSIV_AD_DESEN.match(f.name)
        if not m:
            continue                       # taninmayan dosya: dokunma
        try:
            ts = time.mktime(time.strptime(
                m.group("tarih") + m.group("saat"), "%Y%m%d%H%M%S"))
        except ValueError:
            continue
        dosyalar.append((ts, f, f.stat().st_size))
    if not dosyalar:
        return 0
    dosyalar.sort(key=lambda t: t[0])       # en eski once

    silinecek = set()

    # 1) Gun siniri
    if max_gun:
        esik = now - max_gun * 86400
        for ts, f, _sz in dosyalar:
            if ts < esik:
                silinecek.add(f)

    # 2) Toplam boyut siniri (silinecekler haric kalani hesapla)
    if toplam_mb:
        limit = toplam_mb * 1e6
        kalan = [(ts, f, sz) for ts, f, sz in dosyalar if f not in silinecek]
        toplam = sum(sz for _t, _f, sz in kalan)
        # korunacak sayisi: en yeni N dosya asla silinmez
        en_yeni = {f for _t, f, _s in kalan[-korunacak:]} if korunacak else set()
        for ts, f, sz in kalan:
            if toplam <= limit:
                break
            if f in en_yeni:
                continue
            silinecek.add(f)
            toplam -= sz

    silinen = 0
    for f in silinecek:
        try:
            f.unlink()
            silinen += 1
        except OSError:
            pass
    return silinen


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        replay(sys.argv[2] if len(sys.argv) > 2 else "journal.jsonl")
    elif len(sys.argv) > 1 and sys.argv[1] == "arsivle":
        hedef = arsivle(sys.argv[2] if len(sys.argv) > 2
                        else "journal.jsonl")
        print("arşivlendi → %s" % hedef if hedef else "günlük boş/yok")
    elif len(sys.argv) > 1 and sys.argv[1] == "temizle":
        # Retansiyon: arsivdeki eski dosyalari sil.
        dizin = sys.argv[2] if len(sys.argv) > 2 else "arsiv"
        max_gun = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        toplam_mb = int(sys.argv[4]) if len(sys.argv) > 4 else 2048
        n = arsiv_temizle(dizin, max_gun=max_gun, toplam_mb=toplam_mb)
        print("silinen arşiv dosyası: %d" % n)
    else:
        print("kullanım: python3 journal.py replay|arsivle|temizle [journal.jsonl]")
