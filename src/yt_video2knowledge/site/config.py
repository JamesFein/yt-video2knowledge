from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    db_path: Path
    assets_dir: Path
    password: str
    secret_key: str
    cookie_domain: str | None = None
    dev_mode: bool = False


def _resolve_path(value: str | None, root_dir: Path, default: Path) -> Path:
    if not value:
        return default
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return root_dir / path


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path | None = None,
    require_auth: bool = True,
) -> Settings:
    values = env or os.environ
    root = (root_dir or PROJECT_ROOT).resolve()
    password = values.get("KNOWLEDGE_SITE_PASSWORD", "")
    secret_key = values.get("KNOWLEDGE_SITE_SECRET_KEY", "")

    if require_auth:
        missing = []
        if not password:
            missing.append("KNOWLEDGE_SITE_PASSWORD")
        if not secret_key:
            missing.append("KNOWLEDGE_SITE_SECRET_KEY")
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variable(s): {names}")

    return Settings(
        root_dir=root,
        db_path=_resolve_path(
            values.get("KNOWLEDGE_SITE_DB"),
            root,
            root / "data" / "knowledge.sqlite3",
        ),
        assets_dir=_resolve_path(
            values.get("KNOWLEDGE_SITE_ASSETS_DIR"),
            root,
            root / "data" / "knowledge-assets",
        ),
        password=password,
        secret_key=secret_key,
        cookie_domain=values.get("KNOWLEDGE_SITE_COOKIE_DOMAIN") or None,
        dev_mode=values.get("KNOWLEDGE_SITE_DEV") == "1",
    )
