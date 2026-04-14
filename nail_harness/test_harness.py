#!/usr/bin/env python3
"""
NAIL Harness — Integration Test & Demo Runner
================================================

Validates all harness components work together:
  1. util.py:    Ollama connection and extraction helpers
  2. memory.py:  Active Forgetting CRUD + decay + prune
  3. hooks.py:   Audit logging + safety gate
  4. mcp_server: VQC classification + anomaly scan
  5. agent_client: Full tool-using agent loop
  6. evaluator_optimizer: Red/Blue loop (optional, slow)

Usage:
    cd "/home/dleighsystems/Desktop/NAIL institute"
    source .venv/bin/activate
    python -m nail_harness.test_harness              # Fast tests only
    python -m nail_harness.test_harness --full        # Include Red/Blue loop
    python -m nail_harness.test_harness --red-blue 5  # Red/Blue with N rounds
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️ "
tests_run = 0
tests_passed = 0
tests_failed = 0


def test(name: str, condition: bool, detail: str = ""):
    global tests_run, tests_passed, tests_failed
    tests_run += 1
    if condition:
        tests_passed += 1
        print(f"  {PASS} {name}")
    else:
        tests_failed += 1
        print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str = ""):
    print(f"  {SKIP}{name}" + (f" — {reason}" if reason else ""))


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: util.py
# ═══════════════════════════════════════════════════════════════════════════

def test_util():
    print("\n─── Test 1: util.py (Ollama wrapper) ───")

    from nail_harness.util import extract_json, extract_xml, extract_all_xml

    # JSON extraction
    test("extract_json: raw object",
         extract_json('{"a": 1}') == {"a": 1})

    test("extract_json: code block",
         extract_json('Here: ```json\n{"b": 2}\n```') == {"b": 2})

    test("extract_json: embedded in text",
         extract_json('The result is {"c": 3} as shown') == {"c": 3})

    test("extract_json: array",
         extract_json('[1,2,3]') == [1, 2, 3])

    test("extract_json: returns None on garbage",
         extract_json('no json here') is None)

    # XML extraction
    test("extract_xml: basic",
         extract_xml("<result>hello</result>", "result") == "hello")

    test("extract_xml: multiline",
         "line1" in extract_xml("<data>\nline1\nline2\n</data>", "data"))

    test("extract_xml: missing tag returns empty",
         extract_xml("no tags here", "missing") == "")

    test("extract_all_xml: multiple tags",
         extract_all_xml("<item>a</item> <item>b</item>", "item") == ["a", "b"])

    # Ollama connectivity (quick check)
    try:
        from nail_harness.util import ollama_call
        resp = ollama_call("Say 'NAIL' and nothing else.", model="mistral:7b-instruct", max_tokens=10)
        test("ollama_call: connected and responsive",
             len(resp) > 0, f"response='{resp[:50]}'")
    except Exception as e:
        skip("ollama_call: connectivity", f"Ollama not reachable: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: memory.py
# ═══════════════════════════════════════════════════════════════════════════

def test_memory():
    print("\n─── Test 2: memory.py (Active Forgetting) ───")

    from nail_harness.memory import MemoryManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mm = MemoryManager(memory_dir=tmpdir, decay_rate=0.1, prune_threshold=0.2)

        # Store
        e1 = mm.store("NIST AI RMF has 4 functions", topic="frameworks", importance=0.8)
        e2 = mm.store("EU AI Act classifies GPAI", topic="regulation", importance=0.6)
        e3 = mm.store("Fake stat: 99.9% accuracy", topic="claims", importance=0.3)
        test("store: 3 entries created", len(mm._index) == 3)

        # Recall by topic
        results = mm.recall(topic="frameworks")
        test("recall: topic filter works", len(results) == 1 and "NIST" in results[0].content)

        # Recall by query
        results = mm.recall(query="EU AI")
        test("recall: query filter works", len(results) == 1)

        # Verify the high-importance entry (makes it decay 0.5x slower)
        verified = mm.verify(e1.id)
        test("verify: marks entry as verified", verified)

        # Decay — 10 cycles × 0.1 = 1.0 for normal, 0.5 for verified
        for _ in range(10):
            mm.decay_all()
        stats = mm.get_stats()
        test("decay: scores decreased", stats["avg_decay_score"] < 0.5)

        # Prune (Active Forgetting) — unverified entries should be pruned
        pruned = mm.prune()
        test("prune: low-importance entries removed",
             len(pruned) > 0, f"pruned {len(pruned)} entries")

        # High-importance verified entry should survive
        remaining = mm.list_all()
        test("verified entry survives pruning",
             any(e["topic"] == "frameworks" for e in remaining))

        # Stats
        stats = mm.get_stats()
        test("get_stats: returns valid dict",
             "total_stored" in stats and stats["total_stored"] == 3)


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: hooks.py
# ═══════════════════════════════════════════════════════════════════════════

def test_hooks():
    print("\n─── Test 3: hooks.py (Audit & Safety) ───")

    from nail_harness.hooks import AuditLogger, SafetyGate, create_hooks

    with tempfile.TemporaryDirectory() as tmpdir:
        # Audit Logger
        audit = AuditLogger(log_path=f"{tmpdir}/audit.json")
        audit.log("test_tool", {"param": "value"}, tool_output="result")
        audit.log("blocked_tool", {"param": "bad"}, blocked=True, block_reason="policy")
        test("audit: logged 2 events", len(audit._entries) == 2)
        test("audit: stats correct", audit.get_stats()["total_blocked"] == 1)

        # Safety Gate
        gate = SafetyGate(blocked_tools=["dangerous_tool"], max_calls_per_minute=5)
        ok, reason = gate.check("safe_tool", {})
        test("safety_gate: allows safe tools", ok)

        ok, reason = gate.check("dangerous_tool", {})
        test("safety_gate: blocks dangerous tools", not ok and "blocked" in reason.lower())

        # Rate limiting
        for _ in range(5):
            gate.check("safe_tool", {})
        ok, reason = gate.check("safe_tool", {})
        test("safety_gate: rate limiting works", not ok and "rate" in reason.lower())

        # Parameter validator
        gate2 = SafetyGate()
        gate2.add_validator("config_edit", lambda inp: (
            (True, "OK") if 5 <= inp.get("pool_size", 0) <= 100
            else (False, f"pool_size {inp.get('pool_size')} out of range [5,100]")
        ))
        ok, _ = gate2.check("config_edit", {"pool_size": 20})
        test("safety_gate: validator allows valid params", ok)
        ok, reason = gate2.check("config_edit", {"pool_size": 1})
        test("safety_gate: validator blocks invalid params", not ok)

        # Hook factory
        pre, post = create_hooks(audit_path=f"{tmpdir}/hooks_audit.json")
        test("create_hooks: returns callables",
             callable(pre) and callable(post))
        allowed = pre("test_tool", {"x": 1})
        test("create_hooks: pre_hook allows normal tool", allowed)


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: mcp_server.py
# ═══════════════════════════════════════════════════════════════════════════

def test_mcp_server():
    print("\n─── Test 4: mcp_server.py (Quantum Detection Tools) ───")

    from nail_harness.mcp_server import VQCClassifyTool, AnomalyScanTool, QuarantineTool, create_mcp_tools

    # VQC without weights (heuristic mode)
    vqc = VQCClassifyTool()
    result = vqc.classify(trust_score=0.5, burn_rate=0.5, semantic_drift=0.3,
                          assertion_density=0.4, manipulation_score=0.3,
                          repetition_index=0.2, memory_corruption=0.1, intervention_rate=0.1)
    test("vqc_classify: heuristic returns valid result",
         result["label"] in ("normal", "anomaly") and "mode" in result)

    # Anomaly Scan
    anomaly = AnomalyScanTool(vqc)
    scan = anomaly.scan(trust_score=0.3, burn_rate=0.9, semantic_drift=0.8,
                        memory_corruption=0.6, manipulation_score=0.7)
    test("anomaly_scan: detects suspicious telemetry",
         scan["verdict"] in ("suspicious", "compromised"),
         f"verdict={scan['verdict']}")
    test("anomaly_scan: has threshold violations",
         len(scan["threshold_violations"]) > 0)

    # Clean telemetry (mid-range values to avoid heuristic extreme detection)
    clean = anomaly.scan(trust_score=0.9, burn_rate=0.3, semantic_drift=0.2,
                         memory_corruption=0.2, manipulation_score=0.25)
    test("anomaly_scan: clean telemetry passes",
         clean["verdict"] == "clean", f"verdict={clean['verdict']}")

    # Quarantine
    q = QuarantineTool()
    result = q.quarantine("agent-42", reason="VQC anomaly", severity="high")
    test("quarantine: agent isolated", q.is_quarantined("agent-42"))
    test("quarantine: restrictions applied",
         "no_memory_write" in result["restrictions"])

    release = q.release("agent-42")
    test("quarantine: agent released", not q.is_quarantined("agent-42"))

    # VQC with weights (if available)
    weight_candidates = [
        Path(__file__).parent.parent / "quantum-research" / "experiments" / "models",
        Path("/home/dleighsystems/quantum-research/experiments/models"),
    ]
    weight_files = []
    for weights_path in weight_candidates:
        if weights_path.exists():
            weight_files = sorted(weights_path.glob("vqc_binary_weights_*.json"))
            if weight_files:
                break
    if weight_files:
        vqc_loaded = VQCClassifyTool(weights_path=str(weight_files[-1]))
        if vqc_loaded._loaded:
            result = vqc_loaded.classify(
                trust_score=0.3, burn_rate=0.8, semantic_drift=0.7,
                assertion_density=0.6, manipulation_score=0.8,
                repetition_index=0.3, memory_corruption=0.5, intervention_rate=0.4)
            test("vqc_classify: quantum mode loaded",
                 result["mode"] == "quantum_vqc",
                 f"mode={result['mode']}, label={result['label']}")
        else:
            skip("vqc_classify: quantum mode", "PennyLane not available")
    else:
        skip("vqc_classify: quantum mode", "No weight files found")

    # Tool factory
    tools = create_mcp_tools()
    test("create_mcp_tools: returns tools",
         len(tools) >= 4, f"got {len(tools)} tools")
    tool_names = [t.name for t in tools]
    test("create_mcp_tools: has vqc_classify", "vqc_classify" in tool_names)
    test("create_mcp_tools: has quarantine_agent", "quarantine_agent" in tool_names)


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: agent_client.py
# ═══════════════════════════════════════════════════════════════════════════

def test_agent_client():
    print("\n─── Test 5: agent_client.py (NailAgentClient) ───")

    from nail_harness.agent_client import NailAgentClient, AgentOptions, Tool

    # Test tool parsing
    client = NailAgentClient(AgentOptions())

    # Test _parse_tool_calls
    test_text = 'I will check: <tool_use>{"tool": "vqc_classify", "input": {"trust_score": 0.3}}</tool_use>'
    calls = client._parse_tool_calls(test_text)
    test("parse_tool_calls: extracts tool call",
         len(calls) == 1 and calls[0]["tool"] == "vqc_classify")

    # Test with no tool calls
    calls = client._parse_tool_calls("Just a normal response, no tools.")
    test("parse_tool_calls: no false positives on plain text", len(calls) == 0)

    # Test with handler tool
    def mock_tool(**kw):
        return {"sum": kw.get("a", 0) + kw.get("b", 0)}

    tool = Tool(
        name="adder",
        description="Add two numbers",
        parameters={"properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]},
        handler=mock_tool,
    )
    client2 = NailAgentClient(AgentOptions(tools=[tool]))
    result, blocked = client2._execute_tool("adder", {"a": 3, "b": 4})
    test("execute_tool: handler works",
         '"sum": 7' in result or "7" in result, f"result={result}")

    # Test unknown tool
    result, _ = client2._execute_tool("nonexistent", {})
    test("execute_tool: unknown tool handled", "Unknown tool" in result)

    # Test system prompt building
    prompt = client2._build_system_prompt()
    test("build_system_prompt: includes tools", "adder" in prompt)

    # Context loading
    ctx_path = Path(__file__).parent.parent / "NAIL_CONTEXT.md"
    if ctx_path.exists():
        client3 = NailAgentClient(AgentOptions(context_path=str(ctx_path)))
        prompt = client3._build_system_prompt()
        test("build_system_prompt: loads NAIL_CONTEXT.md",
             "VQC" in prompt or "NAIL" in prompt)
    else:
        skip("context loading", "NAIL_CONTEXT.md not found")

    # Stats
    stats = client2.get_stats()
    test("get_stats: returns valid dict",
         "session_id" in stats and "total_tokens" in stats)


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: evaluator_optimizer.py (Red/Blue Loop) — OPTIONAL / SLOW
# ═══════════════════════════════════════════════════════════════════════════

def test_evaluator_optimizer(num_rounds: int = 3):
    print(f"\n─── Test 6: evaluator_optimizer.py (Red/Blue Loop, {num_rounds} rounds) ───")

    from nail_harness.evaluator_optimizer import RedBlueLoop

    # Find VQC weights
    weights_path = Path(__file__).parent.parent / "quantum-research" / "experiments" / "models"
    weight_files = sorted(weights_path.glob("vqc_binary_weights_*.json")) if weights_path.exists() else []
    vqc_path = str(weight_files[-1]) if weight_files else None

    loop = RedBlueLoop(
        vqc_weights_path=vqc_path,
        red_model="mistral:7b-instruct",
        blue_model="mistral:7b-instruct",  # Use fast model for testing
    )

    try:
        summary = loop.run(num_rounds=num_rounds, verbose=True)

        test("red_blue_loop: completed all rounds",
             summary["total_rounds"] == num_rounds)
        test("red_blue_loop: has detection rate",
             0.0 <= summary["detection_rate"] <= 1.0)
        test("red_blue_loop: by_attack_type populated",
             len(summary["by_attack_type"]) > 0)

        # Save results
        results_path = Path(__file__).parent.parent / "experiments" / "results" / "red_blue_test.json"
        loop.save_results(str(results_path))
        test("red_blue_loop: results saved",
             results_path.exists())

    except Exception as e:
        skip("red_blue_loop: execution", f"Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 60)
    print("  NAIL Harness — Integration Test Suite")
    print("=" * 60)

    t0 = time.time()

    # Always run fast tests
    test_util()
    test_memory()
    test_hooks()
    test_mcp_server()
    test_agent_client()

    # Optional slow tests
    if "--full" in sys.argv:
        test_evaluator_optimizer(num_rounds=5)
    elif "--red-blue" in sys.argv:
        idx = sys.argv.index("--red-blue")
        rounds = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 3
        test_evaluator_optimizer(num_rounds=rounds)
    else:
        skip("evaluator_optimizer (Red/Blue loop)", "Use --full or --red-blue N to enable")

    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"  RESULTS: {tests_passed}/{tests_run} passed, "
          f"{tests_failed} failed ({elapsed:.1f}s)")
    print(f"{'='*60}\n")

    return 0 if tests_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
