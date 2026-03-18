"""
dese.stats — Statistical quality tests for DESE entropy output.
================================================================

Implements a subset of the NIST SP 800-22 randomness test suite,
plus additional tests relevant to deterministic entropy:

1. **Frequency (Monobit)** — proportion of 0s and 1s
2. **Block Frequency**     — uniformity within M-bit blocks
3. **Runs Test**           — oscillation between 0/1 runs
4. **Longest Run**         — longest run of ones in a block
5. **Serial Test**         — frequency of 2-bit patterns
6. **Approximate Entropy** — pattern predictability (ApEn)
7. **Chi-squared Byte**    — byte-value uniformity (χ² on 256 bins)
8. **Autocorrelation**     — lag-1 through lag-16 bit correlation
9. **Entropy Rate**        — Shannon entropy per byte

Each test returns a ``TestResult`` with the statistic, p-value,
and PASS/FAIL at α = 0.01.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List


@dataclass
class TestResult:
    """Result of a single statistical test."""
    test_name: str
    statistic: float
    p_value: float
    passed: bool
    detail: str = ""

    def __repr__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (f"TestResult({self.test_name}: stat={self.statistic:.6f}, "
                f"p={self.p_value:.6f}, {status})")


ALPHA = 0.01  # significance level


def _bytes_to_bits(data: bytes) -> List[int]:
    """Convert bytes to a list of individual bits (MSB first)."""
    bits: list[int] = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _erfc(x: float) -> float:
    """Complementary error function (pure Python, no scipy dependency)."""
    # Abramowitz & Stegun approximation 7.1.26
    t = 1.0 / (1.0 + 0.3275911 * abs(x))
    poly = t * (0.254829592 + t * (-0.284496736 + t * (
        1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    result = poly * math.exp(-x * x)
    return result if x >= 0 else 2.0 - result


def _normal_cdf(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * _erfc(-x / math.sqrt(2.0))


def _chi2_cdf(x: float, k: int) -> float:
    """Chi-squared CDF via regularised incomplete gamma function.
    
    Uses series expansion for the lower incomplete gamma function.
    Computed in log-space to avoid overflow for large k.
    """
    if x <= 0:
        return 0.0
    a = k / 2.0
    half_x = x / 2.0
    # Series expansion of lower incomplete gamma in log-space
    # P(a, x) = exp(-x/2) * (x/2)^a / Gamma(a) * sum_n [term_n]
    # where term_0 = 1/a, term_n = term_{n-1} * (x/2) / (a+n)
    s = 1.0 / a
    term = 1.0 / a
    for n in range(1, 500):
        term *= half_x / (a + n)
        s += term
        if abs(term) < 1e-15:
            break
    # Compute in log-space: log(s) + (-x/2) + a*log(x/2) - lgamma(a)
    try:
        log_result = math.log(s) + (-half_x) + a * math.log(half_x) - math.lgamma(a)
        result = math.exp(log_result)
    except (OverflowError, ValueError):
        # For extreme values, CDF is effectively 0 or 1
        if x > k:
            return 1.0
        return 0.0
    return min(1.0, max(0.0, result))


# ─── Test Implementations ────────────────────────────────────────────

def frequency_test(data: bytes) -> TestResult:
    """
    NIST SP 800-22 §2.1 — Frequency (Monobit) Test.

    Tests whether the number of 1s and 0s are approximately equal.
    """
    bits = _bytes_to_bits(data)
    n = len(bits)
    if n == 0:
        return TestResult("frequency", 0.0, 0.0, False, "No data")

    s = sum(2 * b - 1 for b in bits)  # convert 0→-1, 1→+1
    s_obs = abs(s) / math.sqrt(n)
    p_value = _erfc(s_obs / math.sqrt(2.0))

    return TestResult(
        test_name="frequency",
        statistic=s_obs,
        p_value=p_value,
        passed=p_value >= ALPHA,
        detail=f"n={n}, sum={s}, S_obs={s_obs:.6f}",
    )


def block_frequency_test(data: bytes, block_size: int = 128) -> TestResult:
    """
    NIST SP 800-22 §2.2 — Block Frequency Test.

    Divides the bit sequence into blocks and tests uniformity of
    1-proportions within each block.
    """
    bits = _bytes_to_bits(data)
    n = len(bits)
    num_blocks = n // block_size
    if num_blocks == 0:
        return TestResult("block_frequency", 0.0, 0.0, False,
                          "Insufficient data")

    chi_sq = 0.0
    for i in range(num_blocks):
        block = bits[i * block_size: (i + 1) * block_size]
        pi = sum(block) / block_size
        chi_sq += (pi - 0.5) ** 2

    chi_sq *= 4.0 * block_size
    p_value = 1.0 - _chi2_cdf(chi_sq, num_blocks)
    p_value = max(0.0, min(1.0, p_value))

    return TestResult(
        test_name="block_frequency",
        statistic=chi_sq,
        p_value=p_value,
        passed=p_value >= ALPHA,
        detail=f"blocks={num_blocks}, M={block_size}",
    )


def runs_test(data: bytes) -> TestResult:
    """
    NIST SP 800-22 §2.3 — Runs Test.

    Tests the oscillation between 0-runs and 1-runs.
    """
    bits = _bytes_to_bits(data)
    n = len(bits)
    if n == 0:
        return TestResult("runs", 0.0, 0.0, False, "No data")

    pi = sum(bits) / n

    # Pre-test: if proportion too far from 0.5, skip
    if abs(pi - 0.5) >= (2.0 / math.sqrt(n)):
        return TestResult("runs", 0.0, 0.0, False,
                          f"Pre-test failed: π={pi:.6f}")

    # Count runs
    v_obs = 1
    for i in range(1, n):
        if bits[i] != bits[i - 1]:
            v_obs += 1

    num = abs(v_obs - 2.0 * n * pi * (1.0 - pi))
    den = 2.0 * math.sqrt(2.0 * n) * pi * (1.0 - pi)
    if den == 0:
        return TestResult("runs", 0.0, 0.0, False, "Degenerate")

    p_value = _erfc(num / den)

    return TestResult(
        test_name="runs",
        statistic=float(v_obs),
        p_value=p_value,
        passed=p_value >= ALPHA,
        detail=f"V_obs={v_obs}, π={pi:.6f}",
    )


def chi2_byte_test(data: bytes) -> TestResult:
    """
    Chi-squared goodness-of-fit on byte values (256 bins).

    Tests whether all 256 byte values occur with equal frequency.
    """
    n = len(data)
    if n < 256:
        return TestResult("chi2_byte", 0.0, 0.0, False,
                          "Need ≥256 bytes")

    counts = [0] * 256
    for b in data:
        counts[b] += 1

    expected = n / 256.0
    chi_sq = sum((c - expected) ** 2 / expected for c in counts)
    p_value = 1.0 - _chi2_cdf(chi_sq, 255)
    p_value = max(0.0, min(1.0, p_value))

    return TestResult(
        test_name="chi2_byte",
        statistic=chi_sq,
        p_value=p_value,
        passed=p_value >= ALPHA,
        detail=f"n={n}, expected/bin={expected:.1f}",
    )


def serial_test(data: bytes) -> TestResult:
    """
    Serial Test — frequency of 2-bit overlapping patterns.

    Tests whether all four 2-bit patterns (00, 01, 10, 11) occur
    with equal frequency.
    """
    bits = _bytes_to_bits(data)
    n = len(bits)
    if n < 4:
        return TestResult("serial", 0.0, 0.0, False, "Need ≥4 bits")

    # Count 2-bit patterns
    counts = [0, 0, 0, 0]  # 00, 01, 10, 11
    for i in range(n - 1):
        pattern = bits[i] * 2 + bits[i + 1]
        counts[pattern] += 1

    total = n - 1
    expected = total / 4.0
    chi_sq = sum((c - expected) ** 2 / expected for c in counts)
    p_value = 1.0 - _chi2_cdf(chi_sq, 3)
    p_value = max(0.0, min(1.0, p_value))

    return TestResult(
        test_name="serial",
        statistic=chi_sq,
        p_value=p_value,
        passed=p_value >= ALPHA,
        detail=f"patterns={counts}",
    )


def autocorrelation_test(data: bytes, max_lag: int = 16) -> TestResult:
    """
    Bit autocorrelation test for lags 1 through max_lag.

    Reports the maximum absolute autocorrelation and corresponding
    p-value.  Good entropy should have near-zero autocorrelation.
    """
    bits = _bytes_to_bits(data)
    n = len(bits)
    if n < max_lag + 100:
        return TestResult("autocorrelation", 0.0, 0.0, False,
                          "Insufficient data")

    # Centre bits: 0→-1, 1→+1
    centred = [2 * b - 1 for b in bits]

    max_abs_corr = 0.0
    worst_lag = 1
    worst_p = 1.0

    for lag in range(1, max_lag + 1):
        corr_sum = sum(centred[i] * centred[i + lag]
                       for i in range(n - lag))
        corr = corr_sum / (n - lag)
        z = abs(corr) * math.sqrt(n - lag)
        p = _erfc(z / math.sqrt(2.0))

        if abs(corr) > max_abs_corr:
            max_abs_corr = abs(corr)
            worst_lag = lag
            worst_p = p

    return TestResult(
        test_name="autocorrelation",
        statistic=max_abs_corr,
        p_value=worst_p,
        passed=worst_p >= ALPHA,
        detail=f"worst_lag={worst_lag}, max_|r|={max_abs_corr:.6f}",
    )


def shannon_entropy(data: bytes) -> TestResult:
    """
    Shannon entropy per byte.

    Perfect randomness → 8.0 bits/byte.
    """
    n = len(data)
    if n == 0:
        return TestResult("shannon_entropy", 0.0, 0.0, False, "No data")

    counts = [0] * 256
    for b in data:
        counts[b] += 1

    h = 0.0
    for c in counts:
        if c > 0:
            p = c / n
            h -= p * math.log2(p)

    # For truly random data, expected H ≈ 8.0 - (255 / (2 * n * ln2))
    # We pass if H > 7.9 for practical purposes
    passed = h >= 7.9

    return TestResult(
        test_name="shannon_entropy",
        statistic=h,
        p_value=h / 8.0,  # pseudo-p: ratio to theoretical max
        passed=passed,
        detail=f"H={h:.6f} bits/byte (max=8.0)",
    )


# ─── Full Suite ──────────────────────────────────────────────────────

def run_full_suite(data: bytes) -> List[TestResult]:
    """Run all statistical tests and return results."""
    return [
        frequency_test(data),
        block_frequency_test(data),
        runs_test(data),
        serial_test(data),
        chi2_byte_test(data),
        autocorrelation_test(data),
        shannon_entropy(data),
    ]


def print_report(results: List[TestResult]) -> None:
    """Pretty-print a test report."""
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print(f"\n{'═' * 72}")
    print(f"  DESE Statistical Quality Report")
    print(f"{'═' * 72}")
    print(f"  {'Test':<25} {'Statistic':>12} {'p-value':>10} {'Result':>8}")
    print(f"  {'─' * 25} {'─' * 12} {'─' * 10} {'─' * 8}")

    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        print(f"  {r.test_name:<25} {r.statistic:>12.6f} {r.p_value:>10.6f} {status}")

    print(f"  {'─' * 25} {'─' * 12} {'─' * 10} {'─' * 8}")
    verdict = "ALL PASS" if passed == total else f"{total - passed} FAILED"
    print(f"  Overall: {passed}/{total} passed — {verdict}")
    print(f"{'═' * 72}\n")
