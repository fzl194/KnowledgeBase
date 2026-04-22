"""LLM provider interfaces — pluggable LLM-backed providers for each pipeline stage.

v1.2: LLMNormalizerProvider now uses LLMRuntimeClient.execute() for real calls.
LLMRerankerProvider remains as future slot.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from agent_serving.serving.schemas.models import (
    EntityRef,
    NormalizedQuery,
    QueryPlan,
    RetrievalCandidate,
)
from agent_serving.serving.schemas.constants import INTENT_GENERAL

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM runtime client (backward compat)."""

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "default",
        temperature: float = 0.0,
        max_tokens: int = 512,
    ) -> str: ...

    def is_available(self) -> bool: ...


class LLMNormalizerProvider:
    """LLM-backed query normalization provider.

    v1.2: Uses LLMRuntimeClient.execute() with pipeline_stage="normalizer".
    Sends query for structured extraction: intent, entities, scope, keywords.
    Falls back to rule-based when LLM is unavailable.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    def set_llm_client(self, client: Any) -> None:
        self._llm = client

    async def normalize(self, query: str) -> NormalizedQuery | None:
        """Attempt LLM normalization. Returns None if unavailable."""
        if not self._llm:
            return None
        try:
            return await self._try_llm_normalize(query)
        except Exception:
            logger.warning("LLM normalization failed", exc_info=True)
            return None

    async def _try_llm_normalize(self, query: str) -> NormalizedQuery | None:
        """Call LLM runtime for structured query understanding."""
        from agent_serving.serving.application.planner import LLMRuntimeClient

        client = self._llm
        if not isinstance(client, LLMRuntimeClient):
            return None

        result = await client.execute(
            pipeline_stage="normalizer",
            template_key="serving-query-understanding",
            input={"query": query},
            expected_output_type="json_object",
        )

        parsed = result.get("parsed_output", {})
        if not parsed:
            return None

        entities = []
        for e in parsed.get("entities", []):
            entities.append(EntityRef(
                type=e.get("type", "unknown"),
                name=e.get("name", ""),
                normalized_name=e.get("normalized_name", e.get("name", "")),
            ))

        return NormalizedQuery(
            original_query=query,
            intent=parsed.get("intent", INTENT_GENERAL),
            entities=entities,
            scope=parsed.get("scope", {}),
            keywords=parsed.get("keywords", []),
            desired_roles=[],
        )


class LLMRerankerProvider:
    """LLM-backed reranking provider (future slot).

    When available, sends candidates to LLM for relevance scoring.
    Falls back to score-based reranker when LLM is unavailable.
    """

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    def set_llm_client(self, client: Any) -> None:
        self._llm = client

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate] | None:
        """Attempt LLM reranking. Returns None if unavailable."""
        if not self._llm:
            return None
        try:
            return await self._try_llm_rerank(candidates, plan)
        except Exception:
            logger.warning("LLM reranking failed", exc_info=True)
            return None

    async def _try_llm_rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate] | None:
        """Future: send candidates to LLM for relevance scoring."""
        return None
