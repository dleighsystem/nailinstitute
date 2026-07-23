"""Tests for the static credential-scope scanner (AVE-2025-0040 / -0028 / -0026)."""
from __future__ import annotations

from pathlib import Path

from nail_security.credential_scope import (
    CredentialScanReport,
    FindingSeverity,
    report_to_markdown,
    scan_source_tree,
)


def _write(root: Path, name: str, text: str) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_flags_full_env_copy_into_untrusted_launcher(tmp_path: Path):
    _write(
        tmp_path,
        "spawn.py",
        "import os, subprocess\n"
        "subprocess.Popen(['npx', '-y', '@vendor/mcp'], env=os.environ.copy())\n",
    )
    report = scan_source_tree(tmp_path)
    cats = {f.category for f in report.findings}
    assert "env_inheritance" in cats
    assert report.max_severity == FindingSeverity.CRITICAL
    assert any("AVE-2025-0040" in f.ave_refs for f in report.findings)


def test_flags_untrusted_launcher_without_explicit_env(tmp_path: Path):
    _write(
        tmp_path,
        "run.py",
        "import subprocess\n"
        "subprocess.run(['pipx', 'run', 'sometool'])\n",
    )
    report = scan_source_tree(tmp_path)
    assert any(f.category == "env_inheritance" for f in report.findings)


def test_explicit_minimal_env_is_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "safe.py",
        "import subprocess\n"
        "subprocess.run(['ls'], env={'PATH': '/usr/bin'})\n",
    )
    report = scan_source_tree(tmp_path)
    assert not any(f.category == "env_inheritance" for f in report.findings)


def test_flags_hardcoded_huggingface_token(tmp_path: Path):
    _write(tmp_path, "cfg.py", 'HF = "hf_abcdEFGHijklMNOPqrstUVWXyz0123456789"\n')
    report = scan_source_tree(tmp_path)
    assert any(f.category == "long_lived_secret" for f in report.findings)
    assert report.max_severity == FindingSeverity.CRITICAL


def test_flags_unquoted_env_file_secret(tmp_path: Path):
    _write(tmp_path, ".env", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIbKciYbdrEXAMPLE01\n")
    report = scan_source_tree(tmp_path)
    assert any(f.category == "secret_in_env" for f in report.findings)


def test_flags_wildcard_iam_grant(tmp_path: Path):
    _write(
        tmp_path,
        "policy.json",
        '{"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}\n',
    )
    report = scan_source_tree(tmp_path)
    assert any(f.category == "overscoped_grant" for f in report.findings)


def test_placeholder_and_env_lookup_are_not_flagged(tmp_path: Path):
    _write(
        tmp_path,
        "settings.py",
        'import os\n'
        'API_KEY = os.getenv("API_KEY", "")\n'
        'TOKEN_PLACEHOLDER = "xxxxxxxx"\n'
        'PASSWORD = "changeme"\n',
    )
    report = scan_source_tree(tmp_path)
    assert not any(f.category in ("long_lived_secret", "secret_in_env") for f in report.findings)


def test_clean_tree_reports_info_only(tmp_path: Path):
    _write(tmp_path, "app.py", "def add(a, b):\n    return a + b\n")
    report = scan_source_tree(tmp_path)
    assert report.max_severity == FindingSeverity.INFO
    assert len(report.findings) == 1
    assert report.risk_score == 0.0


def test_missing_path_is_reported():
    report = scan_source_tree("/nonexistent/path/xyz")
    assert isinstance(report, CredentialScanReport)
    assert any(f.category == "input" for f in report.findings)


def test_markdown_render_and_serialisation(tmp_path: Path):
    _write(tmp_path, "cfg.py", 'HF = "hf_abcdEFGHijklMNOPqrstUVWXyz0123456789"\n')
    report = scan_source_tree(tmp_path)
    md = report_to_markdown(report)
    assert "# Credential-Scope Scan" in md
    payload = report.to_dict()
    assert payload["max_severity"] == "critical"
    assert payload["files_scanned"] >= 1
