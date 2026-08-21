"""Fetch valuation snapshots from djeva (Danjuan) and persist per index."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import requests

try:
    from .common import ensure_data_dir, load_indices
except ImportError:  # pragma: no cover - direct execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.common import ensure_data_dir, load_indices  # type: ignore


API_URL = "https://danjuanapp.com/djapi/index_eva/dj"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

RAW_DIR = ensure_data_dir("raw", "djeva")
OUTPUT_FILENAME = "{code}_valuation.csv"


def _build_code_map() -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for cfg in load_indices():
        code = str(cfg["code"])
        djeva_code = cfg.get("djeva_code")
        if isinstance(djeva_code, str) and djeva_code:
            mapping[djeva_code.upper()] = code
    return mapping


def _normalise_item(item: dict[str, object]) -> dict[str, object]:
    timestamp = item.get("ts")
    if timestamp is None:
        raise ValueError("缺少时间戳字段 ts")
    date = dt.datetime.utcfromtimestamp(float(timestamp) / 1000.0).date()

    return {
        "date": date.isoformat(),
        "pe": item.get("pe"),
        "pb": item.get("pb"),
        "pe_percentile": item.get("pe_percentile"),
        "pb_percentile": item.get("pb_percentile"),
        "dividend_yield": item.get("yeild"),
        "roe": item.get("roe"),
        "eva_type": item.get("eva_type"),
        "eva_type_int": item.get("eva_type_int"),
        "bond_yield": item.get("bond_yeild"),
        "source": item.get("source"),
    }


def _append_records(code: str, records: List[dict[str, object]]) -> None:
    if not records:
        return
    path = RAW_DIR / OUTPUT_FILENAME.format(code=code)
    frame = pd.DataFrame(records)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    if path.exists():
        existing = pd.read_csv(path, parse_dates=["date"])
        existing["date"] = pd.to_datetime(existing["date"])
        frame = pd.concat([existing, frame], ignore_index=True, sort=False)
        frame = frame.drop_duplicates(subset=["date"], keep="last").sort_values("date")

    frame["date"] = frame["date"].dt.date.astype(str)
    frame.to_csv(path, index=False)


def _fetch_snapshot() -> list[dict[str, object]]:
    resp = requests.get(API_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or "data" not in payload:
        raise ValueError("无效响应：缺少 data 字段")
    data = payload["data"]
    if not isinstance(data, dict) or "items" not in data:
        raise ValueError("无效响应：缺少 items 字段")
    items = data["items"]
    if not isinstance(items, list):
        raise ValueError("无效响应：items 必须是列表")
    return items


def _import_bootstrap(paths: Iterable[Path], mapping: Dict[str, str]) -> None:
    total = 0
    for path in paths:
        if path.is_dir():
            for child in sorted(path.glob("*.csv")):
                _import_bootstrap([child], mapping)
            continue
        if path.suffix.lower() != ".csv":
            continue
        df = pd.read_csv(path)
        if "index_code" not in df.columns:
            continue
        for code, group in df.groupby("index_code"):
            mapped = mapping.get(str(code).upper())
            if not mapped:
                continue
            group = group.copy()
            records = []
            for item in group.to_dict("records"):
                if "ts" not in item or pd.isna(item["ts"]):
                    continue
                records.append(_normalise_item(item))
            _append_records(mapped, records)
            total += len(records)
    if total:
        print(f"已导入历史估值记录 {total} 条")


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 djeva 估值数据")
    parser.add_argument(
        "--bootstrap",
        nargs="*",
        type=str,
        help="从已有 CSV 目录或文件导入历史数据（仅需执行一次）",
    )
    args = parser.parse_args()

    mapping = _build_code_map()
    if not mapping:
        raise SystemExit("config/indices.yaml 缺少 djeva_code 配置")

    if args.bootstrap:
        paths = [Path(p).resolve() for p in args.bootstrap]
        _import_bootstrap(paths, mapping)

    try:
        items = _fetch_snapshot()
    except Exception as exc:  # noqa: BLE001
        error_path = RAW_DIR / "fetch_error.log"
        error_path.write_text(str(exc), encoding="utf-8")
        raise SystemExit(f"拉取 djeva 数据失败: {exc}") from exc

    grouped: Dict[str, List[dict[str, object]]] = {}
    for item in items:
        index_code = str(item.get("index_code", "")).upper()
        mapped = mapping.get(index_code)
        if not mapped:
            continue
        grouped.setdefault(mapped, []).append(_normalise_item(item))

    if not grouped:
        raise SystemExit("本次拉取未匹配到任何配置内的指数")

    for code, records in grouped.items():
        _append_records(code, records)
        print(f"[djeva] {code} -> 新增 {len(records)} 条记录")


if __name__ == "__main__":
    main()
