#!/usr/bin/env python3
"""Tests for process telemetry sampling and online baseline learning."""

import os
import tempfile
from types import SimpleNamespace
from pathlib import Path

from surec import Surec
from organism import Organism
import noral_beyn as ust_beyn


def _snapshot(cpu_ticks, cpu_total, cpu_idle, available_kb, extra=None):
    processes = {
        "worker": {
            "count": 1, "cpu_ticks": cpu_ticks, "rss_kb": 1024, "R": 1, "S": 0,
        },
    }
    if extra:
        processes.update(extra)
    return {
        "processes": processes,
        "cpu_total": cpu_total,
        "cpu_idle": cpu_idle,
        "memory_total_kb": 4096,
        "memory_available_kb": available_kb,
    }


with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    monitor = Surec({"surec": {"periyot": 2}}, root=root)
    first = monitor.olcumle(
        _snapshot(100, 1000, 900, 3072), tik=2, simdi=100.0, saat=10.0
    )
    assert first["ok"] is True
    assert first["cpu_yuzde"] is None
    assert first["bellek_yuzde"] == 25.0
    assert first["surec_sayisi"] == 1
    assert first["surec_turu"] == 1

    second = monitor.olcumle(
        _snapshot(
            100 + int(os.sysconf("SC_CLK_TCK")),
            1100, 970, 2867,
            {"new-worker": {"count": 2, "cpu_ticks": 0, "rss_kb": 2048,
                            "R": 0, "S": 2}},
        ),
        tik=4,
        simdi=102.0,
        saat=11.0,
    )
    assert second["cpu_yuzde"] == 30.0
    assert second["bellek_yuzde"] == round(100 * (4096 - 2867) / 4096, 2)
    assert second["yeni"] == ["new-worker"]
    worker = next(row for row in second["surecler"] if row["ad"] == "worker")
    assert worker["cpu_yuzde"] == 100.0
    assert monitor.profiller["worker"]["gorulme_orani"] == 1.0
    assert second["degisim_skoru"] > 0
    signals = ust_beyn.topla_sinyalleri(
        SimpleNamespace(energy=50, energy_cap=100, hunger=10),
        None, None, None, monitor, [],
    )
    assert signals[ust_beyn.IDX_ANOMALI] == second["degisim_skoru"]
    assert len(monitor.gecmis) == 2

    monitor.save()
    restored = Surec({"surec": {}}, root=root)
    assert restored.load()
    assert restored.ornek == 2
    assert restored.son_olcum["tik"] == 4
    assert restored.profiller["worker"]["ornek"] == 2
    assert restored.sistem_profili["bellek_yuzde"]["ornek"] == 2
    assert "pid" not in str(restored.gecmis)

class _Journal:
    def __init__(self):
        self.events = []

    def log(self, name, **data):
        self.events.append((name, data))


class _Monitor:
    periyot = 2
    ornek = 5
    adet = {"worker": 4}

    def __init__(self):
        self.samples = []
        self.saves = 0

    def ornekle(self, tik):
        self.samples.append(tik)
        return {"ok": True, "ornek": self.ornek, "tik": tik}

    def save(self):
        self.saves += 1


organism = Organism.__new__(Organism)
organism.sur = _Monitor()
organism.jour = _Journal()
organism._yerel_surecleri_izle(1)
assert organism.sur.samples == []
organism._yerel_surecleri_izle(2)
assert organism.sur.samples == [2]
assert organism.sur.saves == 1
assert organism.jour.events[0][0] == "surec_olcum"
assert organism.jour.events[1][0] == "surec_save"

print("local process telemetry tests: ALL PASSED")
