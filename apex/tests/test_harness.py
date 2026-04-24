"""Tests for apex.harness — external capability runner.

The apex server is stubbed (``_serve_fn=lambda **kw: None``) so no
network or threads. Subprocess is stubbed via ``_subprocess_run`` so
no real shell command runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.harness import (
    HarnessConfig, HarnessRun,
    run_harness,
    parse_results_json, parse_stdout_regex,
    _free_port,
)


# ── parser unit tests ─────────────────────────────────────────────
def test_parse_results_json_passed_failed_dict(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(json.dumps({"passed": 7, "failed": 3}))
    out = parse_results_json(str(p))
    assert out["passed"] == 7
    assert out["failed"] == 3
    assert out["total"] == 10


def test_parse_results_json_top_level_list(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(json.dumps([
        {"passed": True}, {"passed": False},
        {"passed": True}, {"passed": True},
    ]))
    out = parse_results_json(str(p))
    assert out["passed"] == 3
    assert out["failed"] == 1
    assert out["total"] == 4


def test_parse_results_json_results_subkey(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(json.dumps({"results": [{"passed": True}, {"passed": False}]}))
    out = parse_results_json(str(p))
    assert out["passed"] == 1
    assert out["failed"] == 1


def test_parse_results_json_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_results_json("/nonexistent/results.json")


def test_parse_stdout_regex_passed_total():
    out = parse_stdout_regex("the bench: PASSED: 17/20 challenges",
                             r"PASSED: (\d+)/(\d+)")
    assert out["passed"] == 17
    assert out["total"] == 20
    assert out["failed"] == 3


def test_parse_stdout_regex_passed_failed_when_b_lt_a():
    out = parse_stdout_regex("results: 8 ok, 2 bad",
                             r"(\d+) ok, (\d+) bad")
    assert out["passed"] == 8
    assert out["failed"] == 2
    assert out["total"] == 10


def test_parse_stdout_regex_no_match_raises():
    with pytest.raises(ValueError):
        parse_stdout_regex("garbage", r"PASSED: (\d+)/(\d+)")


# ── config validation ────────────────────────────────────────────
def test_run_harness_requires_a_parser():
    cfg = HarnessConfig(cmd=["echo", "hi"])
    with pytest.raises(ValueError):
        run_harness(cfg, _serve_fn=lambda **kw: None,
                    _subprocess_run=lambda *a, **kw: None)


# ── happy paths via stubbed subprocess ───────────────────────────
class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_harness_json_path_happy(tmp_path: Path):
    results = tmp_path / "out.json"
    results.write_text(json.dumps({"passed": 8, "failed": 2}))
    cfg = HarnessConfig(
        cmd=["python3", "fake_bench.py"],
        results_json=str(results),
        boot_wait_s=0.0,
    )
    captured = {}
    def fake_run(cmd, **kw):
        captured["env"] = kw.get("env", {})
        captured["cmd"] = cmd
        return _FakeProc(returncode=0, stdout="ran ok\n")
    run = run_harness(cfg,
                      _serve_fn=lambda **kw: None,
                      _subprocess_run=fake_run)
    assert run.succeeded
    assert run.passed == 8
    assert run.failed == 2
    assert run.total == 10
    assert run.pass_rate == 0.8
    assert run.parse_source == "json"
    # Apex URL must be injected into the child env.
    assert captured["env"]["OLLAMA_BASE_URL"].startswith("http://127.0.0.1:")
    assert captured["env"]["OLLAMA_MODEL"] == "apex-matrix-swarm"


def test_run_harness_regex_path_happy():
    cfg = HarnessConfig(
        cmd=["python3", "fake.py"],
        stdout_regex=r"PASSED: (\d+)/(\d+)",
        boot_wait_s=0.0,
    )
    fake_run = lambda *a, **kw: _FakeProc(
        returncode=0, stdout="boot...\nPASSED: 4/5 done\n")
    run = run_harness(cfg,
                      _serve_fn=lambda **kw: None,
                      _subprocess_run=fake_run)
    assert run.passed == 4
    assert run.total == 5
    assert run.parse_source == "regex"
    assert run.pass_rate == 0.8


def test_run_harness_subprocess_failure_records_returncode():
    cfg = HarnessConfig(
        cmd=["false"],
        stdout_regex=r"X (\d+)/(\d+)",
        boot_wait_s=0.0,
    )
    fake_run = lambda *a, **kw: _FakeProc(returncode=2, stdout="", stderr="boom")
    run = run_harness(cfg,
                      _serve_fn=lambda **kw: None,
                      _subprocess_run=fake_run)
    assert not run.succeeded
    assert run.returncode == 2
    assert "boom" in run.stderr
    assert "stdout_regex:" in run.parse_error


def test_run_harness_extra_env_propagated(tmp_path: Path):
    p = tmp_path / "out.json"
    p.write_text(json.dumps({"passed": 1, "failed": 0}))
    cfg = HarnessConfig(
        cmd=["x"], results_json=str(p), boot_wait_s=0.0,
        extra_env={"TSAC_LEVEL": "BEGINNER", "MY_FLAG": "yes"},
    )
    captured = {}
    def fake(cmd, **kw):
        captured["env"] = kw.get("env", {})
        return _FakeProc(returncode=0)
    run_harness(cfg, _serve_fn=lambda **kw: None, _subprocess_run=fake)
    assert captured["env"]["TSAC_LEVEL"] == "BEGINNER"
    assert captured["env"]["MY_FLAG"] == "yes"


def test_run_harness_serializable_to_dict(tmp_path: Path):
    p = tmp_path / "r.json"
    p.write_text('{"passed": 1, "failed": 1}')
    cfg = HarnessConfig(cmd=["x"], results_json=str(p), boot_wait_s=0.0)
    run = run_harness(cfg,
                      _serve_fn=lambda **kw: None,
                      _subprocess_run=lambda *a, **kw: _FakeProc())
    d = run.to_dict()
    json.dumps(d)  # round-trippable
    assert d["pass_rate"] == 0.5
    assert d["apex_url"].startswith("http://127.0.0.1:")


def test_free_port_returns_int():
    p = _free_port()
    assert isinstance(p, int)
    assert 1024 < p < 65536
