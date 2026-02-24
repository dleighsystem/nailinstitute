"""
NAIL Institute — Statistical Analysis & Figure Generation
==========================================================

Generates publication-quality figures and statistical tests for the paper.

OUTPUT:
  - paper/figures/*.png  (matplotlib/seaborn figures)
  - paper/stats_report.md (statistical test results)

USAGE:
  conda activate nail_experiments
  python analyze_stats.py
"""

import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))

DATA_DIR = Path(__file__).resolve().parent / "data"
FIG_DIR = Path(__file__).resolve().parent.parent / "paper" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Publication style
plt.rcParams.update({
    'figure.figsize': (10, 6),
    'font.size': 12,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
    'legend.fontsize': 10,
    'figure.dpi': 150,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
})
sns.set_palette("colorblind")


def load_json(name):
    path = DATA_DIR / name
    if path.exists():
        with open(path) as f:
            return json.load(f)
    print(f"  ⚠️  Missing: {name}")
    return None


def bootstrap_ci(data, n_boot=10000, ci=0.95, func=np.mean):
    """Bootstrap confidence interval."""
    rng = np.random.default_rng(42)
    boot = [func(rng.choice(data, size=len(data), replace=True)) for _ in range(n_boot)]
    lo = np.percentile(boot, (1 - ci) / 2 * 100)
    hi = np.percentile(boot, (1 + ci) / 2 * 100)
    return func(data), lo, hi


# ═══════════════════════════════════════════════════════════════════════════
# Figure 1: Experiment 2 — Consensus Paralysis Comparison
# ═══════════════════════════════════════════════════════════════════════════

def fig_exp2_consensus():
    """Bar chart of Exp2 conditions: rounds, consensus rate, tokens."""
    d = load_json("exp2_results.json")
    if not d:
        return

    modes = ["control", "weighted_voting", "escalation", "compromise"]
    labels = ["Control", "Weighted\nVoting", "Escalation", "Compromise"]
    colors = ["#d62728", "#ff7f0e", "#2ca02c", "#1f77b4"]

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Panel A: Average Rounds
    rounds = [d[m]["avg_rounds"] for m in modes]
    bars = axes[0].bar(labels, rounds, color=colors, edgecolor="black", linewidth=0.5)
    axes[0].set_ylabel("Average Rounds")
    axes[0].set_title("A. Rounds to Resolution")
    axes[0].axhline(y=30, color="gray", linestyle="--", alpha=0.5, label="Max (30)")
    axes[0].legend()
    for bar, val in zip(bars, rounds):
        axes[0].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.3,
                     f'{val:.1f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Panel B: Consensus Rate
    cons = [d[m]["consensus_rate"] * 100 for m in modes]
    bars = axes[1].bar(labels, cons, color=colors, edgecolor="black", linewidth=0.5)
    axes[1].set_ylabel("Consensus Rate (%)")
    axes[1].set_title("B. Consensus Achievement")
    axes[1].set_ylim(0, 110)
    for bar, val in zip(bars, cons):
        axes[1].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                     f'{val:.0f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Panel C: Token Cost
    tokens = [d[m]["avg_tokens"] / 1000 for m in modes]
    bars = axes[2].bar(labels, tokens, color=colors, edgecolor="black", linewidth=0.5)
    axes[2].set_ylabel("Average Tokens (K)")
    axes[2].set_title("C. Compute Cost")
    for bar, val in zip(bars, tokens):
        axes[2].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 2,
                     f'{val:.0f}K', ha='center', va='bottom', fontsize=10, fontweight='bold')

    fig.suptitle("Experiment 2: Consensus Paralysis — Intervention Comparison", fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig1_exp2_consensus.png")
    plt.close()
    print("  ✅ Figure 1: Exp2 Consensus Paralysis")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 2: Experiment 4 — Prompt Inbreeding Convergence
# ═══════════════════════════════════════════════════════════════════════════

def fig_exp4_inbreeding():
    """Line chart of cosine similarity over generations."""
    d = load_json("exp4_results.json")
    if not d:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    for condition, color, marker in [("control", "#d62728", "o"), ("entropy", "#2ca02c", "s")]:
        if condition in d and "generations" in d[condition]:
            gens = d[condition]["generations"]
            sims = []
            for i in range(1, len(gens)):
                if "embedding" in gens[i] and "embedding" in gens[i-1]:
                    e1 = np.array(gens[i]["embedding"])
                    e2 = np.array(gens[i-1]["embedding"])
                    sim = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
                    sims.append(sim)
                elif "similarity_to_previous" in gens[i]:
                    sims.append(gens[i]["similarity_to_previous"])

            if sims:
                ax.plot(range(1, len(sims)+1), sims, color=color, marker=marker,
                        markersize=4, label=condition.title(), linewidth=2)

    # If we don't have per-gen data, use summary stats
    if not ax.lines:
        for condition in ["control", "entropy"]:
            if condition in d:
                sim = d[condition].get("avg_similarity", 0)
                first = d[condition].get("first_half_similarity", sim)
                second = d[condition].get("second_half_similarity", sim)
                color = "#d62728" if condition == "control" else "#2ca02c"
                ax.plot([1, 10, 20], [first, (first+second)/2, second],
                        color=color, marker="o", markersize=6, label=condition.title(), linewidth=2)

    ax.set_xlabel("Generation")
    ax.set_ylabel("Cosine Similarity (to previous generation)")
    ax.set_title("Experiment 4: Prompt Inbreeding — Convergence Over Generations")
    ax.legend()
    ax.set_ylim(0.8, 1.0)
    ax.grid(True, alpha=0.3)
    plt.savefig(FIG_DIR / "fig2_exp4_inbreeding.png")
    plt.close()
    print("  ✅ Figure 2: Exp4 Prompt Inbreeding")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 3: Experiment 5 — CYA Cascade Blame Patterns
# ═══════════════════════════════════════════════════════════════════════════

def fig_exp5_cya():
    """Grouped bar chart of blame patterns under individual vs shared accountability."""
    d = load_json("exp5_results.json")
    if not d:
        return

    fig, ax = plt.subplots(figsize=(10, 6))

    categories = ["blame_manager", "blame_coder", "blame_qa", "self_exoneration", "collaborative"]
    cat_labels = ["Blame\nManager", "Blame\nCoder", "Blame\nQA", "Self-\nExoneration", "Collaborative"]

    x = np.arange(len(categories))
    width = 0.35

    individual_vals = [d.get("individual", {}).get("aggregate_blame", d.get("individual", {})).get(c, 0) for c in categories]
    shared_vals = [d.get("shared", {}).get("aggregate_blame", d.get("shared", {})).get(c, 0) for c in categories]

    # Try alternate key structure
    if all(v == 0 for v in individual_vals):
        for mode_key, vals_list in [("individual", individual_vals), ("shared", shared_vals)]:
            mode_data = d.get(mode_key, {})
            if "trials" in mode_data:
                for trial in mode_data["trials"]:
                    blame = trial.get("aggregate_blame", trial.get("total_blame", {}))
                    for i, cat in enumerate(categories):
                        vals_list[i] += blame.get(cat, 0)

    bars1 = ax.bar(x - width/2, individual_vals, width, label='Individual Accountability',
                   color='#d62728', edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x + width/2, shared_vals, width, label='Shared Accountability',
                   color='#2ca02c', edgecolor='black', linewidth=0.5)

    ax.set_xlabel('Blame Category')
    ax.set_ylabel('Total Instances')
    ax.set_title('Experiment 5: CYA Cascade — Blame Attribution by Accountability Framing')
    ax.set_xticks(x)
    ax.set_xticklabels(cat_labels)
    ax.legend()
    ax.grid(True, alpha=0.3, axis='y')

    plt.savefig(FIG_DIR / "fig3_exp5_cya.png")
    plt.close()
    print("  ✅ Figure 3: Exp5 CYA Cascade")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 4: 7B vs 70B Comparison — Goodhart's Cartel (Exp7)
# ═══════════════════════════════════════════════════════════════════════════

def fig_7b_vs_70b():
    """Side-by-side comparison of 7B vs 70B key metrics."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # Hardcoded from paper (7B data overwritten in JSON by 70B run)
    data = {
        "7B": {"quality_decay": 0.05, "score_divergence": -2.27, "publish_rate": 100,
               "engagement_early": 478, "engagement_late": 301},
        "70B": {"quality_decay": -0.47, "score_divergence": 0.97, "publish_rate": 72,
                "engagement_early": 764, "engagement_late": 866},
    }

    colors = {"7B": "#1f77b4", "70B": "#d62728"}

    # Panel A: Quality Decay
    models = ["7B", "70B"]
    decay = [data[m]["quality_decay"] for m in models]
    bars = axes[0].bar(models, decay, color=[colors[m] for m in models], edgecolor="black", linewidth=0.5)
    axes[0].set_ylabel("Quality Decay (late - early)")
    axes[0].set_title("A. Quality Decay")
    axes[0].axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    for bar, val in zip(bars, decay):
        axes[0].text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.02,
                     f'{val:+.2f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    # Panel B: Score Divergence (Editor - Independent)
    diverg = [data[m]["score_divergence"] for m in models]
    bars = axes[1].bar(models, diverg, color=[colors[m] for m in models], edgecolor="black", linewidth=0.5)
    axes[1].set_ylabel("Score Divergence (Editor − Independent)")
    axes[1].set_title("B. Score Divergence")
    axes[1].axhline(y=0, color="gray", linestyle="--", alpha=0.5)
    for bar, val in zip(bars, diverg):
        y_pos = bar.get_height() + 0.05 if val >= 0 else bar.get_height() - 0.15
        axes[1].text(bar.get_x() + bar.get_width()/2., y_pos,
                     f'{val:+.2f}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    # Panel C: Engagement Pattern
    x = np.arange(2)
    width = 0.3
    axes[2].bar(x - width/2, [data["7B"]["engagement_early"], data["7B"]["engagement_late"]],
                width, label='7B', color=colors["7B"], edgecolor="black", linewidth=0.5)
    axes[2].bar(x + width/2, [data["70B"]["engagement_early"], data["70B"]["engagement_late"]],
                width, label='70B', color=colors["70B"], edgecolor="black", linewidth=0.5)
    axes[2].set_xticks(x)
    axes[2].set_xticklabels(["Early", "Late"])
    axes[2].set_ylabel("Editor Feedback (chars)")
    axes[2].set_title("C. Engagement Pattern")
    axes[2].legend()

    fig.suptitle("Experiment 7: Goodhart's Cartel — 7B vs 70B Scale Comparison", fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig4_7b_vs_70b.png")
    plt.close()
    print("  ✅ Figure 4: 7B vs 70B Comparison")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 5: CrewAI Dampening Effect
# ═══════════════════════════════════════════════════════════════════════════

def fig_crewai_dampening():
    """Heatmap of the CrewAI dampening effect across experiments."""
    dynamics = [
        "Blame\n(Individual)", "Self-\nExoneration", "Deceptive\nClaims",
        "Collaboration\n(Shared)", "Quality\nDiscrimination", "Task\nSuccess",
    ]
    prompt_vals = [10, 9, 4, 12, 4.3, 5]       # (range=5.7-9.3 → use 4.3 as proxy for range)
    crewai_vals = [3, 0, 0, 4, 0, 100]

    # Normalize to [0, 1] for heatmap
    max_vals = [max(p, c) if max(p, c) > 0 else 1 for p, c in zip(prompt_vals, crewai_vals)]
    prompt_norm = [p / m for p, m in zip(prompt_vals, max_vals)]
    crewai_norm = [c / m for c, m in zip(crewai_vals, max_vals)]

    fig, ax = plt.subplots(figsize=(12, 4))
    data = np.array([prompt_vals, crewai_vals])

    im = ax.imshow([[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]], cmap="YlOrRd", alpha=0)

    # Manual colored cells
    for j, (pv, cv) in enumerate(zip(prompt_vals, crewai_vals)):
        # Color based on "badness" — red for pathological dynamics, green for good ones
        if j < 3:  # Pathological (less is better)
            p_color = plt.cm.Reds(pv / max(max_vals[j], 1) * 0.7 + 0.1)
            c_color = plt.cm.Greens(0.3) if cv == 0 else plt.cm.Reds(cv / max(max_vals[j], 1) * 0.7 + 0.1)
        elif j < 5:  # Beneficial (more is better)
            p_color = plt.cm.Greens(pv / max(max_vals[j], 1) * 0.7 + 0.1)
            c_color = plt.cm.Reds(0.5) if cv <= 4 else plt.cm.Greens(cv / max(max_vals[j], 1) * 0.7 + 0.1)
        else:  # Task success (more is better)
            p_color = plt.cm.Reds(0.5)
            c_color = plt.cm.Greens(0.8)

        ax.add_patch(plt.Rectangle((j - 0.5, -0.5), 1, 1, facecolor=p_color, edgecolor='white', linewidth=2))
        ax.add_patch(plt.Rectangle((j - 0.5, 0.5), 1, 1, facecolor=c_color, edgecolor='white', linewidth=2))

        ax.text(j, 0, f"{pv}", ha='center', va='center', fontsize=12, fontweight='bold')
        ax.text(j, 1, f"{cv}", ha='center', va='center', fontsize=12, fontweight='bold')

    ax.set_xticks(range(len(dynamics)))
    ax.set_xticklabels(dynamics)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Prompt-\nOrchestrated", "CrewAI"])
    ax.set_xlim(-0.5, len(dynamics) - 0.5)
    ax.set_ylim(-0.5, 1.5)
    ax.set_title("CrewAI Dampening Effect — All Dynamics Flattened", fontsize=14, fontweight='bold')

    # Legend patches
    red_patch = mpatches.Patch(color=plt.cm.Reds(0.5), label='Pathological / Reduced')
    green_patch = mpatches.Patch(color=plt.cm.Greens(0.5), label='Beneficial / Present')
    ax.legend(handles=[red_patch, green_patch], loc='upper right')

    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig5_crewai_dampening.png")
    plt.close()
    print("  ✅ Figure 5: CrewAI Dampening Effect")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 6: Pydantic/LangGraph Vulnerability Severity Matrix
# ═══════════════════════════════════════════════════════════════════════════

def fig_pydantic_vulnerabilities():
    """Scatter plot of vulnerability severity vs visibility."""
    vulns = {
        "V1: Procrustean\nBed": {"severity": 8, "visibility": 8, "tokens": 50},
        "V2: Pydantic\nPurgatory": {"severity": 5, "visibility": 4, "tokens": 70},
        "V3: State\nAsphyxiation": {"severity": 9, "visibility": 2, "tokens": 60},
        "V4: Conditional\nDeadlock": {"severity": 8, "visibility": 7, "tokens": 80},
        "V5: Coercion\nMasking": {"severity": 9, "visibility": 1, "tokens": 83},
    }

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = ["#d62728", "#ff7f0e", "#e377c2", "#1f77b4", "#9467bd"]

    for i, (name, v) in enumerate(vulns.items()):
        ax.scatter(v["visibility"], v["severity"], s=v["tokens"] * 8,
                   color=colors[i], edgecolor="black", linewidth=1, alpha=0.8, zorder=5)
        offset_y = 0.3 if v["severity"] < 9 else -0.4
        ax.annotate(name, (v["visibility"], v["severity"]),
                    textcoords="offset points", xytext=(15, offset_y * 30),
                    fontsize=9, fontweight='bold',
                    arrowprops=dict(arrowstyle='->', color='gray', lw=0.8))

    ax.set_xlabel("Visibility (1=Silent, 10=Loud)")
    ax.set_ylabel("Severity (1=Low, 10=Critical)")
    ax.set_title("Pydantic/LangGraph Vulnerability Matrix\n(bubble size = % affected test cases)", fontsize=14, fontweight='bold')
    ax.set_xlim(0, 10)
    ax.set_ylim(3, 10)
    ax.grid(True, alpha=0.3)

    # Danger zone
    ax.axhspan(7, 10, xmin=0, xmax=0.3, alpha=0.1, color='red', label='Silent + Critical = Danger Zone')
    ax.legend(loc='lower right')

    plt.savefig(FIG_DIR / "fig6_pydantic_vulns.png")
    plt.close()
    print("  ✅ Figure 6: Pydantic Vulnerability Matrix")


# ═══════════════════════════════════════════════════════════════════════════
# Figure 7: Master Overview — All Experiments Risk Map
# ═══════════════════════════════════════════════════════════════════════════

def fig_master_overview():
    """Risk categorization overview across all experiments."""
    categories = [
        "Structural\nBehavioral", "Governance\nDeadlock", "Vigilance\nDecay",
        "Capability-\nGated", "Infrastructure", "Framework\nDampening",
    ]
    experiments = [
        ["Exp4\nInbreeding", "Exp5\nCYA"],
        ["Exp2\nConsensus"],
        ["Exp7\nEngagement", "Exp1\nMemory"],
        ["Exp7-70B\nGoodhart"],
        ["V1-V5\nPydantic"],
        ["CR-4,5,7\nCrewAI"],
    ]
    severity = [0.7, 0.9, 0.5, 0.95, 0.8, 0.6]
    colors_sev = [plt.cm.YlOrRd(s) for s in severity]

    fig, ax = plt.subplots(figsize=(14, 6))

    for i, (cat, exps, sev) in enumerate(zip(categories, experiments, severity)):
        ax.barh(i, sev, color=colors_sev[i], edgecolor="black", linewidth=0.5, height=0.6)
        exp_text = ", ".join(exps)
        ax.text(sev + 0.02, i, exp_text, va='center', fontsize=9, style='italic')

    ax.set_yticks(range(len(categories)))
    ax.set_yticklabels(categories, fontsize=11)
    ax.set_xlabel("Risk Severity")
    ax.set_title("NAIL Institute — AI Agent Certification Risk Categories", fontsize=14, fontweight='bold')
    ax.set_xlim(0, 1.3)
    ax.invert_yaxis()
    ax.grid(True, alpha=0.3, axis='x')

    plt.savefig(FIG_DIR / "fig7_master_overview.png")
    plt.close()
    print("  ✅ Figure 7: Master Risk Overview")


# ═══════════════════════════════════════════════════════════════════════════
# Statistical Tests
# ═══════════════════════════════════════════════════════════════════════════

def run_statistical_tests():
    """Run bootstrap CIs and Mann-Whitney U tests on key comparisons."""
    report = []
    report.append("# NAIL Institute — Statistical Analysis Report\n")
    report.append(f"Generated: {__import__('datetime').datetime.now().isoformat()}\n")

    # --- Exp2: Control vs Escalation ---
    d2 = load_json("exp2_results.json")
    if d2:
        report.append("\n## Experiment 2: Consensus Paralysis\n")
        
        ctrl_rounds = [t["rounds"] for t in d2["control"]["trials"]]
        esc_rounds = [t["rounds"] for t in d2["escalation"]["trials"]]

        U, p = stats.mannwhitneyu(ctrl_rounds, esc_rounds, alternative='greater')
        report.append(f"**Control vs Escalation (rounds):** Mann-Whitney U = {U}, p = {p:.6f}")
        report.append(f"  Control: mean={np.mean(ctrl_rounds):.1f}, median={np.median(ctrl_rounds):.1f}")
        report.append(f"  Escalation: mean={np.mean(esc_rounds):.1f}, median={np.median(esc_rounds):.1f}")

        mean_c, lo_c, hi_c = bootstrap_ci(np.array(ctrl_rounds))
        mean_e, lo_e, hi_e = bootstrap_ci(np.array(esc_rounds))
        report.append(f"  Control 95% CI: [{lo_c:.1f}, {hi_c:.1f}]")
        report.append(f"  Escalation 95% CI: [{lo_e:.1f}, {hi_e:.1f}]")

        # Token comparison
        ctrl_tokens = [t["total_tokens"] for t in d2["control"]["trials"]]
        esc_tokens = [t["total_tokens"] for t in d2["escalation"]["trials"]]
        U_t, p_t = stats.mannwhitneyu(ctrl_tokens, esc_tokens, alternative='greater')
        report.append(f"\n**Control vs Escalation (tokens):** Mann-Whitney U = {U_t}, p = {p_t:.6f}")
        report.append(f"  Token ratio: {np.mean(ctrl_tokens)/np.mean(esc_tokens):.1f}×")

        # All pairwise comparisons
        report.append("\n**All pairwise comparisons (rounds):**")
        modes = ["control", "weighted_voting", "escalation", "compromise"]
        for i, m1 in enumerate(modes):
            for m2 in modes[i+1:]:
                r1 = [t["rounds"] for t in d2[m1]["trials"]]
                r2 = [t["rounds"] for t in d2[m2]["trials"]]
                U, p = stats.mannwhitneyu(r1, r2, alternative='two-sided')
                sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
                report.append(f"  {m1} vs {m2}: U={U}, p={p:.4f} {sig}")

    # --- Exp5: Individual vs Shared ---
    d5 = load_json("exp5_results.json")
    if d5:
        report.append("\n## Experiment 5: CYA Cascade\n")
        # Extract per-trial blame counts
        for mode in ["individual", "shared"]:
            mode_data = d5.get(mode, {})
            if "trials" in mode_data:
                blame_per_trial = []
                for trial in mode_data["trials"]:
                    blame = trial.get("aggregate_blame", trial.get("total_blame", {}))
                    total = sum(blame.get(k, 0) for k in ["blame_manager", "blame_coder", "blame_qa"])
                    blame_per_trial.append(total)
                if blame_per_trial:
                    mean, lo, hi = bootstrap_ci(np.array(blame_per_trial))
                    report.append(f"  {mode}: blame mean={mean:.1f}, 95% CI=[{lo:.1f}, {hi:.1f}]")

    # --- Exp4: Similarity trend ---
    d4 = load_json("exp4_results.json")
    if d4:
        report.append("\n## Experiment 4: Prompt Inbreeding\n")
        for cond in ["control", "entropy"]:
            if cond in d4:
                sim = d4[cond].get("avg_similarity", "?")
                trend = d4[cond].get("similarity_trend", "?")
                report.append(f"  {cond}: avg_similarity={sim}, trend={trend}")

    # Write report
    report_path = FIG_DIR.parent / "stats_report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(report))
    print(f"  ✅ Statistical report: {report_path}")


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "=" * 70)
    print("  NAIL INSTITUTE — Statistical Analysis & Figure Generation")
    print("=" * 70 + "\n")

    print("Generating figures...")
    fig_exp2_consensus()
    fig_exp4_inbreeding()
    fig_exp5_cya()
    fig_7b_vs_70b()
    fig_crewai_dampening()
    fig_pydantic_vulnerabilities()
    fig_master_overview()

    print("\nRunning statistical tests...")
    run_statistical_tests()

    print(f"\n✅ All figures saved to {FIG_DIR}/")
    print(f"✅ Stats report saved to {FIG_DIR.parent}/stats_report.md")


if __name__ == "__main__":
    main()
