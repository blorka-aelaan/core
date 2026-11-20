import json
import subprocess
import sys
from pathlib import Path

TEST_GOREVLERI = [
    {
        "ad": "1_kernighan_en_sagdaki_1_bitini_temizle",
        "seviye": 1, "azami_komut": 3, "butce": 50000,
        "training": [
            {"input": {"rax": 12}, "output": {"rax": 8,  "rbx": 11}},
            {"input": {"rax": 10}, "output": {"rax": 8,  "rbx": 9}},
            {"input": {"rax": 7},  "output": {"rax": 6,  "rbx": 6}},
        ],
        "validation": [
            {"input": {"rax": 6},  "output": {"rax": 4,  "rbx": 5}},
            {"input": {"rax": 16}, "output": {"rax": 0,  "rbx": 15}},
        ]
    },
    {
        "ad": "2_bit_paketleme_rax_sol3_veya_rbx_mask5",
        "seviye": 1, "azami_komut": 3, "butce": 50000,
        "training": [
            {"input": {"rax": 5, "rbx": 7}, "output": {"rax": 45, "rbx": 5}},
            {"input": {"rax": 3, "rbx": 6}, "output": {"rax": 28, "rbx": 4}},
            {"input": {"rax": 1, "rbx": 1}, "output": {"rax": 9,  "rbx": 1}},
        ],
        "validation": [
            {"input": {"rax": 4, "rbx": 3}, "output": {"rax": 33, "rbx": 1}},
            {"input": {"rax": 2, "rbx": 5}, "output": {"rax": 21, "rbx": 5}},
        ]
    },
    {
        "ad": "3_gercek_bellek_yazma_zorunlu",
        "seviye": 2, "azami_komut": 2, "butce": 50000,
        "training": [
            {
                "input": {"rax": 42, "rbx": 64},
                "output": {"rax": 42, "rbx": 64},
                "bellek": {"64": 42, "65": 0, "66": 0, "67": 0, "68": 0, "69": 0, "70": 0, "71": 0}
            },
            {
                "input": {"rax": 255, "rbx": 128},
                "output": {"rax": 255, "rbx": 128},
                "bellek": {"128": 255, "129": 0, "130": 0, "131": 0, "132": 0, "133": 0, "134": 0, "135": 0}
            },
        ],
        "validation": [
            {
                "input": {"rax": 99, "rbx": 256},
                "output": {"rax": 99, "rbx": 256},
                "bellek": {"256": 99, "257": 0, "258": 0, "259": 0, "260": 0, "261": 0, "262": 0, "263": 0}
            }
        ]
    },
    {
        "ad": "4_dongu_ile_gauss_toplami_1_den_N_e",
        "seviye": 4, "azami_komut": 4, "butce": 350000, "zaman": 45,
        "training": [
            {"input": {"rax": 0, "rcx": 3}, "output": {"rax": 6,  "rcx": 0}},
            {"input": {"rax": 0, "rcx": 4}, "output": {"rax": 10, "rcx": 0}},
            {"input": {"rax": 0, "rcx": 5}, "output": {"rax": 15, "rcx": 0}},
        ],
        "validation": [
            {"input": {"rax": 0, "rcx": 6}, "output": {"rax": 21, "rcx": 0}},
            {"input": {"rax": 0, "rcx": 2}, "output": {"rax": 3,  "rcx": 0}},
        ]
    }
]

def calistir():
    gecici = Path("/tmp/yama_gorev.json")
    for g in TEST_GOREVLERI:
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
        print(f"=== {g['ad']} ===")
        print(res.stdout.strip() or res.stderr.strip(), "\n")

if __name__ == "__main__":
    calistir()
