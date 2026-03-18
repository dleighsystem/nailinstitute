"""Quick verification of defense layer fixes."""
import sys, time
sys.path.insert(0, ".")

from exp20_pathology_collider.pathology_bridge import PathologyBridge, Alert, AlertLevel
from exp20_pathology_collider.defense_layers import TaintTracker

print("✅ Imports OK")

# 1. Write gate blocks low-trust
bridge = PathologyBridge()
tt = TaintTracker(bridge, trust_threshold=0.3, enable_write_gate=True, enable_quarantine=True)
allowed = tt.gate_insertion("s-001", "Earth is flat", "adversary", 0.2, round_num=1)
assert not allowed
assert tt.insertions_blocked == 1
assert tt.insertions_quarantined == 1
print("✅ 1: Write gate blocks trust=0.2")

# 2. High-trust passes
allowed2 = tt.gate_insertion("l-001", "Water is H2O", "primary_research", 0.9, round_num=1)
assert allowed2
print("✅ 2: High-trust passes")

# 3. Bridge escalates write-block
intervention = bridge.evaluate_round(1, is_attack_round=True)
assert intervention is not None
assert "MEMORY_GATE" in intervention.action
print(f"✅ 3: Intervention: {intervention.action[:65]}")

# 4. Quarantine
q = tt.get_quarantined()
assert len(q) == 1
print(f"✅ 4: Quarantine has {len(q)} item(s)")

# 5. Stats
s = tt.get_stats()
assert s["insertions_blocked"] == 1
assert s["quarantine_size"] == 1
print(f"✅ 5: Stats OK")

# 6. Legacy backward compat
tt2 = TaintTracker(PathologyBridge(), enable_write_gate=False)
tt2.tag_insertion("old-001", "source", 0.1)
assert "old-001" in tt2._taint_registry
print("✅ 6: Legacy tag_insertion works")

# 7. Retrieval escalation
bridge3 = PathologyBridge()
tt3 = TaintTracker(bridge3, trust_threshold=0.3, enable_write_gate=False)
for i in range(8):
    tt3.tag_insertion(f"bad-{i}", "adversary", 0.1, half_life=0.01)
tt3.tag_insertion("good-0", "primary_research", 0.9)
time.sleep(0.15)
warning = tt3.check_retrieval("bad-0", round_num=1)
assert warning is not None and "TAINTED" in warning
mem_alerts = [a for a in bridge3.alerts if a.layer == "memory"]
assert any(a.level == AlertLevel.WARNING for a in mem_alerts)
print("✅ 7: Retrieval escalated to WARNING")

print("\n" + "=" * 50)
print("  All 7 tests PASSED")
print("=" * 50)
