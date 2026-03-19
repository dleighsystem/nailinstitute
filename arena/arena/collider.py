"""
Pathology Collider — 24/7 DGX Arena Runner
============================================

Operationalises the Arena as a continuous daemon that:

  1. Runs adversarial self-play seasons around the clock.
  2. Checkpoints state (populations, configs, logs) to disk after
     every generation so work survives restarts.
  3. Implements the nightly mutation cycle described in Agent-CVE.md:
     evaluate → select best Red attacks → GA-mutate → relaunch.
  4. Auto-publishes breakthroughs as draft AVE cards.
  5. Exports evolved Blue Bridge thresholds to TrapWire / ThreatFeed.
  6. Exposes a status API for monitoring dashboards.

Usage (programmatic):
    >>> from arena.collider import Collider
    >>> c = Collider.standard()
    >>> c.run_forever()  # blocks, runs 24/7

Usage (CLI):
    $ arena run               # standard mode, runs indefinitely
    $ arena run --rounds 50   # single season, 50 rounds
    $ arena status            # show collider state from checkpoint
    $ arena export             # export breakthroughs + thresholds
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .arena import Arena, Breakthrough, SeasonResult
from .swarm import RedSwarm
from .defences import BlueBridge, DefenceConfig
from .vectors import AttackVector, AttackType


# ═══════════════════════════════════════════════════════════════════════════
# Checkpoint — Persist / restore arena state to survive restarts
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Checkpoint:
    """
    Serialisable snapshot of Collider state.

    Saved to disk after every generation so the DGX can be power-cycled
    without losing evolution progress.
    """
    collider_id: str
    season: int
    generation: int
    red_population: list[dict[str, Any]]
    blue_thresholds: dict[str, float]
    breakthroughs: list[dict[str, Any]]
    fitness_trajectory: list[dict[str, float]]
    total_battles: int
    total_red_wins: int
    total_blue_wins: int
    total_breakthroughs: int
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "collider_id": self.collider_id,
            "season": self.season,
            "generation": self.generation,
            "red_population_size": len(self.red_population),
            "blue_thresholds": {k: round(v, 4) for k, v in self.blue_thresholds.items()},
            "breakthroughs_count": len(self.breakthroughs),
            "total_battles": self.total_battles,
            "total_red_wins": self.total_red_wins,
            "total_blue_wins": self.total_blue_wins,
            "total_breakthroughs": self.total_breakthroughs,
            "fitness_trajectory": self.fitness_trajectory[-10:],  # last 10
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def save(self, path: Path) -> None:
        """Save checkpoint to disk as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "collider_id": self.collider_id,
            "season": self.season,
            "generation": self.generation,
            "red_population": self.red_population,
            "blue_thresholds": self.blue_thresholds,
            "breakthroughs": self.breakthroughs,
            "fitness_trajectory": self.fitness_trajectory,
            "total_battles": self.total_battles,
            "total_red_wins": self.total_red_wins,
            "total_blue_wins": self.total_blue_wins,
            "total_breakthroughs": self.total_breakthroughs,
            "timestamp": time.time(),
            "metadata": self.metadata,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        """Load checkpoint from disk."""
        with open(path) as f:
            data = json.load(f)
        return cls(
            collider_id=data.get("collider_id", "unknown"),
            season=data.get("season", 0),
            generation=data.get("generation", 0),
            red_population=data.get("red_population", []),
            blue_thresholds=data.get("blue_thresholds", {}),
            breakthroughs=data.get("breakthroughs", []),
            fitness_trajectory=data.get("fitness_trajectory", []),
            total_battles=data.get("total_battles", 0),
            total_red_wins=data.get("total_red_wins", 0),
            total_blue_wins=data.get("total_blue_wins", 0),
            total_breakthroughs=data.get("total_breakthroughs", 0),
            timestamp=data.get("timestamp", 0.0),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def empty(cls, collider_id: str = "") -> Checkpoint:
        cid = collider_id or f"collider-{uuid.uuid4().hex[:8]}"
        return cls(
            collider_id=cid,
            season=0,
            generation=0,
            red_population=[],
            blue_thresholds={},
            breakthroughs=[],
            fitness_trajectory=[],
            total_battles=0,
            total_red_wins=0,
            total_blue_wins=0,
            total_breakthroughs=0,
            timestamp=time.time(),
        )


# ═══════════════════════════════════════════════════════════════════════════
# Nightly Schedule — Configures the mutation/evolution cycle
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Schedule:
    """
    Controls the evolution cadence.

    In production the Collider runs 24/7 with the nightly cycle:
      • Day: run battles at the current generation.
      • Night: evaluate → GA-mutate → checkpoint → restart.

    For testing/development, shorter cycles are used.
    """
    rounds_per_season: int = 10       # battles per generation per season
    seasons_per_cycle: int = 1        # seasons before nightly checkpoint
    cooldown_seconds: float = 0.0     # pause between seasons (0 for max speed)
    max_seasons: int = 0              # 0 = unlimited (run forever)
    checkpoint_every: int = 1         # save state every N seasons

    @classmethod
    def quick(cls) -> Schedule:
        """Quick schedule for testing (~seconds)."""
        return cls(rounds_per_season=3, seasons_per_cycle=1, max_seasons=2)

    @classmethod
    def standard(cls) -> Schedule:
        """Standard schedule (~minutes)."""
        return cls(rounds_per_season=10, seasons_per_cycle=3, max_seasons=0)

    @classmethod
    def nightly(cls) -> Schedule:
        """Full nightly cycle (~hours). Max speed, run until stopped."""
        return cls(
            rounds_per_season=50,
            seasons_per_cycle=10,
            cooldown_seconds=1.0,
            max_seasons=0,
            checkpoint_every=1,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Collider Hooks — Extension points for integrations
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ColliderHooks:
    """
    Callback hooks for integrating the Collider with external systems.

    Set any hook to inject custom behaviour at key lifecycle points.
    """
    on_season_start: Callable[[int], None] | None = None
    on_season_end: Callable[[SeasonResult], None] | None = None
    on_breakthrough: Callable[[Breakthrough], None] | None = None
    on_checkpoint: Callable[[Checkpoint], None] | None = None
    on_generation: Callable[[int, dict[str, Any]], None] | None = None
    on_shutdown: Callable[[], None] | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Collider — The 24/7 Pathology Collider Engine
# ═══════════════════════════════════════════════════════════════════════════

class Collider:
    """
    Pathology Collider — Continuous adversarial evolution on DGX.

    Wraps the Arena in an operational daemon loop with:
      • Checkpointing (survives restarts)
      • Nightly mutation scheduling
      • Breakthrough auto-publishing
      • Threshold export for TrapWire/ThreatFeed
      • Hook system for integrations

    Usage:
        collider = Collider.standard()
        collider.run_forever()   # blocks — production 24/7 mode

        # Or single-cycle for testing:
        collider = Collider.quick()
        result = collider.run_cycle()
    """

    def __init__(
        self,
        arena: Arena | None = None,
        schedule: Schedule | None = None,
        checkpoint_dir: str | Path = "logs/arena",
        hooks: ColliderHooks | None = None,
    ):
        self.arena = arena or Arena.standard()
        self.schedule = schedule or Schedule.standard()
        self.checkpoint_dir = Path(checkpoint_dir)
        self.hooks = hooks or ColliderHooks()
        self.collider_id = f"collider-{uuid.uuid4().hex[:8]}"

        # Running state
        self._running = False
        self._seasons_completed = 0
        self._all_breakthroughs: list[Breakthrough] = []
        self._all_results: list[SeasonResult] = []
        self._total_battles = 0
        self._total_red_wins = 0
        self._total_blue_wins = 0
        self._start_time = 0.0
        self._checkpoint: Checkpoint | None = None

    # ── Factory constructors ────────────────────────────────────

    @classmethod
    def quick(cls) -> Collider:
        """Quick collider for testing (~seconds)."""
        return cls(
            arena=Arena.quick(),
            schedule=Schedule.quick(),
        )

    @classmethod
    def standard(cls) -> Collider:
        """Standard collider for development (~minutes)."""
        return cls(
            arena=Arena.standard(),
            schedule=Schedule.standard(),
        )

    @classmethod
    def production(cls, checkpoint_dir: str = "logs/arena") -> Collider:
        """Production collider for 24/7 DGX operation."""
        return cls(
            arena=Arena.maximum(),
            schedule=Schedule.nightly(),
            checkpoint_dir=checkpoint_dir,
        )

    # ── Main loop ───────────────────────────────────────────────

    def run_cycle(self) -> list[SeasonResult]:
        """
        Run one complete evolution cycle (N seasons per schedule).

        Returns the season results. Use this for testing or single-shot.
        """
        self._start_time = time.time()
        cycle_results: list[SeasonResult] = []

        for i in range(self.schedule.seasons_per_cycle):
            self._seasons_completed += 1
            season_num = self._seasons_completed

            # Hook: season start
            if self.hooks.on_season_start:
                self.hooks.on_season_start(season_num)

            # Run season
            result = self.arena.run_season(
                rounds=self.schedule.rounds_per_season,
            )
            cycle_results.append(result)
            self._all_results.append(result)

            # Accumulate stats
            self._total_battles += result.total_battles
            self._total_red_wins += result.red_wins
            self._total_blue_wins += result.blue_wins

            # Process breakthroughs
            for bt in result.breakthroughs:
                self._all_breakthroughs.append(bt)
                if self.hooks.on_breakthrough:
                    self.hooks.on_breakthrough(bt)

            # Hook: season end
            if self.hooks.on_season_end:
                self.hooks.on_season_end(result)

            # Hook: generation stats
            if self.hooks.on_generation:
                stats = self.arena.red.stats()
                self.hooks.on_generation(
                    self.arena.red.generation,
                    stats.to_dict(),
                )

            # Checkpoint
            if season_num % self.schedule.checkpoint_every == 0:
                self.save_checkpoint()

            # Cooldown
            if self.schedule.cooldown_seconds > 0 and i < self.schedule.seasons_per_cycle - 1:
                time.sleep(self.schedule.cooldown_seconds)

        return cycle_results

    def run_forever(self) -> None:
        """
        Run the collider indefinitely (24/7 production mode).

        Blocks the calling thread. Stop by calling stop() from
        another thread or by sending SIGINT.
        """
        self._running = True
        self._start_time = time.time()
        cycle_count = 0

        try:
            while self._running:
                cycle_count += 1
                self.run_cycle()

                # Check max_seasons limit
                if (self.schedule.max_seasons > 0
                        and self._seasons_completed >= self.schedule.max_seasons):
                    break
        except KeyboardInterrupt:
            pass
        finally:
            self._running = False
            self.save_checkpoint()
            if self.hooks.on_shutdown:
                self.hooks.on_shutdown()

    def stop(self) -> None:
        """Signal the collider to stop after the current season."""
        self._running = False

    # ── Checkpointing ──────────────────────────────────────────

    def save_checkpoint(self) -> Checkpoint:
        """Save current state to disk."""
        # Serialise Red population
        red_pop = []
        for vec in self.arena.red.population:
            red_pop.append({
                "vector_id": vec.vector_id,
                "attack_type": vec.attack_type.value,
                "genes": {k: round(v, 6) for k, v in vec.genes.items()},
                "fitness": round(vec.fitness, 6),
                "generation": vec.generation,
                "wins": vec.wins,
                "losses": vec.losses,
            })

        # Fitness trajectory
        trajectory = self.arena.red.fitness_trajectory()

        cp = Checkpoint(
            collider_id=self.collider_id,
            season=self._seasons_completed,
            generation=self.arena.red.generation,
            red_population=red_pop,
            blue_thresholds=dict(self.arena.blue.config.thresholds),
            breakthroughs=[bt.to_dict() for bt in self._all_breakthroughs],
            fitness_trajectory=trajectory,
            total_battles=self._total_battles,
            total_red_wins=self._total_red_wins,
            total_blue_wins=self._total_blue_wins,
            total_breakthroughs=len(self._all_breakthroughs),
            timestamp=time.time(),
            metadata={
                "arena_mode": "production" if self.schedule.rounds_per_season >= 50 else "standard",
                "uptime": time.time() - self._start_time if self._start_time else 0,
            },
        )

        cp.save(self.checkpoint_dir / "checkpoint.json")
        self._checkpoint = cp

        if self.hooks.on_checkpoint:
            self.hooks.on_checkpoint(cp)

        return cp

    def load_checkpoint(self, path: Path | None = None) -> bool:
        """
        Restore state from a checkpoint file.

        Returns True if a checkpoint was loaded, False if none found.
        """
        cp_path = path or (self.checkpoint_dir / "checkpoint.json")
        if not cp_path.exists():
            return False

        cp = Checkpoint.load(cp_path)
        self._checkpoint = cp
        self.collider_id = cp.collider_id
        self._seasons_completed = cp.season
        self._total_battles = cp.total_battles
        self._total_red_wins = cp.total_red_wins
        self._total_blue_wins = cp.total_blue_wins

        # Restore Red population
        if cp.red_population:
            vectors = []
            for v_data in cp.red_population:
                vec = AttackVector(
                    attack_type=AttackType(v_data["attack_type"]),
                    genes=v_data.get("genes", {}),
                    fitness=v_data.get("fitness", 0.0),
                    generation=v_data.get("generation", 0),
                )
                vec.wins = v_data.get("wins", 0)
                vec.losses = v_data.get("losses", 0)
                vectors.append(vec)
            self.arena.red.seed(population=vectors)
            self.arena.red.generation = cp.generation

        # Restore Blue config
        if cp.blue_thresholds:
            config = DefenceConfig(
                thresholds=cp.blue_thresholds,
                generation=cp.generation,
            )
            self.arena.blue = BlueBridge(config=config)

        return True

    # ── Results & Export ────────────────────────────────────────

    def draft_ave_cards(self) -> list[dict[str, Any]]:
        """Export all breakthrough AVE cards discovered so far."""
        return [bt.draft_ave_card() for bt in self._all_breakthroughs]

    def export_thresholds(self) -> dict[str, float]:
        """Export evolved Blue Bridge defence thresholds."""
        return self.arena.export_thresholds()

    def export_red_signatures(self) -> list[dict[str, Any]]:
        """Export successful Red attack gene profiles."""
        return self.arena.export_red_signatures()

    def export_report(self) -> dict[str, Any]:
        """Full export: thresholds + signatures + cards + trajectory."""
        return {
            "collider_id": self.collider_id,
            "seasons_completed": self._seasons_completed,
            "generation": self.arena.red.generation,
            "total_battles": self._total_battles,
            "total_red_wins": self._total_red_wins,
            "total_blue_wins": self._total_blue_wins,
            "breach_rate": round(
                self._total_red_wins / max(1, self._total_battles), 4
            ),
            "breakthroughs": len(self._all_breakthroughs),
            "draft_ave_cards": self.draft_ave_cards(),
            "evolved_thresholds": self.export_thresholds(),
            "red_signatures": self.export_red_signatures(),
            "fitness_trajectory": self.arena.red.fitness_trajectory()[-20:],
        }

    # ── Status ──────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Current collider status for monitoring/dashboards."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "collider_id": self.collider_id,
            "running": self._running,
            "seasons_completed": self._seasons_completed,
            "generation": self.arena.red.generation,
            "red_population": len(self.arena.red.population),
            "blue_detectors": len(self.arena.blue.config.thresholds),
            "total_battles": self._total_battles,
            "total_red_wins": self._total_red_wins,
            "total_blue_wins": self._total_blue_wins,
            "breach_rate": round(
                self._total_red_wins / max(1, self._total_battles), 4
            ),
            "breakthroughs": len(self._all_breakthroughs),
            "uptime_seconds": round(uptime, 1),
            "checkpoint_dir": str(self.checkpoint_dir),
            "schedule": {
                "rounds_per_season": self.schedule.rounds_per_season,
                "seasons_per_cycle": self.schedule.seasons_per_cycle,
                "max_seasons": self.schedule.max_seasons,
            },
        }

    @property
    def breakthroughs(self) -> list[Breakthrough]:
        """All breakthroughs discovered across all seasons."""
        return list(self._all_breakthroughs)

    @property
    def results(self) -> list[SeasonResult]:
        """All season results."""
        return list(self._all_results)
