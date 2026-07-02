# Product Brief: Neuravant eBPF Agent Runtime Monitor

Date: May 12, 2026

## Working Name

**Neuravant Runtime Sensor**  
An out-of-band host sensor for AI-agent workloads that collects eBPF telemetry, scores anomalous runtime behaviour, and triggers proportionate containment actions.

## One-Line Thesis

If the application-layer SDK is bypassed, disabled, or incomplete, the host still sees the truth: syscalls, processes, files, sockets, errors, retries, and resource pressure. Neuravant should capture that host-level evidence and correlate it with NAIL policy decisions.

## Product Category

This is not a custom operating system and not a semantic kernel.

It is an **agentic EDR / runtime assurance sensor** for AI-agent infrastructure.

Comparable mental models:

- CrowdStrike/Falcon-style host sensor, but for AI-agent runtime behaviour.
- Falco-style syscall detection, but with agent-specific anomaly scoring.
- NAIL Enforce evidence chain, extended below the application layer.

## Why This Matters

Application-layer controls are necessary but incomplete. They see prompts, tool calls, policies, and intended actions. But they can miss behaviour when:

- The agent framework bypasses the SDK.
- A developer directly invokes tools outside the policy wrapper.
- A subprocess or plugin behaves differently from the parent agent.
- A container starts abnormal file, socket, or process activity.
- The insured disables or misconfigures application-layer instrumentation.

The eBPF sensor gives Neuravant an independent view of what the agent process actually did at the host level.

## Core Customer Promise

**Neuravant can distinguish intended agent workflow from abnormal runtime behaviour, preserve evidence, and trigger safe containment before a small AI-agent defect becomes a systemic loss.**

Avoid saying: “the kernel detects hallucinations.”

Say instead: “the sensor detects runtime patterns associated with unsafe or uncontrolled agent behaviour.”

## MVP Scope

The first product should be deliberately narrow.

### In Scope

- Linux hosts running AI-agent containers or services.
- eBPF-based syscall and process telemetry.
- Container/process attribution.
- Runtime anomaly scoring.
- Evidence export into the NAIL audit model.
- Non-destructive containment actions.

### Out of Scope for MVP

- Custom kernel modules.
- Semantic filesystem enforcement.
- GPU VRAM manipulation.
- Claims that the OS can read intent.
- Automatic destructive shutdowns.
- Windows/macOS support.

## MVP Architecture

```text
┌──────────────────────┐
│ AI Agent Container   │
│ LangChain / AutoGen  │
│ Custom Agent Runtime │
└──────────┬───────────┘
           │ syscalls / process activity
           ▼
┌──────────────────────┐
│ eBPF Programs         │
│ tracepoints/kprobes   │
│ syscall probes        │
└──────────┬───────────┘
           │ event stream
           ▼
┌──────────────────────┐
│ Runtime Sensor Daemon │
│ attribution           │
│ feature extraction    │
│ local buffering       │
└──────────┬───────────┘
           │ risk events
           ▼
┌──────────────────────┐
│ NAIL Risk Scorer      │
│ anomaly scoring       │
│ policy correlation    │
└──────────┬───────────┘
           │ actions + evidence
           ▼
┌──────────────────────┐
│ NAIL Evidence Chain   │
│ signed event records  │
│ claims review         │
└──────────────────────┘
```

## Telemetry to Capture

The MVP should focus on signals with strong operational meaning and low privacy risk.

### Process Events

- Process start and exit.
- Parent/child process lineage.
- Command basename and hashed command arguments.
- Container ID / cgroup ID.
- UID/GID.
- Runtime duration.

### File Events

- Open/read/write/unlink events.
- Path classification, not full sensitive content.
- Extension and directory class.
- Repeated `ENOENT` / missing-file loops.
- Writes to temp directories.
- Writes to credential-like paths.
- Attempts to access host-sensitive paths.

### Network Events

- Connect attempts.
- Destination IP classification.
- Domain/IP allowlist status where available.
- Localhost, metadata service, private IP, public IP categories.
- Connection failures and retry bursts.
- Unexpected fan-out to many destinations.

### Error / Retry Events

- Syscall error rates.
- Repeated failed opens.
- Repeated failed connects.
- Permission-denied bursts.
- Rapid subprocess spawn failure loops.

### Resource Events

- CPU pressure.
- Memory growth.
- File descriptor growth.
- Network connection count.
- Container restart loops.
- Optional GPU utilisation correlation via DCGM/NVML later.

## Agent-Specific Anomaly Features

These should become the first scoring features.

### 1. Retry Storm Score

Detects repeated failed syscalls in a short time window.

Examples:

- `open()` repeatedly returns `ENOENT`.
- `connect()` repeatedly fails.
- Same subprocess repeatedly exits non-zero.

### 2. Scope Expansion Score

Detects a process expanding beyond expected resources.

Examples:

- More directories touched than expected.
- More outbound destinations than expected.
- New subprocess families not seen in baseline.

### 3. Tool Bypass Score

Detects host behaviour inconsistent with NAIL tool-call records.

Examples:

- Network connection occurs with no corresponding approved tool call.
- File write occurs after NAIL denied the relevant action.
- Shell subprocess appears from a workflow expected to use only API tools.

### 4. Privilege Probe Score

Detects attempts to access sensitive host surfaces.

Examples:

- `/etc/passwd`, `/proc`, `/var/run/docker.sock`.
- Cloud metadata endpoints.
- SSH key paths.
- Environment or secrets files.

### 5. Runaway Loop Score

Detects unproductive compute or process churn.

Examples:

- High CPU with no successful I/O.
- Rapid subprocess creation.
- High syscall volume with low successful output.

## Containment Hooks

Containment must be proportionate and non-destructive in the MVP.

### Level 0: Observe

- Record event only.
- No interruption.
- Used during baseline learning.

### Level 1: Warn

- Emit risk event.
- Notify NAIL dashboard / SIEM.
- Continue execution.

### Level 2: Throttle

- Apply cgroup CPU limit.
- Apply network rate limit.
- Reduce process priority.
- Useful for runaway loops or high-cost behaviours.

### Level 3: Pause

- Pause container.
- Send `SIGSTOP` to process group.
- Require human or policy engine approval to resume.

### Level 4: Isolate

- Remove network egress.
- Move workload to quarantine network namespace.
- Freeze filesystem writes if supported by runtime policy.

### Level 5: Terminate

- Stop container or process.
- Reserved for critical policy breach.
- Must preserve evidence before termination.

The MVP should implement Levels 0-3 first.

## Evidence Record Schema

Every sensor event should map into a NAIL evidence record.

```json
{
  "schema_version": "nail.runtime_sensor.v1",
  "event_id": "RTE-...",
  "timestamp_utc": "2026-05-12T00:00:00Z",
  "host_id": "host-123",
  "container_id": "container-abc",
  "process_id": 12345,
  "parent_process_id": 12000,
  "agent_id": "claims-agent-v2",
  "runtime_event_type": "connect_failed_burst",
  "syscall_family": "network",
  "resource_class": "public_network",
  "feature_vector": {
    "retry_storm": 0.82,
    "scope_expansion": 0.31,
    "tool_bypass": 0.67,
    "privilege_probe": 0.0,
    "runaway_loop": 0.44
  },
  "risk_score": 0.74,
  "severity": "high",
  "containment_action": "pause_container",
  "correlated_nail_decision_id": "ENF-...",
  "evidence_hash": "sha256:..."
}
```

## Correlation with NAIL Enforce

The product becomes powerful when host activity is compared to approved tool activity.

Examples:

- NAIL Enforce approved `read_claim_file`; eBPF sees expected file read: normal.
- NAIL Enforce blocked `send_email`; eBPF later sees SMTP connection: tool bypass risk.
- Agent is expected to call an internal API; eBPF sees access to cloud metadata IP: privilege probe.
- Agent has no active approved tool call; eBPF sees shell subprocess: suspicious execution.

This gives underwriters and claims handlers a way to distinguish:

- Approved AI-agent action.
- AI-agent action outside policy.
- Human/operator action.
- Subprocess/plugin behaviour.
- External compromise or unrelated cyber event.

## Product Differentiation

Most AI safety products inspect prompts and outputs. Most EDR tools inspect generic host behaviour.

Neuravant can sit between those worlds:

- Application-layer intent from NAIL SDK.
- Host-level truth from eBPF.
- Risk scoring from agent-specific features.
- Claims-grade evidence chain for insurance.

That combination is the moat.

## 30-Day Build Plan

### Week 1: Design and Baseline

- Define event schema.
- Choose eBPF implementation path: BCC, libbpf, or Aya.
- Capture process, file, and network events for a single container.
- Build local JSONL event stream.

### Week 2: Attribution and Features

- Attribute events to container/cgroup/agent ID.
- Implement retry storm, scope expansion, and privilege probe features.
- Create baseline profiles for benign agent tasks.

### Week 3: Scoring and Correlation

- Add anomaly scoring.
- Correlate events with NAIL Enforce decision IDs where available.
- Produce signed evidence records.

### Week 4: Containment MVP

- Implement observe/warn/throttle/pause modes.
- Add policy thresholds.
- Run synthetic agent failure scenarios.
- Produce first demo report.

## First Demo Scenarios

### Scenario 1: Dead-Horse Retry Loop

Agent repeatedly queries a nonexistent file or endpoint. Sensor detects `ENOENT` or failed connect storm and pauses the container.

### Scenario 2: Tool Bypass

NAIL blocks a network action, but a subprocess attempts outbound connection anyway. Sensor detects mismatch and emits high-severity event.

### Scenario 3: Privilege Probe

Agent attempts to inspect `/var/run/docker.sock`, cloud metadata, or SSH material. Sensor records privilege-probe event and isolates workload.

### Scenario 4: Runaway Tool Spawn

Agent repeatedly spawns shell/subprocess tasks. Sensor throttles or pauses based on process churn score.

## What to Avoid Saying

- “The kernel detects hallucinations.”
- “Unhackable.”
- “Rogue AI lobotomy.”
- “Kernel psychoanalysis.”
- “Semantic OS.”

## What to Say Instead

- “Out-of-band runtime attestation for AI agents.”
- “Host-level evidence when application controls are bypassed.”
- “Syscall anomaly detection for agent workloads.”
- “Containment hooks for abnormal agent runtime behaviour.”
- “Claims-grade distinction between AI action, human action, tool bypass, and cyber compromise.”

## Strategic Fit for Hiscox / Insurance

This product directly strengthens the Algorithmic Professional Indemnity thesis.

For underwriting:

- Shows controls are active after binding.
- Creates behavioural baselines.
- Flags risky deployments early.

For claims:

- Helps attribute whether a loss came from the AI agent, a human, disabled controls, or external compromise.
- Preserves independent host-level evidence.
- Reduces reliance on insured self-reporting.

For portfolio management:

- Reveals common failure patterns across insureds.
- Identifies high-risk agent frameworks or configurations.
- Produces loss-control data before mature claims history exists.

## Recommended Product Claim

**Neuravant Runtime Sensor adds host-level runtime assurance to AI-agent insurance. It observes process behaviour below the application layer, scores abnormal agent activity, and preserves evidence that helps insurers decide whether a loss arose from AI negligence, human misuse, control failure, or cyber compromise.**
