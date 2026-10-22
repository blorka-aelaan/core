"""Güvenlik beyini — öğrenilmiş zarar-kararı modeli (saf Python).

Kural HİÇ yazılmaz: egit_guvenlik.py deney-simülasyonundan gelen
etiketlerle eğitilir; çalışma anında main bu modeli sorar:
    "bu durumda şok uygulamak güvenli mi?" → uygula / bekle

Özellik uzayı GENİŞLETİLEBİLİR: ileride cpu/ram/disk bin'leri ek
parametreyle gelebilir (features(..., ek={...})).

  guv = Guvenlik(); guv.load(); guv.karar_ver(E, H, sarsinti, yemek)
Kayıt: guvenlik.json (atomik). Yaşam verisi: guvenlik_veri.jsonl
"""
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Karar eşiği (hiperparametre, kural değil): yanlış "uygula" ölüm demek,
# yanlış "bekle" ucuz. Simetrik 0.5 yerine asimetrik eşik.
# NOT (test dersi): 0.9 TIKANMA yaptı — belirsiz bölgenin (marj 0-15)
# ulaşılabilir maks puanı ~0.76; E=150 kapasitesiyle büyük şoklarda marj
# 15 hiç görülmüyor → şok sonsuza dek askıda kaldı. 0.7: marj≤-15 bandı
# (puan ≤0.24) yine reddedilir, belirsiz bölge kapak dolunca açılır.
ESIK = 0.7

# True: marj sıfır civarında 5'lik ince kova (mj=…); False: eski 15'lik kova
# (marj=…). True yapınca modeli egit_guvenlik.py ile YENİDEN EĞİTMEN gerekir:
# eski guvenlik.json'daki 'marj=' anahtarları yeni şemada kullanılmaz.
INCE_MARJ = True

# Karar modeli sürümü. guvenlik_veri.jsonl kayıtlarına damga olarak yazılır;
# eski kayıtlar (damgasız) = eski eşik/şema dönemi → eğitimde ayrı sayılır.
SURUM = 2


def marj_ozellik(m):
    m = int(m)
    if INCE_MARJ:
        if -30 <= m < 30:
            return "mj=%d" % (m // 5)       # sıfır civarı: 5 birim
        return "mk=%d" % (m // 15)          # uzak bölge: kaba
    return "marj=%d" % (m // 15)


def features(E, H, sarsinti, yemek, ek=None):
    """Durum → özellik anahtarları (bucket). Genişletilebilir.

    NOT: 'marj' (E − şok) zaten enerji ve şoku BİRLİKTE taşır; ayrı 'e'/'s'
    özellikleri koymak çapraz gürültü yapıp tehlikeli bölgede yanlış
    karara yol açıyordu (E=101 & şok=120 durumu, küçük şoklu güvenli
    durumlarla aynı 'e' kovasını paylaşıyordu). Bu yüzden sadeleştirildi.
    """
    feats = [
        "h=" + ("T" if H <= 30 else "O" if H <= 70 else "A"),
        "yemek=" + ("var" if yemek else "yok"),
        # marj: enerji − şok; kural değil, en bilgilendirici özellik
        marj_ozellik(int(E) - int(sarsinti)),
        # kaba şok ölçeği (büyük şoklar farklı davranır)
        "s=%d" % min(9, max(0, int(sarsinti) // 25)),
    ]
    if ek:
        for k, v in ek.items():
            feats.append("%s=%s" % (k, v))
    return feats


class Guvenlik:
    """Delta öğrenmeli karar modeli: etiket 1=uygula, 0=bekle."""

    def __init__(self, lr=0.2, yumusatma=500.0):
        self.lr = lr
        self.k = yumusatma
        self.n = {}            # özellik -> [sayım, delta]
        self.global_n = 0
        self.global_sum = 0.0
        self.samples = 0

    def ogren(self, feats, etiket):
        pred = self.tahmin(feats)
        err = float(etiket) - pred
        n_f = max(1, len(feats))
        for f in feats:
            s = self.n.setdefault(f, [0, 0.0])
            step = self.lr / (1.0 + s[0] / self.k)
            s[1] += step * err / n_f
            s[0] += 1
        self.global_n += 1
        self.global_sum += float(etiket)
        self.samples += 1

    def tahmin(self, feats):
        base = (self.global_sum / self.global_n) if self.global_n else 0.5
        deltas = [self.n[f][1] for f in feats if f in self.n]
        if not deltas:
            return base
        return base + sum(deltas) / len(deltas)

    def karar_ver(self, E, H, sarsinti, yemek, ek=None, esik=None):
        """→ ('uygula'|'bekle', puan). Eşik varsayılan: ESIK (asimetrik)."""
        p = self.tahmin(features(E, H, sarsinti, yemek, ek))
        e = ESIK if esik is None else esik
        return ("uygula" if p >= e else "bekle", p)

    # ---------- kayıt ----------

    def save(self, path=None):
        import zeka
        path = Path(path or zeka.kayit("guvenlik.json"))
        tmp = path.with_name(path.name + ".tmp")
        data = {"samples": self.samples,
                "global": [self.global_n, self.global_sum],
                "n": self.n}
        tmp.write_text(json.dumps(data, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))

    def load(self, path=None):
        import zeka
        path = Path(path or zeka.yol("guvenlik.json"))
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return False
        self.samples = int(data.get("samples", 0))
        g = data.get("global", [0, 0.5])
        self.global_n, self.global_sum = int(g[0]), float(g[1])
        self.n = {f: [int(v[0]), float(v[1])]
                  for f, v in data.get("n", {}).items()}
        return True


def veri_yaz(kayit, path=None):
    """Yaşam kararı kaydı (eğitim verisine dönüşür) — append-only."""
    import zeka
    path = Path(path or zeka.kayit("guvenlik_veri.jsonl"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(kayit, ensure_ascii=False) + "\n")