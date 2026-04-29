import pytest
from nail_monitor.flight_recorder import FlightRecorder, FlightRecorderError
from nail_monitor.types import Alert, PathologyType, Severity

def test_flight_recorder_initializes():
    recorder = FlightRecorder("test-bot")
    assert len(recorder.chain) == 1
    assert recorder.chain[0].event_type == "SESSION_START"
    assert recorder.verify_integrity()

def test_log_action_maintains_integrity():
    recorder = FlightRecorder("test-bot")
    hash_1 = recorder.log_thought("What is 2+2?", "4", 100)
    hash_2 = recorder.log_action("calculator", {"expr": "2+2"})
    hash_3 = recorder.log_observation("4", "calculator")

    assert len(recorder.chain) == 4
    assert recorder.chain[-1].prev_hash == recorder.chain[-2].hash
    assert hash_3 == recorder.chain[-1].hash
    assert recorder.verify_integrity()

def test_log_alert_integration():
    recorder = FlightRecorder("test-bot")
    alert = Alert(
        detector="TestDetector",
        pathology=PathologyType.OVERSIGHT_FAILURE,
        severity=Severity.CRITICAL,
        message="Failure test.",
        metric_value=0.0,
        threshold=0.0,
        metadata={},
        timestamp=0.0
    )
    recorder.log_alert(alert)
    assert recorder.chain[-1].event_type == "MONITOR_ALERT"
    assert recorder.verify_integrity()

def test_tampering_detected():
    recorder = FlightRecorder("test-bot")
    recorder.log_thought("hello", "world")
    recorder.log_action("tool", {"arg": 1})

    # Simulate malicious actor altering log history to hide a bad tool call
    recorder.chain[2].payload["arguments"] = {"arg": "hidden malicious command"}

    with pytest.raises(FlightRecorderError, match="invalid for its contents"):
        recorder.verify_integrity()

def test_hash_chain_broken():
    recorder = FlightRecorder("test-bot")
    recorder.log_thought("hello", "world")
    recorder.log_action("tool", {"arg": 1})
    
    # Simulate a log entry deletion
    del recorder.chain[1]

    with pytest.raises(FlightRecorderError, match="does not match prior hash"):
        recorder.verify_integrity()
