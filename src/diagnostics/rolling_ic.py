from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.diagnostics.horizon_scan import horizon_return


def _spearman_pair(left: pd.Series, right: pd.Series) -> tuple[float, float, float, int]:
    sample = pd.concat([left, right], axis=1).dropna()
    n_obs = len(sample)
    if n_obs < 3 or sample.iloc[:, 0].nunique() < 2 or sample.iloc[:, 1].nunique() < 2:
        return np.nan, np.nan, np.nan, n_obs

    result = spearmanr(sample.iloc[:, 0], sample.iloc[:, 1])
    ic = float(getattr(result, "statistic", result[0]))
    p_value = float(getattr(result, "pvalue", result[1]))
    if abs(ic) >= 1:
        t_stat = np.inf * np.sign(ic)
    else:
        t_stat = ic * np.sqrt((n_obs - 2) / max(1e-12, 1 - ic**2))
    return ic, float(t_stat), p_value, n_obs


def rolling_ic_series(
    signal: pd.Series,
    target_price: pd.Series,
    horizon: int,
    window: int = 126,
    min_window_obs: int = 100,
) -> pd.DataFrame:
    if horizon <= 0:
        raise ValueError("rolling_ic_series only supports positive forward horizons.")

    signal = signal.astype(float).sort_index().rename("signal")
    returns = horizon_return(target_price, horizon).rename("forward_return")
    index = signal.dropna().index.intersection(returns.dropna().index).sort_values()
    aligned_signal = signal.reindex(index)
    aligned_returns = returns.reindex(index)

    rows: list[dict[str, float | int | pd.Timestamp]] = []
    for output_pos, output_date in enumerate(index):
        cutoff_pos = output_pos - horizon - 1
        if cutoff_pos < 0:
            continue
        start_pos = max(0, cutoff_pos - window + 1)
        window_signal = aligned_signal.iloc[start_pos : cutoff_pos + 1]
        window_returns = aligned_returns.iloc[start_pos : cutoff_pos + 1]
        ic, t_stat, p_value, n_obs = _spearman_pair(window_signal, window_returns)
        if n_obs < min_window_obs:
            ic = t_stat = p_value = np.nan
        rows.append(
            {
                "date": output_date,
                "horizon": horizon,
                "rolling_ic": ic,
                "rolling_t_stat": t_stat,
                "p_value": p_value,
                "rolling_n": n_obs,
                "window_start": index[start_pos],
                "sample_end": index[cutoff_pos],
            }
        )

    return pd.DataFrame(rows).set_index("date").sort_index()


def rolling_ic_table(
    signal: pd.Series,
    target_price: pd.Series,
    horizons: list[int],
    window: int = 126,
    min_window_obs: int = 100,
) -> pd.DataFrame:
    frames = [
        rolling_ic_series(
            signal=signal,
            target_price=target_price,
            horizon=horizon,
            window=window,
            min_window_obs=min_window_obs,
        )
        for horizon in horizons
    ]
    return pd.concat(frames).sort_index()


def rolling_ic_diagnostics(table: pd.DataFrame, expected_sign: str = "negative") -> pd.DataFrame:
    expected_multiplier = -1 if expected_sign == "negative" else 1
    rows = []
    for horizon, group in table.groupby("horizon"):
        valid = group.dropna(subset=["rolling_ic"])
        last_year = valid[valid.index >= valid.index.max() - pd.DateOffset(years=1)] if not valid.empty else valid
        same_sign = np.sign(valid["rolling_ic"]) == expected_multiplier
        rows.append(
            {
                "horizon": horizon,
                "mean_ic": valid["rolling_ic"].mean(),
                "median_ic": valid["rolling_ic"].median(),
                "last_1y_mean_ic": last_year["rolling_ic"].mean(),
                "expected_sign_consistency": same_sign.mean() if len(valid) else np.nan,
                "n_windows": len(valid),
            }
        )
    return pd.DataFrame(rows)


def rolling_ic_batch(
    signals: pd.DataFrame,
    targets: dict[str, pd.Series],
    horizons: list[int],
    expected_signs: dict[str, str] | None = None,
    window: int = 126,
    min_window_obs: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    expected_signs = expected_signs or {}
    tables = []
    summaries = []

    for signal_name, signal in signals.items():
        for target_name, target in targets.items():
            table = rolling_ic_table(
                signal=signal,
                target_price=target,
                horizons=horizons,
                window=window,
                min_window_obs=min_window_obs,
            )
            table = table.assign(signal=signal_name, target=target_name)
            tables.append(table.reset_index())

            summary = rolling_ic_diagnostics(table, expected_sign=expected_signs.get(signal_name, "negative"))
            summary = summary.assign(signal=signal_name, target=target_name)
            summaries.append(summary)

    if not tables:
        return pd.DataFrame(), pd.DataFrame()

    rolling = pd.concat(tables, ignore_index=True)
    summary = pd.concat(summaries, ignore_index=True)
    return rolling, summary[["signal", "target", "horizon", "mean_ic", "median_ic", "last_1y_mean_ic", "expected_sign_consistency", "n_windows"]]
