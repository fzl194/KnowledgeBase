"""Search API — unified QueryPlan pipeline for generic evidence retrieval.

/search is the main entry. /command-usage is a compatible shortcut that
forces intent=command_usage and uses entity.type=command, but otherwise
walks the same pipeline as /search.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agent_serving.serving.schemas.models import (
    CommandUsageRequest,
    EntityRef,
    EvidencePack,
    NormalizedQuery,
    QueryPlan,
    SearchRequest,
)
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.application.normalizer import QueryNormalizer, build_plan
from agent_serving.serving.application.assembler import EvidenceAssembler

router = APIRouter(prefix="/api/v1", tags=["search"])


def get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.db)


async def _execute_plan(
    query: str, normalized: NormalizedQuery, plan: QueryPlan, repo: AssetRepository,
) -> EvidencePack:
    """Core pipeline: search canonical → drill down → assemble evidence pack."""
    assembler = EvidenceAssembler()

    # 1. Search L1 canonical segments
    canonical_hits = await repo.search_canonical(plan)

    # 2. Fallback: if entity search found nothing, try keywords
    if not canonical_hits and plan.keywords:
        from agent_serving.serving.schemas.models import QueryPlan as QP
        keyword_plan = QP(
            intent=plan.intent,
            retrieval_targets=plan.retrieval_targets,
            entity_constraints=[],
            scope_constraints=plan.scope_constraints,
            semantic_role_preferences=plan.semantic_role_preferences,
            block_type_preferences=plan.block_type_preferences,
            variant_policy=plan.variant_policy,
            conflict_policy=plan.conflict_policy,
            evidence_budget=plan.evidence_budget,
            expansion=plan.expansion,
            keywords=plan.keywords,
        )
        canonical_hits = await repo.search_canonical(keyword_plan)

    # 3. Drill down for each canonical hit
    drill_results: list[tuple[list[dict], list[dict], list[dict]]] = []
    for canon in canonical_hits:
        evidence, variants, conflicts = await repo.drill_down(
            canonical_segment_id=canon["id"],
            plan=plan,
        )
        drill_results.append((evidence, variants, conflicts))

    # 4. Assemble evidence pack
    pack = assembler.assemble(
        query=query,
        intent=plan.intent,
        normalized=normalized,
        plan=plan,
        canonical_hits=canonical_hits,
        drill_results=drill_results,
    )

    return pack


@router.post("/search", response_model=EvidencePack)
async def search(
    request: SearchRequest,
    repo: AssetRepository = Depends(get_repo),
) -> EvidencePack:
    normalizer = QueryNormalizer()
    normalized = normalizer.normalize(request.query)
    plan = build_plan(normalized)

    return await _execute_plan(request.query, normalized, plan, repo)


@router.post("/command-usage", response_model=EvidencePack)
async def command_usage(
    request: CommandUsageRequest,
    repo: AssetRepository = Depends(get_repo),
) -> EvidencePack:
    """Compatible shortcut: forces intent=command_usage.

    Internally walks the same QueryPlan pipeline as /search.
    """
    normalizer = QueryNormalizer()
    normalized = normalizer.normalize(request.query)

    # Force intent to command_usage
    has_command = any(e.type == "command" for e in normalized.entities)
    if not has_command:
        raise HTTPException(
            status_code=400,
            detail="Could not identify a command in the query",
        )

    # Override intent for command-usage shortcut
    normalized.intent = "command_usage"
    normalized.desired_semantic_roles = ["parameter", "example", "procedure_step"]

    plan = build_plan(normalized)
    return await _execute_plan(request.query, normalized, plan, repo)
