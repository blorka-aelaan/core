"""CORE main — kalp atışı.

Algıla → karar ver → hareket et → enerjiye bak → öğren.
Tek süreç, tek döngü, tek "ben".

  python3 main.py                 # sonsuza kadar yaşar (Ctrl+C ile uyur)
  python3 main.py --ticks 20      # 20 tik yaşayıp durur
  python3 main.py --quiet         # günlüğe yazar, konsola az baskı yapar
"""
import argparse
import json
import os
import queue
import random
import time
from pathlib import Path

import body as body_mod
import brain as brain_mod
import atolye as atolye_mod
import damak as damak_mod
import door as door_mod
import drives as drives_mod
import gorev as gorev_mod
import guvenlik as guvenlik_mod
import journal as journal_mod
import kutu_uretici as kutu_mod
import kullan as kullan_mod
import ders as ders_mod
import surec as surec_mod
import uyku as uyku_mod
import zeka
import ust_beyn as ust_beyn_mod

ROOT = Path(__file__).resolve().parent


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    # laboratuvar kuralları (varsa) — kutu & komut maliyetleri
    kurallar_path = ROOT / "kurallar.json"
    if kurallar_path.exists():
        with open(kurallar_path, encoding="utf-8") as f:
            kr = json.load(f)
        cfg["kutu_dir"] = kr.get("kutu", {}).get("dir")
        cfg["kutu_sonek"] = kr.get("kutu", {}).get("sonek", "")
        cfg["console_costs"] = kr.get("console_costs", {})
        cfg["kurallar"] = kr  # tam kural seti (damak özellik çıkarımı için)
    return cfg


def uzuv_riskli(yol=None, simdi=None):
    """FAZ 2 gözlemi: taze uzuv_durum.json 'tehlikeli' ≥ 1 ise True.

    ag 3 dakikada bir yazar; 15 dakikadan bayat dosya sayılmaz —
    ag durursa eski risk tokenı beyini yanlış bağlama sokmasın.
    Hiç dosya yoksa False (Faz 2 henüz eğitilmedi → yaşam sürer).
    """
    yol = zeka.yol("uzuv_durum.json") if yol is None else Path(yol)
    try:
        d = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    simdi = time.time() if simdi is None else simdi
    if simdi - float(d.get("t", 0)) > 900:
        return False
    return int(d.get("tehlikeli", 0)) >= 1


def main():
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
                    help="atölye keşif kolu (prod: sayim; "
                         "surpriz = ölçüm kolu — sürpriz iç seçimi "
                         "değiştirir mi A/B'si, opt-in)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    # göç: eski konumdaki (kök) zeka dosyaları varsa zeka/'ya taşı —
    # aksi halde taşınmadan önce doğan canlıların yazdıkları kaybolur
    import zeka
    tasinan = zeka.goc()
    jour = journal_mod.Journal(ROOT / cfg["stage"]["journal"],
                               quiet=args.quiet)
    if tasinan:
        jour.log("zeka_goc", tasinan=tasinan)
    drives = drives_mod.Drives(cfg)
    mind = brain_mod.Brain(seed=args.seed)
    brain_path = ROOT / cfg["stage"].get("brain", "brain.json")
    brain_path.parent.mkdir(parents=True, exist_ok=True)
    recalled = mind.load(brain_path)
    if recalled:
        jour.log("brain_recall", links=recalled)
    bod = body_mod.Body(cfg, ROOT, jour)
    # atölye (Sahne 0 substrate): organizmanın yazılabilir kum havuzu.
    # Dünyası gerçekten evrilir (kota + bozulma); sahne 1/2 bunun üstüne.
    atolye = atolye_mod.Atolye(bod.world, jour,
                               politika=args.atolye_politika)
    jour.log("atolye_load", nesne=len(atolye.nesneler))
    # kazanılan yetenekler beyinle gelir-gider (sort vb. ölmeyen kaslar)
    bod.allowed |= set(getattr(mind, "allowed_extra", set()))
    mind.allowed_extra = bod.allowed
    # görev/tezgâh: Debian klasör envanteri (gorev.json) — "iş ver, yapmazsan ceza al"
    gorev_cfg = {}
    gorev_yolu = Path(args.gorev) if args.gorev else (ROOT / "gorev.json")
    if gorev_yolu.exists():
        with open(gorev_yolu, encoding="utf-8") as f:
            gorev_cfg = json.load(f)
    tez = gorev_mod.Tezgah(gorev_cfg, bod, jour)
    # kullan: "hangi komutu ne zaman kullanırım?" öğretmeni.
    # Hedefi dosya sistemi ve dpkg kurar, çıktıyı o yargılar (nesnel ödül).
    kul = kullan_mod.Kullan(cfg, ROOT)
    if kul.aktif:
        kul.don()
        jour.log("kullan_hedef",
                 tip=(kul.hedef or {}).get("tip"))
    # damak: eğitilmiş isim-ödül damağı (egit.py üretir, yaşamda ince ayar)
    dam = damak_mod.Damak()
    damak_ok = dam.load()
    if damak_ok:
        dam.lr = float(cfg.get("kurallar", {})
                       .get("damak_canli_lr", 0.02))
        jour.log("damak_load", samples=dam.samples, kova=len(dam.n))
    # güvenlik beyini: zararlı komut kararları öğrenilmiş modelden gelir
    guv = guvenlik_mod.Guvenlik()
    guv_ok = guv.load()
    if guv_ok:
        jour.log("guvenlik_load", samples=guv.samples, kova=len(guv.n))
    else:
        jour.log("guvenlik_yok", not_="egit_guvenlik.py ile eğit")

    # paket beyini: "bu dosya ne, ne işe yarar?" (dpkg'den kendini eğitti)
    import paket as paket_mod
    paket_beyin = paket_mod.Paket()
    paket_ok = paket_beyin.load()
    if paket_ok:
        jour.log("paket_load", ornek=paket_beyin.ornek,
                 bilgi=len(paket_beyin.bilgi))
    else:
        jour.log("paket_yok", not_="egit_paket.py ile eğit")

    # ölüm beyini (Z3): acıda ön-belirti günlüğü + ölümde kategori kaydı.
    # Hiç ölüm olmadı — model etiketleri sentetik (20 maddelik kullanıcı
    # kataloğu). Bu yüzden DAVRANIŞI DEĞİŞTİRMEZ (ölüm yokken strateji
    # dayatmak sahte otorite olur); gözler, ölçer, kalibre verisi biriktirir.
    # Gerçek ölümler + tahminler birikince kalibrasyon ölçülür.
    import olum as olum_mod
    olum_beyin = olum_mod.Olum()
    olum_ok = olum_beyin.load()
    if olum_ok:
        jour.log("olum_load", ornek=olum_beyin.ornek)
    else:
        jour.log("olum_yok", not_="egit_olum.py ile eğit")

    # bağışıklık: habitat (çalışan süreçler) tanınması — kendi normalini
    # öğrenir; "kendim" kaybolursa eksik, hiç görülmemiş varsa yeni der
    sur = surec_mod.Surec(cfg)
    sur_ok = sur.load()
    jour.log("surec_load", ornek=sur.ornek, adet=len(sur.adet),
             yuklendi=sur_ok)

    # uyku (konsolidasyon): yaşarken biriken deneyim modellere akar —
    # organizma kendi kendine eğitilir, evrim döngüsü kapanır
    uyku = uyku_mod.Uyku(cfg)
    jour.log("uyku_load", son=list(uyku.son.keys()))

    # Üst (genel) beyin: tüm alt beyinleri gözetir, acil durumlarda override
    ust = ust_beyn_mod.UstBeyn(cfg, root=ROOT, seed=args.seed)
    jour.log("ust_beyn_load", samples=ust.samples)

    msgs = queue.Queue()
    state = {"ticks": 0, "last": "-"}
    bekleyen_sok = 0.0   # ertelenmiş zarar (yara): güvenli olana kadar uygulanmaz
    uyku_son_tik = 0     # son uyku kontrolünün/tetiklenmesinin tiki (dinamik periyot)
    bekleyen_tip = "aninda"   # zararın kaynağı: aninda | gorev (görev cezası)

    def status():
        s = drives.state()
        s.update(name=cfg["identity"]["name"], last=state["last"],
                 ticks=state["ticks"], bekleyen=round(bekleyen_sok, 1))
        return s

    door = door_mod.Door(cfg["door"]["host"], cfg["door"]["port"],
                         status, msgs, jour)
    door.start()
    jour.log("birth", **status())

    tick_sleep = cfg["metabolism"]["tick_seconds"]
    max_acts = cfg["quota"]["max_actions_per_tick"]
    # günlük bu boyutu aşarsa otomatik arşivlenir (canlı güvenli: arsivle)
    journal_azami_mb = float(cfg["stage"].get("journal_azami_mb", 20))
    # gölge kapı günlüğü: aynı mantık — 60MB'a dayanmıştı, dönüş yoktu
    # (2026-10-18 denetimi). GOLGE_LOG env'i kullan.py ile ortak.
    golge_azami_mb = float(cfg["stage"].get("golge_azami_mb", 20))
    golge_yolu = os.environ.get("GOLGE_LOG") or str(ROOT / "golge_log.jsonl")
    context = "start"
    last_kind = "start"
    son_cmd = None  # son komut denemesinin sonucu (ok/hata) —
                    # çalışma belleği tokenı (Aşama 3)
    son_gozlem = ""  # son gözlem metni (atölye nesnesine 'yazılır')
    was_danger = False  # Perde 1: acı bölgesi hafızası
    recent = []          # son eylemler (gecikmeli kredi için)
    son_hedef_tip = None  # Aşama 3: hedef tipi değişince recent sıfırlanır
    gorev = None         # misyon: aranacak klasör (kanonik yol öneki)
    ac_bekle = False     # "kutu aç" isteği
    uzuv_risk = False    # Faz 2 gözlemi → sistem:RISK (periyodik tazelenir)

    try:
        while drives.alive and (args.ticks == 0
                                or state["ticks"] < args.ticks):
            state["ticks"] += 1
            drives.tick()
            mind.working_sindir()   # çalışma belleği sönümü (Aşama 3)
            bod.tick(drives.energy)
            atolye.tikla(state["ticks"])   # dünyanın evrimi: bozulma + model
            # sığınak: yuva varsa metabolizma ucuzalaşır
            wcfg = cfg.get("world", {})
            drives.decay_factor = (float(wcfg.get("shelter_factor", 1.0))
                                   if bod.has_nest() else 1.0)
            # bağışıklık: periyodik habitat taraması; anomali günlüğe,
            # eksik varsa ortam toksik → metabolizma hızlanır (yaşam kayn.)
            if state["ticks"] % sur.periyot == 0:
                kesif = sur.ornekle()
                if kesif["eksik"] or kesif["yeni"]:
                    jour.log("surec", eksik=kesif["eksik"][:10],
                             yeni=kesif["yeni"][:10],
                             toplam=kesif["toplam"])
                if state["ticks"] % (sur.periyot * 10) == 0:
                    sur.save()
                # Faz 2: uzuv durumunu taze oku → sistem:RISK tokenı
                # (ag yazar, biz yalnız okuruz — gözlem, karar değil)
                yeni_risk = uzuv_riskli()
                if yeni_risk != uzuv_risk:
                    jour.log("uzuv_risk", aktif=yeni_risk)
                uzuv_risk = yeni_risk
            if sur.eksik:
                drives.decay_factor *= sur.dusman
            # uyku: tok & dinçken ve periyot dolunca — en bayat/acil model
            # tazelenir (tek uyku = tek eğitim; tikler eğitim boyunca durur)
            if (state["ticks"] > 0
                    and state["ticks"] - uyku_son_tik >= uyku.periyot_icin(drives)
                    and drives.energy > uyku.min_enerji
                    and drives.hunger < uyku.max_ac):
                uyku_son_tik = state["ticks"]
                karar = uyku.karar()
                if karar:
                    jour.log("uyku_basla", ad=karar["ad"],
                             veri=karar.get("veri", 0))
                    sonuc = uyku.uyu(karar, beyn=mind)
                    jour.log("uyku_bitti", **sonuc)
                    # Z1 — UYKU SONRASI YENIDEN YUKLEME: offline egitim
                    # diske yazar; canli bellek baslangicta yuklenmisti
                    # (bayat-agirlik tuzagi). DAMAK mtime deseni ornek;
                    # guvenlik/paket/dizin egitim-sonrasi tazelenir.
                    # load() yeniden girislidir: okuma basarisizsa eski
                    # model aynen kalir, is kesilmez.
                    try:
                        _uad = sonuc.get("ad")
                        if sonuc.get("kod") == 0:
                            if _uad == "guvenlik" and guv.load():
                                jour.log("guvenlik_reload",
                                         samples=guv.samples)
                            elif _uad == "paket" and paket_beyin.load():
                                jour.log("paket_reload",
                                         ornek=paket_beyin.ornek)
                            elif _uad in ("dizin", "dizin_kaynak") \
                                    and tez.reload_dizin():
                                jour.log("dizin_reload",
                                         agirlik=tez.dizin_agirlik)
                    except Exception:
                        pass   # tazeleme yoksa bayat agirlikla devam
                    # DAMAK DIS EGITIM KORUMASI: egit.py canliyken
                    # damak.json'i yenilediyse (mtime oynadi) modeli
                    # yeniden yukle — yoksa save() bir daha asla True
                    # doner ( _disk_mtime guncellenmez) ve canli ince
                    # ayar bellekte kalip kaybolur. load _disk_mtime'i
                    # de tazeler -> sonraki kayitlar calisir.
                    try:
                        _mt = float(zeka.yol("damak.json").stat().st_mtime)
                        if dam._disk_mtime is None or \
                                abs(_mt - dam._disk_mtime) > 1e-6:
                            if dam.load():
                                jour.log("damak_reload", samples=dam.samples,
                                         kova=len(dam.n))
                    except OSError:
                        pass

            # kapıdan gelen: uyaran + sosyal kıvılcım / ŞOK (lab aleti)
            ping = False
            while not msgs.empty():
                m = msgs.get()
                if m.startswith("shock:"):
                    try:
                        miktar = float(m.split(":", 1)[1])
                    except ValueError:
                        miktar = 50.0
                    # ANINDA UYGULANMAZ: kuyuya alınır (ertelenmiş yara).
                    # if refleksi: enerji − şok güvenli tamponun üstündeyse
                    # bir sonraki tikte uygulanır; yoksa organizma doyup
                    # tamponu doldurana kadar bekler.
                    bekleyen_sok = max(bekleyen_sok, miktar)
                    bekleyen_tip = "aninda"
                    jour.log("sok_beklede", miktar=miktar,
                             bekleyen=round(bekleyen_sok, 1),
                             E=round(drives.energy, 1))
                elif m.startswith("gorev:"):
                    gorev = m.split(":", 1)[1].strip().rstrip("/")
                    yol = bod.gorev_ayarla(gorev)
                    jour.log("gorev", klasor=gorev, cozulen=yol)
                elif m == "ac":
                    ac_bekle = True
                    jour.log("ac_istek", gorev=gorev)
                else:
                    jour.log("door_inbox", msg=m)
                    drives.spark(2)
                ping = True

            # --- GÜVENLİK BEYNİ KARARI (kod değil, öğrenilmiş model) ---
            # görev süresi dolduysa ceza şoku doğar (tip: gorev); şok
            # kuyuya gider, uygulanıp uygulanmayacağına BEYİN karar verir
            if (tez.aktif(state["ticks"])
                    and tez.sure_kontrol(state["ticks"])):
                ceza = float(gorev_cfg.get("ceza", 0))
                bekleyen_sok = max(bekleyen_sok, ceza)
                bekleyen_tip = "gorev"
                jour.log("gorev_kacirildi", ceza=ceza,
                         **(tez.son_ilerleme or tez.ilerleme(
                             state["ticks"])))
            if bekleyen_sok > 0:
                yemek_var = bool(bod.find_food())
                if guv_ok:
                    karar, puan = guv.karar_ver(
                        drives.energy, drives.hunger,
                        bekleyen_sok, yemek_var)
                else:
                    karar, puan = "bekle", 0.0   # model yoksa risk alma
                jour.log("sok_karar", karar=karar, puan=round(puan, 2),
                         E=round(drives.energy, 1),
                         sarsinti=bekleyen_sok, tip=bekleyen_tip,
                         yemek=yemek_var)
                guvenlik_mod.veri_yaz(
                    {"t": round(time.time(), 3),
                     "E": round(drives.energy, 1),
                     "H": round(drives.hunger, 1),
                     "sarsinti": bekleyen_sok, "yemek": yemek_var,
                     "tip": bekleyen_tip, "karar": karar,
                     "surum": guvenlik_mod.SURUM,
                     "puan": round(puan, 2)})
                if karar == "uygula":
                    drives.spend(bekleyen_sok)
                    jour.log("sok_uygulandi", miktar=bekleyen_sok,
                             tip=bekleyen_tip,
                             E=round(drives.energy, 1))
                    bekleyen_sok = 0.0
                    bekleyen_tip = "aninda"

            context = "door" if ping else last_kind

            for _ in range(max_acts):
                if not drives.alive:
                    break
                # --- KUTU AÇMA (sınav): misyon kapsamında tek açım ---
                if ac_bekle:
                    ac_bekle = False
                    kcfg = cfg.get("kurallar") or cfg
                    adaylar = [p for p in bod.food_cache
                               if bod.kutu_yolu(p)
                               and bod._kutu_resolve(p) is not None
                               and bod._kutu_resolve(p).exists()]
                    if gorev:
                        kapsam = [p for p in adaylar
                                  if p.startswith(gorev)]
                        if kapsam:
                            adaylar = kapsam
                    if not adaylar:
                        # arama yetersiz kaldıysa: misyon kapsamının
                        # tamamına düş (sınav her hâlükârda yapılabilsin)
                        zorunlu = [p for p in bod.kutu_listesi()
                                   if (not gorev or p.startswith(gorev))]
                        if zorunlu:
                            adaylar = zorunlu
                            jour.log("ac_tarama_yetersiz",
                                     aday=len(adaylar))
                        else:
                            jour.log("ac_bos", gorev=gorev)
                            continue
                    preds = {p: dam.tahmin(damak_mod.ozellikler(
                        p.split("/")[-1], kcfg, path=p))
                        for p in adaylar}
                    path = max(preds, key=preds.get)
                    # laboratuvar ölçümü — organizma gerçeği GÖRMEZ:
                    kapsam_tum = [p for p in bod.kutu_listesi()
                                  if (not gorev or p.startswith(gorev))]
                    gercekler = {p: kutu_mod.kutu_tam_deger(p, kcfg)
                                 for p in kapsam_tum}
                    en_iyi = (max(gercekler, key=gercekler.get)
                              if gercekler else None)
                    sirali = sorted(preds.values(), reverse=True)
                    guven = (round(sirali[0] - sirali[1], 1)
                             if len(sirali) > 1 else None)
                    res = bod.perform("eat", path=path)
                    cost = bod.last_cost
                    drives.spend(cost)
                    if not res.get("kutu"):
                        # kutu tutmadı (bayat yol vb.) — sınav sayılmaz
                        jour.log("ac_ıska", dosya=path)
                        continue
                    if res.get("gain"):
                        drives.consume(res.get("gain", 0),
                                       res.get("relief", 0))
                    feats = damak_mod.ozellikler(
                        path.split("/")[-1], kcfg, path=path)
                    jour.log("acildi", dosya=path,
                             tahmin=round(preds[path], 1),
                             gercek=kutu_mod.kutu_tam_deger(path, kcfg),
                             en_gercek=(gercekler.get(en_iyi)
                                        if en_iyi else None),
                             en_iyi=en_iyi,
                             derinlik=kutu_mod.derinlik_bul(path, kcfg),
                             guven=guven, aday=len(adaylar))
                    # Dünyanın değerini öğren (enerji cap'i bağımsız):
                    # damak kutunun KIYMETİNİ bilir, anlık doygunluğu değil
                    dam.ogren(feats, kutu_mod.kutu_tam_deger(path, kcfg))
                    context = "ac"
                    continue
                if kul.aktif and not kul.hedef:
                    kul.don()
                # gorev tokenı: beyne "şu an hangi iş bekliyor" bilgisini
                # taşır → (gorev:DOSYA_BUL, cmd:find) bağlantısı öğrenilir
                hedef_tip = ((kul.hedef or {}).get("tip")
                             if kul.aktif else None)
                # Aşama 3 — recent sıfırlama: hedef tipi değiştiğinde
                # gecikmeli kredi penceresi temizlenir; bir görevin
                # "gizli'ye döndüm/doydum" bonusu sonraki göreve sızmasın
                # (zincirde yanlış komutu öğrenilen gerçek tuzak buydu).
                if hedef_tip != son_hedef_tip:
                    recent.clear()
                    son_hedef_tip = hedef_tip
                # atölye uyaranı (Sahne 0/1): dünya sağlığı + taze sürpriz
                # beyne token olarak taşınır (sistem:RISK deseni)
                d = atolye.durum_vek()
                dunya_tok = ("dunya:BOZUK" if d["bozuk"]
                             else "dunya:DOLU" if d["adet"] >= atolye.KOTA
                             else "dunya:BOS" if d["adet"] == 0
                             else "dunya:IYI")
                # S4: sürpriz kovalı (0<0.3 / 1<1 / 2<3 / 3>=3) — beyin
                # "az sürpriz" ile "çok sürpriz"i ayrı öğrenir; eski
                # "surpriz:var" bağı da sıcak tutulur (>=1'de eklenir)
                _sn = atolye.model["surpriz"]
                surpriz_tok = "surpriz:%d" % (0 if _sn < 0.3 else
                                              1 if _sn < 1.0 else
                                              2 if _sn < 3.0 else 3)
                if _sn >= 1.0:
                    surpriz_tok += "|surpriz:var"
                stim = mind.stimulus(drives, context, bod.location,
                                     bod.last_food_loc,
                                     gorev=("gorev:" + hedef_tip)
                                     if hedef_tip else None,
                                     sistem=("sistem:RISK" if uzuv_risk
                                             else "sistem:EKSIK"
                                             if sur.eksik
                                             else "sistem:YENI"
                                             if sur.yeni else None),
                                     son=son_cmd,
                                     # sıradaki deneme (1|2|3+): hedef
                                     # yenilenene kadar beyin şunu görür
                                     deneme=(kul.hedef_deneme + 1
                                             if hedef_tip else None),
                                     # ara bellek durumu (Aşama 2):
                                     # dosyasız wc/head bu tamponu okur
                                     ara=(bool(kul.ara)
                                          if hedef_tip else None),
                                     dunya=dunya_tok,
                                     surpriz=surpriz_tok)
                feasible = bod.feasible(brain_mod.ACTIONS)
                # tokken yemez (israf); ama ACI varsa yaşam doygunluğa
                # galip gelir — ölümün eşiğinde her lokma mukaddesdir
                if drives.hunger <= 15 and not drives.in_danger:
                    feasible = [a for a in feasible if a != "eat"]
                if not bod.nest_ready():
                    feasible = [a for a in feasible if a != "nest"]
                if drives.in_danger:
                    # acıda arama yok: hayatta kalma > merak
                    # (atölye de bir tür meraktır — acıda ertelenir)
                    feasible = [a for a in feasible
                                if a not in ("console", "atolye")]
                if tez.aktif(state["ticks"]) and not tez.bitti_mi():
                    feasible = feasible + ["katalogla"]
                if tez.konum_aktif():
                    feasible = feasible + ["konum"]
                if paket_ok:
                    feasible = feasible + ["nedir"]
                feasible = feasible + kul.eylemler()
                # sıkılma (Aşama 4): iç dürtü uygara taşınır (uyaran
                # tokenı + decide'de keşif baskısı)
                mind.sikilma = drives.sikilma
                # Yeni: dinamik lr/epsilon (enerji / acı / sıkılma duyarlı)
                mind.update_dynamic_params(drives)
                # inkâr hakkı (Aşama 4): aktif hedef varsa bedelsiz
                # "bırak" — hayır diyemeyen varlık serbest değildir
                if kul.hedef:
                    feasible = feasible + ["birak"]
                # atölye (Sahne 0): yazılabilir dünya — her zaman mevcut
                feasible = feasible + ["atolye"]

                # --- ÜST BEYİN (Genel Beyin) override kontrolü ---
                # Tüm alt beyinlerden sinyalleri topla, MLP ile komut seç.
                _yemek_var_ust = bool(bod.find_food())
                _surpriz_ust = float(_sn) if "_sn" in locals() else 0.0
                _dunya_bozuk_ust = bool(d.get("bozuk")) if isinstance(
                    d, dict) else False
                # Kriz belirtisi: ölüm risk sinyali YALNIZCA gerçek bir
                # sağlık krizi varken üretilir (tehlike, enerji çöküşü
                # veya açlık krizi). Normal durumda risk 0'dır.
                _olum_kriz_ust = bool(
                    drives.in_danger
                    or drives.energy < 20.0
                    or drives.hunger > 85.0)
                # Ölüm ön-belirti gözlemi → risk sinyali.
                #
                # DİKKAT: risk HER TIKTE üretilmez. Ölüm modelinin
                # etiketleri sentetiktir (gerçek ölüm kaydı yok) ve
                # proje ilkesi şudur: "ölüm yokken strateji dayatmak sahte
                # otorite olur". Sürekli pozitif risk, modeli tek bir
                # komuta (kisitla_dosya) eğitip davranışı ele geçirirdi.
                # Bu yüzden risk YALNIZCA gerçek bir kriz belirtisi
                # varken (tehlike, enerji çöküşü, açlık krizi) üretilir;
                # o da yalnızca ÖLÜM ANINDA GÖRÜLEN sinyallerden
                # (ölüm günlüğü) beslenir.
                _olum_feats_ust = None
                if olum_ok and _olum_kriz_ust:
                    try:
                        _goz_ust = {"sinyal": "yok",
                                    "kaynak": ("bellek"
                                               if drives.hunger > 80
                                               else "guc"),
                                    "kim": "cekirdek",
                                    "siddet": ("ani"
                                               if drives.energy < 10
                                               else "kademeli"),
                                    "belirti": ("kaynak_tukendi"
                                                if drives.hunger > 30
                                                else "aniden_kesildi"),
                                    "onbelirti": "evet"}
                        _olum_feats_ust = olum_mod.ozellikler(_goz_ust)
                    except Exception:
                        _olum_feats_ust = None
                _sinyal_ust = ust_beyn_mod.topla_sinyalleri(
                    drives, mind, dam if damak_ok else None,
                    guv if guv_ok else None, sur, list(msgs.queue),
                    olum=olum_beyin if olum_ok else None,
                    context=context,
                    feats_damak=None,
                    E=drives.energy, H=drives.hunger,
                    sarsinti=float(bekleyen_sok),
                    yemek_var=_yemek_var_ust,
                    gorev_aktif=(gorev is not None),
                    surpriz=_surpriz_ust,
                    dunya_bozuk=_dunya_bozuk_ust,
                    olum_feats=_olum_feats_ust,
                )
                # Üst beyin dinamik epsilon: enerji/acı/sıkılmaya göre keşif
                # oranını ayarla (survival-first, boredom-driven exploration).
                ust.update_dynamic_params(drives)
                (_komut_ust, _idx_ust, _guven_ust,
                 _kaynak_ust) = ust.sec(_sinyal_ust)
                # Reddedildi mi? (öğrenme sinyali taşımaz — aşağıda
                # ust.ogren() çağrısı atlanır)
                _reddedildi_ust = False

                # Güvenlik ağı: modelin/keşfin önerdiği komut canlıda
                # etkili olabilir mi? (eğitilmemiş komut uygulanmaz)
                (_uygulanabilir, _gerekce) = ust.komut_uygulanabilir_mi(
                    _idx_ust, _guven_ust, _kaynak_ust, _sinyal_ust)
                if not _uygulanabilir:
                    ust.reddedilen += 1
                    jour.log("ust_beyn_reddedildi",
                             komut=_komut_ust,
                             idx=_idx_ust,
                             gerekce=_gerekce,
                             guven=round(_guven_ust, 3),
                             kaynak=_kaynak_ust)
                    # REDDEDİLEN KARAR → NE ÖDÜL NE CEZA.
                    #
                    # Önceki davranış (reddedilen komuta ceza): model
                    # reddedildiği komuttan kaçınmayı öğrenir → başka
                    # komutu da güvenle öneremez → hiç ödül → hiçbir
                    # şey öğrenilemez → güven eşiği ASLA geçilemez.
                    # Bu ÖLÜMCÜL KİLİTLENME döngüsüydü (denemede 186
                    # model kararının 186'sı da 'guven_yetersiz' ile
                    # reddedildi, hiçbiri doğrulanamadı).
                    #
                    # Şimdi: komut UYGULANMADI → gerçek bir sonuç
                    # (ödül) YOK → olmayan olaydan ders çıkarılamaz
                    # (epistemik dürüstlük). Doğrulama puanı düşürülmez,
                    # negatif ceza uygulanmaz; yalnızca reddedilen
                    # sayacı artar (şeffaflık + kilitlenme teşhisi).
                    #
                    # Modelin o komutu TEKRAR ÖNERMESİ devam eder;
                    # komut keşif/uygulama döngüsüyle gerçekten
                    # denendiğinde ödül gelir ve doğrulama puanı artar.
                    ust.reddedildi_ogren(_sinyal_ust, _idx_ust)
                    jour.log("ust_beyn_reddedildi_sayac",
                             komut=_komut_ust,
                             idx=_idx_ust,
                             gerekce=_gerekce,
                             guven=round(_guven_ust, 3),
                             kaynak=_kaynak_ust)
                    _reddedildi_ust = True
                    _komut_ust = ust_beyn_mod.KOMUT_YOK
                    _idx_ust = ust_beyn_mod.KOMUT_INDEKSI[
                        ust_beyn_mod.KOMUT_YOK]
                # NOT: string karşılaştırması `is` ile DEĞİL `==` ile
                # yapılır — `is` kimlik (identity) karşılaştırır ve
                # aynı değerli farklı nesnelerde yanlış sonuç verir.
                _override_aktif = (_komut_ust != ust_beyn_mod.KOMUT_YOK)
                # Tablo büyüklüğü BUDAMA ÖNCESİ ölçülür.
                #
                # NEDEN? "sifirla" komutu aşağıdaki blokta
                # mind.konsolide() çağırır ve tabloyu küçültür.
                # Ölçüm budamadan SONRA yapılırsa, şişik tablo
                # (1937 bağlantı) budandıktan sonra (131 bağlantı)
                # "sağlıklı" görünür → faydalı budama CEZALANIR
                # ve komut hiç öğrenilemez (ölçüt tersine döner).
                _bag_once_ust = len(mind.w)
                # "sifirla" komutunun budadığı bağlantı sayısı.
                #
                # SIFIRLAMA KOMUT BLOĞUNDAN ÖNCE YAPILIR.
                #
                # NEDEN? "sifirla" komutu, aşağıdaki override
                # bloğunda mind.konsolide() çağırır ve sonucu
                # _budanan_ust'a yazar. Sıfırlama bu bloğun
                # ARDINDA kalırsa, değer anında EZİLİR →
                # ödül hesabı her zaman "_budanan == 0" görür →
                # "sifirla" her denemede -0.1 alır → kanıt eşiğe
                # ASLA ulaşamaz → komut sürekli "dogrulanmadi"
                # ile reddedilir (gözlenen: 109 kez, kanıt 0.0).
                #
                # ESKİ SIRALAMA: sıfırlama komut bloğundan sonra
                # geliyordu (yorumu "önce sıfırlanmalı" diyordu ama
                # kod tersini yapıyordu — yorum ve kod çelişiyordu).
                _budanan_ust = 0

                if _override_aktif:
                    jour.log("ust_beyn_override",
                             komut=_komut_ust,
                             idx=_idx_ust,
                             guven=round(_guven_ust, 3),
                             kaynak=_kaynak_ust)
                    # Komutun ömrünü başlat: override 3 tik boyunca
                    # geçerlidir (her tikte azalt_sure() ile bir azalır)
                    ust.komut_ayarla(_komut_ust, _idx_ust, sure=3)
                    # Override komutunu eyleme dönüştür
                    if _komut_ust == ust_beyn_mod.KOMUT_ACIL_DINLEN:
                        act = "rest"
                    elif _komut_ust == ust_beyn_mod.KOMUT_ACIL_YEM:
                        act = "eat"
                    elif _komut_ust == ust_beyn_mod.KOMUT_KAPAT_AG:
                        # Ağ erişimini kapat: console/atolye/katalogla yok
                        feasible = [a for a in feasible
                                    if a not in ("console", "atolye",
                                                 "katalogla", "nedir",
                                                 "konum")]
                        act = mind.decide(stim, feasible) if feasible else "rest"
                    elif _komut_ust == ust_beyn_mod.KOMUT_KISITLA_DOSYA:
                        # Dosya sistemi erişimini kısıtla
                        feasible = [a for a in feasible
                                    if a not in ("console", "atolye",
                                                 "katalogla", "nedir",
                                                 "konum", "birak")]
                        act = mind.decide(stim, feasible) if feasible else "rest"
                    elif _komut_ust == ust_beyn_mod.KOMUT_GUVENLI_MOD:
                        # Sadece hayatta kalma eylemleri
                        guvenli = ["wander", "eat", "rest", "sense_self",
                                   "nest"]
                        feasible = [a for a in feasible if a in guvenli]
                        act = mind.decide(stim, feasible) if feasible else "rest"
                    elif _komut_ust == ust_beyn_mod.KOMUT_SIFIRLA:
                        # Sıfırla aralığı kontrolü: çok sık sıfırlama yapılırsa
                        # diğer komutlar starvation'a uğrar.
                        if state["ticks"] - ust.sifirla_son_tik < ust.SIFIRLA_ARALIK:
                            jour.log("ust_beyn_sifirla_aralik_atlandi",
                                     komut="sifirla",
                                     links=len(mind.w))
                            act = "rest"
                        else:
                            idx_sifirla = ust_beyn_mod.KOMUT_INDEKSI[
                                ust_beyn_mod.KOMUT_SIFIRLA]
                            # Cooldown aktifse sıfırlamayı tamamen atla.
                            if ust.redd_cooldown[idx_sifirla] > 0:
                                jour.log("ust_beyn_sifirla_cooldown_atlandi",
                                         komut="sifirla",
                                         links=len(mind.w))
                                act = "rest"
                            else:
                                ust.sifirla_son_tik = state["ticks"]
                                _budanan = mind.konsolide(koru_ust=300)
                                _budanan_ust = _budanan
                                if _budanan == 0:
                                    # Budamsız sıfırlama: no-op. Anında cooldown.
                                    ust.redd_cooldown[idx_sifirla] = 5
                                    jour.log("ust_beyn_sifirla_noop_cooldown",
                                             komut="sifirla",
                                             links=len(mind.w))
                                else:
                                    # Başarılı sıfırlama da kısaca cooldown'a girer:
                                    # ardışık sıfırlama tight-loop'unu kırar.
                                    ust.redd_cooldown[idx_sifirla] = 2
                                    ust.sifirla_noop_serisi = 0
                                jour.log("ust_beyn_sifirla", budanan=_budanan,
                                         links=len(mind.w))
                                act = "rest"
                    else:
                        act = mind.decide(stim, feasible)
                else:
                    act = mind.decide(stim, feasible)
                mind.working_remember(stim, act)  # çalışma belleği kaydı (Aşama 3)
                # Üst beyin öğrenmesi için eylemden önceki enerji/açlık
                # fotoğrafı (komutun amacına göre ödül ölçümü için)
                _enerji_once_ust = float(drives.energy)
                _aclik_once_ust = float(drives.hunger)
                _kurtulus_ust = False   # bu tikte acıdan kurtulma oldu mu
                # NOT: _budanan_ust, yukarıda (komut bloğundan ÖNCE)
                # sıfırlandı. Burada TEKRAR sıfırlanırsa, "sifirla"
                # komutunun budama sayısı anında ezilir → ödül
                # hesabı hep 0 görür → kanıt eşiğe asla ulaşamaz.
                path = None
                pred = None
                veto = 0.0        # inkâr hakkı ödülü (Aşama 4)
                if act == "eat":
                    food = bod.find_food()
                    if food:
                        kcfg = cfg.get("kurallar") or cfg
                        # damak adayları sıralar: en yüksek tahminli yemek
                        path = (dam.sec(food, kcfg, epsilon=0.15)
                                if damak_ok else random.choice(food))
                        if path and bod.kutu_yolu(path):
                            pred = dam.tahmin(damak_mod.ozellikler(
                                path.split("/")[-1], kcfg, path=path))
                    else:
                        # Yemek yok: "eat" eylemi yolsuz çalıştırılırsa
                        # gövde patlar. Yemek yokluğu bir GÖZLEM
                        # (acı faturası değil) — boşuna denemek
                        # enerji harcar, o yüzden kısa devre.
                        res_eat = {"obs": "yemek yok", "kind": "file",
                                   "novel": 0, "gain": 0, "relief": 0,
                                   "unlock": []}
                # Hiçbir eylem organizmayı öldüremez: ölüm BEDENDEN gelir
                # (enerji), Python hatasından değil. Beklenmedik hata
                # günlüğe düşer, enerji harcanır, döngü sürer.
                try:
                    # tezgâh işi bedenin değil görev organının aletidir
                    if act == "katalogla":
                        res = tez.calistir_bir(state["ticks"])
                        bod.last_cost = body_mod.Body.COSTS.get("katalogla", 3)
                    elif act == "nedir":
                        res = tez.nedir_bir(paket_beyin)
                        bod.last_cost = body_mod.Body.COSTS.get("nedir", 2)
                    elif act == "konum":
                        # dizin modeli "bu dosya nerede?" diyor, organizma
                        # SADECE ilk 3 aileyi tarıyor (arama ekonomisi)
                        res = tez.konum_bir()
                        bod.last_cost = body_mod.Body.COSTS.get("konum", 2)
                    elif act == "birak":
                        # inkâr hakkı (Aşama 4): hedefi bedelsiz terk et.
                        # Ödül kural değil ölçüm: 2+ denemeden sonra
                        # bırakmak kârdır (+1), ilk denemede bırakmak
                        # aceledir (−1) → "ne zaman hayır diyeceğini"
                        # beyin bu ödülden öğrenir; hedef sonraki tikte
                        # kendiliğinden yenilenir.
                        deneme = kul.hedef_deneme
                        veto = 1.0 if deneme >= 2 else -1.0
                        res = {"obs": "bıraktı (%s, deneme=%d)"
                               % (hedef_tip, deneme),
                               "kind": "birak", "novel": 0, "gain": 0}
                        jour.log("birak", hedef=hedef_tip, deneme=deneme)
                        kul.birak()
                        bod.last_cost = 0
                    elif act.startswith("cmd:"):
                        # komut kullanımı: hedefi kullanan organ çalıştırır,
                        # çıktıyı dosya sistemi/dpkg yargılar
                        res = kul.uygula(act)
                        res["hedef_tip"] = hedef_tip
                        bod.last_cost = int(res.get("cost", 2))
                    elif act == "atolye":
                        # Sahne 1: tek kapı eylem() — işi kendi seçer
                        # (sec_is), sürprizden merak ödülünü o biçer.
                        # Ödül enerjiye değil doğrudan reward'a gider.
                        res = atolye.eylem(atolye.sec_is(), son_gozlem)
                        bod.last_cost = body_mod.Body.COSTS.get("atolye", 1)
                    elif act == "eat" and not path:
                        # yemek seçilemedi (yok ya da kutu dışı) →
                        # gövdeye hiç göndermeden gözlem döndür
                        res = {"obs": "yemek yok", "kind": "file",
                               "novel": 0, "gain": 0, "relief": 0,
                               "unlock": []}
                        bod.last_cost = body_mod.Body.COSTS.get("eat", 2)
                    else:
                        res = bod.perform(act, path=path)
                except Exception as e:      # noqa: BLE001
                    import traceback
                    tb = traceback.format_exc(limit=3)
                    jour.log("hata", act=act, err=type(e).__name__,
                             msg=str(e)[:200], iz=tb[-400:])
                    bod.last_cost = body_mod.Body.COSTS.get(act, 2)
                    res = {"obs": "eylem bozuldu: %s" % type(e).__name__,
                           "kind": "hata", "novel": 0, "gain": 0}

                cost = bod.last_cost
                drives.spend(cost)
                gain, relief_done = 0.0, 0.0
                if act == "eat":
                    gain, relief_done = drives.consume(
                        res.get("gain", 0), res.get("relief", 0))
                elif act in ("katalogla", "konum", "nedir") or \
                        act.startswith("cmd:"):
                    odul = int(res.get("gain", 0))
                    if odul:
                        gain, _ = drives.consume(odul, 0)
                    if act.startswith("cmd:"):
                        # çalışma belleği: son komut tuttu mu →
                        # bir sonraki uyaran son:ok/son:hata taşır
                        son_cmd = "ok" if res.get("dogru") else "hata"
                        # öğrenme kanıtı: hangi hedefe hangi komut tuttu
                        # (journal her denemeyi kanıt olarak saklar)
                        jour.log("kullan", hedef=res.get("hedef_tip"),
                                 komut=act, dogru=bool(res.get("dogru")),
                                 odul=odul, deneme=res.get("deneme"))
                        if res.get("engel"):
                            # AELAAN sert duvarı: yasaklı sınıf önerisi —
                            # çevrimdışı analiz kanıtı (golge_log.jsonl'deki
                            # neden ile eşleşir: hedef+komut+deneme)
                            jour.log("kullan_engel",
                                     hedef=res.get("hedef_tip"),
                                     komut=act,
                                     neden=res.get("obs", "")[:200],
                                     deneme=res.get("deneme"))
                        if res.get("duraklama"):
                            # çevrimdışı yeniden eğitim kanıtı (egit_ag.py):
                            # hedef 3 denemede karşılanamadı → kapısı ölü
                            # ya da ödül ölçümde gürültü üretiyor
                            jour.log("kullan_duraklama",
                                     hedef=res.get("hedef_tip"),
                                     komut=act,
                                     deneme=res.get("deneme"))
                            # 3. deneme alternatifi (Faz 2): zincirde ilk
                            # ara-veri komutu (pgrep/find) boş çıkarsa,
                            # yerine PS/LS denensin — tek deneme, son şans.
                            alt = {"cmd:pgrep": "cmd:ps",
                                   "cmd:ps": "cmd:pgrep",
                                   "cmd:find": "cmd:ls",
                                   "cmd:ls": "cmd:find"}.get(act)
                            if (alt
                                    and res.get("hedef_tip")
                                    in ("SUREC_SAY", "DOSYA_SAY")
                                    and alt in kul.eylemler()):
                                res2 = kul.uygula(alt)
                                res2["hedef_tip"] = res.get("hedef_tip")
                                jour.log("kullan",
                                         hedef=res2.get("hedef_tip"),
                                         komut=alt,
                                         dogru=bool(res2.get("dogru")),
                                         odul=int(res2.get("gain", 0)),
                                         deneme=res2.get("deneme"),
                                         alt3=act)
                                if res2.get("dogru"):
                                    odul2 = int(res2.get("gain", 0))
                                    if odul2:
                                        gain += odul2
                                        drives.consume(odul2, 0)
                        zincir = res.get("hedef_tip") in (
                            "SUREC_SAY", "DOSYA_SAY")
                        if (not res.get("dogru")
                                and not res.get("engel")
                                and not mind.son_kesif and not zincir):
                            # yanlış KESTİRİM denemesi → ders defterine:
                            # beyin emindi ama yanıldı — gerçek bilgi
                            # boşluğu. Keşif hatası yazılmaz: zaten
                            # emin değildi, bedelini enerjiyle ödedi.
                            # Zincir hedeflerinde (Aşama 2) ara adım
                            # (ps → wc) hata DEĞİL: doğrulayıcı yalnızca
                            # son sayıyı yargılar → ders'e girmez.
                            # İnsan satır sonuna |dogrusu=cmd:... yazarsa
                            # organizma onu doğrudan öğrenir.
                            ders_mod.yaz(res.get("hedef_tip"), act,
                                         res.get("obs"))
                for cmd in res.get("unlock", []):
                    jour.log("organ_unlock", organ=cmd)
                if res.get("kutu") and path:
                    # tahmin-gerçeklik çifti: damak hem ölçülür hem yaşar
                    kcfg = cfg.get("kurallar") or cfg
                    feats = damak_mod.ozellikler(path.split("/")[-1], kcfg,
                                                 path=path)
                    jour.log("tahmin", dosya=path,
                             tahmin=(round(pred, 1)
                                     if pred is not None else None),
                             gercek=res["gain"])
                    dam.ogren(feats, res["gain"])

                reward = (gain - cost
                          + veto
                          + relief_done * 0.4
                          + float(res.get("merak", 0.0))   # Sahne 1: merak
                          + res.get("novel", 0) * 3.0
                          + (4.0 if res.get("novel_cmd") else 0.0)
                          + (2.0 if act.startswith("go:")
                             and ".bite" in res.get("obs", "") else 0.0)
                          + (1.0 if act in ("rest", "nest") else 0.0))

                # --- gecikmeli kredi: yemek bulunca son eylemler de pay alır ---
                # "gizli'ye döndüm ve doydum" bilgisi go'ya geri yazılır
                # → tahmin böyle öğrenilir (Perde 3'ün beyni).
                if gain > 0.2:
                    for i, (prev_stim, prev_act) in enumerate(
                            reversed(recent[-3:])):
                        if prev_act == act:
                            continue
                        bonus = gain * (0.30, 0.20, 0.10)[i]
                        mind.credit(prev_stim, prev_act, bonus)

                # --- Perde 1: acı & kurtuluş ---
                if drives.in_danger and not was_danger:
                    jour.log("pain_enter",
                             E=round(drives.energy, 1),
                             H=round(drives.hunger, 1))
                    # Z3 (ölüm ön-belirti): acı eşiğinde olum modelinden
                    # kategori+strateji TAHMİNİ günlüğe (davranışı değil,
                    # gözlemi bağlar: ölüm yokken strateji dayatılmaz).
                    # Ön-belirti + (ölünürse) gerçek kategori = kalibrasyon
                    # verisi; sur=sur+eksik listesi acıyı bağlar.
                    try:
                        if olum_ok:
                            _onb = {"sinyal": "yok",
                                    "kaynak":
                                    ("bellek" if drives.hunger > 80
                                     else "guc"),
                                    "kim": "cekirdek",
                                    "siddet": ("ani" if drives.energy < 10
                                               else "kademeli"),
                                    "belirti": ("kaynak_tukendi"
                                                if drives.hunger > 30
                                                else "aniden_kesildi"),
                                    "onbelirti": "evet"}
                            _kat, _str = olum_beyin.tani(_onb)[:2]
                            jour.log("olum_onbelirti", kategori=_kat,
                                     strateji=_str,
                                     E=round(drives.energy, 1))
                    except Exception:
                        pass
                    was_danger = True
                if drives.in_danger:
                    # acı: derinleştikçe sertleşen bir fatura
                    reward -= drives.pain() * drives.pain_penalty
                elif was_danger:
                    # kurtuluş: eşiğin üstüne bir kerelik hayat ödülü
                    reward += drives.relief_bonus
                    jour.log("relief", act=act,
                             E=round(drives.energy, 1))
                    _kurtulus_ust = True
                    was_danger = False

                # sıkılma (Aşama 4): yenilik doyurur, rutin bunaltır —
                # iç dürtü her tikte güncellenir; beyin keşif baskısını
                # bundan alır (drives.sikilma → mind.sikilma → decide).
                # Aşama 6: merak ÖDÜLÜ de doygunluk söndürür (kesirli) —
                # atölye novel=0 döndürdüğü için meraksız dünyada
                # sıkılma hiç sönmeyip1.00'de kitleniyordu (ölçüm:
                #3309 merak olayı → sikilma hep 1.00).
                drives.sikilan(res.get("novel", 0)
                               + (1 if res.get("novel_cmd") else 0)
                               + (1.0 if float(res.get("merak", 0.0)) > 0
                                  else 0.0))

                mind.learn(stim, act, reward,
                           r_merak=float(res.get("merak", 0.0)))
                # --- Üst (genel) beyin öğrenmesi ---
                # Bileşik ve AMAÇ-HİZALI ödül. Tek bileşenli enerji
                # farkı çok zayıf bir sinyal (tipik |ΔE| ~ 3-5 / 150 =
                # 0.02-0.03 → gradyan yok denecek kadar küçük) ve
                # komutun amacıyla ilgisiz. Bu yüzden iki bileşen:
                #   (a) GERÇEK sistem ödülü (reward) — "eylem işe yaradı mı"
                #   (b) amaç-hizalı bonus — "komutun kendi amacı gerçekleşti mi"
                # Bileşenler:
                #   acil_dinlen  → tehlikede sakinleşmek
                #   acil_yem     → açlığın düşmesi
                #   kapat_ag     → saldırı/shock varsa doğru, yoksa zararsız
                #   kisitla_dosya→ riskli erişim engellendiyse doğru
                #   guvenli_mod  → tehlike varken hayatta kalmaya katkı
                #   sifirla      → ölü ağırlıkları budar (tablo şişmesini önler)
                #   yok          → alt beyinler serbestken doğru davranıldı
                _enerji_son_ust = float(drives.energy)
                _dE = _enerji_son_ust - _enerji_once_ust
                _aclik_son = float(drives.hunger)
                _aclik_once = _aclik_once_ust
                # TEMEL BİLEŞEN: eylemin GERÇEK sistem ödülü. Alt beyin
                # de aynı sinyali kullanıyor; üst beyin bunu "komut
                # işe yaradı mı" ölçütü olarak alır. (Enerji farkı
                # tek başına çok zayıf: |ΔE| ~ 3-5 / 150 = 0.02-0.03.)
                _odul_ust = max(-0.6, min(0.6, reward / 25.0))
                # AMAÇ-HİZALI bonus: komutun KENDİ amacı gerçekleşti mi?
                # Bonus küçük tutulur (+0.1..+0.4) ve koşul sağlanmazsa
                # ceza da küçüktür (-0.05) — aksi halde keşif (epsilon)
                # sistematik olarak cezalandırılır ve hiçbir komut
                # öğrenilemez (ölümcül kilitlenme).
                if _komut_ust == ust_beyn_mod.KOMUT_ACIL_DINLEN:
                    # dinlenmenin amacı: tehlikede sakinleşmek.
                    # (rest enerji toplamaz — bedende öyle bir mekanizma
                    # yok; bu yüzden ölçüt "zarar görmemek")
                    if drives.in_danger:
                        _odul_ust += 0.2
                elif _komut_ust == ust_beyn_mod.KOMUT_ACIL_YEM:
                    # yemenin amacı: açlığı dindirmek
                    if _aclik_once > 50.0:
                        _odul_ust += 0.25     # gerçekten acıktı
                    if _yemek_var_ust:
                        _odul_ust += 0.1
                    else:
                        _odul_ust -= 0.1      # yemek yoksa boşuna dene
                elif _komut_ust == ust_beyn_mod.KOMUT_KAPAT_AG:
                    # ağ kapatmanın amacı: saldırıyı engellemek
                    if _sinyal_ust[ust_beyn_mod.IDX_SOK_BEKLIYOR] > 0.0:
                        _odul_ust += 0.4
                    else:
                        _odul_ust -= 0.05     # gereksiz ama zararsız
                elif _komut_ust == ust_beyn_mod.KOMUT_KISITLA_DOSYA:
                    # dosya kısıtlamanın amacı: riskli erişimi durdurmak
                    if (_sinyal_ust[ust_beyn_mod.IDX_MESAJ_VAR] > 0.0
                            or _sinyal_ust[ust_beyn_mod.IDX_OLUM_RISK] > 0.0):
                        _odul_ust += 0.3
                    else:
                        _odul_ust -= 0.05
                elif _komut_ust == ust_beyn_mod.KOMUT_GUVENLI_MOD:
                    # güvenli modun amacı: tehlikede hayatta kalmak
                    if drives.in_danger:
                        _odul_ust += 0.25
                    else:
                        _odul_ust -= 0.05
                elif _komut_ust == ust_beyn_mod.KOMUT_SIFIRLA:
                    # Sıfırlamak: tablo şişmesini engeller (gerçek fayda).
                    #
                    # ÖLÇÜT: EYLEM DEĞİL, DURUM.
                    #
                    # NEDEN durum? "Sifirla"nın amacı "tablo şişmesin";
                    # faydası budunan bağlantı SAYISI DEĞİL, tablonun
                    # sağlıklı olup olmamasıdır. Eyleme göre ödül
                    # verilirse model "her zaman sifirla" diye öğrenir
                    # ve her tikte tabloyu siler → tüm öğrenme yok
                    # olur (ödül hacking'i). Duruma göre ödül verilirse
                    # model "tablo ŞİŞTİĞİNDE sifirla" diye öğrenir —
                    # tam olarak istenen davranış.
                    #
                    # ESKİ ÖLÇÜT (iki hata bir arada):
                    #   "+0.15 if budama else -0.1"
                    #   (a) _budanan_ust sıfırlama hatası yüzünden
                    #       HER ZAMAN 0 görünüyordu → hep -0.1;
                    #   (b) "budama gerçekleşti" EYLEMİ ödüllendiriyordu.
                    # Ölçüt (a) yukarıda düzeltildi; (b) burada.
                    #
                    # ÖLÇÜM: tablo sağlığı = bağlantı sayısı / kapasite.
                    # "Kapasite" beyin dokümanına göre (~165 bağlantı
                    # yeter; ölçülen: budama sonrası ~130, şişik hali
                    # ~2000) — 600 tablonun "rahat" sınırıdır.
                    _BAG_KAP = 600
                    _bag_son = _bag_once_ust
                    if _bag_son <= _BAG_KAP:
                        # Tablo zaten sağlıklı: budamanın ek faydası
                        # YOK. Nötrden hafif NEGATİF — model "gereksiz
                        # budama yapma" demeyi de öğrenir.
                        # (Negatif küçük: 0.0 olsaydı "ödül" dalına
                        # düşer ve "sifirla iyi" diye öğretirdi.)
                        _odul_ust -= 0.02
                    elif _budanan_ust:
                        # Şişikti VE budandı → gerçek fayda.
                        _odul_ust += 0.15
                    else:
                        # Şişik ama budanamadı → komut işe yaramadı.
                        _odul_ust -= 0.10
                else:
                    # KOMUT_YOK da bir KARARDIR: alt beyinlerin serbest
                    # davranması doğruysa ödül alır → "yok" sınıfı da
                    # öğrenilir (aksi halde model hep komut seçmeye eğilimli
                    # kalır ve alt beyinler devre dışı kalır).
                    #
                    # DENGE (kritik): "yok" sınıfının ödülü, bir komutun
                    # olumlu bonusundan KÜÇÜK ve NEREDEYSE SIFIR olmalı.
                    # Çünkü softmax hedefi doğrudan olasılığa yakınsar:
                    #   ödül 0.05 → hedef ≈ 0.33  ("yok" ~0.33, diğerleri
                    #   ~0.11 → "yok" DAIMA argmax olur → model eşiğe
                    #   ULAŞAMAZ, kilitlenme)
                    #   ödül 0.00 → hedef = 0.30 (= eşik, sınırda)
                    # Doğru: "yok" NE ödüllendirilir NE cezalandırılır;
                    # sadece tehlikede cezalandırılır (müdahale
                    # gerekirken müdahale etmemek yanlıştır).
                    if drives.in_danger:
                        _odul_ust -= 0.2     # tehlikede müdahale etmeliydi

                # ortak acı/kurtuluş bileşeni
                if drives.in_danger:
                    _odul_ust -= 0.5 * drives.pain()
                elif _kurtulus_ust:
                    _odul_ust += 0.3

                _odul_ust = max(-1.0, min(1.0, _odul_ust))
                # ÖĞRENME YALNIZCA GERÇEK BİR KARAR OLDUĞUNDA:
                # reddedilen karar uygulanmadı, dolayısıyla ödülü de
                # yoktur — olmayan bir olaydan ders çıkarılamaz.
                # (Reddedilme → "yok" sınıfına ödül yazmak modeli
                # "reddedilmek"i öğrenmeye itiyor ve güven eşiğine
                # ulaşmasını engelliyordu — kilitlenme.)
                if not _reddedildi_ust:
                    ust.ogren(_sinyal_ust, _idx_ust, _odul_ust,
                              keşif=(_kaynak_ust == "kesif"))
                recent.append((stim, act))
                if len(recent) > 4:
                    recent.pop(0)

                state["last"] = act
                last_kind = res.get("kind", "act")
                son_gozlem = res.get("obs", "")   # atölye nesnesine yazılır
                context = last_kind
                jour.log("act", action=act, obs=res["obs"],
                         E=round(drives.energy, 1),
                         H=round(drives.hunger, 1),
                         R=round(reward, 1))
                if state["ticks"] % 10 == 0:
                    jour.log("learn", stim=stim, action=act,
                             w=round(mind.score(stim, act), 2),
                             # Aşama 4: R = o anki ödül (hatıra replay'i
                             # bunu okur), S = sıkılma (gözlem)
                             R=round(reward, 1),
                             # R_merak = R'nin atölye-merak bileşeni:
                             # sürpriz↔öğrenme ablasyonu (R−R_merak replây,
                             # karıştır-merak deneyi) bu alandan kurulur
                             R_merak=round(float(res.get("merak", 0.0)), 2),
                             S=round(drives.sikilma, 2))
                    mind.save(brain_path)
                # ders defteri: insanın düzelttiği satırları işle
                if state["ticks"] % 20 == 0:
                    n_ders, n_red = ders_mod.oku(
                        mind, jour, beyaz=kullan_mod.BEYAZ)
                    if n_ders or n_red:
                        jour.log("ders_ozet", islenen=n_ders, red=n_red)
                # her 50 tikte bir zincir replay: ara tampon doluysa son
                # adımı (cmd:wc) pekiştir → beyin "ara veri → sayı" zincirini
                # kalıcılaştırır (Faz 2, canlı deneme)
                if (state["ticks"] % 50 == 0 and kul.ara.strip()
                        and kul.hedef
                        and kul.hedef["tip"] in ("SUREC_SAY", "DOSYA_SAY")):
                    deneme_snapshot = kul.hedef_deneme
                    res_replay = kul.uygula("cmd:wc")
                    kul.hedef_deneme = deneme_snapshot  # 3'e ulaşmayı bozma
                    jour.log("kullan_replay",
                             hedef=kul.hedef["tip"],
                             komut="cmd:wc",
                             dogru=bool(res_replay.get("dogru")),
                             odul=int(res_replay.get("gain", 0)),
                             deneme=res_replay.get("deneme"))
                    if res_replay.get("dogru"):
                        odul_r = int(res_replay.get("gain", 0))
                        if odul_r:
                            gain += odul_r
                            drives.consume(odul_r, 0)
                # günlük şişkinliğini dizinde tut: eşik aşarsa arşivle
                if (journal_azami_mb > 0
                        and state["ticks"] % 200 == 0):
                    try:
                        mb = Path(jour.path).stat().st_size / 1e6
                        if mb > journal_azami_mb:
                            hedef = journal_mod.arsivle(jour.path)
                            if hedef:
                                jour.log("journal_arsiv", mb=round(mb, 1),
                                         hedef=hedef)
                    except OSError:
                        pass
                # gölge günlüğü de aynı ritimle arşivle: Journal.log ve
                # Kapi.calistir ikisi de her çağrıda 'a' modunda açar →
                # taşıma canlıya güvenli (aynı disk → atomik replace)
                if (golge_azami_mb > 0
                        and state["ticks"] % 200 == 0):
                    try:
                        mb = Path(golge_yolu).stat().st_size / 1e6
                        if mb > golge_azami_mb:
                            hedef = journal_mod.arsivle(golge_yolu)
                            if hedef:
                                jour.log("golge_arsiv", mb=round(mb, 1),
                                         hedef=hedef)
                    except OSError:
                        pass
                # gündüz konsolidasyonu (Aşama 5): uyku hattı 6 saatte bir
                # bakıyor, tablo o sırada şişiyor (2026-10-18: 16k bağlantı,
                # medyan 0.001 — neredeyse tümü budama eşiği altında). Aynı
                # konsolide() (INSTINCTS korunur, ±0.02), gündüz periyodik:
                # rastgele/docs zayıf bağlantılar 500 tikte bir temizlenir,
                # save bir sonraki %10 tikinde atomik olarak iner.
                if (state["ticks"]
                        and state["ticks"] % 500 == 0):
                    # koru_ust=300: budama SONRASI korunacak TOPLAM tablo
                    # tabanı (güçlüler zaten korunur, kalan pay zayıflardan
                    # doldurulur). Tablonun tamamını silmek tüm öğrenmeyi
                    # yok eder.
                    budanan = mind.konsolide(koru_ust=300)
                    if budanan:
                        mind.save(brain_path)
                        jour.log("konsolide_gunduz", silinen=budanan,
                                 links=len(mind.w))

            # Üst beyin override süresini azalt (her tik)
            ust.azalt_sure()

            time.sleep(tick_sleep)
    except KeyboardInterrupt:
        jour.log("sleep", note="dışarıdan uyku emri", **status())
    finally:
        mind.allowed_extra = bod.allowed
        mind.save(brain_path)
        jour.log("brain_save", links=len(mind.w))
        ust.save()
        jour.log("ust_beyn_save", samples=ust.samples, tik=ust.tik,
                 dogrulama=[round(d, 2) for d in ust.dogrulama],
                 reddedilen=ust.reddedilen,
                 secim=ust.secim_sayilari)
        sur.save()
        jour.log("surec_save", ornek=sur.ornek, adet=len(sur.adet))
        if dam.samples:
            if dam.save():
                jour.log("damak_save", samples=dam.samples, kova=len(dam.n))
            else:
                jour.log("damak_save_atlandi",
                         not_="dosya dışarıdan yeniden eğitilmiş, "
                              "korundu")
        if not drives.alive:
            # Z3: ölüm anında kategori tahmini kayda (gerçek-sonuç tohumu):
            # organizma daha hiç ölmedi; ilk ölümde tahmin-vs-gerçek
            # kalibrasyonu kurulur. death olayı her zamanki gibi düşer
            # (erken dönüş YOK — aşağıda door.stop() çalışmalı).
            try:
                if olum_ok:
                    _kat, _str = olum_beyin.tani({"sinyal": "yok",
                                                  "kaynak": "guc",
                                                  "kim": "cekirdek",
                                                  "siddet": "kademeli",
                                                  "belirti": "kaynak_tukendi",
                                                  "onbelirti": "evet"})[:2]
                    jour.log("olum_gercek", kategori=_kat, strateji=_str,
                             **status())
            except Exception:
                pass
            jour.log("death", note="enerji tükendi", **status())
        elif state["ticks"] and args.ticks:
            jour.log("pause", note="tik doldu", **status())
        door.stop()


if __name__ == "__main__":
    main()