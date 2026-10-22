import json

d = json.load(open('zeka/brain.json'))
ls = d['links']
zayif = [l for l in ls if abs(l[2]) < 0.02]
print('toplam link:', len(ls))
print('zayif (|w|<0.02):', len(zayif))
print('guclu (|w|>=0.02):', len(ls) - len(zayif))
kuc = sorted(ls, key=lambda l: abs(l[2]))[:5]
print('en zayif 5:', [(round(abs(l[2]), 5), l[0], l[1]) for l in kuc])
print('en guclu 3:', [(round(l[2], 3), l[0], l[1])
                     for l in sorted(ls, key=lambda l: -abs(l[2]))[:3]])
