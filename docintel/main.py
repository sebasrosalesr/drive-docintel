"""FastAPI app: API under /api, the built SPA at /, the sync loop in a daemon thread."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import sync
from .api import ask_routes, auth_routes, data_routes, drive_routes
from .config import ROOT, settings
from .db import IS_SQLITE, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("docintel")
DIST = ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.google_ready or settings.watch_dir:
        sync.start_scheduler()
        log.info("sync loop every %ss (google=%s, watch_dir=%s)", settings.sync_interval_seconds, settings.google_ready, settings.watch_dir)
    else:
        log.info("neither Google OAuth nor WATCH_DIR configured; sync loop off (uploads and run_local still work)")
    yield
    sync.stop_scheduler()


app = FastAPI(title="Drive DocIntel", lifespan=lifespan)
for r in (auth_routes.router, drive_routes.router, data_routes.router, ask_routes.router):
    app.include_router(r)

OPEN_PATHS = {"/api/health", "/api/login", "/api/me", "/api/auth/google/start", "/api/auth/google/callback"}


@app.middleware("http")
async def app_password_gate(request: Request, call_next):
    """When APP_PASSWORD is set, every /api route except sign-in and health needs the app cookie."""
    if settings.app_password and request.url.path.startswith("/api/") and request.url.path not in OPEN_PATHS:
        from . import auth
        if not auth.app_authed(request):
            return JSONResponse({"detail": "sign in first"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True, "db": "sqlite" if IS_SQLITE else "postgres", "google": settings.google_ready, "llm": settings.llm_ready, "sync": sync.status()}


if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        file = DIST / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(DIST / "index.html")
else:

    @app.get("/")
    def no_frontend():
        return JSONResponse({"hint": "frontend not built: cd frontend && npm run build", "api": "/docs"})
