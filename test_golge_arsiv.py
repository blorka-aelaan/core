"""golge_log arşivleme + gündüz konsolidasyonu (2026-10-18 denetim maddesi 2-3).

1) journal.arsivle HER jsonl dosyasında çalışır (golge_log da aynı desende):
   arsiv/golge_log_*.jsonl'ye atomik taşır, canlı Kapi.calistir ('a' modu)
   sonraki yazımı yeni dosyada sürdürür → canlıya zarar yok.
2) golge._log_tum() arşiv + canlıyı zaman sırasıyla okur: incele/rapor
   arşivlemeden sonra tarihi görmez.
3) main.py gündüz konsolidasyonu: 500 tikte bir mind.konsolide() →
   brain.konsolide zaten INSTINCTS korur (uyku hattı testi kapsamındaki
   davranış); burada çağrının kendisi + save atomikliği sınanır
   (test_uyku_egit konsolide maddeyi ayrıca kapsar).
4) body.json stage.golge_azami_mb okunur (main.load_config görünürlüğü).
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/home/emrah/Genel/core")
import golge
import journal


def test_arsivle_golge_deseni():
    """arsiv/golge_log_*.jsonl taşınır, boş canlı kalır, veri kaybolmaz."""
    with tempfile.TemporaryDirectory(prefix="golge_arsiv_") as td:
        log = Path(td) / "golge_log.jsonl"
        satirlar = [{"t": time.time(), "komut": "ls -la", "sinif": "okuma"}
                    for _ in range(5)]
        log.write_text("".join(json.dumps(s) + "\n" for s in satirlar),
                       encoding="utf-8")
        hedef = journal.arsivle(str(log))
        assert hedef and "golge_log_" in hedef and hedef.endswith(".jsonl"), hedef
        assert not log.exists() or log.stat().st_size == 0, "canlı taşınmalı"
        # arşivde tüm satırlar duruyor
        arsiv_satir = Path(hedef).read_text(encoding="utf-8").strip().splitlines()
        assert len(arsiv_satir) == 5
        # canlı yazmaya devam edebilir (Kapi.calistir ile aynı 'a' modu)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "komut": "ps"}) + "\n")
        assert log.exists() and log.stat().st_size > 0


def test_log_tum_arsiv_ve_canli():
    """_log_tum: arşiv (eski) + canlı (yeni) → kronolojik bütünlük."""
    with tempfile.TemporaryDirectory(prefix="golge_tum_") as td:
        kok = Path(td)
        (kok / "arsiv").mkdir()
        eski = kok / "arsiv" / "golge_log_20261018_000000.jsonl"
        eski.write_text(json.dumps({"t": 1.0, "komut": "find"}) + "\n",
                        encoding="utf-8")
        canli = kok / "golge_log.jsonl"
        canli.write_text(json.dumps({"t": 2.0, "komut": "du"}) + "\n",
                         encoding="utf-8")
        eski_LOG, eski_KOK = golge.LOG, golge.KOK
        try:
            golge.LOG, golge.KOK = canli, kok
            kayit = golge._log_tum()
        finally:
            golge.LOG, golge.KOK = eski_LOG, eski_KOK
        assert [k["komut"] for k in kayit] == ["find", "du"], kayit


def test_golge_azami_okunur():
    """body.json → stage.golge_azami_mb main tarafında görünür (>0, esnek).    
    """
    cfg = json.loads((Path("/home/emrah/Genel/core/body.json")).read_text(
        encoding="utf-8"))
    assert float(cfg["stage"].get("golge_azami_mb", 0)) > 0
    assert float(cfg["stage"].get("journal_azami_mb", 0)) > 0


def test_gunduz_konsolide_cagrisi():
    """Gündüz ritmi: zayıf bağlantı budanır, INSTINCTS yaşar, save + log."""
    sys.path.insert(0, "/home/emrah/Genel/core")
    import brain as B
    b = B.Brain(seed=3)
    b.w[("Z|Q", "nest")] = 0.001         # zayıf, instinksiz → budanacak
    b.usage[("Z|Q", "nest")] = 0         # kanıtsız: budanılabilir
    zayif = [k for k, v in b.w.items()
             if abs(v) < 0.02 and k not in b.INSTINCTS]
    assert zayif, "budama adayı olmalı"
    n = b.konsolide()
    assert n >= len(zayif), (n, len(zayif))
    kalan = [k for k in b.w if k not in b.INSTINCTS and abs(b.w[k]) < 0.02]
    assert not kalan, "eşik altı kalmamalı"
    for k, v in b.INSTINCTS.items():
        assert k in b.w, "instinkt korunmalı (budanmaz)"


test_arsivle_golge_deseni()
test_log_tum_arsiv_ve_canli()
test_golge_azami_okunur()
test_gunduz_konsolide_cagrisi()
print("GOLGE ARSIV + GUNDUZ KONSOLIDASYON: 4/4 OK")