from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import yaml

from src.composite import build_composite
from src.diagnostics.horizon_scan import classification_summary, scan_horizons
from src.diagnostics.reporting_diag import generate_diagnostics_report
from src.diagnostics.rolling_ic import rolling_ic_batch, rolling_ic_diagnostics, rolling_ic_series
from src.diagnostics.target_loader import load_target_series
from src.factors.base import build_factor_panel
from src.fetchers.fred_fetcher import FREDFetcher
from scripts.validate_credit_substitute import validate_credit_substitute


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FACTORS_CONFIG = PROJECT_ROOT / "config" / "factors.yaml"
DIAGNOSTICS_CONFIG = PROJECT_ROOT / "config" / "diagnostics.yaml"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
LOCAL_TARGET_DIR = PROJECT_ROOT / "data" / "local_targets"
META_PATH = PROJECT_ROOT / "data" / "cache_meta.json"


def ensure_credit_validation_chart() -> None:
    try:
        validate_credit_substitute(warn_only=True)
    except Exception as exc:
        print(f"Warning: could not generate credit substitute validation chart: {exc}")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_fred_series(ticker: str, name: str) -> pd.Series:
    path = RAW_DIR / f"fred_{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing required target cache: {path}")
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame[ticker].rename(name)


def ensure_fred_cache(name: str, ticker: str, start: str, end: str) -> None:
    path = RAW_DIR / f"fred_{ticker}.parquet"
    needs_fetch = True
    if path.exists():
        frame = pd.read_parquet(path)
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        clean = frame.iloc[:, 0].dropna()
        needs_fetch = clean.empty or clean.index.min() > pd.Timestamp(start)

    if not needs_fetch:
        return

    if not os.environ.get("FRED_API_KEY"):
        print(f"Warning: {ticker} long-history cache needs FRED_API_KEY; using existing local cache if available.")
        return

    FREDFetcher().update_cache(name, ticker, start, end, RAW_DIR, META_PATH)


def load_targets(target_names: list[str]) -> dict[str, pd.Series]:
    targets = {}
    for name in target_names:
        try:
            targets[name] = load_target_series(name, RAW_DIR, LOCAL_TARGET_DIR)
        except FileNotFoundError as exc:
            print(f"Skipping target {name}: {exc}")
            continue
    return targets


def build_signals(
    factors_config: dict[str, Any],
    factor_filter: str | None = None,
    factor_allowlist: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors_path = PROCESSED_DIR / "factors.parquet"
    esi_path = PROCESSED_DIR / "esi.parquet"
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if factors_path.exists():
        factors = pd.read_parquet(factors_path)
        factors.index = pd.to_datetime(factors.index).tz_localize(None).normalize()
    else:
        factors = build_factor_panel(factors_config, RAW_DIR)
        factors.to_parquet(factors_path)

    expected_factor_columns = [f"{name}_nonlinear" for name in factors_config["factors"]]
    if any(column not in factors.columns for column in expected_factor_columns):
        factors = build_factor_panel(factors_config, RAW_DIR)
        factors.to_parquet(factors_path)

    if esi_path.exists():
        esi = pd.read_parquet(esi_path)
        esi.index = pd.to_datetime(esi.index).tz_localize(None).normalize()
    else:
        target = load_fred_series("SP500", "^GSPC")
        composite = build_composite(factors_config, factors, target)
        esi = composite.esi
        esi.to_parquet(esi_path)

    factor_signals = factors.filter(regex=r"_nonlinear$").rename(columns=lambda value: value.replace("_nonlinear", ""))
    if factor_filter:
        if factor_filter not in factor_signals.columns:
            raise ValueError(f"Unknown factor for diagnostics: {factor_filter}")
        factor_signals = factor_signals[[factor_filter]]
    elif factor_allowlist:
        available = [name for name in factor_allowlist if name in factor_signals.columns]
        missing = sorted(set(factor_allowlist) - set(available))
        if missing:
            print(f"Skipping missing long-history factor(s): {missing}")
        factor_signals = factor_signals[available]

    include_esi = not factor_filter and not factor_allowlist
    if include_esi:
        signals = pd.concat(
            [esi[["esi_equal_weighted"]], esi[[col for col in esi.columns if col != "esi_equal_weighted"]], factor_signals],
            axis=1,
        )
    else:
        signals = factor_signals
    return signals, factors


def run_horizon_scan(factor_filter: str | None = None, long_history_only: bool = False) -> pd.DataFrame:
    factors_config = load_yaml(FACTORS_CONFIG)
    diagnostics_config = load_yaml(DIAGNOSTICS_CONFIG)
    scan_config = diagnostics_config["horizon_scan"]
    class_config = diagnostics_config["factor_classification"]
    output_dir = PROJECT_ROOT / diagnostics_config["output"]["cache_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    allowlist = diagnostics_config["rolling_ic"]["long_history_factors"] if long_history_only and not factor_filter else None
    signals, _ = build_signals(factors_config, factor_filter=factor_filter, factor_allowlist=allowlist)
    targets = load_targets(diagnostics_config["targets"])
    table = scan_horizons(
        signals=signals,
        targets=targets,
        horizons=scan_config["horizons"],
        expected_signs=class_config["expected_signs"],
        min_obs=int(scan_config["min_obs"]),
        leading_t_threshold=float(class_config["leading_t_threshold"]),
        lagging_t_threshold=float(class_config["lagging_t_threshold"]),
        noise_t_threshold=float(class_config["noise_t_threshold"]),
    )
    table.to_parquet(output_dir / "horizon_ic_matrix.parquet")
    summary = classification_summary(table)
    summary.to_parquet(output_dir / "horizon_classification.parquet")

    print("\nHorizon IC summary")
    print(summary.to_string(index=False, max_rows=80))
    print("\nHorizon IC table, strongest rows by |t-stat|")
    strongest = table.dropna(subset=["t_stat"]).assign(abs_t=lambda df: df["t_stat"].abs()).sort_values("abs_t", ascending=False)
    print(strongest.head(40).drop(columns=["abs_t"]).to_string(index=False))
    print(f"\nSaved: {output_dir / 'horizon_ic_matrix.parquet'}")
    print(f"Saved: {output_dir / 'horizon_classification.parquet'}")
    return table


def plot_credit_long_history_ic(
    rolling: pd.DataFrame,
    target: pd.Series,
    events: list[dict[str, str]],
    output_path: Path,
) -> None:
    plot_data = rolling.dropna(subset=["rolling_ic"])
    target = target.reindex(plot_data.index).ffill()
    normalized_target = target / target.dropna().iloc[0]

    fig, ax_ic = plt.subplots(figsize=(14, 7))
    ax_ic.plot(plot_data.index, plot_data["rolling_ic"], color="#0f766e", linewidth=1.3, label="126D rolling IC (+10D)")
    ax_ic.axhline(0, color="#444444", linewidth=0.8)
    ax_ic.axhline(-0.2, color="#0f766e", linewidth=0.8, linestyle="--", alpha=0.5)
    ax_ic.axhline(0.2, color="#b91c1c", linewidth=0.8, linestyle="--", alpha=0.5)
    ax_ic.set_ylabel("Rolling Spearman IC")
    ax_ic.set_title("credit_baa_10y vs SPX +10D Return: Rolling IC, no look-ahead")
    ax_ic.grid(True, axis="y", alpha=0.25)

    ax_spx = ax_ic.twinx()
    ax_spx.plot(normalized_target.index, normalized_target, color="#334155", linewidth=1.0, alpha=0.45, label="SPX normalized")
    ax_spx.set_yscale("log")
    ax_spx.set_ylabel("SPX normalized, log scale")

    for item in events:
        event_date = pd.Timestamp(item["date"])
        if plot_data.index.min() <= event_date <= plot_data.index.max():
            ax_ic.axvline(event_date, color="#7c2d12", linewidth=0.8, linestyle=":", alpha=0.7)
            ax_ic.text(
                event_date,
                0.97,
                item["label"],
                transform=ax_ic.get_xaxis_transform(),
                rotation=90,
                va="top",
                ha="right",
                fontsize=8,
                color="#7c2d12",
            )

    ax_ic.xaxis.set_major_locator(mdates.YearLocator(4))
    ax_ic.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    lines, labels = ax_ic.get_legend_handles_labels()
    lines_2, labels_2 = ax_spx.get_legend_handles_labels()
    ax_ic.legend(lines + lines_2, labels + labels_2, loc="lower left")
    fig.text(
        0.01,
        0.01,
        "Interpretation: negative rolling IC means higher credit stress tends to precede weaker +10D SPX returns. "
        "Each date only uses samples ending at t-10-1, so future data is excluded.",
        fontsize=9,
        color="#334155",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def run_credit_baa_10y_rolling_demo() -> tuple[pd.DataFrame, pd.DataFrame]:
    factors_config = load_yaml(FACTORS_CONFIG)
    diagnostics_config = load_yaml(DIAGNOSTICS_CONFIG)
    rolling_config = diagnostics_config["rolling_ic"]
    output_dir = PROJECT_ROOT / diagnostics_config["output"]["cache_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    end = pd.Timestamp.today().normalize().strftime("%Y-%m-%d")
    if not (LOCAL_TARGET_DIR / "GSPC.csv").exists():
        ensure_fred_cache("target_sp500_long_history", "SP500", "1990-01-01", end)

    signals, _ = build_signals(factors_config, factor_filter="credit_baa_10y")
    signal = signals["credit_baa_10y"].loc["1990-01-01":]
    target = load_target_series("^GSPC", RAW_DIR, LOCAL_TARGET_DIR).loc["1990-01-01":]
    rolling = rolling_ic_series(
        signal=signal,
        target_price=target,
        horizon=10,
        window=int(rolling_config["window"]),
        min_window_obs=int(rolling_config["min_window_obs"]),
    )
    diagnostics = rolling_ic_diagnostics(rolling, expected_sign="negative")

    rolling_path = output_dir / "rolling_ic_credit_baa_10y_GSPC.parquet"
    diagnostics_path = output_dir / "rolling_ic_credit_baa_10y_GSPC_summary.parquet"
    chart_path = output_dir / "credit_long_history_ic_analysis.png"
    rolling.to_parquet(rolling_path)
    diagnostics.to_parquet(diagnostics_path)
    plot_credit_long_history_ic(rolling, target, diagnostics_config["historical_events"], chart_path)

    print("\nCredit BAA10Y rolling IC diagnostics")
    print(diagnostics.to_string(index=False))
    print(f"\nSaved: {rolling_path}")
    print(f"Saved: {diagnostics_path}")
    print(f"Saved: {chart_path}")
    return rolling, diagnostics


def run_full_rolling_ic(signals: pd.DataFrame, targets: dict[str, pd.Series]) -> tuple[pd.DataFrame, pd.DataFrame]:
    diagnostics_config = load_yaml(DIAGNOSTICS_CONFIG)
    rolling_config = diagnostics_config["rolling_ic"]
    class_config = diagnostics_config["factor_classification"]
    output_dir = PROJECT_ROOT / diagnostics_config["output"]["cache_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    rolling, summary = rolling_ic_batch(
        signals=signals,
        targets=targets,
        horizons=rolling_config["horizons"],
        expected_signs=class_config["expected_signs"],
        window=int(rolling_config["window"]),
        min_window_obs=int(rolling_config["min_window_obs"]),
    )
    rolling_path = output_dir / "rolling_ic_all.parquet"
    summary_path = output_dir / "rolling_ic_summary.parquet"
    rolling.to_parquet(rolling_path)
    summary.to_parquet(summary_path)
    print(f"\nSaved: {rolling_path}")
    print(f"Saved: {summary_path}")
    print("\nRolling IC summary")
    print(summary.to_string(index=False, max_rows=80))
    return rolling, summary


def run_full_diagnostics(no_pdf: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    factors_config = load_yaml(FACTORS_CONFIG)
    diagnostics_config = load_yaml(DIAGNOSTICS_CONFIG)
    output_dir = PROJECT_ROOT / diagnostics_config["output"]["cache_dir"]
    report_dir = PROJECT_ROOT / diagnostics_config["output"]["report_dir"]
    scan_config = diagnostics_config["horizon_scan"]
    class_config = diagnostics_config["factor_classification"]

    signals, _ = build_signals(factors_config)
    targets = load_targets(diagnostics_config["targets"])

    horizon = scan_horizons(
        signals=signals,
        targets=targets,
        horizons=scan_config["horizons"],
        expected_signs=class_config["expected_signs"],
        min_obs=int(scan_config["min_obs"]),
        leading_t_threshold=float(class_config["leading_t_threshold"]),
        lagging_t_threshold=float(class_config["lagging_t_threshold"]),
        noise_t_threshold=float(class_config["noise_t_threshold"]),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    horizon.to_parquet(output_dir / "horizon_ic_matrix.parquet")
    classification = classification_summary(horizon)
    classification.to_parquet(output_dir / "horizon_classification.parquet")
    print("\nHorizon IC summary")
    print(classification.to_string(index=False, max_rows=80))

    rolling, rolling_summary = run_full_rolling_ic(signals, targets)
    run_credit_baa_10y_rolling_demo()
    ensure_credit_validation_chart()

    if not no_pdf:
        today = pd.Timestamp.today().strftime("%Y-%m-%d")
        report_path = report_dir / f"esi_diagnostics_{today}.pdf"
        generate_diagnostics_report(
            horizon_table=horizon,
            classification=classification,
            rolling_table=rolling,
            rolling_summary=rolling_summary,
            output_path=report_path,
            validation_path=output_dir / "credit_substitute_validation.png",
            credit_chart_path=output_dir / "credit_long_history_ic_analysis.png",
        )
        print(f"\nSaved: {report_path}")

    return horizon, rolling_summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ESI diagnostics.")
    parser.add_argument("--factor", default=None, help="Optional single factor name to diagnose.")
    parser.add_argument("--long-history-only", action="store_true", help="Run only Moody's long-history factors.")
    parser.add_argument("--no-pdf", action="store_true", help="Run diagnostics data calculations without generating PDF.")
    parser.add_argument(
        "--rolling-credit-demo",
        action="store_true",
        help="Step 4: run credit_baa_10y x ^GSPC x +10D rolling IC only.",
    )
    args = parser.parse_args()

    if args.rolling_credit_demo:
        rolling, diagnostics = run_credit_baa_10y_rolling_demo()
        mean_ic = diagnostics["mean_ic"].iloc[0] if not diagnostics.empty else float("nan")
        print(
            "\nStep 4 完成, 关键发现: "
            f"credit_baa_10y +10D rolling IC generated {rolling['rolling_ic'].notna().sum()} valid windows; "
            f"mean IC={mean_ic:.3f}."
        )
        return

    if args.factor or args.long_history_only:
        table = run_horizon_scan(factor_filter=args.factor, long_history_only=args.long_history_only)
        print(f"\nStep 3 完成, 关键发现: horizon scan generated {len(table)} rows. Review classifications before Step 4.")
        return

    horizon, rolling_summary = run_full_diagnostics(no_pdf=args.no_pdf)
    print(
        "\nStep 5 完成, 关键发现: "
        f"horizon rows={len(horizon)}, rolling summary rows={len(rolling_summary)}. "
        "Diagnostics PDF generated unless --no-pdf was set."
    )


if __name__ == "__main__":
    main()
