"""CORE main — kalp atışı.

Algıla → karar ver → hareket et → enerjiye bak → öğren.
Tek süreç, tek döngü, tek "ben".

   python3 main.py                 # sonsuza kadar yaşar (Ctrl+C ile uyur)
   python3 main.py --ticks 20      # 20 tik yaşayıp durur
   python3 main.py --quiet         # günlüğe yazar, konsola az baskı yapar
"""

from __future__ import annotations

import argparse
import json
import queue
import time
from pathlib import Path

import body as body_mod
import brain as brain_mod
import atolye as atolye_mod
import damak as damak_mod
import door as door_mod
import drives as drives_mod
import ders as ders_mod
import gorev as gorev_mod
import guvenlik as guvenlik_mod
import journal as journal_mod
import kutu_uretici as kutu_mod
import kullan as kullan_mod
import meta_ogrenme as meta_ogrenme_mod
import olum as olum_mod
import paket as paket_mod
import surec as surec_mod
import training as training_mod
import uyku as uyku_mod
import uzuv as uzuv_mod
import zeka
import ust_beyn as ust_beyn_mod
import oz_hedef as oz_hedef_mod
import dusunme as dusunme_mod
import reward as reward_mod
from organism import Organism


ROOT = Path(__file__).resolve().parent


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    kurallar_path = ROOT / "kurallar.json"
    if kurallar_path.exists():
        with open(kurallar_path, encoding="utf-8") as f:
            kr = json.load(f)
        cfg["kutu_dir"] = kr.get("kutu", {}).get("dir")
        cfg["kutu_sonek"] = kr.get("kutu", {}).get("sonek", "")
        cfg["console_costs"] = kr.get("console_costs", {})
        cfg["kurallar"] = kr
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="CORE — yaşayan tek hücre")
    ap.add_argument("--config", default=str(ROOT / "body.json"))
    ap.add_argument("--ticks", type=int, default=0,
                    help="tik sayısı (0 = sonsuz)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--gorev", default=None,
                    help="görev dosyası (varsayılan: gorev.json)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--atolye-politika", default="sayim",
                    choices=("sayim", "eski", "yok", "surpriz"),
                    help="atölye keşif kolu")
    args = ap.parse_args()

    cfg = load_config(args.config)

    # Göç: eski konumdaki zeka dosyaları varsa zeka/'ya taşı
    tasinan = zeka.goc()

    jour = journal_mod.Journal(
        ROOT / cfg["stage"]["journal"], quiet=args.quiet
    )
    if tasinan:
        jour.log("zeka_goc", tasinan=tasinan)

    drives = drives_mod.Drives(cfg)
    mind = brain_mod.Brain(seed=args.seed)

    # Meta-öğrenme: lr/epsilon'ı dinamik ayarlar
    lim = uzuv_mod.LIM()
    meta = meta_ogrenme_mod.MetaOgrenme(mind, pencere=100, lim=lim)

    # İçsel keşif & serbest hedef motoru
    oz = oz_hedef_mod.OzHedef(mind, drives)

    brain_path = ROOT / cfg["stage"].get("brain", "brain.json")
    brain_path.parent.mkdir(parents=True, exist_ok=True)
    recalled = mind.load(brain_path)
    if recalled:
        jour.log("brain_recall", links=recalled)

    bod = body_mod.Body(cfg, ROOT, jour)

    # ---- Degraded mode: opsiyonel modüller try/except ile sarılıyor ----
    _modul_hatalari = []

    try:
        atolye = atolye_mod.Atolye(bod.world, jour, politika=args.atolye_politika)
        jour.log("atolye_load", nesne=len(atolye.nesneler))
    except Exception as _e:
        _modul_hatalari.append("atolye")
        atolye = None
        jour.log("modul_degraded", modul="atolye", hata=str(_e)[:200])

    bod.allowed |= set(getattr(mind, "allowed_extra", set()))
    mind.allowed_extra = bod.allowed

    # Görev / tezgâh
    gorev_cfg = {}
    gorev_yolu = Path(args.gorev) if args.gorev else (ROOT / "gorev.json")
    if gorev_yolu.exists():
        with open(gorev_yolu, encoding="utf-8") as f:
            gorev_cfg = json.load(f)
    tez = gorev_mod.Tezgah(gorev_cfg, bod, jour)

    # Komut kullanımı öğretmeni
    try:
        kul = kullan_mod.Kullan(cfg, ROOT)
        if kul.aktif:
            kul.don()
            jour.log("kullan_hedef",
                     tip=(kul.hedef or {}).get("tip"))
    except Exception as _e:
        _modul_hatalari.append("kullan")
        kul = None
        jour.log("modul_degraded", modul="kullan", hata=str(_e)[:200])

    # Damak (eğitilmiş isim-ödür damacı)
    try:
        dam = damak_mod.Damak()
        damak_ok = dam.load()
        if damak_ok:
            dam.lr = float(cfg.get("kurallar", {})
                           .get("damak_canli_lr", 0.02))
            jour.log("damak_load", samples=dam.samples, kova=len(dam.n))
    except Exception as _e:
        _modul_hatalari.append("damak")
        dam = None
        damak_ok = False
        jour.log("modul_degraded", modul="damak", hata=str(_e)[:200])

    # Güvenlik beyni
    try:
        guv = guvenlik_mod.Guvenlik()
        guv_ok = guv.load()
        if guv_ok:
            jour.log("guvenlik_load", samples=guv.samples, kova=len(guv.n))
        else:
            jour.log("guvenlik_yok", not_="egit_guvenlik.py ile eğit")
    except Exception as _e:
        _modul_hatalari.append("guvenlik")
        guv = None
        guv_ok = False
        jour.log("modul_degraded", modul="guvenlik", hata=str(_e)[:200])

    # Paket beyni
    try:
        paket_beyin = paket_mod.Paket()
        paket_ok = paket_beyin.load()
        if paket_ok:
            jour.log("paket_load", ornek=paket_beyin.ornek,
                     bilgi=len(paket_beyin.bilgi))
        else:
            jour.log("paket_yok", not_="egit_paket.py ile eğit")
    except Exception as _e:
        _modul_hatalari.append("paket")
        paket_beyin = None
        paket_ok = False
        jour.log("modul_degraded", modul="paket", hata=str(_e)[:200])

    # Ölüm beyni (Z3)
    try:
        olum_beyin = olum_mod.Olum()
        olum_ok = olum_beyin.load()
        if olum_ok:
            jour.log("olum_load", ornek=olum_beyin.ornek)
        else:
            jour.log("olum_yok", not_="egit_olum.py ile eğit")
    except Exception as _e:
        _modul_hatalari.append("olum")
        olum_beyin = None
        olum_ok = False
        jour.log("modul_degraded", modul="olum", hata=str(_e)[:200])

    # Bağışıklık / sureç
    try:
        sur = surec_mod.Surec(cfg)
        sur_ok = sur.load()
        jour.log("surec_load", ornek=sur.ornek, adet=len(sur.adet),
                 yuklendi=sur_ok)
    except Exception as _e:
        _modul_hatalari.append("surec")
        sur = None
        sur_ok = False
        jour.log("modul_degraded", modul="surec", hata=str(_e)[:200])

    # Uyku (konsolidasyon)
    try:
        uyku = uyku_mod.Uyku(cfg)
        uyku.set_meta(meta)
        jour.log("uyku_load", son=list(uyku.son.keys()))
    except Exception as _e:
        _modul_hatalari.append("uyku")
        uyku = None
        jour.log("modul_degraded", modul="uyku", hata=str(_e)[:200])

    # Üst (genel) beyin
    try:
        ust = ust_beyn_mod.UstBeyn(cfg, root=ROOT, seed=args.seed)
        jour.log("ust_beyn_load", samples=ust.samples)
    except Exception as _e:
        _modul_hatalari.append("ust_beyn")
        ust = None
        jour.log("modul_degraded", modul="ust_beyn", hata=str(_e)[:200])

    # Düşünme (eylem-öncesi simülasyon) + kendini-öğretim
    try:
        dusun = dusunme_mod.Dusunme(ust, path=ROOT / "zeka" / "dusunme.json")
        if dusun.load():
            jour.log("dusunme_load", samples=dusun.samples)
        else:
            jour.log("dusunme_yeni", not_="öğrenilmiş ödül örneği yok")
        selftrainer = training_mod.SelfTrainer(ust, jour.path)
        selftrainer.set_cmd_resolver(
            lambda komut: ust_beyn_mod.KOMUT_INDEKSI.get(komut))
        if cfg["stage"].get("training", False):
            selftrainer.start()
            jour.log("training_start",
                     samples=selftrainer.stats()["samples"])
    except Exception as _e:
        _modul_hatalari.append("dusunme")
        dusun = None
        selftrainer = None
        jour.log("modul_degraded", modul="dusunme", hata=str(_e)[:200])

    msgs = queue.Queue()
    state = {"ticks": 0, "last": "-"}

    def status() -> dict:
        s = drives.state()
        s.update(name=cfg["identity"]["name"], last=state["last"],
                 ticks=state["ticks"])
        return s

    try:
        door = door_mod.Door(cfg["door"]["host"], cfg["door"]["port"],
                             status, msgs, jour)
        door.start()
        jour.log("birth", **status())
    except Exception as _e:
        _modul_hatalari.append("door")
        door = None
        jour.log("modul_degraded", modul="door", hata=str(_e)[:200])

    # Uzuv entegrasyonu
    try:
        uzuv = uzuv_mod.AsmUzuv()
        jour.log("uzuv_baslat", not_="x86-64 asm uzuv entegre edildi")
    except Exception as _e:
        _modul_hatalari.append("uzuv")
        uzuv = None
        jour.log("modul_degraded", modul="uzuv", hata=str(_e)[:200])

    if _modul_hatalari:
        jour.log("degraded_baslat", moduller=_modul_hatalari)

    # ----- Organizmayı oluştur ve döngüyü başlat -----
    organism = Organism(
        cfg=cfg,
        root=ROOT,
        journal=jour,
        door=door,
        brain_path=str(brain_path),
        args=args,
        state=state,
        mind=mind,
        ust=ust,
        drives=drives,
        bod=bod,
        tez=tez,
        kul=kul,
        dam=dam,
        meta=meta,
        oz=oz,
        dusun=dusun,
        atolye=atolye,
        sur=sur,
        guv=guv,
        paket_beyin=paket_beyin,
        olum_ok=olum_ok,
        olum_beyin=olum_beyin,
        selftrainer=selftrainer,
        uyku=uyku,
    )

    try:
        while True:
            devam = organism.tik_at()
            if not devam:
                break
            if args.ticks and state["ticks"] >= args.ticks:
                break
    except KeyboardInterrupt:
        jour.log("interrupt", note="kullanıcı ile durduruldu")
    finally:
        organism.lifecycle.handle_death(args.ticks, state, organism.hedef_tip)
        organism.lifecycle.save_all(state["ticks"])
        organism.lifecycle.kapat()
        jour.log("shutdown", ticks=state["ticks"])


if __name__ == "__main__":
    main()