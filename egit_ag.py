#!/usr/bin/env python3
"""egit_ag.py — AG_TARA/BENI_TARA öğrenmesini günlüften yeniden oynat (çevrimdışı).

Faz 1'in ölçüm + eğitim aracı. Ağ taraması (nmap/ping/ip) denemeleri
jurnalde kanıt olarak durur; bu betik o kanıtları toplar, raporlar ve
(beyne dokunulduğunda) ÖDÜL UYDURMADAN yeniden oynatır — jurnale o an
kaydedilen R aynen kullanılır (brain.hatira ile aynı ilke).

  python3 egit_ag.py              # rapor + AG tekrar oynat + beyne kaydet
  python3 egit_ag.py --rapor      # yalnızca rapor (beyne dokunmaz)
  python3 egit_ag.py --sifirdan   # beyin AG kanıtlarından yeniden kurulur
                                  # (eski dosya .egit_ag_yedek'e taşınır)
  python3 egit_ag.py --epok N     # tekrar oynatım turu (varsayılan 1)

Rapor iki kayıt türünden:
  kullan            → kapı bazlı deneme/kazanma (cmd:nmap / cmd:ping / ...)
  kullan_duraklama  → 3 denemede karşılanamayan hedef (ölü kapı adayı)

Not: yalnızca aktif journal.jsonl okunur (arşiv .gz'lar değil — hatira
da son pencereyi oynatır); journal döndüyse en güncel kanıt buradadır.
"""
import argparse
import json
import shutil
from pathlib import Path

import brain as brain_mod

ROOT = Path(__file__).resolve().parent


def gunlugu_oku(yol, kuyruk=4_000_000):
    """Jurnalin son penceresi (brain.hatira ile aynı okuma deseni)."""
    try:
        with open(yol, "rb") as f:
            f.seek(0, 2)
            boy = f.tell()
            f.seek(max(0, boy - kuyruk))
            ham = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    kayitlar = []
    for satir in ham.splitlines():
        if '"kind"' not in satir:
            continue
        try:
            kayitlar.append(json.loads(satir))
        except ValueError:
            continue
    return kayitlar


def rapor(kayitlar):
    """Kapı bazlı deneme/kazanma + duraklama tablosu (AG_TARA + BENI_TARA)."""
    kapi = {}       # komut → [deneme, kazanma]
    duraklama = {}  # komut → 3'te takılma sayısı
    for j in kayitlar:
        hedef = j.get("hedef")
        if hedef not in ("AG_TARA", "BENI_TARA"):
            continue
        komut = j.get("komut") or "?"
        if j.get("kind") == "kullan":
            k = kapi.setdefault(komut, [0, 0])
            k[0] += 1
            if j.get("dogru"):
                k[1] += 1
        elif j.get("kind") == "kullan_duraklama":
            duraklama[komut] = duraklama.get(komut, 0) + 1

    print("=== AG/BENI kapı performansı (jurnal kanıtı) ===")
    if not kapi:
        print("  (AG_TARA/BENI_TARA 'kullan' kaydı yok — canlı deneme henüz olmamış)")
    for komut in sorted(kapi):
        deneme, kazanma = kapi[komut]
        oran = (100.0 * kazanma / deneme) if deneme else 0.0
        print("  %-12s %5d deneme  %5d kazanç  %%%.1f  (duraklama: %d)"
              % (komut, deneme, kazanma, oran, duraklama.get(komut, 0)))
    toplam_d = sum(d[0] for d in kapi.values())
    toplam_k = sum(d[1] for d in kapi.values())
    if toplam_d:
        print("  TOPLAM        %5d deneme  %5d kazanç  %%%.1f"
              % (toplam_d, toplam_k, 100.0 * toplam_k / toplam_d))
    print("  duraklama (3'te takılma): %d" % sum(duraklama.values()))
    return {"kapi": kapi, "duraklama": duraklama}


def tekrar_oynat(mind, kayitlar, epok=1):
    """gorev:AG_TARA/gorev:BENI_TARA uyaranlı learn kayıtlarını kayıtlı R ile oynat.

    Ödül uydurulmaz: jurnale o an ne yazıldıysa o tekrarlanır. AG_TARA
    dışı learn satırları seçilmez (hedefli tekrar — ağ öğrenmesinin
    diğer bağlantılarını bozmaz).
    """
    ornekler = []
    for j in kayitlar:
        if j.get("kind") != "learn":
            continue
        stim = j.get("stim") or ""
        if not any(t in stim for t in ("gorev:AG_TARA", "gorev:BENI_TARA")):
            continue
        if "action" not in j or not isinstance(j.get("R"), (int, float)):
            continue   # R'siz eski learn satırları (hatira ile aynı kural)
        ornekler.append((stim, j["action"], float(j["R"])))
    oynanan = 0
    for _ in range(max(1, epok)):
        for stim, act, r in ornekler:
            mind.learn(stim, act, r)
            oynanan += 1
    return oynanan, len(ornekler)


def main():
    ap = argparse.ArgumentParser(
        description="AG_TARA öğrenmesini jurnal kanıtından yeniden oynat")
    ap.add_argument("--rapor", action="store_true",
                    help="yalnızca rapor; beyne dokunma")
    ap.add_argument("--sifirdan", action="store_true",
                    help="beyni AG kanıtlarından yeniden kur (yedekli)")
    ap.add_argument("--epok", type=int, default=1,
                    help="tekrar oynatım turu (varsayılan 1)")
    ap.add_argument("--gunluk", default=str(ROOT / "journal.jsonl"))
    ap.add_argument("--beyin", default=str(ROOT / "zeka" / "brain.json"))
    b = ap.parse_args()

    kayitlar = gunlugu_oku(b.gunluk)
    print("jurnal kaydı okundu: %d (son pencere)" % len(kayitlar))
    rapor(kayitlar)

    if b.rapor:
        return 0

    yol = Path(b.beyin)
    mind = brain_mod.Brain()
    if b.sifirdan:
        if yol.exists():
            yedek = Path(str(yol) + ".egit_ag_yedek")
            shutil.copy2(yol, yedek)
            print("eski beyin yedeklendi:", yedek)
        print("beyin SIFIRDAN kuruluyor (yalnızca AG kanıtlarıyla)")
    elif yol.exists():
        try:
            mind.load(yol)
        except OSError:
            pass   # yoksa/okunamazsa sıfırdan (hatira ile aynı hoşgörü)

    oynanan, aday = tekrar_oynat(mind, kayitlar, b.epok)
    if aday == 0:
        print("AG learn kaydı yok: tekrar oynatılacak kanıt bulunamadı")
        if not b.sifirdan:
            return 0   # boş beyinle ezme; sifirdan istenmişse kurulsun
    else:
        print("tekrar oynatılan AG örneği: %d (%d benzersiz × %d epok)"
              % (oynanan, aday, max(1, b.epok)))
    mind.save(yol)
    print("beyin kaydedildi:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
