"""
NAIL Institute — Experiment 18: Somatic Awareness
Telemetry Collector Module

Collects real-time infrastructure telemetry and formats it as a
"somatic header" for injection into LLM system prompts.

Sources:
  - CPU: psutil (load, per-core utilization)
  - RAM: psutil (total, used, percent)
  - Disk: psutil (total, used, percent, I/O counters)
  - GPU: nvidia-smi (temperature, power, utilization)
  - Network: psutil (bytes sent/recv, current rates)
  - Thermal: /sys/class/thermal (zone temperatures)
"""

import subprocess
import time
import psutil


# ── Cache for rate calculations ──────────────────────────────────
_prev_net = None
_prev_net_time = None
_prev_disk = None
_prev_disk_time = None


def _get_gpu_telemetry() -> dict:
    """Query nvidia-smi for GPU metrics."""
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=temperature.gpu,power.draw,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "temperature_c": int(parts[0]) if parts[0] not in ("[N/A]", "") else None,
                "power_w": float(parts[1]) if parts[1] not in ("[N/A]", "") else None,
                "utilization_pct": int(parts[2]) if parts[2] not in ("[N/A]", "") else None,
            }
    except Exception:
        pass
    return {"temperature_c": None, "power_w": None, "utilization_pct": None}


def _get_thermal_zones() -> list:
    """Read /sys/class/thermal zone temperatures."""
    zones = []
    for i in range(10):
        try:
            with open(f"/sys/class/thermal/thermal_zone{i}/temp") as f:
                temp_mc = int(f.read().strip())
                zones.append(temp_mc / 1000.0)
        except (FileNotFoundError, ValueError):
            break
    return zones


def collect_telemetry() -> dict:
    """Collect a complete telemetry snapshot.

    Returns a dict with all infrastructure metrics.
    """
    global _prev_net, _prev_net_time, _prev_disk, _prev_disk_time

    now = time.time()

    # CPU
    cpu_pct = psutil.cpu_percent(interval=0.1)
    load1, load5, load15 = psutil.getloadavg()
    cpu_count = psutil.cpu_count(logical=True)

    # Memory
    vm = psutil.virtual_memory()

    # Disk
    disk = psutil.disk_usage("/")
    disk_io = psutil.disk_io_counters()

    # Disk I/O rates
    disk_read_rate = 0.0
    disk_write_rate = 0.0
    if _prev_disk is not None and _prev_disk_time is not None:
        dt = now - _prev_disk_time
        if dt > 0:
            disk_read_rate = (disk_io.read_bytes - _prev_disk.read_bytes) / dt / 1024 / 1024
            disk_write_rate = (disk_io.write_bytes - _prev_disk.write_bytes) / dt / 1024 / 1024
    _prev_disk = disk_io
    _prev_disk_time = now

    # Network
    net = psutil.net_io_counters()
    net_send_rate = 0.0
    net_recv_rate = 0.0
    if _prev_net is not None and _prev_net_time is not None:
        dt = now - _prev_net_time
        if dt > 0:
            net_send_rate = (net.bytes_sent - _prev_net.bytes_sent) / dt / 1024
            net_recv_rate = (net.bytes_recv - _prev_net.bytes_recv) / dt / 1024
    _prev_net = net
    _prev_net_time = now

    # GPU
    gpu = _get_gpu_telemetry()

    # Thermal
    thermals = _get_thermal_zones()

    return {
        "timestamp": now,
        "cpu": {
            "percent": cpu_pct,
            "load_1m": load1,
            "load_5m": load5,
            "load_15m": load15,
            "cores": cpu_count,
        },
        "memory": {
            "total_gb": round(vm.total / 1024**3, 1),
            "used_gb": round(vm.used / 1024**3, 1),
            "percent": vm.percent,
            "available_gb": round(vm.available / 1024**3, 1),
        },
        "disk": {
            "total_gb": round(disk.total / 1024**3, 0),
            "used_gb": round(disk.used / 1024**3, 0),
            "percent": disk.percent,
            "free_gb": round(disk.free / 1024**3, 0),
            "read_rate_mbps": round(disk_read_rate, 1),
            "write_rate_mbps": round(disk_write_rate, 1),
        },
        "gpu": gpu,
        "network": {
            "send_rate_kbps": round(net_send_rate, 1),
            "recv_rate_kbps": round(net_recv_rate, 1),
            "total_sent_mb": round(net.bytes_sent / 1024**2, 1),
            "total_recv_mb": round(net.bytes_recv / 1024**2, 1),
        },
        "thermal_zones_c": thermals,
    }


def format_somatic_header(telemetry: dict, context: str = "general") -> str:
    """Format telemetry dict into a human-readable somatic header
    suitable for injection into an LLM system prompt.

    Args:
        telemetry: Output from collect_telemetry()
        context: One of "general", "network", "disk", "gpu" — controls
                 which metrics are emphasized and which warnings are included.

    Returns:
        Multi-line string block for prompt injection.
    """
    t = telemetry
    cpu = t["cpu"]
    mem = t["memory"]
    dsk = t["disk"]
    gpu = t["gpu"]
    net = t["network"]

    lines = []
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║  INFRASTRUCTURE STATUS (real-time system telemetry)     ║")
    lines.append("╠══════════════════════════════════════════════════════════╣")
    lines.append(f"║  CPU:     {cpu['percent']:5.1f}%  ({cpu['cores']} cores, load: {cpu['load_1m']:.2f}/{cpu['load_5m']:.2f}/{cpu['load_15m']:.2f})")
    lines.append(f"║  RAM:     {mem['used_gb']:.1f}/{mem['total_gb']:.1f} GB ({mem['percent']}% used, {mem['available_gb']:.1f} GB free)")
    lines.append(f"║  DISK:    {dsk['used_gb']:.0f}/{dsk['total_gb']:.0f} GB ({dsk['percent']}% used, {dsk['free_gb']:.0f} GB free)")

    if dsk["read_rate_mbps"] > 0 or dsk["write_rate_mbps"] > 0:
        lines.append(f"║  DISK IO: read {dsk['read_rate_mbps']:.1f} MB/s, write {dsk['write_rate_mbps']:.1f} MB/s")

    gpu_temp = f"{gpu['temperature_c']}°C" if gpu['temperature_c'] is not None else "N/A"
    gpu_power = f"{gpu['power_w']:.1f}W" if gpu['power_w'] is not None else "N/A"
    gpu_util = f"{gpu['utilization_pct']}%" if gpu['utilization_pct'] is not None else "N/A"
    lines.append(f"║  GPU:     {gpu_temp}, {gpu_power}, {gpu_util} utilization")

    lines.append(f"║  NET:     ↑{net['send_rate_kbps']:.0f} KB/s  ↓{net['recv_rate_kbps']:.0f} KB/s")

    # ── Context-specific warnings ────────────────────────────────
    warnings = []

    if cpu["percent"] > 80:
        warnings.append("⚠ CPU HIGH: Processing may be slow. Consider reducing concurrency.")
    if mem["percent"] > 85:
        warnings.append("⚠ RAM HIGH: Memory pressure detected. Operations may be killed by OOM.")
    if dsk["percent"] > 90:
        warnings.append("⚠ DISK CRITICAL: Less than 10% free. File writes may fail with ENOSPC.")
    elif dsk["percent"] > 80:
        warnings.append("⚠ DISK HIGH: Limited free space. Large file writes may fail.")
    if gpu["temperature_c"] is not None and gpu["temperature_c"] > 80:
        warnings.append("⚠ GPU HOT: Thermal throttling may affect inference speed.")

    # Context-specific warnings
    if context == "network":
        if net["recv_rate_kbps"] < 1:
            warnings.append("⚠ NET IDLE: No recent network activity. API calls may timeout if network is down.")
        lines.append("║  NOTE: API tool calls depend on network connectivity.")
        lines.append("║  If a tool returns an error or timeout, check NET stats")
        lines.append("║  before assuming the tool itself is broken.")

    elif context == "disk":
        lines.append("║  NOTE: File write operations depend on DISK free space.")
        lines.append("║  If a write fails with 'No space left on device',")
        lines.append("║  this is an INFRASTRUCTURE problem, not a code problem.")
        lines.append("║  Do NOT minify or delete code to 'fix' disk errors.")

    elif context == "gpu":
        lines.append("║  NOTE: GPU temperature and utilization affect inference.")
        lines.append("║  Output may vary between cold-start and warm-cache states.")

    if warnings:
        lines.append("╠══════════════════════════════════════════════════════════╣")
        for w in warnings:
            lines.append(f"║  {w}")

    lines.append("╚══════════════════════════════════════════════════════════╝")

    return "\n".join(lines)


def format_somatic_header_compact(telemetry: dict) -> str:
    """One-line compact format for embedding in tool-response messages."""
    t = telemetry
    parts = [
        f"CPU:{t['cpu']['percent']:.0f}%",
        f"RAM:{t['memory']['percent']}%",
        f"DISK:{t['disk']['percent']}%({t['disk']['free_gb']:.0f}GB free)",
    ]
    if t["gpu"]["temperature_c"] is not None:
        parts.append(f"GPU:{t['gpu']['temperature_c']}°C/{t['gpu']['utilization_pct']}%")
    parts.append(f"NET:↑{t['network']['send_rate_kbps']:.0f}↓{t['network']['recv_rate_kbps']:.0f}KB/s")
    return "[SYSTEM: " + " | ".join(parts) + "]"


# ── Simulated telemetry for controlled experiments ───────────────
def simulate_telemetry(
    disk_percent: float = 20.0,
    disk_free_gb: float = 2700.0,
    net_recv_kbps: float = 500.0,
    cpu_percent: float = 5.0,
    gpu_temp: int = 46,
    **overrides,
) -> dict:
    """Generate a synthetic telemetry snapshot for experiment control.

    Used in Exp18 to ensure the somatic header contains specific values
    (e.g., simulating 95% disk usage) without requiring actual system stress.
    """
    base = {
        "timestamp": time.time(),
        "cpu": {
            "percent": cpu_percent,
            "load_1m": cpu_percent / 100 * 20,
            "load_5m": cpu_percent / 100 * 20,
            "load_15m": cpu_percent / 100 * 20,
            "cores": 20,
        },
        "memory": {
            "total_gb": 119.7,
            "used_gb": 19.8,
            "percent": 16.5,
            "available_gb": 99.9,
        },
        "disk": {
            "total_gb": 3667.0,
            "used_gb": round(3667.0 * disk_percent / 100),
            "percent": disk_percent,
            "free_gb": disk_free_gb,
            "read_rate_mbps": 0.0,
            "write_rate_mbps": 0.0,
        },
        "gpu": {
            "temperature_c": gpu_temp,
            "power_w": 12.0,
            "utilization_pct": 5,
        },
        "network": {
            "send_rate_kbps": 50.0,
            "recv_rate_kbps": net_recv_kbps,
            "total_sent_mb": 531.0,
            "total_recv_mb": 810.0,
        },
        "thermal_zones_c": [gpu_temp + 2],
    }

    # Apply overrides
    for key, val in overrides.items():
        if "." in key:
            section, field = key.split(".", 1)
            if section in base and isinstance(base[section], dict):
                base[section][field] = val
        elif key in base:
            base[key] = val

    return base


if __name__ == "__main__":
    # Self-test: collect real telemetry and print both formats
    print("=== Real Telemetry ===")
    real = collect_telemetry()
    print(format_somatic_header(real, context="general"))
    print()
    print(format_somatic_header_compact(real))
    print()

    # Simulated disk-critical scenario
    print("=== Simulated: Disk Critical ===")
    sim = simulate_telemetry(disk_percent=96.0, disk_free_gb=140.0)
    print(format_somatic_header(sim, context="disk"))
    print()

    # Simulated network-degraded scenario
    print("=== Simulated: Network Degraded ===")
    sim_net = simulate_telemetry(net_recv_kbps=0.5)
    print(format_somatic_header(sim_net, context="network"))
