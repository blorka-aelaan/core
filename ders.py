"""ders — insan-gözlemcili düzeltme defteri.

Yanlış komut denemeleri bu dosyaya düşer:

    {"t":...,"hedef":"DOSYA_OKU","komut":"cmd:head","dogru":false,
     "ozet":"head: dizin hatası"}

Sen satır sonuna doğrusunu yazarsın (JSON bozulmaz, işaretleme ekle):

    ...} |dogrusu=cmd:wc

Organizma periyodik olarak dosyayı okur; düzeltmeyi doğrudan beyne işler
(keşiften değerli ödül) ve satırı |ok=1 ile işaretler — tekrar işlemez.
İki düzeltme arasına virgül konabilir: |dogrusu=cmd:wc,cmd:head

İlkeler:
  * insan düzeltmesi keşiften değerli (ODUL > kulland.py.ODUL)
  * yanlış komut ayrıca cezalandırılır (pekiştirme = yanlış değil, doğrusu)
  * yalnızca beyaz liste komutları kabul edilir (güvenlik)
  * atomik yazım: yarım satır asla okunmaz

Defter bir İŞ KUYRUĞUDUR, deneme arşivi değil:
  * yalnızca KEŞİF DEĞİL kestirim hatası yazılır (beyin emin olduğu
    halde yanıldıysa = gerçek bilgi boşluğu); keşif gürültüsü bedelini
    enerjiyle öder, defteri kirletmez (main.py mind.son_kesif'e bakar)
  * ham denemeler (hedef, komut) başına en fazla SIKISTIR_BAS tane
    açık örnek tutulur; fazlası arsiv/ders_*.jsonl'ye taşınır
  * tüm deneme geçmişi journal'daki "kullan" satırlarında kanıt olarak
    durur — sikistir() hiçbir şeyi yok etmez, yalnızca taşır
"""

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOSYA_ADI = "ders.jsonl"
ARSIV = ROOT / "arsiv"

ODUL = 8.0        # insan düzeltmesi: keşif (6) ve tuzak-keşfinden değerli
CEZA = -3.0       # yanlış komut: tersine öğrenme değil, bir daha denemesin
ISARET = "|ok="   # işaretleme: |dogrusu=... |ok=1
AAYRAC = " |dogrusu="
KOK_GORUNUM = "gorev:"   # beyin uyaranındaki görev tokenı öneki
SIKISTIR_BAS = 3   # her (hedef, komut) için kaç açık örnek kalsın


def _yol(yol=None):
    return Path(yol) if yol else (ROOT / DOSYA_ADI)


def toplu(hedef, dogrusu, yol=None):
    """Defterdeki AÇIK satırlarının tümüne aynı düzeltmeyi ekle.

    İnsan toplu sözü: "şu hedefin doğrusu şudur" — işaretlenmemiş
    her satıra |dogrusu=... ekler; oku() bir sonraki döngüde işler.
    İşaretli satırlara dokunmaz (zaten öğrenilmiş/reddedilmiş).
    → (islenen_satir_sayisi)
    """
    p = _yol(yol)
    if not p.exists():
        return 0
    try:
        satirlar = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return 0
    ek = 0
    yeni = []
    for satir in satirlar:
        kayit, _d, islenmis = _ayristir(satir)
        if (kayit is not None and not islenmis
                and kayit.get("hedef") == hedef and AAYRAC not in satir):
            satir = satir.rstrip() + AAYRAC + dogrusu
            ek += 1
        yeni.append(satir)
    if ek:
        tmp = p.with_name("%s.%d.tmp" % (p.name, os.getpid()))
        try:
            tmp.write_text("\n".join(yeni) + "\n", encoding="utf-8")
            os.replace(str(tmp), str(p))
        except OSError:
            return 0
    return ek


def _sikistir_satirlar(satirlar, bas=SIKISTIR_BAS):
    """Ham deneme satırlarını (hedef, komut) başına en fazla `bas`
    taneyle sınırla → (kalan_satirlar, arsivlenecekler).

    Yalnızca HAM satırlar sıkıştırılır: |dogrusu= (insan düzeltmesi
    bekleyen) ve |ok=1|işaretli satırlara asla dokunulmaz.
    """
    sayac = {}
    for i, s in enumerate(satirlar):
        kayit, dogrusu, islenmis = _ayristir(s)
        if kayit is None or dogrusu or islenmis:
            continue
        anahtar = (kayit.get("hedef") or "?", kayit.get("komut") or "?")
        sayac.setdefault(anahtar, []).append(i)
    silinen = set()
    for idxs in sayac.values():
        for i in idxs[:-bas] if bas > 0 else idxs:
            silinen.add(i)
    kalan = [s for i, s in enumerate(satirlar) if i not in silinen]
    arsiv = [satirlar[i] for i in sorted(silinen)]
    return kalan, arsiv


def sikistir(yol=None, bas=SIKISTIR_BAS):
    """Defter hijyeni: fazla ham örneği arsive taşı (silme, taşıma).

    journal'daki "kullan" satırları tüm deneme geçmini kanıtladığı
    için arşiv yalnızca disk alanını korur. → (tasinan, kalan_satir)
    """
    p = _yol(yol)
    if not p.exists():
        return 0, 0
    try:
        satirlar = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return 0, 0
    kalan, arsiv = _sikistir_satirlar(satirlar, bas)
    if not arsiv:
        return 0, len(satirlar)
    try:
        ARSIV.mkdir(exist_ok=True)
        hedef = ARSIV / ("ders_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
        with open(hedef, "a", encoding="utf-8") as f:
            for s in arsiv:
                f.write(s + "\n")
    except OSError:
        return 0, len(satirlar)   # arşivlenemediyse silme de yok
    tmp = p.with_name("%s.%d.tmp" % (p.name, os.getpid()))
    try:
        tmp.write_text("\n".join(kalan) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError:
        return 0, len(satirlar)
    return len(arsiv), len(kalan)


def yaz(hedef, komut, ozet, yol=None):
    """Yanlış denemeyi deftere düş (append)."""
    kayit = {"t": round(time.time(), 3), "hedef": hedef, "komut": komut,
             "dogru": False, "ozet": (ozet or "")[:200]}
    with open(_yol(yol), "a", encoding="utf-8") as f:
        f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


def _ayristir(satir):
    """(kayit, dogrusu, islenmis) — işaretleme JSON bozmadan satır sonunda."""
    if AAYRAC not in satir:
        ham, geri = satir, ""
    else:
        ham, geri = satir.split(AAYRAC, 1)
    islenmis = (ISARET in geri) if geri else False
    dogrusu = ""
    if geri:
        dogrusu = geri.split(ISARET, 1)[0].strip()
    try:
        kayit = json.loads(ham)
    except (ValueError, OSError):
        return None, "", islenmis
    return kayit, dogrusu, islenmis


def _gecerli(ad, beyaz):
    """cmd:ön eki + beyaz liste (insan yazsa da güvenlik ihlal edilemez)."""
    ad = ad.strip()
    if not ad:
        return None
    if not ad.startswith("cmd:"):
        ad = "cmd:" + ad
    return ad if ad.split(":", 1)[1] in beyaz else None


def oku(mind, jour, yol=None, beyaz=()):
    """İşaretlenmemiş düzeltmeleri beyne işle, satırları |ok=1 ile boşa.

    → (islenen_sayi, atlanan_sayi)
    """
    p = _yol(yol)
    if not p.exists():
        return 0, 0
    try:
        satirlar = p.read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return 0, 0

    islenen = 0
    atlanan = 0
    yeni_satirlar = []
    degisti = False
    for satir in satirlar:
        if not satir.strip():
            continue
        kayit, dogrusu, islenmis = _ayristir(satir)
        if kayit is None:
            # bozuk satır: olduğu gibi koru, dokunma
            yeni_satirlar.append(satir)
            continue
        if islenmis or not dogrusu:
            yeni_satirlar.append(satir)
            continue
        if islenmis is False and dogrusu:
            hedef = kayit.get("hedef") or "?"
            kok = KOK_GORUNUM + hedef
            eski = kayit.get("komut") or ""
            # 1) yanlış komut: "bunu bir daha deneme"
            if eski:
                ge = _gecerli(eski, beyaz)
                if ge:
                    mind.learn(kok, ge, CEZA)
            # 2) insanın dediği doğrusu: doğrudan pekiştir
            islenen_komutlar = []
            for ad in dogrusu.split(","):
                g = _gecerli(ad, beyaz)
                if not g:
                    continue
                mind.learn(kok, g, ODUL)
                islenen_komutlar.append(g)
            if islenen_komutlar:
                islenen += 1
                jour.log("ders_uygulandi", hedef=hedef,
                         yanlis=eski, dogrusu=islenen_komutlar,
                         odul=ODUL, ceza=CEZA)
                yeni_satirlar.append(satir.rstrip() + " " + ISARET + "1")
                degisti = True
            else:
                # beyaz liste dışı düzeltme: işaretleme, düzeltmeyi öğretme
                atlanan += 1
                jour.log("ders_red", hedef=hedef, dogrusu=dogrusu,
                         not_="beyaz liste dışı")
                yeni_satirlar.append(satir.rstrip() + " " + ISARET + "0")
                degisti = True

    # defter hijyeni: fazla ham örneği arsive taşı (satırlar zaten elde)
    kalan, arsiv_satirlar = _sikistir_satirlar(yeni_satirlar)
    if arsiv_satirlar:
        try:
            ARSIV.mkdir(exist_ok=True)
            h = ARSIV / ("ders_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
            with open(h, "a", encoding="utf-8") as f:
                for s in arsiv_satirlar:
                    f.write(s + "\n")
            yeni_satirlar = kalan
            degisti = True
        except OSError:
            pass  # arsivlenemediyse defter olduğu gibi kalır (silme yok)

    if degisti:
        # atomik: insan aynı anda düzenliyorsa bile yarım satır kalmaz
        tmp = p.with_name("%s.%d.tmp" % (p.name, os.getpid()))
        try:
            tmp.write_text("\n".join(yeni_satirlar) + "\n",
                           encoding="utf-8")
            os.replace(str(tmp), str(p))
        except OSError:
            pass
    return islenen, atlanan