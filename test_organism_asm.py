#!/usr/bin/env python3
"""ASM command integration tests for the organism loop."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from organism import Organism


class _Journal:
    def __init__(self):
        self.events = []

    def log(self, name, **data):
        self.events.append((name, data))


class _Drives:
    def __init__(self, energy, in_danger=False):
        self.energy = energy
        self.in_danger = in_danger


class _Ust:
    def __init__(self):
        self.run_calls = []
        self.save_calls = 0

    def asm_öğren(self, dakika, nn_ana=None):
        self.run_calls.append(dakika)
        return {
            "oturum_gorev": 10,
            "oturum_cozulen": 8,
            "yeni_primtik": 1,
        }

    def save(self):
        self.save_calls += 1


def _organism(energy, in_danger=False):
    organism = Organism.__new__(Organism)
    organism.drives = _Drives(energy, in_danger)
    organism.ust = _Ust()
    organism.jour = _Journal()
    return organism


organism = _organism(energy=50)
result = organism._asm_ogren_komutunu_calistir()
assert result["oturum_gorev"] == 10
assert organism.ust.run_calls == [2.0]
assert organism.ust.save_calls == 1
assert organism.jour.events[-1][0] == "asm_ogren_dongu"

for organism in (_organism(energy=30), _organism(energy=50, in_danger=True)):
    assert organism._asm_ogren_komutunu_calistir() is None
    assert organism.ust.run_calls == []
    assert organism.ust.save_calls == 0
    assert organism.jour.events[-1] == (
        "asm_ogren_atlandi", {"neden": "kaynak_az"}
    )

print("organism ASM integration tests: ALL PASSED")
