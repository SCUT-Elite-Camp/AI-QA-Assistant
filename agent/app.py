# app.py
import sys
from pathlib import Path

agent_dir = Path(__file__).resolve().parent
project_root = agent_dir.parent
for folder in [project_root, project_root / "data-pipeline", project_root / "data-persistence", project_root / "toolset"]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.api.chat_routes import router as chat_router
from agent.api.internal_memory_routes import router as internal_memory_router
from agent.config.settings import settings
from agent.logger.logger import get_logger, setup_logger
from agent.query import HybridIntentRouter
from toolset.tool_layer.registry import ToolRegistry


# 初始化日志
setup_logger(level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Starting {settings.APP_NAME}")

    app.state.retrieval_ready = False
    app.state.retrieval_preload_error = ""
    app.state.intent_ready = not settings.HYBRID_INTENT_ROUTER_ENABLED
    app.state.intent_preload_error = ""
    logger.info("Preloading retrieval model weights and dictionary (cold-start prevention)...")
    try:
        registry = ToolRegistry()
        search_tool = registry.get_tool("search_documents")
        if search_tool is None:
            raise RuntimeError("search_documents is not registered")

        # Warm retrieval through the Tool Layer directly. A startup task is not
        # a user query and must not pass through intent classification,
        # clarification, query planning, or answer generation.
        await asyncio.to_thread(
            search_tool.search,
            query="企业智能问答助手",
            top_k=1,
            mode="hybrid",
            filters=None,
            min_score=0.0,
            trace_id="startup-preload",
        )
        app.state.retrieval_ready = True
        logger.info("Retrieval model preloaded successfully!")
    except Exception as e:
        app.state.retrieval_preload_error = str(e) or e.__class__.__name__
        logger.exception("Failed to preload retrieval model")

    if settings.HYBRID_INTENT_ROUTER_ENABLED:
        logger.info("Preloading local intent embedding model (cold-start prevention)...")
        try:
            intent_router = HybridIntentRouter(enabled=True)
            await asyncio.to_thread(intent_router.warmup)
            app.state.intent_ready = True
            logger.info("Intent embedding model preloaded successfully!")
        except Exception as e:
            app.state.intent_preload_error = str(e) or e.__class__.__name__
            logger.exception(
                "Failed to preload intent embedding model; LLM fallback remains available"
            )
    yield

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
def readiness() -> dict[str, str | bool]:
    """Report whether local retrieval resources completed cold-start loading."""
    retrieval_ready = bool(getattr(app.state, "retrieval_ready", False))
    intent_ready = bool(getattr(app.state, "intent_ready", False))
    ready = retrieval_ready and intent_ready
    details = [
        value
        for value in (
            getattr(app.state, "retrieval_preload_error", ""),
            getattr(app.state, "intent_preload_error", ""),
        )
        if value
    ]
    return {
        "status": "ready" if ready else "degraded",
        "retrieval_ready": retrieval_ready,
        "intent_ready": intent_ready,
        "detail": "; ".join(details),
    }


app.include_router(chat_router, prefix="/api")
app.include_router(internal_memory_router, prefix="/api/internal")


# 添加直接运行的入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
