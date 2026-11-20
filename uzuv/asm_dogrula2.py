"""
asm_dogrula.py — Assembly için "gerçeklik hakemi" (sadece Python stdlib + binutils: as, ld)

Fikir: Uzuv bir kodun ne yapacağını TAHMİN eder, bu modül kodu gerçekten
derleyip çalıştırır ve makinenin verdiği cevabı geri döndürür.
  - Derleme hatası  -> assembler'ın kendi mesajı (gerçek ders)
  - Çalışma hatası  -> sinyal adı (SIGSEGV vb.)
  - Başarı          -> çalışma sonrası tüm yazmaçlar + bayraklar

Sözdizimi: GAS Intel (noprefix). NASM'dan küçük farklar var:
  mov [rax], 5            -> mov qword ptr [rax], 5   (boyut belirtmek gerekir)
  mov rsi, msg            -> lea rsi, [rip + msg]     (etiketin adresi için)
Bu farklar da uzuv için gerçek derstir; assembler söyler.

Kullanım:
    from asm_dogrula import dene
    s = dene("mov rax, 5\\nadd rax, 3", baslangic={"rbx": 7})
    s["tamam"], s["yazmac"]["rax"], s["bayrak"]["ZF"]

Bellek denemeleri için 256 baytlık sıfırlı bir alan vardır: [rip + veri]
"""

import os
import resource
import signal
import struct
import subprocess
import tempfile

YAZMACLAR = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
             "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
BAYRAKLAR = {"CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7, "OF": 11}

_SABLON = """.intel_syntax noprefix
.section .bss
.lcomm kayit, 256
.lcomm veri, 256
.lcomm yigin, 4096
.section .text
.globl _start
_start:
    lea rsp, [rip + yigin + 4096]
{baslangic}
    xor rbp, rbp
# ---- kullanıcı kodu başlangıç ----
{kod}
# ---- kullanıcı kodu bitiş ----
{kaydet}
    pushfq
    pop rax
    mov qword ptr [rip + kayit + 128], rax
    mov rax, 1
    mov rdi, 1
    lea rsi, [rip + kayit]
    mov rdx, 136
    syscall
    mov rax, 60
    xor rdi, rdi
    syscall
"""


def _hata_ayikla(stderr):
    """'x.s:12: Error: ...' satırlarından sadece mesaj kısmını al."""
    mesajlar = []
    for satir in stderr.splitlines():
        if "Error:" in satir:
            mesajlar.append(satir.split("Error:", 1)[1].strip())
    return "; ".join(mesajlar) if mesajlar else stderr.strip()[:300]


def _sinir():
    resource.setrlimit(resource.RLIMIT_CPU, (1, 2))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def dene(kod, baslangic=None, zaman_asimi=3):
    """Kodu derle + çalıştır. Her zaman bir sözlük döner:
        tamam: bool
        asama: 'derleme' | 'baglama' | 'calisma' | 'bitti'
        hata:  str | None      (assembler mesajı ya da sinyal adı)
        yazmac: {ad: int}      (başarılıysa; rsp, çalıştırma öncesi yığına göre göreli değil mutlak)
        bayrak: {ad: 0/1}      (başarılıysa)
    """
    baslangic = baslangic or {}
    for ad in baslangic:
        if ad.lower() not in YAZMACLAR:
            return {"tamam": False, "asama": "derleme",
                    "hata": f"bilinmeyen başlangıç yazmacı: {ad}", "yazmac": {}, "bayrak": {}}

    bas = "\n".join(f"    mov {ad.lower()}, {int(v)}" for ad, v in baslangic.items())
    kaydet = "\n".join(
        f"    mov qword ptr [rip + kayit + {i * 8}], {r}" for i, r in enumerate(YAZMACLAR)
    )
    metin = _SABLON.format(baslangic=bas, kod=kod, kaydet=kaydet)

    with tempfile.TemporaryDirectory(prefix="asmdogrula_") as d:
        s_yol, o_yol, exe = (os.path.join(d, n) for n in ("t.s", "t.o", "t"))
        with open(s_yol, "w", encoding="utf-8") as f:
            f.write(metin)

        r = subprocess.run(["as", "--64", "-o", o_yol, s_yol],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"tamam": False, "asama": "derleme", "hata": _hata_ayikla(r.stderr),
                    "yazmac": {}, "bayrak": {}}

        r = subprocess.run(["ld", "-o", exe, o_yol], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {"tamam": False, "asama": "baglama", "hata": r.stderr.strip()[:300],
                    "yazmac": {}, "bayrak": {}}

        try:
            r = subprocess.run([exe], capture_output=True, timeout=zaman_asimi,
                               preexec_fn=_sinir)
        except subprocess.TimeoutExpired:
            return {"tamam": False, "asama": "calisma", "hata": "zaman aşımı (sonsuz döngü?)",
                    "yazmac": {}, "bayrak": {}}

        if r.returncode < 0:
            try:
                ad = signal.Signals(-r.returncode).name
            except ValueError:
                ad = f"sinyal {-r.returncode}"
            if ad in ("SIGXCPU", "SIGKILL"):
                ad = "zaman aşımı (sonsuz döngü?)"
            return {"tamam": False, "asama": "calisma", "hata": ad, "yazmac": {}, "bayrak": {}}

        if len(r.stdout) != 136:
            return {"tamam": False, "asama": "calisma",
                    "hata": f"kayıt okunamadı ({len(r.stdout)} bayt)", "yazmac": {}, "bayrak": {}}

        degerler = struct.unpack("<17Q", r.stdout)
        yazmac = dict(zip(YAZMACLAR, degerler[:16]))
        rflags = degerler[16]
        bayrak = {ad: (rflags >> bit) & 1 for ad, bit in BAYRAKLAR.items()}
        return {"tamam": True, "asama": "bitti", "hata": None, "yazmac": yazmac, "bayrak": bayrak}


def karsilastir(tahmin, sonuc):
    """Tahmin {'rax': 8, 'ZF': 0, ...} ile gerçek sonucu karşılaştır.
    Dönen: {anahtar: (tahmin, gercek)} sadece tutmayanlar. Boşsa tahmin tam doğru."""
    if not sonuc["tamam"]:
        return {"_calisma": (tahmin, sonuc["hata"])}
    fark = {}
    for k, beklenen in tahmin.items():
        if k in BAYRAKLAR:
            gercek = sonuc["bayrak"][k.upper()]
        else:
            gercek = sonuc["yazmac"][k.lower()]
        if gercek != (beklenen & 0xFFFFFFFFFFFFFFFF if k not in BAYRAKLAR else beklenen):
            fark[k] = (beklenen, gercek)
    return fark


if __name__ == "__main__":
    ornekler = [
        ("toplama",            "mov rax, 5\nadd rax, 3", {}),
        ("xor ile sıfırlama",  "mov rax, 99\nxor rax, rax", {}),
        ("bellekten belleğe",  "mov [rip+veri], [rip+veri+8]", {}),
        ("boyutsuz imm->mem",  "mov [rip+veri], 5", {}),
        ("cmp bayrakları",     "mov rax, 4\ncmp rax, 4", {}),
        ("taşma (OF/CF)",      "mov rax, 0x7fffffffffffffff\nadd rax, 1", {}),
        ("başlangıç değeri",   "imul rax, rbx", {"rax": 6, "rbx": 7}),
        ("sonsuz döngü",       "l: jmp l", {}),
        ("geçersiz bellek",    "mov rax, [0]", {}),
    ]
    for ad, kod, bas in ornekler:
        s = dene(kod, bas)
        if s["tamam"]:
            ek = f"rax={s['yazmac']['rax']} ZF={s['bayrak']['ZF']} CF={s['bayrak']['CF']} OF={s['bayrak']['OF']}"
            print(f"[ok ] {ad:22} {ek}")
        else:
            print(f"[hata] {ad:22} ({s['asama']}) {s['hata']}")
