"""talep.py — Keşif → Talep → Onay hattı (salt-okunur, KURULUM YOK).

Organizma yeni aleti KENDİSİ KEŞFEDER ama KENDİSİ KURMAZ:
  1) KEŞİF: aday komutun sistemde var mı (shutil.which), paketi kurulu mu
     (dpkg-query), depoda aday mı (apt-cache policy) — üçü de salt-okunur.
  2) TALEP: eksik ama işe yarar bulunan komut zeka/talep.json'a yazılır
     (gerekçe + hedef tipi + kurulum komutu ÖNERİSİ).
  3) ONAY: insan talepler.md'yi okur, "kur" der → sudo apt-get insan elinde.
     Organizma ASLA kendisi kurmaz, ASLA aday komutu çalıştırmaz.

Doktrin (bkz. kullan.py BEYAZ, golge.py duvarı): yetki insanda kalır;
organizma yalnızca "şu komut şu hedefi çözerdi, kurulu değil" der.
Yeni komut BEYAZ'a yine eski yoldan girer: argv builder + judge + test.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

KOK = Path(__file__).resolve().parent
TALEP_JSON = KOK / "zeka" / "talep.json"
TALEP_MD = KOK / "talepler.md"

# (komut, paket, hedef_tipi, gerekce, judge_var_mi)
# judge_var_mi: mevcut hedef tipi + _dogrula varsa True → BEYAZ'a giriş kolay;
# False ise önce yargı yazmak gerekir (yeni hedef tipi demek).
ADAY_KOMUTLAR = [
    ("traceroute", "traceroute", "AG_SOR", "paketin yolunu izle", False),
    ("nstat", "iproute2", "AG_SOR", "ağ istatistiği (SNMP sayaçları)", True),
    ("lnstat", "iproute2", "AG_SOR", "linux netstat /proc/net istatistik", True),
    ("netstat", "net-tools", "AG_SOR", "bağlantı/yönlendirme tablosu", True),
    ("resolveip", "mariadb-client", "AG_SOR", "hostname↔IP çözümleme", True),
    ("nload", "nload", "AG_SOR", "canlı ağ kullanımı", False),
    ("lsof", "lsof", "SUREC_SOR", "açık dosya/süreç listesi", True),
    ("pstree", "psmisc", "SUREC_SOR", "süreç ağacı", True),
    ("tree", "tree", "DIZIN_LISTE", "iç içe dizin ağacı", True),
    ("realpath", "coreutils", "DOSYA_BUL", "sembolik çözümü gerçek yol", True),
    ("readlink", "coreutils", "DOSYA_BUL", "bağlantıyı çöz", True),
    ("lsblk", "util-linux", "DISK_SOR", "blok cihaz ağacı", True),
    ("lscpu", "util-linux", "DISK_SOR", "CPU bilgisi", False),
    ("free", "procps", "DISK_SOR", "bellek kullanımı", False),
    ("md5sum", "coreutils", "OKUMA", "dosya özeti (bütünlük)", False),
    ("sha256sum", "coreutils", "OKUMA", "dosya özeti (güçlü)", False),
    ("hexdump", "bsdextrautils", "OKUMA", "onaltılık görüntü", False),
    ("xxd", "xxd", "OKUMA", "onaltılık/düz çeviri", False),
    ("xz", "xz-utils", "DOSYA_OKU", "xz/lzma açma", True),
    ("bzip2", "bzip2", "DOSYA_OKU", "bzip2 açma", True),
    ("zstd", "zstd", "DOSYA_OKU", "zstd açma", True),
]

try:
    import golge
    _YASAK = (set(getattr(golge, "YASAKLI_FIIL", set()))
              | set(getattr(golge, "SARMALA", set()))
              | set(getattr(golge, "KABUKLAR", set())))
except Exception:
    _YASAK = set()


def _which(komut):
    return shutil.which(komut) is not None


def _dpkg_kurulu(paket):
    try:
        r = subprocess.run(["dpkg-query", "-W", "-f=${Status}", paket],
                           capture_output=True, text=True, timeout=8)
        return "install ok installed" in (r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _apt_aday(paket):
    try:
        r = subprocess.run(["apt-cache", "policy", paket],
                           capture_output=True, text=True, timeout=8)
        cikti = r.stdout or ""
        return "Candidate:" in cikti and "Candidate: (none)" not in cikti
    except (OSError, subprocess.TimeoutExpired):
        return False


def tara():
    talep, hazir, red = [], [], []
    # BEYAZ süzgeci: zaten beyaz listedeki komut "aday" değildir
    try:
        import kullan
        beyaz = set(kullan.BEYAZ)
    except Exception:
        beyaz = set()
    for komut, paket, hedef, gerekce, judge in ADAY_KOMUTLAR:
        if komut in beyaz:
            continue   # zaten BEYAZ'a girdi (Aşama 6 dahil)
        if komut in _YASAK:
            red.append({"komut": komut, "neden": "golge duvarinda"})
            continue
        var = _which(komut)
        kuruldu = _dpkg_kurulu(paket)
        aday = _apt_aday(paket)
        kayit = {"komut": komut, "paket": paket, "hedef_tipi": hedef,
                 "gerekce": gerekce, "judge_var": judge,
                 "sistemde_var": var, "paket_kurulu": kuruldu,
                 "depoda_aday": aday}
        kayit["oncelik"] = oncelik_skoru(kayit)
        if var:
            # sistemde hazır → kurulum gerekmez, BEYAZ'a giriş adayı
            kayit["durum"] = "hazir_beyaz_aday"
            hazir.append(kayit)
        elif kuruldu:
            kayit["durum"] = "paket_kurulu_ama_yok"
        elif aday:
            kayit["durum"] = "talep_edilebilir"
            kayit["kurulum_onerisi"] = "sudo apt-get install -y %s" % paket
            talep.append(kayit)
        else:
            kayit["durum"] = "depoda_yok"
    return {"talep": talep, "hazir": hazir, "red": red,
            "t": round(time.time(), 3)}


# Hedef tipi bazlı temel oncelik: ag/disk/surec sorgulari operasyonel
# olarak daha kritik; dosya/okuma isleri orta, digerleri dusuk.
ONCELIK_AGIRLIK = {
    "AG_SOR": 3.0, "DISK_SOR": 3.0, "SUREC_SOR": 3.0,
    "DOSYA_BUL": 2.0, "DOSYA_OKU": 2.0, "DOSYA_OLC": 2.0,
    "DOSYA_OZET": 2.0, "DOSYA_HAM": 2.0, "METIN_ARA": 2.0,
    "OKUMA": 2.0, "DIZIN_LISTE": 2.0,
}


def oncelik_skoru(kayit):
    """Talep oncelik puani (buyuk = once onaylanmali).

    Kriterler:
      - hedef tipi: sistem operasyonel sorgular daha once
      - judge_var: mevcut hedef tipine uygun, BEYAZ girisi kolay
      - kurulum_onerisi var: tam kurulum rehberi hazir
    """
    skor = float(ONCELIK_AGIRLIK.get(kayit.get("hedef_tipi", ""), 1.0))
    if kayit.get("judge_var"):
        skor += 1.0
    if kayit.get("kurulum_onerisi"):
        skor += 0.5
    return round(skor, 2)


def oncelik_yazi(skor):
    if skor >= 3.5:
        return "YUKSEK"
    if skor >= 2.0:
        return "ORTA"
    return "DUSUK"


def oncelik_nedeni(kayit):
    """Kisa aciklama: bu talep neden once onaylanmali?"""
    if kayit.get("judge_var"):
        return "mevcut hedef tipi (BEYAZ girisi kolay)"
    if kayit.get("hedef_tipi") in ("AG_SOR", "DISK_SOR", "SUREC_SOR"):
        return "sistem operasyonel"
    return "genel keşif"


def sirala(veri):
    """Talepleri oncelige gore sirala (buyukten kucuge; esitlikte komut ismi)."""
    talep = list(veri.get("talep", []))
    talep.sort(key=lambda t: (-t.get("oncelik", oncelik_skoru(t)),
                              str(t.get("komut", ""))))
    return talep


def kaydet(veri):
    """zeka/talep.json (atomik)."""
    TALEP_JSON.parent.mkdir(exist_ok=True)
    tmp = TALEP_JSON.with_name(TALEP_JSON.name + ".tmp")
    tmp.write_text(json.dumps(veri, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(TALEP_JSON)


def raporla(veri):
    """talepler.md — insanın okuyup onaylayacağı rapor."""
    lines = [
        "# 📩 Talep Raporu (organizmanın eksik aletleri)",
        "",
        "> **talep.py** üretti. **Kurulum YOK** — organizma yalnızca",
        "> ihtiyacını söyler; kurma yetkisi insandadır.",
        "",
        "Olusturma: %s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                       time.localtime(veri["t"])),
        "",
    ]
    talep = veri.get("talep", [])
    if talep:
        lines.append("## 🔶 Onay bekleyen talepler (%d)" % len(talep))
        lines.append("")
        lines.append("| Komut | Paket | Hedef | Öncelik | Gerekçe | Kurulum |")
        lines.append("|---|---|---|---|---|---|")
        for t in talep:
            _skor = t.get("oncelik", oncelik_skoru(t))
            lines.append("| `%s` | %s | %s | %.2f (%s) | %s | `%s` |" % (
                t["komut"], t["paket"], t["hedef_tipi"], _skor,
                oncelik_yazi(_skor), t["gerekce"],
                t.get("kurulum_onerisi", "")))
        lines.append("")
        sirali = sirala(veri)
        if sirali:
            lines.append("## 🎯 Akıllı onay önerisi (öncelik sırası)")
            lines.append("")
            lines.append("| Sıra | Komut | Paket | Hedef | Puan | Neden |")
            lines.append("|---|---|---|---|---|---|")
            for i, t in enumerate(sirali[:6], 1):
                _skor = t.get("oncelik", oncelik_skoru(t))
                lines.append("| %d | `%s` | %s | %s | %.2f | %s |" % (
                    i, t["komut"], t["paket"], t["hedef_tipi"], _skor,
                    oncelik_nedeni(t)))
            lines.append("")
            from collections import Counter
            _sayac = Counter(t["paket"] for t in sirali)
            _en_iyi = _sayac.most_common(1)
            if _en_iyi and _en_iyi[0][1] > 1:
                _paket, _adet = _en_iyi[0]
                lines.append("**Kümelenme:** `%s` paketi kurulduğunda %d talep bir karşılanır — bunu önce onaylamak en verimlidir." % (_paket, _adet))
                lines.append("")
        paketler = sorted({t["paket"] for t in talep})
        lines.append("**Toplu kurulum (onaylarsan):**")
        lines.append("")
        lines.append("```bash")
        lines.append("sudo apt-get install -y " + " ".join(paketler))
        lines.append("```")
        lines.append("")
        kolay = sum(1 for t in talep if t.get("judge_var"))
        lines.append("- %d komut mevcut hedef tipine uygun (judge var → "
                     "BEYAZ girişi kolay)" % kolay)
        lines.append("- %d komut için önce yeni hedef tipi + judge "
                     "yazılmalı" % (len(talep) - kolay))
        lines.append("")
    else:
        lines.append("## ✅ Onay bekleyen talep yok")
        lines.append("")
    hazir = veri.get("hazir", [])
    if hazir:
        lines.append("## 🟢 Sistemde hazır — BEYAZ'a giriş adayları "
                     "(kurulum gerekmez, sadece argv+judge gerekir) (%d)"
                     % len(hazir))
        lines.append("")
        lines.append("| Komut | Hedef | Öncelik | Gerekçe | Judge var? |")
        lines.append("|---|---|---|---|---|")
        for h in hazir:
            _skor = h.get("oncelik", oncelik_skoru(h))
            lines.append("| `%s` | %s | %.2f (%s) | %s | %s |" % (
                h["komut"], h["hedef_tipi"], _skor, oncelik_yazi(_skor),
                h["gerekce"],
                "✅ evet" if h.get("judge_var") else "❌ önce judge yaz"))
        lines.append("")
        kolay = sum(1 for h in hazir if h.get("judge_var"))
        lines.append("**Değerlendirme:** %d/%d komut için judge zaten var → "
                     "bunları BEYAZ'a eklemek tek tek argv builder + judge + "
                     "test ile aynı gün yapılabilir. Kalan %d için önce yeni "
                     "hedef tipi yazılmalı."
                     % (kolay, len(hazir), len(hazir) - kolay))
        lines.append("")
    if veri.get("red"):
        lines.append("## 🚫 golge duvarınca elenenler")
        lines.append("")
        for r in veri["red"]:
            lines.append("- `%s` — %s" % (r["komut"], r["neden"]))
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("**Sonraki adım (onaydan sonra):** BEYAZ'a eski yoldan:")
    lines.append("`kullan.py BEYAZ` + `_harita()` argv + `_dogrula()` judge + "
                 "`test_kullan.py`.")
    TALEP_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return TALEP_MD


def main():
    veri = tara()
    kaydet(veri)
    md = raporla(veri)
    print("talep: %d onay bekliyor, %d hazır BEYAZ adayı, %d golge elendi"
          % (len(veri["talep"]), len(veri.get("hazir", [])),
             len(veri["red"])))
    print("rapor: %s" % md)
    for t in veri["talep"]:
        print("  🔶 %s (%s) → %s | %s"
              % (t["komut"], t["paket"], t["hedef_tipi"],
                 t.get("kurulum_onerisi", "")))


if __name__ == "__main__":
    main()
