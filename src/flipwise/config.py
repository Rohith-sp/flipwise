"""Experiment configuration: load, check, hash (PRD §13.3)."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import yaml

from flipwise.errors import ConfigError


def load_config(path: Path) -> dict:
    try:
        cfg = yaml.safe_load(Path(path).read_text())
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: expected a mapping at top level")
    for key in ("data", "regions", "horizon_days", "splits"):
        if key not in cfg:
            raise ConfigError(f"{path}: missing required key {key!r}")
    if not (isinstance(cfg["regions"], list) and all(isinstance(r, int) for r in cfg["regions"])):
        raise ConfigError("regions: expected a list of NESO region ids (int)")
    return cfg


def apply_overrides(cfg: dict, overrides: list[str]) -> dict:
    """Return a copy of `cfg` with each `a.b.c=value` applied; the value is parsed as YAML."""
    out = copy.deepcopy(cfg)
    for item in overrides:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise ConfigError(f"--set: expected key=value, got {item!r}")
        *parents, leaf = key.split(".")
        node = out
        for part in parents:
            if not isinstance(node.get(part), dict):
                raise ConfigError(f"--set {key}: {part!r} is not a section of the config")
            node = node[part]
        if leaf not in node:
            raise ConfigError(f"--set {key}: unknown key {leaf!r}")
        node[leaf] = yaml.safe_load(raw)
    return out


def canonical_json(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True, separators=(",", ":"), default=str)


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(canonical_json(cfg).encode()).hexdigest()


def date(s: str, key: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(s))
    except ValueError:
        raise ConfigError(f"{key}: expected an ISO date, got {s!r}") from None
