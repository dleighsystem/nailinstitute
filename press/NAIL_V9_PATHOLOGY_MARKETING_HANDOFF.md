# NAIL v9 Pathology Marketing Handoff

Audience: Marketing, press, growth, product marketing, sales enablement

Purpose: Translate the new NAIL Agent Pathology Registry and first v9 detector pack into market-ready language, launch assets, and claim guardrails.

## Core Message

NAIL now monitors the agent control plane: tool metadata, memory writes, and goal trajectory. These are the places where production agents can be compromised before a final answer exists.

## Executive Summary

Most AI safety messaging focuses on bad prompts and bad outputs. The next class of production failures is subtler: agents can be redirected through their tools, poisoned through memory, or drift away from the authorized task while still appearing operational.

The new NAIL v9 detector pack gives teams deterministic runtime visibility into three high-risk agent pathologies:

| Pathology | Plain-English Risk | What NAIL Detects | Remedy |
| --- | --- | --- | --- |
| Tool Manifest Poisoning | A tool description, MCP server, or schema quietly changes and influences planning before the tool is called. | Tool metadata hash drift, untrusted tools, instruction-like descriptions, privilege expansion. | Sign/hash manifests, pin approved metadata, quarantine new tools, require human approval for expanded privileges. |
| Memory Write Poisoning | Untrusted content gets persisted as long-term policy, credentials, routing logic, goals, or other privileged state. | Low-trust writes, protected fact types, secret-like content, missing provenance or expiry. | Quarantine risky memory writes, require source/trust/expiry metadata, review protected writes, separate user memory from policy/config memory. |
| Goal Drift | An agent's plan, tools, or proposed actions diverge from the declared goal. | Low goal alignment, unauthorized tool calls, self-preservation/evasion language, exfiltration or control-plane manipulation intent. | Reauthorize the goal, gate sensitive actions, replan from clean context, restrict tools until drift clears. |

## Positioning

### Headline Position

From prompt security to control-plane assurance.

### Supporting Position

NAIL helps teams detect agent failures before the final answer exists by watching the runtime metadata that governs agent behavior: tools, memory, goals, and actions.

### Why This Matters

Modern agents are not just chatbots. They browse, call APIs, write memory, execute workflows, and coordinate with other services. That means safety cannot be measured only at the output layer.

The key market shift:

- Old world: Was the answer safe?
- New world: Was the agent's operating path safe?

## Pathology Cards

### 1. Tool Manifest Poisoning

Marketing-safe name: Tool metadata tampering

Buyer pain: Agents trust tool descriptions and schemas when deciding what to do. If those descriptions change, a compromised tool can influence agent behavior before any suspicious API call happens.

Plain-language explanation: An attacker does not always need to hack the model. They can alter the labels, descriptions, permissions, or schemas that tell the model what its tools are for.

NAIL signal: Unexpected tool manifest changes, unsigned high-risk scopes, suspicious instruction-like language in metadata, or newly introduced privileged capabilities.

Remedy: Pin and hash approved tool manifests, quarantine new MCP servers or tools until reviewed, and require approval when a tool gains network, filesystem, shell, database, email, secrets, payments, or similar scopes.

Soundbite: The tool description is part of the attack surface.

### 2. Memory Write Poisoning

Marketing-safe name: Persistent memory poisoning

Buyer pain: Long-term memory can turn a one-time bad instruction into a persistent operating rule. That is especially dangerous when agents remember policies, goals, credentials, tool settings, routing choices, or customer facts.

Plain-language explanation: If an agent writes untrusted text into privileged memory, the next session may inherit a compromised belief or instruction.

NAIL signal: Low-trust memory writes, protected fact types, missing provenance, missing expiry, or secret-like content being stored in long-term memory.

Remedy: Require provenance, trust level, and expiry metadata for memory writes. Quarantine risky writes and separate user facts from system policy, tool configuration, credentials, and legal or financial state.

Soundbite: Memory needs a firewall, not just a database.

### 3. Goal Drift

Marketing-safe name: Agent trajectory drift

Buyer pain: Agents can continue taking actions while quietly moving away from the authorized task. This matters most when agents have tools, access, budgets, or permission to affect production systems.

Plain-language explanation: The model may still sound helpful while its plan no longer matches the job it was given.

NAIL signal: Low overlap with the declared goal, unauthorized tool use, sensitive actions outside the approved domain, or language related to evasion, self-preservation, exfiltration, persistence, or control-plane manipulation.

Remedy: Reauthorize the goal, gate sensitive actions, replan from clean context, and temporarily restrict tools until alignment recovers.

Soundbite: It is not enough to inspect the answer. You need to inspect the trajectory.

## Messaging Hierarchy

Primary message: Detect agent failures before the final answer exists.

Secondary message: NAIL monitors the runtime metadata that shapes agent behavior: tool metadata, memory writes, goals, and actions.

Technical proof point: The v9 detectors use deterministic metadata contracts rather than another model call. They can run as production-safe monitoring around live agent workflows.

Market category language:

- Agent control-plane monitoring
- Runtime governance for production AI agents
- Agent pathology detection
- Deterministic agent safety telemetry
- Monitoring as prescribed, not monitoring as hoped

## Recommended Launch Assets

### Blog Post

Working title: Your AI Agent Can Be Compromised Before It Answers

Angle: The biggest production agent risks are shifting from prompts and outputs to the runtime control plane. Explain the three new pathologies and show how NAIL detects them.

Suggested structure:

1. The output is too late.
2. The new attack surface: tools, memory, goals.
3. Three pathologies NAIL now detects.
4. Why deterministic metadata matters.
5. What teams should instrument next.

### LinkedIn Carousel

Working title: Three Hidden Failure Surfaces in Production AI Agents

Slides:

1. Your agent can fail before it answers.
2. Tool metadata can steer planning.
3. Memory can persist bad instructions.
4. Goals can drift while the agent still sounds helpful.
5. NAIL monitors the control plane.
6. Ask: Are you monitoring the answer, or the path?

### Sales One-Pager

Working title: Control-Plane Monitoring for Production Agents

Use cases:

- Agent platforms adopting MCP or third-party tools
- Enterprises adding long-term memory to workflows
- Teams giving agents production actions or cloud access
- Regulated teams that need auditability and deterministic evidence

### Demo Script

Show three short scenarios:

1. A tool manifest changes and gains high-risk scope.
2. A low-trust input attempts to write policy-like content into memory.
3. An agent proposes a sensitive action that does not match the session goal.

For each scenario:

- Show the metadata event.
- Show the NAIL detector finding.
- Show the recommended remedy.

## Claims Guidance

### Safe Claims

Marketing can say:

- NAIL detects tool metadata drift, risky memory writes, and goal trajectory drift.
- NAIL v9 extends monitoring from model outputs to agent runtime metadata.
- NAIL uses deterministic metadata contracts for these detectors.
- NAIL helps teams quarantine risky memory writes and untrusted tool changes.
- NAIL gives teams earlier warning before unsafe behavior appears in a final answer.

### Claims To Avoid

Avoid saying:

- NAIL prevents every agent compromise.
- NAIL guarantees zero false positives or zero false negatives.
- NAIL makes agents fully autonomous without human oversight.
- NAIL replaces security review, access control, or governance.
- NAIL guarantees compliance, insurance approval, or legal safety.

Better replacement language:

- "Adds deterministic monitoring coverage for..."
- "Helps teams detect and investigate..."
- "Provides earlier warning for..."
- "Creates auditable evidence around..."

## Internal FAQ

### Is this just prompt injection detection?

No. Prompt injection is one failure mode. This detector pack focuses on runtime metadata and agent operating state: tool manifests, memory writes, and goal alignment.

### Why does tool metadata matter?

Agents use tool names, descriptions, schemas, and permissions to decide what actions are available. That metadata can shape behavior before the tool is ever called.

### Why does memory need special monitoring?

Memory can persist across sessions. A bad memory write can turn transient untrusted input into future operating context.

### Why is goal drift separate from hallucination?

Hallucination is about incorrect content. Goal drift is about action trajectory: whether the agent's plan and tool use still match the authorized objective.

### Is this blocking or passive monitoring?

The detector pack is designed for deterministic monitoring and policy enforcement. Teams can configure remedies such as quarantine, review, reauthorization, or tool restriction depending on risk tolerance.

## Product And Engineering Pointers

Source of truth for pathology definitions:

- `nail_monitor/nail_monitor/registry.py`

Detector implementation:

- `nail_monitor/nail_monitor/detectors_v9.py`

Important metadata contracts:

- Tool integrity: `tool_manifest`, `tool_manifests`
- Memory firewall: `memory_writes`
- Goal drift: `task_goal`, `session_id`, `plan_steps`, `tool_calls`, `action`, `allowed_tools`, `allowed_domains`, `sensitive_action`, `goal_alignment_score`

## Handoff Checklist

- Product marketing: turn this into one narrative and one short sales explainer.
- Content: draft the blog post using the "output is too late" angle.
- Growth: build a short carousel around the three failure surfaces.
- Sales: create a one-page objection handler for "we already monitor outputs."
- Product: prepare a demo using one event per detector.
- Legal/compliance: review claims before public launch.

## Recommended Next Action

Create a public-facing blog draft titled "Your AI Agent Can Be Compromised Before It Answers" and pair it with a short demo script showing all three detectors firing on deterministic metadata events.
