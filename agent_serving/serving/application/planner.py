"""LLM Runtime client — thin wrapper over agent_llm_runtime.

Serving calls LLM through this client for all pipeline stages.
All audit and logging goes to agent_llm_runtime, not Serving's own tables.

This client implements the LLMClient protocol defined in pipeline/llm_providers.py.
When the runtime service is not configured, is_available() returns False
and all pipeline stages fall back to their rule-based defaults.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMRuntimeClient:
    """Client for LLM calls via agent_llm_runtime service.

    Configuration:
    - Set via environment variables or app init
    - Does NOT directly access runtime DB
    - Calls runtime service API when available
    """

    def __init__(self, endpoint: str | None = None, api_key: str | None = None) -> None:
        self._endpoint = endpoint
        self._api_key = api_key

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "default",
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str:
        """Call LLM via agent_llm_runtime service.

        For v1.1, this returns empty string when runtime is not configured.
        Real implementation will call the runtime service API.
        """
        if not self.is_available():
            return ""

        # Future: HTTP call to agent_llm_runtime service
        # POST /api/v1/tasks with structured prompt
        logger.info("LLM complete called: model=%s", model)
        return ""

    def is_available(self) -> bool:
        """Check if LLM runtime service is configured and reachable."""
        return self._endpoint is not None
