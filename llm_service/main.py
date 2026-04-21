from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from jinja2 import Environment, FileSystemLoader

from llm_service.config import LLMServiceConfig
from llm_service.db import init_db
from llm_service.providers.base import ProviderProtocol
from llm_service.providers.openai_compatible import OpenAICompatibleProvider
from llm_service.runtime.service import LLMService

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app(
    config: LLMServiceConfig | None = None,
    provider_factory: Callable[[], ProviderProtocol] | None = None,
) -> FastAPI:
    cfg = config or LLMServiceConfig()
    _factory = provider_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = await init_db(cfg.db_path)
        provider = _factory() if _factory else OpenAICompatibleProvider(
            base_url=cfg.provider_base_url,
            api_key=cfg.provider_api_key,
            model=cfg.provider_model,
            headers=cfg.provider_headers,
            timeout=cfg.provider_timeout,
        )
        app.state.llm_service = LLMService(db=db, provider=provider, config=cfg)
        app.state.db = db
        app.state.templates = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=True,
        )
        yield
        await db.close()

    app = FastAPI(title="LLM Service", version="0.1.0", lifespan=lifespan)
    app.state.config = cfg

    from llm_service.api.health import router as health_router
    from llm_service.api.results import router as results_router
    from llm_service.api.tasks import router as tasks_router
    from llm_service.dashboard.views import router as dashboard_router

    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(results_router)
    app.include_router(dashboard_router)

    return app
