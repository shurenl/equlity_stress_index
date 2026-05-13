from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

INTERPRETATIONS = {
    "snapshot": "Higher ESI means tighter or more fragile risk conditions. Regime uses the historical 70th and 90th percentiles.",
    "trend": "This chart shows whether stress is rising or falling versus its own recent distribution. Dashed lines mark elevated and stress thresholds.",
    "composition": "Weights are the configured model weights. Latest contribution shows which components are currently pushing ESI up or down.",
    "component_detail": "Each component chart shows its own z-score trend and latest raw/transformed/nonlinear/contribution values. Nonlinear equals zero when |z| < 0.5 by design.",
    "contributions": "Positive bars add stress; negative bars reduce stress. Missing delayed inputs are excluded from the daily reweighting.",
    "heatmap": "Red cells indicate high positive stress z-scores. Green cells indicate low or easing stress relative to each factor's own history.",
    "ic": "Negative IC means higher stress is followed by lower future returns. Larger absolute t-stat indicates stronger statistical evidence.",
    "hit": "Hit ratio compares drawdown risk during high-ESI regimes with the unconditional sample baseline.",
    "benchmark": "This compares ESI with broad financial condition indexes. Moderate correlation is desired; too high means little independent signal.",
    "coverage": "Coverage diagnostics identify whether each input has enough history for 2020 onward validation.",
}

COMPONENT_MEANINGS = {
    "credit_hy": "High-yield credit spread stress. Rising HY OAS changes are stress-positive.",
    "credit_ig": "Investment-grade credit spread stress. Rising IG OAS changes are stress-positive.",
    "vix_term_structure": "Equity volatility term structure. VIX/VIX3M above normal means near-term fear is elevated.",
    "move": "Rates volatility stress. Rising MOVE indicates unstable Treasury/rates conditions.",
    "dxy": "Broad dollar pressure. Dollar strength can tighten global financial conditions.",
    "skew": "Tail-risk pricing. High SKEW versus its moving average indicates richer crash protection.",
    "breadth_proxy": "Market breadth. Equal-weight underperformance versus cap-weight is stress-positive.",
}


def format_number(value: float | int | None, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "NA"
    value = float(value)
    if abs(value) < 0.5 * 10 ** (-digits):
        value = 0.0
    return f"{value:.{digits}f}"


def add_interpretation(ax, key: str) -> None:
    ax.text(
        0.01,
        -0.12,
        f"Interpretation: {INTERPRETATIONS[key]}",
        transform=ax.transAxes,
        fontsize=9,
        color="#555555",
        va="top",
        wrap=True,
    )


def latest_valid_date(frame: pd.DataFrame) -> pd.Timestamp:
    valid = frame.dropna(how="all")
    if valid.empty:
        raise ValueError("Cannot generate report from an empty frame")
    return pd.Timestamp(valid.index.max())


def regime_for_value(series: pd.Series, value: float) -> str:
    history = series.dropna()
    if history.empty or pd.isna(value):
        return "Unknown"
    q70 = history.quantile(0.70)
    q90 = history.quantile(0.90)
    if value >= q90:
        return "Stress"
    if value >= q70:
        return "Elevated"
    return "Normal"


def rolling_normalize(series: pd.Series, window: int = 252) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window // 2).mean()
    std = series.rolling(window=window, min_periods=window // 2).std().replace(0, np.nan)
    return (series - mean) / std


def add_table_page(pdf: PdfPages, title: str, frame: pd.DataFrame, max_rows: int = 24) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold", pad=16)

    display = frame.head(max_rows).copy()
    for column in display.columns:
        if pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].map(lambda value: format_number(value, digits=4))
    table = ax.table(
        cellText=display.astype(str).values,
        colLabels=display.columns,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.35)
    ax.text(
        0.02,
        0.03,
        f"Interpretation: {INTERPRETATIONS.get('ic' if 'IC' in title else 'coverage' if 'Coverage' in title else 'benchmark')}",
        transform=ax.transAxes,
        fontsize=9,
        color="#555555",
        va="bottom",
        wrap=True,
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_snapshot(pdf: PdfPages, esi: pd.DataFrame) -> None:
    date = latest_valid_date(esi)
    equal = esi["esi_equal_weighted"].dropna()
    ic = esi["esi_ic_weighted"].dropna() if "esi_ic_weighted" in esi else pd.Series(dtype=float)
    current_equal = float(equal.loc[:date].iloc[-1])
    current_ic = float(ic.loc[:date].iloc[-1]) if not ic.empty else np.nan
    change_20d = current_equal - float(equal.loc[:date].iloc[-21]) if len(equal.loc[:date]) > 20 else np.nan
    regime = regime_for_value(equal.loc[:date], current_equal)
    alert = "ON" if regime == "Stress" else "OFF"

    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.text(0.04, 0.90, "ESI Daily Snapshot", fontsize=24, fontweight="bold", transform=ax.transAxes)
    ax.text(0.04, 0.84, f"Report date: {date.date()}", fontsize=12, transform=ax.transAxes)

    rows = [
        ("Equal-weighted ESI", f"{current_equal:.2f}"),
        ("IC-weighted ESI", "NA" if pd.isna(current_ic) else f"{current_ic:.2f}"),
        ("Regime", regime),
        ("20D change", "NA" if pd.isna(change_20d) else f"{change_20d:+.2f}"),
        ("Alert", alert),
    ]
    y = 0.70
    for label, value in rows:
        ax.text(0.08, y, label, fontsize=14, color="#555555", transform=ax.transAxes)
        ax.text(0.44, y, value, fontsize=18, fontweight="bold", transform=ax.transAxes)
        y -= 0.10

    note = "Regime thresholds use historical q70/q90 of equal-weighted ESI."
    ax.text(0.04, 0.10, note, fontsize=10, color="#666666", transform=ax.transAxes)
    ax.text(0.04, 0.06, f"Interpretation: {INTERPRETATIONS['snapshot']}", fontsize=10, color="#555555", transform=ax.transAxes)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_trend(pdf: PdfPages, esi: pd.DataFrame) -> None:
    date = latest_valid_date(esi)
    window = esi.loc[:date].tail(252)
    history = esi["esi_equal_weighted"].loc[:date].dropna()
    q70 = history.quantile(0.70)
    q90 = history.quantile(0.90)

    fig, ax = plt.subplots(figsize=(11, 8.5))
    window["esi_equal_weighted"].plot(ax=ax, lw=2, label="Equal-weighted")
    if "esi_ic_weighted" in window:
        window["esi_ic_weighted"].plot(ax=ax, lw=1.5, label="IC-weighted", alpha=0.8)
    ax.axhline(q70, color="#f0ad4e", ls="--", lw=1, label="q70")
    ax.axhline(q90, color="#d9534f", ls="--", lw=1, label="q90")
    ax.set_title("ESI Trend, Last 252 Business Days", loc="left", fontsize=16, fontweight="bold")
    ax.set_ylabel("z-score")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    add_interpretation(ax, "trend")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_composition(
    pdf: PdfPages,
    config: dict,
    factors: pd.DataFrame,
    contributions: pd.DataFrame,
) -> None:
    date = latest_valid_date(contributions)
    names = list(config["factors"].keys())
    weights = pd.Series({name: float(config["factors"][name]["weight"]) for name in names}, name="weight")
    latest_contrib = contributions.loc[date].rename(lambda value: value.replace("equal_", "")).reindex(names)
    latest_z = pd.Series({name: factors[f"{name}_z_score"].loc[:date].dropna().iloc[-1] if f"{name}_z_score" in factors else np.nan for name in names})
    latest_nonlinear = pd.Series(
        {name: factors[f"{name}_nonlinear"].loc[:date].dropna().iloc[-1] if f"{name}_nonlinear" in factors else np.nan for name in names}
    )
    table_data = pd.DataFrame(
        {
            "weight": weights,
            "latest_z": latest_z,
            "latest_nonlinear": latest_nonlinear,
            "latest_contribution": latest_contrib,
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(11, 8.5), gridspec_kw={"width_ratios": [1.0, 1.35]})
    weights.sort_values().plot(kind="barh", ax=axes[0], color="#4c78a8")
    axes[0].set_title("Configured Weights", loc="left", fontsize=14, fontweight="bold")
    axes[0].set_xlabel("Weight")
    axes[0].grid(True, axis="x", alpha=0.25)

    axes[1].axis("off")
    axes[1].set_title(f"Latest Composition, {date.date()}", loc="left", fontsize=14, fontweight="bold")
    display = table_data.reset_index(names="factor")
    for column in ["weight", "latest_z", "latest_nonlinear", "latest_contribution"]:
        display[column] = display[column].map(format_number)
    table = axes[1].table(
        cellText=display.values,
        colLabels=display.columns,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.28)
    add_interpretation(axes[0], "composition")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def component_latest_row(
    name: str,
    config: dict,
    factors: pd.DataFrame,
    contributions: pd.DataFrame,
    date: pd.Timestamp,
) -> dict[str, float | str]:
    return {
        "weight": float(config["factors"][name]["weight"]),
        "raw": factors[f"{name}_raw"].loc[:date].dropna().iloc[-1] if f"{name}_raw" in factors else np.nan,
        "transformed": factors[f"{name}_transformed"].loc[:date].dropna().iloc[-1] if f"{name}_transformed" in factors else np.nan,
        "z_score": factors[f"{name}_z_score"].loc[:date].dropna().iloc[-1] if f"{name}_z_score" in factors else np.nan,
        "nonlinear": factors[f"{name}_nonlinear"].loc[:date].dropna().iloc[-1] if f"{name}_nonlinear" in factors else np.nan,
        "contribution": contributions[f"equal_{name}"].loc[date] if f"equal_{name}" in contributions else np.nan,
    }


def plot_component_detail_pages(
    pdf: PdfPages,
    config: dict,
    factors: pd.DataFrame,
    contributions: pd.DataFrame,
) -> None:
    date = latest_valid_date(contributions)
    names = list(config["factors"].keys())
    for start in range(0, len(names), 4):
        subset = names[start : start + 4]
        fig, axes = plt.subplots(2, 2, figsize=(11, 8.5))
        axes = axes.flatten()
        for ax, name in zip(axes, subset):
            z_column = f"{name}_z_score"
            if z_column in factors:
                factors[z_column].loc[:date].tail(252).plot(ax=ax, lw=1.6, color="#4c78a8")
            ax.axhline(0, color="#333333", lw=0.8, alpha=0.5)
            ax.axhline(0.5, color="#f0ad4e", lw=0.8, ls="--", alpha=0.8)
            ax.axhline(-0.5, color="#5cb85c", lw=0.8, ls="--", alpha=0.8)
            ax.set_title(name, loc="left", fontsize=12, fontweight="bold")
            ax.set_ylabel("z-score")
            ax.grid(True, alpha=0.22)

            values = component_latest_row(name, config, factors, contributions, date)
            metrics = (
                f"raw {format_number(values['raw'])} | transformed {format_number(values['transformed'])}\n"
                f"z {format_number(values['z_score'])} | nonlinear {format_number(values['nonlinear'])}\n"
                f"weight {format_number(values['weight'])} | contribution {format_number(values['contribution'])}"
            )
            ax.text(
                0.01,
                0.97,
                metrics,
                transform=ax.transAxes,
                fontsize=8,
                va="top",
                ha="left",
                bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#dddddd", "alpha": 0.9},
            )
            ax.text(
                0.01,
                -0.25,
                COMPONENT_MEANINGS.get(name, ""),
                transform=ax.transAxes,
                fontsize=8,
                color="#555555",
                va="top",
                wrap=True,
            )

        for ax in axes[len(subset) :]:
            ax.axis("off")
        fig.suptitle(f"ESI Component Details, {date.date()}", x=0.02, y=0.98, ha="left", fontsize=16, fontweight="bold")
        fig.text(0.02, 0.02, f"Interpretation: {INTERPRETATIONS['component_detail']}", fontsize=9, color="#555555")
        fig.tight_layout(rect=[0, 0.05, 1, 0.95])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


def plot_contributions(pdf: PdfPages, contributions: pd.DataFrame) -> None:
    date = latest_valid_date(contributions)
    latest = contributions.loc[date].sort_values()
    latest.index = latest.index.str.replace("equal_", "", regex=False)

    fig, ax = plt.subplots(figsize=(11, 8.5))
    colors = ["#d9534f" if value > 0 else "#5cb85c" for value in latest]
    latest.plot(kind="barh", ax=ax, color=colors)
    ax.set_title(f"Component Contributions, {date.date()}", loc="left", fontsize=16, fontweight="bold")
    ax.set_xlabel("Contribution to raw ESI")
    ax.grid(True, axis="x", alpha=0.25)
    add_interpretation(ax, "contributions")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(pdf: PdfPages, factors: pd.DataFrame) -> None:
    z = factors.filter(regex=r"_z_score$")
    z = z.rename(columns=lambda value: value.replace("_z_score", "")).tail(60)

    fig, ax = plt.subplots(figsize=(11, 8.5))
    image = ax.imshow(z.T.fillna(0), aspect="auto", cmap="RdYlGn_r", vmin=-3, vmax=3)
    ax.set_title("Factor z-score Heatmap, Last 60 Business Days", loc="left", fontsize=16, fontweight="bold")
    ax.set_yticks(range(len(z.columns)))
    ax.set_yticklabels(z.columns, fontsize=9)
    step = max(1, len(z.index) // 8)
    ticks = list(range(0, len(z.index), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([z.index[i].strftime("%Y-%m-%d") for i in ticks], rotation=45, ha="right", fontsize=8)
    fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    add_interpretation(ax, "heatmap")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_hit_and_distribution(pdf: PdfPages, hit_ratio: pd.DataFrame, conditional_returns: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 8.5))
    pivot = hit_ratio.pivot(index="esi_quantile", columns="drawdown_threshold", values="hit_ratio")
    pivot.plot(kind="bar", ax=axes[0])
    axes[0].set_title("Hit Ratio", loc="left", fontsize=14, fontweight="bold")
    axes[0].set_ylabel("Probability")
    axes[0].grid(True, axis="y", alpha=0.25)
    axes[0].legend(title="Drawdown")
    add_interpretation(axes[0], "hit")

    dist = conditional_returns.copy()
    axes[1].bar(dist["esi_percentile_bucket"].astype(str), dist["mean"])
    axes[1].set_title("Conditional 10D Return Mean", loc="left", fontsize=14, fontweight="bold")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].grid(True, axis="y", alpha=0.25)
    axes[1].text(
        0.01,
        -0.22,
        "Interpretation: More negative bars in high-percentile buckets imply stress is followed by weaker returns.",
        transform=axes[1].transAxes,
        fontsize=9,
        color="#555555",
        va="top",
        wrap=True,
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def plot_benchmark_comparison(pdf: PdfPages, esi: pd.DataFrame, benchmarks: dict[str, pd.Series]) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    rolling_normalize(esi["esi_equal_weighted"]).tail(504).plot(ax=ax, lw=2, label="ESI")
    for name, series in benchmarks.items():
        rolling_normalize(series).reindex(esi.index).tail(504).plot(ax=ax, lw=1.5, label=name, alpha=0.85)
    ax.set_title("ESI vs Financial Conditions Benchmarks", loc="left", fontsize=16, fontweight="bold")
    ax.set_ylabel("Rolling z-score")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="upper left")
    add_interpretation(ax, "benchmark")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def generate_report(
    output_path: Path,
    config: dict,
    esi: pd.DataFrame,
    factors: pd.DataFrame,
    equal_contributions: pd.DataFrame,
    ic_matrix: pd.DataFrame,
    hit_ratio: pd.DataFrame,
    conditional_returns: pd.DataFrame,
    benchmark_correlation: pd.DataFrame,
    data_coverage: pd.DataFrame,
    benchmarks: dict[str, pd.Series],
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output_path) as pdf:
        plot_snapshot(pdf, esi)
        plot_trend(pdf, esi)
        plot_composition(pdf, config, factors, equal_contributions)
        plot_component_detail_pages(pdf, config, factors, equal_contributions)
        plot_contributions(pdf, equal_contributions)
        plot_heatmap(pdf, factors)

        ic_display = ic_matrix.sort_values(["target", "horizon", "signal"])
        add_table_page(pdf, "IC Matrix", ic_display)
        plot_hit_and_distribution(pdf, hit_ratio, conditional_returns)
        plot_benchmark_comparison(pdf, esi, benchmarks)
        add_table_page(pdf, "Benchmark Correlation", benchmark_correlation)
        add_table_page(pdf, "Data Coverage Diagnostics", data_coverage, max_rows=40)

    return output_path
