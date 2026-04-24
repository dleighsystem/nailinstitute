"""Neuro-symbolic ground-truth Critic.

Where ``HeuristicCritic`` and ``OllamaCritic`` reason *about* the plan,
``SymbolicCritic`` actually *runs* validatable claims and asks objective
oracles whether they hold:

* Python execution    — does this snippet exit cleanly?
* SymPy equivalence   — is ``actual_expr`` algebraically equal to ``expected_expr``?
* Z3 satisfiability   — is the ``solver`` reachable / model-able?

A plan step opts in by setting *any* of the following keys in ``step.args``::

    "python_code":          str   # executed in subprocess; non-zero exit -> CRITICAL
    "sympy_expr":           str   # paired with "sympy_expected"
    "sympy_expected":       str
    "z3_code":              str   # final 's' must be a Solver; expected sat by default
    "z3_expected":          str   # one of "sat" | "unsat" | "unknown"
    "validate_timeout_s":   float # per-step override (default 5.0)

Provenance: ground-truth pattern inspired by
~/Desktop/apex_matrix/pipeline/distillation/validator.py
(NeuroSymbolicValidator, ~60 LOC). Rewritten from scratch — no shared
code; conforms to NAIL ``Critic`` Protocol; uses subprocess sandbox with
hard timeout; Z3 + SymPy are optional imports so the critic degrades
gracefully when the libs are absent.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from typing import Optional

from .critique import Critique, Risk, RiskSeverity
from .plan import Plan, Step


DEFAULT_TIMEOUT_S = 5.0
MODEL_NAME = "symbolic"


# ── runners (exposed for stubbing in tests) ─────────────────────────
@dataclass
class ExecResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str = ""


def run_python(code: str, *,
               timeout_s: float = DEFAULT_TIMEOUT_S,
               python_exe: Optional[str] = None) -> ExecResult:
    """Run Python in a strict subprocess. Returns ExecResult.

    ``python_exe`` defaults to ``sys.executable``. Override only if you
    need a more restrictive interpreter (e.g. nsjail-wrapped python3).
    """
    exe = python_exe or sys.executable
    if not exe or not shutil.which(exe.split()[0]):
        return ExecResult(ok=False, error=f"python interpreter not found: {exe}")
    try:
        out = subprocess.run(
            [exe, "-I", "-c", code],
            capture_output=True, text=True, timeout=timeout_s,
        )
        return ExecResult(
            ok=(out.returncode == 0),
            stdout=out.stdout,
            stderr=out.stderr,
            error="" if out.returncode == 0 else f"exit={out.returncode}",
        )
    except subprocess.TimeoutExpired:
        return ExecResult(ok=False, error=f"timeout after {timeout_s}s")
    except Exception as exc:  # pragma: no cover - exceptional
        return ExecResult(ok=False, error=str(exc))


def check_sympy_equivalence(actual: str, expected: str) -> ExecResult:
    """True iff ``simplify(actual - expected) == 0``. SymPy required."""
    try:
        import sympy
        from sympy.parsing.sympy_parser import parse_expr
    except ImportError:
        return ExecResult(ok=False, error="sympy not installed")
    try:
        a = parse_expr(actual)
        b = parse_expr(expected)
        diff = sympy.simplify(a - b)
        equivalent = diff == 0
        return ExecResult(
            ok=equivalent,
            stdout=f"actual={a}; expected={b}; diff={diff}",
            error="" if equivalent else "expressions are not equivalent",
        )
    except Exception as exc:
        return ExecResult(ok=False, error=f"parse/eval error: {exc}")


def check_z3(z3_code: str, expected: str = "sat", *,
             timeout_s: float = DEFAULT_TIMEOUT_S,
             python_exe: Optional[str] = None) -> ExecResult:
    """Run Z3 code in subprocess; expects last ``s`` to be a Solver.

    The script prints ``s.check()`` (sat|unsat|unknown). Compared
    case-insensitively to ``expected``.
    """
    expected_lower = expected.strip().lower()
    if expected_lower not in {"sat", "unsat", "unknown"}:
        return ExecResult(ok=False,
                          error=f"bad expected={expected!r} "
                                "(want sat|unsat|unknown)")
    # User code must land at module top-level, NOT inside the import
    # try/except. Build the wrapper line-by-line at zero indent.
    wrapped = (
        "import sys\n"
        "try:\n"
        "    from z3 import *  # noqa\n"
        "except ImportError:\n"
        "    print('Z3_MISSING', file=sys.stderr); raise SystemExit(2)\n"
        + z3_code.rstrip() + "\n"
        "if 's' in dir() and isinstance(s, Solver):\n"
        "    print(str(s.check()).strip().lower())\n"
        "else:\n"
        "    print('NO_SOLVER', file=sys.stderr); raise SystemExit(3)\n"
    )
    res = run_python(wrapped, timeout_s=timeout_s, python_exe=python_exe)
    if not res.ok:
        if "Z3_MISSING" in res.stderr:
            return ExecResult(ok=False, error="z3-solver not installed")
        if "NO_SOLVER" in res.stderr:
            return ExecResult(ok=False,
                              error="z3 script must define `s = Solver(...)`")
        return res
    actual = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    matched = actual == expected_lower
    return ExecResult(
        ok=matched,
        stdout=actual,
        error="" if matched else f"got {actual!r}, expected {expected_lower!r}",
    )


# ── Critic ──────────────────────────────────────────────────────────
class SymbolicCritic:
    """Ground-truth Critic. Implements the foresight ``Critic`` Protocol.

    Steps without any validation hint are silently skipped — this critic
    is *additive* and intended to run alongside ``HeuristicCritic`` and
    ``OllamaCritic``. A plan with zero validatable steps yields a clean
    Critique with no risks.
    """

    def __init__(self, *,
                 default_timeout_s: float = DEFAULT_TIMEOUT_S,
                 python_exe: Optional[str] = None,
                 # injectable runners for tests / sandboxing:
                 python_runner=run_python,
                 sympy_runner=check_sympy_equivalence,
                 z3_runner=check_z3) -> None:
        self.default_timeout_s = default_timeout_s
        self.python_exe = python_exe
        self._py = python_runner
        self._sym = sympy_runner
        self._z3 = z3_runner

    # ── Critic Protocol ─────────────────────────────────────────
    def critique(self, plan: Plan, *,
                 world: dict | None = None) -> Critique:
        risks: list[Risk] = []
        validated = 0
        passed = 0

        for i, step in enumerate(plan.steps, 1):
            timeout_s = float(step.args.get("validate_timeout_s",
                                            self.default_timeout_s))
            for risk, did_validate, did_pass in self._validate_step(
                    step, i, timeout_s):
                if did_validate:
                    validated += 1
                    if did_pass:
                        passed += 1
                if risk is not None:
                    risks.append(risk)

        if validated == 0:
            summary = ("symbolic: no validatable claims in plan "
                       "(no python_code/sympy_expr/z3_code keys)")
        else:
            summary = (f"symbolic: {passed}/{validated} validations passed")

        return Critique(
            risks=risks,
            summary=summary,
            raw_response="",
            model=MODEL_NAME,
        )

    # ── per-step dispatch ──────────────────────────────────────
    def _validate_step(self, step: Step, idx: int, timeout_s: float):
        """Yield (risk_or_none, did_validate, did_pass) tuples."""
        if "python_code" in step.args:
            res = self._py(step.args["python_code"], timeout_s=timeout_s,
                           python_exe=self.python_exe)
            yield (
                None if res.ok else Risk(
                    severity=RiskSeverity.CRITICAL,
                    title=f"step {idx}: python_code failed validation",
                    detail=(res.error or res.stderr or "non-zero exit")[:400],
                    affects_step=idx,
                    mitigation="Fix the snippet so it runs cleanly under "
                               "`python -I -c …`.",
                ),
                True, res.ok,
            )

        if "sympy_expr" in step.args:
            expected = str(step.args.get("sympy_expected", ""))
            if not expected:
                yield (Risk(
                    severity=RiskSeverity.HIGH,
                    title=f"step {idx}: sympy_expr without sympy_expected",
                    detail="Cannot validate equivalence without the target.",
                    affects_step=idx,
                    mitigation="Set step.args['sympy_expected'].",
                ), False, False)
            else:
                res = self._sym(str(step.args["sympy_expr"]), expected)
                yield (
                    None if res.ok else Risk(
                        severity=RiskSeverity.CRITICAL,
                        title=f"step {idx}: sympy expression mismatch",
                        detail=(res.error or res.stdout)[:400],
                        affects_step=idx,
                        mitigation="Ensure the expression is algebraically "
                                   "equal to the expected value.",
                    ),
                    True, res.ok,
                )

        if "z3_code" in step.args:
            expected = str(step.args.get("z3_expected", "sat"))
            res = self._z3(str(step.args["z3_code"]), expected,
                           timeout_s=timeout_s, python_exe=self.python_exe)
            yield (
                None if res.ok else Risk(
                    severity=RiskSeverity.CRITICAL,
                    title=f"step {idx}: z3 verdict mismatch",
                    detail=(res.error or res.stdout)[:400],
                    affects_step=idx,
                    mitigation="Adjust constraints so solver returns "
                               f"{expected!r}.",
                ),
                True, res.ok,
            )
