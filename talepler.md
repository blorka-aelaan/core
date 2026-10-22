# 📩 Talep Raporu (organizmanın eksik aletleri)

> **talep.py** üretti. **Kurulum YOK** — organizma yalnızca
> ihtiyacını söyler; kurma yetkisi insandadır.

Olusturma: 2026-10-18 22:07:05

## ✅ Onay bekleyen talep yok

## 🟢 Sistemde hazır — BEYAZ'a giriş adayları (kurulum gerekmez, sadece argv+judge gerekir) (2)

| Komut | Hedef | Gerekçe | Judge var? |
|---|---|---|---|
| `traceroute` | AG_SOR | paketin yolunu izle | ❌ önce judge yaz |
| `nload` | AG_SOR | canlı ağ kullanımı | ❌ önce judge yaz |

**Değerlendirme:** 0/2 komut için judge zaten var → bunları BEYAZ'a eklemek tek tek argv builder + judge + test ile aynı gün yapılabilir. Kalan 2 için önce yeni hedef tipi yazılmalı.

---

**Sonraki adım (onaydan sonra):** BEYAZ'a eski yoldan:
`kullan.py BEYAZ` + `_harita()` argv + `_dogrula()` judge + `test_kullan.py`.
