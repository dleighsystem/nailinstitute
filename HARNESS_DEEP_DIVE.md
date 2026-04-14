# 🔬 ANTHROPIC HARNESS DEEP DIVE — NAIL Institute Analysis

> **Date**: 2025-03-29  
> **Status**: Complete deep dive — ready for architecture implementation  
> **Source**: `harness-reference/` (cloned from `anthropics/claude-cookbooks`)

---

## 1. WHAT THE "HARNESS" ACTUALLY IS

There is **no single "Harness 2.0" binary to download**. Anthropic's harness is a **composable architecture philosophy** implemented across three layers:

| Layer | Location in Our Repo | What It Is |
|-------|---------------------|------------|
| **Pattern Library** | `harness-reference/patterns/agents/` | 5 workflow blueprints (Chaining → Routing → Parallelization → Orchestrator-Workers → Evaluator-Optimizer) |
| **Agent SDK** | `harness-reference/claude_agent_sdk/` | 4 production-grade agent implementations using the Claude Agent SDK (`ClaudeSDKClient` + `ClaudeAgentOptions`) |
| **Tool Ecosystem** | `harness-reference/tool_use/` | Memory management, context compaction, parallel tools, Pydantic integration |

**The key insight**: Claude Code itself is the harness. The SDK wraps Claude's agentic loop (`query()` → tool use → response → repeat`) and the patterns show how to compose multiple agents for complex tasks.

---

## 2. THE FIVE WORKFLOW PATTERNS (patterns/agents/)

### 2.1 Core Building Blocks (`util.py`)

```python
# The entire foundation is TWO functions:
def llm_call(prompt, system_prompt="", model="claude-sonnet-4-6") -> str
def extract_xml(text, tag) -> str
```

Every pattern composes these primitives. XML tags provide structured inter-agent communication.

### 2.2 Prompt Chaining
**Pattern**: Output of step N becomes input of step N+1  
**NAIL Mapping**: Our VQC pipeline — binary stage → multiclass stage → confidence calibration  
**Implementation**: Sequential `llm_call()` with `extract_xml()` extraction between steps

### 2.3 Routing
**Pattern**: Classifier routes input to specialized handlers  
**NAIL Mapping**: `quantum_anomaly_layer.py` Tier system — VQC (Tier 0) → Reservoir (Tier 1) → SVM (Tier 2) → Heuristic (Tier 3)  
**Implementation**: First LLM call classifies, then routes to specialized prompt

### 2.4 Parallelization
**Pattern**: Multiple LLM calls run simultaneously, results merged  
**NAIL Mapping**: Contagion experiment arms (Control/Passive/Behavioral/Firewall running in parallel)  
**Implementation**: `asyncio.gather()` or thread pool of `llm_call()` instances

### 2.5 Orchestrator-Workers
**Pattern**: Central orchestrator decomposes task, spawns workers, synthesizes  
**NAIL Mapping**: **This is our Pathology Collider**. The collider orchestrates 5 defense layers, each a "worker" with its own detection method  
**Implementation**: Orchestrator uses `run_blocking_subagent` to spawn workers with detailed prompts

### 2.6 Evaluator-Optimizer
**Pattern**: Generator produces output, evaluator scores it, loop until PASS  
**NAIL Mapping**: **This is our Red Team / Blue Team loop**. Red team generates attacks, Blue team (with VQC) evaluates, iterate until defense holds  
**Implementation**: Generator → Evaluator → if `NEEDS_IMPROVEMENT` → regenerate with feedback

---

## 3. THE CLAUDE AGENT SDK AGENTS (claude_agent_sdk/)

### 3.1 Architecture: `ClaudeSDKClient` + `ClaudeAgentOptions`

Every agent follows the same skeleton:

```python
options = ClaudeAgentOptions(
    model="claude-opus-4-6",
    allowed_tools=["WebSearch", "Read", "Bash", "Task"],  # <-- Tool whitelist
    disallowed_tools=["Bash"],                              # <-- Tool blacklist
    system_prompt=SYSTEM_PROMPT,
    permission_mode="acceptEdits",                          # default | plan | acceptEdits
    mcp_servers={"name": McpServerConfig(...)},             # <-- MCP integration
    cwd="/path/to/project",
    setting_sources=["project", "local"],                   # Load .claude/ filesystem
)

async with ClaudeSDKClient(options=options) as agent:
    await agent.query(prompt=user_input)
    async for msg in agent.receive_response():
        # Stream processing
        if hasattr(msg, "result"):
            final_result = msg.result
```

### 3.2 Research Agent (Notebook 00)
- **Simplest agent**: WebSearch + Read tools only
- **Key feature**: `max_buffer_size=10MB` for large document analysis
- **NAIL relevance**: Template for our literature-scanning quantum research agent

### 3.3 Chief of Staff Agent (Notebook 01) — **MOST RELEVANT TO NAIL**
- **Multi-agent delegation** via `Task` tool (spawns subagents)
- **CLAUDE.md as persistent memory** — company context loaded automatically
- **Subagent definitions** in `.claude/agents/` (financial-analyst.md, recruiter.md)
- **Custom slash commands** in `.claude/commands/`
- **Hooks** for audit trails (PostToolUse triggers Python scripts)
- **Output styles** for different audiences (executive vs. technical)
- **NAIL mapping**: Our institute needs EXACTLY this pattern:
  - `CLAUDE.md` → NAIL threat intelligence context
  - `.claude/agents/red-team.md` → Red team attack generator
  - `.claude/agents/blue-team.md` → Blue team VQC defender
  - `.claude/agents/quantum-researcher.md` → Experiment orchestrator
  - Hooks → Audit trail for all defense decisions

### 3.4 Observability Agent (Notebook 02)
- **MCP server integration** — GitHub MCP server (100+ tools)
- **Disallowed tools** force MCP usage over Bash shortcuts
- **NAIL mapping**: MCP server for our Prometheus/Grafana monitoring of agent health

### 3.5 SRE Agent (Notebook 03) — **MOST SOPHISTICATED**
- **2,722-line MCP server** (`sre_mcp_server.py`) with:
  - 12+ tools: `query_metrics`, `get_logs`, `get_alerts`, `read_config_file`, `edit_config_file`, `run_shell_command`, `write_postmortem`, `execute_runbook`
  - **Conditional tool registration**: PagerDuty tools only loaded if API key present, Confluence tools only loaded if configured
  - **Simulated incidents**: Server generates realistic failure scenarios with time-based degradation
- **Safety hooks** (PreToolUse): Validate write operations before execution
  - Config sanity checks (e.g., DB_POOL_SIZE must be in range 5-100)
  - Prevents dangerous commands
- **Full incident lifecycle**: Detection → Investigation → Diagnosis → Remediation → Postmortem
- **Infrastructure as Code** (`infra_setup.py`, 1099 lines): Generates complete Docker stack (Postgres, FastAPI, Prometheus, Grafana, traffic generator)
- **NAIL mapping**: Template for our autonomous defense agent that can:
  - Detect anomaly via VQC
  - Investigate with quantum kernel analysis
  - Apply quarantine (from contagion experiment)
  - Write defense postmortem

---

## 4. MEMORY & CONTEXT MANAGEMENT (tool_use/)

### 4.1 Memory Tool (`memory_tool.py`, 363 lines)
- **File-based memory system** with CRUD operations (view, create, str_replace, insert, delete, rename)
- **Path validation** prevents directory traversal attacks
- **Confined to `/memories` directory** — security boundary
- **NAIL mapping**: This is exactly what our Ship of Theseus Active Forgetting needs:
  - Agent memories stored as files
  - Pruning = deleting stale memory files
  - Identity verification = comparing current memories to baseline

### 4.2 Context Compaction (`automatic-context-compaction.ipynb`)
- **Anthropic's solution to the context window problem**
- Technique: When context exceeds threshold, summarize older conversation turns
- **NAIL mapping**: Directly maps to our Active Forgetting pruning mechanism

---

## 5. THE HOOK SYSTEM — AUDIT & SAFETY

### 5.1 PostToolUse Hooks
```json
{
  "hooks": {
    "PostToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "script-usage-logger.py"}]},
      {"matcher": "Write", "hooks": [{"type": "command", "command": "report-tracker.py"}]},
      {"matcher": "Edit", "hooks": [{"type": "command", "command": "report-tracker.py"}]}
    ]
  }
}
```

- **Every tool use triggers a Python script** via stdin JSON
- `report-tracker.py`: Logs all file writes/edits to `audit/report_history.json` (last 50 entries)
- `script-usage-logger.py`: Logs Python script executions to `audit/script_usage_log.json` (last 100 entries)
- **NAIL mapping**: We need PreToolUse hooks for:
  - Validating agent actions against defense policy
  - Quantum anomaly check BEFORE allowing tool execution
  - Logging all agent decisions for forensic analysis

### 5.2 PreToolUse Hooks (SRE Agent)
- Run BEFORE tool execution — can **block dangerous actions**
- Validate config changes (e.g., pool size ranges)
- **NAIL mapping**: VQC confidence check before allowing agent to modify system state

---

## 6. RESEARCH AGENT ARCHITECTURE (patterns/agents/prompts/)

### 6.1 Three-Tier System
| Role | Prompt File | Function |
|------|------------|----------|
| **Lead** | `research_lead_agent.md` | Plans strategy, delegates to subagents, synthesizes final report |
| **Subagent** | `research_subagent.md` | Executes OODA loop (Observe-Orient-Decide-Act) with tool budget |
| **Citations** | `citations_agent.md` | Post-processing: adds source citations to final report |

### 6.2 Key Design Patterns
- **Query classification**: Depth-first (multiple perspectives) vs. Breadth-first (independent sub-questions) vs. Straightforward
- **Subagent budgeting**: 1 subagent for simple → 3-5 for standard → 5-10 for complex → max 20
- **Research budget per subagent**: 5-15 tool calls maximum
- **OODA loop**: Each subagent runs observe→orient→decide→act cycle
- **Source quality reasoning**: Explicit instructions to evaluate source reliability
- **NAIL mapping**: Our quantum experiment orchestration should follow this exact pattern:
  - Lead agent: Plans which experiments to run
  - Subagents: Each runs one experiment (VQC, Contagion, Ship of Theseus, etc.)
  - Synthesis: Lead aggregates results into research report

---

## 7. 🎯 NAIL HARNESS ARCHITECTURE — Direct Mapping

Based on deep dive, here's how every Anthropic component maps to NAIL:

| Anthropic Component | NAIL Implementation | Status |
|---|---|---|
| `util.py` (llm_call + extract_xml) | `ollama_call()` + JSON extraction via nemotron:70b | 🔧 BUILD |
| Prompt Chaining | VQC binary→multiclass pipeline | ✅ DONE |
| Routing | Layer 5 Tier system (VQC→Reservoir→SVM→Heuristic) | ✅ DONE |
| Parallelization | Contagion multi-arm experiments | ✅ DONE |
| Orchestrator-Workers | Pathology Collider (5 defense layers) | ✅ DONE |
| Evaluator-Optimizer | Red/Blue team loop with VQC scoring | 🔧 BUILD |
| ClaudeSDKClient | `NailAgentClient` wrapping Ollama API | 🔧 BUILD |
| CLAUDE.md | `NAIL_CONTEXT.md` (threat intel, thresholds, experiment results) | 🔧 BUILD |
| `.claude/agents/` | `.nail/agents/` (red-team.md, blue-team.md, quantum-researcher.md) | 🔧 BUILD |
| Hooks (PostToolUse) | Defense audit logging + quantum anomaly pre-checks | 🔧 BUILD |
| MCP Server | NAIL MCP server exposing quantum detection tools | 🔧 BUILD |
| Memory Tool | Active Forgetting memory manager from Ship of Theseus | 🔧 BUILD |
| Research Lead/Subagent | Experiment orchestration (lead plans, subagents execute) | 🔧 BUILD |
| SRE Incident Lifecycle | NAIL Defense Lifecycle (Detect→Investigate→Quarantine→Postmortem) | 🔧 BUILD |

---

## 8. IMPLEMENTATION PRIORITY

### Phase 1: Foundation (Build `nail_harness/`)
1. `nail_harness/util.py` — Ollama wrapper equivalent to Anthropic's util.py
2. `nail_harness/agent_client.py` — NailAgentClient (query loop with tool routing)
3. `NAIL_CONTEXT.md` — Persistent context file (thresholds, experiment results, threat intel)

### Phase 2: Agent Definitions
4. `.nail/agents/red_team.md` — Attack generator prompt
5. `.nail/agents/blue_team.md` — VQC-powered defense evaluator
6. `.nail/agents/quantum_researcher.md` — Experiment orchestrator

### Phase 3: Tool Infrastructure
7. `nail_harness/mcp_server.py` — MCP server exposing VQC inference, anomaly detection, quarantine
8. `nail_harness/hooks/` — PreToolUse (anomaly gate) + PostToolUse (audit trail)
9. `nail_harness/memory.py` — Active Forgetting memory manager

### Phase 4: Evaluator-Optimizer Loop
10. Red/Blue team loop — Generator creates attack, VQC evaluates, loop until defense passes

---

## 9. FILES DOWNLOADED (Local Reference)

```
harness-reference/
├── patterns/agents/
│   ├── basic_workflows.ipynb          # Chaining, Routing, Parallelization
│   ├── evaluator_optimizer.ipynb      # Generator/Evaluator loop
│   ├── orchestrator_workers.ipynb     # Dynamic subtask orchestration
│   ├── prompts/
│   │   ├── research_lead_agent.md     # Lead researcher prompt (200+ lines)
│   │   ├── research_subagent.md       # Subagent OODA loop (80+ lines)
│   │   └── citations_agent.md         # Citation injection prompt
│   ├── util.py                        # llm_call() + extract_xml()
│   └── README.md
├── claude_agent_sdk/
│   ├── research_agent/agent.py        # WebSearch + Read agent
│   ├── chief_of_staff_agent/          # Multi-agent with hooks, CLAUDE.md, subagents
│   │   ├── agent.py                   # Task delegation, permission modes
│   │   ├── CLAUDE.md                  # Persistent context
│   │   ├── .claude/agents/            # Subagent definitions
│   │   ├── .claude/hooks/             # PostToolUse audit scripts
│   │   └── .claude/commands/          # Slash commands
│   ├── observability_agent/agent.py   # MCP server (GitHub) integration
│   └── site_reliability_agent/
│       ├── sre_mcp_server.py          # 2,722 lines — 12+ MCP tools
│       └── infra_setup.py             # 1,099 lines — Docker infrastructure
└── tool_use/
    ├── memory_tool.py                 # 363 lines — file-based memory CRUD
    ├── memory_cookbook.ipynb           # Context editing patterns
    └── automatic-context-compaction.ipynb  # Context window management
```

---

## 10. KEY TAKEAWAYS FOR NAIL

1. **We're already implementing most of the patterns** — our Pathology Collider IS an orchestrator-workers pattern, our VQC pipeline IS prompt chaining, our contagion experiment IS parallelization

2. **What we're missing**: The harness layer that CONNECTS them — the `NailAgentClient` that orchestrates defense layers, the hooks that audit decisions, the CLAUDE.md that provides persistent threat context

3. **The quantum advantage is unique to us** — Anthropic's patterns use LLMs for everything. We replace the Evaluator with a VQC quantum classifier (100% Sleeper recall). This is our patent-worthy innovation.

4. **Build with Ollama, not Anthropic API** — Our DGX Spark runs nemotron:70b locally. The `util.py` equivalent wraps Ollama instead of Anthropic's API. Zero cloud dependency.

5. **The SRE agent pattern is our North Star** — MCP server exposing quantum tools + safety hooks + full incident lifecycle = NAIL's autonomous defense agent
