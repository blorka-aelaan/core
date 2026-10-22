"""Kutu üretici — gizli kural dünyası.

<govde>_emr isimli dosyalar üretir; içerik ödülü kurallar motorundan gelir.
Organizma kuralı GÖRMEZ; sadece (isim, ödül) örneklerinden çıkarır.

  python3 kutu_uretici.py            # kutuyu üret (kurallar.json)
  python3 kutu_uretici.py --temizle  # kutuyu sil

egit.py de aynı motoru import eder (ground truth = bu dosya).
"""
import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_cfg(path=None):
    with open(path or ROOT / "kurallar.json", encoding="utf-8") as f:
        return json.load(f)


# ---------- özellik çıkarımı (ground truth) ----------

def features(name, cfg):
    sonek = cfg["kutu"]["sonek"]
    body = name[:-len(sonek)] if name.endswith(sonek) else name
    tip = ("sayi" if body.isdigit()
           else "harf" if body.isalpha() else "karisik")
    f = {"uzunluk": len(body), "tip": tip}
    if tip == "sayi":
        f["rakam_toplam"] = sum(int(c) for c in body)
    elif tip == "harf":
        f["harf_toplam"] = sum(ord(c) - 96 for c in body)
    return f


def _eslesir(feat, kural):
    for key, cond in kural.items():
        if key == "odul":
            continue
        if isinstance(cond, dict):  # {"min":..} / {"max":..}
            v = feat.get(key)
            if v is None:
                return False
            if "min" in cond and v < cond["min"]:
                return False
            if "max" in cond and v > cond["max"]:
                return False
        elif feat.get(key) != cond:
            return False
    return True


def odul_hesapla(name, cfg):
    """İsim → ödül: sıralı kurallar, ilk eşleşen; yoksa varsayılan."""
    feat = features(name, cfg)
    kc = cfg["kural"]
    for kural in kc["kurallar"]:
        if _eslesir(feat, kural):
            return int(kural["odul"])
    return int(kc.get("varsayilan_odul", 10))


def derinlik_bul(rel, cfg):
    """'kutular/k02/ax/dosya_emr' → derinlik 2 (klasör katmanı)."""
    prefix = cfg["kutu"]["dir"] + "/"
    r = rel[len(prefix):] if rel.startswith(prefix) else rel
    parts = [p for p in r.split("/") if p]
    return max(0, len(parts) - 1)


def kutu_tam_deger(rel, cfg):
    """Kutunun GERÇEK değeri (laboratuvar hesabı — organizma görmez):
    isim kuralı ödülü × (1 + derinlik)."""
    base = rel.split("/")[-1]
    return odul_hesapla(base, cfg) * (1 + derinlik_bul(rel, cfg))


# ---------- isim ve içerik üretimi ----------

def _govde(rng, uzunluk, tip):
    alfabe = "0123456789" if tip == "sayi" else "abcdefghijklmnopqrstuvwxyz"
    return "".join(rng.choice(alfabe) for _ in range(uzunluk))


def icerik_yaz(path, odul, rng):
    if rng.random() < 0.5:
        path.write_text("# kutu\nENERGY=%d\n# isim-degeri\n" % odul,
                        encoding="utf-8")
    else:
        path.write_text(json.dumps(
            {"energy": odul, "kutu": True}, ensure_ascii=False),
            encoding="utf-8")


def kutu_uret(cfg=None, sessiz=False):
    """20 kutu (dosya) — rastgele derinliklerde klasörlerde.

    Değer = isim kuralı ödülü × (1 + derinlik): derin klasör = büyük ödül.
    Eski 5000'lik tek-kutu dünyası da temizlenir.
    """
    cfg = cfg or load_cfg()
    k = cfg["kutu"]
    root = ROOT / k["dir"]
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(ROOT / "kutu", ignore_errors=True)  # eski dünya
    rng = random.Random(k.get("seed", 42))
    sonek = k["sonek"]
    adet = int(k["kutu_sayisi"])
    derinlikler = list(k.get("derinlikler", [1, 2, 3]))
    kombinasyon = [(u, t) for u in k["govde_uzunluklar"]
                   for t in k["govde_tipleri"]]

    # derinlik başına kutu payı (dengeli artan sırada)
    pay = [adet // len(derinlikler)] * len(derinlikler)
    for i in range(adet - sum(pay)):
        pay[i % len(pay)] += 1

    # klasör planı: derinlik başına ~2.5 kutu, benzersiz yollar
    harf = "abcdefghjkmnpqrstuvwxyz"
    kullanilan = set()
    plan = []  # [derinlik, yol, kutu_sayisi]
    for idx, d in enumerate(derinlikler):
        n_folder = max(1, round(pay[idx] / 2.5))
        for _ in range(n_folder):
            while True:
                segler = ["".join(rng.choice(harf) for _ in range(3))
                          for _ in range(d)]
                yol = "/".join(segler)
                if yol not in kullanilan:
                    kullanilan.add(yol)
                    break
            plan.append([d, root / yol, 0])

    # kutulari klasorlere dagit (derinlik payina gore round-robin)
    isler = []
    for idx, d in enumerate(derinlikler):
        folders = [p for p in plan if p[0] == d]
        for j in range(pay[idx]):
            isler.append(folders[j % len(folders)])

    seen = set()
    sayim = {}
    kutu_idx = 0
    degerler = []
    for folder in isler:
        while True:
            u, tip = kombinasyon[kutu_idx % len(kombinasyon)]
            kutu_idx += 1
            name = _govde(rng, u, tip) + sonek
            if name not in seen:
                break
        seen.add(name)
        d = folder[0]
        odul = odul_hesapla(name, cfg) * (1 + d)
        folder[1].mkdir(parents=True, exist_ok=True)
        icerik_yaz(folder[1] / name, odul, rng)
        folder[2] += 1
        key = "%d-%s" % (u, tip)
        sayim[key] = sayim.get(key, 0) + 1
        degerler.append((str(folder[1].relative_to(root)) + "/" + name,
                         odul, d))

    if not sessiz:
        print("kutular üretildi:", root)
        print("kutu: %d   klasör: %d   derinlikler: %s"
              % (len(degerler), len(plan), sorted(set(d for _, _, d in degerler))))
        for yol, odul, d in sorted(degerler):
            print("  d=%d  %-28s → %3d" % (d, yol, odul))
        for key in sorted(sayim):
            print("  kategori %-10s %d" % (key, sayim[key]))


if __name__ == "__main__":
    if "--temizle" in sys.argv:
        cfg = load_cfg()
        shutil.rmtree(ROOT / cfg["kutu"]["dir"], ignore_errors=True)
        shutil.rmtree(ROOT / "kutu", ignore_errors=True)
        print("kutular silindi")
    else:
        kutu_uret()