"""CORE lifecycle — doğum, uyku, ölüm ve kalıcılık yönetimi.

main.py'deki finally bloğu ve yaşam döngüsü işlemlerini ayrıştırır:
  * beyin / üst-beyin / diğer modellerin kaydedilmesi ve yüklenmesi
  * ölüm olayı ve kalibrasyon
  * kapı (door) durdurma ve temizlik
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import time

import journal as journal_mod


class LifecycleManager:
    """Yaşam döngüsü ve kalıcılık yöneticisi."""

    def __init__(
        self,
        mind: Any,
        ust: Any,
        journal: Any,
        door: Any,
        drives: Any,
        sur: Any,
        dam: Any,
        guv: Any,
        paket_beyin: Any,
        kul: Any,
        dusun: Any,
        olum_ok: bool,
        olum_beyin: Any,
        cfg: Dict[str, Any],
        root: Any,
        brain_path: str,
        golge_yolu: str,
        journal_azami_mb: int,
        golge_azami_mb: int,
        selftrainer: Any,
        status_fn: Any,
    ) -> None:
        self.mind = mind
        self.ust = ust
        self.journal = journal
        self.door = door
        self.drives = drives
        self.sur = sur
        self.dam = dam
        self.guv = guv
        self.paket_beyin = paket_beyin
        self.kul = kul
        self.dusun = dusun
        self.olum_ok = olum_ok
        self.olum_beyin = olum_beyin
        self.cfg = cfg
        self.root = root
        self.brain_path = brain_path
        self.golge_yolu = golge_yolu
        self.journal_azami_mb = journal_azami_mb
        self.golge_azami_mb = golge_azami_mb
        self.selftrainer = selftrainer
        self.status_fn = status_fn

    # ------------------------------------------------------------------ kaydetme

    def save_all(self, tik: int) -> None:
        """Tüm modelleri diske kaydeder."""
        self.mind.save(self.brain_path)
        self.journal.log("brain_save", links=len(self.mind.w))
        self.dusun.save()
        self.journal.log("dusunme_save", samples=self.dusun.samples)
        self.ust.save()
        self.journal.log(
            "ust_beyn_save",
            samples=self.ust.samples,
            tik=self.ust.tik,
            dogrulama=[round(d, 2) for d in self.ust.dogrulama],
            reddedilen=self.ust.reddedilen,
            secim=self.ust.secim_sayilari,
        )
        self.sur.save()
        self.journal.log("surec_save", ornek=self.sur.ornek, adet=len(self.sur.adet))

        if self.dam.samples:
            if self.dam.save():
                self.journal.log(
                    "damak_save", samples=self.dam.samples, kova=len(self.dam.n)
                )
            else:
                self.journal.log(
                    "damak_save_atlandi",
                    not_="dosya dışarıdan yeniden eğitilmiş, korundu",
                )

        if self.kul.aktif:
            self.kul._komut_tehlike.save()
            self.journal.log(
                "komut_tehlike_save",
                samples=self.kul._komut_tehlike.samples,
                help=len(self.kul._komut_tehlike.help_aciklamalar),
            )

        if self.guv:
            self.guv.save()
            self.journal.log(
                "guvenlik_save", samples=self.guv.samples, kova=len(self.guv.n)
            )

        if self.paket_beyin:
            self.paket_beyin.save()
            self.journal.log(
                "paket_save",
                ornek=self.paket_beyin.ornek,
                bilgi=len(self.paket_beyin.bilgi),
            )

    # ------------------------------------------------------------------ ölüm

    def handle_death(
        self,
        args_ticks: int,
        state: Dict[str, Any],
        hedef: Optional[str],
    ) -> None:
        """Ölüm anında kalibrasyon ve günlük kaydı."""
        if not self.drives.alive:
            # Z3: ölüm anında kategori tahmini kayda
            try:
                if self.olum_ok:
                    _kat, _str = self.olum_beyin.tani(
                        {
                            "sinyal": "yok",
                            "kaynak": "guc",
                            "kim": "cekirdek",
                            "siddet": "kademeli",
                            "belirti": "kaynak_tukendi",
                            "onbelirti": "evet",
                        }
                    )[:2]
                    self.journal.log(
                        "olum_gercek",
                        kategori=_kat,
                        strateji=_str,
                        **self.status_fn(),
                    )
            except Exception:
                pass
            self.journal.log("death", note="enerji tükendi", **self.status_fn())
        elif state["ticks"] and args_ticks:
            self.journal.log("pause", note="tik doldu", **self.status_fn())

    # ------------------------------------------------------------------ arşivleme

    def arsivle_gunlukler(self, tik: int, hedef: Optional[str]) -> None:
        """Periyodik günlük arşivi ve gölge günlüğü boyut kontrolü."""
        if self.journal_azami_mb > 0 and tik % 200 == 0:
            try:
                from pathlib import Path
                mb = Path(self.journal.path).stat().st_size / 1e6
                if mb > self.journal_azami_mb:
                    arsiv_hedef = journal_mod.arsivle(self.journal.path)
                    if arsiv_hedef:
                        self.journal.log(
                            "journal_arsiv", mb=round(mb, 1), hedef=arsiv_hedef
                        )
            except OSError:
                pass

        if self.golge_azami_mb > 0 and tik % 200 == 0:
            try:
                from pathlib import Path
                mb = Path(self.golge_yolu).stat().st_size / 1e6
                if mb > self.golge_azami_mb:
                    arsiv_hedef = journal_mod.arsivle(self.golge_yolu)
                    if arsiv_hedef:
                        self.journal.log(
                            "golge_arsiv", mb=round(mb, 1), hedef=arsiv_hedef
                        )
            except OSError:
                pass

    # ------------------------------------------------------------------ kapatma

    def kapat(self) -> None:
        """Tüm kaynakları serbest bırakır ve kapıyı durdurur."""
        self.selftrainer.stop()
        self.door.stop()