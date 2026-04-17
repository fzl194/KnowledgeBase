"""FastAPI application with SQLite dev mode and DB injection.

Supports two modes:
- Production: COREMASTERKB_ASSET_DB_PATH points to Mining-generated SQLite DB
- Dev/test: in-memory SQLite with shared DDL (no data by default)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import aiosqlite
from fastapi import FastAPI, Request

from agent_serving.serving.api.health import router as health_router
from agent_serving.serving.api.search import router as search_router
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite

_DB_PATH_ENV = "COREMASTERKB_ASSET_DB_PATH"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get(_DB_PATH_ENV)
    if db_path:
        # Read-only connection to Mining-generated SQLite DB
        db = await aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        # Dev/test mode: in-memory with shared DDL
        db = await aiosqlite.connect(":memory:")
        await create_asset_tables_sqlite(db)
    db.row_factory = aiosqlite.Row
    app.state.db = db
    yield
    await db.close()


def get_repo(request: Request) -> AssetRepository:
    return AssetRepository(request.app.state.db)


app = FastAPI(
    title="Cloud Core Knowledge Backend",
    version="0.1.0",
    description="Agent Knowledge Backend for cloud core network.",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(search_router)
