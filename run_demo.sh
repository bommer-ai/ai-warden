#!/usr/bin/env bash
cd "$(dirname "$0")"
export ANTHROPIC_API_KEY="$(~/.local/bin/get-litellm-key 2>/dev/null || true)"
export ANTHROPIC_BASE_URL="https://litellm.kumoroku.com"
export AIWARDEN_DEBUG="true"
export AIWARDEN_POLICY_FILE="$(pwd)/.aiwarden/policies.yaml"
exec uv run python /Users/anoop.bansal/llm-intercept-poc/tests/chatbot.py "$@"
