"""kontrol_katalog.py — "gerçekten çalışıyor mu?" sağlık denetimi.

  python3 kontrol_katalog.py            # tek ölçüm (30 sn büyüme farkı)
  python3 kontrol_katalog.py --saat 5   # 5 dakikalık pencere

Bu araç 2026-10-04'teki sessiz durmaya karşı yazıldı: organizma 18 saat
canlı görünüyor, journal doluyordu ama görev eylemi hiç sunulmadığı için
katalog 505 klasörde donmuştu. Tek bakışta görülemiyordu.

DİKKAT: katalog veritabanı SALT OKUNUR açılır. Yazma kipiyle açılan ikinci
bir bağlantı, temiz kapandığında -wal/-shm dosyalarını siler ve çalışan
sürecin verisi görünmez olur (2026-10-05'te yaşandı).
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "world" / "katalog" / "katalog.db"
JOURNAL = ROOT / "journal.jsonl"


def yari(n):
    return "%sK" % ("%.0f" % (n / 1024.0)) if n < 1024 * 1024 \
        else "%.1fM" % (n / 1048576.0)


def surec(kok_tam=True):
    """Çalışan organizma var mı? → (pid, cpu_sn, cwd_dogrulanabilir)

    pgrep'e güvenilmez: süreç `python main.py` olarak da
    başlatılabiliyor (python3 değil) ve kalıp tutmuyordu — "yok" dedi,
    hâlâ çalışıyordu. Bu yüzden /proc taranır: cmdline'da main.py olan
    süreçler.

    cwd_çakışması yoksa süreç elenir. cwd OKUNAMAZSA (root süreci)
    süreç yine döner ama `cwd_dogrulanabilir=None` olur: doğrulanamayan
    süreç "yok" sayılmaz.
    """
    return _surec_bul(kok_tam)


def _surec_bul(kok_tam):
    ROOT = str(Path(__file__).resolve().parent)
    adaylar = []
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    argv = [a for a in f.read().split(b"\0") if a]
                if not any(a.endswith(b"main.py") for a in argv):
                    continue
                # cwd OKUNAMAYABİLİR: süreç ROOT ile çalışıyorsa
                # /proc/PID/cwd erişime kapalıdır. Eski kod burada
                # `continue` yapıp süreci sessizce ATLIYORDU →
                # "organizma yok" diye yanlış rapor (05.10 19:57).
                # Doğrulanamayan süreç "yok sayılmaz".
                try:
                    cwd = os.path.realpath("/proc/%s/cwd" % pid)
                    dogrulanabilir = (cwd == ROOT)
                except OSError:
                    cwd, dogrulanabilir = None, None   # root: bilemiyoruz
                if cwd and cwd != ROOT:
                    continue
                with open("/proc/%s/stat" % pid) as f:
                    alan = f.read().rsplit(")", 1)[1].split()
                cpu = int(alan[11]) / 100.0
                # `sudo python main.py` → iki süreç vardır: sarmalayıcı
                # (cpu ~0) ve asıl python. Raporda asıl python tercih edilir.
                python_mi = b"python" in argv[0]
                adaylar.append((1 if python_mi else 0, int(pid), cpu,
                                dogrulanabilir))
            except (OSError, IndexError, ValueError):
                continue
    except OSError:
        pass
    if not adaylar:
        return None, None, None
    adaylar.sort(reverse=True)      # önce python olan, sonra büyük pid
    _, pid, cpu, dogr = adaylar[0]
    return pid, cpu, dogr


def db_oku():
    if not DB.exists():
        return None
    # CANLI WRITER'A DOKUNMA: organizma yazarken doğrudan okumak onun
    # kendi bağlantı hatasına yol açabiliyor (05.10 19:20: "malformed").
    # Online backup ile tutarlı anlık kopya alınır, o okunur.
    try:
        from katalog import anlik_kopya
        kopya = anlik_kopya(DB)
    except Exception:
        kopya = None
    yol = kopya or DB
    c = sqlite3.connect("file:%s?mode=ro" % yol, uri=True, timeout=15)

    def ara(sql, varsayilan=0):
        """Sütun yoksa (henüz migrate edilmemiş şema) ÇÖKME.

        Sağlık aracının amacı teşhistir; eski şemada patlayarak rapor
        edemez hale gelmesi kendi başına bir hatadır.
        """
        try:
            return c.execute(sql).fetchone()[0]
        except sqlite3.Error:
            return varsayilan

    d = {"klasor": ara("SELECT COUNT(*) FROM klasor"),
         "dosya": ara("SELECT COUNT(*) FROM dosya"),
         "x": ara("SELECT COUNT(*) FROM dosya WHERE x=1"),
         "sb": ara("SELECT COUNT(*) FROM dosya WHERE shebang<>''"),
         "kar": ara("SELECT COALESCE(SUM(boyut),0) FROM dosya"),
         "son": ara("SELECT MAX(son) FROM klasor"),
         "erisilemez": ara("SELECT COUNT(*) FROM klasor "
                          "WHERE durum='erisilemez'"),
         "cop": ara("SELECT COUNT(*) FROM klasor WHERE yol NOT LIKE '/%'")}
    try:
        d["x_liste"] = c.execute(
            "SELECT yol,shebang FROM dosya WHERE x=1 ORDER BY yol LIMIT 3"
        ).fetchall()
    except sqlite3.Error:
        d["x_liste"] = []
    c.close()
    if kopya:
        try:
            os.remove(kopya)
        except OSError:
            pass
    return d


def journal_ozet(pencere_sn):
    """Son N saniyede: eylem karışımı ve tezgâh sağlığı."""
    if not JOURNAL.exists():
        return None
    esik = time.time() - pencere_sn
    say = collections.Counter()
    katalogla = 0
    envanter = 0
    bos = derin = tazele = hata = 0
    son_t = None
    with open(JOURNAL, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 8_000_000))
        f.readline()
        for ham in f:
            try:
                r = json.loads(ham)
            except ValueError:
                continue
            t = r.get("t")
            if t is None or t < esik:
                continue
            son_t = t
            k = r.get("kind")
            a = r.get("action") or ""
            if k == "act":
                say[a] += 1
                if a == "katalogla":
                    katalogla += 1
                    if "envanter:" in str(r.get("obs", "")):
                        envanter += 1
            elif k == "kuyruk_bos":
                bos += 1
            elif k == "derinlesti":
                derin += 1
            elif k == "tazeleme":
                tazele += 1
            elif k in ("hata", "olum"):
                hata += 1
    return {"pencere": pencere_sn, "son": son_t, "eylem": say,
            "katalogla": katalogla, "envanter": envanter,
            "bos": bos, "derin": derin, "tazele": tazele, "hata": hata}

def main():
    ap = argparse.ArgumentParser(description="katalog sağlık denetimi")
    ap.add_argument("--saat", type=float, default=0.5,
                    help="journal penceresi (saat), varsayılan 0.5")
    ap.add_argument("--bekle", type=float, default=30.0,
                    help="büyüme ölçümü için bekleme saniyesi")
    args = ap.parse_args()

    sorun = []
    pid, cpu, cwd_dogr = surec()
    print("=== SÜREÇ ===")
    if pid:
        if cwd_dogr is None:
            print("canlı: pid=%s  cpu=%.0f sn  (ROOT — çalışma dizini "
                  "doğrulanamıyor)" % (pid, cpu))
        else:
            print("canlı: pid=%s  cpu=%.0f sn" % (pid, cpu))
    else:
        print("ÇALIŞAN ORGANİZMA YOK (python3 main.py)")
        sorun.append("süreç yok")

    print("\n=== KATALOG (salt okunur) ===")
    a = db_oku()
    if not a:
        print("katalog.db yok: %s" % DB)
        return 2
    print("klasör=%d  dosya=%d  karakter=%s"
          % (a["klasor"], a["dosya"], yari(a["kar"])))
    print("yürütülebilir=%d  shebang=%d" % (a["x"], a["sb"]))
    print("erişilemez=%d (okunamadı, boş DEĞİL)  çöp satır=%d"
          % (a["erisilemez"], a["cop"]))
    print("son klasör kaydı: %s"
          % (time.strftime("%m-%d %H:%M:%S", time.localtime(a["son"]))
             if a["son"] else "-"))
    for yol, sb in a["x_liste"]:
        print("   x: %-44s %s" % (yol[-44:], sb or "(shebang yok)"))

    # Bütçe kontrolü ÖNCE hesaplanmalı: hem büyüme hem journal bölümü
    # buna göre karar verir. Görevin "sunulmaması" her zaman sorun değildir.
    # azami_klasor dolduysa görevin başarılı biçimde bitmesidir (05.10'da
    # sağlık aracı bu başarıyı "SORUN" diye raporlamıştı → yanlış uyarı).
    butce = 0
    try:
        butce = int(json.loads(
            (ROOT / "gorev.json").read_text(encoding="utf-8")
        ).get("azami_klasor", 0))
    except (ValueError, OSError):
        butce = 0
    butce_doldu = bool(butce) and a["klasor"] >= butce

    if args.bekle > 0:
        time.sleep(args.bekle)
        b = db_oku()
        dk = b["klasor"] - a["klasor"]
        dd = b["dosya"] - a["dosya"]
        print("\n=== BÜYÜME (%.0f sn) ===" % args.bekle)
        print("klasör +%d   dosya +%d" % (dk, dd))
        if pid and dk == 0 and dd == 0:
            if butce_doldu:
                print("katalog durgun — bütçe dolduğu için (doğru)")
            else:
                print("!! süreç ama katalog BÜYÜMÜYOR")
                sorun.append("katalog büyümüyor")
    j = journal_ozet(args.saat * 3600)
    print("\n=== JOURNAL (son %.1f saat) ===" % args.saat)
    if butce_doldu:
        print("bütçe doldu: %d/%d klasör → görev tamamlandı, 'katalogla' "
              "artık sunulmuyor (doğru)" % (a["klasor"], butce))
        print("devam etmek için: gorev.json → azami_klasor değerini artır "
              "(0 = sınırsız)")
    if not j or not j["son"]:
        print("bu pencerede kayıt yok")
    else:
        print("son kayıt: %s"
              % time.strftime("%H:%M:%S", time.localtime(j["son"])))
        print("katalogla eylemi: %d kez  (envanter üreten: %d)"
              % (j["katalogla"], j["envanter"]))
        print("derinleşme=%d  boş kuyruk=%d  tazeleme=%d  hata/ölüm=%d"
              % (j["derin"], j["bos"], j["tazele"], j["hata"]))
        for ad, n in j["eylem"].most_common(8):
            print("   %-24s %5d" % (ad, n))
        if j["katalogla"] == 0 and j["envanter"] == 0 and not butce_doldu:
            print("!! görev eylemi seçilmiyor (tezgâh sunulmuyor olabilir)")
            sorun.append("görev eylemi seçilmiyor")
        if j["bos"] > 3:
            print("!! boş kuyruk çok: tarama tükenmiş olabilir")
            sorun.append("kuyruk boş")
        if a["cop"]:
            print("!! %d çöp satır (stderr karışmış) — doğuşta temizlenmeli"
                  % a["cop"])
            sorun.append("çöp satır var")

    print("\n=== SONUÇ ===")
    if sorun:
        for s in sorun:
            print("SORUN: %s" % s)
        return 1
    print("sağlıklı görünüyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
