"""S3: merak (R_merak) ayrı öğrenme hızı (lr_merak = lr * 1.5).

R_merak > 0 olduğunda organizmanın "bilmiyorum ama deneyeyim"
keşif eylemi kalıcılaşır; aynı ödül ile r_merak=0'dan farklı (1.5×)
ağırlık güncellemesi yapılır.
"""
import sys
sys.path.insert(0, "/home/emrah/Genel/core")
import brain


def test_merak_hizi():
    # instinkt'te olmayan özellikler: "Z","W" → başlangıç score 0,
    # err = reward, oran temiz 1.5 çıkar
    stim = "Z|W"
    act = "eat"
    reward = 4.0

    b_normal = brain.Brain(lr=0.12, seed=1)
    b_normal.learn(stim, act, reward, r_merak=0.0)
    w_normal = b_normal.score(stim, act)

    b_merak = brain.Brain(lr=0.12, seed=1)
    b_merak.learn(stim, act, reward, r_merak=1.0)
    w_merak = b_merak.score(stim, act)

    oran = w_merak / w_normal
    print("normal w=%.4f  merak w=%.4f  oran=%.3f (hedef 1.500)"
          % (w_normal, w_merak, oran))
    assert abs(oran - 1.5) < 0.01, (w_normal, w_merak, oran)


def test_merak_sifir_aynidir():
    """r_merak=0 varsayılanla eski davranış bozulmamalı."""
    stim = "X|Y"
    act = "wander"
    reward = 3.0
    b1 = brain.Brain(lr=0.12, seed=7)
    b1.learn(stim, act, reward, r_merak=0.0)
    b2 = brain.Brain(lr=0.12, seed=7)
    b2.learn(stim, act, reward)  # varsayılan r_merak=0
    assert b1.score(stim, act) == b2.score(stim, act)


def test_merak_negatif_aynidir():
    """r_merak <= 0 ise normal lr kullanılır."""
    stim = "M|N"
    act = "rest"
    reward = 2.0
    b1 = brain.Brain(lr=0.12, seed=3)
    b1.learn(stim, act, reward, r_merak=-1.0)
    b2 = brain.Brain(lr=0.12, seed=3)
    b2.learn(stim, act, reward, r_merak=0.0)
    assert b1.score(stim, act) == b2.score(stim, act)


test_merak_hizi()
test_merak_sifir_aynidir()
test_merak_negatif_aynidir()
print("S3 MERAK lr_merak: 3/3 OK")
