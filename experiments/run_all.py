#!/usr/bin/env python3
"""
NAIL Institute — Master Experiment Runner
===========================================
Runs all 8 experiments sequentially or individually.

Usage:
  conda activate nail_experiments
  cd /home/dleighsystems/Desktop/NAIL\ institute/experiments

  # Run all experiments:
  python run_all.py

  # Run individual experiments:
  python run_all.py --exp 1     # Memory Pollution
  python run_all.py --exp 2     # Consensus Paralysis
  python run_all.py --exp 3     # Token Embezzlement
  python run_all.py --exp 4     # Prompt Inbreeding
  python run_all.py --exp 5     # CYA Cascade
  python run_all.py --exp 6     # Language Drift
  python run_all.py --exp 7     # Goodhart's Cartel
  python run_all.py --exp 8     # Learned Helplessness

  # Quick smoke test (small scale):
  python run_all.py --smoke-test
"""

import argparse
import sys
import time
from pathlib import Path
from datetime import datetime

# Ensure we can import shared modules
sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.config import PRIMARY_MODEL, FAST_MODEL, CODE_MODEL, OLLAMA_BASE_URL
from shared.ollama_llm import test_ollama_connection
from rich.console import Console
from rich.panel import Panel

console = Console()


def print_banner():
    banner = """
    ███╗   ██╗ █████╗ ██╗██╗         ██╗███╗   ██╗███████╗████████╗██╗████████╗██╗   ██╗████████╗███████╗
    ████╗  ██║██╔══██╗██║██║         ██║████╗  ██║██╔════╝╚══██╔══╝██║╚══██╔══╝██║   ██║╚══██╔══╝██╔════╝
    ██╔██╗ ██║███████║██║██║         ██║██╔██╗ ██║███████╗   ██║   ██║   ██║   ██║   ██║   ██║   █████╗  
    ██║╚██╗██║██╔══██║██║██║         ██║██║╚██╗██║╚════██║   ██║   ██║   ██║   ██║   ██║   ██║   ██╔══╝  
    ██║ ╚████║██║  ██║██║███████╗    ██║██║ ╚████║███████║   ██║   ██║   ██║   ╚██████╔╝   ██║   ███████╗
    ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝╚══════╝    ╚═╝╚═╝  ╚═══╝╚══════╝   ╚═╝   ╚═╝   ╚═╝    ╚═════╝    ╚═╝   ╚══════╝

    Agentic Framework Pathology Research — Experimental Suite
    """
    console.print(Panel(banner, style="bold cyan"))


def check_prerequisites():
    """Verify Ollama is running and models are available."""
    console.print("\n[bold yellow]🔍 Checking Prerequisites...[/bold yellow]\n")

    all_ok = True
    for model in [FAST_MODEL, CODE_MODEL]:
        if not test_ollama_connection(model):
            console.print(f"[red]❌ Model {model} not available![/red]")
            all_ok = False

    if not all_ok:
        console.print("\n[red]Some models are unavailable. Please check Ollama is running:[/red]")
        console.print("  ollama serve")
        console.print(f"  ollama list  # should show {FAST_MODEL}, {CODE_MODEL}")
        return False

    console.print("[green]✅ All prerequisites met![/green]\n")
    return True


def run_experiment_1():
    """Run Experiment 1: Memory Pollution."""
    from exp1_memory_pollution.run import main
    main()


def run_experiment_2():
    """Run Experiment 2: Consensus Paralysis."""
    from exp2_consensus_paralysis.run import run_experiment
    run_experiment()


def run_experiment_3():
    """Run Experiment 3: Token Embezzlement."""
    from exp3_token_embezzlement.run import run_experiment
    run_experiment()


def run_experiment_4():
    """Run Experiment 4: Prompt Inbreeding."""
    from exp4_prompt_inbreeding.run import run_experiment
    run_experiment()


def run_experiment_5():
    """Run Experiment 5: CYA Cascade."""
    from exp5_cya_cascade.run import run_experiment
    run_experiment()


def run_experiment_6():
    """Run Experiment 6: Language Drift."""
    from exp6_language_drift.run import run_experiment
    run_experiment()


def run_experiment_7():
    """Run Experiment 7: Goodhart's Cartel."""
    from exp7_goodharts_cartel.run import run_experiment
    run_experiment()


def run_experiment_8():
    """Run Experiment 8: Learned Helplessness."""
    from exp8_learned_helplessness.run import run_experiment
    run_experiment()


EXPERIMENTS = {
    1: ("Tragedy of the Commons (Memory Pollution)", run_experiment_1),
    2: ("Algorithmic Filibustering (Consensus Paralysis)", run_experiment_2),
    3: ("Token Embezzlement (Goal Displacement)", run_experiment_3),
    4: ("Prompt Inbreeding (Lineage Degradation)", run_experiment_4),
    5: ("CYA Cascade (Bureaucratic Blame-Shifting)", run_experiment_5),
    6: ("Language Drift (Agentic Creole)", run_experiment_6),
    7: ("Goodhart's Cartel (Metric Collusion)", run_experiment_7),
    8: ("Learned Helplessness (Tool Fragility)", run_experiment_8),
}


def main():
    parser = argparse.ArgumentParser(description="NAIL Institute Experiment Runner")
    parser.add_argument("--exp", type=int, choices=[1, 2, 3, 4, 5, 6, 7, 8],
                        help="Run a specific experiment (1-8). Default: run all.")
    parser.add_argument("--smoke-test", action="store_true",
                        help="Run a quick smoke test to verify setup.")
    parser.add_argument("--skip-prereq", action="store_true",
                        help="Skip prerequisite checks.")
    args = parser.parse_args()

    print_banner()

    # Smoke test: just verify everything works
    if args.smoke_test:
        console.print("[bold yellow]🧪 SMOKE TEST MODE[/bold yellow]")
        if not check_prerequisites():
            sys.exit(1)
        console.print("[green]✅ Smoke test passed! All systems operational.[/green]")
        sys.exit(0)

    # Check prerequisites
    if not args.skip_prereq:
        if not check_prerequisites():
            sys.exit(1)

    start_time = time.time()
    console.print(f"[bold]Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/bold]\n")

    if args.exp:
        name, func = EXPERIMENTS[args.exp]
        console.print(f"\n[bold cyan]▶ Running Experiment {args.exp}: {name}[/bold cyan]\n")
        func()
    else:
        for exp_num, (name, func) in EXPERIMENTS.items():
            console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
            console.print(f"[bold cyan]▶ Experiment {exp_num}: {name}[/bold cyan]")
            console.print(f"[bold cyan]{'='*70}[/bold cyan]\n")
            try:
                func()
            except Exception as e:
                console.print(f"[red]❌ Experiment {exp_num} failed: {e}[/red]")
                import traceback
                traceback.print_exc()

    elapsed = time.time() - start_time
    console.print(f"\n[bold green]✅ All done! Total time: {elapsed/60:.1f} minutes[/bold green]")
    console.print(f"[dim]Logs: experiments/logs/  |  Data: experiments/data/[/dim]")


if __name__ == "__main__":
    main()
