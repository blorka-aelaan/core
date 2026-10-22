#!/usr/bin/env python3
"""olcum_zincir.py — zincir ogrenme olcum araci (kalici).

Amaç: zincir hedeflerinde (DOSYA_SAY / SUREC_SAY) ogrenme egilimini
sayisal olarak izlemek ve 5-asamali plan (kesif havuzu, recent sifirlama,
aile jetonu, konsolidasyon) oncesi/sonrasi karsilastirmayi mumkun kilmak.

Teşhis (2026-10-17, salt-okunur /tmp betikleri) su sonuca vardi:
  · dogru yollar biliniyor (ls->wc %96.9, find->wc %99.8, pgrep->wc %100)
  · wc ilk adim orani %12'de kilitli; wc 1. adimda neredeyse hic kazanmiyor
  · oturumlarin ~%61'i butceyi ayni komutu tekrarlayarak israf ediyor
  · KOK NEDEN: kesif (son_kesif) 1. adimda ogrenilmis aracagirliklere
    bakmaksizin rastgele bir komut seciyor; yanlis 1. adim MALIYET cezasi
    + hedef_deneme artisi uretiyor, wc daha secilmeden duraklama basliyor.

Olçtugumuz sey (her zincir oturumu icin):
  · oturum basarisi (dogru'ya ulasti mi)
  · 1. adim komut karisimi  (kesif kalitesi — bu dusmeli)
  · wc-ilk orani             (patoloji — bu dusmeli)
  · bilinen-yolu payi        (1. adim veri ureten adim mi — bu YUKSELMELI)
  · yol basarilari (adim1->adim2 cifti)  (kredi atamasi — bozulmamali)
  · israf orani              (ayni komutun tekrari — bu dusmeli)

Kullanim:
    python3 olcum_zincir.py                 # tum jurnal + arsiv, rapor bas
    python3 olcum_zincir.py --son 5000      # son 5000 kullan kaydi
    python3 olcum_zincir.py --json cikti.json
    python3 olcum_zincir.py --taban         # mevcut degerleri TABAN olarak
                                            #   olcum_zincir_taban.json'a yaz
    python3 olcum_zincir.py --karsilastir   # tabana gore DELTA bas
Kaynak ASCII-only.
"""
import argparse
import glob
import json
import os
import sys

KOK = os.path.dirname(os.path.abspath(__file__))
ZINCIR_TIPLERI = ("DOSYA_SAY", "SUREC_SAY")

# --- zincir hedefi "adim aileleri" -----------------------------------------
# Veri ureten (girdi adimi) komutlar: bunlar zinciri baslatmali.
# Tuketici (wc) asla 1. adim olmamali — ara bellek disinda calisir.
VERI_URETEN = {"ls", "find", "pgrep", "head", "cat", "du", "ss", "ps"}
TUKETICI = {"wc"}

# --- TABAN (baseline) sabitleri ---------------------------------------------
# 5-asamali plan ONCESI, 2026-10-17 salt-okunur teşhisten alinmistir.
# Bunlar "eski hali" referansidir; --karsilastir ile yeni olcum buna gore
# karsilastirilir. Duzenli calistirip --taban ile tazelenir.
TABAN = {
    "kayit_sayisi": 200000,        # teşhis penceresi (son N kullan kaydi)
    "DOSYA_SAY": {
        "oturum_basari": 0.55,     # oturumlarin basari orani (yaklasik)
        "wc_ilk": 0.12,            # wc 1. adim orani (patoloji tavan)
        "bilinen_yol": 0.47,       # 1. adim veri ureten komut (kalan kesif yanlis)
        "israf": 0.61,             # ayni komut tekrarlayan oturum payi
    },
    "SUREC_SAY": {
        "oturum_basari": 0.55,
        "wc_ilk": 0.12,
        "bilinen_yol": 0.47,
        "israf": 0.61,
    },
    # yol (adim1->adim2) basarilari — kredi atamasi sagligi (bozulmamali)
    "yol_basari": {
        "ls->wc": 0.969,
        "find->wc": 0.998,
        "pgrep->wc": 1.0,
    },
}


def _jurnal_dosyalari():
    """Canlı jurnal + arsiv jurnalleri (zaman sirasinda)."""
    arsiv = sorted(glob.glob(os.path.join(KOK, "arsiv", "journal_*.jsonl")))
    canli = os.path.join(KOK, "journal.jsonl")
    return arsiv + ([canli] if os.path.exists(canli) else [])


def _kullan_kayitlari(son=None):
    """kullan kayitlarini (zaman sirasinda) oku. son: son N kayit."""
    kayitlar = []
    for yol in _jurnal_dosyalari():
        try:
            f = open(yol, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            for satir in f:
                if '"kind": "kullan"' not in satir:
                    continue
                try:
                    j = json.loads(satir)
                except ValueError:
                    continue
                if j.get("hedef") in ZINCIR_TIPLERI:
                    kayitlar.append(j)
    kayitlar.sort(key=lambda j: j.get("t", 0))
    if son and len(kayitlar) > son:
        kayitlar = kayitlar[-son:]
    return kayitlar


def _oturumlar(kayitlar):
    """Zincir oturumlarini yeniden kur: deneme==1 yeni oturum baslatir.

    Donus: [(tip, [(deneme, komut_adi, dogru, odul), ...]), ...]
    """
    oturumlar = []
    cur = None
    for j in kayitlar:
        tip = j.get("hedef")
        den = j.get("deneme", 1)
        komut = (j.get("komut") or "?").replace("cmd:", "")
        if den == 1 or cur is None or cur[0] != tip:
            if cur:
                oturumlar.append(cur)
            cur = (tip, [])
        cur[1].append((den, komut, bool(j.get("dogru")), j.get("odul", 0)))
    if cur:
        oturumlar.append(cur)
    return oturumlar


def olcum(kayitlar):
    """Tum zincir kayitlarindan olcum sozlugu uret."""
    oturumlar = _oturumlar(kayitlar)
    sonuc = {"toplam_kayit": len(kayitlar), "toplam_oturum": len(oturumlar),
             "tip": {}, "yol_basari": {}}
    tip_stat = {t: {"oturum": 0, "basarili": 0, "wc_ilk": 0,
                    "veri_ilk": 0, "israf": 0} for t in ZINCIR_TIPLERI}
    ilk_kar = {t: {} for t in ZINCIR_TIPLERI}
    yol = {}
    for tip, adimlar in oturumlar:
        st = tip_stat[tip]
        st["oturum"] += 1
        if any(d for _d, _k, d, _o in adimlar):
            st["basarili"] += 1
        ilk = next((k for dn, k, _d, _o in adimlar if dn == 1), None)
        if ilk:
            ilk_kar[tip][ilk] = ilk_kar[tip].get(ilk, 0) + 1
            if ilk in TUKETICI:
                st["wc_ilk"] += 1
            if ilk in VERI_URETEN:
                st["veri_ilk"] += 1
        if any(adimlar[i][1] == adimlar[i - 1][1]
               for i in range(1, len(adimlar))):
            st["israf"] += 1
        if len(adimlar) >= 2:
            ak = "%s->%s" % (adimlar[0][1], adimlar[1][1])
            b, n = yol.get(ak, (0, 0))
            yol[ak] = (b + (1 if adimlar[1][2] else 0), n + 1)
    for t in ZINCIR_TIPLERI:
        st = tip_stat[t]
        o = max(1, st["oturum"])
        sonuc["tip"][t] = {
            "oturum": st["oturum"],
            "oturum_basari": round(st["basarili"] / o, 4),
            "wc_ilk": round(st["wc_ilk"] / o, 4),
            "bilinen_yol": round(st["veri_ilk"] / o, 4),
            "israf": round(st["israf"] / o, 4),
            "ilk_karisim": dict(sorted(ilk_kar[t].items(),
                                       key=lambda x: -x[1])),
        }
    for k, (b, n) in yol.items():
        if n >= 5:
            sonuc["yol_basari"][k] = {"basari": round(b / n, 4), "n": n}
    return sonuc


def rapor_bas(s, kaynak=""):
    """Olçum sozlugunu okunabilir rapor olarak bas."""
    print("# zincir olcum raporu %s" % kaynak)
    print("kayit=%d oturum=%d" % (s["toplam_kayit"], s["toplam_oturum"]))
    for t in ZINCIR_TIPLERI:
        d = s["tip"][t]
        print("\n== %s == oturum %d" % (t, d["oturum"]))
        print("   oturum basari : %.1f%%" % (100 * d["oturum_basari"]))
        print("   wc-ilk        : %.1f%%   (patoloji; dusmeli)" %
              (100 * d["wc_ilk"]))
        print("   bilinen-yol   : %.1f%%   (veri ureten 1. adim; yuksekmeli)" %
              (100 * d["bilinen_yol"]))
        print("   israf         : %.1f%%   (ayni komut tekrari; dusmeli)" %
              (100 * d["israf"]))
        ilk = list(d["ilk_karisim"].items())[:6]
        print("   1. adim karisimi: " +
              ", ".join("%s=%.0f%%" % (k, 100.0 * v / max(1, d["oturum"]))
                        for k, v in ilk))
    if s["yol_basari"]:
        print("\n== yol basarilari (adim1->adim2, n>=5) ==")
        for k, d in sorted(s["yol_basari"].items(), key=lambda x: -x[1]["n"]):
            print("   %-14s %.1f%%  (n=%d)" % (k, 100 * d["basari"], d["n"]))

def _taban_pencere(taban):
    """Taban sozlugunde karsilastirma penceresi (kayit sayisi) varsa dondur.

    --taban ile yazilan olcum sozlugunde "toplam_kayit" pencereyi tasir;
    eski sabit TABAN blogunda "kayit_sayisi" vardir (ikisini de kabul et).
    """
    if not isinstance(taban, dict):
        return 0
    for k in ("toplam_kayit", "kayit_sayisi"):
        n = taban.get(k)
        if isinstance(n, int) and n > 0:
            return n
    return 0


def _taban_tip(taban, t):
    """Taban tip metriklerini al — iki kabul et.

    --taban dosyasi olcum sozlugudur, metrikler "tip" altindadir; eski
    sabit TABAN blogu duzdur ("DOSYA_SAY" dogrudan ustte). Eski kod yalnizca
    duz formu aradigi icin dosya tabaninda TUM tip karsilastirmalari
    sessizce atlanir, arac her kosulda "belirgin fark yok" basardi
    (2026-10-18: DOSYA_SAY basarisi tabana gore dustu, denetim gormedi).
    """
    ici = taban.get("tip")
    if isinstance(ici, dict) and t in ici:
        return ici.get(t) or {}
    return taban.get(t) or {}


def taban_karsilastir(s, taban):
    """Mevcut olcum ile tabani karsilastir, delta bas.

    Donus: belirgin fark (|delta| > 0.02) var mi — test/regresyon icin.
    """
    print("\n# TABAN karsilastirmasi (yeni - taban)")
    fark_var = False
    for t in ZINCIR_TIPLERI:
        tb = _taban_tip(taban, t)
        y = s["tip"].get(t, {})
        for anahtar, etiket, iyi_yon in (
                ("oturum_basari", "basari", "yuksek"),
                ("wc_ilk", "wc-ilk", "dusuk"),
                ("bilinen_yol", "bilinen-yol", "yuksek"),
                ("israf", "israf", "dusuk")):
            yeni, eski = y.get(anahtar), tb.get(anahtar)
            if yeni is None or eski is None:
                continue
            d = yeni - eski
            ok = d < -0.01 if iyi_yon == "dusuk" else d > 0.01
            bayrak = "  <<" if ok else ("  !!" if abs(d) > 0.02 else "")
            print("  %s %-13s %-12s taban=%.3f yeni=%.3f delta=%+.3f%s" %
                  (t, anahtar, etiket, eski, yeni, d, bayrak))
            if abs(d) > 0.02:
                fark_var = True
    for k, ref in taban.get("yol_basari", {}).items():
        # TABAN sabitleri duz sayidir; olcum_zincir_taban.json ise tam
        # olcum sozlugudur (yol_basari[k] = {"basari":.., "n":..}).
        if isinstance(ref, dict):
            ref = ref.get("basari")
        if ref is None:
            continue
        y = s["yol_basari"].get(k)
        if y:
            d = y["basari"] - ref
            bayrak = "  !! DUSTU" if d < -0.05 else ""
            print("  YOL %-11s taban=%.3f yeni=%.3f delta=%+.3f%s" %
                  (k, ref, y["basari"], d, bayrak))
            if d < -0.05:
                fark_var = True
    if not fark_var:
        print("  (belirgin fark yok — ogrenme egilimi kararli)")
    return fark_var


def main():
    ap = argparse.ArgumentParser(description="zincir ogrenme olcum araci")
    ap.add_argument("--son", type=int, default=0,
                    help="son N zincir kullan kaydi (0 = tum)")
    ap.add_argument("--json", help="olcumu JSON dosyasina yaz")
    ap.add_argument("--taban", action="store_true",
                    help="mevcut degerleri TABAN dosyasina yaz")
    ap.add_argument("--karsilastir", action="store_true",
                    help="TABAN dosyasina gore delta bas")
    args = ap.parse_args()

    # TABAN pencere uyumu: --taban son-N penceresinde olculduysa
    # --karsilastir da ayni pencereyle sinirlanmali — tum jurnal (eski
    # patolojili donem dahil) ile son-60000 tabani karsilastirilinca
    # eski veri bugunu ezer, arac haksiz yere "regresyon" gosterir.
    taban = None
    if args.karsilastir:
        try:
            with open(os.path.join(KOK, "olcum_zincir_taban.json"),
                      encoding="utf-8") as f:
                taban = json.load(f)
        except (OSError, ValueError):
            taban = TABAN   # dosya yoksa sabit referans blogu
        if args.son == 0:
            pencere = _taban_pencere(taban)
            if pencere:
                args.son = pencere

    kayitlar = _kullan_kayitlari(son=args.son or None)
    if not kayitlar:
        print("zincir kullan kaydi bulunamadi", file=sys.stderr)
        return 1
    s = olcum(kayitlar)
    kaynak = "son %d" % args.son if args.son else "tum jurnal+arsiv"
    rapor_bas(s, kaynak)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        print("\nJSON yazildi: %s" % args.json)
    if args.taban:
        yol = os.path.join(KOK, "olcum_zincir_taban.json")
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        print("TABAN yazildi: %s" % yol)
    if args.karsilastir:
        taban_karsilastir(s, taban)
    return 0


if __name__ == "__main__":
    sys.exit(main())
