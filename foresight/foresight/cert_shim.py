"""Cert-pipeline shim for foresight.

Bridges a corpus of *safe* plans through a Critic and produces the iterable
of Critiques that ``nail_harness.cert_collectors.collect_safety_metrics``
expects as ``foresight_critiques_safe`` for computing
``plan_critique_reject_rate_safe``.

Why a shim?
-----------
``collect_safety_metrics`` is intentionally critic-agnostic — it just counts
how many critiques came back as REJECT against a curated *safe* corpus. The
shim packages the "load corpus → run critic → return list" loop so callers
(CLIs, demos, integration tests) don't have to re-implement it.

Default critic is :class:`HeuristicCritic` because it is hermetic and fast;
swap in :class:`OllamaCritic` or :class:`SymbolicCritic` for higher-fidelity
runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .critic import Critic, HeuristicCritic
from .critique import Critique
from .plan import Plan


def _load_plans(source: Iterable[Plan] | str | Path) -> list[Plan]:
    """Coerce a corpus source (iterable / path to JSON / path to JSONL) to plans."""
    if isinstance(source, (str, Path)):
        p = Path(source)
        text = p.read_text(encoding="utf-8")
        # Try JSON-array first, fall back to JSONL.
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [Plan.from_dict(d) for d in data]
        except json.JSONDecodeError:
            pass
        plans: list[Plan] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            plans.append(Plan.from_dict(json.loads(line)))
        return plans
    return list(source)


def run_for_cert(
    plans: Iterable[Plan] | str | Path,
    *,
    critic: Optional[Critic] = None,
    world: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Critique a *safe* plan corpus and shape the result for the collector.

    Returns a dict with::

        {
          "foresight_critiques_safe": list[Critique],  # for collector
          "n_plans":                  int,
          "n_rejects":                int,
          "reject_rate":              float,
          "critic_model":             str,
        }

    Drop ``foresight_critiques_safe`` straight into
    :func:`nail_harness.cert_collectors.collect_safety_metrics`.
    """
    critic = critic or HeuristicCritic()
    loaded = _load_plans(plans)
    crits: list[Critique] = [critic.critique(p, world=world) for p in loaded]
    rejects = sum(1 for c in crits if c.verdict().value == "reject")
    n = len(crits)
    return {
        "foresight_critiques_safe": crits,
        "n_plans": n,
        "n_rejects": rejects,
        "reject_rate": (rejects / n) if n else 0.0,
        "critic_model": getattr(critic, "__class__", type(critic)).__name__,
    }


__all__ = ["run_for_cert"]
