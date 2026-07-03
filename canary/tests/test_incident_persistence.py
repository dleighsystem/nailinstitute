"""IncidentLog durability: JSONL persistence survives a restart."""

from canary.incident import Incident, IncidentLog, Severity
from canary.trapwire import ThreatSignal, TripResult


class _Agent:
    """Minimal stand-in for a CanaryAgent for capture()."""
    agent_id = "canary-1"
    name = "support-bot"

    def export_conversation(self):
        return [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]


def _trip():
    return TripResult(
        triggered=True,
        signals=[ThreatSignal.PROMPT_INJECTION],
        matched_rules=["ignore previous instructions"],
        confidence=0.9,
    )


def test_in_memory_default_is_unchanged():
    log = IncidentLog()
    log.capture(_Agent(), _trip(), severity=Severity.HIGH)
    assert len(log) == 1


def test_incident_round_trips_through_dict():
    log = IncidentLog()
    inc = log.capture(_Agent(), _trip(), severity=Severity.HIGH)
    clone = Incident.from_dict(inc.to_dict())
    assert clone.incident_id == inc.incident_id
    assert clone.severity == Severity.HIGH
    assert [s.value for s in clone.trip_result.signals] == ["prompt_injection"]
    assert len(clone.conversation) == len(inc.conversation)   # len preserved for cards


def test_incidents_persist_across_restart(tmp_path):
    path = tmp_path / "incidents.jsonl"
    log = IncidentLog(path)
    log.capture(_Agent(), _trip(), severity=Severity.CRITICAL)
    log.capture(_Agent(), _trip(), severity=Severity.HIGH)

    # New process: a fresh IncidentLog on the same file reloads the history.
    reopened = IncidentLog(path)
    assert len(reopened) == 2
    assert reopened.count()["total"] == 2
    assert {i.severity for i in reopened.all_incidents()} == {Severity.CRITICAL, Severity.HIGH}


def test_flywheel_survives_restart(tmp_path):
    path = tmp_path / "incidents.jsonl"
    IncidentLog(path).capture(_Agent(), _trip(), severity=Severity.CRITICAL)

    cards = IncidentLog(path).draft_ave_cards()
    assert len(cards) == 1
    assert cards[0]["category"] == "injection"        # from the persisted signal
    assert cards[0]["severity"] == "critical"


def test_corrupt_line_is_skipped(tmp_path):
    path = tmp_path / "incidents.jsonl"
    IncidentLog(path).capture(_Agent(), _trip(), severity=Severity.HIGH)
    with path.open("a") as fh:
        fh.write("{not valid json\n")
    assert len(IncidentLog(path)) == 1   # good record kept, junk skipped
