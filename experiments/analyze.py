#!/usr/bin/env python3
"""
NAIL Institute — Post-Hoc Analysis Dashboard
==============================================
Loads experiment logs (JSONL) and system monitor data,
generates plots and summary reports.

Usage:
  conda activate nail_experiments
  cd /home/dleighsystems/Desktop/NAIL\ institute/experiments

  # Analyze a specific experiment run:
  python analyze.py --experiment exp1_memory_pollution --run control

  # Analyze all runs for an experiment:
  python analyze.py --experiment exp2_consensus_paralysis

  # Full analysis across all experiments:
  python analyze.py --all

  # Just GPU/system analysis:
  python analyze.py --system-only --experiment exp1_memory_pollution --run control
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared.config import LOGS_DIR, DATA_DIR

console = Console()
OUTPUT_DIR = DATA_DIR / "analysis"
OUTPUT_DIR.mkdir(exist_ok=True)


# ─── Data Loading ────────────────────────────────────────────────────────────

def load_experiment_log(experiment: str, run_id: str) -> pd.DataFrame:
    """Load a single experiment run JSONL log into a DataFrame."""
    log_file = LOGS_DIR / experiment / f"run_{run_id}.jsonl"
    if not log_file.exists():
        console.print(f"[red]Log file not found: {log_file}[/red]")
        return pd.DataFrame()
    df = pd.read_json(log_file, lines=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_system_log(experiment: str, run_id: str) -> pd.DataFrame:
    """Load system monitor JSONL log into a DataFrame."""
    log_file = LOGS_DIR / experiment / f"system_{run_id}.jsonl"
    if not log_file.exists():
        console.print(f"[yellow]System log not found: {log_file}[/yellow]")
        return pd.DataFrame()
    df = pd.read_json(log_file, lines=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def discover_runs(experiment: str) -> list[str]:
    """Find all run IDs for an experiment."""
    exp_dir = LOGS_DIR / experiment
    if not exp_dir.exists():
        return []
    runs = set()
    for f in exp_dir.glob("run_*.jsonl"):
        run_id = f.stem.replace("run_", "")
        runs.add(run_id)
    return sorted(runs)


def discover_experiments() -> list[str]:
    """Find all experiments that have log data."""
    if not LOGS_DIR.exists():
        return []
    return sorted([d.name for d in LOGS_DIR.iterdir() if d.is_dir() and list(d.glob("*.jsonl"))])


# ─── Token Usage Analysis ───────────────────────────────────────────────────

def analyze_token_usage(df: pd.DataFrame, experiment: str, run_id: str):
    """Analyze and plot token usage patterns."""
    agent_events = df[df["event_type"] == "agent_response"].copy()
    if agent_events.empty:
        console.print("[yellow]No agent events found for token analysis[/yellow]")
        return

    # Extract token counts from data column
    agent_events["tokens"] = agent_events["data"].apply(lambda d: d.get("tokens", 0) if isinstance(d, dict) else 0)

    # Per-agent token breakdown
    agent_totals = agent_events.groupby("agent")["tokens"].agg(["sum", "count", "mean", "max"])
    agent_totals.columns = ["total_tokens", "num_calls", "avg_tokens", "max_tokens"]
    agent_totals = agent_totals.sort_values("total_tokens", ascending=False)

    table = Table(title=f"Token Usage by Agent — {experiment}/{run_id}")
    table.add_column("Agent", style="cyan")
    table.add_column("Total Tokens", style="green", justify="right")
    table.add_column("Calls", justify="right")
    table.add_column("Avg/Call", justify="right")
    table.add_column("Max/Call", justify="right")
    for agent_name, row in agent_totals.iterrows():
        table.add_row(
            str(agent_name),
            f"{int(row['total_tokens']):,}",
            str(int(row["num_calls"])),
            f"{row['avg_tokens']:,.0f}",
            f"{int(row['max_tokens']):,}",
        )
    console.print(table)

    # Plot: cumulative tokens over time
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"Token Analysis — {experiment}/{run_id}", fontsize=14, fontweight="bold")

    # 1. Cumulative tokens over elapsed time
    ax = axes[0, 0]
    for agent_name, group in agent_events.groupby("agent"):
        cumtokens = group["tokens"].cumsum()
        ax.plot(group["elapsed_s"], cumtokens, label=agent_name, linewidth=2)
    ax.set_xlabel("Elapsed Time (s)")
    ax.set_ylabel("Cumulative Tokens")
    ax.set_title("Cumulative Token Usage per Agent")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    # 2. Tokens per call (bar distribution)
    ax = axes[0, 1]
    agent_names = agent_totals.index.tolist()
    bars = ax.bar(agent_names, agent_totals["total_tokens"], color=plt.cm.Set2(range(len(agent_names))))
    ax.set_xlabel("Agent")
    ax.set_ylabel("Total Tokens")
    ax.set_title("Total Tokens by Agent")
    ax.tick_params(axis="x", rotation=45)
    for bar, val in zip(bars, agent_totals["total_tokens"]):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                f"{int(val):,}", ha="center", va="bottom", fontsize=8)

    # 3. Token usage per call (histogram)
    ax = axes[1, 0]
    ax.hist(agent_events["tokens"], bins=30, edgecolor="black", alpha=0.7, color="steelblue")
    ax.set_xlabel("Tokens per Call")
    ax.set_ylabel("Frequency")
    ax.set_title("Distribution of Tokens per LLM Call")
    ax.axvline(agent_events["tokens"].mean(), color="red", linestyle="--", label=f"Mean: {agent_events['tokens'].mean():.0f}")
    ax.legend()

    # 4. Token usage over time (scatter)
    ax = axes[1, 1]
    for agent_name, group in agent_events.groupby("agent"):
        ax.scatter(group["elapsed_s"], group["tokens"], label=agent_name, alpha=0.6, s=20)
    ax.set_xlabel("Elapsed Time (s)")
    ax.set_ylabel("Tokens per Call")
    ax.set_title("Tokens per Call Over Time")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    outpath = OUTPUT_DIR / f"tokens_{experiment}_{run_id}.png"
    plt.savefig(outpath, dpi=150)
    plt.close()
    console.print(f"[green]📊 Token chart saved: {outpath}[/green]")


# ─── Throughput Analysis ────────────────────────────────────────────────────

def analyze_throughput(df: pd.DataFrame, experiment: str, run_id: str):
    """Analyze and plot LLM throughput (tokens/sec, TTFT, latency)."""
    agent_events = df[df["event_type"] == "agent_response"].copy()
    if agent_events.empty:
        return

    # Extract throughput data
    def extract_throughput(data):
        if isinstance(data, dict) and "throughput" in data:
            return data["throughput"]
        return {}

    tp = agent_events["data"].apply(extract_throughput).apply(pd.Series)
    if tp.empty or "tokens_per_second" not in tp.columns:
        console.print("[yellow]No throughput data found (run experiment again with updated code)[/yellow]")
        return

    agent_events = pd.concat([agent_events.reset_index(drop=True), tp.reset_index(drop=True)], axis=1)

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"Throughput Analysis — {experiment}/{run_id}", fontsize=14, fontweight="bold")

    # 1. Tokens/sec over time
    ax = axes[0, 0]
    valid = agent_events.dropna(subset=["tokens_per_second"])
    if not valid.empty:
        for agent_name, group in valid.groupby("agent"):
            ax.plot(group["elapsed_s"], group["tokens_per_second"], "o-", label=agent_name, alpha=0.7, markersize=3)
        ax.set_xlabel("Elapsed Time (s)")
        ax.set_ylabel("Tokens/sec")
        ax.set_title("Generation Throughput Over Time")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # 2. Time to First Token
    ax = axes[0, 1]
    if "time_to_first_token_s" in agent_events.columns:
        valid_ttft = agent_events.dropna(subset=["time_to_first_token_s"])
        if not valid_ttft.empty:
            ax.hist(valid_ttft["time_to_first_token_s"], bins=25, edgecolor="black", alpha=0.7, color="coral")
            mean_ttft = valid_ttft["time_to_first_token_s"].mean()
            p95_ttft = valid_ttft["time_to_first_token_s"].quantile(0.95)
            ax.axvline(mean_ttft, color="red", linestyle="--", label=f"Mean: {mean_ttft:.2f}s")
            ax.axvline(p95_ttft, color="orange", linestyle="--", label=f"P95: {p95_ttft:.2f}s")
            ax.set_xlabel("Time to First Token (s)")
            ax.set_ylabel("Frequency")
            ax.set_title("Time to First Token Distribution")
            ax.legend()

    # 3. Wall-clock latency per call
    ax = axes[1, 0]
    if "wall_clock_s" in agent_events.columns:
        valid_wc = agent_events.dropna(subset=["wall_clock_s"])
        if not valid_wc.empty:
            for agent_name, group in valid_wc.groupby("agent"):
                ax.plot(group["elapsed_s"], group["wall_clock_s"], "o-", label=agent_name, alpha=0.7, markersize=3)
            ax.set_xlabel("Experiment Elapsed Time (s)")
            ax.set_ylabel("Call Latency (s)")
            ax.set_title("Per-Call Latency Over Time")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    # 4. Throughput boxplot by agent
    ax = axes[1, 1]
    valid = agent_events.dropna(subset=["tokens_per_second"])
    if not valid.empty:
        agents = sorted(valid["agent"].unique())
        data = [valid[valid["agent"] == a]["tokens_per_second"].values for a in agents]
        bp = ax.boxplot(data, labels=agents, patch_artist=True)
        for patch, color in zip(bp["boxes"], plt.cm.Set2(range(len(agents)))):
            patch.set_facecolor(color)
        ax.set_xlabel("Agent")
        ax.set_ylabel("Tokens/sec")
        ax.set_title("Throughput Distribution by Agent")
        ax.tick_params(axis="x", rotation=45)

    plt.tight_layout()
    outpath = OUTPUT_DIR / f"throughput_{experiment}_{run_id}.png"
    plt.savefig(outpath, dpi=150)
    plt.close()
    console.print(f"[green]📊 Throughput chart saved: {outpath}[/green]")


# ─── System / GPU Analysis ──────────────────────────────────────────────────

def analyze_system(sys_df: pd.DataFrame, experiment: str, run_id: str):
    """Analyze and plot system resource usage (GPU, CPU, RAM)."""
    if sys_df.empty:
        console.print("[yellow]No system monitor data available[/yellow]")
        return

    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle(f"System Resources — {experiment}/{run_id}", fontsize=14, fontweight="bold")

    elapsed = sys_df["elapsed_s"]

    # 1. CPU Utilization
    ax = axes[0, 0]
    ax.plot(elapsed, sys_df["cpu_util_pct"], color="steelblue", linewidth=1.5)
    ax.fill_between(elapsed, sys_df["cpu_util_pct"], alpha=0.2, color="steelblue")
    ax.set_ylabel("CPU %")
    ax.set_title("CPU Utilization")
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    # 2. RAM Usage
    ax = axes[0, 1]
    ax.plot(elapsed, sys_df["ram_used_gb"], color="green", linewidth=1.5, label="Used")
    ax.axhline(sys_df["ram_total_gb"].iloc[0], color="red", linestyle="--", alpha=0.5, label="Total")
    ax.fill_between(elapsed, sys_df["ram_used_gb"], alpha=0.2, color="green")
    ax.set_ylabel("RAM (GB)")
    ax.set_title("RAM Usage")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 3. GPU Utilization (from nested gpus column)
    ax = axes[1, 0]
    if "gpus" in sys_df.columns:
        gpu_utils = sys_df["gpus"].apply(lambda g: g[0]["gpu_util_pct"] if g and len(g) > 0 else 0)
        ax.plot(elapsed, gpu_utils, color="orange", linewidth=1.5)
        ax.fill_between(elapsed, gpu_utils, alpha=0.2, color="orange")
        ax.set_ylabel("GPU Util %")
        ax.set_title("GPU Utilization")
        ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    # 4. GPU VRAM
    ax = axes[1, 1]
    if "gpus" in sys_df.columns:
        vram_used = sys_df["gpus"].apply(lambda g: g[0]["memory_used_mb"] if g and len(g) > 0 else 0)
        vram_total = sys_df["gpus"].apply(lambda g: g[0]["memory_total_mb"] if g and len(g) > 0 else 0)
        ax.plot(elapsed, vram_used, color="red", linewidth=1.5, label="Used")
        if vram_total.max() > 0:
            ax.axhline(vram_total.iloc[0], color="darkred", linestyle="--", alpha=0.5, label=f"Total: {vram_total.iloc[0]:.0f} MB")
        ax.fill_between(elapsed, vram_used, alpha=0.2, color="red")
        ax.set_ylabel("VRAM (MB)")
        ax.set_title("GPU VRAM Usage")
        ax.legend()
    ax.grid(True, alpha=0.3)

    # 5. GPU Temperature
    ax = axes[2, 0]
    if "gpus" in sys_df.columns:
        temps = sys_df["gpus"].apply(lambda g: g[0]["temperature_c"] if g and len(g) > 0 else 0)
        ax.plot(elapsed, temps, color="crimson", linewidth=1.5)
        ax.fill_between(elapsed, temps, alpha=0.1, color="crimson")
        ax.set_ylabel("Temperature (°C)")
        ax.set_xlabel("Elapsed Time (s)")
        ax.set_title("GPU Temperature")
        ax.axhline(80, color="red", linestyle=":", alpha=0.5, label="Thermal Throttle Zone")
        ax.legend()
    ax.grid(True, alpha=0.3)

    # 6. Ollama Process RSS
    ax = axes[2, 1]
    ax.plot(elapsed, sys_df["ollama_rss_mb"], color="purple", linewidth=1.5)
    ax.fill_between(elapsed, sys_df["ollama_rss_mb"], alpha=0.2, color="purple")
    ax.set_ylabel("Ollama RSS (MB)")
    ax.set_xlabel("Elapsed Time (s)")
    ax.set_title("Ollama Process Memory")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    outpath = OUTPUT_DIR / f"system_{experiment}_{run_id}.png"
    plt.savefig(outpath, dpi=150)
    plt.close()
    console.print(f"[green]📊 System chart saved: {outpath}[/green]")

    # Print summary stats
    table = Table(title=f"System Resource Summary — {experiment}/{run_id}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Duration", f"{elapsed.max():.0f} s")
    table.add_row("CPU Avg", f"{sys_df['cpu_util_pct'].mean():.1f}%")
    table.add_row("CPU Max", f"{sys_df['cpu_util_pct'].max():.1f}%")
    table.add_row("RAM Avg", f"{sys_df['ram_used_gb'].mean():.1f} GB / {sys_df['ram_total_gb'].iloc[0]:.0f} GB")
    table.add_row("RAM Max", f"{sys_df['ram_used_gb'].max():.1f} GB")
    if "gpus" in sys_df.columns:
        gpu_utils = sys_df["gpus"].apply(lambda g: g[0]["gpu_util_pct"] if g and len(g) > 0 else 0)
        vram_used = sys_df["gpus"].apply(lambda g: g[0]["memory_used_mb"] if g and len(g) > 0 else 0)
        temps = sys_df["gpus"].apply(lambda g: g[0]["temperature_c"] if g and len(g) > 0 else 0)
        table.add_row("GPU Util Avg", f"{gpu_utils.mean():.1f}%")
        table.add_row("GPU Util Max", f"{gpu_utils.max():.1f}%")
        table.add_row("VRAM Avg", f"{vram_used.mean():.0f} MB")
        table.add_row("VRAM Max", f"{vram_used.max():.0f} MB")
        table.add_row("GPU Temp Avg", f"{temps.mean():.1f}°C")
        table.add_row("GPU Temp Max", f"{temps.max():.1f}°C")
    table.add_row("Ollama RSS Max", f"{sys_df['ollama_rss_mb'].max():.0f} MB")
    console.print(table)


# ─── Main ────────────────────────────────────────────────────────────────────

def analyze_run(experiment: str, run_id: str, system_only: bool = False):
    """Run full analysis for one experiment run."""
    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"[bold]Analyzing: {experiment} / {run_id}[/bold]")
    console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")

    # System analysis (always)
    sys_df = load_system_log(experiment, run_id)
    if not sys_df.empty:
        analyze_system(sys_df, experiment, run_id)

    if system_only:
        return

    # Experiment log analysis
    df = load_experiment_log(experiment, run_id)
    if df.empty:
        return

    analyze_token_usage(df, experiment, run_id)
    analyze_throughput(df, experiment, run_id)


def main():
    parser = argparse.ArgumentParser(description="NAIL Institute Analysis Dashboard")
    parser.add_argument("--experiment", "-e", type=str, help="Experiment name (e.g., exp1_memory_pollution)")
    parser.add_argument("--run", "-r", type=str, help="Specific run ID")
    parser.add_argument("--all", action="store_true", help="Analyze all experiments")
    parser.add_argument("--system-only", action="store_true", help="Only analyze system/GPU metrics")
    args = parser.parse_args()

    console.print("[bold]NAIL Institute — Analysis Dashboard[/bold]\n")

    if args.all:
        experiments = discover_experiments()
        if not experiments:
            console.print("[red]No experiment logs found![/red]")
            return
        for exp in experiments:
            runs = discover_runs(exp)
            for run_id in runs:
                analyze_run(exp, run_id, system_only=args.system_only)

    elif args.experiment:
        if args.run:
            analyze_run(args.experiment, args.run, system_only=args.system_only)
        else:
            runs = discover_runs(args.experiment)
            if not runs:
                console.print(f"[red]No runs found for {args.experiment}[/red]")
                return
            for run_id in runs:
                analyze_run(args.experiment, run_id, system_only=args.system_only)
    else:
        # Show available experiments
        experiments = discover_experiments()
        if experiments:
            table = Table(title="Available Experiments")
            table.add_column("Experiment", style="cyan")
            table.add_column("Runs", style="green")
            for exp in experiments:
                runs = discover_runs(exp)
                table.add_row(exp, ", ".join(runs))
            console.print(table)
        else:
            console.print("[yellow]No experiment logs found yet. Run an experiment first![/yellow]")

    console.print(f"\n[dim]Charts saved to: {OUTPUT_DIR}[/dim]")


if __name__ == "__main__":
    main()
