"""
NAIL Institute - Experiment Logger
====================================
Structured logging for all experiments.
Logs to both console (rich) and JSON files for analysis.
Integrates system/GPU monitoring for full observability.
"""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from rich.console import Console
from rich.table import Table

from .config import LOGS_DIR


console = Console()


class ExperimentLogger:
    """
    Structured logger that saves experiment events as JSON Lines (.jsonl)
    for easy post-hoc analysis with pandas.
    
    Optionally starts a SystemMonitor background thread to capture
    GPU, CPU, RAM, and Ollama process stats at regular intervals.
    """

    def __init__(
        self,
        experiment_name: str,
        run_id: Optional[str] = None,
        monitor_interval_s: float = 5.0,
        enable_system_monitor: bool = True,
    ):
        self.experiment_name = experiment_name
        self.run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = LOGS_DIR / experiment_name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"run_{self.run_id}.jsonl"
        self.events: list[dict] = []
        self._start_time = time.time()

        # System monitor (GPU, CPU, RAM, Ollama process)
        self._system_monitor = None
        if enable_system_monitor:
            try:
                from .system_monitor import SystemMonitor
                self._system_monitor = SystemMonitor(
                    experiment_name=experiment_name,
                    run_id=self.run_id,
                    interval_s=monitor_interval_s,
                )
                self._system_monitor.start()
            except Exception as e:
                console.print(f"[yellow]⚠ System monitor failed to start: {e}[/yellow]")

        console.print(
            f"[bold green]📋 Experiment:[/bold green] {experiment_name} | "
            f"[bold cyan]Run:[/bold cyan] {self.run_id} | "
            f"[dim]Monitor: {'✅' if self._system_monitor else '❌'}[/dim]"
        )

    def log_event(
        self,
        event_type: str,
        agent: str = "",
        data: Optional[dict] = None,
        message: str = "",
    ):
        """Log a structured event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_s": round(time.time() - self._start_time, 2),
            "experiment": self.experiment_name,
            "run_id": self.run_id,
            "event_type": event_type,
            "agent": agent,
            "message": message,
            "data": data or {},
        }
        self.events.append(event)

        # Append to JSONL file
        with open(self.log_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Console output
        color = {
            "agent_message": "cyan",
            "agent_response": "green",
            "metric": "yellow",
            "error": "red",
            "round": "magenta",
            "consensus": "bold green",
            "info": "white",
        }.get(event_type, "white")
        console.print(
            f"[{color}][{event_type:>16}][/{color}] "
            f"[dim]{agent:>20}[/dim] {message[:120]}"
        )

    def log_metric(self, metric_name: str, value: Any, agent: str = ""):
        """Convenience: log a numeric / categorical metric."""
        self.log_event(
            event_type="metric",
            agent=agent,
            data={"metric": metric_name, "value": value},
            message=f"{metric_name} = {value}",
        )

    def log_agent_turn(self, agent: str, prompt: str, response: str, tokens: int = 0,
                       throughput: Optional[dict] = None):
        """Log one agent interaction turn with optional throughput data."""
        data = {
            "prompt_preview": prompt[:500],
            "response_preview": response[:500],
            "tokens": tokens,
        }
        if throughput:
            data["throughput"] = throughput
        self.log_event(
            event_type="agent_response",
            agent=agent,
            data=data,
            message=response[:120],
        )

    def log_resource_snapshot(self, label: str = ""):
        """Take an on-demand system resource snapshot and log it."""
        if self._system_monitor:
            snap = self._system_monitor.take_snapshot_now()
            from dataclasses import asdict
            self.log_event(
                event_type="resource_snapshot",
                data=asdict(snap),
                message=f"Resource snapshot: {label}" if label else "Resource snapshot",
            )

    def finalize(self) -> Optional[dict]:
        """
        Stop the system monitor and log a final resource summary.
        Call this at the end of every experiment run.
        Returns the system resource summary dict (or None).
        """
        resource_summary = None
        if self._system_monitor:
            self._system_monitor.stop()
            resource_summary = self._system_monitor.get_summary()
            self.log_event(
                event_type="resource_summary",
                data=resource_summary,
                message="System resource summary (full run)",
            )

            # Print resource summary table
            res_table = Table(title=f"System Resources: {self.experiment_name} ({self.run_id})")
            res_table.add_column("Metric", style="cyan")
            res_table.add_column("Value", style="green")
            for k, v in resource_summary.items():
                res_table.add_row(str(k), str(v))
            console.print(res_table)

        total_elapsed = round(time.time() - self._start_time, 1)
        self.log_event(
            event_type="experiment_complete",
            data={"total_elapsed_s": total_elapsed},
            message=f"Experiment complete in {total_elapsed}s",
        )
        return resource_summary

    def summary_table(self, metrics: dict[str, Any]):
        """Print a rich summary table to console."""
        table = Table(title=f"Results: {self.experiment_name} (run {self.run_id})")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        for k, v in metrics.items():
            table.add_row(str(k), str(v))
        console.print(table)

    def get_log_path(self) -> Path:
        return self.log_file
