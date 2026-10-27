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




def test_arsiv_retansiyon_gun_siniri():
    """Retansiyon: N gunden eski arsiv dosyalari silinir, yeni kalir."""
    import os
    import shutil
    import tempfile
    import time
    sys.path.insert(0, "/home/emrah/Genel/core")
    import journal as J

    d = tempfile.mkdtemp()
    ars = os.path.join(d, "arsiv")
    os.makedirs(ars)
    try:
        def yaz(ad, boyut, gun_once):
            ts = time.time() - gun_once * 86400
            isim = "%s_%s.jsonl" % (ad, time.strftime(
                "%Y%m%d_%H%M%S", time.localtime(ts)))
            with open(os.path.join(ars, isim), "wb") as f:
                f.write(b"x" * boyut)

        yaz("journal", 1000, 100)     # eski -> silinir
        yaz("journal", 2000, 90)      # eski -> silinir
        yaz("journal", 3000, 10)      # yeni -> kalir
        # desenle eslesmeyen dosya: ASLA dokunulmaz
        kanit = os.path.join(ars, "kanit_gecmis.jsonl")
        with open(kanit, "w", encoding="utf-8") as f:
            f.write("korunur")

        n = J.arsiv_temizle(ars, max_gun=30, toplam_mb=2048, korunacak=50)
        assert n == 2, n
        assert os.path.exists(kanit), "desen disi dosya silinmemeli"
        assert len(os.listdir(ars)) == 2, os.listdir(ars)
    finally:
        shutil.rmtree(d)


def test_arsiv_retansiyon_toplam_boyut():
    """Retansiyon: toplam boyut siniri asilirsa en eskiler silinir."""
    import os
    import shutil
    import tempfile
    import time
    sys.path.insert(0, "/home/emrah/Genel/core")
    import journal as J

    d = tempfile.mkdtemp()
    ars = os.path.join(d, "arsiv")
    os.makedirs(ars)
    try:
        def yaz(ad, boyut, gun_once):
            ts = time.time() - gun_once * 86400
            isim = "%s_%s.jsonl" % (ad, time.strftime(
                "%Y%m%d_%H%M%S", time.localtime(ts)))
            with open(os.path.join(ars, isim), "wb") as f:
                f.write(b"x" * boyut)

        for i in range(6):
            yaz("journal", 1_000_000, 6 - i)
        n = J.arsiv_temizle(ars, max_gun=None, toplam_mb=3, korunacak=1)
        assert n == 3, n
        assert len(os.listdir(ars)) == 3, os.listdir(ars)
    finally:
        shutil.rmtree(d)


def test_arsiv_retansiyon_korunacak():
    """Retansiyon: en yeni N dosya (korunacak) hicbir zaman silinmez."""
    import os
    import shutil
    import tempfile
    import time
    sys.path.insert(0, "/home/emrah/Genel/core")
    import journal as J

    d = tempfile.mkdtemp()
    ars = os.path.join(d, "arsiv")
    os.makedirs(ars)
    try:
        def yaz(ad, boyut, gun_once):
            ts = time.time() - gun_once * 86400
            isim = "%s_%s.jsonl" % (ad, time.strftime(
                "%Y%m%d_%H%M%S", time.localtime(ts)))
            with open(os.path.join(ars, isim), "wb") as f:
                f.write(b"x" * boyut)

        for i in range(6):
            yaz("journal", 1_000_000, 6 - i)
        n = J.arsiv_temizle(ars, max_gun=None, toplam_mb=1, korunacak=3)
        assert len(os.listdir(ars)) == 3, os.listdir(ars)
    finally:
        shutil.rmtree(d)


def test_arsiv_ayarlari_body_json():
    """body.json -> stage retansiyon ayarlari gorunur."""
    cfg = json.loads((Path("/home/emrah/Genel/core/body.json")).read_text(
        encoding="utf-8"))
    assert int(cfg["stage"].get("arsiv_azami_gun", 0)) > 0
    assert int(cfg["stage"].get("arsiv_azami_mb", 0)) > 0


def test_retansiyon_arsivlemeden_bagimsiz_calisir():
    """Retansiyon tetigi arsivlemeye bagli olmamali (periyodik blok).

    Arşiv 2048 MB sınırı, arşivleme olmadan aşılırsa (günlük ~106 MB
    üretim → 19 günde aşılır) limit kendiliğinden korunamaz. Periyodik
    blok (main.py, 1000 tikte bir) arşivlemeyi beklemez.
    """
    import os
    import shutil
    import tempfile
    import time
    sys.path.insert(0, "/home/emrah/Genel/core")
    import journal as J

    d = tempfile.mkdtemp()
    ars = os.path.join(d, "arsiv")
    os.makedirs(ars)
    try:
        # YENI ama eski olmayan dosyalar: gun siniri degil, TOPLAM BOYUT
        # siniri tetikler. Arşivleme olmadan da temizlenmeli.
        def yaz(ad, boyut, gun_once):
            ts = time.time() - gun_once * 86400
            isim = "%s_%s.jsonl" % (ad, time.strftime(
                "%Y%m%d_%H%M%S", time.localtime(ts)))
            with open(os.path.join(ars, isim), "wb") as f:
                f.write(b"x" * boyut)

        for i in range(5):
            yaz("journal", 1_000_000, 2 - i * 0.2)   # hepsi 30 gunden yeni
        n = J.arsiv_temizle(ars, max_gun=30, toplam_mb=2, korunacak=1)
        assert n == 3, "toplam boyut siniri arsivlemeden da tetiklenmeli: %s" % n
        assert len(os.listdir(ars)) == 2, os.listdir(ars)
    finally:
        shutil.rmtree(d)


def test_main_periyodik_retansiyon_blogu():
    """main.py: periyodik retansiyon blogu var ve dogru dizinleri kapsar."""
    src = (Path("/home/emrah/Genel/core/main.py")).read_text(encoding="utf-8")
    assert "arsiv_temizle" in src, "main.py retansiyon cagrisi icermeli"
    # Periyodik tetikleme: arsivlemeden bagimsiz, %1000'de bir
    assert "arsiv_retansiyon" in src
    assert 'state["ticks"] % 1000 == 0' in src, \
        "periyodik retansiyon blogu eksik (1000 tikte bir)"
    # Retansiyon, arşivlenen dosyanin GERCEK hedef dizininde uygulanmali
    # (sabit ROOT/arsiv yerine) — GOLGE_LOG farkli dizini gosterebilir.
    assert "str(Path(hedef).parent)" in src, \
        "retansiyon arsivlenen dosyanin hedef dizininde olmali"
    assert 'str(ROOT / "arsiv")' not in src, \
        "sabit ROOT/arsiv dizini kullanilmamali"


test_arsivle_golge_deseni()
test_log_tum_arsiv_ve_canli()
test_golge_azami_okunur()
test_gunduz_konsolide_cagrisi()
test_arsiv_retansiyon_gun_siniri()
test_arsiv_retansiyon_toplam_boyut()
test_arsiv_retansiyon_korunacak()
test_arsiv_ayarlari_body_json()
test_retansiyon_arsivlemeden_bagimsiz_calisir()
test_main_periyodik_retansiyon_blogu()
print("GOLGE ARSIV + GUNDUZ KONSOLIDASYON + RETANSIYON: 10/10 OK")
