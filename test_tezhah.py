"""test_tezhah.py — tezgâh/görev organının REGRESYON testleri.

Çalıştır:  python3 test_tezhah.py

Bu dosya bir hatayı kalıcı olarak kapatır: 2026-10-04 23:33'te
gorev.json'daki `hedef` 600→20 düşürüldü; 505 klasör kataloglanmış bir
organizmada `bitti_mi()` bir daha False olmadı ve görev 18 saat boyunca
görünmez biçimde durdu (beyin boşta kalan bir yürüyüşte döngüye girdi).
Testler o tuzağı ve derinleşme davranışını kilitler.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import body as B        # noqa: E402
import gorev as G       # noqa: E402
import journal as J     # noqa: E402
import katalog as K     # noqa: E402

GECTI = []
KALDI = []


def ok(ad, kosul, ayrinti=""):
    (GECTI if kosul else KALDI).append(ad)
    print("  %s %s%s" % ("GECTI " if kosul else "KALDI ", ad,
                         ("  — " + ayrinti) if ayrinti else ""))


# Geçici alan HEP /tmp içinde: çalışma dizininde asla.
GECICI = "/tmp"


def gecici(prefix):
    """Güvenli geçici klasör → /tmp içinde mutlak yol."""
    return Path(tempfile.mkdtemp(prefix=prefix, dir=GECICI))


def temizle_kalanlar():
    """Daha önce sızan tez_* klasörlerini sök → silinen sayı.

    (Kök neden düzeltildi: `world_dir = tmp.name` yalnızca BAŞIN verip
    klasörü proje dizininde yaratıyordu; test ise sadece /tmp'dekini
    siliyordu → her test koşusu bir tez_test_* + 48 KB boş DB bırakıyordu.)
    """
    silinen = 0
    for kok in (ROOT, Path(GECICI)):
        for k in kok.glob("tez_*"):
            if not k.is_dir():
                continue
            try:
                shutil.rmtree(k, ignore_errors=True)
                if not k.exists():
                    silinen += 1
            except OSError:
                pass
    return silinen


def govde(cfg_ek=None, kaynaklar=None, db=None):
    """Gerçek Body (güvenli komut listesi) + Tezgah; geçici world."""
    tmp = gecici("tez_test_")
    cfg = json.loads((ROOT / "body.json").read_text(encoding="utf-8"))
    # TAM YOL şart: `tmp.name` yalnızca son bileşeni verir → Body onu
    # proje dizininde çözer ve test bitince silinemeyen klasör kalır.
    cfg["stage"]["world_dir"] = str(tmp)
    j = J.Journal(str(tmp / "j.log"), quiet=True)
    b = B.Body(cfg, ROOT, j)
    tez = G.Tezgah(dict({"aktif": True, "hedef": 1000, "sure_tik": 10 ** 7,
                         "klasor_siniri": 5, "azami_klasor": 0,
                         "tarama": "duvar", "derinlik": 1,
                         "tazeleme_oran": 0, "odul_enerji": 8}, **(cfg_ek or {})),
                   b, j)
    if kaynaklar is not None:
        tez.cfg["kaynaklar"] = kaynaklar
    if db is not None:
        tez.depo = K.Katalog(db)
        tez.yapilan = tez.depo.yapilanlar()
    return tez, tmp


def agac(kok, dallar):
    for p in dallar:
        d = os.path.join(kok, p)
        os.makedirs(d, exist_ok=True)
        for i in range(2):
            with open(os.path.join(d, "f%d.txt" % i), "w") as f:
                f.write("x" * 32)
    return kok



def test_hedef_tezgahi_kapatmaz():
    """CANLI TUZAK: hedef küçük, katalog büyük → görev sunulmaya devam etmeli."""
    print("\n[1] hedef, tezgâhı kalıcı kapatmamalı")
    tmpd = gecici("tez_agac_")
    kok = agac(str(tmpd / "kok"), ["a", "a/b", "a/b/c", "x"])
    tez, tmp = govde({"hedef": 3}, [kok])          # hedef 3, derinlik 1
    for _ in range(3):
        tez.calistir_bir(0)
    ok("hedef 3 aşıldı", tez.hedef_ulasildi(), "teslim=%d" % tez.teslim)
    ok("hedefe rağmen tezgâh hâlâ sunuluyor", not tez.bitti_mi(),
       "bitti_mi=%s" % tez.bitti_mi())
    r = tez.calistir_bir(0)
    ok("yeni klasör bulundu", "envanter" in r["obs"], r["obs"][:50])
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_derinlesme():
    """Kuyruk boşaldığında görev kapanmamalı, derinleşmeli."""
    print("\n[2] kuyruk boşalınca derinleşme (bitmemeli)")
    tmpd = gecici("tez_derin_")
    kok = agac(str(tmpd / "kok"), ["a", "a/b", "a/b/c", "a/b/c/d", "x", "x/y"])
    tez, tmp = govde({"derinlik": 1, "derinlik_tavan": 6,
                      "arama_deneme": 3}, [kok])
    for _ in range(30):
        tez.calistir_bir(0)
    gercek = {d for d, _, _ in os.walk(kok) if d != kok}
    kalan = gercek - tez.yapilan
    ok("tüm dallar tarandı", not kalan,
       "diskte=%d kataloglanan=%d kalan=%d" % (len(gercek), len(tez.yapilan),
                                               len(kalan)))
    ok("derinleşme gerçekleşti", tez.derinleme > 0,
       "derinleme=%d derinlik=%d" % (tez.derinleme, tez.derinlik))
    ok("tükenince kapandı", tez.tamamlandi and tez.bitti_mi())
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_butce():
    """Bütçe dolunca gerçekten kapanmalı."""
    print("\n[3] bütçe dolunca kapanmalı")
    tmpd = gecici("tez_butce_")
    kok = agac(str(tmpd / "kok"), ["a", "a/b", "a/b/c", "x"])
    tez, tmp = govde({"azami_klasor": 2, "derinlik": 3}, [kok])
    for _ in range(10):
        tez.calistir_bir(0)
        if tez.bitti_mi():
            break
    ok("bütçede kapandı", tez.bitti_mi(), "klasor=%d" % len(tez.yapilan))
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_ayni_klasor_iki_kez_yazilmaz():
    """Tazeleme aynı satırı çoğaltmamalı, sayacı artırmalı."""
    print("\n[4] tazeleme: tekrar satır yok")
    tmpd = gecici("tez_tekrar_")
    kok = agac(str(tmpd / "kok"), ["a", "a/b"])
    tez, tmp = govde({"tazeleme_oran": 1, "derinlik": 4,
                      "derinlik_tavan": 4}, [kok])
    for _ in range(12):
        tez.calistir_bir(0)
    s = tez.depo.istatistik()
    diskte = sum(len([f for f in fs if os.path.isfile(os.path.join(d, f))])
                 for d, _, fs in os.walk(kok))
    ok("klasor satırı = benzersiz",
       s["klasor"] == len(set(tez.depo.yapilanlar())), "klasor=%d" % s["klasor"])
    ok("dosya satırı = diskteki dosya", s["dosya"] == diskte,
       "db=%d disk=%d" % (s["dosya"], diskte))
    ok("tazeleme sayacı arttı", tez.yenilenen > 0,
       "yenilenen=%d" % tez.yenilenen)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_salt_okunur_wal_korur():
    """Salt okunur açılış, çalışan sürecin WAL'ını silmemeli."""
    print("\n[5] salt okunur erişim WAL'ı bozmamalı")
    tmp = gecici("tez_ro_")
    db = str(tmp / "k.db")
    yaz = K.Katalog(db)
    yaz.klasor_yaz("/a", 2, 30)
    yaz.klasor_yaz("/a/b", 1, 10)
    ok("-wal dosyası yazma kipinde var", os.path.exists(db + "-wal"),
       "WAL dosyası beklenen yerde değil")
    ro = K.Katalog(db, salt_okunur=True)
    n = ro.klasor_sayisi()
    ro.kapat()
    ok("salt okunurda -wal yerinde", os.path.exists(db + "-wal"),
       "salt okunur açılış WAL'ı SİLDİ — canlı sürecin verisi kaybolur")
    ok("salt okunur veri gördü", n == 2, "klasor=%d" % n)
    yaz.kapat()
    shutil.rmtree(tmp, ignore_errors=True)


def test_kok_tespiti_ve_kilit():
    """`proje_kok()` bir dizin fazla kaymamalı (sıfırlama kilidi buna bağlı).

    05.10'da kök `Genel/` olarak hesaplanmış, `organizma_yasiyor` hiçbir
    süreç bulamamış ve sıfırlama çalışan organizmanın veritabanını
    arşivlemişti (süreç hâlâ arşivlenmiş inode'a yazıyordu).
    """
    print("\n[6] proje kökü ve sıfırlama kilidi")
    kok = K.proje_kok()
    ok("kök bu dosyanın dizini", kok == str(ROOT), kok)
    ok("kök bir üst dizin DEĞİL", kok != str(ROOT.parent),
       "kötü: %s" % ROOT.parent)
    pid = K.organizma_yasiyor()
    if pid:
        # root süreci: /proc/PID/cwd okunamaz (PermissionError) — ürün kodu
        # bunu yakalar, test de yakalamalı.
        try:
            cwd = os.path.realpath("/proc/%s/cwd" % pid)
        except OSError:
            cwd = None
        if cwd is None:
            ok("root süreç algılandı (cwd okunamıyor ama süreç VAR)", True,
               "pid=%d" % pid)
        else:
            ok("bulunan süreç core dizininde", cwd == str(ROOT),
               "pid=%d cwd=%s" % (pid, cwd))
    else:
        ok("süreç yok (kilit ödünç alınamadı)", True,
           "organizma çalışmıyor — kilit sınanamadı ama kök doğru")
    # sıfırlama, çalışan organizma varken yapılmamalı
    tmp = gecici("tez_kilit_")
    db = str(tmp / "k.db")
    yaz = K.Katalog(db)
    yaz.klasor_yaz("/a", 1, 1)
    yaz.kapat()
    if pid:
        sonuc = K.sifirla(str(tmp))
        ok("çalışan organizma varken sıfırlama reddedildi",
           sonuc["uyari"] is not None and sonuc["arsiv"] is None,
           sonuc["uyari"] or "sessizce yaptı!")
        ok("reddedildiğinde veri yerinde",
           K.Katalog(db).istatistik()["klasor"] == 1)
    else:
        sonuc = K.sifirla(str(tmp), saat="T")
        ok("sıfırlama arşivledi ve boş kurdu",
           sonuc["istatistik"]["klasor"] == 0 and sonuc["arsiv"],
           "arşiv=%s" % sonuc["arsiv"])
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        sutun = [r[1] for r in c.execute("PRAGMA table_info(dosya)")]
        c.close()
        ok("yeni şema Faz3 sütunlarını içeriyor",
           all(s in sutun for s in ("mod", "x", "shebang", "tur")),
           str(sutun))
    yaz2 = K.Katalog(db)
    yaz2.kapat()
    shutil.rmtree(tmp, ignore_errors=True)


def test_stderr_veri_sayilmaz():
    """find stderr'ı YOL sayılmamalı — 05.10'da 27 sahte kayıt böyle girdi.

    `find: '/root': Permission denied` satırları stdout'a karışıp kuyruğa
    giriyor, sonra "klasör" diye kataloglanıyordu: /root, /etc/redis gibi
    dizinler okunmadan "tarandı" sayılıyordu.
    """
    print("\n[7] stderr veri olarak ayrıştırılmamalı")
    if os.geteuid() == 0:
        ok("root olarak atlandı (izin reddi üretilemez)", True)
        return
    tmpd = gecici("tez_stderr_")
    kok = str(tmpd / "kok")
    os.makedirs(os.path.join(kok, "gorunur"))
    os.makedirs(os.path.join(kok, "kilitli"))
    with open(os.path.join(kok, "gorunur", "a.txt"), "w") as f:
        f.write("x" * 10)
    os.chmod(os.path.join(kok, "kilitli"), 0o000)
    tez, tmp = govde({"derinlik": 2, "derinlik_tavan": 2,
                      "klasor_siniri": 10}, [kok])
    liste = tez._duvar_listesi(kok, 10)
    kotu = [y for y in liste if not y.startswith("/") or ":" in y]
    ok("listede stderr satırı yok", not kotu, str(kotu[:2]))
    ok("gerçek klasör listede", any(y.endswith("gorunur") for y in liste),
       str(liste))
    ok("erişilemez kayda geçti", len(tez.erisilemez) > 0,
       "erisilemez=%d" % len(tez.erisilemez))
    # ayrık çağrı: stderr stdout'a karışmamalı.
    # DİKKAT: -maxdepth 1 yeterli DEĞİL — find kilitli dizini listeleyebilir,
    # hata ancak İÇİNE girerken (yani derinleşince) oluşur.
    ok_, out, err = tez.body._calistir(["find", kok, "-type", "d"],
                                        ayrik=True)
    ok("stdout temiz (Permission denied içermiyor)",
       "Permission denied" not in out, out[:60])
    ok("stderr ayrı geldi", "Permission denied" in err, err[:80])
    # katalog: erişilemez, "boş" gibi yazılmamalı
    tez.depo.klasor_yaz(os.path.join(kok, "kilitli"), 0, 0,
                        durum="erisilemez")
    ok("durum=erisilemez saklandı",
       os.path.join(kok, "kilitli") in tez.depo.erisilemezler(),
       str(tez.depo.erisilemezler()))
    # çöp temizliği
    tez.depo.db.execute(
        "INSERT INTO klasor(yol,ad,derinlik,dosya,karakter,ilk,son,sayac,"
        "durum) VALUES(?,?,?,?,?,?,?,1,'ok')",
        ("find: '/root': Permission denied", "x", 0, 0, 0, 0, 0))
    tez.depo.db.commit()
    silinen = tez.depo.supheli_temizle()
    kalan = tez.depo.db.execute(
        "SELECT COUNT(*) FROM klasor WHERE yol NOT LIKE '/%'").fetchone()[0]
    ok("çöp satır temizlendi", silinen == 1 and kalan == 0,
       "silinen=%d kalan=%d" % (silinen, kalan))
    os.chmod(os.path.join(kok, "kilitli"), 0o755)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_prune_dislanan_agac_inmez():
    """Dışlanan ağaç NE çıktığa girer NE de "erişilemez" sayısına.

    Eski kod `-not -path` kullanıyordu: bu yalnızca ÇIKTIYI filtreler, find
    /proc, /sys içine inmeye devam eder → binlerce "Permission denied"
    stderr gürültüsü ve boşa CPU. Doğrusu `-prune` (ağacı hiç inmemek).
    """
    print("\n[8] -prune: dışlanan ağaç inilmez")
    if os.geteuid() == 0:
        ok("root olarak atlandı", True)
        return
    tmpd = gecici("tez_prune_")
    kok = str(tmpd / "kok")
    gizli = str(tmpd / "gizli")
    os.makedirs(os.path.join(kok, "acik"))
    os.makedirs(os.path.join(gizli, "alt"))
    os.chmod(os.path.join(gizli, "alt"), 0o000)   # stderr üretir
    tez, tmp = govde({"derinlik": 5, "derinlik_tavan": 5,
                      "klasor_siniri": 50, "haric": [gizli]}, [kok])
    liste = tez._duvar_listesi(kok, 50)
    sızan = [y for y in liste if y.startswith(gizli)]
    ok("dışlanan ağaç çıkmadı", not sızan, str(sızan[:2]))
    ok("açık klasör çıktı", any(y.endswith("acik") for y in liste),
       str(liste))
    gizli_yok = [y for y in tez.erisilemez if y.startswith(gizli)]
    ok("dışlanan ağaç 'erişilemez' sayılmadı", not gizli_yok,
       str(gizli_yok[:2]))
    os.chmod(os.path.join(gizli, "alt"), 0o755)
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(tmpd, ignore_errors=True)


def test_goc_sonu_carpitar_m():
    """Göç, var olan satırların `son`/`sayac` değerini DEĞİŞTİRMEMELİ.

    `ice_aktar` her doğuşta JSONL'i yeniden okur. Eski davranış tüm
    katalogun `son` değerini "göç zamanı" yapıyordu → alan artık "diskte
    en son ne zaman görüldü" demek olmuyordu, `sayac` da şişiyordu.
    """
    print("\n[9] göç `son`/`sayac` çarpıtmamalı")
    tmp = gecici("tez_goc_")
    db = str(tmp / "k.db")
    envanter = tmp / "envanter.jsonl"
    dosyalar = tmp / "dosyalar.jsonl"

    def saat_dondur(n):
        return lambda: n

    k = K.Katalog(db, saat=saat_dondur(1000.0))   # eski zaman damgası
    k.klasor_yaz("/usr/bin", 900, 4_000_000, durum="ok")
    k.dosya_yaz([("/usr/bin/ls", 140_000, None, "755")])
    k.kapat()
    envanter.write_text('{"klasor": "/usr/bin", "dosya": 900, '
                        '"karakter": 4000000}\n')
    dosyalar.write_text('{"yol": "/usr/bin/ls", "boyut": 140000}\n'
                        '{"yol": "/usr/bin/yeni", "boyut": 5}\n')

    k = K.Katalog(db, saat=saat_dondur(9999.0))   # göç zamanı çok sonra
    sonuc = k.ice_aktar(str(envanter), str(dosyalar))
    satir_k = k.db.execute("SELECT son, sayac FROM klasor WHERE yol='/usr/bin'"
                           ).fetchone()
    satir_d = k.db.execute("SELECT son, sayac FROM dosya WHERE yol='/usr/bin/ls'"
                           ).fetchone()
    yeni_d = k.db.execute(
        "SELECT son FROM dosya WHERE yol='/usr/bin/yeni'").fetchone()
    k.kapat()
    ok("klasör `son` eski kaldı", satir_k[0] == 1000.0, str(satir_k))
    ok("klasör `sayac` şişmedi", satir_k[1] == 1, str(satir_k))
    ok("dosya `son` eski kaldı", satir_d[0] == 1000.0, str(satir_d))
    ok("dosya `sayac` şişmedi", satir_d[1] == 1, str(satir_d))
    ok("JSONL'deki YENİ satır eklendi",
       yeni_d is not None and yeni_d[0] == 9999.0, str(yeni_d))
    ok("göç yeni satır saydı", sonuc.get("yeni_dosya") == 1, str(sonuc))
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    print("=== TEZGÂH REGRESYON TESTLERİ ===")
    eski = temizle_kalanlar()
    if eski:
        print("önceki koşulardan sızan %d geçici klasör temizlendi" % eski)
    for t in (test_hedef_tezgahi_kapatmaz, test_derinlesme, test_butce,
              test_ayni_klasor_iki_kez_yazilmaz,
              test_salt_okunur_wal_korur, test_kok_tespiti_ve_kilit,
              test_stderr_veri_sayilmaz, test_prune_dislanan_agac_inmez,
              test_goc_sonu_carpitar_m):
        t()
    kalan = temizle_kalanlar()
    if kalan:
        print("test sonrası %d geçici klasör temizlendi" % kalan)
    print("\n=== SONUÇ: %d geçti, %d kaldı ===" % (len(GECTI), len(KALDI)))
    for a in KALDI:
        print("  KALDI: %s" % a)
    return 1 if KALDI else 0


if __name__ == "__main__":
    sys.exit(main())
