import logging
from typing import Optional

from aiwarden.pipeline.base import Block, PostProcessor, PreProcessor

log = logging.getLogger(__name__)


class Pipeline:
    """
    Manages a chain of pre- and post-processors that run in the request/response path.

    Pre-processors  run serially BEFORE the LLM API call.
    Post-processors run serially AFTER the LLM API call, before the agent gets the response.

    Usage:
        from aiwarden.pipeline import pipeline
        pipeline.add_pre(MemoryInjectProcessor())
        pipeline.add_post(GuardrailProcessor())
    """

    def __init__(self):
        self._pre:  list[PreProcessor]  = []
        self._post: list[PostProcessor] = []

    def add_pre(self, p: PreProcessor) -> "Pipeline":
        self._pre.append(p)
        return self

    def add_post(self, p: PostProcessor) -> "Pipeline":
        self._post.append(p)
        return self

    def run_pre(self, request: dict) -> tuple[dict, Optional[Block]]:
        """
        Run all pre-processors in order.
        Returns (modified_request, None)  on success.
        Returns (request, Block)          if any processor blocks the request.
        Processor errors are logged and skipped — never crash the agent.
        """
        for processor in self._pre:
            try:
                request, block = processor.process(request)
                if block:
                    log.info(
                        f"Request blocked by {processor.__class__.__name__}: {block.reason}"
                    )
                    return request, block
            except Exception as e:
                log.error(f"PreProcessor {processor.__class__.__name__} error: {e}")
        return request, None

    def run_post(self, request: dict, response: object) -> object:
        """
        Run all post-processors in order.
        Returns (possibly modified) response.
        Processor errors are logged and skipped — original response preserved.
        """
        for processor in self._post:
            try:
                response = processor.process(request, response)
            except Exception as e:
                log.error(f"PostProcessor {processor.__class__.__name__} error: {e}")
        return response
