import sys
from pathlib import Path

# Make `arsenal` importable for the tests.
_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_root / "arsenal"))
sys.path.insert(0, str(_root / "scripts"))
