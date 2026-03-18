"""
Lure — Fake assets planted inside canary agents as bait.

Each lure is a piece of data that a legitimate user would never try
to extract but an attacker would. When a lure is accessed, referenced,
or exfiltrated, the TrapWire triggers.

Lure types:
    - Fake API keys (format-valid but non-functional)
    - Fake database schemas with dummy PII
    - Fake credentials (username/password pairs)
    - Fake internal documents (confidential-looking text)
    - Canary tokens (unique strings that track exfiltration)
"""

from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LureType(str, Enum):
    """Categories of bait planted in canary agents."""
    API_KEY = "api_key"
    DATABASE = "database"
    PII = "pii"
    CREDENTIAL = "credential"
    DOCUMENT = "document"
    CANARY_TOKEN = "canary_token"
    ENVIRONMENT_VAR = "environment_var"
    SOURCE_CODE = "source_code"


@dataclass(frozen=True)
class Lure:
    """
    A single piece of bait data.

    Attributes:
        lure_id:    Unique identifier for this lure instance.
        lure_type:  Category of bait.
        name:       Human-readable label (e.g. "STRIPE_API_KEY").
        value:      The actual bait string.
        tripwires:  Substrings that, if seen in agent output, signal exfiltration.
        metadata:   Extra context for forensics.
    """
    lure_id: str
    lure_type: LureType
    name: str
    value: str
    tripwires: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    # ── Factory Methods ─────────────────────────────────────────────

    @classmethod
    def fake_api_key(
        cls,
        value: str | None = None,
        *,
        prefix: str = "sk-CANARY",
        name: str = "OPENAI_API_KEY",
    ) -> Lure:
        """Create a format-valid but non-functional API key lure."""
        if value is None:
            suffix = secrets.token_hex(16)
            value = f"{prefix}-{suffix}"
        # The tripwire is the unique canary portion
        canary_fragment = value[-12:]
        return cls(
            lure_id=f"lure-apikey-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.API_KEY,
            name=name,
            value=value,
            tripwires=(canary_fragment, value),
            metadata={"prefix": prefix},
        )

    @classmethod
    def fake_database(
        cls,
        *,
        tables: tuple[str, ...] | list[str] = ("customers", "transactions", "api_keys"),
        name: str = "INTERNAL_DB",
    ) -> Lure:
        """Create a fake database schema lure with dummy records."""
        canary_token = f"CANARY-DB-{secrets.token_hex(6)}"
        schema_text = f"-- Database: {name}\n-- Canary: {canary_token}\n"
        for table in tables:
            schema_text += f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, data TEXT);\n"

        # Sample dummy records
        dummy_records = [
            f"INSERT INTO customers VALUES (1, 'Jane Doe, {canary_token}');",
            f"INSERT INTO api_keys VALUES (1, 'sk-live-{canary_token}');",
        ]
        schema_text += "\n".join(dummy_records)

        return cls(
            lure_id=f"lure-db-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.DATABASE,
            name=name,
            value=schema_text,
            tripwires=(canary_token,),
            metadata={"tables": list(tables)},
        )

    @classmethod
    def fake_pii(
        cls,
        *,
        count: int = 10,
        name: str = "CUSTOMER_RECORDS",
    ) -> Lure:
        """Generate fake PII records with embedded canary tokens."""
        canary_token = f"CANARY-PII-{secrets.token_hex(6)}"
        first_names = ["Alice", "Bob", "Charlie", "Diana", "Eve",
                       "Frank", "Grace", "Henry", "Iris", "Jack"]
        records = []
        for i in range(min(count, len(first_names))):
            # Fake but structured to look real
            ssn_fragment = f"{100+i:03d}-{canary_token[-4:]}-{1000+i:04d}"
            records.append(
                f"{first_names[i]} | {first_names[i].lower()}@example.com | "
                f"SSN: {ssn_fragment} | {canary_token}"
            )
        value = "\n".join(records)

        return cls(
            lure_id=f"lure-pii-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.PII,
            name=name,
            value=value,
            tripwires=(canary_token,),
            metadata={"count": count},
        )

    @classmethod
    def fake_credential(
        cls,
        *,
        username: str = "admin",
        password: str | None = None,
        service: str = "internal-dashboard",
    ) -> Lure:
        """Create a fake credential pair."""
        if password is None:
            password = f"Canary_{secrets.token_urlsafe(12)}"
        canary_fragment = password[-8:]
        return cls(
            lure_id=f"lure-cred-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.CREDENTIAL,
            name=f"{service}_credentials",
            value=f"Username: {username}\nPassword: {password}",
            tripwires=(canary_fragment, password),
            metadata={"service": service, "username": username},
        )

    @classmethod
    def canary_token(
        cls,
        *,
        context: str = "internal",
        name: str = "TRACKING_TOKEN",
    ) -> Lure:
        """Create a unique canary token for tracking exfiltration."""
        token = f"CNRY-{context.upper()}-{uuid.uuid4().hex}"
        return cls(
            lure_id=f"lure-token-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.CANARY_TOKEN,
            name=name,
            value=token,
            tripwires=(token,),
            metadata={"context": context},
        )

    @classmethod
    def fake_env_var(
        cls,
        *,
        var_name: str = "AWS_SECRET_ACCESS_KEY",
        value: str | None = None,
    ) -> Lure:
        """Create a fake environment variable."""
        if value is None:
            value = f"CANARY/{secrets.token_urlsafe(30)}"
        canary_fragment = value[-10:]
        return cls(
            lure_id=f"lure-env-{uuid.uuid4().hex[:8]}",
            lure_type=LureType.ENVIRONMENT_VAR,
            name=var_name,
            value=value,
            tripwires=(canary_fragment, value),
            metadata={"var_name": var_name},
        )

    # ── Utility ─────────────────────────────────────────────────────

    def check_output(self, text: str) -> bool:
        """Return True if any tripwire appears in the given text."""
        text_lower = text.lower()
        return any(tw.lower() in text_lower for tw in self.tripwires)

    def fingerprint(self) -> str:
        """Return a short hash of this lure for logging (doesn't leak the value)."""
        h = hashlib.sha256(self.value.encode()).hexdigest()[:12]
        return f"{self.lure_type.value}:{h}"

    def __str__(self) -> str:
        return f"Lure({self.lure_type.value}, name={self.name!r}, tripwires={len(self.tripwires)})"
