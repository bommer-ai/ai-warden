import re
from typing import Optional

from aiwarden.pipeline.base import Block, PreProcessor

PATTERNS: dict[str, re.Pattern] = {
    "email":   re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone":   re.compile(r"\b(\+?1?\s?)?(\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4})\b"),
    "ssn":     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "api_key": re.compile(r"\bsk-[a-zA-Z0-9]{20,}\b"),
    "cc":      re.compile(r"\b(?:\d[ -]?){13,16}\b"),
}


def redact(text: str) -> tuple[str, list[str]]:
    """Returns (redacted_text, list_of_pii_types_found)."""
    if not isinstance(text, str):
        return text, []
    found = []
    for pii_type, pattern in PATTERNS.items():
        if pattern.search(text):
            found.append(pii_type)
            text = pattern.sub(f"[REDACTED:{pii_type}]", text)
    return text, found


def redact_messages(messages: list) -> tuple[list, list[str]]:
    """Redact PII from all message contents. Returns (clean_messages, pii_types)."""
    clean   = []
    all_pii: set[str] = set()

    for msg in messages:
        content = msg.get("content", "")

        if isinstance(content, str):
            clean_content, found = redact(content)
            all_pii.update(found)
            clean.append({**msg, "content": clean_content})

        elif isinstance(content, list):
            clean_blocks = []
            for block in content:
                block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
                if block_type == "text":
                    raw = block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
                    clean_text, found = redact(raw)
                    all_pii.update(found)
                    clean_blocks.append(
                        {**block, "text": clean_text} if isinstance(block, dict) else block
                    )
                else:
                    clean_blocks.append(block)
            clean.append({**msg, "content": clean_blocks})
        else:
            clean.append(msg)

    return clean, list(all_pii)


class PIIRedactPreProcessor(PreProcessor):
    """
    Redacts PII from input messages and system prompt before they reach the LLM.
    Stores found PII types in request metadata so _emit can record them.
    """

    def process(self, request: dict) -> tuple[dict, Optional[Block]]:
        messages = request.get("messages", [])
        clean_messages, pii_found = redact_messages(messages)

        system = request.get("system", "")
        if system:
            system, sys_pii = redact(system)
            pii_found.extend(sys_pii)

        return {
            **request,
            "messages": clean_messages,
            **({"system": system} if system else {}),
            # stash for _emit to pick up — not sent to the API
            "_pii_found": list(set(pii_found)),
        }, None
