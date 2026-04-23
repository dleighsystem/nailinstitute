import sys
from pathlib import Path

# Make `import shield` work without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
