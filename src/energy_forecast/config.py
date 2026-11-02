"""Configuration loading. All paths are resolved relative to the repo root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"


@dataclass
class Config:
    raw: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def path(self, key: str) -> Path:
        p = ROOT / self.raw["paths"][key]
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def tz(self) -> str:
        return self.raw["project"]["timezone"]

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(self.raw["project"]["start"], tz="UTC")

    @property
    def end(self) -> pd.Timestamp:
        end = self.raw["project"].get("end")
        if end:
            return pd.Timestamp(end, tz="UTC")
        return pd.Timestamp.now(tz="UTC").floor("D")

    @property
    def all_targets(self) -> list[str]:
        t = self.raw["targets"]
        return [t["price"], *t["production"]]


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return Config(yaml.safe_load(f))


def entsoe_api_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.getenv("ENTSOE_API_KEY", "")
    if not key or key == "your-token-here":
        raise RuntimeError(
            "ENTSOE_API_KEY missing. Copy .env.example to .env and add your ENTSO-E token "
            "(see README > Data access)."
        )
    return key
