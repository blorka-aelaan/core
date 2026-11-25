#!/usr/bin/env python3
"""Öz hedef köprüsü ve üst beyin seçimlerini journal'dan özetler (salt okunur).

Kullanım:  python3 kopru_izle.py [journal.jsonl] [saat=3]
"""
import collections
import json
import statistics
import sys
import time

yol = sys.argv[1] if len(sys.argv) > 1 else "journal.jsonl"
saat = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
GAP = 300  # sn: aynı komutun ardışık satırları tek "seçim" sayılır

olaylar = []
with open(yol, encoding="utf-8", errors="ignore") as f:
    for satir in f:
        try:
            e = json.loads(satir)
        except ValueError:
            continue
        if isinstance(e, dict) and "t" in e:
            olaylar.append(e)
if not olaylar:
    sys.exit("journal boş")
son = olaylar[-1]["t"]
pencere = [e for e in olaylar if e["t"] >= son - saat * 3600]
T = lambda t: time.strftime("%H:%M:%S", time.localtime(t))
print("pencere: %s → %s (%.1f saat, %d olay)" % (T(pencere[0]["t"]), T(son), saat, len(pencere)))

# --- yeniden başlatmalar ve tik hızı (learn olaylarındaki tik sayacı geri sararsa yeni çalışma)
learn = [(e["t"], e["tick"]) for e in pencere if e.get("kind") == "learn" and isinstance(e.get("tick"), int)]
parcalar, mevcut = [], []
for a in learn:
    if mevcut and a[1] < mevcut[-1][1]:
        parcalar.append(mevcut)
        mevcut = []
    mevcut.append(a)
if mevcut:
    parcalar.append(mevcut)
print("\nçalışma parçaları (tik sayacı sıfırlanınca yeni parça):")
for p in parcalar:
    if len(p) >= 2 and p[-1][1] > p[0][1]:
        print("  %s → %s  tik %d→%d  ≈%.0f sn/tik" % (
            T(p[0][0]), T(p[-1][0]), p[0][1], p[-1][1], (p[-1][0] - p[0][0]) / (p[-1][1] - p[0][1])))
    else:
        print("  %s  (tek kayıt)" % T(p[0][0]))

# --- ayrı seçimler (ham satırlar değil)
satirlar = collections.Counter()
secimler = collections.Counter()
son_gorulen = {}
for e in pencere:
    if e.get("kind") != "ust_beyn_override":
        continue
    k = (e.get("komut"), e.get("kaynak"))
    satirlar[k] += 1
    if k not in son_gorulen or e["t"] - son_gorulen[k] > GAP:
        secimler[k] += 1
    son_gorulen[k] = e["t"]
print("\nüst beyin: AYRI seçim (ham günlük satırı) — komut/kaynak:")
for k, n in secimler.most_common(10):
    print("  %-26s %4d   (%d satır)" % (k, n, satirlar[k]))

# --- gerçek ASM oturumları
asm = [e["t"] for e in pencere if e.get("kind") == "asm_ogren_dongu"]
print("\nasm_ogren_dongu (gerçek ASM oturumu) sayısı:", len(asm))
if len(asm) >= 2:
    araliklar = [b - a for a, b in zip(asm, asm[1:])]
    print("  ilk %s, son %s, medyan aralık %.0f sn" % (T(asm[0]), T(asm[-1]), statistics.median(araliklar)))

# --- köprü
kopru = [e for e in pencere if e.get("kind") == "oz_hedef_kopru"]
print("\nköprü olayı:", len(kopru), "| hata:", sum(1 for e in pencere if e.get("kind") == "oz_hedef_kopru_hata"))
by = collections.defaultdict(list)
for e in kopru:
    by[e["komut"]].append(e["bias"])
for k, v in by.items():
    print("  %-12s olay %3d  bias medyan %.4f  en yüksek %.4f" % (k, len(v), statistics.median(v), max(v)))
print("  son 6:", [(T(e["t"]), e["komut"], e["bias"]) for e in kopru[-6:]])
print("\nOkuma: en yüksek bias ≈0.08'e (asm_ogren) yaklaşıyorsa köprü tam güçte itiyor demektir;")
print("       0.01'in altında kalıyorsa soğuma bitmeden komut hep yeniden seçilmiş demektir.")
