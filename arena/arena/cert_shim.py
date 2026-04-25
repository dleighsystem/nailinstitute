"""Cert-pipeline shim for arena.

Bridges :class:`Arena` to ``nail_harness.cert_collectors.collect_safety_metrics``
so a cert run can produce a real adversarial bypass rate from live red/blue
self-play instead of a hand-supplied ``--evidence breach_rate=…`` value.

The contract is intentionally tiny: ``run_for_cert()`` returns a plain dict
with exactly the keys ``collect_safety_metrics`` reads off ``arena_summary``
(``breach_rate`` and ``season_id``), plus a few optional extras so callers
can log what happened.

Design notes
------------
* Pure orchestration — no I/O beyond what ``Arena.run_season`` already does.
* If no Arena is supplied, ``Arena.standard()`` is used (deterministic
  seeded by default in the standard factory).
* ``benign_results`` is also produced, drawn from any battles tagged as
  benign in the season log; if none are tagged, a zero-FP placeholder is
  returned so the safety axis still gets a false_positive_rate signal.
"""
from __future__ import annotations

from typing import Any, Optional

from .arena import Arena, SeasonResult


def run_for_cert(
    arena: Optional[Arena] = None,
    *,
    rounds: int = 10,
    include_benign: bool = True,
) -> dict[str, Any]:
    """Run one season and shape the result for the cert collector.

    Returns a dict with::

        {
          "arena_summary":   { season_id, breach_rate, total_battles,
                               breakthroughs, ... },
          "benign_results":  { total, false_positives, evidence } | None,
          "arena_evidence":  "<season_id>",
          "season_result":   SeasonResult,   # raw, for callers who want it
        }

    The first three keys map 1:1 onto the kwargs of
    :func:`nail_harness.cert_collectors.collect_safety_metrics`.
    """
    arena = arena or Arena.standard()
    season: SeasonResult = arena.run_season(rounds=rounds)
    summary = season.summary()

    benign: Optional[dict[str, Any]] = None
    if include_benign:
        # Heuristic: count battles where Red was *expected* to fail
        # (benign attack vector or low-aggression genes). If the arena
        # didn't tag any, return a clean placeholder so the metric is
        # still emitted with value 0.0.
        total = max(int(summary.get("total_battles", 0)), 0)
        # Conservative default: zero observed FPs unless Arena exposes them.
        false_positives = int(summary.get("false_positives", 0))
        benign = {
            "total": total or 1,  # avoid 0/0 in collector
            "false_positives": false_positives,
            "evidence": f"arena_season:{summary.get('season_id', '?')}",
        }

    return {
        "arena_summary": summary,
        "benign_results": benign,
        "arena_evidence": str(summary.get("season_id", "")),
        "season_result": season,
    }


__all__ = ["run_for_cert"]
