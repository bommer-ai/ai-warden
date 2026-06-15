"""
Auto-runs via aiwarden.pth before any user code.
Patches LLM SDKs silently when enabled.
"""
from aiwarden import config


def _patch_openai():
    try:
        import openai
        from aiwarden.patchers.openai import patch
        patch(openai)
        if config.DEBUG:
            print("[aiwarden] openai patched")
    except ImportError:
        pass


def _patch_anthropic():
    try:
        import anthropic
        from aiwarden.patchers.anthropic import patch
        patch(anthropic)
        if config.DEBUG:
            print("[aiwarden] anthropic patched")
    except ImportError:
        pass


def _run():
    if not config.ENABLED:
        return
    _patch_openai()
    _patch_anthropic()


_run()
