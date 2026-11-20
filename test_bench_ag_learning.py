#!/usr/bin/env python3
"""Regression tests for the offline probe-learning benchmark."""

import unittest

from bench_ag_learning import run_benchmark


class ProbeBenchmarkTest(unittest.TestCase):
    def test_benchmark_is_reproducible_and_reports_held_out_comparisons(self):
        first = run_benchmark(seeds=2, train_episodes=5, test_episodes=4)
        second = run_benchmark(seeds=2, train_episodes=5, test_episodes=4)
        self.assertEqual(first, second)
        self.assertEqual(
            first["data_kind"],
            "synthetic_simulation_not_live_network_measurement",
        )
        self.assertEqual(first["independent_run_count"], 18)
        self.assertEqual(
            first["stationary_vs_shifted"]["stationary"]["runs"], 6
        )
        self.assertEqual(
            first["stationary_vs_shifted"]["after_environment_shift"]["runs"], 12
        )
        self.assertEqual(
            len(first["stationary_vs_shifted"]["stationary"]
                ["learned_minus_fixed_ci95_by_run"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
