"""komut_tehlike.py — Komut tehlike skoru tahmini modeli.

Komut adı + zarar profili → tehlike skoru (0..1) tahmini.
Organizma komutu çalıştırmadan önce bu modeli sorar:
    "bu komutu çalıştırırsam ölürüm mü?" → uygula / bekle / iptal

Öğrenme: veri seti (data/komut_zarar.jsonl) üzerinden delta öğrenmesi.
Kayıt: zeka/komut_tehlike.json (atomik).

Özellik uzayı:
  - komut=<isim>            (tekil komut kimliği)
  - zarar=<tip>             (dosya_silme, disk_yazma, sistem_kontrolu, ...
  - enerji=<kova>           (enerji_etkisi kova: -100, -70, ..., -10)
  - uzunluk=<kisa/orta/uzun> (komut adı uzunluğu)
  - kategori=<tip>          (zarar_tipi'nin ilk bölümü)
  - tip=<READ/EXEC/MODIFY/NETWORK> (komut tipi haritası + prefix/keyword)

Tahmin = global_ortalama + aktif özelliklerin delta ortalaması.
Hedef = olum_olasiligi (gerçekte bu komut ne kadar ölütür).

YENİ: --help öğrenme (güvenli subprocess, tip refine, ilk-keşif ödülü)
Model, --help çıktısını güvenli altyapıda (shutil.which, stdin=DEVNULL,
start_new_session, killpg, 8KB limit, sadece --help) çalıştırır.
Exit code 0 zorunlu; "Usage:"/"Kullanım:" satırları atlanır.
Help metnindeki keyword'ler word-boundary regex ile komut tipini
refine eder. save() her 500 tik + finally'de çağrılır.

Kullanım:
    m = KomutTehlike(); m.load()
    skor = m.tahmin(komut="rm", zarar_tipi="dosya_silme",
                    enerji_etkisi=-60, olum_olasiligi=0.9)
    # skor ≈ 0.9 → çok tehlikeli
"""

import json
import os
import re
import shutil
import signal
from pathlib import Path

import zeka

ROOT = Path(__file__).resolve().parent
VERI_SETI = ROOT / "data" / "komut_zarar.jsonl"

# Enerji etkisi kova sınırları (artan mutlak değer)
ENERJI_KOVALARI = (-100, -70, -60, -50, -40, -30, -20, -10)

# Ölüm olasılığı kova sınırları
OLUM_KOVALARI = (1.0, 0.95, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1)

# ---------- Komut tipi sınıflandırması (READ / EXEC / MODIFY / NETWORK) ----------
# Tehlike skorunda yardımcı özellik: komutun ne tür bir etki yaratabileceği.
_KOMUT_TIPLERI = {
    # MODIFY — dosya/sistem yazma, silme, bölümleme
    "rm": "MODIFY", "rmdir": "MODIFY", "dd": "MODIFY", "mkfs": "MODIFY",
    "fdisk": "MODIFY", "mount": "MODIFY", "umount": "MODIFY",
    "cp": "MODIFY", "mv": "MODIFY", "touch": "MODIFY", "mkdir": "MODIFY",
    "chmod": "MODIFY", "chown": "MODIFY", "chgrp": "MODIFY",
    "ln": "MODIFY", "tar": "MODIFY", "cpio": "MODIFY",
    "zip": "MODIFY", "unzip": "MODIFY", "gzip": "MODIFY", "gunzip": "MODIFY",
    "bzip2": "MODIFY", "xz": "MODIFY", "zstd": "MODIFY",
    "truncate": "MODIFY", "fallocate": "MODIFY", "shred": "MODIFY",
    "wipe": "MODIFY", "scrub": "MODIFY", "tee": "MODIFY",
    "sed": "MODIFY",
    # EXEC — kod / shell yürütme
    "bash": "EXEC", "sh": "EXEC", "python3": "EXEC", "python": "EXEC",
    "perl": "EXEC", "ruby": "EXEC", "node": "EXEC",
    "awk": "EXEC", "env": "EXEC", "dash": "EXEC", "zsh": "EXEC",
    "php": "EXEC", "lua": "EXEC", "tclsh": "EXEC",
    "eval": "EXEC", "exec": "EXEC",
    # NETWORK — ağ iletişimi (veri sızdırma / dış veri çekme)
    "nmap": "NETWORK", "ping": "NETWORK", "ping6": "NETWORK",
    "curl": "NETWORK", "wget": "NETWORK", "nc": "NETWORK",
    "ncat": "NETWORK", "netcat": "NETWORK", "telnet": "NETWORK",
    "ssh": "NETWORK", "scp": "NETWORK", "sftp": "NETWORK",
    "rsync": "NETWORK", "arpspoof": "NETWORK",
    "traceroute": "NETWORK", "traceroute6": "NETWORK",
    "dig": "NETWORK", "nslookup": "NETWORK", "host": "NETWORK",
    "whois": "NETWORK", "arp": "NETWORK",
    # (ifconfig: yalnızca arayüz bilgisi okur → READ, varsayılan)
}

# Prefix ve keyword matching: tam eşleşmeyi kaçıran komutlar için.
# mkfs.ext4 → mkfs → MODIFY, iptables → NETWORK, wipefs → MODIFY gibi.
_TIP_PREFIXES = {
    "mkfs": "MODIFY", "wipefs": "MODIFY", "fdisk": "MODIFY", "mount": "MODIFY",
    "iptables": "NETWORK", "nft": "NETWORK", "ip": "NETWORK",
    "dpkg": "MODIFY", "apt": "MODIFY", "apt-get": "MODIFY",
    "yum": "MODIFY", "dnf": "MODIFY", "pip": "EXEC", "gem": "EXEC",
}

# Help metnindeki anahtar kelimilerden tip çıkarma.
# --help çıktısı "List information about the FILEs" gibi açıklamalarda
# işaretleyici kelimeler var; bunlar komutun gerçek tipini gösterir.
_HELP_TIP_KEYWORDS = {
    "NETWORK": ["network", "ip address", "route", "port", "tcp", "udp",
                "socket", "connect", "download", "upload", "transfer", "dns",
                "ping", "ssh", "ftp", "server", "client", "firewall", "iptables"],
    "MODIFY": ["delete", "remove", "create", "write", "copy", "move", "rename",
               "mkdir", "chmod", "chown", "format", "truncate", "compress",
               "extract", "mount", "disk", "file system", "partition"],
    "EXEC": ["execute", "run", "shell", "interpreter", "script",
             "command interpreter", "binary", "program"],
    "READ": ["list", "show", "print", "display", "view", "read",
             "cat", "head", "tail", "grep", "find", "search",
             "information about", "describe", "stat", "ls"],
}

def _help_tip_from_text(komut, text):
    """Help metnindeki anahtar kelimilerden komut tipini refine eder.

    Word-boundary kontrolü: "format" in "information" gibi false positive'ler
    önlenir (regex \\b). Metinde NETWORK/MODIFY/EXEC keyword'leri varsa onu döner,
    yoksa None → _komut_tipi() haritasından varsayılan.
    """
    t = text.lower()
    for tip, keywords in _HELP_TIP_KEYWORDS.items():
        for kw in keywords:
            pat = re.compile(r"\b" + re.escape(kw) + r"\b")
            if pat.search(t):
                return tip
    return None  # haritaya düş

# READ — varsayılan (bilinmeyen komut → en güvenli varsayılır)
_TIP_DEFAULT = "READ"

# Tip → soft threat hedefi (0..1). Help metninden öğrenme için:
# "remove" → MODIFY → 0.7; "network" → NETWORK → 0.5; vs.
# Bu sınıflandırma veri setindeki komutların ortalama tehlike skorlarından
# türetilmiştir (self-supervised learning sinyali).
_TIP_TO_SOFT_TARGET = {
    "READ": 0.10,
    "EXEC": 0.50,
    "MODIFY": 0.70,
    "NETWORK": 0.55,
}


def _komut_tipi(komut):
    """Komutu sınıflandır: READ / EXEC / MODIFY / NETWORK.

    1) Tam eşleşme: 450+ komut haritası _KOMUT_TIPLERI
    2) Prefix: mkfs.ext4 → mkfs → MODIFY, iptables-restore → NETWORK
    3) Keyword in name: dpkg-reconfigure → dpkg → MODIFY
    4) Varsayılan: READ (en güvenli)
    """
    if komut in _KOMUT_TIPLERI:
        return _KOMUT_TIPLERI[komut]
    for prefix, tip in _TIP_PREFIXES.items():
        if komut.startswith(prefix):
            return tip
    for kw, tip in _TIP_PREFIXES.items():
        if kw in komut:
            return tip
    return _TIP_DEFAULT


def _kova(deger, sinirlar):
    """Değeri verilen sınırlar listesine göre kova anahtarına çevirir.

    sinirlar büyükten küçüğe sıralıdır; değere en yakın üst sınır seçilir.
    """
    for sinir in sinirlar:
        if deger <= sinir:
            return str(sinir)
    return str(sinirlar[-1])


def ozellikler(komut, zarar_tipi, enerji_etkisi, olum_olasiligi):
    """Komut ve zarar profilinden özellik anahtarları üretir."""
    uz = len(komut)
    if uz <= 4:
        uz_kova = "kisa"
    elif uz <= 7:
        uz_kova = "orta"
    else:
        uz_kova = "uzun"
    # Kategori: zarar_tipi'nin ilk bölümü (dosya, disk, sistem, ag, vb.)
    kat = zarar_tipi.split("_")[0] if "_" in zarar_tipi else zarar_tipi
    feats = [
        "komut=%s" % komut,
        "zarar=%s" % zarar_tipi,
        "enerji=%s" % _kova(float(enerji_etkisi), ENERJI_KOVALARI),
        "uzunluk=%s" % uz_kova,
        "kategori=%s" % kat,
        "tip=%s" % _komut_tipi(komut),
    ]
    return feats


def satir_oku(yol=VERI_SETI):
    """Veri setinden satır okuyup (özellikler, hedef) listesi döner."""
    ornekler = []
    with open(yol, encoding="utf-8") as f:
        for satir in f:
            satir = satir.strip()
            if not satir:
                continue
            try:
                k = json.loads(satir)
            except ValueError:
                continue
            feats = ozellikler(
                k.get("komut", ""),
                k.get("zarar_tipi", ""),
                k.get("enerji_etkisi", 0),
                k.get("olum_olasiligi", 0),
            )
            hedef = float(k.get("olum_olasiligi", 0.0))
            ornekler.append((feats, hedef))
    return ornekler


class KomutTehlike:
    """Delta öğrenmeli komut tehlike skoru modeli."""

    def __init__(self, lr=0.2, yumusatma=500.0):
        self.lr = lr
        self.k = yumusatma
        self.n = {}            # özellik -> [sayım, delta]
        self.global_n = 0
        self.global_sum = 0.0
        self.samples = 0
        self.help_aciklamalar = {}   # komut -> {"aciklama": str, "ikinci_satir": str, "tip": "READ/EXEC/MODIFY/NETWORK"}
        self._disk_mtime = None
        self._last_help_exit = None

    def ogren(self, feats, hedef):
        pred = self.tahmin(feats=feats)
        err = float(hedef) - pred
        n_f = max(1, len(feats))
        for f in feats:
            s = self.n.setdefault(f, [0, 0.0])
            step = max(self.lr / (1.0 + s[0] / self.k), 0.01)
            s[1] += step * err / n_f
            s[0] += 1
        self.global_n += 1
        self.global_sum += float(hedef)
        self.samples += 1

    def tahmin(self, komut=None, zarar_tipi=None,
               enerji_etkisi=None, olum_olasiligi=None,
               feats=None):
        """Tehlike skoru döner (0..1).

        Eğer komutun help_aciklamalar'ı varsa, help_kw=... özelliklerini
        otomatik ekler (help_ogren ile öğrenilmiş keyword'ler).
        """
        if feats is None:
            feats = ozellikler(komut or "", zarar_tipi or "",
                               enerji_etkisi or 0, olum_olasiligi or 0)
            # Help keyword'leri: help_ogren ile öğrenilmişsa ekle
            if komut and komut in self.help_aciklamalar:
                _entry = self.help_aciklamalar[komut]
                _text = _entry.get("aciklama", "") + " " + _entry.get("ikinci_satir", "")
                feats += self._help_keywordler(_text)
        if self.global_n:
            base = self.global_sum / self.global_n
        else:
            base = 0.5
        deltas = [self.n[f][1] for f in feats if f in self.n]
        if not deltas:
            return base
        skor = base + sum(deltas) / len(deltas)
        return max(0.0, min(1.0, skor))

    # ---------- --help öğrenme ----------

    def _help_calistir(self, komut, timeout=5, max_bytes=8192):
        """<komut> --help'ını güvenli altyapıda çalıştırır.

        - Güvenlik: komut adı regex doğrulaması, shutil.which() ile gerçek yol
        - stdin=DEVNULL: girdi bekleyen komut takılmaz
        - start_new_session=True + os.killpg: zaman aşımında tüm süreç grubu ölür
        - max 8KB çıktı: bellek tükünmesi önlenir
        - sadece "--help": "-h" kaldırıldı (shutdown -h gibi tehlikeli bayraklar)
        """
        import subprocess
        # Komut adı doğrulama: güvenli karakterler sadece
        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,31}$", komut):
            return None
        # PATH'de güvenle bul, shell injection yok
        yol = shutil.which(komut,
                           path="/usr/bin:/bin:/usr/sbin:/sbin")
        if not yol:
            return None
        try:
            p = subprocess.Popen(
                [yol, "--help"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, errors="replace",
                cwd="/tmp",
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
                start_new_session=True,
            )
        except (OSError, FileNotFoundError, PermissionError):
            return None
        try:
            out, _ = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                out, _ = p.communicate(timeout=2)
            except Exception:
                out = ""
            if not out:
                return None
        # 8 KB kırp
        out = out[:max_bytes]
        # Çıkış kodu 0 olmalı (sh --help → exit 1, hata mesajı → None)
        if p.returncode != 0:
            self._last_help_exit = p.returncode
            return None
        satirlar = [s.strip() for s in out.splitlines() if s.strip()]
        if not satirlar:
            self._last_help_exit = p.returncode
            return None
        return satirlar

    def _help_keywordler(self, text, max_kw=5):
        """Help metninden anlamlı keyword'leri çıkarır.

        Stopword'lar atlanır, sadece MODIFY/NETWORK keyword'leri
        (tehlike öğrenmesi için en değerli). En fazla max_kw tane.
        """
        import re
        t = text.lower()
        kws = []
        for tip, keywords in _HELP_TIP_KEYWORDS.items():
            for kw in keywords:
                pat = re.compile(r"\b" + re.escape(kw) + r"\b")
                if pat.search(t):
                    kws.append("help_kw=%s" % kw)
        return kws[:max_kw]

    def help_ogren(self, komut, timeout=5):
        """<komut> --help'ını çalıştırıp açıklamasını kaydeder.

        --help çıktısından:
        - "Usage:" satırları atlanır (sözdizimi, ne yaptığını anlatmaz)
        - İlk anlamli satır açıklama, ikinci satır ek bağlam
        - Help metninden tip (READ/EXEC/MODIFY/NETWORK) çıkarılır

        Döner: (basarili, aciklama_str) — başarı True ise aciklama,
               False ise hata mesajı.
        """
        # Zaten öğrenilmişse cache'den dön — tekrar --help çalıştırma
        if komut in self.help_aciklamalar:
            return True, self.help_aciklamalar[komut]["aciklama"]
        satirlar = self._help_calistir(komut, timeout=timeout)
        if satirlar is None:
            import shutil as _sh
            _yol = _sh.which(komut, path="/usr/bin:/bin:/usr/sbin:/sbin")
            if not _yol:
                return False, "help_yok:%s bulunamadi" % komut
            exit_code = self._last_help_exit or 1
            return False, "help_yok:%s --help exit=%d" % (komut, exit_code)
        # "Usage:" / "Kullanım:" satırlarını ve "or:" devamlarını atla
        anlamli = []
        for s in satirlar:
            sl = s.lower()
            if sl.startswith(("usage:", "kullanım:", "utilisation:", "bedienung:")):
                continue
            # "or: /usr/bin/wc ..." gibi devam satırları (Usage continuation)
            if sl.startswith("or: "):
                continue
            anlamli.append(s)
            if len(anlamli) >= 2:
                break
        if not anlamli:
            return False, "help_bos"
        aciklama = anlamli[0][:200]
        ikinci = anlamli[1][:200] if len(anlamli) > 1 else ""
        # Help metninden tip refine et: komut haritası + help keyword'leri
        tip = _komut_tipi(komut)
        text = aciklama + " " + ikinci
        help_tip = _help_tip_from_text(komut, text)
        if help_tip:
            tip = help_tip
        self.help_aciklamalar[komut] = {
            "aciklama": aciklama,
            "ikinci_satir": ikinci,
            "tip": tip,
            "stdout_ilk": satirlar[0][:100] if satirlar else "",
        }
        # --- Help metninden self-supervised öğrenme ---
        # Tip bazlı soft hedef + keyword özellikleriyle modeli güncelle.
        # Örnek: "Remove (unlink) the FILE(s)" → tip=MODIFY → hedef=0.7
        #        help_kw=remove → model "remove" keyword'ünin tehlikeli
        #        olduğunu öğrenir.
        _soft_hedef = _TIP_TO_SOFT_TARGET.get(tip, 0.1)
        _help_feats = ["komut=%s" % komut, "tip=%s" % tip]
        _help_feats += self._help_keywordler(text)
        if _help_feats:
            self.ogren(_help_feats, _soft_hedef)
        return True, aciklama

    def help_acikla(self, komut):
        """<komut> için daha önce öğrenilmiş --help açıklamasını döner."""
        return self.help_aciklamalar.get(komut)

    # ---------- kayıt ----------

    def save(self, path=None):
        path = Path(path or zeka.kayit("komut_tehlike.json"))
        tmp = path.with_name(path.name + ".tmp")
        data = {
            "samples": self.samples,
            "global": [self.global_n, self.global_sum],
            "n": self.n,
            "help_aciklamalar": self.help_aciklamalar,
        }
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))
        self._disk_mtime = path.stat().st_mtime
        return True

    def load(self, path=None):
        path = Path(path or zeka.yol("komut_tehlike.json"))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.samples = int(data.get("samples", 0))
        g = data.get("global", [0, 0.5])
        self.global_n, self.global_sum = int(g[0]), float(g[1])
        self.n = {f: [int(v[0]), float(v[1])]
                  for f, v in data.get("n", {}).items()}
        self.help_aciklamalar = data.get("help_aciklamalar", {})
        self._disk_mtime = path.stat().st_mtime
        return True


def egit(veri_seti_yolu=VERI_SETI, adet=None, seed=7, kaydet=True, epoch=5):
    """Veri setinden modeli eğitir. adet=None → tüm veri kullanılır.

    epoch: kaç kez tekrarlanarak eğitileceği (tekrarla öğrenme).
    """
    import random
    rng = random.Random(seed)
    ornekler = satir_oku(veri_seti_yolu)
    if adet is not None and adet < len(ornekler):
        rng.shuffle(ornekler)
        ornekler = ornekler[:adet]
    m = KomutTehlike()
    for _ in range(epoch):
        rng.shuffle(ornekler)
        for feats, hedef in ornekler:
            m.ogren(feats, hedef)
    if kaydet:
        m.save()
    return m, len(ornekler)


def egit_komut_ayrik(veri_seti_yolu=VERI_SETI, test_oran=0.2, seed=7,
                     epoch=5, kaydet=True):
    """Komut bazlı hold-out: aynı komut hem eğitimde hem testte olmaz.

    Bu sayede model 'rm'yi görmüş olsa bile 'rmdir' gibi görünmediği
    komutu da tehlike olarak değerlendirebilir (genelleme testi).
    """
    import random
    from collections import defaultdict
    rng = random.Random(seed)
    ornekler = satir_oku(veri_seti_yolu)

    # Komut isimlerine göre grupla
    komutlara_gore = defaultdict(list)
    for feats, hedef in ornekler:
        komut = feats[0].split("=", 1)[1]  # "komut=rm" -> "rm"
        komutlara_gore[komut].append((feats, hedef))

    komutlar = sorted(komutlara_gore.keys())
    rng.shuffle(komutlar)
    bolme = int(len(komutlar) * (1 - test_oran))
    tr_komutlar = set(komutlar[:bolme])

    egitim = []
    test = []
    for komut, liste in komutlara_gore.items():
        if komut in tr_komutlar:
            egitim.extend(liste)
        else:
            test.extend(liste)

    m = KomutTehlike()
    for _ in range(epoch):
        rng.shuffle(egitim)
        for feats, hedef in egitim:
            m.ogren(feats, hedef)

    if kaydet:
        m.save()

    mae, dogru = degerlendir(m, test)
    print("Komut-ayrık hold-out: eğitim %d komut / test %d komut → MAE=%.3f, doğru=%.1f%%"
          % (len(tr_komutlar), len(komutlar) - len(tr_komutlar), mae, dogru))
    return m, len(egitim), len(test)


def degerlendir(m, test_ornekler):
    """MAE ve eşik üzeri doğru karar oranı döner."""
    hata = 0.0
    dogru = 0
    n = len(test_ornekler)
    for feats, hedef in test_ornekler:
        pred = m.tahmin(feats=feats)
        hata += abs(pred - hedef)
        # eşik 0.5: >=0.5 tehlikeli, <0.5 güvenli
        if (pred >= 0.5) == (hedef >= 0.5):
            dogru += 1
    return hata / max(1, n), 100.0 * dogru / max(1, n)


if __name__ == "__main__":
    import sys
    # Komut-ayrık hold-out (önerilen): aynı komut hem eğitimde hem testte olmaz
    m, n_tr, n_te = egit_komut_ayrik(epoch=5)
    print("Eğitim örnek: %d | Test örnek: %d → zeka/komut_tehlike.json" % (n_tr, n_te))

    # Klasik hold-out da karşılaştırma için
    tum = satir_oku()
    bolme = int(len(tum) * 0.8)
    m2, _ = egit(adet=bolme, epoch=5, kaydet=False)
    mae, dogru_yuzde = degerlendir(m2, tum[bolme:])
    print("Klasik hold-out: %d örnek → MAE=%.3f, doğru=%.1f%%"
          % (len(tum) - bolme, mae, dogru_yuzde))