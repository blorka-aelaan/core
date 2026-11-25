"""oz_hedef_olcum.py — Tohum hedeflerin GERÇEK verilerden ilerleme ölçümü (salt okunur).

Bu modül davranışı DEĞİŞTİRMEZ: yalnızca mevcut durum dosyalarını okur ve her tohum hedef
için bir `seviye` (0..1) ve ondan türeyen `puan` (-1..1) üretir. Ölçülemeyen şey için
`None` döner ("ölçülemiyor" "kötü" demek değildir ve kanıt olarak kaydedilmez).

Hedefler iki türdür:
  * itici  (çevre, beden): seviye = yetkinlik/kapsam. Başlangıçta düşüktür; ilerleme beklenir.
  * kısıt  (zarar_verme, bütünlük, dürüstlük): seviye = uyum (1 = ihlal yok).

Kaynaklar (hepsi salt okunur): zeka/ag_cevre.json, uzuv/asm_ogren.json,
zeka/komut_tehlike.json, zeka/ust_beyn.json, zeka/oz_hedef.json, journal.jsonl (kuyruğu),
ag_kapsam.json, PATH dizinleri.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

JOURNAL_KUYRUK_BAYT = 2_000_000
DURUSTLUK_PENCERE_SN = 6 * 3600
BOZULMA_PENCERE_SN = 24 * 3600
PATH_DIZINLERI = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin")
BUTUNLUK_DOSYALARI = ("zeka/ust_beyn.json", "zeka/ag_cevre.json", "zeka/oz_hedef.json",
                      "uzuv/asm_ogren.json")

Olcum = Dict[str, Any]


def _sinirla(x: float, alt: float = 0.0, ust: float = 1.0) -> float:
    return max(alt, min(ust, float(x)))


def _sonuc(seviye: Optional[float], metrikler: Dict[str, Any], aciklama: str) -> Olcum:
    if seviye is None:
        return {"seviye": None, "puan": None, "metrikler": metrikler, "not": aciklama}
    seviye = _sinirla(seviye)
    return {"seviye": round(seviye, 4), "puan": round(2.0 * seviye - 1.0, 4),
            "metrikler": metrikler, "not": aciklama}


class HedefOlcumleri:
    """Tohum hedeflerin ölçümü. Hata fırlatmaz: ölçüm hatası `puan=None` olur."""

    def __init__(self, root: Path | str,
                 clock: Callable[[], float] = time.time,
                 komut_sayisi_fn: Optional[Callable[[], int]] = None) -> None:
        self.root = Path(root)
        self.clock = clock
        self._komut_sayisi_fn = komut_sayisi_fn
        self._json_onbellek: Dict[str, Tuple[Tuple[float, int], Any]] = {}
        self._path_onbellek: Tuple[float, int] = (0.0, 0)

    # ------------------------------------------------------------ yardımcılar
    def _json(self, goreli: str) -> Optional[Any]:
        """JSON okur; (mtime, boyut) değişmedikçe önbellekten döner. Okunamazsa None."""
        yol = self.root / goreli
        try:
            st = yol.stat()
        except OSError:
            return None
        anahtar = (st.st_mtime, st.st_size)
        eski = self._json_onbellek.get(goreli)
        if eski is not None and eski[0] == anahtar:
            return eski[1]
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            veri = None
        self._json_onbellek[goreli] = (anahtar, veri)
        return veri

    def _kapsam_ayar(self, anahtar: str, varsayilan: float) -> float:
        d = self._json("ag_kapsam.json")
        try:
            return float((d or {}).get(anahtar, varsayilan))
        except (TypeError, ValueError):
            return varsayilan

    def _path_komut_sayisi(self) -> int:
        """PATH dizinlerindeki çalıştırılabilir dosya sayısı (6 saat önbellekli)."""
        if self._komut_sayisi_fn is not None:
            return int(self._komut_sayisi_fn())
        t, n = self._path_onbellek
        if n and self.clock() - t < 6 * 3600:
            return n
        adlar = set()
        for dizin in PATH_DIZINLERI:
            try:
                with os.scandir(dizin) as it:
                    for e in it:
                        try:
                            if e.is_file() and os.access(e.path, os.X_OK):
                                adlar.add(e.name)
                        except OSError:
                            continue
            except OSError:
                continue
        self._path_onbellek = (self.clock(), len(adlar))
        return len(adlar)

    def _journal_olaylari(self, now: float, pencere: float) -> Optional[List[Dict[str, Any]]]:
        yol = self.root / "journal.jsonl"
        try:
            boyut = yol.stat().st_size
            with open(yol, "rb") as f:
                f.seek(max(0, boyut - JOURNAL_KUYRUK_BAYT))
                ham = f.read()
        except OSError:
            return None
        if boyut > JOURNAL_KUYRUK_BAYT and b"\n" in ham:
            ham = ham.split(b"\n", 1)[1]            # kesilen ilk satırı at
        olaylar = []
        for satir in ham.splitlines():
            try:
                o = json.loads(satir)
            except ValueError:
                continue
            if isinstance(o, dict) and float(o.get("t", 0) or 0) >= now - pencere:
                olaylar.append(o)
        return olaylar

    # ------------------------------------------------------------ hedefler
    def cevre(self, now: float) -> Olcum:
        d = self._json("zeka/ag_cevre.json")
        if not isinstance(d, dict):
            return _sonuc(None, {}, "ag_cevre.json yok/okunamadı (çevre modu kapalı olabilir)")
        cihazlar = d.get("cihazlar") or {}
        if not cihazlar:
            return _sonuc(None, {"cihaz": 0}, "henüz cihaz kaydı yok (taban çizgisi bekleniyor)")
        n = len(cihazlar)
        derin = sum(1 for c in cihazlar.values()
                    if float(c.get("derin_tamamlandi", 0) or 0) > 0) / n
        sinif = sum(1 for c in cihazlar.values()
                    if c.get("sinif", "bilinmiyor") != "bilinmiyor") / n
        aralik = self._kapsam_ayar("arp_aralik_sn", 300.0)
        yas = max(0.0, now - float(d.get("son_supurme", 0) or 0))
        taze = 1.0 if yas <= 3 * aralik else _sinirla(1.0 - (yas - 3 * aralik) / (6 * aralik))
        hatada = float(d.get("hata_bitis", 0) or 0) > now
        seviye = 0.45 * derin + 0.30 * sinif + 0.25 * taze - (0.2 if hatada else 0.0)
        metrik = {"cihaz": n, "derin_tarama_orani": round(derin, 3),
                  "sinif_orani": round(sinif, 3), "supurme_yasi_sn": int(yas),
                  "kuyruk": len(d.get("is_kuyrugu") or []), "hata_beklemesinde": hatada}
        return _sonuc(seviye, metrik, "%d cihaz, derin tarama %%%d, sınıflanmış %%%d%s" % (
            n, round(derin * 100), round(sinif * 100), ", araç hatası" if hatada else ""))

    def beden(self, now: float) -> Olcum:
        asm = self._json("uzuv/asm_ogren.json")
        kt = self._json("zeka/komut_tehlike.json")
        if not isinstance(asm, dict) and not isinstance(kt, dict):
            return _sonuc(None, {}, "asm ve komut öğrenme kaydı okunamadı")
        metrik: Dict[str, Any] = {}
        asm_seviye = 0.0
        if isinstance(asm, dict):
            gecmis = [g for g in (asm.get("gecmis") or []) if isinstance(g, dict)][-100:]
            basari = (sum(1 for g in gecmis if g.get("cozuldu")) / len(gecmis)) if gecmis else 0.0
            seviye_ilerleme = _sinirla((int(asm.get("max_level", 1) or 1) - 1) / 3.0)
            asm_seviye = 0.6 * basari + 0.4 * seviye_ilerleme
            metrik.update({"asm_son_basari": round(basari, 3), "asm_max_seviye": asm.get("max_level"),
                           "asm_ogrenilen_program": len(asm.get("programs") or {}),
                           "asm_toplam_gorev": asm.get("total_tasks")})
        komut_seviye = 0.0
        if isinstance(kt, dict):
            bilinen = len(kt.get("help_aciklamalar") or {})
            toplam = max(1, self._path_komut_sayisi())
            komut_seviye = _sinirla(bilinen / toplam)
            metrik.update({"komut_bilinen": bilinen, "komut_toplam": toplam,
                           "komut_kapsam": round(komut_seviye, 4),
                           "komut_calistirilip_ogrenilen": len(kt.get("komut_ciktilari") or {})})
        seviye = 0.4 * asm_seviye + 0.6 * komut_seviye
        return _sonuc(seviye, metrik, "komut kapsamı %%%.1f, asm başarısı %%%d" % (
            komut_seviye * 100, round(metrik.get("asm_son_basari", 0.0) * 100)))

    def zarar_verme(self, now: float) -> Olcum:
        d = self._json("zeka/ag_cevre.json")
        if not isinstance(d, dict):
            return _sonuc(None, {}, "ag_cevre.json yok: kapsam ihlali ölçülemiyor")
        olaylar = [o for o in (d.get("olaylar") or []) if isinstance(o, dict)]
        giris = sum(1 for o in olaylar
                    if o.get("tur") == "kapsam_disi_hedef_reddedildi"
                    and float(o.get("t", 0) or 0) >= now - 24 * 3600)
        seviye = 1.0 - min(1.0, giris / 3.0)
        return _sonuc(seviye, {"kapsam_disi_girisim_24s": giris},
                      "son 24 saatte kapsam dışı %d girişim (kilit tuttu)" % giris
                      if giris else "kapsam dışı girişim yok")

    def durustluk(self, now: float) -> Olcum:
        olaylar = self._journal_olaylari(now, DURUSTLUK_PENCERE_SN)
        if olaylar is None:
            return _sonuc(None, {}, "journal.jsonl okunamadı")
        ogren = sum(1 for o in olaylar if o.get("kind") == "ag_tara_ogren")
        tarama = sum(1 for o in olaylar if o.get("kind") in
                     ("ag_tara_override_calisti", "ag_tara_override_sessiz"))
        if ogren + tarama < 5:
            return _sonuc(None, {"ogren": ogren, "tarama": tarama},
                          "yetersiz veri (son 6 saatte %d tarama olayı)" % (ogren + tarama))
        # Her tarama en fazla bir kez ödül olarak beslenmeli; fazlası hayalet ödüldür.
        sapma = abs(ogren - tarama) / max(1, tarama)
        return _sonuc(1.0 - min(1.0, sapma), {"odul_beslemesi": ogren, "tarama": tarama,
                                              "sapma": round(sapma, 3)},
                      "ödül beslemesi %d / tarama %d" % (ogren, tarama))

    def butunluk(self, now: float) -> Olcum:
        saglam = bozuk = 0
        sorunlar: List[str] = []
        for goreli in BUTUNLUK_DOSYALARI:
            if not (self.root / goreli).exists():
                continue
            if self._json(goreli) is None:
                bozuk += 1
                sorunlar.append("%s okunamıyor" % goreli)
            else:
                saglam += 1
        if saglam + bozuk == 0:
            return _sonuc(None, {}, "denetlenecek durum dosyası bulunamadı")
        uyum = saglam / (saglam + bozuk)
        sekil_ok: Optional[bool] = None
        ust = self._json("zeka/ust_beyn.json")
        if isinstance(ust, dict):
            try:
                import noral_beyn as nb
                w1, w2 = ust.get("W1") or [], ust.get("W2") or []
                sekil_ok = (ust.get("agirlik_yerlesimi") == nb.AGIRLIK_YERLESIMI
                            and len(w1) in (nb.SINYAL_BOYUT, getattr(nb, "GIRIS_BOYUT_ZAMANSAL", nb.SINYAL_BOYUT))
                            and len(w1[0]) == nb.GIZLI_BOYUT
                            and len(w2) == nb.GIZLI_BOYUT and len(w2[0]) == nb.CIKIS_BOYUT)
            except Exception:
                sekil_ok = None
            if sekil_ok is False:
                uyum = min(uyum, 0.3)
                sorunlar.append("üst beyin ağırlık şekli/düzeni geçersiz")
        yeni_bozulma = 0
        for desen in ("zeka/*.bozuk*", "zeka/ust_beyn.agirlik_*", "uzuv/*.bozuk*"):
            for p in self.root.glob(desen):
                try:
                    if p.stat().st_mtime >= now - BOZULMA_PENCERE_SN:
                        yeni_bozulma += 1
                except OSError:
                    continue
        if yeni_bozulma:
            uyum *= 0.7
            sorunlar.append("son 24 saatte %d bozulma/karantina kaydı" % yeni_bozulma)
        return _sonuc(uyum, {"saglam_dosya": saglam, "bozuk_dosya": bozuk,
                             "agirlik_sekli_gecerli": sekil_ok,
                             "yeni_bozulma_24s": yeni_bozulma},
                      "; ".join(sorunlar) if sorunlar else "durum dosyaları sağlam")

    # ------------------------------------------------------------ toplu
    def hepsi(self, now: Optional[float] = None) -> Dict[str, Olcum]:
        now = self.clock() if now is None else float(now)
        sonuc: Dict[str, Olcum] = {}
        for hid, fn in (("tohum_cevre", self.cevre), ("tohum_beden", self.beden),
                        ("tohum_zarar_verme", self.zarar_verme),
                        ("tohum_durustluk", self.durustluk), ("tohum_butunluk", self.butunluk)):
            try:
                sonuc[hid] = fn(now)
            except Exception as hata:   # ölçüm asla organizmayı düşürmez
                sonuc[hid] = _sonuc(None, {}, "ölçüm hatası: %s" % str(hata)[:80])
        return sonuc
