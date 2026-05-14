from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation import spearman_ic


def horizon_return(price: pd.Series, horizon: int) -> pd.Series:
    price = price.astype(float).sort_index()
    if horizon > 0:
        return price.pct_change(horizon, fill_method=None).shift(-horizon).rename(f"return_plus_{horizon}d")
    if horizon < 0:
        lookback = abs(horizon)
        return price.pct_change(lookback, fill_method=None).rename(f"return_minus_{lookback}d")
    return pd.Series(np.nan, index=price.index, name="return_0d")


def expected_sign_value(expected_sign: str | None) -> int:
    if expected_sign == "negative":
        return -1
    if expected_sign == "positive":
        return 1
    return 0


def sign_matches(ic: float, expected_sign: str | None) -> bool | float:
    if pd.isna(ic) or expected_sign_value(expected_sign) == 0:
        return np.nan
    return bool(np.sign(ic) == expected_sign_value(expected_sign))


def any_actual_sign_match(values: pd.Series) -> bool:
    return any(bool(value) for value in values.dropna())


def sign_flip_horizon(group: pd.DataFrame) -> int | float:
    ordered = group.sort_values("horizon")
    signs = ordered["ic"].dropna().apply(np.sign)
    if signs.empty:
        return np.nan

    previous = signs.iloc[0]
    for idx, current in signs.iloc[1:].items():
        if current != 0 and previous != 0 and current != previous:
            return int(ordered.loc[idx, "horizon"])
        if current != 0:
            previous = current
    return np.nan


def classify_factor_group(
    group: pd.DataFrame,
    expected_sign: str | None,
    leading_t_threshold: float = 2.0,
    lagging_t_threshold: float = 2.0,
    noise_t_threshold: float = 1.5,
) -> str:
    valid = group.dropna(subset=["t_stat", "ic"])
    if valid.empty or valid["t_stat"].abs().max() < noise_t_threshold:
        return "NOISE"

    significant = valid[valid["t_stat"].abs() > leading_t_threshold]
    reversed_sig = significant[significant["actual_sign_matches"] == False]  # noqa: E712
    if not reversed_sig.empty:
        return "REVERSED"

    leading = valid[(valid["horizon"].between(5, 20)) & (valid["t_stat"].abs() > leading_t_threshold)]
    if not leading.empty and any_actual_sign_match(leading["actual_sign_matches"]):
        return "LEADING"

    strongest = valid.loc[valid["t_stat"].abs().idxmax()]
    horizon = int(strongest["horizon"])
    if -1 <= horizon <= 3:
        return "COINCIDENT"
    if -20 <= horizon <= -3 and abs(strongest["t_stat"]) > lagging_t_threshold:
        return "LAGGING"
    return "NOISE"


def scan_horizons(
    signals: pd.DataFrame,
    targets: dict[str, pd.Series],
    horizons: list[int],
    expected_signs: dict[str, str] | None = None,
    min_obs: int = 250,
    leading_t_threshold: float = 2.0,
    lagging_t_threshold: float = 2.0,
    noise_t_threshold: float = 1.5,
) -> pd.DataFrame:
    expected_signs = expected_signs or {}
    records = []

    for signal_name, signal in signals.items():
        expected_sign = expected_signs.get(signal_name, "negative")
        for target_name, target in targets.items():
            for horizon in horizons:
                returns = horizon_return(target, horizon)
                metrics = spearman_ic(signal, returns)
                if metrics["n"] < min_obs:
                    metrics = {"ic": np.nan, "t_stat": np.nan, "p_value": np.nan, "n": metrics["n"]}
                records.append(
                    {
                        "signal": signal_name,
                        "target": target_name,
                        "horizon": horizon,
                        "expected_sign": expected_sign,
                        "actual_sign_matches": sign_matches(metrics["ic"], expected_sign),
                        "ic": metrics["ic"],
                        "t_stat": metrics["t_stat"],
                        "p_value": metrics["p_value"],
                        "n_obs": metrics["n"],
                    }
                )

    table = pd.DataFrame(records)
    if table.empty:
        return table

    flips = table.groupby(["signal", "target"], group_keys=False).apply(sign_flip_horizon, include_groups=False)
    flip_lookup = flips.rename("sign_flip_horizon").reset_index()
    table = table.merge(flip_lookup, on=["signal", "target"], how="left")

    labels = []
    for (signal, target), group in table.groupby(["signal", "target"]):
        expected_sign = expected_signs.get(signal, "negative")
        label = classify_factor_group(
            group,
            expected_sign=expected_sign,
            leading_t_threshold=leading_t_threshold,
            lagging_t_threshold=lagging_t_threshold,
            noise_t_threshold=noise_t_threshold,
        )
        labels.append({"signal": signal, "target": target, "classification": label})
    return table.merge(pd.DataFrame(labels), on=["signal", "target"], how="left")


def classification_summary(ic_table: pd.DataFrame) -> pd.DataFrame:
    if ic_table.empty:
        return pd.DataFrame()

    rows = []
    for (signal, target), group in ic_table.groupby(["signal", "target"]):
        valid = group.dropna(subset=["t_stat"])
        if valid.empty:
            strongest = pd.Series({"horizon": np.nan, "ic": np.nan, "t_stat": np.nan})
        else:
            strongest = valid.loc[valid["t_stat"].abs().idxmax()]
        rows.append(
            {
                "signal": signal,
                "target": target,
                "classification": group["classification"].iloc[0],
                "strongest_horizon": strongest["horizon"],
                "strongest_ic": strongest["ic"],
                "strongest_t_stat": strongest["t_stat"],
                "sign_flip_horizon": group["sign_flip_horizon"].iloc[0],
            }
        )
    return pd.DataFrame(rows).sort_values(["target", "classification", "signal"])
