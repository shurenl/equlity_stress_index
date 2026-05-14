from __future__ import annotations

from pathlib import Path
from typing import Any

from src.factors.base import BaseFactor


class CreditBaa10Y(BaseFactor):
    """
    Moody's Seasoned Baa - 10Y Treasury spread (FRED: BAA10Y).

    Long-history credit spread, daily from 1986-01-02, not subject to
    ICE BofA's 3-year truncation on FRED. Moody's series is based on
    longer-duration bonds, so levels are not directly comparable with ICE
    BofA OAS, but standardized changes are useful as long-history signals.
    """

    fred_ticker = "BAA10Y"

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)


class CreditAaa10Y(BaseFactor):
    """Moody's Seasoned Aaa - 10Y Treasury spread (FRED: AAA10Y)."""

    fred_ticker = "AAA10Y"

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)


class CreditBaaAaa(BaseFactor):
    """
    Moody's Baa minus Aaa spread.

    This computed factor isolates default-risk premium from broad
    duration/term-structure effects by subtracting AAA10Y from BAA10Y.
    """

    fred_expression = "BAA10Y - AAA10Y"

    def __init__(self, name: str, spec: dict[str, Any], raw_dir: Path) -> None:
        super().__init__(name=name, spec=spec, raw_dir=raw_dir)

