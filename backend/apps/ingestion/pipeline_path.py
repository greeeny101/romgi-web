"""
The vendored pipeline in apps/ingestion/pipeline/ (copied near-verbatim from
romgi/db/{core,sources,parsers,grouping,utils,scripts}) uses flat absolute
imports (`from core.contract import ...`, `from utils import cache_manager`,
etc.) exactly as it did in the original repo, where db/ itself was the
script's CWD/directory and therefore implicitly on sys.path.

Importing it from Django instead of running it as a script means we have to
put pipeline/ on sys.path ourselves. Call ensure() before importing anything
from apps.ingestion.pipeline.*.
"""

import sys
from pathlib import Path

_PIPELINE_DIR = Path(__file__).resolve().parent / "pipeline"

_done = False


def ensure() -> None:
    global _done
    if _done:
        return
    path = str(_PIPELINE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    _done = True
