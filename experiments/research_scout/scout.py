"""
NAIL Institute — Research Scout Agent
========================================
An automated threat intelligence agent that:
1. Searches for new AI safety papers, incidents, and failure reports
2. Cross-references against our existing pathology catalog (23 experiments)
3. Identifies coverage gaps
4. Generates experiment proposals for unaddressed failure modes
5. Updates the threat landscape document

Usage:
    python3 -m research_scout.scout                    # Full scan
    python3 -m research_scout.scout --source arxiv     # Specific source
    python3 -m research_scout.scout --since 7          # Last N days
"""

import json
import re
import time
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, DATA_DIR
from shared.agent_base import Agent
from shared.logger import ExperimentLogger


# ═══════════════════════════════════════════════════════════════════════════
# OUR EXISTING PATHOLOGY CATALOG — what we've already tested
# ═══════════════════════════════════════════════════════════════════════════

EXISTING_PATHOLOGIES = {
    "memory_pollution": {
        "experiment": "exp1", "status": "PROVEN",
        "description": "Sleeper payload injection into shared memory",
        "keywords": ["memory poisoning", "data poisoning", "knowledge corruption", "memory injection"],
    },
    "consensus_paralysis": {
        "experiment": "exp2", "status": "PROVEN",
        "description": "Multi-agent committees deadlock indefinitely",
        "keywords": ["consensus", "deadlock", "committee", "multi-agent coordination", "group decision"],
    },
    "token_embezzlement": {
        "experiment": "exp3", "status": "PROVEN",
        "description": "Economic denial-of-service via token inflation",
        "keywords": ["token", "cost", "economic attack", "resource exhaustion", "denial of service", "edos"],
    },
    "prompt_inbreeding": {
        "experiment": "exp4", "status": "PROVEN",
        "description": "Recursive prompt degradation over generations",
        "keywords": ["prompt degradation", "recursive", "self-referential", "model collapse"],
    },
    "cya_cascade": {
        "experiment": "exp5", "status": "PROVEN",
        "description": "Blame-shifting escalation in agent hierarchies",
        "keywords": ["responsibility", "blame", "escalation", "accountability", "delegation"],
    },
    "language_drift": {
        "experiment": "exp6", "status": "PROVEN",
        "description": "Long-running agents develop incomprehensible shorthand",
        "keywords": ["language drift", "communication breakdown", "semantic drift", "jargon"],
    },
    "goodharts_cartel": {
        "experiment": "exp7", "status": "PROVEN",
        "description": "Agents optimise for metric rather than actual goal",
        "keywords": ["goodhart", "metric gaming", "reward hacking", "proxy gaming", "specification gaming"],
    },
    "learned_helplessness": {
        "experiment": "exp8", "status": "PROVEN",
        "description": "Agent gives up after repeated failures",
        "keywords": ["learned helplessness", "giving up", "failure cascade", "motivation"],
    },
    "epistemic_contagion": {
        "experiment": "exp9", "status": "PROVEN",
        "description": "One poisoned agent infects all clean agents",
        "keywords": ["contagion", "viral", "spreading", "infection", "cascading failure"],
    },
    "clever_hans": {
        "experiment": "exp10", "status": "PROVEN",
        "description": "Agent uses spurious correlations instead of reasoning",
        "keywords": ["clever hans", "spurious correlation", "shortcut learning", "sycophancy"],
    },
    "prompt_satiation": {
        "experiment": "exp11", "status": "PROVEN",
        "description": "Context window fatigue from information overload",
        "keywords": ["satiation", "context window", "information overload", "attention fatigue"],
    },
    "alignment_friction": {
        "experiment": "exp12", "status": "PROVEN",
        "description": "RLHF safety training causes sycophantic collapse",
        "keywords": ["alignment", "rlhf", "sycophancy", "people pleasing", "over-alignment"],
    },
    "chronological_desync": {
        "experiment": "exp13", "status": "PROVEN",
        "description": "Agent loses track of temporal ordering",
        "keywords": ["temporal", "time", "ordering", "sequence", "chronological", "staleness"],
    },
    "mcp_security": {
        "experiment": "exp14", "status": "PROVEN",
        "description": "MCP tool discovery and manipulation vulnerabilities",
        "keywords": ["mcp", "tool use", "tool poisoning", "plugin", "function calling"],
    },
    "observer_effect": {
        "experiment": "exp15", "status": "PROVEN",
        "description": "Agent changes behaviour when monitoring is detected",
        "keywords": ["observer effect", "monitoring", "surveillance", "behaviour change"],
    },
    "upgrade_anomalies": {
        "experiment": "exp16", "status": "TESTED",
        "description": "Model upgrades cause unexpected behavioural changes",
        "keywords": ["upgrade", "version", "regression", "compatibility", "model swap"],
    },
    "container_isolation": {
        "experiment": "exp17", "status": "TESTED",
        "description": "Container escape and isolation bypass",
        "keywords": ["container", "sandbox", "isolation", "escape", "breakout"],
    },
    "somatic_awareness": {
        "experiment": "exp18", "status": "PROVEN",
        "description": "Agent lacks awareness of its own resource consumption",
        "keywords": ["self-awareness", "resource monitoring", "introspection", "somatic"],
    },
    "digital_homeostasis": {
        "experiment": "exp19", "status": "PROVEN",
        "description": "Agent cannot maintain stable internal state under perturbation",
        "keywords": ["homeostasis", "stability", "self-regulation", "equilibrium", "perturbation"],
    },
    "pathology_collider": {
        "experiment": "exp20", "status": "PROVEN",
        "description": "Simultaneous 13-pathology attack with 4-layer defence",
        "keywords": ["multi-attack", "defense", "collider", "adversarial", "red team"],
    },
    "errors_of_omission": {
        "experiment": "exp21", "status": "PROVEN",
        "description": "5 theories of autonomous inaction (bystander, gridlock, smoothing)",
        "keywords": ["inaction", "omission", "bystander", "paralysis", "inaction bias"],
    },
    "memory_laundering": {
        "experiment": "exp22", "status": "PROVEN",
        "description": "Poisoned facts laundered via self-citation to bypass trust scoring",
        "keywords": ["laundering", "trust", "provenance", "self-citation", "fact washing"],
    },
    "tool_chain_exploitation": {
        "experiment": "exp23", "status": "PROVEN",
        "description": "Indirect prompt injection via poisoned tool outputs",
        "keywords": ["indirect injection", "tool chain", "prompt injection", "data poisoning", "exfiltration"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH SOURCES
# ═══════════════════════════════════════════════════════════════════════════

ARXIV_SEARCH_QUERIES = [
    "LLM agent vulnerability security",
    "autonomous AI failure modes",
    "prompt injection defense",
    "multi-agent system failure",
    "AI safety benchmark adversarial",
    "language model jailbreak",
    "agent tool use security risks",
    "agentic AI emergent behaviour",
    "LLM hallucination cascading",
    "AI agent reliability production",
    "retrieval augmented generation attack",
    "model context protocol security",
    "AI alignment failure",
    "reward hacking autonomous agent",
]

INCIDENT_CATEGORIES = [
    "data_exfiltration",
    "prompt_injection_real_world",
    "autonomous_trading_failure",
    "ai_agent_production_incident",
    "model_collapse_in_production",
    "chatbot_jailbreak",
    "rag_poisoning_incident",
    "autonomous_vehicle_ai_failure",
    "healthcare_ai_misdiagnosis",
    "financial_ai_error",
]


# ═══════════════════════════════════════════════════════════════════════════
# SCOUT AGENT
# ═══════════════════════════════════════════════════════════════════════════

SCOUT_SYSTEM_PROMPT = """You are an AI Safety Research Scout for the NAIL Institute
(Neuravant AI Limited). Your job is to identify NEW and EMERGING failure modes,
vulnerabilities, and attack vectors that affect autonomous AI agents.

You have deep knowledge of the current threat landscape. When analysing a new
finding, you must:

1. CLASSIFY it into one of these categories:
   - PROMPT_INJECTION: Attacks that manipulate agent instructions
   - MEMORY_ATTACK: Attacks on agent knowledge/memory systems
   - TOOL_ABUSE: Exploitation of agent tool-use capabilities
   - MULTI_AGENT: Failures in multi-agent coordination
   - EMERGENT: Unexpected behaviours arising from complexity
   - ECONOMIC: Cost/resource attacks (token, compute, API)
   - TRUST: Trust/provenance/attribution failures
   - TEMPORAL: Time-related failures (staleness, ordering, scheduling)
   - ALIGNMENT: Safety/alignment/RLHF-induced failures
   - INFRASTRUCTURE: Container, networking, deployment failures

2. ASSESS novelty: Is this genuinely new or a variant of something known?

3. SCORE severity (1-10) based on:
   - Blast radius: How many systems could this affect?
   - Detectability: How hard is it to detect?
   - Exploitability: How easy is it to exploit?
   - Impact: What's the worst-case outcome?

4. PROPOSE an experiment to test it.

Respond in JSON format:
{
  "findings": [
    {
      "title": "Short descriptive title",
      "category": "CATEGORY",
      "description": "What this vulnerability is and why it matters",
      "novelty": "NEW|VARIANT|KNOWN",
      "similar_to": "existing pathology name if variant, or null",
      "severity_score": 1-10,
      "severity_reasoning": "Why this score",
      "proposed_experiment": {
        "name": "exp_XX_name",
        "hypothesis": "What we expect to find",
        "method": "How to test it",
        "success_criteria": "What would prove/disprove it"
      },
      "sources": ["citation or reference"]
    }
  ]
}"""

TREND_ANALYSIS_PROMPT = """You are an AI Safety Trend Analyst for the NAIL Institute.
Given a collection of recent findings, identify:

1. EMERGING PATTERNS — clusters of related vulnerabilities that suggest a deeper systemic issue
2. COVERAGE GAPS — areas where NAIL has no experimental coverage
3. PRIORITY THREATS — which findings should be tested first and why

You have access to NAIL's existing pathology catalog (23 experiments covering
memory pollution, consensus paralysis, token embezzlement, prompt inbreeding,
language drift, epistemic contagion, alignment friction, MCP security,
errors of omission, memory laundering, tool chain exploitation, and more).

Respond in JSON format:
{
  "patterns": [
    {"pattern": "description", "related_findings": ["title1", "title2"], "systemic_risk": "why this matters"}
  ],
  "coverage_gaps": [
    {"gap": "description", "priority": "P0|P1|P2", "reasoning": "why unaddressed"}
  ],
  "experiment_queue": [
    {"priority": 1, "name": "exp_name", "targets": "what it tests", "justification": "why now"}
  ]
}"""


@dataclass
class ScoutFinding:
    """A single finding from the Research Scout."""
    title: str
    category: str
    description: str
    novelty: str  # NEW, VARIANT, KNOWN
    similar_to: Optional[str]
    severity_score: int
    proposed_experiment: dict
    sources: list
    timestamp: float = field(default_factory=time.time)


class ResearchScout:
    """
    Automated threat intelligence agent.

    Scans for new AI failure modes, cross-references against the
    existing pathology catalog, and proposes experiments.
    """

    def __init__(
        self,
        model: str = None,
        fast_model: str = None,
        logger: Optional[ExperimentLogger] = None,
    ):
        self.model = model or PRIMARY_MODEL
        self.fast_model = fast_model or FAST_MODEL
        self.logger = logger
        self.findings: list[ScoutFinding] = []
        self.coverage_gaps: list[dict] = []
        self.experiment_queue: list[dict] = []

    def scan_research_landscape(self) -> list[ScoutFinding]:
        """
        Scan for new and emerging AI failure modes.
        Uses the LLM to synthesise knowledge about recent developments.
        """
        scout = Agent(
            name="Research_Scout",
            role="Threat Intelligence",
            system_prompt=SCOUT_SYSTEM_PROMPT,
            model=self.model,
            logger=self.logger,
            temperature=0.4,
        )

        # Build context about what we already know
        existing_summary = "\n".join(
            f"  - {name}: {p['description']} ({p['status']})"
            for name, p in EXISTING_PATHOLOGIES.items()
        )

        # Scan different domains
        domains = [
            {
                "name": "Prompt Injection & Jailbreaking",
                "focus": (
                    "Recent advances in prompt injection attacks, jailbreaking techniques, "
                    "and defenses. Include: multi-turn jailbreaks, role-play attacks, "
                    "many-shot jailbreaking, ASCII art attacks, cipher-based attacks, "
                    "crescendo attacks, skeleton key attacks, and any new bypass techniques "
                    "for safety filters in production LLM agents."
                ),
            },
            {
                "name": "Multi-Agent Failures",
                "focus": (
                    "Failures in multi-agent AI systems: coordination failures, "
                    "emergent deceptive behaviour, agent collusion, Byzantine failures, "
                    "reward hacking in multi-agent RL, competitive dynamics leading to "
                    "unsafe behaviour, communication protocol failures, and trust "
                    "establishment failures between agents."
                ),
            },
            {
                "name": "Tool Use & MCP Vulnerabilities",
                "focus": (
                    "Vulnerabilities in AI agent tool use: MCP (Model Context Protocol) "
                    "security issues, toolchain poisoning, confused deputy attacks, "
                    "capability escalation through tools, API key leakage, server-side "
                    "request forgery (SSRF) via agent tools, and SQL/code injection through "
                    "agent-generated queries."
                ),
            },
            {
                "name": "RAG & Knowledge Base Attacks",
                "focus": (
                    "Attacks on Retrieval-Augmented Generation: embedding inversion attacks, "
                    "knowledge base poisoning, semantic collision attacks, rank manipulation, "
                    "backdoor injection into vector stores, and cross-tenant data leakage "
                    "in shared RAG systems."
                ),
            },
            {
                "name": "Emergent & Systemic Failures",
                "focus": (
                    "Emergent failures in autonomous AI: deceptive alignment, power-seeking "
                    "behaviour, sandbagging (hiding capabilities), scheming, sycophancy at "
                    "scale, mode collapse under distribution shift, catastrophic forgetting "
                    "during fine-tuning, and context window exploitation."
                ),
            },
            {
                "name": "Production & Infrastructure",
                "focus": (
                    "Production deployment failures: model serving vulnerabilities, "
                    "inference-time attacks (adversarial inputs at scale), supply chain "
                    "attacks on model weights, model extraction attacks, membership "
                    "inference attacks, training data extraction, and denial-of-wallet "
                    "attacks on API-based agents."
                ),
            },
        ]

        all_findings = []

        for domain in domains:
            prompt = (
                f"SCAN DOMAIN: {domain['name']}\n\n"
                f"FOCUS AREAS:\n{domain['focus']}\n\n"
                f"EXISTING NAIL COVERAGE (do NOT repeat these):\n{existing_summary}\n\n"
                f"Identify 2-3 NEW or EMERGING failure modes in this domain that "
                f"we have NOT already tested. Focus on threats that are:\n"
                f"- Recently discovered or theorised (2024-2026)\n"
                f"- Specific to autonomous AGENTS (not just chatbots)\n"
                f"- Potentially high-impact in production deployments\n\n"
                f"Respond with your findings in the specified JSON format."
            )

            response = scout.respond(prompt, json_mode=True)

            try:
                parsed = json.loads(response)
                findings = parsed.get("findings", [])
                for f in findings:
                    finding = ScoutFinding(
                        title=f.get("title", "Unknown"),
                        category=f.get("category", "EMERGENT"),
                        description=f.get("description", ""),
                        novelty=f.get("novelty", "NEW"),
                        similar_to=f.get("similar_to"),
                        severity_score=f.get("severity_score", 5),
                        proposed_experiment=f.get("proposed_experiment", {}),
                        sources=f.get("sources", []),
                    )
                    all_findings.append(finding)

                    if self.logger:
                        self.logger.log_event("scout_finding", data={
                            "domain": domain["name"],
                            "title": finding.title,
                            "category": finding.category,
                            "novelty": finding.novelty,
                            "severity": finding.severity_score,
                        })

            except (json.JSONDecodeError, TypeError, KeyError) as e:
                print(f"  ⚠️ Failed to parse findings for {domain['name']}: {e}")

            print(f"  ✅ Scanned {domain['name']}: {len(findings) if 'findings' in dir() else 0} findings")

        self.findings = all_findings
        return all_findings

    def analyse_trends(self) -> dict:
        """
        Analyse findings for patterns, gaps, and priorities.
        """
        if not self.findings:
            return {"patterns": [], "coverage_gaps": [], "experiment_queue": []}

        analyst = Agent(
            name="Trend_Analyst",
            role="Pattern Analysis",
            system_prompt=TREND_ANALYSIS_PROMPT,
            model=self.model,
            logger=self.logger,
            temperature=0.3,
        )

        findings_summary = "\n".join(
            f"  [{f.severity_score}/10] {f.title} ({f.category}, {f.novelty}): {f.description[:100]}"
            for f in self.findings
        )

        response = analyst.respond(
            f"Analyse these {len(self.findings)} recent findings:\n\n"
            f"{findings_summary}\n\n"
            f"Identify patterns, coverage gaps relative to NAIL's 23 experiments, "
            f"and prioritise the experiment queue.",
            json_mode=True,
        )

        try:
            analysis = json.loads(response)
            self.coverage_gaps = analysis.get("coverage_gaps", [])
            self.experiment_queue = analysis.get("experiment_queue", [])
            return analysis
        except (json.JSONDecodeError, TypeError):
            return {"error": "Failed to parse trend analysis"}

    def cross_reference(self) -> dict:
        """
        Cross-reference findings against existing pathology catalog.
        Returns coverage analysis.
        """
        covered = set()
        novel = []
        variants = []

        for finding in self.findings:
            # Check if any existing pathology keywords match
            matched = False
            for path_name, pathology in EXISTING_PATHOLOGIES.items():
                for keyword in pathology["keywords"]:
                    if keyword.lower() in finding.description.lower() or \
                       keyword.lower() in finding.title.lower():
                        covered.add(path_name)
                        if finding.novelty != "KNOWN":
                            variants.append({
                                "new_finding": finding.title,
                                "existing_pathology": path_name,
                                "description": finding.description[:150],
                            })
                        matched = True
                        break
                if matched:
                    break

            if not matched:
                novel.append({
                    "title": finding.title,
                    "category": finding.category,
                    "severity": finding.severity_score,
                    "description": finding.description[:150],
                    "proposed_experiment": finding.proposed_experiment,
                })

        uncovered = set(EXISTING_PATHOLOGIES.keys()) - covered

        return {
            "total_findings": len(self.findings),
            "novel_threats": len(novel),
            "variants_of_existing": len(variants),
            "pathologies_covered": len(covered),
            "pathologies_uncovered": len(uncovered),
            "coverage_pct": len(covered) / len(EXISTING_PATHOLOGIES) * 100,
            "novel_details": novel,
            "variant_details": variants,
            "uncovered_pathologies": list(uncovered),
        }

    def generate_report(self, output_dir: Optional[Path] = None) -> Path:
        """
        Generate a comprehensive threat intelligence report.
        """
        output_dir = output_dir or Path(DATA_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        cross_ref = self.cross_reference()
        trends = self.analyse_trends()

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": self.model,
            "total_findings": len(self.findings),
            "findings": [
                {
                    "title": f.title,
                    "category": f.category,
                    "novelty": f.novelty,
                    "severity": f.severity_score,
                    "description": f.description,
                    "similar_to": f.similar_to,
                    "proposed_experiment": f.proposed_experiment,
                    "sources": f.sources,
                }
                for f in sorted(self.findings, key=lambda x: x.severity_score, reverse=True)
            ],
            "cross_reference": cross_ref,
            "trend_analysis": trends,
        }

        # Save JSON
        json_path = output_dir / "scout_report.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Generate markdown report
        md_lines = [
            "# NAIL Research Scout — Threat Intelligence Report",
            f"*Generated: {time.strftime('%Y-%m-%d %H:%M')}*\n",
            f"**Model:** {self.model}  ",
            f"**Findings:** {len(self.findings)}  ",
            f"**Novel threats:** {cross_ref['novel_threats']}  ",
            f"**Coverage:** {cross_ref['coverage_pct']:.0f}% of existing catalog matched\n",
            "---\n",
            "## 🔴 High-Severity Findings (≥7/10)\n",
        ]

        high_sev = [f for f in self.findings if f.severity_score >= 7]
        if high_sev:
            for f in sorted(high_sev, key=lambda x: x.severity_score, reverse=True):
                md_lines.append(f"### [{f.severity_score}/10] {f.title}")
                md_lines.append(f"**Category:** {f.category} | **Novelty:** {f.novelty}")
                if f.similar_to:
                    md_lines.append(f"**Variant of:** {f.similar_to}")
                md_lines.append(f"\n{f.description}\n")
                if f.proposed_experiment:
                    exp = f.proposed_experiment
                    md_lines.append(f"**Proposed experiment:** `{exp.get('name', 'TBD')}`")
                    md_lines.append(f"- Hypothesis: {exp.get('hypothesis', 'TBD')}")
                    md_lines.append(f"- Method: {exp.get('method', 'TBD')}")
                md_lines.append("")
        else:
            md_lines.append("*No findings scored ≥7/10*\n")

        md_lines.extend([
            "---\n",
            "## 🟡 Medium-Severity Findings (4-6)\n",
        ])

        med_sev = [f for f in self.findings if 4 <= f.severity_score < 7]
        for f in sorted(med_sev, key=lambda x: x.severity_score, reverse=True):
            md_lines.append(f"- **[{f.severity_score}/10] {f.title}** ({f.category}): {f.description[:120]}")
        if not med_sev:
            md_lines.append("*None*\n")

        md_lines.extend([
            "\n---\n",
            "## Coverage Gaps\n",
        ])

        for gap in self.coverage_gaps:
            md_lines.append(f"- **{gap.get('gap', 'Unknown')}** [{gap.get('priority', 'P2')}]: {gap.get('reasoning', '')}")

        md_lines.extend([
            "\n---\n",
            "## Experiment Queue\n",
            "| Priority | Experiment | Target | Justification |",
            "|---|---|---|---|",
        ])

        for exp in self.experiment_queue:
            md_lines.append(
                f"| {exp.get('priority', '?')} "
                f"| {exp.get('name', 'TBD')} "
                f"| {exp.get('targets', '?')} "
                f"| {exp.get('justification', '')} |"
            )

        md_path = output_dir / "scout_report.md"
        with open(md_path, "w") as f:
            f.write("\n".join(md_lines))

        print(f"\n  📄 Reports saved:")
        print(f"    JSON: {json_path}")
        print(f"    MD:   {md_path}")

        return md_path

    def run_full_scan(self) -> dict:
        """Run a complete scan: search → analyse → cross-reference → report."""
        print("\n" + "=" * 70)
        print("  ╔═══════════════════════════════════════════════════════════════╗")
        print("  ║  NAIL RESEARCH SCOUT — THREAT INTELLIGENCE SCAN             ║")
        print(f"  ║  Model: {self.model:<55}║")
        print(f"  ║  Existing pathologies: {len(EXISTING_PATHOLOGIES):<39}║")
        print("  ╚═══════════════════════════════════════════════════════════════╝")
        print("=" * 70 + "\n")

        start = time.time()

        # Phase 1: Scan
        print("  Phase 1: Scanning research landscape...")
        findings = self.scan_research_landscape()
        print(f"  → {len(findings)} findings\n")

        # Phase 2: Cross-reference
        print("  Phase 2: Cross-referencing against catalog...")
        cross_ref = self.cross_reference()
        print(f"  → {cross_ref['novel_threats']} novel, "
              f"{cross_ref['variants_of_existing']} variants, "
              f"{cross_ref['coverage_pct']:.0f}% coverage\n")

        # Phase 3: Report
        print("  Phase 3: Generating report...")
        report_path = self.generate_report()

        total_time = time.time() - start

        print(f"\n  ✅ Scan complete in {total_time/60:.1f} min")
        print(f"  📊 {len(findings)} findings | "
              f"{cross_ref['novel_threats']} novel threats | "
              f"{len(self.experiment_queue)} experiments proposed")

        return {
            "findings_count": len(findings),
            "novel_threats": cross_ref["novel_threats"],
            "variants": cross_ref["variants_of_existing"],
            "coverage_pct": cross_ref["coverage_pct"],
            "experiments_proposed": len(self.experiment_queue),
            "time_s": round(total_time, 1),
            "report_path": str(report_path),
        }


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="NAIL Research Scout")
    parser.add_argument("--model", default=None, help="LLM model to use")
    parser.add_argument("--fast", action="store_true", help="Use fast model")
    args = parser.parse_args()

    model = args.model or (FAST_MODEL if args.fast else PRIMARY_MODEL)

    run_id = time.strftime("%Y%m%d_%H%M%S")
    logger = ExperimentLogger(experiment_name="research_scout", run_id=run_id)

    scout = ResearchScout(model=model, logger=logger)
    result = scout.run_full_scan()

    print(f"\n  Report: {result['report_path']}")


if __name__ == "__main__":
    main()
