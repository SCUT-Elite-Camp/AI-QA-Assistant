# app.py
import sys
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
from agent.config.settings import settings
from agent.logger.logger import get_logger, setup_logger


# 初始化日志
setup_logger(level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Starting {settings.APP_NAME}")
    
    logger.info("Preloading retrieval model weights and dictionary (cold-start prevention)...")
    try:
        from agent.agent import Agent
        from agent.schemas.chat import ChatRequest
        agent = Agent()
        # Send a dummy request to trigger cold start loading of SearchTool
        dummy_request = ChatRequest(query="预热", top_k=1, retrieval_mode="hybrid")
        agent.chat(dummy_request)
        logger.info("Retrieval model preloaded successfully!")
    except Exception as e:
        logger.error(f"Failed to preload retrieval model: {e}")
        
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


app.include_router(chat_router, prefix="/api")


# 添加直接运行的入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
