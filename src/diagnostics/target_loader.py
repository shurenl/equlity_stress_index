from __future__ import annotations

from pathlib import Path

import pandas as pd


TARGET_TO_FRED = {"^GSPC": "SP500", "^NDX": "NASDAQ100"}
TARGET_TO_LOCAL = {"^GSPC": "GSPC.csv", "^NDX": "NDX.csv", "QQQ": "QQQ.csv"}


def load_local_target_csv(path: Path, target_name: str) -> pd.Series:
    frame = pd.read_csv(path)
    columns = {column.lower(): column for column in frame.columns}
    date_column = columns.get("date")
    value_column = columns.get("close") or columns.get("adj close") or columns.get("value")
    if not date_column or not value_column:
        raise ValueError(f"{path} must contain date and close/adj close/value columns.")

    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.tz_localize(None).dt.normalize()
    values = pd.to_numeric(frame[value_column], errors="coerce")
    series = pd.Series(values.to_numpy(), index=dates, name=target_name).dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series.asfreq("B").ffill(limit=3).rename(target_name)


def load_fred_target(raw_dir: Path, target_name: str) -> pd.Series:
    ticker = TARGET_TO_FRED[target_name]
    path = raw_dir / f"fred_{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing required target cache: {path}")
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame[ticker].rename(target_name)


def load_target_series(target_name: str, raw_dir: Path, local_dir: Path) -> pd.Series:
    local_file = TARGET_TO_LOCAL.get(target_name)
    if local_file:
        local_path = local_dir / local_file
        if local_path.exists():
            return load_local_target_csv(local_path, target_name)

    if target_name in TARGET_TO_FRED:
        return load_fred_target(raw_dir, target_name)

    raise FileNotFoundError(
        f"No local target CSV for {target_name}. Expected one of: "
        f"{', '.join(sorted(TARGET_TO_LOCAL.values()))}"
    )
