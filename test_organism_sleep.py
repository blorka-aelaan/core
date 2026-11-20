#!/usr/bin/env python3
"""Tests for sleep consolidation in the organism tick lifecycle."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

from organism import Organism


class _Journal:
    def __init__(self):
        self.events = []

    def log(self, name, **data):
        self.events.append((name, data))


class _Sleep:
    min_enerji = 50
    max_ac = 50

    def __init__(self):
        self.calls = []

    def periyot_icin(self, drives):
        return 3

    def karar(self):
        return {"ad": "hatira", "veri": 1}

    def uyu(self, decision, beyn):
        self.calls.append((decision, beyn))
        return {"ad": "hatira", "kod": 0, "sure": 0.1}


def _organism(root, energy, hunger):
    organism = Organism.__new__(Organism)
    organism.uyku = _Sleep()
    organism.drives = SimpleNamespace(energy=energy, hunger=hunger)
    organism.mind = object()
    organism.jour = _Journal()
    organism.root = root
    organism.dam = SimpleNamespace(_disk_mtime=None)
    organism.guv = None
    organism.paket_beyin = None
    organism.tez = None
    organism._uyku_son_tik = 0
    return organism


with tempfile.TemporaryDirectory() as temp_dir:
    organism = _organism(Path(temp_dir), energy=80, hunger=10)
    organism._uykuyu_denetime_al(2)
    organism._uykuyu_denetime_al(3)

    assert len(organism.uyku.calls) == 1
    assert organism.uyku.calls[0][1] is organism.mind
    assert [event[0] for event in organism.jour.events] == [
        "uyku_basla",
        "uyku_bitti",
    ]

    organism = _organism(Path(temp_dir), energy=40, hunger=60)
    organism._uykuyu_denetime_al(3)
    assert organism.uyku.calls == []
    assert organism.jour.events == []

print("organism sleep lifecycle tests: ALL PASSED")
