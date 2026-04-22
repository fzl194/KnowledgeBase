"""Reranker — post-retrieval reranking stage.

Default: score-based truncation with role/block_type preference.
Future: LLM reranker, cross-encoder reranker.
"""
from __future__ import annotations

import logging
from typing import Any

from agent_serving.serving.schemas.models import QueryPlan, RetrievalCandidate

logger = logging.getLogger(__name__)


class Reranker:
    """Abstract reranker interface."""

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        """Rerank and truncate candidates."""
        ...


class ScoreReranker(Reranker):
    """Default reranker: role/block_type preference + budget truncation.

    Separates reranking logic from retrieval, so retrievers stay pure
    (return raw scored candidates) and reranking is a pluggable stage.
    """

    async def rerank(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        filtered = list(candidates)

        # Prefer desired roles (move to front, don't exclude)
        if plan.desired_roles:
            preferred = [
                c for c in filtered
                if c.metadata.get("semantic_role") in plan.desired_roles
            ]
            other = [
                c for c in filtered
                if c.metadata.get("semantic_role") not in plan.desired_roles
            ]
            filtered = preferred + other

        # Prefer desired block types (move to front, don't exclude)
        if plan.desired_block_types:
            preferred = [
                c for c in filtered
                if c.metadata.get("block_type") in plan.desired_block_types
            ]
            other = [
                c for c in filtered
                if c.metadata.get("block_type") not in plan.desired_block_types
            ]
            filtered = preferred + other

        # Truncate to budget
        recall_limit = plan.budget.max_items
        return filtered[:recall_limit]
