import pytest

pytestmark = pytest.mark.asyncio


def _mock_provider():
    from llm_service.providers.mock import MockProvider

    return MockProvider(
        responses=[{"choices": [{"message": {"content": '{"answer": 42}'}}]}]
    )


@pytest.fixture
async def client(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from llm_service.config import LLMServiceConfig
    from llm_service.main import create_app

    cfg = LLMServiceConfig(
        db_path=str(tmp_path / "test_api.sqlite"),
        provider_base_url="http://localhost:11434/v1",
        provider_api_key="test-key",
        provider_model="test-model",
    )
    app = create_app(cfg, provider_factory=_mock_provider)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_submit_task(client):
    resp = await client.post(
        "/api/v1/tasks",
        json={
            "caller_domain": "mining",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "task_id" in body
    assert body["status"] == "queued"


async def test_execute_task(client):
    resp = await client.post(
        "/api/v1/execute",
        json={
            "caller_domain": "mining",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"answer": 42}'}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["result"]["parsed_output"] == {"answer": 42}


async def test_get_task(client):
    submit = await client.post(
        "/api/v1/tasks",
        json={"caller_domain": "mining", "pipeline_stage": "test"},
    )
    task_id = submit.json()["task_id"]
    resp = await client.get(f"/api/v1/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == task_id


async def test_cancel_task(client):
    submit = await client.post(
        "/api/v1/tasks",
        json={"caller_domain": "mining", "pipeline_stage": "test"},
    )
    task_id = submit.json()["task_id"]
    resp = await client.post(f"/api/v1/tasks/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


async def test_get_result_after_execute(client):
    exec_resp = await client.post(
        "/api/v1/execute",
        json={
            "caller_domain": "serving",
            "pipeline_stage": "search",
            "messages": [{"role": "user", "content": '{"name": "test"}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    result_resp = await client.get(f"/api/v1/tasks/{task_id}/result")
    assert result_resp.status_code == 200
    result = result_resp.json()
    assert result["parse_status"] == "succeeded"


async def test_get_attempts_after_execute(client):
    exec_resp = await client.post(
        "/api/v1/execute",
        json={
            "caller_domain": "mining",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"ok": true}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    attempts_resp = await client.get(f"/api/v1/tasks/{task_id}/attempts")
    assert attempts_resp.status_code == 200
    attempts = attempts_resp.json()
    assert len(attempts) >= 1
    assert attempts[0]["status"] == "succeeded"


async def test_get_events_after_execute(client):
    exec_resp = await client.post(
        "/api/v1/execute",
        json={
            "caller_domain": "mining",
            "pipeline_stage": "test",
            "messages": [{"role": "user", "content": '{"x": 1}'}],
        },
    )
    task_id = exec_resp.json()["task_id"]
    events_resp = await client.get(f"/api/v1/tasks/{task_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) >= 1


async def test_idempotent_submit(client):
    payload = {
        "caller_domain": "mining",
        "pipeline_stage": "test",
        "messages": [{"role": "user", "content": "hi"}],
        "idempotency_key": "unique-123",
    }
    r1 = await client.post("/api/v1/tasks", json=payload)
    r2 = await client.post("/api/v1/tasks", json=payload)
    assert r1.json()["task_id"] == r2.json()["task_id"]
