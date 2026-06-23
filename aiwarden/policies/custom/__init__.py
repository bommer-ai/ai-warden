"""
Custom declarative policy engine — no-code policy creation via YAML or UI.

Usage in policies.yaml:
    - name: my-guardrails
      type: custom
      priority: 20
      rules:
        - name: no-gpt4-in-prod
          hook: pre
          action: block
          message: "GPT-4 not allowed in production"
          match:
            model:
              startswith: "gpt-4"
          when:
            metadata.environment: production
"""
from aiwarden.policies.custom.operators import Operator, VALID_OPERATORS, match_value
from aiwarden.policies.custom.policy import CustomPolicy
from aiwarden.policies.custom.resolver import evaluate_rule, resolve_field, check_when
from aiwarden.policies.custom.schema import (
    Action,
    CustomRule,
    Hook,
    VALID_ACTIONS,
    VALID_HOOKS,
    parse_rule,
    validate_rule,
)

__all__ = [
    "CustomPolicy",
    "CustomRule",
    "Action",
    "Hook",
    "Operator",
    "VALID_OPERATORS",
    "VALID_ACTIONS",
    "VALID_HOOKS",
    "validate_rule",
    "parse_rule",
    "match_value",
    "evaluate_rule",
    "resolve_field",
    "check_when",
]
