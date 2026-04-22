"""LLM provider interfaces — pluggable LLM-backed providers for each pipeline stage.

Three provider slots:
- LLMNormalizerProvider: replaces rule-based normalizer when LLM is available
- LLMPlannerProvider: enriches QueryPlan via LLM (already in query_planner.py)
- LLMRerankerProvider: replaces score-based reranker with LLM ranking

All providers go through the unified LLM runtime client,
not direct model calls. When the runtime is unavailable,
each falls back to its rule-based default.
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

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Unified LLM runtime client interface.

    This is the contract that agent_llm_runtime must implement.
    Serving never imports runtime internals — only this protocol.
    """

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

    When available, sends the query to LLM for structured extraction:
    intent, entities, scope, keywords.
    Falls back to rule-based normalizer when LLM is unavailable.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client

    def set_llm_client(self, client: LLMClient) -> None:
        self._llm = client

    def normalize(self, query: str, fallback: Any = None) -> NormalizedQuery | None:
        """Attempt LLM normalization. Returns None if unavailable."""
        if not self._llm or not self._llm.is_available():
            return None
        try:
            return self._try_llm_normalize(query)
        except Exception:
            logger.warning("LLM normalization failed", exc_info=True)
            return None

    def _try_llm_normalize(self, query: str) -> NormalizedQuery | None:
        """Future: structured prompt → JSON NormalizedQuery.

        The prompt template will ask the LLM to extract:
        intent, entities, scope, keywords from the query.
        Response is parsed as JSON into NormalizedQuery.
        """
        # v1.1: not yet connected — requires agent_llm_runtime
        return None


class LLMRerankerProvider:
    """LLM-backed reranking provider.

    When available, sends candidates to LLM for relevance scoring.
    Falls back to score-based reranker when LLM is unavailable.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client

    def set_llm_client(self, client: LLMClient) -> None:
        self._llm = client

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate] | None:
        """Attempt LLM reranking. Returns None if unavailable."""
        if not self._llm or not self._llm.is_available():
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
        """Future: send candidates to LLM for relevance scoring.

        The prompt template will include the query intent and
        candidate texts, asking the LLM to score relevance.
        """
        # v1.1: not yet connected — requires agent_llm_runtime
        return None
