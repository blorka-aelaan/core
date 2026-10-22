"""Güvenlik beyini eğitim hattı — DENEY-SİMÜLASYONU (kural yazılmaz).

Buradaki ZARAR KODLARI gerçekten çalıştırılır: rastgele durumlardan
mini ömürler simüle edilir; etiket "şimdi uygulasaydı yaşar mıydı?"
SORUSUNUN SONUÇTAN gelir. Hiçbir eşik/kural sayılmaz — sadece dünya
fiziği (metabolizma) ve zarar kodları.

  python3 egit_guvenlik.py                  # sentetik senaryolarla eğit
  python3 egit_guvenlik.py --deneyim        # YAŞARKEN verilen kararları
                                            # (guvenlik_veri.jsonl) sonuç
                                            # etiketleyip eğitim verisine kat

İleride: cpu/ram/disk kaynak düşüşleri bu dosyaya yeni zarar kodı olarak
eklenir; özellik uzayı guvenlik.features(..., ek={...}) ile genişler.
"""
import argparse
import json
import random
import time
from pathlib import Path

import guvenlik as G

ROOT = Path(__file__).resolve().parent

ZARAR_TIPLERI = ["aninda", "aninda", "saga", "stres"]


# ---------- ZARAR KODLARI ----------

def zarar_uygula(E, tip, miktar, durum):
    """Zarar kodunun etkisi. durum: süreli zarar kuyruğu."""
    if tip == "saga":
        # yarısı anında, yarısı sonraki 8 tikte sızar
        durum["sizinti"] = miktar / 2.0 / 8.0
        durum["kalan"] = 8
        return E - miktar / 2.0
    if tip == "stres":
        durum["stres"] = 10              # 10 tik yakıt ×1.5
        return E - miktar
    return E - miktar                    # "aninda"


# ---------- DÜNYA FİZİĞİ (metabolizma — kural değil, doğa) ----------

def fizik():
    cfg = json.loads((ROOT / "body.json").read_text(encoding="utf-8"))
    m = cfg["metabolism"]
    return {"decay": m["energy_decay_per_tick"],
            "cap": m.get("energy_cap", 150),
            "growth": m["hunger_growth_per_tick"],
            "relief": m["eat_hunger_relief"],
            "gain": 25, "charges": 4}


def mini_omur(E, H, yemek, tip, miktar, f, tik=30):
    """Şoku UYGULA ve 'tik' boyunca yaşat. True = yaşadı."""
    durum = {"sizinti": 0.0, "kalan": 0, "stres": 0}
    E = zarar_uygula(E, tip, miktar, durum)
    charges = f["charges"] if yemek else 0
    for _ in range(tik):
        stres = 1.5 if H > 80 else 1.0
        if durum["stres"] > 0:
            stres *= 1.5
            durum["stres"] -= 1
        E -= f["decay"] * stres
        H += f["growth"]
        if durum["kalan"] > 0:
            E -= durum["sizinti"]
            durum["kalan"] -= 1
        if E <= 0:
            return False                # ÖLDÜ → etiket: bekle (0)
        if H > 15 and charges > 0:      # doğal yeme davranışı
            E = min(f["cap"], E + f["gain"])
            H = max(0.0, H - f["relief"])
            charges -= 1
    return E > 0


# ---------- senaryo üretimi + eğitim ----------

def senaryo_uret(rng, f, adet):
    """(feats, etiket): etiket = simülasyon SONUCU (kural yok)."""
    veri = []
    while len(veri) < adet:
        E = rng.uniform(5, 150)
        H = rng.uniform(0, 95)
        tip = rng.choice(ZARAR_TIPLERI)
        miktar = rng.uniform(10, 120)
        yemek = rng.random() < 0.7
        etiket = 1 if mini_omur(E, H, yemek, tip, miktar, f) else 0
        feats = G.features(E, H, miktar, yemek, {"tip": tip})
        veri.append((feats, etiket))
    return veri


def deneyim_yukle():
    """Yaşarken verilen kararlar → simülasyonla etiketlenir → veriye
    dönüşür.

    Hata muhasebesi önemli:
      * aşırı cesaret = "uygula" dedi ama sim ölüm diyor  → HATA
      * erteleme    = "bekle" dedi, sim "yaşardı" diyor      → HATA DEĞİL
        (bilinçli erteleme; sadece fırsat kaçırması sayılır)
    Süremsiz (damgasız) kayıtlar ayrı tutulur.
    """
    import zeka
    yol = zeka.yol("guvenlik_veri.jsonl")
    if not yol.exists():
        return [], {"yeni": 0, "eski": 0, "asiri_cesaret": 0,
                    "erteleme": 0}
    f = fizik()
    kayitlar = []
    say = {"yeni": 0, "eski": 0, "asiri_cesaret": 0, "erteleme": 0}
    for line in yol.read_text(encoding="utf-8").splitlines():
        try:
            k = json.loads(line)
        except ValueError:
            continue
        tip = k.get("tip", "aninda")
        gercek = 1 if mini_omur(k["E"], k["H"], bool(k["yemek"]),
                                tip, k["sarsinti"], f) else 0
        feats = G.features(k["E"], k["H"], k["sarsinti"],
                           bool(k["yemek"]), {"tip": tip})
        kayitlar.append((feats, gercek))
        if k.get("surum") == G.SURUM:
            say["yeni"] += 1
        else:
            say["eski"] += 1
            continue                      # eski şema: muhasebeye katılmaz
        if k.get("karar") == "uygula" and not gercek:
            say["asiri_cesaret"] += 1
        if k.get("karar") == "bekle" and gercek:
            say["erteleme"] += 1
    return kayitlar, say


def _marj_kova(feats):
    """Bir özellik listesinden marj kova anahtarını çıkar (şemadan bağımsız)."""
    for f in feats:
        if f.split("=", 1)[0] in ("mj", "mk", "marj"):
            return f
    return None


def rapor(d, veri_test, say=None):
    dogru = sum(1 for feats, e in veri_test
                if (d.tahmin(feats) >= 0.5) == bool(e))
    n = len(veri_test)
    print("hold-out: %d örnek → doğruluk %%%.1f"
          % (n, 100.0 * dogru / max(1, n)))
    print("sınır görünümü (marj kovası → uygula oranı):")
    gruplar = {}
    for feats, e in veri_test:
        k = _marj_kova(feats)
        if k is not None:
            gruplar.setdefault(k, []).append((feats, e))
    for k in sorted(gruplar,
                    key=lambda x: int(x.split("=", 1)[1])
                    * (5 if x.startswith("mj") else 15)):
        subset = gruplar[k]
        if len(subset) < 10:
            continue
        p = sum(1 for feats, _ in subset if d.tahmin(feats) >= 0.5)
        e_p = sum(e for _, e in subset)
        print("  %-8s model %%%3d   gercek %%%3d   (n=%d)"
              % (k, 100.0 * p / len(subset),
                 100.0 * e_p / len(subset), len(subset)))
    if say and say.get("yeni"):
        print("yaşam verisi: %d yeni karar (+%d eski kayıt) | "
              "aşırı cesaret %d | fırsat kaçıran erteleme %d"
              % (say["yeni"], say["eski"], say["asiri_cesaret"],
                 say["erteleme"]))


def main():
    ap = argparse.ArgumentParser(description="güvenlik beyini eğitimi")
    ap.add_argument("--ornek", type=int, default=40000)
    ap.add_argument("--deneyim", action="store_true",
                    help="yaşarken verilen kararları da veriye kat")
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    f = fizik()
    rng = random.Random(args.seed)
    print("=== SENTETİK SENARYOLAR (zarar kodları çalışıyor) ===")
    t0 = time.time()
    veri = senaryo_uret(rng, f, args.ornek)
    print("%d senaryo %.1fs" % (len(veri), time.time() - t0))

    deneyim, say = [], {"yeni": 0, "eski": 0, "asiri_cesaret": 0,
                        "erteleme": 0}
    if args.deneyim:
        deneyim, say = deneyim_yukle()
        print("=== YAŞAM VERİSİ: %d yeni karar (+%d eski) ==="
              % (say["yeni"], say["eski"]))

    rng.shuffle(veri)
    test = veri[:len(veri) // 5]
    egitim = veri[len(veri) // 5:] + deneyim

    d = G.Guvenlik()
    for feats, e in egitim:
        d.ogren(feats, e)
    d.save()
    print("=== EĞİTİM ===")
    print("model örnek: %d   kova: %d → guvenlik.json"
          % (d.samples, len(d.n)))
    print("=== DEĞERLENDİRME ===")
    rapor(d, test, say)


if __name__ == "__main__":
    main()