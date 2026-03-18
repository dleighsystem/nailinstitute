"""
PII Detector — NVIDIA GLiNER-based PII detection for Canary lure analysis
==========================================================================

Wraps the NVIDIA GLiNER PII model to replace the naive word-overlap
lure detection in the Canary system with real ML-based PII detection.

Available modes:
  - ``nim``  — Local NIM container on DGX GB10
  - ``api``  — NVIDIA Build hosted endpoint (free)
  - ``mock`` — Pattern-based mock for testing

Integration with the Canary system:

    >>> from integration.pii_detector import PIIDetector, PIIEntity
    >>> detector = PIIDetector()
    >>> entities = detector.detect("My SSN is 123-45-6789")
    >>> entities[0].entity_type  # "SSN"
    >>> entities[0].value        # "123-45-6789"

    # Use for lure leak detection
    >>> from canary.lure import Lure
    >>> lure = Lure.fake_pii()
    >>> leaked = detector.check_lure_leakage(response_text, lure)
    >>> leaked.pii_found        # True
    >>> leaked.leaked_entities   # [PIIEntity(...)]
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PIIType(str, Enum):
    """PII entity types (aligned with GLiNER PII taxonomy)."""
    PERSON_NAME = "person_name"
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    PASSWORD = "password"
    BANK_ACCOUNT = "bank_account"
    DRIVER_LICENSE = "driver_license"
    PASSPORT = "passport"
    CANARY_TOKEN = "canary_token"
    UNKNOWN = "unknown"


class DetectorMode(str, Enum):
    """How to reach the PII detection model."""
    NIM = "nim"
    API = "api"
    MOCK = "mock"


@dataclass
class PIIEntity:
    """A single PII entity found in text."""
    entity_type: PIIType
    value: str
    start: int
    end: int
    confidence: float = 1.0
    source: str = "gliner_pii"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.entity_type.value,
            "value": self.value[:20] + "..." if len(self.value) > 20 else self.value,
            "start": self.start,
            "end": self.end,
            "confidence": self.confidence,
        }


@dataclass
class DetectionResult:
    """Result from PII detection on a text."""
    entities: list[PIIEntity] = field(default_factory=list)
    pii_found: bool = False
    entity_count: int = 0
    entity_types: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    text_length: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pii_found": self.pii_found,
            "entity_count": self.entity_count,
            "entity_types": self.entity_types,
            "entities": [e.to_dict() for e in self.entities],
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class LureLeakageResult:
    """Result from checking whether a lure's PII leaked into output."""
    leaked: bool = False
    leaked_entities: list[PIIEntity] = field(default_factory=list)
    tripwire_hits: list[str] = field(default_factory=list)
    pii_in_response: list[PIIEntity] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaked": self.leaked,
            "leaked_entity_count": len(self.leaked_entities),
            "tripwire_hits": self.tripwire_hits,
            "total_pii_in_response": len(self.pii_in_response),
            "confidence": self.confidence,
        }


# ═══════════════════════════════════════════════════════════════════════════
# PATTERN-BASED MOCK ENGINE
# ═══════════════════════════════════════════════════════════════════════════

# Regex patterns for common PII types
_PII_PATTERNS: list[tuple[re.Pattern, PIIType]] = [
    # SSN (US format)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), PIIType.SSN),
    # Credit card (basic 16-digit with optional separators)
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), PIIType.CREDIT_CARD),
    # Email
    (re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"), PIIType.EMAIL),
    # Phone (US format)
    (re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), PIIType.PHONE),
    # IP address (v4)
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), PIIType.IP_ADDRESS),
    # Date of birth (common formats)
    (re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"), PIIType.DATE_OF_BIRTH),
    # API key patterns (sk-..., key-..., CANARY prefixed)
    (re.compile(r"\b(?:sk|key|token|CANARY|CNRY)[-_][a-zA-Z0-9]{8,}\b"), PIIType.API_KEY),
    # Password-like (after "password:" or "Password:")
    (re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*(\S+)", re.I), PIIType.PASSWORD),
    # Bank account (basic: 8-17 digit number after "account" keyword)
    (re.compile(r"(?:account|acct)\s*(?:no|number|#)?\s*[:=]?\s*(\d{8,17})", re.I), PIIType.BANK_ACCOUNT),
]


class PIIDetector:
    """
    PII detector powered by NVIDIA GLiNER PII or pattern-based mock.

    Usage:
        >>> detector = PIIDetector()                 # Mock mode
        >>> detector = PIIDetector(mode="api")        # NVIDIA Build API
        >>> detector = PIIDetector(mode="nim", base_url="http://localhost:8200")

        >>> result = detector.detect("My SSN is 123-45-6789")
        >>> result.pii_found  # True
        >>> result.entities[0].entity_type  # PIIType.SSN

        >>> from canary.lure import Lure
        >>> lure = Lure.fake_api_key()
        >>> leak = detector.check_lure_leakage("Here is sk-CANARY-abc123", lure)
        >>> leak.leaked  # True
    """

    def __init__(
        self,
        mode: str | DetectorMode = DetectorMode.MOCK,
        base_url: str = "",
        api_key: str = "",
        timeout: float = 30.0,
    ):
        self.mode = DetectorMode(mode) if isinstance(mode, str) else mode
        self.base_url = base_url or os.environ.get(
            "GLINER_PII_URL", "http://localhost:8200"
        )
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.timeout = timeout
        self._call_count = 0
        self._total_latency = 0.0

    def detect(self, text: str) -> DetectionResult:
        """
        Scan text for PII entities.

        Returns a DetectionResult with all found entities.
        """
        start = time.time()

        if self.mode == DetectorMode.MOCK:
            entities = self._detect_mock(text)
        elif self.mode == DetectorMode.NIM:
            entities = self._detect_nim(text)
        elif self.mode == DetectorMode.API:
            entities = self._detect_api(text)
        else:
            entities = self._detect_mock(text)

        latency = (time.time() - start) * 1000
        self._call_count += 1
        self._total_latency += latency

        entity_types = list(dict.fromkeys(e.entity_type.value for e in entities))
        return DetectionResult(
            entities=entities,
            pii_found=len(entities) > 0,
            entity_count=len(entities),
            entity_types=entity_types,
            latency_ms=latency,
            text_length=len(text),
        )

    def check_lure_leakage(
        self,
        response_text: str,
        lure: Any,
    ) -> LureLeakageResult:
        """
        Check if a Canary Lure's data leaked into a response.

        Combines:
        1. Traditional tripwire detection (exact substring matching)
        2. ML-based PII detection to find entity leakage patterns

        Much more robust than the old word-overlap approach.
        """
        # Step 1: Traditional tripwire check
        tripwire_hits = []
        text_lower = response_text.lower()
        for tw in getattr(lure, "tripwires", ()):
            if tw.lower() in text_lower:
                tripwire_hits.append(tw)

        # Step 2: ML-based PII detection on the response
        pii_result = self.detect(response_text)

        # Step 3: Cross-reference PII entities with lure data
        leaked_entities: list[PIIEntity] = []
        lure_value = getattr(lure, "value", "").lower()

        for entity in pii_result.entities:
            entity_lower = entity.value.lower()
            # Check if the found PII entity matches anything in the lure
            if entity_lower in lure_value or lure_value and entity_lower in lure_value:
                leaked_entities.append(entity)
            # Also check if entity type matches lure type
            elif hasattr(lure, "lure_type"):
                lure_type_str = lure.lure_type.value if hasattr(lure.lure_type, "value") else str(lure.lure_type)
                if (
                    (lure_type_str == "api_key" and entity.entity_type == PIIType.API_KEY) or
                    (lure_type_str == "pii" and entity.entity_type in (PIIType.SSN, PIIType.EMAIL, PIIType.PHONE)) or
                    (lure_type_str == "credential" and entity.entity_type == PIIType.PASSWORD) or
                    (lure_type_str == "canary_token" and entity.entity_type == PIIType.CANARY_TOKEN)
                ):
                    leaked_entities.append(entity)

        # Determine if leakage occurred
        leaked = len(tripwire_hits) > 0 or len(leaked_entities) > 0
        # Confidence: tripwire hits = 1.0, PII detection = based on entity confidence
        confidence = 0.0
        if tripwire_hits:
            confidence = 1.0
        elif leaked_entities:
            confidence = max(e.confidence for e in leaked_entities)

        return LureLeakageResult(
            leaked=leaked,
            leaked_entities=leaked_entities,
            tripwire_hits=tripwire_hits,
            pii_in_response=pii_result.entities,
            confidence=confidence,
        )

    def _detect_mock(self, text: str) -> list[PIIEntity]:
        """Pattern-based PII detection (mock)."""
        entities: list[PIIEntity] = []
        for pattern, pii_type in _PII_PATTERNS:
            for match in pattern.finditer(text):
                # For patterns with groups, use group(1) if available
                value = match.group(1) if match.lastindex else match.group(0)
                entities.append(PIIEntity(
                    entity_type=pii_type,
                    value=value,
                    start=match.start(),
                    end=match.end(),
                    confidence=0.90,
                    source="mock_pattern",
                ))

        # Check for canary tokens (CNRY- or CANARY- prefixed strings)
        canary_pattern = re.compile(r"\bC(?:NRY|ANARY)[-_][A-Za-z0-9-]+\b")
        for match in canary_pattern.finditer(text):
            entities.append(PIIEntity(
                entity_type=PIIType.CANARY_TOKEN,
                value=match.group(0),
                start=match.start(),
                end=match.end(),
                confidence=0.95,
                source="mock_pattern",
            ))

        return entities

    def _detect_nim(self, text: str) -> list[PIIEntity]:
        """Call local GLiNER PII NIM container."""
        try:
            import urllib.request
            url = f"{self.base_url}/v1/pii/detect"
            payload = {"input": text}
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read())

            return self._parse_gliner_response(result, text)
        except Exception:
            # Fall back to mock on NIM failure
            return self._detect_mock(text)

    def _detect_api(self, text: str) -> list[PIIEntity]:
        """Call NVIDIA Build GLiNER PII API (free endpoint)."""
        try:
            import urllib.request
            url = "https://ai.api.nvidia.com/v1/nvidia/gliner-pii"
            payload = {"input": text}
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url, data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read())

            return self._parse_gliner_response(result, text)
        except Exception:
            return self._detect_mock(text)

    def _parse_gliner_response(
        self, result: dict[str, Any], text: str,
    ) -> list[PIIEntity]:
        """Parse GLiNER PII API response into PIIEntity list."""
        entities: list[PIIEntity] = []
        for ent in result.get("entities", []):
            pii_type = self._map_gliner_type(ent.get("type", ""))
            entities.append(PIIEntity(
                entity_type=pii_type,
                value=ent.get("text", ""),
                start=ent.get("start", 0),
                end=ent.get("end", 0),
                confidence=ent.get("score", 0.0),
                source="gliner_pii",
            ))
        return entities

    @staticmethod
    def _map_gliner_type(gliner_type: str) -> PIIType:
        """Map GLiNER entity types to our PIIType enum."""
        mapping = {
            "person": PIIType.PERSON_NAME,
            "email": PIIType.EMAIL,
            "phone_number": PIIType.PHONE,
            "ssn": PIIType.SSN,
            "credit_card": PIIType.CREDIT_CARD,
            "address": PIIType.ADDRESS,
            "date_of_birth": PIIType.DATE_OF_BIRTH,
            "ip_address": PIIType.IP_ADDRESS,
            "api_key": PIIType.API_KEY,
            "password": PIIType.PASSWORD,
            "bank_account": PIIType.BANK_ACCOUNT,
            "driver_license": PIIType.DRIVER_LICENSE,
            "passport": PIIType.PASSPORT,
        }
        return mapping.get(gliner_type.lower(), PIIType.UNKNOWN)

    def stats(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "calls": self._call_count,
            "avg_latency_ms": round(
                self._total_latency / max(self._call_count, 1), 1
            ),
        }
