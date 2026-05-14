from __future__ import annotations

import numpy as np
import pandas as pd


def assign_regime(dates, method: str, **kwargs) -> pd.Series:
    index = pd.DatetimeIndex(dates)
    if method == "vix":
        return vix_regime(index, kwargs["vix"])
    if method == "spx_trend":
        return spx_trend_regime(index, kwargs["spx"])
    if method == "esi_quantile":
        return esi_quantile_regime(index, kwargs["esi"])
    if method == "realized_vol":
        return realized_vol_regime(index, kwargs["spx"], window=kwargs.get("window", 20))
    if method == "decade":
        return decade_regime(index)
    raise ValueError(f"Unsupported regime method: {method}")


def vix_regime(index: pd.DatetimeIndex, vix: pd.Series) -> pd.Series:
    aligned = vix.reindex(index).astype(float)
    return pd.cut(
        aligned,
        bins=[0, 15, 25, np.inf],
        labels=["low_vix", "mid_vix", "high_vix"],
        include_lowest=True,
    ).astype("object")


def spx_trend_regime(index: pd.DatetimeIndex, spx: pd.Series) -> pd.Series:
    aligned = spx.reindex(index).astype(float)
    ma200 = aligned.rolling(200, min_periods=100).mean()
    slope = ma200.diff(60)
    above = aligned >= ma200
    rising = slope >= 0
    regime = pd.Series(index=index, dtype="object")
    regime[above & rising] = "above_200dma_rising"
    regime[above & ~rising] = "above_200dma_falling"
    regime[~above & rising] = "below_200dma_rising"
    regime[~above & ~rising] = "below_200dma_falling"
    return regime


def esi_quantile_regime(index: pd.DatetimeIndex, esi: pd.Series) -> pd.Series:
    aligned = esi.reindex(index).astype(float)
    q70 = aligned.rolling(252, min_periods=126).quantile(0.70)
    q90 = aligned.rolling(252, min_periods=126).quantile(0.90)
    regime = pd.Series("normal", index=index, dtype="object")
    regime[aligned >= q70] = "elevated"
    regime[aligned >= q90] = "stress"
    regime[aligned.isna() | q70.isna() | q90.isna()] = np.nan
    return regime


def realized_vol_regime(index: pd.DatetimeIndex, spx: pd.Series, window: int = 20) -> pd.Series:
    aligned = spx.reindex(index).astype(float)
    realized = aligned.pct_change(fill_method=None).rolling(window, min_periods=window).std() * np.sqrt(252)
    low = realized.rolling(252, min_periods=126).quantile(1 / 3)
    high = realized.rolling(252, min_periods=126).quantile(2 / 3)
    regime = pd.Series("mid_realized_vol", index=index, dtype="object")
    regime[realized <= low] = "low_realized_vol"
    regime[realized >= high] = "high_realized_vol"
    regime[realized.isna() | low.isna() | high.isna()] = np.nan
    return regime


def decade_regime(index: pd.DatetimeIndex) -> pd.Series:
    years = index.year
    labels = ((years // 10) * 10).astype(str) + "s"
    return pd.Series(labels, index=index, dtype="object")

