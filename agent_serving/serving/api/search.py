"""Search API — v1.1 /search endpoint.

Single endpoint: /api/v1/search
Pipeline: normalize → plan → resolve scope → retrieve → fuse → rerank → assemble

Each stage is pluggable through dependency injection.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from agent_serving.serving.schemas.models import (
    ContextPack,
    SearchRequest,
)
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.retrieval.bm25_retriever import FTS5BM25Retriever
from agent_serving.serving.retrieval.graph_expander import GraphExpander
from agent_serving.serving.application.normalizer import QueryNormalizer
from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.pipeline.retriever_manager import RetrieverManager
from agent_serving.serving.pipeline.fusion import IdentityFusion, RRFFusion
from agent_serving.serving.pipeline.reranker import ScoreReranker
from agent_serving.serving.pipeline.query_planner import QueryPlanner, RulePlannerProvider

router = APIRouter(prefix="/api/v1", tags=["search"])


def _get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.db)


def _get_retriever_manager(request: Request) -> RetrieverManager:
    bm25 = FTS5BM25Retriever(request.app.state.db)
    mgr = RetrieverManager({"fts_bm25": bm25})
    # Future: register vector retriever here
    return mgr


def _get_expander(request: Request) -> GraphExpander:
    return GraphExpander(request.app.state.db)


def _get_planner() -> QueryPlanner:
    return QueryPlanner(RulePlannerProvider())


def _get_reranker() -> ScoreReranker:
    return ScoreReranker()


@router.post("/search", response_model=ContextPack)
async def search(
    body: SearchRequest,
    repo: AssetRepository = Depends(_get_repo),
    retriever_mgr: RetrieverManager = Depends(_get_retriever_manager),
    expander: GraphExpander = Depends(_get_expander),
    planner: QueryPlanner = Depends(_get_planner),
    reranker: ScoreReranker = Depends(_get_reranker),
) -> ContextPack:
    # 1. Normalize query
    normalizer = QueryNormalizer()
    normalized = normalizer.normalize(body.query)

    # Merge explicit overrides
    if body.scope:
        normalized = normalized.model_copy(update={"scope": body.scope})
    if body.entities:
        normalized = normalized.model_copy(update={"entities": body.entities})

    # 2. Build plan via pluggable planner
    plan = planner.plan(
        normalized,
        scope_override=body.scope,
        entities_override=body.entities,
    )

    # 3. Resolve active scope (release → build → snapshots)
    try:
        scope = await repo.resolve_active_scope()
    except ValueError as e:
        if str(e) == "no_active_release":
            raise HTTPException(
                status_code=503,
                detail="No active release — knowledge base is empty",
            )
        if str(e) == "multiple_active_releases":
            raise HTTPException(
                status_code=500,
                detail="Data integrity error: multiple active releases",
            )
        raise

    # 4. Retrieve from all configured paths
    raw_candidates = await retriever_mgr.retrieve(plan, scope.snapshot_ids)

    # 5. Fuse (combine multi-path results)
    fusion = IdentityFusion()
    if plan.retriever_config.fusion_method == "rrf":
        fusion = RRFFusion(k=plan.retriever_config.rrf_k)
    fused = await fusion.fuse(raw_candidates, plan)

    # 6. Rerank
    ranked = await reranker.rerank(fused, plan)

    # 7. Assemble ContextPack
    assembler = ContextAssembler(repo, expander)
    pack = await assembler.assemble(
        query=body.query,
        normalized=normalized,
        plan=plan,
        scope=scope,
        candidates=ranked,
    )

    if body.debug:
        pack = pack.model_copy(update={
            "debug": {
                "plan": plan.model_dump(),
                "scope": scope.model_dump(),
                "candidate_count": len(ranked),
                "retriever_config": plan.retriever_config.model_dump(),
                "fusion_method": plan.retriever_config.fusion_method,
            },
        })

    return pack
