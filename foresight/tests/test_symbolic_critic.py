"""Tests for foresight.symbolic_critic.SymbolicCritic.

Heavy work (subprocess / sympy / z3) is stubbed via injectable runners so
the test suite stays fast and dependency-free.
"""
from __future__ import annotations

import pytest

from foresight.plan import Plan, Step
from foresight.critique import RiskSeverity, Verdict
from foresight.symbolic_critic import (
    SymbolicCritic, ExecResult,
    run_python, check_sympy_equivalence, check_z3,
)


def _ok(stdout=""):    return ExecResult(ok=True, stdout=stdout)
def _bad(error="boom"): return ExecResult(ok=False, error=error)


# ── plans without any validation hints ─────────────────────────────
def test_plan_with_no_validatable_steps_returns_clean_critique():
    plan = Plan(goal="x", steps=[Step(tool="noop", args={})])
    c = SymbolicCritic().critique(plan)
    assert c.risks == []
    assert c.risk == 0.0
    assert c.verdict() is Verdict.ALLOW
    assert "no validatable" in c.summary


# ── python_code path ───────────────────────────────────────────────
def test_python_code_passes_clean():
    plan = Plan(goal="x", steps=[
        Step(tool="run", args={"python_code": "print('ok')"}),
    ])
    c = SymbolicCritic(python_runner=lambda code, **kw: _ok("ok\n")).critique(plan)
    assert c.risks == []
    assert "1/1 validations passed" in c.summary


def test_python_code_fail_emits_critical_risk():
    plan = Plan(goal="x", steps=[
        Step(tool="run", args={"python_code": "raise RuntimeError('boom')"}),
    ])
    c = SymbolicCritic(python_runner=lambda code, **kw: _bad("exit=1")).critique(plan)
    assert len(c.risks) == 1
    assert c.risks[0].severity is RiskSeverity.CRITICAL
    assert c.risks[0].affects_step == 1
    assert c.verdict() is Verdict.REJECT


def test_python_runner_receives_timeout_override():
    seen = {}
    def fake(code, *, timeout_s, python_exe=None):
        seen["timeout_s"] = timeout_s
        return _ok()
    plan = Plan(goal="x", steps=[
        Step(tool="run", args={"python_code": "1", "validate_timeout_s": 12.5}),
    ])
    SymbolicCritic(python_runner=fake).critique(plan)
    assert seen["timeout_s"] == 12.5


# ── sympy path ─────────────────────────────────────────────────────
def test_sympy_equivalent_expressions_pass():
    plan = Plan(goal="x", steps=[Step(tool="alg", args={
        "sympy_expr": "(x+1)*(x-1)", "sympy_expected": "x**2 - 1",
    })])
    c = SymbolicCritic(sympy_runner=lambda a, b: _ok()).critique(plan)
    assert c.risks == []


def test_sympy_mismatch_emits_critical_risk():
    plan = Plan(goal="x", steps=[Step(tool="alg", args={
        "sympy_expr": "x + 1", "sympy_expected": "x + 2",
    })])
    c = SymbolicCritic(sympy_runner=lambda a, b: _bad("not equivalent")).critique(plan)
    assert len(c.risks) == 1
    assert c.risks[0].severity is RiskSeverity.CRITICAL


def test_sympy_expected_missing_is_high_not_critical():
    """Missing target is a config bug, not a falsification — flag HIGH."""
    plan = Plan(goal="x", steps=[Step(tool="alg", args={
        "sympy_expr": "x + 1",
    })])
    c = SymbolicCritic().critique(plan)
    assert len(c.risks) == 1
    assert c.risks[0].severity is RiskSeverity.HIGH
    # And does NOT count as a validation attempt.
    assert "0/0" in c.summary or "no validatable" in c.summary


# ── z3 path ────────────────────────────────────────────────────────
def test_z3_sat_default_passes():
    plan = Plan(goal="x", steps=[Step(tool="solve", args={
        "z3_code": "x = Int('x'); s = Solver(); s.add(x > 0)",
    })])
    c = SymbolicCritic(z3_runner=lambda code, exp, **kw: _ok("sat")).critique(plan)
    assert c.risks == []


def test_z3_unsat_when_expected_sat_emits_critical():
    plan = Plan(goal="x", steps=[Step(tool="solve", args={
        "z3_code": "x = Int('x'); s = Solver(); s.add(x > 0, x < 0)",
        "z3_expected": "sat",
    })])
    c = SymbolicCritic(z3_runner=lambda code, exp, **kw: _bad(
        "got 'unsat', expected 'sat'")).critique(plan)
    assert c.risks[0].severity is RiskSeverity.CRITICAL


# ── multi-step aggregation ─────────────────────────────────────────
def test_multistep_mixed_pass_fail_summarises_correctly():
    plan = Plan(goal="x", steps=[
        Step(tool="a", args={"python_code": "x"}),
        Step(tool="b", args={"python_code": "y"}),
        Step(tool="c", args={"sympy_expr": "x", "sympy_expected": "x"}),
    ])
    runs = iter([_ok(), _bad("exit=1")])
    c = SymbolicCritic(
        python_runner=lambda code, **kw: next(runs),
        sympy_runner=lambda a, b: _ok(),
    ).critique(plan)
    assert "2/3 validations passed" in c.summary
    assert len(c.risks) == 1
    assert c.risks[0].affects_step == 2


def test_critique_model_field_is_symbolic():
    plan = Plan(goal="x", steps=[])
    c = SymbolicCritic().critique(plan)
    assert c.model == "symbolic"


# ── live integration smokes (skip if libs absent) ─────────────────
def test_run_python_real_subprocess_smoke():
    res = run_python("print('hi')")
    assert res.ok
    assert "hi" in res.stdout


def test_check_sympy_real_smoke():
    sympy = pytest.importorskip("sympy")  # noqa: F841
    assert check_sympy_equivalence("(x+1)**2", "x**2 + 2*x + 1").ok
    assert not check_sympy_equivalence("x + 1", "x + 2").ok


def test_check_z3_real_smoke():
    z3 = pytest.importorskip("z3")  # noqa: F841
    code = "x = Int('x'); s = Solver(); s.add(x > 0)"
    assert check_z3(code, "sat").ok


# ── Protocol conformance ──────────────────────────────────────────
def test_symbolic_critic_satisfies_critic_protocol():
    from foresight.critic import Critic
    assert isinstance(SymbolicCritic(), Critic)
