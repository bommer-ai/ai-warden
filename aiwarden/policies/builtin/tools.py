import logging
from typing import Optional

from aiwarden.policies.base import Block, Policy, PolicyViolationError
from aiwarden.policies.builtin.tools_rules import (
    BUILTIN_TEMPLATES,
    PolicyRule,
    _parse_rule,
    matches,
)

log = logging.getLogger(__name__)


class ToolsPolicy(Policy):
    """
    Intercepts tool_use blocks in LLM responses before the agent executes them.

    Supports:
      - Built-in templates (filesystem-safety, no-privilege-escalation, etc.)
      - Custom YAML rules (match on tool name, args, metadata)
      - Actions: refusal (agent loop continues), interrupt (loop breaks), warn (log only)

    Config (from policies.yaml):
        builtin:
          filesystem-safety: true
          no-privilege-escalation: true
        rules:
          - name: no-delete-home
            action: refusal
            match:
              tool: delete_file
              path:
                startswith: "/Users/anoop.bansal"
    """

    name          = "tool-safety"
    default_hooks = ["post"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._rules: list[PolicyRule] | None = None

    def post(self, request: dict, response: object) -> object:
        if self._rules is None:
            self._rules = self._load_rules()

        if not self._rules:
            return response

        metadata = request.get("metadata") or {}

        for block in getattr(response, "content", []):
            if getattr(block, "type", "") != "tool_use":
                continue

            tool_name  = getattr(block, "name", "")
            tool_input = getattr(block, "input", {}) or {}

            for rule in self._rules:
                if not matches(rule, tool_name, tool_input, metadata):
                    continue

                msg = rule.message or f"Policy '{rule.name}' blocked tool '{tool_name}'"
                log.info("[aiwarden] tools-policy '%s' matched '%s' action=%s", rule.name, tool_name, rule.action)

                if rule.action == "interrupt":
                    raise PolicyViolationError(msg)

                if rule.action == "refusal":
                    request["_policy_blocked"] = True
                    request["_blocked_rule"]   = rule.name
                    request["_blocked_tool"]   = tool_name
                    request["_blocked_input"]  = tool_input
                    return _refusal_response(response, msg)

                if rule.action == "warn":
                    log.warning("[aiwarden] POLICY WARN — %s (tool: %s)", msg, tool_name)

        return response

    def _load_rules(self) -> list[PolicyRule]:
        rules = []

        # built-in templates
        for name, enabled in (self.config.get("builtin") or {}).items():
            if enabled and name in BUILTIN_TEMPLATES:
                rules.extend(BUILTIN_TEMPLATES[name])

        # custom rules from config
        for raw in self.config.get("rules") or []:
            try:
                rules.append(_parse_rule(raw))
            except Exception as e:
                log.warning("[aiwarden] skipping invalid tool rule: %s", e)

        return rules


def _refusal_response(original, message: str):
    try:
        from anthropic.types import TextBlock
        return original.model_copy(update={
            "content":     [TextBlock(type="text", text=message)],
            "stop_reason": "end_turn",
        })
    except Exception as e:
        log.error("[aiwarden] could not build refusal response: %s", e)
        return original
