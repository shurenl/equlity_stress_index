# Equity Stress Index (ESI) v1

ESI is a daily Equity Stress Index for monitoring short-horizon downside stress in US equities. This first milestone initializes the project and implements the data layer only.

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

## Run data update

```bash
python run_daily.py
```

The data layer reads `config/factors.yaml`, incrementally updates raw parquet caches under `data/raw/`, and records cache metadata in `data/cache_meta.json`.
If Yahoo Finance is temporarily rate limited, the fetcher uses public fallback sources where available:
CBOE historical CSVs for VIX/VIX3M/SKEW and Convex Trade's CC BY 4.0 MOVE Index CSV for MOVE.
The breadth proxy uses FRED's Nasdaq S&P 500 equal-weighted and market-cap-weighted large-cap indexes to avoid Yahoo ETF rate limits while preserving the equal-weight/cap-weight signal.

## GitHub Actions

The repository includes `.github/workflows/daily-esi-report.yml`.

- Schedule: daily at 08:30 Asia/Shanghai (`00:30 UTC`).
- Manual trigger: GitHub Actions -> Daily ESI Report -> Run workflow.
- Required repository secret: `FRED_API_KEY`.
- Required Gmail secrets for email delivery: `GMAIL_USERNAME` and `GMAIL_APP_PASSWORD`.
- Optional recipient secret: `REPORT_EMAIL_TO`. If omitted, the report is sent to `GMAIL_USERNAME`.
- Outputs: PDF reports are emailed by Gmail SMTP, and also saved under the `esi-daily-report` artifact. Evaluation CSVs are saved under the `esi-evaluation-tables` artifact.

For Gmail delivery, create a Google App Password and store it as `GMAIL_APP_PASSWORD`. Do not use or commit your normal Gmail password.

## Tests

```bash
pytest tests/test_fetchers.py
```

## Current modules

- Data layer: implemented and cached under `data/raw/`.
- Factor layer: implemented and cached under `data/processed/factors.parquet`.
- Composite layer: implemented for `equal_weighted` and `ic_weighted` under `data/processed/esi.parquet`.
- Evaluation layer: implemented under `data/processed/evaluation/`.
- Reporting layer: implemented under `reports/`.

Note: as of May 2026, FRED's public `BAMLH0A0HYM2` and `BAMLC0A0CM` history starts in 2023 in this environment. The evaluation layer writes `data_coverage.csv` to make this visible. A separate historical backfill source is needed before validating 2020-03 and 2022-Q2 credit behavior.
