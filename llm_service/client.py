from __future__ import annotations

from typing import Any

import httpx


class LLMClient:
    """Formal client for Mining/Serving to call LLM Service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8900",
        http_client: httpx.AsyncClient | None = None,
        timeout: int = 60,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._external_client = http_client is not None
        self._client = http_client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._external_client:
            await self._client.aclose()
            self._client = None

    def _build_submit_payload(
        self,
        caller_domain: str,
        pipeline_stage: str,
        *,
        template_key: str | None = None,
        input: dict | None = None,
        messages: list[dict] | None = None,
        params: dict | None = None,
        expected_output_type: str = "json_object",
        output_schema: dict | None = None,
        ref_type: str | None = None,
        ref_id: str | None = None,
        build_id: str | None = None,
        release_id: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        priority: int = 100,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "caller_domain": caller_domain,
            "pipeline_stage": pipeline_stage,
            "expected_output_type": expected_output_type,
            "max_attempts": max_attempts,
            "priority": priority,
        }
        for k, v in [
            ("template_key", template_key),
            ("input", input),
            ("messages", messages),
            ("params", params),
            ("output_schema", output_schema),
            ("ref_type", ref_type),
            ("ref_id", ref_id),
            ("build_id", build_id),
            ("release_id", release_id),
            ("idempotency_key", idempotency_key),
        ]:
            if v is not None:
                payload[k] = v
        return payload

    async def submit(
        self,
        caller_domain: str,
        pipeline_stage: str,
        **kwargs,
    ) -> str:
        payload = self._build_submit_payload(caller_domain, pipeline_stage, **kwargs)
        c = self._get_client()
        resp = await c.post("/api/v1/tasks", json=payload)
        resp.raise_for_status()
        return resp.json()["task_id"]

    async def execute(
        self,
        caller_domain: str,
        pipeline_stage: str,
        **kwargs,
    ) -> dict:
        payload = self._build_submit_payload(caller_domain, pipeline_stage, **kwargs)
        c = self._get_client()
        resp = await c.post("/api/v1/execute", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_task(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    async def cancel(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.post(f"/api/v1/tasks/{task_id}/cancel")
        resp.raise_for_status()
        return resp.json()

    async def get_result(self, task_id: str) -> dict:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/result")
        resp.raise_for_status()
        return resp.json()

    async def get_attempts(self, task_id: str) -> list[dict]:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/attempts")
        resp.raise_for_status()
        return resp.json()

    async def get_events(self, task_id: str) -> list[dict]:
        c = self._get_client()
        resp = await c.get(f"/api/v1/tasks/{task_id}/events")
        resp.raise_for_status()
        return resp.json()
