# Equity Stress Index (ESI) v1

ESI is a daily Equity Stress Index for monitoring short-horizon downside stress in US equities. The project produces a daily ESI PDF report plus a separate diagnostics report for factor lead/lag and IC stability analysis.

For detailed handoff notes, architecture, module status, and known limitations, see `read.md`.

## Environment

Use Python 3.11+:

```bash
/Users/linshuren/.local/bin/python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## FRED API key

FRED data requires an API key. Create one from the FRED website, then export it before running the daily update:

```bash
export FRED_API_KEY="your_key_here"
```

`.env.example` is only a template. Do not commit real keys.

## Run daily ESI

```bash
python run_daily.py
```

The daily pipeline reads `config/factors.yaml`, incrementally updates raw parquet caches under `data/raw/`, calculates factors, builds equal-weighted and IC-weighted ESI, evaluates predictive statistics, and writes `reports/esi_daily_report_YYYY-MM-DD.pdf`.
If Yahoo Finance is temporarily rate limited, the fetcher uses public fallback sources where available:
CBOE historical CSVs for VIX/VIX3M/SKEW and Convex Trade's CC BY 4.0 MOVE Index CSV for MOVE.
The breadth proxy uses FRED's Nasdaq S&P 500 equal-weighted and market-cap-weighted large-cap indexes to avoid Yahoo ETF rate limits while preserving the equal-weight/cap-weight signal.

## Credit long-history upgrade

The factor config now includes Moody's long-history credit spread proxies:

- `credit_baa_10y`: FRED `BAA10Y`, Moody's Baa - 10Y Treasury spread.
- `credit_aaa_10y`: FRED `AAA10Y`, Moody's Aaa - 10Y Treasury spread.
- `credit_baa_aaa`: computed `BAA10Y - AAA10Y`, pure Baa-vs-Aaa credit premium.

These series provide longer credit history than the ICE BofA OAS series currently available from FRED. Moody's spread levels are not directly comparable to ICE BofA OAS levels because of duration/composition differences; use z-scores and changes for ESI diagnostics.

Current configured weights sum to 1.0 and are read directly by the composite layer from `config/factors.yaml`:

- ICE BofA short-history credit: `credit_hy` 0.20, `credit_ig` 0.05.
- Moody's long-history credit: `credit_baa_10y` 0.15, `credit_aaa_10y` 0.05, `credit_baa_aaa` 0.10.
- Other stress factors: `vix_term_structure` 0.15, `move` 0.10, `dxy` 0.10, `skew` 0.05, `breadth_proxy` 0.05.

## Diagnostics

The diagnostics module is separate from the daily production report. It is used to diagnose whether each factor is leading, coincident, lagging, reversed, or noise.

```bash
.venv/bin/python -m src.diagnostics.run_diagnostics
.venv/bin/python -m src.diagnostics.run_diagnostics --no-pdf
.venv/bin/python -m src.diagnostics.run_diagnostics --factor credit_baa_10y --no-pdf
.venv/bin/python -m src.diagnostics.run_diagnostics --long-history-only --no-pdf
.venv/bin/python -m src.diagnostics.run_diagnostics --rolling-credit-demo --no-pdf
```

Main outputs:

- `data/diagnostics/horizon_ic_matrix.parquet`
- `data/diagnostics/horizon_classification.parquet`
- `data/diagnostics/rolling_ic_all.parquet`
- `data/diagnostics/rolling_ic_summary.parquet`
- `data/diagnostics/credit_substitute_validation.png`
- `data/diagnostics/credit_long_history_ic_analysis.png`
- `reports/diagnostics/esi_diagnostics_YYYY-MM-DD.pdf`

Important: the long-history credit rolling IC page needs long-history `SP500` cache. If `FRED_API_KEY` is exported, the diagnostics entrypoint will update `SP500` from FRED as needed. Without it, diagnostics falls back to the local cache and may only cover the existing shorter window.

If FRED `SP500` does not provide enough history, place a local target CSV at:

```text
data/local_targets/GSPC.csv
```

Accepted columns are `date,close`, `Date,Close`, `date,adj close`, or `date,value`. Diagnostics prefers this local CSV over the FRED cache for `^GSPC`, so a 1990-present SPX close file will unlock the intended long-history rolling IC analysis. Local target CSVs are ignored by git.

## GitHub Actions

The repository includes `.github/workflows/daily-esi-report.yml`.

- Schedule: daily at 08:30 Asia/Shanghai (`00:30 UTC`).
- Manual trigger: GitHub Actions -> Daily ESI Report -> Run workflow.
- JavaScript actions use Node.js 24-compatible versions: `actions/checkout@v5`, `actions/setup-python@v6`, and `actions/upload-artifact@v7`.
- Required repository secret: `FRED_API_KEY`.
- Required Gmail secrets for email delivery: `GMAIL_USERNAME` and `GMAIL_APP_PASSWORD`.
- Optional recipient secret: `REPORT_EMAIL_TO`. If omitted, the report is sent to `GMAIL_USERNAME`.
- Outputs: the daily ESI PDF and diagnostics PDF are emailed together by Gmail SMTP, and also saved under the `esi-pdf-reports` artifact. Evaluation CSVs are saved under the `esi-evaluation-tables` artifact; diagnostics parquet tables are saved under `esi-diagnostics-tables`.
- The workflow downloads local SPX history via `scripts/update_local_gspc.py` before diagnostics so `credit_baa_10y` rolling IC can use 1990-present SPX history.
- The workflow sets `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` and uses `actions/upload-artifact@v7` to avoid Node.js 20 action deprecation warnings.

For Gmail delivery, create a Google App Password and store it as `GMAIL_APP_PASSWORD`. Do not use or commit your normal Gmail password.

If a workflow fails with only `Process completed with exit code 1`, expand the failed step logs. The workflow checks `FRED_API_KEY`, `GMAIL_USERNAME`, and `GMAIL_APP_PASSWORD` before running the pipeline so missing secrets should be reported explicitly.

## Tests

```bash
.venv/bin/python -m pytest
```

## Current modules

- Data layer: implemented and cached under `data/raw/`.
- Factor layer: implemented and cached under `data/processed/factors.parquet`.
- Composite layer: implemented for `equal_weighted` and `ic_weighted` under `data/processed/esi.parquet`.
- Evaluation layer: implemented under `data/processed/evaluation/`.
- Reporting layer: implemented under `reports/`.
- Diagnostics layer: implemented under `src/diagnostics/`, with outputs under `data/diagnostics/` and `reports/diagnostics/`.

Note: as of May 2026, FRED's public `BAMLH0A0HYM2` and `BAMLC0A0CM` history starts in 2023 in this environment. The evaluation layer writes `data_coverage.csv` to make this visible. A separate historical backfill source is needed before validating 2020-03 and 2022-Q2 credit behavior.
