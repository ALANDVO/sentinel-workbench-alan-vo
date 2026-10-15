"""Configuration settings for Sentinel Workbench."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _read_version() -> str:
    root = Path(__file__).resolve().parents[3]
    version_file = root / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version") and "=" in stripped:
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    return "1.0.0"


def _read_portfolio_name() -> str:
    root = Path(__file__).resolve().parents[3]
    portfolio = root / "portfolio.json"
    if portfolio.is_file():
        try:
            payload = json.loads(portfolio.read_text(encoding="utf-8"))
            return str(payload.get("name", "sentinel-workbench-alan-vo"))
        except Exception:
            return "sentinel-workbench-alan-vo"
    return "sentinel-workbench-alan-vo"


@dataclass(frozen=True)
class Settings:
    app_name: str
    version: str
    db_path: str
    environment: str


def get_settings() -> Settings:
    default_db = str(Path(__file__).resolve().parents[2] / "data" / "sentinel_workbench.db")
    return Settings(
        app_name=_read_portfolio_name(),
        version=_read_version(),
        db_path=os.environ.get("SENTINEL_DB_PATH", default_db),
        environment=os.environ.get("SENTINEL_ENV", "development"),
    )
