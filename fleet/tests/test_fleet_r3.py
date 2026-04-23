"""R3 — query/aggregation API + alert engine."""
from __future__ import annotations

import json
import time

import pytest

from fleet import (
    Alert, AlertEngine, Event, PercentileRule, Query, RateRule, RatioRule,
    SeverityRule, SilenceRule, Store,
)
from fleet.cli import build_parser


# ── helpers ────────────────────────────────────────────────────
def _seed(store: Store, *, kind: str, n: int, base_ts: float,
          step_s: float = 0.01, agent: str = "bot-1",
          severity: str = "info", attrs: dict | None = None) -> None:
    """Insert n events ending AT base_ts (so they are all <= base_ts)."""
    for i in range(n):
        store.insert_event(Event(
            agent_id=agent, kind=kind, severity=severity,
            ts=base_ts - (n - 1 - i) * step_s, attrs=dict(attrs or {}),
        ))
    store.upsert_agent(agent, base_ts)


# ── Query primitives ──────────────────────────────────────────
def test_query_rate_and_count_in_window():
    s = Store(":memory:")
    now = 10_000.0
    _seed(s, kind="arsenal.deny", n=10, base_ts=now - 5)   # last 5s
    _seed(s, kind="arsenal.deny", n=4,  base_ts=now - 100) # outside

    q = Query(s)
    assert q.count(kind="arsenal.deny", window_s=10, now=now) == 10
    assert q.rate(kind="arsenal.deny",  window_s=10, now=now) == pytest.approx(1.0)
    # outside-window events visible without window filter
    assert q.count(kind="arsenal.deny") == 14


def test_query_latency_percentiles_and_stats():
    s = Store(":memory:")
    now = 5_000.0
    durations = [10, 12, 15, 20, 25, 30, 50, 80, 120, 500]
    for i, d in enumerate(durations):
        s.insert_event(Event(
            agent_id="bot", kind="foresight.verdict",
            ts=now - 100 + i, attrs={"duration_ms": d, "verdict": "allow"},
        ))
    q = Query(s)
    p = q.latency_percentiles(kind="foresight.verdict",
                              attr_key="duration_ms")
    assert p.n == 10
    assert p.p50 == pytest.approx(27.5)   # median of sorted
    assert p.p95 >= 120
    assert p.max == 500.0

    stats = q.numeric_stats(kind="foresight.verdict", attr_key="duration_ms")
    assert stats.n == 10
    assert stats.sum == sum(durations)
    assert stats.min == 10.0 and stats.max == 500.0


def test_query_top_n_group_by_and_histogram():
    s = Store(":memory:")
    now = 2_000.0
    for tool, n in [("transfer_funds", 7), ("send_email", 3), ("nuke_db", 1)]:
        for _ in range(n):
            s.insert_event(Event(agent_id="a", kind="arsenal.deny", ts=now,
                                 attrs={"tool": tool, "amount_gbp": 50.0}))

    q = Query(s)
    top = q.top_n(kind="arsenal.deny", attr_key="tool", n=2)
    assert top == [("transfer_funds", 7), ("send_email", 3)]

    grp = q.group_by(kind="arsenal.deny", attr_key="tool")
    assert grp == {"transfer_funds": 7, "send_email": 3, "nuke_db": 1}

    hist = q.histogram(kind="arsenal.deny", attr_key="amount_gbp",
                       buckets=[10.0, 100.0, 1000.0])
    # 11 events, all amount=50 → fall into <=100.0 bucket
    assert hist["<=100.0"] == 11
    assert hist["<=10.0"] == 0
    assert hist[">1000.0"] == 0


def test_query_time_series_buckets():
    s = Store(":memory:")
    base = 1_000.0
    # 3 in bucket 0, 0 in bucket 1, 5 in bucket 2
    for t in [base + 1, base + 2, base + 3]:
        s.insert_event(Event(agent_id="a", kind="x", ts=t))
    for t in [base + 21, base + 22, base + 23, base + 24, base + 25]:
        s.insert_event(Event(agent_id="a", kind="x", ts=t))

    q = Query(s)
    series = q.time_series(since=base, until=base + 30, bucket_s=10.0,
                           kind="x")
    assert [c for _, c in series] == [3, 0, 5]
    assert series[0][0] == base


def test_query_ratio_and_deny_allow():
    s = Store(":memory:")
    now = 3_000.0
    _seed(s, kind="arsenal.deny",  n=3,  base_ts=now - 5)
    _seed(s, kind="arsenal.allow", n=7,  base_ts=now - 5)

    q = Query(s)
    assert q.deny_allow_ratio(window_s=60, now=now) == pytest.approx(0.3)
    assert q.ratio(num_kind="arsenal.deny",
                   denom_kinds=("arsenal.deny", "arsenal.allow"),
                   window_s=60, now=now) == pytest.approx(0.3)
    # Empty denominator → 0.0
    assert q.ratio(num_kind="arsenal.deny",
                   denom_kinds=("nope.kind",),
                   window_s=60, now=now) == 0.0


# ── Alert rules ────────────────────────────────────────────────
def test_rate_rule_fires_above_threshold_and_silent_below():
    s = Store(":memory:")
    now = 6_000.0
    _seed(s, kind="arsenal.deny", n=12, base_ts=now - 5)   # 12 in 60s

    fire = RateRule(name="deny_spike", kind="arsenal.deny",
                    threshold=0.1, window_s=60, op=">=").evaluate(s, now=now)
    assert fire is not None and fire.value == pytest.approx(0.2)
    assert fire.severity == "warn"

    quiet = RateRule(name="deny_spike", kind="arsenal.deny",
                     threshold=10.0, window_s=60, op=">=").evaluate(s, now=now)
    assert quiet is None


def test_ratio_rule_respects_min_denominator():
    s = Store(":memory:")
    now = 7_000.0
    _seed(s, kind="arsenal.deny",  n=2, base_ts=now - 5)
    _seed(s, kind="arsenal.allow", n=1, base_ts=now - 5)

    # min_denominator=10, total=3 → no fire even though ratio is 0.66
    r = RatioRule(name="rr", num_kind="arsenal.deny",
                  denom_kinds=["arsenal.deny", "arsenal.allow"],
                  threshold=0.5, window_s=60, op=">=",
                  min_denominator=10).evaluate(s, now=now)
    assert r is None

    # min_denominator=1 → fires
    r2 = RatioRule(name="rr", num_kind="arsenal.deny",
                   denom_kinds=["arsenal.deny", "arsenal.allow"],
                   threshold=0.5, window_s=60, op=">=",
                   min_denominator=1).evaluate(s, now=now)
    assert r2 is not None
    assert r2.value == pytest.approx(2 / 3)


def test_percentile_rule_requires_min_samples():
    s = Store(":memory:")
    now = 4_000.0
    for d in [10, 20, 30]:
        s.insert_event(Event(agent_id="a", kind="foresight.verdict",
                             ts=now - 1, attrs={"duration_ms": d}))
    # 3 samples < default min_samples=5 → silent
    r = PercentileRule(name="slow", kind="foresight.verdict",
                       attr_key="duration_ms", threshold=15.0,
                       percentile=95).evaluate(s, now=now)
    assert r is None

    for d in [40, 50, 100, 200]:
        s.insert_event(Event(agent_id="a", kind="foresight.verdict",
                             ts=now - 1, attrs={"duration_ms": d}))
    r2 = PercentileRule(name="slow", kind="foresight.verdict",
                        attr_key="duration_ms", threshold=15.0,
                        percentile=95).evaluate(s, now=now)
    assert r2 is not None
    assert r2.value >= 100.0


def test_silence_rule_fires_when_agent_dark():
    s = Store(":memory:")
    now = 8_000.0
    s.upsert_agent("bot-1", ts=now - 1000)   # last seen 1000s ago
    s.upsert_agent("bot-2", ts=now - 10)     # fresh

    r = SilenceRule(name="dark", max_silence_s=300).evaluate(s, now=now)
    assert r is not None
    assert r.attrs["agent_id"] == "bot-1"

    # Targeted at bot-2: not fired
    r2 = SilenceRule(name="dark", max_silence_s=300,
                     agent_id="bot-2").evaluate(s, now=now)
    assert r2 is None


def test_severity_rule_fires_on_critical():
    s = Store(":memory:")
    now = 9_000.0
    _seed(s, kind="anything", n=2, base_ts=now - 5, severity="critical")
    r = SeverityRule(name="crit", severity="critical",
                     min_count=1, window_s=60).evaluate(s, now=now)
    assert r is not None
    assert r.value == 2.0
    assert r.severity == "critical"


def test_alert_engine_runs_multiple_rules_and_serialises():
    s = Store(":memory:")
    now = 11_000.0
    _seed(s, kind="arsenal.deny",  n=10, base_ts=now - 5)
    _seed(s, kind="arsenal.allow", n=2,  base_ts=now - 5)
    s.upsert_agent("bot-1", ts=now - 999)

    eng = AlertEngine([
        RateRule(name="deny_spike", kind="arsenal.deny",
                 threshold=0.05, window_s=60),
        RatioRule(name="refusal_high", num_kind="arsenal.deny",
                  denom_kinds=["arsenal.deny", "arsenal.allow"],
                  threshold=0.5, window_s=60, min_denominator=5),
        SilenceRule(name="dark", max_silence_s=300),
        # quiet rule:
        RateRule(name="never_fires", kind="arsenal.allow",
                 threshold=99999, window_s=60),
    ])
    fired = eng.evaluate(s, now=now)
    names = {a.rule for a in fired}
    assert names == {"deny_spike", "refusal_high", "dark"}
    # JSON-safe
    blob = json.dumps([a.to_dict() for a in fired], default=float)
    assert "deny_spike" in blob


# ── CLI integration ───────────────────────────────────────────
def test_cli_query_rate(tmp_path, capsys):
    db = tmp_path / "fleet.sqlite"
    s = Store(db)
    now = time.time()
    _seed(s, kind="arsenal.deny", n=5, base_ts=now - 2)
    s.close()

    parser = build_parser()
    args = parser.parse_args([
        "--db", str(db),
        "query", "count",
        "--kind", "arsenal.deny",
    ])
    rc = args.func(args)
    captured = capsys.readouterr().out
    assert rc == 0
    out = json.loads(captured)
    assert out["count"] == 5


def test_cli_alerts_with_inline_rules_and_exit_code(tmp_path, capsys):
    db = tmp_path / "fleet.sqlite"
    s = Store(db)
    now = time.time()
    _seed(s, kind="arsenal.deny", n=20, base_ts=now - 2)
    s.close()

    parser = build_parser()
    args = parser.parse_args([
        "--db", str(db),
        "alerts",
        "--deny-rate", "0.01",
        "--window", "60",
        "--exit-nonzero-on-fire",
    ])
    rc = args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert rc == 4
    assert out["n_fired"] >= 1
    assert any(a["rule"] == "deny_spike" for a in out["alerts"])


def test_cli_alerts_rules_file(tmp_path, capsys):
    db = tmp_path / "fleet.sqlite"
    s = Store(db)
    now = time.time()
    s.upsert_agent("bot-x", ts=now - 999)
    s.close()

    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps([
        {"type": "silence", "name": "dark", "max_silence_s": 300},
    ]))

    parser = build_parser()
    args = parser.parse_args([
        "--db", str(db),
        "alerts", "--rules-file", str(rules_path),
    ])
    rc = args.func(args)
    out = json.loads(capsys.readouterr().out)
    assert rc == 0   # without --exit-nonzero-on-fire
    assert out["n_fired"] == 1
    assert out["alerts"][0]["rule"] == "dark"
