"""Verify Pydantic models serialize/deserialize correctly."""
import pytest
from agent_serving.serving.schemas.models import (
    SearchRequest,
    CommandUsageRequest,
    EvidencePack,
    NormalizedQuery,
    QueryPlan,
    EntityRef,
    QueryScope,
    CanonicalItem,
    EvidenceItem,
    Gap,
    ConflictInfo,
    VariantInfo,
)


def test_search_request_defaults():
    req = SearchRequest(query="ADD APN 怎么写")
    assert req.query == "ADD APN 怎么写"


def test_command_usage_request():
    req = CommandUsageRequest(query="UDG V100R023C10 ADD APN")
    assert req.query == "UDG V100R023C10 ADD APN"


def test_normalized_query_with_entities():
    nq = NormalizedQuery(
        intent="command_usage",
        entities=[EntityRef(type="command", name="ADD APN", normalized_name="ADD APN")],
        scope=QueryScope(products=["UDG"], product_versions=["V100R023C10"]),
        keywords=[],
        missing_constraints=[],
    )
    assert nq.intent == "command_usage"
    assert nq.entities[0].type == "command"
    assert nq.scope.products == ["UDG"]


def test_query_plan_defaults():
    plan = QueryPlan()
    assert plan.intent == "general"
    assert plan.variant_policy == "flag"
    assert plan.conflict_policy == "flag_not_answer"
    assert plan.evidence_budget.canonical_limit == 10
    assert plan.expansion.use_ontology is False


def test_evidence_pack_serialization():
    pack = EvidencePack(
        query="ADD APN",
        intent="command_usage",
        normalized_query="intent=command_usage command=ADD APN",
        canonical_items=[
            CanonicalItem(
                id="c1", canonical_key="CANON_ADD_APN",
                block_type="paragraph", semantic_role="parameter",
                title="ADD APN", canonical_text="ADD APN 归并文本",
                entity_refs=[EntityRef(type="command", name="ADD APN", normalized_name="ADD APN")],
                scope=QueryScope(products=["UDG", "UNC"]),
                has_variants=True, variant_policy="require_scope",
            )
        ],
        evidence_items=[],
        conflicts=[
            ConflictInfo(raw_text="冲突版本", diff_summary="参数描述矛盾"),
        ],
        gaps=[
            Gap(field="product", reason="需要指定产品", suggested_options=["UDG", "UNC"]),
        ],
    )
    data = pack.model_dump()
    assert data["intent"] == "command_usage"
    assert len(data["canonical_items"]) == 1
    assert data["canonical_items"][0]["block_type"] == "paragraph"
    assert len(data["conflicts"]) == 1
    assert len(data["gaps"]) == 1
    assert data["gaps"][0]["field"] == "product"


def test_scope_model():
    scope = QueryScope(
        products=["UDG"],
        product_versions=["V100R023C10"],
        network_elements=["UDM"],
    )
    assert scope.products == ["UDG"]
    assert scope.projects == []
    assert scope.domains == []
