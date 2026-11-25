#!/usr/bin/env python3
"""ASM beam search iyileştirmeleri için testler.

Kapsam:
  1. Yoğun skor + durum imzası (Emulator.score_yogun) sözleşmesi
  2. Davranışsal tekrar budaması güvenliği (_dedup_uygun)
  3. Seviyenin son uzunluğunun da kontrol edilmesi (`<=` düzeltmesi)
  4. Kernighan x & (x-1): yalnızca rax hedefli, rbx geri konmalı (4 komut)
"""

import dataclasses
import random
import tempfile
from pathlib import Path

from uzuv.asm_ogren import (
    AssemblyLearner,
    CURRICULUM,
    Emulator,
    LearningState,
    OPS,
    _dedup_uygun,
    ops_for_level,
)
from uzuv.asm_uzuv import AsmUzuv


def _ogrenici(root: Path, curriculum=CURRICULUM) -> AssemblyLearner:
    asm = AsmUzuv(root=root)
    state = LearningState(root / "uzuv" / "asm_ogren.json")
    return AssemblyLearner(asm, state, curriculum, OPS, Emulator(), random.Random(7))


def _op(code: str):
    return next(op for op in OPS if op[1] == code)


def test_score_yogun_sozlesmesi() -> None:
    em = Emulator()
    regs = CURRICULUM[1].registers
    # rax += 1 hedefi; rbx değişmemeli (çözücünün normalize ettiği biçim)
    egitim = [
        {"rax": x, "rbx": 0, "cikti": {"rax": x + 1, "rbx": 0}} for x in (2, 7, 12, 40)
    ]
    tam, imza, _ara = em.score_yogun([_op("inc rax")], egitim, regs)
    assert int(tam) == len(egitim) and imza is not None
    # Tam olmayan örnek asla 0.5'e ulaşmaz => int(puan) yalnızca tam çözümde n olur
    for kod in ("inc rbx", "add rax, 2", "mov rbx, rax", "not rax"):
        puan, _, _ = em.score_yogun([_op(kod)], egitim, regs)
        assert int(puan) < len(egitim), kod
        assert puan < 0.5 * len(egitim), (kod, puan)
    # score ile uyum: tam eşleşmede ikisi de aynı sayıyı verir
    assert int(em.score([_op("inc rax")], egitim, regs)) == len(egitim)


def test_dedup_imzasi_ve_guvenligi() -> None:
    em = Emulator()
    regs = CURRICULUM[1].registers
    egitim = [{"rax": x, "rbx": 0, "cikti": {"rax": x, "rbx": 0}} for x in (3, 9, 21)]
    # rbx başlangıçta 0 iken mov rbx,rax ile add rbx,rax aynı durumu üretir
    s_mov = em.score_yogun([_op("mov rbx, rax")], egitim, regs)
    s_add = em.score_yogun([_op("add rbx, rax")], egitim, regs)
    assert s_mov[1] == s_add[1]
    # veriye bağlı ara değer işaretlenir, sabit atama işaretlenmez
    assert s_mov[2] >= 1
    assert em.score_yogun([_op("mov rbx, 5")], egitim, regs)[2] == 0
    # Akış/yığın/sistem çağrısı içeren programlar dedup'a girmez
    assert _dedup_uygun(["mov rbx, rax", "dec rbx", "and rax, rbx"])
    for kod in ("jmp dongu", "jz dongu", "jnz dongu", "dongu:", "push rax",
                "pop rax", "call dongu", "ret", "syscall"):
        assert not _dedup_uygun(["mov rax, rbx", kod]), kod


def test_seviye_sonu_uzunlugu_kontrol_ediliyor() -> None:
    """Seviye tavanı 2 iken 2 komutluk çözüm bulunabilmeli (eski `<` bunu kaçırıyordu)."""
    seviye1 = dataclasses.replace(CURRICULUM[1], max_instructions=2)
    mufredat = dict(CURRICULUM)
    mufredat[1] = seviye1
    ops = ops_for_level(1, OPS, mufredat)
    assert any(op[1] == "shl rax, 1" for op in ops) and any(op[1] == "inc rax" for op in ops)
    with tempfile.TemporaryDirectory() as tmp:
        ogr = _ogrenici(Path(tmp), mufredat)
        # 2x + 1: tek komutla yazılamaz => tam 2 komut (tavan) gerekir
        sonuc = ogr.solve_examples(
            training=[{"input": {"rax": x}, "output": {"rax": 2 * x + 1}} for x in (1, 4, 9, 20)],
            validation=[{"input": {"rax": 33}, "output": {"rax": 67}}],
            budget=50000, timeout_seconds=30.0,
        )
        assert sonuc.solved, sonuc
        assert len(sonuc.program) == 2, sonuc.program


def test_kernighan_sadece_rax_hedefli() -> None:
    """x & (x-1); rbx geri konmalı => ara değeri olan 4 komutluk program."""
    girdiler = (12, 7, 40, 9, 100, 33, 96, 255)
    egitim = [{"input": {"rax": x}, "output": {"rax": x & (x - 1)}} for x in girdiler[:4]]
    dogrulama = [{"input": {"rax": x}, "output": {"rax": x & (x - 1)}} for x in girdiler[4:]]
    with tempfile.TemporaryDirectory() as tmp:
        ogr = _ogrenici(Path(tmp))
        sonuc = ogr.solve_examples(
            training=egitim, validation=dogrulama, level=1, max_length=4,
            budget=300000, timeout_seconds=120.0,
        )
        assert sonuc.solved, sonuc
        assert len(sonuc.program) <= 4
        # Bulunan program emülatörde bağımsız girdilerde de doğru olmalı
        em = Emulator()
        by = {op[1]: op for op in OPS}
        prog = [by[kod] for kod in sonuc.program]
        for x in (0, 1, 2, 5, 64, 1000, 4095, 2**40 + 8):
            sonuc_reg = em.run(prog, {"rax": x, "rbx": 0})
            assert sonuc_reg["rax"] == x & (x - 1) and sonuc_reg["rbx"] == 0, (x, sonuc_reg)


if __name__ == "__main__":
    test_score_yogun_sozlesmesi()
    test_dedup_imzasi_ve_guvenligi()
    test_seviye_sonu_uzunlugu_kontrol_ediliyor()
    test_kernighan_sadece_rax_hedefli()
    print("ASM arama (beam) testleri: ALL PASSED")
