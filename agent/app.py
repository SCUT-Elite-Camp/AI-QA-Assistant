# app.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

from agent.api.chat_routes import router as chat_router
from agent.logger.logger import setup_logger, get_logger
from agent.config.settings import settings


# 初始化日志
setup_logger(level=settings.LOG_LEVEL, log_file=settings.LOG_FILE)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Starting {settings.APP_NAME} in {'mock' if settings.is_mock_mode else 'real'} mode")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan
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