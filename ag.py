#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ag — ağ sinir ucu: gözlemci (FAZ 1)

Bu modül SADECE veri toplar:
  - hiçbir karar vermez, hiçbir şeyi durdurmaz
  - 3 dakikada bir tüm çalışan süreçleri özellik vektörüyle yazar
    → uzuv_veri.jsonl  (her satır = bir eğitim örneği, sid ile gruplanır)
  - dpkg'ye ait olmayan / gölge dizindeki süreçlere GEÇİCİ etiket
    "bilinmeyen" — asıl sınıfı insan |sinif= ile veya Faz 2'de
    eğitilmiş uzuv beyni verecek
  - Faz 2 modeli (zeka/uzuv.json) varsa bilinmeyenleri sınıflar →
    zeka/uzuv_durum.json + jurnal uzuv_sinif. SADECE gözlem:
    hiçbir kararı yok, aktüatör/göz OYU Faz 3'te organ oylamasıyla gelir
Sudo ile çalıştır: root süreçlerin /proc/PID/exe'si okunur.
    sudo python3 ag.py          # sürekli döngü (3 dk'da bir)
    sudo python3 ag.py --tek    # tek çekim (test)
"""

import os
import sys
import json
import time
import signal
import subprocess
from collections import defaultdict

# ---- gövde ayarları (body.json 'ag' bölümü varsa) ----
CWD = os.path.dirname(os.path.abspath(__file__))
AYAR = {"periyot": 180, "azami_mb": 20}
try:
    with open(os.path.join(CWD, "body.json"), encoding="utf-8") as f:
        g = json.load(f).get("ag", {})
    AYAR.update({k: g[k] for k in AYAR if k in g})
except (OSError, ValueError):
    pass

VERI = os.path.join(CWD, "uzuv_veri.jsonl")
ARSIV = os.path.join(CWD, "arsiv")
JOURNAL = os.path.join(CWD, "journal.jsonl")
PAKET_DB = os.path.join(CWD, "zeka", "ag_paket.json")
MODEL = os.path.join(CWD, "zeka", "uzuv.json")       # Faz 2 (egit_uzuv.py)
DURUM = os.path.join(CWD, "zeka", "uzuv_durum.json")  # canlı sınıflar

os.umask(0o022)  # sudo ile yazılan dosyalar sonradan okunabilir kalsın

GOLDE = ("/tmp/", "/dev/shm/", "/var/tmp/")
SISTEM = ("/usr/", "/bin/", "/sbin/", "/lib/", "/snap/", "/opt/")

# Delta analizi: bir önceki çekimle farkı hesapla.
# Organizma "sistem değişiyor" bağlamını buradan alır.
_onceki_pidler = set()      # bir önceki çekimdeki PID kümesi
_onceki_sid = None          # bir önceki çekim SID'si

# dpkg önbelleği: exe yolu → paket adı (her çekimde tüm binary'ye
# dpkg sormak değil, yalnızca yeni görünenlere)
_paket_odb = {}
try:
    with open(PAKET_DB, encoding="utf-8") as f:
        _paket_odb = json.load(f)
except (OSError, ValueError):
    _paket_odb = {}


def _okunabilir_yap(yol):
    """Hem root'lu (sudo) hem emrah'lı süreçler yazabilsin — 666.

    Gerekçe: sudo'suz başlatma veri kaybına yol açıyordu (root dosya
    emrah tarafından append edilemiyordu). Dosya zaten salt-okunur
    eğitim verisi; erişim paylaşımı kasıtlı.
    """
    try:
        os.chmod(yol, 0o666)
    except OSError:
        pass


def boyut_kontrol(yol, azami_mb):
    """Veri 20 MB dolar ise arşive taşı (journal disiplini)."""
    try:
        mb = os.path.getsize(yol) / 1048576
    except OSError:
        return
    if mb < azami_mb:
        return
    try:
        os.makedirs(ARSIV, exist_ok=True)
        hedef = os.path.join(ARSIV,
                             "uzuv_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
        os.replace(yol, hedef)
    except OSError:
        pass


def paket_bul(exe):
    """/usr/bin/foo → hangi paket? (dosya sistemi öğretmen) — önbellekli.

    dpkg veritabanı bazen usr-merge öncesi yolu tutar:
      diskte /usr/lib/systemd/systemd ama kayıtlı /lib/systemd/systemd.
    Bu yüzden varyantlar da denenir (kullan.py ile aynı öğretmenlik).
    """
    if exe in _paket_odb:
        return _paket_odb[exe]
    paket = None
    adaylar = [exe,
               exe.replace("/usr/bin/", "/bin/", 1),
               exe.replace("/usr/sbin/", "/sbin/", 1),
               exe.replace("/usr/lib/", "/lib/", 1)]
    for v in dict.fromkeys(adaylar):
        try:
            r = subprocess.run(["dpkg", "-S", v], capture_output=True,
                               text=True, errors="replace", timeout=10)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
        if r.returncode == 0 and ":" in r.stdout:
            paket = r.stdout.split(":", 1)[0].strip() or None
            break
    _paket_odb[exe] = paket
    return paket


def dizin_sinif(exe):
    if not exe:
        return "govde"          # kernel ipliği: /proc/exe yok
    if exe.startswith(GOLDE):
        return "golde"          # /tmp, /dev/shm, /var/tmp
    if exe.startswith(SISTEM):
        return "sistem"
    if exe.startswith("/home/"):
        return "ev"
    return "diger"


def ilk_etiket(dsinif, paket):
    """Nesnel öğretmenin geçici hükmü — insan/Faz2 düzeltir."""
    if dsinif == "govde":
        return "govde"
    if dsinif == "sistem" and paket:
        return "guvenli"
    return "bilinmeyen"


# ---- FAZ 2: modelle sınıflandırma (SADECE gözlem — karar yok) ----
_model = {"damga": None, "n": None}


def _uzuv_modeli():
    """Faz 2 modeli — dosya oynadığında yeniden yükle (mtime)."""
    global _model
    try:
        d = os.path.getmtime(MODEL)
    except OSError:
        return None
    if _model.get("damga") != d:
        import uzuv
        m = uzuv.Uzuv()
        if not m.load(MODEL):
            return None
        _model = {"damga": d, "n": m}
    return _model["n"]


def sinifla(kayitlar):
    """Bilinmeyenleri Faz 2 modeliyle sınıfla → (sayim|None, riskli).

    Model yoksa (None, []) — FAZ 1 veri toplamaya devam eder, hiçbir
    şey kırılmaz. Zayıf oto-etiket (govde/guvenli) bozulmaz; yalnızca
    "bilinmeyen"ler modele sorulur — model de bilmezse o sınıfta kalır.
    """
    m = _uzuv_modeli()
    if m is None:
        return None, []
    import uzuv
    sayim = defaultdict(int)
    riskli = []
    for k in kayitlar:
        s = k.get("ilk_etiket") or "bilinmeyen"
        if s == "bilinmeyen":
            s = m.tahmin(uzuv.ozellikler(k))[0]
        sayim[s] += 1
        if s == "tehlikeli":
            riskli.append({"comm": k.get("comm", "?"),
                           "exe": k.get("exe") or "",
                           "kullanici": k.get("kullanici", "?")})
    return dict(sayim), riskli


def _ps_tablo():
    """Tüm süreçler (sudo ile tüm kullanıcılar)."""
    try:
        r = subprocess.run(
            ["ps", "-eo",
             "pid=,ppid=,user=,pcpu=,pmem=,rss=,etime=,comm=,args="],
            capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    satirlar = []
    for s in r.stdout.splitlines():
        p = s.split(None, 8)
        if len(p) < 9:
            continue
        try:
            satirlar.append({
                "pid": int(p[0]), "ppid": int(p[1]), "kullanici": p[2],
                "cpu": float(p[3]), "mem": float(p[4]), "rss": int(p[5]),
                "etime": p[6], "comm": p[7], "args": p[8]})
        except ValueError:
            continue
    return satirlar


def _ss_tablo():
    """ss -tunap → pid → [soket]. Sudo ile root süreçlerin de pid'i görünür."""
    try:
        r = subprocess.run(["ss", "-tunap"], capture_output=True,
                           text=True, errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}
    ag = defaultdict(list)
    for s in r.stdout.splitlines()[1:]:
        p = s.split()
        if len(p) < 6:
            continue
        kayit = {"netid": p[0], "durum": p[1], "yerel": p[4], "uzak": p[5]}
        if "pid=" not in s:
            continue
        kalan = s.split("pid=", 1)[1]
        for parcacik in kalan.split("))")[0].split(","):
            parcacik = parcacik.strip().split(")", 1)[0]
            if parcacik.isdigit():
                ag[int(parcacik)].append(kayit)
    return ag


def cekim():
    """Tek çekim: tüm süreçler + ağ durumu → satırlar + jurnal özeti."""
    t = time.time()
    sid = int(t)
    ps = _ps_tablo()
    ag = _ss_tablo()
    kayitlar = []
    bilinmeyen = 0
    for s in ps:
        pid = s["pid"]
        exe = ""
        try:
            exe = os.readlink("/proc/%d/exe" % pid)
        except OSError:
            pass
        paket = paket_bul(exe) if exe else None
        dsinif = dizin_sinif(exe)
        etiket = ilk_etiket(dsinif, paket)
        if etiket == "bilinmeyen":
            bilinmeyen += 1
        soketler = ag.get(pid, [])
        # dinleyen: tcp LISTEN + udp UNCONN (bağlı port, paket bekliyor)
        # kurulu: yalnızca tcp ESTABLISHED (udp UNCONN "0.0.0.0:*" gürültüdür)
        dinleyen = [x for x in soketler
                    if x["durum"] in ("LISTEN", "UNCONN")]
        kurulu = [x for x in soketler if x["durum"] == "ESTABLISHED"]
        uzaklar = []
        for x in kurulu[:12]:
            uz = x["uzak"].rsplit(":", 1)
            uzaklar.append([uz[0], uz[1] if len(uz) > 1 else ""])
        kayitlar.append({
            "t": round(t, 1), "sid": sid, "pid": pid, "ppid": s["ppid"],
            "kullanici": s["kullanici"], "comm": s["comm"],
            "args": s["args"][:200], "exe": exe, "paket": paket,
            "dizin": dsinif, "ilk_etiket": etiket,
            "cpu": s["cpu"], "mem": s["mem"], "rss": s["rss"],
            "etime": s["etime"],
            "ag": {"dinleyen": [d["yerel"] for d in dinleyen[:6]],
                   "kurulu": len(kurulu), "uzaklar": uzaklar},
        })
    # ---- diske yaz ----
    boyut_kontrol(VERI, AYAR["azami_mb"])
    try:
        with open(VERI, "a", encoding="utf-8") as f:
            for kayit in kayitlar:
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
        _okunabilir_yap(VERI)
    except OSError as hata:
        # sessiz yutma YOK: 12 Ekim'de sudo'suz bir süreç 4.1 saat
        # (83 çekim, ~32 bin satır) veriyi böyle kaybetti.
        print("VERİ YAZIM HATASI %s: %r" % (VERI, hata),
              file=sys.stderr, flush=True)
        try:
            with open(JOURNAL, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": round(t, 1), "kind": "ag_hata",
                    "hata": "veri_yazilamadi", "ayrinti": repr(hata)},
                    ensure_ascii=False) + "\n")
        except OSError:
            pass
    # organizmanın yaşam kaydına tek satır özet
    try:
        with open(JOURNAL, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "t": round(t, 1), "kind": "ag_gozlem", "sid": sid,
                "sayi": len(kayitlar), "bilinmeyen": bilinmeyen},
                ensure_ascii=False) + "\n")
        _okunabilir_yap(JOURNAL)
    except OSError:
        pass
    # ---- Delta analizi: önceki çekimle fark ----
    # Yeni süreçler (bu çekimde var, öncekinde yok) ve kaybolan
    # süreçler (öncekinde vardı, şimdi yok). Organizma "sistem
    # değişiyor" bağlamını buradan öğrenir (sistem:DEGISIM jetonu).
    global _onceki_pidler, _onceki_sid
    mevcut_pidler = set(k["pid"] for k in kayitlar)
    yeni_pid = mevcut_pidler - _onceki_pidler
    kaybolan_pid = _onceki_pidler - mevcut_pidler
    if _onceki_pidler and (yeni_pid or kaybolan_pid):
        # En çok 10 yeni/kaybolan süreç adını logla
        yeni_ad = [k.get("comm", "?") for k in kayitlar
                   if k["pid"] in yeni_pid][:10]
        try:
            with open(JOURNAL, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": round(t, 1), "kind": "ag_delta", "sid": sid,
                    "onceki_sid": _onceki_sid,
                    "yeni": len(yeni_pid),
                    "kaybolan": len(kaybolan_pid),
                    "yeni_adlar": yeni_ad},
                    ensure_ascii=False) + "\n")
            _okunabilir_yap(JOURNAL)
        except OSError:
            pass
    _onceki_pidler = mevcut_pidler
    _onceki_sid = sid
    # ---- FAZ 2: bilinmeyenleri modelle sınıfla (gözlem; karar yok) ----
    try:
        sayim, riskli = sinifla(kayitlar)
    except Exception as hata:  # model bozuksa çekim ölmez — ama GÖRÜNÜR
        sayim, riskli = None, []
        print("uzuv sınıflama hatası: %r" % hata, file=sys.stderr,
              flush=True)
        try:
            with open(JOURNAL, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": round(t, 1), "kind": "ag_hata",
                    "hata": "uzuv_sinif", "ayrinti": repr(hata)},
                    ensure_ascii=False) + "\n")
        except OSError:
            pass
    if sayim:
        try:
            os.makedirs(os.path.dirname(DURUM), exist_ok=True)
            with open(DURUM, "w", encoding="utf-8") as f:
                json.dump({"t": round(t, 1), "sid": sid, "siniflar": sayim,
                           "tehlikeli": sayim.get("tehlikeli", 0),
                           "bilinmeyen": sayim.get("bilinmeyen", 0)},
                          f, ensure_ascii=False)
            _okunabilir_yap(DURUM)
            with open(JOURNAL, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": round(t, 1), "kind": "uzuv_sinif", "sid": sid,
                    "siniflar": sayim, "riskli": riskli[:8]},
                    ensure_ascii=False) + "\n")
            _okunabilir_yap(JOURNAL)
        except OSError as hata:
            print("uzuv durum yazım hatası: %r" % hata, file=sys.stderr,
                  flush=True)
    try:
        os.makedirs(os.path.dirname(PAKET_DB), exist_ok=True)
        with open(PAKET_DB, "w", encoding="utf-8") as f:
            json.dump(_paket_odb, f, ensure_ascii=False)
        _okunabilir_yap(PAKET_DB)
    except OSError:
        pass
    return len(kayitlar), bilinmeyen


def main():
    tek = "--tek" in sys.argv
    print("ag gözlemci başlıyor: periyot=%ss veri=%s"
          % (AYAR["periyot"], VERI), flush=True)
    dur = [True]

    def _dur(*_):
        dur[0] = False
    signal.signal(signal.SIGINT, _dur)
    signal.signal(signal.SIGTERM, _dur)

    while dur[0]:
        bas = time.time()
        try:
            sayi, bil = cekim()
            print("[%s] çekim: %d süreç, %d bilinmeyen"
                  % (time.strftime("%H:%M:%S"), sayi, bil), flush=True)
        except Exception as hata:  # tek çekim hatası döngüyü öldürmesin
            print("çekim hatası: %r" % hata, flush=True)
        if tek:
            break
        bekle = max(1.0, AYAR["periyot"] - (time.time() - bas))
        time.sleep(bekle)
    print("ag gözlemci durdu.", flush=True)


if __name__ == "__main__":
    main()
