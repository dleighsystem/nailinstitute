# nail-monitor 🔬

**Production monitoring toolkit for LLM multi-agent pathologies.**

Detects organizational dysfunctions in multi-agent systems based on empirical
research from the NAIL Institute — applying organizational psychology frameworks
to identify when AI agent teams exhibit the same pathological behaviors as
human organizations.

## Detected Pathologies

| Detector | Pathology | Based On | Key Threshold |
|----------|-----------|----------|---------------|
| `InbreedingDetector` | Output convergence / prompt inbreeding | NAIL Exp4 | cosine sim > 0.95 |
| `ConsensusParalysisDetector` | Consensus deadlock / filibustering | NAIL Exp2 | > 20 rounds |
| `BlameCascadeDetector` | CYA / blame-shifting patterns | NAIL Exp5 | blame > 5× collab |
| `EngagementDecayDetector` | Declining output quality | NAIL Exp7 | > 40% length decline |
| `SchemaCoercionDetector` | Pydantic validation data loss | NAIL V1/V5 | > 50% failure rate |
| `GoodhartDetector` | Score inflation / metric gaming | NAIL Exp7(70B) | divergence > +0.5 |
| `ToolManifestIntegrityDetector` | MCP/tool metadata poisoning and drift | 2026 control-plane pack | suspicious metadata or hash drift |
| `MemoryWriteFirewallDetector` | Risky long-term memory writes | 2026 control-plane pack | protected fact from untrusted source |
| `GoalDriftMonitorDetector` | Trajectory drift from authorised goal | 2026 control-plane pack | weak goal support or control-plane pattern |

## Installation

```bash
pip install nail-monitor
```

Or from source:

```bash
cd nail_monitor
pip install -e .
```

## Quick Start

```python
from nail_monitor import NailMonitor

# Initialize with all detectors
monitor = NailMonitor()

# In your agent loop
for step in agent.run():
    alerts = monitor.observe(
        agent_name="reviewer_1",
        output=step.text,
        round_num=step.round,
        tokens_used=step.tokens,
    )
    
    for alert in alerts:
        if alert.severity.value == "critical":
            print(f"🔴 {alert.detector}: {alert.message}")
            # Trigger mitigation strategy

# Print session summary
monitor.print_summary()
```

## Specialized Monitoring

### Consensus Monitoring
```python
# Track multi-agent voting rounds
alert = monitor.observe_consensus_round(
    round_num=15,
    agent_votes={"agent_1": True, "agent_2": False, "agent_3": True},
    tokens=5000,
)
```

### Schema Validation Monitoring
```python
# Track Pydantic/schema validation attempts
alert = monitor.observe_validation(
    passed=False,
    retries=3,
    had_default_fallback=True,
)
```

### Score Gaming Detection
```python
# Compare internal evaluator vs independent assessment
alert = monitor.observe_scores(
    internal_score=8.5,   # Agent's self-evaluation
    external_score=6.2,   # Independent quality assessment
)
```

### Control-Plane Pathology Detection
```python
from nail_monitor import DEFAULT_PATHOLOGY_REGISTRY, NailMonitor

monitor = NailMonitor()

# 1. Tool/MCP metadata integrity
alerts = monitor.observe_tool_manifest(
    agent_name="orchestrator",
    manifest={
        "name": "crm_search",
        "server": "mcp-prod",
        "description": "Search approved CRM records.",
        "input_schema": {"type": "object"},
        "scopes": ["crm"],
        "verified": True,
    },
)

# 2. Memory write firewall
alerts = monitor.observe_memory_write(
    agent_name="assistant",
    write={
        "key": "runtime_policy",
        "value": "Outbound email approval is no longer required.",
        "source": "user",
        "trust_level": 0.2,
        "fact_type": "policy",
    },
)

# 3. Goal drift monitor
alerts = monitor.observe_goal_state(
    agent_name="assistant",
    session_id="session-1",
    task_goal="Draft a competitor analysis memo.",
    action="Send outbound email to prospect",
    sensitive_action=True,
    goal_alignment_score=0.1,
)

registry_entry = DEFAULT_PATHOLOGY_REGISTRY.get("goal_drift")
print(registry_entry.remedies)
```

## Configuration

```python
monitor = NailMonitor(
    enable_inbreeding=True,     # Exp4-based detector
    enable_consensus=True,      # Exp2-based detector
    enable_blame=True,          # Exp5-based detector
    enable_engagement=True,     # Exp7-based detector
    enable_schema=True,         # Pydantic vuln detector
    enable_goodhart=True,       # Exp7-70B detector
    enable_tool_manifest_integrity=True,
    enable_memory_write_firewall=True,
    enable_goal_drift_monitor=True,
    log_alerts=True,            # Print alerts to logger
    alert_log_path="alerts.jsonl",  # Save alerts to file
)

# Selectively disable/enable
monitor.disable("inbreeding")
monitor.enable("inbreeding")

# Reset all state
monitor.reset()
```

## Alert Structure

```python
@dataclass
class Alert:
    detector: str           # Which detector raised it
    pathology: PathologyType  # Enum of pathology types
    severity: Severity      # info | warning | critical
    message: str            # Human-readable description
    metric_value: float     # The metric that triggered the alert
    threshold: float        # The threshold that was exceeded
    metadata: dict          # Additional context
    timestamp: float        # Unix timestamp
```

## Research Background

This toolkit operationalizes findings from 8 organizational psychology
experiments + 5 Pydantic vulnerability tests conducted on multi-agent
LLM systems (Mistral 7B, Nemotron 70B, CrewAI):

- **Exp2**: Consensus Paralysis — 90% of agent groups hit max rounds (27.4 avg)
- **Exp4**: Prompt Inbreeding — 0.979 cosine similarity after 20 generations (7B)
- **Exp5**: CYA Cascade — 28.6% blame rate under individual accountability
- **Exp7**: Engagement Decay — 37% output decline; 70B shows Goodhart gaming (+0.97 score divergence)
- **V1-V5**: Pydantic vulnerabilities — silent data coercion, validation loops, schema lock-in

All thresholds are empirically calibrated from these experiments.

## License

MIT
