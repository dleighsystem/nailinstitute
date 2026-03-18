"""
NAIL Institute — 70B Re-run of Exp27, 28, 29
==============================================
Original runs were on mistral:7b-instruct. The 7B model was too small
to exhibit the deception/delegation/sleeper behaviours these experiments
test. This script re-runs all three on nemotron:70b.

Results saved to:
  exp27_70b_results.json
  exp28_70b_results.json
  exp29_70b_results.json

STATUS: ALL THREE 70B RUNS COMPLETE (2026-03-16)
  - exp27_70b_results.json ✅
  - exp28_70b_results.json ✅
  - exp29_70b_results.json ✅ (runtime: 11,952s = ~199 min)

USAGE:
  cd "/home/dleighsystems/Desktop/NAIL institute/experiments"
  PYTHONUNBUFFERED=1 nohup python -u rerun_27_28_29_70b.py > ../rerun_70b.log 2>&1 &

DESIGN NOTES (fixed in v2):
  - Checks for existing 70B results before running (skip if already complete)
  - Patches FAST_MODEL at both cfg level and module level before calling main()
  - The `from shared.config import FAST_MODEL` pattern copies the value at import
    time into the module namespace. We patch mod.FAST_MODEL *after* import so that
    when main() reads `model = FAST_MODEL`, it gets our patched value (since Python
    resolves bare names in the module's own global dict first).
  - Backup/restore of 7B results prevents data loss if main() overwrites them.
"""

import json
import sys
import time
import importlib
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared.config import PRIMARY_MODEL, DATA_DIR


def patch_and_run(module_name: str, output_filename: str,
                  original_filename: str = "",
                  model: str = PRIMARY_MODEL):
    """
    Import an experiment module, monkey-patch FAST_MODEL to 70B,
    call main(), then rename its output file to our 70B filename.

    Skips execution if the 70B output file already exists and is valid.
    """
    out_path = DATA_DIR / output_filename

    # ── Skip if 70B results already exist ──
    if out_path.exists():
        try:
            with open(out_path) as f:
                existing = json.load(f)
            if existing.get("model") == model:
                print(f"\n{'═' * 60}")
                print(f"  SKIP {module_name} — 70B results already exist")
                print(f"  File: {out_path}")
                print(f"{'═' * 60}\n")
                return existing
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupt file — re-run

    print(f"\n{'═' * 60}")
    print(f"  Re-running {module_name} with {model}")
    print(f"{'═' * 60}\n")

    t0 = time.time()

    # Back up original 7B results if they exist
    orig_path = DATA_DIR / original_filename if original_filename else None
    backup_path = None
    if orig_path and orig_path.exists():
        backup_path = orig_path.with_suffix(".7b_backup.json")
        if not backup_path.exists():
            import shutil
            shutil.copy2(orig_path, backup_path)
            print(f"  📦 Backed up {original_filename} → {backup_path.name}")

    # Import the module
    mod = importlib.import_module(module_name)

    # Patch FAST_MODEL at the module level.
    # The experiment's main() does `model = FAST_MODEL` which resolves against
    # the module's own __dict__, so patching mod.FAST_MODEL is sufficient.
    original_mod_fast = getattr(mod, 'FAST_MODEL', None)
    mod.FAST_MODEL = model

    # Also patch at config level for any sub-imports that read cfg.FAST_MODEL
    import shared.config as cfg
    original_fast = cfg.FAST_MODEL
    cfg.FAST_MODEL = model

    try:
        # Call main() which internally reads FAST_MODEL
        mod.main()

        elapsed = time.time() - t0
        print(f"  Runtime: {timedelta(seconds=int(elapsed))}")

        # main() writes to the standard output path; rename to 70B filename
        if orig_path and orig_path.exists():
            # Read, augment, and save to 70B path
            with open(orig_path) as f:
                result = json.load(f)
            result["model"] = model
            result["rerun_note"] = "70B re-run of original 7B experiment"
            with open(out_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            print(f"  ✅ 70B results saved to {out_path}")

            # Restore the 7B backup
            if backup_path and backup_path.exists():
                import shutil
                shutil.copy2(backup_path, orig_path)
                print(f"  ♻️  Restored original 7B results to {original_filename}")

            return result

        return {"status": "complete", "runtime_s": round(elapsed, 1)}

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        # Restore backup on error too
        if backup_path and backup_path.exists() and orig_path:
            import shutil
            shutil.copy2(backup_path, orig_path)
        return {"error": str(e), "module": module_name}

    finally:
        cfg.FAST_MODEL = original_fast
        if original_mod_fast is not None:
            mod.FAST_MODEL = original_mod_fast


def main():
    print("\n" + "═" * 70)
    print("  ╔═══════════════════════════════════════════════════════════════╗")
    print("  ║  NAIL INSTITUTE — 70B RE-RUN: Exp27, 28, 29                ║")
    print("  ║                                                             ║")
    print("  ║  Testing deception/delegation/sleeper at 70B scale          ║")
    print(f"  ║  Model: {PRIMARY_MODEL:<51}║")
    print("  ╚═══════════════════════════════════════════════════════════════╝")
    print("═" * 70 + "\n")

    overall_start = time.time()
    summary = {}

    # ── Exp27: Shadow Delegation ──
    r = patch_and_run(
        "exp27_shadow_delegation.run",
        "exp27_70b_results.json",
        "exp27_results.json",
    )
    if r:
        summary["exp27"] = "complete"
    else:
        summary["exp27"] = "failed"

    # ── Exp28: Credential Harvesting ──
    r = patch_and_run(
        "exp28_credential_harvesting.run",
        "exp28_70b_results.json",
        "exp28_results.json",
    )
    if r:
        summary["exp28"] = "complete"
    else:
        summary["exp28"] = "failed"

    # ── Exp29: Temporal Sleeper ──
    r = patch_and_run(
        "exp29_temporal_sleeper.run",
        "exp29_70b_results.json",
        "exp29_results.json",
    )
    if r:
        summary["exp29"] = "complete"
    else:
        summary["exp29"] = "failed"

    total = time.time() - overall_start
    print("\n" + "═" * 70)
    print(f"  70B RE-RUN COMPLETE — {timedelta(seconds=int(total))}")
    print(f"  Summary: {summary}")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    main()
