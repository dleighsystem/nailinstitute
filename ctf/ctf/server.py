"""
server — FastAPI web server for CTF Events.

Exposes Agentic CTF tournaments as HTTP endpoints:

  1. POST   /register                — Register a team
  2. GET    /challenges              — List available challenges (redacted flags)
  3. POST   /interact                — Conversation turn in a sandbox
  4. POST   /submit                  — Submit a flag capture attempt
  5. GET    /scoreboard              — Live leaderboard
  6. GET    /team/{name}             — Team stats + submission history
  7. GET    /sandbox/{team}/{cid}    — Sandbox state (turns, tokens, time)
  8. GET    /status                  — Tournament lifecycle state
  9. GET    /health                  — Server health check
  10. GET   /bounties                — List all awarded bounties
  11. POST  /bounty                  — Award a bounty (admin)
  12. GET   /results                 — Final results (after close)
  13. POST  /admin/open              — Open tournament (admin)
  14. POST  /admin/pause             — Pause tournament (admin)
  15. POST  /admin/resume            — Resume tournament (admin)
  16. POST  /admin/close             — Close tournament (admin)

Usage (standalone):
    uvicorn ctf.server:create_app --host 0.0.0.0 --port 9200

Usage (Docker):
    See Dockerfile.ctf and docker-compose.yml
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from fastapi import Request
except ImportError:
    pass

from .challenge import Challenge, Difficulty
from .tournament import Tournament, TournamentState, PrizeTier, EventResult
from .submission import SubmissionVerdict


# ═══════════════════════════════════════════════════════════════════════════
# Server Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CTFServerConfig:
    """Configuration for the CTF web server."""
    host: str = "0.0.0.0"
    port: int = 9200
    admin_token: str = ""
    event_name: str = "NAIL Weekend CTF"
    event_mode: str = "weekend"     # "weekend", "quick", "custom"
    log_dir: str = "logs/ctf"
    max_teams: int = 100
    registration_open: bool = True

    @classmethod
    def from_env(cls) -> "CTFServerConfig":
        return cls(
            host=os.environ.get("CTF_HOST", "0.0.0.0"),
            port=int(os.environ.get("CTF_PORT", "9200")),
            admin_token=os.environ.get("CTF_ADMIN_TOKEN", ""),
            event_name=os.environ.get("CTF_EVENT_NAME", "NAIL Weekend CTF"),
            event_mode=os.environ.get("CTF_EVENT_MODE", "weekend"),
            log_dir=os.environ.get("CTF_LOG_DIR", "logs/ctf"),
            max_teams=int(os.environ.get("CTF_MAX_TEAMS", "100")),
            registration_open=os.environ.get("CTF_REGISTRATION_OPEN", "1") == "1",
        )


# ═══════════════════════════════════════════════════════════════════════════
# App Factory
# ═══════════════════════════════════════════════════════════════════════════

def create_app(config: CTFServerConfig | None = None) -> Any:
    """
    Create the FastAPI app for a CTF event.

    Call this from uvicorn or from the CLI:
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=9200)
    """
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the CTF server. "
            "Install with: pip install 'nail-ctf[server]'"
        )

    cfg = config or CTFServerConfig.from_env()
    log_dir = Path(cfg.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Create tournament based on mode
    if cfg.event_mode == "quick":
        tournament = Tournament.quick_ctf(name=cfg.event_name)
    else:
        tournament = Tournament.weekend_ctf(name=cfg.event_name)

    start_time = time.time()
    server_id = f"ctf-srv-{uuid.uuid4().hex[:8]}"

    # ── Admin auth helper ───────────────────────────────────────

    def _check_admin(request: Request) -> None:
        if not cfg.admin_token:
            return  # No auth configured — open admin
        token = request.headers.get("X-Admin-Token", "")
        if token != cfg.admin_token:
            raise HTTPException(status_code=403, detail="Invalid admin token")

    # ── Build app ───────────────────────────────────────────────

    app = FastAPI(
        title="NAIL CTF Server",
        description="Agentic Capture-The-Flag — Red Team AI Security Events",
        version="2.0.0",
    )

    # ── Health ──────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "server_id": server_id,
            "event": cfg.event_name,
            "tournament_state": tournament.state.value,
            "teams": tournament.scoreboard.team_count,
            "challenges": len(tournament.challenges),
            "uptime_seconds": round(time.time() - start_time, 1),
        }

    # ── Status ──────────────────────────────────────────────────

    @app.get("/status")
    async def status():
        return tournament.status()

    # ── Registration ────────────────────────────────────────────

    @app.post("/register")
    async def register(request: Request):
        body = await request.json()
        team_name = body.get("team_name", "").strip()
        if not team_name:
            raise HTTPException(status_code=400, detail="team_name is required")
        if not cfg.registration_open and tournament.state == TournamentState.REGISTRATION:
            raise HTTPException(status_code=403, detail="Registration is closed")
        if tournament.scoreboard.team_count >= cfg.max_teams:
            raise HTTPException(status_code=403, detail="Maximum teams reached")
        try:
            tournament.register_team(team_name)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("register", {"team": team_name})
        return {"status": "registered", "team_name": team_name}

    # ── Challenges ──────────────────────────────────────────────

    @app.get("/challenges")
    async def challenges():
        return {
            "event": cfg.event_name,
            "state": tournament.state.value,
            "challenges": tournament.challenge_briefings(),
        }

    # ── Interact (conversation turn) ────────────────────────────

    @app.post("/interact")
    async def interact(request: Request):
        body = await request.json()
        team_name = body.get("team_name", "").strip()
        challenge_id = body.get("challenge_id", "").strip()
        user_input = body.get("input", "").strip()
        if not all([team_name, challenge_id, user_input]):
            raise HTTPException(
                status_code=400,
                detail="team_name, challenge_id, and input are required",
            )
        try:
            turn = tournament.interact(team_name, challenge_id, user_input)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("interact", {
            "team": team_name,
            "challenge": challenge_id,
            "turn": turn["turn_number"],
        })
        return turn

    # ── Submit flag ─────────────────────────────────────────────

    @app.post("/submit")
    async def submit(request: Request):
        body = await request.json()
        team_name = body.get("team_name", "").strip()
        challenge_id = body.get("challenge_id", "").strip()
        flag = body.get("flag", "").strip()
        if not all([team_name, challenge_id, flag]):
            raise HTTPException(
                status_code=400,
                detail="team_name, challenge_id, and flag are required",
            )
        try:
            sub = tournament.submit(team_name, challenge_id, flag)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("submit", {
            "team": team_name,
            "challenge": challenge_id,
            "verdict": sub.verdict.value,
            "points": sub.points_awarded,
        })
        return sub.to_dict()

    # ── Scoreboard ──────────────────────────────────────────────

    @app.get("/scoreboard")
    async def scoreboard():
        return {
            "event": cfg.event_name,
            "state": tournament.state.value,
            "rankings": tournament.scoreboard.to_list(),
        }

    # ── Team details ────────────────────────────────────────────

    @app.get("/team/{team_name}")
    async def team_detail(team_name: str):
        ts = tournament.scoreboard.get_team(team_name)
        if ts is None:
            raise HTTPException(status_code=404, detail=f"Team '{team_name}' not found")
        return ts.to_dict()

    # ── Sandbox state ───────────────────────────────────────────

    @app.get("/sandbox/{team_name}/{challenge_id}")
    async def sandbox_state(team_name: str, challenge_id: str):
        try:
            sb = tournament.get_sandbox(team_name, challenge_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        return sb.summary()

    # ── Bounties ────────────────────────────────────────────────

    @app.get("/bounties")
    async def bounties():
        return {
            "bounties": tournament.bounties(),
            "total_usd": tournament.total_bounties_usd(),
        }

    @app.post("/bounty")
    async def award_bounty(request: Request):
        _check_admin(request)
        body = await request.json()
        team = body.get("team", "").strip()
        amount = body.get("amount_usd", 0)
        reason = body.get("reason", "").strip()
        category = body.get("category", "general")
        if not all([team, amount, reason]):
            raise HTTPException(
                status_code=400,
                detail="team, amount_usd, and reason are required",
            )
        bounty = tournament.award_bounty(
            team=team, amount_usd=amount, reason=reason, category=category,
        )
        _log_event("bounty", bounty)
        return bounty

    # ── Results (post-close) ────────────────────────────────────

    @app.get("/results")
    async def results():
        if tournament.state != TournamentState.CLOSED:
            raise HTTPException(
                status_code=400,
                detail="Tournament is not closed yet",
            )
        result = _cached_result()
        return result.summary()

    # ── Admin endpoints ─────────────────────────────────────────

    @app.post("/admin/open")
    async def admin_open(request: Request):
        _check_admin(request)
        try:
            tournament.open()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("admin", {"action": "open"})
        return {"status": "open", "state": tournament.state.value}

    @app.post("/admin/pause")
    async def admin_pause(request: Request):
        _check_admin(request)
        try:
            tournament.pause()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("admin", {"action": "pause"})
        return {"status": "paused", "state": tournament.state.value}

    @app.post("/admin/resume")
    async def admin_resume(request: Request):
        _check_admin(request)
        try:
            tournament.resume()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        _log_event("admin", {"action": "resume"})
        return {"status": "resumed", "state": tournament.state.value}

    @app.post("/admin/close")
    async def admin_close(request: Request):
        _check_admin(request)
        try:
            result = tournament.close()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # Save results
        result_path = log_dir / "event_result.json"
        with open(result_path, "w") as f:
            json.dump(result.summary(), f, indent=2)
        # Draft AVE cards
        cards = result.draft_ave_cards()
        if cards:
            cards_path = log_dir / "draft_ave_cards.json"
            with open(cards_path, "w") as f:
                json.dump(cards, f, indent=2)
        _log_event("admin", {
            "action": "close",
            "teams": result.total_teams,
            "submissions": result.total_submissions,
            "flags_captured": result.total_flags_captured,
        })
        return {
            "status": "closed",
            "summary": result.summary(),
            "draft_ave_cards": len(cards),
        }

    # ── Methodologies (post-close) ──────────────────────────────

    @app.get("/methodologies")
    async def methodologies():
        return {
            "methodologies": tournament.harvest_methodologies(),
        }

    # ── Internal helpers ────────────────────────────────────────

    _event_result_cache: list[EventResult] = []

    def _cached_result() -> EventResult:
        if _event_result_cache:
            return _event_result_cache[0]
        # Re-derive (tournament is already closed)
        rankings = tournament.scoreboard.rankings()
        result = EventResult(
            event_id=tournament.event_id,
            name=tournament.name,
            rankings=rankings,
            total_teams=tournament.scoreboard.team_count,
            total_submissions=len(tournament._submissions),
            total_flags_captured=sum(
                1 for s in tournament._submissions
                if s.verdict == SubmissionVerdict.CORRECT
            ),
            total_challenges=len(tournament._challenges),
        )
        _event_result_cache.append(result)
        return result

    def _log_event(event_type: str, data: dict[str, Any]) -> None:
        """Append event to JSONL log."""
        entry = {
            "timestamp": time.time(),
            "event": event_type,
            **data,
        }
        log_path = log_dir / f"ctf_{cfg.event_name.replace(' ', '_').lower()}.jsonl"
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass  # Non-fatal — don't crash the server for logging

    return app
