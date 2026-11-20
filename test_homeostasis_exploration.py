#!/usr/bin/env python3
"""Adaptif yeme ve güvenli keşif davranışı regresyon testleri."""

from types import SimpleNamespace

from drives import Drives
from organism import Organism


def make_drives(energy=450.0, hunger=0.0):
    return Drives({
        "metabolism": {
            "energy_start": energy,
            "energy_cap": 450.0,
            "energy_decay_per_tick": 4.0,
            "hunger_start": hunger,
            "hunger_growth_per_tick": 4.0,
            "eat_hunger_relief": 45.0,
            "pain_threshold": 30.0,
        }
    })


def test_eating_tracks_need():
    drives = make_drives()
    assert not drives.needs_food

    drives.hunger = drives.eat_hunger_threshold
    assert drives.needs_food

    drives.hunger = 0.0
    drives.energy = drives.energy_cap * drives.eat_energy_ratio
    assert drives.needs_food

    drives.energy = drives.pain_threshold
    assert drives.needs_food

    organism = object.__new__(Organism)
    organism.drives = drives
    organism.kul = SimpleNamespace(eylemler=lambda: ["cmd:ls", "help:ls"])
    assert "eat" in organism._hesapla_feasible()

    drives.energy = drives.energy_cap
    drives.hunger = 0.0
    assert "eat" not in organism._hesapla_feasible()
    organism.mind = SimpleNamespace(decide=lambda _stim, feasible: feasible[0])
    actions, selected = organism._beslenmeyi_sinirla(
        "state", ["eat", "rest"], "eat"
    )
    assert "eat" not in actions
    assert selected == "rest"


def test_safe_exploration_schedule():
    organism = object.__new__(Organism)
    organism.drives = make_drives()
    organism.hedef_tip = None
    assert organism.drives.safe_to_explore
    assert organism._kesif_araligi() == 40

    organism.hedef_tip = "AG_TARA"
    assert organism._kesif_araligi() == 100

    organism.hedef_tip = None
    organism.drives.hunger = 40.0
    assert not organism.drives.safe_to_explore
    assert organism._kesif_araligi() == 100


if __name__ == "__main__":
    test_eating_tracks_need()
    test_safe_exploration_schedule()
    print("Adaptif beslenme ve güvenli keşif: 2/2 OK")
