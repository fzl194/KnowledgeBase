"""RetrieverManager — orchestrates multi-path retrieval.

Dispatches query to one or more Retriever implementations concurrently,
collects candidates from each, and deduplicates by ID.
"""
from __future__ import annotations

import asyncio
import logging

from agent_serving.serving.schemas.models import QueryPlan, RetrievalCandidate
from agent_serving.serving.retrieval.retriever import Retriever

logger = logging.getLogger(__name__)


class RetrieverManager:
    """Manages multiple retriever paths and merges results.

    Retriever selection is driven by QueryPlan.retriever_config.
    Each retriever is registered with a name; the manager runs
    the ones requested concurrently and returns merged candidates.
    """

    def __init__(self, retrievers: dict[str, Retriever] | None = None) -> None:
        self._retrievers: dict[str, Retriever] = retrievers or {}

    def register(self, name: str, retriever: Retriever) -> None:
        self._retrievers[name] = retriever

    async def retrieve(
        self,
        plan: QueryPlan,
        snapshot_ids: list[str],
    ) -> list[RetrievalCandidate]:
        """Run all configured retrievers concurrently and merge candidates."""
        if not self._retrievers:
            return []

        enabled = plan.retriever_config.enabled_retrievers
        if not enabled:
            enabled = list(self._retrievers.keys())

        # Run retrievers concurrently
        async def _safe_retrieve(name: str, retriever: Retriever) -> list[RetrievalCandidate]:
            try:
                return await retriever.retrieve(plan, snapshot_ids)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Retriever '%s' failed", name, exc_info=True)
                return []

        tasks = []
        for name in enabled:
            retriever = self._retrievers.get(name)
            if not retriever:
                logger.warning("Retriever '%s' not registered, skipping", name)
                continue
            tasks.append(_safe_retrieve(name, retriever))

        results = await asyncio.gather(*tasks)
        all_candidates = [c for batch in results for c in batch]

        # Deduplicate by retrieval_unit_id, keeping higher score
        seen: dict[str, RetrievalCandidate] = {}
        for c in all_candidates:
            key = c.retrieval_unit_id
            if key not in seen or c.score > seen[key].score:
                seen[key] = c

        return list(seen.values())
