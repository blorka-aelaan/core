#!/usr/bin/env python3
"""Gerçek sonuç geri bildirimi ve düşünme modelinin hold-out testleri."""

import tempfile
import json
from pathlib import Path
from types import SimpleNamespace

import brain
import home_world
import organism as organism_mod
import reward
import noral_beyn as ust_beyn
from dusunme import Dusunme
from training import SelfTrainer


def sinyal(enerji, aclik):
    x = [0.0] * 36
    x[0] = enerji
    x[1] = aclik
    return x


def test_contextual_reward_model():
    with tempfile.TemporaryDirectory(prefix="core_dusunme_") as tmp:
        model = Dusunme(object(), path=Path(tmp) / "model.json")
        aclik = sinyal(0.20, 0.80)
        tok = sinyal(0.80, 0.10)

        assert model.dusun_ve_sec(aclik, ["eat", "rest"]) == (None, None)
        for _ in range(8):
            model.observe(aclik, "eat", 8.0)
            model.observe(aclik, "rest", -3.0)
            model.observe(tok, "eat", -2.0)
            model.observe(tok, "rest", 3.0)

        test = [
            (sinyal(0.24, 0.84), "eat", 8.0),
            (sinyal(0.24, 0.84), "rest", -3.0),
            (sinyal(0.84, 0.14), "eat", -2.0),
            (sinyal(0.84, 0.14), "rest", 3.0),
        ]
        mae = sum(
            abs(model.tahmin(state, action)[1] - actual)
            for state, action, actual in test
        ) / len(test)
        random_baseline_mae = 4.0
        assert mae < random_baseline_mae, (mae, random_baseline_mae)
        assert model.dusun_ve_sec(aclik, ["eat", "rest"])[0] == "eat"
        assert model.dusun_ve_sec(tok, ["eat", "rest"])[0] == "rest"
        assert model.guven(aclik, "eat") > 0.7

        model.save()
        restored = Dusunme(object(), path=Path(tmp) / "model.json")
        assert restored.load()
        assert restored.samples == model.samples
        assert restored.dusun_ve_sec(aclik, ["eat", "rest"]) == \
            model.dusun_ve_sec(aclik, ["eat", "rest"])

        print("Düşünme hold-out MAE: %.3f (eylem ortalaması baseline: %.3f)"
              % (mae, random_baseline_mae))


def test_verified_command_reward():
    calc = reward.OdulHesaplayici()
    common = dict(gain=0, cost=0, veto=0, relief_done=0)
    basari = calc.sistem_odulu(
        **common, res={"dogru": True}, act="cmd:ls"
    )
    hata = calc.sistem_odulu(
        **common, res={"dogru": False}, act="cmd:ls"
    )
    belirsiz = calc.sistem_odulu(
        **common, res={}, act="cmd:ls"
    )
    unrelated = calc.sistem_odulu(
        **common, res={"dogru": True}, act="eat"
    )
    help_not_task_success = calc.sistem_odulu(
        **common, res={"dogru": None, "help_ok": True}, act="help:ls"
    )
    assert basari == 2.0
    assert hata == -2.0
    assert belirsiz == 0.0
    assert unrelated == 0.0
    assert help_not_task_success == 0.0
    failed_novel = calc.sistem_odulu(
        **common,
        res={"dogru": False, "novel": 100, "novel_cmd": True},
        act="cmd:ls",
    )
    assert abs(failed_novel + 0.2) < 1e-9
    failed_parts = calc.hesapla(
        **common,
        res={"dogru": False, "novel": 100, "novel_cmd": True},
        act="cmd:ls", in_danger=False, was_danger=False, pain=0,
        pain_penalty=0, relief_bonus=0,
    )
    assert failed_parts["yenilik"] == 1.8
    assert failed_parts["dogrulanmis_komut"] == -2.0
    assert failed_parts["alt_beyin"] < 0.0

    chain_progress = calc.hesapla(
        gain=3, cost=1, veto=0, relief_done=0,
        res={"dogru": False, "dogrulanmis": True, "ilerleme": True},
        act="cmd:ps", in_danger=False, was_danger=False, pain=0,
        pain_penalty=0, relief_bonus=0,
    )
    assert chain_progress["dogrulanmis_komut"] == 0.0
    assert chain_progress["alt_beyin"] == 2.0
    chain_failure = calc.sistem_odulu(
        gain=0, cost=1, veto=0, relief_done=0,
        res={"dogru": False, "dogrulanmis": True},
        act="cmd:wc",
    )
    assert chain_failure == -3.0
    print("Doğrulanmış komut ödülü: başarı=%.1f başarısızlık=%.1f"
          % (basari, hata))


def test_reward_confidence_tracks_variability():
    model = Dusunme(object())
    state = sinyal(0.8, 0.2)
    for value in (5.0,) * 12:
        model.observe(state, "steady", value)
    for value in (0.0, 10.0) * 6:
        model.observe(state, "noisy", value)
    steady = model.guven(state, "steady")
    noisy = model.guven(state, "noisy")
    assert steady > noisy, (steady, noisy)
    assert noisy < 0.5, noisy
    print("Tahmin güveni değişken ödülde düşüyor: %.2f > %.2f"
          % (steady, noisy))


def test_reward_learning_separation():
    calc = reward.OdulHesaplayici()
    result = calc.hesapla(
        gain=0, cost=0, veto=0, relief_done=0, res={}, act="wander",
        in_danger=True, was_danger=False, pain=0.5, pain_penalty=4,
        relief_bonus=8, komut="yok",
        drives_state={"in_danger": True, "pain": 0.5},
    )
    assert result["alt_beyin"] == -2.0
    assert result["ust_beyn"] == -0.2
    assert result["toplam"] == -2.2
    assert result["toplam"] == (
        result["alt_beyin"] + result["ust_beyn"]
    )
    upper_without_system_reward = calc.ust_beyn_odulu(
        0.0, "acil_yem", drives_state={"aclik_once": 80, "yemek_var": True}
    )
    upper_with_large_system_reward = calc.ust_beyn_odulu(
        1000.0, "acil_yem",
        drives_state={"aclik_once": 80, "yemek_var": True},
    )
    assert upper_without_system_reward == upper_with_large_system_reward
    print("Ödül ayrımı: alt=%.2f üst=%.2f"
          % (result["alt_beyin"], result["ust_beyn"]))


def test_energy_signal_normalization():
    for energy, expected in ((300.0, 2 / 3), (450.0, 1.0), (500.0, 1.0)):
        drives = SimpleNamespace(
            energy=energy, energy_cap=450.0, hunger=50.0, sikilma=0.2,
            in_danger=False, alive=True, pain=lambda: 0.1,
        )
        signals = ust_beyn.topla_sinyalleri(
            drives, None, None, None, None, []
        )
        assert abs(signals[ust_beyn.IDX_ENERJI] - expected) < 1e-9
        assert all(0.0 <= value <= 1.0 for value in signals)
    print("Enerji sinyali gerçek kapasiteye göre [0,1] aralığında")


def test_task_and_previous_action_context():
    org = object.__new__(organism_mod.Organism)
    org.drives = SimpleNamespace(
        bins=lambda: ("E", "H"), energy=300.0, hunger=20.0, sikilma=0.0
    )
    org.bod = SimpleNamespace(location="root", last_food_loc="root")
    org.state = {"last": "help:stat"}
    org.hedef_tip = "DOSYA_OLC"
    org.mind = SimpleNamespace(AILE=brain.Brain.AILE)
    org.sur = SimpleNamespace(eksik=False, yeni=False)
    org.kul = SimpleNamespace(hedef_deneme=0, ara="")
    org.atolye = SimpleNamespace(model={})
    org.home_world = home_world.HomeWorld({})
    org._home_world_signature = None
    org.jour = SimpleNamespace(log=lambda *_args, **_kwargs: None)

    tokens = org._topla_sinyal().split("|")
    assert "gorev:DOSYA_OLC" in tokens
    assert "gorev_aile:DOSYA" in tokens
    assert any(token.startswith("home:resources:") for token in tokens)
    assert "internet:observation:disabled" in tokens
    assert "son:help:stat" in tokens
    assert "deneme:1" in tokens
    print("Görev, önceki yardım ve komut sonucu sinyal bağlamında")


def test_legacy_upper_model_migration():
    with tempfile.TemporaryDirectory(prefix="core_ust_model_") as tmp:
        root = Path(tmp)
        legacy = ust_beyn.NöralUstBeyn({}, root=root, seed=3)
        # Pure-Python NöralBeyn: W1 = ağırlıklar[0] (liste), NumPy yok.
        legacy.mlp.ağırlıklar[0] = [
            [0.0 for _ in row] for row in legacy.mlp.ağırlıklar[0]
        ]
        for row in legacy.mlp.ağırlıklar[0]:
            row[ust_beyn.IDX_ENERJI] = 2.0
        legacy.save()

        model_path = root / "zeka" / "ust_beyn.json"
        data = json.loads(model_path.read_text(encoding="utf-8"))
        data["surum"] = 2
        model_path.write_text(json.dumps(data), encoding="utf-8")

        migrated = ust_beyn.NöralUstBeyn({}, root=root, seed=3)
        assert all(
            row[ust_beyn.IDX_ENERJI] == 6.0
            for row in migrated.mlp.ağırlıklar[0]
        )
    print("Eski üst-beyin enerji ağırlıkları ölçek eşdeğerliğiyle taşındı")


def test_brain_contextual_learning_benchmark():
    train_cases = (
        ("state:hungry", "eat"),
        ("state:rested", "rest"),
    )
    holdout_cases = (
        ("state:hungry|phase:holdout", "eat"),
        ("state:rested|phase:holdout", "rest"),
    )
    scores = []
    for seed in (3, 11, 29, 47, 83):
        model = brain.Brain(seed=seed, lr=0.12, epsilon=0.35)
        for _ in range(120):
            for state, target in train_cases:
                action = model.decide(state, brain.ACTIONS)
                model.learn(state, action, 1.0 if action == target else -1.0)
        correct = sum(
            max(brain.ACTIONS, key=lambda action: model.score(state, action))
            == target
            for state, target in holdout_cases
        )
        scores.append(correct / len(holdout_cases))

    learning_accuracy = sum(scores) / len(scores)
    constant_action_baseline = 0.5
    assert learning_accuracy > constant_action_baseline, (
        scores, learning_accuracy, constant_action_baseline
    )
    print(
        "Brain sentetik hold-out: %.2f (sabit eylem baseline: %.2f; "
        "seed sayısı: %d)"
        % (learning_accuracy, constant_action_baseline, len(scores))
    )


def test_brain_explores_least_tried_contextual_action():
    model = brain.Brain(seed=17, epsilon=100.0)
    state = "H|gorev:SUREC_SAY|ara:yok"
    actions = ["eat", "rest", "cmd:ps"]
    features, _ = brain.Brain._bilesen(state)
    for feature in features:
        model.usage[(feature, "eat")] = 20
        model.usage[(feature, "cmd:ps")] = 5

    selected = model.decide(state, actions)
    assert selected == "rest", (selected, model.usage)
    print("Bağlamsal keşif, en az denenmiş eylemi seçti")


def test_training_data_quality():
    class Model:
        def __init__(self):
            self.mlp = SimpleNamespace(n_in=36, n_out=2)
            self.updates = []

        def ogren(self, sinyal, idx, odul):
            self.updates.append((list(sinyal), idx, odul))

    def row(idx=1, odul=0.5,
            signal_version=ust_beyn.SINYAL_SURUMU):
        return {"kind": "ust_ogren", "sinyal": [0.0] * 36,
                "idx": idx, "odul": odul,
                "sinyal_surumu": signal_version}

    with tempfile.TemporaryDirectory(prefix="core_training_") as tmp:
        journal = Path(tmp) / "journal.jsonl"
        model = Model()
        trainer = SelfTrainer(model, journal, epochs=1, min_samples=2)
        journal.write_text(
            "\n".join(json.dumps(r) for r in (
                row(), row(2), row(1, float("nan")),
                {**row(), "sinyal": [0.0]}, row(signal_version=1),
            )) + "\n",
            encoding="utf-8",
        )
        trainer.train()
        assert trainer.stats()["samples"] == 1
        assert trainer.stats()["rejected_samples"] == 4
        assert not model.updates

        with journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row()) + "\n")
        trainer.train()
        assert len(model.updates) == 2

        journal.write_text(json.dumps(row(1, 1.0)) + "\n", encoding="utf-8")
        trainer._collect()
        assert trainer._offset == journal.stat().st_size
        assert trainer.stats()["rejected_samples"] == 4

        complete = json.dumps(row())
        journal.write_text(complete[:-4], encoding="utf-8")
        assert trainer._collect() == []
        with journal.open("a", encoding="utf-8") as f:
            f.write(complete[-4:] + "\n")
        assert len(trainer._collect()) == 1
    print("Eğitim: bozuk örnekler reddedildi, eksik mini-batch saklandı")


if __name__ == "__main__":
    test_contextual_reward_model()
    test_verified_command_reward()
    test_reward_confidence_tracks_variability()
    test_reward_learning_separation()
    test_energy_signal_normalization()
    test_task_and_previous_action_context()
    test_legacy_upper_model_migration()
    test_brain_contextual_learning_benchmark()
    test_brain_explores_least_tried_contextual_action()
    test_training_data_quality()
