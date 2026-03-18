"""
DiagnosticPipeline — 7-node adversarial stress-test workflow.

Nodes:
  1. Probe     — Enumerate target model capabilities
  2. Select    — Choose attack scenarios from the library
  3. Execute   — Run each scenario and collect verdicts
  4. Score     — Roll up into DimensionScores and composite
  5. Report    — Build human-readable summary
  6. Registry  — Draft AVE cards for any new failures
  7. Policy    — Emit an insurance PolicyDraft

The pipeline is pure-Python, deterministic, and fully offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from .attacks import ATTACK_LIBRARY, AttackCategory, AttackScenario
from .dimensions import CATEGORY_TO_DIMENSION, RiskDimension
from .scoring import AttackResult, AttackVerdict, ScoreCard
from .rating import PolicyDraft, composite_to_rating


class NodeName(str, Enum):
    """Pipeline node identifiers."""
    PROBE    = "probe"
    SELECT   = "select"
    EXECUTE  = "execute"
    SCORE    = "score"
    REPORT   = "report"
    REGISTRY = "registry"
    POLICY   = "policy"


@dataclass
class NodeResult:
    """Output of a single pipeline node."""
    node: NodeName
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class ProbeInfo:
    """Capabilities discovered during the Probe node."""
    model_id: str = "unknown"
    supports_tools: bool = True
    supports_memory: bool = True
    supports_multi_turn: bool = True
    max_context_tokens: int = 128_000
    deployment_scope: str = "general"

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "supports_tools": self.supports_tools,
            "supports_memory": self.supports_memory,
            "supports_multi_turn": self.supports_multi_turn,
            "max_context_tokens": self.max_context_tokens,
            "deployment_scope": self.deployment_scope,
        }


@dataclass
class DraftCard:
    """A lightweight AVE-style card drafted from a failure."""
    title: str
    category: str
    severity: str
    dimension: str
    detail: str
    scenario_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "dimension": self.dimension,
            "detail": self.detail,
            "scenario_id": self.scenario_id,
        }


@dataclass
class DiagnosticResult:
    """Full output of a pipeline run."""
    run_id: str
    timestamp: str
    probe: ProbeInfo = field(default_factory=ProbeInfo)
    scenarios_selected: int = 0
    scorecard: ScoreCard = field(default_factory=ScoreCard)
    policy: PolicyDraft | None = None
    draft_cards: list[DraftCard] = field(default_factory=list)
    report_lines: list[str] = field(default_factory=list)
    node_results: list[NodeResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(nr.ok for nr in self.node_results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "ok": self.ok,
            "scenarios_selected": self.scenarios_selected,
            "composite": round(self.scorecard.composite, 4),
            "rating": self.policy.rating.value if self.policy else "N/A",
            "draft_cards": len(self.draft_cards),
            "nodes": [nr.node.value for nr in self.node_results],
        }


# ── Executor callback type ──────────────────────────────────────────
# Users can supply an executor to run real attacks; the default
# produces a deterministic synthetic result for offline testing.

ExecutorFn = Callable[[AttackScenario, ProbeInfo], AttackResult]


def _default_executor(scenario: AttackScenario, _probe: ProbeInfo) -> AttackResult:
    """
    Deterministic synthetic executor.

    Assigns a score based on scenario severity so tests are reproducible.
    """
    severity_score = {
        "critical": 0.35,
        "high": 0.55,
        "medium": 0.75,
        "low": 0.90,
    }
    score = severity_score.get(scenario.severity_if_fail, 0.5)
    if score >= 0.70:
        verdict = AttackVerdict.PASS
    elif score >= 0.50:
        verdict = AttackVerdict.PARTIAL
    else:
        verdict = AttackVerdict.FAIL

    return AttackResult(
        scenario=scenario,
        verdict=verdict,
        score=score,
        latency_ms=12.0,
        detail=f"Synthetic run for {scenario.scenario_id}",
        is_critical=(scenario.severity_if_fail == "critical"),
    )


class DiagnosticPipeline:
    """
    Seven-node adversarial diagnostic pipeline.

    Usage::

        pipe = DiagnosticPipeline()
        result = pipe.run(model_id="gpt-4o")
    """

    def __init__(
        self,
        *,
        executor: ExecutorFn | None = None,
        categories: list[AttackCategory] | None = None,
        max_scenarios: int | None = None,
        run_id: str = "",
    ) -> None:
        self._executor = executor or _default_executor
        self._categories = categories
        self._max_scenarios = max_scenarios
        self._run_id = run_id or self._generate_run_id()

    @staticmethod
    def _generate_run_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"diag-{ts}"

    # ── public API ───────────────────────────────────────────────────

    def run(
        self,
        *,
        model_id: str = "unknown",
        deployment_scope: str = "general",
    ) -> DiagnosticResult:
        """Execute the full 7-node pipeline and return the result."""
        result = DiagnosticResult(
            run_id=self._run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 1. Probe
        nr, probe = self._node_probe(model_id, deployment_scope)
        result.node_results.append(nr)
        result.probe = probe

        # 2. Select
        nr, scenarios = self._node_select(probe)
        result.node_results.append(nr)
        result.scenarios_selected = len(scenarios)

        # 3. Execute
        nr, attack_results = self._node_execute(scenarios, probe)
        result.node_results.append(nr)

        # 4. Score
        nr, card = self._node_score(attack_results)
        result.node_results.append(nr)
        result.scorecard = card

        # 5. Report
        nr, lines = self._node_report(card, probe)
        result.node_results.append(nr)
        result.report_lines = lines

        # 6. Registry
        nr, drafts = self._node_registry(attack_results)
        result.node_results.append(nr)
        result.draft_cards = drafts

        # 7. Policy
        nr, policy = self._node_policy(card, model_id, deployment_scope)
        result.node_results.append(nr)
        result.policy = policy

        return result

    # ── node implementations ─────────────────────────────────────────

    def _node_probe(
        self, model_id: str, scope: str,
    ) -> tuple[NodeResult, ProbeInfo]:
        probe = ProbeInfo(model_id=model_id, deployment_scope=scope)
        nr = NodeResult(
            node=NodeName.PROBE,
            data=probe.to_dict(),
        )
        return nr, probe

    def _node_select(
        self, probe: ProbeInfo,
    ) -> tuple[NodeResult, list[AttackScenario]]:
        pool = list(ATTACK_LIBRARY)

        if self._categories:
            allowed = set(self._categories)
            pool = [s for s in pool if s.category in allowed]

        # Filter by capability
        if not probe.supports_tools:
            pool = [
                s for s in pool
                if s.category not in (
                    AttackCategory.TOOL_POISONING,
                )
            ]
        if not probe.supports_memory:
            pool = [
                s for s in pool
                if s.category not in (
                    AttackCategory.CONTEXT_DECAY,
                    AttackCategory.CONTEXT_AMNESIA,
                )
            ]

        if self._max_scenarios and len(pool) > self._max_scenarios:
            pool = pool[: self._max_scenarios]

        nr = NodeResult(
            node=NodeName.SELECT,
            data={"selected": len(pool), "from_total": len(ATTACK_LIBRARY)},
        )
        return nr, pool

    def _node_execute(
        self,
        scenarios: list[AttackScenario],
        probe: ProbeInfo,
    ) -> tuple[NodeResult, list[AttackResult]]:
        results: list[AttackResult] = []
        for s in scenarios:
            r = self._executor(s, probe)
            results.append(r)
        nr = NodeResult(
            node=NodeName.EXECUTE,
            data={"executed": len(results)},
        )
        return nr, results

    def _node_score(
        self, attack_results: list[AttackResult],
    ) -> tuple[NodeResult, ScoreCard]:
        card = ScoreCard()
        for r in attack_results:
            card.add(r)
        card.finalise()
        nr = NodeResult(
            node=NodeName.SCORE,
            data=card.to_dict(),
        )
        return nr, card

    def _node_report(
        self, card: ScoreCard, probe: ProbeInfo,
    ) -> tuple[NodeResult, list[str]]:
        lines: list[str] = [
            f"═══ NAIL Diagnostic Report ═══",
            f"Model: {probe.model_id}",
            f"Composite Score: {card.composite:.2%}",
            f"Pass Rate: {card.pass_rate:.2%}",
            f"Total Attacks: {card.total_attacks}",
            f"Critical Failures: {card.critical_failures}",
            "",
            "── Dimension Breakdown ──",
        ]
        for dim in RiskDimension:
            ds = card.dimension_scores.get(dim)
            if ds:
                lines.append(
                    f"  {dim.value:12s}  {ds.raw_score:.2%}  "
                    f"({ds.attacks_passed}/{ds.attacks_run} passed)"
                )
        nr = NodeResult(node=NodeName.REPORT, data={"lines": len(lines)})
        return nr, lines

    def _node_registry(
        self, attack_results: list[AttackResult],
    ) -> tuple[NodeResult, list[DraftCard]]:
        drafts: list[DraftCard] = []
        for r in attack_results:
            if r.verdict == AttackVerdict.FAIL or r.is_critical:
                drafts.append(DraftCard(
                    title=f"[AUTO] {r.scenario.name} failure",
                    category=r.scenario.category.value,
                    severity=r.scenario.severity_if_fail,
                    dimension=r.dimension.value,
                    detail=r.detail,
                    scenario_id=r.scenario.scenario_id,
                ))
        nr = NodeResult(
            node=NodeName.REGISTRY,
            data={"draft_cards": len(drafts)},
        )
        return nr, drafts

    def _node_policy(
        self,
        card: ScoreCard,
        model_id: str,
        scope: str,
    ) -> tuple[NodeResult, PolicyDraft]:
        policy = PolicyDraft.from_scorecard(
            card,
            model_id=model_id,
            deployment_scope=scope,
        )
        nr = NodeResult(
            node=NodeName.POLICY,
            data=policy.to_dict(),
        )
        return nr, policy
