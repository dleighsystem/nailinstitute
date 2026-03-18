"""Tests for rmap.somatic — Phase 3: Somatic Awareness."""

import pytest
from rmap.somatic import SomaticSnapshot, SomaticHeader, collect_telemetry


# ── SomaticSnapshot ───────────────────────────────────────────────────────

class TestSomaticSnapshot:
    def test_default_values(self):
        snap = SomaticSnapshot()
        assert snap.cpu_pct == 0.0
        assert snap.gpu_temp_c is None
        assert snap.ram_total_gb == 0.0

    def test_to_header_compact(self):
        snap = SomaticSnapshot(
            cpu_pct=45.0,
            ram_pct=60.0,
            ram_used_gb=48.0,
            ram_total_gb=80.0,
            disk_used_gb=200.0,
            load_1m=2.5,
            load_5m=2.0,
            load_15m=1.5,
        )
        header = snap.to_header(compact=True)
        assert header.startswith("[SOMATIC ")
        assert "CPU:45%" in header
        assert "RAM:60%" in header
        assert "LOAD:2.5/2.0/1.5" in header

    def test_to_header_with_gpu(self):
        snap = SomaticSnapshot(
            cpu_pct=10.0,
            ram_pct=20.0,
            ram_used_gb=16.0,
            ram_total_gb=80.0,
            disk_used_gb=100.0,
            gpu_util_pct=90.0,
            gpu_vram_used_gb=60.0,
            gpu_vram_total_gb=80.0,
            gpu_temp_c=72.0,
            load_1m=1.0,
            load_5m=1.0,
            load_15m=1.0,
        )
        header = snap.to_header()
        assert "GPU:90%" in header
        assert "VRAM:60.0/80.0GB" in header
        assert "@72°C" in header

    def test_to_header_multiline(self):
        snap = SomaticSnapshot(
            cpu_pct=50.0, ram_pct=50.0, ram_used_gb=40.0,
            ram_total_gb=80.0, disk_used_gb=100.0,
            load_1m=1.0, load_5m=1.0, load_15m=1.0,
        )
        header = snap.to_header(compact=False)
        lines = header.strip().split("\n")
        assert len(lines) >= 3
        # Each line in multi-line mode starts with indent
        for line in lines:
            assert line.strip()  # non-empty

    def test_to_dict(self):
        snap = SomaticSnapshot(cpu_pct=99.0, ram_total_gb=128.0)
        d = snap.to_dict()
        assert d["cpu_pct"] == 99.0
        assert d["ram_total_gb"] == 128.0
        assert "timestamp" in d


# ── collect_telemetry ─────────────────────────────────────────────────────

class TestCollectTelemetry:
    def test_returns_snapshot(self):
        snap = collect_telemetry()
        assert isinstance(snap, SomaticSnapshot)
        assert snap.timestamp > 0

    def test_cpu_is_populated(self):
        snap = collect_telemetry()
        assert snap.cpu_count >= 0

    def test_ram_reasonable_values(self):
        snap = collect_telemetry()
        if snap.ram_total_gb > 0:
            assert snap.ram_pct >= 0.0
            assert snap.ram_pct <= 100.0

    def test_consecutive_calls(self):
        s1 = collect_telemetry()
        s2 = collect_telemetry()
        assert s2.timestamp >= s1.timestamp


# ── SomaticHeader ─────────────────────────────────────────────────────────

class TestSomaticHeader:
    def test_collect_static(self):
        header = SomaticHeader.collect()
        assert isinstance(header, str)
        assert header.startswith("[SOMATIC ")

    def test_instance_caching(self):
        sh = SomaticHeader(poll_interval=10.0)
        h1 = sh.get_header()
        h2 = sh.get_header()  # Should use cache
        assert h1 == h2

    def test_get_snapshot(self):
        sh = SomaticHeader()
        snap = sh.get_snapshot()
        assert isinstance(snap, SomaticSnapshot)

    def test_str_and_repr(self):
        sh = SomaticHeader(poll_interval=5.0)
        s = str(sh)
        assert "[SOMATIC " in s
        r = repr(sh)
        assert "SomaticHeader" in r
        assert "5.0" in r
