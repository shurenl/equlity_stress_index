from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.base import BaseFactor


class CreditFactor(BaseFactor):
    """Credit spread factor using OAS changes as stress-positive inputs."""

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)
