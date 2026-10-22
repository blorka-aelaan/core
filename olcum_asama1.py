"""Aşama 1 canlı ölçümü — YALNIZCA restart sonrası olaylar.

Kullanım: python3 olcum_asama1.py <restart_epoch>
  restart_epoch verilmezse journal'ın son satırının t'si kullanılır.

Ölçer:
- hedef tipi dağılımı (yeni DOSYA_OLC / PAKET_VERSIYON belirdi mi?)
- kapı (hedef x komut) başarısı → ölü alan oranı
"""
import json, sys, collections, os
R = '/home/emrah/Genel/core'
t_min = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
dosyalar = [R + '/journal.jsonl'] + sorted(
    __import__('glob').glob(R + '/arsiv/journal*.jsonl'))
hedef = collections.Counter()
mat = collections.defaultdict(lambda: [0, 0, 0])  # (hedef,komut)->[deneme,dogru,odul>0]
toplam = ok = 0
for d in dosyalar:
    if not os.path.exists(d):
        continue
    with open(d, encoding='utf-8', errors='replace') as f:
        for satir in f:
            if '"kullan"' not in satir:
                continue
            try:
                e = json.loads(satir)
            except Exception:
                continue
            if e.get('kind') != 'kullan':
                continue
            if (e.get('t') or 0) < t_min:
                continue
            h = e.get('hedef') or '?'
            k = (e.get('komut') or '?').split(':')[-1]
            dg = bool(e.get('dogru'))
            od = float(e.get('odul') or 0) > 0
            toplam += 1
            ok += dg
            hedef[h] += 1
            mat[(h, k)][0] += 1
            mat[(h, k)][1] += dg
            mat[(h, k)][2] += od
print('restart sonrasi kullan denemesi: %d  dogru: %d (%.1f%%)'
      % (toplam, ok, 100.0 * ok / max(1, toplam)))
print('')
print('hedef tipi dagilimi:')
for h, n in hedef.most_common():
    print('  %-14s %6d' % (h, n))
print('')
yeni = ('DOSYA_OLC', 'PAKET_VERSIYON')
print('yeni tipler:')
for h in yeni:
    satirlar = [(k, v) for (hh, k), v in mat.items() if hh == h]
    den = sum(val[0] for _, val in satirlar)
    dgr = sum(val[1] for _, val in satirlar)
    kapilar = {k: '%d/%d' % (val[1], val[0]) for k, val in satirlar}
    print('  %-14s deneme:%5d dogru:%5d  kapilar: %s'
          % (h, den, dgr, kapilar))
print('')
print('hedef x komut — hic odul URETMEYEN (gercek olu alan;')
print('  zincir ara adimlari ILERLEME kazandigindan olu sayilmaz):')
olu_toplam = 0
for h in sorted(hedef):
    oluler = []
    for (hh, kk), (den, dg, od) in mat.items():
        if hh == h and od == 0:
            oluler.append('%s(%d)' % (kk, den))
    if oluler:
        oluler.sort()
        olu_toplam += len(oluler)
        print('  %-14s olu: %s' % (h, ', '.join(oluler)))
print('')
print('toplam olu (hedef,komut) kombinasyonu: %d' % olu_toplam)
