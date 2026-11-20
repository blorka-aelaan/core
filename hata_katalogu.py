"""hata_katalogu.py — organizmanın kendi hatalarını sınıflandırır.

Öğrenme döngüsünde her (stimül, eylem, ödül) üçlüsünden önce
hata türü belirlenir ve journal'a 'kind: hata' ile yazılır.
meta_ogrenme bu bilgiyi lr/epsilon ayarında kullanır.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional
import json
from pathlib import Path

# Kara liste: Organizmanın "buraya girme/bunu deneme" dediği komutlar
KARA_LISTE_DOSYA = Path(__file__).resolve().parent / "zeka" / "kara_liste.json"


class HataTuru(str, Enum):
    YANLIS_KOMUT = "yanlış_komut"          # komut beklenildiği gibi çalışmadı
    YANLIS_BAGLAM = "yanlış_baglam"        # bağlam (enerji/açlık/tehlike) uyumsuz
    DUSUK_ODUL = "dusuk_odul"              # ödül eşiğin altında (çok kötü sonuç)
    TEKRAR_BASARISIZLIK = "tekrar_basarısızlık"  # aynı eylem N kez başarısız
    GUVEN_ZAFIYETI = "guven_zafiyeti"      # düşük güvenle alınan karar


@dataclass
class HataKaydi:
    tur: str
    stim: str
    eylem: str
    odul: float
    guven: float
    tik: int
    aciklama: str


def kara_liste_yukle():
    if KARA_LISTE_DOSYA.exists():
        try:
            with open(KARA_LISTE_DOSYA, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()


def kara_liste_ekle(komut):
    liste = kara_liste_yukle()
    liste.add(komut)
    KARA_LISTE_DOSYA.parent.mkdir(parents=True, exist_ok=True)
    with open(KARA_LISTE_DOSYA, "w") as f:
        json.dump(list(liste), f)


def siniflandir(
    odul: float,
    guven: float,
    eylem_basarili: bool,
    tekrarlayan_basarısız: bool,
    baglam_uygun: bool,
    eylem: str,
    dusuk_odul_esigi: float = -1.0,
    guven_esigi: float = 0.30,
) -> Optional[HataTuru]:
    """Verilen koşullara göre hata türünü döndürür; hata yoksa None."""

    # Eğer bir komut tekrarlı başarısız oluyorsa, onu kara listeye ekle
    if tekrarlayan_basarısız and not eylem_basarili:
        kara_liste_ekle(eylem) # Eylemi kara listeye ekle
        return HataTuru.TEKRAR_BASARISIZLIK

    if odul < dusuk_odul_esigi:
        return HataTuru.DUSUK_ODUL

    if guven < guven_esigi:
        return HataTuru.GUVEN_ZAFIYETI

    if not baglam_uygun:
        return HataTuru.YANLIS_BAGLAM

    if not eylem_basarili:
        return HataTuru.YANLIS_KOMUT

    return None