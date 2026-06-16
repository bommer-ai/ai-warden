import logging
import os
from pathlib import Path

import yaml

from aiwarden.policies.base import Policy

log = logging.getLogger(__name__)

_CONFIG_PATHS = [
    Path(".aiwarden/policies.yaml"),
    Path.home() / ".aiwarden" / "policies.yaml",
]

# Default policies when no config file found
_DEFAULTS = [
    {"name": "pii-protection", "type": "pii",   "enabled": True},
    {
        "name": "tool-safety", "type": "tools", "enabled": True,
        "builtin": {"filesystem-safety": True, "no-privilege-escalation": True},
    },
]


def load_policies() -> list[Policy]:
    path = _find_config()
    raw  = _read_config(path) if path else {"policies": _DEFAULTS}
    return _build(raw.get("policies") or [])


def _find_config() -> Path | None:
    if env := os.getenv("AIWARDEN_POLICY_FILE"):
        p = Path(env)
        if not p.exists():
            log.warning("[aiwarden] AIWARDEN_POLICY_FILE=%s not found — using defaults", env)
            return None
        return p
    return next((p for p in _CONFIG_PATHS if p.exists()), None)


def _read_config(path: Path) -> dict:
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error("[aiwarden] failed to read %s: %s — using defaults", path, e)
        return {"policies": _DEFAULTS}


def _build(policy_configs: list[dict]) -> list[Policy]:
    from aiwarden.policies.builtin import BUILTIN_POLICY_TYPES

    policies = []
    for cfg in policy_configs:
        if not cfg.get("enabled", True):
            continue
        policy_type = cfg.get("type", "")
        cls = BUILTIN_POLICY_TYPES.get(policy_type)
        if cls is None:
            log.warning("[aiwarden] unknown policy type: '%s' — skipping", policy_type)
            continue
        try:
            policies.append(cls(cfg))
            log.debug("[aiwarden] loaded policy: %s (%s)", cfg.get("name"), policy_type)
        except Exception as e:
            log.error("[aiwarden] failed to init policy '%s': %s", cfg.get("name"), e)

    return policies
