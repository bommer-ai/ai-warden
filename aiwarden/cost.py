"""
Token-based cost computation.

Pricing is loaded from (in priority order):
  1. AIWARDEN_PRICING_FILE env var (YAML file with {model: {prompt, completion}})
  2. Hardcoded defaults below

To override pricing without code changes, create a YAML file:

    # custom_pricing.yaml
    gpt-4o: {prompt: 0.005, completion: 0.015}
    claude-sonnet-4-6: {prompt: 0.003, completion: 0.015}

Then: export AIWARDEN_PRICING_FILE=./custom_pricing.yaml

NOTE: Hardcoded prices become stale when providers change pricing.
Override with AIWARDEN_PRICING_FILE for accurate cost tracking.
"""
import logging
import os
import re as _re
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_PRICING = {
    # OpenAI
    "gpt-4o":                        {"prompt": 0.005,    "completion": 0.015},
    "gpt-4o-mini":                   {"prompt": 0.00015,  "completion": 0.0006},
    "gpt-4-turbo":                   {"prompt": 0.01,     "completion": 0.03},

    # Anthropic
    "claude-3-5-sonnet-20241022":    {"prompt": 0.003,    "completion": 0.015},
    "claude-3-5-haiku-20241022":     {"prompt": 0.0008,   "completion": 0.004},
    "claude-3-opus-20240229":        {"prompt": 0.015,    "completion": 0.075},
    "claude-opus-4-5":               {"prompt": 0.015,    "completion": 0.075},
    "claude-sonnet-4-5":             {"prompt": 0.003,    "completion": 0.015},
    "claude-haiku-4-5-20251001":     {"prompt": 0.0008,   "completion": 0.004},
    "claude-3-5-sonnet":             {"prompt": 0.003,    "completion": 0.015},
    "claude-3-5-haiku":              {"prompt": 0.0008,   "completion": 0.004},
    "claude-opus-4-6":               {"prompt": 0.015,    "completion": 0.075},
    "claude-sonnet-4-6":             {"prompt": 0.003,    "completion": 0.015},
}

PRICING: dict = {}


def _load_pricing() -> dict:
    """Load pricing from env-var file or fall back to hardcoded defaults."""
    pricing_file = os.getenv("AIWARDEN_PRICING_FILE")
    if pricing_file:
        path = Path(pricing_file)
        if path.exists():
            try:
                import yaml
                with open(path) as f:
                    custom = yaml.safe_load(f) or {}
                if isinstance(custom, dict):
                    log.debug("[aiwarden] loaded custom pricing from %s (%d models)", path, len(custom))
                    merged = {**_DEFAULT_PRICING, **custom}
                    return merged
            except Exception as e:
                log.warning("[aiwarden] failed to load pricing from %s: %s — using defaults", path, e)
        else:
            log.warning("[aiwarden] AIWARDEN_PRICING_FILE=%s not found — using defaults", pricing_file)
    return dict(_DEFAULT_PRICING)


def set_pricing(model: str, prompt: float, completion: float):
    """Override pricing for a model at runtime."""
    _ensure_loaded()
    PRICING[model] = {"prompt": prompt, "completion": completion}


def _ensure_loaded():
    global PRICING
    if not PRICING:
        PRICING = _load_pricing()


def _normalize(model: str) -> str:
    """
    Strip provider/region/version prefixes so lookups are prefix-agnostic.
    'bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0' → 'claude-haiku-4-5-20251001'
    """
    if "/" in model:
        model = model.split("/", 1)[1]
    for region_prefix in ("us.", "eu.", "ap."):
        if model.startswith(region_prefix):
            model = model[len(region_prefix):]
    model = _re.sub(r"-v\d+(?::\d+)?$", "", model)
    model = _re.sub(r":\d+$", "", model)
    if "." in model:
        model = model.split(".", 1)[1]
    return model


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    _ensure_loaded()
    prices = PRICING.get(model) or PRICING.get(_normalize(model), {"prompt": 0.0, "completion": 0.0})
    return round(
        (prompt_tokens / 1000 * prices["prompt"]) +
        (completion_tokens / 1000 * prices["completion"]),
        6
    )
