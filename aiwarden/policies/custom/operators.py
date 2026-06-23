"""
Operator definitions and value matching for custom policies.

Each operator is a pure function: (value, pattern) → bool.
All operators are registered in the Operator enum and VALID_OPERATORS set.
"""
import logging
import re
from enum import Enum

log = logging.getLogger(__name__)


class Operator(str, Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTSWITH = "startswith"
    NOT_STARTSWITH = "not_startswith"
    ENDSWITH = "endswith"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    IN = "in"
    NOT_IN = "not_in"
    REGEX = "regex"
    GT = "gt"
    LT = "lt"
    GTE = "gte"
    LTE = "lte"


VALID_OPERATORS = frozenset(op.value for op in Operator)


def match_value(value, matchers: dict) -> bool:
    """
    Apply all operators to a value. All must pass (AND logic).
    Returns False immediately on unknown operator (fail-safe).
    """
    str_value = str(value) if value is not None else ""

    for op, pattern in matchers.items():
        if op not in VALID_OPERATORS:
            log.warning("[aiwarden] unknown operator '%s' — fail-safe, rule won't match", op)
            return False

        if op == Operator.CONTAINS:
            if str(pattern) not in str_value:
                return False
        elif op == Operator.NOT_CONTAINS:
            if str(pattern) in str_value:
                return False
        elif op == Operator.STARTSWITH:
            patterns = pattern if isinstance(pattern, list) else [pattern]
            if not any(str_value.startswith(str(p)) for p in patterns):
                return False
        elif op == Operator.NOT_STARTSWITH:
            patterns = pattern if isinstance(pattern, list) else [pattern]
            if any(str_value.startswith(str(p)) for p in patterns):
                return False
        elif op == Operator.ENDSWITH:
            patterns = pattern if isinstance(pattern, list) else [pattern]
            if not any(str_value.endswith(str(p)) for p in patterns):
                return False
        elif op == Operator.EQUALS:
            if str_value != str(pattern):
                return False
        elif op == Operator.NOT_EQUALS:
            if str_value == str(pattern):
                return False
        elif op == Operator.IN:
            if str_value not in [str(p) for p in pattern]:
                return False
        elif op == Operator.NOT_IN:
            if str_value in [str(p) for p in pattern]:
                return False
        elif op == Operator.REGEX:
            if not re.search(str(pattern), str_value):
                return False
        elif op == Operator.GT:
            try:
                if not (float(value) > float(pattern)):
                    return False
            except (TypeError, ValueError):
                return False
        elif op == Operator.LT:
            try:
                if not (float(value) < float(pattern)):
                    return False
            except (TypeError, ValueError):
                return False
        elif op == Operator.GTE:
            try:
                if not (float(value) >= float(pattern)):
                    return False
            except (TypeError, ValueError):
                return False
        elif op == Operator.LTE:
            try:
                if not (float(value) <= float(pattern)):
                    return False
            except (TypeError, ValueError):
                return False
    return True
