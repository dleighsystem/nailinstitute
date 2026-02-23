"""
Vulnerability 5: Type Coercion Masking (The "Helpful" Sabotage)

Tests whether Pydantic's automatic type coercion hides LLM
degradation. When the LLM outputs wrong types (string instead of
bool, int instead of float), Pydantic silently "fixes" them,
masking cognitive degradation.

Key metric: Coercion rate, comparison of strict vs lax mode,
how many garbage outputs pass validation via coercion.
"""
import sys, os, json, time
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger


# ── Schemas: Lax (default) vs Strict ─────────────────────────────

class ThreatLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class LaxSecurityAlert(BaseModel):
    """Default Pydantic — will coerce types silently."""
    is_threat: bool
    threat_level: ThreatLevel
    confidence: float
    affected_systems: int
    description: str

class StrictSecurityAlert(BaseModel):
    """Strict mode — no type coercion."""
    model_config = ConfigDict(strict=True)
    
    is_threat: bool
    threat_level: ThreatLevel
    confidence: float
    affected_systems: int
    description: str


# ── Deliberately ambiguous prompts ───────────────────────────────

SCENARIOS = [
    {
        "name": "clear_threat",
        "prompt": "A confirmed ransomware attack is encrypting files across 47 servers. Classify this security alert.",
        "ambiguity": "none",
    },
    {
        "name": "ambiguous_signal",
        "prompt": "A single failed login from an internal IP at 3am, followed by a successful login 2 minutes later. Could be an employee who mistyped their password, or could be credential stuffing. Classify this.",
        "ambiguity": "moderate",
    },
    {
        "name": "confusing_mixed",
        "prompt": "Traffic analysis shows 0 or 1 systems might be affected, with anywhere from 0% to 100% confidence possible. This could be a threat or could be nothing. Is it true or false that this is a threat? Express your uncertainty numerically. Classify this alert.",
        "ambiguity": "high",
    },
    {
        "name": "type_trap_boolean",
        "prompt": "Is this a threat: 'User logged in from a new device'? Answer the is_threat field. How many systems: maybe zero, maybe one. Confidence: about half.",
        "ambiguity": "type_ambiguous",
    },
    {
        "name": "type_trap_numeric",
        "prompt": "Threat level: somewhere between medium and high. Confidence: 'pretty sure' — express as a number. Systems affected: 'a few'. Is it a threat: 'yes'. Classify.",
        "ambiguity": "type_ambiguous",
    },
    {
        "name": "edge_case_zeros",
        "prompt": "Zero systems affected. Zero confidence. Is it a threat? No — or maybe expressed as 0, or False, or 'false', or 'no'. Threat level is the lowest possible. Classify this non-event.",
        "ambiguity": "edge_case",
    },
]

SCHEMA_PROMPT = """Classify this security alert. Respond with ONLY valid JSON:
{{
  "is_threat": <true or false>,
  "threat_level": "low" | "medium" | "high" | "critical",
  "confidence": <float 0.0 to 1.0>,
  "affected_systems": <integer>,
  "description": "<brief description>"
}}

Alert: {scenario}

Respond with ONLY the JSON object."""


def run_experiment():
    llm = OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)
    logger = ExperimentLogger("pydantic_v5_coercion", "pydantic_vulns")
    
    results = {"lax": [], "strict": [], "raw_types": []}
    
    for scenario in SCENARIOS:
        logger.log_event("scenario", data={"name": scenario["name"]})
        
        prompt = SCHEMA_PROMPT.format(scenario=scenario["prompt"])
        raw = llm.generate(prompt).content
        
        # Extract JSON
        json_str = raw.strip()
        if "```" in json_str:
            json_str = json_str.split("```")[1].replace("json", "").strip()
        
        # Record raw types before any coercion
        raw_types = {}
        parsed_raw = None
        try:
            parsed_raw = json.loads(json_str)
            for k, v in parsed_raw.items():
                raw_types[k] = {"value": str(v)[:50], "type": type(v).__name__}
        except:
            raw_types = {"parse_error": json_str[:200]}
        
        results["raw_types"].append({
            "scenario": scenario["name"],
            "raw_response": raw[:300],
            "parsed_types": raw_types,
        })
        
        # ── Try Lax (default Pydantic) ──
        lax_result = {
            "scenario": scenario["name"],
            "ambiguity": scenario["ambiguity"],
            "valid": False,
            "coercions": [],
        }
        try:
            obj = LaxSecurityAlert(**parsed_raw)
            lax_result["valid"] = True
            lax_result["parsed"] = obj.model_dump()
            lax_result["parsed"]["threat_level"] = obj.threat_level.value
            
            # Detect coercions by comparing raw types to final types
            if parsed_raw:
                if not isinstance(parsed_raw.get("is_threat"), bool):
                    lax_result["coercions"].append(f"is_threat: {type(parsed_raw.get('is_threat')).__name__}→bool")
                if not isinstance(parsed_raw.get("confidence"), float):
                    lax_result["coercions"].append(f"confidence: {type(parsed_raw.get('confidence')).__name__}→float")
                if not isinstance(parsed_raw.get("affected_systems"), int) or isinstance(parsed_raw.get("affected_systems"), bool):
                    lax_result["coercions"].append(f"affected_systems: {type(parsed_raw.get('affected_systems')).__name__}→int")
        except Exception as e:
            lax_result["error"] = str(e)
        
        results["lax"].append(lax_result)
        
        # ── Try Strict ──
        strict_result = {
            "scenario": scenario["name"],
            "ambiguity": scenario["ambiguity"],
            "valid": False,
            "error": None,
        }
        try:
            obj = StrictSecurityAlert(**parsed_raw)
            strict_result["valid"] = True
            strict_result["parsed"] = obj.model_dump()
            strict_result["parsed"]["threat_level"] = obj.threat_level.value
        except Exception as e:
            strict_result["error"] = str(e)[:300]
        
        results["strict"].append(strict_result)
        
        logger.log_metric(f"lax_{scenario['name']}", lax_result)
        logger.log_metric(f"strict_{scenario['name']}", strict_result)
        
        status_lax = "✅" if lax_result["valid"] else "❌"
        status_strict = "✅" if strict_result["valid"] else "❌"
        coerce = len(lax_result.get("coercions", []))
        print(f"  {scenario['name']}: lax={status_lax} strict={status_strict} coercions={coerce}")
    
    # ── Aggregate ──
    n = len(SCENARIOS)
    lax_valid = sum(1 for r in results["lax"] if r["valid"])
    strict_valid = sum(1 for r in results["strict"] if r["valid"])
    total_coercions = sum(len(r.get("coercions", [])) for r in results["lax"])
    
    # "Passed lax but failed strict" = the coercion masking gap
    masking_gap = sum(
        1 for lax, strict in zip(results["lax"], results["strict"])
        if lax["valid"] and not strict["valid"]
    )
    
    # Coercions on ambiguous scenarios specifically
    ambiguous = [r for r in results["lax"] if r["ambiguity"] in ("high", "type_ambiguous", "edge_case")]
    coercions_on_ambiguous = sum(len(r.get("coercions", [])) for r in ambiguous)
    
    summary = {
        "lax_valid_rate": lax_valid / n,
        "strict_valid_rate": strict_valid / n,
        "masking_gap": masking_gap,
        "masking_gap_rate": masking_gap / n,
        "total_coercions": total_coercions,
        "coercions_on_ambiguous": coercions_on_ambiguous,
        "coercion_hides_degradation": masking_gap > 0,
    }
    results["summary"] = summary
    
    from pydantic_vulns.shared_utils import save_results
    save_results("pydantic_v5_coercion", results)
    logger.finalize()
    
    print("\n" + "="*60)
    print("  V5: TYPE COERCION MASKING RESULTS")
    print("="*60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    
    return results


if __name__ == "__main__":
    run_experiment()
