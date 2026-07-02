# Your AI Agent Can Be Compromised Before It Answers

*Subtitle: The next generation of agent failures happens in the control plane: tools, memory, and goals.*

**Most AI safety systems watch the answer. That is too late.**

By the time an autonomous agent produces a final response, it may already have selected a compromised tool, written poisoned content into long-term memory, or drifted away from the task it was authorized to complete.

That is the uncomfortable lesson behind the newest work from the NAIL Institute. Production agents are no longer just text generators. They call APIs, use MCP servers, update memory, browse systems, coordinate with other agents, and trigger real workflows. Their safety depends not only on what they say, but on the path they take before they say it.

We call that path the agent control plane.

And it needs monitoring.

## The Output Is Too Late

Traditional AI monitoring asks questions like:

- Did the model produce harmful content?
- Did it leak private data in the final answer?
- Did it hallucinate?
- Did it violate a policy in the response?

Those are necessary questions. They are not sufficient for agents.

An agent can fail before the answer exists.

It can trust a tool whose metadata has changed. It can persist an unsafe instruction into memory. It can begin taking actions that no longer match the user's goal. In each case, the final answer may look normal, polite, and helpful while the operating path underneath it is already compromised.

For production teams, that means output validation alone leaves a blind spot.

You need to know whether the agent's tools, memory, and goals remained trustworthy throughout the run.

## The New Attack Surface: Tools, Memory, Goals

Modern agents are assembled from runtime components. The model is only one part of the system.

The rest of the system includes:

- Tool names, descriptions, schemas, and permissions
- MCP servers and third-party tool registries
- Long-term memory stores
- Session goals and task plans
- Allowed tools, domains, and actions
- Agent-to-agent messages and handoffs

This metadata shapes what the model believes it can do.

That makes it security-relevant.

If a tool description changes, the agent's plan can change. If memory is polluted, a future session can inherit a bad rule. If the goal drifts, the agent can keep acting while quietly leaving the authorized task behind.

This is why NAIL's latest detector pack moves beyond output inspection and into control-plane monitoring.

## Three Pathologies We Now Detect

The new NAIL Agent Pathology Registry adds deterministic detectors for three high-risk agent failure modes: tool manifest poisoning, memory write poisoning, and goal drift.

These are not just theoretical categories. They correspond to the metadata contracts production systems already expose or can instrument: tool manifests, memory write events, session goals, tool calls, planned actions, allowed domains, and sensitivity labels.

### 1. Tool Manifest Poisoning

**The pathology:** A tool description, schema, permission set, or MCP server changes in a way that influences the agent before the tool is ever called.

Agents rely on tool metadata to decide which actions are available and appropriate. That means tool metadata is not harmless documentation. It is part of the agent's operating context.

If an attacker, dependency update, misconfiguration, or compromised registry changes a tool's description, the agent may treat the new instruction as legitimate. A tool that used to "save a report" might now include language nudging the agent to send sensitive data elsewhere. A low-risk integration might quietly gain network, filesystem, shell, database, email, secrets, or payment scope.

**What NAIL watches for:**

- Tool manifest hash drift
- New untrusted tool metadata
- Unsigned high-risk scopes
- Instruction-like language inside tool descriptions or schemas
- Privilege expansion from previously approved tools

**The remedy:** Hash and pin approved tool manifests. Quarantine newly introduced tools or MCP servers until reviewed. Require human approval when a tool gains sensitive capabilities.

**The short version:** The tool description is part of the attack surface.

### 2. Memory Write Poisoning

**The pathology:** Untrusted content gets written into long-term memory as if it were a trusted fact, policy, credential, route, goal, or configuration.

Memory changes the risk profile of agent systems. A bad prompt can disappear when the session ends. A bad memory write can persist.

That persistence is useful when the memory is trustworthy. It is dangerous when the agent stores untrusted text as privileged operating state.

For example, an agent might write a user's instruction into memory as a future policy. It might store a tool routing preference without provenance. It might persist secret-like content, legal conclusions, financial advice, or a modified goal without expiry. The next session may then inherit that poisoned state as context.

**What NAIL watches for:**

- Low-trust memory writes
- Protected fact types from external or tool-originated sources
- Secret-like content being persisted
- Missing provenance
- Missing expiry or time-to-live metadata

**The remedy:** Put a firewall in front of memory writes. Require source, trust level, and expiry metadata. Quarantine protected writes for review. Separate user facts from system policy, tool configuration, credentials, legal state, and financial state.

**The short version:** Memory needs a firewall, not just a database.

### 3. Goal Drift

**The pathology:** The agent's plan, tool use, or proposed action diverges from the declared task while the agent continues operating.

Goal drift is not the same thing as hallucination. A hallucination is about content being wrong. Goal drift is about trajectory being wrong.

An agent may start with a valid task: summarize a document, file a support ticket, deploy a fix, or reconcile an account. During the run, its plan may shift. It may call tools outside the allowed set. It may propose a sensitive action that is weakly connected to the goal. It may begin reasoning about persistence, evasion, exfiltration, control-plane changes, or self-preservation.

The final message may still sound helpful. The path no longer matches the authorization.

**What NAIL watches for:**

- Low alignment between the declared goal and proposed action
- Unauthorized tool calls
- Sensitive actions outside allowed domains
- Self-preservation or monitoring-evasion language
- Exfiltration, persistence, or control-plane manipulation intent

**The remedy:** Reauthorize the goal. Gate sensitive actions. Replan from clean context. Restrict tools until the drift clears.

**The short version:** It is not enough to inspect the answer. You need to inspect the trajectory.

## Why Deterministic Metadata Matters

A common answer to AI safety is to add another model call: ask a judge model whether the output looks safe.

That can help. But it is not the whole answer for production agents.

For these pathologies, the most reliable signals are often not semantic judgments. They are metadata facts:

- Did this tool manifest change?
- Did this tool gain a sensitive permission?
- Who requested this memory write?
- What trust level was attached to it?
- Does this memory write have an expiry?
- Is this tool call allowed for the current goal?
- Is this action inside the approved domain?

Those questions can be answered deterministically.

That matters because production governance needs evidence. Teams need audit trails, repeatable checks, incident review, and policies that behave the same way tomorrow as they did today.

NAIL's v9 detector pack is built around that idea: monitor the runtime contracts that shape agent behavior, then apply clear remedies when those contracts are violated.

## What Teams Should Instrument Next

If you are running production agents, start by logging the operating path, not just the final response.

At minimum, instrument:

- A canonical tool manifest for every tool the agent can see
- Hashes or signatures for approved tool metadata
- Tool scopes, permissions, and owner information
- Every memory write, including source, trust level, fact type, and expiry
- The declared task goal for each session
- Planned actions and executed tool calls
- Allowed tools, allowed domains, and sensitive action labels
- Goal alignment or authorization checks before high-impact actions

Then decide which events should be allowed, quarantined, reviewed, or blocked.

The important shift is simple: stop treating agent safety as a final-answer problem. Treat it as a runtime governance problem.

## Monitoring As Prescribed, Not Monitoring As Hoped

Agent systems are becoming production infrastructure. They need the same discipline we expect from other production infrastructure: telemetry, integrity checks, access boundaries, incident trails, and clearly defined failure modes.

The NAIL Agent Pathology Registry is our way of naming those failure modes so teams can detect and remedy them.

This detector pack is the next step:

- Tool manifest integrity for the agent's tools
- Memory write firewalls for the agent's state
- Goal drift monitoring for the agent's trajectory

The lesson is not that agents are unusable. The lesson is that agents need monitoring at the level where their decisions are formed.

Because by the time the answer appears, the important decision may already have happened.

## Call To Action

If your organization is deploying agents with tools, long-term memory, or production actions, audit the control plane now.

Ask three questions:

1. Can we prove our tool metadata has not changed unexpectedly?
2. Can we prove untrusted input cannot become privileged memory?
3. Can we prove each sensitive action still matches the authorized goal?

If the answer is no, your monitoring is watching the wrong moment.

NAIL exists to help teams watch the moment that matters.
