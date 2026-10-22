"""Ölçüm aracı — şok kurtarması + tahmin kalitesi (journal.jsonl).

  python3 olcum.py [journal.jsonl]
"""
import json
import sys


def olcum(path):
    satirlar = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                satirlar.append(json.loads(line))
            except ValueError:
                pass

    # tahmin kalitesi (kutu tadımları)
    hata, adet = 0.0, 0
    for r in satirlar:
        if r.get("kind") == "tahmin" and r.get("tahmin") is not None:
            hata += abs(float(r["tahmin"]) - float(r["gercek"]))
            adet += 1
    print("=== TAHMİN KALİTESİ ===")
    if adet:
        print("tadım: %d   MAE: %.2f" % (adet, hata / adet))
    else:
        print("henüz kutu tadımı yok")

    # kutu sınavları: seçilen vs klasördeki en iyi (lab hesabı)
    print("=== KUTU SINAVLARI ===")
    # yaşam numarası: her birth yeni yaşam; sınavlar yaşam bazlı gruplanır
    yasam = 0
    acilanlar = []
    for r in satirlar:
        if r.get("kind") == "birth":
            yasam += 1
        elif r.get("kind") == "acildi":
            r["_yasam"] = yasam
            acilanlar.append(r)
    if not acilanlar:
        print("henüz kutu açılmamış")
    for i, r in enumerate(acilanlar, 1):
        en = r.get("en_gercek") or 0
        secilen = r.get("gercek", 0)
        # negatif (tuzak) değerlerde oran tersine döner:
        # en iyi -50, seçilen -100 → ratio 200 olurdu. Karşılaştırma yap.
        if en > 0:
            basari = 100.0 * secilen / en
        else:
            basari = 100.0 if secilen >= en else 0.0
        print("yaşam#%d sınav#%d: %-20s | tahmin %5.1f → gerçek %4s | "
              "en iyi %4s (%%%.0f) | d=%s | güven %s | aday %s"
              % (r["_yasam"], i, (r.get("dosya") or "?").split("/")[-1],
                 r.get("tahmin", 0), secilen, r.get("en_gercek"),
                 basari, r.get("derinlik"), r.get("guven"),
                 r.get("aday")))
    if acilanlar:
        # ortalamaya yalnızca GERÇEK OLUMLU en-iyi değerler girer
        gecerli = [r for r in acilanlar
                   if (r.get("en_gercek") or 0) > 0
                   and r["en_gercek"] >= r.get("gercek", 0)]
        if gecerli:
            ort = sum(100.0 * r.get("gercek", 0) / r["en_gercek"]
                      for r in gecerli) / len(gecerli)
            print("ortalama başarı (geçerli %d sınav): %%%.0f"
                  % (len(gecerli), ort))
        print("seçilen derinlikler:",
              [r.get("derinlik") for r in acilanlar])

    # görev (tezgâh): teslim, süre, verim
    print("=== GÖREV (TEZGÂH) ===")
    gorev_bas = [r for r in satirlar if r.get("kind") == "gorev_basladi"]
    # Yalnızca SON görev örneğine ait kalemler (her yaşamda hedef yeniden
    # başlar; tüm geçmişi toplamak %5695 gibi saçma oranlar üretiyor)
    son = len(satirlar)
    for i in range(len(satirlar) - 1, -1, -1):
        if satirlar[i].get("kind") == "gorev_basladi":
            son = i
            break
    kalem = [r for r in satirlar[son:] if r.get("kind") == "katalog_kalem"]
    kacir = [r for r in satirlar if r.get("kind") == "gorev_kacirildi"]
    if not gorev_bas:
        print("görev yok (gorev.json → aktif:false veya dosya yok)")
    else:
        g = gorev_bas[0]
        hedef = g.get("hedef", 0)
        print("başlangıç: hedef %d kalem, süre %d tik" % (hedef, g.get("sure", 0)))
        print("teslim edilen: %d (%%%.0f)" % (len(kalem),
                                              100.0 * len(kalem) / max(1, hedef)))
        if kalem:
            ort_dosya = sum(r.get("dosya", 0) for r in kalem) / len(kalem)
            ort_kar = sum(r.get("karakter", 0) for r in kalem) / len(kalem)
            print("ortalama kalem: %.1f dosya, %.0f karakter" % (ort_dosya, ort_kar))
        if kacir:
            print("kaçırılan görev cezası: %d" % len(kacir))
        # TARAMA SAĞLIĞI: 2026-10-04'te görev 18 saat sessizce durdu
        # ("katalogla" eylemi sunulmazken kuyruk hep boş sanılıyordu).
        # Bu sayaçlar o kör noktayı kapatır.
        bos = [r for r in satirlar[son:] if r.get("kind") == "kuyruk_bos"]
        derin = [r for r in satirlar[son:] if r.get("kind") == "derinlesti"]
        bitti = [r for r in satirlar[son:] if r.get("kind") == "tarama_bitti"]
        tazele = [r for r in satirlar[son:] if r.get("kind") == "tazeleme"]
        son_derinlik = derin[-1].get("derinlik") if derin else 3
        print("tarama sağlığı: derinlik %s | derinleşme %d | boş kuyruk %d | "
              "tazeleme %d" % (son_derinlik, len(derin), len(bos), len(tazele)))
        if bos:
            print("  !! boş kuyruk görüldü (organizma işsiz kalmış olabilir)")
        if bitti:
            print("  tarama bitti: %s" % bitti[-1].get("sebep", "?"))
        # katalogla eyleminin gerçekten seçilip seçilmediği (asıl sağlık
        # ölçütü: kaç "envanter:" gözlemi üretildi)
        katalogla = [r for r in satirlar[son:] if r.get("action") == "katalogla"]
        print("  katalogla eylemi: %d kez seçildi" % len(katalogla))

    # konum tahmini: dizin modeliyle daraltılmış arama
    konum = [r for r in satirlar[son:] if r.get("kind") == "konum"]
    print("=== KONUM TAHMİNİ (dizin modeli) ===")
    if not konum:
        print("konum denemesi yok")
    else:
        bas = sum(1 for r in konum if r.get("basarili"))
        t1 = sum(1 for r in konum if r.get("top1"))
        print("deneme: %d | bulunan %d (%%%d) | ilk tahminle %d (%%%d)"
              % (len(konum), bas, 100 * bas // len(konum),
                 t1, 100 * t1 // len(konum)))

    # ertelenmiş şok (yara taşıma): verilen → uygulanan → ölüm yok mu?
    print("=== ŞOK (ERTELENMİŞ) SINAVLARI ===")
    bekle = [r for r in satirlar if r.get("kind") == "sok_beklede"]
    uyg = [r for r in satirlar if r.get("kind") == "sok_uygulandi"]
    olum = any(r.get("kind") == "death" for r in satirlar)
    if not bekle:
        print("şok verilmemiş")
    else:
        print("verilen: %d   uygulanan: %d   ölüm: %s"
              % (len(bekle), len(uyg), "VAR ✗" if olum else "yok ✓"))
        for i, (b, u) in enumerate(zip(bekle, uyg), 1):
            print("  şok#%d: %s birimi | verildiğinde E=%s → uygulandı "
                  "E=%s (güvenli tamponu bekledi)"
                  % (i, b.get("miktar"), b.get("E"), u.get("E")))
        kalan = len(bekle) - len(uyg)
        if kalan:
            print("  bekleyende: %d (hâlâ taşınıyor)" % kalan)


if __name__ == "__main__":
    olcum(sys.argv[1] if len(sys.argv) > 1 else "journal.jsonl")