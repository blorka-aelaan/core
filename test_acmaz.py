"""Açmaz koruması (Sahne 2b canlısı) — refleks aşırı-tekrar kaçışı.

Kontroller:
1) sayim kolunda refleks REFLEKS_ESIK turda bir serbest banda bırakır
   (ritim: 7 bak : 1 kaçış)
2) kaçış kararı sayımın kendisinden gelir (en az denenmiş iş)
3) dünya onarılınca sabır sayacı sıfırlanır
4) eski/yok ölçüm kolları kaçıştan muaf (ölçüm tekrarlanabilirliği)
5) uçtan uca: kilitli dünya (12 bozuk, araç yok) → kaçış → kur →
   araç doğar → guc devreye girer → bozuk sayısı düşer
   (canlı 8.5 saatlik "bak" kilitinin çözüm zinciri)
6) tasi öneki BİR KEZ (grup_grup_x yok); ham hedef kalmayınca no-op
   sayıma girmez (keşif şişmesi/kitlenmesi yok)
7) kota dolu yarat no-op sayılmaz; hayalet (dosyasız) kayıt temizliği
   .durum.json'a yazılır — sahte doluluk yeniden açılışta geri gelmez
8) kur: parça içerikleri TAM korunur ([:400] kesik yok), kuvvet =
   GERÇEK korunan bayt/64 (bedava/ertelenmiş malzeme kuvveti yok)
9) bak onarımı malzemeyi kesmez (eski [:80] yıkımı yok) — guc ile
   aynı tam tur, yazım hatası eylemi çökertmez
10) merak sürprizi = Δ − E[Δ|eylem]: eylemin öğrenilmiş beklenen
   değişiminden sapma; tekrarlanabilir eylem sürpriz üretmez ve
   tahmin modeli .beklenen.json'da kalıcıdır
"""
import sys, tempfile, shutil, json
sys.path.insert(0, "/home/emrah/Genel/core")
from atolye import Atolye


class J:
    def log(self, *a, **k):
        pass


def kilitli(politika=None, adet=12, icerik="x" * 200):
    td = tempfile.mkdtemp()
    a = Atolye(td, J()) if politika is None else Atolye(td, J(),
                                                        politika=politika)
    while len(a.nesneler) < adet:
        a.eylem("yarat", icerik)
    for adx in list(a.nesneler):
        a.nesneler[adx]["bozuk"] = True
    return td, a


# 1) ritim: 7 bak + 1 kaçış (eşik 8) — kaçışlar 8. ve 16. turda
td, a = kilitli()
sonuclar = [a.sec_is() for _ in range(16)]
kacis = [i for i, s in enumerate(sonuclar) if s != "bak"]
assert kacis == [7, 15], (kacis, sonuclar)
assert all(sonuclar[i] in ("tasi", "yarat", "kur") for i in kacis)
assert sonuclar.count("bak") == 14, sonuclar
print("1 ritim (7 bak : 1 kaçış) OK")

# 2) kaçış kararı sayımdan: kur en az denenmiş → kaçış = kur
td, a = kilitli()
a.is_say = {"tasi": 9, "yarat": 9, "kur": 1}
for _ in range(7):
    a.sec_is()
assert a.sec_is() == "kur", a.sec_is()
assert a.refleks_ust == 0, a.refleks_ust      # kaçıştan sonra sıfır
print("2 kaçış sayimdan (kur min → kur) OK")

# 3) dünya onarıldı → sabır sayacı sıfırla
for adx in list(a.nesneler):
    a.nesneler[adx]["bozuk"] = False
a.sec_is()
assert a.refleks_ust == 0, a.refleks_ust
print("3 saglikta sayaç sıfır OK")

# 4) eski/yok kolları kaçıştan muaf (12 tur refleks, sayaç işlemez)
for kol in ("eski", "yok"):
    td, a = kilitli(kol)
    for _ in range(12):
        assert a.sec_is() in ("bak", "guc", "kur"), (kol, a.sec_is())
    assert a.refleks_ust == 0, (kol, a.refleks_ust)
print("4 eski/yok muaf OK")

# 5) uçtan uca: kilit → (kaçış) → kur → araç → guc → onarım
td, a = kilitli()
arac_dogdu = None
bozuk_ilk = sum(1 for v in a.nesneler.values() if v.get("bozuk"))
for tur in range(80):
    a.eylem(a.sec_is())
    arac = [x for x, v in a.nesneler.items()
            if v.get("tur") == "arac" and v.get("kuvvet", 0) > 0
            and not v.get("bozuk")]
    if arac and arac_dogdu is None:
        arac_dogdu = tur
    if arac_dogdu is not None and not any(v.get("bozuk")
                                          for v in a.nesneler.values()):
        break
assert arac_dogdu is not None, "araç hiç doğmadı (kaçış zinciri kırık)"
geri = sum(1 for v in a.nesneler.values() if v.get("bozuk"))
assert geri < bozuk_ilk, (geri, bozuk_ilk)
print("5 uçtan uca: kilit→kur→arac(tur %d)→onarim (geri %d/%d) OK"
      % (arac_dogdu, geri, bozuk_ilk))

# 6) tasi öneki bir kez + kapalı kapı no-op sayılmaz (düzeltilen madde 1-2)
td, a = kilitli(adet=4, icerik="y" * 100)
for _ in range(10):
    a.eylem("tasi")
ads = list(a.nesneler)
assert not any(ad.startswith("grup_grup_") for ad in ads), ads
assert all(ad.startswith("grup_") for ad in ads), ads   # 4 ham → 4 grup
onc = a.is_say.get("tasi", 0)
assert onc == 4, ("no-op sayıma girdi", a.is_say)        # 6 no-op sayılmadı
res = a.eylem("tasi")
assert res.get("bos") and a.is_say.get("tasi", 0) == onc, (res, a.is_say)
print("6 tasi önek bir kez + no-op sayılmaz OK")

# 7) kota no-op sayılmaz + hayalet temizliği diske (madde 2 + yarat notu)
td, a = kilitli(adet=24, icerik="z" * 50)      # KOTA tam dolu
onc = a.is_say.get("yarat", 0)
res = a.eylem("yarat", "dolu")
assert res.get("bos") and "dolu" in res["obs"], res
assert a.is_say.get("yarat", 0) == onc, a.is_say
a.nesneler["hayalet_x"] = {"son_bakim": 0, "bozuk": False}  # dosyasız kayıt
res = a.eylem("yarat", "yine dolu")
assert res.get("bos"), res                                  # 24 gerçek → dolu
durum = json.load(open(a.kok / ".durum.json", encoding="utf-8"))
assert "hayalet_x" not in durum, "hayalet temizliği diske yazılmadı"
print("7 kota no-op sayılmaz + hayalet diske OK")

# 8) kur malzeme dürüstlüğü: TAM içerik + kuvvet = gerçek bayt/64
td, a = kilitli(adet=0)
a.eylem("yarat", "a" * 300)   # toplam 610 bayt > eski [400] kesiti
a.eylem("yarat", "b" * 310)
a.eylem("kur")
arac_ad = [x for x, v in a.nesneler.items() if v.get("tur") == "arac"]
assert len(arac_ad) == 1, a.nesneler
icerik = (a.kok / arac_ad[0]).read_text(encoding="utf-8")
assert icerik == "a" * 300 + "b" * 310, (len(icerik), icerik[:30])
kv = a.nesneler[arac_ad[0]]["kuvvet"]
assert kv == max(1, len(icerik.encode("utf-8")) // 64), kv
print("8 kur: tam malzeme + dürüst kuvvet (%d) OK" % kv)

# 9) bak onarımı malzemeyi korur (eski [:80] yıkımı yok)
td, a = kilitli(adet=1)
ad = next(iter(a.nesneler))
(a.kok / ad).write_text("m" * 300, encoding="utf-8")
a.nesneler[ad]["bozuk"] = True
res = a.eylem("bak")
assert not a.nesneler[ad]["bozuk"], res
assert (a.kok / ad).stat().st_size == 300, (a.kok / ad).stat().st_size
print("9 bak malzeme korur (300 bayt → 300 bayt) OK")

# 10) merak = Δ − E[Δ|eylem]: tekrar sürpriz üretmez; model kalıcı
#     (boyut vektorü bayt//64 ölçeklidir — Δ sabit olsun diye 64'ün katı)
td, a = kilitli(adet=0)
ilk = a.eylem("yarat", "t" * 128)
ikinci = a.eylem("yarat", "t" * 128)
assert ilk["surpriz"] > 0 and ilk["merak"] > 0, ilk
assert ikinci["surpriz"] == 0 and ikinci["merak"] == 0, ikinci
a2 = Atolye(td, J())      # .beklenen.json yeniden yüklenir (kalıcı tahmin)
assert a2.beklenen.get("yarat", {}).get("say") == 2, a2.beklenen
print("10 merak = Δ − E[Δ|eylem] (kalıcı model) OK")

# 11) hayalet döngü koruması (2026-10-19 canlı dersi): dosyası silinmiş
#     ama kaydı kalmış "bozuk" nesneler sec_is'i sonsuz guc no-op'una
#     kilitlemişti (151 dk, 82 olay/15dk). Hayaletler karar ÖNCESİ
#     temizlenir; guc asla var olmayan bozuk onarmaya çıkmaz.
td, a = kilitli(adet=6)
hayalet_adlari = list(a.nesneler)[:3]   # 3 nesnenin dosyasını sil
for hx in hayalet_adlari:
    (a.kok / hx).unlink()
# bellek-kayıt hâlâ "bozuk" (çift-süreç izi gibi) — disk temizliği bekler
assert all(a.nesneler[h].get("bozuk") for h in hayalet_adlari)
kararlar = [a.sec_is() for _ in range(12)]
assert "guc" not in kararlar, kararlar   # hayalet bozuk guc'a sürükleyemez
assert all(hx not in a.nesneler for hx in hayalet_adlari), a.nesneler.keys()
assert len(a.nesneler) == 3, a.nesneler  # kalan 3 sağlam kayıt duruyor
# kalan saglam kayitlar bozuk → bak refleksi devrede (döngü değil, iş)
assert kararlar[-1] == "bak", kararlar
shutil.rmtree(td, ignore_errors=True)
print("11 hayalet döngü koruması: guc kilitlenmesi yok OK")

shutil.rmtree(td, ignore_errors=True)
print("ACMAZ + ATOLYE 5 MADDE: 11/11 OK")