import numpy as np
import random
import ust_beyn as ub

SIN = ub.SINYAL_BOYUT
CIK = ub.CIKIS_BOYUT
YOK = ub.KOMUT_INDEKSI[ub.KOMUT_YOK]
KOM = ub.KOMUTLAR


class Mini(ub.UstBeyn):
    """Gerçek UstBeyn davranışını taklit eden hafif simülasyon.

    Not: gerçek UstBeyn.__init__ yerine bu sınıf kullanılır çünkü
    simülasyon dosya sistemine (zeka/ust_beyn.json) dokunmamalıdır.
    """

    def __init__(self):
        self.cfg = {}
        self.rng = random.Random(1)
        self.mlp = ub.TinyMLP(SIN, ub.GIZLI_BOYUT, CIK, seed=1)
        self.epsilon = 0.15
        self.epsilon_min = 0.05
        self.epsilon_decay = 0.99985
        self.guven_esigi = 0.30
        self.marj_olcek = 0.15
        self.kanit_çarpanı = 0.35
        self.dogrulama_esigi = 0.35
        self.dogrulama = [0.0] * CIK
        self.dogrulama_bağlam = {}
        self.sure = 0
        self.sure_azami = 0
        self.son_komut = ub.KOMUT_YOK
        self.son_idx = 0
        self.reddedilen = 0
        self.samples = 0
        self.tik = 0
        self.secim_sayilari = [0] * CIK
        self.reddedilen_sayilari = [0] * CIK
        self.redd_serisi = [0] * CIK
        self.redd_cooldown = [0] * CIK
        self.RED_SERI_MAKS = 3
        self.odul_gecmisi = []


def sinyal(acik, tehlike, yemek_var):
    """main.py'deki topla_sinyalleri ile aynı indeks düzeninde sinyal."""
    v = np.zeros(SIN)
    v[ub.IDX_ENERJI] = 0.5
    v[ub.IDX_ACLIK] = acik / 100.0
    v[ub.IDX_TEHLIKE] = 1.0 if tehlike else 0.0
    v[ub.IDX_CANLI] = 1.0
    return v


def odul_hesapla(idx, acik, tehlike, yemek_var):
    """main.py'deki amaç-hizalı ödül mantığının aynısı."""
    o = 0.0
    if idx == ub.KOMUT_INDEKSI[ub.KOMUT_ACIL_DINLEN]:
        if tehlike:
            o += 0.2
    elif idx == ub.KOMUT_INDEKSI[ub.KOMUT_ACIL_YEM]:
        if acik > 50.0:
            o += 0.25
        o += 0.1 if yemek_var else -0.1
    elif idx == ub.KOMUT_INDEKSI[ub.KOMUT_KAPAT_AG]:
        o += 0.4 if tehlike else -0.05
    elif idx == ub.KOMUT_INDEKSI[ub.KOMUT_KISITLA_DOSYA]:
        o += 0.3 if tehlike else -0.05
    elif idx == ub.KOMUT_INDEKSI[ub.KOMUT_GUVENLI_MOD]:
        o += 0.25 if tehlike else -0.05
    return o


m = Mini()
kabul = red = kesif_kabul = model_onay = 0
Fazlar = [(70.0, 0.0, True), (30.0, 0.6, True), (40.0, 0.0, False)]
# 1200 tik: modelin güven eşiğine ulaşması ve kanıt biriktirmesi
# için gereken süre (300 tikte model henüz keskinleşmiyor).
for tik in range(1200):
    acik, tehlike, yemek = Fazlar[tik % 3]
    xs = sinyal(acik, tehlike, yemek)
    komut, idx, gv, kaynak = m.sec(xs)
    if idx == YOK:
        # main.py: "yok" → tehlikede ceza, aksi halde NÖTR (0.0)
        odul_yok = -0.2 if tehlike else 0.0
        m.ogren(xs, idx, odul_yok)
        continue
    ok, gk = m.komut_uygulanabilir_mi(idx, gv, kaynak, xs)
    if not ok:
        red += 1
        m.reddedildi_ogren(xs, idx)
        continue
    if kaynak == "kesif":
        kesif_kabul += 1
    else:
        model_onay += 1
    kabul += 1
    m.ogren(xs, idx, odul_hesapla(idx, acik, tehlike, yemek),
            keşif=(kaynak == "kesif"))

print("kabul=%d red=%d kesif_kabul=%d model_onay=%d"
      % (kabul, red, kesif_kabul, model_onay))
print("dogrulama:", ["%.3f" % d for d in m.dogrulama])
print("secim_sayilari:", m.secim_sayilari)
print("reddedilen_sayilari:", m.reddedilen_sayilari)
print("--- BAGLAMSAL DOGRULAMA ---")
for (idx, bag), puan in sorted(m.dogrulama_bağlam.items()):
    print("  %-12s %-4s %.3f" % (KOM[idx], bag, puan))
print("--- FAZ BAZLI KARAR ---")
for faz, (acik, tehlike, yemek) in enumerate(Fazlar):
    v = sinyal(acik, tehlike, yemek)
    p = m.mlp.predict(v)
    i = int(np.argmax(p))
    g = m._guven_hesapla(p, i)
    # Gerçek karar veren yol: sec() + komut_uygulanabilir_mi()
    _k, _i, _gv, _kaynak = m.sec(v)
    _ok, _gk = m.komut_uygulanabilir_mi(_i, _gv, _kaynak, v)
    print("  faz%d: argmax=%s p=%.3f marj_guven=%.3f | karar=%s "
          "kaynak=%s guven=%.3f dogrulama=%.3f -> %s (%s)"
          % (faz, KOM[i], p[i], g, KOM[_i], _kaynak, _gv,
             m._dogrulama_puani(_i, v),
             "ONAY" if _ok else "RED", _gk))
print("epsilon=%.3f" % m.epsilon)