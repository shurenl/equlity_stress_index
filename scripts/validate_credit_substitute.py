from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "data" / "diagnostics"


def rolling_z_score(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window // 2).mean()
    std = series.rolling(window=window, min_periods=window // 2).std().replace(0, pd.NA)
    return (series - mean) / std


def load_series(path: Path, column: str) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(f"Missing required cache: {path}")
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return pd.to_numeric(frame[column], errors="coerce").rename(column)


def validate_credit_substitute(
    start: str = "2023-05-15",
    end: str | None = None,
    min_corr: float = 0.80,
    warn_only: bool = False,
) -> dict[str, float]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    baa = load_series(RAW_DIR / "fred_BAA10Y.parquet", "BAA10Y")
    ice = load_series(RAW_DIR / "fred_BAMLC0A0CM.parquet", "BAMLC0A0CM")
    data = pd.concat({"BAA10Y": baa, "BAMLC0A0CM": ice}, axis=1).loc[start:end].dropna()
    if data.empty:
        raise ValueError("No overlapping observations between BAA10Y and BAMLC0A0CM")

    changes = data.diff(5).dropna()
    change_corr = float(changes["BAA10Y"].corr(changes["BAMLC0A0CM"]))

    z_changes = pd.concat(
        {
            "BAA10Y": rolling_z_score(changes["BAA10Y"]),
            "BAMLC0A0CM": rolling_z_score(changes["BAMLC0A0CM"]),
        },
        axis=1,
    ).dropna()
    z_change_corr = float(z_changes["BAA10Y"].corr(z_changes["BAMLC0A0CM"])) if not z_changes.empty else float("nan")

    z_levels = pd.concat(
        {
            "BAA10Y": rolling_z_score(data["BAA10Y"]),
            "BAMLC0A0CM": rolling_z_score(data["BAMLC0A0CM"]),
        },
        axis=1,
    ).dropna()
    z_level_corr = float(z_levels["BAA10Y"].corr(z_levels["BAMLC0A0CM"])) if not z_levels.empty else float("nan")

    output_path = OUTPUT_DIR / "credit_substitute_validation.png"
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    data.plot(ax=axes[0, 0], lw=1.4)
    axes[0, 0].set_title("Raw levels, overlap period", loc="left", fontweight="bold")
    axes[0, 0].set_ylabel("percentage points")
    axes[0, 0].grid(True, alpha=0.25)

    changes.plot(ax=axes[0, 1], lw=1.2)
    axes[0, 1].set_title(f"5D changes, Pearson r={change_corr:.3f}", loc="left", fontweight="bold")
    axes[0, 1].grid(True, alpha=0.25)

    axes[1, 0].scatter(changes["BAA10Y"], changes["BAMLC0A0CM"], s=14, alpha=0.55)
    axes[1, 0].set_title("5D change scatter", loc="left", fontweight="bold")
    axes[1, 0].set_xlabel("BAA10Y 5D change")
    axes[1, 0].set_ylabel("BAMLC0A0CM 5D change")
    axes[1, 0].grid(True, alpha=0.25)

    z_changes.plot(ax=axes[1, 1], lw=1.2)
    axes[1, 1].set_title(f"252D z-score of 5D changes, r={z_change_corr:.3f}", loc="left", fontweight="bold")
    axes[1, 1].grid(True, alpha=0.25)

    fig.suptitle("Credit Substitute Validation: Moody's BAA10Y vs ICE BofA BAMLC0A0CM", x=0.02, ha="left", fontsize=15)
    fig.text(
        0.02,
        0.02,
        "Note: Moody's 20+yr duration spread levels are not directly comparable to ICE BofA OAS levels; validation focuses on changes and z-scores.",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.95])
    fig.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close(fig)

    results = {
        "overlap_start": data.index.min().strftime("%Y-%m-%d"),
        "overlap_end": data.index.max().strftime("%Y-%m-%d"),
        "overlap_obs": float(len(data)),
        "change_5d_corr": change_corr,
        "z_change_5d_corr": z_change_corr,
        "z_level_corr": z_level_corr,
        "min_required_corr": min_corr,
        "passed": bool(change_corr >= min_corr and z_change_corr >= min_corr),
    }

    print("Credit substitute validation")
    for key, value in results.items():
        print(f"{key}: {value}")
    print(f"chart: {output_path}")

    if not results["passed"] and not warn_only:
        raise SystemExit(
            "Validation failed: 5D change and/or 5D-change z-score correlation is below "
            f"{min_corr:.2f}. Stop before Step 3 and review substitute assumption."
        )
    if not results["passed"]:
        print(
            "Warning: credit substitute validation is below threshold; "
            "chart was still generated for diagnostics reporting."
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Moody's BAA10Y as an ICE BofA credit substitute.")
    parser.add_argument("--start", default="2023-05-15")
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-corr", type=float, default=0.80)
    parser.add_argument("--warn-only", action="store_true", help="Generate the chart and warn instead of exiting nonzero.")
    args = parser.parse_args()
    validate_credit_substitute(start=args.start, end=args.end, min_corr=args.min_corr, warn_only=args.warn_only)


if __name__ == "__main__":
    main()
