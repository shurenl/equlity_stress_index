from __future__ import annotations

import numpy as np
import pandas as pd

from src.diagnostics.horizon_scan import classify_factor_group, horizon_return, scan_horizons
from src.diagnostics.reporting_diag import generate_diagnostics_report
from src.diagnostics.regime_split import assign_regime
from src.diagnostics.rolling_ic import rolling_ic_series


def test_horizon_scan_recovers_known_positive_ic():
    index = pd.bdate_range("2024-01-01", periods=80)
    signal = pd.Series(np.linspace(0.001, 0.02, len(index)), index=index, name="test_factor")
    price_values = [100.0]
    for value in signal.iloc[:-1]:
        price_values.append(price_values[-1] * (1 + value))
    price = pd.Series(price_values, index=index, name="target")

    table = scan_horizons(
        signals=signal.to_frame(),
        targets={"TARGET": price},
        horizons=[1],
        expected_signs={"test_factor": "positive"},
        min_obs=30,
    )

    row = table.iloc[0]
    assert row["ic"] > 0.99
    assert bool(row["actual_sign_matches"]) is True


def test_horizon_return_negative_uses_past_return():
    index = pd.bdate_range("2024-01-01", periods=4)
    price = pd.Series([100.0, 110.0, 121.0, 133.1], index=index)

    result = horizon_return(price, -2)

    assert np.isclose(result.iloc[2], 0.21)
    assert pd.isna(result.iloc[0])


def test_classify_factor_group_reversed_when_significant_wrong_sign():
    group = pd.DataFrame(
        {
            "horizon": [5, 10, 20],
            "ic": [0.2, 0.25, 0.1],
            "t_stat": [2.5, 3.0, 1.0],
            "actual_sign_matches": [False, False, False],
        }
    )

    assert classify_factor_group(group, expected_sign="negative") == "REVERSED"


def test_regime_split_decade_and_vix():
    index = pd.to_datetime(["1998-01-01", "2008-01-01", "2021-01-01"])
    decade = assign_regime(index, "decade")
    vix = pd.Series([12.0, 20.0, 30.0], index=index)
    vix_regime = assign_regime(index, "vix", vix=vix)

    assert decade.tolist() == ["1990s", "2000s", "2020s"]
    assert vix_regime.tolist() == ["low_vix", "mid_vix", "high_vix"]


def test_rolling_ic_captures_sign_flip_without_future_window():
    index = pd.bdate_range("2024-01-01", periods=300)
    first = np.linspace(0.001, 0.02, 150)
    second = np.linspace(0.02, 0.001, 150)
    signal = pd.Series(np.concatenate([first, second]), index=index, name="factor")
    forward_returns = pd.Series(np.concatenate([first, -second]), index=index)
    price_values = [100.0]
    for value in forward_returns.iloc[:-1]:
        price_values.append(price_values[-1] * (1 + value))
    price = pd.Series(price_values, index=index, name="target")

    result = rolling_ic_series(signal, price, horizon=1, window=60, min_window_obs=50)
    valid = result.dropna(subset=["rolling_ic"])

    assert valid["rolling_ic"].iloc[:40].mean() > 0.8
    assert valid["rolling_ic"].iloc[-40:].mean() < -0.8
    assert (valid["sample_end"] < valid.index).all()


def test_generate_diagnostics_report(tmp_path):
    horizon = pd.DataFrame(
        {
            "signal": ["factor"],
            "target": ["^GSPC"],
            "horizon": [10],
            "ic": [-0.2],
            "t_stat": [-2.5],
            "classification": ["LEADING"],
        }
    )
    classification = pd.DataFrame(
        {
            "signal": ["factor"],
            "target": ["^GSPC"],
            "classification": ["LEADING"],
            "strongest_horizon": [10],
            "strongest_ic": [-0.2],
            "strongest_t_stat": [-2.5],
            "sign_flip_horizon": [np.nan],
        }
    )
    rolling_summary = pd.DataFrame(
        {
            "signal": ["credit_baa_10y"],
            "target": ["^GSPC"],
            "horizon": [10],
            "mean_ic": [-0.1],
            "median_ic": [-0.1],
            "last_1y_mean_ic": [-0.05],
            "expected_sign_consistency": [0.7],
            "n_windows": [20],
        }
    )
    output = tmp_path / "diag.pdf"

    result = generate_diagnostics_report(
        horizon_table=horizon,
        classification=classification,
        rolling_table=pd.DataFrame(),
        rolling_summary=rolling_summary,
        output_path=output,
        validation_path=tmp_path / "missing_validation.png",
        credit_chart_path=tmp_path / "missing_credit.png",
    )

    assert result.exists()
    assert result.stat().st_size > 0
