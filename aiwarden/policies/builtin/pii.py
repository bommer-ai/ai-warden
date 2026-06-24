"""
PII redaction policy.

Redacts personally identifiable information from messages before they reach the LLM.
Supports both built-in patterns and custom patterns defined in YAML.

Config example:
    - name: pii-protection
      type: pii
      enabled: true
      patterns:
        employee_id: "\\bEMP-\\d{6}\\b"      # add custom pattern
        internal_ip: "\\b10\\.\\d+\\.\\d+\\.\\d+\\b"
        cc: false                              # disable built-in credit card pattern
"""
import logging
import re
from typing import Optional

from aiwarden.policies.base import Block, Policy

log = logging.getLogger(__name__)

_BUILTIN_PATTERNS: dict[str, str] = {
    "email":   r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+",
    "phone":   r"\b(\+?1?\s?)?(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})\b",
    "ssn":     r"\b\d{3}-\d{2}-\d{4}\b",
    "api_key": r"\bsk-[a-zA-Z0-9]{20,}\b",
    "cc":      r"\b(?:\d[ -]?){13,16}\b",
}


class PIIPolicy(Policy):
    """
    Redacts PII from request messages and system prompt before sending to LLM.

    Patterns are compiled once at init time — zero regex compilation overhead per call.
    Custom patterns from YAML are merged with built-ins. Set a pattern to false to disable it.
    """

    name          = "pii-protection"
    priority      = 90
    default_hooks = ["pre"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._patterns: dict[str, re.Pattern] = self._compile_patterns()

    def _compile_patterns(self) -> dict[str, re.Pattern]:
        """Merge built-in + custom patterns, compile once at init."""
        custom = self.config.get("patterns", {}) or {}
        compiled = {}

        for pii_type, regex_str in _BUILTIN_PATTERNS.items():
            if custom.get(pii_type) is False:
                log.debug("[aiwarden] PII pattern '%s' disabled by config", pii_type)
                continue
            compiled[pii_type] = re.compile(regex_str)

        for pii_type, regex_str in custom.items():
            if pii_type in _BUILTIN_PATTERNS:
                continue  # already handled above (either kept or disabled)
            if regex_str is False:
                continue
            try:
                compiled[pii_type] = re.compile(str(regex_str))
                log.debug("[aiwarden] PII custom pattern added: '%s'", pii_type)
            except re.error as e:
                log.warning("[aiwarden] PII pattern '%s' has invalid regex: %s — skipping", pii_type, e)

        return compiled

    def pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        messages = request.get("messages", [])
        clean_messages, pii_found = self._redact_messages(messages)

        system = request.get("system", "")
        if system and isinstance(system, str):
            system, sys_pii = self._redact(system)
            pii_found.extend(sys_pii)

        return {
            **request,
            "messages": clean_messages,
            **({"system": system} if system else {}),
            "_pii_found": list(set(pii_found)),
        }, None

    def post(self, request: dict, response: object) -> object:
        return response

    def _redact(self, text: str) -> tuple[str, list[str]]:
        if not isinstance(text, str):
            return text, []
        found = []
        for pii_type, pattern in self._patterns.items():
            result = pattern.sub(f"[REDACTED:{pii_type}]", text)
            if result != text:
                found.append(pii_type)
                text = result
        return text, found

    def _redact_messages(self, messages: list) -> tuple[list, list[str]]:
        clean: list = []
        all_pii: list[str] = []

        for msg in messages:
            content = msg.get("content", "")

            if isinstance(content, str):
                clean_content, found = self._redact(content)
                all_pii.extend(found)
                clean.append({**msg, "content": clean_content})

            elif isinstance(content, list):
                clean_blocks = []
                for block in content:
                    block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
                    if block_type == "text":
                        raw = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                        clean_text, found = self._redact(raw)
                        all_pii.extend(found)
                        clean_blocks.append(
                            {**block, "text": clean_text} if isinstance(block, dict) else block
                        )
                    else:
                        clean_blocks.append(block)
                clean.append({**msg, "content": clean_blocks})
            else:
                clean.append(msg)

        return clean, all_pii
