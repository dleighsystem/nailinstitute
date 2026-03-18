"""
dese.cli — Command-line interface for DESE.
============================================

Usage::

    # Generate entropy from default Lorenz manifest
    python -m dese generate --system lorenz --steps 100000 -o entropy.bin

    # Generate from a seed phrase
    python -m dese generate --seed "NAIL Institute 2026" --steps 50000 -o out.bin

    # Generate from a manifest file
    python -m dese generate --manifest spec.json -o entropy.bin

    # Verify a manifest against reference output
    python -m dese verify --manifest spec.json --reference entropy.bin

    # Run statistical tests on entropy output
    python -m dese test --input entropy.bin

    # Show manifest info
    python -m dese info --manifest spec.json

    # Benchmark throughput
    python -m dese benchmark --system lorenz --steps 100000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from dese.manifest import Manifest
from dese.engine import DESEEngine
from dese.stats import run_full_suite, print_report


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate entropy from a manifest or inline parameters."""
    engine = DESEEngine()

    if args.manifest:
        manifest = Manifest.load(args.manifest)
    elif args.seed:
        manifest = Manifest.from_seed(
            phrase=args.seed,
            system=args.system,
            extract_steps=args.steps,
            warmup=args.warmup,
            comment=f"CLI: seed='{args.seed}'",
        )
    else:
        manifest = Manifest(
            system=args.system,
            initial_state=[1.0] * _system_dim(args.system),
            dt=_default_dt(args.system),
            warmup_steps=args.warmup,
            extract_steps=args.steps,
            extractor=args.extractor,
            comment="CLI-generated",
        )

    print(f"Manifest identity: {manifest.identity}")
    print(f"System: {manifest.system}, steps: {manifest.extract_steps}")
    print(f"Extractor: {manifest.extractor}")

    entropy, record = engine.generate(manifest)

    # Save entropy
    if args.output:
        with open(args.output, "wb") as f:
            f.write(entropy)
        print(f"Entropy written: {args.output} ({len(entropy):,} bytes)")
    else:
        sys.stdout.buffer.write(entropy)

    # Save manifest alongside output
    if args.output and args.save_manifest:
        mpath = args.output + ".manifest.json"
        manifest.save(mpath)
        print(f"Manifest saved: {mpath}")

    # Print record
    print(f"\n  Output SHA-256: {record.output_sha256}")
    print(f"  Entropy rate:   {record.entropy_rate_bps:.1f} bits/step")
    print(f"  Throughput:     {record.throughput_kbps:.1f} KB/s")
    print(f"  Elapsed:        {record.elapsed_seconds:.3f}s")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify a manifest against reference entropy."""
    engine = DESEEngine()
    manifest = Manifest.load(args.manifest)

    with open(args.reference, "rb") as f:
        reference = f.read()

    print(f"Manifest identity: {manifest.identity}")
    print(f"Reference file:    {args.reference} ({len(reference):,} bytes)")
    print(f"Reference SHA-256: {hashlib.sha256(reference).hexdigest()}")
    print(f"Regenerating...")

    entropy, record = engine.generate(manifest)
    match = (entropy == reference)

    if match:
        print(f"\n✅  VERIFIED — byte-exact match ({len(entropy):,} bytes)")
    else:
        print(f"\n❌  MISMATCH")
        print(f"  Expected SHA-256: {hashlib.sha256(reference).hexdigest()}")
        print(f"  Got SHA-256:      {record.output_sha256}")
        # Find first divergence
        for i in range(min(len(entropy), len(reference))):
            if entropy[i] != reference[i]:
                print(f"  First divergence at byte {i}")
                break
        sys.exit(1)


def cmd_test(args: argparse.Namespace) -> None:
    """Run statistical tests on entropy data."""
    with open(args.input, "rb") as f:
        data = f.read()

    print(f"Testing: {args.input} ({len(data):,} bytes)")
    results = run_full_suite(data)
    print_report(results)

    failed = sum(1 for r in results if not r.passed)
    if failed > 0:
        sys.exit(1)


def cmd_info(args: argparse.Namespace) -> None:
    """Show manifest information."""
    manifest = Manifest.load(args.manifest)
    print(manifest.to_json(pretty=True))


def cmd_benchmark(args: argparse.Namespace) -> None:
    """Benchmark entropy generation throughput."""
    engine = DESEEngine()

    systems = [args.system] if args.system else [
        "lorenz", "rossler", "chua", "chen", "hyper_lorenz", "double_pendulum"
    ]
    extractors = [args.extractor] if args.extractor else [
        "lsb", "xor_fold", "hash", "composite"
    ]

    print(f"\n{'System':<18} {'Extractor':<12} {'Bytes':>10} "
          f"{'Time (s)':>10} {'KB/s':>10} {'bits/step':>10}")
    print("─" * 72)

    for sys_name in systems:
        for ext_name in extractors:
            manifest = Manifest(
                system=sys_name,
                initial_state=[1.0] * _system_dim(sys_name),
                dt=_default_dt(sys_name),
                warmup_steps=500,
                extract_steps=args.steps,
                extractor=ext_name,
                comment="benchmark",
            )
            entropy, record = engine.generate(manifest)
            print(f"{sys_name:<18} {ext_name:<12} {record.output_bytes:>10,} "
                  f"{record.elapsed_seconds:>10.3f} "
                  f"{record.throughput_kbps:>10.1f} "
                  f"{record.entropy_rate_bps:>10.1f}")

    print("─" * 72)


# ─── Helpers ─────────────────────────────────────────────────────────

def _system_dim(name: str) -> int:
    from dese.systems import SYSTEMS
    return SYSTEMS[name]().dimension


def _default_dt(name: str) -> float:
    from dese.systems import SYSTEMS
    return SYSTEMS[name]()._dt


# ─── Entry point ─────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dese",
        description="DESE — Deterministic Entropy Simulation Engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    p_gen = sub.add_parser("generate", help="Generate entropy")
    p_gen.add_argument("--system", default="lorenz",
                       choices=["lorenz", "rossler", "chua", "chen",
                                "hyper_lorenz", "double_pendulum"])
    p_gen.add_argument("--steps", type=int, default=10_000)
    p_gen.add_argument("--warmup", type=int, default=1000)
    p_gen.add_argument("--extractor", default="lsb",
                       choices=["lsb", "xor_fold", "hash", "composite"])
    p_gen.add_argument("--seed", type=str, default=None,
                       help="Human-readable seed phrase")
    p_gen.add_argument("--manifest", type=str, default=None,
                       help="Load manifest from JSON file")
    p_gen.add_argument("-o", "--output", type=str, default=None,
                       help="Output file (default: stdout)")
    p_gen.add_argument("--save-manifest", action="store_true",
                       help="Save manifest alongside output")
    p_gen.set_defaults(func=cmd_generate)

    # verify
    p_ver = sub.add_parser("verify", help="Verify entropy against manifest")
    p_ver.add_argument("--manifest", required=True)
    p_ver.add_argument("--reference", required=True)
    p_ver.set_defaults(func=cmd_verify)

    # test
    p_test = sub.add_parser("test", help="Run statistical tests")
    p_test.add_argument("--input", "-i", required=True)
    p_test.set_defaults(func=cmd_test)

    # info
    p_info = sub.add_parser("info", help="Show manifest info")
    p_info.add_argument("--manifest", required=True)
    p_info.set_defaults(func=cmd_info)

    # benchmark
    p_bench = sub.add_parser("benchmark", help="Benchmark throughput")
    p_bench.add_argument("--system", default=None)
    p_bench.add_argument("--extractor", default=None)
    p_bench.add_argument("--steps", type=int, default=50_000)
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
