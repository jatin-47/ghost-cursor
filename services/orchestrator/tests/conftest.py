import os
import sys
from pathlib import Path

# Ensure services/orchestrator and repo root are in sys.path
_orchestrator_dir = str(Path(__file__).resolve().parent.parent)
_repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _orchestrator_dir not in sys.path:
    sys.path.insert(0, _orchestrator_dir)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

os.environ.setdefault("GHOST_STORE", "memory")

