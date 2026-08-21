"""Shared utilities for the data-fetch pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import yaml

# Project root relative paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "indices.yaml"
DATA_ROOT = PROJECT_ROOT / "data"


def load_indices() -> List[dict[str, Any]]:
    """Load the index configuration table."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    if not isinstance(data, list):
        raise ValueError("indices.yaml must define a list of index entries")
    return data


def ensure_data_dir(*segments: str) -> Path:
    """Ensure a sub-directory under data/ exists and return its path."""
    target = DATA_ROOT.joinpath(*segments)
    target.mkdir(parents=True, exist_ok=True)
    return target


def ensure_workspace_dir(*segments: str) -> Path:
    """Ensure a directory relative to project root exists."""
    target = PROJECT_ROOT.joinpath(*segments)
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = ["PROJECT_ROOT", "DATA_ROOT", "load_indices", "ensure_data_dir", "ensure_workspace_dir"]
