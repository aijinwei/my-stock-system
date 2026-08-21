"""Transform metrics into docs/assets.csv for the dashboard."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    from .common import DATA_ROOT, PROJECT_ROOT, load_indices
except ImportError:  # pragma: no cover - direct execution fallback
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from scripts.common import DATA_ROOT, PROJECT_ROOT, load_indices  # type: ignore


METRICS_PATH = DATA_ROOT / "processed" / "metrics.csv"
DOCS_DIR = PROJECT_ROOT / "docs"
TARGET_CSV = DOCS_DIR / "assets.csv"


def _format_etfs(cfg: dict[str, object]) -> str:
    display = cfg.get("etf_display")
    if isinstance(display, list) and display:
        return "; ".join(str(item) for item in display)
    proxies = cfg.get("etf_proxies") or []
    if isinstance(proxies, list):
        return "; ".join(str(item) for item in proxies)
    return ""


def _safe(value, default: float | None = None, digits: int = 4) -> float | None:
    if value is None:
        return default
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return default


def main() -> None:
    if not METRICS_PATH.exists():
        raise SystemExit("缺少指标文件 metrics.csv，请先运行 compute_metrics.py")

    metrics_df = pd.read_csv(METRICS_PATH)
    if "index_code" not in metrics_df.columns:
        raise SystemExit("指标文件缺少 index_code 列")
    metrics_df.set_index("index_code", inplace=True)

    rows: list[dict[str, object]] = []
    for cfg in load_indices():
        code = cfg["code"]
        metrics = metrics_df.loc[code] if code in metrics_df.index else {}

        rows.append(
            {
                "index_name": cfg["name"],
                "index_code": code,
                "etfs": _format_etfs(cfg),
                "pe": _safe(metrics.get("pe_current"), None, 2),
                "pe_pct": _safe(metrics.get("pe_pct"), 100.0, 2),
                "pb": _safe(metrics.get("pb_current"), None, 2),
                "pb_pct": _safe(metrics.get("pb_pct"), 100.0, 2),
                "dividend": _safe(metrics.get("dividend_current"), None, 4),
                "roe": _safe(metrics.get("roe_current"), None, 4),
                "drawdown": _safe(metrics.get("drawdown"), 0.0, 4),
                "eva_type": metrics.get("eva_type") if isinstance(metrics, pd.Series) else None,
            }
        )

    assets_df = pd.DataFrame(rows)
    assets_df.to_csv(TARGET_CSV, index=False)
    print(f"仪表盘数据已写入 {TARGET_CSV} ({len(assets_df)} 条记录)")


if __name__ == "__main__":
    main()
