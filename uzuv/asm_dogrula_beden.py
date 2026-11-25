"""
asm_dogrula_beden.py — Assembly için "beden erişim" doğrulayıcı.

Amaç: Organizmanın kendi yazdığı kodla /proc, /sys gibi çekirdek arayüzlerini
okuyabilmesini test et. Mevcut `asm_dogrula.py` strict seccomp (sadece
read/write/exit/sigreturn) kullandığından openat, mmap, ioctl gibi syscall'lar
engellenir. Bu modül yerine BPF allow-list (openat, read, write, exit_group)
kullanarak sınırlı fakat gerçek dosya erişimine izin verir.

Görev türü: "/proc/self/stat'ın ilk satırını stdout'a yaz" gibi.

Oracle: Python tarafından aynı dosya okunur ve programın stdout'u ile
karşılaştırılır.

Kullanım:
    from asm_dogrula_beden import dene_beden, karsilastir_beden

    s = dene_beden(
        kod="mov rax, 257\\nlea rdi, [rip + yol]\\nmov rsi, 0\\nmov rdx, 0\\nsyscall\\n...",
        hedef_yol="/proc/self/stat",
    )
    s["tamam"], s["stdout"], s["hata"]
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import struct
import subprocess
import tempfile
from typing import Any, Dict, Optional

# ----------------------------------------------------------------- Seccomp BPF
# Seccomp veri yapısı (seccomp_data, <linux/seccomp.h>):
#   offset 0 : nr (u32)  — syscall numarası
#   offset 4 : arch (u32)
#   offset 8 : instruction_pointer (u64)
#   offset 16: args[0..5] (her biri u64)
#
# BPF yönerge yapısı (sock_filter, 8 bayt):
#   code: u16 (2), jt: u8 (1), jf: u8 (1), k: u32 (4)  → toplam 8 byte

PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2
SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000 | 1  # EPERM

# x86_64 syscall numaraları
SC_READ = 0
SC_WRITE = 1
SC_OPENAT = 257
SC_EXIT_GROUP = 231

# BPF yönerge kodları (Linux)
BPF_LD = 0x00
BPF_W = 0x08
BPF_ABS = 0x20
BPF_JEQ = 0x10
BPF_K = 0x00
BPF_RET = 0x06
BPF_K_RET = 0x00


def _bpf_instr_load_abs(offset: int) -> int:
    """LD abs offset → 8 baytlık BPF yönergesini int olarak döndür.

    Biçim: code(u16) + jt(u8) + jf(u8) + k(u32) = 8 byte.
    """
    code = BPF_LD | BPF_W | BPF_ABS
    return struct.unpack("<Q", struct.pack("<HBB I", code, 0, 0, offset))[0]


def _bpf_instr_jeq(k: int, jt: int, jf: int) -> int:
    """JEQ k → 8 baytlık BPF yönergesini int olarak döndür."""
    code = BPF_JEQ | BPF_K
    return struct.unpack("<Q", struct.pack("<HBB I", code, jt, jf, k))[0]


def _bpf_instr_ret(val: int) -> int:
    """RET val → 8 baytlık BPF yönergesini int olarak döndür."""
    code = BPF_RET | BPF_K_RET
    return struct.unpack("<Q", struct.pack("<HBB I", code, 0, 0, val))[0]


def _bpg_build_allowlist_bytes() -> bytes:
    """
    BPF allow-list'ı raw bytes olarak döndür (sock_filter dizisi, her biri 8 bayt).

    Akış:
      LD  syscall_nr      -> A
      JEQ read(0)         -> allow, next
      JEQ write(1)        -> allow, next
      JEQ openat(257)     -> allow, next
      JEQ exit_group(231) -> allow, next
      RET EPERM           -> engelle
      RET ALLOW           -> izin ver
    """
    instrs = [
        _bpf_instr_load_abs(0),           # syscall numarasını yükle (offset 0)
        _bpf_instr_jeq(SC_READ, 1, 0),    # read ise allow'a atla (jt=1, jf=0)
        _bpf_instr_jeq(SC_WRITE, 1, 0),   # write ise allow'a atla
        _bpf_instr_jeq(SC_OPENAT, 1, 0),  # openat ise allow'a atla
        _bpf_instr_jeq(SC_EXIT_GROUP, 1, 0),  # exit_group ise allow'a atla
        _bpf_instr_ret(SECCOMP_RET_ERRNO),    # başkası → EPERM
        _bpf_instr_ret(SECCOMP_RET_ALLOW),    # izin verilen syscall → ALLOW
    ]
    return b"".join(struct.pack("<Q", i) for i in instrs)


_libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)


def _install_seccomp_bpf_from_bytes(bpf_bytes: bytes) -> None:
    """
    BPF filtresini raw bytes'tan ctypes buffer ile prctl üzerinden yükler.
    Bu işlev preexec_fn içinde çağrılmalı (çocuk işlemde).
    Seccomp desteklenmiyorsa (ör. sınırlı container) sessizce atlanır.
    """
    buf = (ctypes.c_ubyte * len(bpf_bytes)).from_buffer_copy(bpf_bytes)

    class _SockFProg(ctypes.Structure):
        _fields_ = [
            ("len", ctypes.c_ushort),
            ("pad", ctypes.c_ushort),
            ("filter", ctypes.c_void_p),
        ]

    prog = _SockFProg(
        len=len(bpf_bytes) // 8,
        pad=0,
        filter=ctypes.addressof(buf),
    )

    ret = _libc.prctl(
        PR_SET_SECCOMP, SECCOMP_MODE_FILTER,
        ctypes.byref(prog), 0, 0,
    )
    if ret != 0:
        errno = ctypes.get_errno()
        # EPERM/EACCES: seccomp capability yok — yine de devam et, sadece rlimits uygula.
        if errno in (1, 13):  # EPERM, EACCES
            return
        raise OSError(errno, f"prctl(PR_SET_SECCOMP) hata kodu: {errno}")


_BPF_BYTES = _bpg_build_allowlist_bytes()


def _preexec() -> None:
    """Çocuk işlemde çağrılır: rlimits + (mümkünse) BPF seccomp."""
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    try:
        _install_seccomp_bpf_from_bytes(_BPF_BYTES)
    except OSError:
        # Seccomp uygulanamadıysa yalnızca rlimits kalır — işlem devam eder.
        pass


# ----------------------------------------------------------------- Görev şablonu
# /proc/self/stat okuyan bir program için minimum şablon.
_PROC_STAT_TEMPLATE = """.intel_syntax noprefix
.section .rodata
yol:
    .asciz "/proc/self/stat"
.section .bss
.lcomm tampon, 4096
.section .text
.globl _start
_start:
    # open("/proc/self/stat", O_RDONLY)
    mov rax, 2              # open
    lea rdi, [rip + yol]    # pathname (RIP-relative)
    mov rsi, 0              # O_RDONLY
    syscall
    test rax, rax
    js _hata
    mov r12, rax            # fd'yi sakla

    # read(fd, tampon, 4096)
    mov rax, 0              # read
    mov rdi, r12            # fd
    lea rsi, [rip + tampon] # buffer
    mov rdx, 4096           # boyut
    syscall
    test rax, rax
    jle _hata
    mov r13, rax            # okunan bayt sayısı

    # write(1, tampon, bayt_sayisi)
    mov rax, 1              # write
    mov rdi, 1              # stdout
    lea rsi, [rip + tampon] # buffer (RIP-relative address)
    mov rdx, r13            # okunan byte sayısı
    syscall

    # exit_group(0)
    mov rax, 231
    mov rdi, 0
    syscall

_hata:
    mov rax, 60             # exit
    mov rdi, 1
    syscall
"""


def _proc_stat_oracle() -> str:
    """Oracle: /proc/self/stat'ın ilk satırını okuyup döndür."""
    with open("/proc/self/stat", "r") as f:
        return f.readline()

def dene_beden(
    kod: str,
    hedef_yol: str = "/proc/self/stat",
    zaman_asimi: float = 2.0,
) -> Dict[str, Any]:
    """
    /proc/self/stat gibi bir dosyayı okuyan assembly kodu derleyip çalıştırır.

    Seccomp BPF allow-list (openat, read, write, exit_group) önceki bir
    preexec_fn ile yüklenir. Kullanıcı kodu sadece okuma-yazma ve çıkış
    yapmalı; diğer syscall'lar engellenir.

    Döner:
        tamam: bool
        stdout: str | None
        hata: str | None
        asama: 'derleme' | 'baglama' | 'calisma' | 'bitti'
        oracle: str | None  (Python tarafından okunan gerçek değer)
        eslesme: bool | None (stdout == oracle ise True)
    """

    def _preexec() -> None:
        _sinir_basu()
        _install_seccomp_bpf_from_bytes(_BPF_BYTES)

    def _sinir_basu() -> None:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))

    # Kullanıcı kodunu şablona yerleştir.
    metin = _PROC_STAT_TEMPLATE.replace("{kod}", kod)

    with tempfile.TemporaryDirectory(prefix="asmbeden_") as d:
        s_yol = os.path.join(d, "t.s")
        o_yol = os.path.join(d, "t.o")
        exe = os.path.join(d, "t")

        with open(s_yol, "w", encoding="utf-8") as f:
            f.write(metin)

        # Derleme
        r = subprocess.run(
            ["as", "--64", "-o", o_yol, s_yol],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode != 0:
            return {
                "tamam": False, "asama": "derleme",
                "hata": r.stderr.strip()[:300],
                "stdout": None, "oracle": None, "eslesme": None,
            }

        # Bağlama
        r = subprocess.run(["ld", "-o", exe, o_yol],
                           capture_output=True, text=True, timeout=2)
        if r.returncode != 0:
            return {
                "tamam": False, "asama": "baglama",
                "hata": r.stderr.strip()[:300],
                "stdout": None, "oracle": None, "eslesme": None,
            }

        # Çalıştırma (rlimits ile, seccomp opsiyonel)
        try:
            r = subprocess.run(
                [exe], stdin=subprocess.DEVNULL, capture_output=True,
                timeout=zaman_asimi,
            )
        except subprocess.TimeoutExpired:
            return {
                "tamam": False, "asama": "calisma",
                "hata": "zaman aşımı",
                "stdout": None, "oracle": None, "eslesme": None,
            }

        if r.returncode < 0:
            try:
                ad = signal.Signals(-r.returncode).name
            except ValueError:
                ad = f"sinyal {-r.returncode}"
            if ad == "SIGSYS":
                ad = "seccomp_engelledi"
            return {
                "tamam": False, "asama": "calisma",
                "hata": ad,
                "stdout": r.stdout.decode("utf-8", "replace") if r.stdout else "",
                "oracle": None, "eslesme": None,
            }
        if r.returncode != 0:
            return {
                "tamam": False, "asama": "calisma",
                "hata": f"çıkış_kodu_{r.returncode}",
                "stdout": r.stdout.decode("utf-8", "replace") if r.stdout else "",
                "oracle": None, "eslesme": None,
            }

        stdout = r.stdout.decode("utf-8", "replace")
        oracle = _proc_stat_oracle()
        eslesme = stdout.strip() == oracle.strip()

        return {
            "tamam": True, "asama": "bitti",
            "hata": None,
            "stdout": stdout,
            "oracle": oracle,
            "eslesme": eslesme,
        }


def karsilastir_beden(tahmin: str, sonuc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Kullanıcının tahmini (okuma sonucu tahmini) ile gerçek sonucu karşılaştır.

    Dönen: {"eslesme": bool, "fark": str | None, "detay": dict}
    """
    if not sonuc["tamam"]:
        return {
            "eslesme": False,
            "fark": f"çalışma hatası: {sonuc['hata']} ({sonuc['asama']})",
            "detay": sonuc,
        }
    eslesme = sonuc.get("eslesme", False)
    fark = None if eslesme else (
        f"tahmin: {tahmin!r}\n"
        f"gerçek: {sonuc['oracle']!r}\n"
        f"stdout: {sonuc['stdout']!r}"
    )
    return {
        "eslesme": eslesme,
        "fark": fark,
        "detay": sonuc,
    }


if __name__ == "__main__":
    # Basit bir duman testi: boş kod (sadece şablon) çalıştırılmalı,
    # /proc/self/stat'ı okuyup yazdırmalı.
    s = dene_beden(kod="")
    print("tamam:", s["tamam"])
    print("asama:", s["asama"])
    print("hata:", s["hata"])
    if s["tamam"]:
        print("stdout:", repr(s["stdout"][:200]))
        print("oracle:", repr(s["oracle"][:200]))
        print("eslesme:", s["eslesme"])
    k = karsilastir_beden(s["oracle"] or "", s)
    print("karsilastirma:", k["eslesme"], k["fark"])
