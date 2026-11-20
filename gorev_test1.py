import json
import subprocess
import sys
from pathlib import Path

MASK = (1 << 64) - 1

GOREVLER = [
    {
        "ad": "3_on_ile_carp_seviye1",
        "seviye": 1, "azami_komut": 4, "butce": 80000,
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
        "ad": "7_lineer_kombinasyon_2a_plus_b_minus_c",
        "seviye": 2, "azami_komut": 4, "butce": 100000,
        "training": [
            {"input": {"rax": 2, "rbx": 3, "rcx": 1}, "output": {"rax": 6}},
            {"input": {"rax": 4, "rbx": 1, "rcx": 5}, "output": {"rax": 4}},
            {"input": {"rax": 1, "rbx": 5, "rcx": 3}, "output": {"rax": 4}},
            {"input": {"rax": 0, "rbx": 2, "rcx": 4}, "output": {"rax": (-2) & MASK}},
        ],
        "validation": [
            {"input": {"rax": 3, "rbx": 4, "rcx": 2}, "output": {"rax": 8}},
            {"input": {"rax": 5, "rbx": 2, "rcx": 9}, "output": {"rax": 3}},
        ]
    },
    {
        "ad": "8_sysv_abi_2rdi_eksi_rsi",
        "seviye": 3, "azami_komut": 3, "butce": 150000,
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
    {
        "ad": "9_kare_alma_x_kare_arti_1",
        "seviye": 4, "azami_komut": 3, "butce": 250000, "zaman": 30,
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
        "seviye": 4, "azami_komut": 2, "butce": 250000, "zaman": 30,
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
            "--butce", str(g["butce"]),
            "--zaman-asimi", str(g.get("zaman", 15)),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        print(f"=== {g['ad']} (Seviye {g['seviye']}) ===")
        print(res.stdout.strip() or res.stderr.strip())

if __name__ == "__main__":
    hepsini_coz()
