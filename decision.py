"""CORE decision — karar verme ve override mantığı.

main.py'deki karar verme bloğunu ayrıştırır:
  * üst-beyin komut seçimi ve action masking
  * komut uygulanabilirlik kontrolü (guvenlik, cooldown, eşik)
  * feasible eylemi düzenleme (komuta göre kısıtlama / genişletme)
  * öz-hedef (oz_hedef) entegrasyonu
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import noral_beyn as ust_beyn_mod
from ag_cevre import olay_alanlari


class DecisionEngine:
    """Üst-beyin override ve alt-beyin karar motoru."""

    def __init__(
        self,
        ust: ust_beyn_mod.NöralUstBeyn,
        mind: Any,
        oz: Any,
        drives: Any,
        door: Any,
        cfg: Dict[str, Any],
        journal: Any,
        dusun: Any = None,
        ag_beyin: Any = None,
    ) -> None:
        self.ust = ust
        self.mind = mind
        self.oz = oz
        self.drives = drives
        self.door = door
        self.cfg = cfg
        self.journal = journal
        self.dusun = dusun  # Faz 4: durum tahmini için
        self.ag_beyin = ag_beyin  # AgBeyin entegrasyonu (ağ keşif)

        # Override durumu
        self._komut_ust: Optional[str] = ust_beyn_mod.KOMUT_YOK
        self._idx_ust: int = ust_beyn_mod.KOMUT_INDEKSI[ust_beyn_mod.KOMUT_YOK]
        self._guven_ust: float = 0.0
        self._kaynak_ust: str = "model"
        self._reddedildi_ust: bool = False
        self._override_aktif: bool = False
        self._asm_son: Optional[Dict[str, Any]] = None
        self._budanan_ust: int = 0
        self._bag_once_ust: int = 0
        # ag_tara scan sonucu (decision engine tarafından yürütülür)
        self._ag_tara_sonuc: Optional[Dict[str, Any]] = None
        self._ag_tara_calisti: bool = False

    # ------------------------------------------------------------------ override seç

    def sec_override(self, sinyal_vektor: List[float], epsilon: float) -> None:
        """Üst-beyin'den komut seçer ve override durumunu günceller.

        Eşikten düşük güven → KOMUT_YOK (pasif). Reddedilen kararlar
        kaydedilir (kilitlenme kırıcı için).
        """
        # DÜZELTME (bayat ödül): ag_tara sonucu yalnızca BU tikte gerçekten
        # tarama yapıldıysa geçerlidir. Sıfırlanmadığında bayrak sonsuza dek
        # True kalıyor ve organism.py her tikte eski ödülü üst beyne yeniden
        # besliyordu (journal: 5997 besleme / 4034 gerçek tarama).
        self._ag_tara_sonuc = None
        self._ag_tara_calisti = False

        komut, idx, guven, kaynak = self.ust.sec(
            sinyal_vektor, epsilon=epsilon
        )
        self._komut_ust = komut
        self._idx_ust = idx
        self._guven_ust = guven
        self._kaynak_ust = kaynak

        # Güven eşiği kontrolü
        uygulanabilir = self.ust.komut_uygulanabilir_mi(
            idx, guven, kaynak
        )

        if not uygulanabilir:
            self._reddedildi_ust = True
            self._komut_ust = ust_beyn_mod.KOMUT_YOK
            self._idx_ust = ust_beyn_mod.KOMUT_INDEKSI[ust_beyn_mod.KOMUT_YOK]
            self._override_aktif = False
        else:
            self._reddedildi_ust = False
            self._override_aktif = komut != ust_beyn_mod.KOMUT_YOK
            if self._override_aktif:
                self.ust.komut_ayarla(komut, idx, sure=3)
                self._kopru_bildir(komut, idx, kaynak)
                # ag_tara override'ı: gerçek tarama adımını ag_beyin üzerinden yürüt
                if komut == ust_beyn_mod.KOMUT_AG_TARA and self.ag_beyin is not None:
                    try:
                        # Ödül, kararı seçtiren bağlamda öğrensin (sıfır vektörde değil)
                        _kaydet = getattr(self.ust, "scan_sinyali_kaydet", None)
                        if callable(_kaydet):
                            _kaydet(sinyal_vektor)
                        sonuc = self.ag_beyin.scan_next_step(time.time())
                        self._ag_tara_sonuc = sonuc
                        self._ag_tara_calisti = sonuc is not None and sonuc.get("ok", False)
                        if self._ag_tara_calisti:
                            self.journal.log(
                                "ag_tara_override_sessiz"
                                if sonuc.get("noop") else "ag_tara_override_calisti",
                                step=sonuc.get("step"),
                                probe=sonuc.get("probe"),
                                hosts=sonuc.get("hosts"),
                                ports=sonuc.get("ports"),
                                reward=sonuc.get("probe_reward", 0.0),
                            )
                        for olay in (sonuc or {}).get("olaylar", []):
                            self.journal.log("ag_cevre_olay", **olay_alanlari(olay))
                    except Exception as e:
                        self._ag_tara_sonuc = None
                        self._ag_tara_calisti = False
                        self.journal.log("ag_tara_override_hata", hata=str(e)[:200])

    def _kopru_bildir(self, komut: str, idx: int, kaynak: str) -> None:
        """Öz hedef köprüsüne seçimi bildirir (soğuma) ve hedef etkisi varsa günlükler."""
        kopru = getattr(self.ust, "hedef_kopru", None)
        if kopru is None:
            return
        try:
            kb = getattr(self.ust, "last_hedef_kopru", None) or {}
            etki = kb.get(idx)
            kopru.secim_bildir(komut)
            if etki:
                self.journal.log("oz_hedef_kopru", komut=komut, bias=round(float(etki), 4),
                                 kaynak=kaynak, **{"etkenler": kopru.aciklama(komut).get("etkenler", [])})
        except Exception as hata:
            self.journal.log("oz_hedef_kopru_hata", hata=str(hata)[:200])

    # ------------------------------------------------------------------ feasible düzenle

    def duzenle_feasible(
        self,
        sinyal_vektor: str,
        feasible: List[str],
        act: str,
    ) -> Tuple[List[str], str]:
        """Komuta göre feasible listesini düzenler ve eylemi döndürür.

        Döner: (guncellenmis_feasible, secilen_act)
        """
        komut = self._komut_ust

        if komut == ust_beyn_mod.KOMUT_KAPAT_AG:
            feasible = [
                a for a in feasible
                if a not in ("console", "atolye", "katalogla", "nedir", "konum")
            ]
        elif komut == ust_beyn_mod.KOMUT_KISITLA_DOSYA:
            feasible = [
                a for a in feasible
                if a not in ("console", "atolye", "katalogla", "nedir", "konum", "birak")
            ]
        elif komut == ust_beyn_mod.KOMUT_KOD_DUZENLE:
            kd = "atolye:kod_duzenle|brain.py|# Organizma kendi kodunu duzenledi (Aşama 4)\\n"
            if kd not in feasible:
                feasible.append(kd)
        elif komut == ust_beyn_mod.KOMUT_GUVENLI_MOD:
            guvenli = ["wander", "eat", "rest", "sense_self", "nest"]
            feasible = [a for a in feasible if a in guvenli]
        elif komut == ust_beyn_mod.KOMUT_ACIL_YEM:
            # Acil yem override: 'eat' eylemini zorla (food varsa)
            if "eat" in feasible:
                return feasible, "eat"

        # Özhedef entegrasyonu
        oz_h = self.oz.mevcut_hedef()
        if oz_h and oz_h.get("tip") == "novel_eylem":
            eylem = oz_h.get("eylem")
            if eylem and eylem not in feasible:
                feasible.append(eylem)
                self.journal.log("oz_hedef_eklendi", **oz_h)

        # Eylem seçimi
        act = self.mind.decide(sinyal_vektor, feasible) if feasible else "rest"

        # Özhedef tüketimi
        if oz_h and oz_h.get("tip") == "novel_eylem" and oz_h.get("eylem") == act:
            self.oz.hedef_secildi(act)

        # Faz 4: tahmine dayalı tehlike filtresi
        # Eğer bir eylemin sonraki durumu tehlike getireceği tahmin ediliyorsa,
        # o eylemi feasible listesinden çıkar (en az alternatives varsa).
        feasible = self._filtrele_tehlikeli_feasible(
            sinyal_vektor, feasible
        )

        return feasible, act

    # ------------------------------------------------- Faz 4: tehlike filtresi

    def _filtrele_tehlikeli_feasible(
        self, sinyal_vektor: str, feasible: List[str]
    ) -> List[str]:
        """Tahmin edilen sonraki durum tehlikeli olan eylemleri çıkar.

        Tehlikeli: sonraki bağlamın düşük enerji (L) veya yüksek açlık (A)
        olması. Eğer tüm eylemler tehlikeliyse, liste boşalmayıp en az
        bir eylem tutulur (hiçbir şey yapmak daha kötü olabilir).
        """
        if self.dusun is None or not feasible:
            return feasible

        filtered = []
        tehlikeli_eylemler = []

        for act in feasible:
            tehlike, _aciklama = self.dusun.tehlike_tahmini(
                sinyal_vektor, act, self.drives
            )
            if tehlike is not None and tehlike >= 0.5:
                tehlikeli_eylemler.append(act)
            else:
                filtered.append(act)

        # Hiçbiri güvenli değilse, orijinal listeyi dön (hiç yapmak peor)
        if not filtered and feasible:
            self.journal.log(
                "tahmin_tum_tehlikeli",
                eylemler=tehlikeli_eylemler[:5],
            )
            return feasible

        if tehlikeli_eylemler:
            self.journal.log(
                "tahmin_tehlike_filtresi",
                cikarilan=tehlikeli_eylemler[:5],
                kalan=len(filtered),
            )

        return filtered

    # ------------------------------------------------------------------ komut yönetimi

    def komut_baslat(self, komut: str, idx: int) -> None:
        """Override komutunu başlatır (3 tiklik ömür)."""
        self._komut_ust = komut
        self._idx_ust = idx
        self._override_aktif = komut != ust_beyn_mod.KOMUT_YOK
        if self._override_aktif:
            self.ust.komut_ayarla(komut, idx, sure=3)

    def komut_sifirla(self) -> None:
        """Override'ı temizler."""
        self._komut_ust = ust_beyn_mod.KOMUT_YOK
        self._idx_ust = ust_beyn_mod.KOMUT_INDEKSI[ust_beyn_mod.KOMUT_YOK]
        self._override_aktif = False

    # ------------------------------------------------------------------ erişiciler

    @property
    def komut_ust(self) -> Optional[str]:
        return self._komut_ust

    @property
    def idx_ust(self) -> int:
        return self._idx_ust

    @property
    def guven_ust(self) -> float:
        return self._guven_ust

    @property
    def kaynak_ust(self) -> str:
        return self._kaynak_ust

    @property
    def reddedildi_ust(self) -> bool:
        return self._reddedildi_ust

    @property
    def override_aktif(self) -> bool:
        return self._override_aktif

    @property
    def asm_son(self) -> Optional[Dict[str, Any]]:
        return self._asm_son

    @asm_son.setter
    def asm_son(self, deger: Optional[Dict[str, Any]]) -> None:
        self._asm_son = deger

    @property
    def ag_tara_sonuc(self) -> Optional[Dict[str, Any]]:
        return self._ag_tara_sonuc

    @property
    def ag_tara_calisti(self) -> bool:
        return self._ag_tara_calisti

    @property
    def budanan_ust(self) -> int:
        return self._budanan_ust

    @budanan_ust.setter
    def budanan_ust(self, deger: int) -> None:
        self._budanan_ust = deger

    @property
    def bag_once_ust(self) -> int:
        return self._bag_once_ust

    @bag_once_ust.setter
    def bag_once_ust(self, deger: int) -> None:
        self._bag_once_ust = deger

    def azalt_sure(self) -> None:
        """Üst-beyin override süresini her tikte azaltır."""
        self.ust.azalt_sure()