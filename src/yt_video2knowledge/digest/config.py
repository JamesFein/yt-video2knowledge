"""Configuration, runtime state, and common serialization helpers."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from yt_video2knowledge.digest.errors import ConfigurationError
from yt_video2knowledge.paths import (
    BROWSER_DIAGNOSTICS_DIR,
    DATA_DIR,
    PLAYWRIGHT_TMP_DIR,
    PROJECT_ROOT,
    STATE_DIR,
)

DEFAULT_CONFIG_PATH = DATA_DIR / "knowledge_config.json"
DEFAULT_STATE_PATH = STATE_DIR / "knowledge_digest_state.json"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env.local"
DEFAULT_AUTOMATION_PROFILE_DIR = DATA_DIR / "chrome-automation-profile"
DEFAULT_CHROME_SOURCE_PROFILE_DIR = Path.home() / "Library/Application Support/Google/Chrome"
DEFAULT_YOUTUBE_CLIENT_SECRETS_PATH = DATA_DIR / "youtube-oauth-client.json"
DEFAULT_YOUTUBE_TOKEN_PATH = DATA_DIR / "youtube-oauth-token.json"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class DigestConfig:
    playlist_url: str
    playlist_name: str
    timezone: str
    browser: str
    browser_mode: str
    chrome_channel: str
    chrome_user_data_dir: str
    chrome_source_profile_dir: str
    chrome_automation_profile_dir: str
    chrome_cdp_url: str
    youtube_client_secrets_path: str
    youtube_token_path: str
    openai_base_url: str
    openai_model: str
    summary_language: str
    mlx_whisper_model: str
    output_root: str

    @property
    def output_root_path(self) -> Path:
        return PROJECT_ROOT / self.output_root

def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def load_env_file(env_path: Path = DEFAULT_ENV_PATH) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def normalize_playlist_url(playlist_url: str) -> str:
    parsed = urllib.parse.urlparse(playlist_url)
    query = urllib.parse.parse_qs(parsed.query)
    playlist_id = query.get("list", [None])[0]
    if not playlist_id:
        return playlist_url
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def extract_playlist_id(playlist_url: str) -> str:
    parsed = urllib.parse.urlparse(playlist_url)
    query = urllib.parse.parse_qs(parsed.query)
    playlist_id = query.get("list", [None])[0]
    if not playlist_id:
        raise ConfigurationError(f"Unable to extract playlist id from URL: {playlist_url}")
    return playlist_id


def load_config(config_path: Path = DEFAULT_CONFIG_PATH, playlist_url: str | None = None) -> DigestConfig:
    load_env_file()
    payload = _read_json(config_path, {})
    payload["playlist_url"] = normalize_playlist_url(playlist_url or payload.get("playlist_url", ""))
    payload.setdefault("playlist_name", "knowledge")
    payload.setdefault("timezone", "Asia/Shanghai")
    payload.setdefault("browser", "chrome")
    payload.setdefault("browser_mode", "managed")
    payload.setdefault("chrome_channel", "chrome")
    payload.setdefault("chrome_source_profile_dir", str(DEFAULT_CHROME_SOURCE_PROFILE_DIR))
    payload.setdefault("chrome_automation_profile_dir", str(DEFAULT_AUTOMATION_PROFILE_DIR.relative_to(PROJECT_ROOT)))
    payload.setdefault("chrome_user_data_dir", payload.get("chrome_automation_profile_dir"))
    payload.setdefault("chrome_cdp_url", "http://127.0.0.1:9222")
    payload.setdefault("youtube_client_secrets_path", str(DEFAULT_YOUTUBE_CLIENT_SECRETS_PATH.relative_to(PROJECT_ROOT)))
    payload.setdefault("youtube_token_path", str(DEFAULT_YOUTUBE_TOKEN_PATH.relative_to(PROJECT_ROOT)))
    payload.setdefault("openai_base_url", "")
    payload.setdefault("openai_model", "")
    payload.setdefault("summary_language", "zh-CN")
    payload.setdefault("mlx_whisper_model", "mlx-community/whisper-small-mlx")
    payload.setdefault("output_root", "data/runs")
    if not payload["playlist_url"]:
        raise ConfigurationError(f"Missing playlist_url in {config_path}")
    return DigestConfig(**payload)


def load_state(state_path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    return _read_json(state_path, {"last_run_at": None, "last_target_date": None, "videos": {}})


def save_state(state: dict[str, Any], state_path: Path = DEFAULT_STATE_PATH) -> None:
    _write_json(state_path, state)


def ensure_output_dirs(config: DigestConfig) -> None:
    config.output_root_path.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PLAYWRIGHT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    BROWSER_DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def parse_target_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return (beijing_now() - timedelta(days=1)).date()


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
