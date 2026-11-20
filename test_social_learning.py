#!/usr/bin/env python3
"""Tests for opt-in, isolated social skill exchange."""

import json
import tempfile
import unittest
from pathlib import Path

from social_learning import SocialLearning


class SocialLearningTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.exchange = self.base / "exchange"
        self.alice = self.base / "alice"
        self.bob = self.base / "bob"

    def tearDown(self):
        self.temp.cleanup()

    def _configure(self, root, instance, peers):
        zeka = root / "zeka"
        zeka.mkdir(parents=True, exist_ok=True)
        (zeka / "social.json").write_text(json.dumps({
            "enabled": True,
            "instance_id": instance,
            "peers": peers,
            "exchange_dir": str(self.exchange),
        }), encoding="utf-8")

    def test_peer_result_is_not_used_until_receiver_has_local_validation(self):
        self._configure(self.alice, "alice", ["bob"])
        self._configure(self.bob, "bob", ["alice"])
        now = [100_000.0]
        sender = SocialLearning(self.alice, clock=lambda: now[0])
        receiver = SocialLearning(self.bob, clock=lambda: now[0])
        sender.exchange({
            "nmap_tcp_ports": {
                "attempts": 8, "successes": 8, "failures": 0,
                "reward_total": 16.0,
            },
        })

        received = receiver.exchange({})
        self.assertEqual(received["reports_new"], 1)
        self.assertEqual(received["reports_received"], 1)
        self.assertIsNone(receiver.prior(
            "nmap_tcp_ports", {"attempts": 2, "successes": 2}
        ))
        prior = receiver.prior(
            "nmap_tcp_ports", {"attempts": 3, "successes": 3}
        )
        self.assertEqual(prior, {"mean_reward": 2.0, "weight": 1.0})

        # Re-reading an unchanged report is idempotent.
        self.assertEqual(receiver.exchange({})["reports_new"], 0)

    def test_only_allowlisted_peer_and_fixed_skill_ids_are_accepted(self):
        self._configure(self.bob, "bob", ["alice"])
        inbox = self.exchange / "bob" / "inbox"
        inbox.mkdir(parents=True)
        for sender, skill, filename in (
            ("mallory", "nmap_tcp_ports", "untrusted.json"),
            ("alice", "shell", "unknown-skill.json"),
        ):
            (inbox / filename).write_text(json.dumps({
                "schema": 1,
                "kind": "validated_skill_summary",
                "sender": sender,
                "recipient": "bob",
                "skill": skill,
                "attempts": 9,
                "success_rate": 1.0,
                "mean_reward": 2.0,
                "sent_at": 100_000.0,
            }), encoding="utf-8")
        receiver = SocialLearning(self.bob, clock=lambda: 100_000.0)
        state = receiver.exchange({})
        self.assertEqual(state["reports_received"], 0)
        self.assertIsNone(receiver.prior(
            "nmap_tcp_ports", {"attempts": 5, "successes": 5}
        ))

    def test_social_learning_is_disabled_without_explicit_config(self):
        receiver = SocialLearning(self.bob, clock=lambda: 100_000.0)
        state = receiver.exchange({})
        self.assertFalse(state["enabled"])
        self.assertFalse(self.bob.joinpath("zeka/social_memory.json").exists())


if __name__ == "__main__":
    unittest.main()
