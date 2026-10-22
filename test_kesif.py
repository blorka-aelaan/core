"""Aşama 6b — keşif kör noktası regresyon testi (canlı dersi).

Canlı ders (2026-10-19, 5.5 saat sıfır görev): keşif havuzu score>=0
filtresiyle {rest}'e inince cmd:* keşfe bile giremiyordu — yeniden
denenmeyen eylemin skoru asla düzelmez, kalıcı kör nokta.

Kontroller:
1) EPS_TABAN: marj devasa olsa bile keşif eps'i tabanın altına inmez
2) KESIF_TAM: score>=0 havuzu tek eyleme insen bile, keşfin bir kısmı
   TAM havuzdan (negatif skorlu adaylar dahil) seçim yapar
3) Uyanma: negatife çökmüş ama aslında kazandıran bir kapı, keşif
   tekrarlayınca skoru hızla pozitife döner (delta kuralı)
"""
import sys
sys.path.insert(0, "/home/emrah/Genel/core")
import brain as B


def test_eps_taban():
    b = B.Brain(seed=3)
    # tek kazanan rest +10; marj ~20 → eski eps 0.35/21 ≈ 0.017 idi
    b.w[("Z", "rest")] = 10.0
    keşif = 0
    n = 4000
    for i in range(n):
        b.decide("Z|Q", ["rest", "wander", "cmd:wc"])
        keşif += 1 if b.son_kesif else 0
    oran = keşif / n
    assert oran >= 0.03, ("keşif tamamen kapandı", oran)
    assert oran <= 0.20, ("keşif fazla açıldı", oran)
    print("1 EPS_TABAN: devasa marja rağmen keşif oranı %.3f (>=0.03)" % oran)


def test_tam_havuz():
    b = B.Brain(seed=11)
    # havuz koşulu: rest pozitif, diğerleri negatif → filtreli havuz {rest}
    b.w[("Z", "rest")] = 5.0
    b.w[("Z", "wander")] = -3.0
    b.w[("Z", "cmd:wc")] = -4.0
    b.sikilma = 1.0   # keşif baskısı tam
    sayim = {"cmd:wc": 0, "wander": 0, "rest": 0}
    n = 6000
    for _ in range(n):
        a = b.decide("Z", ["rest", "wander", "cmd:wc"])
        sayim[a] += 1
    # negatifler toplam keşfin ~KESIF_TAM kadarında görünmeli
    neg_oran = (sayim["cmd:wc"] + sayim["wander"]) / n
    assert neg_oran > 0.02, ("kör nokta: negatifler hiç denenmedi", sayim)
    print("2 KESIF_TAM: negatif skorlu adaylar keşifte %.1f%% (sayım %s)"
          % (100 * neg_oran, sayim))


def test_uyanma():
    """Negatife çökmüş kazançlı kapı keşifle yeniden bulunca skoru döner."""
    b = B.Brain(seed=5)
    b.w[("Z", "rest")] = 3.0
    b.w[("Z", "cmd:wc")] = -2.0
    # dünya: cmd:wc aslında +6 kazandırıyor (kayıp kapı)
    for _ in range(300):
        a = b.decide("Z", ["rest", "cmd:wc"])
        r = 6.0 if a == "cmd:wc" else 0.5
        b.learn("Z", a, r)
    skor = b.score("Z", "cmd:wc")
    assert skor > 0.5, ("uyanma yok: kapı hâlâ negatif", skor)
    print("3 uyanma: cmd:wc skoru -2.0 → %+.2f (keşifle bulundu)" % skor)


test_eps_taban()
test_tam_havuz()
test_uyanma()
print("KESIF KOR NOKTA: 3/3 OK")