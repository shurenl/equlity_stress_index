from __future__ import annotations

import os

import pandas as pd

from src.fetchers.base import BaseFetcher, Ticker


class FREDFetcher(BaseFetcher):
    """FRED data fetcher using the FRED_API_KEY environment variable."""

    source = "fred"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("FRED_API_KEY")
        if not self.api_key:
            raise RuntimeError("FRED_API_KEY is required for FRED data. Set it as an environment variable.")

        from fredapi import Fred

        self.client = Fred(api_key=self.api_key)

    def fetch(self, ticker: Ticker, start: str, end: str) -> pd.DataFrame:
        if isinstance(ticker, list):
            frames = [self._fetch_one(item, start, end) for item in ticker]
            data = pd.concat(frames, axis=1)
        else:
            data = self._fetch_one(ticker, start, end)

        return self.to_business_frame(data, start, end)

    def _fetch_one(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        series = self.client.get_series(ticker, observation_start=start, observation_end=end)
        series.name = ticker
        return series.to_frame()

