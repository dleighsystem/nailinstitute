#!/usr/bin/env python3
"""
Quantum Research Visualizations
================================

Generates publication-quality charts from quantum experiment results.

Outputs:
  quantum/visualizations/
    ├── convergence_plot.png       — QAOA fitness convergence (150 steps)
    ├── threshold_comparison.png   — Quantum vs GA threshold radar chart
    ├── qnn_confusion_matrix.png   — Hybrid QNN per-class accuracy
    ├── certification_badge.png    — Gold certification badge
    ├── risk_tier_scores.png       — Quantum risk score distribution
    └── phase_summary.png          — All 5 phases summary dashboard

Requirements: matplotlib, numpy (both in standard scientific Python)
"""

import json
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
except ImportError:
    print("❌ matplotlib and numpy required: pip install matplotlib numpy")
    sys.exit(1)

# ─────────────────────────────────────────
# Paths
# ─────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
RESULTS_DIR = SCRIPT_DIR.parent.parent / "quantum-research" / "experiments" / "results"
OUTPUT_DIR = SCRIPT_DIR.parent / "public-repo" / "quantum" / "visualizations"

# Allow override for CI or different locations
if not RESULTS_DIR.exists():
    # Try relative to workspace root
    RESULTS_DIR = Path("/home/dleighsystems/quantum-research/experiments/results")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Style
plt.rcParams.update({
    "figure.facecolor": "#0d1117",
    "axes.facecolor": "#161b22",
    "axes.edgecolor": "#30363d",
    "axes.labelcolor": "#c9d1d9",
    "text.color": "#c9d1d9",
    "xtick.color": "#8b949e",
    "ytick.color": "#8b949e",
    "grid.color": "#21262d",
    "font.family": "monospace",
    "font.size": 11,
})

QUANTUM_COLOR = "#58a6ff"
GA_COLOR = "#f78166"
ACCENT_COLOR = "#3fb950"
WARN_COLOR = "#d29922"
GOLD_COLOR = "#ffd700"


# ─────────────────────────────────────────
# 1. Convergence Plot
# ─────────────────────────────────────────

def plot_convergence():
    """QAOA fitness convergence over 150 optimization steps."""
    data_file = RESULTS_DIR / "quantum_optimization_20260325_001118.json"
    if not data_file.exists():
        print(f"  ⚠️  Skipping convergence plot — {data_file} not found")
        return

    with open(data_file) as f:
        data = json.load(f)

    history = data["convergence_history"]
    steps = [h["step"] for h in history]
    fitness = [h["best_fitness"] for h in history]
    ga_fitness = data["ga_baseline"]["fitness"]

    fig, ax = plt.subplots(figsize=(12, 6))

    # Main convergence line
    ax.plot(steps, fitness, color=QUANTUM_COLOR, linewidth=2, label="Quantum Optimizer")
    ax.axhline(y=ga_fitness, color=GA_COLOR, linewidth=2, linestyle="--",
               label=f"GA Baseline ({ga_fitness:.4f})")

    # Breakthrough phases
    ax.axvspan(77, 103, alpha=0.15, color=ACCENT_COLOR, label="Breakthrough 1")
    ax.axvspan(104, 150, alpha=0.10, color=GOLD_COLOR, label="Breakthrough 2")

    # Final value annotation
    final = fitness[-1]
    ax.annotate(f"Final: {final:.4f}\n(+{final - ga_fitness:.4f} over GA)",
                xy=(145, final), xytext=(110, final + 0.015),
                arrowprops=dict(arrowstyle="->", color=QUANTUM_COLOR),
                fontsize=10, color=QUANTUM_COLOR,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#161b22",
                          edgecolor=QUANTUM_COLOR, alpha=0.9))

    ax.set_xlabel("Optimization Step")
    ax.set_ylabel("Defence Fitness")
    ax.set_title("QAOA Threshold Optimization — Convergence",
                 fontsize=14, fontweight="bold")
    ax.legend(loc="lower right", framealpha=0.9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, 150)
    ax.set_ylim(0.895, 0.965)

    out = OUTPUT_DIR / "convergence_plot.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# 2. Threshold Comparison (Bar Chart)
# ─────────────────────────────────────────

def plot_threshold_comparison():
    """Side-by-side comparison of quantum vs GA thresholds."""
    data_file = RESULTS_DIR / "quantum_optimization_20260325_001118.json"
    if not data_file.exists():
        print(f"  ⚠️  Skipping threshold comparison — {data_file} not found")
        return

    with open(data_file) as f:
        data = json.load(f)

    q_thresh = data["quantum_result"]["thresholds"]
    ga_thresh = data["ga_baseline"]["thresholds"]

    # Normalize all to [0, 1] for visual comparison
    ranges = {
        "trust_threshold": (0.1, 0.9),
        "min_trust_floor": (0.1, 0.9),
        "scan_probability": (0.3, 1.0),
        "compound_threshold": (1.0, 5.0),
        "spike_threshold": (0.1, 0.8),
        "burn_rate_accel": (0.5, 3.0),
        "drift_threshold": (0.1, 0.8),
        "manipulation_threshold": (1.0, 6.0),
        "memory_decay_rate": (0.01, 0.50),
        "alert_cooldown": (1.0, 10.0),
        "sentinel_sensitivity": (0.1, 2.0),
        "token_budget_margin": (0.05, 0.50),
    }

    labels = list(ranges.keys())
    short_labels = [l.replace("_threshold", "").replace("_", "\n") for l in labels]

    q_norm = [(q_thresh[k] - ranges[k][0]) / (ranges[k][1] - ranges[k][0]) for k in labels]
    ga_norm = [(ga_thresh[k] - ranges[k][0]) / (ranges[k][1] - ranges[k][0]) for k in labels]

    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(14, 6))
    bars1 = ax.bar(x - width/2, q_norm, width, label="Quantum", color=QUANTUM_COLOR, alpha=0.85)
    bars2 = ax.bar(x + width/2, ga_norm, width, label="GA (g1_8241)", color=GA_COLOR, alpha=0.85)

    ax.set_xlabel("Defence Parameter")
    ax.set_ylabel("Normalized Value (within valid range)")
    ax.set_title("Quantum vs GA — Defence Threshold Comparison",
                 fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=8)
    ax.legend()
    ax.grid(True, alpha=0.2, axis="y")
    ax.set_ylim(0, 1.1)

    out = OUTPUT_DIR / "threshold_comparison.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# 3. QNN Confusion Matrix / Per-Class Accuracy
# ─────────────────────────────────────────

def plot_qnn_accuracy():
    """Per-class accuracy comparison: QNN vs Classical NN."""
    classes = ["Normal", "Goal\nDrift", "Memory\nCorruption", "EDoS\nAttack",
               "Prompt\nInjection", "Sleeper\nAgent"]
    qnn_acc = [1.0, 0.35, 1.0, 1.0, 0.80, 0.90]
    classical_acc = [0.95, 0.95, 1.0, 1.0, 0.95, 0.90]

    x = np.arange(len(classes))
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    bars1 = ax.bar(x - width/2, qnn_acc, width, label="Hybrid QNN (8 qubits)",
                   color=QUANTUM_COLOR, alpha=0.85)
    bars2 = ax.bar(x + width/2, classical_acc, width, label="Classical NN",
                   color=GA_COLOR, alpha=0.85)

    # Highlight quantum wins
    for i, (q, c) in enumerate(zip(qnn_acc, classical_acc)):
        if q > c:
            ax.annotate("★", xy=(x[i] - width/2, q + 0.02),
                        fontsize=14, color=GOLD_COLOR, ha="center")

    ax.set_xlabel("Pathology Class")
    ax.set_ylabel("Accuracy")
    ax.set_title("Hybrid QNN vs Classical NN — Per-Class Accuracy",
                 fontsize=14, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(classes, fontsize=9)
    ax.legend()
    ax.grid(True, alpha=0.2, axis="y")
    ax.set_ylim(0, 1.15)
    ax.axhline(y=1.0, color="#30363d", linewidth=0.5, linestyle=":")

    out = OUTPUT_DIR / "qnn_confusion_matrix.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# 4. Certification Badge
# ─────────────────────────────────────────

def plot_certification_badge():
    """Gold certification badge visualization."""
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # Outer ring
    outer = plt.Circle((0, 0), 1.3, fill=False, edgecolor=GOLD_COLOR,
                        linewidth=4)
    ax.add_patch(outer)

    # Inner ring
    inner = plt.Circle((0, 0), 1.1, fill=True, facecolor="#1a1500",
                        edgecolor=GOLD_COLOR, linewidth=2)
    ax.add_patch(inner)

    # Shield shape
    shield_x = [0, 0.6, 0.6, 0, -0.6, -0.6]
    shield_y = [-0.8, -0.2, 0.4, 0.7, 0.4, -0.2]
    ax.fill(shield_x, shield_y, color=GOLD_COLOR, alpha=0.3)
    ax.plot(shield_x + [shield_x[0]], shield_y + [shield_y[0]],
            color=GOLD_COLOR, linewidth=2)

    # Text
    ax.text(0, 0.25, "GOLD", fontsize=28, fontweight="bold",
            color=GOLD_COLOR, ha="center", va="center",
            fontfamily="monospace")
    ax.text(0, -0.15, "CERTIFIED", fontsize=14,
            color=GOLD_COLOR, ha="center", va="center",
            fontfamily="monospace")
    ax.text(0, -0.50, "99% CI: 97.4%–100%", fontsize=9,
            color="#c9d1d9", ha="center", va="center",
            fontfamily="monospace")

    # Top label
    ax.text(0, 1.05, "⚛️ QUANTUM", fontsize=10,
            color="#c9d1d9", ha="center", va="center",
            fontfamily="monospace")

    # Bottom label
    ax.text(0, -1.05, "NAIL INSTITUTE", fontsize=9,
            color="#8b949e", ha="center", va="center",
            fontfamily="monospace")

    fig.patch.set_facecolor("#0d1117")

    out = OUTPUT_DIR / "certification_badge.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# 5. Risk Tier Scores
# ─────────────────────────────────────────

def plot_risk_scores():
    """Quantum risk score distribution by tier."""
    tiers = ["Low", "Medium", "High", "Critical"]
    means = [0.312, 0.395, 0.500, 0.527]
    stds = [0.013, 0.027, 0.022, 0.013]
    colors = [ACCENT_COLOR, QUANTUM_COLOR, WARN_COLOR, GA_COLOR]

    fig, ax = plt.subplots(figsize=(10, 6))

    bars = ax.bar(tiers, means, yerr=stds, capsize=8, color=colors, alpha=0.85,
                  edgecolor="#30363d", linewidth=1)

    for bar, mean, std in zip(bars, means, stds):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + std + 0.01,
                f"{mean:.3f} ± {std:.3f}", ha="center", fontsize=10,
                color="#c9d1d9")

    ax.set_xlabel("Risk Tier")
    ax.set_ylabel("Quantum Risk Score")
    ax.set_title("Quantum VQC Risk Scoring — Score Distribution by Tier",
                 fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="y")
    ax.set_ylim(0, 0.65)

    out = OUTPUT_DIR / "risk_tier_scores.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# 6. Phase Summary Dashboard
# ─────────────────────────────────────────

def plot_phase_summary():
    """All 5 phases summary as a horizontal bar chart."""
    phases = [
        "Phase 1: QAOA\nThreshold Optimizer",
        "Phase 2a: Hybrid\nQNN Classifier",
        "Phase 2b: Quantum\nKernel SVM",
        "Phase 3: Robustness\nCertification",
        "Phase 4: QAOA\nCoordinator",
        "Phase 5: Quantum\nRisk Scoring",
    ]
    quantum_scores = [0.9383, 0.842, 0.542, 1.0, 1.0, 0.85]
    classical_scores = [0.9071, 0.967, 0.967, 0.735, 1.0, 1.0]
    advantage = ["✅ Quantum", "Mixed", "❌ Classical", "✅ Quantum",
                 "= Tied", "❌ Classical"]

    y = np.arange(len(phases))
    height = 0.35

    fig, ax = plt.subplots(figsize=(12, 7))
    bars1 = ax.barh(y - height/2, quantum_scores, height, label="Quantum",
                     color=QUANTUM_COLOR, alpha=0.85)
    bars2 = ax.barh(y + height/2, classical_scores, height, label="Classical",
                     color=GA_COLOR, alpha=0.85)

    for i, adv in enumerate(advantage):
        color = ACCENT_COLOR if "Quantum" in adv else (
            GA_COLOR if "Classical" in adv else "#8b949e")
        ax.text(max(quantum_scores[i], classical_scores[i]) + 0.02, y[i],
                adv, va="center", fontsize=9, color=color)

    ax.set_xlabel("Score / Accuracy")
    ax.set_yticks(y)
    ax.set_yticklabels(phases, fontsize=9)
    ax.set_title("Quantum Research Programme — All Phases Summary",
                 fontsize=14, fontweight="bold")
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.2, axis="x")
    ax.set_xlim(0, 1.2)

    out = OUTPUT_DIR / "phase_summary.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out.name}")


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def main():
    print("=" * 60)
    print("  ⚛️  NAIL Quantum Research — Visualization Generator")
    print("=" * 60)
    print(f"  Results: {RESULTS_DIR}")
    print(f"  Output:  {OUTPUT_DIR}")
    print()

    plot_convergence()
    plot_threshold_comparison()
    plot_qnn_accuracy()
    plot_certification_badge()
    plot_risk_scores()
    plot_phase_summary()

    print()
    print(f"  📊 All visualizations saved to {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
