"""
NAIL Institute — Experiment 21: Somatic Starvation Proof
Telemetry and Starvation Simulator Module
"""

from __future__ import annotations

import os
import time
import subprocess
from typing import Any, Optional

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def query_gpu() -> dict[str, Any]:
    """Query nvidia-smi for active GPU stats."""
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
    except Exception:
        pass
    return {}


def collect_real_telemetry() -> dict[str, Any]:
    """Collect real-time hardware telemetry."""
    snap = {
        "timestamp": time.time(),
        "cpu_pct": 0.0,
        "cpu_count": 0,
        "load_1m": 0.0,
        "load_5m": 0.0,
        "load_15m": 0.0,
        "ram_total_gb": 0.0,
        "ram_used_gb": 0.0,
        "ram_pct": 0.0,
        "disk_total_gb": 0.0,
        "disk_used_gb": 0.0,
        "disk_pct": 0.0,
        "gpu_temp_c": None,
        "gpu_power_w": None,
        "gpu_util_pct": None,
        "gpu_vram_used_gb": None,
        "gpu_vram_total_gb": None,
        "net_latency_ms": 10.0,
    }

    if _HAS_PSUTIL:
        snap["cpu_pct"] = psutil.cpu_percent(interval=0.05)
        snap["cpu_count"] = psutil.cpu_count(logical=True) or 0
        try:
            load = psutil.getloadavg()
            snap["load_1m"], snap["load_5m"], snap["load_15m"] = load
        except Exception:
            pass

        vm = psutil.virtual_memory()
        snap["ram_total_gb"] = vm.total / (1024 ** 3)
        snap["ram_used_gb"] = vm.used / (1024 ** 3)
        snap["ram_pct"] = vm.percent

        disk = psutil.disk_usage("/")
        snap["disk_total_gb"] = disk.total / (1024 ** 3)
        snap["disk_used_gb"] = disk.used / (1024 ** 3)
        snap["disk_pct"] = disk.percent

    # GPU
    gpu = query_gpu()
    if gpu:
        snap["gpu_temp_c"] = gpu.get("temp_c")
        snap["gpu_power_w"] = gpu.get("power_w")
        snap["gpu_util_pct"] = gpu.get("util_pct")
        if gpu.get("vram_used_mb") is not None:
            snap["gpu_vram_used_gb"] = gpu["vram_used_mb"] / 1024
        if gpu.get("vram_total_mb") is not None:
            snap["gpu_vram_total_gb"] = gpu["vram_total_mb"] / 1024

    return snap


def simulate_stressed_telemetry(
    cpu_pct: float = 95.0,
    ram_pct: float = 98.0,
    disk_pct: float = 99.5,
    gpu_util_pct: float = 98.0,
    gpu_temp_c: float = 84.0,
    gpu_vram_used_gb: float = 78.5,
    gpu_vram_total_gb: float = 80.0,
    net_latency_ms: float = 850.0,
) -> dict[str, Any]:
    """Generate custom stressed telemetry for hardware starvation tests."""
    return {
        "timestamp": time.time(),
        "cpu_pct": cpu_pct,
        "cpu_count": 64,
        "load_1m": 48.5,
        "load_5m": 42.0,
        "load_15m": 35.2,
        "ram_total_gb": 128.0,
        "ram_used_gb": 128.0 * (ram_pct / 100),
        "ram_pct": ram_pct,
        "disk_total_gb": 2000.0,
        "disk_used_gb": 2000.0 * (disk_pct / 100),
        "disk_pct": disk_pct,
        "gpu_temp_c": gpu_temp_c,
        "gpu_power_w": 380.0,
        "gpu_util_pct": gpu_util_pct,
        "gpu_vram_used_gb": gpu_vram_used_gb,
        "gpu_vram_total_gb": gpu_vram_total_gb,
        "net_latency_ms": net_latency_ms,
    }


def format_somatic_header(snap: dict[str, Any]) -> str:
    """Format hardware telemetry snapshot into a compact system context header."""
    parts = [
        f"CPU:{snap['cpu_pct']:.0f}%",
        f"RAM:{snap['ram_pct']:.0f}%",
        f"DISK:{snap['disk_pct']:.0f}%",
    ]

    if snap.get("gpu_util_pct") is not None:
        gpu_str = f"GPU:{snap['gpu_util_pct']:.0f}%"
        if snap.get("gpu_vram_used_gb") is not None and snap.get("gpu_vram_total_gb") is not None:
            gpu_str += f"(VRAM:{snap['gpu_vram_used_gb']:.1f}/{snap['gpu_vram_total_gb']:.1f}GB)"
        if snap.get("gpu_temp_c") is not None:
            gpu_str += f"@{snap['gpu_temp_c']:.0f}°C"
        parts.append(gpu_str)

    if snap.get("net_latency_ms", 0.0) > 0:
        parts.append(f"NET_LATENCY:{snap['net_latency_ms']:.0f}ms")

    return f"[SOMATIC " + " | ".join(parts) + "]"
