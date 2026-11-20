"""CORE organism — ana yaşam döngüsü (tick orchestration).

main.py'deki while döngüsünü ayrıştırır:
  * sinyal toplama (36 boyutlu vektör)
  * karar verme (alt beyin + üst beyin override)
  * eylem yürütme ve ödül hesaplama
  * öğrenme (mind.learn, ust.ogren, meta, oz_hedef)
  * periyodik kayıt, replay, konsolidasyon
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import time

import body as body_mod
import brain as brain_mod
import ag_beyin as ag_beyin_mod
import usb_beyn as usb_beyn_mod
import noral_beyn as noral_beyn_mod
import hata_katalogu as hata_katalogu_mod
import neden as neden_mod
import damak as damak_mod
import ders as ders_mod
import journal as journal_mod
from oz_hedef import HedefSeviyesi
import kullan as kullan_mod
import meta_ogrenme as meta_ogrenme_mod
import surec as surec_mod
import home_world as home_world_mod
import uzuv as uzuv_mod
import ust_beyn as ust_beyn_mod
import reward as reward_mod
from decision import DecisionEngine
from lifecycle import LifecycleManager


class Organism:
    """CORE organizmanın ana yaşam döngüsü."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        root: Any,
        journal: Any,
        door: Any,
        brain_path: str,
        args: Any,
        state: Dict[str, Any],
        mind: Any,
        ust: Any,
        drives: Any,
        bod: Any,
        tez: Any,
        kul: Any,
        dam: Any,
        meta: Any,
        oz: Any,
        dusun: Any,
        atolye: Any,
        sur: Any,
        guv: Any,
        paket_beyin: Any,
        olum_ok: bool,
        olum_beyin: Any,
        selftrainer: Any,
        uyku: Any = None,
        hedef_tip: Optional[str] = None,
    ) -> None:
        self.cfg = cfg
        self.root = root
        self.journal = journal
        self.door = door
        self.brain_path = brain_path
        self.args = args
        self.state = state

        self.mind = mind
        self.ust = ust
        self.drives = drives
        self.bod = bod
        self.tez = tez
        self.kul = kul
        self.dam = dam
        self.meta = meta
        self.oz = oz
        self.dusun = dusun
        self.atolye = atolye
        self.sur = sur
        self.guv = guv
        self.paket_beyin = paket_beyin
        self.olum_ok = olum_ok
        self.olum_beyin = olum_beyin
        self.selftrainer = selftrainer
        self.uyku = uyku
        self.ag_beyin = ag_beyin_mod.AgBeyin(root)
        self.usb_beyn = usb_beyn_mod.UsbBeyin(root)
        # ---------- Nöral beyinler (kanal bazlı, kendi dosyalarıyla) ----------
        self.nn_usb = noral_beyn_mod.NöralBeyn("usb", [6, 5, 3], lr=0.15)
        self.nn_ag = noral_beyn_mod.NöralBeyn("ag", [6, 5, 3], lr=0.15)
        self.nn_ana = noral_beyn_mod.NöralBeyn("ana", [48, 256, 5], lr=0.12)
        self.hedef_tip = hedef_tip
        self.home_world = home_world_mod.HomeWorld(
            cfg.get("environment", {})
        )
        self._home_world_signature = None
        self._asm_command_active = False
        self.uzuv_risk = False
        self.canlanma_sayisi = 0
        # Sıkılma kırıcı: aynı eylemi N tik tekrarladıysa küçük novelty üretir
        self._onceki_akt = None
        self._tekrar_sayaci = 0
        # Tutarlılık denetimi sayacı (her 100 tikte bir)
        self._tutarlilik_sayaci = 0
        # Yeni dizin zorlama: organizma henüz ziyaret etmediği dizinleri takip et
        self._ziyaret_edilen_dizinler = set()

        # Alt sistemler
        self.decision = DecisionEngine(
            ust=ust,
            mind=mind,
            oz=oz,
            drives=drives,
            door=door,
            cfg=cfg,
            journal=journal,
            dusun=dusun,  # Faz 4: durum tahmini
            ag_beyin=self.ag_beyin,  # Ağ keşif entegrasyonu
        )
        # Üst beyin'e ag_beyin referansını bağla (scan_hazir_mi, scan_calistir, scan_odulu_besle)
        ust.ag_beyin = self.ag_beyin
        self.reward_h = reward_mod.OdulHesaplayici(cfg)
        self.lifecycle = LifecycleManager(
            mind=mind,
            ust=ust,
            journal=journal,
            door=door,
            drives=drives,
            sur=sur,
            dam=dam,
            guv=guv,
            paket_beyin=paket_beyin,
            kul=kul,
            dusun=dusun,
            olum_ok=olum_ok,
            olum_beyin=olum_beyin,
            cfg=cfg,
            root=root,
            brain_path=brain_path,
            golge_yolu=cfg.get("stage", {}).get("golge", "golge_log.jsonl"),
            journal_azami_mb=cfg.get("stage", {}).get("journal_azami_mb", 20),
            golge_azami_mb=cfg.get("stage", {}).get("golge_azami_mb", 70),
            selftrainer=selftrainer,
            status_fn=self._status,
        )

        # Döngü durumu
        self.tick_sleep: float = cfg.get("metabolism", {}).get("tick_seconds", 0.4)
        self.jour = journal
        self.was_danger: bool = False
        self.recent: List[tuple] = []
        self._yemek_var_ust: bool = False
        self._sinyal_ust: List[float] = []
        self._uyku_son_tik: int = 0

        # Hata takibi: son N tikteki başarısızlık sayısı per eylem
        self._hata_son_n: Dict[str, int] = {}
        self._hata_son_n_window: int = 10

        # Faz 4: durum geçiş takibi (Markov zinciri) için önceki tik bilgisi
        self._onceki_stim: Optional[str] = None
        self._onceki_act: Optional[str] = None
        self._onceki_sinyal_v: Optional[List[float]] = None

        # Faz 5: neden / kanıt üretimi
        self.neden = neden_mod.NedenUretici(self.mind, self.dusun)

        # Faz 7: dışsal geri bildirim takibi
        self._dis_sal_geribildirim: Optional[str] = None

    # ------------------------------------------------------------------ durum raporu

    def _status(self) -> Dict[str, Any]:
        """Güncel organizma durumu (günlük / ölüm kaydı için)."""
        return {
            "ticks": self.state.get("ticks", 0),
            "energy": round(self.drives.energy, 1),
            "hunger": round(self.drives.hunger, 1),
            "alive": self.drives.alive,
            "homeostaz": round(self.drives.homeostaz_puani(), 2),
            "hayatta_kalma": self.drives.hayatta_kalma_modu,
            "brain_links": len(self.mind.w) if self.mind is not None else 0,
            "ust_samples": self.ust.samples,
        }

    # ------------------------------------------------------------------ tek tik

    def tik_at(self) -> bool:
        """Tek tik döngüsü. False dönerse organizma ölmüştür / durdurulmuştur."""
        tik = self.state.get("ticks", 0)
        tik += 1
        self.state["ticks"] = tik
        if self.kul is not None:
            self.hedef_tip = (self.kul.hedef or {}).get("tip")

        # ---------- 0. Metabolizma (enerji harcaması + açlık artışı) ----------
        self.drives.tick()
        if not self.drives.alive:
            metabolism = self.cfg["metabolism"]
            self.drives.energy = float(metabolism["energy_start"])
            self.drives.hunger = float(metabolism.get("hunger_start", 10))
            self.canlanma_sayisi += 1
            self.jour.log(
                "canlanma",
                sayi=self.canlanma_sayisi,
                **self._status(),
            )
        self.mind.working_sindir()
        # Beden/ dünya döngüsü: yemek regrow, tohum yönetimi, valf kontrolü
        self.bod.tick(energy=self.drives.energy)
        self.atolye.tikla(tik)
        world_cfg = self.cfg.get("world", {})
        self.drives.decay_factor = (
            float(world_cfg.get("shelter_factor", 1.0))
            if self.bod.has_nest()
            else 1.0
        )
        self._yerel_surecleri_izle(tik)
        if tik % 10 == 0:
            self._ag_envanteri_guncelle()
        if getattr(self.sur, "eksik", False):
            self.drives.decay_factor *= self.sur.dusman
        self._uzuv_riskini_guncelle(tik)
        self._uykuyu_denetime_al(tik)
        self._beden_duyularini_olcer(tik)

        # ---------- 1. Sinyal toplayıcı ----------
        stim = self._topla_sinyal()                    # string for brain.decide()
        stim_ust = self._topla_sinyal_ust()            # numeric for ust.sec()
        self._sinyal_ust = stim_ust                    # store for upper-brain learning

        # ---------- Faz 4: durum geçiş kaydı ----------
        # (onceki_sinyal_v, onceki_act) -> su anki stim_ust geçişini kaydet
        if (
            self.dusun is not None
            and self._onceki_sinyal_v is not None
            and self._onceki_act is not None
        ):
            self.dusun.observe_gecis(
                self._onceki_sinyal_v,
                self._onceki_act,
                stim_ust,
            )

        # ---------- 2. Alt beyin karar ----------
        # (3) Epsilon/lr'yi iç duruma göre dinamik ayarla (bağlama bazlı keşif)
        try:
            self.mind.update_dynamic_params(self.drives)
        except Exception:
            pass
        feasible = self._hesapla_feasible()
        # (4) Düşünme tahmini ile eyleme yönlü ödül iyileştirme
        dusun_bonus = 0.0
        dusun_act = None
        if self.dusun is not None:
            try:
                _t, _s = self.dusun.tahmin(self._sinyal_ust, None)
                if _t is not None:
                    dusun_act = _t
                    dusun_bonus = float(_s) * 0.5  # tahmin skorunun yarısı kadar bonus
            except Exception:
                pass
        act = self.mind.decide(stim, feasible, dusun_bonus=dusun_bonus,
                               dusun_act=dusun_act) if feasible else "rest"

        # ---------- 3. Üst beyin override ----------
        self.decision.asm_son = None
        self.decision.sec_override(stim_ust, epsilon=self._epsilon_tik())
        asm_requested = (
            self.decision.override_aktif
            and self.decision.komut_ust == ust_beyn_mod.KOMUT_ASM_OGREN
        )
        asm_new_request = asm_requested and not self._asm_command_active
        self._asm_command_active = asm_requested
        if self.decision.override_aktif:
            self.jour.log(
                "ust_beyn_override",
                komut=self.decision.komut_ust,
                idx=self.decision.idx_ust,
                guven=round(self.decision.guven_ust, 3),
                kaynak=self.decision.kaynak_ust,
            )
            # Komut ömrünü başlat: 3 tik
            self.ust.komut_ayarla(
                self.decision.komut_ust, self.decision.idx_ust, sure=3
            )

            # Override komutuna göre feasible'ı kısıtla / genişlet
            feasible, act = self.decision.duzenle_feasible(stim, feasible, act)
            if asm_requested:
                act = "rest"
        else:
            # Özhedef entegrasyonu (override yokken)
            # ACIL seviye hedefleri: hayatta kalma eylemleri (enerji kritik, acı)
            if self.drives.in_danger:
                if "eat" not in [g.get("eylem") for g in self.oz.hedef_deposu[HedefSeviyesi.ACIL]]:
                    self.oz.hedef_deposu[HedefSeviyesi.ACIL].append({
                        "tip": "acil_yem",
                        "aciklama": "enerji kritikte acil yemek gerekiyor",
                        "eylem": "eat",
                    })
                if self.drives.energy < self.drives.pain_threshold * 0.5:
                    if "rest" not in [g.get("eylem") for g in self.oz.hedef_deposu[HedefSeviyesi.ACIL]]:
                        self.oz.hedef_deposu[HedefSeviyesi.ACIL].append({
                            "tip": "acil_dinlen",
                            "aciklama": "enerji kritik seviyede acil dinlenme",
                            "eylem": "rest",
                        })

            oz_h = self.oz.mevcut_hedef()
            if oz_h and oz_h.get("tip") == "novel_eylem":
                eylem = oz_h.get("eylem")
                if eylem and eylem not in feasible:
                    feasible.append(eylem)
                    self.jour.log("oz_hedef_eklendi", **oz_h)
            act = self.mind.decide(stim, feasible) if feasible else "rest"
            if oz_h and oz_h.get("tip") == "novel_eylem" and oz_h.get("eylem") == act:
                self.oz.hedef_secildi(act)

            # Sağlıklı durumda yerel keşif daha sık; ağ görevleri varsayılan
            # keşif aralığını korur ve kendiliğinden yoğunlaştırılmaz.
            kesif_araligi = self._kesif_araligi()
            if tik and tik % kesif_araligi == 0 and len(feasible) > 1:
                digerleri = [a for a in feasible if a != act]
                if digerleri:
                    import random
                    act = self.mind.rng.choice(digerleri)
                    self.jour.log(
                        "forced_explore", action=act, interval=kesif_araligi
                    )

        feasible, act = self._beslenmeyi_sinirla(stim, feasible, act)

        # ---------- 4. Çalışma belleği ----------
        if self.mind is not None:
            self.mind.working_remember(stim, act)

        # ---------- 5. Eylem öncesi fotoğraf ----------
        _enerji_once = float(self.drives.energy)
        _aclik_once = float(self.drives.hunger)
        self._budanan_ust = 0
        self._bag_once_ust = len(self.mind.w) if self.mind is not None else 0

        path: Optional[str] = None
        pred: Optional[float] = None
        veto: float = 0.0

        if act == "eat":
            food = self.bod.find_food()
            if food:
                kcfg = self.cfg.get("kurallar") or self.cfg
                damak_ok = getattr(self.dam, "ok", True)
                path = (
                    self.dam.sec(food, kcfg, epsilon=0.15)
                    if damak_ok
                    else __import__("random").choice(food)
                )
                if path and self.bod.kutu_yolu(path):
                    pred = self.dam.tahmin(
                        damak_mod.ozellikler(path.split("/")[-1], kcfg, path=path)
                    )
            else:
                # Yemek yok: boş deneme
                res_eat = {
                    "obs": "yemek yok",
                    "kind": "file",
                    "novel": 0,
                    "gain": 0,
                    "relief": 0,
                    "unlock": [],
                }

        # ---------- 6. Eylem yürütme ----------
        res: Dict[str, Any] = {"obs": "", "kind": "act", "novel": 0, "gain": 0}
        try:
            if asm_new_request:
                if act == "rest":
                    self.decision.asm_son = self._asm_ogren_komutunu_calistir()
                else:
                    self.jour.log(
                        "asm_ogren_atlandi",
                        neden="eylem_onceligi",
                        eylem=act,
                    )
            if act == "katalogla":
                res = self.tez.calistir_bir(tik)
                self.bod.last_cost = body_mod.Body.COSTS.get("katalogla", 3)
            elif act == "nedir":
                res = self.tez.nedir_bir(self.paket_beyin)
                self.bod.last_cost = body_mod.Body.COSTS.get("nedir", 2)
            elif act == "konum":
                res = self.tez.konum_bir()
                self.bod.last_cost = body_mod.Body.COSTS.get("konum", 2)
            elif act == "birak":
                deneme = getattr(self.kul, "hedef_deneme", 0) if self.kul else 0
                veto = 1.0 if deneme >= 2 else -1.0
                res = {
                    "obs": "bıraktı (%s, deneme=%d)" % (self.hedef_tip, deneme),
                    "kind": "birak",
                    "novel": 0,
                    "gain": 0,
                }
                self.jour.log("birak", hedef=self.hedef_tip, deneme=deneme)
                if self.kul is not None:
                    self.kul.birak()
                self.bod.last_cost = 0
            elif act.startswith("cmd:") or act.startswith("help:"):
                if self.kul is not None:
                    res = self.kul.uygula(act)
                else:
                    res = {"dogru": False, "cost": 2, "gain": 0}
                res["hedef_tip"] = res.get("hedef_tip") or self.hedef_tip
                self.bod.last_cost = float(res.get("cost", 2))
                self.meta.transfer(
                    dogru=res.get("dogru"),
                    komut_tehlike=res.get("komut_tehlike", 0.0),
                    komut_tip=res.get("komut_tip"),
                )
            elif act == "atolye":
                res = self.atolye.eylem(self.atolye.sec_is(), None)
                self.bod.last_cost = body_mod.Body.COSTS.get("atolye", 1)
            elif act == "eat" and not path:
                res = {
                    "obs": "yemek yok",
                    "kind": "file",
                    "novel": 0,
                    "gain": 0,
                    "relief": 0,
                    "unlock": [],
                }
                self.bod.last_cost = body_mod.Body.COSTS.get("eat", 2)
            else:
                res = self.bod.perform(act, path=path)
        except Exception as e:
            import traceback

            tb = traceback.format_exc(limit=3)
            self.jour.log(
                "hata",
                act=act,
                err=type(e).__name__,
                msg=str(e)[:200],
                iz=tb[-400:],
            )
            self.bod.last_cost = body_mod.Body.COSTS.get(act, 2)
            res = {
                "obs": "eylem bozuldu: %s" % type(e).__name__,
                "kind": "hata",
                "novel": 0,
                "gain": 0,
            }

        self.state["last"] = act

        # --- Yeni dizin zorlama: explore:<ad> eylemlerini takip et ---
        if isinstance(act, str) and act.startswith("explore:"):
            _dizin_adi = act.split(":", 1)[-1]
            self._ziyaret_edilen_dizinler.add(_dizin_adi)

        # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
        # Beden duyularının sonuçlarını okuyup drives'e aktar, böylece
        # organizmanın iç durumu bu bilgisayarın fiziksel durumuna bağlanır.
        if isinstance(res, dict) and isinstance(act, str):
            import re
            _obs = str(res.get("obs", ""))
            _insan = self.drives.insan_var
            _saat = self.drives.sistem_saati
            _disk = self.drives.disk_yuzde
            _bellek = self.drives.bellek_yuzde

            if act == "sense_kullanici":
                _insan = "kullanici_yok" not in _obs and "aktif:" in _obs
            elif act == "sistem_umuru":
                _m = re.search(r"acik:(\d+)g(\d+)s(\d+)", _obs)
                if _m:
                    _g, _s, _d = int(_m.group(1)), int(_m.group(2)), int(_m.group(3))
                    _saat = _g * 24 + _s + _d / 60.0
            elif act == "terminal_var":
                pass  # terminal_var zaten insan_var ipucu verir, ayrı işlem yok
            elif act == "sense_disk":
                _m = re.search(r"disk:([\d.]+)%", _obs)
                if _m:
                    _disk = float(_m.group(1))
            elif act == "sense_bellek":
                # /proc/meminfo satırlarından bellek oranını tahmin et
                _total = None
                _avail = None
                for _line in _obs.split(";"):
                    _line = _line.strip()
                    if _line.startswith("MemTotal:"):
                        try:
                            _total = int(_line.split(":")[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                    elif _line.startswith("MemAvailable:"):
                        try:
                            _avail = int(_line.split(":")[1].strip().split()[0])
                        except (ValueError, IndexError):
                            pass
                if _total and _avail is not None and _total > 0:
                    _bellek = round((_total - _avail) / _total * 100, 1)

            self.drives.beden_guncelle(
                _insan, _saat, _disk, _bellek,
                usb_cihaz=res.get("cihaz_sayisi", 0) or 0,
                usb_node=res.get("node_sayisi", 0) or 0,
            )

        # ---------- Yeni: USB ögrenme — uzuv-usb (Aşama 10) ----------
        # Organizma USB cihazlarını algiladiginda uzuv-usb dizinine kayit
        # yazar, böylece cihaz laidini hatirlayabilir ve uzerinden ogrenir.
        # USB beyni (usb_beyn.py / zeka/usb.json) ile kalıcı öğrenme.
        if isinstance(act, str) and act == "sense_usb_kernel":
            try:
                _detayli = []
                for _cb in res.get("cihazlar", []):
                    # "usb:1-1 v=1d6b p=0002 if=1 mfr=Linux prd=xHCI"
                    _parca = _cb.split()
                    _cihaz_bilgi = {"adres": "?", "vendor": "?", "product": "?", "manufacturer": "", "product_name": "", "interfaces": "?"}
                    for _p in _parca:
                        if _p.startswith("usb:"):
                            _cihaz_bilgi["adres"] = _p[4:]
                        elif _p.startswith("v="):
                            _cihaz_bilgi["vendor"] = _p[2:]
                        elif _p.startswith("p="):
                            _cihaz_bilgi["product"] = _p[2:]
                        elif _p.startswith("mfr="):
                            _cihaz_bilgi["manufacturer"] = _p[4:]
                        elif _p.startswith("prd="):
                            _cihaz_bilgi["product_name"] = _p[4:]
                        elif _p.startswith("if="):
                            _cihaz_bilgi["interfaces"] = _p[3:]
                    _detayli.append(_cihaz_bilgi)
                if _detayli:
                    for _c in _detayli:
                        _sonuc = self.usb_beyn.learn(_c)
                        # ---------- Nöral beyin: USB cihazından öğren ----------
                        _v = int(_c.get("vendor", "0"), 16) if _c.get("vendor", "0").isdigit() or all(c in "0123456789abcdefABCDEF" for c in _c.get("vendor", "0")) else 0
                        _p = int(_c.get("product", "0"), 16) if _c.get("product", "0").isdigit() or all(c in "0123456789abcdefABCDEF" for c in _c.get("product", "0")) else 0
                        _ifc = int(_c.get("interfaces", "0")) if str(_c.get("interfaces", "0")).isdigit() else 0
                        _mfr = 1.0 if _c.get("manufacturer") else 0.0
                        _prd = 1.0 if _c.get("product_name") else 0.0
                        _yeni = 1.0 if _sonuc["yeni_mi"] else 0.0
                        # 6 boyutlu girdi: [vendor, product, interfaces, mfr, prd, yeni]
                        _nn_giriş = [_v / 65535.0, _p / 65535.0,
                                     _ifc / 16.0, _mfr, _prd, _yeni]
                        # Hedef: yeni cihazsa meraklı hedef [1, 0, 0], bilikse [0, 1, 0]
                        _nn_hedef = [1.0, 0.0, 0.0] if _sonuc["yeni_mi"] else [0.0, 1.0, 0.0]
                        self.nn_usb.öğren(_nn_giriş, _nn_hedef)
                        if _sonuc["yeni_mi"]:
                            self.jour.log(
                                "usb_yeni_cihaz",
                                vendor=_c["vendor"],
                                product=_c["product"],
                                adres=_c["adres"],
                            )
                            # Yeni USB cihaz keşfedildi → merak artır (Aşama 11)
                            self.drives.usb_yeni_cihaz_buldu()
            except Exception as _e:
                self.jour.log(
                    "usb_kayit_hata", hata=str(_e)[:200])

        # Ağ trafiği gözlemi sonucunu Ağ-Beyn'e öğret (zeka/ag_beyin.json)
        if isinstance(act, str) and act == "sense_ag_trafigi":
            try:
                _baglantilar = res.get("baglanti_detay", []) or []
                for _b in _baglantilar[:20]:
                    _t = self.ag_beyin.learn_traffic(_b)
                    # ---------- Nöral beyin: Ağ trafiğinden öğren ----------
                    _lp = float(_b.get("local_port", 0)) / 65535.0
                    _rp = float(_b.get("remote_port", 0)) / 65535.0
                    _proto = 1.0 if str(_b.get("protocol", "")).lower() == "tcp" else 0.0
                    _st = float(_b.get("state", "0")) / 255.0 if str(_b.get("state", "0")).isdigit() else 0.0
                    _nn_giriş = [_lp, _rp, _proto, _st, 0.5, 0.5]
                    _nn_hedef = [1.0, 0.0, 0.0] if _t["yeni_mi"] else [0.0, 1.0, 0.0]
                    self.nn_ag.öğren(_nn_giriş, _nn_hedef)
                    if _t["yeni_mi"]:
                        self.jour.log(
                            "ag_yeni_trafigi",
                            local_port=_b.get("local_port"),
                            remote_port=_b.get("remote_port"),
                            protocol=_b.get("protocol"),
                            key=_t["key"],
                        )
                        # Yeni ağ deseni keşfedildi → merak artır
                        self.drives.ag_yeni_trafigi_buldu()
            except Exception as _e:
                self.jour.log(
                    "ag_trafigi_hata", hata=str(_e)[:200])

        # --- Sıkılma kırıcı: aynı eylemi N tik tekrarladıysa küçük novelty ---
        if act == self._onceki_akt:
            self._tekrar_sayaci += 1
        else:
            self._tekrar_sayaci = 0
            self._onceki_akt = act

        if self._tekrar_sayaci >= 20:
            self.drives.sikilan(novelty=0.3)
            self.jour.log(
                "sikilma_kirici",
                eylem=act,
                tekrar=self._tekrar_sayaci,
                sikilma=round(self.drives.sikilma, 3),
            )
            self._tekrar_sayaci = 0

        cost = self.bod.last_cost
        self.drives.spend(cost)
        gain: float = 0.0
        relief_done: float = 0.0

        if act == "eat":
            gain, relief_done = self.drives.consume(
                res.get("gain", 0), res.get("relief", 0)
            )
        elif act in ("katalogla", "konum", "nedir") or act.startswith(
            "cmd:"
        ) or act.startswith("help:"):
            odul = int(res.get("gain", 0))
            if odul:
                gain, _ = self.drives.consume(odul, 0)
            if act.startswith("cmd:") or act.startswith("help:"):
                self.jour.log(
                    "kullan",
                    hedef=res.get("hedef_tip"),
                    komut=act,
                    dogru=(res.get("dogru")
                           if isinstance(res.get("dogru"), bool) else None),
                    dogrulanmis=bool(res.get("dogrulanmis", False)),
                    ilerleme=bool(res.get("ilerleme", False)),
                    gorev_sonucu=res.get("gorev_sonucu"),
                    help_ok=res.get("help_ok"),
                    odul=odul,
                    deneme=res.get("deneme"),
                    calisti=res.get("calisti"),
                    obs=str(res.get("obs", ""))[:180],
                )
                if res.get("engel"):
                    self.jour.log(
                        "kullan_engel",
                        hedef=res.get("hedef_tip"),
                        komut=act,
                        neden=res.get("obs", "")[:200],
                        deneme=res.get("deneme"),
                    )
                if res.get("duraklama"):
                    self.jour.log(
                        "kullan_duraklama",
                        hedef=res.get("hedef_tip"),
                        komut=act,
                        deneme=res.get("deneme"),
                        calisti=res.get("calisti"),
                        obs=str(res.get("obs", ""))[:180],
                    )
                    alt = {
                        "cmd:pgrep": "cmd:ps",
                        "cmd:ps": "cmd:pgrep",
                        "cmd:find": "cmd:ls",
                        "cmd:ls": "cmd:find",
                    }.get(act)
                    if (
                        alt
                        and res.get("hedef_tip") in ("SUREC_SAY", "DOSYA_SAY")
                        and self.kul is not None
                        and alt in self.kul.eylemler()
                    ):
                        res2 = self.kul.uygula(alt)
                        res2["hedef_tip"] = res.get("hedef_tip")
                        self.jour.log(
                            "kullan",
                            hedef=res2.get("hedef_tip"),
                            komut=alt,
                            dogru=bool(res2.get("dogru")),
                            odul=int(res2.get("gain", 0)),
                            deneme=res2.get("deneme"),
                            alt3=act,
                        )
                        if res2.get("dogru"):
                            odul2 = int(res2.get("gain", 0))
                            if odul2:
                                gain += odul2
                                self.drives.consume(odul2, 0)
            zincir = res.get("hedef_tip") in ("SUREC_SAY", "DOSYA_SAY")
            if (
                act.startswith("cmd:")
                and not res.get("dogru")
                and not res.get("engel")
                and not (self.mind is not None and self.mind.son_kesif)
                and not zincir
            ):
                ders_mod.yaz(res.get("hedef_tip"), act, res.get("obs"))

        for cmd in res.get("unlock", []):
            self.jour.log("organ_unlock", organ=cmd)
        if res.get("kutu") and path:
            kcfg = self.cfg.get("kurallar") or self.cfg
            feats = damak_mod.ozellikler(path.split("/")[-1], kcfg, path=path)
            self.jour.log(
                "tahmin",
                dosya=path,
                tahmin=(round(pred, 1) if pred is not None else None),
                gercek=res["gain"],
            )
        # ---------- 7. Ödül hesaplama (merkezi) ----------
        # ---------- Yeni: Beden duyuları ödül bileşenleri (Aşama 2) ----------
        _disk_baski = max(0.0, (self.drives.disk_yuzde - 80.0) / 20.0)
        _bellek_baski = max(0.0, (self.drives.bellek_yuzde - 80.0) / 20.0)
        _beden_baski = max(_disk_baski, _bellek_baski)

        # Yeni keşif: res içindeki novel veya yeni cihaz/ağ sinyali
        _yeni_keşif = float(res.get("novel", 0.0))
        if res.get("kind") in ("usb_kernel", "ag_trafigi", "explore"):
            _yeni_keşif = max(_yeni_keşif, 0.5)

        # Beden sağlığı: enerji ve aclik denge (0..1)
        _e_cap = max(1.0, self.drives.energy_cap)
        _e_ratio = max(0.0, min(1.0, self.drives.energy / _e_cap))
        _h_ratio = max(0.0, min(1.0, self.drives.hunger / 100.0))
        _beden_saglik = (_e_ratio + (1.0 - _h_ratio)) / 2.0

        res["beden_baski"] = _beden_baski
        res["yeni_keşif"] = _yeni_keşif
        res["beden_saglik"] = _beden_saglik

        reward_parts = self.reward_h.hesapla(
            gain=gain,
            cost=cost,
            veto=veto,
            relief_done=relief_done,
            res=res,
            act=act,
            in_danger=self.drives.in_danger,
            was_danger=self.was_danger,
            pain=self.drives.pain(),
            pain_penalty=self.drives.pain_penalty,
            relief_bonus=self.drives.relief_bonus,
            komut=self.decision.komut_ust,
            sinyal=self._sinyal_ust,
            drives_state={
                "in_danger": self.drives.in_danger,
                "aclik_once": _aclik_once,
                "yemek_var": self._yemek_var_ust,
            },
            asm_son=self.decision.asm_son,
            dis_sal_geribildirim=self._dis_sal_geribildirim,
        )
        reward = reward_parts["alt_beyin"]
        upper_reward = reward_parts["ust_beyn"]

        # Çalışma belleğine gerçek ödülü yaz (daha önce working_remember
        # sadece strength ile kaydı yapmıştı; şimdi ödül bilgisi eklenir)
        if self.mind is not None:
            self.mind.working_remember(stim, act, reward=reward)

        # Gecikmeli kredi: yemek bulunca son eylemler de pay alır
        if gain > 0.2:
            for i, (prev_stim, prev_act) in enumerate(
                reversed(self.recent[-3:])
            ):
                if prev_act == act:
                    continue
                bonus = gain * (0.30, 0.20, 0.10)[i]
                if self.mind is not None:
                    self.mind.credit(prev_stim, prev_act, bonus)

        # Perde 1: acı & kurtuluş
        if self.drives.in_danger:
            if not self.was_danger:
                self.jour.log(
                    "pain_enter",
                    E=round(self.drives.energy, 1),
                    H=round(self.drives.hunger, 1),
                )
            self.was_danger = True
        elif self.was_danger:
            self.jour.log(
                "relief", act=act, E=round(self.drives.energy, 1)
            )
            self.was_danger = False

        # Sıkılma güncelleme
        self.drives.sikilan(
            res.get("novel", 0)
            + (1 if res.get("novel_cmd") else 0)
            + (1.0 if float(res.get("merak", 0.0)) > 0 else 0.0)
        )

        _, dusunme_tahmini = None, None
        dusunme_guveni = None
        if self.dusun is not None:
            _, dusunme_tahmini = self.dusun.tahmin(self._sinyal_ust, act)
            dusunme_guveni = self.dusun.guven(self._sinyal_ust, act)
        if dusunme_tahmini is not None:
            self.jour.log(
                "dusunme_olcum",
                action=act,
                tahmin=round(dusunme_tahmini, 4),
                gercek=round(reward, 4),
                mutlak_hata=round(abs(dusunme_tahmini - reward), 4),
                guven=round(dusunme_guveni if dusunme_guveni is not None else 0.0, 3),
            )

        # Alt-beyin öğrenme — hata sınıflandırması önce
        eylem_basarili = reward >= 0.0
        guven = self.mind.guven(stim, act) if self.mind is not None else 0.0
        baglam_uygun = not (
            self.drives.in_danger and act not in ("eat", "rest", "sense_self")
        )
        self._hata_son_n[act] = self._hata_son_n.get(act, 0) + (0 if eylem_basarili else 1)
        if len(self._hata_son_n) > 50:
            # eski anahtarları temizle
            eski = sorted(self._hata_son_n.items(), key=lambda kv: kv[1])[:10]
            for k, _v in eski:
                self._hata_son_n.pop(k, None)
        tekrarlayan = self._hata_son_n.get(act, 0) >= 3

        hata = hata_katalogu_mod.siniflandir(
            odul=reward,
            guven=guven,
            eylem_basarili=eylem_basarili,
            tekrarlayan_basarısız=tekrarlayan,
            baglam_uygun=baglam_uygun,
            eylem=act,
        )
        if hata is not None:
            self.jour.log(
                "hata",
                tur=hata,
                stim=stim,
                eylem=act,
                odul=round(reward, 4),
                guven=round(guven, 3),
                tik=tik,
            )
            self.meta.hata_kaydi(hata, reward, guven, tik)

        if self.mind is not None:
            self.mind.learn(
                stim, act, reward, r_merak=float(res.get("merak", 0.0))
            )
            self.dusun.observe(self._sinyal_ust, act, reward) if self.dusun is not None else None
        # (1) AraBeyn — Brain sağlık sinyali eğitimi: saglik_egitim'i doldur
        try:
            _durum = {"komut": act, "dogru": bool(reward >= 0.0),
                      "surpriz": float(res.get("merak", 0.0))}
            _puan = float(max(-50.0, min(150.0, reward * 10.0 + 75.0)))
            if reward >= 3.0:
                _sinif = "Mükemmel"
            elif reward >= 0.0:
                _sinif = "Normal"
            else:
                _sinif = "Ölüm Tehlikesi"
            if self.mind is not None:
                self.mind.ogren_saglik(_durum, _puan, _sinif)
        except Exception:
            pass

        # ---------- Faz 5: neden / kanıt kaydı ----------
        _tehlike_o, _tehlike_a = None, None
        if self.dusun is not None:
            _tehlike_o, _tehlike_a = self.dusun.tehlike_tahmini(
                self._sinyal_ust, act, self.drives
            )
        _neden_kayit = self.neden.uret(
            tik=tik,
            stim=stim,
            act=act,
            guven=guven,
            reward=reward,
            dusunme_tahmini=dusunme_tahmini,
            dusunme_guven=dusunme_guveni,
            tehlike_olasilik=_tehlike_o,
            tehlike_aciklama=_tehlike_a,
        )
        self.jour.log(**_neden_kayit)

        # Üst beyin öğrenmesi (yalnızca gerçek karar olduğunda)
        self._odul_ust = upper_reward
        if not self.decision.reddedildi_ust:
            self.ust.ogren(
                self._sinyal_ust,
                self.decision.idx_ust,
                self._odul_ust,
                keşif=(self.decision.kaynak_ust == "kesif"),
            )
            self.jour.log(
                "ust_ogren",
                sinyal=[float(x) for x in self._sinyal_ust],
                idx=self.decision.idx_ust,
                odul=upper_reward,
                sinyal_surumu=ust_beyn_mod.SINYAL_SURUMU,
            )

        # --- ag_beyin → ust_beyn: tarama sonucu ödülüyla üst beyni eğit ---
        if (
            self.decision.ag_tara_calisti
            and self.decision.ag_tara_sonuc is not None
        ):
            _scan = self.decision.ag_tara_sonuc
            _odul = float(_scan.get("probe_reward", 0.0))
            self.ust.scan_odulu_besle(_odul, tik)
            self.jour.log(
                "ag_tara_ogren",
                step=_scan.get("step"),
                probe=_scan.get("probe"),
                odul=_odul,
            )

        # Canlı durum: web paneli için enerji / açlık / ödül verisi
        self.jour.log(
            "act",
            t=tik,
            E=round(self.drives.energy, 1),
            H=round(self.drives.hunger, 1),
            R=round(reward_parts["toplam"], 1),
            R_alt=round(reward, 4),
            R_ust=round(upper_reward, 4),
            R_yenilik=reward_parts["yenilik"],
            R_dogrulanmis=reward_parts["dogrulanmis_komut"],
            R_dis=reward_parts.get("dis_sal_geribildirim", 0.0),
            action=act,
            hedef=res.get("hedef_tip"),
            dogru=(res.get("dogru")
                   if isinstance(res.get("dogru"), bool) else None),
            dogrulanmis=bool(res.get("dogrulanmis", False)),
            ilerleme=bool(res.get("ilerleme", False)),
            gorev_sonucu=res.get("gorev_sonucu"),
            deneme=res.get("deneme"),
        )

        self.recent.append((stim, act))
        if len(self.recent) > 4:
            self.recent.pop(0)

        # Periyodik işlemler
        if tik % 10 == 0:
            self._periyodik_10(stim, act, reward, res, feasible)

        if tik % 100 == 0:
            self._tutarlilik_sayaci += 1
            self._tutarlilik_denetle()

        if tik % 20 == 0:
            n_ders, n_red = ders_mod.oku(
                self.mind, self.jour, beyaz=kullan_mod.BEYAZ
            )
            if n_ders or n_red:
                self.jour.log("ders_ozet", islenen=n_ders, red=n_red)

        if tik % 50 == 0 and self.kul is not None and self.kul.ara.strip() and self.kul.hedef:
            if self.kul.hedef["tip"] in ("SUREC_SAY", "DOSYA_SAY"):
                deneme_snapshot = self.kul.hedef_deneme
                res_replay = self.kul.uygula("cmd:wc")
                self.kul.hedef_deneme = deneme_snapshot
                self.jour.log(
                    "kullan_replay",
                    hedef=self.kul.hedef["tip"],
                    komut="cmd:wc",
                    dogru=bool(res_replay.get("dogru")),
                    odul=int(res_replay.get("gain", 0)),
                    deneme=res_replay.get("deneme"),
                )
                if res_replay.get("dogru"):
                    odul_r = int(res_replay.get("gain", 0))
                    if odul_r:
                        gain += odul_r
                        self.drives.consume(odul_r, 0)

        if tik % 200 == 0:
            self.lifecycle.arsivle_gunlukler(tik, None)
            try:
                if self.mind is not None:
                    n_replay = self.mind.hatira(self.jour.path)
                    if n_replay:
                        self.jour.log("hatira_periodik", oynanan=n_replay)
            except Exception:
                pass

        if tik % 500 == 0:
            if self.mind is not None:
                budanan = self.mind.konsolide(koru_ust=300)
                if budanan:
                    self.mind.save(self.brain_path)
                    self.jour.log(
                        "konsolide_gunduz", silinen=budanan,
                        links=len(self.mind.w)
                    )
                # (6) Ağırlık dağılım analizi — periyodik beyin sağlık raporu
                try:
                    _dagilim = self.mind.bagirlik_dagilimi()
                    self.jour.log("brain_dagilim", **_dagilim)
                except Exception:
                    pass
            if self.kul is not None and self.kul.aktif:
                self.kul._komut_tehlike.save()
                self.jour.log(
                    "komut_tehlike_save",
                    samples=self.kul._komut_tehlike.samples,
                    help=len(self.kul._komut_tehlike.help_aciklamalar),
                )
            if self.guv:
                self.guv.save()

        if tik % 1000 == 0:
            _ret = self._arsiv_retansiyon(None)
            if _ret:
                self.jour.log("arsiv_retansiyon", hedef=None, silinen=_ret)

        # Üst beyin override süresini azalt
        self.decision.azalt_sure()

        # Gossip (P2P) - her N tikte bir
        if self.door.gossip_zaman_dusti(time.time()):
            try:
                _durum = {
                    "kimlik": self.cfg.get("identity", {}).get("name", "core"),
                    "enerji": round(self.drives.energy, 1),
                    "aciklik": round(self.drives.hunger, 1),
                    "homeostaz": round(self.drives.homeostaz_puani(), 2),
                    "mood": getattr(self.drives, "mood", {}),
                    "mood_dominant": getattr(self.drives, "mood_dominant", "-"),
                    "ticks": tik,
                    "brain_links": len(self.mind.w) if self.mind is not None else 0,
                    "ust_samples": self.ust.samples,
                    "port": self.door.port,
                }
                self.door.gossip_gonder(_durum)
            except Exception as _e:
                self.jour.log("gossip_hata", hata=str(_e)[:200])

        import queue
        # Door kuyruğunu boşalt
        try:
            while True:
                _dm = self.door.queue.get_nowait()
                if isinstance(_dm, dict) and _dm.get("type") == "gossip_ack":
                    self.jour.log("gossip_ack", **_dm)
                elif isinstance(_dm, dict):
                    self.jour.log("door_msg", **_dm)
                elif isinstance(_dm, str) and _dm.startswith("feedback:"):
                    # Faz 7: dışsal geri bildirim (iyi/kotu)
                    fb = _dm.split(":", 1)[1]
                    self._dis_sal_geribildirim = fb
                    self.jour.log(
                        "door_feedback_isle", deger=fb, tik=tik
                    )
        except queue.Empty:
            pass

        # Faz 4: su anki durumu bir sonraki tik icin kaydet
        self._onceki_stim = stim
        self._onceki_act = act
        self._onceki_sinyal_v = list(stim_ust)

        # Faz 7: dışsal geri bildirim bir kez uygulandıktan sonra sıfırla
        self._dis_sal_geribildirim = None

        time.sleep(self.tick_sleep)
        return self.drives.alive

    def _hesapla_feasible(self) -> List[str]:
        """Mevcut yapılabilir eylem listesini döndürür."""
        feasible = [
            "wander", "console", "sense_self", "nest", "rest",
            "katalogla", "konum", "nedir", "birak", "atolye",
            # Yeni: Bu bilgisayarın bedeni (Aşama 7) — organizmanın ev sahibi sistemini algıla
            "sense_kullanici", "sistem_umuru", "terminal_var",
            # Yeni: Bu bilgisayarın bedeni — fiziksel durum (Aşama 8)
            "sense_disk", "sense_bellek",
            # Yeni: USB — kernel seviyesinde (Aşama 10) — organizmanın USB
            # cihazlarını algilayip ogrenmesi icin (uzuv-usb / usb_beyn)
            "sense_usb_kernel", "sense_usb_nodes",
            # Yeni: Ağ trafiği gözlemi (Ağ-Beyn) — pasif /proc net gözlemi
            "sense_ag_trafigi",
        ]
        if self.drives.needs_food:
            feasible.append("eat")
        # cmd: ve help: eylemleri
        if self.kul is not None:
            feasible.extend(self.kul.eylemler())

        # --- Kara liste kesin engeli: zeka/komut_tehlike.json'daki
        # 'kara_liste' anahtarındaki eylemler feasible dışı bırakılır.
        # (tek kaynak: kara_liste.json ile komut_tehlike.json birleştirildi) ---
        kara_path = self.root / "zeka" / "komut_tehlike.json"
        if kara_path.exists():
            try:
                kara_veri = json.loads(kara_path.read_text(encoding="utf-8"))
                kara = kara_veri.get("kara_liste", [])
                if isinstance(kara, list):
                    feasible = [a for a in feasible if a not in kara]
            except (OSError, ValueError):
                pass

        # --- Yeni dizin zorlama: organizma henüz ziyaret etmediği
        # bir real_rooms dizinini feasible listeye ekle (keşif teşviki) ---
        # Beden baskısı yüksekse keşif kısıtlanır (disk/bellek %80 üzeri).
        _disk = float(getattr(self.drives, "disk_yuzde", 0) or 0)
        _bellek = float(getattr(self.drives, "bellek_yuzde", 0) or 0)
        _beden_baski = max(
            max(0.0, (_disk - 80.0) / 20.0),
            max(0.0, (_bellek - 80.0) / 20.0),
        )
        if _beden_baski < 0.3 and hasattr(self.bod, "real_rooms") and self.bod.real_rooms:
            for _ad, _yol in self.bod.real_rooms.items():
                if _ad not in self._ziyaret_edilen_dizinler:
                    feasible.append(f"explore:{_ad}")
                    break  # Her tikte sadece yeni bir dizin teşvik et

        # Beden baskısı yüksekse rest ağırlığını artır (daha çok dinlen).
        if _beden_baski >= 0.3:
            feasible.append("rest")
            feasible.append("rest")

        return feasible

    def _epsilon_tik(self) -> float:
        """Bu tik için keşif oranı (epsilon) döndürür."""
        return getattr(self.drives, "epsilon", 0.35) if hasattr(self.drives, "epsilon") else 0.35

    def _yerel_surecleri_izle(self, tik: int) -> None:
        """Sample local process behavior on the configured tick interval."""
        if not self.sur or tik % max(1, int(self.sur.periyot)) != 0:
            return
        sample = self.sur.ornekle(tik=tik)
        if not sample.get("ok"):
            self.jour.log(
                "surec_olcum_atlandi",
                neden=sample.get("neden", "bilinmeyen"),
            )
            return
        self.jour.log("surec_olcum", **sample)
        if self.sur.ornek % 5 == 0:
            self.sur.save()
            self.jour.log(
                "surec_save",
                ornek=self.sur.ornek,
                adet=len(self.sur.adet),
            )

    def _uzuv_riskini_guncelle(self, tik: int) -> None:
        """Read a fresh ASM risk signal; stale reports must not affect decisions."""
        periyot = max(1, int(getattr(self.sur, "periyot", 50)))
        if tik % periyot:
            return
        risk = False
        path = self.root / "zeka" / "uzuv_durum.json"
        if not path.exists():
            path = self.root / "uzuv_durum.json"
        try:
            durum = json.loads(path.read_text(encoding="utf-8"))
            risk = (
                time.time() - float(durum.get("t", 0)) <= 900
                and int(durum.get("tehlikeli", 0)) >= 1
            )
        except (OSError, ValueError, TypeError):
            pass
        if risk != self.uzuv_risk:
            self.uzuv_risk = risk
            self.jour.log("uzuv_risk", aktif=risk)

    def _ag_envanteri_guncelle(self) -> None:
        ag_beyin = getattr(self, "ag_beyin", None)
        if ag_beyin is None:
            return
        try:
            ogrenme = ag_beyin.learn_local_knowledge()
            if (
                ogrenme.get("changed")
                or ogrenme.get("warnings")
                or ogrenme.get("consolidated")
            ):
                self.jour.log(
                    "ag_yerel_bilgi_ogren",
                    arac=ogrenme.get("tools", []),
                    kaynak_dosya=ogrenme.get("references", []),
                    sosyal=ogrenme.get("social", {}),
                    konsolidasyon=ogrenme.get("consolidated", False),
                    uyari=ogrenme.get("warnings", []),
                )
            sonuc = ag_beyin.scan_if_due()
        except (OSError, RuntimeError, ValueError) as error:
            self.jour.log(
                "ag_envanter_hata",
                hata="%s: %s" % (type(error).__name__, str(error)[:200]),
            )
            return
        if sonuc is None:
            return
        if sonuc.get("skipped"):
            self.jour.log("ag_envanter_atlandi", neden=sonuc.get("reason"))
        elif sonuc.get("ok"):
            self.jour.log(
                "ag_envanter_tamamlandi",
                aglar=sonuc.get("networks", []),
                cihaz=sonuc.get("hosts", 0),
                port=sonuc.get("ports", 0),
                port_taranan=sonuc.get("port_scan_hosts", 0),
                mdns_servis=sonuc.get("mdns_services", 0),
                secilen_yoklama=sonuc.get("probe"),
                ogrenme_odulu=sonuc.get("probe_reward"),
                uyari=sonuc.get("warnings", []),
                sure=round(time.time() - float(sonuc.get("t", time.time())), 1),
            )
        else:
            self.jour.log(
                "ag_envanter_hata",
                aglar=sonuc.get("networks", []),
                hata=sonuc.get("reason", "bilinmeyen tarama hatasi"),
            )

    def _uykuyu_denetime_al(self, tik: int) -> None:
        """Run one due consolidation job while the organism has spare resources."""
        if self.uyku is None:
            return
        periyot = self.uyku.periyot_icin(self.drives)
        if (
            tik <= 0
            or tik - self._uyku_son_tik < periyot
            or self.drives.energy <= self.uyku.min_enerji
            or self.drives.hunger >= self.uyku.max_ac
        ):
            return
        self._uyku_son_tik = tik
        karar = self.uyku.karar()
        if not karar:
            return

        self.jour.log(
            "uyku_basla",
            ad=karar["ad"],
            veri=karar.get("veri", 0),
        )
        sonuc = self.uyku.uyu(
            karar,
            beyn=self.mind,
            usb_beyn=self.usb_beyn,
            ag_beyin=self.ag_beyin,
            nn_usb=self.nn_usb,
            nn_ag=self.nn_ag,
            nn_ana=self.nn_ana,
            asm_ogren=self.ust.asm_sistemi() if self.ust else None,
        )
        self.jour.log("uyku_bitti", **sonuc)
        if sonuc.get("kod") != 0:
            return

        # Çalışma belleğinden uzun belleğe konsolidasyon (uyku)
        try:
            konsolide_sayisi = self.mind.calisma_bellekten_konsolide(
                strength_esik=0.5, odul_esik=0.0, lr_carpan=0.5
            )
            if konsolide_sayisi:
                self.jour.log(
                    "calisma_bellek_konsolidasyon",
                    adet=konsolide_sayisi,
                )
        except Exception as _e:
            self.jour.log(
                "calisma_bellek_konsolidasyon_hata",
                hata=str(_e)[:200],
            )

        ad = sonuc.get("ad")
        try:
            if ad == "guvenlik" and self.guv.load():
                self.jour.log("guvenlik_reload", samples=self.guv.samples)
            elif ad == "paket" and self.paket_beyin.load():
                self.jour.log("paket_reload", ornek=self.paket_beyin.ornek)
            elif ad in ("dizin", "dizin_kaynak") and self.tez.reload_dizin():
                self.jour.log("dizin_reload", agirlik=self.tez.dizin_agirlik)

            model_path = self.root / "zeka" / "damak.json"
            if not model_path.exists():
                model_path = self.root / "damak.json"
            if model_path.exists():
                disk_mtime = model_path.stat().st_mtime
                if (
                    self.dam._disk_mtime is None
                    or abs(disk_mtime - self.dam._disk_mtime) > 1e-6
                ) and self.dam.load():
                    self.jour.log(
                        "damak_reload",
                        samples=self.dam.samples,
                        kova=len(self.dam.n),
                    )
        except Exception as error:
            self.jour.log(
                "uyku_yeniden_yukleme_hata",
                hat=ad,
                hata=f"{type(error).__name__}: {error}"[:200],
            )

    def _beden_duyularini_olcer(self, tik: int) -> None:
        """Periyodik olarak bu bilgisayarın fiziksel bedeni durumunu ölçer.

        Her 20 tikte bir disk, bellek, kullanıcı varlığı ve sistem yaşı
        bilgilerini günceller. Böylece organizma bu eylemleri kendisi
        seçmese de fiziksel durumu takip edebilir.
        """
        if tik % 20 != 0:
            return
        import re

        # --- Kullanıcı varlığı ---
        try:
            sonuc = self.bod.perform("sense_kullanici")
            _obs = str(sonuc.get("obs", ""))
            _insan = "kullanici_yok" not in _obs and "aktif:" in _obs
        except Exception:
            _insan = self.drives.insan_var

        # --- Sistem yaşı (uptime) ---
        try:
            sonuc = self.bod.perform("sistem_umuru")
            _obs = str(sonuc.get("obs", ""))
            _m = re.search(r"acik:(\d+)g(\d+)s(\d+)", _obs)
            if _m:
                _g, _s, _d = int(_m.group(1)), int(_m.group(2)), int(_m.group(3))
                _saat = _g * 24 + _s + _d / 60.0
            else:
                _saat = self.drives.sistem_saati
        except Exception:
            _saat = self.drives.sistem_saati

        # --- Disk doluluk ---
        try:
            sonuc = self.bod.perform("sense_disk")
            _obs = str(sonuc.get("obs", ""))
            _m = re.search(r"disk:([\d.]+)%", _obs)
            _disk = float(_m.group(1)) if _m else self.drives.disk_yuzde
        except Exception:
            _disk = self.drives.disk_yuzde

        # --- Bellek kullanımı ---
        try:
            sonuc = self.bod.perform("sense_bellek")
            _obs = str(sonuc.get("obs", ""))
            _total = None
            _avail = None
            for _line in _obs.split(";"):
                _line = _line.strip()
                if _line.startswith("MemTotal:"):
                    try:
                        _total = int(_line.split(":")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
                elif _line.startswith("MemAvailable:"):
                    try:
                        _avail = int(_line.split(":")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
            if _total and _avail is not None and _total > 0:
                _bellek = round((_total - _avail) / _total * 100, 1)
            else:
                _bellek = self.drives.bellek_yuzde
        except Exception:
            _bellek = self.drives.bellek_yuzde

        self.drives.beden_guncelle(
            _insan,
            _saat,
            _disk,
            _bellek,
            usb_cihaz=getattr(self.drives, "usb_cihaz_sayisi", 0),
            usb_node=getattr(self.drives, "usb_node_sayisi", 0),
        )

    def _asm_ogren_komutunu_calistir(self) -> Optional[Dict[str, Any]]:
        """Üst-beyin isteğiyle kısa, kaynak-korumalı ASM öğrenme oturumu çalıştırır."""
        if self.drives.energy <= 30.0 or self.drives.in_danger:
            self.jour.log("asm_ogren_atlandi", neden="kaynak_az")
            return None
        sonuc = self.ust.asm_öğren(
            dakika=2.0,
        )
        self.ust.save()
        self.jour.log("asm_ogren_dongu", **sonuc)
        return sonuc

    def _periyodik_10(
        self,
        stim: str,
        act: str,
        reward: float,
        res: Dict[str, Any],
        feasible: List[str],
    ) -> None:
        """Her 10 tikte bir öğrenme / beyin günlüğü."""
        self.jour.log(
            "learn",
            tick=self.state.get("ticks"),
            hedef=res.get("hedef_tip") or self.hedef_tip,
            dogru=(res.get("dogru")
                   if isinstance(res.get("dogru"), bool) else None),
            dogrulanmis=bool(res.get("dogrulanmis", False)),
            stim=stim,
            action=act,
            w=round(self.mind.score(stim, act), 2),
            R=round(reward, 4),
            R_merak=round(float(res.get("merak", 0.0)), 2),
            S=round(self.drives.sikilma, 2),
            # ---------- Yeni: Bu bilgisayarın bedeni (Aşama 8) ----------
            insan_var=bool(self.drives.insan_var),
            sistem_saati=self.drives.sistem_saati,
            disk_yuzde=self.drives.disk_yuzde,
            bellek_yuzde=self.drives.bellek_yuzde,
            # ---------- Yeni: USB — kernel seviyesinde (Aşama 10) ----------
            usb_cihaz_sayisi=self.drives.usb_cihaz_sayisi,
            usb_node_sayisi=self.drives.usb_node_sayisi,
            # ---------- Yeni: Ruh hali / mood vektörü (Aşama 9) ----------
            mood_mutluluk=getattr(self.drives, "mood", {}).get("mutluluk", 0),
            mood_korku=getattr(self.drives, "mood", {}).get("korku", 0),
            mood_guven=getattr(self.drives, "mood", {}).get("guven", 0),
            mood_merak=getattr(self.drives, "mood", {}).get("merak", 0),
            mood_sikilma=getattr(self.drives, "mood", {}).get("sikilma", 0),
            mood_dominant=getattr(self.drives, "mood_dominant", "-"),
            mood_beden_baski=getattr(self.drives, "mood", {}).get("beden_baski", 0),
        )
        self.mind.save(self.brain_path)
        self.jour.log("oz_hedef", **self.oz.durum())
        _oz_h = self.oz.mevcut_hedef()
        if _oz_h:
            self.jour.log("oz_hedef_hedef", **_oz_h)
        try:
            _tahmin, _skor = self.dusun.dusun_ve_sec(
                self._sinyal_ust, feasible
            )
            self.jour.log(
                "dusunme_plan",
                eylem=_tahmin,
                skor=round(_skor, 4) if _skor is not None else None,
                guven=(round(self.dusun.guven(self._sinyal_ust, _tahmin), 3)
                       if _tahmin is not None else 0.0),
                samples=self.dusun.samples,
            )
            self.dusun.save()
        except Exception as _e:
            self.jour.log("dusunme_hata", hata=str(_e))

    def _tutarlilik_denetle(self) -> None:
        """Tek kaynak-of-truth: journal, brain.json ve sistem durumu
        arasında tutarsızlık tespit edilir; bozuksa 'degraded' kaydedilir."""
        import json
        bozuk = []
        # 1. brain.json var ve geçerli JSON olmalı
        brain_path = Path(self.brain_path)
        if not brain_path.exists():
            bozuk.append("brain.json_yok")
        else:
            try:
                json.loads(brain_path.read_text(encoding="utf-8"))
            except ValueError:
                bozuk.append("brain.json_bozuk")
        # 2. journal.jsonl son satırı geçerli JSON olmalı
        jour_path = self.root / "journal.jsonl"
        if jour_path.exists():
            try:
                son = jour_path.read_text(encoding="utf-8").strip().splitlines()[-1]
                json.loads(son)
            except (IndexError, ValueError):
                bozuk.append("journal_bozuk")
        # 3. Enerji sıfırsa ama beyin dosyası varsa çelişki
        if self.drives.energy <= 0 and brain_path.exists():
            bozuk.append("enerji_sifir_beyin_var")
        if bozuk:
            self.jour.log("tutarlilik_bozuk", nedenler=bozuk,
                          ticks=self.state.get("ticks"),
                          durum="degraded")

    def _arsiv_retansiyon(self, hedef: Optional[str]) -> int:
        """Arşiv retansiyonu; yaşam döngüsü main modülüne bağlı olmamalı."""
        if not hedef:
            return 0
        try:
            return journal_mod.arsiv_temizle(
                str(Path(hedef).parent),
                max_gun=30,
                toplam_mb=2048,
                korunacak=50,
            )
        except OSError as exc:
            self.jour.log(
                "arsiv_retansiyon_hata", hedef=hedef, hata=str(exc)
            )
            return 0

    # ------------------------------------------------------------------ yardimcilar


    def _kesif_araligi(self) -> int:
        """Güvenli durumda yerel keşfi 40, diğer durumlarda 100 tikte yap."""
        hedef = getattr(self, "hedef_tip", None) or ""
        if hedef.startswith("AG_") or hedef == "BENI_TARA":
            return 100
        return 40 if self.drives.safe_to_explore else 100

    def _beslenmeyi_sinirla(self, stim, feasible, act):
        """Özhedef veya üst-beyin eylemleri eklese de gereksiz yemeyi engelle."""
        if self.drives.needs_food:
            return feasible, act
        feasible = [action for action in feasible if action != "eat"]
        if act == "eat":
            act = self.mind.decide(stim, feasible) if feasible else "rest"
        return feasible, act




    # ------------------------------------------------------------------ yardimcilar

    def _topla_sinyal_ust(self) -> List[float]:
        """Üst beyin (MLP) için SINYAL_BOYUT'luk numeric vektör döndürür."""
        import ust_beyn as ust_beyn_mod
        import queue
        door_msgs = []
        try:
            while True:
                _dm = self.door.msgs.get_nowait()
                door_msgs.append(_dm)
        except queue.Empty:
            pass
        except Exception:
            pass

        feats_damak = None
        try:
            import damak as damak_mod
            kcfg = self.cfg.get("kurallar") or self.cfg
            feats_damak = damak_mod.ozellikler("dummy", kcfg, path="dummy")
        except Exception:
            pass

        # ---------- Yeni: Beden duyuları (Aşama 1) ----------
        _cpu = self.bod.sense_cpu() if self.bod else {"cpu_yuk": 0.0}
        _proses = self.bod.sense_proses() if self.bod else {"proses_norm": 0.0}
        _disk_baski = max(0.0, (self.drives.disk_yuzde - 80.0) / 20.0)
        _bellek_baski = max(0.0, (self.drives.bellek_yuzde - 80.0) / 20.0)
        _beden_baski = max(_disk_baski, _bellek_baski)

        return ust_beyn_mod.topla_sinyalleri(
            drives=self.drives,
            mind=self.mind,
            dam=self.dam,
            guv=self.guv,
            surec=self.sur,
            door_msgs=door_msgs,
            olum=self.olum_beyin,
            context="act",
            feats_damak=feats_damak,
            E=self.drives.energy,
            H=self.drives.hunger,
            sarsinti=0.0,
            yemek_var=self._yemek_var_ust,
            gorev_aktif=bool(self.hedef_tip),
            surpriz=getattr(self.atolye, "model", {}).get("surpriz", 0.0),
            dunya_bozuk=False,
            olum_feats=None,
            cpu_yuk=_cpu.get("cpu_yuk", 0.0),
            proses_norm=_proses.get("proses_norm", 0.0),
            disk_yuzde_norm=self.drives.disk_yuzde / 100.0,
            bellek_yuzde_norm=self.drives.bellek_yuzde / 100.0,
            usb_cihaz_norm=min(1.0, self.drives.usb_cihaz_sayisi / 50.0),
            usb_keşif_bonusu=self.drives.usb_keşif_bonusu,
            ag_baglanti_norm=0.0,
            insan_var=self.drives.insan_var,
            sistem_saati_norm=min(1.0, self.drives.sistem_saati / 86400.0),
            disk_baski=_disk_baski,
            bellek_baski=_bellek_baski,
            beden_baski=_beden_baski,
        )

    def _topla_sinyal(self) -> str:
        """Pipe-ayrılmış sinyal stringi döndürür (brain.stimulus() ile uyumlu)."""
        world = self.home_world.observe()
        signature = tuple(world["tokens"])
        if signature != self._home_world_signature:
            self._home_world_signature = signature
            self.jour.log(
                "home_world",
                tokens=list(signature),
                local=world["local"],
                internet=world["internet"],
                internet_enabled=world["internet_enabled"],
            )
        eb, hb = self.drives.bins()
        e_ince = "e:%d" % min(15, max(0, int(self.drives.energy // 10)))
        h_ince = "h:%d" % min(10, max(0, int(self.drives.hunger // 10)))
        parcalar = [
            eb, hb, e_ince, h_ince,
            self.bod.location[:6] or "kok",
            self.bod.last_food_loc[:6] or "-",
            "act:" + self.state.get("last", "-")[:10],
        ]
        parcalar.extend(world["tokens"])
        if self.hedef_tip:
            parcalar.append("gorev:" + self.hedef_tip)
            tip = self.hedef_tip.split(":", 1)[1] if ":" in self.hedef_tip else self.hedef_tip
            aile_map = getattr(self.mind, "AILE", None)
            aile = aile_map.get(tip) if isinstance(aile_map, dict) else None
            if aile:
                parcalar.append("gorev_aile:" + aile)
        sur_eksik = getattr(self.sur, "eksik", False)
        sur_yeni = getattr(self.sur, "yeni", False)
        if getattr(self, "uzuv_risk", False):
            parcalar.append("sistem:RISK")
        elif sur_eksik:
            parcalar.append("sistem:EKSIK")
        elif sur_yeni:
            parcalar.append("sistem:YENI")
        son_cmd = self.state.get("last", "-")
        if son_cmd and son_cmd != "-":
            parcalar.append("son:" + son_cmd)
        ag_beyin = getattr(self, "ag_beyin", None)
        if ag_beyin is not None:
            parcalar.extend(ag_beyin.stimulus_tokens())
        deneme = getattr(self.kul, "hedef_deneme", 0) + 1 if self.hedef_tip else None
        if deneme:
            n = min(int(deneme), 3)
            parcalar.append("deneme:%d+" % n if n >= 3 else "deneme:%d" % n)
        ara = bool(getattr(self.kul, "ara", None)) if self.hedef_tip else None
        if ara is not None:
            parcalar.append("ara:var" if ara else "ara:yok")
        _sk = getattr(self.drives, "sikilma", 0.0)
        if _sk >= 0.66:
            parcalar.append("sikilma:2")
        elif _sk >= 0.33:
            parcalar.append("sikilma:1")
        _sn = getattr(self.atolye, "model", {}).get("surpriz", 0.0)
        if _sn >= 1.0:
            parcalar.append("surpriz:%d|surpriz:var" % (0 if _sn < 0.3 else 1 if _sn < 1.0 else 2 if _sn < 3.0 else 3))
        elif _sn > 0:
            parcalar.append("surpriz:%d" % (0 if _sn < 0.3 else 1 if _sn < 1.0 else 2 if _sn < 3.0 else 3))
        return "|".join(parcalar)


