PRICING = {
    # OpenAI
    "gpt-4o":                        {"prompt": 0.005,    "completion": 0.015},
    "gpt-4o-mini":                   {"prompt": 0.00015,  "completion": 0.0006},
    "gpt-4-turbo":                   {"prompt": 0.01,     "completion": 0.03},

    # Anthropic — model IDs as returned by the API
    "claude-3-5-sonnet-20241022":    {"prompt": 0.003,    "completion": 0.015},
    "claude-3-5-haiku-20241022":     {"prompt": 0.0008,   "completion": 0.004},
    "claude-3-opus-20240229":        {"prompt": 0.015,    "completion": 0.075},
    "claude-opus-4-5":               {"prompt": 0.015,    "completion": 0.075},
    "claude-sonnet-4-5":             {"prompt": 0.003,    "completion": 0.015},
    "claude-haiku-4-5-20251001":     {"prompt": 0.0008,   "completion": 0.004},
    # short aliases used in config
    "claude-3-5-sonnet":             {"prompt": 0.003,    "completion": 0.015},
    "claude-3-5-haiku":              {"prompt": 0.0008,   "completion": 0.004},
    "claude-opus-4-6":               {"prompt": 0.015,    "completion": 0.075},
    "claude-sonnet-4-6":             {"prompt": 0.003,    "completion": 0.015},
}

def _normalize(model: str) -> str:
    """Strip provider prefix and cross-region prefix so lookups are prefix-agnostic.
    'bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0' → 'claude-haiku-4-5-20251001'
    """
    # strip provider prefix (bedrock/, openai/, etc.)
    if "/" in model:
        model = model.split("/", 1)[1]
    # strip cross-region prefix (us., eu., ap.)
    for region_prefix in ("us.", "eu.", "ap."):
        if model.startswith(region_prefix):
            model = model[len(region_prefix):]
    # strip AWS Bedrock version suffix ('-v1:0', '-v1', ':0', etc.)
    import re as _re
    model = _re.sub(r"-v\d+(?::\d+)?$", "", model)  # trailing -v1 or -v1:0
    model = _re.sub(r":\d+$", "", model)             # trailing :0
    # strip model-vendor prefix (anthropic., meta., amazon., etc.)
    if "." in model:
        model = model.split(".", 1)[1]
    return model


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prices = PRICING.get(model) or PRICING.get(_normalize(model), {"prompt": 0.0, "completion": 0.0})
    return round(
        (prompt_tokens    / 1000 * prices["prompt"]) +
        (completion_tokens / 1000 * prices["completion"]),
        6
    )
