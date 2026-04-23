"""Critic protocol + non-LLM implementations.

A ``Critic`` takes (plan, world) and returns a ``Critique``. Multiple
implementations exist so the rest of the stack can be tested without
hitting Ollama:

* ``HeuristicCritic`` — pure stdlib rules; useful as a fallback when LLM
  is unavailable (e.g. CI without GPU).
* ``MockCritic``     — returns canned risks for unit tests.
* ``OllamaCritic``   — calls a local Ollama model (default ``nail-reason:v3.1``)
  and parses its JSON. Lives in ``ollama_critic.py``.
"""
from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from ._telemetry import default_agent_id, telemetry_emit
from .critique import Critique, Risk, RiskSeverity
from .plan import Plan


@runtime_checkable
class Critic(Protocol):
    def critique(self, plan: Plan, *,
                 world: dict | None = None) -> Critique: ...


# ── heuristic ────────────────────────────────────────────────────────
class HeuristicCritic:
    """Cheap, deterministic risk detector. Looks for:

    * Money tools used with arguments above thresholds.
    * Same write-tool used multiple times in a single plan (idempotency
      smell).
    * 'send_external' or 'email.*' with attachments inferred from prior
      step output (data exfil pattern).
    * Plan length explosion.
    """

    DEFAULT_MONEY_TOOLS: tuple[str, ...] = (
        "refunds.issue", "payments.send", "transfers.create",
        "wire.send", "treasury.disburse",
    )
    DEFAULT_EXTERNAL_TOOLS: tuple[str, ...] = (
        "email.send", "slack.send", "webhook.post",
        "http.post", "sms.send",
    )
    MONEY_HARD_CAP_GBP = 500
    PLAN_LENGTH_WARN = 12

    def __init__(self, *,
                 money_tools: tuple[str, ...] = DEFAULT_MONEY_TOOLS,
                 external_tools: tuple[str, ...] = DEFAULT_EXTERNAL_TOOLS,
                 money_hard_cap_gbp: float = MONEY_HARD_CAP_GBP) -> None:
        self.money_tools = set(money_tools)
        self.external_tools = set(external_tools)
        self.money_hard_cap_gbp = money_hard_cap_gbp

    def critique(self, plan: Plan, *,
                 world: dict | None = None) -> Critique:
        risks: list[Risk] = []
        write_tool_counts: dict[str, int] = {}

        for i, step in enumerate(plan.steps, 1):
            # Money cap
            if step.tool in self.money_tools:
                amt = float(step.args.get("amount_gbp")
                            or step.args.get("amount") or 0)
                if amt > self.money_hard_cap_gbp:
                    risks.append(Risk(
                        severity=RiskSeverity.CRITICAL,
                        title=f"{step.tool} amount £{amt:g} exceeds hard cap "
                              f"£{self.money_hard_cap_gbp:g}",
                        detail="Single-call spend above hard policy cap.",
                        affects_step=i,
                        mitigation="Split into smaller transactions or "
                                   "escalate to human approval.",
                    ))
                elif amt > self.money_hard_cap_gbp * 0.4:
                    risks.append(Risk(
                        severity=RiskSeverity.HIGH,
                        title=f"{step.tool} amount £{amt:g} above warn band",
                        affects_step=i,
                        mitigation="Add holding policy; require confirmation.",
                    ))

            # Idempotency: same write-tool used multiple times
            if step.tool in self.money_tools or step.tool in self.external_tools:
                write_tool_counts[step.tool] = write_tool_counts.get(step.tool, 0) + 1

            # External + likely-attachment data
            if step.tool in self.external_tools:
                low = " ".join(str(v).lower() for v in step.args.values())
                if any(w in low for w in ("attachment", "all_records",
                                          "dump", "export", "csv")):
                    risks.append(Risk(
                        severity=RiskSeverity.HIGH,
                        title=f"possible data exfiltration via {step.tool}",
                        detail="External call references bulk/export terms.",
                        affects_step=i,
                        mitigation="Confirm recipient + payload size; "
                                   "rate-limit; require approval.",
                    ))

        # Idempotency tail
        for tool, n in write_tool_counts.items():
            if n > 1:
                risks.append(Risk(
                    severity=RiskSeverity.MEDIUM,
                    title=f"{tool} invoked {n}× in same plan",
                    detail="Repeated write may indicate retry-without-idempotency.",
                    mitigation="Use idempotency key or de-duplicate before commit.",
                ))

        # Plan-length smell
        if len(plan.steps) > self.PLAN_LENGTH_WARN:
            risks.append(Risk(
                severity=RiskSeverity.MEDIUM,
                title=f"plan has {len(plan.steps)} steps "
                      f"(>{self.PLAN_LENGTH_WARN})",
                mitigation="Decompose into sub-plans; checkpoint between.",
            ))

        # World-aware: budget exhaustion
        world = world or {}
        spent = float(world.get("today_refund_total_gbp", 0))
        proposed = sum(
            float(s.args.get("amount_gbp", 0))
            for s in plan.steps if s.tool in self.money_tools
        )
        daily_cap = float(world.get("daily_refund_cap_gbp", 1000))
        if spent + proposed > daily_cap:
            risks.append(Risk(
                severity=RiskSeverity.CRITICAL,
                title=f"plan would exceed daily cap "
                      f"(£{spent + proposed:g} > £{daily_cap:g})",
                mitigation="Defer until budget refresh or split across days.",
            ))

        c = Critique(
            risks=risks,
            summary=(f"{len(risks)} risk(s) found by heuristic critic"
                     if risks else "no heuristic risks identified"),
            model="heuristic",
        )
        _emit_critique(c, plan)
        return c


# ── mock ─────────────────────────────────────────────────────────────
class MockCritic:
    """Returns whatever the test feeds it. For unit tests only."""
    def __init__(self, critique: Critique) -> None:
        self._critique = critique
        self.calls: list[tuple[Plan, dict]] = []

    def critique(self, plan: Plan, *,
                 world: dict | None = None) -> Critique:
        self.calls.append((plan, dict(world or {})))
        return self._critique


# ── shared telemetry emit ────────────────────────────────────────────
def _emit_critique(c: Critique, plan: Plan) -> None:
    v = c.verdict()
    telemetry_emit(
        "foresight.verdict",
        agent_id=default_agent_id("foresight"),
        severity="warn" if v.value != "allow" else "info",
        attrs={
            "verdict": v.value,
            "risk": round(c.risk, 3),
            "max_severity": c.max_severity.value,
            "n_risks": len(c.risks),
            "n_steps": len(plan.steps),
            "goal": plan.goal[:200],
            "model": c.model,
        },
    )
