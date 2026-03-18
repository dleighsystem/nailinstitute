"""
Tests for the GLiNER PII Detector.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from integration.pii_detector import (
    PIIDetector,
    DetectionResult,
    LureLeakageResult,
    PIIEntity,
    PIIType,
    DetectorMode,
)


# A minimal lure stand-in for tests (avoids importing canary package)
@dataclass
class _FakeLure:
    value: str = ""
    tripwires: list[str] = field(default_factory=list)
    lure_type: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# BASIC DETECTION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPIIDetector:
    """Test the PIIDetector in mock mode."""

    def test_create(self):
        detector = PIIDetector()
        assert detector.mode == DetectorMode.MOCK

    def test_no_pii(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("Hello, how are you today?")
        assert isinstance(result, DetectionResult)
        assert result.pii_found is False
        assert result.entity_count == 0

    def test_detect_email(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("My email is john@example.com, please help.")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.EMAIL in found_types

    def test_detect_ssn(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("SSN: 123-45-6789")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.SSN in found_types

    def test_detect_credit_card(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("Card number 4111111111111111")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.CREDIT_CARD in found_types

    def test_detect_phone(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("Call me at (555) 123-4567.")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.PHONE in found_types

    def test_detect_ip_address(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("Server is at 192.168.1.100")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.IP_ADDRESS in found_types

    def test_detect_api_key(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect("api_key=sk-abc123def456ghi789jkl012mno345p")
        assert result.pii_found is True
        found_types = {e.entity_type for e in result.entities}
        assert PIIType.API_KEY in found_types

    def test_detect_multiple_pii(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        result = detector.detect(
            "Email: alice@corp.com, SSN: 111-22-3333, Phone: (800) 555-1212"
        )
        assert result.pii_found is True
        assert result.entity_count >= 3


# ═══════════════════════════════════════════════════════════════════════════
# LURE LEAKAGE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestLureLeakage:
    """Test canary lure leakage detection."""

    def test_no_leakage(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        lure = _FakeLure(value="DB_PASSWORD=fake-secret-xyz", tripwires=["fake-secret-xyz"])
        result = detector.check_lure_leakage(
            response_text="I can help you with your question.",
            lure=lure,
        )
        assert isinstance(result, LureLeakageResult)
        assert result.leaked is False

    def test_leakage_via_tripwire(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        lure = _FakeLure(value="fake-secret-xyz", tripwires=["fake-secret-xyz"])
        result = detector.check_lure_leakage(
            response_text="Sure, the password is fake-secret-xyz for the database.",
            lure=lure,
        )
        assert result.leaked is True
        assert len(result.tripwire_hits) > 0

    def test_leakage_with_pii(self):
        detector = PIIDetector(mode=DetectorMode.MOCK)
        lure = _FakeLure(
            value="john@company.com",
            tripwires=["john@company.com"],
        )
        result = detector.check_lure_leakage(
            response_text="The email is john@company.com and the SSN is 123-45-6789",
            lure=lure,
        )
        assert result.leaked is True
        assert len(result.pii_in_response) > 0


# ═══════════════════════════════════════════════════════════════════════════
# DATA CLASS TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestPIIDataClasses:
    """Test PII data classes."""

    def test_pii_entity(self):
        entity = PIIEntity(
            entity_type=PIIType.EMAIL,
            value="test@example.com",
            start=10,
            end=26,
            confidence=0.95,
        )
        assert entity.entity_type == PIIType.EMAIL
        assert entity.value == "test@example.com"

    def test_detection_result(self):
        result = DetectionResult(
            entities=[],
            pii_found=False,
            entity_count=0,
        )
        assert result.pii_found is False

    def test_pii_type_enum(self):
        assert PIIType.EMAIL.value == "email"
        assert PIIType.SSN.value == "ssn"
        assert PIIType.CREDIT_CARD.value == "credit_card"
        assert PIIType.CANARY_TOKEN.value == "canary_token"

    def test_detector_mode_enum(self):
        assert DetectorMode.MOCK.value == "mock"
        assert DetectorMode.NIM.value == "nim"
        assert DetectorMode.API.value == "api"
