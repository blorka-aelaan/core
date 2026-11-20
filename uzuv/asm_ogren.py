"""
asm_ogren.py — x86-64 Assembly öğrenme organı (profesyonel sürüm)

CORE organizmasının ``uzuv`` (Assembly) organı için otomatik program-öğrenme
döngüsü. Sadece Python standard kitaplığı (stdlib) kullanılır.

Mimari
------
- ``Emulator``:      Bellek/rakım/yığın desteği olan hızlı x86-64 emülatörü.
- ``TaskGenerator``: Müfredat (curriculum) tabanlı görev üretir; emülatörle
                     üretir, ``AsmUzuv`` ile gerçek makinede doğrular.
- ``BeamSearchSolver``: Aile ağırlıklarıyla kışmalı arama (beam search) ile
                        çözüm üretir.
- ``WeightTable``:   Bağlamsal op-aile ağırlıkları (isabet / deneme).
- ``LearningState``: Öğrenme durumu (seviye, geçmiş, ağırlıklar) diske
                     kalıcılaşır (atomik yazma).
- ``AssemblyLearner``: Zaman sınırlı öğrenme döngüsünü koordine eder.
- CLI:               ``--dakika``, ``--kiyas``, ``--rapor``, ``--seed``,
                     ``--kok`` seçenekleri.

Kullanım (``uzuv/`` dizininde)::

    python3 asm_ogren.py --dakika 5      # öğren
    python3 asm_ogren.py --kiyas 40      # öğrenilmiş ağırlık vs düz arama
    python3 asm_ogren.py --rapor         # rapor yazdır
    python3 asm_ogren.py --coz-json gorev.json  # örneklerden program ara
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger("asm_ogren")

# Paket olarak içe aktarıldığında (örn. ``from uzuv.asm_ogren import ...``) göreli
# import kullanılır; doğrudan ``python3 asm_ogren.py`` çalıştırıldığında ise
# aynı dizindeki ``asm_uzuv`` modülü bulunur.
try:
    from .asm_uzuv import AsmUzuv  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - doğrudan betik olarak çalıştırıldığında
    from asm_uzuv import AsmUzuv  # type: ignore[no-redef,import-not-found]


# --------------------------------------------------------------------------- Sabitler

MASK: int = (1 << 64) - 1
"""64 bitlik maske: x86-64 register sıfırlama sınırı."""

REGISTERS: Tuple[str, ...] = (
    "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
    "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
)
"""Tam x86-64 genel amaçlı yazmaç kümesi (System V AMD64 ABI)."""

IMMEDIATES: Tuple[int, ...] = (1, 2, 3, 5, 10)
INPUT_POOL: Tuple[int, ...] = (
    0, 1, 2, 3, 5, 7, 10, -3, 100, 255,
    (1 << 63) - 1, 1 << 63, MASK - 1, MASK,
)
STACK_SIZE: int = 256
MAX_MEMORY_BYTES: int = 2 * 1024 * 1024 * 1024
MAX_STEPS: int = 1000
BEAM_WIDTH: int = 128
CURRICULUM_MAX_LEVEL: int = 4

# System V AMD64 çağrı kuralı: ilk 6 tamsayı argümanı.
ARG_REGISTER: Tuple[str, ...] = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")

MEMORY_ADDRESS_PATTERNS: Tuple[str, ...] = (
    "[rax]", "[rbx]", "[rcx]", "[rdx]", "[rsi]", "[rdi]", "[r8]", "[r9]",
    "[rip + veri]", "[rip + veri + 8]",
)

BINARY_OPS: Dict[str, Callable[[int, int], int]] = {
    "add": lambda a, b: (a + b) & MASK,
    "sub": lambda a, b: (a - b) & MASK,
    "imul": lambda a, b: (a * b) & MASK,
    "and": lambda a, b: a & b,
    "or": lambda a, b: a | b,
    "xor": lambda a, b: a ^ b,
}

UNARY_OPS: Dict[str, Callable[[int], int]] = {
    "inc": lambda a: (a + 1) & MASK,
    "dec": lambda a: (a - 1) & MASK,
    "neg": lambda a: (-a) & MASK,
    "not": lambda a: (~a) & MASK,
}

OP = Tuple[str, str, Callable[[Dict[str, Any]], None]]
"""``(aile_ön_ek, kod_satırı, durum_mutasyon_fonksiyonu)`` üçlüsü."""

__all__ = [
    "MASK", "REGISTERS", "INPUT_POOL", "BEAM_WIDTH", "CURRICULUM_MAX_LEVEL",
    "OP", "CurriculumLevel", "Task", "SolveResult", "WeightTable",
    "LearningState", "Emulator", "TaskGenerator", "BeamSearchSolver",
    "AssemblyLearner", "build_ops", "ops_for_level", "context_key",
    "_gorev_ozellik_vektoru", "main",
]

# --------------------------------------------------------------------------- Yardımcılar

_REGISTER_RE = re.compile(
    r"\b(rax|rbx|rcx|rdx|rsi|rdi|rbp|rsp|r8|r9|r10|r11|r12|r13|r14|r15)\b"
)
def _extract_registers(code: str) -> List[str]:
    """Assembly kod satırından kullanılan yazmaç isimlerini çıkarır."""
    return _REGISTER_RE.findall(code)


def _family_of(code: str) -> Optional[str]:
    """Kod satırına karşılık gelen op ailesini döndürür."""
    op = _CODE_TO_OP.get(code)
    return op[0] if op else None


# --- Durum mutasyonu yardımcıları (her biri bir Op fonksiyonu üretir) ---

def _mov_reg(dest: str, src: str) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = state[src]

    return fn


def _mov_imm(dest: str, value: int) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = value & MASK

    return fn


def _binary_op(dest: str, src: str,
               op: Callable[[int, int], int]) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = op(state[dest], state[src])

    return fn


def _binary_imm(dest: str, value: int,
                op: Callable[[int, int], int]) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = op(state[dest], value)

    return fn


def _lea(dest: str, src: str, scale: int) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = (state[src] * (1 + scale)) & MASK

    return fn


def _shift_imm(dest: str, value: int, left: bool) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        if left:
            state[dest] = (state[dest] << value) & MASK
        else:
            state[dest] = state[dest] >> value

    return fn


def _unary(dest: str, op: Callable[[int], int]) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[dest] = op(state[dest]) & MASK

    return fn


class SparseMemory:
    """2 GiB sanal adres sınırına sahip, yalnızca erişilen baytları saklayan bellek."""

    def __init__(
        self,
        initial: Optional[Any] = None,
        limit: int = MAX_MEMORY_BYTES,
    ) -> None:
        if not 0 < limit <= MAX_MEMORY_BYTES:
            raise ValueError(f"memory limit must be between 1 and {MAX_MEMORY_BYTES}")
        self.limit = limit
        self.data: Dict[int, int] = {}
        self.touched: Set[int] = set()
        if initial is None:
            return
        items = initial.items() if isinstance(initial, dict) else enumerate(initial)
        for address, value in items:
            if isinstance(address, bool) or not isinstance(address, int):
                raise ValueError("memory addresses must be integers")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError("memory values must be bytes")
            if not 0 <= address < limit:
                raise ValueError("initial memory address is out of bounds")
            if value:
                self.data[address] = value

    def _check(self, address: int, size: int) -> None:
        if address < 0 or address + size > self.limit:
            raise IndexError("memory access out of bounds")
        self.touched.update(range(address, address + size))

    def read_u64(self, address: int) -> int:
        self._check(address, 8)
        return sum(
            self.data.get(address + offset, 0) << (offset * 8)
            for offset in range(8)
        )

    def write_u64(self, address: int, value: int) -> None:
        self._check(address, 8)
        for offset, byte in enumerate((value & MASK).to_bytes(8, "little")):
            if byte:
                self.data[address + offset] = byte
            else:
                self.data.pop(address + offset, None)

    def snapshot(self) -> Dict[int, int]:
        return {address: self.data.get(address, 0) for address in sorted(self.touched)}


def _mem_write_imm(ra: str, value: int) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state["bellek"].write_u64(state[ra], value)

    return fn


def _mem_read_reg(ra: str, rb: str) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state[ra] = state["bellek"].read_u64(state[rb])

    return fn


def _mem_write_reg(ra: str, rb: str) -> Callable[[Dict[str, Any]], None]:
    def fn(state: Dict[str, Any]) -> None:
        state["bellek"].write_u64(state[ra], state[rb])

    return fn


# --------------------------------------------------------------------------- Op tablosu

def build_ops() -> List[OP]:
    """Tüm desteklenen (aile, kod, fonksiyon) op üçlüsünü döndürür."""
    ops: List[OP] = []

    def add(prefix: str, code: str,
            fn: Callable[[Dict[str, Any]], None]) -> None:
        ops.append((prefix, code, fn))

    # --- Register ⇄ Register / Register ⇄ Immidiate ---
    for dest in REGISTERS:
        for src in REGISTERS:
            if dest != src:
                add("mov:rr", f"mov {dest}, {src}", _mov_reg(dest, src))
            for mnemonic, op in BINARY_OPS.items():
                add(f"{mnemonic}:rr", f"{mnemonic} {dest}, {src}",
                    _binary_op(dest, src, op))
            for scale in (1, 2, 4, 8):
                add("lea:r", f"lea {dest}, [{src} + {src}*{scale}]",
                    _lea(dest, src, scale))
        for value in IMMEDIATES:
            add("mov:ri", f"mov {dest}, {value}", _mov_imm(dest, value))
            for mnemonic, op in BINARY_OPS.items():
                add(f"{mnemonic}:ri", f"{mnemonic} {dest}, {value}",
                    _binary_imm(dest, value, op))
        for value in (1, 2, 3):
            add("shl:ri", f"shl {dest}, {value}", _shift_imm(dest, value, True))
            add("shr:ri", f"shr {dest}, {value}", _shift_imm(dest, value, False))
        for mnemonic, op in UNARY_OPS.items():
            add(f"{mnemonic}:r", f"{mnemonic} {dest}", _unary(dest, op))

    # --- Bellek erişimi (2 GiB sınır içinde seyrek bellek) ---
    for ra in REGISTERS:
        add("mov:[ra]-imm5", f"mov [{ra}], 5", _mem_write_imm(ra, 5))
        add("mov:[ra]-imm10", f"mov [{ra}], 10", _mem_write_imm(ra, 10))
        for rb in REGISTERS:
            add("mov:ra-[rb]", f"mov {ra}, [{rb}]", _mem_read_reg(ra, rb))
            add("mov:[ra]-rb", f"mov [{ra}], {rb}", _mem_write_reg(ra, rb))

    # --- Bayrak işlemleri (yazmacı değiştirmez, sadece ZF/CF/OF) ---
    def _cmp(state: Dict[str, Any], ra: str, rb: str) -> None:
        fark = (state[ra] - state[rb]) & MASK
        state["ZF"] = 1 if fark == 0 else 0
        state["CF"] = 1 if state[ra] < state[rb] else 0
        state["OF"] = 1 if (((state[ra] ^ state[rb]) & (1 << 63))
                            and ((state[ra] ^ fark) & (1 << 63))) else 0

    def _test(state: Dict[str, Any], ra: str, rb: str) -> None:
        sonuc = state[ra] & state[rb]
        state["ZF"] = 1 if sonuc == 0 else 0
        state["CF"] = 0
        state["OF"] = 0

    for ra in REGISTERS:
        for rb in REGISTERS:
            add("cmp:rr", f"cmp {ra}, {rb}",
                lambda state, ra=ra, rb=rb: _cmp(state, ra, rb))
            add("test:rr", f"test {ra}, {rb}",
                lambda state, ra=ra, rb=rb: _test(state, ra, rb))

    # --- Etiket ve atlama (pc tabanlı akış kontrolü) ---
    LABELS = ("dongu", "son", "baslangic", "kontrol", "cikis")
    for etiket in LABELS:
        add(f"label:{etiket}", f"{etiket}:",
            lambda state, etiket=etiket: None)

    for etiket in LABELS:
        add("jmp", f"jmp {etiket}",
            lambda state, etiket=etiket: state.__setitem__(
                "pc", state["_label_pos"].get(etiket, state["pc"] + 1)))
        add("jz", f"jz {etiket}",
            lambda state, etiket=etiket: state.__setitem__(
                "pc", state["_label_pos"].get(etiket, state["pc"] + 1))
            if state["ZF"] == 1 else None)
        add("jnz", f"jnz {etiket}",
            lambda state, etiket=etiket: state.__setitem__(
                "pc", state["_label_pos"].get(etiket, state["pc"] + 1))
            if state["ZF"] == 0 else None)

    # --- Yığın işlemleri (push, pop, call, ret) ---
    for ra in REGISTERS:
        add(f"push:{ra}", f"push {ra}",
            lambda state, ra=ra: (
                state["yigin"].append(state[ra]),
                state.__setitem__("rsp", (state["rsp"] - 8) & MASK))) # type: ignore
        add(f"pop:{ra}", f"pop {ra}",
            lambda state, ra=ra: (
                state.__setitem__(ra, state["yigin"].pop()),
                state.__setitem__("rsp", (state["rsp"] + 8) & MASK))
            if state["yigin"] else None) # type: ignore

    for etiket in LABELS:
        add(f"call:{etiket}", f"call {etiket}",
            lambda state, etiket=etiket: (
                state["yigin"].append(state["pc"] + 1),
                state.__setitem__("pc", state["_label_pos"].get(etiket, state["pc"] + 1)))) # type: ignore
    add("ret", "ret",
        lambda state: state.__setitem__("pc", state["yigin"].pop())
        if state["yigin"] else None)

    # --- Sistem çağrısı (syscall): exit(60), write(1) ---
    def _syscall(state: Dict[str, Any]) -> None:
        no = state["rax"]
        if no == 60:  # exit
            state["_exit_code"] = state.get("rdi", 0)
            state["_halt"] = True
        elif no == 1:  # write
            fd = state.get("rdi", 0)
            cnt = state.get("rdx", 0)
            if fd == 1 and cnt > 0:
                state["_wrote"] = state.get("_wrote", 0) + cnt
        else:
            state["_unsupported_syscall"] = no

    add("syscall", "syscall", _syscall)

    return ops


OPS: List[OP] = build_ops()
AILELER: Dict[str, List[Tuple[str, Callable[[Dict[str, Any]], None]]]] = {}
_CODE_TO_OP: Dict[str, OP] = {}
for _prefix, _code, _fn in OPS:
    AILELER.setdefault(_prefix, []).append((_code, _fn))
    _CODE_TO_OP[_code] = (_prefix, _code, _fn)

# --------------------------------------------------------------------------- Müfredat (curriculum)


@dataclass(frozen=True)
class CurriculumLevel:
    """Bir müfredat seviyesinin yapılandırması."""

    level: int
    """Seviye numarası (1..CURRICULUM_MAX_LEVEL)."""

    name: str
    """İnsan tarafından okunabilir seviye adı."""

    registers: Tuple[str, ...]
    """İzin verilen yazmaçlar."""

    op_prefixes: Tuple[str, ...]
    """Bu seviyede kullanıma açılan op-ön ekleri."""

    memory: bool = False
    """Bellek erişimine izin verilsin mi."""

    flags: bool = False
    """Bayrak işlemlerine izin verilsin mi."""

    jumps: bool = False
    """Atlama/etiketlere izin verilsin mi."""

    stack: bool = False
    """Yığın işlemlerine izin verilsin mi."""

    syscall: bool = False
    """Sistem çağrısına izin verilsin mi."""

    max_instructions: int = 5
    """Programda izin verilen maksimum komut sayısı."""

    def allowed_registers(self) -> Set[str]:
        return set(self.registers)


def _curriculum() -> Dict[int, CurriculumLevel]:
    return {
        1: CurriculumLevel(
            1, "Temel aritmetik", ("rax", "rbx"),
            ("mov:rr", "mov:ri", "add:rr", "add:ri", "sub:rr", "sub:ri",
             "xor:rr", "xor:ri", "and:rr", "and:ri", "or:rr", "or:ri",
             "neg:r", "not:r", "inc:r", "dec:r", "shl:ri", "shr:ri"),
            max_instructions=5,
        ),
        2: CurriculumLevel(
            2, "4 yazmaç + bellek + bayrak", ("rax", "rbx", "rcx", "rdx"),
            ("mov:rr", "mov:ri", "mov:ra-[rb]", "mov:[ra]-rb",
             "add:rr", "add:ri", "sub:rr", "sub:ri",
             "xor:rr", "xor:ri", "and:rr", "and:ri", "or:rr", "or:ri",
             "neg:r", "not:r", "inc:r", "dec:r", "shl:ri", "shr:ri",
             "cmp:rr", "test:rr"),
            memory=True, flags=True, max_instructions=6,
        ),
        3: CurriculumLevel(
            3, "8 yazmaç + bayrak (bellek yok)",
            ("rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp"),
            ("mov:rr", "mov:ri", "add:rr", "add:ri", "sub:rr", "sub:ri",
             "xor:rr", "xor:ri", "and:rr", "and:ri", "or:rr", "or:ri",
             "neg:r", "not:r", "inc:r", "dec:r", "shl:ri", "shr:ri",
             "cmp:rr", "test:rr"),
            flags=True, max_instructions=10,
        ),
        4: CurriculumLevel(
            4, "Tam x86-64 (16 yazmaç + yığın + syscall + atlamalar)", REGISTERS,
            ("mov:rr", "mov:ri", "mov:ra-[rb]", "mov:[ra]-rb",
             "mov:[ra]-imm5", "mov:[ra]-imm10",
             "add:rr", "add:ri", "sub:rr", "sub:ri", "imul:rr", "imul:ri",
             "xor:rr", "xor:ri", "and:rr", "and:ri", "or:rr", "or:ri",
             "neg:r", "not:r", "inc:r", "dec:r", "shl:ri", "shr:ri", "lea:r",
             "cmp:rr", "test:rr",
             "push:", "pop:", "call:", "ret",
             "jmp", "jz", "jnz", "label:",
             "syscall"),
            memory=True, flags=True, jumps=True, stack=True, syscall=True,
            max_instructions=10,
        ),
    }


CURRICULUM: Dict[int, CurriculumLevel] = _curriculum()


def ops_for_level(level: int, all_ops: Sequence[OP],
                  curriculum: Dict[int, CurriculumLevel]) -> List[OP]:
    """Belirli seviyeye uygun op'ları filtreler (yazmaç isimleri de kontrol edilir)."""
    cfg = curriculum[level]
    prefixes = cfg.op_prefixes
    allowed = set(cfg.registers)
    result: List[OP] = []
    for prefix, code, fn in all_ops:
        eslesiyor = any(prefix.startswith(oek) or code.startswith(oek)
                        for oek in prefixes)
        if not eslesiyor:
            continue
        kod_yazmaclari = set(_extract_registers(code))
        if kod_yazmaclari and not kod_yazmaclari.issubset(allowed):
            continue
        result.append((prefix, code, fn))
    return result


@dataclass
class Task:
    """Öğrenme görevi: gizli programın (girdi → çıktı) eşlemesi."""

    level: int
    length: int
    program: List[OP]
    code: str
    training: List[Dict[str, Any]]
    secret: List[Dict[str, Any]]


@dataclass
class SolveResult:
    """Bir görevin çözüm sonucu."""

    solved: bool
    program: Optional[List[str]]
    attempts: int
    emulator_mismatch: int
    attempts_detail: Dict[str, int]
    successful_detail: Dict[str, int]
    timed_out: bool = False


# --------------------------------------------------------------------------- Bağlam anahtarı


def _iliski_turu(training: Sequence[Dict[str, Any]]) -> str:
    """Her çıktı kaydının hangi basit işlemle üretildiği tahmini.

    Harfler: a=aynı, +=artır, -=azalt, 0=sıfırla, n=not, ?=diğer
    """
    out: List[str] = []
    for row in training:
        # DÜZELTME: 'input' alt anahtarı yoksa doğrudan row'un kendisini kullan
        girdi = row.get("input", row)
        çıkış = row.get("cikti", {})
        türler: List[str] = []
        for reg in REGISTERS:
            if reg == "rsp":
                continue
            v_in = int(girdi.get(reg, 0)) & MASK
            v_out = int(çıkış.get(reg, v_in)) & MASK
            if v_out == v_in:
                türler.append("a")
            elif v_out == (v_in + 1) & MASK:
                türler.append("+")
            elif v_out == (v_in - 1) & MASK:
                türler.append("-")
            elif v_out == 0:
                türler.append("0")
            elif v_out == (~v_in) & MASK:
                türler.append("n")
            else:
                türler.append("?")
        out.append("".join(türler))
    return ",".join(out)


def context_key(training: Sequence[Dict[str, Any]]) -> tuple[str, str]:
    """(fine_context, coarse_context) ikilisi döndürür.

    fine: mevcut özel yazmaç/bayrak imzası.
    coarse: seviye + işlem türü kalıbı (görülmemiş görevlerde fallback).
    """
    registers = tuple(
        register for register in REGISTERS if register != "rsp"
        and all(register in row and register in row["cikti"] for row in training)
    )
    flags = tuple(
        flag for flag in ("ZF", "CF", "OF")
        if all(flag in row["cikti"] for row in training)
    )
    features: List[bool] = []

    for dest in registers:
        inputs = [row[dest] & MASK for row in training]
        outputs = [row["cikti"][dest] & MASK for row in training]
        features.extend((
            len({(out - value) & MASK for value, out in zip(inputs, outputs)}) == 1,
            all(value == out for value, out in zip(inputs, outputs)),
            len(set(outputs)) == 1,
            any(out == 0 for out in outputs),
            all(out & ~value & MASK == 0 for value, out in zip(inputs, outputs)),
        ))
        for src in registers:
            source = [row[src] & MASK for row in training]
            features.append(all(
                out == value for value, out in zip(source, outputs)
            ))
            features.append(all(
                out == ((own + value) & MASK)
                for own, value, out in zip(inputs, source, outputs)
            ))

    for flag in flags:
        values = [row["cikti"][flag] for row in training]
        features.extend((len(set(values)) == 1, any(values)))

    registers_key = ",".join(registers)
    flags_key = ",".join(flags)
    bits = "".join("1" if feature else "0" for feature in features)
    fine = f"v2:r[{registers_key}]:f[{flags_key}]:{bits}"
    coarse = f"v3:L:{_iliski_turu(training)}"
    return fine, coarse


def _gorev_ozellik_vektoru(training: Sequence[Dict[str, Any]],
                           level: int,
                           length: int) -> list[float]:
    """Göreve özgü 48 boyutlu özellik vektörü üretir.

    Dağılım:
      0-3:    Seviye one-hot (4 bit)
      4-9:    İlişki türü karakterleri (a,+,-,0,n,?) → 6 bit
      10-25:  Kullanılan yazmaçlar (16 bit)
      26-28:  Bayrak kullanımı (ZF, CF, OF) → 3 bit
      29-33:  Eğitim örneği sayısı (normalize) → 5 bit
      34-38:  Komut uzunluğu (normalize) → 5 bit
      39-43:  Çıktı değişim oranı → 5 bit
      44-47:  Bellek erişimi varlığı → 4 bit
    """
    v = [0.0] * 48

    # 0-3: Seviye one-hot
    lv = min(max(level, 1), 4)
    v[lv - 1] = 1.0

    # 4-9: İlişki türü (a=aynı, +=artır, -=azalt, 0=sıfırla, n=not, ?=diğer)
    iliski = _iliski_turu(training)
    iliski_map = {"a": 4, "+": 5, "-": 6, "0": 7, "n": 8, "?": 9}
    for ch in iliski:
        if ch in iliski_map:
            v[iliski_map[ch]] = 1.0

    # 10-25: Yazmaç kullanımı
    for example in training:
        for i, reg in enumerate(REGISTERS):
            if reg in example:
                v[10 + i] = 1.0

    # 26-28: Bayrak kullanımı (ZF, CF, OF)
    for i, flag in enumerate(("ZF", "CF", "OF")):
        if any(flag in ex["cikti"] for ex in training):
            v[26 + i] = 1.0

    # 29-33: Eğitim örneği sayısı (normalize)
    n_examples = min(len(training), 31) / 31.0
    for i in range(5):
        if n_examples > (i + 1) / 5.0:
            v[29 + i] = 1.0

    # 34-38: Komut uzunluğu (normalize)
    length_n = min(length, 31) / 31.0
    for i in range(5):
        if length_n > (i + 1) / 5.0:
            v[34 + i] = 1.0

    # 39-43: Çıktı değişim oranı (girişten farklı çıkış oranı)
    changed = 0
    total = 0
    for ex in training:
        for reg in REGISTERS:
            if reg in ex and reg in ex["cikti"]:
                total += 1
                if ex[reg] != ex["cikti"][reg]:
                    changed += 1
    change_ratio = changed / max(total, 1)
    for i in range(5):
        if change_ratio > (i + 1) / 5.0:
            v[39 + i] = 1.0

    # 44-47: Bellek erişimi varlığı
    has_memory = any(
        "[" in str(ex.get("cikti", {})) for ex in training
    )
    if has_memory:
        v[44] = 1.0
    # 45-47: Kullanılmadı (geçiş için)

    return v


# --------------------------------------------------------------------------- Ağırlık tablosu


@dataclass
class WeightTable:
    """Bağlamsal op-aile ağırlıkları: {baglam: {aile: [isabet, deneme]}}.

    Ağırlık = (isabet + 1) / (deneme + 10). Görülmemiş bağlamda hepsi eşittir.
    """

    records: Dict[str, Dict[str, List[int]]] = field(default_factory=dict)

    def weights(self, ctx_fine: str, families: Sequence[str],
                ctx_coarse: Optional[str] = None) -> Dict[str, float]:
        """Her aile için normalized ağırlık döndürür."""
        row = self.records.get(ctx_fine, {})
        sonuç: Dict[str, float] = {}
        for a in families:
            w = (row.get(a, [0, 0])[0] + 1) / (row.get(a, [0, 0])[1] + 10)
            sonuç[a] = max(w, 0.05)  # Alt sınır: başarısızlıkla ağırlık sıfıra yaklaşmasın

        # DÜZELTME: Varsayılan ağırlık 0.1 olduğu için 'not row' kontrolü ile coarse'a düş
        if ctx_coarse is not None and not row:
            row_coarse = self.records.get(ctx_coarse, {})
            if row_coarse:
                for a in families:
                    w = (row_coarse.get(a, [0, 0])[0] + 1) / (
                        row_coarse.get(a, [0, 0])[1] + 10
                    )
                    sonuç[a] = max(w, 0.05)
        return sonuç

    def record_attempts(self, ctx: str, attempts: Dict[str, Tuple[int, int]]) -> None:
        """Deneme ve başarı sayılarını kaydeder.

        attempts = {aile: (successful_attempts, total_attempts)}
        row = [0] = başarılı deneme sayısı, [1] = toplam deneme sayısı
        """
        row = self.records.setdefault(ctx, {})
        for aile, (successful, total) in attempts.items():
            row.setdefault(aile, [0, 0])[0] += successful
            row.setdefault(aile, [0, 0])[1] += total


# --------------------------------------------------------------------------- Nöral beyin entegrasyonu (nn_ana rehberi)


def _prefix_to_nn_category(prefix: str) -> str:
    """Detaylı op ön ekini (örn. 'add:rr', 'mov:[ra]-rb') nn_ana kategorisine çevirir."""
    if "[" in prefix:
        return "memory"
    base = prefix.split(":", 1)[0]
    if base == "mov":
        return "mov"
    if base in ("add", "sub", "imul", "lea"):
        return "arithmetic"
    if base in ("and", "or", "xor"):
        return "logic"
    if base in ("shl", "shr"):
        return "shift"
    if base in ("inc", "dec", "neg", "not"):
        return "unary"
    if base in ("cmp", "test", "jmp", "jz", "jnz", "call", "ret", "push", "pop", "syscall", "label"):
        return "control"
    return "other"


def nn_predict_op_weights(
    nn_ana,
    stim_features: list[float],
    families: Sequence[str],
) -> dict[str, float]:
    """nn_ana'dan op ailesi öncelik skorları döndürür."""
    if nn_ana is None:
        return {a: 0.5 for a in families}

    vektor = [0.0] * 48
    for i, val in enumerate(stim_features[:48]):
        vektor[i] = max(0.0, min(1.0, float(val)))

    raw_outputs = nn_ana.ileri_geçiş(vektor)   # dönüş değeri: paylaşılan duruma bakma

    category_scores = {
        "control":    float(raw_outputs[0]) if len(raw_outputs) > 0 else 0.5,
        "mov":        float(raw_outputs[2]) if len(raw_outputs) > 2 else 0.5,
        "arithmetic": float(raw_outputs[2]) if len(raw_outputs) > 2 else 0.5,
        "logic":      float(raw_outputs[2]) if len(raw_outputs) > 2 else 0.5,
        "shift":      float(raw_outputs[2]) if len(raw_outputs) > 2 else 0.5,
        "unary":      float(raw_outputs[2]) if len(raw_outputs) > 2 else 0.5,
        "memory":     float(raw_outputs[3]) if len(raw_outputs) > 3 else 0.5,
        "other":      float(raw_outputs[4]) if len(raw_outputs) > 4 else 0.5,
    }

    # DÜZELTME: Her op ön ekini kendi kategorisine eşle
    return {
        a: max(0.0, min(1.0, category_scores[_prefix_to_nn_category(a)]))
        for a in families
    }


class NNWeightBlender:
    """WeightTable ile nn_ana tahminlerini karıştıran sarmalayıcı.

    BeamSearchSolver, weights.weights(ctx, families) çağırır.
    Bu sınıf aynı arayüzü sunarken, mevcut deneyim ağırlıklarını
    nn_ana'nın tahminleriyle blend eder.
    """

    def __init__(
        self,
        weight_table,
        nn_ana,
        stim_features: list[float],
        alpha: float = 0.6,
    ):
        self.weight_table = weight_table
        self.nn_ana = nn_ana
        self.stim_features = list(stim_features or [0.0] * 48)
        self.alpha_base = max(0.0, min(1.0, alpha))  # başlangıç nn_ana etkisi
        self.alpha = self.alpha_base
        self._nn_cache: dict[str, dict[str, float]] = {}
        self._success_count = 0
        self._total_count = 0

    def set_context_keys(self, ctx_fine: str, ctx_coarse: str) -> None:
        """Solver'dan gelen fine ve coarse bağlam anahtarlarını kaydeder."""
        self._ctx_fine = ctx_fine
        self._ctx_coarse = ctx_coarse

    def report_result(self, success: bool) -> None:
        """Başarı/başarısızlığı kaydeder ve alpha'yı dinamik ayarlar.

        Başarı oranı yüksekse nn_ana'ya daha çok güven (alpha artar),
        düşükse WeightTable deneyimine daha çok güven (alpha azalır).
        """
        self._total_count += 1
        if success:
            self._success_count += 1
        oran = self._success_count / max(1, self._total_count)
        # alpha: 0.3 (düşük güven) ile 0.9 (yüksek güven) arasında
        self.alpha = max(0.3, min(0.9, 0.3 + 0.6 * oran))

    def weights(self, ctx: str, families: Sequence[str],
                ctx_coarse: Optional[str] = None) -> Dict[str, float]:
        """nn_ana ile blend edilmiş ağırlıklar döndürür.

        ctx, solver tarafından fine bağlam string'i olarak gelir.
        ctx_coarse, solver tarafından opsiyonel coarse bağlam string'i.
        """
        base = self.weight_table.weights(ctx, families, ctx_coarse)

        # nn_ana tahminlerini fine ctx'e göre cache'le
        cache_key = ctx
        if cache_key not in self._nn_cache:
            self._nn_cache[cache_key] = nn_predict_op_weights(
                self.nn_ana, self.stim_features, list(families)
            )
        nn_weights = self._nn_cache[cache_key]

        blended: Dict[str, float] = {}
        for a in families:
            w_base = float(base.get(a, 0.5))
            w_nn = float(nn_weights.get(a, 0.5))
            blended[a] = (1.0 - self.alpha) * w_base + self.alpha * w_nn
        return blended


# --------------------------------------------------------------------------- Kalıcı durum


@dataclass
class LearningState:
    """Kalıcı öğrenme durumu (asm_ogren.json)."""

    path: Path
    weights: WeightTable = field(default_factory=WeightTable)
    history: List[Dict[str, Any]] = field(default_factory=list)
    max_length: int = 1
    max_level: int = 1
    total_tasks: int = 0
    failures: Dict[str, Set[Tuple[str, ...]]] = field(default_factory=dict)
    primitives: Dict[str, List[str]] = field(default_factory=dict)
    programs: Dict[str, List[List[str]]] = field(default_factory=dict)

    def load(self) -> None:
        """Disktan durumu yükler; dosya yoksa/bozuksa sessizce geri dönülür."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.max_length = data.get("max_length", 1)
        self.max_level = data.get("max_level", 1)
        self.total_tasks = data.get("total_tasks", 0)
        raw_failures = data.get("failures", {})
        self.failures = {
            k: {tuple(x) for x in v} for k, v in raw_failures.items()
        }
        self.primitives = data.get("primitives", {})
        raw_programs = data.get("programs", {})
        self.programs = {
            ctx: [
                list(program) for program in candidates
                if isinstance(program, list)
                and all(isinstance(line, str) for line in program)
            ]
            for ctx, candidates in raw_programs.items()
            if isinstance(ctx, str) and isinstance(candidates, list)
        } if isinstance(raw_programs, dict) else {}
        self.weights.records = data.get("bagil", {})
        self.history = data.get("gecmis", [])

    def save(self, keep_history: int = 300) -> None:
        """Durumu atomik olarak diske yazar (geçmişi son ``keep_history``'ye kırpır)."""
        payload = {
            "bagil": self.weights.records,
            "gecmis": self.history[-keep_history:],
            "max_length": self.max_length,
            "max_level": self.max_level,
            "total_tasks": self.total_tasks,
            "failures": {k: [list(x) for x in v] for k, v in self.failures.items()},
            "primitives": self.primitives,
            "programs": self.programs,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self.path)


# --------------------------------------------------------------------------- Emülatör


class Emulator:
    """Hızlı, bellek/bayrak/yığın desteği olan x86-64 emülatörü.

    Durum sözlüğü: yazmaçlar + ZF/CF/OF + pc + bellek + yigin + rsp +
    _label_pos + _halt.
    """

    def __init__(self, registers: Sequence[str] = REGISTERS) -> None:
        self.registers = tuple(registers)

    def label_positions(self, program: Sequence[OP]) -> Dict[str, int]:
        """Programdaki ``label:<isim>`` işlemlerinin konum haritası."""
        positions: Dict[str, int] = {}
        for index, (prefix, _code, _fn) in enumerate(program):
            if prefix.startswith("label:"):
                positions[prefix[len("label:"):]] = index
        return positions

    def fresh_state(self, initial: Dict[str, int],
                    label_positions: Dict[str, int],
                    initial_memory: Optional[Any] = None) -> Dict[str, Any]:
        state: Dict[str, Any] = {r: initial.get(r, 0) & MASK for r in self.registers}
        state.update({
            "ZF": 0, "CF": 0, "OF": 0,
            "pc": 0, "_halt": False,
            "bellek": SparseMemory(initial_memory),
            "yigin": [],
            "rsp": 0x7FFF,
            "_label_pos": label_positions,
        })
        return state

    def run(self, program: Sequence[OP], initial: Dict[str, int],
            max_steps: int = MAX_STEPS,
            include_flags: bool = False,
            initial_memory: Optional[Any] = None,
            include_memory: bool = False) -> Optional[Dict[str, Any]]:
        """Programı çalıştırır; gerekirse bayrak ve bellek çıktısını da döndürür.

        Sonsuz döngü tespit edilirse ``None`` döner. ``rsp`` çıktıdan
        hariç tutulur (yığın işaretçisi iç durum tutulur).
        """
        labels = self.label_positions(program)
        state = self.fresh_state(initial, labels, initial_memory)
        steps = 0
        while (0 <= state["pc"] < len(program)
               and steps < max_steps
               and not state.get("_halt", False)):
            prev_pc = state["pc"]
            _, _, fn = program[state["pc"]]
            try:
                fn(state)
            except IndexError:
                return None
            if state["pc"] == prev_pc:
                state["pc"] += 1  # normal akış: bir sonraki komuta geç
            steps += 1
        if steps >= max_steps:
            return None  # sonsuz döngü
        result = {r: state[r] & MASK for r in self.registers if r != "rsp"}
        if include_flags:
            result.update({flag: state[flag] for flag in ("ZF", "CF", "OF")})
        if include_memory:
            result["bellek"] = state["bellek"].snapshot()
        return result

    def matches(self, program: Sequence[OP], examples: Sequence[Dict[str, Any]],
                registers: Sequence[str]) -> bool:
        """Programın tüm örnekler için doğru çıkış üretip üretmediğini döndürür."""
        for example in examples:
            initial = {r: example[r] for r in registers}
            expected = example["cikti"]
            result = self.run(
                program, initial,
                include_flags=any(flag in expected for flag in ("ZF", "CF", "OF")),
                initial_memory=example.get("bellek_girdi"),
                include_memory="bellek" in expected,
            )
            if result is None:
                return False
            if any(result[key] != expected[key] for key in expected):
                return False
        return True

    def score(self, program: Sequence[OP], examples: Sequence[Dict[str, Any]],
              registers: Sequence[str]) -> float:
        """Doğru çıkış üreten örnek sayısını döndürür (daha yüksek = daha iyi).

        Tam eşleşme için 1.0, kısmi eşleşme için 0.5 * (tutan / toplam) puan.
        """
        points = 0.0
        for example in examples:
            initial = {r: example[r] for r in registers}
            expected = example["cikti"]
            result = self.run(
                program, initial,
                include_flags=any(flag in expected for flag in ("ZF", "CF", "OF")),
                initial_memory=example.get("bellek_girdi"),
                include_memory="bellek" in expected,
            )
            if result is None:
                continue
            tutan = sum(1 for key in expected if result[key] == expected[key])
            if tutan == len(expected):
                points += 1.0
            else:
                # Kısmi eşleşme bonusu (tam çözümden her zaman küçük kalır)
                points += 0.5 * (tutan / max(1, len(expected)))
        return points


# --------------------------------------------------------------------------- Görev üretimi


class TaskGenerator:
    """Müfredat bazlı görev üretir; emülatörle üretir, AsmUzuv ile doğrular."""

    def __init__(self, emulator: Emulator, ops: Sequence[OP],
                 curriculum: Dict[int, CurriculumLevel]) -> None:
        self.emulator = emulator
        self.ops = ops
        self.curriculum = curriculum

    def _selected_ops(self, level: int) -> List[OP]:
        return ops_for_level(level, self.ops, self.curriculum)

    def _reducible(self, examples: Sequence[Dict[str, Any]], length: int,
                   registers: Sequence[str],
                   selected_ops: Optional[Sequence[OP]] = None,
                   deadline: Optional[float] = None) -> bool:
        """Tek komutluk bir program aynı davranışı veriyorsa görev o kadar uzun değil."""
        if length <= 1:
            return False
        ops_list = selected_ops if selected_ops is not None else self.ops
        for prefix, code, fn in ops_list:
            if deadline is not None and time.monotonic() >= deadline:
                return False
            if self.emulator.matches([(prefix, code, fn)], examples, registers):
                return True
        return False

    def generate(self, asm: AsmUzuv, rng: random.Random, level: int,
                 length: int, max_attempts: int = 100,
                 deadline: Optional[float] = None) -> Optional[Task]:
        """Seviye bazlı görev üretir. Hibrit: emülatörle üretir, gerçek makineyle doğrular."""
        cfg = self.curriculum[level]
        registers = cfg.registers
        selected_ops = self._selected_ops(level)
        if not selected_ops:
            return None
        max_instructions = cfg.max_instructions
        n = min(length, max_instructions)
        if n < 1:
            n = 1

        for _ in range(max_attempts):
            if deadline is not None and time.monotonic() >= deadline:
                return None
            secret = [rng.choice(selected_ops)[1] for _ in range(n)]
            code = "\n".join(secret)
            code_to_fn: Dict[str, OP] = {}
            for prefix, k, f in selected_ops:
                if k not in code_to_fn:
                    code_to_fn[k] = (prefix, k, f)
            ordered_program = [code_to_fn[k] for k in secret]

            memory_registers = {
                register.lower()
                for code_line in secret
                for register in re.findall(
                    r"\[\s*(rax|rbx|rcx|rdx|rsi|rdi|rbp|rsp|r(?:[89]|1[0-5]))\s*\]",
                    code_line,
                    re.I,
                )
            }
            memory_addresses = (
                0, 248, 256, 4096, 1 << 20,
                1 << 28, MAX_MEMORY_BYTES // 4,
                (MAX_MEMORY_BYTES * 3) // 4,
                MAX_MEMORY_BYTES - 8,
            )
            inputs: List[Dict[str, int]] = []
            seen_inputs: Set[Tuple[int, ...]] = set()
            while len(inputs) < 10:
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                given = {ad: rng.choice(INPUT_POOL) for ad in registers}
                for address_register_index, address_register in enumerate(
                    sorted(memory_registers)
                ):
                    if address_register in given:
                        address_index = (
                            len(inputs) * max(1, len(memory_registers))
                            + address_register_index
                        ) % len(memory_addresses)
                        given[address_register] = memory_addresses[address_index]
                key = tuple(given[register] & MASK for register in registers)
                if key not in seen_inputs:
                    inputs.append(given)
                    seen_inputs.add(key)
            last_flag_writer = None
            last_flag_index = -1
            for index, (prefix, _instruction, _fn) in enumerate(ordered_program):
                if prefix.startswith((
                    "add:", "sub:", "imul:", "and:", "or:", "xor:",
                    "inc:", "dec:", "neg:", "shl:", "shr:", "cmp:", "test:",
                )):
                    last_flag_writer = prefix.split(":", 1)[0]
                    last_flag_index = index
            observe_flags = (
                last_flag_writer in ("cmp", "test")
                and not any(
                    prefix == "syscall"
                    for prefix, _instruction, _fn in ordered_program[last_flag_index + 1:]
                )
            )
            examples: List[Dict[str, Any]] = []
            emulator_ok = True
            for input_index, given in enumerate(inputs):
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                output = self.emulator.run(
                    ordered_program,
                    given,
                    include_flags=observe_flags,
                    include_memory=bool(memory_registers),
                )
                if output is None:
                    emulator_ok = False
                    break
                initial_memory = None
                if memory_registers:
                    initial_memory = {
                        address: (address * 37 + input_index * 53 + 11) & 255
                        for address in output["bellek"]
                    }
                    output = self.emulator.run(
                        ordered_program,
                        given,
                        include_flags=observe_flags,
                        initial_memory=initial_memory,
                        include_memory=True,
                    )
                    if output is None:
                        emulator_ok = False
                        break
                example = {**given, "cikti": output}
                if initial_memory is not None:
                    example["bellek_girdi"] = initial_memory
                examples.append(example)
            if not emulator_ok:
                continue

            outputs = {
                (
                    tuple(o["cikti"][ad] for ad in registers if ad != "rsp"),
                    tuple(o["cikti"].get("bellek", ())),
                )
                for o in examples
            }
            if len(outputs) <= 1:
                continue  # çıkış sabit, görev ilgisiz

            # Tek-komutluk indirgenebilirlik kontrolü.
            if self._reducible(
                examples, n, registers, selected_ops, deadline
            ):
                continue
            if deadline is not None and time.monotonic() >= deadline:
                return None

            return Task(
                level=level, length=n, program=ordered_program, code=code,
                training=examples[:6], secret=examples[6:],
            )
        return None

# --------------------------------------------------------------------------- Çözücü (beam search)


class BeamSearchSolver:
    """Aile ağırlıklarıyla kışmalı arama (beam search) ile çözüm üretir."""

    def __init__(self, emulator: Emulator, ops: Sequence[OP],
                 curriculum: Dict[int, CurriculumLevel]) -> None:
        self._deneme_sayaci: Dict[Tuple[str, ...], int] = {}
        self.emulator = emulator
        self.ops = ops
        self.curriculum = curriculum

    def _selected_ops(self, level: int) -> List[OP]:
        return ops_for_level(level, self.ops, self.curriculum)

    def _limiti_sec(self, kutu: Set[Tuple[str, ...]]) -> Set[Tuple[str, ...]]:
        """Başarısızlık kümesini sabit boyutla sınırlandır."""
        if len(kutu) <= 200:
            return kutu
        # En az denenmiş (en eski/düşük sayaçlı) 190 elemanı tut
        eder = sorted(kutu, key=lambda x: self._deneme_sayaci.get(x, 0))
        return set(eder[:190])

    def _kayıtla_basarisizlik(self,
                               state: Optional[LearningState],
                               ctx: str,
                               kodu: Tuple[str, ...],
                               deneme: int) -> None:
        """Başarısızlıkı state.failures'e işle ve log yaz."""
        if state is None:
            return
        kutu = state.failures.setdefault(ctx, set())
        if not kodu and len(kutu) < 200:
            kodu = ("__boş__",)
        kutu.discard(kodu)
        kutu.add(kodu)
        if len(kutu) > 200:
            kutu = self._limiti_sec(kutu)
            state.failures[ctx] = kutu
        
        # Tek bir standart değişken adı (_deneme_sayaci) kullanılıyor
        v = self._deneme_sayaci.get(kodu, 0) + 1
        self._deneme_sayaci[kodu] = v
        if v >= 3:
            logger.warning(f"[NM] tekrarlayan başarısızlık (ctx={ctx[:12]}): "
                           f"{kodu[:4]}... deneme={v}")


    def _verify_real_all(self, asm: AsmUzuv, code: str,
                         examples: Sequence[Dict[str, Any]],
                         registers: Sequence[str],
                         cache: Dict[Tuple[Any, ...], bool],
                         deadline: Optional[float] = None,
                         record_evidence: bool = True) -> bool:
        """Tüm örnekler için gerçek makineyle doğrulama (önbellekli)."""
        for example in examples:
            initial = {r: example[r] for r in registers}
            if deadline is not None and time.monotonic() >= deadline:
                return False
            expected = example["cikti"]
            initial_memory = example.get("bellek_girdi")
            memory_output = expected.get("bellek")
            memory_addresses = (
                memory_output.keys() if isinstance(memory_output, dict) else None
            )
            key = (
                code,
                tuple(sorted(initial.items())),
                tuple(sorted(initial_memory.items()))
                if isinstance(initial_memory, dict)
                else tuple(initial_memory) if initial_memory is not None else None,
                tuple(sorted(memory_addresses)) if memory_addresses is not None else None,
            )
            if key in cache:
                if not cache[key]:
                    return False
                continue
            if record_evidence:
                ok = asm.tahmin_dene(
                    code, expected, initial, initial_memory
                )["dogru"]
            else:
                sonuc = asm._calistir(
                    code, initial, initial_memory, memory_addresses
                )
                if not sonuc["tamam"]:
                    ok = False
                else:
                    from asm_dogrula import karsilastir
                    ok = not karsilastir(expected, sonuc)
            cache[key] = ok
            if not ok:
                return False
        return True

    def _verify_independent(
        self,
        asm: AsmUzuv,
        codes: Sequence[str],
        registers: Sequence[str],
        known_examples: Sequence[Dict[str, Any]],
        cache: Dict[Tuple[Any, ...], bool],
        deadline: Optional[float],
        record_evidence: bool,
        level: int,
    ) -> bool:
        """Ayrı sınır girdilerinde CPU ile emülatör sonuçlarını karşılaştır."""
        code = "\n".join(codes)
        memory_registers = {
            register.lower()
            for register in re.findall(
                r"\[\s*(rax|rbx|rcx|rdx|rsi|rdi|rbp|rsp|r(?:[89]|1[0-5]))\s*\]",
                code,
                re.I,
            )
        }
        operation_by_code = {
            operation[1]: operation for operation in self._selected_ops(level)
        }
        program = [operation_by_code.get(line) for line in codes]
        if any(operation is None for operation in program):
            return False
        resolved_program = [
            operation for operation in program if operation is not None
        ]
        flag_writers = {
            "add", "sub", "imul", "and", "or", "xor",
            "inc", "dec", "neg", "shl", "shr", "cmp", "test",
        }
        last_flag_index = max(
            (index for index, operation in enumerate(resolved_program)
             if operation[0].split(":", 1)[0] in flag_writers),
            default=-1,
        )
        last_flag_writer = (
            resolved_program[last_flag_index][0] if last_flag_index >= 0 else None
        )
        syscall_after_flags = any(
            operation[0] == "syscall"
            for operation in resolved_program[last_flag_index + 1:]
        )
        observe_flags = (
            last_flag_writer in ("cmp:rr", "test:rr") and not syscall_after_flags
        )
        bases = (
            0x5555555555555555,
            0xAAAAAAAAAAAAAAAA,
            0x8000000000000003,
            0x7FFFFFFFFFFFFFFD,
            0x0123456789ABCDEF,
        )
        memory_offsets = (
            0, 248, 256, 4096,
            1 << 20, 1 << 28,
            MAX_MEMORY_BYTES // 4,
            (MAX_MEMORY_BYTES * 3) // 4,
            MAX_MEMORY_BYTES - 8,
        )
        seen_inputs = {
            tuple(example[register] for register in registers)
            for example in known_examples
        }
        probes: List[Dict[str, Any]] = []
        probe_count = max(len(bases), len(memory_offsets)) if memory_registers else len(bases)
        for probe_index in range(probe_count):
            if deadline is not None and time.monotonic() >= deadline:
                return False
            base = bases[probe_index % len(bases)]
            initial = {
                register: (base + (index * 0x101010101010101)) & MASK
                for index, register in enumerate(registers)
            }
            for index, register in enumerate(sorted(memory_registers)):
                if register in initial:
                    offset_index = (probe_index + index) % len(memory_offsets)
                    initial[register] = memory_offsets[offset_index]
            input_key = tuple(initial[register] for register in registers)
            if input_key in seen_inputs:
                continue
            seen_inputs.add(input_key)
            expected = self.emulator.run(
                resolved_program,
                initial,
                include_flags=observe_flags,
                include_memory=bool(memory_registers),
            )
            if expected is None:
                return False
            initial_memory = None
            if memory_registers:
                initial_memory = {
                    address: (address * 29 + probe_index * 71 + 19) & 255
                    for address in expected["bellek"]
                }
                expected = self.emulator.run(
                    resolved_program,
                    initial,
                    include_flags=observe_flags,
                    initial_memory=initial_memory,
                    include_memory=True,
                )
                if expected is None:
                    return False
            example: Dict[str, Any] = {**initial, "cikti": expected}
            if initial_memory is not None:
                example["bellek_girdi"] = initial_memory
            probes.append(example)
        return bool(probes) and self._verify_real_all(
            asm, code, probes, registers, cache, deadline, record_evidence
        )

    def solve(self, asm: AsmUzuv, task: Task, weights: Any,
              rng: random.Random, level: int,
              state: Optional[LearningState],
              record_to_brain: bool = True,
              budget: int = 60000,
              max_length: Optional[int] = None,
              deadline: Optional[float] = None) -> SolveResult:
        """Görevi çözmeye çalışır.

        ``state`` verildiğinde başarısız önbellek ve primitik kütüphanesi
        kullanılır; ``record_to_brain`` False ise çözüm beyine yazılmaz.
        """
        budget = max(1, int(budget))
        explored = [0]

        def exhausted() -> bool:
            return explored[0] >= budget or (deadline is not None and time.monotonic() >= deadline)
        egitim, sakli = task.training, task.secret
        registers = self.curriculum[level].registers
        attempts = emulator_mismatch = 0
        attempts_detail: Dict[str, int] = {}
        successful_detail: Dict[str, int] = {}
        ctx_fine, ctx_coarse = context_key(egitim)
        # Gereksiz 4 ekstra etiketi ve onlara atlayan komutları ele, sadece 'dongu' kalsın
        gereksiz_etiketler = ("son", "baslangic", "kontrol", "cikis")
        selected_ops = [
            op for op in self._selected_ops(level)
            if not any(e in op[1] for e in gereksiz_etiketler)
        ]
        search_max_length = self.curriculum[level].max_instructions
        if max_length is not None:
            search_max_length = min(search_max_length, max(1, int(max_length)))

        def _w(aile: str) -> float:
            if hasattr(weights, "weights"):
                return float(
                    weights.weights(ctx_fine, [aile], ctx_coarse).get(aile, 0.1)
                )
            return float(weights.get(aile, 1.0))

        # DÜZELTME 1: Ağırlık farklarını karekök ile yumuşat ve %15 rastgele keşif şansı tanı
        def _sort_key(op: OP) -> Tuple[float, float]:
            if rng.random() < 0.15:
                return (0.0, rng.random())  # %15 keşif (exploration)
            return (-(_w(op[0]) ** 0.5), rng.random())

        # DÜZELTME 2: Aileden çok yoğunlaşmaması için family-based scattering
        # Aile başına 3-4 adet al, kalanları karıştır, çevirilmiş sıralama yap
        families: Dict[str, List[OP]] = {}
        for op in selected_ops:
            prefix = op[0]  # "mov", "arithmetic", ... vs
            families.setdefault(prefix, []).append(op)

        ordered: List[OP] = []
        # Aynı aileden fazla kaplamamak için her aileden 3-4'ü al, kalanları karıştır
        for prefix in sorted(families.keys(), key=lambda p: -_w(p)):
            ops = families[prefix]
            # Ağırlığa göre sırala, en iyi 3-4'ü önde al
            scored = sorted(ops, key=lambda o: -_w(o[0]))
            keep_top = min(4, len(scored))
            top = scored[:keep_top]
            rest = scored[keep_top:]
            rng.shuffle(rest)
            ordered.extend(top)
            ordered.extend(rest)
        # Arada rastgele keşif komutlarını da ekle (%15 şansı ile)
        if rng.random() < 0.15:
            op = rng.choice(selected_ops)
            ordered.append(op)
        ordered = list(dict.fromkeys(ordered))  # karıştırılmış tekrarları kaldır

        # DÜZELTME: Seviye 4'te gereksiz etiket dallanmasını kısıtla
        # Yalnızca 'dongu:' etiketini açık tut, diğerleri (baslangic:, son:, kontrol:, cikis:)
        # ve ona atlayan jump komutları arama uzayından çıkarılır.
        if level == 4:
            ordered = [op for op in ordered
                       if not op[1].endswith(":") or op[1] == "dongu:"]

        seen: Set[Tuple[str, ...]] = set()
        cache: Dict[Tuple[Any, ...], bool] = {}
        # DÜZELTME (başarısızlık önbelleği zehirlenmesi): ctx_fine yalnızca
        # ilişki imzasıdır, sabitleri (add rax, 5 / add rax, 7) ayırt etmez.
        # Kalıcı ctx-seviyesi önbellekle budamak, bir görevde elenen komutu
        # aynı imzalı TÜM görevlerde yasaklıyordu; ayrıca "tek komut çözüm
        # değil" bilgisi uzun programların ilk komutunu da eliyor ve beam
        # boş kalıyordu (görev başına ~0 deneme). Budama yalnızca bu
        # çağrıya özel (yerel) kalır.
        failure_cache: Set[Tuple[str, ...]] = set()


        # --- 1. Aynı bağlamda daha önce doğrulanan programları yeniden kullan ---
        if state is not None:
            known_programs = list(state.programs.get(ctx_fine, []))
            known_programs.extend(
                [[code] for code in state.primitives.get(ctx_fine, [])]
            )
            operation_by_code = {code: (prefix, code, fn)
                                 for prefix, code, fn in selected_ops}
            already_checked: Set[Tuple[str, ...]] = set()
            for codes in known_programs:
                if exhausted():
                    break
                key = tuple(codes)
                if key in already_checked or not key or len(key) > search_max_length:
                    continue
                already_checked.add(key)
                candidate = [operation_by_code.get(code) for code in codes]
                if any(operation is None for operation in candidate):
                    continue
                program = [operation for operation in candidate if operation is not None]
                explored[0] += 1
                attempts += 1
                for prefix, _code, _fn in program:
                    attempts_detail[prefix] = attempts_detail.get(prefix, 0) + 1
                code = "\n".join(codes)
                if (self.emulator.matches(program, egitim, registers)
                        and self._verify_real_all(
                            asm, code, egitim, registers, {}, deadline,
                            record_evidence=record_to_brain,
                        )
                        and self._verify_real_all(
                            asm, code, sakli, registers, {}, deadline,
                            record_evidence=record_to_brain,
                        )
                        and self._verify_independent(
                            asm, codes, registers, egitim + sakli, cache,
                            deadline, record_to_brain, level,
                        )):
                    if record_to_brain:
                        asm.program_kaydet(code, ctx_fine, deneme=attempts)
                    return SolveResult(True, list(codes), attempts, 0,
                                       attempts_detail, successful_detail)

        def try_candidate(program: List[OP],
                          families: List[str]) -> Optional[List[str]]:
            nonlocal attempts, emulator_mismatch
            if exhausted():
                return None
            explored[0] += 1
            attempts += 1
            for aile in families:
                attempts_detail[aile] = attempts_detail.get(aile, 0) + 1
            if not self.emulator.matches(program, egitim, registers):
                return None
            # Başarılı eşleşme: başarı sayısını güncelle
            for aile in families:
                successful_detail[aile] = successful_detail.get(aile, 0) + 1
            return [k for _, k, _ in program]

        solution: Optional[List[str]] = None
        # Uzunluk 1: ağırlık sırasıyla tam tarama (başarısızlık önbelleği korumalı)
        for prefix, code, fn in ordered:
            # DÜZELTME 2: Daha önce bu bağlamda başarısız olmuş tekli komutları atla
            if state is not None and (code,) in failure_cache:
                continue
            solution = try_candidate([(prefix, code, fn)], [prefix])
            if solution is not None:
                kod_str = "\n".join(solution)
                if (self._verify_real_all(
                        asm, kod_str, egitim, registers, cache, deadline,
                        record_evidence=record_to_brain,
                    )
                        and self._verify_real_all(
                            asm, kod_str, sakli, registers, cache, deadline,
                            record_evidence=record_to_brain,
                        )
                        and (
                            not task.program
                            or self._verify_independent(
                                asm, solution or [], registers, egitim + sakli,
                                cache, deadline, record_to_brain, level,
                            )
                        )):
                    break
                solution = None
                emulator_mismatch += 1
                if state is not None:
                    self._kayıtla_basarisizlik(state, ctx_fine, (code,), attempts + 1)


        # Uzunluk >= 2: beam search — her seviyede en iyi BEAM_WIDTH adayı tutar.
        if solution is None:
            beam: List[Tuple[List[OP], int]] = []
            for prefix, code, fn in ordered:
                key = (code,)
                if exhausted():
                    break
                if state is not None and key in failure_cache:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                explored[0] += 1
                attempts += 1
                attempts_detail[prefix] = attempts_detail.get(prefix, 0) + 1
                puan = float(self.emulator.score([(prefix, code, fn)], egitim, registers))
                # Etiketlere keşif bonusu ver ki ilk adımda elenmesin
                if code.endswith(":"):
                    puan += 0.5
                beam.append(([(prefix, code, fn)], puan))
            beam.sort(key=lambda item: -item[1])
            beam = beam[:BEAM_WIDTH]

            mevcut_uzunluk = 1
            while (mevcut_uzunluk < self.curriculum[level].max_instructions
                   and mevcut_uzunluk < search_max_length
                   and beam and solution is None
                   and not exhausted()):
                yeni_beam: List[Tuple[List[OP], int]] = []
                for program, _ in beam:
                    etiket_var = any(k.endswith(":") for _, k, _ in program)
                    for prefix, code, fn in ordered:
                        # Etiket yoksa dongu hedefli jump komutlarını atla
                        if not etiket_var and code.endswith("dongu"):
                            continue
                        # Birden fazla etiket eklemeyi engelle (arama uzayını daraltır)
                        if etiket_var and code.endswith(":"):
                            continue
                        yeni_program = program + [(prefix, code, fn)]
                        anahtar = tuple(k for _, k, _ in yeni_program)
                        if state is not None and anahtar in failure_cache:
                            continue
                        if anahtar in seen:
                            continue
                        seen.add(anahtar)
                        if exhausted():
                            break
                        explored[0] += 1
                        attempts += 1
                        attempts_detail[prefix] = attempts_detail.get(prefix, 0) + 1
                        tam_eslesme = self.emulator.score(yeni_program, egitim, registers)
                        puan = float(tam_eslesme)
                        # Etiket varsa ve henüz atlama komutu eklenmediyse şans tanı
                        if (etiket_var or code.endswith(":")) and tam_eslesme < len(egitim):
                            puan += 0.5
                        # Etiketten sonraki ilk komut cmp/test/syscall/push/pop değilse, direkt yazmaç değiştiren işlem tercih et
                        if etiket_var and not code.endswith(":"):
                            komut_prefix = code.split()[0] if " " in code else code
                            if komut_prefix not in ("cmp", "test", "syscall", "push", "pop"):
                                puan += 0.3
                        yeni_beam.append((yeni_program, puan))
                if exhausted():
                    break
                # Etiketli (döngü) adaylara beam içinde özel kontenjan ayır (boş komutlar tarafından ezilmesin)
                etiketliler = [x for x in yeni_beam if any(k.endswith(":") for _, k, _ in x[0])]
                normals = [x for x in yeni_beam if not any(k.endswith(":") for _, k, _ in x[0])]
                etiketliler.sort(key=lambda item: -item[1])
                normals.sort(key=lambda item: -item[1])
                beam = (etiketliler[:BEAM_WIDTH // 2] + normals[:BEAM_WIDTH])[:BEAM_WIDTH]
                mevcut_uzunluk += 1

                for program, puan in beam:
                    if int(puan) == len(egitim):
                        kodlar = [k for _, k, _ in program]
                        kod = "\n".join(kodlar)
                        if (self._verify_real_all(
                                asm, kod, egitim, registers, cache, deadline,
                                record_evidence=record_to_brain,
                            )
                                and self._verify_real_all(
                                    asm, kod, sakli, registers, cache, deadline,
                                    record_evidence=record_to_brain,
                                )
                                and (
                                    not task.program
                                    or self._verify_independent(
                                        asm, kodlar, registers,
                                        egitim + sakli, cache, deadline,
                                        record_to_brain, level,
                                    )
                                )):
                            solution = kodlar
                            break
                        emulator_mismatch += 1
                        if state is not None:
                            self._kayıtla_basarisizlik(state, ctx_fine, (kod,), attempts + 1)

        # --- 2. Doğrulanan programları sonraki aynı-bağlam aramalarında kullan ---
        if solution is not None and state is not None:
            programs = state.programs.setdefault(ctx_fine, [])
            if solution not in programs:
                programs.append(list(solution))
                del programs[:-32]
            if len(solution) == 1:
                primitives = state.primitives.setdefault(ctx_fine, [])
                if solution[0] not in primitives:
                    primitives.append(solution[0])

        # --- 3. Çözülen programı AsmUzuv beynine kalıcı yaz ---
        if solution is not None and asm is not None and record_to_brain:
            kod_str = "\n".join(solution)
            asm.program_kaydet(kod_str, ctx_fine, deneme=attempts)

        return SolveResult(
            solved=solution is not None,
            program=solution,
            attempts=attempts,
            emulator_mismatch=emulator_mismatch,
            attempts_detail=attempts_detail,
            successful_detail=successful_detail,
            timed_out=deadline is not None and time.monotonic() >= deadline,
        )


# --------------------------------------------------------------------------- Öğrenme döngüsü


class AssemblyLearner:
    """Zaman sınırlı öğrenme döngüsünü koordine eder."""

    def __init__(self, asm: AsmUzuv, state: LearningState,
                 curriculum: Dict[int, CurriculumLevel], ops: Sequence[OP],
                 emulator: Emulator, rng: random.Random) -> None:
        self.asm = asm
        self.state = state
        self.curriculum = curriculum
        self.ops = ops
        self.emulator = emulator
        self.rng = rng
        self.generator = TaskGenerator(emulator, ops, curriculum)
        self.solver = BeamSearchSolver(emulator, ops, curriculum)
        self.verify_cache: Dict[Tuple[Any, ...], bool] = {}
        # Program arama uzunluğu sınırı: yüksekte başla (1 = çözülemeyen
        # uzun programların aranmasını engelleyen kurtarma döngüsünü önler).
        self.state.max_length = max(2, self.state.max_length)

    def solve_examples(
        self,
        training: Sequence[Dict[str, Any]],
        validation: Sequence[Dict[str, Any]],
        level: int = 1,
        max_length: Optional[int] = None,
        budget: int = 10000,
        timeout_seconds: float = 10.0,
    ) -> SolveResult:
        """Find a program from input/output examples and verify held-out cases.

        Each example has ``input`` and ``output`` register mappings. Unspecified
        inputs default to zero; unspecified outputs are required to stay unchanged.
        """
        if isinstance(level, bool) or not isinstance(level, int) or level not in self.curriculum:
            raise ValueError(f"unknown curriculum level: {level}")
        cfg = self.curriculum[level]
        if not training or not validation:
            raise ValueError("training and validation examples must both be non-empty")
        if len(training) + len(validation) > 128:
            raise ValueError("at most 128 examples may be supplied")
        if max_length is not None and (
            isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or not 1 <= max_length <= cfg.max_instructions
        ):
            raise ValueError(f"max_length must be an integer between 1 and {cfg.max_instructions}")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            raise ValueError("budget must be positive")
        timeout_seconds = float(timeout_seconds)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        writable_registers = set(cfg.registers) - {"rsp"}

        def normalize(rows: Sequence[Dict[str, Any]], group: str) -> List[Dict[str, Any]]:
            normalized = []
            allowed_keys = {"input", "output", "bellek_girdi", "bellek"}
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ValueError(f"{group}[{index}] must be a mapping")
                if not {"input", "output"}.issubset(set(row)) or not set(row).issubset(allowed_keys):
                    raise ValueError(
                        f"{group}[{index}] must contain input and output (optional bellek_girdi/bellek)"
                    )
                inputs, outputs = row["input"], row["output"]
                if not isinstance(inputs, dict) or not isinstance(outputs, dict):
                    raise ValueError(f"{group}[{index}] input/output must be mappings")
                if not outputs and "bellek" not in row:
                    raise ValueError(f"{group}[{index}].output must not be empty")
                initial = {register: 0 for register in cfg.registers}
                normalized_outputs: Dict[str, int] = {}
                for values, target, label, allowed in (
                    (inputs, initial, "input", set(cfg.registers) - {"rsp"}),
                    (outputs, normalized_outputs, "output", writable_registers),
                ):
                    seen_registers: Set[str] = set()
                    for raw_register, value in values.items():
                        register = raw_register.lower() if isinstance(raw_register, str) else ""
                        if register not in allowed:
                            raise ValueError(
                                f"{group}[{index}].{label}: unsupported register "
                                f"{raw_register!r} for level {level}"
                            )
                        if register in seen_registers:
                            raise ValueError(
                                f"{group}[{index}].{label} repeats register {register}"
                            )
                        seen_registers.add(register)
                        if isinstance(value, bool) or not isinstance(value, int):
                            raise ValueError(
                                f"{group}[{index}].{label}.{register} must be an integer"
                            )
                        target[register] = value & MASK
                expected = {
                    register: initial[register]
                    for register in writable_registers
                }
                expected.update(normalized_outputs)

                kayit: Dict[str, Any] = {**initial, "cikti": expected}
                if "bellek_girdi" in row and isinstance(row["bellek_girdi"], dict):
                    kayit["bellek_girdi"] = {int(k): int(v) & 255 for k, v in row["bellek_girdi"].items()}
                if "bellek" in row and isinstance(row["bellek"], dict):
                    expected["bellek"] = {int(k): int(v) & 255 for k, v in row["bellek"].items()}
                normalized.append(kayit)
            return normalized

        normalized_training = normalize(training, "training")
        normalized_validation = normalize(validation, "validation")
        training_inputs = {
            tuple(example[register] for register in cfg.registers if register != "rsp")
            for example in normalized_training
        }
        validation_inputs = {
            tuple(example[register] for register in cfg.registers if register != "rsp")
            for example in normalized_validation
        }
        if training_inputs & validation_inputs:
            raise ValueError("validation inputs must be separate from training inputs")

        task = Task(
            level=level,
            length=max_length or cfg.max_instructions,
            program=[],
            code="user_examples",
            training=normalized_training,
            secret=normalized_validation,
        )
        sonuc = self.solver.solve(
            self.asm,
            task,
            self.state.weights,
            random.Random(7),
            level,
            state=self.state,          # Hafızayı kullan ve güncelle
            record_to_brain=True,      # AsmUzuv beynine kaydet
            budget=budget,
            max_length=max_length,
            deadline=time.monotonic() + timeout_seconds,
        )
        if sonuc.solved:
            ctx_fine, _ = context_key(normalized_training)
            self.state.weights.record_attempts(
                ctx_fine,
                {aile: (sonuc.successful_detail.get(aile, 0), sonuc.attempts_detail.get(aile, 0))
                 for aile in set(sonuc.successful_detail) | set(sonuc.attempts_detail)}
            )
            self.state.save()
        return sonuc

    def run(self, minutes: float,
            solution_path: Optional[Path] = None,
            nn_ana=None,
            stim_features: Optional[list[float]] = None) -> None:
        """``minutes`` dakika boyunca öğrenme döngüsünü çalıştırır.

        nn_ana ve stim_features verildiğinde, beam search araması
        nöral beyin tarafından yönlendirilir (hibrit öğrenme).
        """
        deadline = time.monotonic() + max(0.0, float(minutes)) * 60
        solution_path = solution_path or (self.asm.uzuv_dir / "asm_cozumler.jsonl")

        # Çift yönlü senkronizasyon: AsmUzuv'un hata derslerini başarısız önbelleğe aktar.
        if self.asm is not None:
            for pattern, _message in self.asm.hata_dersleri.items():
                self.state.failures.setdefault("", set()).add((pattern,))

        while time.monotonic() < deadline:
            level = self.state.max_level
            cfg = self.curriculum[level]
            # max_length'ı mevcut seviyenin geçerli aralığına sıkıştır
            # (kaydedilmiş durumdan gelen eskiler / aşırı değerler için).
            self.state.max_length = max(
                2, min(self.state.max_length, cfg.max_instructions))
            length = self.rng.randint(1, cfg.max_instructions)
            task = self.generator.generate(
                self.asm, self.rng, level, length,
                max_attempts=20, deadline=deadline)
            if task is None:
                if time.monotonic() >= deadline:
                    break
                continue

            ctx_fine, ctx_coarse = context_key(task.training)

            # Hibrit: nn_ana varsa beam search'ı nöral beyinle yönlendir
            if nn_ana is not None:
                blend_weights = NNWeightBlender(
                    self.state.weights, nn_ana,
                    stim_features or _gorev_ozellik_vektoru(
                        task.training, level, length),
                    alpha=0.6,
                )
                solve_weights = blend_weights
            else:
                solve_weights = self.state.weights

            # WeightTable'a fine ve coarse anahtarları tanıt
            if hasattr(solve_weights, "set_context_keys"):
                solve_weights.set_context_keys(ctx_fine, ctx_coarse)

            result = self.solver.solve(
                self.asm, task, solve_weights, self.rng, level, self.state,
                record_to_brain=True, deadline=deadline, max_length=None,
            )
            # Dinamik alpha: nn_ana'nın başarı/başarısızlığını kaydet
            if nn_ana is not None and isinstance(solve_weights, NNWeightBlender):
                solve_weights.report_result(result.solved)
            solved_families = (
                [family for code in (result.program or [])
                 if (family := _family_of(code)) is not None]
                if result.solved else []
            )
            # Ağırlık güncellemesi YALNIZCA başarıyla çözülen görevlerde:
            # başarısız aramada denenen her aileye "deneme" artmak yerine
            # isabet kalırsa bu ailelerin ağırlığı (isabet+1)/(deneme+10)
            # formülüyle sürekli düşer ve doğru olabilecek ama yanlış
            # kombinasyonda kullanılan aileler asla denenmez hale gelir
            # (anti-learning döngüsü). Başarısız aramada ağırlığı hiç
            # değiştirmeyelim; yalnızca keşfedilen çözümdeki aileleri
            # pekiştirelim.
            if result.solved:
                # başarılı agırlaştırma: row[aile][0] = başarılı deneme, row[aile][1] = toplam deneme
                self.state.weights.record_attempts(
                    ctx_fine,
                    {aile: (result.successful_detail.get(aile, 0), result.attempts_detail.get(aile, 0))
                     for aile in set(result.successful_detail) | set(result.attempts_detail)}
                )

                # ---------- Geri besleme: asm_ogren başarılarını nn_ana'ya öğret ----------
                # Döngüyü kapat: "bu fiziksel durumda bu op ailesi işe yaradı"
                if nn_ana is not None and stim_features is not None:
                    _v = [max(0.0, min(1.0, float(x))) for x in stim_features[:48]]
                    while len(_v) < 48:
                        _v.append(0.0)
                    _hedef = [0.1] * 5
                    for fam in solved_families:
                        cat = _prefix_to_nn_category(fam)
                        _idx = {
                            "mov": 2, "arithmetic": 2, "logic": 2,
                            "shift": 2, "unary": 2,
                            "control": 0,
                            "memory": 3,
                        }.get(cat, 4)
                        _hedef[_idx] = 1.0
                    # Sönümlü momentum nedeniyle 3 tekrarlı pekiştirme daha hızlı öğretir
                    for _ in range(3):
                        nn_ana.öğren(_v, _hedef, diske_yaz=False)
                    self._nn_ana_teach_count = getattr(self, "_nn_ana_teach_count", 0) + 1
                    if self._nn_ana_teach_count % 10 == 0:
                        nn_ana.kaydet()
            self.state.total_tasks += 1
            # Program uzunluğunu son 10 göreve göre uyarla: başarılıysa tam
            # müfredat uzunluğuna, düşük başarıysa daha kısa (ama en az 2
            # komut) denemelere odaklan. state.max_length solver'da
            # search_max_length'ı sıner; tek başına bir başarısızlıkla
            # 1'e düşüp sonsuz döngüye girmez.
            son10 = [g for g in self.state.history[-10:]
                     if g.get("seviye") == self.state.max_level]
            basari10 = (sum(g["cozuldu"] for g in son10) / len(son10)
                        if son10 else 0.0)
            if basari10 >= 0.5:
                self.state.max_length = min(
                    self.state.max_length + 1, cfg.max_instructions)
            elif basari10 < 0.3 and self.state.max_length > 2:
                self.state.max_length -= 1
            self.state.history.append({
                "seviye": level,
                "uzunluk": length,
                "cozuldu": result.solved,
                "deneme": result.attempts,
                "emu_yanilgi": result.emulator_mismatch,
            })

            if result.solved:
                with open(solution_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({
                        "t": time.time(), "program": result.program,
                        "seviye": level, "uzunluk": length,
                        "deneme": result.attempts,
                    }, ensure_ascii=False) + "\n")

            # Müfredat ileri / geri dönüş: düşük başarı seviyeyi düşürür,
            # yüksek başarı raisesır. Böylece orgama zor bir seviyede
            # sonsuza kadar sıkışmaz ("çapak kalsa" durumu önlenir).
            son = [g for g in self.state.history[-40:]
                   if g.get("seviye") == self.state.max_level][-20:]
            basari = (sum(g["cozuldu"] for g in son) / len(son) if son else 0.0)
            if len(son) >= 10:
                if (basari >= 0.70
                        and self.state.max_level < CURRICULUM_MAX_LEVEL):
                    self.state.max_level += 1
                    logger.info(
                        "müfredat: ileri seviye %d (%s)",
                        self.state.max_level,
                        self.curriculum[self.state.max_level].name,
                    )
                elif basari < 0.30 and self.state.max_level > 1:
                    self.state.max_level -= 1
                    logger.info(
                        "müfredat: geri seviye %d (%s)",
                        self.state.max_level,
                        self.curriculum[self.state.max_level].name,
                    )

            if self.state.total_tasks % 2 == 0:
                self.state.save()
                self.report()

        self.state.save()
        if self.asm is not None:
            self.asm.log("asm_ogren", gorev=self.state.total_tasks,
                         maks_seviye=self.state.max_level)

    def report(self, n: int = 20) -> None:
        """Son ``n`` görevin özetini yazdırır."""
        son = self.state.history[-n:]
        if not son:
            print("henüz görev yok")
            return
        cozulen = [g for g in son if g["cozuldu"]]
        ort = (sum(g["deneme"] for g in cozulen) / len(cozulen) if cozulen else 0)
        toplam_primtik = sum(len(v) for v in self.state.primitives.values())
        toplam_basarisiz = sum(len(s) for s in self.state.failures.values())
        print(
            f"[{self.state.total_tasks:4d}] son {len(son)}: "
            f"çözüm %{100 * len(cozulen) // len(son)} | "
            f"seviye {self.state.max_level} | ort. deneme {ort:.0f} | "
            f"primtik {toplam_primtik} | başarısız önbellek {toplam_basarisiz}"
        )


# --------------------------------------------------------------------------- Karşılaştırma


def compare(asm: AsmUzuv, state: LearningState, count: int,
            seed: int = 7) -> None:
    """Aynı görevlerde düz arama (ağırlık hep 1) ile öğrenilmiş ağırlığı karşılaştırır.

    Öğrenmez, kaydetmez.
    """
    duz = {aile: 1.0 for aile in AILELER}
    emulator = Emulator()
    generator = TaskGenerator(emulator, OPS, CURRICULUM)
    solver = BeamSearchSolver(emulator, OPS, CURRICULUM)
    rng = random.Random(seed)
    sonuc: Dict[str, List[Tuple[int, SolveResult]]] = {"düz": [], "öğrenilmiş": []}

    for i in range(count):
        level = min(state.max_level, CURRICULUM_MAX_LEVEL)
        cfg = CURRICULUM[level]
        length = rng.randint(1, cfg.max_instructions)
        task = generator.generate(asm, rng, level, length)
        if task is None:
            continue
        ctx_fine, ctx_coarse = context_key(task.training)
        for label, weights in (("düz", duz),
                               ("öğrenilmiş", state.weights.weights(ctx_fine, AILELER, ctx_coarse))): # type: ignore
            task_rng = random.Random(seed * 1000 + i)
            res = solver.solve(asm, task, weights, task_rng, level, None,
                               record_to_brain=False)
            sonuc[label].append((length, res))

    for label, liste in sonuc.items():
        cozulen = [r for _, r in liste if r.solved]
        ort = (sum(r.attempts for r in cozulen) / len(cozulen) if cozulen else 0)
        ortanca = (sorted(r.attempts for r in cozulen)[len(cozulen) // 2]
                   if cozulen else 0)
        print(f"{label:11}: {len(cozulen)}/{len(liste)} çözüldü | "
              f"çözülenlerde ort. deneme {ort:.0f}, ortanca {ortanca}")


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="x86-64 Assembly öğrenme organu")
    ap.add_argument("--dakika", type=float, default=0,
                    help="Öğrenme süresi (dakika)")
    ap.add_argument("--kiyas", type=int, default=0,
                    help="N görev üzerinde düz vs öğrenilmiş ağırlık karşılaştırması")
    ap.add_argument("--rapor", action="store_true",
                    help="Öğrenme raporu yazdır")
    ap.add_argument("--seed", type=int, default=None,
                    help="Rastgele sayı tohumu")
    ap.add_argument("--kok", default=None,
                    help="CORE kök dizini (varsayılan: bu dosyanın iki üst dizini)")
    ap.add_argument("--coz-json", default=None,
                    help="training/validation örneklerini içeren JSON dosyası")
    ap.add_argument("--seviye", type=int, default=1,
                    help="Örnek tabanlı çözüm için müfredat seviyesi (1-4)")
    ap.add_argument("--azami-komut", type=int, default=None,
                    help="Aday programın azami komut sayısı")
    ap.add_argument("--butce", type=int, default=400000,
                    help="En fazla arama adımı")
    ap.add_argument("--zaman-asimi", type=float, default=60.0,
                    help="Çözüm araması için saniye sınırı")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.kok).resolve() if args.kok else Path(__file__).resolve().parent.parent
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    asm = AsmUzuv(root=root)
    state_path = asm.uzuv_dir / "asm_ogren.json"
    state = LearningState(state_path)
    state.load()

    rng = random.Random(args.seed)
    emulator = Emulator()
    learner = AssemblyLearner(asm, state, CURRICULUM, OPS, emulator, rng)

    if args.coz_json:
        try:
            specification = json.loads(
                Path(args.coz_json).read_text(encoding="utf-8")
            )
            if not isinstance(specification, dict):
                raise ValueError("JSON root must be an object")
            training = specification.get("training")
            validation = specification.get("validation")
            if not isinstance(training, list) or not isinstance(validation, list):
                raise ValueError("JSON must contain training and validation arrays")
            result = learner.solve_examples(
                training,
                validation,
                level=args.seviye,
                max_length=args.azami_komut,
                budget=args.butce,
                timeout_seconds=args.zaman_asimi,
            )
        except (OSError, ValueError, TypeError) as error:
            print(json.dumps({"hata": str(error)}, ensure_ascii=False),
                  file=sys.stderr)
            return 2
        print(json.dumps({
            "cozuldu": result.solved,
            "program": result.program,
            "deneme": result.attempts,
            "emulator_uyusmazligi": result.emulator_mismatch,
            "zaman_asimi": result.timed_out,
        }, ensure_ascii=False))
        return 0 if result.solved else 1

    if args.dakika:
        learner.run(args.dakika)
    if args.kiyas:
        compare(asm, state, args.kiyas, seed=args.seed or 7)
    if args.rapor or not (args.dakika or args.kiyas or args.coz_json):
        learner.report()
        print(f"öğrenilen kalıp sayısı: {len(state.primitives)}")
        for ctx in sorted(state.primitives,
                          key=lambda c: -sum(v[1] for v in
                                             state.weights.records.get(c, {}).values()))[:5]:
            wmap = state.weights.weights(ctx, AILELER) # type: ignore
            en_iyi = sorted(wmap, key=lambda a: -wmap[a])[:3]
            print(f"  kalıp {ctx}: önce {', '.join(en_iyi)}")
        asm.rapor()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
