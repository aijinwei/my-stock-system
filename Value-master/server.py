"""
FastAPI backend for the percentile valuation dashboard (Tushare edition).

Now supports A-share stocks, domestic ETFs, and broad indexes. It exposes the same
two endpoints consumed by the frontend:
  - GET /api/indices  （返回所有可搜索的证券清单）
  - GET /api/indices/{id}/history?metric=pe&range=10

Depending on the security type, the service calls different Tushare interfaces:
  * Index: index_dailybasic + index_daily
  * Stock / ETF: daily_basic + daily (+ fina_indicator to derive P/CF)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Dict, List, Literal, Optional, TypedDict

import pandas as pd
import tushare as ts  # type: ignore
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

TS_TOKEN = os.getenv(
    "TUSHARE_TOKEN",
    "316fe3016ecb3c316cba784e5d9a95d4247e575b4c113ecf860287a8",
)
if not TS_TOKEN:
    raise RuntimeError("Missing Tushare token. Set TUSHARE_TOKEN env variable.")

pro = ts.pro_api(TS_TOKEN)

app = FastAPI(
    title="Valuation Percentile API (Tushare)",
    description="Serves valuation history for indexes / stocks / ETFs via Tushare Pro.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


MetricKey = Literal["pe", "pb", "ps", "pcf", "dividend", "riskPremium"]
SecurityKind = Literal["index", "stock", "etf"]


FALLBACK_SECURITIES: List[Dict[str, str]] = [
    {"id": "000300.SH", "name": "沪深300", "ts_code": "000300.SH", "kind": "index"},
    {"id": "000905.SH", "name": "中证500", "ts_code": "000905.SH", "kind": "index"},
    {"id": "600519.SH", "name": "贵州茅台", "ts_code": "600519.SH", "kind": "stock"},
    {"id": "601318.SH", "name": "中国平安", "ts_code": "601318.SH", "kind": "stock"},
    {"id": "510300.SH", "name": "沪深300ETF", "ts_code": "510300.SH", "kind": "etf"},
    {"id": "159915.SZ", "name": "创业板ETF", "ts_code": "159915.SZ", "kind": "etf"},
]

CACHE_SECONDS = 30 * 60


class HistoryPoint(TypedDict):
    date: str
    indexValue: float
    metrics: Dict[MetricKey, Optional[float]]


class CacheEntry(TypedDict):
    timestamp: float
    payload: List[HistoryPoint]


_history_cache: Dict[str, CacheEntry] = {}


def _safe_float(value: object) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return None if pd.isna(result) else result
    except (ValueError, TypeError):
        return None


def get_cached_history(key: str) -> Optional[List[HistoryPoint]]:
    entry = _history_cache.get(key)
    if not entry:
        return None
    if time.time() - entry["timestamp"] > CACHE_SECONDS:
        return None
    return entry["payload"]


def set_cached_history(key: str, payload: List[HistoryPoint]) -> None:
    _history_cache[key] = {"timestamp": time.time(), "payload": payload}


def determine_date_range(years: Optional[int]) -> tuple[str, str]:
    end_date = datetime.utcnow().strftime("%Y%m%d")
    if years is None:
        start_date = "20000101"
    else:
        start_dt = datetime.utcnow() - timedelta(days=365 * years)
        start_date = start_dt.strftime("%Y%m%d")
    return start_date, end_date


def fetch_history(definition: Dict[str, str], years: Optional[int]) -> List[HistoryPoint]:
    ts_code = definition.get("ts_code")
    if not ts_code:
        raise HTTPException(status_code=422, detail="缺少 ts_code，无法请求数据")
    kind = definition.get("kind", "index")
    cache_key = f"{ts_code}:{kind}:{years or 'max'}"
    cached = get_cached_history(cache_key)
    if cached:
        return cached

    if kind == "index":
        history, resolved_code = fetch_index_history(ts_code, years)
        definition["ts_code"] = resolved_code
    elif kind in {"stock", "etf"}:
        history = fetch_equity_history(ts_code, years)
    else:
        raise HTTPException(status_code=400, detail=f"暂不支持的证券类型 {kind}")

    set_cached_history(cache_key, history)
    return history


def fetch_index_history(ts_code: str, years: Optional[int]) -> tuple[List[HistoryPoint], str]:
    start_date, end_date = determine_date_range(years)
    base = ts_code.split(".")[0]
    value_fields = "ts_code,trade_date,pe,pb,ps,pcf,dv_ratio"
    price_fields = "ts_code,trade_date,close"

    def load_index_dailybasic(code: str) -> pd.DataFrame:
        try:
            df = pro.index_dailybasic(
                ts_code=code,
                start_date=start_date,
                end_date=end_date,
                fields=value_fields,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"index_dailybasic {code} 失败: {exc}") from exc
        if not df.empty:
            df["trade_date"] = df["trade_date"].astype(str)
            return df
        if df.empty:
            try:
                df = pro.index_dailybasic(
                    ts_code=code,
                    limit=6000,
                    fields=value_fields,
                )
            except Exception:
                return df
            if not df.empty:
                df["trade_date"] = df["trade_date"].astype(str)
                df = df[
                    (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)
                ]
        return df

    def load_index_daily(code: str) -> pd.DataFrame:
        try:
            df = pro.index_daily(
                ts_code=code,
                start_date=start_date,
                end_date=end_date,
                fields=price_fields,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"index_daily {code} 失败: {exc}") from exc
        if not df.empty:
            df["trade_date"] = df["trade_date"].astype(str)
            return df
        if df.empty:
            try:
                df = pro.index_daily(
                    ts_code=code,
                    limit=6000,
                    fields=price_fields,
                )
            except Exception:
                return df
            if not df.empty:
                df["trade_date"] = df["trade_date"].astype(str)
                df = df[
                    (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)
                ]
        return df

    def build_candidates(code: str) -> List[str]:
        suffix = code.split(".")[-1]
        if suffix == "CSI":
            return [f"{base}.CSI", f"{base}.SH", f"{base}.SZ"]
        if suffix in {"SH", "SZ"}:
            return [code, f"{base}.CSI"]
        return [code]

    candidates = build_candidates(ts_code)

    last_error: Optional[str] = None
    for code in candidates:
        try:
            basic_df = load_index_dailybasic(code)
        except RuntimeError as exc:
            last_error = str(exc)
            continue

        if basic_df.empty:
            last_error = f"index_dailybasic {code} 无返回数据"
            continue

        price_df = None
        for price_code in build_candidates(code):
            try:
                candidate_price = load_index_daily(price_code)
            except RuntimeError as exc:
                last_error = str(exc)
                continue
            if candidate_price.empty:
                last_error = f"index_daily {price_code} 无返回数据"
                continue
            price_df = candidate_price.assign(price_ts_code=price_code)
            break

        if price_df is None:
            continue

        merged = pd.merge(
            basic_df.sort_values("trade_date"),
            price_df.sort_values("trade_date"),
            on="trade_date",
            how="inner",
        )

        if merged.empty:
            last_error = f"{code} 估值与收盘价未匹配"
            continue

        history = []
        for _, row in merged.iterrows():
            trade_date = row.get("trade_date")
            if not trade_date:
                continue
            iso_date = datetime.strptime(str(trade_date), "%Y%m%d").date().isoformat()
            pe_value = _safe_float(row.get("pe"))
            earnings_yield = (100 / pe_value) if pe_value not in (None, 0) else None
            history.append(
                HistoryPoint(
                    date=iso_date,
                    indexValue=float(row["close"]),
                    metrics={
                        "pe": _safe_float(row.get("pe")),
                        "pb": _safe_float(row.get("pb")),
                        "ps": _safe_float(row.get("ps")),
                        "pcf": _safe_float(row.get("pcf")),
                        "dividend": _safe_float(row.get("dv_ratio")),
                        "riskPremium": earnings_yield - 3.0 if earnings_yield else None,
                    },
                )
            )
        if history:
            return history, code

    raise HTTPException(
        status_code=404,
        detail=last_error or f"Tushare 未返回 {ts_code} 指数数据",
    )


def fetch_equity_history(ts_code: str, years: Optional[int]) -> List[HistoryPoint]:
    start_date, end_date = determine_date_range(years)
    try:
        basic_df = pro.daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,pe_ttm,pb,ps_ttm,dv_ratio",
        )
        price_df = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,close",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Tushare 请求失败: {exc}") from exc

    if basic_df.empty or price_df.empty:
        raise HTTPException(status_code=404, detail="Tushare 未返回该证券估值数据")

    merged = pd.merge(
        basic_df.rename(columns={"pe_ttm": "pe", "ps_ttm": "ps"}),
        price_df,
        on=["ts_code", "trade_date"],
        how="inner",
    ).sort_values("trade_date")

    if merged.empty:
        raise HTTPException(status_code=404, detail="未能匹配估值与收盘价")

    merged["pcf"] = compute_pcf_series(ts_code, merged)

    history: List[HistoryPoint] = []
    for _, row in merged.iterrows():
        trade_date = row["trade_date"]
        iso_date = datetime.strptime(str(trade_date), "%Y%m%d").date().isoformat()
        pe_value = _safe_float(row.get("pe"))
        earnings_yield = (100 / pe_value) if pe_value not in (None, 0) else None
        history.append(
            HistoryPoint(
                date=iso_date,
                indexValue=float(row["close"]),
                metrics={
                    "pe": _safe_float(row.get("pe")),
                    "pb": _safe_float(row.get("pb")),
                    "ps": _safe_float(row.get("ps")),
                    "pcf": _safe_float(row.get("pcf")),
                    "dividend": _safe_float(row.get("dv_ratio")),
                    "riskPremium": earnings_yield - 3.0 if earnings_yield else None,
                },
            )
        )
    return history


def compute_pcf_series(ts_code: str, merged_df: pd.DataFrame) -> List[Optional[float]]:
    """Derive P/CF using operating cash flow per share (ocfps) from fina_indicator."""
    try:
        indicator_df = pro.fina_indicator(
            ts_code=ts_code,
            start_date=merged_df["trade_date"].min(),
            end_date=merged_df["trade_date"].max(),
            fields="ts_code,ann_date,ocfps",
        )
    except Exception:
        indicator_df = pd.DataFrame()

    if indicator_df.empty:
        return [None] * len(merged_df)

    indicator_df = indicator_df.dropna(subset=["ann_date", "ocfps"]).copy()
    if indicator_df.empty:
        return [None] * len(merged_df)

    indicator_df["ann_date"] = pd.to_datetime(indicator_df["ann_date"])
    indicator_df = indicator_df.sort_values("ann_date")

    timeline = (
        merged_df[["trade_date"]]
        .copy()
        .assign(trade_dt=lambda df: pd.to_datetime(df["trade_date"]))
        .sort_values("trade_dt")
    )
    indicator_view = (
        indicator_df[["ann_date", "ocfps"]]
        .rename(columns={"ann_date": "trade_dt"})
        .sort_values("trade_dt")
    )
    try:
        aligned = pd.merge_asof(
            timeline,
            indicator_view,
            on="trade_dt",
            direction="backward",
        )
    except ValueError:
        return [None] * len(merged_df)

    ocfps_series = aligned["ocfps"].tolist()
    pcf_values: List[Optional[float]] = []
    for close, ocfps in zip(merged_df["close"], ocfps_series):
        if ocfps and ocfps != 0:
            pcf_values.append(float(close) / float(ocfps))
        else:
            pcf_values.append(None)
    return pcf_values


def filter_by_range(points: List[HistoryPoint], range_years: Optional[int]) -> List[HistoryPoint]:
    if range_years is None:
        return points
    cutoff = datetime.utcnow() - timedelta(days=range_years * 365)
    filtered: List[HistoryPoint] = []
    for point in points:
        try:
            point_date = datetime.fromisoformat(point["date"])
        except ValueError:
            continue
        if point_date >= cutoff:
            filtered.append(point)
    return filtered


@lru_cache(maxsize=1)
def get_security_catalog() -> List[Dict[str, str]]:
    catalog: List[Dict[str, str]] = []
    seen_ids: set[str] = set()

    def add_entry(ts_code: str, name: str, kind: SecurityKind):
        ticker = ts_code.upper()
        if ticker in seen_ids:
            return
        catalog.append(
            {
                "id": ticker,
                "name": name,
                "ticker": ticker,
                "ts_code": ticker,
                "kind": kind,
            }
        )
        seen_ids.add(ticker)

    index_markets = ["SSE", "SZSE", "CSI", "CICC", "SW", "OTH"]
    for market in index_markets:
        try:
            idx_df = pro.index_basic(market=market, fields="ts_code,name,market")
        except Exception:
            continue
        for _, row in idx_df.iterrows():
            ts_code = row.get("ts_code")
            name = row.get("name")
            if ts_code and name:
                add_entry(ts_code, name, "index")

    try:
        stock_df = pro.stock_basic(list_status="L", fields="ts_code,name")
        for _, row in stock_df.iterrows():
            if row.get("ts_code") and row.get("name"):
                add_entry(row["ts_code"], row["name"], "stock")
    except Exception:
        pass

    try:
        fund_df = pro.fund_basic(market="E", status="L", fields="ts_code,name,fund_type")
        for _, row in fund_df.iterrows():
            if row.get("ts_code") and "ETF" in str(row.get("fund_type", "")):
                add_entry(row["ts_code"], row["name"], "etf")
    except Exception:
        pass

    for fallback in FALLBACK_SECURITIES:
        if fallback["id"].upper() not in seen_ids:
            catalog.append(fallback)
            seen_ids.add(fallback["id"].upper())
    return catalog


@app.get("/api/indices")
def list_indices(q: Optional[str] = Query(default=None, description="模糊搜索名称或代码")):
    catalog = get_security_catalog()
    if q:
        keyword = q.lower()
        catalog = [
            item
            for item in catalog
            if keyword
            in (
                (item.get("name") or "")
                + (item.get("id") or "")
                + (item.get("ticker") or "")
            ).lower()
        ]
    return catalog


@app.get("/api/indices/{security_id}/history")
def security_history(
    security_id: str,
    metric: MetricKey = Query(default="pe"),
    range: Optional[str] = Query(default="10"),
):
    security_id = security_id.upper()
    catalog = get_security_catalog()
    definition = next(
        (
            item
            for item in catalog
            if item["id"].upper() == security_id
            or item.get("ts_code", "").upper() == security_id
            or item.get("ticker", "").upper() == security_id
        ),
        None,
    )
    if not definition:
        raise HTTPException(status_code=404, detail="未找到对应标的")

    years: Optional[int]
    if range == "max":
        years = None
    else:
        try:
            years = int(range)
        except (TypeError, ValueError):
            years = 10

    history = fetch_history(definition, years)
    history = filter_by_range(history, years)
    if not history:
        raise HTTPException(status_code=404, detail="该区间没有可用数据")

    return {
        "meta": {
            "id": definition.get("id", security_id),
            "name": definition.get("name", security_id),
            "ticker": definition.get("ticker", ""),
            "ts_code": definition.get("ts_code"),
            "kind": definition.get("kind"),
        },
        "history": history,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
