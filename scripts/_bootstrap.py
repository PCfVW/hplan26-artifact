"""Let the scripts run from a checkout even without `pip install -e .`."""
import sys
from pathlib import Path

try:
    import hplan_orchestrator  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator" / "src"))
