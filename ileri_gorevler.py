import json
import subprocess
import sys
from pathlib import Path

MASK = (1 << 64) - 1

ILERI_GOREVLER = [
    # =========================================================================
    # BÖLÜM A: BİT MANİPÜLASYONU (Seviye 1 - 2)
    # =========================================================================
    {
        "ad": "1_tek_cift_parite_kontrolu_bit0",
        "aciklama": "En düşük anlamlı biti (LSB) izole et: rax = rax & 1",
        "seviye": 1, "azami_komut": 1, "butce": 10000,
        "training": [
            {"input": {"rax": 14}, "output": {"rax": 0}},
            {"input": {"rax": 15}, "output": {"rax": 1}},
            {"input": {"rax": 254}, "output": {"rax": 0}},
            {"input": {"rax": 101}, "output": {"rax": 1}},
        ],
        "validation": [
            {"input": {"rax": 88}, "output": {"rax": 0}},
            {"input": {"rax": 77}, "output": {"rax": 1}},
        ]
    },
    {
        "ad": "2_en_sagdaki_1_bitini_temizle_kernighan",
        "aciklama": "n & (n - 1) algoritması (2'nin kuvveti testi temeli)",
        "seviye": 1, "azami_komut": 3, "butce": 50000,
        "training": [
            {"input": {"rax": 12}, "output": {"rax": 8}},   # 1100 -> 1000
            {"input": {"rax": 10}, "output": {"rax": 8}},   # 1010 -> 1000
            {"input": {"rax": 8},  "output": {"rax": 0}},   # 1000 -> 0000
            {"input": {"rax": 7},  "output": {"rax": 6}},   # 0111 -> 0110
        ],
        "validation": [
            {"input": {"rax": 6},  "output": {"rax": 4}},   # 0110 -> 0100
            {"input": {"rax": 16}, "output": {"rax": 0}},   # 10000 -> 00000
        ]
    },
    {
        "ad": "3_iki_nibble_paketleme",
        "aciklama": "(rax << 3) | (rbx & 7) bit paketleme işlemi",
        "seviye": 1, "azami_komut": 3, "butce": 60000,
        "training": [
            {"input": {"rax": 5, "rbx": 2},  "output": {"rax": 42}},  # 40 | 2
            {"input": {"rax": 3, "rbx": 15}, "output": {"rax": 31}},  # 24 | 7
            {"input": {"rax": 1, "rbx": 9},  "output": {"rax": 9}},   # 8 | 1
        ],
        "validation": [
            {"input": {"rax": 4, "rbx": 11}, "output": {"rax": 35}},  # 32 | 3
            {"input": {"rax": 2, "rbx": 6},  "output": {"rax": 22}},  # 16 | 6
        ]
    },
    {
        "ad": "4_ikinin_tumleyeni_ters_isaret_xor_ile",
        "aciklama": "(~rax) + 1 = -rax dönüşümü",
        "seviye": 1, "azami_komut": 2, "butce": 25000,
        "training": [
            {"input": {"rax": 5},   "output": {"rax": (-5) & MASK}},
            {"input": {"rax": 100}, "output": {"rax": (-100) & MASK}},
            {"input": {"rax": 0},   "output": {"rax": 0}},
        ],
        "validation": [
            {"input": {"rax": 1},  "output": {"rax": (-1) & MASK}},
            {"input": {"rax": 42}, "output": {"rax": (-42) & MASK}},
        ]
    },

    # =========================================================================
    # BÖLÜM B: BELLEK OKUMA / YAZMA (Seviye 2 - 4 yazmaç + bellek açık)
    # =========================================================================
    {
        "ad": "5_bellek_yaz_ve_geri_oku_dereference",
        "aciklama": "[rbx] adresine sabit 10 yaz ve rcx'e oku (pointer dereference)",
        "seviye": 2, "azami_komut": 2, "butce": 80000,
        "training": [
            {"input": {"rbx": 64,  "rcx": 0}, "output": {"rcx": 10}},
            {"input": {"rbx": 128, "rcx": 5}, "output": {"rcx": 10}},
            {"input": {"rbx": 256, "rcx": 9}, "output": {"rcx": 10}},
        ],
        "validation": [
            {"input": {"rbx": 512,  "rcx": 1}, "output": {"rcx": 10}},
            {"input": {"rbx": 1024, "rcx": 7}, "output": {"rcx": 10}},
        ]
    },
    {
        "ad": "6_bellek_uzerinden_deger_aktarimi_ve_artirma",
        "aciklama": "rax değerini [rbx] adresine yaz, [rbx] adresinden rcx'e oku ve artır",
        "seviye": 2, "azami_komut": 3, "butce": 120000,
        "training": [
            {"input": {"rax": 15, "rbx": 64},  "output": {"rcx": 16}},
            {"input": {"rax": 40, "rbx": 128}, "output": {"rcx": 41}},
            {"input": {"rax": 0,  "rbx": 256}, "output": {"rcx": 1}},
        ],
        "validation": [
            {"input": {"rax": 99, "rbx": 512}, "output": {"rcx": 100}},
            {"input": {"rax": 7,  "rbx": 32},  "output": {"rcx": 8}},
        ]
    },
    {
        "ad": "7_iki_bellek_hucresi_toplami",
        "aciklama": "rax -> [rcx], rbx -> [rdx] yaz, sonra bellekten okuyup topla",
        "seviye": 2, "azami_komut": 4, "butce": 180000,
        "training": [
            {"input": {"rax": 10, "rbx": 25, "rcx": 64,  "rdx": 128}, "output": {"rax": 35}},
            {"input": {"rax": 7,  "rbx": 8,  "rcx": 256, "rdx": 512}, "output": {"rax": 15}},
            {"input": {"rax": 50, "rbx": 50, "rcx": 32,  "rdx": 96},  "output": {"rax": 100}},
        ],
        "validation": [
            {"input": {"rax": 12, "rbx": 30, "rcx": 16,  "rdx": 48},  "output": {"rax": 42}},
            {"input": {"rax": 3,  "rbx": 9,  "rcx": 80,  "rdx": 160}, "output": {"rax": 12}},
        ]
    },

    # =========================================================================
    # CÖLÜM C: DÖNGÜLER (jnz / label) VE YIĞIN (Seviye 4 - Tam x86-64)
    # =========================================================================
    {
        "ad": "8_dongu_ile_toplama_rax_arti_rbx",
        "aciklama": "dongu: inc rax / dec rbx / jnz dongu ile döngüsel toplama",
        "seviye": 4, "azami_komut": 4, "butce": 250000, "zaman": 30,
        "training": [
            {"input": {"rax": 10, "rbx": 3}, "output": {"rax": 13, "rbx": 0}},
            {"input": {"rax": 5,  "rbx": 4}, "output": {"rax": 9,  "rbx": 0}},
            {"input": {"rax": 20, "rbx": 2}, "output": {"rax": 22, "rbx": 0}},
        ],
        "validation": [
            {"input": {"rax": 7,  "rbx": 5}, "output": {"rax": 12, "rbx": 0}},
            {"input": {"rax": 100,"rbx": 1}, "output": {"rax": 101,"rbx": 0}},
        ]
    },
    {
        "ad": "9_dongu_ile_1_den_N_e_kadar_toplam",
        "aciklama": "baslangic: add rax, rcx / dec rcx / jnz baslangic (Gauss toplamı)",
        "seviye": 4, "azami_komut": 4, "butce": 300000, "zaman": 40,
        "training": [
            {"input": {"rax": 0, "rcx": 3}, "output": {"rax": 6,  "rcx": 0}},  # 3+2+1
            {"input": {"rax": 0, "rcx": 4}, "output": {"rax": 10, "rcx": 0}},  # 4+3+2+1
            {"input": {"rax": 0, "rcx": 5}, "output": {"rax": 15, "rcx": 0}},  # 5+4+3+2+1
        ],
        "validation": [
            {"input": {"rax": 0, "rcx": 6}, "output": {"rax": 21, "rcx": 0}},
            {"input": {"rax": 0, "rcx": 2}, "output": {"rax": 3,  "rcx": 0}},
        ]
    },
]

def calistir():
    gecici = Path("/tmp/ileri_gorev.json")
    cozulen = 0
    for g in ILERI_GOREVLER:
        veri = {"training": g["training"], "validation": g["validation"]}
        gecici.write_text(json.dumps(veri), encoding="utf-8")
        cmd = [
            sys.executable, "uzuv/asm_ogren.py",
            "--coz-json", str(gecici),
            "--seviye", str(g["seviye"]),
            "--azami-komut", str(g["azami_komut"]),
            "--butce", str(g["butce"]),
            "--zaman-asimi", str(g.get("zaman", 20)),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        cikti = res.stdout.strip() or res.stderr.strip()
        print(f"=== {g['ad']} ===")
        print(f"Hedef: {g['aciklama']}")
        print(f"Sonuç: {cikti}\n")
        if '"cozuldu": true' in cikti:
            cozulen += 1

    print(f"ÖZET: {cozulen}/{len(ILERI_GOREVLER)} ileri seviye görev çözüldü.")

if __name__ == "__main__":
    calistir()
