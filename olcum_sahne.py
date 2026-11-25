import json, sys, tempfile, statistics as st, random, collections
from pathlib import Path
sys.path.insert(0,'.')
import zeka
kok=Path(tempfile.mkdtemp()); (kok/'zeka').mkdir(); zeka.KOK=zeka.KLASOR=kok/'zeka'
import noral_beyn as nb
rows=[]
for l in open('journal.jsonl',encoding='utf-8'):
    try: d=json.loads(l)
    except: continue
    if d.get('kind')=='ust_ogren' and len(d.get('sinyal',[]))==48: rows.append(d)
S=[r['sinyal'] for r in rows]
print("satır",len(rows),"idx dağılımı",collections.Counter(nb.KOMUTLAR[r['idx']] for r in rows).most_common(6))
print("ödül dağılımı",collections.Counter(round(r['odul'],2) for r in rows).most_common(6))
cos=nb.kosinus_benzerligi
rnd=random.Random(1)
pairs=[(rnd.randrange(len(S)),rnd.randrange(len(S))) for _ in range(4000)]
pairs=[(a,b) for a,b in pairs if a!=b]
def rapor(ad,V):
    c=sorted(cos(V[a],V[b]) for a,b in pairs)
    print(f"{ad:18s} medyan {c[len(c)//2]:+.3f}  %5 {c[len(c)//20]:+.3f}  >0.6: {100*sum(x>.6 for x in c)/len(c):5.1f}%  >0.8: {100*sum(x>.8 for x in c)/len(c):5.1f}%")
tr=nb.SahneTakipcisi()
Z=[];D=[];SC=[]
for s in S:
    z,d,sc=tr.guncelle(s); Z.append(z);D.append(d);SC.append(sc)
rapor("ham S",S); rapor("z (Welford)",Z); rapor("sahne [z|Δ]",SC)
# ΔS sessizliği: tek-kare vs EMA farkı, canlı boyutlarda ortalama |.|
canli=[i for i in range(48) if max(s[i] for s in S)-min(s[i] for s in S)>1e-9]
tek=[abs(S[t][i]-S[t-1][i]) for t in range(1,len(S)) for i in canli]
ema=[abs(D[t][i]) for t in range(1,len(S)) for i in canli]
print("canlı boyut",len(canli),"| tek-kare |ΔS| medyan %.2e  p95 %.3f"%(st.median(tek),sorted(tek)[int(.95*len(tek))]),
      "| EMA-fark |Δ| medyan %.3f  p95 %.3f  maks %.2f"%(st.median(ema),sorted(ema)[int(.95*len(ema))],max(ema)))
# bellek + sürpriz tekrarı
u=nb.NöralUstBeyn({}, root=kok, seed=3)
sur=[]
for r in rows:
    u.zamansal_guncelle(r['sinyal']); u.eylem_uygulandi(r['idx']); sur.append((u.son_tahmin_hatasi,u.son_surpriz))
    u.ogren(r['sinyal'], r['idx'], r['odul'])
print("prototip sayısı",len(u.kavram_prototipi),"(eski tasarım: ≤ 12) | toplam sayi",sum(p['sayi'] for p in u.kavram_prototipi))
print("birleşen prototip (sayi>1):",sum(p['sayi']>1 for p in u.kavram_prototipi))
h=[a for a,_ in sur[10:]]; sv=[b for _,b in sur[10:]]
print("tahmin hatası σ: medyan %.2f p90 %.2f maks %.2f | sürpriz[0,1]: medyan %.2f p90 %.2f maks %.2f"%(st.median(h),sorted(h)[int(.9*len(h))],max(h),st.median(sv),sorted(sv)[int(.9*len(sv))],max(sv)))
