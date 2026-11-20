import json
from collections import Counter
c=Counter()
with open("journal.jsonl") as f:
    for l in f:
        l=l.strip()
        if not l: continue
        try: r=json.loads(l)
        except: continue
        if r.get("kind")=="act": c[r.get("action")]+=1
print("=== SON EYLEMLER (tum journal, ilk 20) ===")
for a,n in c.most_common(20):
    print(f"{a:<40} {n}")
print("\nToplam farkli eylem:", len(c))