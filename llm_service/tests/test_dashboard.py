import pytest

pytestmark = pytest.mark.asyncio


async def test_dashboard_page(api_client):
    resp = await api_client.get("/dashboard")
    assert resp.status_code == 200
    assert "LLM Service Dashboard" in resp.text
    assert "Total Tasks" in resp.text


async def test_dashboard_stats_api(api_client):
    # Submit a task first so stats aren't empty
    await api_client.post(
        "/api/v1/tasks",
        json={"caller_domain": "mining", "pipeline_stage": "test"},
    )
    resp = await api_client.get("/dashboard/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "tasks_by_status" in data
    assert "total_tokens" in data


async def test_dashboard_shows_tasks(api_client):
    # Execute a task so it shows up
    await api_client.post(
        "/api/v1/execute",
        json={
            "caller_domain": "serving",
            "pipeline_stage": "search",
            "messages": [{"role": "user", "content": '{"result": "ok"}'}],
        },
    )
    resp = await api_client.get("/dashboard")
    assert resp.status_code == 200
    assert "serving" in resp.text
