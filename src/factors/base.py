from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.fetchers.base import BaseFetcher


@dataclass
class BaseFactor:
    """Config-driven factor with stress-positive transforms."""

    name: str
    spec: dict[str, Any]
    raw_dir: Path

    def raw_series(self) -> pd.Series:
        frame = self.raw_frame()
        if frame.shape[1] == 1:
            return frame.iloc[:, 0].rename(self.name)
        return (frame.iloc[:, 0] / frame.iloc[:, 1]).rename(self.name)

    def raw_frame(self) -> pd.DataFrame:
        path = self.raw_path()
        if not path.exists():
            raise FileNotFoundError(f"Missing raw data cache for factor {self.name}: {path}")
        frame = pd.read_parquet(path)
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        return frame.sort_index()

    def raw_path(self) -> Path:
        ticker = self.spec.get("ticker_compute", self.spec.get("tickers", self.spec.get("ticker")))
        cache_key = f"{self.spec['source']}_{BaseFetcher._safe_ticker(ticker)}"
        return self.raw_dir / f"{cache_key}.parquet"

    def transformed(self) -> pd.Series:
        transform = self.spec["transform"]
        frame = self.raw_frame()
        series = self.raw_series().astype(float)

        if transform == "diff_5d":
            result = series.diff(5)
        elif transform == "diff_20d_pct":
            result = series.pct_change(20, fill_method=None)
        elif transform == "ratio_minus_one":
            result = (frame.iloc[:, 0].astype(float) / frame.iloc[:, 1].astype(float)) - 1.0
        elif transform == "diff_from_ma60":
            result = series - series.rolling(window=60, min_periods=30).mean()
        elif transform == "ratio_chg_20d":
            ratio = frame.iloc[:, 0].astype(float) / frame.iloc[:, 1].astype(float)
            result = -ratio.pct_change(20, fill_method=None)
        else:
            raise ValueError(f"Unsupported transform for {self.name}: {transform}")

        result = result.replace([np.inf, -np.inf], np.nan)
        return result.rename(self.name)

    def z_score(self, window: int = 252) -> pd.Series:
        series = self.transformed()
        mean = series.rolling(window=window, min_periods=window // 2).mean()
        std = series.rolling(window=window, min_periods=window // 2).std()
        z = (series - mean) / std.replace(0, np.nan)
        return z.rename(self.name)

    def winsorized(self, clip: float = 3.0) -> pd.Series:
        return self.z_score().clip(lower=-clip, upper=clip).rename(self.name)

    def nonlinear(self) -> pd.Series:
        z = self.winsorized()
        weights = pd.Series(1.0, index=z.index)
        weights[z.abs() < 0.5] = 0.0
        weights[z.abs() > 2.0] = 2.0
        return (z * weights).rename(self.name)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                f"{self.name}_raw": self.raw_series(),
                f"{self.name}_transformed": self.transformed(),
                f"{self.name}_z_score": self.z_score(),
                f"{self.name}_winsorized": self.winsorized(),
                f"{self.name}_nonlinear": self.nonlinear(),
            }
        )


def build_factor(name: str, spec: dict[str, Any], raw_dir: Path) -> BaseFactor:
    return BaseFactor(name=name, spec=spec, raw_dir=raw_dir)


def build_factor_panel(config: dict[str, Any], raw_dir: Path) -> pd.DataFrame:
    frames = [build_factor(name, spec, raw_dir).to_frame() for name, spec in config["factors"].items()]
    return pd.concat(frames, axis=1).sort_index()
