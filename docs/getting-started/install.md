# Installation

```bash
pip install aiwarden
```

That's it. On import, ai-warden auto-patches any installed LLM SDKs (Anthropic, OpenAI).

## Verify

```python
python -c "import aiwarden; print('ai-warden active')"
```

## Optional: disable auto-patching

```bash
export AIWARDEN_ENABLED=false
```

## Configuration (all optional)

| Env var | Default | Purpose |
|---------|---------|---------|
| `AIWARDEN_ENABLED` | `true` | Kill switch |
| `AIWARDEN_DEBUG` | `false` | Print events to stdout |
| `AIWARDEN_LOG_FILE` | `~/.aiwarden/events.jsonl` | Event output path |
| `AIWARDEN_AGENT_NAME` | `default` | Default agent name for policy scoping |
| `AIWARDEN_PRICING_FILE` | — | Custom pricing YAML |
| `AIWARDEN_CALLER_TRACKING` | `true` | Stack-walk for caller attribution |
