from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

Ticker = str | list[str]


class BaseFetcher(ABC):
    """Base class for source-specific market data fetchers."""

    source: str = "base"

    @abstractmethod
    def fetch(self, ticker: Ticker, start: str, end: str) -> pd.DataFrame:
        """Fetch data for an inclusive date range."""

    def update_cache(
        self,
        name: str,
        ticker: Ticker,
        start: str,
        end: str,
        raw_dir: Path,
        meta_path: Path,
    ) -> pd.DataFrame:
        """Read local parquet cache, fetch missing edge ranges, then persist."""
        raw_dir.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        start_ts = self._normalize_date(start)
        end_ts = self._normalize_date(end)
        if end_ts < start_ts:
            raise ValueError(f"end date {end} is earlier than start date {start}")

        cache_key = self.cache_key(ticker)
        cache_path = raw_dir / f"{cache_key}.parquet"
        existing = self._read_cache(cache_path)

        frames: list[pd.DataFrame] = []
        if not existing.empty:
            frames.append(existing)

        for missing_start, missing_end in self._missing_edge_ranges(existing, start_ts, end_ts):
            fetched = self.fetch(
                ticker,
                missing_start.strftime("%Y-%m-%d"),
                missing_end.strftime("%Y-%m-%d"),
            )
            if not fetched.empty:
                frames.append(fetched)

        if frames:
            combined = pd.concat(frames)
        else:
            combined = pd.DataFrame()

        normalized = self.to_business_frame(combined, start_ts, end_ts)
        normalized.to_parquet(cache_path)
        self._update_meta(meta_path, cache_key, name, ticker, start_ts, end_ts, cache_path)
        return normalized

    def cache_key(self, ticker: Ticker) -> str:
        return f"{self.source}_{self._safe_ticker(ticker)}"

    @staticmethod
    def to_business_frame(
        data: pd.DataFrame | pd.Series,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
    ) -> pd.DataFrame:
        """Normalize market data to business-day frequency with limited ffill."""
        start_ts = BaseFetcher._normalize_date(start)
        end_ts = BaseFetcher._normalize_date(end)
        index = pd.bdate_range(start_ts, end_ts)

        if isinstance(data, pd.Series):
            frame = data.to_frame()
        else:
            frame = data.copy()

        if frame.empty:
            return pd.DataFrame(index=index)

        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame = frame.apply(pd.to_numeric, errors="coerce")
        return frame.reindex(index).ffill(limit=3)

    @staticmethod
    def _normalize_date(value: str | pd.Timestamp) -> pd.Timestamp:
        return pd.Timestamp(value).tz_localize(None).normalize()

    @staticmethod
    def _safe_ticker(ticker: Ticker) -> str:
        tickers = ticker if isinstance(ticker, list) else [ticker]
        parts = []
        for item in tickers:
            cleaned = re.sub(r"[^A-Za-z0-9]+", "_", item.replace("^", "")).strip("_")
            parts.append(cleaned)
        return "_".join(parts)

    @staticmethod
    def _read_cache(cache_path: Path) -> pd.DataFrame:
        if not cache_path.exists():
            return pd.DataFrame()
        frame = pd.read_parquet(cache_path)
        frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        return frame.sort_index()

    @staticmethod
    def _missing_edge_ranges(
        existing: pd.DataFrame,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        if existing.empty:
            return [(start, end)]

        cached_start = existing.index.min()
        cached_end = existing.index.max()
        ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []

        if start < cached_start:
            left_end = min(end, cached_start - pd.offsets.BDay(1))
            if start <= left_end:
                ranges.append((start, left_end))

        if end > cached_end:
            right_start = max(start, cached_end + pd.offsets.BDay(1))
            if right_start <= end:
                ranges.append((right_start, end))

        return ranges

    def _update_meta(
        self,
        meta_path: Path,
        cache_key: str,
        name: str,
        ticker: Ticker,
        start: pd.Timestamp,
        end: pd.Timestamp,
        cache_path: Path,
    ) -> None:
        meta: dict[str, Any] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        meta[cache_key] = {
            "name": name,
            "source": self.source,
            "ticker": ticker,
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "cache_path": str(cache_path),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")

