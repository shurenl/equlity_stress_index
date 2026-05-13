from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


@dataclass
class CompositeResult:
    esi: pd.DataFrame
    equal_contributions: pd.DataFrame
    ic_contributions: pd.DataFrame
    ic_weights: pd.DataFrame


def factor_names(config: dict) -> list[str]:
    return list(config["factors"].keys())


def config_weights(config: dict) -> pd.Series:
    weights = {name: float(spec["weight"]) for name, spec in config["factors"].items()}
    return pd.Series(weights, dtype=float)


def nonlinear_factor_panel(config: dict, factor_panel: pd.DataFrame) -> pd.DataFrame:
    columns = {name: f"{name}_nonlinear" for name in factor_names(config)}
    missing = [column for column in columns.values() if column not in factor_panel.columns]
    if missing:
        raise KeyError(f"Missing nonlinear factor columns: {missing}")
    return factor_panel[list(columns.values())].rename(columns={value: key for key, value in columns.items()})


def rolling_z_score(series: pd.Series, window: int = 252, min_periods: int | None = None) -> pd.Series:
    min_periods = min_periods or window // 2
    mean = series.rolling(window=window, min_periods=min_periods).mean()
    std = series.rolling(window=window, min_periods=min_periods).std().replace(0, np.nan)
    return ((series - mean) / std).rename(series.name)


def row_normalized_weights(signals: pd.DataFrame, weights: pd.Series) -> pd.DataFrame:
    aligned = weights.reindex(signals.columns).astype(float)
    available = signals.notna().mul(aligned, axis=1)
    row_sums = available.sum(axis=1).replace(0, np.nan)
    normalized = available.div(row_sums, axis=0)
    return normalized.where(signals.notna())


def build_equal_weighted(
    config: dict,
    factor_panel: pd.DataFrame,
    z_window: int = 252,
) -> tuple[pd.Series, pd.DataFrame]:
    signals = nonlinear_factor_panel(config, factor_panel)
    weights = row_normalized_weights(signals, config_weights(config))
    contributions = signals.mul(weights).add_prefix("equal_")
    raw = contributions.sum(axis=1, min_count=1).rename("esi_equal_weighted_raw")
    esi = rolling_z_score(raw, window=z_window).rename("esi_equal_weighted")
    return esi, contributions


def future_returns(target: pd.Series, horizon: int = 10) -> pd.Series:
    target = target.astype(float).sort_index()
    return target.pct_change(horizon, fill_method=None).shift(-horizon).rename(f"future_return_{horizon}d")


def rolling_spearman_ic_weights(
    signals: pd.DataFrame,
    target: pd.Series,
    horizon: int = 10,
    window: int = 252,
    min_periods: int | None = None,
) -> pd.DataFrame:
    min_periods = min_periods or window // 2
    returns = future_returns(target, horizon=horizon).reindex(signals.index)
    weights = pd.DataFrame(np.nan, index=signals.index, columns=signals.columns, dtype=float)

    for idx, current_date in enumerate(signals.index):
        end_pos = idx - horizon
        if end_pos < min_periods:
            continue

        start_pos = max(0, end_pos - window + 1)
        window_index = signals.index[start_pos : end_pos + 1]
        ic_values: dict[str, float] = {}

        for column in signals.columns:
            sample = pd.concat([signals.loc[window_index, column], returns.loc[window_index]], axis=1).dropna()
            if len(sample) < min_periods or sample.iloc[:, 0].nunique() < 2 or sample.iloc[:, 1].nunique() < 2:
                continue
            ic = spearmanr(sample.iloc[:, 0], sample.iloc[:, 1]).statistic
            if pd.notna(ic):
                ic_values[column] = float(ic)

        if not ic_values:
            continue

        raw = pd.Series(ic_values)
        signed = -raw
        signed = signed.where(signed > 0, 0.0)
        if signed.sum() == 0:
            signed = raw.abs()
        if signed.sum() > 0:
            weights.loc[current_date, signed.index] = signed / signed.sum()

    return weights


def build_ic_weighted(
    config: dict,
    factor_panel: pd.DataFrame,
    target: pd.Series,
    horizon: int = 10,
    ic_window: int = 252,
    z_window: int = 252,
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    signals = nonlinear_factor_panel(config, factor_panel)
    weights = rolling_spearman_ic_weights(signals, target, horizon=horizon, window=ic_window)
    weights = weights.where(signals.notna())
    weights = weights.div(weights.sum(axis=1).replace(0, np.nan), axis=0)
    contributions = signals.mul(weights).add_prefix("ic_")
    raw = contributions.sum(axis=1, min_count=1).rename("esi_ic_weighted_raw")
    esi = rolling_z_score(raw, window=z_window).rename("esi_ic_weighted")
    return esi, contributions, weights.add_prefix("ic_weight_")


def build_composite(
    config: dict,
    factor_panel: pd.DataFrame,
    target: pd.Series | None = None,
) -> CompositeResult:
    equal_esi, equal_contributions = build_equal_weighted(config, factor_panel)
    esi = pd.DataFrame({"esi_equal_weighted": equal_esi})

    if target is None:
        ic_contributions = pd.DataFrame(index=factor_panel.index)
        ic_weights = pd.DataFrame(index=factor_panel.index)
    else:
        ic_esi, ic_contributions, ic_weights = build_ic_weighted(config, factor_panel, target)
        esi["esi_ic_weighted"] = ic_esi

    return CompositeResult(
        esi=esi,
        equal_contributions=equal_contributions,
        ic_contributions=ic_contributions,
        ic_weights=ic_weights,
    )
