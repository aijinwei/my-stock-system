"""Aggregate price & valuation data to compute dashboard metrics."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from .common import DATA_ROOT, ensure_data_dir, load_indices
except ImportError:  # pragma: no cover - direct execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.common import DATA_ROOT, ensure_data_dir, load_indices  # type: ignore


PRICE_DIRS = {
    "CN_CSI": DATA_ROOT / "raw" / "cn_csi",
    "HK_HSI": DATA_ROOT / "raw" / "hk_hsi",
    "US_INDEX": DATA_ROOT / "raw" / "us_index",
}

DJEVA_DIR = DATA_ROOT / "raw" / "djeva"
PROCESSED_DIR = ensure_data_dir("processed")
METRICS_FILE = PROCESSED_DIR / "metrics.csv"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["date"])


def _ten_year_window(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    series = series.sort_index()
    last_date = series.index.max()
    cutoff = last_date - pd.DateOffset(years=10)
    window = series[series.index >= cutoff]
    return window if not window.empty else series


def _percentile(series: pd.Series) -> Optional[float]:
    series = series.dropna()
    if series.empty:
        return None
    series = series.sort_index()
    window = _ten_year_window(series)
    current = window.iloc[-1]
    percentile = (window <= current).sum() / len(window) * 100.0
    return float(np.clip(percentile, 0.0, 100.0))


def _current(series: pd.Series) -> Optional[float]:
    series = series.dropna()
    if series.empty:
        return None
    series = series.sort_index()
    value = series.iloc[-1]
    return float(value)


def _drawdown(price: pd.Series) -> Optional[float]:
    price = price.dropna()
    if price.empty:
        return None
    price = price.sort_index()
    window = _ten_year_window(price)
    rolling_max = window.cummax()
    dd = 1.0 - window / rolling_max
    return float(np.clip(dd.iloc[-1], 0.0, 1.0))


def _load_price(cfg: dict[str, object]) -> pd.DataFrame:
    market = cfg.get("class")
    if market not in PRICE_DIRS:
        raise ValueError(f"未知市场分类: {market}")
    path = PRICE_DIRS[market] / f"{cfg['code']}_price.csv"
    df = _read_csv(path)
    if not df.empty:
        df = df.sort_values("date")
        df.set_index("date", inplace=True, drop=False)
    return df


def _load_valuation(cfg: dict[str, object]) -> pd.DataFrame:
    path = DJEVA_DIR / f"{cfg['code']}_valuation.csv"
    df = _read_csv(path)
    if df.empty:
        return df
    df = df.sort_values("date")
    df.set_index("date", inplace=True, drop=False)
    numeric_cols = [
        "pe",
        "pb",
        "pe_percentile",
        "pb_percentile",
        "dividend_yield",
        "roe",
        "bond_yield",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def main() -> None:
    indices = load_indices()
    records: list[dict[str, object]] = []

    for cfg in indices:
        code = cfg["code"]
        valuation = _load_valuation(cfg)
        prices = _load_price(cfg)

        if valuation.empty:
            print(f"[metrics] 缺少估值数据: {code}")
        if prices.empty:
            print(f"[metrics] 缺少行情数据: {code}")

        pe_pct = None
        if "pe_percentile" in valuation.columns:
            pe_pct = _current(valuation.get("pe_percentile", pd.Series(dtype=float)))
            if pe_pct is not None:
                pe_pct = float(pe_pct) * 100.0
        if pe_pct is None:
            pe_pct = _percentile(valuation.get("pe", pd.Series(dtype=float)))

        pb_pct = None
        if "pb_percentile" in valuation.columns:
            pb_pct = _current(valuation.get("pb_percentile", pd.Series(dtype=float)))
            if pb_pct is not None:
                pb_pct = float(pb_pct) * 100.0
        if pb_pct is None:
            pb_pct = _percentile(valuation.get("pb", pd.Series(dtype=float)))

        drawdown = _drawdown(prices.get("close", pd.Series(dtype=float)))

        pe_current = _current(valuation.get("pe", pd.Series(dtype=float)))
        pb_current = _current(valuation.get("pb", pd.Series(dtype=float)))
        div_current = _current(valuation.get("dividend_yield", pd.Series(dtype=float)))
        roe_current = _current(valuation.get("roe", pd.Series(dtype=float)))

        eva_type = None
        eva_type_int = None
        bond_yield = None
        if not valuation.empty:
            last = valuation.iloc[-1]
            eva_type = last.get("eva_type")
            eva_type_int = last.get("eva_type_int")
            bond_yield = last.get("bond_yield")

        records.append(
            {
                "index_code": code,
                "pe_pct": pe_pct,
                "pb_pct": pb_pct,
                "drawdown": drawdown,
                "pe_current": pe_current,
                "pb_current": pb_current,
                "dividend_current": div_current,
                "roe_current": roe_current,
                "eva_type": eva_type,
                "eva_type_int": eva_type_int,
                "bond_yield": bond_yield,
            }
        )

    metrics = pd.DataFrame(records)
    metrics.to_csv(METRICS_FILE, index=False)
    print(f"指标文件已生成: {METRICS_FILE} ({len(metrics)} 条记录)")


if __name__ == "__main__":
    main()
