"""Fetch Hang Seng related index prices via yfinance."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable, List

import pandas as pd
import yfinance as yf

try:
    from .common import ensure_data_dir, load_indices
except ImportError:  # pragma: no cover - direct execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.common import ensure_data_dir, load_indices  # type: ignore


RAW_DIR = ensure_data_dir("raw", "hk_hsi")
PRICE_FILENAME = "{code}_price.csv"


def _candidate_symbols(primary: str, extras: Iterable[str]) -> List[str]:
    symbols: List[str] = []
    if primary:
        symbols.append(primary)
    for item in extras:
        if isinstance(item, str) and item and item not in symbols:
            symbols.append(item)
    return symbols


def _fetch(symbols: Iterable[str], start: dt.date) -> pd.DataFrame:
    last_error: Exception | None = None
    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start.isoformat(), progress=False, auto_adjust=False)
            if df.empty:
                continue
            frame = df.reset_index()[["Date", "Close"]]
            frame.columns = ["date", "close"]
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.loc[frame["date"] >= pd.Timestamp(start)].dropna(subset=["close"])
            if frame.empty:
                continue
            return frame.sort_values("date")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("未能获取任何有效的行情数据")


def main() -> None:
    indices = [cfg for cfg in load_indices() if cfg.get("class") == "HK_HSI"]
    if not indices:
        raise SystemExit("config/indices.yaml 未配置任何 HK_HSI 指数")

    start_date = dt.date.today() - dt.timedelta(days=365 * 15)

    for cfg in indices:
        code = cfg["code"]
        primary = str(cfg.get("price_symbol") or code)
        extras = cfg.get("etf_proxies", [])
        symbols = _candidate_symbols(primary, extras)

        print(f"[HK_HSI] {code} -> {', '.join(symbols)}")
        frame = _fetch(symbols, start_date)
        path = RAW_DIR / PRICE_FILENAME.format(code=code)
        frame.to_csv(path, index=False)
        print(f"  行情 {len(frame)} 条，来源 {symbols[0]}")


if __name__ == "__main__":
    main()
