from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.base import BaseFactor


class BreadthFactor(BaseFactor):
    """Breadth factor where equal-weight underperformance contributes to stress."""

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)
