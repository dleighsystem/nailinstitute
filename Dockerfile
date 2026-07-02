# ═══════════════════════════════════════════════════════════════════════════
# NAIL Institute — Application Container
# ═══════════════════════════════════════════════════════════════════════════
# Lightweight Python image — no GPU needed in this container.
# The NIM models run in their own GPU-enabled containers.
# This container runs the orchestration layer: pipeline, guardrails client,
# PII detector client, data flywheel, tests, etc.
# ═══════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

# System deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install all NAIL packages in editable mode ───────────────────────────
# Copy just pyproject.toml files first for layer caching
COPY rmap/pyproject.toml rmap/pyproject.toml
COPY ave/pyproject.toml ave/pyproject.toml
COPY canary/pyproject.toml canary/pyproject.toml
COPY arena/pyproject.toml arena/pyproject.toml
COPY ctf/pyproject.toml ctf/pyproject.toml
COPY diagnostic/pyproject.toml diagnostic/pyproject.toml
COPY horizon/pyproject.toml horizon/pyproject.toml
COPY integration/pyproject.toml integration/pyproject.toml
COPY nail_monitor/pyproject.toml nail_monitor/pyproject.toml
COPY fleet/pyproject.toml fleet/pyproject.toml
COPY shield/pyproject.toml shield/pyproject.toml
COPY nail_harness/pyproject.toml nail_harness/pyproject.toml
COPY nail_security/pyproject.toml nail_security/pyproject.toml
COPY arsenal/pyproject.toml arsenal/pyproject.toml
COPY threatfeed/pyproject.toml threatfeed/pyproject.toml

# Copy source
COPY . .

# Install all packages in editable mode (matching the venv setup)
RUN pip install --no-cache-dir \
    -e rmap \
    -e ave \
    -e canary \
    -e arena \
    -e ctf \
    -e diagnostic \
    -e horizon \
    -e integration \
    -e nail_monitor \
    -e fleet \
    -e shield \
    -e nail_harness \
    -e nail_security \
    -e arsenal \
    -e threatfeed

# ── Health check endpoint ─────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import integration; print('ok')"

# Default: run the test suite (override with your own command)
CMD ["python", "-m", "pytest", "--tb=short", "-q"]
