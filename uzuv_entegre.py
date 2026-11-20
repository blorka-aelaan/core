"""
CORE Uzuv-Main Entegrasyonu

main.py'de değiştirilmeden, door.py send ile 'asm:' komutlarını
işleyerek uzuv modülünü entegre eder.

Kullanım:
    python3 uzuv_entegre.py          # standalone test

    door.py send asm:sorgula RAX     # register sorgula
    door.py send asm:derle "mov rax, 5"  # derleme simülasyonu
    door.py send asm:dene True|xor rax, rax  # başarı kaydı
    door.py send asm:dene False|mov [rax],[rbx]|bellekten belleğe aktarılamaz  # hata kaydı
    door.py send asm:hata_var "mov [rax],[rbx]"  # hata kontrolü
    door.py send asm:rapor           # uzuv raporu
"""

import sys
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CORE_ROOT))

from uzuv.asm_uzuv import AsmUzuv

UZUV = AsmUzuv()


def isle(mesaj: str) -> dict:
    """
    'asm:' önekli mesajı işler ve cevap döndürür.

    Args:
        mesaj: 'asm:' önekli komut (örn. 'asm:sorgula RAX')

    Dönüş: dict (cevap)
    """
    if not mesaj.startswith("asm:"):
        return {"hata": "asm: önekli degil"}

    icerik = mesaj[4:].strip()

    if not icerik:
        return {"hata": "bos komut"}

    parcalar = icerik.split(" ", 1)
    komut = parcalar[0]
    arg = parcalar[1] if len(parcalar) > 1 else ""

    try:
        if komut == "sorgula":
            bulundu, bilgi = UZUV.sorgula(arg)
            return {
                "komut": "sorgula",
                "terim": arg,
                "bulundu": bulundu,
                "bilgi": str(bilgi)[:500] if bilgi else bilgi,
            }

        elif komut == "derle":
            basarili, sonuc = UZUV.derle(arg)
            return {
                "komut": "derle",
                "kod": arg[:200],
                "basarili": basarili,
                "sonuc": sonuc[:500] if basarili else sonuc,
            }

        elif komut == "dene":
            # format: dene <True/False>|<kod>|[hata_mesaji]
            dene_parcalar = arg.split("|", 2)
            basarili = dene_parcalar[0].lower() == "true" if len(dene_parcalar) > 0 else False
            kod = dene_parcalar[1] if len(dene_parcalar) > 1 else ""
            hata = dene_parcalar[2] if len(dene_parcalar) > 2 else None
            UZUV.dene_kod(kod, basarili=basarili, hata_mesaji=hata)
            return {
                "komut": "dene",
                "kod": kod,
                "basarili": basarili,
                "hata": hata,
            }

        elif komut == "hata_var":
            var, mesaj = UZUV.hata_var_mi(arg)
            return {
                "komut": "hata_var",
                "kod": arg,
                "var": var,
                "mesaj": mesaj,
            }

        elif komut == "rapor":
            UZUV.yazdir_rapor()
            return {
                "komut": "rapor",
                "rapor": UZUV.rapor(),
            }

        elif komut == "durum":
            return UZUV.durum()

        else:
            return {
                "hata": "bilinmeyen asm komutu: %s" % komut,
                "mevcut": ["sorgula", "derle", "dene", "hata_var", "rapor", "durum"],
            }

    except Exception as e:
        return {"hata": str(e), "komut": komut}


if __name__ == "__main__":
    print("=== Uzuv Entegrasyon Testi ===")

    testler = [
        "asm:sorgula RAX",
        "asm:sorgula MOV",
        "asm:sorgula BILINMEYEN",
        "asm:derle mov rax, 5",
        "asm:derle mov [rax], [rbx]",
        "asm:dene True|xor rax, rax",
        "asm:dene False|mov [rax],[rbx]|bellekten_bellege_aktarilamaz",
        "asm:hata_var mov [rax],[rbx]",
        "asm:hata_var xor rax, rax",
        "asm:rapor",
        "asm:durum",
        "asm:bilinmeyen",
    ]

    for t in testler:
        cevap = isle(t)
        print("\n--> %s" % t)
        print("   %s" % str(cevap)[:300])

    UZUV.kapat()
    print("\n=== TEST TAMAMLANDI ===")
