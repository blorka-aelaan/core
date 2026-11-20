"""Local, opt-in exchange of verified skill summaries between CORE instances."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


SKILLS = ("nmap_tcp_ports", "avahi_browse", "ip_neigh")
INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
MAX_REPORT_BYTES = 4096
MAX_REPORTS = 64
REPORT_TTL_SECONDS = 30 * 24 * 60 * 60
MIN_PEER_TRIALS = 5
MIN_PEER_SUCCESS_RATE = 0.8
MIN_LOCAL_TRIALS = 3
MIN_LOCAL_SUCCESS_RATE = 2 / 3


class SocialLearning:
    """Exchange small, allowlisted skill metrics; never exchange executable data."""

    def __init__(
        self, root: Path | str, clock=time.time
    ) -> None:
        self.root = Path(root)
        self.config_path = self.root / "zeka" / "social.json"
        self.memory_path = self.root / "zeka" / "social_memory.json"
        self.clock = clock
        self.config = self._load_config()
        self.memory = self._load_memory()

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {"enabled": False, "peers": []}
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("social.json okunamadi: %s" % error) from error
        if not isinstance(config, dict):
            raise ValueError("social.json bir JSON nesnesi olmali")
        if config.get("enabled") is not True:
            return {"enabled": False, "peers": []}
        instance_id = config.get("instance_id")
        exchange_dir = config.get("exchange_dir")
        peers = config.get("peers")
        if not isinstance(instance_id, str) or not INSTANCE_ID.fullmatch(instance_id):
            raise ValueError("social.json instance_id gecersiz")
        if not isinstance(exchange_dir, str) or not Path(exchange_dir).is_absolute():
            raise ValueError("social.json exchange_dir mutlak yol olmali")
        if not isinstance(peers, list) or len(peers) > 8:
            raise ValueError("social.json peers en fazla 8 kimlik icermeli")
        if any(not isinstance(peer, str) or not INSTANCE_ID.fullmatch(peer)
               or peer == instance_id for peer in peers):
            raise ValueError("social.json peers kimlikleri gecersiz")
        return {
            "enabled": True,
            "instance_id": instance_id,
            "exchange_dir": Path(exchange_dir),
            "peers": sorted(set(peers)),
        }

    def _load_memory(self) -> Dict[str, Any]:
        if not self.memory_path.exists():
            return {"schema": 1, "reports": {}}
        try:
            memory = json.loads(self.memory_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError("social_memory.json okunamadi: %s" % error) from error
        if not isinstance(memory, dict) or memory.get("schema") != 1:
            raise ValueError("social_memory.json semasi taninmiyor")
        memory.setdefault("reports", {})
        return memory

    @staticmethod
    def _valid_stats(stats: Dict[str, Any]) -> Optional[Dict[str, float]]:
        try:
            attempts = int(stats.get("attempts", 0))
            successes = int(stats.get("successes", 0))
            if "reward_total" in stats:
                reward_total = float(stats["reward_total"])
            else:
                reward_total = (
                    float(stats.get("mean_reward", 0.0)) * attempts
                )
        except (TypeError, ValueError):
            return None
        if (
            attempts < MIN_PEER_TRIALS
            or successes < 0
            or successes > attempts
            or not math.isfinite(reward_total)
        ):
            return None
        success_rate = successes / attempts
        if success_rate < MIN_PEER_SUCCESS_RATE:
            return None
        mean_reward = max(0.0, min(10.0, reward_total / attempts))
        return {
            "attempts": float(attempts),
            "success_rate": success_rate,
            "mean_reward": mean_reward,
        }

    def exchange(self, skills: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.get("enabled"):
            return self.snapshot()
        exchange_dir: Path = self.config["exchange_dir"]
        sender = self.config["instance_id"]
        sent = 0
        now = self.clock()
        for peer in self.config["peers"]:
            inbox = exchange_dir / peer / "inbox"
            for skill in SKILLS:
                stats = skills.get(skill, {})
                if not isinstance(stats, dict):
                    continue
                validated = self._valid_stats(stats)
                if not validated:
                    continue
                envelope = {
                    "schema": 1,
                    "kind": "validated_skill_summary",
                    "sender": sender,
                    "recipient": peer,
                    "skill": skill,
                    **validated,
                    "successes": int(stats["successes"]),
                    "sent_at": now,
                }
                payload = json.dumps(
                    envelope, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                if len(payload) > MAX_REPORT_BYTES:
                    raise ValueError("sosyal ozet boyut sinirini asti")
                inbox.mkdir(parents=True, exist_ok=True)
                target = inbox / ("%s-%s.json" % (sender, skill))
                if target.exists():
                    try:
                        previous = json.loads(target.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        previous = {}
                    if all(previous.get(key) == envelope.get(key) for key in (
                        "schema", "kind", "sender", "recipient", "skill",
                        "attempts", "successes", "success_rate", "mean_reward",
                    )):
                        continue
                tmp = target.with_name("%s.%d.tmp" % (target.name, os.getpid()))
                tmp.write_bytes(payload)
                os.replace(tmp, target)
                sent += 1

        received, changed = self._receive()
        if changed:
            self._save()
        return self.snapshot(sent=sent, received=received)

    def _receive(self) -> tuple[int, bool]:
        receiver = self.config["instance_id"]
        inbox = self.config["exchange_dir"] / receiver / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        reports = self.memory.setdefault("reports", {})
        received = 0
        changed = False
        now = self.clock()
        files = sorted(inbox.glob("*.json"), key=lambda path: path.name)[:MAX_REPORTS]
        for path in files:
            try:
                stat = path.lstat()
                if path.is_symlink():
                    record = {
                        "status": "rejected",
                        "reason": "symlink",
                        "digest": "symlink:%d" % stat.st_mtime_ns,
                    }
                    if reports.get(path.name) != record:
                        reports[path.name] = record
                        changed = True
                    received += 1
                    continue
                with path.open("rb") as source:
                    raw = source.read(MAX_REPORT_BYTES + 1)
            except (OSError, ValueError) as error:
                record = {
                    "status": "rejected",
                    "reason": "%s: %s" % (type(error).__name__, str(error)[:120]),
                }
                if reports.get(path.name) != record:
                    reports[path.name] = record
                    changed = True
                continue
            digest = hashlib.sha256(raw).hexdigest()
            existing = reports.get(path.name, {})
            if existing.get("digest") == digest:
                continue
            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                record = {
                    "status": "rejected",
                    "reason": "%s: %s" % (type(error).__name__, str(error)[:120]),
                    "digest": digest,
                }
                reports[path.name] = record
                changed = True
                received += 1
                continue
            if len(raw) > MAX_REPORT_BYTES:
                digest = "oversize:%d:%d" % (len(raw), stat.st_mtime_ns)
                record = {
                    "status": "rejected",
                    "reason": "oversize",
                    "digest": digest,
                }
                if reports.get(path.name) != record:
                    reports[path.name] = record
                    changed = True
                received += 1
                continue
            if not isinstance(envelope, dict):
                reports[path.name] = {
                    "status": "rejected", "reason": "shape", "digest": digest,
                }
                changed = True
                received += 1
                continue
            sender = envelope.get("sender")
            timestamp = envelope.get("sent_at")
            skill = envelope.get("skill")
            if (
                envelope.get("schema") != 1
                or envelope.get("kind") != "validated_skill_summary"
                or envelope.get("recipient") != receiver
                or sender not in self.config["peers"]
                or skill not in SKILLS
                or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)
                or timestamp > now + 600
                or now - timestamp > REPORT_TTL_SECONDS
            ):
                reports[path.name] = {
                    "status": "rejected", "reason": "invalid", "digest": digest,
                }
                changed = True
                received += 1
                continue
            validated = self._valid_stats(envelope)
            if not validated:
                reports[path.name] = {
                    "status": "rejected", "reason": "unverified",
                    "digest": digest,
                }
                changed = True
                received += 1
                continue
            reports[path.name] = {
                "status": "peer_evidence",
                "sender": sender,
                "skill": skill,
                **validated,
                "sent_at": float(timestamp),
                "digest": digest,
            }
            changed = True
            received += 1
        return received, changed

    def _save(self) -> None:
        self.memory_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.memory_path.with_name(
            "%s.%d.tmp" % (self.memory_path.name, os.getpid())
        )
        tmp.write_text(
            json.dumps(self.memory, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, self.memory_path)

    def prior(
        self, skill: str, local_stats: Dict[str, Any]
    ) -> Optional[Dict[str, float]]:
        """Return a weak peer prior only after the receiving instance validates it."""
        try:
            attempts = int(local_stats.get("attempts", 0))
            successes = int(local_stats.get("successes", 0))
        except (TypeError, ValueError):
            return None
        if (
            attempts < MIN_LOCAL_TRIALS
            or successes / attempts < MIN_LOCAL_SUCCESS_RATE
        ):
            return None
        peer_reports = [
            report for report in self.memory.get("reports", {}).values()
            if report.get("status") == "peer_evidence"
            and report.get("skill") == skill
            and self.clock() - float(report.get("sent_at", 0))
            <= REPORT_TTL_SECONDS
        ]
        if not peer_reports:
            return None
        weights = [min(5.0, float(report["attempts"])) for report in peer_reports]
        total_weight = sum(weights)
        return {
            "mean_reward": sum(
                float(report["mean_reward"]) * weight
                for report, weight in zip(peer_reports, weights)
            ) / total_weight,
            "weight": min(1.0, total_weight / 5.0),
        }

    def snapshot(self, sent: int = 0, received: int = 0) -> Dict[str, Any]:
        reports = self.memory.get("reports", {})
        return {
            "enabled": bool(self.config.get("enabled")),
            "instance_id": self.config.get("instance_id"),
            "peers": list(self.config.get("peers", [])),
            "reports_received": sum(
                1 for report in reports.values()
                if report.get("status") == "peer_evidence"
            ),
            "reports_sent": sent,
            "reports_new": received,
        }
