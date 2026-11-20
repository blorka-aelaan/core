"""CORE USB Beyn — USB cihazları için kendi öğrenme modeli.

Her takılan USB cihazı zeka/usb.json üzerinden kalıcı olarak kaydedilir.
Uyku durumunda yeni cihazlar eski verilere eklenir (konsolidasyon).

Kayıt şeması:
{
  "cihazlar": {
    "1-1": {
      "adres": "1-1",
      "vendor": "1d6b",
      "product": "0002",
      "manufacturer": "Linux",
      "product_name": "xHCI",
      "interfaces": "1",
      "gorulenme_sayisi": 1,
      "ilk_gorunme": 1794488761.0,
      "son_gorunme": 1794488761.0,
      "durum": "yeni"
    }
  },
  "toplam_cihaz": 1,
  "yeni_cihaz_sayisi": 0,
  "son_etkinlik": 1794488761.0
}
"""
import json
import os
import time
from pathlib import Path

import zeka


class UsbBeyin:
    """USB cihaz beyni — her cihazı bir kayıt olarak öğrenir ve hatırlar."""

    def __init__(self, root: Path):
        self.root = root
        self.yol = zeka.yol("usb.json")
        self.cihazlar: dict = {}
        self.toplam_cihaz = 0
        self.yeni_cihaz_sayisi = 0
        self.son_etkinlik = 0.0
        self._yukle()

    def _yukle(self):
        try:
            veri = json.loads(self.yol.read_text(encoding="utf-8"))
            self.cihazlar = veri.get("cihazlar", {})
            self.toplam_cihaz = int(veri.get("toplam_cihaz", len(self.cihazlar)))
            self.yeni_cihaz_sayisi = int(veri.get("yeni_cihaz_sayisi", 0))
            self.son_etkinlik = float(veri.get("son_etkinlik", 0.0))
        except (OSError, ValueError):
            self.cihazlar = {}
            self.toplam_cihaz = 0
            self.yeni_cihaz_sayisi = 0
            self.son_etkinlik = 0.0

    def save(self):
        tmp = self.yol.with_name("%s.%d.tmp" % (self.yol.name, os.getpid()))
        tmp.write_text(
            json.dumps(
                {
                    "cihazlar": self.cihazlar,
                    "toplam_cihaz": self.toplam_cihaz,
                    "yeni_cihaz_sayisi": self.yeni_cihaz_sayisi,
                    "son_etkinlik": self.son_etkinlik,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(self.yol))

    def learn(self, cihaz_bilgi: dict) -> dict:
        """Yeni bir USB cihazı öğren. Eğer daha önce görüldüyse güncelle, değilse ekle.

        Döndürür: {"yeni_mi": bool, "cikarilan": str}
        """
        adres = cihaz_bilgi.get("adres", "?")
        simdi = time.time()
        yeni_mi = adres not in self.cihazlar

        if yeni_mi:
            self.cihazlar[adres] = {
                "adres": adres,
                "vendor": cihaz_bilgi.get("vendor", "?"),
                "product": cihaz_bilgi.get("product", "?"),
                "manufacturer": cihaz_bilgi.get("manufacturer", ""),
                "product_name": cihaz_bilgi.get("product_name", ""),
                "interfaces": cihaz_bilgi.get("interfaces", "?"),
                "gorulenme_sayisi": 1,
                "ilk_gorunme": simdi,
                "son_gorunme": simdi,
                "durum": "yeni",
            }
            self.toplam_cihaz += 1
            self.yeni_cihaz_sayisi += 1
            cikarilan = "yeni_usb_cihaz"
        else:
            kayit = self.cihazlar[adres]
            kayit["gorulenme_sayisi"] = int(kayit.get("gorulenme_sayisi", 0)) + 1
            kayit["son_gorunme"] = simdi
            # Eğer daha önce "yeni" işaretliyse, şimdi "bilinik" yap
            if kayit.get("durum") == "yeni":
                kayit["durum"] = "bilinik"
            cikarilan = "bilinik_usb_cihaz"

        self.son_etkinlik = simdi
        self.save()

        return {"yeni_mi": yeni_mi, "cikarilan": cikarilan, "adres": adres}

    def durum_raporu(self) -> dict:
        return {
            "toplam_cihaz": self.toplam_cihaz,
            "yeni_cihaz_sayisi": self.yeni_cihaz_sayisi,
            "son_etkinlik": self.son_etkinlik,
            "cihaz_sayisi": len(self.cihazlar),
        }