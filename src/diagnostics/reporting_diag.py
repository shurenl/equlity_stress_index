from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages


def _blank_page(title: str, lines: list[str], pdf: PdfPages) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.text(0.04, 0.94, title, fontsize=18, fontweight="bold", ha="left", va="top")
    ax.text(0.04, 0.86, "\n".join(lines), fontsize=10.5, ha="left", va="top", linespacing=1.55)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _table_page(title: str, frame: pd.DataFrame, pdf: PdfPages, max_rows: int = 26) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.set_title(title, fontsize=15, fontweight="bold", loc="left", pad=18)
    view = frame.head(max_rows).copy()
    for column in view.columns:
        if pd.api.types.is_float_dtype(view[column]):
            view[column] = view[column].map(lambda value: "NA" if pd.isna(value) else f"{value:.3f}")
    table = ax.table(cellText=view.values, colLabels=view.columns, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.25)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _image_page(title: str, image_path: Path, pdf: PdfPages, note: str) -> None:
    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.set_title(title, fontsize=15, fontweight="bold", loc="left", pad=16)
    if image_path.exists():
        image = plt.imread(image_path)
        ax.imshow(image)
    else:
        ax.text(0.5, 0.55, f"Missing image: {image_path}", ha="center", va="center", fontsize=11)
    fig.text(0.04, 0.04, note, fontsize=9, color="#334155")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _horizon_plot_page(horizon_table: pd.DataFrame, target: str, pdf: PdfPages) -> None:
    data = horizon_table[horizon_table["target"] == target]
    fig, ax = plt.subplots(figsize=(11, 8.5))
    for signal, group in data.groupby("signal"):
        group = group.sort_values("horizon")
        ax.plot(group["horizon"], group["ic"], marker="o", linewidth=1.0, markersize=3, label=signal)
    ax.axhline(0, color="#1f2937", linewidth=0.8)
    ax.set_title(f"Horizon IC Scan - {target}", fontsize=15, fontweight="bold", loc="left")
    ax.set_xlabel("Horizon: negative = past return, positive = future return")
    ax.set_ylabel("Spearman IC")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), fontsize=7)
    fig.text(
        0.04,
        0.03,
        "Interpretation: positive horizons test leading power. Negative horizons reveal coincident or lagging behavior.",
        fontsize=9,
        color="#334155",
    )
    fig.tight_layout(rect=(0, 0.05, 0.82, 1))
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _rolling_heatmap_page(rolling_summary: pd.DataFrame, pdf: PdfPages) -> None:
    data = rolling_summary[rolling_summary["target"] == "^GSPC"].copy()
    if data.empty:
        _blank_page("Rolling IC Heatmap", ["No rolling IC data available."], pdf)
        return

    data["label"] = data["signal"] + " +" + data["horizon"].astype(str) + "D"
    pivot = data.pivot_table(index="label", values="mean_ic", aggfunc="mean").sort_values("mean_ic")
    fig, ax = plt.subplots(figsize=(11, 8.5))
    values = pivot["mean_ic"].to_numpy().reshape(-1, 1)
    vmax = max(0.2, float(np.nanmax(np.abs(values))) if np.isfinite(values).any() else 0.2)
    image = ax.imshow(values, aspect="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=8)
    ax.set_xticks([0])
    ax.set_xticklabels(["mean IC"])
    ax.set_title("Rolling IC Mean Heatmap - ^GSPC", fontsize=15, fontweight="bold", loc="left")
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    fig.text(
        0.04,
        0.03,
        "Interpretation: blue/negative values match stress-factor intuition; red/positive values indicate reversed behavior.",
        fontsize=9,
        color="#334155",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _executive_summary(
    classification: pd.DataFrame,
    rolling_summary: pd.DataFrame,
    validation_path: Path,
    credit_chart_path: Path,
) -> list[str]:
    counts = classification["classification"].value_counts().to_dict() if not classification.empty else {}
    reversed_names = sorted(classification.loc[classification["classification"] == "REVERSED", "signal"].unique())
    leading_names = sorted(classification.loc[classification["classification"] == "LEADING", "signal"].unique())
    credit = rolling_summary[
        (rolling_summary["signal"] == "credit_baa_10y")
        & (rolling_summary["target"] == "^GSPC")
        & (rolling_summary["horizon"] == 10)
    ]
    credit_line = "credit_baa_10y rolling IC unavailable."
    if not credit.empty:
        row = credit.iloc[0]
        credit_line = (
            "credit_baa_10y +10D rolling IC: "
            f"mean={row['mean_ic']:.3f}, last_1y={row['last_1y_mean_ic']:.3f}, "
            f"sign consistency={row['expected_sign_consistency']:.1%}."
        )

    return [
        f"Classification counts: {counts}",
        f"Leading candidates: {', '.join(leading_names) if leading_names else 'None'}",
        f"Reversed / needs redesign: {', '.join(reversed_names) if reversed_names else 'None'}",
        credit_line,
        f"Credit substitute validation image: {'available' if validation_path.exists() else 'missing'}",
        f"Credit long-history chart: {'available' if credit_chart_path.exists() else 'missing'}",
        "Recommendation: treat the current ESI as a stress-condition diagnostic until reversed/lagging factors are redesigned.",
    ]


def generate_diagnostics_report(
    horizon_table: pd.DataFrame,
    classification: pd.DataFrame,
    rolling_table: pd.DataFrame,
    rolling_summary: pd.DataFrame,
    output_path: Path,
    validation_path: Path,
    credit_chart_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(output_path) as pdf:
        _blank_page(
            "ESI Diagnostics Executive Summary",
            _executive_summary(classification, rolling_summary, validation_path, credit_chart_path),
            pdf,
        )
        if not classification.empty:
            _table_page("Factor Classification", classification, pdf)
        if not rolling_summary.empty:
            _table_page("Rolling IC Summary", rolling_summary.sort_values(["target", "signal", "horizon"]), pdf)
        for target in sorted(horizon_table["target"].dropna().unique()):
            _horizon_plot_page(horizon_table, target, pdf)
        _rolling_heatmap_page(rolling_summary, pdf)
        _image_page(
            "Credit Substitute Validation",
            validation_path,
            pdf,
            "Interpretation: this page compares Moody's BAA10Y with ICE BofA IG OAS over the overlap window.",
        )
        _image_page(
            "Credit Long-History Rolling IC",
            credit_chart_path,
            pdf,
            "Interpretation: negative rolling IC means higher credit stress precedes weaker SPX +10D returns.",
        )
    return output_path
