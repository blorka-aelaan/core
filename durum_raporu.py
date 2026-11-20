#!/usr/bin/env python3
"""CORE sistem durum raporu: öğrenme, eylem, hatira, atolye."""
import json, sys, os

CORE = "/home/emrah/Genel/core"
JOURNAL = os.path.join(CORE, "journal.jsonl")
DURUM = os.path.join(CORE, "world", "atolye", ".durum.json")
BRAIN = os.path.join(CORE, "zeka", "brain.json")

def son_meta():
    last = None
    if not os.path.exists(JOURNAL):
        print("journal.jsonl yok")
        return
    with open(JOURNAL) as f:
        for l in f:
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("kind") == "meta":
                last = r
    if not last:
        print("meta kaydi bulunamadi")
        return
    print("=== SON META ===")
    print("tik:", last.get("tik"), "| baglam:", last.get("baglam"))
    print("lr:", last.get("lr"), "| epsilon:", last.get("epsilon"))
    print("dogrulama:", last.get("dogrulama_skoru"))
    print("trend_ema:", last.get("trend_ema"))
    print("lim:", last.get("lim_durum"))

def son_eylemler(n=5):
    print("\n=== SON %d EYLEM ===" % n)
    count = 0
    with open(JOURNAL) as f:
        lines = [l.strip() for l in f if l.strip()]
    for l in reversed(lines):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("kind") == "act":
            print(r.get("action"), "| R=", r.get("R"), "| E=", r.get("E"))
            count += 1
            if count >= n:
                break

def hatira_sayilari():
    print("\n=== HATIRA KAYITLARI ===")
    creplay = 0
    cperiodik = 0
    with open(JOURNAL) as f:
        for l in f:
            if '"hatira_replay"' in l:
                creplay += 1
            elif '"hatira_periodik"' in l:
                cperiodik += 1
    print("hatira_replay:", creplay)
    print("hatira_periodik:", cperiodik)

def atolye_durumu():
    print("\n=== ATOLYE ===")
    if not os.path.exists(DURUM):
        print("atolye durum dosyasi yok")
        return
    d = json.load(open(DURUM))
    toplam = len(d)
    bozuk = sum(1 for v in d.values() if v.get("bozuk"))
    saglik = round((toplam - bozuk) / max(1, toplam), 3)
    print("toplam nesne:", toplam)
    print("bozuk:", bozuk)
    print("saglik:", saglik)
    arac = [(k, v) for k, v in d.items() if v.get("tur") == "arac"]
    print("arac sayisi:", len(arac))
    for k, v in arac:
        print("  ", k, "kuvvet:", v.get("kuvvet"), "bozuk:", v.get("bozuk"))

def brain_baglanti():
    print("\n=== BEYIN ===")
    if not os.path.exists(BRAIN):
        print("brain.json yok")
        return
    b = json.load(open(BRAIN))
    links = b.get("links", [])
    print("baglanti sayisi:", len(links))

def zeka_dosyalari():
    print("\n=== ZEKA KLASORU (beyin/ogrenme dosyalari) ===")
    dosyalar = [
        "brain.json",
        "ust_beyn.json",
        "damak.json",
        "guvenlik.json",
        "komut_tehlike.json",
        "paket.json",
        "sistem_hafiza.json",
        "uyku.json",
    ]
    for ad in dosyalar:
        p = os.path.join(CORE, "zeka", ad)
        if os.path.exists(p):
            boyut = os.path.getsize(p)
            mt = os.path.getmtime(p)
            import time
            zaman = time.strftime("%H:%M:%S", time.localtime(mt))
            print(f"  {ad:<22} {boyut:>10} bytes  son degisim: {zaman}")
        else:
            print(f"  {ad:<22} YOK")


def ust_beyn_komutlar():
    print("\n=== UST BEYIN KOMUTLARI (zeka/ust_beyn.json) ===")
    p = os.path.join(CORE, "zeka", "ust_beyn.json")
    if not os.path.exists(p):
        print("ust_beyn.json yok")
        return
    try:
        d = json.load(open(p))
    except Exception as e:
        print("okunamadi:", e)
        return

    komutlar = ["yok", "acil_dinlen", "acil_yem", "kapat_ag",
                "kisitla_dosya", "guvenli_mod", "sifirla"]

    secim = d.get("secim_sayilari", [])
    dogr = d.get("dogrulama", [])

    print(f"  {'komut':<18} {'secim':>8} {'dogrulama':>10}")
    for i, k in enumerate(komutlar):
        s = secim[i] if i < len(secim) else 0
        dd = dogr[i] if i < len(dogr) else 0.0
        print(f"  {k:<18} {s:>8} {dd:>10.3f}")

    # Baglamsal dogrulama (en iyi 5)
    db = d.get("dogrulama_bağlam", {})
    if db:
        sirali = sorted(db.items(), key=lambda x: x[1], reverse=True)[:5]
        print("\n  En yuksek baglamsal dogrulama:")
        for (komut_idx, baglam_anahtar), puan in sirali:
            komut_adi = komutlar[int(komut_idx)] if isinstance(komut_idx, int) and int(komut_idx) < len(komutlar) else str(komut_idx)
            print(f"    {komut_adi:<16} | {baglam_anahtar:<30} | {puan:.3f}")


def eylem_cesidi():
    print("\n=== EYLEM CESIDI (ogrenme / takilma kontrolu) ===")
    acts = []
    with open(JOURNAL) as f:
        for l in f:
            l = l.strip()
            if not l:
                continue
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("kind") == "act":
                acts.append(r.get("action"))
    if not acts:
        print("act kaydi yok")
        return
    from collections import Counter
    c = Counter(acts)
    toplam = len(acts)
    farkli = len(c)
    print(f"  tum act sayisi: {toplam}")
    print(f"  farkli eylem sayisi: {farkli}")
    print(f"  cesitlilik orani: {farkli / max(1, toplam) * 100:.1f}%")
    print("  En cok tekrar eden 5 eylem:")
    for action, n in c.most_common(5):
        print(f"    {action:<30} {n:>5} kez (%{n / toplam * 100:.1f})")


if __name__ == "__main__":
    son_meta()
    son_eylemler()
    hatira_sayilari()
    atolye_durumu()
    brain_baglanti()
    ust_beyn_komutlar()
    eylem_cesidi()
    zeka_dosyalari()
    zeka_dosyalari()
