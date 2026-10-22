#!/usr/bin/env python3
"""Atölye decay → onarım zinciri: içerik kaybı GERİ DÖNÜŞSÜZ olmamalı.

Kök neden (2026-10-21): bozulma (decay) dosyayı "?" ile eziyordu.
`bak`/`guc` "onarım"ı diskten okuyup geri yazıyordu → okunan zaten "?"
idi → onarım SAHTEYDI, gerçek içerik kalıcı olarak yok oluyordu
(13 baytlık "?????????" dosyaları).

Düzeltme: bozulma anında orijinal içerik `.yedek/<ad>` altına alınır;
onarım YEDEKTEN yükler. Yedek yoksa ve içerik "?" ise onarım YAPILMAZ
(uydurma iyileşme yok) — nesne bozuk kalır.

Çalıştırma: python3 test_atolye_onarim.py
"""
import shutil
import sys
import tempfile

sys.path.insert(0, "/home/emrah/Genel/core")
from atolye import Atolye


class J:
    def log(self, *a, **k):
        pass


hata = []


def kontrol(kosul, mesaj):
    if not kosul:
        hata.append(mesaj)
        print("  ✗ %s" % mesaj)


def yeni():
    td = tempfile.mkdtemp()
    return td, Atolye(td, J())


# 1) decay içeriği ezer + orijinal yedeğe alınır
td, a = yeni()
a.eylem("yarat", "KALICI ICERIK " * 20)
ad = next(iter(a.nesneler))
a.tikla(a.tik + a.BOZULMA + 1)
disk = (a.kok / ad).read_text(encoding="utf-8")
kontrol(set(disk) == {"?"}, "decay diski '?' ile ezmeli: %r" % disk[:20])
kontrol(a.nesneler[ad].get("bozuk") is True, "decay bozuk bayrağı koymalı")
yedek = a.yedek_kok / ad
kontrol(yedek.exists(), "orijinal içerik yedeğe alınmalı")
kontrol(yedek.read_text(encoding="utf-8").startswith("KALICI ICERIK"),
        "yedek orijinal içeriği taşımalı")
print("1 decay + yedek alımı OK")

# 2) bak onarımı YEDEKTEN yükler → içerik birebir geri gelir
a.eylem("bak")
sonra = (a.kok / ad).read_text(encoding="utf-8")
kontrol(sonra.startswith("KALICI ICERIK"), "bak yedekten geri yüklemeli: %r" % sonra[:30])
kontrol(a.nesneler[ad].get("bozuk") is False, "bak bozukluğu kaldırmalı")
kontrol(not yedek.exists(), "onarım sonrası yedek temizlenmeli")
print("2 bak gerçek onarım (içerik geri geldi) OK")

# 3) guc (araçla toplu onarım) de yedekten yükler
td, a = yeni()
a.eylem("yarat", "A" * 200)
a.eylem("yarat", "B" * 200)
a.eylem("yarat", "C" * 200)
a.eylem("kur")            # araç doğar
arac = [x for x, v in a.nesneler.items() if v.get("tur") == "arac"]
kontrol(len(arac) == 1, "araç doğmalı: %s" % a.nesneler)
# yalnız normal nesneler bozulsun (araç bozulursa araç kullanılamaz —
# bu da doğru davranış: bozuk araç onarılamadan kullanamaz)
normal = [x for x in a.nesneler if not a.nesneler[x].get("tur") == "arac"]
for x in normal:
    a.nesneler[x]["son_bakim"] = a.tik - a.BOZULMA - 1
a.tikla(a.tik + 1)
bozuk_adlar = [x for x in normal if a.nesneler[x].get("bozuk")]
kontrol(bozuk_adlar, "normal nesneler bozulmalı")
for x in bozuk_adlar:
    yedek = a.yedek_kok / x
    kontrol(yedek.exists(), "her bozulan nesnenin yedeği olmalı: %s" % x)
a.eylem("guc")
for x in bozuk_adlar:
    ic = (a.kok / x).read_text(encoding="utf-8")
    kontrol(set(ic) != {"?"}, "guc '?' bırakmamalı: %s → %r" % (x, ic[:20]))
    kontrol(a.nesneler[x].get("bozuk") is False, "guc bozukluğu kaldırmalı: %s" % x)
print("3 guc toplu onarımı yedekten OK")

# 4) yedek yoksa + içerik "?" ise onarım YAPILMAZ (uydurma iyileşme)
td, a = yeni()
a.eylem("yarat", "GERI DONUMSUZ")
ad = next(iter(a.nesneler))
(a.kok / ad).write_text("?" * 12, encoding="utf-8")   # eski dünyadan kalma
a.nesneler[ad]["bozuk"] = True
res = a.eylem("bak")
kontrol(a.nesneler[ad].get("bozuk") is True,
        "kurtarılamayan içerik bozuk kalmalı (uydurma onarım yok): %s" % res)
kontrol((a.kok / ad).read_text(encoding="utf-8").startswith("?"),
        "içerik uydurulmamalı")
print("4 kurtarılamayan içerik onarılmaz (dürüst) OK")

# 5) tasi: yedek yeni adla taşınır (onarım kaynağı kaybolmaz)
td, a = yeni()
a.eylem("yarat", "TASI MALZEME " * 10)
a.eylem("yarat", "IKINCI " * 10)
a.tikla(a.tik + a.BOZULMA + 1)
# önce onar (bozuk nesne taşınsa da yedek taşınmalı)
bozuk_adlar = [x for x, v in a.nesneler.items() if v.get("bozuk")]
for x in bozuk_adlar:
    a.nesneler[x]["son_bakim"] = a.tik   # tekrar bozulmasın
a.eylem("tasi")
grup = [x for x in a.nesneler if x.startswith("grup_")]
kontrol(len(grup) == 1, "tasi grup_ yapmalı: %s" % list(a.nesneler))
kontrol((a.yedek_kok / grup[0]).exists(),
        "yedek yeni adla taşınmalı: %s" % grup[0])
# taşınan nesnenin ESKİ adının yedeği kalmamalı (hayalet yedek yok);
# taşınmayan bozuk nesnenin yedeği KALMALI (onarım kaynağı)
kalan = [x for x in bozuk_adlar if x != grup[0].replace("grup_", "", 1)]
kontrol(not (a.yedek_kok / grup[0].replace("grup_", "", 1)).exists(),
        "taşınan nesnenin eski yedeği kalmamalı")
kontrol(all((a.yedek_kok / x).exists() for x in kalan),
        "taşınmayan bozuk nesnenin yedeği kalmalı: %s" % kalan)
print("5 tasi yedeği taşır OK")

# 6) kur: parça yedekleri araca taşınır (araç da bozulabilir)
td, a = yeni()
a.eylem("yarat", "P1 " * 50)
a.eylem("yarat", "P2 " * 50)
a.tikla(a.tik + a.BOZULMA + 1)
a.eylem("kur")
arac = [x for x, v in a.nesneler.items() if v.get("tur") == "arac"]
kontrol(len(arac) == 1, "araç doğmalı: %s" % list(a.nesneler))
kontrol((a.yedek_kok / arac[0]).exists(),
        "aracın yedeği olmalı: %s" % arac[0])
ic = (a.kok / arac[0]).read_text(encoding="utf-8")
kontrol("P1" in ic and "P2" in ic, "araca '?' bulaşmamalı: %r" % ic[:40])
print("6 kur parça yedeklerini araca taşır OK")

# 7) sil: yedek de silinir (hayalet yedek yığılması yok)
td, a = yeni()
a.eylem("yarat", "SIL " * 20)
ad = next(iter(a.nesneler))
a.tikla(a.tik + a.BOZULMA + 1)
kontrol((a.yedek_kok / ad).exists(), "silmeden önce yedek olmalı")
a.eylem("sil")
kontrol(not (a.yedek_kok / ad).exists(), "silinen nesnenin yedeği de silinmeli")
print("7 sil yedeği de temizler OK")

# 8) yedekler .durum.json'a SIZMAZ (web nesne listesini oradan okur)
td, a = yeni()
a.eylem("yarat", "SAYIM " * 20)
a.tikla(a.tik + a.BOZULMA + 1)
durum = a._durum_yukle()
kontrol(len(durum) == 1, ".durum.json yalnız nesne kaydı: %s" % list(durum))
kontrol(all(not k.startswith(".") for k in durum),
        "gizli anahtar sızmamalı: %s" % list(durum))
print("8 .durum.json biçimi bozulmaz OK")

# 9) uçtan uca: decay → onarım → içerik birebir aynı (byte eşitliği)
#    (yarat içeriği 400 bayta keser — kayıtlanan içerik neyse onun
#    birebir geri gelmesi gerekir)
td, a = yeni()
icerik = "X" * 1234 + "son satır"
a.eylem("yarat", icerik)
ad = next(iter(a.nesneler))
beklenen = (a.kok / ad).read_text(encoding="utf-8")
a.tikla(a.tik + a.BOZULMA + 1)
kontrol(set((a.kok / ad).read_text(encoding="utf-8")) == {"?"},
        "decay diski ezmeli")
a.eylem("bak")
kontrol((a.kok / ad).read_text(encoding="utf-8") == beklenen,
        "byte eşitliği: içerik birebir geri gelmeli")
print("9 uçtan uca byte eşitliği OK")

# 10) ÖLÜ NESNE: yedeksiz + "?" içerik → onarım döngüsünü tıkayamaz,
#     sec_is "sil" der (temizlik), "bak" ölüyü seçmez
td, a = yeni()
a.eylem("yarat", "OLMUYOR")
ad = next(iter(a.nesneler))
(a.kok / ad).write_text("?" * 12, encoding="utf-8")
a.nesneler[ad]["bozuk"] = True
a._durum_kaydet()
sec = a.sec_is()
kontrol(sec == "sil",
        "ölü nesne varsa sec_is 'sil' demeli (onarım döngüsü tıkamasın): %s" % sec)
a.eylem("bak")
kontrol(a.nesneler[ad].get("bozuk") is True,
        "bak ölü nesneyi seçmemeli (bozuk kalmalı)")
print("10 ölü nesne onarım döngüsünü tıkayamaz OK")

# 11) Ölü nesne "sil" ile temizlenir (kota açılır)
a.eylem("sil")
kontrol(ad not in a.nesneler, "ölü nesne silinmeli")
kontrol(not (a.kok / ad).exists(), "ölü nesnenin dosyası silinmeli")
print("11 ölü nesne sil ile temizlenir OK")

# 12) ESKİ SAHTE ONARIM İZİ: kayıt "bozuk: false" ama içerik "?" →
#     yükleme denetimi bozuk işaretler (sağlık gerçeği yansıtır)
td = tempfile.mkdtemp()
a = Atolye(td, J())
a.eylem("yarat", "SAHTESIZ")
ad = next(iter(a.nesneler))
(a.kok / ad).write_text("?" * 12, encoding="utf-8")
a.nesneler[ad]["bozuk"] = False
a._durum_kaydet()
b = Atolye(td, J())          # yeniden açılış → denetim
kontrol(b.nesneler[ad].get("bozuk") is True,
        "yükleme denetimi sahte sağlığı bozuk işaretlemeli")
kontrol(b.saglik() == 0.0,
        "saglik sahte onarımı yansıtmamalı: %s" % b.saglik())
print("12 eski sahte onarım izi yüklemede yakalanır OK")

# 13) Bayrak uydurma: kayıt "bozuk: true" ama içerik SAĞLAM →
#     denetim bayrağı düzeltir (malzeme zaten sağlamdı)
td = tempfile.mkdtemp()
a = Atolye(td, J())
a.eylem("yarat", "SAĞLAM İÇERİK")
ad = next(iter(a.nesneler))
a.nesneler[ad]["bozuk"] = True
a._durum_kaydet()
b = Atolye(td, J())
kontrol(b.nesneler[ad].get("bozuk") is False,
        "uydurma bozuk bayrağı düzeltilmeli")
kontrol(b.saglik() == 1.0, "saglik 1.0 olmalı: %s" % b.saglik())
print("13 uydurma bozuk bayrağı düzeltilir OK")

# 14) Ölü nesne onarılabilir listede değil → guc boşa enerji yakmaz
td, a = yeni()
a.eylem("yarat", "A" * 200)
a.eylem("yarat", "B" * 200)
a.eylem("yarat", "C" * 200)
a.eylem("kur")
olu_ad = [x for x, v in a.nesneler.items()
          if v.get("tur") != "arac"][0]
(a.kok / olu_ad).write_text("?" * 5, encoding="utf-8")
a.nesneler[olu_ad]["bozuk"] = True
res = a.eylem("guc")
kontrol("onarılacak bozuk yok" in res.get("obs", ""),
        "guc ölü nesneyi hedef almamalı: %s" % res.get("obs"))
print("14 guc ölü nesneyi hedef almaz OK")

shutil.rmtree(td, ignore_errors=True)

if hata:
    print("\nONARIM TESTLERİ: %d HATA" % len(hata))
    sys.exit(1)
print("\nATOLYE ONARIM (decay→yedek→onarım): 14/14 OK")
