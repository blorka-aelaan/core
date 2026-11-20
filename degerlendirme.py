#!/usr/bin/env python3
"""CORE ASM Öğrenme Değerlendirmesi (v2)

asm_ogren.py'ye dokunmaz; core/ klasöründe yanında çalışır.

AYNI sabit sınavı üç koşulda çözer:
  duz     : ağırlık hep 1, state yok            -> saf arama (taban)
  agirlik : öğrenilmiş op-aile ağırlıkları      -> compare() ile aynı şey
  tam     : ağırlık + başarısız önbellek + primitikler + kayıtlı programlar
"düz -> ağırlık" farkı ağırlık öğrenmesini, "ağırlık -> tam" farkı state'in
(önbellek/primitik/program) katkısını gösterir.

Sınav ilk çalıştırmada üretilip sinav_kumesi.json'a yazılır ve bir daha
DEĞİŞMEZ (--yenile hariç); böylece günler arası sonuçlar karşılaştırılabilir.
Her çalıştırma degerlendirme_gecmis.jsonl'e bir satır ekler.

Kullanım:
    python3 degerlendirme.py
    python3 degerlendirme.py --madde 30 --butce 20000 --seviyeler 1,2
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import os
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from uzuv.asm_ogren import (  # noqa: E402
    AILELER, CURRICULUM, MASK, REGISTERS, OPS, AssemblyLearner, BeamSearchSolver,
    Emulator, LearningState, NNWeightBlender, Task, TaskGenerator, context_key,
    _iliski_turu, _gorev_ozellik_vektoru,
)
from uzuv.asm_uzuv import AsmUzuv  # noqa: E402
import noral_beyn as noral_beyn_mod  # noqa: E402

SINAV_YOLU = ROOT / "sinav_kumesi.json"
RAPOR_YOLU = ROOT / "degerlendirme_rapor.json"
GECMIS_YOLU = ROOT / "degerlendirme_gecmis.jsonl"
KOSULLAR = ("duz", "agirlik", "nn", "tam")

# ------------------------------------------------------------------ hazırlık


def asm_olustur() -> AsmUzuv:
    try:
        return AsmUzuv(root=ROOT)
    except TypeError:
        return AsmUzuv()


def state_yukle(arg: Optional[str]) -> LearningState:
    if arg:
        yol = Path(arg)
    else:
        adaylar = [p for p in (ROOT / "zeka" / "asm_ogren.json",
                               ROOT / "uzuv" / "asm_ogren.json",
                               ROOT / "asm_ogren.json") if p.exists()]
        if not adaylar:
            sys.exit("asm_ogren.json bulunamadı; --state ile yolu ver.")
        yol = max(adaylar, key=lambda p: p.stat().st_mtime)
    if not yol.exists():
        sys.exit(f"state dosyası yok: {yol}")
    state = LearningState(yol)
    state.load()  # dosya bozuksa sessizce boş döner -> aşağıda kontrol
    if state.total_tasks == 0 and not state.weights.records:
        sys.exit(f"state boş yüklendi ({yol}); yanlış dosya ya da bozuk.")
    print(f"state: {yol}  görev={state.total_tasks} seviye={state.max_level} "
          f"bağlam={len(state.weights.records)}")
    return state


# ------------------------------------------------------------------ sabit sınav


def sinav_uret(asm: AsmUzuv, madde: int, tohum: int) -> List[Dict[str, Any]]:
    gen = TaskGenerator(Emulator(), OPS, CURRICULUM)
    gorevler: List[Dict[str, Any]] = []
    for lv in sorted(CURRICULUM):
        rng = random.Random(tohum * 100 + lv)
        cfg = CURRICULUM[lv]
        gorulen = set()
        sayi = 0
        for _ in range(madde * 30):
            if sayi >= madde:
                break
            uzunluk = rng.randint(1, cfg.max_instructions)
            task = gen.generate(asm, rng, lv, uzunluk)
            if task is None:
                continue
            anahtar = repr(task.training)
            if anahtar in gorulen:
                continue
            gorulen.add(anahtar)
            # repr/literal_eval: JSON int anahtarları (bellek adresi) str'ye
            # çevirir; bu yol tipleri aynen korur.
            gorevler.append({
                "level": lv, "length": task.length, "code": task.code,
                "veri": repr({"training": task.training, "secret": task.secret}),
            })
            sayi += 1
        print(f"  seviye {lv}: {sayi}/{madde} görev")
    return gorevler


def sinav_yukle_veya_uret(asm: AsmUzuv, madde: int, tohum: int,
                          yenile: bool) -> Tuple[List[Dict[str, Any]], str]:
    if SINAV_YOLU.exists() and not yenile:
        veri = json.loads(SINAV_YOLU.read_text(encoding="utf-8"))
        return veri["gorevler"], veri["sinav_id"]
    print("sınav üretiliyor (bir kez, sonra sabit kalır)...")
    gorevler = sinav_uret(asm, madde, tohum)
    sid = hashlib.sha1(json.dumps(gorevler, sort_keys=True).encode("utf-8")
                       ).hexdigest()[:10]
    tmp = SINAV_YOLU.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sinav_id": sid, "tohum": tohum,
                               "madde": madde, "gorevler": gorevler},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SINAV_YOLU)
    return gorevler, sid


def gorev_olustur(kayit: Dict[str, Any]) -> Task:
    veri = ast.literal_eval(kayit["veri"])
    # program=[]: çözücü yalnızca training/secret kullanır, cevabı görmez.
    return Task(level=kayit["level"], length=kayit["length"], program=[],
                code=kayit["code"], training=veri["training"],
                secret=veri["secret"])


# ------------------------------------------------------------------ çözme


def kosul_coz(asm: AsmUzuv, gorevler: List[Tuple[Dict[str, Any], Task]],
              kosul: str, state: LearningState, butce: int,
              saniye: float,
              nn_ana=None, stim_features: Optional[list[float]] = None,
              ) -> List[Dict[str, Any]]:
    solver = BeamSearchSolver(Emulator(), OPS, CURRICULUM)
    duz = {aile: 1.0 for aile in AILELER}
    satirlar: List[Dict[str, Any]] = []
    ilk_hata = True
    for i, (kayit, task) in enumerate(gorevler):
        lv = kayit["level"]
        rng = random.Random(lv * 10_000 + i)   # her koşulda aynı tohum
        if kosul == "duz":
            w: Any = duz
            st: Optional[LearningState] = None
        elif kosul == "agirlik":
            cf, cc = context_key(task.training)
            w = state.weights.weights(cf, AILELER, cc)
            st = None  # sadece ağırlık karşılaştırması, state önbelleği yok (duz ile aynı koşul)
        elif kosul == "nn":
            # Hibrit: AssemblyLearner.run(nn_ana=...) ile tek görev çöz
            satir = {"level": lv, "solved": False, "attempts": 0,
                     "timed_out": False, "hata": ""}
            try:
                learner = AssemblyLearner(
                    asm, state, CURRICULUM, OPS,
                    Emulator(), random.Random(lv * 10_000 + i),
                )
                sonuc = learner.solver.solve(
                    asm, task,
                    NNWeightBlender(state.weights, nn_ana,
                                    stim_features or _gorev_ozellik_vektoru(task),
                                    alpha=0.6),
                    rng, lv, None,  # state önbelleği yok, sadece NN blend ağırlıkları
                    record_to_brain=False,
                    budget=butce,
                    deadline=time.monotonic() + saniye,
                )
                satir.update(
                    solved=bool(sonuc.solved),
                    attempts=int(sonuc.attempts),
                    timed_out=bool(sonuc.timed_out),
                )
            except Exception as e:  # noqa: BLE001
                satir["hata"] = f"{type(e).__name__}: {e}"
                if ilk_hata:
                    ilk_hata = False
                    traceback.print_exc()
            satirlar.append(satir)
            continue
        else:
            st = copy.deepcopy(state)          # maddeler birbirini beslemesin
            w = st.weights
        satir = {"level": lv, "solved": False, "attempts": 0,
                 "timed_out": False, "hata": ""}
        try:
            res = solver.solve(asm, task, w, rng, lv, st,
                               record_to_brain=False, budget=butce,
                               deadline=time.monotonic() + saniye)
            satir.update(solved=bool(res.solved), attempts=int(res.attempts),
                         timed_out=bool(res.timed_out))
        except Exception as e:  # noqa: BLE001
            satir["hata"] = f"{type(e).__name__}: {e}"
            if ilk_hata:
                ilk_hata = False
                traceback.print_exc()
        satirlar.append(satir)
    return satirlar


# ------------------------------------------------------------------ istatistik


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    m = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, m - h), min(1.0, m + h)


def ozetle(satirlar: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(satirlar)
    coz = [s for s in satirlar if s["solved"]]
    att = sorted(s["attempts"] for s in coz)
    lo, hi = wilson(len(coz), n)
    return {
        "n": n, "cozuldu": len(coz),
        "oran": round(len(coz) / n, 3) if n else 0.0,
        "aralik95": [round(lo, 3), round(hi, 3)],
        "ortanca_deneme": att[len(att) // 2] if att else None,
        "ort_deneme": round(sum(att) / len(att), 1) if att else None,
        "deneme_le_1000": sum(1 for a in att if a <= 1000),
        "deneme_le_5000": sum(1 for a in att if a <= 5000),
        "zaman_asimi": sum(1 for s in satirlar if s["timed_out"]),
        "hata": sum(1 for s in satirlar if s["hata"]),
    }


def hucre(o: Dict[str, Any]) -> str:
    lo, hi = o["aralik95"]
    return (f"{o['cozuldu']:>2}/{o['n']:<2} %{o['oran'] * 100:>3.0f} "
            f"[{lo * 100:.0f}-{hi * 100:.0f}]")


# ------------------------------------------------------------------ ana


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", help="asm_ogren.json yolu (varsayılan: otomatik)")
    ap.add_argument("--madde", type=int, default=30, help="seviye başına görev")
    ap.add_argument("--butce", type=int, default=20000)
    ap.add_argument("--saniye", type=float, default=60.0,
                    help="görev başına güvenlik zaman aşımı")
    ap.add_argument("--seviyeler", default="", help="örn. 1,2 (varsayılan hepsi)")
    ap.add_argument("--kosullar", default=",".join(KOSULLAR))
    ap.add_argument("--tohum", type=int, default=42)
    ap.add_argument("--yenile", action="store_true",
                    help="sınavı yeniden üret (eski geçmişle karşılaştırılamaz)")
    a = ap.parse_args()

    asm = asm_olustur()
    state = state_yukle(a.state)
    gorev_kayitlari, sinav_id = sinav_yukle_veya_uret(
        asm, a.madde, a.tohum, a.yenile)
    seviyeler = ([int(x) for x in a.seviyeler.split(",") if x]
                 or sorted({k["level"] for k in gorev_kayitlari}))
    gorevler = [(k, gorev_olustur(k)) for k in gorev_kayitlari
                if k["level"] in seviyeler]
    kosullar = [k for k in a.kosullar.split(",") if k in KOSULLAR]
    nn_ana = None
    stim_features = None
    if "nn" in kosullar:
        # nn_ana'yı oluştur ve test ağırlıklarını yükle
        # zeka/nn_ana_test.json: [48, 10, 5] - eğitilmiş test dosyası
        try:
            nn_ana = noral_beyn_mod.NöralBeyn("ana_test", [48, 10, 5], lr=0.12)
            # Eğitilmiş ağırlıkları yükle (ozeti dosya yolundan otomatik okur)
            nn_ana._yükle()
            # Ödemeyi devre dışı bırak: sınavda NASIL dosyaya yazılmasın
            nn_ana.kaydet = lambda *a, **k: None
            # Eğitilmiş ağırlıkların giriş boyutu ile uyumluluğu kontrol et
            girdi_boyutu = len(nn_ana.ağırlıklar[0]) if nn_ana.ağırlıklar else 0
            if girdi_boyutu != 48:
                print(f"nn_ana giriş boyutu {girdi_boyutu}, 48 bekleniyor; nn koşulu devre dışı")
                nn_ana = None
            else:
                print(f"nn_ana yüklendi: zeka/nn_ana_test.json (giriş: {girdi_boyutu})")
        except Exception as e:
            print(f"nn_ana yükleme hatası: {e}")
            nn_ana = None
    # Eğer tipik sigara varsa, gerçek eğitim özellik vektörünü gönder:
    if nn_ana is not None and stim_features is None:
        # Tüm görevlerde eşit ağırlık (gerekirse görev özellikleri buradan
        # hesaplanabilir; şimdilik general bir vektörlü kalıyor)
        stim_features = [0.5] * 48
    print(f"sınav {sinav_id}: {len(gorevler)} görev, seviyeler {seviyeler}, "
          f"bütçe {a.butce}")

    # Öğrenilmiş ağırlıklar sınav bağlamlarında hiç var mı?
    bag = {}
    for lv in seviyeler:
        ts = [t for k, t in gorevler if k["level"] == lv]
        bag[str(lv)] = {
            "agirlik_baglami": sum(context_key(t.training)[0] in state.weights.records for t in ts),
            "kayitli_program": sum(context_key(t.training)[0] in state.programs for t in ts),
            "n": len(ts),
        }

    sonuc: Dict[str, Dict[str, Any]] = {}
    for kosul in kosullar:
        t0 = time.monotonic()
        if kosul == "nn":
            satirlar = kosul_coz(asm, gorevler, kosul, state, a.butce,
                                 a.saniye, nn_ana=nn_ana,
                                 stim_features=stim_features)
        else:
            satirlar = kosul_coz(asm, gorevler, kosul, state, a.butce,
                                 a.saniye)
        sonuc[kosul] = {"toplam": ozetle(satirlar), "seviye": {
            str(lv): ozetle([s for s in satirlar if s["level"] == lv])
            for lv in seviyeler}}
        print(f"  {kosul}: {time.monotonic() - t0:.0f} sn")

    print("\nseviye  " + "  ".join(f"{k:<20}" for k in kosullar)
          + "  bağlam-isabeti")
    for lv in seviyeler:
        b = bag[str(lv)]
        print(f"  {lv:<5} " + "  ".join(
            f"{hucre(sonuc[k]['seviye'][str(lv)]):<20}" for k in kosullar)
            + f"  ağırlık {b['agirlik_baglami']}/{b['n']}, program {b['kayitli_program']}/{b['n']}")
    print(f"  {'TOPLAM':<6}" + "  ".join(
        f"{hucre(sonuc[k]['toplam']):<20}" for k in kosullar))
    print("\nçözülenlerde ortanca deneme (≤1000 / ≤5000 içinde çözülen):")
    for k in kosullar:
        for lv in seviyeler:
            o = sonuc[k]["seviye"][str(lv)]
            print(f"  {k:<8} S{lv}: ortanca {o['ortanca_deneme']}  "
                  f"≤1000: {o['deneme_le_1000']}  ≤5000: {o['deneme_le_5000']}")
    zam = sum(sonuc[k]["toplam"]["zaman_asimi"] for k in kosullar)
    hat = sum(sonuc[k]["toplam"]["hata"] for k in kosullar)
    if zam:
        print(f"\nUYARI: {zam} zaman aşımı; sonuç makine yüküne bağlı olabilir "
              f"(--saniye artır).")
    if hat:
        print(f"\nUYARI: {hat} görevde istisna oluştu (ilki yukarıda).")

    rapor = {
        "zaman": time.time(), "sinav_id": sinav_id, "butce": a.butce,
        "state": {
            "toplam_gorev": state.total_tasks, "max_seviye": state.max_level,
            "baglam": len(state.weights.records),
            "primitif": sum(len(v) for v in state.primitives.values()),
            "basarisiz_onbellek": sum(len(v) for v in state.failures.values()),
            "kayitli_program": sum(len(v) for v in state.programs.values()),
        },
        "baglam_isabeti": bag, "sonuc": sonuc,
    }
    RAPOR_YOLU.write_text(json.dumps(rapor, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    with open(GECMIS_YOLU, "a", encoding="utf-8") as f:
        f.write(json.dumps(rapor, ensure_ascii=False) + "\n")
    print(f"\nrapor: {RAPOR_YOLU.name}   geçmiş: {GECMIS_YOLU.name}")


if __name__ == "__main__":
    main()
