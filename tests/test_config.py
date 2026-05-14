from __future__ import annotations

from pathlib import Path

import numpy as np
import yaml

from src.composite import config_weights


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_factor_weights_sum_to_one_and_include_long_credit():
    config = load_yaml(PROJECT_ROOT / "config" / "factors.yaml")
    weights = config_weights(config)

    assert np.isclose(weights.sum(), 1.0)
    assert weights["credit_hy"] == 0.20
    assert weights["credit_ig"] == 0.05
    assert weights["credit_baa_10y"] == 0.15
    assert weights["credit_aaa_10y"] == 0.05
    assert weights["credit_baa_aaa"] == 0.10


def test_diagnostics_expected_signs_cover_all_factors_and_esi_modes():
    factors_config = load_yaml(PROJECT_ROOT / "config" / "factors.yaml")
    diagnostics_config = load_yaml(PROJECT_ROOT / "config" / "diagnostics.yaml")
    expected_signs = diagnostics_config["factor_classification"]["expected_signs"]
    required = set(factors_config["factors"]) | {"esi_equal_weighted", "esi_ic_weighted"}

    assert required <= set(expected_signs)
    assert set(expected_signs.values()) <= {"negative", "positive"}
