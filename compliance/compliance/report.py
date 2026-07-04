"""Client-facing rendering + tamper-evident attestation for a GapReport.

- ``render_markdown`` produces a per-jurisdiction gap report a client can read.
- ``attest`` content-hashes the report and (optionally) anchors it into a
  hash-chain for a tamper-evident, verifiable record. The chain is duck-typed to
  shield's ``HashChain`` — ``append(source=, canonical_sha256=) -> entry`` — so it
  works with the real chain out of the box without importing shield.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .engine import GapReport
from .schema import Jurisdiction, Status

_JURISDICTION_ORDER = (Jurisdiction.EU, Jurisdiction.UK, Jurisdiction.US)
_JURISDICTION_LABEL = {Jurisdiction.EU: "EU — European Union",
                       Jurisdiction.UK: "UK — United Kingdom",
                       Jurisdiction.US: "US — United States"}
_STATUS_ORDER = (Status.VIOLATION, Status.GAP, Status.PARTIAL, Status.SATISFIED)
_STATUS_HEADING = {Status.VIOLATION: "⛔ Violations", Status.GAP: "⚠️ Gaps",
                   Status.PARTIAL: "◐ Partial", Status.SATISFIED: "✅ Satisfied"}

_DISCLAIMER = ("_Decision-support only — **not legal advice**. Control content must be "
               "validated by a qualified person; each control carries an `effective_date`._")


@dataclass(frozen=True)
class ComplianceAttestation:
    profile: str
    generated_at: str
    jurisdictions: tuple[str, ...]
    compliant: bool
    summary: dict[str, int]
    content_hash: str
    chain_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "generated_at": self.generated_at,
            "jurisdictions": list(self.jurisdictions),
            "compliant": self.compliant,
            "summary": self.summary,
            "content_hash": self.content_hash,
            "chain_id": self.chain_id,
        }


def attest(report: GapReport, *, chain: Any = None,
           source: str = "compliance-attestation") -> ComplianceAttestation:
    """Content-hash the report; optionally anchor it into a hash-chain."""
    payload = {
        "profile": report.profile_name,
        "compliant": report.compliant,
        "summary": report.summary(),
        "findings": [f.to_dict() for f in report.findings],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    chain_id: str | None = None
    if chain is not None:
        entry = chain.append(source=source, canonical_sha256=content_hash)
        chain_id = getattr(entry, "entry_hash", None) or (entry if isinstance(entry, str) else str(entry))

    jurisdictions = tuple(sorted({f.control.jurisdiction.value for f in report.findings}))
    return ComplianceAttestation(
        profile=report.profile_name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        jurisdictions=jurisdictions,
        compliant=report.compliant,
        summary=report.summary(),
        content_hash=content_hash,
        chain_id=chain_id,
    )


def render_markdown(report: GapReport, *, attestation: ComplianceAttestation | None = None) -> str:
    lines: list[str] = [f"# Compliance Gap Report — {report.profile_name}", ""]

    n_viol = len(report.violations)
    n_gap = len(report.gaps)
    status = ("✅ **COMPLIANT**" if report.compliant
              else f"⛔ **NON-COMPLIANT** — {n_viol} violation(s), {n_gap} gap(s)")
    lines.append(f"- Status: {status}")
    if attestation is not None:
        lines.append(f"- Generated: `{attestation.generated_at}`")
        anchor = f" · chain `{attestation.chain_id}`" if attestation.chain_id else ""
        lines.append(f"- Attestation: `sha256:{attestation.content_hash}`{anchor}")
    lines.append("")

    lines.append("## Summary")
    for key, count in sorted(report.summary().items()):
        lines.append(f"- {key}: {count}")
    lines.append("")

    by_juris: dict[Jurisdiction, list] = {}
    for f in report.findings:
        by_juris.setdefault(f.control.jurisdiction, []).append(f)

    for juris in _JURISDICTION_ORDER:
        findings = by_juris.get(juris)
        if not findings:
            continue
        lines.append(f"## {_JURISDICTION_LABEL[juris]}")
        for st in _STATUS_ORDER:
            group = [f for f in findings if f.status == st]
            if not group:
                continue
            lines.append(f"### {_STATUS_HEADING[st]}")
            for f in sorted(group, key=lambda x: x.control.control_id):
                c = f.control
                head = f"- **{c.control_id}** ({c.reference}) — {c.title}"
                if st == Status.VIOLATION:
                    head += f" — prohibited: `{', '.join(f.triggered_prohibitions)}`"
                elif st in (Status.GAP, Status.PARTIAL):
                    head += f" — missing: `{', '.join(f.missing_capabilities)}` — *{c.guidance}*"
                elif st == Status.SATISFIED and c.evidence:
                    head += f" — evidence: {', '.join(e.nail_component or e.name for e in c.evidence)}"
                lines.append(head)
            lines.append("")

    lines.append("---")
    lines.append(_DISCLAIMER)
    return "\n".join(lines).rstrip() + "\n"
