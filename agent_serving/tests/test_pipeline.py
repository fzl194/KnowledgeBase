"""Tests for pipeline components: Fusion, Reranker, QueryPlanner, RetrieverManager, LLM providers."""
import pytest

from agent_serving.serving.schemas.models import (
    ExpansionConfig,
    NormalizedQuery,
    QueryPlan,
    RetrievalBudget,
    RetrievalCandidate,
    RetrieverConfig,
)
from agent_serving.serving.pipeline.fusion import IdentityFusion, RRFFusion
from agent_serving.serving.pipeline.reranker import ScoreReranker
from agent_serving.serving.pipeline.query_planner import (
    QueryPlanner,
    RulePlannerProvider,
)
from agent_serving.serving.pipeline.llm_providers import (
    LLMNormalizerProvider,
    LLMRerankerProvider,
)
from agent_serving.serving.schemas.json_utils import (
    parse_source_refs,
    parse_target_ref,
    safe_json_parse,
)


def _candidate(ru_id, score, source="fts_bm25"):
    return RetrievalCandidate(
        retrieval_unit_id=ru_id, score=score, source=source, metadata={},
    )


class TestIdentityFusion:
    @pytest.mark.asyncio
    async def test_dedup_keeps_higher_score(self):
        fusion = IdentityFusion()
        candidates = [
            _candidate("a", 0.9, "fts"),
            _candidate("a", 0.5, "like"),
            _candidate("b", 0.7, "fts"),
        ]
        result = await fusion.fuse(candidates, QueryPlan())
        assert len(result) == 2
        assert result[0].score == 0.9  # Sorted desc
        assert result[1].score == 0.7

    @pytest.mark.asyncio
    async def test_empty_input(self):
        fusion = IdentityFusion()
        result = await fusion.fuse([], QueryPlan())
        assert result == []


class TestRRFFusion:
    @pytest.mark.asyncio
    async def test_multi_source_fusion(self):
        fusion = RRFFusion(k=60)
        candidates = [
            _candidate("a", 0.9, "fts"),
            _candidate("b", 0.8, "fts"),
            _candidate("a", 0.5, "vector"),
            _candidate("c", 0.7, "vector"),
        ]
        result = await fusion.fuse(candidates, QueryPlan())
        ids = [c.retrieval_unit_id for c in result]
        # "a" appears in both sources, should rank highest
        assert ids[0] == "a"

    @pytest.mark.asyncio
    async def test_single_source(self):
        fusion = RRFFusion()
        candidates = [_candidate("x", 0.9, "fts"), _candidate("y", 0.5, "fts")]
        result = await fusion.fuse(candidates, QueryPlan())
        assert len(result) == 2


class TestScoreReranker:
    @pytest.mark.asyncio
    async def test_role_preference(self):
        reranker = ScoreReranker()
        plan = QueryPlan(desired_roles=["parameter"])
        candidates = [
            RetrievalCandidate(retrieval_unit_id="a", score=0.5, source="fts", metadata={"semantic_role": "concept"}),
            RetrievalCandidate(retrieval_unit_id="b", score=0.8, source="fts", metadata={"semantic_role": "parameter"}),
        ]
        result = await reranker.rerank(candidates, plan)
        assert result[0].metadata["semantic_role"] == "parameter"

    @pytest.mark.asyncio
    async def test_budget_truncation(self):
        reranker = ScoreReranker()
        plan = QueryPlan(budget=RetrievalBudget(max_items=2))
        candidates = [_candidate(f"ru-{i}", i * 0.1) for i in range(5)]
        result = await reranker.rerank(candidates, plan)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        reranker = ScoreReranker()
        result = await reranker.rerank([], QueryPlan())
        assert result == []


class TestRulePlannerProvider:
    def test_builds_plan_from_normalized(self):
        provider = RulePlannerProvider()
        normalized = NormalizedQuery(
            original_query="ADD APN",
            intent="command_usage",
            keywords=["ADD", "APN"],
        )
        plan = provider.build_plan(normalized)
        assert plan.intent == "command_usage"
        assert plan.keywords == ["ADD", "APN"]

    def test_scope_override(self):
        provider = RulePlannerProvider()
        normalized = NormalizedQuery(original_query="test", scope={"products": ["X"]})
        plan = provider.build_plan(normalized, scope_override={"products": ["Y"]})
        assert plan.scope_constraints == {"products": ["Y"]}


class TestQueryPlannerFacade:
    def test_delegates_to_provider(self):
        planner = QueryPlanner(RulePlannerProvider())
        normalized = NormalizedQuery(original_query="test", intent="general")
        plan = planner.plan(normalized)
        assert plan.intent == "general"


class TestLLMProviders:
    def test_normalizer_returns_none_when_no_client(self):
        provider = LLMNormalizerProvider()
        assert provider.normalize("test") is None

    def test_reranker_returns_none_when_no_client(self):
        import asyncio
        provider = LLMRerankerProvider()
        result = asyncio.get_event_loop().run_until_complete(
            provider.rerank([], QueryPlan()),
        )
        assert result is None


class TestJsonUtils:
    def test_parse_source_refs_valid(self):
        assert parse_source_refs('{"raw_segment_ids": ["a", "b"]}') == ["a", "b"]

    def test_parse_source_refs_empty(self):
        assert parse_source_refs(None) == []
        assert parse_source_refs("{}") == []

    def test_parse_source_refs_invalid_type(self):
        assert parse_source_refs('{"raw_segment_ids": [1, 2]}') == []

    def test_parse_target_ref_single(self):
        assert parse_target_ref('{"raw_segment_id": "abc"}') == ["abc"]

    def test_parse_target_ref_multiple(self):
        assert parse_target_ref('{"raw_segment_ids": ["a", "b"]}') == ["a", "b"]

    def test_parse_target_ref_empty(self):
        assert parse_target_ref(None) == []
        assert parse_target_ref("{}") == []

    def test_safe_json_parse_dict_passthrough(self):
        assert safe_json_parse({"a": 1}) == {"a": 1}

    def test_safe_json_parse_string(self):
        assert safe_json_parse('{"b": 2}') == {"b": 2}

    def test_safe_json_parse_invalid(self):
        assert safe_json_parse("not json") == {}
