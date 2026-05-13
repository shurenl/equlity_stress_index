from __future__ import annotations

import numpy as np
import pandas as pd

from src.composite import (
    build_composite,
    build_equal_weighted,
    build_ic_weighted,
    future_returns,
    rolling_spearman_ic_weights,
    row_normalized_weights,
)


def sample_config() -> dict:
    return {
        "factors": {
            "credit_hy": {"weight": 0.6},
            "vix_term_structure": {"weight": 0.4},
        }
    }


def sample_factor_panel(periods: int = 420) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-01", periods=periods)
    stress = np.linspace(-2.0, 2.0, periods)
    vol = np.sin(np.linspace(0.0, 20.0, periods))
    return pd.DataFrame(
        {
            "credit_hy_nonlinear": stress,
            "vix_term_structure_nonlinear": vol,
        },
        index=index,
    )


def test_row_normalized_weights_reweights_available_factors():
    signals = pd.DataFrame(
        {"credit_hy": [1.0, np.nan], "vix_term_structure": [2.0, 3.0]},
        index=pd.bdate_range("2024-01-01", periods=2),
    )
    weights = pd.Series({"credit_hy": 0.6, "vix_term_structure": 0.4})

    result = row_normalized_weights(signals, weights)

    assert result.iloc[0]["credit_hy"] == 0.6
    assert result.iloc[0]["vix_term_structure"] == 0.4
    assert pd.isna(result.iloc[1]["credit_hy"])
    assert result.iloc[1]["vix_term_structure"] == 1.0


def test_equal_weighted_outputs_esi_and_contributions():
    panel = sample_factor_panel()

    esi, contributions = build_equal_weighted(sample_config(), panel)

    assert esi.name == "esi_equal_weighted"
    assert list(contributions.columns) == ["equal_credit_hy", "equal_vix_term_structure"]
    assert pd.notna(esi.dropna().iloc[-1])


def test_future_returns_are_shifted_forward():
    target = pd.Series([100.0, 110.0, 121.0, 133.1], index=pd.bdate_range("2024-01-01", periods=4))

    result = future_returns(target, horizon=2)

    assert np.isclose(result.iloc[0], 0.21)
    assert pd.isna(result.iloc[-1])


def test_ic_weights_start_after_observable_horizon_and_window():
    index = pd.bdate_range("2024-01-01", periods=320)
    signal = pd.Series(np.linspace(-3.0, 3.0, len(index)), index=index)
    target = (100.0 - signal.cumsum()).rename("^GSPC")
    signals = pd.DataFrame({"credit_hy": signal}, index=index)

    weights = rolling_spearman_ic_weights(signals, target, horizon=10, window=100, min_periods=50)

    assert weights.iloc[:60].isna().all().all()
    assert pd.notna(weights["credit_hy"].dropna().iloc[-1])


def test_build_ic_weighted_outputs_weights_and_contributions():
    panel = sample_factor_panel()
    target = (100.0 - panel["credit_hy_nonlinear"].cumsum()).rename("^GSPC")

    esi, contributions, weights = build_ic_weighted(sample_config(), panel, target, ic_window=100, z_window=100)

    assert "ic_credit_hy" in contributions.columns
    assert "ic_weight_credit_hy" in weights.columns
    assert pd.notna(esi.dropna().iloc[-1])


def test_build_composite_includes_both_modes_when_target_is_available():
    panel = sample_factor_panel()
    target = (100.0 - panel["credit_hy_nonlinear"].cumsum()).rename("^GSPC")

    result = build_composite(sample_config(), panel, target)

    assert "esi_equal_weighted" in result.esi.columns
    assert "esi_ic_weighted" in result.esi.columns
    assert not result.equal_contributions.empty
    assert not result.ic_weights.empty

