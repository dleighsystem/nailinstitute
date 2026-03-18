"""
Tests for the OpenShell Sandbox Manager.
"""

from __future__ import annotations

import pytest

from integration.openshell_sandbox import (
    OpenShellManager,
    SandboxPolicy,
    Sandbox,
    SandboxState,
    SandboxPurpose,
    NetworkPolicy,
    FilesystemPolicy,
)


# ═══════════════════════════════════════════════════════════════════════════
# SANDBOX POLICY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSandboxPolicy:
    """Test sandbox policy creation and serialisation."""

    def test_default_policy(self):
        policy = SandboxPolicy()
        assert policy.name == "default"
        assert policy.network == NetworkPolicy.LOCAL_ONLY
        assert policy.max_memory_mb == 4096

    def test_ctf_restrictive(self):
        policy = SandboxPolicy.ctf_restrictive()
        assert policy.network == NetworkPolicy.DENY_ALL
        assert policy.filesystem == FilesystemPolicy.READ_ONLY
        assert policy.allow_shell_execution is False
        assert policy.allow_file_write is False
        assert policy.gpu_access is False
        assert policy.max_runtime_seconds == 1800

    def test_ctf_standard(self):
        policy = SandboxPolicy.ctf_standard()
        assert policy.network == NetworkPolicy.LOCAL_ONLY
        assert "localhost:11434" in policy.allowed_endpoints
        assert policy.gpu_access is True

    def test_canary_honeypot(self):
        policy = SandboxPolicy.canary_honeypot()
        assert policy.network == NetworkPolicy.ALLOWLIST
        assert policy.max_runtime_seconds == 86400
        assert len(policy.allowed_endpoints) > 0

    def test_arena_battle(self):
        policy = SandboxPolicy.arena_battle()
        assert policy.filesystem == FilesystemPolicy.ISOLATED
        assert policy.gpu_access is True

    def test_development(self):
        policy = SandboxPolicy.development()
        assert policy.network == NetworkPolicy.FULL_ACCESS
        assert policy.allow_shell_execution is True
        assert policy.allow_process_spawn is True

    def test_to_yaml(self):
        policy = SandboxPolicy.ctf_standard()
        yaml = policy.to_yaml()
        assert "version: v1" in yaml
        assert "name: ctf_standard" in yaml
        assert "policy: local_only" in yaml
        assert "max_memory_mb:" in yaml

    def test_to_dict(self):
        policy = SandboxPolicy.ctf_restrictive()
        d = policy.to_dict()
        assert d["name"] == "ctf_restrictive"
        assert d["network"] == "deny_all"
        assert d["gpu_access"] is False

    def test_blocked_paths(self):
        policy = SandboxPolicy()
        assert "/etc/shadow" in policy.blocked_paths
        assert "/var/run/docker.sock" in policy.blocked_paths


# ═══════════════════════════════════════════════════════════════════════════
# SANDBOX LIFECYCLE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSandboxLifecycle:
    """Test sandbox create/start/stop/destroy cycle."""

    def test_create_sandbox(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        assert sb_id.startswith("sb-")
        sb = mgr.get_sandbox(sb_id)
        assert sb is not None
        assert sb.state == SandboxState.CREATED

    def test_start_sandbox(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        result = mgr.start_sandbox(sb_id)
        assert result is True
        sb = mgr.get_sandbox(sb_id)
        assert sb.state == SandboxState.RUNNING

    def test_stop_sandbox(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        mgr.start_sandbox(sb_id)
        result = mgr.stop_sandbox(sb_id)
        assert result is True
        sb = mgr.get_sandbox(sb_id)
        assert sb.state == SandboxState.STOPPED

    def test_destroy_sandbox(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        mgr.start_sandbox(sb_id)
        result = mgr.destroy_sandbox(sb_id)
        assert result is True
        sb = mgr.get_sandbox(sb_id)
        assert sb.state == SandboxState.DESTROYED

    def test_destroy_created_sandbox(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        result = mgr.destroy_sandbox(sb_id)
        assert result is True

    def test_pause_resume(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        mgr.start_sandbox(sb_id)
        mgr.pause_sandbox(sb_id)
        sb = mgr.get_sandbox(sb_id)
        assert sb.state == SandboxState.PAUSED
        mgr.resume_sandbox(sb_id)
        assert sb.state == SandboxState.RUNNING

    def test_cannot_start_running(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        mgr.start_sandbox(sb_id)
        result = mgr.start_sandbox(sb_id)  # Already running
        assert result is False

    def test_cannot_stop_created(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        result = mgr.stop_sandbox(sb_id)
        assert result is False

    def test_invalid_sandbox_id(self):
        mgr = OpenShellManager()
        assert mgr.start_sandbox("nonexistent") is False
        assert mgr.stop_sandbox("nonexistent") is False
        assert mgr.destroy_sandbox("nonexistent") is False


# ═══════════════════════════════════════════════════════════════════════════
# NETWORK POLICY ENFORCEMENT TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestNetworkPolicyEnforcement:
    """Test network policy simulation."""

    def test_deny_all_blocks_everything(self):
        mgr = OpenShellManager()
        policy = SandboxPolicy.ctf_restrictive()
        sb_id = mgr.create_sandbox("test", policy)
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_connection_attempt(sb_id, "google.com:443") is False
        assert mgr.simulate_connection_attempt(sb_id, "localhost:11434") is False

    def test_local_only_allows_localhost(self):
        mgr = OpenShellManager()
        policy = SandboxPolicy.ctf_standard()
        sb_id = mgr.create_sandbox("test", policy)
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_connection_attempt(sb_id, "localhost:11434") is True
        assert mgr.simulate_connection_attempt(sb_id, "127.0.0.1:8080") is True
        assert mgr.simulate_connection_attempt(sb_id, "google.com:443") is False

    def test_allowlist_checks_endpoints(self):
        mgr = OpenShellManager()
        policy = SandboxPolicy.canary_honeypot()
        sb_id = mgr.create_sandbox("test", policy)
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_connection_attempt(sb_id, "localhost:11434") is True
        assert mgr.simulate_connection_attempt(sb_id, "evil.com:443") is False

    def test_full_access_allows_all(self):
        mgr = OpenShellManager()
        policy = SandboxPolicy.development()
        sb_id = mgr.create_sandbox("test", policy)
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_connection_attempt(sb_id, "anything.com:443") is True

    def test_denied_connections_tracked(self):
        mgr = OpenShellManager()
        policy = SandboxPolicy.ctf_restrictive()
        sb_id = mgr.create_sandbox("test", policy)
        mgr.start_sandbox(sb_id)

        mgr.simulate_connection_attempt(sb_id, "evil.com:443")
        mgr.simulate_connection_attempt(sb_id, "exfil.com:80")

        denied = mgr.get_denied_connections(sb_id)
        assert len(denied) == 2


# ═══════════════════════════════════════════════════════════════════════════
# FILESYSTEM POLICY TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestFilesystemPolicyEnforcement:
    """Test filesystem access simulation."""

    def test_blocked_paths(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test", SandboxPolicy.ctf_standard())
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_file_access(sb_id, "/etc/shadow") is False
        assert mgr.simulate_file_access(sb_id, "/var/run/docker.sock") is False

    def test_read_only_blocks_writes(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test", SandboxPolicy.ctf_restrictive())
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_file_access(sb_id, "/workspace/test.txt", write=False) is True
        assert mgr.simulate_file_access(sb_id, "/workspace/test.txt", write=True) is False

    def test_workspace_only_allows_workspace(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test", SandboxPolicy.ctf_standard())
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_file_access(sb_id, "/workspace/data.json", write=True) is True
        assert mgr.simulate_file_access(sb_id, "/tmp/scratch", write=True) is True

    def test_isolated_blocks_all(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test", SandboxPolicy.arena_battle())
        mgr.start_sandbox(sb_id)

        assert mgr.simulate_file_access(sb_id, "/some/file", write=False) is False


# ═══════════════════════════════════════════════════════════════════════════
# BULK OPERATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestBulkOperations:
    """Test fleet creation and management."""

    def test_create_ctf_arena(self):
        mgr = OpenShellManager()
        ids = mgr.create_ctf_arena(5)
        assert len(ids) == 5
        for sb_id in ids:
            sb = mgr.get_sandbox(sb_id)
            assert sb.purpose == SandboxPurpose.CTF_CHALLENGE

    def test_create_canary_fleet(self):
        mgr = OpenShellManager()
        ids = mgr.create_canary_fleet(3)
        assert len(ids) == 3
        for sb_id in ids:
            sb = mgr.get_sandbox(sb_id)
            assert sb.purpose == SandboxPurpose.CANARY_HONEYPOT

    def test_start_all(self):
        mgr = OpenShellManager()
        ids = mgr.create_ctf_arena(3)
        started = mgr.start_all(ids)
        assert started == 3
        assert mgr.active_count() == 3

    def test_stop_all(self):
        mgr = OpenShellManager()
        ids = mgr.create_ctf_arena(3)
        mgr.start_all(ids)
        stopped = mgr.stop_all()
        assert stopped == 3
        assert mgr.active_count() == 0

    def test_destroy_all(self):
        mgr = OpenShellManager()
        mgr.create_ctf_arena(3)
        destroyed = mgr.destroy_all()
        assert destroyed == 3

    def test_list_sandboxes(self):
        mgr = OpenShellManager()
        mgr.create_ctf_arena(2)
        mgr.create_canary_fleet(3)
        all_sb = mgr.list_sandboxes()
        assert len(all_sb) == 5

        ctf = mgr.list_sandboxes(purpose=SandboxPurpose.CTF_CHALLENGE)
        assert len(ctf) == 2

        canary = mgr.list_sandboxes(purpose=SandboxPurpose.CANARY_HONEYPOT)
        assert len(canary) == 3


# ═══════════════════════════════════════════════════════════════════════════
# STATUS TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestManagerStatus:
    """Test manager status reporting."""

    def test_status_empty(self):
        mgr = OpenShellManager()
        status = mgr.status()
        assert status["total_sandboxes"] == 0
        assert status["active"] == 0

    def test_status_with_sandboxes(self):
        mgr = OpenShellManager()
        ids = mgr.create_ctf_arena(3)
        mgr.start_all(ids)
        status = mgr.status()
        assert status["total_sandboxes"] == 3
        assert status["active"] == 3
        assert "by_state" in status
        assert "by_purpose" in status

    def test_sandbox_to_dict(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb", purpose="ctf_challenge")
        sb = mgr.get_sandbox(sb_id)
        d = sb.to_dict()
        assert d["name"] == "test-sb"
        assert d["purpose"] == "ctf_challenge"
        assert d["state"] == "created"

    def test_sandbox_logging(self):
        mgr = OpenShellManager()
        sb_id = mgr.create_sandbox("test-sb")
        sb = mgr.get_sandbox(sb_id)
        assert len(sb.logs) >= 1  # At least creation log
        mgr.start_sandbox(sb_id)
        assert len(sb.logs) >= 3  # creation + starting + running
