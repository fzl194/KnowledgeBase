from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1")


@router.get("/tasks/{task_id}/result")
async def get_result(task_id: str, request: Request):
    svc = request.app.state.llm_service
    result = await svc.get_result(task_id)
    if not result:
        return {"error": "not found"}
    return dict(result)


@router.get("/tasks/{task_id}/attempts")
async def get_attempts(task_id: str, request: Request):
    svc = request.app.state.llm_service
    attempts = await svc.get_attempts(task_id)
    return attempts


@router.get("/tasks/{task_id}/events")
async def get_events(task_id: str, request: Request):
    svc = request.app.state.llm_service
    events = await svc.get_events(task_id)
    return events
