from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from .config import Settings, load_settings
from .database import initialize_database
from .routes import api_v1, pages


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings(require_auth=True)
    if not resolved.password or not resolved.secret_key:
        raise RuntimeError(
            "KNOWLEDGE_SITE_PASSWORD and KNOWLEDGE_SITE_SECRET_KEY are required for the web app."
        )

    initialize_database(resolved.db_path)
    resolved.assets_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Knowledge Site")
    app.state.settings = resolved
    app.add_middleware(
        SessionMiddleware,
        secret_key=resolved.secret_key,
        session_cookie="knowledge_site_session",
        max_age=60 * 60 * 24 * 15,
        same_site="lax",
        https_only=not resolved.dev_mode,
        domain=resolved.cookie_domain,
    )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/assets", StaticFiles(directory=resolved.assets_dir, check_dir=False), name="assets")
    app.include_router(pages.router)
    app.include_router(api_v1.router)
    return app
