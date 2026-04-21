from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = request.app.state.db
    cur = await db.execute("SELECT COUNT(*) as cnt FROM agent_llm_tasks")
    total = (await cur.fetchone())["cnt"]

    cur = await db.execute("SELECT status, COUNT(*) as cnt FROM agent_llm_tasks GROUP BY status")
    by_status = {row["status"]: row["cnt"] for row in await cur.fetchall()}

    cur = await db.execute(
        "SELECT id, caller_domain, pipeline_stage, status, attempt_count, created_at FROM agent_llm_tasks ORDER BY created_at DESC LIMIT 20"
    )
    recent = [dict(r) for r in await cur.fetchall()]

    templates = request.app.state.templates
    html = templates.get_template("dashboard.html").render(
        total=total,
        by_status=by_status,
        recent=recent,
    )
    return HTMLResponse(content=html)


@router.get("/dashboard/api/stats")
async def dashboard_stats(request: Request):
    db = request.app.state.db
    cur = await db.execute("SELECT status, COUNT(*) as cnt FROM agent_llm_tasks GROUP BY status")
    by_status = {row["status"]: row["cnt"] for row in await cur.fetchall()}

    cur = await db.execute("SELECT COUNT(*) as cnt FROM agent_llm_attempts WHERE status = 'succeeded'")
    succeeded = (await cur.fetchone())["cnt"]

    cur = await db.execute("SELECT SUM(total_tokens) as total FROM agent_llm_attempts")
    row = await cur.fetchone()
    total_tokens = row["total"] or 0

    cur = await db.execute("SELECT AVG(latency_ms) as avg_lat FROM agent_llm_attempts WHERE latency_ms IS NOT NULL")
    row = await cur.fetchone()
    avg_latency = row["avg_lat"] or 0

    return {
        "tasks_by_status": by_status,
        "succeeded_attempts": succeeded,
        "total_tokens": total_tokens,
        "avg_latency_ms": round(avg_latency, 1),
    }
