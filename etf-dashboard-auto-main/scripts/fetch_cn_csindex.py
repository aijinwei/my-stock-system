"""Fetch CSI index daily prices via akshare/yfinance."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable, List

import akshare as ak
import pandas as pd
import yfinance as yf

try:
    from .common import ensure_data_dir, load_indices
except ImportError:  # pragma: no cover - direct execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.common import ensure_data_dir, load_indices  # type: ignore


RAW_DIR = ensure_data_dir("raw", "cn_csi")
PRICE_FILENAME = "{code}_price.csv"


def _akshare_symbol(symbol: str) -> str:
    return symbol.lower()


def _fetch_via_akshare(symbol: str, start: dt.date) -> pd.DataFrame:
    df = ak.stock_zh_index_daily_em(symbol=_akshare_symbol(symbol))
    if df.empty:
        raise RuntimeError("akshare 返回空结果")
    df = df.rename(columns={"date": "date", "close": "close"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.loc[df["date"] >= pd.Timestamp(start)].sort_values("date")
    return df[["date", "close"]]


def _fetch_via_yfinance(symbols: Iterable[str], start: dt.date) -> pd.DataFrame:
    for symbol in symbols:
        if not symbol:
            continue
        try:
            df = yf.download(symbol, start=start.isoformat(), progress=False, auto_adjust=False)
            if df.empty:
                continue
            frame = df.reset_index()[["Date", "Close"]]
            frame.columns = ["date", "close"]
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.loc[frame["date"] >= pd.Timestamp(start)].dropna(subset=["close"])
            if not frame.empty:
                frame = frame.sort_values("date")
                return frame
        except Exception:
            continue
    raise RuntimeError("yfinance 兜底失败")


def _candidate_proxies(raw: Iterable[str]) -> List[str]:
    return [symbol for symbol in raw if isinstance(symbol, str) and symbol]


def main() -> None:
    indices = [cfg for cfg in load_indices() if cfg.get("class") == "CN_CSI"]
    if not indices:
        raise SystemExit("config/indices.yaml 未配置任何 CN_CSI 指数")

    start_date = dt.date.today() - dt.timedelta(days=365 * 15)

    for cfg in indices:
        code = cfg["code"]
        price_symbol = str(cfg.get("price_symbol") or code)
        proxies = _candidate_proxies(cfg.get("etf_proxies", []))

        print(f"[CN_CSI] {code} -> {price_symbol}")
        try:
            price_df = _fetch_via_akshare(price_symbol, start_date)
            source = "akshare"
        except Exception as exc:  # noqa: BLE001
            print(f"  akshare 失败: {exc}")
            price_df = _fetch_via_yfinance([price_symbol, *proxies], start_date)
            source = "yfinance"

        path = RAW_DIR / PRICE_FILENAME.format(code=code)
        price_df.to_csv(path, index=False)
        print(f"  行情 {len(price_df)} 条，来源 {source}")


if __name__ == "__main__":
    main()
