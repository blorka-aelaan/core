"""Öğrenme kanıtı — kanit_ogrenme.py

"Öğrendiğini nasıl kanıtlayabiliriz?" — salt-okunur, karşıt-olgusal
kontrollü deneysel yanıt. journal.jsonl ve zeka/brain.json asla
yazılmaz; canlı organizma döngüsü etkilenmez.

YÖNTEM (gözden geçirmesiyle düzeltildi):
  · Zamansal bölüme: jurnal ilk %85 EĞİTİM / son ~%15 TEST; replây
    beyinleri yalnızca eğitimden kurulur, test penceresini hiç görmez.
  · ust1() düzeltildi: her (uyaran, eylem) grubu KENDİ uyaranıyla
    puanlanır (eski sürümde döngü değişkeni dışarıda kalıyordu → tüm
    gruplar tek uyaranla puanlanıyordu), R'ler ORTALAMASIYLA ve
    beraberlik sabit-tohumlu paylaşılan sırayla kırılır (tüm beyinler
    aynı grup sırasını görür).
  · plasebo: R'ler karıştırılmış replây × N (varsayılan 50); p
    değerleri gerçek plasebo dağılımından hesaplanır.
  · Sıfır beyin sabit skor fonksiyonudur: korelasyonu TANIMSIZDIR —
    "r=0.000" kontrol sonucu sayılmaz, varyans ayrıca raporlanır.

DENEYLER:
  1) RETANSİYON/GENELLEME — test skor↔R: canlı (test'i gördü =
     retansiyon üst sınırı) vs replây-85 (görmedi = genelleme) vs
     plasebo vs sıfır.
  2) DOZ-TEPKİ — %0…%100 ince dozlar, sabit test penceresi.
  3) MEKANİZMA — ara:var→cmd:wc koşullu ağırlık replây-85'te + plasebo
     üstünlüğü + testteki gerçek R ile dünya uyumu.
  4) DAVRANIŞ — çevrimdışı politika: argmax üst-1 isabeti, politika
     değeri (seçilen eylemin ort. R'si), plasebo karşılaştırması.
  5) YENİ HEDEF — bilinmeyen token / görev kimliği ile sonda sınav
     (dürüst sınırla: yeni hedefin kendi doğru eylemi bilinemez).

Not: replây yalnızca jurnalleşen learn kayıtlarını (her 10. tik)
oynatır; canlı beyin ayrıca ders/gecikmeli kredi aldı → replây bir
alt sınırdır.
Veri kaynağı: en son jurnal arşivi (arsiv/journal_*.jsonl) + canlı
journal.jsonl — jurnal 20MB'da otomatik arşivlendiği için tarihsel
learn kayıtları arşivde kalır (tek başına canlı dosya yetersiz güç verir).
Kullanım: python3 kanit_ogrenme.py [--perm 2000] [--plasebo 50]
"""
import argparse
import json
import math
import random
from pathlib import Path

import brain

KOK = Path(__file__).resolve().parent
JURNAL = KOK / "journal.jsonl"
ARSIV = KOK / "arsiv"
BEYIN = KOK / "zeka" / "brain.json"


def jurnal_dosyalari():
    """Canlı jurnal + en son jurnal arşivi (kronolojik sırada).

    Jurnal 20MB'da main.py tarafından otomatik arşivlenir; tek başına
    canlı dosya arşivlenmiş learn kayıtlarını görmez. Epoch'un son
    parçası = en yeni arşiv + canlı dosya.
    """
    arsivler = sorted(ARSIV.glob("journal_*.jsonl")) if ARSIV.exists() else []
    dosyalar = list(arsivler[-1:]) + [JURNAL]
    return [d for d in dosyalar if d.exists()]


def learn_kayitlari(dosyalar):
    """Verilen jurnal dosyalarından learn satırlarını kronolojik okur
    (salt okuma; dosya sırası = kronoloji)."""
    kayitlar = []
    for yol in dosyalar:
        with open(yol, "r", encoding="utf-8", errors="replace") as f:
            for satir in f:
                if '"kind": "learn"' not in satir:
                    continue
                try:
                    j = json.loads(satir)
                except ValueError:
                    continue
                if ("stim" in j and "action" in j
                        and isinstance(j.get("R"), (int, float))):
                    kayitlar.append((j["stim"], j["action"],
                                     float(j["R"]), float(j.get("w") or 0.0)))
    return kayitlar


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def r_ve_perm(b, pairs, perm, rng):
    """skor↔R korelasyonu + permütasyon null'dan p değeri."""
    xs = [b.score(s, a) for s, a, _r, _w in pairs]
    rs = [p[2] for p in pairs]
    goz = pearson(xs, rs)
    null = 0
    for _ in range(perm):
        karis = rs[:]
        rng.shuffle(karis)
        if pearson(xs, karis) >= goz:
            null += 1
    return goz, (1 + null) / (perm + 1)


def sabit_skor(b, pairs):
    """Beyin tüm çiftlerde aynı skoru veriyorsa True (sabit fonksiyon)."""
    xs = [b.score(s, a) for s, a, _r, _w in pairs]
    if not xs:
        return True
    return max(xs) - min(xs) < 1e-15


def replay(b, kayitlar, karistir=False, rng=None):
    """Learn kayıtlarını sırayla beyne oynat (hatıra ile aynı kural)."""
    if karistir:
        rs = [r for _s, _a, r, _w in kayitlar]
        rng.shuffle(rs)
        veri = [(s, a, r) for (s, a, _r, _w), r in zip(kayitlar, rs)]
    else:
        veri = [(s, a, r) for s, a, r, _w in kayitlar]
    for s, a, r in veri:
        b.learn(s, a, r)
    return b


def grupla(pairs):
    """uyaran → {eylem: [R...]} — ortalama R ile adil karşılaştırma."""
    grup = {}
    for s, a, r, _w in pairs:
        grup.setdefault(s, {}).setdefault(a, []).append(r)
    return grup


def ust1(b, pairs, tohum=7):
    """Argmax gerçekten en yüksek ortalama R'li eylemi seçiyor mu?

    Döner: (doğru, toplam, şans, politika_değeri). politika_değeri =
    seçilen eylemlerin ortalama R'si. Beraberlik, sabit tohumlu
    paylaşılan sırayla kırılır: her beyin aynı grup sırasını ve aynı
    karışımı görür (adil karşılaştırma).
    """
    grup = grupla(pairs)
    yerel = random.Random(tohum)
    dogru = toplam = 0
    sans = 0.0
    deger = 0.0
    for s, harita in grup.items():      # DÜZELTME: her grup kendi uyaranı
        if len(harita) < 2:
            continue
        ort = {a: sum(rs) / len(rs) for a, rs in harita.items()}
        eylemler = list(ort)
        yerel.shuffle(eylemler)         # paylaşılan deterministik sıra
        en_iyi = max(ort.values())
        kazananlar = {a for a, r in ort.items() if abs(r - en_iyi) < 1e-12}
        secim = max(eylemler, key=lambda a: b.score(s, a))
        toplam += 1
        if secim in kazananlar:
            dogru += 1
        sans += 1.0 / len(eylemler)
        deger += ort[secim]
    if not toplam:
        return 0, 0, 0.0, 0.0
    return dogru, toplam, sans / toplam, deger / toplam


def agirlik_tablosu(b, etiketler):
    """(etiket, cmd:wc) bağlantı ağırlıkları — kuralın mekanizması."""
    return {e: b.w.get((e, "cmd:wc"), 0.0) for e in etiketler}


def main():
    ap = argparse.ArgumentParser(description="Öğrenme kanıtı (salt okuma)")
    ap.add_argument("--perm", type=int, default=2000,
                    help="permütasyon turu (p değeri alt sınırı)")
    ap.add_argument("--plasebo", type=int, default=50,
                    help="karışık-R plasebo beyin turu")
    args = ap.parse_args()
    perm = max(1, args.perm)
    npl = max(1, args.plasebo)
    rng = random.Random(42)   # tekrarlanabilir rapor

    kaynaklar = jurnal_dosyalari()
    kayitlar = learn_kayitlari(kaynaklar)
    n = len(kayitlar)
    print("=== ÖĞRENME KANITI (salt okuma — canlı dosyalara dokunulmaz) ===")
    print("jurnal kaynağı: %s" % " + ".join(d.name for d in kaynaklar))
    print("jurnal learn kaydı: %d" % n)
    if n < 400:
        print("yetersiz kayıt — kanıt için en az 400 learn kaydı gerekir")
        return

    # ---------- zamansal bölüme ----------
    test = kayitlar[-max(1, n // 7):]          # son ~%15: TEST
    egitim = kayitlar[:-len(test)]             # ilk %85: EĞİTİM
    print("zamansal bölüme: eğitim %d kayıt (replây tek kaynağı) · "
          "test %d kayıt (replây görmedi)" % (len(egitim), len(test)))

    egitim_cift = {(s, a) for s, a, _r, _w in egitim}
    test_yeni = [p for p in test if (p[0], p[1]) not in egitim_cift]
    olcum = test_yeni
    olcum_ad = "eğitimde hiç görülmemiş %d çift" % len(test_yeni)
    if sum(1 for _s, h in grupla(olcum).items() if len(h) >= 2) < 30:
        olcum = test
        olcum_ad = ("tüm test penceresi %d çift (bir kısmı eğitimde de "
                    "görülmüştü)" % len(test))
    print("davranış ölçüm seti: %s" % olcum_ad)

    # ---------- canlı beyin + yeniden-inşa doğruluğu ----------
    b_canli = brain.Brain()
    yuklenen = b_canli.load(BEYIN)
    sapmalar = [abs(b_canli.score(s, a) - w)
                for s, a, _r, w in kayitlar[-100:] if w]
    print("brain.json bağlantı: %d · jurnaldeki skora sapma (son 100): "
          "ort %.3f / enkötü %.3f"
          % (yuklenen,
             sum(sapmalar) / len(sapmalar) if sapmalar else -1.0,
             max(sapmalar) if sapmalar else -1.0))

    b_sifir = brain.Brain()                    # yalnız içgüdüler
    b_genel = replay(brain.Brain(), egitim)    # test'i hiç görmedi

    def r_test(b):
        return pearson([b.score(s, a) for s, a, _r, _w in test],
                       [p[2] for p in test])

    # ---------- plasebo kohortu (her tur ölçülüp atılır) ----------
    print("plasebo kohortu: %d beyin (eğitim R'leri karışık)..." % npl,
          flush=True)
    pl_r, pl_u, pl_v, pl_ara = [], [], [], []
    for _ in range(npl):
        bp = replay(brain.Brain(), egitim, karistir=True, rng=rng)
        pl_r.append(r_test(bp))
        d, t, _s, v = ust1(bp, olcum)
        pl_u.append(100.0 * d / t if t else 0.0)
        pl_v.append(v)
        pl_ara.append(bp.w.get(("ara:var", "cmd:wc"), 0.0)
                      - bp.w.get(("ara:yok", "cmd:wc"), 0.0))
        del bp

    # ---------- 1) RETANSİYON / GENELLEME ----------
    r_canli, p_canli = r_ve_perm(b_canli, test, perm, rng)
    r_genel, p_genel = r_ve_perm(b_genel, test, perm, rng)
    p_gecis = (1 + sum(1 for x in pl_r if x >= r_genel)) / (1 + npl)
    print("\n1) RETANSİYON/GENELLEME — test penceresinde (%d çift) "
          "skor↔R korelasyonu" % len(test))
    print("   canlı (retansiyon, bu pencereyi de gördü): r=%+.3f "
          "(perm p=%.3f)" % (r_canli, p_canli))
    print("   replây-85 (genelleme, görmedi)          : r=%+.3f "
          "(perm p=%.3f)" % (r_genel, p_genel))
    print("   plasebo×%d (karışık R)                   : ort %+.3f · "
          "aralık %+.3f…%+.3f · p(replây ≥ plasebo)=%.3f"
          % (npl, sum(pl_r) / npl, min(pl_r), max(pl_r), p_gecis))
    if sabit_skor(b_sifir, test):
        print("   sıfır beyin : sabit skor (varyans 0) → korelasyon "
              "TANIMSIZ; r=0.000 bir kontrol sonucu değildir")
    else:
        print("   sıfır beyin : beklenmedik — skorlar sabit değil")

    # ---------- 2) DOZ-TEPKİ ----------
    print("\n2) DOZ-TEPKİ — ince dozlar (test penceresi sabit, n=%d)"
          % len(test))
    doz_r = []
    for oran in (0.0, 0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 0.75, 1.0):
        kisit = egitim[:int(len(egitim) * oran)]
        r = r_test(replay(brain.Brain(), kisit))
        doz_r.append(r)
        print("   doz %3d%% (n=%4d): r=%+.3f"
              % (int(oran * 100), len(kisit), r))
    print("   (1. deneydeki plasebo tam doz ort: %+.3f)" % (sum(pl_r) / npl))

    # ---------- 3) MEKANİZMA ----------
    etiketler = ("ara:var", "ara:yok", "deneme:1", "deneme:2", "deneme:3+")
    print("\n3) MEKANİZMA — cmd:wc koşullu ağırlıkları")
    tbl_g = agirlik_tablosu(b_genel, etiketler)
    tbl_c = agirlik_tablosu(b_canli, etiketler)
    tbl_0 = agirlik_tablosu(b_sifir, etiketler)
    for e in etiketler:
        print("   %-9s replây-85 %+.3f · canlı %+.3f · sıfır %+.3f"
              % (e, tbl_g[e], tbl_c[e], tbl_0[e]))
    ara_g = tbl_g["ara:var"] - tbl_g["ara:yok"]
    ara_c = tbl_c["ara:var"] - tbl_c["ara:yok"]
    ara_0 = tbl_0["ara:var"] - tbl_0["ara:yok"]
    p_ara_g = (1 + sum(1 for x in pl_ara if x >= ara_g)) / (1 + npl)
    print("   ara etkisi (var−yok): replây-85 %+.3f · canlı %+.3f · "
          "sıfır %+.3f" % (ara_g, ara_c, ara_0))
    print("   plasebo ara etkisi  : ort %+.3f · aralık %+.3f…%+.3f · "
          "p(replây ≥ plasebo)=%.3f"
          % (sum(pl_ara) / npl, min(pl_ara), max(pl_ara), p_ara_g))
    wc_var = [r for s, a, r, _w in test if a == "cmd:wc" and "ara:var" in s]
    wc_yok = [r for s, a, r, _w in test if a == "cmd:wc" and "ara:yok" in s]
    if wc_var and wc_yok:
        print("   test gerçeği: wc+ara:var ort R=%+.3f (n=%d) · "
              "wc+ara:yok ort R=%+.3f (n=%d)  ← kural dünyayla uyumlu mu"
              % (sum(wc_var) / len(wc_var), len(wc_var),
                 sum(wc_yok) / len(wc_yok), len(wc_yok)))
    else:
        print("   test gerçeği: wc+ara çifti yetersiz (var %d / yok %d)"
              % (len(wc_var), len(wc_yok)))

    # ---------- 4) DAVRANIŞ (çevrimdışı politika değerlendirmesi) ----------
    print("\n4) DAVRANIŞ — çevrimdışı politika değerlendirmesi (%s)"
          % olcum_ad)
    sonuclar = {}
    for ad, b in (("canlı", b_canli), ("replây-85", b_genel),
                  ("sıfır", b_sifir)):
        d, t, s, v = ust1(b, olcum)
        sonuclar[ad] = (d, t, s, v)
        print("   %-9s üst-1 %d/%d = %%%.1f · şans %%%.1f · politika "
              "değeri %+.3f"
              % (ad, d, t, 100.0 * d / t if t else 0.0, s * 100, v))
    d_gen, t_gen, _s_gen, v_gen = sonuclar["replây-85"]
    u_gen = 100.0 * d_gen / t_gen if t_gen else 0.0
    p_u = (1 + sum(1 for x in pl_u if x >= u_gen)) / (1 + npl)
    p_v = (1 + sum(1 for x in pl_v if x >= v_gen)) / (1 + npl)
    print("   plasebo×%d üst-1 : ort %%%.1f (aralık %%%.1f…%%%.1f, "
          "p=%.3f)" % (npl, sum(pl_u) / npl, min(pl_u), max(pl_u), p_u))
    print("   plasebo×%d değer : ort %+.3f (aralık %+.3f…%+.3f, "
          "p=%.3f)" % (npl, sum(pl_v) / npl, min(pl_v), max(pl_v), p_v))

    # ---------- 5) YENİ HEDEF SINAVI ----------
    print("\n5) YENİ HEDEF — görülmemiş token ve görev kimliği "
          "(replây-85 beyin)")
    esit = toplam = 0
    for s, a, _r, _w in test[:300]:
        toplam += 1
        if b_genel.score(s, a) == b_genel.score(s + "|yeni:paket-adsiz", a):
            esit += 1
    print("   bilinmeyen token eklendi: %d/%d çiftte skor TAM AYNI "
          "(yeni token ağırlığı 0 → bozulma yok)" % (esit, toplam))
    degisti = toplam = 0
    grup_olcum = grupla(olcum)
    for s, harita in grup_olcum.items():
        par = s.split("|")
        if len(harita) < 2 or not any(x.startswith("gorev:") for x in par):
            continue
        s2 = "|".join("gorev:YENI_HEDEF" if x.startswith("gorev:") else x
                      for x in par)
        eylemler = sorted(harita)
        a1 = max(eylemler, key=lambda a: b_genel.score(s, a))
        a2 = max(eylemler, key=lambda a: b_genel.score(s2, a))
        toplam += 1
        if a1 != a2:
            degisti += 1
    if toplam:
        print("   görev kimliği görmediği varyantta: %d/%d grupta karar "
              "DEĞİŞTİ" % (degisti, toplam))
    else:
        print("   görev kimliği sınavı: gorev-tokenlı çok-eylem grup yok")
    print("   yorum: bilinmeyen token kararı bozmaz; gorev kimliği "
          "değişince yalnız onun ağırlıkları düşer — bağlam kuralları "
          "(ör. ara:var→wc) devrede kalır. Yeni hedefin KENDİ doğru "
          "eylemi için yeni sinyal gerekir; eşlemeli model bunu "
          "bilemez (bilinçli sınırdır).")

    # ---------- SONUÇ ÖZETİ (dürüst çerçeve) ----------
    print("\nSONUÇ ÖZETİ")
    kosullar = [
        ("genelleme: replây-85, görmediği testte r>0 (perm p<0.05)",
         r_genel > 0 and p_genel < 0.05),
        ("nedensellik: gerçek R replây'i plasebo dağılımının üstünde "
         "(p<0.05)", p_gecis < 0.05),
        ("doz-tepkî: her doz %0 dozun üstünde ve %100 > plasebo ort.",
         all(r > doz_r[0] for r in doz_r[1:])
         and doz_r[-1] > sum(pl_r) / npl),
        ("mekanizma: replây-85 ara:var→wc etkisi > 0 ve plasebo üstünde "
         "(p<0.05)", ara_g > 0 and p_ara_g < 0.05),
        ("davranış (%d grup): replây-85 politika değeri plasebo üstünde "
         "(p<0.05)" % t_gen, p_v < 0.05),
    ]
    for ad, ok in kosullar:
        print("  [%s] %s" % ("✓" if ok else "✗", ad))
    gecti = sum(1 for _a, ok in kosullar if ok)
    print("%d/%d koşul — bu ölçüm neyi kurar, neyi kurmaz:"
          % (gecti, len(kosullar)))
    print("  KURAR: jurnalden replây edilen ödül sinyali şans ve "
          "dağılım değişikliğiyle açıklanamaz (plasebo ayrışması), "
          "dozla güçlenir, görmediği veride ve bağlamda taşınıyor.")
    print("  KURMAZ: canlı organizmanın tüm davranışının öğrenmeden "
          "geldiğini. Ölçüm nesnesi replây'dir; canlı beyin ayrıca "
          "ders/gecikmeli kredi aldı (canlı satırları retansiyon "
          "üst sınırıdır). Sıfır beyin sabit skordur, 'r=0.000'ı "
          "kontrol değildir.")
    if gecti == len(kosullar):
        print("  ÖZET: Ödül istatistikleri replây'le tutuyor; sinyalin "
              "kaynağı learn olayları ve genelleme mevcut.")
    else:
        print("  ÖZET: Bazı koşullar sağlanmadı — sayıları incele; "
              "iddia ölçümün ötesine taşınmamalı.")


if __name__ == "__main__":
    main()
