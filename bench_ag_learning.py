#!/usr/bin/env python3
"""Offline paired benchmark for the bounded network probe selector.

The simulated rewards are deliberately synthetic: current persisted scans do
not yet contain enough per-probe outcome history for a real-world comparison.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
from pathlib import Path
from typing import Any

from ag_beyin import AgBeyin, PROBE_ACTIONS


PROFILES = {
    "port_rich": {
        "nmap_tcp_ports": 4.0,
        "avahi_browse": 1.5,
        "ip_neigh": 1.1,
    },
    "service_rich": {
        "nmap_tcp_ports": 1.5,
        "avahi_browse": 3.4,
        "ip_neigh": 1.0,
    },
    "neighbor_rich": {
        "nmap_tcp_ports": 1.4,
        "avahi_browse": 1.2,
        "ip_neigh": 3.1,
    },
}
NOISE_SD = 0.35


def _draw_rewards(
    means: dict[str, float], count: int, rng: random.Random
) -> list[dict[str, float]]:
    return [
        {
            action: max(0.0, rng.gauss(means[action], NOISE_SD))
            for action in PROBE_ACTIONS
        }
        for _ in range(count)
    ]


def _seed_learning(brain: AgBeyin, rewards: list[dict[str, float]]) -> None:
    for index, reward_row in enumerate(rewards):
        action = brain._choose_probe(PROBE_ACTIONS)
        brain._record_probe_result(action, reward_row[action], index + 1)


def _run_profile(
    scenario: str,
    profile_name: str,
    train_means: dict[str, float],
    test_means: dict[str, float],
    seed: int,
    train_episodes: int,
    test_episodes: int,
    root: Path,
) -> dict[str, Any]:
    rng = random.Random(seed)
    training = _draw_rewards(train_means, train_episodes, rng)
    held_out = _draw_rewards(test_means, test_episodes, rng)

    learner = AgBeyin(root)
    _seed_learning(learner, training)

    # Select this baseline only on the training partition, then freeze it.
    observed_train_means = {
        action: statistics.fmean(row[action] for row in training)
        for action in PROBE_ACTIONS
    }
    fixed_action = max(
        PROBE_ACTIONS, key=lambda action: observed_train_means[action]
    )
    random_picker = random.Random(seed ^ 0x5F3759DF)
    learned_rewards = []
    fixed_rewards = []
    random_rewards = []
    oracle_rewards = []
    selected_best = 0

    for index, row in enumerate(held_out):
        action = learner._choose_probe(PROBE_ACTIONS)
        value = row[action]
        learner._record_probe_result(
            action, value, train_episodes + index + 1, verified=True
        )
        learned_rewards.append(value)
        fixed_rewards.append(row[fixed_action])
        random_action = random_picker.choice(PROBE_ACTIONS)
        random_rewards.append(row[random_action])
        best_action = max(PROBE_ACTIONS, key=lambda item: row[item])
        oracle_rewards.append(row[best_action])
        selected_best += action == best_action

    return {
        "scenario": scenario,
        "profile": profile_name,
        "seed": seed,
        "fixed_action": fixed_action,
        "learned_mean": statistics.fmean(learned_rewards),
        "fixed_mean": statistics.fmean(fixed_rewards),
        "random_mean": statistics.fmean(random_rewards),
        "oracle_mean": statistics.fmean(oracle_rewards),
        "learned_best_action_rate": selected_best / test_episodes,
    }


def _bootstrap_ci(
    paired_differences: list[float],
    seed: int,
    iterations: int = 4000,
) -> list[float]:
    rng = random.Random(seed)
    size = len(paired_differences)
    estimates = [
        statistics.fmean(
            paired_differences[rng.randrange(size)] for _ in range(size)
        )
        for _ in range(iterations)
    ]
    estimates.sort()
    return [
        estimates[int(iterations * 0.025)],
        estimates[min(iterations - 1, int(iterations * 0.975))],
    ]


def run_benchmark(
    seeds: int = 30,
    train_episodes: int = 120,
    test_episodes: int = 80,
) -> dict[str, Any]:
    if seeds < 2 or train_episodes < len(PROBE_ACTIONS) or test_episodes < 1:
        raise ValueError("benchmark boyutlari cok kucuk")
    runs = []
    with tempfile.TemporaryDirectory(prefix="core-probe-bench-") as temp_dir:
        root = Path(temp_dir)
        for profile_index, (name, means) in enumerate(PROFILES.items()):
            for seed in range(seeds):
                run_seed = 10_000 * profile_index + seed
                runs.append(_run_profile(
                    "stationary", name, means, means, run_seed,
                    train_episodes, test_episodes,
                    root / ("stationary-%s-%d" % (name, seed)),
                ))
        shift_index = 0
        for source_name, source_means in PROFILES.items():
            for target_name, target_means in PROFILES.items():
                if source_name == target_name:
                    continue
                for seed in range(seeds):
                    run_seed = 1_000_000 + shift_index * 10_000 + seed
                    runs.append(_run_profile(
                        "shifted_%s_to_%s" % (source_name, target_name),
                        target_name, source_means, target_means, run_seed,
                        train_episodes, test_episodes,
                        root / ("shifted-%d-%d" % (shift_index, seed)),
                    ))
                shift_index += 1

    profile_results = []
    for profile_name in PROFILES:
        group = [
            run for run in runs
            if run["scenario"] == "stationary" and run["profile"] == profile_name
        ]
        profile_results.append({
            "profile": profile_name,
            "runs": len(group),
            "learned_mean_reward": statistics.fmean(
                run["learned_mean"] for run in group
            ),
            "fixed_mean_reward": statistics.fmean(
                run["fixed_mean"] for run in group
            ),
            "random_mean_reward": statistics.fmean(
                run["random_mean"] for run in group
            ),
            "oracle_mean_reward": statistics.fmean(
                run["oracle_mean"] for run in group
            ),
        })
    stationary_runs = [run for run in runs if run["scenario"] == "stationary"]
    shifted_runs = [run for run in runs if run["scenario"].startswith("shifted_")]
    comparisons = {}
    for label, group in (
        ("stationary", stationary_runs),
        ("after_environment_shift", shifted_runs),
    ):
        learned_fixed = [
            run["learned_mean"] - run["fixed_mean"] for run in group
        ]
        learned_random = [
            run["learned_mean"] - run["random_mean"] for run in group
        ]
        comparisons[label] = {
            "runs": len(group),
            "learned_mean_reward": statistics.fmean(
                run["learned_mean"] for run in group
            ),
            "fixed_train_selected_mean_reward": statistics.fmean(
                run["fixed_mean"] for run in group
            ),
            "random_mean_reward": statistics.fmean(
                run["random_mean"] for run in group
            ),
            "per_episode_oracle_upper_bound": statistics.fmean(
                run["oracle_mean"] for run in group
            ),
            "learned_minus_fixed": statistics.fmean(learned_fixed),
            "learned_minus_fixed_ci95_by_run": _bootstrap_ci(
                learned_fixed,
                2026110601 if label == "stationary" else 2026110603,
            ),
            "learned_minus_random": statistics.fmean(learned_random),
            "learned_minus_random_ci95_by_run": _bootstrap_ci(
                learned_random,
                2026110602 if label == "stationary" else 2026110604,
            ),
            "learned_best_action_rate": statistics.fmean(
                run["learned_best_action_rate"] for run in group
            ),
        }
    return {
        "data_kind": "synthetic_simulation_not_live_network_measurement",
        "seeds_per_profile": seeds,
        "profiles": len(PROFILES),
        "train_episodes_per_run": train_episodes,
        "held_out_episodes_per_run": test_episodes,
        "independent_run_count": len(runs),
        "metric": "mean newly discovered evidence reward per scan",
        "stationary_vs_shifted": comparisons,
        "by_profile": profile_results,
        "interpretation": (
            "The oracle is an unattainable per-episode upper bound. "
            "A confidence interval crossing zero does not establish a "
            "reliable improvement over that baseline."
        ),
    }


def historical_probe_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("ag_beyin.json okunamadi: %s" % error) from error
    return sum(
        1 for scan in data.get("scans", [])
        if scan.get("probe") in PROBE_ACTIONS
        and isinstance(scan.get("probe_reward"), (int, float))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--train", type=int, default=120)
    parser.add_argument("--test", type=int, default=80)
    parser.add_argument(
        "--memory",
        type=Path,
        default=Path(__file__).resolve().parent / "zeka" / "ag_beyin.json",
    )
    args = parser.parse_args()
    report = run_benchmark(args.seeds, args.train, args.test)
    report["historical_probe_observations"] = historical_probe_count(args.memory)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
