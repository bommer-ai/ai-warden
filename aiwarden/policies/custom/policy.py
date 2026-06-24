"""
CustomPolicy — the declarative policy class.

Loads rules from YAML config, separates into pre/post,
evaluates on every LLM call. No user code needed.
"""
import logging
from typing import Optional

from aiwarden.policies.base import Block, Policy, PolicyViolationError, Warn
from aiwarden.policies.custom.resolver import evaluate_rule
from aiwarden.policies.custom.schema import (
    Action,
    CustomRule,
    Hook,
    parse_rule,
    validate_rule,
)

log = logging.getLogger(__name__)


class CustomPolicy(Policy):
    """
    Declarative custom policy. Users define rules in YAML — no code required.

    Pre-rules match on request fields (model, messages, metadata, max_tokens).
    Post-rules match on response fields (content, tokens, finish_reason).

    YAML type: "custom"
    """

    name          = "custom"
    priority      = 20
    default_hooks = ["pre", "post"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        if "name" in self.config:
            self.name = self.config["name"]
        self._pre_rules: list[CustomRule] = []
        self._post_rules: list[CustomRule] = []
        self._load_rules()

    def _load_rules(self):
        raw_rules = self.config.get("rules", [])
        for raw in raw_rules:
            if raw is None:
                continue
            errors = validate_rule(raw)
            if errors:
                rule_name = raw.get("name", "<unnamed>") if isinstance(raw, dict) else "<invalid>"
                for err in errors:
                    log.warning("[aiwarden] custom rule '%s' validation error: %s — skipping", rule_name, err)
                continue
            rule = parse_rule(raw)
            if rule.hook == Hook.PRE:
                self._pre_rules.append(rule)
            else:
                self._post_rules.append(rule)

        log.debug("[aiwarden] CustomPolicy '%s': %d pre-rules, %d post-rules",
                 self.name, len(self._pre_rules), len(self._post_rules))

    def pre(self, request: dict) -> tuple[dict, Optional[Block | Warn]]:
        for rule in self._pre_rules:
            if evaluate_rule(rule, request):
                msg = rule.message or f"Rule '{rule.name}' triggered"
                log.info("[aiwarden] rule '%s' fired (pre, %s): %s", rule.name, rule.action.value, msg)
                if rule.action == Action.BLOCK:
                    return request, Block(msg)
                elif rule.action == Action.WARN:
                    return request, Warn(msg)
        return request, None

    def post(self, request: dict, response: object) -> object:
        if not self._post_rules:
            return response

        data = dict(request)
        data["_content"] = self._extract_text(response)
        data["_completion_tokens"] = self._extract_tokens(response, "completion")
        data["_prompt_tokens"] = self._extract_tokens(response, "prompt")
        data["_finish_reason"] = self._extract_finish_reason(response)

        for rule in self._post_rules:
            if evaluate_rule(rule, data):
                msg = rule.message or f"Rule '{rule.name}' triggered"
                log.info("[aiwarden] rule '%s' fired (post, %s): %s", rule.name, rule.action.value, msg)
                if rule.action == Action.BLOCK:
                    raise PolicyViolationError(msg)
                elif rule.action == Action.WARN:
                    return response, Warn(msg)
        return response

    def _extract_text(self, response) -> str:
        if hasattr(response, "content") and not hasattr(response, "choices"):
            return "".join(
                getattr(b, "text", "")
                for b in getattr(response, "content", [])
                if getattr(b, "type", "") == "text"
            )
        if hasattr(response, "choices"):
            try:
                return getattr(response.choices[0].message, "content", "") or ""
            except (IndexError, AttributeError):
                pass
        return ""

    def _extract_tokens(self, response, which: str) -> int:
        usage = getattr(response, "usage", None)
        if not usage:
            return 0
        if which == "completion":
            return getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
        return getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0

    def _extract_finish_reason(self, response) -> str:
        if hasattr(response, "stop_reason"):
            return getattr(response, "stop_reason", "") or ""
        if hasattr(response, "choices"):
            try:
                return getattr(response.choices[0], "finish_reason", "") or ""
            except (IndexError, AttributeError):
                pass
        return ""
