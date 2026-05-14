from __future__ import annotations

import os

import pandas as pd
import pytest

from src.fetchers.base import BaseFetcher
from src.fetchers.fred_fetcher import FREDFetcher
from src.fetchers.yahoo_fetcher import YahooFetcher


class FakeFetcher(BaseFetcher):
    source = "fake"

    def __init__(self, payloads: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str | list[str], str, str]] = []

    def fetch(self, ticker, start: str, end: str) -> pd.DataFrame:
        self.calls.append((ticker, start, end))
        return self.payloads.get((start, end), pd.DataFrame())


def test_update_cache_creates_parquet_and_metadata(tmp_path):
    payload = pd.DataFrame(
        {"ABC": [1.0, 2.0, 3.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    fetcher = FakeFetcher({("2024-01-02", "2024-01-05"): payload})

    result = fetcher.update_cache(
        "test_factor",
        "ABC",
        "2024-01-02",
        "2024-01-05",
        tmp_path / "raw",
        tmp_path / "cache_meta.json",
    )

    assert fetcher.calls == [("ABC", "2024-01-02", "2024-01-05")]
    assert (tmp_path / "raw" / "fake_ABC.parquet").exists()
    assert (tmp_path / "cache_meta.json").exists()
    assert result.index.equals(pd.bdate_range("2024-01-02", "2024-01-05"))
    assert result.loc["2024-01-05", "ABC"] == 3.0


def test_update_cache_fetches_only_missing_right_edge(tmp_path):
    raw_dir = tmp_path / "raw"
    meta_path = tmp_path / "cache_meta.json"
    initial = pd.DataFrame(
        {"ABC": [1.0, 2.0, 3.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    first = FakeFetcher({("2024-01-02", "2024-01-04"): initial})
    first.update_cache("test_factor", "ABC", "2024-01-02", "2024-01-04", raw_dir, meta_path)

    extra = pd.DataFrame({"ABC": [4.0, 5.0]}, index=pd.to_datetime(["2024-01-05", "2024-01-08"]))
    second = FakeFetcher({("2024-01-05", "2024-01-08"): extra})
    result = second.update_cache("test_factor", "ABC", "2024-01-02", "2024-01-08", raw_dir, meta_path)

    assert second.calls == [("ABC", "2024-01-05", "2024-01-08")]
    assert result.loc["2024-01-08", "ABC"] == 5.0


def test_business_frequency_ffill_limit_preserves_long_gaps():
    sparse = pd.DataFrame(
        {"ABC": [10.0, 20.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-10"]),
    )

    result = BaseFetcher.to_business_frame(sparse, "2024-01-02", "2024-01-10")

    assert result.index.equals(pd.bdate_range("2024-01-02", "2024-01-10"))
    assert result.loc["2024-01-05", "ABC"] == 10.0
    assert pd.isna(result.loc["2024-01-08", "ABC"])
    assert result.loc["2024-01-10", "ABC"] == 20.0


def test_yahoo_fetch_retries_then_succeeds(monkeypatch):
    calls = {"count": 0}
    raw = pd.DataFrame(
        {"Adj Close": [100.0, 101.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    def fake_download(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("temporary network failure")
        return raw

    import yfinance as yf

    monkeypatch.setattr(yf, "download", fake_download)
    fetcher = YahooFetcher(retries=3, backoff_seconds=0)

    result = fetcher.fetch("SPY", "2024-01-02", "2024-01-03")

    assert calls["count"] == 3
    assert list(result.columns) == ["SPY"]
    assert result.loc["2024-01-03", "SPY"] == 101.0


def test_yahoo_fetch_downloads_multi_ticker_one_at_a_time(monkeypatch):
    requested = []

    def fake_download(*args, **kwargs):
        ticker = kwargs["tickers"]
        requested.append(ticker)
        return pd.DataFrame(
            {"Adj Close": [10.0 if ticker == "AAA" else 20.0]},
            index=pd.to_datetime(["2024-01-02"]),
        )

    import yfinance as yf

    monkeypatch.setattr(yf, "download", fake_download)
    fetcher = YahooFetcher(retries=1, backoff_seconds=0, request_pause_seconds=0)

    result = fetcher.fetch(["AAA", "BBB"], "2024-01-02", "2024-01-02")

    assert requested == ["AAA", "BBB"]
    assert list(result.columns) == ["AAA", "BBB"]
    assert result.loc["2024-01-02", "AAA"] == 10.0
    assert result.loc["2024-01-02", "BBB"] == 20.0


def test_yahoo_fetch_uses_public_fallback_before_yfinance(monkeypatch):
    def fail_download(*args, **kwargs):
        raise AssertionError("yfinance should not be called for fallback tickers")

    import yfinance as yf

    monkeypatch.setattr(yf, "download", fail_download)
    monkeypatch.setattr(
        YahooFetcher,
        "_fetch_public_fallback",
        lambda self, ticker, start, end: pd.DataFrame(
            {ticker: [13.5]},
            index=pd.to_datetime(["2024-01-02"]),
        ),
    )
    fetcher = YahooFetcher(retries=1, backoff_seconds=0, request_pause_seconds=0)

    result = fetcher.fetch("^VIX", "2024-01-02", "2024-01-02")

    assert result.loc["2024-01-02", "^VIX"] == 13.5


def test_fred_fetcher_requires_api_key_without_leaking_secret(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        FREDFetcher()

    message = str(excinfo.value)
    assert "FRED_API_KEY" in message
    assert "secret" not in message.lower()
    assert os.environ.get("FRED_API_KEY") is None


def test_fred_fetcher_supports_safe_compute_expression():
    class FakeFredClient:
        def get_series(self, ticker, observation_start=None, observation_end=None):
            values = {
                "BAA10Y": [2.0, 2.5],
                "AAA10Y": [1.0, 1.2],
            }
            return pd.Series(values[ticker], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))

    fetcher = FREDFetcher.__new__(FREDFetcher)
    fetcher.client = FakeFredClient()

    result = fetcher.fetch("BAA10Y - AAA10Y", "2024-01-02", "2024-01-03")

    assert list(result.columns) == ["BAA10Y - AAA10Y"]
    assert result.loc["2024-01-02", "BAA10Y - AAA10Y"] == 1.0
    assert result.loc["2024-01-03", "BAA10Y - AAA10Y"] == 1.3


def test_fred_fetcher_rejects_unsafe_compute_expression():
    with pytest.raises(ValueError):
        FREDFetcher._expression_tickers("__import__('os').system('echo bad')")
