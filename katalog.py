"""katalog.py — katalog deposu: SQLite (yalnızca stdlib).

Neden PostgreSQL değil:
  * Bu proje "sıfır bağımlılık, saf stdlib" ilkesiyle yaşar. Organizmanın
    görevi dışarıdaki bir servisin (veritabanı sunucusu) ayakta olmasına
    bağımlı OLAMAZ — servis düşerse iş durur. Kimlik, bağlantı havuzu,
    WAL/vacuum, collation yok. SQLite tek dosya: `cp core/` başka
    makinede de çalışır, günlük gözle okunur, organizma ölse de katalog
    diskte kalır. PostgreSQL'e geçiş ileride mümkün (aynı şema).

Ne kazandırır:
  * **Tekrar imkânsız**: `yol` PRIMARY KEY → aynı klasör/dosya ikinci kez
    yazılamaz. Bugün koruma sadece süreç içi `yapilan` setine dayanıyordu;
    veritabanı seviyesinde kural değişmez.
  * **Sorgu**: "tüm .conf dosyaları", "1 MB'tan büyükler", "hangi aile"
    → tüm dosyayı Python'da taramak yerine indeksli sorgu.
  * **Tazeleme**: kayıt üstüne yazılır, `sayac` artar → "bu klasör sayıldı"
    bilgisi asla kaybolmaz, ama veri tazelenebilir.
"""
import json
import os
import sqlite3
import time

SEMA = (
    """CREATE TABLE IF NOT EXISTS klasor (
           yol TEXT PRIMARY KEY, ad TEXT, derinlik INTEGER,
           dosya INTEGER, karakter INTEGER,
           ilk REAL, son REAL, sayac INTEGER DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS dosya (
           yol TEXT PRIMARY KEY, klasor TEXT, ad TEXT, uzanti TEXT,
           boyut INTEGER, mtime REAL,
           ilk REAL, son REAL, sayac INTEGER DEFAULT 1)""",
    # Faz 3: yürütülebilirlik sinyalleri (aynı find çağrısından, ek maliyet yok)
    "ALTER TABLE dosya ADD COLUMN mod TEXT DEFAULT ''",
    "ALTER TABLE dosya ADD COLUMN x INTEGER DEFAULT 0",
    "ALTER TABLE dosya ADD COLUMN shebang TEXT DEFAULT ''",
    "ALTER TABLE dosya ADD COLUMN tur TEXT DEFAULT ''",
    # Faz 3b: "0 dosya" ile "okunamadı" AYRI bilgilerdir. Erişilemeyen bir
    # dizin tarandı sayılırsa katalog kendi kör noktasının farkında olmaz.
    "ALTER TABLE klasor ADD COLUMN durum TEXT DEFAULT 'ok'",
    "CREATE INDEX IF NOT EXISTS ix_klasor_ad ON klasor(ad)",
    "CREATE INDEX IF NOT EXISTS ix_dosya_ad ON dosya(ad)",
    "CREATE INDEX IF NOT EXISTS ix_dosya_uzanti ON dosya(uzanti)",
    "CREATE INDEX IF NOT EXISTS ix_dosya_klasor ON dosya(klasor)",
    "CREATE INDEX IF NOT EXISTS ix_dosya_boyut ON dosya(boyut)",
    "CREATE TABLE IF NOT EXISTS meta (anahtar TEXT PRIMARY KEY, deger TEXT)",
)


def norm(yol):
    """Yol normalizasyonu: aynı klasör/dosya TEK sayılsın.

    `/etc`, `/etc/`, `/etc/.`, `//etc`, `/etc/./x` ve `/usr/lib/../lib/x`
    → hepsi kanonik tek biçime iner.
    """
    y = str(yol).strip()
    if not y:
        return ""
    mutlak = y.startswith("/")
    parcalar = []
    for p in y.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parcalar and parcalar[-1] != "..":
                parcalar.pop()
                continue
            if mutlak:
                continue          # /.. == /
        parcalar.append(p)
    n = "/".join(parcalar)
    if mutlak:
        return "/" + n
    return n or "."


def uzanti(ad):
    nokta = ad.rfind(".")
    return ad[nokta:] if nokta > 0 else ""


class Katalog:
    def __init__(self, yol, saat=None, salt_okunur=False):
        """`salt_okunur=True` ÇALIŞAN organizmanın veritabanını bozamaz.

        ÖNEMLİ: yazma kipiyle açılan ikinci bir bağlantı, temiz kapandığında
        `-wal`/`-shm` dosyalarını SİLER; çalışan sürecin açık tuttuğu
        tanıtıcılar sahipsiz (unlinked) inode'a düşer ve o andan itibaren
        o sürecin yazdıkları görünmez olur. Analiz/ölçüm araçları (eğitim,
        rapor) bu yüzden daima salt okunur açmalı — ya da bir kopyayı.
        """
        self.yol = str(yol)
        self.saat = saat or (lambda: round(time.time(), 3))
        self.salt_okunur = bool(salt_okunur)
        klasorler = os.path.dirname(self.yol)
        if not self.salt_okunur and klasorler:
            os.makedirs(klasorler, exist_ok=True)
        if self.salt_okunur:
            self.db = sqlite3.connect("file:%s?mode=ro" % self.yol,
                                      uri=True, timeout=15)
        else:
            self.db = sqlite3.connect(self.yol, timeout=15)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
            for sql in SEMA:
                try:
                    self.db.execute(sql)
                except sqlite3.OperationalError:
                    pass          # ALTER TABLE: sütun zaten vardı
            self.db.commit()

    def kapat(self):
        try:
            self.db.commit()
            self.db.close()
        except sqlite3.Error:
            pass

    # ---------- yazma ----------

    def klasor_yaz(self, yol, dosya, karakter, durum="ok", goc=False):
        """Klasör özetini yaz → (yeni_mi, onceki_karakter).

        Çakışmada üstüne yazılır; eski kayıt SİLİNMEZ. "Bu klasör sayıldı
        mı" sorusu her zaman doğru yanıtlanır (sayaç artar).

        `durum`: "ok" | "erisilemez". Erişilemeyen dizin de kaydedilir ama
        "boş" gibi görünmez — 0 dosya ile "okunamadı" farklı bilgidir.

        `goc=True` → GÖÇ modu: var olan satıra DOKUNMAZ (DO NOTHING).
        Göç JSONL'i her doğuşta yeniden okur; o satırlar daha önce
        tarandıysa `son` "göç zamanı" diye sahte güncellenir ve `sayac`
        şişerdi. `son` "diskte en son ne zaman görüldü" anlamını korumalı.
        """
        yol = norm(yol)
        if not yol:
            return False, 0
        ad = yol.rsplit("/", 1)[-1] or "/"
        derinlik = yol.count("/")
        t = self.saat()
        onceki = self.db.execute(
            "SELECT karakter FROM klasor WHERE yol=?", (yol,)).fetchone()
        if goc:
            self.db.execute(
                """INSERT INTO klasor(yol,ad,derinlik,dosya,karakter,ilk,
                                     son,sayac,durum)
                   VALUES(?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(yol) DO NOTHING""",
                (yol, ad, derinlik, dosya, karakter, t, t, durum))
        else:
            self.db.execute(
                """INSERT INTO klasor(yol,ad,derinlik,dosya,karakter,ilk,
                                     son,sayac,durum)
                   VALUES(?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(yol) DO UPDATE SET
                     dosya=excluded.dosya, karakter=excluded.karakter,
                     son=excluded.son, sayac=klasor.sayac+1,
                     durum=excluded.durum""",
                (yol, ad, derinlik, dosya, karakter, t, t, durum))
        self.db.commit()
        return onceki is None, (onceki[0] if onceki else 0)

    def erisilemezler(self):
        return [r[0] for r in self.db.execute(
            "SELECT yol FROM klasor WHERE durum='erisilemez' ORDER BY yol")]

    def supheli_temizle(self):
        """Çöp satırları sil → silinen sayı.

        05.10'da `find`'in stderr'i stdout'a karışıp
        "find: '/root': Permission denied" gibi satırlar klasör olarak
        kaydedilmişti (27 satır). Bunlar yol bile değil; her doğuşta
        temizlenir. Dışarıdan yazma yapılmaz (çalışan organizmanın WAL'ı
        bozulur) — işi YASAMANIN KENDİSİ yapar.
        """
        cur = self.db.execute(
            "DELETE FROM klasor WHERE yol NOT LIKE '/%' "
            "OR yol LIKE '%Permission denied%'")
        silinen = cur.rowcount or 0
        if silinen:
            self.db.execute(
                "DELETE FROM dosya WHERE yol NOT LIKE '/%' "
                "OR yol LIKE '%Permission denied%'")
            self.db.commit()
        return silinen

    def dosya_yaz(self, kayitlar, goc=False):
        """(yol, boyut[, mtime, mod]) listesi → yeni dosya sayısı.

        `mod` verilirse yürütülebilirlik (x) ve shebang kaydedilir; böylece
        "bu dosya çalıştırılabilir mi?" sorusu katalogdan yanıtlanır.

        `goc=True` → var olan satıra dokunulmaz (`son`/`sayac` sahte
        güncellenmez). Göç JSONL'i her doğuşta yeniden okur; aksi halde
        tüm katalogun `son` değeri "göç zamanı" olurdu ve alan artık
        "diskte en son ne zaman görüldü" anlamına gelmezdi.
        """
        t = self.saat()
        satir = []
        for k in kayitlar:
            yol, boyut = k[0], k[1]
            mtime = k[2] if len(k) >= 3 else None
            mod = k[3] if len(k) >= 4 else ""
            yol = norm(yol)
            if not yol:
                continue
            ad = yol.rsplit("/", 1)[-1]
            x, sb = self._yurutulebilir(yol, boyut, mod)
            satir.append((yol, yol.rsplit("/", 1)[0] or "/", ad,
                          uzanti(ad), boyut, mtime, t, t, mod or "",
                          x, sb, "f"))
        if not satir:
            return 0
        # "yeni" sayısı: UPDATE de total_changes sayar, bu yüzden tablo
        # satır sayısı farkı alınır (upsert sonrası gerçek ekleme).
        once = self.dosya_sayisi()
        if goc:
            sql = """INSERT INTO dosya(yol,klasor,ad,uzanti,boyut,mtime,
                                      ilk,son,sayac,mod,x,shebang,tur)
                     VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?)
                     ON CONFLICT(yol) DO NOTHING"""
        else:
            sql = """INSERT INTO dosya(yol,klasor,ad,uzanti,boyut,mtime,
                                      ilk,son,sayac,mod,x,shebang,tur)
                     VALUES(?,?,?,?,?,?,?,?,1,?,?,?,?)
                     ON CONFLICT(yol) DO UPDATE SET
                       boyut=excluded.boyut, mtime=excluded.mtime,
                       mod=CASE WHEN excluded.mod<>'' THEN excluded.mod
                                ELSE dosya.mod END,
                       x=CASE WHEN excluded.mod<>'' THEN excluded.x
                              ELSE dosya.x END,
                       shebang=CASE WHEN excluded.shebang<>''
                                     THEN excluded.shebang
                                     ELSE dosya.shebang END,
                       son=excluded.son, sayac=dosya.sayac+1"""
        self.db.executemany(sql, satir)
        self.db.commit()
        return self.dosya_sayisi() - once

    @staticmethod
    def _yurutulebilir(yol, boyut, mod):
        """(x, shebang) — mod bitleri ve ilk satır.

        Shebang sadece yürütülebilir ve küçük dosyalarda okunur (I/O
        maliyeti sınırlı kalsın diye).
        """
        x = 0
        if mod:
            try:
                x = 1 if int(str(mod).strip() or "0", 8) & 0o111 else 0
            except ValueError:
                x = 0
        sb = ""
        if x and 0 < boyut <= (1 << 20):
            try:
                with open(yol, "rb") as f:
                    ilk = f.read(128)
                if ilk[:2] == b"#!":
                    sb = ilk[2:].split(b"\n", 1)[0].decode(
                        "utf-8", "replace").strip()[:80]
            except OSError:
                sb = ""
        return x, sb


    # ---------- okuma ----------

    def yapilanlar(self):
        """Envanterlenmiş klasör yolları (kalıcı hafıza)."""
        return {r[0] for r in self.db.execute("SELECT yol FROM klasor")}

    def klasor_sayisi(self):
        return self.db.execute("SELECT COUNT(*) FROM klasor").fetchone()[0]

    def dosya_sayisi(self):
        return self.db.execute("SELECT COUNT(*) FROM dosya").fetchone()[0]

    def rastgele_calistirilabilir(self):
        """x=1 olan rastgele bir dosya → (yol, ad).

        "nedir?" egzersizi bununla çalışır: organizma çalıştırılabilir bir
        aday seçer, kendi beyinine sorar, bilemezse GERÇEK dpkg'ye danışır.
        """
        satir = self.db.execute(
            "SELECT yol, ad FROM dosya WHERE x=1 "
            "ORDER BY RANDOM() LIMIT 1").fetchone()
        return satir

    def adlar(self, sinir=0):
        """Dosya adları (konum egzersizi bununla çalışır)."""
        sql = "SELECT ad FROM dosya"
        if sinir:
            sql += " LIMIT %d" % int(sinir)
        return [r[0] for r in self.db.execute(sql)]

    def dosya_satirlari(self, sinir=0):
        """Eğitim için satırlar: (yol, ad, uzanti, boyut)."""
        sql = "SELECT yol,ad,uzanti,boyut FROM dosya"
        if sinir:
            sql += " LIMIT %d" % int(sinir)
        return self.db.execute(sql).fetchall()

    def yurutulebilirler(self, sinir=100):
        """Çalıştırılabilir dosyalar: (yol, shebang) — Faz 3'ün hammaddesi."""
        return self.db.execute(
            "SELECT yol,shebang FROM dosya WHERE x=1 ORDER BY yol LIMIT ?",
            (int(sinir),)).fetchall()

    def yurutulebilir_sayisi(self):
        return self.db.execute(
            "SELECT COUNT(*) FROM dosya WHERE x=1").fetchone()[0]

    def rastgele_klasor(self, haric=()):
        """Rastgele bir envanterlenmiş klasör (tazeleme için)."""
        for _ in range(8):
            satir = self.db.execute(
                "SELECT yol FROM klasor ORDER BY RANDOM() LIMIT 1").fetchone()
            if not satir:
                return None
            if satir[0] not in haric:
                return satir[0]
        return None

    def istatistik(self):
        s = {}
        s["klasor"] = self.klasor_sayisi()
        s["dosya"] = self.dosya_sayisi()
        s["karakter"] = self.db.execute(
            "SELECT COALESCE(SUM(karakter),0) FROM klasor").fetchone()[0]
        s["dosya_boyut"] = self.db.execute(
            "SELECT COALESCE(SUM(boyut),0) FROM dosya").fetchone()[0]
        s["en_buyuk"] = self.db.execute(
            "SELECT yol,boyut FROM dosya ORDER BY boyut DESC LIMIT 1"
        ).fetchone()
        s["uzantilar"] = self.db.execute(
            """SELECT uzanti, COUNT(*) c FROM dosya WHERE uzanti<>''
               GROUP BY uzanti ORDER BY c DESC LIMIT 6""").fetchall()
        try:
            s["erisilemez"] = self.db.execute(
                "SELECT COUNT(*) FROM klasor WHERE durum='erisilemez'"
            ).fetchone()[0]
        except sqlite3.Error:
            s["erisilemez"] = 0
        return s

    # ---------- göç (eski JSONL ↔ SQLite) ----------

    def ice_aktar(self, envanter_yolu, dosyalar_yolu):
        """Eski JSONL dosyalarını içe al (bir kerelik göç, tekrar çalışsa
        da zararsız: PRIMARY KEY aynı satırı iki kez almaz)."""
        k = d = 0
        try:
            with open(envanter_yolu, encoding="utf-8") as f:
                for satir in f:
                    try:
                        r = json.loads(satir)
                    except ValueError:
                        continue
                    yeni, _ = self.klasor_yaz(r.get("klasor", ""),
                                             int(r.get("dosya", 0)),
                                             int(r.get("karakter", 0)),
                                             goc=True)
                    k += 1 if yeni else 0
        except OSError:
            pass
        toplu = []
        try:
            with open(dosyalar_yolu, encoding="utf-8") as f:
                for satir in f:
                    try:
                        r = json.loads(satir)
                    except ValueError:
                        continue
                    toplu.append((r.get("yol", ""), int(r.get("boyut", 0))))
                    if len(toplu) >= 2000:
                        d += self.dosya_yaz(toplu, goc=True)
                        toplu = []
        except OSError:
            pass
        if toplu:
            d += self.dosya_yaz(toplu, goc=True)
        return {"yeni_klasor": k, "yeni_dosya": d,
                "klasor": self.klasor_sayisi(), "dosya": self.dosya_sayisi()}

    def jsonl_aktar(self, envanter_yolu, dosyalar_yolu):
        """SQLite → JSONL dışa aktarım (denetim/okunabilirlik için).

        Yazma iki aşamalı: geçici dosya → os.replace. Yarım kalan aktarım
        asla okunabilir bir katalog haline gelmez.
        """
        for hedef, sql, tur in (
                (envanter_yolu,
                 "SELECT yol,dosya,karakter,son FROM klasor ORDER BY yol",
                 "klasor"),
                (dosyalar_yolu,
                 "SELECT yol,ad,uzanti,boyut,son FROM dosya ORDER BY yol",
                 "dosya")):
            gecici = "%s.tmp" % hedef
            with open(gecici, "w", encoding="utf-8") as f:
                for row in self.db.execute(sql):
                    if tur == "klasor":
                        rec = {"klasor": row[0], "dosya": row[1],
                               "karakter": row[2], "t": row[3]}
                    else:
                        rec = {"yol": row[0], "ad": row[1], "uzanti": row[2],
                               "boyut": row[3],
                               "klasor": row[0].rsplit("/", 1)[0] or "/",
                               "t": row[4]}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            os.replace(gecici, hedef)
        return True


def proje_kok():
    """Proje kökü (bu dosyanın bulunduğu dizin).

    DİKKAT: burada TAM BİR dirname yeterlidir. Bir kez daha çağrılırsa kök
    bir üst dizine (Genel/) kayar, `organizma_yasiyor` hiçbir süreç
    bulamaz ve sıfırlama kilidi sessizce düşer. 05.10'da böyle oldu:
    çalışan organizmanın veritabanı arşivlenip yerine boş bırakıldı,
    süreç arşivlenmiş inode'a yazmaya devam etti.
    """
    return os.path.dirname(os.path.abspath(__file__))


def anlik_kopya(db_yolu, hedef=None, deneme=3):
    """Canlı veritabanından TUTARLI anlık kopya al → kopya yolu.

    Neden şart: canlı WAL veritabanını başka bir süreç doğrudan okuduğunda,
    yazıcı checkpoint yapıp -wal'ı değiştirdiği anda okuyucu
    "database disk image is malformed" hatası alabilir (05.10 19:20'de
    yaşandı — sağlık aracı okurken organizmanın _jsonl_aktar'ı bu hatayı
    gördü). Kopya, SQLite'ın kendi online-backup protokolüyle alınır:
    kilitli sayfa kopyalama, tutarlı anlık görüntü, okuyucu-kırıcı değil.

    Doğrudan dosya kopyası (shutil.copy) YETERLİ DEĞİLDİR: -wal içindeki
    commit'ler kopyalanmaz veya kırılır.
    """
    import shutil
    db_yolu = str(db_yolu)
    if hedef is None:
        hedef = "/tmp/katalog_anlik_%d.db" % os.getpid()
    for _ in range(max(1, deneme)):
        try:
            kaynak = sqlite3.connect("file:%s?mode=ro" % db_yolu, uri=True,
                                     timeout=10)
            hedef_bag = sqlite3.connect(hedef, timeout=10)
            kaynak.backup(hedef_bag)
            hedef_bag.close()
            kaynak.close()
            return hedef
        except sqlite3.Error:
            time.sleep(0.2)
    return None


def organizma_yasiyor(kok=None):
    """Bu projede çalışan `main.py` süreci var mı? (PID veya None)

    Yazma yapan bir sürecin veritabanını silmek/taşımak, o sürecin
    tanıtıcılarını sahipsiz bırakır (05.10'da yaşanan WAL kazası).
    Bu yüzden sıfırlama çalışan bir organizmaya sessizce uygulanmaz.
    """
    kok = os.path.realpath(kok or proje_kok())
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    argv = f.read().split(b"\0")
                if not any(a.endswith(b"main.py") for a in argv):
                    continue
                # cwd OKUNAMAZ (root süreç) → süreç YOK SAYILMAZ.
                # Aksi halde sıfırlama kilidi düşer ve çalışan organizmanın
                # veritabanı altında taşınır (05.10 18:25'te yaşandı).
                # Doğrulanamayan süreç VAR SAYILIR (güvenli taraf).
                try:
                    cwd = os.path.realpath("/proc/%s/cwd" % pid)
                except OSError:
                    cwd = None
                if cwd is not None and cwd != kok:
                    continue
                return int(pid)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return None


def sifirla(dizin, zorla=False, saat=None):
    """Katalog deposunu arşivleyip BOŞ olarak yeniden kur.

    Silmez, arşivler: `world/katalog/arsiv/<damga>/` altına katalog.db
    (+ -wal/-shm) ve JSONL dışa aktarımları taşınır. Böylece "sıfırla"
    geri alınabilir bir işlemdir.

    Döner: {"arsiv": yol, "tasinan": [...], "pid": pid, "uyari": str}
    """
    kok = proje_kok()
    pid = organizma_yasiyor(kok)
    if pid and not zorla:
        return {"arsiv": None, "tasinan": [], "pid": pid,
                "uyari": "çalışan organizma var (pid %d) — kapatıp tekrar "
                         "dene ya da --zorla" % pid}

    damga = (saat or time.strftime("%Y%m%d-%H%M%S"))
    arsiv = os.path.join(dizin, "arsiv", damga)
    os.makedirs(arsiv, exist_ok=True)

    tasinan = []
    # Önce WAL'ı ana dosyaya yazdır: arşiv tutarlı olsun (yazan yok).
    db = os.path.join(dizin, "katalog.db")
    if os.path.exists(db):
        try:
            k = Katalog(db)
            k.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            k.kapat()
        except sqlite3.Error:
            pass
    for ad in ("katalog.db", "katalog.db-wal", "katalog.db-shm",
               "envanter.jsonl", "dosyalar.jsonl"):
        yol = os.path.join(dizin, ad)
        if os.path.exists(yol):
            os.replace(yol, os.path.join(arsiv, ad))
            tasinan.append(ad)

    # Yeni boş depo (şema dahil: klasor, dosya + mod/x/shebang/tur)
    k = Katalog(db)
    sonuc = {"arsiv": arsiv, "tasinan": tasinan, "pid": pid, "uyari": None}
    sonuc["istatistik"] = k.istatistik()
    k.kapat()
    return sonuc


if __name__ == "__main__":
    import sys
    kok = os.path.dirname(os.path.abspath(__file__))
    dizin = os.path.join(kok, "world", "katalog")
    if "--sifirla" in sys.argv:
        sonuc = sifirla(dizin, zorla="--zorla" in sys.argv)
        if sonuc["uyari"]:
            print("YAPILMADI:", sonuc["uyari"])
            sys.exit(1)
        print("arşiv  :", sonuc["arsiv"])
        print("taşınan:", ", ".join(sonuc["tasinan"]) or "(yok)")
        s = sonuc["istatistik"]
        print("yeni katalog: klasör=%d dosya=%d"
              % (s["klasor"], s["dosya"]))
        sys.exit(0)
    k = Katalog(os.path.join(dizin, "katalog.db"))
    if "--ice" in sys.argv:
        print("göç:", k.ice_aktar(os.path.join(dizin, "envanter.jsonl"),
                                  os.path.join(dizin, "dosyalar.jsonl")))
    if "--aktar" in sys.argv:
        k.jsonl_aktar(os.path.join(dizin, "envanter.jsonl"),
                      os.path.join(dizin, "dosyalar.jsonl"))
        print("JSONL aktarıldı")
    s = k.istatistik()
    print("klasör: %d | dosya: %d | karakter: %d" %
          (s["klasor"], s["dosya"], s["karakter"]))
    print("en büyük: %s" % (s["en_buyuk"],))
    print("uzantılar: %s" % (s["uzantilar"],))

