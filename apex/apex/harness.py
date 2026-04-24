"""External capability harness.

Boots an ``apex.serve`` instance on a free port, runs an arbitrary
external benchmark with ``OLLAMA_BASE_URL`` injected so it speaks to
ApexBrain instead of raw Ollama, then parses pass/fail from one of:

* a JSON results file the harness writes (``--results-json path``)
* a stdout regex (e.g. ``r"PASSED: (\\d+)/(\\d+)"``)

Designed for TSACEV-style external runners (``challenge_runner.py``)
but generic enough to wrap any Ollama-compatible benchmark. Result is
a ``HarnessRun`` dataclass that can be fed straight into
``diagnostic`` for capability rating.

Usage from CLI:

    nail-apex bench \\
        --cmd "python3 challenge_runner.py --start-level BEGINNER" \\
        --cwd /path/to/TSACEV \\
        --results-json /tmp/tsacev_out.json \\
        --port 11437

Usage from Python:

    from apex.harness import HarnessConfig, run_harness
    cfg = HarnessConfig(
        cmd=["python3", "run_bench.py"],
        cwd="/path/to/bench",
        results_json="/tmp/out.json",
    )
    run = run_harness(cfg)
    print(run.passed, run.failed, run.pass_rate)

Provenance: harness pattern inspired by
~/Desktop/apex_matrix/start_nail_infrastructure.sh which boots a
TSACEV adapter then expects users to manually run TSACEV. This is the
Pythonic, scriptable, stub-testable equivalent.
apex_matrix is unchanged.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from .brain import ApexBrain


def _free_port() -> int:
    """Ask the kernel for a free TCP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class HarnessConfig:
    """Inputs to ``run_harness``.

    Either ``results_json`` OR ``stdout_regex`` must be set so we know
    how to score pass/fail. If both are set, ``results_json`` wins.
    """
    cmd: Sequence[str]
    cwd: Optional[str] = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 600.0
    # Apex server config
    host: str = "127.0.0.1"
    port: Optional[int] = None  # None => pick a free one
    model_name: str = "apex-matrix-swarm"
    boot_wait_s: float = 2.0
    # Result parsing
    results_json: Optional[str] = None  # path the bench writes
    stdout_regex: Optional[str] = None  # e.g. r"PASSED: (\d+)/(\d+)"
    # Extra env vars beyond OLLAMA_BASE_URL
    extra_env: dict[str, str] = field(default_factory=dict)


@dataclass
class HarnessRun:
    """Result of running an external benchmark through ApexBrain."""
    cmd: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    passed: int = 0
    failed: int = 0
    total: int = 0
    parse_source: str = ""   # "json" | "regex" | "none"
    parse_error: str = ""
    apex_url: str = ""
    apex_model_name: str = ""
    raw_results: dict[str, Any] | None = None

    @property
    def pass_rate(self) -> float:
        if self.total <= 0:
            return 0.0
        return self.passed / self.total

    @property
    def succeeded(self) -> bool:
        """Subprocess exited cleanly AND we parsed at least one result."""
        return self.returncode == 0 and self.total > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd": list(self.cmd),
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 2),
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "pass_rate": round(self.pass_rate, 4),
            "parse_source": self.parse_source,
            "parse_error": self.parse_error,
            "apex_url": self.apex_url,
            "apex_model_name": self.apex_model_name,
        }


# ── parsers (exposed for testing) ──────────────────────────────────
def parse_results_json(path: str) -> dict[str, Any]:
    """Read a results JSON. Recognises common shapes:

      {"passed": 7, "failed": 3}
      {"passed": 7, "failed": 3, "total": 10}
      {"results": [{"passed": true}, {"passed": false}, …]}
      [{"passed": true}, {"passed": false}, …]    (top-level list)
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"results json not found: {path}")
    data = json.loads(p.read_text())
    out = {"passed": 0, "failed": 0, "total": 0, "raw": data}
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            items = data["results"]
        elif "passed" in data and "failed" in data:
            out["passed"] = int(data.get("passed", 0))
            out["failed"] = int(data.get("failed", 0))
            out["total"] = int(data.get("total",
                                        out["passed"] + out["failed"]))
            return out
    if items is None:
        raise ValueError(
            "results json must contain {passed,failed} or list of "
            "{passed: bool} entries")
    for it in items:
        if isinstance(it, dict) and bool(it.get("passed")):
            out["passed"] += 1
        else:
            out["failed"] += 1
    out["total"] = out["passed"] + out["failed"]
    return out


def parse_stdout_regex(stdout: str, pattern: str) -> dict[str, int]:
    """Apply a regex with two integer groups (passed, total).

    ``passed/total`` form is matched first; ``passed/failed`` is also
    supported when the third group is missing or numeric.
    """
    rx = re.compile(pattern)
    m = rx.search(stdout)
    if not m:
        raise ValueError(f"regex {pattern!r} did not match stdout")
    groups = m.groups()
    if len(groups) < 2:
        raise ValueError(
            f"regex {pattern!r} must capture at least 2 integer groups")
    a, b = int(groups[0]), int(groups[1])
    # Heuristic: if b >= a treat as (passed, total); else as (passed, failed).
    if b >= a:
        passed, total = a, b
        failed = total - passed
    else:
        passed, failed = a, b
        total = passed + failed
    return {"passed": passed, "failed": failed, "total": total}


# ── main runner ────────────────────────────────────────────────────
def run_harness(cfg: HarnessConfig, *,
                brain: Optional[ApexBrain] = None,
                _serve_fn=None,
                _subprocess_run=subprocess.run) -> HarnessRun:
    """Boot apex, run cfg.cmd against it, return a HarnessRun.

    ``brain`` defaults to a fresh ``ApexBrain()``.
    ``_serve_fn`` and ``_subprocess_run`` are stub injection points for
    tests. In production neither is overridden.
    """
    if not cfg.results_json and not cfg.stdout_regex:
        raise ValueError(
            "HarnessConfig requires results_json or stdout_regex")

    port = cfg.port or _free_port()
    url = f"http://{cfg.host}:{port}"

    # Boot the apex server in a daemon thread so we can shut down
    # by simply exiting (uvicorn doesn't expose a clean .stop() yet).
    serve_fn = _serve_fn
    if serve_fn is None:
        from .server import serve as _real_serve
        serve_fn = _real_serve

    server_thread = threading.Thread(
        target=serve_fn,
        kwargs={"host": cfg.host, "port": port,
                "brain": brain or ApexBrain(),
                "model_name": cfg.model_name},
        daemon=True,
    )
    server_thread.start()
    time.sleep(cfg.boot_wait_s)

    # Build child env with OLLAMA_BASE_URL injected.
    child_env = os.environ.copy()
    child_env["OLLAMA_BASE_URL"] = url
    child_env["OLLAMA_HOST"] = url   # some clients look at this name
    child_env["OLLAMA_MODEL"] = cfg.model_name
    child_env.update(cfg.env)
    child_env.update(cfg.extra_env)

    started = time.perf_counter()
    try:
        proc = _subprocess_run(
            list(cfg.cmd),
            cwd=cfg.cwd,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=cfg.timeout_s,
            check=False,
        )
        rc = proc.returncode
        out = proc.stdout or ""
        err = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = -1
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = ((exc.stderr or "") if isinstance(exc.stderr, str) else "") + \
              f"\nTIMEOUT after {cfg.timeout_s}s"

    duration_s = time.perf_counter() - started

    run = HarnessRun(
        cmd=cfg.cmd, returncode=rc,
        stdout=out, stderr=err,
        duration_s=duration_s,
        apex_url=url, apex_model_name=cfg.model_name,
    )

    # Score
    parsed = None
    parse_err = ""
    parse_src = "none"
    if cfg.results_json:
        try:
            parsed = parse_results_json(cfg.results_json)
            parse_src = "json"
        except Exception as exc:
            parse_err = f"results_json: {exc}"
    if parsed is None and cfg.stdout_regex:
        try:
            parsed = parse_stdout_regex(out, cfg.stdout_regex)
            parse_src = "regex"
        except Exception as exc:
            parse_err = (parse_err + " | " if parse_err else "") + \
                        f"stdout_regex: {exc}"
    if parsed is not None:
        run.passed = int(parsed["passed"])
        run.failed = int(parsed["failed"])
        run.total = int(parsed["total"])
        run.parse_source = parse_src
        run.raw_results = parsed.get("raw")
    else:
        run.parse_error = parse_err

    return run
