"""
RMAP Phase 3 — Somatic Awareness
===================================
Real-time infrastructure telemetry injected into agent context.

Agents that run inside computers but don't know they're inside computers
will misattribute infrastructure failures (network timeouts, GPU throttling,
OOM kills) as code bugs or data problems. Somatic Awareness fixes this.

The SomaticHeader is a compact telemetry string injected into every agent's
system prompt or context window. When a tool times out, the agent can see
`NET_LATENCY: 400ms` and reason "the network is congested" instead of
hallucinating code rewrites.

Sources:
  - CPU: load, per-core utilization
  - RAM: total, used, percent
  - Disk: total, used, I/O rates
  - GPU: temperature, power, utilization (nvidia-smi)
  - Network: bytes sent/recv, current rates
  - Thermal: zone temperatures

Based on: NAIL Experiment 18 — Somatic Awareness
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ── Cache for rate calculations ──────────────────────────────────
_prev_net = None
_prev_net_time: Optional[float] = None
_prev_disk = None
_prev_disk_time: Optional[float] = None


@dataclass
class SomaticSnapshot:
    """Complete infrastructure telemetry snapshot at one point in time."""
    timestamp: float = 0.0
    # CPU
    cpu_pct: float = 0.0
    cpu_count: int = 0
    load_1m: float = 0.0
    load_5m: float = 0.0
    load_15m: float = 0.0
    # RAM
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_pct: float = 0.0
    # Disk
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_read_mb_s: float = 0.0
    disk_write_mb_s: float = 0.0
    # GPU
    gpu_temp_c: Optional[float] = None
    gpu_power_w: Optional[float] = None
    gpu_util_pct: Optional[float] = None
    gpu_vram_used_gb: Optional[float] = None
    gpu_vram_total_gb: Optional[float] = None
    # Network
    net_send_mb_s: float = 0.0
    net_recv_mb_s: float = 0.0

    def to_header(self, compact: bool = True) -> str:
        """
        Format as a somatic header string for injection into agent context.

        Args:
            compact: If True, single-line format. If False, multi-line.
        """
        parts = [
            f"CPU:{self.cpu_pct:.0f}%",
            f"RAM:{self.ram_pct:.0f}%({self.ram_used_gb:.1f}/{self.ram_total_gb:.1f}GB)",
            f"DISK:{self.disk_used_gb:.0f}GB",
        ]

        if self.gpu_util_pct is not None:
            gpu_str = f"GPU:{self.gpu_util_pct:.0f}%"
            if self.gpu_vram_used_gb is not None and self.gpu_vram_total_gb is not None:
                gpu_str += f"(VRAM:{self.gpu_vram_used_gb:.1f}/{self.gpu_vram_total_gb:.1f}GB)"
            if self.gpu_temp_c is not None:
                gpu_str += f"@{self.gpu_temp_c:.0f}°C"
            parts.append(gpu_str)

        if self.net_send_mb_s > 0 or self.net_recv_mb_s > 0:
            parts.append(
                f"NET:↑{self.net_send_mb_s:.1f}MB/s↓{self.net_recv_mb_s:.1f}MB/s"
            )

        parts.append(f"LOAD:{self.load_1m:.1f}/{self.load_5m:.1f}/{self.load_15m:.1f}")

        if compact:
            return "[SOMATIC " + " | ".join(parts) + "]"
        else:
            return "\n".join(f"  {p}" for p in parts)

    def to_dict(self) -> dict:
        """Serialize to dict for logging."""
        return {
            "timestamp": self.timestamp,
            "cpu_pct": self.cpu_pct,
            "cpu_count": self.cpu_count,
            "load_1m": self.load_1m,
            "ram_total_gb": round(self.ram_total_gb, 2),
            "ram_used_gb": round(self.ram_used_gb, 2),
            "ram_pct": self.ram_pct,
            "disk_total_gb": round(self.disk_total_gb, 1),
            "disk_used_gb": round(self.disk_used_gb, 1),
            "gpu_temp_c": self.gpu_temp_c,
            "gpu_power_w": self.gpu_power_w,
            "gpu_util_pct": self.gpu_util_pct,
            "gpu_vram_used_gb": self.gpu_vram_used_gb,
            "gpu_vram_total_gb": self.gpu_vram_total_gb,
            "net_send_mb_s": round(self.net_send_mb_s, 2),
            "net_recv_mb_s": round(self.net_recv_mb_s, 2),
        }


def _query_gpu() -> dict:
    """Query nvidia-smi for GPU metrics."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,power.draw,utilization.gpu,"
                "memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "temp_c": float(parts[0]) if parts[0] not in ("[N/A]", "") else None,
                "power_w": float(parts[1]) if parts[1] not in ("[N/A]", "") else None,
                "util_pct": float(parts[2]) if parts[2] not in ("[N/A]", "") else None,
                "vram_used_mb": float(parts[3]) if parts[3] not in ("[N/A]", "") else None,
                "vram_total_mb": float(parts[4]) if parts[4] not in ("[N/A]", "") else None,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return {}


def collect_telemetry() -> SomaticSnapshot:
    """
    Collect a complete infrastructure telemetry snapshot.

    Returns a SomaticSnapshot that can be formatted as a header string
    for injection into agent system prompts.

    Works with or without psutil installed, with or without nvidia-smi.
    """
    global _prev_net, _prev_net_time, _prev_disk, _prev_disk_time

    snap = SomaticSnapshot(timestamp=time.time())

    if not _HAS_PSUTIL:
        return snap

    now = time.time()

    # CPU
    snap.cpu_pct = psutil.cpu_percent(interval=0.1)
    snap.cpu_count = psutil.cpu_count(logical=True) or 0
    load = psutil.getloadavg()
    snap.load_1m, snap.load_5m, snap.load_15m = load

    # RAM
    vm = psutil.virtual_memory()
    snap.ram_total_gb = vm.total / (1024 ** 3)
    snap.ram_used_gb = vm.used / (1024 ** 3)
    snap.ram_pct = vm.percent

    # Disk
    disk = psutil.disk_usage("/")
    snap.disk_total_gb = disk.total / (1024 ** 3)
    snap.disk_used_gb = disk.used / (1024 ** 3)

    try:
        disk_io = psutil.disk_io_counters()
        if disk_io and _prev_disk is not None and _prev_disk_time is not None:
            dt = now - _prev_disk_time
            if dt > 0:
                snap.disk_read_mb_s = (
                    (disk_io.read_bytes - _prev_disk.read_bytes) / dt / (1024 ** 2)
                )
                snap.disk_write_mb_s = (
                    (disk_io.write_bytes - _prev_disk.write_bytes) / dt / (1024 ** 2)
                )
        _prev_disk = disk_io
        _prev_disk_time = now
    except Exception:
        pass

    # Network
    try:
        net = psutil.net_io_counters()
        if net and _prev_net is not None and _prev_net_time is not None:
            dt = now - _prev_net_time
            if dt > 0:
                snap.net_send_mb_s = (
                    (net.bytes_sent - _prev_net.bytes_sent) / dt / (1024 ** 2)
                )
                snap.net_recv_mb_s = (
                    (net.bytes_recv - _prev_net.bytes_recv) / dt / (1024 ** 2)
                )
        _prev_net = net
        _prev_net_time = now
    except Exception:
        pass

    # GPU
    gpu = _query_gpu()
    if gpu:
        snap.gpu_temp_c = gpu.get("temp_c")
        snap.gpu_power_w = gpu.get("power_w")
        snap.gpu_util_pct = gpu.get("util_pct")
        vram_used = gpu.get("vram_used_mb")
        vram_total = gpu.get("vram_total_mb")
        if vram_used is not None:
            snap.gpu_vram_used_gb = vram_used / 1024
        if vram_total is not None:
            snap.gpu_vram_total_gb = vram_total / 1024

    return snap


class SomaticHeader:
    """
    Convenience class for injecting somatic awareness into agent prompts.

    Usage:
        >>> header = SomaticHeader.collect()
        >>> prompt = f"{header}\\n\\nYou are a coding agent..."

    Or with continuous monitoring:
        >>> somatic = SomaticHeader(poll_interval=5.0)
        >>> header_str = somatic.get_header()
    """

    def __init__(self, poll_interval: float = 5.0, compact: bool = True):
        self.poll_interval = poll_interval
        self.compact = compact
        self._last_snapshot: Optional[SomaticSnapshot] = None
        self._last_poll: float = 0.0

    def get_header(self) -> str:
        """Get the current somatic header string, polling if stale."""
        now = time.time()
        if self._last_snapshot is None or (now - self._last_poll) >= self.poll_interval:
            self._last_snapshot = collect_telemetry()
            self._last_poll = now
        return self._last_snapshot.to_header(compact=self.compact)

    def get_snapshot(self) -> SomaticSnapshot:
        """Get the latest snapshot, polling if stale."""
        self.get_header()  # Ensures refresh
        return self._last_snapshot  # type: ignore

    @staticmethod
    def collect(compact: bool = True) -> str:
        """One-shot: collect telemetry and return header string."""
        snap = collect_telemetry()
        return snap.to_header(compact=compact)

    def __str__(self) -> str:
        return self.get_header()

    def __repr__(self) -> str:
        return f"SomaticHeader(poll_interval={self.poll_interval})"
