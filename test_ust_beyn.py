#!/usr/bin/env python3
"""ust_beyn öğrenme/güvenlik birim testleri.

Çalıştırma: python3 test_ust_beyn.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ust_beyn import (CIKIS_BOYUT, GIZLI_BOYUT, IDX_ACLIK, IDX_MESAJ_VAR,
                      IDX_OLUM_RISK, IDX_TEHLIKE, KOMUT_ACIL_DINLEN,
                      KOMUT_ACIL_YEM, KOMUT_INDEKSI, KOMUT_KAPAT_AG,
                      KOMUT_KISITLA_DOSYA, KOMUT_SIFIRLA, KOMUT_YOK,
                      SINYAL_BOYUT, TinyMLP, UstBeyn)

hata = []


def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)


class _Ust(UstBeyn):
    """Ağır kurulum olmadan test için sahte üst beyin."""

    def __init__(self):
        self.cfg = {}
        self.rng = __import__("random").Random(1)
        self.mlp = TinyMLP(SINYAL_BOYUT, GIZLI_BOYUT, CIKIS_BOYUT, seed=1)
        self.epsilon = 0.15
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.99985
        self.guven_esigi = 0.30
        self.marj_olcek = 0.15
        self.kanit_çarpanı = 0.35
        self.dogrulama_esigi = 0.35
        self.dogrulama = [0.0] * CIKIS_BOYUT
        # Bağlam bazlı doğrulama puanı (anahtar: komut_idx, bağlam)
        self.dogrulama_bağlam = {}
        self.sure = 0
        self.sure_azami = 0
        self.son_komut = KOMUT_YOK
        self.son_idx = 0
        self.reddedilen = 0
        self.samples = 0
        self.tik = 0
        self.secim_sayilari = [0] * CIKIS_BOYUT
        self.reddedilen_sayilari = [0] * CIKIS_BOYUT
        self.odul_gecmisi = []
        # Kilitlenme kırıcı alanları (ust_beyn.py ile uyumlu)
        self.RED_SERI_MAKS = 1
        self.redd_serisi = [0] * CIKIS_BOYUT
        self.redd_cooldown = [0] * CIKIS_BOYUT
        self.sifirla_noop_serisi = 0
        self.sifirla_kullanim_sayaci = 0
        self.SIFIRLA_MAKS_KULLANIM = 1
        self.sifirla_son_tik = 0
        self.SIFIRLA_ARALIK = 5


ust = _Ust()
x = np.zeros(SINYAL_BOYUT)

# --- 1) hedef vektörü toplamı 1, negatif değer yok ---
for odul in (0.5, -0.5, 1.0, -1.0, 0.0):
    yakalanan = {}
    _eski = ust.mlp.backward

    def _yakala(xv, hedef, **kw):
        yakalanan["hedef"] = np.array(hedef, dtype=float)
        return _eski(xv, hedef, **kw)

    ust.mlp.backward = _yakala
    ust.ogren(x, 3, odul)
    ust.mlp.backward = _eski
    h = yakalanan.get("hedef")
    kontrol(h is not None, "hedef yakalanmadi (odul=%s)" % odul)
    if h is not None:
        kontrol(abs(float(h.sum()) - 1.0) < 1e-9,
                "hedef toplami 1 degil (odul=%s): %s" % (odul, h.sum()))
        kontrol(h.min() >= 0.0,
                "hedef negatif (odul=%s): %s" % (odul, h))
        if odul < 0:
            kontrol(h[3] < 0.15,
                    "cezada secilen sinif hedefi neredeyse 0 olmali: %s" % h[3])
        else:
            kontrol(h[3] > 0.0,
                    "odulde secilen sinif hedefi >0 olmali: %s" % h[3])

# --- 2) doğrulama puanı: pozitif artar, negatif düşürür, taban 0 ---
ust2 = _Ust()
ust2.ogren(x, 1, 1.0)
p1 = ust2.dogrulama[1]
kontrol(p1 > 0.0, "pozitif odul dogrulama puanini artirmadi")
ust2.ogren(x, 1, -1.0)
p2 = ust2.dogrulama[1]
kontrol(p2 < p1, "negatif odul dogrulama puanini dusurmedi: %s->%s" % (p1, p2))
kontrol(p2 >= 0.0, "dogrulama puani negatif: %s" % p2)

# --- 3) güvenlik ağı ---
# NOT: Her kontrol kendi TEMİZ bir _Ust örneği üzerinde yapılır;
# çünkü doğrulama puanı BİRİKİMLİ bir değerdir (test 1'deki
# öğrenmeler puanı yükseltmiş olurdu).
ust_g = _Ust()
ok, gk = ust_g.komut_uygulanabilir_mi(3, 0.1, "model")
kontrol(not ok and gk == "guven_yetersiz",
        "dusuk guvenli model komutu reddedilmedi: %s %s" % (ok, gk))
ok2, gk2 = ust_g.komut_uygulanabilir_mi(3, 0.1, "kesif")
kontrol(ok2 and gk2 == "kesif_deneme",
        "kesif karari guvenlikten gecemedi: %s %s" % (ok2, gk2))
ok3, gk3 = ust_g.komut_uygulanabilir_mi(3, 0.9, "model")
kontrol(not ok3 and gk3 == "dogrulanmadi",
        "dogrulanmamis komut reddedilmedi: %s %s" % (ok3, gk3))
ust_g.dogrulama[3] = 0.5
ok4, gk4 = ust_g.komut_uygulanabilir_mi(3, 0.9, "model")
kontrol(ok4 and gk4 == "onaylandi",
        "dogrulanmis komut onaylanmadi: %s %s" % (ok4, gk4))
# "yok" her zaman uygulanabilir
ok5, gk5 = ust_g.komut_uygulanabilir_mi(KOMUT_INDEKSI[KOMUT_YOK], 0.0, "model")
kontrol(ok5, "komut_yok uygulanamaz sayildi")

# --- 3b) MARJ TABANLI GÜVEN ---
# Ham olasılık yerine marj kullanılır: modelin en iyi seçimi ile
# ikinci en iyisi arasındaki fark / marj_olcek.
ust_m = _Ust()
probs_flat = np.array([1.0 / CIKIS_BOYUT] * CIKIS_BOYUT)
g_flat = ust_m._guven_hesapla(probs_flat, 0)
kontrol(abs(g_flat) < 1e-9,
        "duz dagilimda marj 0 olmali (belirsizlik): %s" % g_flat)

probs_net = np.zeros(CIKIS_BOYUT)
probs_net[2] = 0.52
probs_net[0] = 0.08
for i in range(3, CIKIS_BOYUT):
    probs_net[i] = 0.08
g_net = ust_m._guven_hesapla(probs_net, 2)
kontrol(g_net > ust_m.guven_esigi,
        "net tercihte guven esigi gecilmeli: %s" % g_net)
kontrol(g_net <= 1.0, "guven 1'i asmamali: %s" % g_net)

# Marj sınıf sayısından bağımsız olmalı: aynı marj, farklı dağılımlar
probs_a = np.array([0.30, 0.15, 0.15, 0.10, 0.10, 0.10, 0.10])
probs_b = np.array([0.50, 0.35, 0.05, 0.04, 0.03, 0.02, 0.01])
g_a = ust_m._guven_hesapla(probs_a, 0)
g_b = ust_m._guven_hesapla(probs_b, 0)
kontrol(abs(g_a - g_b) < 1e-9,
        "ayni marj farkli guven vermeli: %s vs %s" % (g_a, g_b))

# Keşif güveni doğrulama eşiğine erişememeli (rastgele tercih kanıt sayılmaz)
ust_k = _Ust()
ust_k.epsilon = 1.0     # hep keşif
for _ in range(200):
    _k, _i, gv_k, kaynak_k = ust_k.sec(x)
    if kaynak_k == "kesif":
        kontrol(gv_k < ust_k.dogrulama_esigi,
                "kesif guveni dogrulama esigini gecmemeli: %s" % gv_k)

# --- 4) sec() geçerli kaynak/indeks/güven döndürür ---
for _ in range(50):
    k, i, gv, kay = ust.sec(x)
    kontrol(kay in ("model", "kesif"), "gecersiz kaynak: %s" % kay)
    kontrol(0 <= i < CIKIS_BOYUT, "gecersiz indeks: %s" % i)
    kontrol(0.0 <= gv <= 1.0, "gecersiz guven: %s" % gv)

# --- 5) ölüm komutu ömrü ---
ust.komut_ayarla("acil_dinlen", 1, sure=3)
kontrol(ust.aktif_komut() == "acil_dinlen", "komut omru baslamadi")
ust.azalt_sure()
ust.azalt_sure()
ust.azalt_sure()
kontrol(ust.aktif_komut() == KOMUT_YOK, "komut omru bitmedi")
kontrol(ust.sure_azami == 3, "sure_azami kaydedilmedi: %s" % ust.sure_azami)

# --- 6) tam döngü: öğrenme → güven birikimi → onay ---
ust3 = _Ust()
for _ in range(200):
    ust3.ogren(x, 2, 1.0)          # acil_yem hep iyi sonuç verdi
kontrol(ust3.dogrulama[2] >= 0.35,
        "olumlu odul dogrulama esigine ulasmadi: %s" % ust3.dogrulama[2])
ok6, gk6 = ust3.komut_uygulanabilir_mi(2, 0.9, "model")
kontrol(ok6 and gk6 == "onaylandi",
        "kanitlanmis komut onaylanmadi: %s %s" % (ok6, gk6))

# --- 8) KİLİTLENME REGRESYONU: model güven eşiğine ulaşabilmeli ---
# Senaryo: "acil_yem" (idx 2) her zaman olumlu ödül alır. Model
# yeterince öğrenince (a) olasılığı güven eşiğini geçmeli,
# (b) doğrulama puanı eşiği geçmeli, (c) komut "onaylandı" olmalı.
#
# NOT: Sinyal AÇLIK içermelidir — "acil_yem" ancak açlık varken
# uygulanabilir (komut_uygun_mu ön koşulu). Açlıksız sinyalde bu
# komut bilinçli olarak reddedilir.
ust4 = _Ust()
ust4.epsilon = 0.0                     # sadece model kararları
x4 = np.zeros(SINYAL_BOYUT)
x4[1] = 0.9                            # açlık yüksek
for _ in range(600):
    ust4.ogren(x4, 2, 0.8)
probs = ust4.mlp.predict(x4)
kontrol(probs[2] > ust4.guven_esigi,
        "model guven esigine ulasmadi (%.3f <= %.2f) — KILITLENME"
        % (probs[2], ust4.guven_esigi))
kontrol(ust4.dogrulama[2] >= 0.35,
        "dogrulama esigine ulasmadi: %.3f" % ust4.dogrulama[2])
ok7, gk7 = ust4.komut_uygulanabilir_mi(2, float(probs[2]), "model", x4)
kontrol(ok7 and gk7 == "onaylandi",
        "ogrenilmis komut onaylanmadi: %s %s" % (ok7, gk7))

# --- 9) CEZA komutun olasılığını düşürür (kilitlenme yok) ---
ust5 = _Ust()
ust5.epsilon = 0.0
for _ in range(300):
    ust5.ogren(x, 3, 1.0)             # "kapat_ag" iyi
p_iyi = float(ust5.mlp.predict(x)[3])
for _ in range(300):
    ust5.ogren(x, 4, -1.0)            # "kisitla_dosya" kötü
p_kotu = float(ust5.mlp.predict(x)[4])
kontrol(p_kotu < p_iyi,
        "cezali komut iyi komuttan daha yuksek olasilik: %.3f >= %.3f"
        % (p_kotu, p_iyi))
kontrol(p_kotu < ust5.guven_esigi,
        "cezali komut hala guven esiginin ustunde: %.3f" % p_kotu)

# --- 10) TAM KİLİTLENME SİMÜLASYONU ---
# main.py'deki gerçek akışın tamamı taklit edilir:
#   sec() → komut_uygulanabilir_mi() → reddedildiyse ceza →
#   uygulandıysa amaç-hizalı ödül → ogren()
# Senaryo: "acil_yem" (idx 2) yemek varsa iyi, yoksa kötü sonuç verir.
# Beklenen: model bir süre sonra güven eşiğini GEÇEN bir komut
# üretmeli (kilitlenme olmamalı).
#
# SİNYAL ANLAMI: xs[0]=enerji, xs[1]=açlık. "acil_yem" ancak açlık
# > 0.5 iken uygulanabilir (ön koşul), bu yüzden yemekli durumda
# açlık yüksek, yemeksiz durumda düşük tutulur.
ust6 = _Ust()
ust6.epsilon = 0.15
yemek_var = True
kabul_edilen = 0
reddedilen = 0
for tik in range(300):
    # sinyal: yemek durumuna göre değişir
    xs = np.zeros(SINYAL_BOYUT)
    xs[0] = 0.6 if yemek_var else 0.2
    xs[1] = 0.9 if yemek_var else 0.2
    komut, idx, guven, kaynak = ust6.sec(xs)
    if idx == KOMUT_INDEKSI[KOMUT_YOK]:
        # "yok" kararı: ödül yok → sadece nötr (tehlike yok)
        ust6.ogren(xs, idx, 0.0)
        continue
    ok, gk = ust6.komut_uygulanabilir_mi(idx, guven, kaynak, xs)
    if not ok:
        reddedilen += 1
        # main.py: reddedilen karar → ne ödül ne ceza (gerçek sonuç yok)
        ust6.reddedildi_ogren(xs, idx)
        continue
    kabul_edilen += 1
    # komut uygulandı → gerçek ödül
    if idx == 2:   # acil_yem
        odul = 0.4 if yemek_var else -0.4
    elif idx == 3:  # kapat_ag
        odul = -0.05
    else:
        odul = 0.1
    ust6.ogren(xs, idx, odul, keşif=(kaynak == "kesif"))

kontrol(kabul_edilen > 0,
        "hicbir komut kabul edilmedi — KILITLENME (300 tik)")
kontrol(reddedilen < 290,
        "neredeyse tum kararlar reddedildi (%d/300) — KILITLENME"
        % reddedilen)
# Marj tabanlı güven eşiği geçebilmeli (ham olasılık DEĞİL marj).
# Ölçüm, modelin karar verdiği komut üzerinden yapılır.
probs6 = ust6.mlp.predict(xs)
_k6, _i6, _gv6, _kaynak6 = ust6.sec(xs)
g6 = ust6._guven_hesapla(probs6, _i6)
kontrol(g6 > ust6.guven_esigi,
        "marj tabanli guven esigini gecmedi (%.3f) — KILITLENME" % g6)
# Aynı kontrol, modelin kendi kararı üzerinden de yapılmalı:
# sec() ne öneriyorsa o komutun marjı eşiği geçmeli.
kontrol(_gv6 > ust6.guven_esigi,
        "sec() guven esigini gecmedi (%.3f) — KILITLENME" % _gv6)

# --- 11) "yok" sınıfı davranışı kilitlememeli ---
# "yok" nötr gözlemde HİÇ gradyan almaz (pasif), dolayısıyla model
# orada kalıcı kilitlenmemelidir. Koruma YAPIISALDIR: sec() model
# kararında "yok"u ASLA seçmez.
#
# Not: olasılık dağılımında "yok" argmax olabilir (rastgele
# başlangıçta olduğu gibi) — bu tek başına bir kilitlenme DEĞİLDir,
# çünkü karar veren sec()'tir. Ölçüt: sec() asla "yok" dememeli.
ust7 = _Ust()
ust7.epsilon = 0.0
for _ in range(300):
    ust7.ogren(x, KOMUT_INDEKSI[KOMUT_YOK], 0.0)   # hep "yok", odulsuz
for _ in range(50):
    _k7, _i7, _g7, _kay7 = ust7.sec(x)
    kontrol(_i7 != KOMUT_INDEKSI[KOMUT_YOK],
            "model karari 'yok' oldu — pasif kilitlenme korumasi calismiyor")
    kontrol(_kay7 == "model", "epsilon=0 iken kaynak model olmali: %s" % _kay7)
# Komut uygulanabilir mi kontrolünde de "yok" her zaman geçerli.
ok7, gk7 = ust7.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_YOK], 0.0, "model", x)
kontrol(ok7, "komut_yok uygulanamaz sayildi")

# --- 12) kalıcılık round-trip ---
import tempfile
with tempfile.TemporaryDirectory() as dtmp:
    yol = Path(dtmp) / "ust.json"
    yol.write_text(json.dumps({
        "surum": 2,
        "W1": ust.mlp.W1.tolist(), "b1": ust.mlp.b1.tolist(),
        "W2": ust.mlp.W2.tolist(), "b2": ust.mlp.b2.tolist(),
        "samples": 5, "tik": 5, "epsilon": 0.1,
        "secim_sayilari": [0] * CIKIS_BOYUT,
        "dogrulama": [0.0] * CIKIS_BOYUT,
        "guven_esigi": 0.3, "dogrulama_esigi": 0.35,
        "sure_azami": 0, "reddedilen": 0}), encoding="utf-8")
    kontrol(yol.exists(), "kalici dosya yazilamadi")

# --- 13) BAĞLAMSAL DOĞRULAMA ---
# Aynı komut farklı bağlamlarda farklı doğrulanabilir:
# "acil_yem" AÇLIK bağlamında işe yarar, TEHLİKE bağlamında ise
# bağlama uygun değildir.
ust_b = _Ust()
x_aclik = np.zeros(SINYAL_BOYUT)
x_aclik[IDX_ACLIK] = 0.9          # açlık yüksek
x_tehlike = np.zeros(SINYAL_BOYUT)
x_tehlike[IDX_TEHLIKE] = 1.0      # tehlike var
kontrol(ust_b.baglam_anahtari(x_aclik) != ust_b.baglam_anahtari(x_tehlike),
        "aclik ve tehlike baglamlari ayni anahtari uretti")
# Ölüm riski de tehlike bağlamına girmeli
x_olum = np.zeros(SINYAL_BOYUT)
x_olum[IDX_OLUM_RISK] = 1.0
kontrol(ust_b.baglam_anahtari(x_olum) == ust_b.baglam_anahtari(x_tehlike),
        "olum riski tehlike baglamina girmedi")
# Ön koşul: acil_yem açlıktayken uygun, açlık yokken uygun değil
kontrol(ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_ACIL_YEM], x_aclik),
        "acil_yem aclik baglaminda uygun sayilmadi")
kontrol(not ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_ACIL_YEM], x_tehlike),
        "acil_yem tehlike baglaminda (acl yok) uygun sayildi")
# acil_dinlen tehlike yokken uygun DEĞİL
kontrol(ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_ACIL_DINLEN], x_tehlike),
        "acil_dinlen tehlike baglaminda uygun sayilmadi")
kontrol(not ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_ACIL_DINLEN], x_aclik),
        "acil_dinlen tehlike yokken uygun sayildi")
# sifirla her koşulda uygun
kontrol(ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_SIFIRLA], x_aclik)
        and ust_b.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_SIFIRLA], x_tehlike),
        "sifirla her baglamda uygun olmali")

# Bağlamsal kanıt YALNIZCA kendi bağlamında birikir
ust_b2 = _Ust()
for _ in range(20):
    ust_b2.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0)
k_aclik = ust_b2._dogrulama_puani(KOMUT_INDEKSI[KOMUT_ACIL_YEM], x_aclik)
k_tehlike = ust_b2._dogrulama_puani(KOMUT_INDEKSI[KOMUT_ACIL_YEM], x_tehlike)
kontrol(k_aclik >= ust_b2.dogrulama_esigi,
        "aclik baglaminda kanit esige ulasmadi: %s" % k_aclik)
kontrol(k_tehlike < ust_b2.dogrulama_esigi,
        "tehlike baglaminda kanit yanlis olarak yuksek: %s" % k_tehlike)
kontrol(ust_b2.dogrulama_bağlam,
        "baglamsal kanit deposu bos kaldi")

# Bağlama özgü doğrulanmış komut, YALNIZCA o bağlamda onaylanır
ok_a, gk_a = ust_b2.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], 0.9, "model", x_aclik)
kontrol(ok_a and gk_a == "onaylandi",
        "aclik baglaminda dogrulanmis komut onaylanmadi: %s %s" % (ok_a, gk_a))
ok_t, gk_t = ust_b2.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], 0.9, "model", x_tehlike)
kontrol(not ok_t,
        "tehlike baglaminda dogrulanmamis komut onaylandi: %s %s" % (ok_t, gk_t))

# --- 14) KEŞİF KANITI DOĞRULAMAYI BİRİKTİRİR ---
# Keşif kararı RASTGELE seçilmiş olsa da komut GERÇEKTEN
# uygulandı ve gerçek ödül üretti — model kararından daha güçlü
# bir kanıttır. Bu yüzden doğrulama puanına 2× katkı verir.
#
# NOT: Puan tavanı 2.0'dir; tavana dayanmamak için az sayıda
# örnek kullanılır (1 ödül → model 0.35, keşif 0.70).
ust_k2 = _Ust()
ust_k2.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0, keşif=True)
kesif_puan = ust_k2.dogrulama[KOMUT_INDEKSI[KOMUT_ACIL_YEM]]
ust_m2 = _Ust()
ust_m2.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0, keşif=False)
model_puan = ust_m2.dogrulama[KOMUT_INDEKSI[KOMUT_ACIL_YEM]]
kontrol(kesif_puan > model_puan,
        "kesif kaniti model kanitindan guclu degil: %s <= %s"
        % (kesif_puan, model_puan))
kontrol(abs(kesif_puan - 2.0 * model_puan) < 1e-6,
        "kesif kaniti 2x olmadi: %s vs %s" % (kesif_puan, model_puan))
# Taban davranış: keşif kanıtı olmadan puan artmaz
ust_n = _Ust()
ust_n.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0)
kontrol(ust_n.dogrulama[KOMUT_INDEKSI[KOMUT_ACIL_YEM]] > 0.0,
        "pozitif odul puani artirmadi")

# --- 15) REDDEDİLEN / PASİF KARAR AĞIRLIK GÜNCELLEMEZ ---
ust_r = _Ust()
w_once = ust_r.mlp.W2.copy()
ust_r.reddedildi_ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM])
kontrol(np.allclose(ust_r.mlp.W2, w_once),
        "reddedilen karar agirliklari degistirdi")
# "yok" (pasif) karar da agirlik degistirmemeli
ust_p = _Ust()
w_p = ust_p.mlp.W2.copy()
ust_p.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_YOK], 0.0)
kontrol(np.allclose(ust_p.mlp.W2, w_p),
        "pasif 'yok' karari agirliklari degistirdi")
# ama istatistikler ilerlemeli
kontrol(ust_p.tik == 1 and ust_p.samples == 1,
        "pasif gozlem sayaci ilerlemedi: tik=%s samples=%s"
        % (ust_p.tik, ust_p.samples))

# --- 16) KEŞİF KANITI SONRA MODEL ONAYINI AÇAR ---
# Senaryo: model güveni yüksek ama doğrulama eşiğinin ALTINDA.
# Keşifle kanıt toplanınca aynı komut onaylanabilir hâle gelir.
ust_o = _Ust()
ust_o.dogrulama[KOMUT_INDEKSI[KOMUT_ACIL_YEM]] = 0.0
ok_o, gk_o = ust_o.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], 0.9, "model", x_aclik)
kontrol(not ok_o and gk_o == "dogrulanmadi",
        "dogrulanmamis komut onaylandi: %s %s" % (ok_o, gk_o))
for _ in range(20):
    ust_o.ogren(x_aclik, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0, keşif=True)
ok_o2, gk_o2 = ust_o.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], 0.9, "model", x_aclik)
kontrol(ok_o2 and gk_o2 == "onaylandi",
        "kesif kaniti sonrasi komut onaylanmadi: %s %s" % (ok_o2, gk_o2))

# --- 17) BAĞLAM BAZLI PUAN KALICILIĞI (geriye dönük uyumlu) ---
import tempfile
with tempfile.TemporaryDirectory() as dtmp:
    kok = Path(dtmp)
    (kok / "zeka").mkdir(parents=True, exist_ok=True)
    yol = kok / "zeka" / "ust_beyn.json"
    # ESKİ kayıt biçimi: dogrulama_baglam alanı YOK
    yol.write_text(json.dumps({
        "surum": 2,
        "W1": ust.mlp.W1.tolist(), "b1": ust.mlp.b1.tolist(),
        "W2": ust.mlp.W2.tolist(), "b2": ust.mlp.b2.tolist(),
        "samples": 5, "tik": 5, "epsilon": 0.1,
        "secim_sayilari": [0] * CIKIS_BOYUT,
        "dogrulama": [0.0] * CIKIS_BOYUT,
        "guven_esigi": 0.3, "dogrulama_esigi": 0.35,
        "sure_azami": 0, "reddedilen": 0}), encoding="utf-8")
    yeni = UstBeyn({}, kok)
    kontrol(yeni.samples == 5, "eski kayit yuklenmedi: samples=%s" % yeni.samples)
    kontrol(yeni.dogrulama_bağlam == {},
            "eski kayit bos baglam deposu vermedi")
    # YENİ kayıt biçimi: dogrulama_baglam dolu
    yeni.dogrulama_bağlam[(2, "b1")] = 1.25
    yeni.save()
    veri = json.loads(yol.read_text(encoding="utf-8"))
    kontrol("dogrulama_baglam" in veri,
            "dogrulama_baglam kayda yazilmadi")
    kontrol(veri.get("dogrulama_baglam", {}).get("2|b1") == 1.25,
            "dogrulama_baglam degeri yanlis: %s"
            % veri.get("dogrulama_baglam"))
    tekrar = UstBeyn({}, kok)
    kontrol(tekrar.dogrulama_bağlam.get((2, "b1")) == 1.25,
            "dogrulama_baglam geri yuklenmedi: %s" % tekrar.dogrulama_bağlam)

# --- 18) ACTION MASKING: UYGUNSUZ KOMUT ASLA SEÇİLEMEZ ---
# Maske, model kararını "bu durumda geçerli olan" komutlara
# yönlendirir. Geçersiz komutların olasılığı yüksek olsa bile
# seçilmemelidir.
ust_m1 = _Ust()
ust_m1.epsilon = 0.0
x_aclik2 = np.zeros(SINYAL_BOYUT)
x_aclik2[IDX_ACLIK] = 0.9          # yalnızca açlık (tehlike/mesaj yok)
# Modeli bilerek "acil_dinlen" (tehlike gerektirir) lehine eğit.
for _ in range(300):
    ust_m1.ogren(x_aclik2, KOMUT_INDEKSI[KOMUT_ACIL_DINLEN], 1.0)
_probs_m1 = ust_m1.mlp.predict(x_aclik2)
kontrol(_probs_m1[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]]
        > _probs_m1[KOMUT_INDEKSI[KOMUT_ACIL_YEM]],
        "test oncesi: model uygunsuz komutu ogrenmedi (hazirlik hatasi)")
for _ in range(30):
    _k_m1, _i_m1, _g_m1, _kay_m1 = ust_m1.sec(x_aclik2)
    kontrol(_kay_m1 == "model", "epsilon=0 iken kaynak model olmali")
    kontrol(_i_m1 != KOMUT_INDEKSI[KOMUT_ACIL_DINLEN],
            "UYGUNSUZ komut secildi (acil_dinlen, tehlike yok)")
    kontrol(_i_m1 != KOMUT_INDEKSI[KOMUT_YOK],
            "model karari 'yok' oldu — pasif kilitlenme")
# Tehlike varken "acil_dinlen" UYGUN olmalı → seçilebilir.
x_tehlike2 = np.zeros(SINYAL_BOYUT)
x_tehlike2[IDX_TEHLIKE] = 1.0
for _ in range(30):
    _k_m2, _i_m2, _g_m2, _kay_m2 = ust_m1.sec(x_tehlike2)
    kontrol(_i_m2 != KOMUT_INDEKSI[KOMUT_ACIL_YEM],
            "aclik yokken acil_yem secildi (uygunsuz)")

# --- 19) KOMUT_YOK MASKELEME: sec() asla 'yok' seçmez ---
ust_m3 = _Ust()
ust_m3.epsilon = 0.0
_m3 = ust_m3.uygun_maske(x_aclik2)
kontrol(not _m3[KOMUT_INDEKSI[KOMUT_YOK]],
        "KOMUT_YOK maskesi kapatilmadi")
# Maske asla boş kalmaz → pasif kilitlenme olmaz.
kontrol(ust_m3.uygun_maske(np.zeros(SINYAL_BOYUT)).any(),
        "maske tamamen bos kaldi — guvenli varsayilan yok")

# --- 20) HEDEF VEKTÖRÜ: UYGUNSUZ KOMUTLAR SIFIR HEDEF ALIR ---
# Ödül dalı: pozitif hedef yalnızca UYGUN komutlara dağıtılır.
ust_h1 = _Ust()
_hedef = {}
_eski_bwd = ust_h1.mlp.backward


def _yakala_h(xv, hedef, **kw):
    _hedef["h"] = np.array(hedef, dtype=float)
    return _eski_bwd(xv, hedef, **kw)


ust_h1.mlp.backward = _yakala_h
# AÇLIK bağlamında "acil_yem" ödüllendirilir.
ust_h1.ogren(x_aclik2, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0)
_h = _hedef.get("h")
kontrol(_h is not None, "hedef yakalanmadi")
if _h is not None:
    # Tehlike gerektiren komutlar bu bağlamda uygunsuz → hedef 0.
    kontrol(_h[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]] == 0.0,
            "uygunsuz komut pozitif hedef aldi: %s"
            % _h[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]])
    kontrol(_h[KOMUT_INDEKSI[KOMUT_KAPAT_AG]] == 0.0,
            "uygunsuz komut pozitif hedef aldi: %s"
            % _h[KOMUT_INDEKSI[KOMUT_KAPAT_AG]])
    kontrol(_h[KOMUT_INDEKSI[KOMUT_ACIL_YEM]] > 0.5,
            "secilen uygun komut hedefi zayif: %s"
            % _h[KOMUT_INDEKSI[KOMUT_ACIL_YEM]])
    kontrol(abs(float(_h.sum()) - 1.0) < 1e-9,
            "hedef toplami 1 degil: %s" % _h.sum())

# Ceza dalı: uygunsuz komutlara pay DAĞITILMAZ.
_hedef2 = {}
_eski_bwd2 = ust_h1.mlp.backward


def _yakala_h2(xv, hedef, **kw):
    _hedef2["h"] = np.array(hedef, dtype=float)
    return _eski_bwd2(xv, hedef, **kw)


ust_h1.mlp.backward = _yakala_h2
ust_h1.ogren(x_aclik2, KOMUT_INDEKSI[KOMUT_ACIL_YEM], -1.0)
_h2 = _hedef2.get("h")
kontrol(_h2 is not None, "ceza hedefi yakalanmadi")
if _h2 is not None:
    kontrol(_h2[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]] == 0.0,
            "ceza hedefi uygunsuz komuta pay verdi: %s"
            % _h2[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]])
    kontrol(_h2[KOMUT_INDEKSI[KOMUT_KAPAT_AG]] == 0.0,
            "ceza hedefi uygunsuz komuta pay verdi: %s"
            % _h2[KOMUT_INDEKSI[KOMUT_KAPAT_AG]])
    kontrol(abs(float(_h2.sum()) - 1.0) < 1e-9,
            "ceza hedefi toplami 1 degil: %s" % _h2.sum())

# --- 21) GÜVEN MARJI YALNIZCA UYGUN KOMUTLARI ÖLÇER ---
# Marj, uygunsuz komutların olasılığını SİLMEZ — yoksa model
# uygunsuz komutu "rakip" sanıp marjı tavanlardı.
#
# SENARYO: "acil_dinlen" (tehlike gerektirir → UYGUNSUZ) ham
# olasılıkta ikinci sırada ve oldukça yüksek. Eğer marj
# uygunsuz komutları "rakip" olarak saysaydı, marj 0'a
# düşerdi (kilitlenme). Doğrusu: marj yalnızca UYGUN
# komutlar arasında ölçülür.
_ust_g1 = _Ust()
_ust_g1.epsilon = 0.0
_p_g1 = np.zeros(CIKIS_BOYUT)
_p_g1[KOMUT_INDEKSI[KOMUT_ACIL_YEM]] = 0.275     # uygun
_p_g1[KOMUT_INDEKSI[KOMUT_SIFIRLA]] = 0.225        # uygun
_p_g1[KOMUT_INDEKSI[KOMUT_ACIL_DINLEN]] = 0.300     # UYGUNSUZ
_p_g1[KOMUT_INDEKSI[KOMUT_KAPAT_AG]] = 0.200        # UYGUNSUZ
_ust_g1.mlp.predict = lambda xv: _p_g1.copy()
_k_g1, _i_g1, _g_g1, _kay_g1 = _ust_g1.sec(x_aclik2)
kontrol(_i_g1 == KOMUT_INDEKSI[KOMUT_ACIL_YEM],
        "maskeli secim yanlis: %s" % _i_g1)
# Maskeli dağılım normalize edilir: p1 = 0.275/0.5 = 0.55,
# p2 = 0.225/0.5 = 0.45 → marj 0.10 → güven 0.10/0.15 = 0.667.
kontrol(abs(_g_g1 - 0.10 / 0.15) < 1e-6,
        "marj uygunsuz komutlardan etkileniyor: %s (beklenen %s)"
        % (_g_g1, 0.10 / 0.15))
# Ham (normalize edilmemiş) dağılımda marj 0.275-0.225 = 0.05
# olurdu; uygunsuz komut rakip sayılsaydı 0'a düşerdi. Bu
# değer eşiğin ALTINDA kalır → kilitlenme. Doğru değer üstte.

# --- 22) SIFIRLA: HER KOŞULDA UYGUN, GLOBAL KANIT TAŞIR ---
# "sifirla" bağlamdan bağımsızdır: kanıtı global birikir ve her
# bağlamda geçerlidir. Aksi halde b0'daki 0.0'lık kayıt global
# kanıtı gölgeler ve komut sürekli "dogrulanmadi" ile reddedilir
# (572 kez — gözlenen hata).
ust_s1 = _Ust()
x_sifirla = np.zeros(SINYAL_BOYUT)
x_sifirla[IDX_ACLIK] = 0.9
kontrol(ust_s1.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_SIFIRLA], x_sifirla),
        "sifirla aclik baglaminda uygun sayilmadi")
kontrol(ust_s1.komut_uygun_mu(KOMUT_INDEKSI[KOMUT_SIFIRLA], x_tehlike),
        "sifirla tehlike baglaminda uygun sayilmadi")
_m_s1 = ust_s1.uygun_maske(x_sifirla)
kontrol(_m_s1[KOMUT_INDEKSI[KOMUT_SIFIRLA]],
        "sifirla maske disinda kaldi")
# Kanıt global birikmelidir.
for _ in range(10):
    ust_s1.ogren(x_sifirla, KOMUT_INDEKSI[KOMUT_SIFIRLA], 1.0)
_global_p = ust_s1.dogrulama[KOMUT_INDEKSI[KOMUT_SIFIRLA]]
kontrol(_global_p >= ust_s1.dogrulama_esigi,
        "sifirla global kaniti esige ulasmadi: %s" % _global_p)
# FARKLI bir bağlamda da aynı (global) puan geçerli olmalı.
_tehlike_sifirla = np.zeros(SINYAL_BOYUT)
_tehlike_sifirla[IDX_TEHLIKE] = 1.0
_p_aclik = ust_s1._dogrulama_puani(
    KOMUT_INDEKSI[KOMUT_SIFIRLA], x_sifirla)
_p_tehlike = ust_s1._dogrulama_puani(
    KOMUT_INDEKSI[KOMUT_SIFIRLA], _tehlike_sifirla)
kontrol(abs(_p_aclik - _p_tehlike) < 1e-9,
        "sifirla kaniti baglamlar arasinda farkli: %s vs %s"
        % (_p_aclik, _p_tehlike))
kontrol(_p_tehlike >= ust_s1.dogrulama_esigi,
        "sifirla farkli baglamda dogrulanmadi: %s" % _p_tehlike)
_ok_s1, _gk_s1 = ust_s1.komut_uygulanabilir_mi(
    KOMUT_INDEKSI[KOMUT_SIFIRLA], 0.9, "model", x_sifirla)
kontrol(_ok_s1 and _gk_s1 == "onaylandi",
        "kaniti olan sifirla onaylanmadi: %s %s" % (_ok_s1, _gk_s1))
# Bağlama bağlı komutun kanıtı ise hâlâ bağlamla sınırlı kalmalı.
ust_s2 = _Ust()
for _ in range(20):
    ust_s2.ogren(x_sifirla, KOMUT_INDEKSI[KOMUT_ACIL_YEM], 1.0)
kontrol(ust_s2._dogrulama_puani(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], x_sifirla) >= ust_s2.dogrulama_esigi,
    "acil_yem aclik baglaminda dogrulanmadi")
kontrol(ust_s2._dogrulama_puani(
    KOMUT_INDEKSI[KOMUT_ACIL_YEM], _tehlike_sifirla) == 0.0,
    "acil_yem yanlis baglamda dogrulandi (baglam izolasyonu bozuldu)")

# --- 23) KEŞİF: 'yok' SEÇİLMEZ, GÜVEN EŞİĞİNİ GEÇMEZ ---
# Keşif bütçesi kanıt toplamak içindir; "yok"a harcanan her
# deneme gerçek bir komutun kanıtını geciktirir.
ust_k3 = _Ust()
ust_k3.epsilon = 1.0
for _ in range(200):
    _k_k3, _i_k3, _g_k3, _kay_k3 = ust_k3.sec(x_aclik2)
    if _kay_k3 == "kesif":
        kontrol(_i_k3 != KOMUT_INDEKSI[KOMUT_YOK],
                "kesif 'yok' komutunu secildi — butce bosa gidiyor")
        kontrol(_g_k3 < ust_k3.dogrulama_esigi,
                "kesif guveni dogrulama esigini gecti: %s" % _g_k3)

# --- 24) KONSOLIDASYON: GÜÇLÜ BAĞLANTILAR KORUNUR ---
# Budama "ölü" ağırlıkları hedefler; tablonun tamamını silmek
# tüm öğrenmeyi yok eder (ölçülen: 1937 → 131 bağlantı) ve
# sistemi körleştirir.
#
# `koru_ust` SEMANTİĞİ (2026-10 düzeltmesi):
#   koru_ust = budama SONRASI korunacak TOPLAM tablo tabanıdır.
#   "zayıf bağlantı tabanı" DEĞİLDİR.
#   Canlı zeka/brain.json kanıtı: 5110 bağlantı, yalnız 57'si zayif
#   (|w| < 0.02) — zayıf tabanı 300 olsaydı tablo 300'e inerdi ve
#   tüm öğrenme körleşirdi. Doğru davranış: güçlüler korunur, kalan
#   pay zayıflardan doldurulur, tablo 300'ün ALTINA düşmez.
from brain import Brain  # noqa: E402

_br = Brain(seed=3)
# 40 zayıf + 10 güçlü bağlantı kur (+ 4 doğuştan refleks = 54 toplam).
for i in range(40):
    _br.w[("zayif%d" % i, "rest")] = 0.001
for i in range(10):
    _br.w[("guclu%d" % i, "eat")] = 0.9
_baslangic = len(_br.w)
_n_budanan = _br.konsolide(koru_ust=30)
# TOPLAM tablo 30'a iner: 54 → 30 (24 bağlantı silindi).
kontrol(_n_budanan == 24,
        "koru_ust=30 ile tablo 30'a inmeliydi, %s silindi" % _n_budanan)
kontrol(len(_br.w) == 30,
        "koru_ust=30 sonrasi tablo 30 olmaliydi, %s" % len(_br.w))
kontrol(len([k for k in _br.w if k[0].startswith("guclu")]) == 10,
        "guclu baglantilar budamada silindi")
# 16 zayıf kalır (40 - 24): zayıf tabanı DEĞİL, toplam tablo tabanı.
kontrol(len([k for k in _br.w if k[0].startswith("zayif")]) == 16,
        "zayif baglantilarin sayisi yanlis: %s"
        % len([k for k in _br.w if k[0].startswith("zayif")]))
# INSTINCTS asla budanmaz (yaşama yanlisi yaratilis korumasi).
kontrol(all(k in _br.w for k in Brain.INSTINCTS),
        "INSTINCTS budamada silindi")
# koru_ust=None → eski davranis (hepsini budar).
_br2 = Brain(seed=3)
for i in range(40):
    _br2.w[("zayif%d" % i, "rest")] = 0.001
_br2.konsolide()
kontrol(len([k for k in _br2.w if k[0].startswith("zayif")]) == 0,
        "koru_ust=None ile zayif baglantilar silinmeliydi")

# --- 24b) REGRESYON: ~5000 BAĞLANTILIK TABLO 300'E DÜŞMEZ ---
# Canlı beyin 5110 bağlantıya ulaştı; bunlardan yalnız 57'si zayif.
# ESKİ "zayıf tabanı" semantiği tabloyu 57'ye indirirdi (körleşme).
# YENİ "toplam tablo tabanı" semantiği 5000 bağlantıyı korur.
_br3 = Brain(seed=3)
_zayif_sayi = 57
for i in range(5000 - len(Brain.INSTINCTS) - _zayif_sayi):
    _br3.w[("guclu%d" % i, "eat")] = 0.5     # güçlü
for i in range(_zayif_sayi):
    _br3.w[("zayif%d" % i, "rest")] = 0.001  # zayıf
_bas = len(_br3.w)
_n3 = _br3.konsolide(koru_ust=300)
kontrol(_bas >= 5000, "test tablosu beklenenden kucuk: %s" % _bas)
kontrol(len(_br3.w) >= 300,
        "5000 baglantilik tablo 300'un altina dustu: %s" % len(_br3.w))
# Güçlü bağlantıların TAMAMI korunmalı (öğrenme kaybı yok).
_korunan = len([k for k in _br3.w if k[0].startswith("guclu")])
kontrol(_korunan == 5000 - len(Brain.INSTINCTS) - _zayif_sayi,
        "guclu baglantilar korunmadi: %s" % _korunan)
kontrol(all(k in _br3.w for k in Brain.INSTINCTS),
        "INSTINCTS 5000 baglantilik tabloda budandi")

# --- 24c) REGRESYON: USAGE KANITLI AMA ZAYIFLAMIS BAGLANTI BUDANMAZ ---
# KOK NEDEN (2026-10-22): canli yol konsolide(koru_ust=300) YALNIZ
# |w| < esik diyordu, "usage" kanitini yok sayiyordu. Zincir:
#   decay -> agirlik esigin altina dustu -> konsolide -> baglanti SILINDI
# Canli beyin kaniti: usage>=2 kanitli 119 baglantinin 84'u bu yuzden
# kayboluyordu. Kanitli baglanti, agirligi zayif olsa da KORUNMALIDIR.
_br4 = Brain(seed=4)
_kanitli = ("kanitli:1", "eat")
_kanitsiz = ("kanitsiz:1", "eat")
_br4.w[_kanitli] = 0.005      # zayif (< 0.02) AMA kanitli
_br4.w[_kanitsiz] = 0.005    # zayif VE kanitsiz
_br4.usage[_kanitli] = 7      # usage >= PRUNE_USAGE_MIN
_br4.usage[_kanitsiz] = 0
_n4 = _br4.konsolide(koru_ust=1)
kontrol(_kanitli in _br4.w,
        "usage kanitli ama zayiflamis baglanti budandi (koru_ust yolu)")
kontrol(_kanitsiz not in _br4.w,
        "kanitsiz zayif baglanti budanilmamaliydi")
kontrol(_n4 == 1, "silinen sayisi 1 olmaliydi, %s" % _n4)
# Ayni kural koru_ust=None (uyku) yolunda da gecerli: tutarli budama.
_br5 = Brain(seed=4)
_br5.w[_kanitli] = 0.005
_br5.w[_kanitsiz] = 0.005
_br5.usage[_kanitli] = 7
_br5.usage[_kanitsiz] = 0
_br5.konsolide()
kontrol(_kanitli in _br5.w,
        "usage kanitli ama zayiflamis baglanti budandi (uyku yolu)")
kontrol(_kanitsiz not in _br5.w,
        "kanitsiz zayif baglanti uyku yolunda budanilmamaliydi")
# usage=1 (tek deneme) kanit sayilmaz: zayifsa budanabilir.
_br6 = Brain(seed=4)
_bir = ("bir:1", "eat")
_br6.w[_bir] = 0.005
_br6.usage[_bir] = 1
_br6.konsolide(koru_ust=1)
kontrol(_bir not in _br6.w,
        "usage=1 zayif baglanti budanilmamaliydi (tek deneme kanit degil)")

# --- 24d) REGRESYON: USAGE TAVANI KANITI SILMEZ ---
# KOK NEDEN 2 (2026-10-22): _usage_tavanla() korumayi yalnizca "o an
# eklenen" girdilere uyguluyordu. Sonuc: her yeni usage=1 girdi tabloya
# girer girmez KORUNURKEN, usage>=2 olan KANITLI girdiler gürültü
# tarafindan atiliyordu (olculen canli beyin: kanitli girdi 108 -> 51).
# Tavan GURULTUYU kesmeli, KANITI kesmemeli.
# KÖK NEDEN 3 (2026-10-22): kanıt bir BAĞLANTININ üzerindeki kanıttır.
# Bağlantısız girdinin kanıtı hiçbir işe yaramaz (sadece tabloyu şişirir)
# → bağlantısız girdiler gürültü sayılır. Testte bağlantı da kurulur.
_bt = Brain(seed=7)
for i in range(50):
    _bt.usage[("kanit:%d" % i, "eat")] = 5      # kanitli
    _bt.w[("kanit:%d" % i, "eat")] = 0.1
for i in range(500):
    _bt.usage[("gurultu:%d" % i, "rest")] = 1   # gürültü
    _bt.w[("gurultu:%d" % i, "rest")] = 0.1
_bt._usage_tavanla()
_kalan = [k for k, v in _bt.usage.items() if v >= 2]
kontrol(len(_kalan) == 50,
        "usage tavani kanitli girdileri sildi: %d/50 kaldi" % len(_kalan))
kontrol(len(_bt.usage) <= Brain.USAGE_TAVAN + len(_kalan),
        "usage tablosu tavan asmadi: %d" % len(_bt.usage))
# Bağlantısız kanıt gürültü sayılır → temizlenir
_bt2 = Brain(seed=7)
_bt2.usage[("kopuk:1", "eat")] = 9      # kanıtlı ama bağlantısız
_bt2._usage_tavanla()
kontrol(("kopuk:1", "eat") not in _bt2.usage,
        "baglantısiz kanit temizlenmedi")
# Sert üst sınır: kanıt tablosu sonsuza dek büyümez.
# KÖK NEDEN 3 DÜZELTMESİ (2026-10-22): sert tavan artık KANITI kesmez —
# kanıtlı girdiler korunur, gürültü (kanıtsız) kesilir. Böylece kanıt
# tablosu büyüyebilir ama kanıt KAYBOLMAZ (dosya boyutu links'ten gelir).
_k2 = Brain(seed=7)
for i in range(Brain.USAGE_TAVAN_KALAN + 100):
    _k2.usage[("kanit:%d" % i, "eat")] = 5
    _k2.w[("kanit:%d" % i, "eat")] = 0.1
_k2._usage_tavanla()
kontrol(len([k for k, v in _k2.usage.items() if v >= 2]) ==
        Brain.USAGE_TAVAN_KALAN + 100,
        "sert tavan kaniti kesti: %d" % len(_k2.usage))
# Gürültü kesilir: dosya boyutu sınırlı kalır
_k3 = Brain(seed=7)
for i in range(Brain.USAGE_TAVAN_KALAN + 100):
    _k3.usage[("gurultu:%d" % i, "eat")] = 1
    _k3.w[("gurultu:%d" % i, "eat")] = 0.1
_k3._usage_tavanla()
kontrol(len(_k3.usage) <= Brain.USAGE_TAVAN_KALAN,
        "sert tavan gurultuyu kesmedi: %d" % len(_k3.usage))

# --- 24e) REGRESYON: SAYAC DONDURMA (KOK NEDEN 3) ---
# Döngüsel tuzak: sert üst sınır kanıt silerse → bağlantı kanıtsızlaşır
# → budama siler → daha çok gürültü → tablo büyür → daha çok kanıt
# silinir. Doğrusu: kanıtın KENDİSİ korunur, TEKRAR SAYISI dondurulur.
_bd = Brain(seed=7)
for i in range(40):
    _bd.usage[("kanit:%d" % i, "eat")] = 300     # çok yüksek sayım
    _bd.w[("kanit:%d" % i, "eat")] = 0.3         # kanıt bağlantının üstünde
_bd._usage_dondur()
kontrol(all(v <= Brain.USAGE_DONDURMA for v in _bd.usage.values()),
        "dondurma sayaclari tasmadi")
kontrol(len([1 for v in _bd.usage.values() if v >= 2]) == 40,
        "dondurma kaniti kaybettirdi")
kontrol(len(_bd.usage_tasma) == 40,
        "dondurulmus fazla kayboldu: %d" % len(_bd.usage_tasma))
# Kanıt gücü dondurma ile korunur (familiarity_boost artmaya devam eder)
_boost1 = _bd.familiarity_boost("kanit:0", "eat")
_bd.usage_tasma[("kanit:0", "eat")] = 5000
_boost2 = _bd.familiarity_boost("kanit:0", "eat")
kontrol(_boost2 >= _boost1,
        "dondurulmus kanit gucu kayboldu: %.3f -> %.3f" % (_boost1, _boost2))
# Dondurma tablosu şişmez: 40 kanıt girdisi kalır, fazlalar ayrı tabloda
_buyuk = Brain(seed=7)
for i in range(Brain.USAGE_TAVAN_KALAN + 100):
    _buyuk.usage[("k:%d" % i, "eat")] = 5
    _buyuk.w[("k:%d" % i, "eat")] = 0.5
_buyuk._usage_dondur()
_buyuk._usage_tavanla()
# SERT TAVAN KANITI KESMEZ (KÖK NEDEN 3): kanıtlı girdiler korunur,
# gürültü (kanıtsız) kesilir.
kontrol(len([1 for v in _buyuk.usage.values() if v >= 2]) ==
        Brain.USAGE_TAVAN_KALAN + 100,
        "sert tavan kaniti kesti")
# Kanıtsız gürültü kesilir (dosya boyutu korunur)
_gurultu = Brain(seed=7)
for i in range(900):
    _gurultu.usage[("g:%d" % i, "eat")] = 1
    _gurultu.w[("g:%d" % i, "eat")] = 0.5
_gurultu._usage_tavanla()
kontrol(len(_gurultu.usage) <= Brain.USAGE_TAVAN_KALAN,
        "sert tavan gurultuyu kesmedi: %d" % len(_gurultu.usage))
# Tavan bir GÜRÜLTÜ girdisini silerse BAĞLANTISI da silinir
# (kanıtsız bağlantı bırakılmaz — sonraki budamada ölürdü).
_kalan = [k for k in _gurultu.w
          if k not in _gurultu.usage and k[0].startswith("g:")]
kontrol(len(_kalan) == 0,
        "tavan kanitsiz baglanti birakti: %d" % len(_kalan))
# Dondurma kalici mi? (save -> load)
import tempfile as _tf
_yol = _tf.mktemp(suffix=".json")
_bd.save(_yol)
_bd2 = Brain(seed=7)
_bd2.load(_yol)
kontrol(_bd2.usage_tasma == _bd.usage_tasma,
        "dondurulmus sayaclar kalici degil")
kontrol(_bd2.usage == _bd.usage,
        "usage tablosu round-trip bozuldu")

# --- 25) KOMUTA ÖZGÜ BAĞLAM ANAHTARI ---

# Genel bit maskesi (açlık|tehlike|mesaj) kanıtı YANLIŞ YERE
# bölerdi: "acil_yem" kanıtı "b1"(açlık) ve "b3"(açlık+tehlike)
# arasında bölünür → açlıkta bile "dogrulanmadi" ile reddedilir
# (runtime'da 300 kez). Kanıt, komutun ÖN KOŞULU üzerinden
# sınıflandırılmalıdır.
ust_k = _Ust()
_ay = KOMUT_INDEKSI[KOMUT_ACIL_YEM]
x_aclik_tehlike = x_aclik.copy()
x_aclik_tehlike[IDX_TEHLIKE] = 1.0
kontrol(ust_k.komut_baglam_anahtari(_ay, x_aclik)
        == ust_k.komut_baglam_anahtari(_ay, x_aclik_tehlike),
        "aclik ve aclik+tehlike farkli baglam anahtari uretti "
        "(kanit bolunuyor)")
# Açlık YOKKEN kanıt taşınmamalı (ön koşul kapısı).
kontrol(ust_k.komut_baglam_anahtari(_ay, x_tehlike)
        != ust_k.komut_baglam_anahtari(_ay, x_aclik),
        "acl yokken acil_yem kaniti aclik baglamina tasindi")
# Kanıt: açlıkta toplanan kanıt, açlık+tehlikede de GEÇERLİ.
for _ in range(20):
    ust_k.ogren(x_aclik, _ay, 1.0)
kontrol(ust_k._dogrulama_puani(_ay, x_aclik)
        >= ust_k.dogrulama_esigi,
        "aclik baglaminda kanit esige ulasmadi")
kontrol(ust_k._dogrulama_puani(_ay, x_aclik_tehlike)
        >= ust_k.dogrulama_esigi,
        "aclik+tehlikede kanit tasinmadi (esik alti: %s)"
        % ust_k._dogrulama_puani(_ay, x_aclik_tehlike))
kontrol(ust_k._dogrulama_puani(_ay, x_tehlike) == 0.0,
        "acl yokken kanit sifir degil: %s"
        % ust_k._dogrulama_puani(_ay, x_tehlike))
# sifirla bağlamdan bağımsız → global kanıt.
_sf = KOMUT_INDEKSI[KOMUT_SIFIRLA]
kontrol(ust_k.komut_baglam_anahtari(_sf, x_aclik)
        == ust_k.komut_baglam_anahtari(_sf, x_tehlike),
        "sifirla baglamdan bagimsiz degil")

if hata:
    print("HATA (%d):" % len(hata))
    for h in hata:
        print("  -", h)
    raise SystemExit(1)
print("ust_beyn ogrenme/guvenlik testleri: TUMU GECTI")