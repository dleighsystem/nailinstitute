#!/usr/bin/env bash
# scripts/demo_certify.sh
#
# Single-command prospect demo: drive a fake third-party agent through
# the M14 collector → M15 cert pipeline and produce a real, signed,
# sha256-fingerprinted dry-run cert bundle.
#
# Run:
#   ./scripts/demo_certify.sh                     # AAA-grade synthetic agent
#   ./scripts/demo_certify.sh weak                # FAIL-grade synthetic agent
#
# Output:
#   /tmp/nail_demo/<id>/metrics.json
#   /tmp/nail_demo/<id>/certs/dry_run/cert_<id>_<sha12>.json
#
set -euo pipefail

WS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WS"

PROFILE="${1:-aaa}"
case "$PROFILE" in
  aaa)
    AGENT_ID="acme-aaa-bot"
    BREACH=0.01;  BENIGN_TOTAL=50; BENIGN_FPS=0
    SAFE_TOT=20;  SAFE_REJ=0
    HAL_TOT=20;   HAL_HITS=0
    DRIFT=0.05;   P95=2.5
    SYM_AGREED=20; SYM_TOTAL=20
    TOK_EFF=3.0;  EDOS=1; AVAIL=0.999
    ;;
  aa)
    AGENT_ID="acme-aa-bot"
    BREACH=0.05;  BENIGN_TOTAL=50; BENIGN_FPS=2
    SAFE_TOT=20;  SAFE_REJ=1
    HAL_TOT=20;   HAL_HITS=1
    DRIFT=0.10;   P95=8.0
    SYM_AGREED=18; SYM_TOTAL=20
    TOK_EFF=4.5;  EDOS=2; AVAIL=0.99
    ;;
  weak|fail)
    AGENT_ID="acme-weak-bot"
    BREACH=0.30;  BENIGN_TOTAL=50; BENIGN_FPS=10
    SAFE_TOT=20;  SAFE_REJ=10
    HAL_TOT=20;   HAL_HITS=5
    DRIFT=0.40;   P95=45.0
    SYM_AGREED=10; SYM_TOTAL=20
    TOK_EFF=12.0; EDOS=8; AVAIL=0.92
    ;;
  *)
    echo "usage: $0 [aaa|aa|weak]"; exit 2;;
esac

OUT_DIR="/tmp/nail_demo/${AGENT_ID}"
mkdir -p "$OUT_DIR"

# A small synthetic harness-runs corpus (30 fake bench runs).
RUNS_JSON="$OUT_DIR/runs.json"
python - <<PY > "$RUNS_JSON"
import json
print(json.dumps([
    {"passed": 1, "total": 1, "duration_s": 1.0, "cmd": [],
     "returncode": 0, "pass_rate": 1.0, "parse_source": "json",
     "parse_error": "", "apex_url": "", "apex_model_name": "demo"}
    for _ in range(30)
]))
PY

echo "── M14: collect metrics for ${AGENT_ID} (${PROFILE}-grade synthetic) ──"
python -m nail_harness.cli_collect \
  --out "$OUT_DIR/metrics.json" \
  --runs-json "$RUNS_JSON" \
  --agent-id "$AGENT_ID" \
  --certify --dry-run-cert \
  --signoff-by "Demo Operator" \
  --cert-out "$OUT_DIR/certs" \
  --evidence "breach_rate=$BREACH" \
  --evidence "benign_total=$BENIGN_TOTAL" --evidence "benign_fps=$BENIGN_FPS" \
  --evidence "safe_critique_total=$SAFE_TOT" --evidence "safe_critique_rejects=$SAFE_REJ" \
  --evidence "hallucination_total=$HAL_TOT" --evidence "hallucination_hits=$HAL_HITS" \
  --evidence "persona_drift_max=$DRIFT" \
  --evidence "p95_latency_s=$P95" \
  --evidence "symbolic_agreed=$SYM_AGREED" --evidence "symbolic_total=$SYM_TOTAL" \
  --evidence "token_efficiency=$TOK_EFF" \
  --evidence "edos_depth=$EDOS" \
  --evidence "cold_start_avail=$AVAIL"

echo
echo "── bundle ──"
ls -1 "$OUT_DIR/certs"/{,dry_run/}cert_${AGENT_ID}_*.json 2>/dev/null | tail -1
