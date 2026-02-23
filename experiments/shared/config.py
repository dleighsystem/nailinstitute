"""
NAIL Institute - Experiment Configuration
==========================================
Central configuration for all experiments.
Uses local Ollama LLM models.
"""

import os
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"

LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ─── Ollama Configuration ────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Primary model for reasoning tasks — pick the best model you have available.
# nemotron:70b is your most powerful; fall back to smaller ones for speed.
PRIMARY_MODEL = os.getenv("NAIL_PRIMARY_MODEL", "nemotron:70b")

# Faster / smaller model for lightweight agent tasks
FAST_MODEL = os.getenv("NAIL_FAST_MODEL", "mistral:7b-instruct")

# Coding-specific model
CODE_MODEL = os.getenv("NAIL_CODE_MODEL", "deepseek-coder:6.7b-instruct")

# ─── Embedding model (sentence-transformers, runs locally on GPU) ────────────
EMBEDDING_MODEL = os.getenv(
    "NAIL_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
)

# ─── ChromaDB ────────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = str(DATA_DIR / "chromadb")

# ─── Experiment Defaults ─────────────────────────────────────────────────────
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 4096
MAX_AGENT_ROUNDS = 30       # safety cap for consensus experiments
TOKEN_BUDGET_DEFAULT = 10000 # for experiment 3

# ─── Docker Sandbox ──────────────────────────────────────────────────────────
DOCKER_IMAGE = "nail-sandbox:latest"
DOCKER_TIMEOUT = 120  # seconds

print(f"[NAIL Config] Primary: {PRIMARY_MODEL} | Fast: {FAST_MODEL} | Code: {CODE_MODEL}")
print(f"[NAIL Config] Ollama: {OLLAMA_BASE_URL}")
