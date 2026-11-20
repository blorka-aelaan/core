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

Bellek denemelerinde veri alanı, erişilen en yüksek adrese göre büyür ve 2 GiB
ile sınırlıdır. Büyük alanlar sanal bellekte demand-zero olarak kullanılır.
"""

import os
import re
import resource
import signal
import struct
import subprocess
import tempfile

MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
MAX_ADDRESS_SPACE = MAX_MEMORY_BYTES + 512 * 1024 * 1024
YAZMACLAR = ["rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
             "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"]
BAYRAKLAR = {"CF": 0, "PF": 2, "AF": 4, "ZF": 6, "SF": 7, "OF": 11}

_SABLON = """.intel_syntax noprefix
.section .bss
.lcomm kayit, {kayit_boyutu}
.lcomm yigin, 4096
.lcomm veri, {bellek_boyutu}
.section .text
.globl _start
_start:
    mov rax, 157
    mov rdi, 38
    mov rsi, 1
    xor rdx, rdx
    syscall
    test rax, rax
    js _core_seccomp_fail
    mov rax, 157
    mov rdi, 22
    mov rsi, 1
    xor rdx, rdx
    syscall
    test rax, rax
    js _core_seccomp_fail
    lea rsp, [rip + yigin + 4096]
{baslangic}
{bellek_hazirla}
{bellek_ilk}
# ---- kullanıcı kodu başlangıç ----
{kod}
# ---- kullanıcı kodu bitiş ----
{kaydet}
    pushfq
    pop rax
    mov qword ptr [rip + kayit + 128], rax
{bellek_kaydet}
{bellek_temizle}
    mov rax, 1
    mov rdi, 1
    lea rsi, [rip + kayit]
    mov rdx, {kayit_boyutu}
    syscall
    mov rax, 60
    xor rdi, rdi
    syscall
_core_seccomp_fail:
    mov rdi, 125
    mov rax, 60
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
    resource.setrlimit(resource.RLIMIT_AS, (MAX_ADDRESS_SPACE, MAX_ADDRESS_SPACE))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


def dene(
    kod, baslangic=None, zaman_asimi=1.0, baslangic_bellek=None,
    bellek_adresleri=None,
):
    """Kodu derle + çalıştır. Her zaman bir sözlük döner:
        tamam: bool
        asama: 'derleme' | 'baglama' | 'calisma' | 'bitti'
        hata:  str | None      (assembler mesajı ya da sinyal adı)
        yazmac: {ad: int}      (başarılıysa; rsp, çalıştırma öncesi yığına göre göreli değil mutlak)
        bayrak: {ad: 0/1}      (başarılıysa)
        bellek: istenen/erişilen son bellek baytlarının adres-değer eşlemesi
    """
    baslangic = baslangic or {}
    for ad in baslangic:
        if ad.lower() not in YAZMACLAR:
            return {"tamam": False, "asama": "derleme",
                    "hata": f"bilinmeyen başlangıç yazmacı: {ad}", "yazmac": {}, "bayrak": {}}

    bas_degerleri = {r: 0 for r in YAZMACLAR if r != "rsp"}
    bas_degerleri.update({ad.lower(): int(v) for ad, v in baslangic.items() if ad.lower() != "rsp"})
    bas = "\n".join(f"    mov {ad}, {v}" for ad, v in bas_degerleri.items())
    bellek_etkin = baslangic_bellek is not None or bellek_adresleri is not None
    initial_memory = {}
    if isinstance(baslangic_bellek, dict):
        initial_memory = dict(baslangic_bellek)
    elif baslangic_bellek is not None:
        initial_memory = dict(enumerate(baslangic_bellek))
    output_addresses = set(bellek_adresleri or ())
    if bellek_etkin:
        if any(
            isinstance(address, bool) or not isinstance(address, int)
            or not 0 <= address < MAX_MEMORY_BYTES
            for address in set(initial_memory) | output_addresses
        ):
            return {"tamam": False, "asama": "derleme",
                    "hata": "bellek adresi 2 GiB sınırının dışında", "yazmac": {}, "bayrak": {}}
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            or not 0 <= value <= 255
            for value in initial_memory.values()
        ):
            return {"tamam": False, "asama": "derleme",
                    "hata": "başlangıç belleği değerleri bayt olmalı", "yazmac": {}, "bayrak": {}}
        memory_registers = set(re.findall(
            r"\[\s*(rax|rbx|rcx|rdx|rsi|rdi|rbp|rsp|r(?:[89]|1[0-5]))\s*\]",
            kod,
            re.I,
        ))
        scratch_register = next(
            (
                register for register in reversed(YAZMACLAR)
                if register != "rsp"
                and re.search(rf"\b{register}\b", kod, re.I) is None
            ),
            None,
        )
        if memory_registers and scratch_register is None:
            return {"tamam": False, "asama": "derleme",
                    "hata": "bellek doğrulaması için boş geçici yazmaç yok",
                    "yazmac": {}, "bayrak": {}}
        memory_ready = ""
        memory_cleanup = ""
        memory_init = ""
        memory_save = ""
        memory_size = max(
            [1]
            + [address + 1 for address in initial_memory]
            + [address + 1 for address in output_addresses]
        )
        if memory_size > MAX_MEMORY_BYTES:
            return {"tamam": False, "asama": "derleme",
                    "hata": "gerekli bellek 2 GiB üst sınırını aşıyor",
                    "yazmac": {}, "bayrak": {}}
        memory_capture_start = 144
        if scratch_register is not None and memory_registers:
            bas += (
                f"\n    mov qword ptr [rip + kayit + 136], {scratch_register}"
            )
            memory_ready = f"    lea {scratch_register}, [rip + veri]"
            for register in memory_registers:
                kod = re.sub(
                    rf"\[\s*{register}\s*\]",
                    f"[{scratch_register} + {register.lower()}]",
                    kod,
                    flags=re.I,
                )
            kod = re.sub(
                rf"\bmov\s+\[({scratch_register}\s*\+\s*"
                r"(?:rax|rbx|rcx|rdx|rsi|rdi|rbp|rsp|r(?:[89]|1[0-5])))\]"
                r"(\s*,\s*-?\d+)",
                r"mov qword ptr [\1]\2",
                kod,
                flags=re.I,
            )
            memory_init = "\n".join(
                f"    mov byte ptr [{scratch_register} + {address}], {value}"
                for address, value in sorted(initial_memory.items())
                if value
            )
            memory_save = "\n".join(
                line
                for index, address in enumerate(sorted(output_addresses))
                for line in (
                    f"    mov al, byte ptr [{scratch_register} + {address}]",
                    f"    mov byte ptr [rip + kayit + {memory_capture_start + index}], al",
                )
            )
            memory_cleanup = (
                f"    mov {scratch_register}, qword ptr [rip + kayit + 136]\n"
                f"    mov qword ptr [rip + kayit + "
                f"{YAZMACLAR.index(scratch_register) * 8}], {scratch_register}"
            )
    else:
        memory_size = 1
        memory_ready = ""
        memory_cleanup = ""
        memory_save = ""
        memory_init = ""
    kayit_boyutu = memory_capture_start + len(output_addresses) if bellek_etkin else 136
    kaydet = "\n".join(
        f"    mov qword ptr [rip + kayit + {i * 8}], {r}" for i, r in enumerate(YAZMACLAR)
    )
    metin = _SABLON.format(
        baslangic=bas,
        kod=kod,
        kaydet=kaydet,
        bellek_ilk=memory_init,
        bellek_hazirla=memory_ready,
        bellek_temizle=memory_cleanup,
        bellek_kaydet=memory_save,
        kayit_boyutu=kayit_boyutu,
        bellek_boyutu=memory_size,
    )

    with tempfile.TemporaryDirectory(prefix="asmdogrula_") as d:
        s_yol, o_yol, exe = (os.path.join(d, n) for n in ("t.s", "t.o", "t"))
        with open(s_yol, "w", encoding="utf-8") as f:
            f.write(metin)

        r = subprocess.run(["as", "--64", "-o", o_yol, s_yol],
                           capture_output=True, text=True, timeout=2)
        if r.returncode != 0:
            return {"tamam": False, "asama": "derleme", "hata": _hata_ayikla(r.stderr),
                    "yazmac": {}, "bayrak": {}}

        r = subprocess.run(["ld", "-o", exe, o_yol], capture_output=True, text=True, timeout=2)
        if r.returncode != 0:
            return {"tamam": False, "asama": "baglama", "hata": r.stderr.strip()[:300],
                    "yazmac": {}, "bayrak": {}}

        try:
            r = subprocess.run([exe], stdin=subprocess.DEVNULL, capture_output=True, timeout=zaman_asimi,
                               preexec_fn=_sinir)
        except subprocess.TimeoutExpired:
            return {"tamam": False, "asama": "calisma", "hata": "zaman aşımı (sonsuz döngü?)",
                    "yazmac": {}, "bayrak": {}}

        if r.returncode < 0:
            try:
                ad = signal.Signals(-r.returncode).name
            except ValueError:
                ad = f"sinyal {-r.returncode}"
            if ad == "SIGXCPU":
                ad = "zaman aşımı (sonsuz döngü?)"
            elif ad in ("SIGKILL", "SIGSYS"):
                ad = "sandbox_kill"
            return {"tamam": False, "asama": "calisma", "hata": ad, "yazmac": {}, "bayrak": {}}

        if len(r.stdout) != kayit_boyutu:
            return {"tamam": False, "asama": "calisma",
                    "hata": f"kayıt okunamadı ({len(r.stdout)} bayt)", "yazmac": {}, "bayrak": {}}

        degerler = struct.unpack("<17Q", r.stdout[:136])
        yazmac = dict(zip(YAZMACLAR, degerler[:16]))
        rflags = degerler[16]
        bayrak = {ad: (rflags >> bit) & 1 for ad, bit in BAYRAKLAR.items()}
        result = {
            "tamam": True, "asama": "bitti", "hata": None,
            "yazmac": yazmac, "bayrak": bayrak,
        }
        if bellek_etkin:
            result["bellek"] = {
                address: r.stdout[memory_capture_start + index]
                for index, address in enumerate(sorted(output_addresses))
            }
        return result


def karsilastir(tahmin, sonuc):
    """Tahmin {'rax': 8, 'ZF': 0, ...} ile gerçek sonucu karşılaştır.
    Dönen: {anahtar: (tahmin, gercek)} sadece tutmayanlar. Boşsa tahmin tam doğru."""
    if not sonuc["tamam"]:
        return {"_calisma": (tahmin, sonuc["hata"])}
    fark = {}
    for k, beklenen in tahmin.items():
        if k == "bellek":
            gercek = sonuc["bellek"]
        elif k in BAYRAKLAR:
            gercek = sonuc["bayrak"][k.upper()]
        else:
            gercek = sonuc["yazmac"][k.lower()]
        if k == "bellek":
            esit = gercek == beklenen
        else:
            esit = gercek == (
                beklenen & 0xFFFFFFFFFFFFFFFF if k not in BAYRAKLAR else beklenen
            )
        if not esit:
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
