"""LLM Runtime client — thin wrapper over llm_service.

v1.2: Wraps llm_service.client.LLMClient for synchronous execute calls.
Serving calls LLM through this client for all pipeline stages.
When the runtime service is not configured, is_available() returns False
and all pipeline stages fall back to their rule-based defaults.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LLMRuntimeClient:
    """Serving's unified LLM Runtime access.

    Wraps llm_service.client.LLMClient for synchronous pipeline calls.
    The underlying client handles HTTP communication, retries, and audit.
    """

    def __init__(self, base_url: str = "http://localhost:8900") -> None:
        self._base_url = base_url
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init the underlying LLMClient."""
        if self._client is None:
            try:
                from llm_service.client import LLMClient
                self._client = LLMClient(base_url=self._base_url)
            except ImportError:
                logger.warning("llm_service not available, LLM calls disabled")
                return None
        return self._client

    async def execute(
        self,
        pipeline_stage: str,
        *,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        expected_output_type: str = "json_object",
    ) -> dict:
        """Execute a synchronous LLM call via the runtime service.

        Raises LLMCallError when the call fails or returns non-succeeded status.
        """
        client = self._get_client()
        if client is None:
            raise LLMCallError({"error": "llm_service not available"})

        result = await client.execute(
            caller_domain="serving",
            pipeline_stage=pipeline_stage,
            template_key=template_key,
            input=input,
            messages=messages,
            expected_output_type=expected_output_type,
        )

        if result.get("status") != "succeeded":
            raise LLMCallError(result.get("error", {"error": "unknown"}))

        return result.get("result", {})

    def is_available(self) -> bool:
        """Check if LLM runtime service is configured."""
        try:
            from llm_service.client import LLMClient
            return True
        except ImportError:
            return False


class LLMCallError(Exception):
    """Raised when an LLM call fails."""

    def __init__(self, detail: dict | str) -> None:
        self.detail = detail
        super().__init__(str(detail))
