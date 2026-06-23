import logging
from types import SimpleNamespace
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

    Works with both Anthropic and OpenAI response formats by detecting
    the provider from the response structure.

    Actions: refusal (agent loop continues), interrupt (loop breaks), warn (log only)
    """

    name          = "tool-safety"
    priority      = 50
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
        tool_blocks = _extract_tool_calls(response)

        for tool_name, tool_input, block_ref in tool_blocks:
            for rule in self._rules:
                if not matches(rule, tool_name, tool_input, metadata):
                    continue

                msg = rule.message or f"Policy '{rule.name}' blocked tool '{tool_name}'"
                log.info("[aiwarden] tools-policy '%s' matched '%s' action=%s",
                        rule.name, tool_name, rule.action)

                if rule.action == "interrupt":
                    raise PolicyViolationError(msg)

                if rule.action == "refusal":
                    request["_policy_blocked"] = True
                    request["_blocked_rule"]   = rule.name
                    request["_blocked_tool"]   = tool_name
                    request["_blocked_input"]  = tool_input
                    return _build_refusal(response, msg)

                if rule.action == "warn":
                    log.warning("[aiwarden] POLICY WARN — %s (tool: %s)", msg, tool_name)

        return response

    def _load_rules(self) -> list[PolicyRule]:
        rules = []
        for name, enabled in (self.config.get("builtin") or {}).items():
            if enabled and name in BUILTIN_TEMPLATES:
                rules.extend(BUILTIN_TEMPLATES[name])
        for raw in self.config.get("rules") or []:
            try:
                rules.append(_parse_rule(raw))
            except Exception as e:
                log.warning("[aiwarden] skipping invalid tool rule: %s", e)
        return rules


def _extract_tool_calls(response) -> list[tuple[str, dict, object]]:
    """
    Extract tool calls from either Anthropic or OpenAI response format.
    Returns list of (tool_name, tool_input, block_reference).
    """
    results = []

    # Anthropic format: response.content = [{type: "tool_use", name, input}]
    if hasattr(response, "content") and not hasattr(response, "choices"):
        for block in getattr(response, "content", []):
            if getattr(block, "type", "") == "tool_use":
                results.append((
                    getattr(block, "name", ""),
                    getattr(block, "input", {}) or {},
                    block,
                ))
        return results

    # OpenAI format: response.choices[0].message.tool_calls = [{function: {name, arguments}}]
    if hasattr(response, "choices"):
        try:
            msg = response.choices[0].message
            for tc in getattr(msg, "tool_calls", None) or []:
                import json
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    args = {"raw": getattr(tc.function, "arguments", "")}
                results.append((tc.function.name, args, tc))
        except (IndexError, AttributeError):
            pass
        return results

    return results


def _build_refusal(original, message: str):
    """
    Build a refusal response that replaces tool_use with a text message.
    Handles both Anthropic (model_copy) and OpenAI (SimpleNamespace replacement) formats.
    """
    # Anthropic: has model_copy (Pydantic model)
    if hasattr(original, "model_copy"):
        try:
            from anthropic.types import TextBlock
            return original.model_copy(update={
                "content":     [TextBlock(type="text", text=message)],
                "stop_reason": "end_turn",
            })
        except Exception:
            pass

    # OpenAI: build a minimal replacement response
    if hasattr(original, "choices"):
        try:
            replacement = SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=message, tool_calls=None),
                    finish_reason="stop",
                )],
                usage=getattr(original, "usage", None),
                model=getattr(original, "model", ""),
            )
            return replacement
        except Exception:
            pass

    # Fallback: return original (shouldn't reach here)
    log.error("[aiwarden] could not build refusal response — returning original")
    return original
