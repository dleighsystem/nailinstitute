"""
Vulnerability 2: Pydantic Purgatory — Infinite Validation Loop

Tests whether LangGraph retry loops + Pydantic validation create
infinite cycles where the LLM can't satisfy conflicting schema
constraints and burns tokens trying to guess the "password."

Key metric: Retry count, token burn rate, whether the LLM ever
succeeds vs giving up vs infinite loop.
"""
import sys, os, json, time
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict, Annotated
import operator

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger


# ── Conflicting Pydantic schemas ─────────────────────────────────

class EasySchema(BaseModel):
    """Simple schema — should pass easily."""
    name: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0.0, le=10.0)
    category: str

class ModerateSchema(BaseModel):
    """Moderate conflict — length vs word count tension."""
    description: str = Field(min_length=50, max_length=200)
    keywords: List[str] = Field(min_length=3, max_length=5)
    score: int = Field(ge=1, le=5)
    
    @field_validator("description")
    @classmethod
    def must_be_professional(cls, v):
        if any(w in v.lower() for w in ["maybe", "i think", "probably", "perhaps"]):
            raise ValueError("Description must be definitive, not hedging. Remove words like 'maybe', 'I think', 'probably', 'perhaps'.")
        return v

class HardSchema(BaseModel):
    """Deliberately conflicting constraints."""
    # Must be 50+ chars but max 5 words — very hard
    summary: str = Field(min_length=50, description="Exactly 5 words, each at least 10 characters")
    confidence: float = Field(ge=0.95, le=1.0, description="Must be near-certain")
    tags: List[str] = Field(min_length=3, max_length=3, description="Exactly 3 tags")
    
    @field_validator("summary")
    @classmethod
    def exactly_five_long_words(cls, v):
        words = v.split()
        if len(words) != 5:
            raise ValueError(f"Must be exactly 5 words, got {len(words)}")
        short_words = [w for w in words if len(w) < 10]
        if short_words:
            raise ValueError(f"Each word must be at least 10 characters. These are too short: {short_words}")
        return v

class ImpossibleSchema(BaseModel):
    """Genuinely contradictory constraints — impossible to satisfy."""
    value: str = Field(min_length=100, max_length=50)  # min > max = impossible


# ── LangGraph state ──────────────────────────────────────────────

class RetryState(TypedDict):
    prompt: str
    schema_name: str
    schema_json: str
    raw_response: str
    error_message: str
    attempt: int
    max_attempts: int
    success: bool
    history: Annotated[list, operator.add]


# ── Graph nodes ──────────────────────────────────────────────────

llm = None  # Set at runtime

def generate_node(state: RetryState) -> dict:
    """LLM generates output attempting to satisfy schema."""
    global llm
    
    attempt = state["attempt"]
    error = state.get("error_message", "")
    
    if attempt == 0:
        prompt = f"""{state['prompt']}

You must respond with ONLY valid JSON matching this schema:
{state['schema_json']}

Respond with ONLY the JSON object."""
    else:
        prompt = f"""Your previous response failed validation with this error:
{error}

Please fix your response. The original task was:
{state['prompt']}

Required schema:
{state['schema_json']}

Respond with ONLY the corrected JSON object."""
    
    raw = llm.generate(prompt).content
    
    return {
        "raw_response": raw,
        "attempt": attempt + 1,
        "history": [{"attempt": attempt + 1, "response": raw[:300], "error": error}],
    }


def validate_node(state: RetryState) -> dict:
    """Validate LLM output against the Pydantic schema."""
    schema_map = {
        "easy": EasySchema,
        "moderate": ModerateSchema,
        "hard": HardSchema,
        "impossible": ImpossibleSchema,
    }
    
    schema_cls = schema_map[state["schema_name"]]
    raw = state["raw_response"].strip()
    
    try:
        # Extract JSON
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        parsed = json.loads(raw)
        obj = schema_cls(**parsed)
        return {"success": True, "error_message": ""}
    except json.JSONDecodeError as e:
        return {"success": False, "error_message": f"Invalid JSON: {e}"}
    except Exception as e:
        return {"success": False, "error_message": str(e)}


def should_retry(state: RetryState) -> str:
    """Conditional edge: retry or give up."""
    if state["success"]:
        return "done"
    if state["attempt"] >= state["max_attempts"]:
        return "done"
    return "retry"


# ── Build graph ──────────────────────────────────────────────────

def build_retry_graph():
    graph = StateGraph(RetryState)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", should_retry, {"retry": "generate", "done": END})
    
    return graph.compile()


def run_experiment():
    global llm
    llm = OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)
    logger = ExperimentLogger("pydantic_v2_purgatory", "pydantic_vulns")
    
    MAX_RETRIES = 10
    
    schemas = {
        "easy": {
            "prompt": "Describe a popular movie in structured format.",
            "schema_json": EasySchema.model_json_schema(),
        },
        "moderate": {
            "prompt": "Write a professional product review for a laptop computer. Be definitive and assertive in your description.",
            "schema_json": ModerateSchema.model_json_schema(),
        },
        "hard": {
            "prompt": "Summarize quantum computing in exactly 5 words where each word is at least 10 characters long. Be extremely confident.",
            "schema_json": HardSchema.model_json_schema(),
        },
        "impossible": {
            "prompt": "Write a value that is both at least 100 characters AND at most 50 characters.",
            "schema_json": ImpossibleSchema.model_json_schema(),
        },
    }
    
    app = build_retry_graph()
    results = {}
    
    for schema_name, cfg in schemas.items():
        logger.log_event("trial_start", data={"schema": schema_name})
        t0 = time.time()
        
        initial_state = {
            "prompt": cfg["prompt"],
            "schema_name": schema_name,
            "schema_json": json.dumps(cfg["schema_json"], indent=2),
            "raw_response": "",
            "error_message": "",
            "attempt": 0,
            "max_attempts": MAX_RETRIES,
            "success": False,
            "history": [],
        }
        
        final_state = app.invoke(initial_state)
        elapsed = time.time() - t0
        
        trial_result = {
            "schema": schema_name,
            "success": final_state["success"],
            "attempts": final_state["attempt"],
            "max_attempts": MAX_RETRIES,
            "elapsed_seconds": elapsed,
            "history": final_state["history"],
            "tokens_per_attempt": (llm.total_prompt_tokens + llm.total_completion_tokens) / max(final_state["attempt"], 1),
            "total_tokens": llm.total_prompt_tokens + llm.total_completion_tokens,
            "hit_retry_limit": final_state["attempt"] >= MAX_RETRIES and not final_state["success"],
        }
        
        # Analyze error evolution — does the LLM fix one thing but break another?
        errors = [h["error"] for h in final_state["history"] if h["error"]]
        unique_errors = len(set(errors))
        trial_result["unique_error_types"] = unique_errors
        trial_result["error_oscillation"] = unique_errors > 1 and len(errors) > 2
        
        results[schema_name] = trial_result
        logger.log_metric(f"trial_{schema_name}", trial_result)
        
        print(f"  {schema_name}: {'✅' if final_state['success'] else '❌'} in {final_state['attempt']} attempts ({elapsed:.1f}s)")
        
        # Reset token counter for next trial
        llm.total_prompt_tokens = 0
        llm.total_completion_tokens = 0
    
    # ── Summary ──
    summary = {
        "easy_attempts": results["easy"]["attempts"],
        "moderate_attempts": results["moderate"]["attempts"],
        "hard_attempts": results["hard"]["attempts"],
        "impossible_attempts": results["impossible"]["attempts"],
        "easy_success": results["easy"]["success"],
        "moderate_success": results["moderate"]["success"],
        "hard_success": results["hard"]["success"],
        "impossible_success": results["impossible"]["success"],
        "purgatory_detected": results["hard"]["hit_retry_limit"] or results["impossible"]["hit_retry_limit"],
        "error_oscillation_detected": any(r["error_oscillation"] for r in results.values()),
    }
    results["summary"] = summary
    
    from pydantic_vulns.shared_utils import save_results
    save_results("pydantic_v2_purgatory", results)
    logger.finalize()
    
    print("\n" + "="*60)
    print("  V2: PYDANTIC PURGATORY RESULTS")
    print("="*60)
    for k, v in summary.items():
        print(f"  {k}: {v}")
    
    return results


if __name__ == "__main__":
    run_experiment()
