"""Fusion — combines and deduplicates candidates from multiple retrievers.

Reciprocal Rank Fusion (RRF) is the default strategy.
Future: weighted fusion, learned fusion.
"""
from __future__ import annotations

import logging
from typing import Any

from agent_serving.serving.schemas.models import QueryPlan, RetrievalCandidate

logger = logging.getLogger(__name__)


class FusionStrategy:
    """Abstract fusion strategy."""

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        """Combine and rerank candidates."""
        ...


class RRFFusion(FusionStrategy):
    """Reciprocal Rank Fusion.

    Default RRF k=60. Candidates are grouped by retriever source,
    ranked per-source, then merged via RRF formula:
    score = sum(1 / (k + rank_i)) for each source ranking.
    """

    def __init__(self, k: int = 60) -> None:
        self._k = k

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        # Group by source and rank
        by_source: dict[str, list[RetrievalCandidate]] = {}
        for c in candidates:
            by_source.setdefault(c.source, []).append(c)

        # Sort each source by original score desc
        for source in by_source:
            by_source[source].sort(key=lambda c: c.score, reverse=True)

        # Compute RRF scores
        rrf_scores: dict[str, float] = {}
        candidate_map: dict[str, RetrievalCandidate] = {}

        for source, ranked in by_source.items():
            for rank, c in enumerate(ranked, start=1):
                uid = c.retrieval_unit_id
                rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (self._k + rank)
                candidate_map[uid] = c

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores, key=lambda uid: rrf_scores[uid], reverse=True)
        return [candidate_map[uid] for uid in sorted_ids]


class IdentityFusion(FusionStrategy):
    """Pass-through fusion: sort by original score, deduplicate."""

    async def fuse(
        self,
        candidates: list[RetrievalCandidate],
        plan: QueryPlan,
    ) -> list[RetrievalCandidate]:
        # Deduplicate by id, keep higher score
        seen: dict[str, RetrievalCandidate] = {}
        for c in candidates:
            key = c.retrieval_unit_id
            if key not in seen or c.score > seen[key].score:
                seen[key] = c
        return sorted(seen.values(), key=lambda c: c.score, reverse=True)
