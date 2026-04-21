from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI

from llm_service.config import LLMServiceConfig
from llm_service.db import init_db
from llm_service.providers.base import ProviderProtocol
from llm_service.providers.mock import MockProvider
from llm_service.runtime.service import LLMService


def create_app(
    config: LLMServiceConfig | None = None,
    provider_factory: Callable[[], ProviderProtocol] | None = None,
) -> FastAPI:
    cfg = config or LLMServiceConfig()
    _factory = provider_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = await init_db(cfg.db_path)
        provider = _factory() if _factory else MockProvider()
        app.state.llm_service = LLMService(db=db, provider=provider, config=cfg)
        app.state.db = db
        yield
        await db.close()

    app = FastAPI(title="LLM Service", version="0.1.0", lifespan=lifespan)
    app.state.config = cfg

    from llm_service.api.health import router as health_router
    from llm_service.api.results import router as results_router
    from llm_service.api.tasks import router as tasks_router

    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(results_router)

    return app
