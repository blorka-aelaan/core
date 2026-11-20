"""Local process and host telemetry for learning normal computer behavior.

Samples only aggregate process names and resource counters. PIDs, command-line
arguments, environment variables, and file contents are never retained.
"""

import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HISTORY_LIMIT = 120
PROCESS_DISPLAY_LIMIT = 20
EMA_ALPHA = 0.2


class Surec:
    def __init__(self, cfg, root=ROOT):
        s = cfg.get("surec", {})
        self.periyot = max(1, int(s.get("periyot", 50)))
        self.prag = float(s.get("prag", 0.6))
        self.azami_ad = max(1, int(s.get("azami_ad", 400)))
        self.dusman = float(s.get("dusman_factor", 1.15))
        self.root = Path(root)
        self.adet = {}
        self.kayip = {}
        self.ornek = 0
        self.eksik = []
        self.yeni = []
        self.profiller = {}
        self.sistem_profili = {}
        self.degisim_skoru = 0.0
        self.gecmis = []
        self.son_olcum = None
        self._onceki_sistem_cpu = None
        self._onceki_surec_cpu = {}
        self._onceki_zaman = None

    def tara(self):
        """Return visible user process names; kernel threads are excluded."""
        detay = self.tara_detay()
        return set(detay["processes"]) if detay is not None else set()

    def tara_detay(self):
        """Read process aggregates and host CPU/memory counters from procfs."""
        try:
            pids = os.listdir("/proc")
        except OSError:
            return None

        processes = {}
        for pid in pids:
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as stream:
                    if not stream.read(1):
                        continue
                with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as stream:
                    name = stream.read().strip()[:64]
                with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as stream:
                    stat = stream.read()
                with open(f"/proc/{pid}/statm", "r", encoding="ascii") as stream:
                    statm = stream.read().split()
                _prefix, separator, suffix = stat.rpartition(")")
                fields = suffix.split() if separator else []
                if not name or len(fields) <= 19 or len(statm) <= 1:
                    continue
                cpu_ticks = int(fields[11]) + int(fields[12])
                state = fields[0]
                rss_kb = int(statm[1]) * (os.sysconf("SC_PAGE_SIZE") // 1024)
            except (OSError, ValueError, IndexError):
                continue

            item = processes.setdefault(name, {
                "count": 0, "cpu_ticks": 0, "rss_kb": 0,
            })
            item["count"] += 1
            item["cpu_ticks"] += cpu_ticks
            item["rss_kb"] += rss_kb
            item[state] = item.get(state, 0) + 1

        cpu_total = cpu_idle = None
        try:
            with open("/proc/stat", "r", encoding="ascii") as stream:
                fields = stream.readline().split()
            if fields and fields[0] == "cpu" and len(fields) >= 5:
                values = [int(value) for value in fields[1:]]
                cpu_total = sum(values)
                cpu_idle = values[3] + (values[4] if len(values) > 4 else 0)
        except (OSError, ValueError):
            pass

        memory_total_kb = memory_available_kb = None
        try:
            memory = {}
            with open("/proc/meminfo", "r", encoding="ascii") as stream:
                for line in stream:
                    key, _, value = line.partition(":")
                    if key in ("MemTotal", "MemAvailable"):
                        memory[key] = int(value.strip().split()[0])
            memory_total_kb = memory.get("MemTotal")
            memory_available_kb = memory.get("MemAvailable")
        except (OSError, ValueError, IndexError):
            pass

        return {
            "processes": processes,
            "cpu_total": cpu_total,
            "cpu_idle": cpu_idle,
            "memory_total_kb": memory_total_kb,
            "memory_available_kb": memory_available_kb,
        }

    def ornekle(self, tik=None):
        """Collect one local telemetry sample and update process behavior profiles."""
        detay = self.tara_detay()
        if detay is None:
            return {"ok": False, "neden": "procfs_okunamadi"}
        return self.olcumle(detay, tik=tik)

    def isle(self, gorunen):
        """Update process-presence frequencies and report stable changes."""
        self.ornek += 1
        ilk = self.ornek == 1
        yeni = [] if ilk else [name for name in gorunen if name not in self.adet]
        for name in gorunen:
            self.adet[name] = self.adet.get(name, 0) + 1
        self.kayip = {
            name: self.kayip.get(name, 0) + 1
            for name in self.adet if name not in gorunen
        }
        eksik = []
        if self.ornek >= 4:
            esik = self.prag * self.ornek
            for name, count in self.adet.items():
                if count < esik or name in gorunen:
                    continue
                if self.kayip.get(name, 0) >= 2:
                    eksik.append(name)
        if len(self.adet) > self.azami_ad:
            excess = len(self.adet) - self.azami_ad
            for name, _count in sorted(self.adet.items(), key=lambda item: item[1])[:excess]:
                del self.adet[name]
                self.kayip.pop(name, None)
                self.profiller.pop(name, None)
        self.eksik = sorted(eksik)
        self.yeni = sorted(yeni)
        return {"eksik": self.eksik, "yeni": self.yeni, "toplam": len(self.adet)}

    def olcumle(self, detay, tik=None, simdi=None, saat=None):
        """Turn a procfs-like snapshot into a bounded dataset and online baseline."""
        processes = detay.get("processes")
        if not isinstance(processes, dict):
            raise ValueError("process snapshot must contain a processes mapping")

        simdi = time.time() if simdi is None else float(simdi)
        saat = time.monotonic() if saat is None else float(saat)
        presence = self.isle(set(processes))
        elapsed = (saat - self._onceki_zaman
                   if self._onceki_zaman is not None else None)
        clk_tck = max(1, int(os.sysconf("SC_CLK_TCK")))
        system_cpu = None
        cpu_total, cpu_idle = detay.get("cpu_total"), detay.get("cpu_idle")
        if (self._onceki_sistem_cpu is not None
                and isinstance(cpu_total, int) and isinstance(cpu_idle, int)):
            previous_total, previous_idle = self._onceki_sistem_cpu
            delta_total = cpu_total - previous_total
            delta_idle = cpu_idle - previous_idle
            if delta_total > 0 and 0 <= delta_idle <= delta_total:
                system_cpu = round(100.0 * (delta_total - delta_idle) / delta_total, 2)

        current_cpu = {}
        process_rows = []
        for name, raw in processes.items():
            if not isinstance(name, str) or not name or not isinstance(raw, dict):
                continue
            count = max(0, int(raw.get("count", 0)))
            cpu_ticks = max(0, int(raw.get("cpu_ticks", 0)))
            rss_kb = max(0, int(raw.get("rss_kb", 0)))
            current_cpu[name] = cpu_ticks
            cpu_percent = None
            previous = self._onceki_surec_cpu.get(name)
            if elapsed and elapsed > 0 and previous is not None and cpu_ticks >= previous:
                cpu_percent = round(
                    100.0 * (cpu_ticks - previous) / (clk_tck * elapsed), 2
                )
            process_rows.append({
                "ad": name[:64],
                "adet": count,
                "cpu_yuzde": cpu_percent,
                "bellek_kb": rss_kb,
            })

        present = set(current_cpu)
        for name in set(self.profiller) | present:
            profile = self.profiller.setdefault(name, {
                "ornek": 0, "gorulme": 0.0, "adet_ort": 0.0,
                "cpu_yuzde_ort": 0.0, "bellek_kb_ort": 0.0,
            })
            item = processes.get(name, {})
            count = max(0, int(item.get("count", 0)))
            rss_kb = max(0, int(item.get("rss_kb", 0)))
            profile["ornek"] += 1
            profile["gorulme"] += 1.0 if name in present else 0.0
            profile["adet_ort"] = self._ema(profile["adet_ort"], count)
            profile["bellek_kb_ort"] = self._ema(profile["bellek_kb_ort"], rss_kb)
            cpu_rate = next(
                (row["cpu_yuzde"] for row in process_rows
                 if row["ad"] == name), None
            )
            if cpu_rate is not None:
                profile["cpu_yuzde_ort"] = self._ema(
                    profile["cpu_yuzde_ort"], cpu_rate
                )
            profile["gorulme_orani"] = round(
                profile["gorulme"] / profile["ornek"], 3
            )
            profile["adet_ort"] = round(profile["adet_ort"], 2)
            profile["cpu_yuzde_ort"] = round(profile["cpu_yuzde_ort"], 2)
            profile["bellek_kb_ort"] = round(profile["bellek_kb_ort"], 1)

        process_rows.sort(
            key=lambda row: (
                row["cpu_yuzde"] is not None,
                row["cpu_yuzde"] or 0,
                row["bellek_kb"],
            ),
            reverse=True,
        )
        total_memory = detay.get("memory_total_kb")
        available_memory = detay.get("memory_available_kb")
        memory_percent = None
        if (isinstance(total_memory, int) and total_memory > 0
                and isinstance(available_memory, int)):
            memory_percent = round(
                100.0 * (total_memory - available_memory) / total_memory, 2
            )
        current_process_count = sum(
            max(0, int(process.get("count", 0)))
            for process in processes.values()
            if isinstance(process, dict)
        )
        changes = []
        for key, value, floor in (
            ("cpu_yuzde", system_cpu, 10.0),
            ("bellek_yuzde", memory_percent, 5.0),
            ("surec_sayisi", float(current_process_count), 2.0),
        ):
            if value is not None:
                changes.append(self._learn_system_metric(key, float(value), floor))
        self.degisim_skoru = round(max(changes, default=0.0), 3)
        snapshot = {
            "t": simdi,
            "tik": tik,
            "ornek": self.ornek,
            "surec_sayisi": current_process_count,
            "surec_turu": len(processes),
            "cpu_yuzde": system_cpu,
            "bellek_yuzde": memory_percent,
            "degisim_skoru": self.degisim_skoru,
            "bellek_kullanilan_kb": (
                max(0, total_memory - available_memory)
                if isinstance(total_memory, int)
                and isinstance(available_memory, int) else None
            ),
            "calisan": sum(int(p.get("R", 0)) for p in processes.values()
                           if isinstance(p, dict)),
            "bekleyen": sum(int(p.get("S", 0)) for p in processes.values()
                            if isinstance(p, dict)),
            "yeni": presence["yeni"],
            "eksik": presence["eksik"],
            "surecler": process_rows[:PROCESS_DISPLAY_LIMIT],
        }
        self.son_olcum = snapshot
        self.gecmis.append(snapshot)
        self.gecmis = self.gecmis[-HISTORY_LIMIT:]
        self._onceki_sistem_cpu = (
            (cpu_total, cpu_idle)
            if isinstance(cpu_total, int) and isinstance(cpu_idle, int)
            else None
        )
        self._onceki_surec_cpu = current_cpu
        self._onceki_zaman = saat
        return {"ok": True, **snapshot}

    @staticmethod
    def _ema(previous, value):
        return (1.0 - EMA_ALPHA) * float(previous) + EMA_ALPHA * float(value)

    def _learn_system_metric(self, name, value, floor):
        profile = self.sistem_profili.get(name)
        if profile is None:
            self.sistem_profili[name] = {
                "ornek": 1, "ortalama": value, "sapma_ort": 0.0,
            }
            return 0.0
        previous_mean = float(profile["ortalama"])
        deviation = abs(value - previous_mean)
        score = min(
            1.0,
            deviation / max(floor, 3.0 * float(profile["sapma_ort"])),
        )
        profile["ortalama"] = self._ema(previous_mean, value)
        profile["sapma_ort"] = self._ema(profile["sapma_ort"], deviation)
        profile["ornek"] += 1
        return score

    def save(self):
        path = self.root / "zeka" / "surec.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        data = {
            "ornek": self.ornek,
            "adet": dict(sorted(self.adet.items())),
            "profiller": self.profiller,
            "sistem_profili": self.sistem_profili,
            "gecmis": self.gecmis[-HISTORY_LIMIT:],
            "son_olcum": self.son_olcum,
        }
        temporary.write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(str(temporary), str(path))

    def load(self):
        path = self.root / "zeka" / "surec.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.ornek = int(data.get("ornek", 0))
        self.adet = {
            str(name): int(count)
            for name, count in data.get("adet", {}).items()
        }
        self.profiller = data.get("profiller", {})
        self.sistem_profili = data.get("sistem_profili", {})
        self.gecmis = data.get("gecmis", [])[-HISTORY_LIMIT:]
        self.son_olcum = data.get("son_olcum")
        self.degisim_skoru = float(
            (self.son_olcum or {}).get("degisim_skoru", 0.0)
        )
        return True
