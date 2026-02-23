"""Shared utilities for Pydantic vulnerability experiments."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.config import FAST_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import OllamaLLM
from shared.logger import ExperimentLogger

def get_llm():
    return OllamaLLM(FAST_MODEL, OLLAMA_BASE_URL)

def save_results(name: str, data: dict):
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}_results.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"Results saved to {path}")
    return path
