import json
import subprocess
import sys
from pathlib import Path

MASK = (1 << 64) - 1

GOREVLER = [
    # --- SEVİYE 1: Temel Aritmetik & Bit Düzeyi (rax, rbx) ---
    {
        "ad": "1_sifirla",
        "seviye": 1, "azami_komut": 1,
        "training": [
            {"input": {"rax": 42}, "output": {"rax": 0}},
            {"input": {"rax": 100}, "output": {"rax": 0}},
            {"input": {"rax": 255}, "output": {"rax": 0}},
        ],
        "validation": [
            {"input": {"rax": 7}, "output": {"rax": 0}},
            {"input": {"rax": 999}, "output": {"rax": 0}},
        ]
    },
    {
        "ad": "2_ikiyle_carp",
        "seviye": 1, "azami_komut": 1,
        "training": [
            {"input": {"rax": 3}, "output": {"rax": 6}},
            {"input": {"rax": 10}, "output": {"rax": 20}},
            {"input": {"rax": 0}, "output": {"rax": 0}},
        ],
        "validation": [
            {"input": {"rax": 7}, "output": {"rax": 14}},
            {"input": {"rax": 50}, "output": {"rax": 100}},
        ]
    },
    {
        "ad": "3_on_ile_carp",
        "seviye": 1, "azami_komut": 3,
        "training": [
            {"input": {"rax": 2}, "output": {"rax": 20}},
            {"input": {"rax": 5}, "output": {"rax": 50}},
            {"input": {"rax": 12}, "output": {"rax": 120}},
        ],
        "validation": [
            {"input": {"rax": 3}, "output": {"rax": 30}},
            {"input": {"rax": 9}, "output": {"rax": 90}},
        ]
    },
    {
        "ad": "4_iki_yazmac_topla_ve_ikiye_katla",
        "seviye": 1, "azami_komut": 3,
        "training": [
            {"input": {"rax": 2, "rbx": 3}, "output": {"rax": 10}},
            {"input": {"rax": 5, "rbx": 1}, "output": {"rax": 12}},
            {"input": {"rax": 0, "rbx": 4}, "output": {"rax": 8}},
        ],
        "validation": [
            {"input": {"rax": 4, "rbx": 6}, "output": {"rax": 20}},
            {"input": {"rax": 10, "rbx": 5}, "output": {"rax": 30}},
        ]
    },
    {
        "ad": "5_xor_takas_swap",
        "seviye": 1, "azami_komut": 3,
        "training": [
            {"input": {"rax": 10, "rbx": 20}, "output": {"rax": 20, "rbx": 10}},
            {"input": {"rax": 1, "rbx": 99}, "output": {"rax": 99, "rbx": 1}},
            {"input": {"rax": 255, "rbx": 0}, "output": {"rax": 0, "rbx": 255}},
        ],
        "validation": [
            {"input": {"rax": 7, "rbx": 42}, "output": {"rax": 42, "rbx": 7}},
            {"input": {"rax": 123, "rbx": 456}, "output": {"rax": 456, "rbx": 123}},
        ]
    },
    {
        "ad": "6_mutlak_fark_veya_neg_arti_5",
        "seviye": 1, "azami_komut": 3,
        "training": [
            {"input": {"rax": 10}, "output": {"rax": (-5) & MASK}},
            {"input": {"rax": 5}, "output": {"rax": 0}},
            {"input": {"rax": 0}, "output": {"rax": 5}},
        ],
        "validation": [
            {"input": {"rax": 2}, "output": {"rax": 3}},
            {"input": {"rax": 8}, "output": {"rax": (-3) & MASK}},
        ]
    },

    # --- SEVİYE 2: 4 Yazmaç (rax, rbx, rcx, rdx) ---
    {
        "ad": "7_lineer_kombinasyon_3a_plus_2b_minus_c",
        "seviye": 2, "azami_komut": 5,
        "training": [
            {"input": {"rax": 2, "rbx": 3, "rcx": 1}, "output": {"rax": 11}},
            {"input": {"rax": 4, "rbx": 1, "rcx": 5}, "output": {"rax": 9}},
            {"input": {"rax": 1, "rbx": 5, "rcx": 3}, "output": {"rax": 10}},
            {"input": {"rax": 0, "rbx": 2, "rcx": 4}, "output": {"rax": 0}},
        ],
        "validation": [
            {"input": {"rax": 3, "rbx": 4, "rcx": 2}, "output": {"rax": 15}},
            {"input": {"rax": 5, "rbx": 2, "rcx": 9}, "output": {"rax": 10}},
        ]
    },

    # --- SEVİYE 3: System V Argüman Yazmaçları (rdi, rsi -> rax) ---
    {
        "ad": "8_sysv_abi_arguman_hesabi",
        "seviye": 3, "azami_komut": 4,
        "training": [
            {"input": {"rdi": 10, "rsi": 3}, "output": {"rax": 17}},
            {"input": {"rdi": 5, "rsi": 2}, "output": {"rax": 8}},
            {"input": {"rdi": 20, "rsi": 10}, "output": {"rax": 30}},
        ],
        "validation": [
            {"input": {"rdi": 7, "rsi": 4}, "output": {"rax": 10}},
            {"input": {"rdi": 15, "rsi": 5}, "output": {"rax": 25}},
        ]
    },

    # --- SEVİYE 4: LEA ve Çarpma (imul / lea) ---
    {
        "ad": "9_kare_alma_x_kare_arti_1",
        "seviye": 4, "azami_komut": 3,
        "training": [
            {"input": {"rdi": 2}, "output": {"rax": 5}},
            {"input": {"rdi": 3}, "output": {"rax": 10}},
            {"input": {"rdi": 5}, "output": {"rax": 26}},
            {"input": {"rdi": 0}, "output": {"rax": 1}},
        ],
        "validation": [
            {"input": {"rdi": 4}, "output": {"rax": 17}},
            {"input": {"rdi": 6}, "output": {"rax": 37}},
        ]
    },
    {
        "ad": "10_polinom_9x_arti_10",
        "seviye": 4, "azami_komut": 3,
        "training": [
            {"input": {"rdi": 1}, "output": {"rax": 19}},
            {"input": {"rdi": 2}, "output": {"rax": 28}},
            {"input": {"rdi": 0}, "output": {"rax": 10}},
        ],
        "validation": [
            {"input": {"rdi": 3}, "output": {"rax": 37}},
            {"input": {"rdi": 5}, "output": {"rax": 55}},
        ]
    },
]

def hepsini_coz():
    gecici = Path("/tmp/aktif_gorev.json")
    for g in GOREVLER:
        veri = {"training": g["training"], "validation": g["validation"]}
        gecici.write_text(json.dumps(veri), encoding="utf-8")
        cmd = [
            sys.executable, "uzuv/asm_ogren.py",
            "--coz-json", str(gecici),
            "--seviye", str(g["seviye"]),
            "--azami-komut", str(g["azami_komut"]),
            "--butce", "30000"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(f"=== {g['ad']} (Seviye {g['seviye']}) ===")
        print(res.stdout.strip() or res.stderr.strip())

if __name__ == "__main__":
    hepsini_coz()
