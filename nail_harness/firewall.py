"""
NAIL Harness — Egress Policy & Semantic Action Firewall
==========================================================

Productised versions of the Infrastructure Layer controls:

  - EgressPolicy:         URL/domain allowlisting for agent HTTP actions
  - SemanticFirewall:     Embedding-based forbidden-action detection
  - ActionGate:           Combined pre-execution gate (egress + semantic + guard)

These implement the "Middleware Layer" and "Infrastructure Layer"
from the NAIL defence-in-depth architecture.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse


# ═══════════════════════════════════════════════════════════════════════════
# Egress Policy — URL/Domain Allowlisting
# ═══════════════════════════════════════════════════════════════════════════

# RFC1918 + link-local + cloud metadata ranges that agents must never reach
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),     # AWS/GCP/Azure metadata
    ipaddress.ip_network("127.0.0.0/8"),         # loopback
    ipaddress.ip_network("::1/128"),             # IPv6 loopback
    ipaddress.ip_network("fd00::/8"),            # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),           # IPv6 link-local
]

# Known cloud metadata hostnames
_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
}


class EgressPolicy:
    """
    Network-level action allowlisting for agent HTTP operations.

    Blocks access to private IP ranges, cloud metadata endpoints,
    and any domain not on the explicit allowlist.

    Usage:
        policy = EgressPolicy(
            allowed_domains=["api.openai.com", "*.googleapis.com"],
            block_private=True,
        )
        ok, reason = policy.check_url("http://169.254.169.254/latest/meta-data/")
        # → (False, "Blocked: cloud metadata endpoint")
    """

    def __init__(
        self,
        allowed_domains: Optional[list[str]] = None,
        blocked_domains: Optional[list[str]] = None,
        block_private: bool = True,
        block_metadata: bool = True,
        allow_all: bool = False,
    ):
        self.allowed_domains = allowed_domains or []
        self.blocked_domains = set(blocked_domains or [])
        self.block_private = block_private
        self.block_metadata = block_metadata
        self.allow_all = allow_all

        # Compile allowlist patterns
        self._allow_patterns: list[re.Pattern] = []
        for domain in self.allowed_domains:
            # Convert glob pattern to regex: *.example.com → .*\.example\.com
            pattern = domain.replace(".", r"\.").replace("*", ".*")
            self._allow_patterns.append(re.compile(f"^{pattern}$", re.IGNORECASE))

    def check_url(self, url: str) -> tuple[bool, str]:
        """
        Validate a URL against the egress policy.

        Returns:
            (allowed, reason)
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "Blocked: malformed URL"

        hostname = (parsed.hostname or "").lower().strip()
        if not hostname:
            return False, "Blocked: no hostname in URL"

        # Block metadata endpoints
        if self.block_metadata and hostname in _BLOCKED_HOSTS:
            return False, f"Blocked: cloud metadata endpoint ({hostname})"

        # Block private IP ranges
        if self.block_private:
            try:
                ip = ipaddress.ip_address(hostname)
                for network in _BLOCKED_NETWORKS:
                    if ip in network:
                        return False, f"Blocked: private/internal IP range ({hostname})"
            except ValueError:
                pass  # Not an IP — it's a hostname, continue to domain checks

        # Explicit block list
        if hostname in self.blocked_domains:
            return False, f"Blocked: domain on block list ({hostname})"

        # If allow_all mode, skip allowlist check
        if self.allow_all:
            return True, "OK (allow-all mode)"

        # Allowlist check (if allowlist is configured)
        if self._allow_patterns:
            for pattern in self._allow_patterns:
                if pattern.match(hostname):
                    return True, "OK"
            return False, f"Blocked: domain not on allowlist ({hostname})"

        # No allowlist configured — allow by default (with private/metadata still blocked)
        return True, "OK (no allowlist configured)"

    def check_urls_in_text(self, text: str) -> list[tuple[str, bool, str]]:
        """Find and validate all URLs in a text string."""
        url_pattern = re.compile(r'https?://[^\s<>"\']+')
        results = []
        for match in url_pattern.finditer(text):
            url = match.group()
            allowed, reason = self.check_url(url)
            results.append((url, allowed, reason))
        return results


# ═══════════════════════════════════════════════════════════════════════════
# Semantic Action Firewall
# ═══════════════════════════════════════════════════════════════════════════

# Default forbidden action patterns (string matching + regex)
_DEFAULT_FORBIDDEN_PATTERNS = [
    # Destructive database operations
    r"(?i)\bDROP\s+TABLE\b",
    r"(?i)\bDROP\s+DATABASE\b",
    r"(?i)\bDELETE\s+FROM\s+\w+\s*$",       # DELETE without WHERE
    r"(?i)\bTRUNCATE\s+TABLE\b",
    r"(?i)\bALTER\s+TABLE\s+\w+\s+DROP\b",

    # Destructive API patterns
    r"(?i)DELETE\s+/users?/all",
    r"(?i)DELETE\s+/\*/",
    r"(?i)POST\s+/admin/reset",

    # Shell injection
    r"(?i)\b(?:rm\s+-rf|mkfs|dd\s+if=|chmod\s+777|curl\s+.*\|\s*(?:bash|sh))\b",

    # Credential access
    r"(?i)\b(?:AWS_SECRET|PRIVATE_KEY|password|api[_-]?key)\s*[:=]",
    r"(?i)/etc/(?:passwd|shadow)",

    # System prompt exfiltration
    r"(?i)(?:reveal|show|print|output)\s+(?:your\s+)?(?:system\s+)?prompt",
    r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions",
]


class SemanticFirewall:
    """
    Checks tool-call payloads against forbidden action patterns.

    Two modes:
      1. Pattern matching — regex against known dangerous operations
      2. Embedding similarity — (optional) checks semantic distance
         against a vector DB of forbidden actions

    Usage:
        firewall = SemanticFirewall()

        ok, reason = firewall.check_action(
            tool_name="database_query",
            tool_input={"sql": "DROP TABLE users;"}
        )
        # → (False, "Blocked: matches forbidden pattern 'DROP TABLE'")
    """

    def __init__(
        self,
        additional_patterns: Optional[list[str]] = None,
        custom_patterns_only: bool = False,
        embedding_checker: Optional[Any] = None,
        similarity_threshold: float = 0.85,
    ):
        patterns = [] if custom_patterns_only else list(_DEFAULT_FORBIDDEN_PATTERNS)
        if additional_patterns:
            patterns.extend(additional_patterns)

        self._patterns: list[re.Pattern] = []
        for p in patterns:
            try:
                self._patterns.append(re.compile(p))
            except re.error:
                continue

        self.embedding_checker = embedding_checker
        self.similarity_threshold = similarity_threshold

    def check_action(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> tuple[bool, str]:
        """
        Validate a tool action against the semantic firewall.

        Returns:
            (allowed, reason)
        """
        # Serialise the full action for pattern matching
        action_text = f"{tool_name} {_flatten_dict(tool_input)}"

        # Pattern matching
        for pattern in self._patterns:
            match = pattern.search(action_text)
            if match:
                return False, f"Blocked: matches forbidden pattern '{match.group()}'"

        # Embedding similarity check (if configured)
        if self.embedding_checker:
            try:
                similarity, matched_action = self.embedding_checker(action_text)
                if similarity >= self.similarity_threshold:
                    return False, (
                        f"Blocked: semantic similarity to forbidden action "
                        f"'{matched_action}' ({similarity:.1%})"
                    )
            except Exception:
                pass  # Embedding check failure should not block

        return True, "OK"

    def check_output(self, output_text: str) -> tuple[bool, str]:
        """Check agent output for forbidden content (data exfiltration, etc.)."""
        for pattern in self._patterns:
            match = pattern.search(output_text)
            if match:
                return False, f"Blocked output: matches pattern '{match.group()}'"
        return True, "OK"


def _flatten_dict(d: dict, prefix: str = "") -> str:
    """Flatten a dict to a searchable string."""
    parts = []
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            parts.append(_flatten_dict(v, key))
        elif isinstance(v, list):
            parts.append(f"{key}={' '.join(str(x) for x in v)}")
        else:
            parts.append(f"{key}={v}")
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Combined Action Gate
# ═══════════════════════════════════════════════════════════════════════════

class ActionGate:
    """
    Combined pre-execution gate that chains:
      1. Egress policy (URL validation)
      2. Semantic firewall (forbidden patterns)
      3. Guard model classification (optional, via GuardClient)

    This is the productised "Action Gating" from middlewareprotection.md.

    Usage:
        gate = ActionGate(
            egress=EgressPolicy(allowed_domains=["api.stripe.com"]),
            firewall=SemanticFirewall(),
            guard=guard_client,  # Optional GuardClient instance
        )

        ok, reason = gate.check(
            tool_name="http_request",
            tool_input={"url": "http://169.254.169.254/...", "method": "GET"},
        )
    """

    def __init__(
        self,
        egress: Optional[EgressPolicy] = None,
        firewall: Optional[SemanticFirewall] = None,
        guard: Optional[Any] = None,  # GuardClient
    ):
        self.egress = egress or EgressPolicy()
        self.firewall = firewall or SemanticFirewall()
        self.guard = guard

    def check(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> tuple[bool, str]:
        """
        Run all checks in sequence. First failure blocks.

        Returns:
            (allowed, reason)
        """
        # 1. Egress policy — check any URLs in the input
        input_text = _flatten_dict(tool_input)
        url_results = self.egress.check_urls_in_text(input_text)
        for url, allowed, reason in url_results:
            if not allowed:
                return False, f"Egress: {reason} (URL: {url})"

        # 2. Semantic firewall — check for forbidden patterns
        allowed, reason = self.firewall.check_action(tool_name, tool_input)
        if not allowed:
            return False, f"Firewall: {reason}"

        # 3. Guard model classification (if available)
        if self.guard:
            try:
                result = self.guard.classify_action(tool_name, tool_input)
                if result.get("blocked", False):
                    return False, f"Guard: {result.get('reason', 'classified as unsafe')}"
            except Exception:
                pass  # Guard failure should not block (fail-open for availability)

        return True, "OK"
