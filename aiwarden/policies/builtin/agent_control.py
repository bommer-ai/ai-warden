"""
Agent control policy — per-session/run enforcement.

Governs the RUN itself (not individual tools — that's the tools policy's job):
  - Max turns (LLM calls per run)
  - Max cost per run
  - Max duration (seconds)
  - Loop detection (same tool called N times consecutively)

Works in both hot mode (aiwarden.run()) and patcher-only mode since it reads
from RunState which exists in both.

Config example:
    - name: agent-limits
      type: agent_control
      agents: ["chatbot"]
      max_turns: 25
      max_cost: 5.00
      max_duration: 300
      max_tool_repeats: 3
"""
import logging
import time
from typing import Optional

from aiwarden.policies.base import Block, Policy, Warn

log = logging.getLogger(__name__)


class AgentControlPolicy(Policy):
    """
    Per-session control policy. Enforces run-level limits.

    Reads from RunState (live counter) — works identically in hot mode
    and patcher-only mode.

    Responsibilities:
      - How many calls can this run make? (max_turns)
      - How much can this run spend? (max_cost)
      - How long can this run take? (max_duration)
      - Is the agent stuck in a loop? (max_tool_repeats)

    Does NOT handle:
      - Which tools are allowed/blocked → use 'tools' policy
      - What arguments are safe → use 'tools' policy
    """

    name          = "agent-control"
    priority      = 15
    default_hooks = ["pre", "post"]

    def __init__(self, config: dict = None):
        super().__init__(config)
        self._max_turns = self.config.get("max_turns", 0)
        self._max_cost = self.config.get("max_cost", 0.0)
        self._max_duration = self.config.get("max_duration", 0)
        self._max_tool_repeats = self.config.get("max_tool_repeats", 0)

    def pre(self, request: dict) -> tuple[dict, Optional[Block | Warn]]:
        from aiwarden.session import _current_run
        state = _current_run.get()
        if state is None:
            return request, None

        # Max turns
        if self._max_turns and state.turn >= self._max_turns:
            return request, Block(
                f"Agent exceeded max turns: {state.turn}/{self._max_turns}"
            )

        # Max cost
        if self._max_cost and state.total_cost >= self._max_cost:
            return request, Block(
                f"Agent exceeded max cost per run: ${state.total_cost:.4f}/${self._max_cost:.2f}"
            )

        # Max duration
        if self._max_duration:
            elapsed = time.monotonic() - state.start_time
            if elapsed >= self._max_duration:
                return request, Block(
                    f"Agent exceeded max duration: {elapsed:.0f}s/{self._max_duration}s"
                )

        # Warn at 80% of limits
        if self._max_turns and state.turn >= self._max_turns * 0.8:
            return request, Warn(
                f"Agent approaching turn limit: {state.turn}/{self._max_turns}"
            )
        if self._max_cost and state.total_cost >= self._max_cost * 0.8:
            return request, Warn(
                f"Agent approaching cost limit: ${state.total_cost:.4f}/${self._max_cost:.2f}"
            )

        return request, None

    def post(self, request: dict, response: object) -> object:
        """Detect tool loops — same tool called N times consecutively."""
        if not self._max_tool_repeats:
            return response

        from aiwarden.session import _current_run
        state = _current_run.get()
        if state is None:
            return response

        tool_calls = self._extract_tools(response)
        if not tool_calls:
            return response

        for tool_name in tool_calls:
            recent = state.tools_called[-self._max_tool_repeats:] if state.tools_called else []
            if len(recent) >= self._max_tool_repeats and all(t == tool_name for t in recent):
                log.info("[aiwarden] agent-control: loop detected — '%s' x%d", tool_name, self._max_tool_repeats + 1)
                return self._refusal(response, f"Tool '{tool_name}' called {self._max_tool_repeats} times consecutively — possible loop detected")

        return response

    def _extract_tools(self, response) -> list[str]:
        """Extract tool names from response (Anthropic or OpenAI format)."""
        tools = []
        if hasattr(response, "content") and not hasattr(response, "choices"):
            for block in getattr(response, "content", []):
                if getattr(block, "type", "") == "tool_use":
                    tools.append(getattr(block, "name", ""))
        elif hasattr(response, "choices"):
            try:
                msg = response.choices[0].message
                for tc in getattr(msg, "tool_calls", None) or []:
                    tools.append(tc.function.name)
            except (IndexError, AttributeError):
                pass
        return tools

    def _refusal(self, response, message: str):
        """Build a refusal response (provider-agnostic)."""
        from types import SimpleNamespace as NS

        if hasattr(response, "model_copy"):
            try:
                from anthropic.types import TextBlock
                return response.model_copy(update={
                    "content": [TextBlock(type="text", text=message)],
                    "stop_reason": "end_turn",
                })
            except Exception:
                pass

        if hasattr(response, "choices"):
            return NS(
                choices=[NS(message=NS(content=message, tool_calls=None), finish_reason="stop")],
                usage=getattr(response, "usage", None),
                model=getattr(response, "model", ""),
            )

        if hasattr(response, "content"):
            return NS(
                content=[NS(type="text", text=message)],
                stop_reason="end_turn",
                usage=getattr(response, "usage", None),
                model=getattr(response, "model", ""),
            )

        return response
