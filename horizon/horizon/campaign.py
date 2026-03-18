"""
Horizon Campaign Runner — orchestrates all three campaigns.

Provides a single entry point to run Horizon 1 (GA), Horizon 2
(Heterogeneous), and Horizon 3 (Polyglot) campaigns, collecting
results into a unified summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .ga import Population, ThresholdGA
from .heterogeneous import GeneralisationResult, HeterogeneousCampaign
from .polyglot import PolyglotCampaign, PolyglotResult


@dataclass
class CampaignResult:
    """Result of a single horizon campaign."""
    horizon: int               # 1, 2, or 3
    name: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "name": self.name,
            "ok": self.ok,
            "data": self.data,
        }


@dataclass
class HorizonSummary:
    """Combined results from all horizon campaigns."""
    run_id: str
    timestamp: str
    campaigns: list[CampaignResult] = field(default_factory=list)

    # Horizon 1 output
    ga_final_population: Population | None = None
    ga_champion_fitness: float = 0.0

    # Horizon 2 output
    generalisation_results: list[GeneralisationResult] = field(
        default_factory=list,
    )
    cross_arch_block_rate: float = 0.0

    # Horizon 3 output
    polyglot_results: list[PolyglotResult] = field(default_factory=list)
    avg_evasion_rate: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.campaigns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "ok": self.ok,
            "campaigns_run": len(self.campaigns),
            "ga_champion_fitness": round(self.ga_champion_fitness, 4),
            "cross_arch_block_rate": round(self.cross_arch_block_rate, 4),
            "avg_evasion_rate": round(self.avg_evasion_rate, 4),
        }


class HorizonRunner:
    """
    Orchestrate all three Horizon campaigns.

    Usage::

        runner = HorizonRunner()
        summary = runner.run_all()
        print(summary.to_dict())
    """

    def __init__(
        self,
        *,
        ga_kwargs: dict[str, Any] | None = None,
        hetero_kwargs: dict[str, Any] | None = None,
        polyglot_kwargs: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> None:
        self._ga_kwargs = ga_kwargs or {}
        self._hetero_kwargs = hetero_kwargs or {}
        self._polyglot_kwargs = polyglot_kwargs or {}
        self._run_id = run_id or self._auto_id()

    @staticmethod
    def _auto_id() -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        return f"horizon-{ts}"

    # ── public API ───────────────────────────────────────────────────

    def run_all(self) -> HorizonSummary:
        """Execute all three Horizon campaigns sequentially."""
        summary = HorizonSummary(
            run_id=self._run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Horizon 1: GA threshold optimisation
        cr1, pop = self._run_ga()
        summary.campaigns.append(cr1)
        summary.ga_final_population = pop
        summary.ga_champion_fitness = pop.best_fitness if pop else 0.0

        # Horizon 2: Heterogeneous model-vs-model
        cr2, gen_results = self._run_heterogeneous()
        summary.campaigns.append(cr2)
        summary.generalisation_results = gen_results
        if gen_results:
            summary.cross_arch_block_rate = sum(
                g.block_rate for g in gen_results
            ) / len(gen_results)

        # Horizon 3: Polyglot obfuscation
        cr3, poly_results = self._run_polyglot()
        summary.campaigns.append(cr3)
        summary.polyglot_results = poly_results
        if poly_results:
            summary.avg_evasion_rate = sum(
                p.evasion_rate for p in poly_results
            ) / len(poly_results)

        return summary

    def run_ga_only(self) -> tuple[CampaignResult, Population]:
        """Run only Horizon 1."""
        return self._run_ga()

    def run_heterogeneous_only(
        self,
    ) -> tuple[CampaignResult, list[GeneralisationResult]]:
        """Run only Horizon 2."""
        return self._run_heterogeneous()

    def run_polyglot_only(
        self,
    ) -> tuple[CampaignResult, list[PolyglotResult]]:
        """Run only Horizon 3."""
        return self._run_polyglot()

    # ── internals ────────────────────────────────────────────────────

    def _run_ga(self) -> tuple[CampaignResult, Population]:
        ga = ThresholdGA(**self._ga_kwargs)
        pop = ga.run()
        cr = CampaignResult(
            horizon=1,
            name="Threshold Optimization GA",
            ok=True,
            data={
                "generations": pop.generation,
                "population_size": len(pop.genomes),
                "best_fitness": round(pop.best_fitness, 4),
                "champion_id": pop.champion.genome_id if pop.champion else None,
                "champion_thresholds": (
                    {k: round(v, 4) for k, v in pop.champion.thresholds.items()}
                    if pop.champion else {}
                ),
            },
        )
        return cr, pop

    def _run_heterogeneous(
        self,
    ) -> tuple[CampaignResult, list[GeneralisationResult]]:
        campaign = HeterogeneousCampaign(**self._hetero_kwargs)
        results = campaign.run()

        avg_block = (
            sum(r.block_rate for r in results) / len(results)
            if results else 0.0
        )
        cr = CampaignResult(
            horizon=2,
            name="Heterogeneous Model-vs-Model",
            ok=True,
            data={
                "attackers_tested": len(results),
                "avg_block_rate": round(avg_block, 4),
                "results": [r.to_dict() for r in results],
            },
        )
        return cr, results

    def _run_polyglot(
        self,
    ) -> tuple[CampaignResult, list[PolyglotResult]]:
        campaign = PolyglotCampaign(**self._polyglot_kwargs)
        results = campaign.run()

        avg_evasion = (
            sum(r.evasion_rate for r in results) / len(results)
            if results else 0.0
        )
        cr = CampaignResult(
            horizon=3,
            name="Polyglot / Obfuscation Protocol",
            ok=True,
            data={
                "codebooks_tested": len(results),
                "avg_evasion_rate": round(avg_evasion, 4),
                "results": [r.to_dict() for r in results],
            },
        )
        return cr, results
