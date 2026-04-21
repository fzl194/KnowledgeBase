from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import aiosqlite

from llm_service.config import LLMServiceConfig
from llm_service.providers.base import ProviderProtocol
from llm_service.runtime.event_bus import EventBus
from llm_service.runtime.executor import Executor
from llm_service.runtime.task_manager import TaskManager


class LLMService:
    """Top-level orchestrator: owns task_manager, executor, event_bus, provider."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        provider: ProviderProtocol,
        config: LLMServiceConfig,
    ):
        self._db = db
        self._config = config
        self._bus = EventBus(db)
        self._mgr = TaskManager(
            db, self._bus,
            max_attempts=config.default_max_attempts,
            lease_duration=config.lease_duration,
            backoff_base=config.retry_backoff_base,
            backoff_max=config.retry_backoff_max,
        )
        self._executor = Executor(db, self._mgr, self._bus, provider)

    async def submit(
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
    ) -> str:
        task_id = await self._mgr.submit(
            caller_domain, pipeline_stage,
            idempotency_key=idempotency_key,
            ref_type=ref_type, ref_id=ref_id,
            build_id=build_id, release_id=release_id,
            max_attempts=max_attempts, priority=priority,
        )
        # Check if this was an idempotency hit (task already existed)
        cur = await self._db.execute("SELECT created_at FROM agent_llm_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        existing_created = row["created_at"]

        # Only create request if this is a new task (no request row yet)
        cur = await self._db.execute("SELECT COUNT(*) as cnt FROM agent_llm_requests WHERE task_id = ?", (task_id,))
        req_row = await cur.fetchone()
        if req_row["cnt"] == 0:
            now = datetime.now(timezone.utc).isoformat()
            request_id = str(uuid.uuid4())
            provider_instance = self._executor._provider
            await self._db.execute(
                """INSERT INTO agent_llm_requests
                   (id, task_id, provider, model, prompt_template_key, messages_json, input_json,
                    params_json, expected_output_type, output_schema_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id, task_id, provider_instance.provider_name,
                    provider_instance.default_model, template_key,
                    json.dumps(messages or []), json.dumps(input or {}),
                    json.dumps(params or {}), expected_output_type,
                    json.dumps(output_schema or {}), now,
                ),
            )
            await self._db.commit()

        return task_id

    async def execute(
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
        timeout: int | None = None,
    ) -> dict:
        """Sync execute: submit, then run immediately, return result."""
        task_id = await self.submit(
            caller_domain, pipeline_stage,
            template_key=template_key, input=input, messages=messages,
            params=params, expected_output_type=expected_output_type,
            output_schema=output_schema,
            ref_type=ref_type, ref_id=ref_id,
            build_id=build_id, release_id=release_id,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts, priority=priority,
        )

        # Check if idempotency returned an already-succeeded task
        cur = await self._db.execute("SELECT status FROM agent_llm_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        if row["status"] == "succeeded":
            return await self._build_execute_response(task_id)

        # Directly set to running and execute (sync path, no queue)
        now_iso = datetime.now(timezone.utc).isoformat()
        lease_dt = datetime.now(timezone.utc) + timedelta(seconds=self._config.lease_duration)
        await self._db.execute(
            "UPDATE agent_llm_tasks SET status = 'running', started_at = ?, lease_expires_at = ?, updated_at = ? WHERE id = ?",
            (now_iso, lease_dt.isoformat(), now_iso, task_id),
        )
        await self._db.commit()
        actual_messages = messages or [{"role": "user", "content": json.dumps(input or {})}]
        actual_params = params or {}

        import asyncio

        effective_timeout = timeout or self._config.execute_timeout
        try:
            result = await asyncio.wait_for(
                self._executor.run(
                    task_id, actual_messages, actual_params,
                    expected_type=expected_output_type, schema=output_schema,
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            await self._mgr.fail(task_id, "timeout", f"execute timed out after {effective_timeout}s")
            return await self._build_execute_response(task_id)

        return await self._build_execute_response(task_id)

    async def _build_execute_response(self, task_id: str) -> dict:
        cur = await self._db.execute("SELECT status, attempt_count FROM agent_llm_tasks WHERE id = ?", (task_id,))
        task = await cur.fetchone()

        cur = await self._db.execute("SELECT parse_status, parsed_output_json, text_output, validation_errors_json FROM agent_llm_results WHERE task_id = ?", (task_id,))
        result_row = await cur.fetchone()

        cur = await self._db.execute("SELECT total_tokens, latency_ms FROM agent_llm_attempts WHERE task_id = ? ORDER BY attempt_no DESC LIMIT 1", (task_id,))
        attempt_row = await cur.fetchone()

        resp = {
            "task_id": task_id,
            "status": task["status"],
            "attempts": task["attempt_count"],
            "total_tokens": attempt_row["total_tokens"] if attempt_row else None,
            "latency_ms": attempt_row["latency_ms"] if attempt_row else None,
        }

        if result_row:
            parse_status = result_row["parse_status"]
            parsed = json.loads(result_row["parsed_output_json"]) if result_row["parsed_output_json"] else None
            validation = json.loads(result_row["validation_errors_json"]) if result_row["validation_errors_json"] else []
            resp["result"] = {
                "parse_status": parse_status,
                "parsed_output": parsed if parsed != {} else None,
                "text_output": result_row["text_output"],
                "validation_errors": validation,
            }
        else:
            resp["result"] = None

        # Get error info if failed
        if task["status"] in ("dead_letter", "failed"):
            cur = await self._db.execute("SELECT error_type, error_message FROM agent_llm_attempts WHERE task_id = ? AND status = 'failed' ORDER BY attempt_no DESC LIMIT 1", (task_id,))
            err_row = await cur.fetchone()
            resp["error"] = {
                "error_type": err_row["error_type"] if err_row else None,
                "error_message": err_row["error_message"] if err_row else None,
            }
        else:
            resp["error"] = None

        return resp

    async def get_task(self, task_id: str) -> dict | None:
        cur = await self._db.execute("SELECT * FROM agent_llm_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return dict(row)

    async def cancel(self, task_id: str) -> None:
        await self._mgr.cancel(task_id)

    async def get_result(self, task_id: str) -> dict | None:
        cur = await self._db.execute("SELECT * FROM agent_llm_results WHERE task_id = ?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_attempts(self, task_id: str) -> list[dict]:
        cur = await self._db.execute("SELECT * FROM agent_llm_attempts WHERE task_id = ? ORDER BY attempt_no", (task_id,))
        return [dict(r) for r in await cur.fetchall()]

    async def get_events(self, task_id: str) -> list[dict]:
        cur = await self._db.execute("SELECT * FROM agent_llm_events WHERE task_id = ? ORDER BY created_at", (task_id,))
        return [dict(r) for r in await cur.fetchall()]
