"""
NAIL Institute - System & GPU Monitor
=======================================
Background thread that polls system resources at configurable intervals.
Captures GPU (nvidia-smi), CPU, RAM, disk, and Ollama process stats.
Writes structured samples to JSONL for post-hoc analysis.
"""

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

from .config import LOGS_DIR


@dataclass
class GPUSnapshot:
    """Single GPU reading."""
    index: int = 0
    name: str = ""
    temperature_c: float = 0.0
    gpu_util_pct: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    memory_util_pct: float = 0.0
    power_draw_w: float = 0.0
    power_limit_w: float = 0.0


@dataclass
class SystemSnapshot:
    """Full system resource reading at one point in time."""
    timestamp: str = ""
    elapsed_s: float = 0.0
    # CPU
    cpu_util_pct: float = 0.0
    cpu_count: int = 0
    cpu_freq_mhz: float = 0.0
    # RAM
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_available_gb: float = 0.0
    ram_util_pct: float = 0.0
    # Swap
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    # Disk
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_free_gb: float = 0.0
    # GPU(s)
    gpus: list = field(default_factory=list)
    # Ollama process
    ollama_rss_mb: float = 0.0
    ollama_cpu_pct: float = 0.0
    ollama_num_threads: int = 0


def _query_nvidia_smi() -> list[GPUSnapshot]:
    """Query nvidia-smi for GPU stats. Returns list of GPUSnapshot."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total,utilization.memory,"
                "power.draw,power.limit",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []

        gpus = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 9:
                try:
                    gpus.append(GPUSnapshot(
                        index=int(parts[0]),
                        name=parts[1],
                        temperature_c=_safe_float(parts[2]),
                        gpu_util_pct=_safe_float(parts[3]),
                        memory_used_mb=_safe_float(parts[4]),
                        memory_total_mb=_safe_float(parts[5]),
                        memory_util_pct=_safe_float(parts[6]),
                        power_draw_w=_safe_float(parts[7]),
                        power_limit_w=_safe_float(parts[8]),
                    ))
                except (ValueError, IndexError):
                    pass
        return gpus
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _safe_float(val: str) -> float:
    """Parse a float from nvidia-smi output, handling [N/A] etc."""
    val = val.strip()
    if not val or val.startswith("[") or val.lower() in ("n/a", "not supported", "err"):
        return 0.0
    try:
        return float(re.sub(r'[^0-9.\-]', '', val))
    except ValueError:
        return 0.0


def _get_ollama_process_stats() -> dict:
    """Find the ollama serve process and get its resource usage."""
    stats = {"rss_mb": 0.0, "cpu_pct": 0.0, "num_threads": 0}
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if "ollama" in cmdline and "serve" in cmdline:
                    mem = proc.memory_info()
                    stats["rss_mb"] = round(mem.rss / (1024 ** 2), 1)
                    stats["cpu_pct"] = proc.cpu_percent(interval=0.1)
                    stats["num_threads"] = proc.num_threads()
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return stats


def take_snapshot(start_time: float = 0.0) -> SystemSnapshot:
    """Take a single full system snapshot right now."""
    now = time.time()

    # CPU
    cpu_pct = psutil.cpu_percent(interval=0.1)
    cpu_freq = psutil.cpu_freq()
    cpu_freq_mhz = cpu_freq.current if cpu_freq else 0.0

    # RAM
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disk
    disk = psutil.disk_usage("/")

    # GPU
    gpus = _query_nvidia_smi()

    # Ollama process
    ollama = _get_ollama_process_stats()

    return SystemSnapshot(
        timestamp=datetime.now().isoformat(),
        elapsed_s=round(now - start_time, 2) if start_time else 0.0,
        cpu_util_pct=cpu_pct,
        cpu_count=psutil.cpu_count(),
        cpu_freq_mhz=round(cpu_freq_mhz, 0),
        ram_total_gb=round(mem.total / (1024 ** 3), 2),
        ram_used_gb=round(mem.used / (1024 ** 3), 2),
        ram_available_gb=round(mem.available / (1024 ** 3), 2),
        ram_util_pct=mem.percent,
        swap_total_gb=round(swap.total / (1024 ** 3), 2),
        swap_used_gb=round(swap.used / (1024 ** 3), 2),
        disk_total_gb=round(disk.total / (1024 ** 3), 2),
        disk_used_gb=round(disk.used / (1024 ** 3), 2),
        disk_free_gb=round(disk.free / (1024 ** 3), 2),
        gpus=[asdict(g) for g in gpus],
        ollama_rss_mb=ollama["rss_mb"],
        ollama_cpu_pct=ollama["cpu_pct"],
        ollama_num_threads=ollama["num_threads"],
    )


class SystemMonitor:
    """
    Background thread that periodically takes system snapshots
    and writes them to a JSONL file.
    
    Usage:
        monitor = SystemMonitor("exp1_memory_pollution", interval_s=5)
        monitor.start()
        # ... run experiment ...
        monitor.stop()
        summary = monitor.get_summary()
    """

    def __init__(
        self,
        experiment_name: str,
        run_id: str = "",
        interval_s: float = 5.0,
    ):
        self.experiment_name = experiment_name
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.interval_s = interval_s

        self.log_dir = LOGS_DIR / experiment_name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"system_{self.run_id}.jsonl"

        self._start_time = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._snapshots: list[SystemSnapshot] = []
        self._lock = threading.Lock()

    def start(self):
        """Start background monitoring."""
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background monitoring and wait for thread to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _poll_loop(self):
        """Main polling loop running in background thread."""
        while not self._stop_event.is_set():
            try:
                snap = take_snapshot(self._start_time)
                with self._lock:
                    self._snapshots.append(snap)

                # Write to JSONL
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(asdict(snap)) + "\n")

            except Exception as e:
                # Don't let monitoring errors kill the experiment
                pass

            self._stop_event.wait(timeout=self.interval_s)

    def take_snapshot_now(self) -> SystemSnapshot:
        """Take an on-demand snapshot (synchronous)."""
        snap = take_snapshot(self._start_time)
        with self._lock:
            self._snapshots.append(snap)
        return snap

    def get_summary(self) -> dict:
        """
        Compute summary statistics across all collected snapshots.
        Call this after stop().
        """
        with self._lock:
            snaps = list(self._snapshots)

        if not snaps:
            return {"error": "No snapshots collected"}

        n = len(snaps)

        # CPU
        cpu_vals = [s.cpu_util_pct for s in snaps]
        # RAM
        ram_vals = [s.ram_util_pct for s in snaps]
        ram_used = [s.ram_used_gb for s in snaps]

        summary = {
            "num_snapshots": n,
            "duration_s": round(snaps[-1].elapsed_s, 1) if snaps else 0,
            "monitor_interval_s": self.interval_s,
            # CPU
            "cpu_avg_pct": round(sum(cpu_vals) / n, 1),
            "cpu_max_pct": round(max(cpu_vals), 1),
            "cpu_min_pct": round(min(cpu_vals), 1),
            # RAM
            "ram_avg_pct": round(sum(ram_vals) / n, 1),
            "ram_max_gb": round(max(ram_used), 2),
            "ram_total_gb": snaps[0].ram_total_gb,
            # Ollama
            "ollama_max_rss_mb": round(max(s.ollama_rss_mb for s in snaps), 1),
            "ollama_avg_rss_mb": round(sum(s.ollama_rss_mb for s in snaps) / n, 1),
            # Disk
            "disk_total_gb": snaps[0].disk_total_gb,
            "disk_used_start_gb": snaps[0].disk_used_gb,
            "disk_used_end_gb": snaps[-1].disk_used_gb,
        }

        # GPU summary (per GPU)
        if snaps[0].gpus:
            num_gpus = len(snaps[0].gpus)
            for g_idx in range(num_gpus):
                gpu_utils = [s.gpus[g_idx]["gpu_util_pct"] for s in snaps if len(s.gpus) > g_idx]
                vram_used = [s.gpus[g_idx]["memory_used_mb"] for s in snaps if len(s.gpus) > g_idx]
                temps = [s.gpus[g_idx]["temperature_c"] for s in snaps if len(s.gpus) > g_idx]
                powers = [s.gpus[g_idx]["power_draw_w"] for s in snaps if len(s.gpus) > g_idx]

                prefix = f"gpu{g_idx}"
                summary[f"{prefix}_name"] = snaps[0].gpus[g_idx]["name"]
                summary[f"{prefix}_vram_total_mb"] = snaps[0].gpus[g_idx]["memory_total_mb"]
                # Utilization
                summary[f"{prefix}_util_avg_pct"] = round(sum(gpu_utils) / len(gpu_utils), 1) if gpu_utils else 0
                summary[f"{prefix}_util_max_pct"] = round(max(gpu_utils), 1) if gpu_utils else 0
                # VRAM
                summary[f"{prefix}_vram_avg_mb"] = round(sum(vram_used) / len(vram_used), 1) if vram_used else 0
                summary[f"{prefix}_vram_max_mb"] = round(max(vram_used), 1) if vram_used else 0
                # Temperature
                summary[f"{prefix}_temp_avg_c"] = round(sum(temps) / len(temps), 1) if temps else 0
                summary[f"{prefix}_temp_max_c"] = round(max(temps), 1) if temps else 0
                # Power
                summary[f"{prefix}_power_avg_w"] = round(sum(powers) / len(powers), 1) if powers else 0
                summary[f"{prefix}_power_max_w"] = round(max(powers), 1) if powers else 0

        return summary

    def get_log_path(self) -> Path:
        return self.log_file
