"""
Schema validation and rule dataclass for custom policies.

Validates rule configs at load time — catches errors early,
not at enforcement time when a request hits the policy.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum

from aiwarden.policies.custom.operators import VALID_OPERATORS

log = logging.getLogger(__name__)


class Action(str, Enum):
    BLOCK = "block"
    WARN = "warn"


class Hook(str, Enum):
    PRE = "pre"
    POST = "post"


VALID_ACTIONS = frozenset(a.value for a in Action)
VALID_HOOKS = frozenset(h.value for h in Hook)


@dataclass
class CustomRule:
    """A single declarative rule parsed from YAML config."""
    name: str
    action: Action
    message: str = ""
    hook: Hook = Hook.PRE
    match: dict = field(default_factory=dict)
    when: dict = field(default_factory=dict)


def validate_rule(raw: dict) -> list[str]:
    """Validate a single rule config. Returns list of error strings (empty = valid)."""
    errors = []
    if not isinstance(raw, dict):
        return [f"rule must be a dict, got {type(raw).__name__}"]

    if "name" not in raw:
        errors.append("missing 'name'")
    if "action" not in raw:
        errors.append("missing 'action'")
    elif raw["action"] not in VALID_ACTIONS:
        errors.append(f"invalid action '{raw['action']}' — must be: {sorted(VALID_ACTIONS)}")

    hook = raw.get("hook", Hook.PRE.value)
    if hook not in VALID_HOOKS:
        errors.append(f"invalid hook '{hook}' — must be: {sorted(VALID_HOOKS)}")

    match = raw.get("match", {})
    if not isinstance(match, dict):
        errors.append(f"'match' must be a dict, got {type(match).__name__}")
    else:
        for field_path, matchers in match.items():
            if not isinstance(matchers, dict):
                errors.append(f"match.{field_path}: value must be {{operator: value}}, got {type(matchers).__name__}")
                continue
            for op in matchers:
                if op not in VALID_OPERATORS:
                    errors.append(f"match.{field_path}: unknown operator '{op}' — valid: {sorted(VALID_OPERATORS)}")

    when = raw.get("when", {})
    if when and not isinstance(when, dict):
        errors.append(f"'when' must be a dict, got {type(when).__name__}")

    return errors


def parse_rule(raw: dict) -> CustomRule:
    """Parse a validated rule dict into a CustomRule dataclass."""
    return CustomRule(
        name=raw.get("name", "unnamed"),
        action=Action(raw.get("action", "warn")),
        message=raw.get("message", ""),
        hook=Hook(raw.get("hook", "pre")),
        match=raw.get("match", {}),
        when=raw.get("when", {}),
    )
