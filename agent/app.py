# app.py
import sys
import asyncio
from pathlib import Path

agent_dir = Path(__file__).resolve().parent
project_root = agent_dir.parent
for folder in [project_root, project_root / "data-pipeline", project_root / "data-persistence", project_root / "toolset"]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.api.chat_routes import router as chat_router
from agent.api.internal_memory_routes import router as internal_memory_router
from agent.api.research_routes import router as research_router
from agent.config.settings import settings
from agent.logger.logger import get_logger, setup_logger
from agent.runtime.lifecycle import get_application_container


# 初始化日志
setup_logger(level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Starting {settings.APP_NAME}")

    container = get_application_container()
    app.state.application_container = container
    app.state.agent = container.startup()
    logger.info("Application-scoped Agent, LLM client, registry and tools initialized")
    warmup_task = asyncio.create_task(asyncio.to_thread(container.warmup_retrieval))
    app.state.retrieval_warmup_task = warmup_task

    yield

    if not warmup_task.done():
        warmup_task.cancel()
    container.shutdown()
    logger.info("Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, str | bool | int]:
    snapshot = get_application_container().snapshot()
    return {
        "status": "ready" if snapshot.retrieval_ready else "degraded",
        "initialized": snapshot.initialized,
        "initialization_count": snapshot.initialization_count,
        "initialization_ms": snapshot.initialization_ms,
        "retrieval_ready": snapshot.retrieval_ready,
        "detail": snapshot.retrieval_error,
    }


app.include_router(chat_router, prefix="/api")
app.include_router(internal_memory_router, prefix="/api/internal")
app.include_router(research_router, prefix="/api")


# 添加直接运行的入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
