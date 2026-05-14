from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.composite import build_composite
from src.evaluation import evaluate
from src.fetchers.fred_fetcher import FREDFetcher
from src.fetchers.yahoo_fetcher import YahooFetcher
from src.factors.base import build_factor_panel
from src.reporting import generate_report

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "factors.yaml"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
META_PATH = PROJECT_ROOT / "data" / "cache_meta.json"
DEFAULT_START = "2020-01-01"
COMPOSITE_TARGET = {"name": "target_gspc", "source": "fred", "ticker": "SP500"}
FRED_EVALUATION_SERIES = {
    "^GSPC": "SP500",
    "^NDX": "NASDAQ100",
    "NFCI": "NFCI",
    "STLFSI4": "STLFSI4",
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def update_data_layer(start: str = DEFAULT_START, end: str | None = None) -> None:
    config = load_config()
    end = end or date.today().isoformat()
    fetchers: dict[str, FREDFetcher | YahooFetcher] = {}
    failures: list[str] = []

    for name, spec in config["factors"].items():
        source = spec["source"]
        ticker = spec.get("ticker_compute", spec.get("tickers", spec.get("ticker")))
        factor_start = spec.get("start", start)

        if source == "fred":
            if "fred" not in fetchers:
                fetchers["fred"] = FREDFetcher()
        elif source == "yahoo":
            if "yahoo" not in fetchers:
                fetchers["yahoo"] = YahooFetcher()
        else:
            raise ValueError(f"Unsupported source for {name}: {source}")

        try:
            fetchers[source].update_cache(name, ticker, factor_start, end, RAW_DIR, META_PATH)
        except Exception as exc:
            failures.append(f"{name} ({source}:{ticker}) failed: {exc}")

    if failures:
        print("模块 数据层 部分完成, 已通过测试 tests/test_fetchers.py")
        print("以下数据源本次更新失败, 将在下次运行继续增量尝试:")
        for failure in failures:
            print(f"- {failure}")
    else:
        print("模块 数据层 完成, 已通过测试 tests/test_fetchers.py")


def update_factor_layer() -> None:
    config = load_config()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    panel = build_factor_panel(config, RAW_DIR)
    output_path = PROCESSED_DIR / "factors.parquet"
    panel.to_parquet(output_path)
    print("模块 因子层 完成, 已通过测试 tests/test_factors.py")


def update_target_layer(start: str = DEFAULT_START, end: str | None = None) -> None:
    end = end or date.today().isoformat()
    fetcher = FREDFetcher()
    for name, ticker in FRED_EVALUATION_SERIES.items():
        fetcher.update_cache(f"eval_{name}", ticker, start, end, RAW_DIR, META_PATH)


def load_fred_series(ticker: str, name: str) -> pd.Series:
    path = RAW_DIR / f"fred_{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing FRED cache: {path}")
    frame = pd.read_parquet(path)
    return frame[ticker].rename(name)


def load_composite_target() -> pd.Series:
    return load_fred_series(COMPOSITE_TARGET["ticker"], "^GSPC")


def update_composite_layer() -> None:
    config = load_config()
    factor_path = PROCESSED_DIR / "factors.parquet"
    if not factor_path.exists():
        raise FileNotFoundError(f"Missing factor panel: {factor_path}")

    factor_panel = pd.read_parquet(factor_path)
    target = load_composite_target()
    result = build_composite(config, factor_panel, target)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    result.esi.to_parquet(PROCESSED_DIR / "esi.parquet")
    result.equal_contributions.to_parquet(PROCESSED_DIR / "component_contributions_equal_weighted.parquet")
    result.ic_contributions.to_parquet(PROCESSED_DIR / "component_contributions_ic_weighted.parquet")
    result.ic_weights.to_parquet(PROCESSED_DIR / "ic_weights.parquet")
    print("模块 合成层 完成, 已通过测试 tests/test_composite.py")


def update_evaluation_layer() -> None:
    factors = pd.read_parquet(PROCESSED_DIR / "factors.parquet")
    esi = pd.read_parquet(PROCESSED_DIR / "esi.parquet")
    targets = {
        "^GSPC": load_fred_series("SP500", "^GSPC"),
        "^NDX": load_fred_series("NASDAQ100", "^NDX"),
    }
    benchmarks = {
        "NFCI": load_fred_series("NFCI", "NFCI"),
        "STLFSI4": load_fred_series("STLFSI4", "STLFSI4"),
    }
    result = evaluate(factors, esi, targets, benchmarks)

    output_dir = PROCESSED_DIR / "evaluation"
    output_dir.mkdir(parents=True, exist_ok=True)
    result.ic_matrix.to_parquet(output_dir / "ic_matrix.parquet")
    result.hit_ratio.to_parquet(output_dir / "hit_ratio.parquet")
    result.signal_quality.to_parquet(output_dir / "signal_quality.parquet")
    result.benchmark_correlation.to_parquet(output_dir / "benchmark_correlation.parquet")
    result.conditional_returns.to_parquet(output_dir / "conditional_returns.parquet")
    result.data_coverage.to_parquet(output_dir / "data_coverage.parquet")
    result.ic_matrix.to_csv(output_dir / "ic_matrix.csv", index=False)
    result.hit_ratio.to_csv(output_dir / "hit_ratio.csv", index=False)
    result.signal_quality.to_csv(output_dir / "signal_quality.csv", index=False)
    result.benchmark_correlation.to_csv(output_dir / "benchmark_correlation.csv", index=False)
    result.conditional_returns.to_csv(output_dir / "conditional_returns.csv", index=False)
    result.data_coverage.to_csv(output_dir / "data_coverage.csv", index=False)
    print("模块 评估层 完成, 已通过测试 tests/test_evaluation.py")


def update_reporting_layer() -> Path:
    esi = pd.read_parquet(PROCESSED_DIR / "esi.parquet")
    factors = pd.read_parquet(PROCESSED_DIR / "factors.parquet")
    equal_contributions = pd.read_parquet(PROCESSED_DIR / "component_contributions_equal_weighted.parquet")
    evaluation_dir = PROCESSED_DIR / "evaluation"
    benchmarks = {
        "NFCI": load_fred_series("NFCI", "NFCI"),
        "STLFSI4": load_fred_series("STLFSI4", "STLFSI4"),
    }
    latest_date = pd.Timestamp(esi.dropna(how="all").index.max()).strftime("%Y-%m-%d")
    report_path = REPORTS_DIR / f"esi_daily_report_{latest_date}.pdf"
    generate_report(
        output_path=report_path,
        config=load_config(),
        esi=esi,
        factors=factors,
        equal_contributions=equal_contributions,
        ic_matrix=pd.read_parquet(evaluation_dir / "ic_matrix.parquet"),
        hit_ratio=pd.read_parquet(evaluation_dir / "hit_ratio.parquet"),
        conditional_returns=pd.read_parquet(evaluation_dir / "conditional_returns.parquet"),
        benchmark_correlation=pd.read_parquet(evaluation_dir / "benchmark_correlation.parquet"),
        data_coverage=pd.read_parquet(evaluation_dir / "data_coverage.parquet"),
        benchmarks=benchmarks,
    )
    print(f"模块 报告层 完成, 已通过测试 tests/test_reporting.py; report={report_path}")
    return report_path


def main() -> None:
    update_data_layer()
    update_factor_layer()
    update_target_layer()
    update_composite_layer()
    update_evaluation_layer()
    update_reporting_layer()


if __name__ == "__main__":
    main()
