"""Tests for AssetRepository — QueryPlan-based L1/L2/L0 access."""
import pytest
import pytest_asyncio
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.schemas.models import (
    EntityRef, EvidenceBudget, ExpansionConfig, QueryPlan, QueryScope,
)
from agent_serving.tests.conftest import ACTIVE_PV_ID, SEED_IDS


def _plan(**overrides) -> QueryPlan:
    defaults = {
        "intent": "command_usage",
        "entity_constraints": [EntityRef(type="command", name="ADD APN", normalized_name="ADD APN")],
        "scope_constraints": QueryScope(),
        "evidence_budget": EvidenceBudget(canonical_limit=10, raw_per_canonical=3),
        "expansion": ExpansionConfig(),
        "keywords": [],
    }
    defaults.update(overrides)
    return QueryPlan(**defaults)


@pytest_asyncio.fixture
async def repo(db_connection):
    return AssetRepository(db_connection)


@pytest.mark.asyncio
async def test_get_active_publish_version_id(repo):
    pv_id = await repo.get_active_publish_version_id()
    assert pv_id == ACTIVE_PV_ID


@pytest.mark.asyncio
async def test_search_canonical_by_entity_command(repo):
    plan = _plan()
    results = await repo.search_canonical(plan)
    assert len(results) >= 1
    assert any("ADD APN" in r["canonical_text"] for r in results)


@pytest.mark.asyncio
async def test_search_canonical_by_keyword(repo):
    plan = _plan(
        intent="general",
        entity_constraints=[],
        keywords=["5G"],
    )
    results = await repo.search_canonical(plan)
    assert len(results) >= 1
    assert any("5G" in r["canonical_text"] for r in results)


@pytest.mark.asyncio
async def test_search_canonical_by_alarm_keyword(repo):
    """Alarm entities are searched via entity name matching search_text LIKE."""
    plan = _plan(
        intent="troubleshooting",
        entity_constraints=[],
        keywords=["CPU过载"],
    )
    results = await repo.search_canonical(plan)
    assert len(results) >= 1
    assert any("CPU" in r["canonical_text"] for r in results)


@pytest.mark.asyncio
async def test_search_canonical_empty_result(repo):
    plan = _plan(
        entity_constraints=[EntityRef(type="command", name="NOTEXIST", normalized_name="notexist")],
    )
    results = await repo.search_canonical(plan)
    assert results == []


@pytest.mark.asyncio
async def test_drill_down_with_scope_filter(repo):
    plan = _plan(
        scope_constraints=QueryScope(products=["UDG"], product_versions=["V100R023C10"]),
    )
    evidence, variants, conflicts = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        plan=plan,
    )
    assert len(evidence) >= 1
    assert any("UDG" in r["raw_text"] for r in evidence)


@pytest.mark.asyncio
async def test_drill_down_no_scope_returns_primary_and_variant(repo):
    plan = _plan()
    evidence, variants, conflicts = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        plan=plan,
    )
    assert len(evidence) >= 2


@pytest.mark.asyncio
async def test_drill_down_separates_conflicts(repo):
    plan = _plan()
    evidence, variants, conflicts = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        plan=plan,
    )
    assert len(conflicts) >= 1
    assert all(c["relation_type"] == "conflict_candidate" for c in conflicts)
    conflict_ids = {c["id"] for c in conflicts}
    evidence_ids = {e["id"] for e in evidence}
    assert conflict_ids.isdisjoint(evidence_ids)


@pytest.mark.asyncio
async def test_get_conflict_sources(repo):
    conflicts = await repo.get_conflict_sources(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
    )
    assert len(conflicts) >= 1
    assert all(c["relation_type"] == "conflict_candidate" for c in conflicts)
