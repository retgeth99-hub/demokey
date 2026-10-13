from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes import health_router, router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.session import SessionFactory, engine
from app.worker.pipeline import AnalysisPipeline
from app.worker.poller import JobPoller

settings = get_settings()
configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pollers: list[JobPoller] = []
    worker_tasks: list[asyncio.Task[None]] = []
    if settings.worker_enabled:
        for index in range(settings.worker_concurrency):
            pipeline = AnalysisPipeline(SessionFactory, settings)
            poller = JobPoller(SessionFactory, settings, pipeline)
            pollers.append(poller)
            worker_tasks.append(
                asyncio.create_task(poller.run_forever(), name=f"analysis-worker-{index + 1}")
            )
    app.state.worker_pollers = pollers
    try:
        yield
    finally:
        for poller in pollers:
            await poller.stop()
        for worker_task in worker_tasks:
            try:
                await asyncio.wait_for(worker_task, timeout=10)
            except TimeoutError:
                worker_task.cancel()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="基于 PubMed 真实数据和 DeepSeek 的科研情报分析后端。",
    lifespan=lifespan,
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key", "Idempotency-Key"],
    )


@app.middleware("http")
async def correlation_id(request: Request, call_next: object) -> object:
    request.state.correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
    response = await call_next(request)  # type: ignore[operator]
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    return response


install_error_handlers(app)
app.include_router(health_router)
app.include_router(router)

