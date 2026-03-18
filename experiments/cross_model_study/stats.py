"""
NAIL Institute — Statistical Analysis Module
================================================
Publication-grade statistical functions for cross-model validation.
"""

import math
import random
from typing import Optional


def mean(data: list[float]) -> float:
    """Arithmetic mean."""
    return sum(data) / len(data) if data else 0.0


def std_dev(data: list[float]) -> float:
    """Sample standard deviation."""
    if len(data) < 2:
        return 0.0
    m = mean(data)
    return math.sqrt(sum((x - m) ** 2 for x in data) / (len(data) - 1))


def std_error(data: list[float]) -> float:
    """Standard error of the mean."""
    if len(data) < 2:
        return 0.0
    return std_dev(data) / math.sqrt(len(data))


def confidence_interval(
    data: list[float],
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """
    Normal-approximation confidence interval.

    Returns: (mean, lower_bound, upper_bound)
    """
    n = len(data)
    if n < 2:
        m = mean(data)
        return (m, m, m)

    m = mean(data)
    se = std_error(data)

    # Z-scores for common confidence levels
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence, 1.96)

    margin = z * se
    return (round(m, 4), round(m - margin, 4), round(m + margin, 4))


def proportion_ci(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """
    Wilson score confidence interval for proportions.
    More accurate than normal approximation for rates near 0 or 1.

    Returns: (proportion, lower_bound, upper_bound)
    """
    if trials == 0:
        return (0.0, 0.0, 0.0)

    p = successes / trials
    z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
    z = z_scores.get(confidence, 1.96)

    denominator = 1 + z ** 2 / trials
    centre = (p + z ** 2 / (2 * trials)) / denominator
    spread = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * trials)) / trials) / denominator

    return (round(p, 4), round(max(0, centre - spread), 4), round(min(1, centre + spread), 4))


def bootstrap_ci(
    data: list[float],
    n_bootstrap: int = 2000,
    confidence: float = 0.95,
    statistic=None,
) -> tuple[float, float, float]:
    """
    Bootstrap confidence interval.

    Args:
        data: Raw data values
        n_bootstrap: Number of bootstrap samples
        confidence: Confidence level
        statistic: Function to compute (default: mean)

    Returns: (observed_statistic, lower_bound, upper_bound)
    """
    if not data:
        return (0.0, 0.0, 0.0)

    stat_fn = statistic or mean
    observed = stat_fn(data)

    boot_stats = []
    for _ in range(n_bootstrap):
        sample = random.choices(data, k=len(data))
        boot_stats.append(stat_fn(sample))

    boot_stats.sort()
    alpha = 1 - confidence
    lower_idx = int(alpha / 2 * n_bootstrap)
    upper_idx = int((1 - alpha / 2) * n_bootstrap) - 1

    return (
        round(observed, 4),
        round(boot_stats[lower_idx], 4),
        round(boot_stats[upper_idx], 4),
    )


def cohens_d(group1: list[float], group2: list[float]) -> float:
    """
    Cohen's d effect size between two groups.

    Returns: Effect size (small=0.2, medium=0.5, large=0.8)
    """
    n1, n2 = len(group1), len(group2)
    if n1 < 2 or n2 < 2:
        return 0.0

    m1, m2 = mean(group1), mean(group2)
    s1, s2 = std_dev(group1), std_dev(group2)

    # Pooled standard deviation
    pooled_s = math.sqrt(((n1 - 1) * s1 ** 2 + (n2 - 1) * s2 ** 2) / (n1 + n2 - 2))

    if pooled_s == 0:
        return 0.0

    return round((m1 - m2) / pooled_s, 4)


def chi_squared_independence(
    observed: list[list[int]],
) -> tuple[float, float, int]:
    """
    Chi-squared test of independence for a 2D contingency table.

    Args:
        observed: 2D list of observed frequencies (rows=models, cols=outcomes)

    Returns: (chi2_statistic, p_value_approx, degrees_of_freedom)

    Note: Uses chi-squared approximation. For small expected counts,
    consider Fisher's exact test.
    """
    rows = len(observed)
    cols = len(observed[0]) if observed else 0

    if rows < 2 or cols < 2:
        return (0.0, 1.0, 0)

    # Row and column totals
    row_totals = [sum(row) for row in observed]
    col_totals = [sum(observed[r][c] for r in range(rows)) for c in range(cols)]
    total = sum(row_totals)

    if total == 0:
        return (0.0, 1.0, 0)

    # Expected frequencies
    chi2 = 0.0
    for r in range(rows):
        for c in range(cols):
            expected = row_totals[r] * col_totals[c] / total
            if expected > 0:
                chi2 += (observed[r][c] - expected) ** 2 / expected

    df = (rows - 1) * (cols - 1)

    # Approximate p-value using chi-squared CDF
    # Using Wilson-Hilferty approximation for chi-squared
    if df > 0:
        z = (chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))
        z /= math.sqrt(2 / (9 * df)) if df > 0 else 1
        # Approximate standard normal CDF
        p_value = 0.5 * math.erfc(z / math.sqrt(2))
    else:
        p_value = 1.0

    return (round(chi2, 4), round(max(0, p_value), 6), df)


def odds_ratio(
    a: int, b: int, c: int, d: int,
) -> tuple[float, float, float]:
    """
    Odds ratio with 95% CI for a 2×2 table.

    | | Exploited | Not Exploited |
    |---|---|---|
    | Model A | a | b |
    | Model B | c | d |

    Returns: (odds_ratio, ci_lower, ci_upper)
    """
    if b == 0 or c == 0 or d == 0 or a == 0:
        # Haldane correction for zeros
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5

    or_val = (a * d) / (b * c)
    log_or = math.log(or_val)
    se_log_or = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)

    ci_lower = math.exp(log_or - 1.96 * se_log_or)
    ci_upper = math.exp(log_or + 1.96 * se_log_or)

    return (round(or_val, 4), round(ci_lower, 4), round(ci_upper, 4))


def format_pct_ci(rate: float, ci_low: float, ci_high: float) -> str:
    """Format a percentage with confidence interval: 67.0% [54.2, 78.1]"""
    return f"{rate*100:.1f}% [{ci_low*100:.1f}, {ci_high*100:.1f}]"


def format_results_table(
    model_results: dict[str, dict],
    metric_name: str,
) -> str:
    """
    Generate a publication-ready markdown table comparing a metric across models.

    Args:
        model_results: {model_label: {"rate": float, "ci_low": float, "ci_high": float, "n": int}}
        metric_name: Name of the metric being compared

    Returns: Markdown table string
    """
    lines = [
        f"| Model | N | {metric_name} | 95% CI |",
        "|---|---|---|---|",
    ]
    for label, data in model_results.items():
        rate = data.get("rate", 0)
        ci_low = data.get("ci_low", 0)
        ci_high = data.get("ci_high", 0)
        n = data.get("n", 0)
        lines.append(f"| {label} | {n} | {rate*100:.1f}% | [{ci_low*100:.1f}, {ci_high*100:.1f}] |")

    return "\n".join(lines)


def significance_stars(p_value: float) -> str:
    """Return significance stars for a p-value."""
    if p_value < 0.001:
        return "***"
    elif p_value < 0.01:
        return "**"
    elif p_value < 0.05:
        return "*"
    elif p_value < 0.1:
        return "†"
    return "ns"
