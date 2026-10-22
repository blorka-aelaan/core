"""zeka.py — tüm zeka dosyaları tek klasörde: `zeka/`.

    zeka/brain.json          beyin ağırlıkları (Hebbian/delta)
    zeka/damak.json          isim-ödül modeli (egit.py üretir)
    zeka/risk.json           çalıştırılabilir risk modeli (egit_risk.py)
    zeka/guvenlik.json       şok kararı modeli (egit_guvenlik.py)
    zeka/guvenlik_veri.jsonl eğitim verisi (yaşam kaydı)
    zeka/dizin_kaynak.json   kaynak ailesi modeli (egit_dizin.py --kaynak)
    zeka/dizin_boyut.json    boyut kovası modeli (egit_dizin.py)
    zeka/uzuv.json           süreç sınıflandırıcı (egit_uzuv.py; Faz 2)

Tek gerçeklik: yüklerken `yol()` eski kök dizine geri düşer (göç
dönemi), kaydederken HEP zeka/ altına yazar — böylece dosyalar tek
yerde toplanır, eski kurulumlar da kırılmaz.
"""
from pathlib import Path

KOK = Path(__file__).resolve().parent
KLASOR = KOK / "zeka"


def yol(ad):
    """Model dosyası yolu: zeka/ varsa orası, yoksa eski kök konumu."""
    yeni = KLASOR / ad
    if yeni.exists():
        return yeni
    eski = KOK / ad
    if eski.exists():
        return eski
    return yeni


def kayit(ad):
    """Kayıt hedefi HEP zeka/ (yoksa oluştur)."""
    KLASOR.mkdir(exist_ok=True)
    return KLASOR / ad


def goc(yalnizca_yeni=True):
    """Doğuşta çağrılır: eski kök konumdaki taze dosyaları zeka/'ya al.

    Geçiş dönemi için: taşınmadan önce doğan canlı süreçler kodun eski
    sürümüyle çalışır ve kök dizine yazar (brain.json, damak.json,
    guvenlik_veri.jsonl). Göç yoksa bu yazmalar sessizce kaybolur.

    - json modelleri: kökteki dosya zeka/'dakinden TAZEYSE onu alır
      (yalnizca_yeni=False → her koşulda alır, yedekleyerek)
    - jsonl (guvenlik_veri): kayıp satırlar eklenir (yinelenen satır yok)
    Döner: taşınan dosya adları listesi.
    """
    alinan = []
    # brain.save() kapanışta bu dizine yazar; yoksa öğrenme kaybolur
    KLASOR.mkdir(exist_ok=True)
    for ad in ("brain.json", "damak.json", "risk.json", "guvenlik.json",
               "dizin_kaynak.json", "dizin_boyut.json", "dizin.json",
               "paket.json", "uzuv.json"):
        eski = KOK / ad
        if not eski.exists():
            continue
        yeni = KLASOR / ad
        if not yeni.exists() or (
                not yalnizca_yeni
                or eski.stat().st_mtime > yeni.stat().st_mtime + 1):
            if yeni.exists():
                # yedek: ezmeden önce son durumu sakla
                hedef_yedek = KLASOR / (ad + ".goc_yedek")
                try:
                    if hedef_yedek.exists():
                        hedef_yedek.unlink()
                    yeni.replace(hedef_yedek)
                except OSError:
                    pass
            eski.replace(yeni)
            alinan.append(ad)
    # satır bazlı: sadece eksik satırlar eklenir
    for ad in ("guvenlik_veri.jsonl",):
        eski = KOK / ad
        if not eski.exists():
            continue
        yeni = KLASOR / ad
        var = set()
        if yeni.exists():
            var = set(yeni.read_text(encoding="utf-8").splitlines())
        yeni_satir = [s for s in eski.read_text(encoding="utf-8").splitlines()
                      if s and s not in var]
        if yeni_satir:
            if not yeni.exists():
                yeni.touch()
            with open(yeni, "a", encoding="utf-8") as f:
                f.write("\n".join(yeni_satir) + "\n")
            eski.unlink()
            alinan.append("%s (+%d satır)" % (ad, len(yeni_satir)))
    return alinan
