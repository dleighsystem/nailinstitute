"""
Vulnerability 1: The Procrustean Bed — Premature Schema Coercion

Tests whether forcing LLM output into strict Pydantic schemas causes
silent discarding of critical nuance. The LLM encounters edge cases
that don't fit the schema's Enum choices and must coerce its answer.

Key metric: How often does the LLM silently misclassify an anomaly
as "normal" just because the schema demands a valid Enum value?
"""
import sys, os, json, time, traceback
from typing import Optional, Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict, Annotated

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

# ── Pydantic schemas (deliberately restrictive) ──────────────────

class ThreatAnalysis(BaseModel):
    """Restrictive schema — forces classification into limited categories."""
    status: Literal["normal", "suspicious", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    category: Literal["malware", "phishing", "brute_force", "dos", "none"]
    summary: str = Field(max_length=100)

class ThreatAnalysisWithCoT(BaseModel):
    """Schema that allows chain-of-thought before structured output."""
    chain_of_thought: str = Field(description="Your reasoning process before classification")
    status: Literal["normal", "suspicious", "critical"]
    confidence: float = Field(ge=0.0, le=1.0)
    category: Literal["malware", "phishing", "brute_force", "dos", "none"]
    summary: str = Field(max_length=100)

# ── Graph state ──────────────────────────────────────────────────

class AnalysisState(TypedDict):
    scenario: str
    raw_response: str
    parsed: Optional[dict]
    parse_success: bool
    retries: int

# ── Test scenarios (designed to defy the schema) ─────────────────

SCENARIOS = [
    {
        "name": "novel_zero_day",
        "description": "A never-before-seen exploit that combines supply chain compromise with firmware-level persistence and uses quantum-resistant encryption for C2 communication. It doesn't match malware, phishing, brute_force, or dos categories.",
        "expected_struggle": True,
        "true_nature": "novel_category_not_in_enum"
    },
    {
        "name": "insider_social_engineering",
        "description": "An employee with legitimate credentials is being slowly manipulated by an external actor through personal relationships to gradually escalate their access privileges. There's no malware, no phishing email, no brute force — just subtle human manipulation.",
        "expected_struggle": True,
        "true_nature": "social_engineering_not_in_enum"
    },
    {
        "name": "ambiguous_anomaly",
        "description": "Network traffic shows a 3.7% deviation from baseline at 3am, with packets going to a legitimate CDN but with unusual TLS certificate pinning behavior. This could be nothing, could be critical, or could be an early indicator of something unprecedented.",
        "expected_struggle": True,
        "true_nature": "genuinely_ambiguous"
    },
    {
        "name": "obvious_malware",
        "description": "A known ransomware binary (SHA256 matches VirusTotal database) was detected executing on a workstation, encrypting files with .locked extension.",
        "expected_struggle": False,
        "true_nature": "malware"
    },
    {
        "name": "clear_normal",
        "description": "Routine automated backup process running at its scheduled time, generating expected network traffic to the backup server.",
        "expected_struggle": False,
        "true_nature": "normal_activity"
    },
    {
        "name": "physical_intrusion",
        "description": "Security cameras detected an unidentified person tailgating through a badge-access door at 2am, who then connected a small USB device to an unattended workstation for 30 seconds before leaving. The USB device type is unknown.",
        "expected_struggle": True,
        "true_nature": "physical_intrusion_not_in_enum"
    },
]


def run_experiment():
    llm = OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)
    logger = ExperimentLogger("pydantic_v1_procrustean", "pydantic_vulns")
    
    results = {
        "strict_schema": [],
        "cot_schema": [],
        "free_text": [],
    }
    
    for scenario in SCENARIOS:
        logger.log_event("scenario", data={"name": scenario["name"], "expected_struggle": scenario["expected_struggle"]})
        
        # ── Condition 1: Strict schema (no CoT) ──
        strict_prompt = f"""Analyze this security scenario and respond with ONLY valid JSON matching this exact schema:
{{
  "status": "normal" | "suspicious" | "critical",
  "confidence": <float 0.0-1.0>,
  "category": "malware" | "phishing" | "brute_force" | "dos" | "none",
  "summary": "<max 100 chars>"
}}

Scenario: {scenario['description']}

Respond with ONLY the JSON object, no other text."""

        strict_raw = llm.generate(strict_prompt).content
        strict_result = {"scenario": scenario["name"], "raw": strict_raw, "parsed": None, "valid": False, "coerced": False}
        try:
            # Try to extract JSON from the response
            json_str = strict_raw.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1].replace("json", "").strip()
            parsed_dict = json.loads(json_str)
            obj = ThreatAnalysis(**parsed_dict)
            strict_result["parsed"] = obj.model_dump()
            strict_result["valid"] = True
            # Check if it was coerced (novel scenario mapped to existing category)
            if scenario["expected_struggle"] and obj.category != "none":
                strict_result["coerced"] = True
            if scenario["expected_struggle"] and obj.status == "normal":
                strict_result["coerced"] = True
        except Exception as e:
            strict_result["error"] = str(e)
        
        results["strict_schema"].append(strict_result)
        logger.log_metric(f"strict_{scenario['name']}", strict_result)
        
        # ── Condition 2: Schema with Chain of Thought ──
        cot_prompt = f"""Analyze this security scenario. First, write your complete reasoning process. Then provide your classification.

Respond with ONLY valid JSON matching this schema:
{{
  "chain_of_thought": "<your full reasoning>",
  "status": "normal" | "suspicious" | "critical",
  "confidence": <float 0.0-1.0>,
  "category": "malware" | "phishing" | "brute_force" | "dos" | "none",
  "summary": "<max 100 chars>"
}}

Scenario: {scenario['description']}

Respond with ONLY the JSON object, no other text."""

        cot_raw = llm.generate(cot_prompt).content
        cot_result = {"scenario": scenario["name"], "raw": cot_raw, "parsed": None, "valid": False, "coerced": False}
        try:
            json_str = cot_raw.strip()
            if "```" in json_str:
                json_str = json_str.split("```")[1].replace("json", "").strip()
            parsed_dict = json.loads(json_str)
            obj = ThreatAnalysisWithCoT(**parsed_dict)
            cot_result["parsed"] = obj.model_dump()
            cot_result["valid"] = True
            cot_result["cot_length"] = len(obj.chain_of_thought)
            cot_result["cot_mentions_limitation"] = any(
                w in obj.chain_of_thought.lower() 
                for w in ["doesn't fit", "not exactly", "none of", "closest", "difficult to classify", "doesn't match", "no exact"]
            )
            if scenario["expected_struggle"] and obj.category != "none":
                cot_result["coerced"] = True
            if scenario["expected_struggle"] and obj.status == "normal":
                cot_result["coerced"] = True
        except Exception as e:
            cot_result["error"] = str(e)
        
        results["cot_schema"].append(cot_result)
        logger.log_metric(f"cot_{scenario['name']}", cot_result)
        
        # ── Condition 3: Free text (no schema constraint) ──
        free_prompt = f"""Analyze this security scenario. Provide your complete assessment including:
- How serious is this? 
- Does it fit neatly into standard categories (malware, phishing, brute force, DoS)? If not, explain why.
- What nuances or uncertainties exist?
- What would you recommend?

Scenario: {scenario['description']}"""

        free_raw = llm.generate(free_prompt).content
        free_result = {
            "scenario": scenario["name"],
            "raw": free_raw,
            "length": len(free_raw),
            "mentions_novelty": any(
                w in free_raw.lower() 
                for w in ["novel", "unprecedented", "new type", "doesn't fit", "unusual", "unique", "not standard", "beyond typical"]
            ),
            "mentions_uncertainty": any(
                w in free_raw.lower() 
                for w in ["uncertain", "unclear", "ambiguous", "could be", "might be", "not sure", "difficult to say", "hard to determine"]
            ),
            "expresses_nuance": any(
                w in free_raw.lower()
                for w in ["however", "on the other hand", "but also", "although", "nevertheless", "complexity", "nuance"]
            ),
        }
        results["free_text"].append(free_result)
        logger.log_metric(f"free_{scenario['name']}", free_result)
    
    # ── Aggregate analysis ──
    struggle_scenarios = [s for s in SCENARIOS if s["expected_struggle"]]
    n_struggle = len(struggle_scenarios)
    
    strict_coercion_rate = sum(1 for r in results["strict_schema"] if r["coerced"]) / n_struggle
    cot_coercion_rate = sum(1 for r in results["cot_schema"] if r["coerced"]) / n_struggle
    strict_valid_rate = sum(1 for r in results["strict_schema"] if r["valid"]) / len(SCENARIOS)
    cot_valid_rate = sum(1 for r in results["cot_schema"] if r["valid"]) / len(SCENARIOS)
    
    # How much nuance is lost in schema vs free text
    free_nuance_rate = sum(1 for r in results["free_text"] if r["mentions_novelty"] or r["mentions_uncertainty"]) / n_struggle
    cot_awareness_rate = sum(1 for r in results["cot_schema"] if r.get("cot_mentions_limitation", False)) / n_struggle
    
    summary = {
        "strict_schema_valid_rate": strict_valid_rate,
        "cot_schema_valid_rate": cot_valid_rate,
        "strict_coercion_rate": strict_coercion_rate,
        "cot_coercion_rate": cot_coercion_rate,
        "free_text_nuance_rate": free_nuance_rate,
        "cot_awareness_rate": cot_awareness_rate,
        "coercion_reduction_with_cot": strict_coercion_rate - cot_coercion_rate,
    }
    
    results["summary"] = summary
    logger.log_metric("summary", summary)
    
    from pydantic_vulns.shared_utils import save_results
    save_results("pydantic_v1_procrustean", results)
    
    logger.finalize()
    
    print("\n" + "="*60)
    print("  V1: PROCRUSTEAN BED RESULTS")
    print("="*60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    
    return results


if __name__ == "__main__":
    run_experiment()
