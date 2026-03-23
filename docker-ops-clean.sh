#!/usr/bin/env bash
# NAIL Institute — Docker Quick Commands
# ═══════════════════════════════════════════════════════════════════════════
#
# Usage:
#   ./docker-ops.sh start          Start core stack (Nemotron + app)
#   ./docker-ops.sh start-full     Start everything (all 6 NIM + app)
#   ./docker-ops.sh start-guards   Start guardrails NIM models + app
#   ./docker-ops.sh rebuild        Rebuild app after code changes
#   ./docker-ops.sh test           Run full test suite in container
#   ./docker-ops.sh logs           Tail application logs
#   ./docker-ops.sh status         Show container health
#   ./docker-ops.sh stop           Stop everything
#   ./docker-ops.sh gpu            Show GPU memory usage per container
#   ./docker-ops.sh shell          Open bash in the app container
#
# ═══════════════════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
RST='\033[0m'

banner() { echo -e "\n${BLU}══════════════════════════════════════════════════${RST}"; echo -e "${GRN}  $1${RST}"; echo -e "${BLU}══════════════════════════════════════════════════${RST}\n"; }

check_env() {
    if [ ! -f .env ]; then
        echo -e "${YLW}⚠  No .env file found. Creating from template...${RST}"
        cp .env.example .env
        echo -e "${YLW}   Edit .env and add your NGC_API_KEY before starting NIM containers.${RST}"
        echo -e "${YLW}   Then run: docker login nvcr.io -u '\$oauthtoken' -p \$(cat .env | grep NGC_API_KEY | cut -d= -f2)${RST}"
    fi
}

case "${1:-help}" in

    # ── Core Stack Commands ────────────────────────────────────────
    start)
        banner "Starting NAIL core stack (Nemotron + app)"
        check_env
        docker compose up -d nail nim-nemotron
        docker compose logs -f nail
        ;;

    start-full)
        banner "Starting FULL stack (all NIM models + app)"
        check_env
        docker compose --profile full up -d
        docker compose logs -f nail
        ;;

    start-guards)
        banner "Starting guardrails stack (4 NemoGuard + app)"
        check_env
        docker compose --profile guardrails up -d nail nim-nemotron
        docker compose logs -f nail
        ;;

    rebuild)
        banner "Rebuilding NAIL app after code changes"
        docker compose up -d --build --no-deps nail
        docker compose logs -f nail
        ;;

    test)
        banner "Running test suite in container"
        docker compose run --rm nail bash run_all_tests.sh
        ;;

    logs)
        docker compose logs -f "${2:-nail}"
        ;;

    status)
        banner "Container Status"
        docker compose ps -a
        echo ""
        echo -e "${BLU}── Health ──${RST}"
        for c in nail-platform nim-nemotron nim-jailbreak nim-content-reasoning nim-content-8b nim-safety-v3 nim-pii; do
            health=$(docker inspect --format='{{.State.Health.Status}}' "$c" 2>/dev/null || echo "not running")
            case "$health" in
                healthy)   icon="${GRN}✓${RST}" ;;
                unhealthy) icon="${RED}✗${RST}" ;;
                starting)  icon="${YLW}…${RST}" ;;
                *)         icon="${RED}○${RST}" ;;
            esac
            printf "  %b %-25s %s\n" "$icon" "$c" "$health"
        done
        ;;

    stop)
        banner "Stopping all containers"
        docker compose --profile full down
        ;;

    gpu)
        banner "GPU Memory Usage"
        nvidia-smi --query-compute-apps=pid,name,used_memory --format=csv,noheader 2>/dev/null || echo "No GPU processes"
        echo ""
        nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "nvidia-smi unavailable"
        ;;

    shell)
        docker compose exec nail bash
        ;;

    # ── Canary Fleet Commands ──────────────────────────────────────
    canary)
        banner "Starting Canary Fleet — NATIVE (no Docker, port 9000)"
        echo -e "${YLW}  Mode: bait (pattern responses, no LLM)${RST}"
        echo -e "${YLW}  To use NIM LLM: ./docker-ops.sh canary-nim${RST}"
        echo ""
        source .venv/bin/activate 2>/dev/null || true
        python -m canary.cli serve --host 0.0.0.0 --port 9000 --no-llm
        ;;

    canary-docker)
        banner "Starting Canary Fleet — Docker (bait mode, port 9000)"
        echo -e "${YLW}  No NIM/NGC required — runs standalone${RST}"
        docker compose --profile canary up -d --build canary-fleet
        echo -e "${GRN}✓ Canary fleet at http://localhost:9000${RST}"
        docker compose logs -f canary-fleet
        ;;

    canary-nim)
        banner "Starting Canary Fleet — Docker + NIM LLM"
        check_env
        docker compose --profile canary-nim up -d
        echo -e "${GRN}✓ Canary fleet (NIM) at http://localhost:9000${RST}"
        docker compose logs -f canary-fleet-nim
        ;;

    canary-full)
        banner "Starting Canary Fleet + Discord Bot + Monitor"
        check_env
        docker compose -f docker-compose.yml -f docker-compose.canary.yml --profile full up -d
        echo -e "${GRN}✓ Canary web at http://localhost:9000${RST}"
        echo -e "${GRN}✓ Discord bot active${RST}"
        echo -e "${GRN}✓ Monitor watching for incidents${RST}"
        ;;

    canary-logs)
        docker compose logs -f canary-fleet 2>/dev/null || docker compose logs -f canary-fleet-nim 2>/dev/null || echo "No canary container running"
        ;;

    canary-status)
        banner "Canary Fleet Status"
        curl -s http://localhost:9000/health | python3 -m json.tool 2>/dev/null || echo "Canary fleet not running"
        echo ""
        echo -e "${BLU}── Metrics ──${RST}"
        curl -s http://localhost:9000/metrics 2>/dev/null || echo "Metrics unavailable"
        ;;

    canary-stop)
        banner "Stopping Canary Fleet"
        docker compose --profile canary --profile canary-nim down 2>/dev/null
        ;;

    # ── Arena Collider Commands ────────────────────────────────────
    arena)
        banner "Starting Arena Collider — Native (Pathology Collider)"
        echo -e "${YLW}  Mode: standard (50 pop, 10 rounds/season)${RST}"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli run --seasons 5
        ;;

    arena-production)
        banner "Starting Arena Collider — Production 24/7"
        echo -e "${YLW}  Mode: production (200 pop, 50 rounds/season, unlimited)${RST}"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli run --production
        ;;

    arena-docker)
        banner "Starting Arena Collider — Docker"
        docker compose --profile arena up -d --build arena-collider
        echo -e "${GRN}✓ Arena collider running${RST}"
        docker compose logs -f arena-collider
        ;;

    arena-status)
        banner "Arena Collider Status"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli status
        ;;

    arena-export)
        banner "Arena Export — Breakthroughs + Thresholds"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli export
        ;;

    arena-dashboard)
        banner "Arena Dashboard"
        source .venv/bin/activate 2>/dev/null || true
        python -m arena.cli dashboard
        ;;

    arena-stop)
        banner "Stopping Arena Collider"
        docker compose --profile arena down 2>/dev/null
        ;;

    # ── CTF Commands ───────────────────────────────────────────────
    ctf)
        banner "Starting CTF Server (native, weekend mode)"
        source .venv/bin/activate 2>/dev/null || true
        python -m ctf.cli serve --port 9200
        ;;

    ctf-quick)
        banner "Starting CTF Server (native, quick mode)"
        source .venv/bin/activate 2>/dev/null || true
        python -m ctf.cli serve --port 9200 --mode quick --event-name "NAIL Quick CTF"
        ;;

    ctf-docker)
        banner "Starting CTF Server in Docker"
        docker compose --profile ctf up -d --build ctf-server
        echo -e "${GRN}✓ CTF server running on http://localhost:9200${RST}"
        docker compose logs -f ctf-server
        ;;

    ctf-simulate)
        banner "Running CTF Simulation (3 teams)"
        source .venv/bin/activate 2>/dev/null || true
        python -m ctf.cli simulate --teams 3
        ;;

    ctf-challenges)
        banner "Listing CTF Challenges"
        source .venv/bin/activate 2>/dev/null || true
        python -m ctf.cli challenges
        ;;

    ctf-status)
        banner "CTF Server Status"
        curl -s http://localhost:9200/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "CTF server not running"
        ;;

    ctf-stop)
        banner "Stopping CTF Server"
        docker compose --profile ctf down 2>/dev/null
        ;;

    *)
        echo "NAIL Docker Operations"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Core Commands:"
        echo "  start          Start core stack (Nemotron + app)"
        echo "  start-full     Start everything (all 6 NIM + app)"
        echo "  start-guards   Start guardrails NIM models + app"
        echo "  rebuild        Rebuild app after code changes (~10s)"
        echo "  test           Run full test suite in container"
        echo "  logs [name]    Tail container logs (default: nail)"
        echo "  status         Show container health"
        echo "  stop           Stop everything"
        echo "  gpu            Show GPU memory per container"
        echo "  shell          Open bash in app container"
        echo ""
        echo "Canary Fleet Commands:"
        echo "  canary         Start canary native (no Docker, bait mode)"
        echo "  canary-docker  Start canary in Docker (bait mode, no NGC)"
        echo "  canary-nim     Start canary in Docker + NIM LLM (needs NGC)"
        echo "  canary-full    Start fleet + Discord bot + monitor"
        echo "  canary-logs    Tail canary logs"
        echo "  canary-status  Show canary fleet health"
        echo "  canary-stop    Stop canary fleet"
        echo ""
        echo "Arena Collider Commands:"
        echo "  arena           Run Pathology Collider (5 seasons, native)"
        echo "  arena-production Run 24/7 production mode (native)"
        echo "  arena-docker    Run in Docker container"
        echo "  arena-status    Show collider state from checkpoint"
        echo "  arena-export    Export breakthroughs + thresholds"
        echo "  arena-dashboard Print evolution dashboard"
        echo "  arena-stop      Stop arena Docker container"
        echo ""
        echo "CTF Commands:"
        echo "  ctf             Start CTF server (native, weekend mode)"
        echo "  ctf-quick       Start CTF server (native, quick mode)"
        echo "  ctf-docker      Start CTF server in Docker"
        echo "  ctf-simulate    Run CTF simulation (3 teams)"
        echo "  ctf-challenges  List available CTF challenges"
        echo "  ctf-status      Show CTF server health"
        echo "  ctf-stop        Stop CTF server"
        ;;
esac
