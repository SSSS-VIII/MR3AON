"""Compatibility namespace for the shared agent strategy; no duplicated implementation."""
from pathlib import Path
__path__ = [str(Path(__file__).resolve().parents[2] / "agent" / "intelligence_strategy")]
