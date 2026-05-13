from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.base import BaseFactor


class VolatilityFactor(BaseFactor):
    """Volatility factor for VIX term structure, SKEW, and MOVE transforms."""

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)
