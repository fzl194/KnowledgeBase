from fastapi import FastAPI

from agent_serving.serving.api.health import router as health_router

app = FastAPI(
    title="Cloud Core Knowledge Backend",
    version="0.1.0",
    description="Agent Knowledge Backend for cloud core network.",
)

app.include_router(health_router)
