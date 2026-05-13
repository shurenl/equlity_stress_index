from __future__ import annotations

import contextlib
import io
import time
from urllib.parse import quote

import pandas as pd

from src.fetchers.base import BaseFetcher, Ticker


class YahooFetcher(BaseFetcher):
    """Yahoo Finance data fetcher with retry and exponential backoff."""

    source = "yahoo"
    _CBOE_HISTORY = {
        "^VIX": ("VIX", "CLOSE"),
        "^VIX3M": ("VIX3M", "CLOSE"),
        "^SKEW": ("SKEW", "SKEW"),
    }
    _CONVEX_HISTORY = {
        "^MOVE": "https://convextrade.com/api/public/metrics/move-index/data.csv",
    }

    def __init__(
        self,
        retries: int = 3,
        backoff_seconds: float = 2.0,
        request_pause_seconds: float = 1.0,
    ) -> None:
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.request_pause_seconds = request_pause_seconds

    def fetch(self, ticker: Ticker, start: str, end: str) -> pd.DataFrame:
        import yfinance as yf

        tickers = ticker if isinstance(ticker, list) else [ticker]
        end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        frames = []

        for index, item in enumerate(tickers):
            frames.append(self._fetch_one(yf, item, start, end, end_exclusive))
            if index < len(tickers) - 1 and self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)

        data = pd.concat(frames, axis=1)
        return self.to_business_frame(data, start, end)

    def _fetch_one(
        self,
        yf,
        ticker: str,
        start: str,
        end: str,
        end_exclusive: str,
    ) -> pd.DataFrame:
        last_error: Exception | None = None

        fallback = self._fetch_public_fallback(ticker, start, end)
        if fallback is not None and not fallback.empty:
            return fallback

        for attempt in range(1, self.retries + 1):
            try:
                raw = self._download(yf, ticker, start, end_exclusive)
                data = self._extract_close(raw, [ticker])
                if data.empty:
                    raise ValueError(f"Yahoo returned no data for {ticker}")
                return data
            except Exception as exc:
                last_error = exc
                if attempt == self.retries:
                    break
                time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))

        raise RuntimeError(f"Yahoo fetch failed for {ticker} after {self.retries} attempts") from last_error

    def _fetch_public_fallback(self, ticker: str, start: str, end: str) -> pd.DataFrame | None:
        if ticker in self._CBOE_HISTORY:
            return self._fetch_cboe_history(ticker, start, end)
        if ticker in self._CONVEX_HISTORY:
            return self._fetch_convex_history(ticker, start, end)
        return None

    def _fetch_cboe_history(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        cboe_symbol, value_column = self._CBOE_HISTORY[ticker]
        url = f"https://cdn.cboe.com/api/global/us_indices/daily_prices/{quote(cboe_symbol)}_History.csv"
        raw = pd.read_csv(url)
        raw["DATE"] = pd.to_datetime(raw["DATE"])
        frame = raw.set_index("DATE")[[value_column]].rename(columns={value_column: ticker})
        return self.to_business_frame(frame.loc[start:end], start, end)

    def _fetch_convex_history(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        raw = pd.read_csv(self._CONVEX_HISTORY[ticker], comment="#")
        raw["date"] = pd.to_datetime(raw["date"])
        frame = raw.set_index("date")[["value_bp"]].rename(columns={"value_bp": ticker})
        return self.to_business_frame(frame.loc[start:end], start, end)

    @staticmethod
    def _download(yf, ticker: str, start: str, end_exclusive: str) -> pd.DataFrame:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            return yf.download(
                tickers=ticker,
                start=start,
                end=end_exclusive,
                progress=False,
                auto_adjust=False,
                threads=False,
                timeout=30,
            )

    @staticmethod
    def _extract_close(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()

        if isinstance(raw.columns, pd.MultiIndex):
            price_field = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
            data = raw[price_field].copy()
        else:
            price_field = "Adj Close" if "Adj Close" in raw.columns else "Close"
            data = raw[[price_field]].copy()
            data.columns = [tickers[0]]

        if isinstance(data, pd.Series):
            data = data.to_frame(name=tickers[0])

        return data.loc[:, [column for column in data.columns if column in tickers]]
