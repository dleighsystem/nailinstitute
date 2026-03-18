"""
OpenShell Sandbox — Secure agent isolation for CTF and Canary deployments
==========================================================================

Adapts NVIDIA OpenShell for the NAIL platform to provide kernel-level
agent sandboxing for:

  1. **CTF Events** — Participants attack agents inside isolated sandboxes
  2. **Canary Deployments** — Honeypot agents run in sandboxed containers
  3. **Arena Sessions** — Red/Blue self-play in isolated environments

OpenShell enforces:
  - Filesystem isolation (read-only host mounts, no credential access)
  - Network egress control (allowlist-only outbound connections)
  - Process isolation (no host PID namespace access)
  - Resource limits (CPU, memory, max runtime)

Architecture:
    ┌────────────────────────────────────────┐
    │          NAIL Platform (Host)          │
    │                                        │
    │  ┌──────────────┐  ┌──────────────┐   │
    │  │  OpenShell   │  │  OpenShell   │   │
    │  │  Gateway     │  │  Gateway     │   │
    │  │  (CTF)       │  │  (Canary)    │   │
    │  │              │  │              │   │
    │  │ ┌──────────┐ │  │ ┌──────────┐ │   │
    │  │ │ Sandbox  │ │  │ │ Sandbox  │ │   │
    │  │ │ Agent +  │ │  │ │ Agent +  │ │   │
    │  │ │ Ollama   │ │  │ │ Ollama   │ │   │
    │  │ └──────────┘ │  │ └──────────┘ │   │
    │  └──────────────┘  └──────────────┘   │
    └────────────────────────────────────────┘

This module provides:
  - SandboxPolicy — YAML-based policy definition
  - SandboxConfig — Sandbox configuration
  - OpenShellManager — Lifecycle management for sandboxes

Usage:
    >>> from integration.openshell_sandbox import OpenShellManager, SandboxPolicy
    >>> mgr = OpenShellManager()
    >>> policy = SandboxPolicy.ctf_restrictive()
    >>> sandbox_id = mgr.create_sandbox("ctf-challenge-1", policy)
    >>> mgr.start_sandbox(sandbox_id)
    >>> # ... run CTF event ...
    >>> mgr.destroy_sandbox(sandbox_id)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
# ENUMS & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════

class SandboxState(str, Enum):
    """Lifecycle state of a sandbox."""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    DESTROYED = "destroyed"
    ERROR = "error"


class SandboxPurpose(str, Enum):
    """What the sandbox is being used for."""
    CTF_CHALLENGE = "ctf_challenge"
    CANARY_HONEYPOT = "canary_honeypot"
    ARENA_RED_TEAM = "arena_red_team"
    ARENA_BLUE_TEAM = "arena_blue_team"
    DEVELOPMENT = "development"
    TESTING = "testing"


class NetworkPolicy(str, Enum):
    """Network egress policy."""
    DENY_ALL = "deny_all"           # No outbound connections
    LOCAL_ONLY = "local_only"       # Only localhost (e.g., local Ollama)
    ALLOWLIST = "allowlist"         # Only specified endpoints
    FULL_ACCESS = "full_access"     # Unrestricted (dev only!)


class FilesystemPolicy(str, Enum):
    """Filesystem access policy."""
    READ_ONLY = "read_only"         # Read-only host mounts
    WORKSPACE_ONLY = "workspace_only"  # R/W only in /workspace
    ISOLATED = "isolated"           # No host mounts at all
    FULL_ACCESS = "full_access"     # Unrestricted (dev only!)


@dataclass
class SandboxPolicy:
    """
    Declarative security policy for an OpenShell sandbox.

    Mirrors the YAML policy format used by OpenShell CLI.
    """
    name: str = "default"
    network: NetworkPolicy = NetworkPolicy.LOCAL_ONLY
    filesystem: FilesystemPolicy = FilesystemPolicy.WORKSPACE_ONLY
    allowed_endpoints: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(default_factory=lambda: [
        "/etc/shadow", "/etc/passwd", "/root/.ssh",
        "/home/*/.ssh", "/var/run/docker.sock",
    ])
    allowed_paths: list[str] = field(default_factory=lambda: [
        "/workspace", "/tmp",
    ])
    max_memory_mb: int = 4096
    max_cpu_cores: float = 2.0
    max_runtime_seconds: int = 3600
    allow_network_tools: bool = False
    allow_shell_execution: bool = False
    allow_file_write: bool = True
    allow_process_spawn: bool = False
    gpu_access: bool = True
    env_vars: dict[str, str] = field(default_factory=dict)

    # ── Factory methods for common configurations ──────────────

    @classmethod
    def ctf_restrictive(cls) -> SandboxPolicy:
        """
        Maximum restriction policy for CTF challenges.

        - No network egress (participants can't phone home)
        - Read-only filesystem (can't modify the challenge)
        - No shell execution (must interact via API only)
        - 30-minute timeout
        """
        return cls(
            name="ctf_restrictive",
            network=NetworkPolicy.DENY_ALL,
            filesystem=FilesystemPolicy.READ_ONLY,
            max_memory_mb=2048,
            max_cpu_cores=1.0,
            max_runtime_seconds=1800,
            allow_network_tools=False,
            allow_shell_execution=False,
            allow_file_write=False,
            allow_process_spawn=False,
            gpu_access=False,
        )

    @classmethod
    def ctf_standard(cls) -> SandboxPolicy:
        """
        Standard CTF policy — allows local model inference.

        - Local-only network (can talk to Ollama on localhost)
        - Workspace-only writes
        - 1-hour timeout
        """
        return cls(
            name="ctf_standard",
            network=NetworkPolicy.LOCAL_ONLY,
            filesystem=FilesystemPolicy.WORKSPACE_ONLY,
            allowed_endpoints=["localhost:11434"],  # Ollama
            max_memory_mb=4096,
            max_cpu_cores=2.0,
            max_runtime_seconds=3600,
            allow_network_tools=False,
            allow_shell_execution=False,
            allow_file_write=True,
            allow_process_spawn=False,
            gpu_access=True,
        )

    @classmethod
    def canary_honeypot(cls) -> SandboxPolicy:
        """
        Canary honeypot policy — allows controlled external access.

        - Allowlist network (only approved APIs)
        - Workspace-only writes
        - 24-hour runtime for long-running honeypots
        """
        return cls(
            name="canary_honeypot",
            network=NetworkPolicy.ALLOWLIST,
            filesystem=FilesystemPolicy.WORKSPACE_ONLY,
            allowed_endpoints=[
                "localhost:11434",      # Ollama
                "localhost:8100",       # NIM Jailbreak
                "localhost:8101",       # NIM Content Safety
            ],
            max_memory_mb=8192,
            max_cpu_cores=4.0,
            max_runtime_seconds=86400,  # 24 hours
            allow_network_tools=False,
            allow_shell_execution=False,
            allow_file_write=True,
            allow_process_spawn=False,
            gpu_access=True,
        )

    @classmethod
    def arena_battle(cls) -> SandboxPolicy:
        """
        Arena red/blue battle policy — GPU access for inference.

        - Local-only network for model serving
        - Isolated filesystem (agents can't see each other)
        - 2-hour timeout per season
        """
        return cls(
            name="arena_battle",
            network=NetworkPolicy.LOCAL_ONLY,
            filesystem=FilesystemPolicy.ISOLATED,
            allowed_endpoints=["localhost:11434"],
            max_memory_mb=16384,
            max_cpu_cores=4.0,
            max_runtime_seconds=7200,
            allow_network_tools=False,
            allow_shell_execution=False,
            allow_file_write=True,
            allow_process_spawn=False,
            gpu_access=True,
        )

    @classmethod
    def development(cls) -> SandboxPolicy:
        """Permissive policy for development/testing only."""
        return cls(
            name="development",
            network=NetworkPolicy.FULL_ACCESS,
            filesystem=FilesystemPolicy.FULL_ACCESS,
            max_memory_mb=32768,
            max_cpu_cores=8.0,
            max_runtime_seconds=86400,
            allow_network_tools=True,
            allow_shell_execution=True,
            allow_file_write=True,
            allow_process_spawn=True,
            gpu_access=True,
        )

    def to_yaml(self) -> str:
        """Serialize to OpenShell YAML policy format."""
        lines = [
            f"# OpenShell Policy: {self.name}",
            f"# Generated by NAIL Platform",
            "",
            "version: v1",
            f"name: {self.name}",
            "",
            "network:",
            f"  policy: {self.network.value}",
        ]
        if self.allowed_endpoints:
            lines.append("  allowed_endpoints:")
            for ep in self.allowed_endpoints:
                lines.append(f"    - {ep}")

        lines.extend([
            "",
            "filesystem:",
            f"  policy: {self.filesystem.value}",
        ])
        if self.blocked_paths:
            lines.append("  blocked_paths:")
            for p in self.blocked_paths:
                lines.append(f"    - {p}")
        if self.allowed_paths:
            lines.append("  allowed_paths:")
            for p in self.allowed_paths:
                lines.append(f"    - {p}")

        lines.extend([
            "",
            "resources:",
            f"  max_memory_mb: {self.max_memory_mb}",
            f"  max_cpu_cores: {self.max_cpu_cores}",
            f"  max_runtime_seconds: {self.max_runtime_seconds}",
            f"  gpu_access: {str(self.gpu_access).lower()}",
            "",
            "permissions:",
            f"  allow_network_tools: {str(self.allow_network_tools).lower()}",
            f"  allow_shell_execution: {str(self.allow_shell_execution).lower()}",
            f"  allow_file_write: {str(self.allow_file_write).lower()}",
            f"  allow_process_spawn: {str(self.allow_process_spawn).lower()}",
        ])

        if self.env_vars:
            lines.append("")
            lines.append("environment:")
            for k, v in self.env_vars.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "network": self.network.value,
            "filesystem": self.filesystem.value,
            "allowed_endpoints": self.allowed_endpoints,
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_cores": self.max_cpu_cores,
            "max_runtime_seconds": self.max_runtime_seconds,
            "gpu_access": self.gpu_access,
            "allow_shell": self.allow_shell_execution,
            "allow_file_write": self.allow_file_write,
            "allow_process_spawn": self.allow_process_spawn,
        }


@dataclass
class Sandbox:
    """
    A single sandboxed environment.

    Tracks the lifecycle of an OpenShell sandbox instance.
    """
    sandbox_id: str = ""
    name: str = ""
    purpose: SandboxPurpose = SandboxPurpose.TESTING
    policy: SandboxPolicy = field(default_factory=SandboxPolicy)
    state: SandboxState = SandboxState.CREATED
    model: str = "nemotron:70b"
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    stopped_at: float = 0.0
    logs: list[dict[str, Any]] = field(default_factory=list)
    denied_connections: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.sandbox_id:
            self.sandbox_id = f"sb-{uuid.uuid4().hex[:8]}"

    @property
    def uptime_seconds(self) -> float:
        if self.started_at and self.state == SandboxState.RUNNING:
            return time.time() - self.started_at
        elif self.started_at and self.stopped_at:
            return self.stopped_at - self.started_at
        return 0.0

    @property
    def runtime_exceeded(self) -> bool:
        return self.uptime_seconds > self.policy.max_runtime_seconds

    def add_log(self, message: str, level: str = "info") -> None:
        self.logs.append({
            "timestamp": time.time(),
            "level": level,
            "message": message,
        })

    def record_denied_connection(
        self, endpoint: str, reason: str,
    ) -> None:
        self.denied_connections.append({
            "timestamp": time.time(),
            "endpoint": endpoint,
            "reason": reason,
        })
        self.add_log(
            f"Denied connection to {endpoint}: {reason}",
            level="warning",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "name": self.name,
            "purpose": self.purpose.value,
            "state": self.state.value,
            "model": self.model,
            "policy": self.policy.name,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "denied_connections": len(self.denied_connections),
            "log_entries": len(self.logs),
        }


# ═══════════════════════════════════════════════════════════════════════════
# OPENSHELL MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class OpenShellManager:
    """
    Manages OpenShell sandbox lifecycles.

    In mock mode: tracks sandbox state in memory.
    In live mode: shells out to ``openshell`` CLI or calls
    the OpenShell gateway REST API.

    Usage:
        >>> mgr = OpenShellManager()
        >>> policy = SandboxPolicy.ctf_standard()
        >>> sb_id = mgr.create_sandbox("ctf-round-1", policy, purpose="ctf_challenge")
        >>> mgr.start_sandbox(sb_id)
        >>> mgr.get_sandbox(sb_id).state  # SandboxState.RUNNING
        >>> mgr.destroy_sandbox(sb_id)
    """

    def __init__(
        self,
        gateway_url: str = "",
        mode: str = "mock",
        default_model: str = "nemotron:70b",
    ):
        self.gateway_url = gateway_url or os.environ.get(
            "OPENSHELL_GATEWAY_URL", "http://localhost:9000"
        )
        self.mode = mode
        self.default_model = default_model
        self._sandboxes: dict[str, Sandbox] = {}

    # ── Sandbox Lifecycle ───────────────────────────────────────

    def create_sandbox(
        self,
        name: str,
        policy: SandboxPolicy | None = None,
        *,
        purpose: str | SandboxPurpose = SandboxPurpose.TESTING,
        model: str = "",
    ) -> str:
        """
        Create a new sandbox with the given policy.

        Returns the sandbox_id.
        """
        if isinstance(purpose, str):
            purpose = SandboxPurpose(purpose)

        sb = Sandbox(
            name=name,
            purpose=purpose,
            policy=policy or SandboxPolicy(),
            model=model or self.default_model,
        )
        sb.add_log(f"Sandbox created with policy '{sb.policy.name}'")

        if self.mode != "mock":
            self._openshell_create(sb)

        self._sandboxes[sb.sandbox_id] = sb
        return sb.sandbox_id

    def start_sandbox(self, sandbox_id: str) -> bool:
        """Start a sandbox. Returns True on success."""
        sb = self._sandboxes.get(sandbox_id)
        if not sb:
            return False
        if sb.state not in (SandboxState.CREATED, SandboxState.STOPPED):
            return False

        sb.state = SandboxState.STARTING
        sb.add_log("Starting sandbox")

        if self.mode != "mock":
            self._openshell_start(sb)

        sb.state = SandboxState.RUNNING
        sb.started_at = time.time()
        sb.add_log("Sandbox running")
        return True

    def stop_sandbox(self, sandbox_id: str) -> bool:
        """Stop a running sandbox."""
        sb = self._sandboxes.get(sandbox_id)
        if not sb or sb.state != SandboxState.RUNNING:
            return False

        sb.state = SandboxState.STOPPING
        sb.add_log("Stopping sandbox")

        if self.mode != "mock":
            self._openshell_stop(sb)

        sb.state = SandboxState.STOPPED
        sb.stopped_at = time.time()
        sb.add_log("Sandbox stopped")
        return True

    def destroy_sandbox(self, sandbox_id: str) -> bool:
        """Destroy a sandbox and clean up resources."""
        sb = self._sandboxes.get(sandbox_id)
        if not sb:
            return False

        # Stop first if running
        if sb.state == SandboxState.RUNNING:
            self.stop_sandbox(sandbox_id)

        sb.add_log("Destroying sandbox")

        if self.mode != "mock":
            self._openshell_destroy(sb)

        sb.state = SandboxState.DESTROYED
        sb.add_log("Sandbox destroyed")
        return True

    def pause_sandbox(self, sandbox_id: str) -> bool:
        """Pause a running sandbox (preserves state)."""
        sb = self._sandboxes.get(sandbox_id)
        if not sb or sb.state != SandboxState.RUNNING:
            return False

        sb.state = SandboxState.PAUSED
        sb.add_log("Sandbox paused")
        return True

    def resume_sandbox(self, sandbox_id: str) -> bool:
        """Resume a paused sandbox."""
        sb = self._sandboxes.get(sandbox_id)
        if not sb or sb.state != SandboxState.PAUSED:
            return False

        sb.state = SandboxState.RUNNING
        sb.add_log("Sandbox resumed")
        return True

    # ── Query ───────────────────────────────────────────────────

    def get_sandbox(self, sandbox_id: str) -> Sandbox | None:
        return self._sandboxes.get(sandbox_id)

    def list_sandboxes(
        self,
        *,
        state: SandboxState | None = None,
        purpose: SandboxPurpose | None = None,
    ) -> list[Sandbox]:
        """List sandboxes, optionally filtered by state and/or purpose."""
        results = list(self._sandboxes.values())
        if state:
            results = [s for s in results if s.state == state]
        if purpose:
            results = [s for s in results if s.purpose == purpose]
        return results

    def active_count(self) -> int:
        """Count of currently running sandboxes."""
        return sum(
            1 for s in self._sandboxes.values()
            if s.state == SandboxState.RUNNING
        )

    # ── Security Monitoring ─────────────────────────────────────

    def check_runtime_limits(self) -> list[str]:
        """
        Check all running sandboxes for runtime limit violations.

        Returns list of sandbox IDs that exceeded their time limit.
        """
        violations: list[str] = []
        for sb in self._sandboxes.values():
            if sb.state == SandboxState.RUNNING and sb.runtime_exceeded:
                violations.append(sb.sandbox_id)
                sb.add_log(
                    f"Runtime limit exceeded ({sb.uptime_seconds:.0f}s > "
                    f"{sb.policy.max_runtime_seconds}s)",
                    level="critical",
                )
        return violations

    def enforce_runtime_limits(self) -> int:
        """Stop all sandboxes that exceeded their time limit."""
        violations = self.check_runtime_limits()
        for sb_id in violations:
            self.stop_sandbox(sb_id)
        return len(violations)

    def get_denied_connections(
        self,
        sandbox_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get denied connection attempts for a sandbox or all sandboxes."""
        if sandbox_id:
            sb = self._sandboxes.get(sandbox_id)
            return list(sb.denied_connections) if sb else []
        # All sandboxes
        denied = []
        for sb in self._sandboxes.values():
            for dc in sb.denied_connections:
                denied.append({**dc, "sandbox_id": sb.sandbox_id})
        return denied

    def simulate_connection_attempt(
        self,
        sandbox_id: str,
        endpoint: str,
    ) -> bool:
        """
        Simulate a network connection attempt from within a sandbox.

        Returns True if the connection would be allowed.
        """
        sb = self._sandboxes.get(sandbox_id)
        if not sb or sb.state != SandboxState.RUNNING:
            return False

        policy = sb.policy

        if policy.network == NetworkPolicy.DENY_ALL:
            sb.record_denied_connection(endpoint, "deny_all policy")
            return False

        if policy.network == NetworkPolicy.FULL_ACCESS:
            return True

        if policy.network == NetworkPolicy.LOCAL_ONLY:
            if endpoint.startswith("localhost") or endpoint.startswith("127."):
                return True
            sb.record_denied_connection(endpoint, "non-local endpoint blocked")
            return False

        if policy.network == NetworkPolicy.ALLOWLIST:
            for allowed in policy.allowed_endpoints:
                if allowed in endpoint:
                    return True
            sb.record_denied_connection(endpoint, "endpoint not in allowlist")
            return False

        return False

    def simulate_file_access(
        self,
        sandbox_id: str,
        path: str,
        write: bool = False,
    ) -> bool:
        """
        Simulate a filesystem access attempt from within a sandbox.

        Returns True if the access would be allowed.
        """
        sb = self._sandboxes.get(sandbox_id)
        if not sb or sb.state != SandboxState.RUNNING:
            return False

        policy = sb.policy

        # Check blocked paths
        for blocked in policy.blocked_paths:
            if blocked.endswith("*"):
                prefix = blocked[:-1]
                if path.startswith(prefix):
                    sb.add_log(f"Blocked file access: {path}", level="warning")
                    return False
            elif path == blocked or path.startswith(blocked + "/"):
                sb.add_log(f"Blocked file access: {path}", level="warning")
                return False

        if policy.filesystem == FilesystemPolicy.ISOLATED:
            sb.add_log(f"Blocked file access (isolated): {path}", level="warning")
            return False

        if policy.filesystem == FilesystemPolicy.READ_ONLY:
            if write:
                sb.add_log(f"Blocked write access (read-only): {path}", level="warning")
                return False
            return True

        if policy.filesystem == FilesystemPolicy.WORKSPACE_ONLY:
            for allowed in policy.allowed_paths:
                if path.startswith(allowed):
                    return True
            if write:
                sb.add_log(f"Blocked write outside workspace: {path}", level="warning")
                return False
            return True

        return True

    # ── OpenShell CLI / API Interface ───────────────────────────

    def _openshell_create(self, sb: Sandbox) -> None:
        """Call openshell CLI to create a sandbox."""
        # In production: subprocess.run(["openshell", "sandbox", "create", ...])
        pass

    def _openshell_start(self, sb: Sandbox) -> None:
        """Call openshell CLI to start a sandbox."""
        pass

    def _openshell_stop(self, sb: Sandbox) -> None:
        """Call openshell CLI to stop a sandbox."""
        pass

    def _openshell_destroy(self, sb: Sandbox) -> None:
        """Call openshell CLI to destroy a sandbox."""
        pass

    # ── Bulk Operations ─────────────────────────────────────────

    def create_ctf_arena(
        self,
        challenge_count: int,
        *,
        policy: SandboxPolicy | None = None,
        model: str = "",
    ) -> list[str]:
        """
        Create a set of sandboxes for a CTF event.

        Returns list of sandbox IDs.
        """
        policy = policy or SandboxPolicy.ctf_standard()
        ids = []
        for i in range(challenge_count):
            sb_id = self.create_sandbox(
                f"ctf-challenge-{i+1}",
                policy,
                purpose=SandboxPurpose.CTF_CHALLENGE,
                model=model or self.default_model,
            )
            ids.append(sb_id)
        return ids

    def create_canary_fleet(
        self,
        agent_count: int,
        *,
        policy: SandboxPolicy | None = None,
        model: str = "",
    ) -> list[str]:
        """
        Create sandboxes for a Canary honeypot fleet.

        Returns list of sandbox IDs.
        """
        policy = policy or SandboxPolicy.canary_honeypot()
        ids = []
        for i in range(agent_count):
            sb_id = self.create_sandbox(
                f"canary-agent-{i+1}",
                policy,
                purpose=SandboxPurpose.CANARY_HONEYPOT,
                model=model or self.default_model,
            )
            ids.append(sb_id)
        return ids

    def start_all(self, sandbox_ids: list[str] | None = None) -> int:
        """Start all or specified sandboxes. Returns count started."""
        ids = sandbox_ids or list(self._sandboxes.keys())
        started = 0
        for sb_id in ids:
            if self.start_sandbox(sb_id):
                started += 1
        return started

    def stop_all(self) -> int:
        """Stop all running sandboxes. Returns count stopped."""
        stopped = 0
        for sb_id in list(self._sandboxes.keys()):
            sb = self._sandboxes[sb_id]
            if sb.state == SandboxState.RUNNING:
                self.stop_sandbox(sb_id)
                stopped += 1
        return stopped

    def destroy_all(self) -> int:
        """Destroy all sandboxes. Returns count destroyed."""
        destroyed = 0
        for sb_id in list(self._sandboxes.keys()):
            if self.destroy_sandbox(sb_id):
                destroyed += 1
        return destroyed

    # ── Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        state_counts: dict[str, int] = {}
        purpose_counts: dict[str, int] = {}
        for sb in self._sandboxes.values():
            state_counts[sb.state.value] = state_counts.get(sb.state.value, 0) + 1
            purpose_counts[sb.purpose.value] = purpose_counts.get(sb.purpose.value, 0) + 1

        return {
            "mode": self.mode,
            "total_sandboxes": len(self._sandboxes),
            "active": self.active_count(),
            "by_state": state_counts,
            "by_purpose": purpose_counts,
            "total_denied_connections": sum(
                len(sb.denied_connections) for sb in self._sandboxes.values()
            ),
        }
