from __future__ import annotations

import numpy as np
import pandas as pd

from src.reporting import format_number, generate_report, regime_for_value


def test_regime_for_value_uses_q70_q90_thresholds():
    series = pd.Series(range(100), dtype=float)

    assert regime_for_value(series, 95.0) == "Stress"
    assert regime_for_value(series, 75.0) == "Elevated"
    assert regime_for_value(series, 20.0) == "Normal"


def test_format_number_handles_negative_zero_and_na():
    assert format_number(-0.0) == "0.000"
    assert format_number(-0.00001) == "0.000"
    assert format_number(np.nan) == "NA"


def test_generate_report_creates_nonempty_pdf(tmp_path):
    index = pd.bdate_range("2024-01-01", periods=260)
    factors = ["credit_hy", "credit_ig", "vix_term_structure", "move", "dxy", "skew", "breadth_proxy"]
    config = {"factors": {factor: {"weight": 1 / len(factors)} for factor in factors}}
    esi = pd.DataFrame(
        {
            "esi_equal_weighted": np.sin(np.linspace(0, 8, len(index))),
            "esi_ic_weighted": np.cos(np.linspace(0, 8, len(index))),
        },
        index=index,
    )
    factor_frame = pd.DataFrame(index=index)
    contributions = pd.DataFrame(index=index)
    for offset, factor in enumerate(factors):
        factor_frame[f"{factor}_z_score"] = np.sin(np.linspace(0, 5, len(index)) + offset)
        factor_frame[f"{factor}_nonlinear"] = np.cos(np.linspace(0, 5, len(index)) + offset)
        contributions[f"equal_{factor}"] = np.cos(np.linspace(0, 5, len(index)) + offset) / 10

    ic_matrix = pd.DataFrame(
        {
            "signal": ["credit_hy", "esi_equal_weighted"],
            "target": ["^GSPC", "^GSPC"],
            "horizon": [10, 10],
            "ic": [-0.1, -0.2],
            "t_stat": [-2.1, -3.0],
            "p_value": [0.03, 0.01],
            "n": [200, 200],
        }
    )
    hit_ratio = pd.DataFrame(
        {
            "esi_quantile": [0.85, 0.90],
            "drawdown_threshold": [0.03, 0.03],
            "hit_ratio": [0.2, 0.3],
            "full_sample_rate": [0.1, 0.1],
            "n": [50, 30],
        }
    )
    conditional_returns = pd.DataFrame(
        {
            "esi_percentile_bucket": ["(-0.001, 0.7]", "(0.7, 0.85]"],
            "count": [100, 20],
            "mean": [0.01, -0.02],
            "median": [0.01, -0.01],
            "std": [0.02, 0.03],
        }
    )
    benchmark_correlation = pd.DataFrame({"benchmark": ["NFCI"], "correlation": [0.4], "n": [200]})
    data_coverage = pd.DataFrame(
        {
            "series": ["credit_hy_raw"],
            "first_valid": [pd.Timestamp("2024-01-01")],
            "last_valid": [pd.Timestamp("2024-12-31")],
            "non_null_count": [260],
            "covers_required_start": [True],
        }
    )
    benchmarks = {
        "NFCI": pd.Series(np.sin(np.linspace(0, 8, len(index))), index=index),
        "STLFSI4": pd.Series(np.cos(np.linspace(0, 8, len(index))), index=index),
    }

    output = generate_report(
        output_path=tmp_path / "report.pdf",
        config=config,
        esi=esi,
        factors=factor_frame,
        equal_contributions=contributions,
        ic_matrix=ic_matrix,
        hit_ratio=hit_ratio,
        conditional_returns=conditional_returns,
        benchmark_correlation=benchmark_correlation,
        data_coverage=data_coverage,
        benchmarks=benchmarks,
    )

    assert output.exists()
    assert output.stat().st_size > 10_000
