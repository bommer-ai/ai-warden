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

_DEFAULTS = [
    {"name": "pii-protection", "type": "pii", "enabled": True},
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


def _validate_policy_config(cfg: dict) -> list[str]:
    """Validate a single policy config dict. Returns list of errors (empty = valid)."""
    from aiwarden.policies.builtin import BUILTIN_POLICY_TYPES

    errors = []
    if not isinstance(cfg, dict):
        errors.append(f"expected dict, got {type(cfg).__name__}")
        return errors
    if "name" not in cfg:
        errors.append("missing required key 'name'")
    if "type" not in cfg:
        errors.append("missing required key 'type'")
    else:
        policy_type = cfg["type"]
        if policy_type != "module" and policy_type not in BUILTIN_POLICY_TYPES:
            errors.append(f"unknown type '{policy_type}' — valid: {sorted(BUILTIN_POLICY_TYPES.keys())} + 'custom'")
        if policy_type == "module" and "module" not in cfg:
            errors.append("type 'module' requires a 'module' key with Python import path (e.g. 'my_app.policies.MyPolicy')")
    if "priority" in cfg and not isinstance(cfg["priority"], int):
        errors.append(f"priority must be int, got {type(cfg['priority']).__name__}")
    return errors


def _import_custom_class(module_path: str):
    """
    Import a Policy class from a dotted module path.
    Supports: 'my_app.policies.RateLimitPolicy' (module.ClassName)
    Import is cached by Python — no repeated overhead after first load.
    """
    import importlib
    parts = module_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(f"module path must be 'module.ClassName', got '{module_path}'")
    module_name, class_name = parts
    mod = importlib.import_module(module_name)
    cls = getattr(mod, class_name)
    from aiwarden.policies.base import Policy
    if not (isinstance(cls, type) and issubclass(cls, Policy)):
        raise TypeError(f"'{module_path}' is not a Policy subclass")
    return cls


def _build(policy_configs: list[dict]) -> list[Policy]:
    from aiwarden.policies.builtin import BUILTIN_POLICY_TYPES

    policies = []
    for cfg in policy_configs:
        if cfg is None:
            continue
        if not cfg.get("enabled", True):
            continue

        validation_errors = _validate_policy_config(cfg)
        if validation_errors:
            policy_name = cfg.get("name", "<unnamed>") if isinstance(cfg, dict) else "<invalid>"
            for err in validation_errors:
                log.warning("[aiwarden] policy '%s' config error: %s — skipping", policy_name, err)
            continue

        policy_type = cfg["type"]

        if policy_type == "module":
            try:
                cls = _import_custom_class(cfg["module"])
                policies.append(cls(cfg))
                log.debug("[aiwarden] loaded custom policy: %s (%s) priority=%d",
                         cfg.get("name"), cfg["module"], cfg.get("priority", 100))
            except Exception as e:
                log.error("[aiwarden] failed to load custom policy '%s' from '%s': %s",
                         cfg.get("name"), cfg.get("module"), e)
            continue

        cls = BUILTIN_POLICY_TYPES[policy_type]
        try:
            policies.append(cls(cfg))
            log.debug("[aiwarden] loaded policy: %s (%s) priority=%d",
                     cfg.get("name"), policy_type, cfg.get("priority", 100))
        except Exception as e:
            log.error("[aiwarden] failed to init policy '%s': %s", cfg.get("name"), e)

    return policies
