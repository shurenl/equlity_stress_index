from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import f1_score, precision_score, recall_score


@dataclass
class EvaluationResult:
    ic_matrix: pd.DataFrame
    hit_ratio: pd.DataFrame
    signal_quality: pd.DataFrame
    benchmark_correlation: pd.DataFrame
    conditional_returns: pd.DataFrame
    data_coverage: pd.DataFrame


def forward_returns(price: pd.Series, horizons: list[int]) -> pd.DataFrame:
    price = price.astype(float).sort_index()
    return pd.DataFrame(
        {f"return_{horizon}d": price.pct_change(horizon, fill_method=None).shift(-horizon) for horizon in horizons}
    )


def forward_max_drawdown(price: pd.Series, horizon: int = 10) -> pd.Series:
    price = price.astype(float).sort_index()
    rows: list[float] = []
    values = price.to_numpy(dtype=float)

    for idx, current in enumerate(values):
        end = min(idx + horizon + 1, len(values))
        future = values[idx + 1 : end]
        if np.isnan(current) or len(future) < horizon or np.isnan(future).all():
            rows.append(np.nan)
            continue
        trough = np.nanmin(future)
        rows.append((trough / current) - 1.0)

    return pd.Series(rows, index=price.index, name=f"max_drawdown_{horizon}d")


def spearman_ic(signal: pd.Series, future_return: pd.Series) -> dict[str, float]:
    sample = pd.concat([signal, future_return], axis=1).dropna()
    if len(sample) < 3 or sample.iloc[:, 0].nunique() < 2 or sample.iloc[:, 1].nunique() < 2:
        return {"ic": np.nan, "t_stat": np.nan, "p_value": np.nan, "n": float(len(sample))}

    result = spearmanr(sample.iloc[:, 0], sample.iloc[:, 1])
    ic = float(result.statistic)
    n = len(sample)
    if abs(ic) >= 1:
        t_stat = np.inf * np.sign(ic)
    else:
        t_stat = ic * np.sqrt((n - 2) / max(1e-12, 1 - ic**2))

    return {"ic": ic, "t_stat": float(t_stat), "p_value": float(result.pvalue), "n": float(n)}


def build_ic_matrix(
    signals: pd.DataFrame,
    targets: dict[str, pd.Series],
    horizons: list[int],
) -> pd.DataFrame:
    records = []
    for signal_name, signal in signals.items():
        for target_name, target in targets.items():
            returns = forward_returns(target, horizons)
            for horizon in horizons:
                metrics = spearman_ic(signal, returns[f"return_{horizon}d"])
                records.append(
                    {
                        "signal": signal_name,
                        "target": target_name,
                        "horizon": horizon,
                        **metrics,
                    }
                )
    return pd.DataFrame(records)


def hit_ratio_table(
    esi: pd.Series,
    price: pd.Series,
    horizon: int = 10,
    quantiles: tuple[float, ...] = (0.85, 0.90, 0.95),
    drawdown_thresholds: tuple[float, ...] = (-0.03, -0.05),
) -> pd.DataFrame:
    drawdown = forward_max_drawdown(price, horizon=horizon)
    sample = pd.concat([esi.rename("esi"), drawdown], axis=1).dropna()
    records = []

    for threshold in drawdown_thresholds:
        full_rate = float((sample.iloc[:, 1] <= threshold).mean()) if not sample.empty else np.nan
        for quantile in quantiles:
            cutoff = sample["esi"].rolling(252, min_periods=126).quantile(quantile)
            high_esi = sample["esi"] >= cutoff.reindex(sample.index)
            subset = sample[high_esi]
            records.append(
                {
                    "esi_quantile": quantile,
                    "drawdown_threshold": abs(threshold),
                    "hit_ratio": float((subset.iloc[:, 1] <= threshold).mean()) if len(subset) else np.nan,
                    "full_sample_rate": full_rate,
                    "n": len(subset),
                }
            )
    return pd.DataFrame(records)


def signal_quality_table(
    esi: pd.Series,
    price: pd.Series,
    horizon: int = 10,
    event_threshold: float = -0.05,
    signal_quantile: float = 0.90,
) -> pd.DataFrame:
    drawdown = forward_max_drawdown(price, horizon=horizon)
    sample = pd.concat([esi.rename("esi"), drawdown], axis=1).dropna()
    cutoff = sample["esi"].rolling(252, min_periods=126).quantile(signal_quantile)
    predicted = sample["esi"] >= cutoff.reindex(sample.index)
    actual = sample.iloc[:, 1] <= event_threshold

    if actual.empty:
        precision = recall = f1 = np.nan
    else:
        precision = precision_score(actual, predicted, zero_division=0)
        recall = recall_score(actual, predicted, zero_division=0)
        f1 = f1_score(actual, predicted, zero_division=0)

    return pd.DataFrame(
        [
            {
                "event": f"max_drawdown_{horizon}d_gt_{abs(event_threshold):.0%}",
                "signal_quantile": signal_quantile,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "events": int(actual.sum()),
                "signals": int(predicted.sum()),
                "n": len(sample),
            }
        ]
    )


def conditional_return_distribution(
    esi: pd.Series,
    future_return: pd.Series,
    buckets: tuple[float, ...] = (0.0, 0.7, 0.85, 0.9, 0.95, 1.0),
) -> pd.DataFrame:
    sample = pd.concat([esi.rename("esi"), future_return.rename("future_return")], axis=1).dropna()
    expanding_pct = sample["esi"].rank(pct=True)
    sample = sample.assign(esi_percentile=expanding_pct)
    bucket = pd.cut(sample["esi_percentile"], bins=buckets, include_lowest=True)
    grouped = sample.groupby(bucket, observed=True)["future_return"]
    result = grouped.agg(["count", "mean", "median", "std"]).reset_index(names="esi_percentile_bucket")
    result["esi_percentile_bucket"] = result["esi_percentile_bucket"].astype(str)
    return result


def benchmark_correlations(esi: pd.Series, benchmarks: dict[str, pd.Series]) -> pd.DataFrame:
    records = []
    for name, benchmark in benchmarks.items():
        sample = pd.concat([esi.rename("esi"), benchmark.rename(name)], axis=1).dropna()
        records.append(
            {
                "benchmark": name,
                "correlation": float(sample["esi"].corr(sample[name])) if len(sample) >= 3 else np.nan,
                "n": len(sample),
            }
        )
    return pd.DataFrame(records)


def data_coverage_table(series: dict[str, pd.Series], required_start: str = "2020-01-01") -> pd.DataFrame:
    required_start_ts = pd.Timestamp(required_start)
    allowed_start_ts = required_start_ts + pd.Timedelta(days=3)
    records = []
    for name, values in series.items():
        clean = values.dropna()
        first_valid = clean.index.min() if not clean.empty else pd.NaT
        last_valid = clean.index.max() if not clean.empty else pd.NaT
        records.append(
            {
                "series": name,
                "first_valid": first_valid,
                "last_valid": last_valid,
                "non_null_count": int(clean.shape[0]),
                "covers_required_start": bool(pd.notna(first_valid) and first_valid <= allowed_start_ts),
            }
        )
    return pd.DataFrame(records)


def evaluate(
    factors: pd.DataFrame,
    esi: pd.DataFrame,
    targets: dict[str, pd.Series],
    benchmarks: dict[str, pd.Series],
    horizons: list[int] | None = None,
) -> EvaluationResult:
    horizons = horizons or [5, 10, 20]
    factor_signals = factors.filter(regex=r"_nonlinear$")
    factor_signals = factor_signals.rename(columns=lambda value: value.replace("_nonlinear", ""))
    esi_signals = esi.copy()
    signals = pd.concat([factor_signals, esi_signals], axis=1)

    primary_target_name = "^GSPC" if "^GSPC" in targets else next(iter(targets))
    primary_target = targets[primary_target_name]
    primary_esi = esi["esi_equal_weighted"]

    ic = build_ic_matrix(signals, targets, horizons)
    hit = hit_ratio_table(primary_esi, primary_target, horizon=10)
    quality = signal_quality_table(primary_esi, primary_target, horizon=10)
    future_10d = forward_returns(primary_target, [10])["return_10d"]
    conditional = conditional_return_distribution(primary_esi, future_10d)
    benchmark_corr = benchmark_correlations(primary_esi, benchmarks)
    coverage = data_coverage_table({**{column: factors[column] for column in factors.columns}, **targets, **benchmarks})

    return EvaluationResult(
        ic_matrix=ic,
        hit_ratio=hit,
        signal_quality=quality,
        benchmark_correlation=benchmark_corr,
        conditional_returns=conditional,
        data_coverage=coverage,
    )
