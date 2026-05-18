from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

import pandas as pd


YAHOO_CHART_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
    "?period1={period1}&period2={period2}&interval=1d&events=history&includeAdjustedClose=true"
)


def unix_timestamp(date: str) -> int:
    return int(pd.Timestamp(date, tz="UTC").timestamp())


def fetch_gspc(start: str, end: str) -> pd.DataFrame:
    url = YAHOO_CHART_URL.format(period1=unix_timestamp(start), period2=unix_timestamp(end))
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read())

    result = payload["chart"]["result"][0]
    dates = (
        pd.to_datetime(result["timestamp"], unit="s")
        .tz_localize("UTC")
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )
    close = pd.to_numeric(pd.Series(result["indicators"]["quote"][0]["close"]), errors="coerce")
    frame = pd.DataFrame({"date": dates, "close": close}).dropna()
    return frame.drop_duplicates(subset=["date"], keep="last").sort_values("date")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download local SPX history for ESI diagnostics.")
    parser.add_argument("--start", default="1990-01-01")
    parser.add_argument("--end", default=(pd.Timestamp.today().normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    parser.add_argument("--output", type=Path, default=Path("data/local_targets/GSPC.csv"))
    args = parser.parse_args()

    frame = fetch_gspc(args.start, args.end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, date_format="%Y-%m-%d")
    first = frame.iloc[0]["date"].strftime("%Y-%m-%d")
    last = frame.iloc[-1]["date"].strftime("%Y-%m-%d")
    print(f"Saved {args.output} rows={len(frame)} first={first} last={last} fetched_at={int(time.time())}")


if __name__ == "__main__":
    main()
