from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw
        self.backends: List[Dict[str, Any]] = raw.get("backends", [])
        self.aliases: Dict[str, str] = raw.get("aliases", {})

        if not isinstance(self.backends, list) or not self.backends:
            raise ConfigError("config.backends must be a non-empty list")

        # Normalize prefixes to always end with '/'
        for backend in self.backends:
            prefix = backend.get("prefix")
            if not prefix or not isinstance(prefix, str):
                raise ConfigError("Each backend must define a string 'prefix'")
            if not prefix.endswith("/"):
                backend["prefix"] = f"{prefix}/"

    @property
    def raw(self) -> Dict[str, Any]:
        return self._raw

    def get_backend_by_prefix(self, prefix: str) -> Optional[Dict[str, Any]]:
        for backend in self.backends:
            if backend.get("prefix") == prefix:
                return backend
        return None


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(data)
