"""ab_asm_nn.py — ASM öğrenmesi için kalıcı A/B ölçüm betiği.

Koşullar
--------
nn_yok : AssemblyLearner ohne nöral beyin (sadece WeightTable / düz arama)
nn_var : mevcut nn_ana mimarisi (48-256-5) rastgele 48 boyutlu stim ile hibrit

Bu betik Adım 1'deki ölçümü tek komutla tekrarlanabilir kılar. seed'ler 1-5,
her koşulda ``--sn`` saniye kadar çalışır. Ağlı koşulda ``zeka/nn_deney_*.json``
dosyaları oluşur; ölçümden sonra silinir.

Kullanım:
    python3 ab_asm_nn.py               # 5 seed, 60 sn/koşul
    python3 ab_asm_nn.py --sn 120 --seeds 1,2,3,4,5

Çıktı: seed başarıyla tablo + koşul bazında ortalama ve standart sapma.
"""

from __future__ import annotations

import argparse
import random
import shutil
import statistics as st
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import noral_beyn as nb  # noqa: E402
from noral_beyn import NöralUstBeyn as UstBeyn  # noqa: E402

ZEKA = Path("zeka")
NN_SHAPE = [48, 64, 7]   # nn_asm: 48 görev-özellik girişi, 64 gizli, 7 op-aile çıkışı
NN_LR = 0.12


def calis(nn_kullan: bool, seed: int, sn: float) -> dict:
    """Tek (koşul, seed) deneyi çalıştırır ve sonuçları döndürür.

    ``root`` geçici dizine alınır çünkü AssemblyLearner``uzuv/asm_ogren.json``
    ve AsmUzuv kök altına yazar. ``zeka/`` altındaki nn dosyaları ise sabit
    konuma yazılır (noral_beyn.sabit), adlarıyla deneyden ayrıştırılır.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"ab_asm_{'nn' if nn_kullan else 'nok'}_{seed}_"))
    nn = None
    try:
        u = UstBeyn({}, root=tmp, seed=seed)
        rnd = random.Random(7)
        stim = [round(rnd.random(), 3) for _ in range(48)]
        if nn_kullan:
            nn = nb.NöralBeyn(f"deney_{int(nn_kullan)}_{seed}", NN_SHAPE, lr=NN_LR)
        r = u.asm_öğren(sn / 60.0, nn_ana=nn, stim_ust=stim if nn else None)

        learner = getattr(u, "_asm_öğrenici", None)
        session = learner.state.history if (learner is not None and learner.state is not None) else []
        denemeler = [g.get("deneme") for g in session if g.get("cozuldu")]
        all_denemeler = [g.get("deneme") for g in session if isinstance(g.get("deneme"), (int, float))]

        return {
            "nn": nn_kullan,
            "seed": seed,
            "sn": sn,
            "toplam_gorev": r.get("toplam_gorev"),
            "maks_seviye": r.get("maks_seviye"),
            "oturum_gorev": r.get("oturum_gorev", 0),
            "oturum_cozulen": r.get("oturum_cozulen", 0),
            "oran": (100.0 * r.get("oturum_cozulen", 0) / r.get("oturum_gorev", 1)) if r.get("oturum_gorev") else 0.0,
            "ortalama_deneme": (st.mean(denemeler) if denemeler else 0.0),
            "ortalama_deneme_tum": (st.mean(all_denemeler) if all_denemeler else 0.0),
            "nn_adim": (nn.adım if nn is not None else None),
            "nn_mse": (nn.hız_geçmişi[-1] if (nn is not None and nn.hız_geçmişi) else None),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def temizle_deney_dosyalari() -> None:
    """Ölçümden sonra oluşan geçici nn_deney_*.json dosyalarını siler."""
    if not ZEKA.exists():
        return
    for dosya in ZEKA.glob("nn_deney_*.json"):
        try:
            dosya.unlink()
        except OSError:
            pass


def ozet(alt: list[dict]) -> dict:
    oranlar = [s["oran"] for s in alt]
    gorevler = [s["oturum_gorev"] for s in alt]
    cozulenler = [s["oturum_cozulen"] for s in alt]
    denemeler = [s["ortalama_deneme"] for s in alt if s["ortalama_deneme"] > 0]
    nn_adimlar = [s["nn_adim"] for s in alt if s["nn_adim"] is not None]
    return {
        "n": len(alt),
        "gorev_ort": st.mean(gorevler) if gorevler else 0.0,
        "cozulma_ort": st.mean(oranlar) if oranlar else 0.0,
        "cozulma_std": st.pstdev(oranlar) if len(oranlar) > 1 else 0.0,
        "deneme_ort": st.mean(denemeler) if denemeler else 0.0,
        "nn_adim_ort": (st.mean(nn_adimlar) if nn_adimlar else None),
        "toplam_cozulen": sum(cozulenler),
        "toplam_gorev": sum(gorevler),
    }




def main() -> int:
    ap = argparse.ArgumentParser(description="ASM nn_ana A/B ölçüm betiği")
    ap.add_argument("--seeds", default="1,2,3,4,5", help="virgülle ayrılmış seed listesi")
    ap.add_argument("--sn", type=float, default=60.0, help="koşul başına saniye")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    sonuclar: list[dict] = []
    for seed in seeds:
        for nn_kullan in (False, True):
            sonuclar.append(calis(nn_kullan, seed, args.sn))

    temizle_deney_dosyalari()

    print(f"\n=== A/B ölçüm raporu (sn={args.sn}, seeds={seeds}) ===\n")
    print(f"{'koşul':<8} {'seed':<5} {'gorev':<6} {'cozuldu':<8} {'oran%':<7} {'ort.deneme':<10} {'nn_adim':<8}")
    for s in sonuclar:
        print(
            f"{'nn_asm' if s['nn'] else 'nn_yok':<8} "
            f"{s['seed']:<5} "
            f"{s['oturum_gorev']:<6} "
            f"{s['oturum_cozulen']:<8} "
            f"{s['oran']:<7.1f} "
            f"{s['ortalama_deneme']:<10.1f} "
            f"{s['nn_adim'] if s['nn_adim'] is not None else '-':<8}"
        )

    print("\n--- Koşul özetleri ---")
    for nn_kullan in (False, True):
        alt = [s for s in sonuclar if s["nn"] == nn_kullan]
        o = ozet(alt)
        print(
            f"{'nn_asm' if nn_kullan else 'nn_yok':<8} "
            f"n={o['n']} gorev_ort={o['gorev_ort']:.1f} "
            f"cozulma%_ort={o['cozulma_ort']:.1f} (±{o['cozulma_std']:.1f}) "
            f"deneme_ort={o['deneme_ort']:.1f} "
            f"toplam={o['toplam_cozulen']}/{o['toplam_gorev']}"
            + (f" nn_adim_ort={o['nn_adim_ort']:.0f}" if o["nn_adim_ort"] is not None else "")
        )

    nn_var = ozet([s for s in sonuclar if s["nn"]])
    nn_yok = ozet([s for s in sonuclar if not s["nn"]])
    fark = (nn_var["cozulma_ort"] - nn_yok["cozulma_ort"]) if nn_yok["cozulma_ort"] > 0 else None
    print(f"\nFark (nn_var - nn_yok) cozulma oran puan: {fark if fark is not None else '-'}")
    print("\nBitti: betik tek komutla çalıştı ve iki koşulun tablosunu bastı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
