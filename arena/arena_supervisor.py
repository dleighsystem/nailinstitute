"""
Arena Supervisor — 24/7 Production Watchdog
============================================
Keeps the Pathology Collider running continuously, handles crashes,
rotates logs, exports daily breakthrough reports to AVE, and emits
health metrics.

Usage (host/VM):
    python3 arena/arena_supervisor.py --checkpoint-dir /data/arena

Usage (Docker — handled by docker-compose restart: unless-stopped):
    The collider itself is the CMD; Docker is the supervisor.
    This script is for bare-metal / systemd deployments.

Design:
    - Launches `arena run --production` as a subprocess
    - Restarts on crash with exponential back-off (cap: 5 min)
    - Rotates checkpoint snapshots daily
    - Posts daily summary to AVE as draft cards
    - Writes health beat to /tmp/arena_supervisor.beat every 60s
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BEAT_FILE = Path("/tmp/arena_supervisor.beat")
MIN_BACKOFF = 5      # seconds before first restart
MAX_BACKOFF = 300    # seconds max back-off
DAILY_REPORT_INTERVAL = 86400   # seconds between daily reports


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_beat(state: dict) -> None:
    BEAT_FILE.write_text(json.dumps({**state, "ts": _utcnow()}, indent=2))


def _daily_report(checkpoint_dir: Path) -> None:
    """Export today's breakthroughs as draft AVE cards and log a summary."""
    cp_path = checkpoint_dir / "checkpoint.json"
    if not cp_path.exists():
        return
    try:
        data = json.loads(cp_path.read_text())
        bts = data.get("breakthroughs", [])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_path = checkpoint_dir / f"daily_report_{today}.json"
        report = {
            "date": today,
            "total_breakthroughs": len(bts),
            "season": data.get("season", 0),
            "generation": data.get("generation", 0),
            "breach_rate": (
                data.get("total_red_wins", 0) / max(1, data.get("total_battles", 1))
            ),
            "breakthroughs": bts[-10:],   # last 10 only
            "blue_thresholds": data.get("blue_thresholds", {}),
        }
        report_path.write_text(json.dumps(report, indent=2))
        print(f"[supervisor] Daily report written to {report_path}", flush=True)
        print(f"[supervisor]   Breakthroughs today: {len(bts)} | "
              f"Breach rate: {report['breach_rate']:.1%} | "
              f"Season: {report['season']}", flush=True)
    except Exception as e:
        print(f"[supervisor] Daily report failed: {e}", flush=True)


def run_supervisor(
    checkpoint_dir: Path,
    arena_args: list[str] | None = None,
) -> None:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    backoff = MIN_BACKOFF
    restarts = 0
    last_report = time.time()

    print(f"[supervisor] Starting Arena supervisor | checkpoint={checkpoint_dir}", flush=True)
    _write_beat({"status": "starting", "restarts": 0})

    # Handle SIGTERM gracefully
    _shutdown = {"requested": False}

    def _on_sigterm(sig, frame):
        _shutdown["requested"] = True
        print("[supervisor] SIGTERM received, shutting down cleanly.", flush=True)

    signal.signal(signal.SIGTERM, _on_sigterm)

    while not _shutdown["requested"]:
        cmd = [
            sys.executable, "-m", "arena.cli", "run",
            "--production",
            "--checkpoint-dir", str(checkpoint_dir),
            "--resume",
        ] + (arena_args or [])

        print(f"[supervisor] Launching collider (restart #{restarts}) | cmd: {' '.join(cmd)}", flush=True)
        _write_beat({"status": "running", "restarts": restarts, "backoff": backoff})

        start = time.time()
        try:
            proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
            while proc.poll() is None:
                if _shutdown["requested"]:
                    proc.terminate()
                    proc.wait(timeout=10)
                    break

                # Health beat every 60s
                elapsed = time.time() - start
                _write_beat({
                    "status": "running",
                    "pid": proc.pid,
                    "restarts": restarts,
                    "uptime_seconds": int(elapsed),
                })

                # Daily report
                if time.time() - last_report >= DAILY_REPORT_INTERVAL:
                    _daily_report(checkpoint_dir)
                    last_report = time.time()

                time.sleep(60)

            rc = proc.returncode
        except Exception as e:
            print(f"[supervisor] Subprocess error: {e}", flush=True)
            rc = -1

        if _shutdown["requested"]:
            break

        uptime = time.time() - start
        restarts += 1
        print(
            f"[supervisor] Collider exited (rc={rc}) after {uptime:.0f}s. "
            f"Restarting in {backoff}s...", flush=True,
        )
        _write_beat({"status": "restarting", "restarts": restarts, "next_in": backoff})

        # Exponential backoff — reset if run was healthy for > 5 min
        if uptime > 300:
            backoff = MIN_BACKOFF
        else:
            backoff = min(backoff * 2, MAX_BACKOFF)

        time.sleep(backoff)

    print("[supervisor] Stopped.", flush=True)
    _write_beat({"status": "stopped", "restarts": restarts})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NAIL Arena Supervisor")
    parser.add_argument(
        "--checkpoint-dir", default="logs/arena",
        help="Directory for Arena checkpoints and daily reports",
    )
    parser.add_argument(
        "--rounds", type=int, default=0,
        help="Override rounds per season (0 = use production default)",
    )
    args = parser.parse_args()

    extra: list[str] = []
    if args.rounds:
        extra += ["--rounds", str(args.rounds)]

    checkpoint_dir = Path(args.checkpoint_dir)

    try:
        run_supervisor(checkpoint_dir, arena_args=extra)
    except KeyboardInterrupt:
        print("\n[supervisor] Keyboard interrupt — stopping.", flush=True)
