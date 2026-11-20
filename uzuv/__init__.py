"""CORE Uzuv paketi — x86-64 Assembly bilgi tabanı ve öğrenme organi.

Bu paket ana organizma beyninden bağımsız, kendi beyin dosyasına ve
kendi günlüğüne sahip bir uzuvdur. Ana sistemle danışmanlık ilişki halindedir.
"""

from .asm_uzuv import AsmUzuv

import importlib.util
from pathlib import Path

# NOT (isim çakışması): kökündeki `uzuv.py` modülü (Faz 2 sınıflandırıcı +
# CPU/RAM/disk LIM izleyicisi) bu paketle aynı ismi taşıdığından normal import
# sistemi paketi seçer ve `uzuv.py`'yi gölgeler. main.py (`uzuv_mod.LIM()`,
# bekleniyor: `.durum()` / `.adaptif_ceza()`) ve ag.py (`uzuv.Uzuv`,
# `uzuv.ozellikler`) bu isimleri ihtiyaç duyar; bu yüzden `uzuv.py` dosyası
# doğrudan dosya yolundan yüklenir ve ortak isimleri paket adası altında
# dışa verilir. `AsmUzuv` (derleme/orgān öğrenme organı) `.asm_uzuv`'den gelir.
# __name__ != "__main__" olduğundan uzuv.py'nin CLI bloğu çalışmaz.
_uzuv_py = Path(__file__).resolve().parent.parent / "uzuv.py"
if _uzuv_py.exists():
    _spec = importlib.util.spec_from_file_location("uzuv._kaynak_modul", _uzuv_py)
    if _spec is not None and _spec.loader is not None:
        _uzuv_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_uzuv_mod)
        for _ad in ("LIM", "Uzuv", "ozellikler", "son_cekim"):
            if hasattr(_uzuv_mod, _ad):
                globals()[_ad] = getattr(_uzuv_mod, _ad)
else:
    # Geri dönüş: uzuv.py yoksa eski (eksik) davranış korunur.
    LIM = AsmUzuv