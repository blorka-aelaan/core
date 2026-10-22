"""kanit_dongu.py — periyodik öğrenme kanıtı döngüsü (salt okunur).

kanit_ogrenme.py'yi çalıştırır, 5 koşul sonucunu (✓/✗) zaman damgalı
olarak arsiv/kanit_gecmis.jsonl'a ekler. Journal ve brain'a dokunulmaz;
canlı organizma döngüsü etkilenmez. Cron ile 6 saatte bir çağrılır:

    0 */6 * * * cd /home/emrah/Genel/core && python3 kanit_dongu.py

Çıktı sonucu ayrıca stdout'a basılır (cron logu /tmp/kanit_dongu.log).
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

KOK = Path(__file__).resolve().parent
GECMIS = KOK / "arsiv" / "kanit_gecmis.jsonl"


def calistir():
    bas = time.time()
    r = subprocess.run(
        [sys.executable, str(KOK / "kanit_ogrenme.py"), "--plasebo", "25"],
        capture_output=True, text=True, errors="replace",
        cwd=str(KOK), timeout=1800)
    cikti = r.stdout or ""
    kosullar = {}
    for m in re.finditer(r"\[(✓|✗)\]\s*([^:]+):", cikti):
        kosullar[m.group(2).strip()] = (m.group(1) == "✓")
    return {"t": round(bas, 1), "sure_sn": round(time.time() - bas, 1),
            "rc": r.returncode, "kosullar": kosullar,
            "gecen": sum(1 for v in kosullar.values() if v),
            "toplam": len(kosullar)}


def main():
    try:
        kayit = calistir()
    except (subprocess.TimeoutExpired, OSError) as e:
        kayit = {"t": round(time.time(), 1), "hata": str(e)[:200]}
    GECMIS.parent.mkdir(exist_ok=True)
    with open(GECMIS, "a", encoding="utf-8") as f:
        f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    print(json.dumps(kayit, ensure_ascii=False))
    return 0 if kayit.get("rc", 1) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())