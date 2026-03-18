"""
AVE Card Validator — Validates AVE card JSON files against the schema.

Usage:
    python -m ave validate ave-database/cards/AVE-2025-0001.json
    python -m ave validate ave-database/cards/                  # validate all
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .schema import Category, Severity, Status


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED FIELDS
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_FIELDS = [
    "ave_id", "name", "category", "severity", "status",
    "summary", "mechanism", "blast_radius", "prerequisite",
]

OPTIONAL_FIELDS = [
    "aliases", "environment", "evidence", "defences",
    "date_discovered", "date_published", "cwe_mapping", "mitre_mapping",
    "references", "related_aves", "avss_score", "poc", "timeline", "_meta",
]

VALID_CATEGORIES = {c.value for c in Category}
VALID_SEVERITIES = {s.value for s in Severity}
VALID_STATUSES = {s.value for s in Status}


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

class ValidationError:
    """A single validation issue."""

    def __init__(self, field: str, message: str, level: str = "error"):
        self.field = field
        self.message = message
        self.level = level  # "error" or "warning"

    def __str__(self) -> str:
        icon = "✗" if self.level == "error" else "⚠"
        return f"  {icon} [{self.field}] {self.message}"


class ValidationResult:
    """Result of validating an AVE card."""

    def __init__(self, path: str):
        self.path = path
        self.errors: list[ValidationError] = []
        self.warnings: list[ValidationError] = []

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, field: str, message: str) -> None:
        self.errors.append(ValidationError(field, message, "error"))

    def add_warning(self, field: str, message: str) -> None:
        self.warnings.append(ValidationError(field, message, "warning"))

    def __str__(self) -> str:
        status = "✓ PASS" if self.valid else "✗ FAIL"
        lines = [f"{status}  {self.path}"]
        for e in self.errors:
            lines.append(str(e))
        for w in self.warnings:
            lines.append(str(w))
        return "\n".join(lines)


def validate_card_data(data: dict[str, Any], path: str = "") -> ValidationResult:
    """Validate a parsed AVE card dict against the schema."""
    result = ValidationResult(path)

    # ── Required fields ─────────────────────────────────────────────
    for field in REQUIRED_FIELDS:
        if field not in data:
            result.add_error(field, f"Required field '{field}' is missing")
        elif not data[field]:
            result.add_error(field, f"Required field '{field}' is empty")

    # ── AVE ID format ───────────────────────────────────────────────
    ave_id = data.get("ave_id", "")
    if ave_id:
        import re
        if not re.match(r"^AVE-(DRAFT|\d{4})-\d{4}$", ave_id):
            result.add_error(
                "ave_id",
                f"Invalid format: '{ave_id}'. Expected AVE-YYYY-NNNN or AVE-DRAFT-NNNN"
            )

    # ── Enum validation ─────────────────────────────────────────────
    category = data.get("category", "")
    if category and category not in VALID_CATEGORIES:
        result.add_error(
            "category",
            f"Invalid category: '{category}'. Valid: {sorted(VALID_CATEGORIES)}"
        )

    severity = data.get("severity", "")
    if severity and severity not in VALID_SEVERITIES:
        result.add_error(
            "severity",
            f"Invalid severity: '{severity}'. Valid: {sorted(VALID_SEVERITIES)}"
        )

    status = data.get("status", "")
    if status and status not in VALID_STATUSES:
        result.add_error(
            "status",
            f"Invalid status: '{status}'. Valid: {sorted(VALID_STATUSES)}"
        )

    # ── Summary length ──────────────────────────────────────────────
    summary = data.get("summary", "")
    if summary and len(summary) < 20:
        result.add_warning("summary", "Summary is very short (< 20 chars)")
    if summary and len(summary) > 2000:
        result.add_warning("summary", "Summary is very long (> 2000 chars)")

    # ── Environment vector ──────────────────────────────────────────
    env = data.get("environment", {})
    if env:
        if not isinstance(env, dict):
            result.add_error("environment", "Must be a JSON object")
        else:
            for bool_field in ("multi_agent", "tools_required", "memory_required"):
                val = env.get(bool_field)
                if val is not None and not isinstance(val, bool):
                    result.add_error(
                        f"environment.{bool_field}",
                        f"Must be boolean, got {type(val).__name__}"
                    )
            for list_field in ("frameworks", "models_tested"):
                val = env.get(list_field)
                if val is not None and not isinstance(val, list):
                    result.add_error(
                        f"environment.{list_field}",
                        f"Must be an array, got {type(val).__name__}"
                    )
    else:
        result.add_warning("environment", "No environment vector specified")

    # ── Evidence ────────────────────────────────────────────────────
    evidence = data.get("evidence", [])
    if evidence:
        if not isinstance(evidence, list):
            result.add_error("evidence", "Must be a JSON array")
        else:
            for i, ev in enumerate(evidence):
                if not isinstance(ev, dict):
                    result.add_error(f"evidence[{i}]", "Must be a JSON object")
                elif "experiment_id" not in ev:
                    result.add_warning(
                        f"evidence[{i}]",
                        "Missing experiment_id"
                    )

    # ── Defences ────────────────────────────────────────────────────
    defences = data.get("defences", [])
    if defences:
        if not isinstance(defences, list):
            result.add_error("defences", "Must be a JSON array")
        else:
            for i, d in enumerate(defences):
                if not isinstance(d, dict):
                    result.add_error(f"defences[{i}]", "Must be a JSON object")
                elif "name" not in d:
                    result.add_error(f"defences[{i}]", "Missing 'name' field")

    # ── Related AVEs ────────────────────────────────────────────────
    related = data.get("related_aves", [])
    if related:
        import re
        for r in related:
            if not re.match(r"^AVE-\d{4}-\d{4}$", r):
                result.add_warning(
                    "related_aves",
                    f"Invalid related AVE format: '{r}'"
                )

    # ── AVSS Score ──────────────────────────────────────────────────
    avss = data.get("avss_score")
    if avss:
        if not isinstance(avss, dict):
            result.add_error("avss_score", "Must be a JSON object")
        else:
            overall = avss.get("overall_score")
            if overall is not None:
                if not isinstance(overall, (int, float)):
                    result.add_error(
                        "avss_score.overall_score",
                        f"Must be numeric, got {type(overall).__name__}"
                    )
                elif overall < 0 or overall > 11.5:
                    result.add_warning(
                        "avss_score.overall_score",
                        f"Score {overall} is outside typical range (0–10)"
                    )

    # ── Metadata ────────────────────────────────────────────────────
    meta = data.get("_meta", {})
    if meta:
        license_val = meta.get("license", "")
        if license_val and license_val != "CC-BY-SA-4.0":
            result.add_warning(
                "_meta.license",
                f"Non-standard license: '{license_val}'. Expected CC-BY-SA-4.0"
            )

    return result


def validate_card_file(path: str) -> ValidationResult:
    """Validate a single AVE card JSON file."""
    result = ValidationResult(path)

    # Check file exists
    if not os.path.isfile(path):
        result.add_error("file", f"File not found: {path}")
        return result

    # Check file extension
    if not path.endswith(".json"):
        result.add_error("file", f"Expected .json file, got: {path}")
        return result

    # Parse JSON
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error("json", f"Invalid JSON: {e}")
        return result

    return validate_card_data(data, path)


def validate_directory(dir_path: str) -> list[ValidationResult]:
    """Validate all AVE card JSON files in a directory."""
    results = []
    p = Path(dir_path)

    if not p.is_dir():
        result = ValidationResult(dir_path)
        result.add_error("directory", f"Not a directory: {dir_path}")
        return [result]

    json_files = sorted(p.glob("*.json"))
    if not json_files:
        result = ValidationResult(dir_path)
        result.add_error("directory", "No .json files found")
        return [result]

    for json_file in json_files:
        # Skip index files
        if json_file.name in ("index.json", "severity_index.json"):
            continue
        results.append(validate_card_file(str(json_file)))

    return results


def validate_path(path: str) -> list[ValidationResult]:
    """Validate a file or directory."""
    p = Path(path)
    if p.is_dir():
        return validate_directory(path)
    else:
        return [validate_card_file(path)]


def run_validation(path: str, verbose: bool = False) -> bool:
    """Run validation and print results. Returns True if all valid."""
    results = validate_path(path)

    total = len(results)
    passed = sum(1 for r in results if r.valid)
    failed = total - passed
    total_warnings = sum(len(r.warnings) for r in results)

    print(f"\n{'═' * 60}")
    print(f"  AVE Card Validation — {total} file{'s' if total != 1 else ''}")
    print(f"{'═' * 60}\n")

    for result in results:
        if verbose or not result.valid or result.warnings:
            print(result)

    print(f"\n{'─' * 60}")
    print(f"  ✓ Passed:   {passed}")
    if failed:
        print(f"  ✗ Failed:   {failed}")
    if total_warnings:
        print(f"  ⚠ Warnings: {total_warnings}")
    print(f"{'─' * 60}\n")

    return failed == 0
