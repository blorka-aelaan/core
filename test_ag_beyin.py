#!/usr/bin/env python3
"""Tests for bounded network knowledge and its five-per-day schedule."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ag_beyin import (
    AgBeyin,
    SCAN_PROFILE_VERSION,
    parse_avahi_output,
    parse_ip_neigh,
    parse_nmap_xml,
)


DISCOVERY_XML = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.1.5" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="80">
      <state state="closed"/>
    </port></ports>
  </host>
  <host>
    <status state="down"/>
    <address addr="192.168.1.6" addrtype="ipv4"/>
  </host>
</nmaprun>"""

PORTS_XML = """<?xml version="1.0"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.1.5" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/></port>
      <port protocol="tcp" portid="631"><state state="open"/></port>
      <port protocol="tcp" portid="9100"><state state="closed"/></port>
    </ports>
  </host>
</nmaprun>"""


class AgBeyinTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "ag_kapsam.json").write_text(json.dumps({
            "acik": True,
            "izin_aglari": [
                "192.168.1.0/24",
                "127.0.0.0/8",
                "8.8.8.8/32",
                "10.0.0.0/16",
            ],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_scope_keeps_only_small_private_lan_networks(self):
        brain = AgBeyin(self.root)
        networks, error = brain._scope()
        self.assertIsNone(error)
        self.assertEqual(networks, ["192.168.1.0/24"])

    def test_xml_parser_keeps_up_hosts_and_open_tcp_ports(self):
        found = parse_nmap_xml(PORTS_XML)
        self.assertEqual(found, {"192.168.1.5": [22, 631]})

    def test_ip_neighbor_parser_filters_out_of_scope_and_failed_entries(self):
        found = parse_ip_neigh(
            "192.168.1.5 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"
            "8.8.8.8 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"
            "192.168.1.9 dev eth0 FAILED\n"
            "fe80::1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE",
            ["192.168.1.0/24"],
        )
        self.assertEqual(found, {"192.168.1.5": []})

    def test_probe_learner_explores_untried_methods_then_prefers_yield(self):
        brain = AgBeyin(self.root)
        candidates = ["nmap_tcp_ports", "avahi_browse", "ip_neigh"]
        first = brain._choose_probe(candidates)
        brain._record_probe_result(first, 0.0, 1000)
        second = brain._choose_probe(candidates)
        brain._record_probe_result(second, 0.0, 1001)
        third = brain._choose_probe(candidates)
        brain._record_probe_result(third, 0.0, 1002)
        self.assertEqual({first, second, third}, set(candidates))

        brain.data["probe_learning"]["nmap_tcp_ports"].update(
            attempts=3, reward_total=12.0
        )
        brain.data["probe_learning"]["avahi_browse"].update(
            attempts=3, reward_total=0.0
        )
        brain.data["probe_learning"]["ip_neigh"].update(
            attempts=3, reward_total=0.0
        )
        self.assertEqual(brain._choose_probe(candidates), "nmap_tcp_ports")

    def test_skill_confidence_uses_only_validated_probe_results(self):
        brain = AgBeyin(self.root)
        brain._record_probe_result("nmap_tcp_ports", 2.0, 1000, verified=True)
        brain._record_probe_result("nmap_tcp_ports", 0.0, 1001, verified=False)
        skill = brain.data["skills"]["nmap_tcp_ports"]
        self.assertEqual(skill["attempts"], 2)
        self.assertEqual(skill["successes"], 1)
        self.assertEqual(skill["failures"], 1)
        self.assertEqual(skill["confidence"], 0.5)

    def test_peer_prior_only_breaks_ties_after_local_skill_validation(self):
        brain = AgBeyin(self.root)
        candidates = ["nmap_tcp_ports", "ip_neigh"]
        for action in candidates:
            brain.data["probe_learning"][action] = {
                "attempts": 3, "reward_total": 0.0,
            }
            brain.data["skills"][action].update(
                attempts=3, successes=3, confidence=1.0,
            )

        class PeerPrior:
            @staticmethod
            def prior(skill, _local):
                if skill == "nmap_tcp_ports":
                    return {"mean_reward": 10.0, "weight": 1.0}
                return None

        brain._social = PeerPrior()
        self.assertEqual(brain._choose_probe(candidates), "nmap_tcp_ports")

    def test_consolidation_deduplicates_metadata_without_discarding_knowledge(self):
        brain = AgBeyin(self.root)
        brain.data["ports"]["tcp/22"]["reference_names"] = ["ssh", "ssh"]
        brain.data["tools"]["nmap_tcp_ports"]["learned_help"] = [
            "line", "line", "details",
        ]
        brain._consolidate(1000, force=True)
        self.assertEqual(
            brain.data["ports"]["tcp/22"]["reference_names"], ["ssh"]
        )
        self.assertEqual(
            brain.data["tools"]["nmap_tcp_ports"]["learned_help"],
            ["line", "details"],
        )
        self.assertEqual(brain.data["consolidation"]["last_at"], 1000)

    def test_ip_neighbor_reward_only_counts_neighbor_table_observations(self):
        before = {"hosts": set(), "ports": set(), "services": set()}
        baseline_hosts = {"192.168.1.5": []}
        self.assertEqual(
            AgBeyin._probe_reward(
                "ip_neigh", baseline_hosts, {}, before, set()
            ),
            0.0,
        )
        self.assertEqual(
            AgBeyin._probe_reward(
                "ip_neigh", baseline_hosts, {}, before, {"192.168.1.7"}
            ),
            1.0,
        )

    def test_local_reference_files_teach_known_port_names(self):
        services = self.root / "services"
        nmap_services = self.root / "nmap-services"
        services.write_text(
            "ssh 22/tcp # secure shell\nunknown 65000/tcp\n",
            encoding="utf-8",
        )
        nmap_services.write_text(
            "ipp 631/tcp 0.99 # printing\nhttp 80/tcp 0.99 # web\n",
            encoding="utf-8",
        )
        brain = AgBeyin(self.root)
        with patch("ag_beyin.REFERENCE_FILES",
                   (str(services), str(nmap_services))):
            brain._learn_local_references(1000)

        self.assertIn("ssh", brain.data["ports"]["tcp/22"]["reference_names"])
        self.assertIn("ipp", brain.data["ports"]["tcp/631"]["reference_names"])
        self.assertNotIn("tcp/65000", brain.data["ports"])
        self.assertEqual(len(brain.data["reference_learning"]), 2)

    def test_local_knowledge_learning_is_independent_of_network_scan(self):
        services = self.root / "services"
        services.write_text("ssh 22/tcp\n", encoding="utf-8")
        brain = AgBeyin(self.root)
        with patch("ag_beyin.REFERENCE_FILES", (str(services),)), patch(
            "ag_beyin.shutil.which", return_value=None
        ):
            result = brain.learn_local_knowledge(1000)
        self.assertTrue(result["changed"])
        self.assertTrue(result["consolidated"])
        self.assertTrue(result["references"])
        self.assertFalse(result["social"]["enabled"])
        self.assertEqual(brain.data["ports"]["tcp/22"]["reference_names"], ["ssh"])
        self.assertFalse(brain.data["scans"])

    def test_tool_help_is_learned_and_cached(self):
        calls = []

        def runner(argv, **_kwargs):
            calls.append(argv)
            return SimpleNamespace(
                returncode=0,
                stdout="Nmap help summary\nHost discovery options\nMore detail\n",
                stderr="",
            )

        brain = AgBeyin(self.root, runner=runner)
        warnings = []
        brain._learn_tool_help("nmap_tcp_ports", "/usr/bin/nmap", 1000, warnings)
        brain._learn_tool_help("nmap_tcp_ports", "/usr/bin/nmap", 1001, warnings)

        tool = brain.data["tools"]["nmap_tcp_ports"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(tool["learned_help"][:2], [
            "Nmap help summary", "Host discovery options",
        ])
        self.assertEqual(tool["learned_from"], "/usr/bin/nmap")
        self.assertEqual(warnings, [])

    def test_failed_scan_from_old_profile_is_due_once(self):
        brain = AgBeyin(self.root)
        brain.data["scans"] = [{"t": 1000.0, "ok": False}]
        self.assertEqual(brain.next_due_in(1000.0), 0.0)
        brain.data["scans"] = [{
            "t": 1000.0, "ok": False, "profile": SCAN_PROFILE_VERSION,
        }]
        self.assertEqual(brain.next_due_in(1000.0), 86400 / 5)

    def test_mdns_parser_keeps_only_scoped_resolved_services(self):
        output = "\n".join([
            "=;eth0;IPv4;Lab TV;_googlecast._tcp;local;tv.local;"
            "192.168.1.5;8009;",
            "=;eth0;IPv4;Phone;_companion-link._tcp;local;phone.local;"
            "192.168.1.9;62078;",
            "=;eth0;IPv4;Outside;_http._tcp;local;outside.local;"
            "8.8.8.8;80;",
        ])
        found = parse_avahi_output(output, ["192.168.1.0/24"])
        self.assertEqual(set(found), {"192.168.1.5", "192.168.1.9"})
        self.assertIn("_googlecast._tcp", found["192.168.1.5"]["services"])
        brain = AgBeyin(self.root)
        brain._learn({ip: [] for ip in found}, ["192.168.1.0/24"],
                     1234.0, complete=True, mdns_records=found)
        summary = brain.summary(1234.0)
        phone = next(d for d in summary["devices"] if d["ip"] == "192.168.1.9")
        self.assertIn("telefon_veya_tablet_olabilir", phone["hints"])
        self.assertEqual(phone["hostname"], "phone.local")

    def test_scans_and_learns_no_more_than_five_per_rolling_day(self):
        calls = []

        def runner(argv, **_kwargs):
            calls.append(argv)
            if "--help" in argv:
                output = "Nmap usage\nSafe scan options\n"
            else:
                output = DISCOVERY_XML if "-sn" in argv else PORTS_XML
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        brain = AgBeyin(self.root, runner=runner, clock=lambda: 1000.0)
        with patch(
            "ag_beyin.shutil.which",
            side_effect=lambda name, path=None: (
                "/usr/bin/nmap" if name == "nmap" else None
            ),
        ):
            for index in range(5):
                now = 1000.0 + index * 24 * 60 * 60 / 5
                result = brain.scan_if_due(now)
                self.assertTrue(result["ok"])
                self.assertEqual(result["hosts"], 1)

            self.assertIsNone(brain.scan_if_due(1000.0 + 4 * 24 * 60 * 60 / 5 + 1))
            sixth = brain.scan_if_due(1000.0 + 24 * 60 * 60 / 5 * 5)

        self.assertTrue(sixth["ok"])
        scan_calls = [argv for argv in calls if "--help" not in argv]
        # 5 scan_if_due çağrısı = 5 adım: adım1(-sn), adım2(-sT),
        # adım3(plan_only, nmap yok), adım1(-sn), adım2(-sT)
        # = 4 non-help nmap çağrısı
        self.assertEqual(len(scan_calls), 4)
        self.assertTrue(all("192.168.1.0/24" in argv or
                            "192.168.1.5" in argv for argv in scan_calls))
        self.assertTrue(all("-T3" in argv for argv in scan_calls))
        self.assertTrue(all(not any(arg.startswith("8.8.") for arg in argv)
                            for argv in scan_calls))

        summary = brain.summary(1000.0 + 24 * 60 * 60 / 5 * 5)
        self.assertEqual(summary["device_count"], 1)
        self.assertEqual(summary["devices"][0]["ip"], "192.168.1.5")
        self.assertEqual(
            {port["port"] for port in summary["devices"][0]["ports"]},
            {"tcp/22", "tcp/631"},
        )
        self.assertIn("yazici", summary["devices"][0]["hints"])
        self.assertEqual(summary["schedule"]["limit_per_24h"], 5)
        self.assertEqual(brain.data["tools"]["msf_active_modules"]["mode"],
                         "not_automated")


if __name__ == "__main__":
    unittest.main()
