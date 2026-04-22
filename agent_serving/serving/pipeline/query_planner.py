"""QueryPlanner — transforms NormalizedQuery into executable QueryPlan.

Pluggable: rule-based default or LLM-backed provider.
LLM integration goes through LLMPlannerProvider, not direct model calls.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from agent_serving.serving.schemas.models import (
    EntityRef,
    ExpansionConfig,
    NormalizedQuery,
    QueryPlan,
    RetrievalBudget,
)

logger = logging.getLogger(__name__)


class PlannerProvider(Protocol):
    """Interface for query planning providers."""

    def build_plan(
        self,
        normalized: NormalizedQuery,
        scope_override: dict | None = None,
        entities_override: list[EntityRef] | None = None,
    ) -> QueryPlan: ...


class RulePlannerProvider:
    """Rule-based query planner — deterministic default.

    Constructs QueryPlan from NormalizedQuery fields.
    No LLM calls; pure rule transformation.
    """

    def build_plan(
        self,
        normalized: NormalizedQuery,
        scope_override: dict | None = None,
        entities_override: list[EntityRef] | None = None,
    ) -> QueryPlan:
        scope = scope_override if scope_override is not None else normalized.scope
        entities = entities_override if entities_override is not None else normalized.entities

        return QueryPlan(
            intent=normalized.intent,
            keywords=normalized.keywords,
            entity_constraints=entities,
            scope_constraints=scope,
            desired_roles=normalized.desired_roles,
            desired_block_types=[],
            budget=RetrievalBudget(),
            expansion=ExpansionConfig(),
        )


class LLMPlannerProvider:
    """LLM-backed query planner — future slot.

    When agent_llm_runtime is available, this provider calls the LLM
    to generate a richer QueryPlan (multi-query decomposition,
    retriever selection, expansion strategy).
    Currently delegates to RulePlannerProvider as fallback.
    """

    def __init__(self, fallback: PlannerProvider | None = None) -> None:
        self._fallback = fallback or RulePlannerProvider()
        self._llm_client: Any = None  # Will be set when runtime is connected

    def set_llm_client(self, client: Any) -> None:
        """Set the LLM runtime client. Called during app init."""
        self._llm_client = client

    def build_plan(
        self,
        normalized: NormalizedQuery,
        scope_override: dict | None = None,
        entities_override: list[EntityRef] | None = None,
    ) -> QueryPlan:
        if self._llm_client and self._llm_client.is_available():
            try:
                return self._try_llm_plan(normalized, scope_override, entities_override)
            except Exception:
                logger.warning("LLM planning failed, falling back to rules", exc_info=True)

        return self._fallback.build_plan(normalized, scope_override, entities_override)

    def _try_llm_plan(
        self,
        normalized: NormalizedQuery,
        scope_override: dict | None,
        entities_override: list[EntityRef] | None,
    ) -> QueryPlan:
        # v1.1: LLM planning not yet connected
        # Future: structured prompt → JSON QueryPlan
        raise NotImplementedError("LLM planning not yet available")


class QueryPlanner:
    """Facade for query planning with pluggable provider."""

    def __init__(self, provider: PlannerProvider | None = None) -> None:
        self._provider = provider or RulePlannerProvider()

    def plan(
        self,
        normalized: NormalizedQuery,
        scope_override: dict | None = None,
        entities_override: list[EntityRef] | None = None,
    ) -> QueryPlan:
        return self._provider.build_plan(normalized, scope_override, entities_override)
