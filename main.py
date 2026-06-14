"""
FastAPI主应用入口
职责：创建应用实例、集成中间件、挂载路由、处理请求生命周期
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import settings
from core.exceptions import BizError
from core.middleware import SelectiveGZipMiddleware
from modules.population.runtime_check import run_population_runtime_check
from router import admin_router, app_router
from store.ai_database import init_ai_db
from store import init_db

# ==================== 配置日志 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("应用启动中...")
    logger.info(f"基础URL: {settings.app_base_url}")
    logger.info(f"静态文件目录: {settings.static_dir}")
    logger.info("=" * 50)

    # 初始化数据库。数据库不可用时，静态工作台和只读工具元数据仍应可访问。
    try:
        await asyncio.to_thread(init_db)
    except Exception:
        logger.exception("数据库初始化失败，应用将以降级模式继续启动")

    try:
        await asyncio.to_thread(init_ai_db)
    except Exception:
        logger.exception("AI 文档数据库初始化失败，文档来源将以降级模式不可用")

    # 确保静态文件目录存在
    os.makedirs(settings.static_dir, exist_ok=True)
    await asyncio.to_thread(run_population_runtime_check)

    try:
        yield
    finally:
        logger.info("应用关闭中...")
        logger.info("应用已关闭")

async def validation_exception_handler(request, exc):
    body = exc.body
    if isinstance(body, (bytes, bytearray)):
        try:
            body = body.decode("utf-8")
        except Exception:
            body = str(body)
    logger.error(f"Validation Error: {body}")
    logger.error(f"Errors: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": body},
    )

async def biz_exception_handler(request, exc: BizError):
    logger.error(f"BizError: {exc.message} | Payload: {exc.payload}")
    return JSONResponse(
        status_code=exc.code,
        content={
            "status": "error",
            "message": exc.message,
            "detail": exc.payload
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="高德地图扣子插件API",
        description="接收JSON数据，生成地图页面并返回URL链接",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        SelectiveGZipMiddleware,
        minimum_size=500,
        excluded_paths={"/api/v1/analysis/agent/turn/stream"},
    )
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(BizError, biz_exception_handler)

    static_root = Path(settings.static_dir).resolve()
    os.makedirs(static_root, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_root), name="static")
    app.include_router(app_router)
    app.include_router(admin_router)
    return app


app = create_app()

# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn

    logger.info("启动FastAPI应用...")
    logger.info(f"访问地址: http://localhost:{settings.app_port}")
    logger.info(f"API文档: http://localhost:{settings.app_port}/docs")

    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        log_level="info"
    )
