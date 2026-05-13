from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation import (
    benchmark_correlations,
    build_ic_matrix,
    conditional_return_distribution,
    evaluate,
    forward_max_drawdown,
    forward_returns,
    hit_ratio_table,
    signal_quality_table,
    spearman_ic,
)


def test_forward_returns_are_aligned_to_signal_date():
    price = pd.Series([100.0, 110.0, 121.0], index=pd.bdate_range("2024-01-01", periods=3))

    result = forward_returns(price, [2])

    assert np.isclose(result.iloc[0]["return_2d"], 0.21)
    assert pd.isna(result.iloc[1]["return_2d"])


def test_forward_max_drawdown_uses_future_window():
    price = pd.Series([100.0, 98.0, 95.0, 105.0], index=pd.bdate_range("2024-01-01", periods=4))

    result = forward_max_drawdown(price, horizon=2)

    assert np.isclose(result.iloc[0], -0.05)
    assert pd.isna(result.iloc[-1])


def test_spearman_ic_returns_negative_for_stress_positive_signal():
    index = pd.bdate_range("2024-01-01", periods=20)
    signal = pd.Series(np.arange(20), index=index)
    returns = pd.Series(-np.arange(20), index=index)

    result = spearman_ic(signal, returns)

    assert result["ic"] < -0.99
    assert result["t_stat"] < 0
    assert result["n"] == 20


def test_build_ic_matrix_creates_signal_target_horizon_rows():
    index = pd.bdate_range("2024-01-01", periods=40)
    signals = pd.DataFrame({"factor": np.arange(40)}, index=index)
    targets = {"^GSPC": pd.Series(np.linspace(100, 120, 40), index=index)}

    result = build_ic_matrix(signals, targets, [5, 10])

    assert set(result["horizon"]) == {5, 10}
    assert set(result["signal"]) == {"factor"}
    assert set(result["target"]) == {"^GSPC"}


def test_hit_ratio_and_signal_quality_return_expected_columns():
    index = pd.bdate_range("2024-01-01", periods=320)
    esi = pd.Series(np.linspace(-2, 2, len(index)), index=index)
    price = pd.Series(100.0, index=index)
    price.iloc[260:270] = np.linspace(100, 90, 10)
    price.iloc[270:] = 90

    hit = hit_ratio_table(esi, price, horizon=10)
    quality = signal_quality_table(esi, price, horizon=10)

    assert {"esi_quantile", "drawdown_threshold", "hit_ratio", "full_sample_rate", "n"}.issubset(hit.columns)
    assert {"precision", "recall", "f1", "events", "signals"}.issubset(quality.columns)


def test_conditional_distribution_and_benchmark_corr():
    index = pd.bdate_range("2024-01-01", periods=20)
    esi = pd.Series(np.linspace(-1, 1, 20), index=index)
    returns = pd.Series(np.linspace(0.02, -0.02, 20), index=index)
    benchmark = pd.Series(np.linspace(-1, 1, 20), index=index)

    distribution = conditional_return_distribution(esi, returns)
    corr = benchmark_correlations(esi, {"NFCI": benchmark})

    assert not distribution.empty
    assert np.isclose(corr.loc[0, "correlation"], 1.0)


def test_evaluate_returns_all_tables():
    index = pd.bdate_range("2024-01-01", periods=320)
    factors = pd.DataFrame({"credit_hy_nonlinear": np.linspace(-2, 2, len(index))}, index=index)
    esi = pd.DataFrame({"esi_equal_weighted": np.linspace(-2, 2, len(index))}, index=index)
    target = pd.Series(np.linspace(120, 100, len(index)), index=index)
    benchmark = pd.Series(np.linspace(-1, 1, len(index)), index=index)

    result = evaluate(factors, esi, {"^GSPC": target}, {"NFCI": benchmark}, horizons=[5])

    assert not result.ic_matrix.empty
    assert not result.hit_ratio.empty
    assert not result.signal_quality.empty
    assert not result.benchmark_correlation.empty
    assert not result.conditional_returns.empty
    assert not result.data_coverage.empty
