#!/usr/bin/env python3
"""Tests for solving user-provided ASM input/output examples."""

import contextlib
import io
import json
import random
import tempfile
import time
from pathlib import Path

from uzuv.asm_ogren import (
    AssemblyLearner,
    BeamSearchSolver,
    CURRICULUM,
    Emulator,
    LearningState,
    MAX_MEMORY_BYTES,
    OPS,
    SolveResult,
    Task,
    TaskGenerator,
    context_key,
    main,
)
from uzuv.asm_uzuv import AsmUzuv


with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    asm = AsmUzuv(root=root)
    state = LearningState(root / "uzuv" / "asm_ogren.json")
    learner = AssemblyLearner(
        asm, state, CURRICULUM, OPS, Emulator(), random.Random(7)
    )
    initial_stats = dict(asm.istatistikler)
    initial_programs = dict(asm.bilinen_programlar)

    result = learner.solve_examples(
        training=[
            {"input": {"rax": 2}, "output": {"rax": 3}},
            {"input": {"rax": 7}, "output": {"rax": 8}},
        ],
        validation=[
            {"input": {"rax": 20}, "output": {"rax": 21}},
        ],
        max_length=1,
        budget=1000,
    )
    assert result.solved, result
    assert result.program and len(result.program) == 1

    emulator = Emulator()
    cmp_op = next(op for op in OPS if op[1] == "cmp rax, rbx")
    generator = TaskGenerator(emulator, [cmp_op], CURRICULUM)
    task = generator.generate(
        asm, random.Random(13), level=2, length=1, max_attempts=1
    )
    assert task is not None
    assert len(task.training) == 6
    assert len(task.secret) == 4
    train_inputs = {
        tuple(row[register] for register in CURRICULUM[2].registers)
        for row in task.training
    }
    validation_inputs = {
        tuple(row[register] for register in CURRICULUM[2].registers)
        for row in task.secret
    }
    assert train_inputs.isdisjoint(validation_inputs)
    assert all({"ZF", "CF", "OF"}.issubset(row["cikti"]) for row in task.training)

    cmp_equal = emulator.run(
        [cmp_op], {"rax": 5, "rbx": 5}, include_flags=True
    )
    cmp_below = emulator.run(
        [cmp_op], {"rax": 3, "rbx": 5}, include_flags=True
    )
    assert cmp_equal is not None
    assert cmp_equal["ZF"] == 1 and cmp_equal["CF"] == 0
    assert cmp_below is not None
    assert cmp_below["ZF"] == 0 and cmp_below["CF"] == 1

    memory_initial = {
        address: (address * 17 + 3) & 255
        for address in range(8, 16)
    }
    write_imm = next(op for op in OPS if op[1] == "mov [rax], 5")
    read_mem = next(op for op in OPS if op[1] == "mov rbx, [rax]")
    memory_program = [write_imm, read_mem]
    memory_prediction = emulator.run(
        memory_program,
        {"rax": 8, "rbx": 0, "rcx": 0, "rdx": 0},
        initial_memory=memory_initial,
        include_memory=True,
    )
    expected_memory = {
        address: value for address, value in memory_initial.items()
    }
    expected_memory.update({address: 0 for address in range(8, 16)})
    expected_memory[8] = 5
    assert memory_prediction is not None
    assert memory_prediction["rbx"] == 5
    assert memory_prediction["bellek"] == expected_memory
    assert emulator.run(
        [write_imm],
        {"rax": MAX_MEMORY_BYTES - 4},
        initial_memory=memory_initial,
    ) is None

    memory_result = asm._calistir(
        "mov [rax], 5\nmov rbx, [rax]",
        {"rax": 8},
        memory_initial,
        range(8, 16),
    )
    assert memory_result["tamam"], memory_result
    assert memory_result["yazmac"]["rbx"] == 5
    assert memory_result["bellek"] == expected_memory
    boundary_result = asm._calistir(
        "mov [rax], 5",
        {"rax": MAX_MEMORY_BYTES - 8},
        {MAX_MEMORY_BYTES - 8: 0},
        range(MAX_MEMORY_BYTES - 8, MAX_MEMORY_BYTES),
    )
    assert boundary_result["tamam"], boundary_result
    assert boundary_result["bellek"] == {
        MAX_MEMORY_BYTES - 8: 5,
        **{address: 0 for address in range(MAX_MEMORY_BYTES - 7, MAX_MEMORY_BYTES)},
    }
    outside_result = asm._calistir(
        "mov [rax], 5", {"rax": MAX_MEMORY_BYTES - 4}
    )
    assert not outside_result["tamam"]

    state = LearningState(root / "uzuv" / "asm_ogren.json")
    solver = BeamSearchSolver(emulator, [cmp_op], CURRICULUM)
    solved = solver.solve(
        asm, task, state.weights, random.Random(13), 2, state,
        record_to_brain=False, max_length=1,
    )
    assert solved.solved and solved.program == ["cmp rax, rbx"], solved
    assert solved.attempts_detail.get("cmp:rr", 0) > 0
    assert state.programs

    reused = solver.solve(
        asm, task, state.weights, random.Random(13), 2, state,
        record_to_brain=False, max_length=1,
    )
    assert reused.solved and reused.program == solved.program
    expired = solver.solve(
        asm, task, state.weights, random.Random(13), 2, state,
        record_to_brain=False, max_length=1, deadline=time.monotonic() - 1,
    )
    assert expired.timed_out and expired.attempts == 0

    state.save()
    restored_state = LearningState(state.path)
    restored_state.load()
    assert restored_state.programs == state.programs

    memory_ops = [op for op in OPS if op[1] == "mov [rax], 5"]
    memory_generator = TaskGenerator(emulator, memory_ops, CURRICULUM)
    memory_task = memory_generator.generate(
        asm, random.Random(17), level=4, length=1, max_attempts=1
    )
    assert memory_task is not None
    assert "bellek" in memory_task.training[0]["cikti"]
    memory_solver = BeamSearchSolver(emulator, memory_ops, CURRICULUM)
    memory_solved = memory_solver.solve(
        asm, memory_task, {}, random.Random(17), 4, None,
        record_to_brain=False, max_length=1,
    )
    assert memory_solved.solved, memory_solved

    feedback_root = root / "feedback"
    feedback_root.mkdir()
    feedback_state = LearningState(feedback_root / "asm_ogren.json")
    feedback_training = [
        {"rax": 2, "rbx": 0, "cikti": {"rax": 3, "rbx": 0}},
        {"rax": 7, "rbx": 0, "cikti": {"rax": 8, "rbx": 0}},
    ]
    feedback_task = Task(
        level=1, length=1,
        program=[next(op for op in OPS if op[1] == "sub rax, 1")],
        code="sub rax, 1", training=feedback_training, secret=[],
    )

    class _OneTaskGenerator:
        def generate(self, *_args, **_kwargs):
            return feedback_task

    class _FeedbackSolver:
        def __init__(self):
            self.deadlines = []

        def solve(self, *_args, deadline=None, **_kwargs):
            self.deadlines.append(deadline)
            assert deadline is not None
            time.sleep(max(0.0, deadline - time.monotonic() + 0.01))
            return SolveResult(
                solved=True, program=["add rax, 1"], attempts=5,
                emulator_mismatch=0, attempts_detail={"add:ri": 3, "sub:ri": 2},
                successful_detail={"add:ri": 3, "sub:ri": 2},
            )

    feedback_solver = _FeedbackSolver()
    feedback_learner = AssemblyLearner(
        asm, feedback_state, CURRICULUM, OPS, emulator,
        random.Random(3),
    )
    setattr(feedback_learner, "generator", _OneTaskGenerator())
    setattr(feedback_learner, "solver", feedback_solver)
    feedback_learner.run(
        0.001, solution_path=feedback_root / "solutions.jsonl"
    )
    assert len(feedback_state.weights.records) >= 0
    print("ASM solver feedback test: OK")
    assert len(feedback_solver.deadlines) == 1
    assert feedback_solver.deadlines[0] is not None

    rejected = learner.solve_examples(
        training=[
            {"input": {"rax": 2}, "output": {"rax": 3}},
        ],
        validation=[
            {"input": {"rax": 20}, "output": {"rax": 22}},
        ],
        max_length=1,
        budget=1000,
    )
    assert not rejected.solved, "a program that failed held-out validation was accepted"

    try:
        learner.solve_examples(
            training=[
                {"input": {"rax": 2}, "output": {"rax": 3}},
            ],
            validation=[
                {"input": {"rax": 2}, "output": {"rax": 3}},
            ],
            max_length=1,
        )
    except ValueError as error:
        assert "separate" in str(error)
    else:
        raise AssertionError("overlapping validation input was accepted")

    try:
        learner.solve_examples(
            training=[{"input": {"rax": True}, "output": {"rax": 1}}],
            validation=[{"input": {"rax": 2}, "output": {"rax": 3}}],
        )
    except ValueError as error:
        assert "integer" in str(error)
    else:
        raise AssertionError("boolean register value was accepted")

    cli_root = root / "cli"
    cli_root.mkdir()
    task_path = root / "task.json"
    task_path.write_text(json.dumps({
        "training": [
            {"input": {"rax": 3}, "output": {"rax": 4}},
            {"input": {"rax": 8}, "output": {"rax": 9}},
        ],
        "validation": [
            {"input": {"rax": 30}, "output": {"rax": 31}},
        ],
    }), encoding="utf-8")
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = main([
            "--coz-json", str(task_path),
            "--kok", str(cli_root),
            "--azami-komut", "1",
        ])
    assert exit_code == 0
    assert json.loads(output.getvalue())["cozuldu"] is True
    invalid_task_path = root / "invalid-task.json"
    invalid_task_path.write_text(json.dumps({"training": []}), encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()):
        invalid_exit_code = main([
            "--coz-json", str(invalid_task_path),
            "--kok", str(cli_root),
        ])
    assert invalid_exit_code == 2

print("ASM example solver tests: ALL PASSED")
