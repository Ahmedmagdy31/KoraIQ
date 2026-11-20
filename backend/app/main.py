from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import dispose_engine
from app.redis_client import close_redis
from app.routers import admin, game, leaderboard, predictions, progress, public, rewards, users

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title=f"{s.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if s.env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if s.env == "production" else "/openapi.json",
    )
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith(s.api_prefix):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    app.include_router(public.router)
    for r in (users.router, game.router, progress.router, predictions.router, leaderboard.router, rewards.router, admin.router):
        app.include_router(r, prefix=s.api_prefix)
    if s.env in ("development", "test"):
        app.include_router(rewards.dev_router, prefix=s.api_prefix)
    return app


app = create_app()
