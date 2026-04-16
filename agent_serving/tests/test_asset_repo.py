"""Tests for AssetRepository — read-only L1/L2/L0 access."""
import pytest
import pytest_asyncio
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.tests.conftest import ACTIVE_PV_ID, SEED_IDS


@pytest_asyncio.fixture
async def repo(db_connection):
    return AssetRepository(db_connection)


@pytest.mark.asyncio
async def test_get_active_publish_version_id(repo):
    pv_id = await repo.get_active_publish_version_id()
    assert pv_id == ACTIVE_PV_ID


@pytest.mark.asyncio
async def test_search_canonical_by_command_name(repo):
    results = await repo.search_canonical(command_name="ADD APN")
    assert len(results) == 1
    assert results[0]["command_name"] == "ADD APN"
    assert results[0]["has_variants"] == 1


@pytest.mark.asyncio
async def test_search_canonical_by_keyword(repo):
    results = await repo.search_canonical(keyword="5G")
    assert len(results) == 1
    assert "5G" in results[0]["canonical_text"]


@pytest.mark.asyncio
async def test_search_canonical_empty_result(repo):
    results = await repo.search_canonical(command_name="NOTEXIST")
    assert results == []


@pytest.mark.asyncio
async def test_drill_down_with_product_version(repo):
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        product="UDG",
        product_version="V100R023C10",
    )
    assert len(raw_segs) == 1
    assert "UDG" in raw_segs[0]["raw_text"]


@pytest.mark.asyncio
async def test_drill_down_without_constraint_returns_all_variants(repo):
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
    )
    assert len(raw_segs) == 3  # 2 version_variants + 1 conflict_candidate


@pytest.mark.asyncio
async def test_drill_down_excludes_conflict_candidates(repo):
    raw_segs = await repo.drill_down(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
        exclude_conflict=True,
    )
    assert len(raw_segs) == 2
    assert all(r["relation_type"] != "conflict_candidate" for r in raw_segs)


@pytest.mark.asyncio
async def test_get_conflict_sources(repo):
    conflicts = await repo.get_conflict_sources(
        canonical_segment_id=SEED_IDS["canon_add_apn"],
    )
    assert len(conflicts) == 1
    assert conflicts[0]["relation_type"] == "conflict_candidate"


@pytest.mark.asyncio
async def test_get_raw_segments_by_ids(repo):
    segs = await repo.get_raw_segments_by_ids([SEED_IDS["raw_seg_5g_concept"]])
    assert len(segs) == 1
    assert "5G" in segs[0]["raw_text"]


@pytest.mark.asyncio
async def test_get_document_for_segment(repo):
    doc = await repo.get_document_for_segment(SEED_IDS["raw_seg_add_apn_udg"])
    assert doc["product"] == "UDG"
    assert doc["product_version"] == "V100R023C10"
