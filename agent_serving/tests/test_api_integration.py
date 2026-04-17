"""Integration tests: full search pipeline via FastAPI TestClient."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agent_serving.serving.main import app
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite
from agent_serving.tests.conftest import _seed_data


@pytest_asyncio.fixture
async def client():
    """Test client with in-memory DB seeded from shared schema."""
    import aiosqlite
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_data(db)
    app.state.db = db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await db.close()


@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_search_command_query(client):
    resp = await client.post("/api/v1/search", json={"query": "ADD APN 怎么写"})
    assert resp.status_code == 200
    pack = resp.json()
    assert pack["intent"] == "command_usage"
    assert len(pack["canonical_items"]) >= 1
    assert any(e["type"] == "command" for e in pack["matched_entities"])


@pytest.mark.asyncio
async def test_search_keyword_query(client):
    resp = await client.post("/api/v1/search", json={"query": "5G 移动通信"})
    assert resp.status_code == 200
    pack = resp.json()
    assert len(pack["canonical_items"]) >= 1
    assert any("5G" in ci["canonical_text"] for ci in pack["canonical_items"])


@pytest.mark.asyncio
async def test_search_troubleshooting(client):
    resp = await client.post("/api/v1/search", json={"query": "CPU过载告警怎么排查"})
    assert resp.status_code == 200
    pack = resp.json()
    assert pack["intent"] == "troubleshooting"


@pytest.mark.asyncio
async def test_search_with_scope_filter(client):
    resp = await client.post("/api/v1/search", json={"query": "UDG V100R023C10 ADD APN"})
    assert resp.status_code == 200
    pack = resp.json()
    assert len(pack["evidence_items"]) >= 1
    # All evidence should come from UDG scope
    for src in pack["sources"]:
        if src["scope"]["products"]:
            assert "UDG" in src["scope"]["products"]


@pytest.mark.asyncio
async def test_command_usage_endpoint(client):
    resp = await client.post("/api/v1/command-usage", json={"query": "ADD APN"})
    assert resp.status_code == 200
    pack = resp.json()
    assert pack["intent"] == "command_usage"


@pytest.mark.asyncio
async def test_command_usage_no_command(client):
    resp = await client.post("/api/v1/command-usage", json={"query": "5G是什么"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_conflict_not_in_evidence(client):
    """Conflict candidates must appear in conflicts, NOT in evidence_items."""
    resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
    assert resp.status_code == 200
    pack = resp.json()
    evidence_texts = [e["raw_text"] for e in pack["evidence_items"]]
    for rt in evidence_texts:
        assert "参数冲突版本" not in rt
    if pack["conflicts"]:
        assert any("冲突" in c.get("raw_text", "") or "冲突" in c.get("diff_summary", "")
                    for c in pack["conflicts"])


@pytest.mark.asyncio
async def test_evidence_pack_has_query_plan(client):
    resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
    assert resp.status_code == 200
    pack = resp.json()
    assert pack["query_plan"] is not None
    assert pack["query_plan"]["conflict_policy"] == "flag_not_answer"


@pytest.mark.asyncio
async def test_search_returns_block_type_and_semantic_role(client):
    resp = await client.post("/api/v1/search", json={"query": "ADD APN"})
    assert resp.status_code == 200
    pack = resp.json()
    assert len(pack["canonical_items"]) >= 1
    ci = pack["canonical_items"][0]
    assert ci["block_type"] in ("paragraph", "table", "list", "code", "unknown")
    assert ci["semantic_role"] in ("parameter", "example", "concept", "unknown")
