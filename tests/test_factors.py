from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import BaseFactor, build_factor_panel


def write_raw(tmp_path, source: str, key: str, frame: pd.DataFrame) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    frame.to_parquet(raw_dir / f"{source}_{key}.parquet")


def test_diff_and_z_score_use_trailing_window(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=140)
    frame = pd.DataFrame({"ABC": np.arange(140, dtype=float) ** 2}, index=dates)
    write_raw(tmp_path, "fred", "ABC", frame)
    factor = BaseFactor(
        "credit_hy",
        {"source": "fred", "ticker": "ABC", "transform": "diff_5d"},
        tmp_path / "raw",
    )

    transformed = factor.transformed()
    z = factor.z_score(window=20)

    assert transformed.iloc[5] == 25.0
    assert pd.isna(z.iloc[8])
    assert pd.notna(z.iloc[20])


def test_ratio_minus_one_transform(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=3)
    frame = pd.DataFrame({"AAA": [12.0, 15.0, 18.0], "BBB": [10.0, 10.0, 12.0]}, index=dates)
    write_raw(tmp_path, "yahoo", "AAA_BBB", frame)
    factor = BaseFactor(
        "vix_term_structure",
        {"source": "yahoo", "tickers": ["AAA", "BBB"], "transform": "ratio_minus_one"},
        tmp_path / "raw",
    )

    result = factor.transformed()

    assert np.isclose(result.iloc[0], 0.2)
    assert np.isclose(result.iloc[2], 0.5)


def test_breadth_ratio_change_is_stress_positive_when_ratio_falls(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=25)
    equal_weight = pd.Series(np.linspace(100.0, 90.0, len(dates)), index=dates)
    cap_weight = pd.Series(100.0, index=dates)
    frame = pd.DataFrame({"EQ": equal_weight, "CAP": cap_weight}, index=dates)
    write_raw(tmp_path, "fred", "EQ_CAP", frame)
    factor = BaseFactor(
        "breadth_proxy",
        {"source": "fred", "tickers": ["EQ", "CAP"], "transform": "ratio_chg_20d"},
        tmp_path / "raw",
    )

    result = factor.transformed()

    assert result.iloc[20] > 0


def test_nonlinear_zeroes_small_values_and_doubles_large_values(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=140)
    values = np.concatenate([np.zeros(130), np.full(10, 100.0)])
    frame = pd.DataFrame({"ABC": values}, index=dates)
    write_raw(tmp_path, "fred", "ABC", frame)
    factor = BaseFactor(
        "stress_factor",
        {"source": "fred", "ticker": "ABC", "transform": "diff_5d"},
        tmp_path / "raw",
    )

    nonlinear = factor.nonlinear()
    z = factor.winsorized()

    small = z[z.abs() < 0.5].dropna()
    assert (nonlinear.loc[small.index] == 0).all()
    large = z[z.abs() > 2.0].dropna()
    assert (nonlinear.loc[large.index] == z.loc[large.index] * 2).all()


def test_build_factor_panel_writes_expected_columns(tmp_path):
    dates = pd.bdate_range("2024-01-01", periods=140)
    write_raw(tmp_path, "fred", "ABC", pd.DataFrame({"ABC": np.arange(140.0)}, index=dates))
    config = {
        "factors": {
            "credit_hy": {
                "source": "fred",
                "ticker": "ABC",
                "transform": "diff_5d",
                "weight": 1.0,
            }
        }
    }

    panel = build_factor_panel(config, tmp_path / "raw")

    assert "credit_hy_raw" in panel.columns
    assert "credit_hy_transformed" in panel.columns
    assert "credit_hy_z_score" in panel.columns
    assert "credit_hy_nonlinear" in panel.columns
