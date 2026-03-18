#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
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

    *)
        echo "NAIL Docker Operations"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
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
        ;;
esac
