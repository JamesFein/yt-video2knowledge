#!/usr/bin/env python3
"""Shared helpers for the local YouTube knowledge digest workflow."""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from opencc import OpenCC

ROOT_DIR = Path(__file__).resolve().parent.parent
PROMPT_DIR = ROOT_DIR / "prompts"
DATA_DIR = ROOT_DIR / "data"
STATE_DIR = DATA_DIR / "state"
DEFAULT_CONFIG_PATH = DATA_DIR / "knowledge_config.json"
DEFAULT_STATE_PATH = STATE_DIR / "knowledge_digest_state.json"
DEFAULT_ENV_PATH = ROOT_DIR / ".env.local"
PLAYWRIGHT_TMP_DIR = ROOT_DIR / ".playwright-tmp"
DEFAULT_AUTOMATION_PROFILE_DIR = DATA_DIR / "chrome-automation-profile"
DEFAULT_CHROME_SOURCE_PROFILE_DIR = Path.home() / "Library/Application Support/Google/Chrome"
BROWSER_DIAGNOSTICS_DIR = DATA_DIR / "browser-diagnostics"
DEFAULT_YOUTUBE_CLIENT_SECRETS_PATH = DATA_DIR / "youtube-oauth-client.json"
DEFAULT_YOUTUBE_TOKEN_PATH = DATA_DIR / "youtube-oauth-token.json"
PLAYWRIGHT_IGNORE_DEFAULT_ARGS = [
    "--enable-automation",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-sync",
    "--password-store=basic",
    "--use-mock-keychain",
]
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
YOUTUBE_READONLY_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
SUMMARY_INLINE_ATTEMPTS = 3
SUMMARY_MAX_ATTEMPTS = 3
SUMMARY_RETRY_WINDOW = timedelta(hours=24)
SUMMARY_RETRY_BACKOFF_SECONDS = (30, 120, 300)
SUMMARY_INCOMPLETE_RETRY_BACKOFF_SECONDS = (2, 5)
SUMMARY_ARTICLE_MAX_TOKENS = 4096
SUMMARY_CHUNK_MAX_CHARS = 120000
SUMMARY_COMPLETE_MARKER = "<!-- SUMMARY_COMPLETE -->"
EVIDENCE_COMPLETE_MARKER = "<!-- EVIDENCE_COMPLETE -->"
SUMMARY_ARTICLE_PROMPT_PATH = Path("production/summary-article-v5.md")
SUMMARY_EVIDENCE_PROMPT_PATH = Path("production/summary-evidence-v1.md")
_SIMPLIFIED_CHINESE_CONVERTER = OpenCC("t2s")
NON_RETRYABLE_SUMMARY_ERROR_MARKERS = (
    "missing runtime configuration",
    "invalid api key",
    "incorrect api key",
    "unauthorized",
    "authentication",
    "permission denied",
    "invalid_request",
    "invalid request",
    "configuration",
    "parameter",
)
TRANSIENT_NETWORK_ERROR_MARKERS = (
    "unexpected_eof_while_reading",
    "eof occurred in violation",
    "incompleteread",
    "incomplete read",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "remote end closed",
    "remote disconnected",
    "temporarily unavailable",
)
YT_DLP_MEDIA_FORBIDDEN_MARKERS = (
    "http error 403",
    "unable to download video data",
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
)
YT_DLP_AUDIO_FALLBACK_FORMATS = ("251", "140", "250", "249", "92", "93", "94", "bestaudio/best")
DEVTOOLS_ACTIVE_PORT_CANDIDATES = [
    Path.home() / "Library/Application Support/Google/Chrome/DevToolsActivePort",
    Path.home() / "Library/Application Support/Google/Chrome/Default/DevToolsActivePort",
]


class DigestError(RuntimeError):
    """Base error for digest workflow."""


class MissingDependencyError(DigestError):
    """Raised when an external dependency is unavailable."""


class ConfigurationError(DigestError):
    """Raised when runtime configuration is incomplete."""


def _load_prompt(relative_path: Path) -> str:
    path = PROMPT_DIR / relative_path
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError(f"Unable to read prompt file: {path}") from exc
    if not prompt:
        raise ConfigurationError(f"Prompt file is empty: {path}")
    return prompt


class ExternalCommandError(DigestError):
    """Raised when an external command fails."""


class BrowserConnectionError(DigestError):
    """Raised when the current Chrome CDP endpoint cannot be used."""


class ModelResponseError(DigestError):
    """Raised when a model response cannot safely be used."""

    failure_kind = "model_response_error"

    def __init__(
        self,
        message: str,
        *,
        response_id: str | None = None,
        provider: str | None = None,
        provider_status: str | None = None,
        stop_reason: str | None = None,
        output_chars: int = 0,
        validation_errors: list[str] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.provider = provider
        self.provider_status = provider_status
        self.stop_reason = stop_reason
        self.output_chars = output_chars
        self.validation_errors = list(validation_errors or [])
        self.usage = dict(usage or {})


class TransportModelResponseError(ModelResponseError):
    """Raised when the HTTP or JSON response is incomplete."""

    failure_kind = "transport_error"


class IncompleteModelResponseError(ModelResponseError):
    """Raised when the provider or completion marker reports truncation."""

    failure_kind = "incomplete_response"


class InvalidSummaryArticleError(ModelResponseError):
    """Raised when generated Markdown fails minimum structural checks."""

    failure_kind = "invalid_structure"


class PolicyModelResponseError(ModelResponseError):
    """Raised when the provider refuses the request for policy reasons."""

    failure_kind = "policy_rejection"


class ProviderModelResponseError(ModelResponseError):
    """Raised when the provider reports a non-policy request failure."""

    failure_kind = "provider_error"


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
        return ROOT_DIR / self.output_root


@dataclass
class TranscriptResult:
    text: str
    language: str
    source: str
    segments: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    text: str
    provider: str
    response_id: str | None = None
    provider_status: str = "missing"
    stop_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedSummary:
    text: str
    response: ModelResponse


@dataclass
class PlaylistFetchResult:
    entries: list[dict[str, Any]]
    cookie_file: Path | None
    browser_mode: str
    diagnostics_dir: Path | None = None


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
    payload.setdefault("chrome_automation_profile_dir", str(DEFAULT_AUTOMATION_PROFILE_DIR.relative_to(ROOT_DIR)))
    payload.setdefault("chrome_user_data_dir", payload.get("chrome_automation_profile_dir"))
    payload.setdefault("chrome_cdp_url", "http://127.0.0.1:9222")
    payload.setdefault("youtube_client_secrets_path", str(DEFAULT_YOUTUBE_CLIENT_SECRETS_PATH.relative_to(ROOT_DIR)))
    payload.setdefault("youtube_token_path", str(DEFAULT_YOUTUBE_TOKEN_PATH.relative_to(ROOT_DIR)))
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


def parse_vtt(vtt_file: Path) -> list[dict[str, Any]]:
    content = vtt_file.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    transcript: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(lines):
        line = lines[cursor].strip()
        if "-->" not in line:
            cursor += 1
            continue
        start_time = line.split("-->", 1)[0].strip()
        parts = start_time.replace(",", ".").split(":")
        seconds = 0.0
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        cursor += 1
        chunk: list[str] = []
        while cursor < len(lines) and lines[cursor].strip() and "-->" not in lines[cursor]:
            text = re.sub(r"<[^>]+>", "", lines[cursor]).strip()
            if text and not text.isdigit():
                chunk.append(text)
            cursor += 1
        if chunk:
            transcript.append({"start": seconds, "text": " ".join(chunk)})
    return transcript


def format_transcript(transcript: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{format_timestamp(entry['start'])}] {entry['text']}" for entry in transcript)


def _run_command(cmd: list[str], timeout: int = 120, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            check=False,
        )
    except FileNotFoundError as exc:
        raise MissingDependencyError(f"Missing dependency: {cmd[0]}") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise ExternalCommandError(f"Command failed: {' '.join(cmd)}\n{stderr}")
    return completed


def _yt_dlp_base(browser: str | None = None, cookies_path: Path | None = None) -> list[str]:
    cmd = [os.environ.get("YT_DLP_BIN") or "yt-dlp", "--no-warnings"]
    if cookies_path:
        cmd.extend(["--cookies", str(cookies_path)])
    elif browser:
        cmd.extend(["--cookies-from-browser", browser])
    return cmd


def _is_yt_dlp_media_forbidden_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in YT_DLP_MEDIA_FORBIDDEN_MARKERS)


def _cleanup_partial_audio_downloads(output_dir: Path) -> None:
    for path in output_dir.glob("source_audio.*"):
        if path.suffix in {".part", ".ytdl"}:
            path.unlink(missing_ok=True)


def _find_existing_source_audio(output_dir: Path) -> Path | None:
    candidates = [
        path
        for path in output_dir.glob("source_audio.*")
        if path.suffix not in {".part", ".ytdl", ".wav"} and not path.name.endswith(".json")
    ]
    return candidates[0] if candidates else None


def _download_audio_format(
    video_id: str,
    output_dir: Path,
    format_selector: str,
    browser: str | None = None,
    cookies_path: Path | None = None,
) -> Path:
    template = output_dir / "source_audio.%(ext)s"
    cmd = _yt_dlp_base(browser, cookies_path)
    cmd.extend(
        [
            "-f",
            format_selector,
            "-o",
            str(template),
            f"https://www.youtube.com/watch?v={video_id}",
        ]
    )
    try:
        _run_command(cmd, timeout=600)
    except ExternalCommandError as exc:
        if "http error 403" not in str(exc).lower():
            raise
        _cleanup_partial_audio_downloads(output_dir)
        _run_command(cmd, timeout=600)
    candidates = [
        path
        for path in output_dir.glob("source_audio.*")
        if path.suffix not in {".part", ".ytdl"} and not path.name.endswith(".json")
    ]
    if not candidates:
        raise ExternalCommandError(f"No audio file downloaded for {video_id} with format {format_selector}")
    return candidates[0]


def fetch_video_info(video_id: str, browser: str | None = None, cookies_path: Path | None = None) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    attempts: list[tuple[str | None, Path | None]] = []
    if cookies_path:
        attempts.append((None, cookies_path))
    if browser:
        attempts.append((browser, None))
    attempts.append((None, None))
    last_error: Exception | None = None
    for current_browser, current_cookies in attempts:
        try:
            cmd = _yt_dlp_base(current_browser, current_cookies)
            cmd.extend(["--dump-json", "--skip-download", url])
            completed = _run_command(cmd, timeout=120)
            return json.loads(completed.stdout)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise ExternalCommandError(f"Unable to fetch metadata for {video_id}: {last_error}") from last_error


def download_thumbnail(
    video_id: str,
    output_dir: Path,
    browser: str | None = None,
    cookies_path: Path | None = None,
) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = _yt_dlp_base(browser, cookies_path)
    cmd.extend(
        [
            "--write-thumbnail",
            "--skip-download",
            "-o",
            str(output_dir / "thumbnail"),
            f"https://www.youtube.com/watch?v={video_id}",
        ]
    )
    try:
        _run_command(cmd, timeout=120)
    except DigestError:
        return None
    for candidate in output_dir.glob("thumbnail.*"):
        if candidate.suffix in {".webp", ".jpg", ".jpeg", ".png"}:
            return candidate
    return None


def _resolve_subtitle_file(video_id: str, output_dir: Path) -> tuple[Path | None, str]:
    files = sorted(output_dir.glob(f"sub_{video_id}*.vtt"))
    if not files:
        return None, ""
    chosen = files[0]
    match = re.search(rf"sub_{re.escape(video_id)}\.([^.]+)", chosen.name)
    return chosen, match.group(1) if match else ""


def download_transcript(
    video_id: str,
    output_dir: Path,
    browser: str | None = None,
    cookies_path: Path | None = None,
) -> tuple[TranscriptResult | None, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_template = str(output_dir / f"sub_{video_id}")
    attempts = [
        ("official", ["--write-sub", "--no-write-auto-sub"]),
        ("auto", ["--write-auto-sub", "--no-write-sub"]),
    ]
    diagnostics: dict[str, Any] = {
        "official_subtitle_available": False,
        "auto_subtitle_available": False,
        "used_source": None,
        "fallback_reason": None,
        "attempts": [],
    }
    for source, subtitle_flags in attempts:
        attempt_payload: dict[str, Any] = {"source": source, "available": False, "language": "", "error": None}
        for existing in output_dir.glob(f"sub_{video_id}*"):
            existing.unlink(missing_ok=True)
        cmd = _yt_dlp_base(browser, cookies_path)
        cmd.extend(
            [
                "--skip-download",
                "--sub-lang",
                "zh-Hans,zh-Hant,zh,en,en-US,en-GB",
                "--sub-format",
                "vtt",
                "-o",
                output_template,
            ]
        )
        cmd.extend(subtitle_flags)
        cmd.append(url)
        try:
            _run_command(cmd, timeout=240)
        except DigestError as exc:
            attempt_payload["error"] = str(exc)
            diagnostics["attempts"].append(attempt_payload)
            continue
        subtitle_file, language = _resolve_subtitle_file(video_id, output_dir)
        if not subtitle_file:
            attempt_payload["error"] = "subtitle file not found"
            diagnostics["attempts"].append(attempt_payload)
            continue
        transcript = parse_vtt(subtitle_file)
        if transcript:
            attempt_payload["available"] = True
            attempt_payload["language"] = language or "unknown"
            diagnostics["attempts"].append(attempt_payload)
            diagnostics[f"{source}_subtitle_available"] = True
            diagnostics["used_source"] = source
            return TranscriptResult(
                text=format_transcript(transcript),
                language=language or "unknown",
                source=source,
                segments=transcript,
                details={"subtitle_attempts": diagnostics["attempts"]},
            ), diagnostics
        attempt_payload["error"] = "parsed subtitle was empty"
        diagnostics["attempts"].append(attempt_payload)
    diagnostics["fallback_reason"] = "no_subtitles_found"
    return None, diagnostics


def download_audio(
    video_id: str,
    output_dir: Path,
    browser: str | None = None,
    cookies_path: Path | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_audio = _find_existing_source_audio(output_dir)
    if existing_audio:
        return existing_audio

    attempts: list[tuple[str, str]] = []

    credential_modes: list[tuple[str | None, Path | None]] = []
    if cookies_path:
        credential_modes.append((None, cookies_path))
    if browser:
        credential_modes.append((browser, None))
    credential_modes.append((None, None))

    tried_keys: set[tuple[str | None, str | None]] = set()
    deduped_modes: list[tuple[str | None, Path | None]] = []
    for current_browser, current_cookies in credential_modes:
        key = (current_browser, str(current_cookies) if current_cookies else None)
        if key in tried_keys:
            continue
        tried_keys.add(key)
        deduped_modes.append((current_browser, current_cookies))

    for current_browser, current_cookies in deduped_modes:
        _cleanup_partial_audio_downloads(output_dir)
        try:
            return _download_audio_format(video_id, output_dir, "bestaudio/best", current_browser, current_cookies)
        except DigestError as exc:
            attempts.append(("bestaudio/best", str(exc)))
            if not _is_yt_dlp_media_forbidden_error(exc):
                raise

        for format_selector in YT_DLP_AUDIO_FALLBACK_FORMATS:
            _cleanup_partial_audio_downloads(output_dir)
            try:
                return _download_audio_format(video_id, output_dir, format_selector, current_browser, current_cookies)
            except DigestError as exc:
                attempts.append((format_selector, str(exc)))

    attempt_lines = "\n".join(f"- {format_selector}: {error}" for format_selector, error in attempts)
    raise ExternalCommandError(f"Unable to download audio for {video_id} after yt-dlp fallback attempts:\n{attempt_lines}")


def convert_audio_to_wav(source_audio: Path, wav_path: Path) -> Path:
    cmd = ["ffmpeg", "-y", "-i", str(source_audio), "-ar", "16000", "-ac", "1", str(wav_path)]
    _run_command(cmd, timeout=600)
    return wav_path


def _mlx_transcribe_file(audio_path: Path, model_name: str) -> dict[str, Any]:
    try:
        import mlx_whisper  # type: ignore
    except ImportError as exc:
        raise MissingDependencyError("Missing dependency: mlx-whisper") from exc
    try:
        return mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=model_name, verbose=False)
    except TypeError:
        return mlx_whisper.transcribe(str(audio_path), model=model_name)


def transcribe_audio(source_audio: Path, model_name: str) -> TranscriptResult:
    wav_path = source_audio.with_suffix(".wav")
    used_wav_fallback = False
    try:
        result = _mlx_transcribe_file(source_audio, model_name)
    except Exception:  # noqa: BLE001
        used_wav_fallback = True
        convert_audio_to_wav(source_audio, wav_path)
        result = _mlx_transcribe_file(wav_path, model_name)
    segments = result.get("segments", []) if isinstance(result, dict) else []
    if segments:
        transcript_text = "\n".join(
            f"[{format_timestamp(segment.get('start', 0.0))}] {segment.get('text', '').strip()}"
            for segment in segments
            if segment.get("text")
        )
    else:
        transcript_text = result.get("text", "").strip() if isinstance(result, dict) else str(result).strip()
        segments = [{"start": 0.0, "text": transcript_text}] if transcript_text else []
    if not transcript_text:
        raise DigestError("mlx-whisper returned an empty transcript")
    wav_path.unlink(missing_ok=True)
    return TranscriptResult(
        text=transcript_text,
        language=result.get("language", "auto") if isinstance(result, dict) else "auto",
        source="mlx-whisper",
        segments=segments,
        details={
            "model": model_name,
            "used_wav_fallback": used_wav_fallback,
            "source_audio_suffix": source_audio.suffix,
        },
    )


def _extract_json_assignment(html_text: str, markers: list[str]) -> dict[str, Any]:
    for marker in markers:
        marker_index = html_text.find(marker)
        if marker_index == -1:
            continue
        start = html_text.find("{", marker_index)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(html_text)):
            char = html_text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    payload = html_text[start : index + 1]
                    return json.loads(payload)
    raise DigestError(f"Unable to locate any JSON payload from markers: {markers}")


def _extract_text(node: Any) -> str:
    if isinstance(node, dict):
        if isinstance(node.get("simpleText"), str):
            return node["simpleText"]
        if isinstance(node.get("runs"), list):
            return "".join(part.get("text", "") for part in node["runs"] if isinstance(part, dict))
    return ""


def _collect_text_fragments(node: Any, fragments: list[str] | None = None) -> list[str]:
    fragments = fragments or []
    if isinstance(node, dict):
        text_value = _extract_text(node)
        if text_value:
            fragments.append(text_value)
        for value in node.values():
            _collect_text_fragments(value, fragments)
    elif isinstance(node, list):
        for item in node:
            _collect_text_fragments(item, fragments)
    return fragments


def _walk_renderers(node: Any) -> list[dict[str, Any]]:
    renderers: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"playlistVideoRenderer", "playlistPanelVideoRenderer"} and isinstance(value, dict):
                renderers.append(value)
            renderers.extend(_walk_renderers(value))
    elif isinstance(node, list):
        for item in node:
            renderers.extend(_walk_renderers(item))
    return renderers


def detect_added_text(fragments: list[str]) -> str | None:
    patterns = [
        re.compile(r"\badded(\s+to\s+playlist)?\b", re.IGNORECASE),
        re.compile(r"(添加到播放列表|加入播放列表|加入清单|加入收藏)"),
        re.compile(r"(added on|added yesterday|added today)", re.IGNORECASE),
    ]
    for fragment in fragments:
        normalized = " ".join(fragment.split())
        if any(pattern.search(normalized) for pattern in patterns):
            return normalized
    return None


def parse_added_date_text(text: str, reference: datetime | None = None) -> date | None:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return None
    reference = reference or beijing_now()
    normalized = cleaned.lower()

    absolute_patterns = [
        (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y-%m-%d"),
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", "%Y/%m/%d"),
    ]
    for pattern, fmt in absolute_patterns:
        match = re.search(pattern, cleaned)
        if match:
            return datetime.strptime(match.group(0), fmt).date()

    chinese_absolute = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", cleaned)
    if chinese_absolute:
        year, month, day = chinese_absolute.groups()
        return date(int(year), int(month), int(day))

    month_name = re.search(
        r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:,\s*(\d{4}))?",
        normalized,
    )
    if month_name:
        raw_month, raw_day, raw_year = month_name.groups()
        month_lookup = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        year = int(raw_year) if raw_year else reference.year
        return date(year, month_lookup[raw_month[:3]], int(raw_day))

    relative_keywords = {
        "today": 0,
        "yesterday": 1,
        "前天": 2,
    }
    for keyword, days_ago in relative_keywords.items():
        if keyword in normalized or keyword in cleaned:
            return (reference - timedelta(days=days_ago)).date()
    if "今天" in cleaned:
        return reference.date()
    if "昨天" in cleaned:
        return (reference - timedelta(days=1)).date()

    english_relative = re.search(r"(\d+)\s+(day|week|month|year)s?\s+ago", normalized)
    if english_relative:
        amount = int(english_relative.group(1))
        unit = english_relative.group(2)
        factor = {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
        return (reference - timedelta(days=amount * factor)).date()

    chinese_relative = re.search(r"(\d+)\s*(天|周|个月|月|年)前", cleaned)
    if chinese_relative:
        amount = int(chinese_relative.group(1))
        unit = chinese_relative.group(2)
        factor = {"天": 1, "周": 7, "个月": 30, "月": 30, "年": 365}[unit]
        return (reference - timedelta(days=amount * factor)).date()
    return None


def _fetch_html(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="ignore")


def _fetch_playlist_entries_via_html(playlist_url: str) -> list[dict[str, Any]]:
    html_text = _fetch_html(playlist_url)
    initial_data = _extract_json_assignment(
        html_text,
        [
            "var ytInitialData = ",
            "window['ytInitialData'] = ",
            'window["ytInitialData"] = ',
            "ytInitialData = ",
        ],
    )
    entries: list[dict[str, Any]] = []
    for renderer in _walk_renderers(initial_data):
        video_id = renderer.get("videoId")
        if not video_id:
            continue
        fragments = list(dict.fromkeys(fragment.strip() for fragment in _collect_text_fragments(renderer) if fragment.strip()))
        added_text = detect_added_text(fragments)
        entries.append(
            {
                "id": video_id,
                "title": _extract_text(renderer.get("title")) or f"Video {video_id}",
                "channel_name": _extract_text(renderer.get("shortBylineText")) or "",
                "duration": _extract_text(renderer.get("lengthText")) or "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "playlist_added_text": added_text,
                "playlist_added_date": parse_added_date_text(added_text or ""),
                "raw_text_fragments": fragments,
            }
        )
    if not entries:
        raise DigestError("No playlist entries were found in the playlist page")
    return entries


def _normalize_playlist_payload(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in payload:
        href = item.get("href", "")
        match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", href)
        if not match:
            bare = re.search(r"/watch/([A-Za-z0-9_-]{11})", href)
            if bare:
                match = bare
        if not match:
            continue
        raw_fragments = [" ".join(fragment.split()) for fragment in item.get("raw_text_fragments", []) if fragment.strip()]
        cleaned_fragments = [
            fragment
            for fragment in raw_fragments
            if fragment
            and fragment.lower() != "now playing"
            and fragment not in {"正在播放", "Play all", "Manual"}
            and not re.fullmatch(r"\d+", fragment)
            and not re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", fragment)
        ]
        fallback_title = cleaned_fragments[0] if cleaned_fragments else f"Video {match.group(1)}"
        fallback_channel = cleaned_fragments[1] if len(cleaned_fragments) > 1 else ""
        normalized_title = " ".join(item.get("title", "").split())
        if not normalized_title or "Now playing" in normalized_title or re.fullmatch(r"[\d:\s▶]+", normalized_title):
            normalized_title = fallback_title
        normalized_channel = " ".join(item.get("channel_name", "").split()) or fallback_channel
        added_text = detect_added_text(item.get("raw_text_fragments", []))
        entries.append(
            {
                "id": match.group(1),
                "title": normalized_title,
                "channel_name": normalized_channel,
                "duration": " ".join(item.get("duration", "").split()),
                "url": f"https://www.youtube.com/watch?v={match.group(1)}",
                "playlist_added_text": added_text,
                "playlist_added_date": parse_added_date_text(added_text or ""),
                "raw_text_fragments": raw_fragments,
            }
        )
    return entries


def _parse_cdp_host_port(cdp_url: str) -> tuple[str, int]:
    normalized = cdp_url.replace("ws://", "http://").replace("wss://", "https://")
    parsed = urllib.parse.urlparse(normalized)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return host, port


def _read_devtools_active_port(host: str, port: int) -> str | None:
    for candidate in DEVTOOLS_ACTIVE_PORT_CANDIDATES:
        if not candidate.exists():
            continue
        lines = [line.strip() for line in candidate.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        if lines[0] == str(port):
            return f"ws://{host}:{port}{lines[1]}"
    return None


def resolve_chrome_cdp_endpoint(cdp_url: str) -> str:
    host, port = _parse_cdp_host_port(cdp_url)
    sock = socket.socket()
    sock.settimeout(2)
    try:
        sock.connect((host, port))
    except OSError as exc:
        raise BrowserConnectionError(
            f"无法连接到当前 Chrome 的远程调试端口 {host}:{port}。"
            "请确认 Chrome 正在运行，并且已开启 remote debugging。"
        ) from exc
    finally:
        sock.close()

    websocket_endpoint = _read_devtools_active_port(host, port)
    if websocket_endpoint:
        return websocket_endpoint

    version_url = cdp_url.rstrip("/") + "/json/version"
    request = urllib.request.Request(version_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BrowserConnectionError(
            f"Chrome CDP 端口 {host}:{port} 已打开，但无法读取 {version_url}。"
        ) from exc
    if "webSocketDebuggerUrl" not in payload:
        raise BrowserConnectionError(f"Chrome CDP endpoint 未返回 webSocketDebuggerUrl: {version_url}")
    return str(payload["webSocketDebuggerUrl"])


def _automation_profile_path(config: DigestConfig) -> Path:
    raw = config.chrome_automation_profile_dir or config.chrome_user_data_dir
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _youtube_client_secrets_path(config: DigestConfig) -> Path:
    path = Path(config.youtube_client_secrets_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _youtube_token_path(config: DigestConfig) -> Path:
    path = Path(config.youtube_token_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _source_profile_root(config: DigestConfig) -> Path:
    path = Path(config.chrome_source_profile_dir).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _source_default_profile_path(config: DigestConfig) -> Path:
    return _source_profile_root(config) / "Default"


def _is_google_chrome_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "Google Chrome"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _remove_path_if_exists(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _cleanup_profile_runtime_artifacts(profile_root: Path) -> None:
    patterns = [
        "Singleton*",
        "DevToolsActivePort",
        "Crashpad",
        "BrowserMetrics",
        "ShaderCache",
        "GrShaderCache",
        "GraphiteDawnCache",
        "Default/Code Cache",
        "Default/GPUCache",
    ]
    for pattern in patterns:
        for candidate in profile_root.glob(pattern):
            _remove_path_if_exists(candidate)


def seed_automation_profile_from_current(config: DigestConfig) -> dict[str, Any]:
    source_root = _source_profile_root(config)
    source_default = _source_default_profile_path(config)
    automation_root = _automation_profile_path(config)

    if _is_google_chrome_running():
        raise BrowserConnectionError("检测到 Google Chrome 仍在运行。请先完全退出 Chrome，再执行 profile 克隆。")
    if not source_root.exists():
        raise ConfigurationError(f"Chrome 源目录不存在: {source_root}")
    if not source_default.exists():
        raise ConfigurationError(f"未找到当前 Chrome 的 Default profile: {source_default}")

    if automation_root.exists():
        shutil.rmtree(automation_root)
    automation_root.mkdir(parents=True, exist_ok=True)

    copy_candidates = ["Default", "Local State", "First Run"]
    copied_items: list[str] = []
    for name in copy_candidates:
        source_path = source_root / name
        destination_path = automation_root / name
        if not source_path.exists():
            continue
        if source_path.is_dir():
            shutil.copytree(
                source_path,
                destination_path,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    "Cache",
                    "Code Cache",
                    "GPUCache",
                    "VideoDecodeStats",
                ),
            )
        else:
            shutil.copy2(source_path, destination_path)
        copied_items.append(name)

    _cleanup_profile_runtime_artifacts(automation_root)

    return {
        "status": "profile_seeded",
        "source_root": str(source_root),
        "source_profile": str(source_default),
        "automation_profile_dir": str(automation_root),
        "copied_items": copied_items,
    }


def _load_youtube_oauth_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise MissingDependencyError(
            "Missing dependencies for YouTube Data API OAuth: "
            "google-auth google-auth-oauthlib google-api-python-client"
        ) from exc
    return Credentials, InstalledAppFlow, Request, build


def _serialize_google_credentials(creds: Any) -> dict[str, Any]:
    payload = json.loads(creds.to_json())
    return {
        key: value
        for key, value in payload.items()
        if value is not None
    }


def _load_youtube_credentials(config: DigestConfig, interactive: bool = False) -> Any:
    Credentials, InstalledAppFlow, Request, _ = _load_youtube_oauth_dependencies()
    token_path = _youtube_token_path(config)
    client_secrets_path = _youtube_client_secrets_path(config)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_READONLY_SCOPES)

    if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(token_path, _serialize_google_credentials(creds))

    if creds and getattr(creds, "valid", False):
        return creds

    if not interactive:
        raise ConfigurationError(
            "Missing or expired YouTube OAuth token. Place your OAuth client JSON at "
            f"{client_secrets_path} and run `scripts/run_knowledge_digest.py --youtube-auth` once."
        )

    if not client_secrets_path.exists():
        raise ConfigurationError(
            "Missing YouTube OAuth client JSON. Download an OAuth desktop client from Google Cloud and save it to "
            f"{client_secrets_path}."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), YOUTUBE_READONLY_SCOPES)
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        authorization_prompt_message="请在浏览器中完成 YouTube Data API 授权，然后返回终端。",
        success_message="YouTube Data API 授权完成，可以返回终端了。",
    )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(token_path, _serialize_google_credentials(creds))
    return creds


def bootstrap_youtube_auth(config: DigestConfig) -> dict[str, Any]:
    _load_youtube_credentials(config, interactive=True)
    return {
        "status": "youtube_oauth_ready",
        "client_secrets_path": str(_youtube_client_secrets_path(config)),
        "token_path": str(_youtube_token_path(config)),
        "scopes": YOUTUBE_READONLY_SCOPES,
    }


def _parse_rfc3339_to_beijing_date(value: str) -> date | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).astimezone(BEIJING_TZ).date()
    except ValueError:
        return None


def fetch_playlist_entries_via_youtube_api(config: DigestConfig) -> list[dict[str, Any]]:
    try:
        creds = _load_youtube_credentials(config, interactive=False)
        _, _, _, build = _load_youtube_oauth_dependencies()
        service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        playlist_id = extract_playlist_id(config.playlist_url)

        entries: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            try:
                response = service.playlistItems().list(
                    part="snippet,contentDetails,status",
                    playlistId=playlist_id,
                    maxResults=50,
                    pageToken=page_token,
                ).execute()
            except Exception as exc:
                error_text = str(exc)
                if entries and "playlistNotFound" in error_text:
                    print(
                        "Warning: YouTube API pagination broke with playlistNotFound after partial success; "
                        "continuing with collected entries and browser merge.",
                    )
                    break
                raise
            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                resource = snippet.get("resourceId", {})
                video_id = resource.get("videoId")
                if not video_id:
                    continue
                published_at = snippet.get("publishedAt", "")
                entries.append(
                    {
                        "id": video_id,
                        "title": snippet.get("title") or f"Video {video_id}",
                        "channel_name": snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle") or "",
                        "duration": "",
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "playlist_item_id": item.get("id"),
                        "playlist_added_text": published_at,
                        "playlist_added_date": _parse_rfc3339_to_beijing_date(published_at),
                        "playlist_added_source": "youtube-api",
                        "raw_text_fragments": [],
                    }
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return entries
    except DigestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DigestError(f"YouTube API request failed: {exc}") from exc


def _merge_playlist_entries(
    api_entries: list[dict[str, Any]],
    browser_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for entry in browser_entries:
        payload = dict(entry)
        payload.setdefault("playlist_added_source", "browser")
        merged[entry["id"]] = payload
    for entry in api_entries:
        existing = merged.get(entry["id"], {})
        payload = {
            **existing,
            **entry,
            "raw_text_fragments": existing.get("raw_text_fragments") or entry.get("raw_text_fragments", []),
            "playlist_added_text": entry.get("playlist_added_text"),
            "playlist_added_date": entry.get("playlist_added_date"),
            "playlist_added_source": "youtube-api",
        }
        merged[entry["id"]] = payload
    return list(merged.values())


def _diagnostics_dir(prefix: str) -> Path:
    stamp = beijing_now().strftime("%Y%m%d-%H%M%S")
    path = BROWSER_DIAGNOSTICS_DIR / f"{prefix}-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _collect_browser_diagnostics(
    page: Any,
    diagnostics_dir: Path,
    console_messages: list[str],
    request_failures: list[str],
) -> dict[str, Any]:
    screenshot_path = diagnostics_dir / "page.png"
    html_path = diagnostics_dir / "page.html"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    payload = {
        "current_url": page.url,
        "page_title": page.title(),
        "console_errors": console_messages[-50:],
        "request_failures": request_failures[-50:],
        "diagnostics_dir": str(diagnostics_dir),
    }
    _write_json(diagnostics_dir / "summary.json", payload)
    return payload


def _request_failure_text(request: Any) -> str:
    failure = getattr(request, "failure", None)
    if callable(failure):
        return str(failure() or "unknown")
    if failure:
        return str(failure)
    return "unknown"


def _verify_youtube_homepage(page: Any, allow_google_signin: bool = False) -> Path | None:
    diagnostics_dir = _diagnostics_dir("youtube-self-check")
    console_messages: list[str] = []
    request_failures: list[str] = []
    page.on("console", lambda msg: console_messages.append(f"{msg.type}: {msg.text}"))
    page.on(
        "requestfailed",
        lambda request: request_failures.append(
            f"{request.method} {request.url} -> {_request_failure_text(request)}"
        ),
    )

    page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=120000)
    page.wait_for_timeout(5000)
    title = page.title()
    url = page.url
    has_youtube_dom = bool(page.locator("ytd-app, ytd-page-manager").count())
    if "youtube.com" in url and "YouTube" in title and has_youtube_dom:
        shutil.rmtree(diagnostics_dir, ignore_errors=True)
        return None
    if allow_google_signin and "accounts.google.com" in url and "service=youtube" in url:
        shutil.rmtree(diagnostics_dir, ignore_errors=True)
        return None

    payload = _collect_browser_diagnostics(page, diagnostics_dir, console_messages, request_failures)
    raise BrowserConnectionError(
        "自动化 Chrome 无法正常打开 YouTube 首页。"
        f" 当前 URL: {payload['current_url']}，标题: {payload['page_title']}，诊断目录: {diagnostics_dir}"
    )


def _write_cookie_jar(cookie_file: Path, cookies: list[dict[str, Any]]) -> Path:
    lines = ["# Netscape HTTP Cookie File", "# This file is generated by youtube-ai-digest."]
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").strip()
        name = str(cookie.get("name") or "").strip()
        if not domain or not name:
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(cookie.get("path") or "/")
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        expires = cookie.get("expires")
        expires_epoch = str(int(expires)) if isinstance(expires, (int, float)) and expires > 0 else "0"
        value = str(cookie.get("value") or "")
        lines.append("\t".join([domain, include_subdomains, path, secure, expires_epoch, name, value]))
    cookie_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cookie_file


def _configure_playlist_routes(page: Any) -> None:
    def route_handler(route: Any) -> None:
        resource_type = route.request.resource_type
        if resource_type in {"media", "image", "font"}:
            route.abort()
            return
        route.continue_()

    page.route("**/*", route_handler)


def _launch_managed_context(playwright: Any, config: DigestConfig, headless: bool) -> Any:
    profile_dir = _automation_profile_path(config)
    if not (profile_dir / "Default").exists():
        raise BrowserConnectionError(
            "自动化 Chrome profile 尚未准备好。请先完全退出 Chrome，然后运行 "
            "`scripts/run_knowledge_digest.py --seed-from-current-profile`。"
        )
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel=config.chrome_channel,
        headless=headless,
        ignore_default_args=PLAYWRIGHT_IGNORE_DEFAULT_ARGS,
        args=[
            "--mute-audio",
            "--disable-session-crashed-bubble",
            "--restore-last-session",
        ],
    )


def _find_or_open_playlist_page(context: Any, playlist_url: str) -> tuple[Any, bool]:
    playlist_id_match = re.search(r"[?&]list=([^&]+)", playlist_url)
    playlist_id = playlist_id_match.group(1) if playlist_id_match else None
    for page in context.pages:
        page_url = page.url or ""
        if page_url == playlist_url:
            return page, False
        if playlist_id and f"list={playlist_id}" in page_url:
            return page, False
    page = context.new_page()
    return page, True


def _fetch_playlist_entries_via_playwright(
    config: DigestConfig,
    attach_current_chrome: bool,
    interactive_login: bool,
) -> PlaylistFetchResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise MissingDependencyError("Missing dependency: playwright") from exc

    PLAYWRIGHT_TMP_DIR.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(PLAYWRIGHT_TMP_DIR)
    os.environ.setdefault("TMPDIR", str(PLAYWRIGHT_TMP_DIR))
    playlist_url = normalize_playlist_url(config.playlist_url)
    cookie_file = PLAYWRIGHT_TMP_DIR / "yt-dlp-cookies.txt"
    with sync_playwright() as playwright:
        browser = None
        context = None
        created_page = False
        page = None
        diagnostics_dir: Path | None = None
        try:
            if attach_current_chrome:
                resolved_cdp_endpoint = resolve_chrome_cdp_endpoint(config.chrome_cdp_url)
                browser = playwright.chromium.connect_over_cdp(resolved_cdp_endpoint)
                if not browser.contexts:
                    raise BrowserConnectionError("已连接 Chrome CDP，但没有可用 browser context。")
                context = browser.contexts[0]
            else:
                context = _launch_managed_context(playwright, config, headless=not interactive_login)

            page, created_page = _find_or_open_playlist_page(context, playlist_url)
            _configure_playlist_routes(page)
            diagnostics_dir = _verify_youtube_homepage(page, allow_google_signin=interactive_login)
            page.goto(playlist_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(2500)
            if interactive_login:
                print("请在自动化 Chrome 窗口中确认 YouTube 已登录且播放列表可见，然后回到终端按回车继续。")
                input()
                page.goto(playlist_url, wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
            stable_rounds = 0
            previous_count = -1
            for _ in range(20):
                page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                page.wait_for_timeout(700)
                current_count = page.locator("ytd-playlist-video-renderer, ytd-playlist-panel-video-renderer").count()
                if current_count == previous_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                previous_count = current_count
                if stable_rounds >= 2:
                    break
            payload = page.evaluate(
                """
                () => Array.from(
                  document.querySelectorAll('ytd-playlist-video-renderer, ytd-playlist-panel-video-renderer')
                ).map((node) => {
                  const titleAnchor = node.querySelector('a#wc-endpoint, #video-title, a#video-title, a[href*="/watch?v="]');
                  const title = titleAnchor?.getAttribute('title') || titleAnchor?.textContent || '';
                  const href = titleAnchor?.getAttribute('href') || '';
                  const channel = node.querySelector('ytd-channel-name a, #metadata a')?.textContent || '';
                  const duration = node.querySelector('span.ytd-thumbnail-overlay-time-status-renderer')?.textContent || '';
                  const fragments = node.innerText.split('\\n').map((line) => line.trim()).filter(Boolean);
                  return { title, href, channel_name: channel.trim(), duration: duration.trim(), raw_text_fragments: fragments };
                });
                """
            )
            _write_cookie_jar(cookie_file, context.cookies())
        finally:
            if attach_current_chrome:
                if created_page and page is not None:
                    page.close()
                if browser is not None:
                    browser.close()
            elif context is not None:
                context.close()
    entries = _normalize_playlist_payload(payload)
    if not entries:
        raise DigestError("无法通过当前 Chrome 会话读取播放列表条目。请确认你已登录 YouTube，并且该播放列表可见。")
    return PlaylistFetchResult(
        entries=entries,
        cookie_file=cookie_file if cookie_file.exists() else None,
        browser_mode="attach-current-chrome" if attach_current_chrome else "managed",
        diagnostics_dir=diagnostics_dir,
    )


def bootstrap_managed_chrome_login(config: DigestConfig) -> dict[str, Any]:
    if not (_automation_profile_path(config) / "Default").exists():
        raise BrowserConnectionError(
            "自动化 profile 还不存在。请先完全退出 Chrome，并执行 "
            "`scripts/run_knowledge_digest.py --seed-from-current-profile`。"
        )
    fetch_result = _fetch_playlist_entries_via_playwright(config, attach_current_chrome=False, interactive_login=True)
    return {
        "status": "login_bootstrapped",
        "browser_mode": fetch_result.browser_mode,
        "playlist_url": config.playlist_url,
        "profile_dir": str(_automation_profile_path(config)),
        "diagnostics_dir": str(fetch_result.diagnostics_dir) if fetch_result.diagnostics_dir else None,
    }


def fetch_playlist_entries(
    config: DigestConfig,
    attach_current_chrome: bool = False,
    interactive_login: bool = False,
) -> PlaylistFetchResult:
    api_entries = fetch_playlist_entries_via_youtube_api(config)
    browser_result = _fetch_playlist_entries_via_playwright(config, attach_current_chrome, interactive_login)
    merged_entries = _merge_playlist_entries(api_entries, browser_result.entries)
    return PlaylistFetchResult(
        entries=merged_entries,
        cookie_file=browser_result.cookie_file,
        browser_mode=browser_result.browser_mode,
        diagnostics_dir=browser_result.diagnostics_dir,
    )


def filter_entries_for_date(entries: list[dict[str, Any]], target_date: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []
    for entry in entries:
        entry_date = entry.get("playlist_added_date")
        if entry_date == target_date:
            matched.append(entry)
        elif entry_date is None:
            needs_review.append(entry)
    return matched, needs_review


def select_entries_for_processing(
    entries: list[dict[str, Any]],
    target_date: date,
    state: dict[str, Any],
    allow_fallback_first_seen: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matched, unresolved = filter_entries_for_date(entries, target_date)
    if not allow_fallback_first_seen:
        return matched, unresolved

    state_videos = state.get("videos", {})
    default_target = parse_target_date(None)

    for entry in unresolved:
        previous = state_videos.get(entry["id"], {})
        first_seen_target_date = previous.get("first_seen_target_date")
        if first_seen_target_date == target_date.isoformat():
            entry["playlist_added_text"] = previous.get("playlist_added_text") or "首次发现于该目标日（fallback）"
            entry["playlist_added_date"] = target_date
            matched.append(entry)
            continue
        if first_seen_target_date is None and target_date == default_target:
            entry["playlist_added_text"] = "首次发现于该目标日（fallback）"
            entry["playlist_added_date"] = target_date
            matched.append(entry)

    matched_ids = {entry["id"] for entry in matched}
    needs_review = [entry for entry in unresolved if entry["id"] not in matched_ids]
    return matched, needs_review


def load_run_manifest(run_dir: Path) -> dict[str, Any]:
    return _read_json(run_dir / "manifest.json", {})


def _index_videos_by_id(videos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for video in videos:
        video_id = video.get("id")
        if video_id:
            indexed[video_id] = video
    return indexed


def _default_incremental_stats(
    *,
    selected_count: int = 0,
    to_process_count: int = 0,
    new_video_count: int = 0,
    retried_non_success_count: int = 0,
    skipped_summary_ready_count: int = 0,
) -> dict[str, int]:
    return {
        "selected_count": selected_count,
        "to_process_count": to_process_count,
        "new_video_count": new_video_count,
        "retried_non_success_count": retried_non_success_count,
        "skipped_summary_ready_count": skipped_summary_ready_count,
    }


def plan_run_entries(
    entries: list[dict[str, Any]],
    existing_manifest: dict[str, Any],
    *,
    full_reprocess: bool = False,
) -> tuple[str, list[dict[str, Any]], dict[str, int]]:
    selected_count = len(entries)
    if full_reprocess or not existing_manifest:
        return (
            "full",
            entries,
            _default_incremental_stats(
                selected_count=selected_count,
                to_process_count=len(entries),
            ),
        )

    processed_index = _index_videos_by_id(existing_manifest.get("processed_videos", []))
    failed_index = _index_videos_by_id(existing_manifest.get("failed_videos", []))
    entries_to_process: list[dict[str, Any]] = []
    new_video_count = 0
    retried_non_success_count = 0
    skipped_summary_ready_count = 0

    for entry in entries:
        existing_processed = processed_index.get(entry["id"])
        if existing_processed and existing_processed.get("processing_status") == "summary_ready":
            skipped_summary_ready_count += 1
            continue
        if existing_processed or entry["id"] in failed_index:
            retried_non_success_count += 1
        else:
            new_video_count += 1
        entries_to_process.append(entry)

    return (
        "incremental",
        entries_to_process,
        _default_incremental_stats(
            selected_count=selected_count,
            to_process_count=len(entries_to_process),
            new_video_count=new_video_count,
            retried_non_success_count=retried_non_success_count,
            skipped_summary_ready_count=skipped_summary_ready_count,
        ),
    )


def merge_run_results(
    existing_manifest: dict[str, Any],
    processed_videos: list[dict[str, Any]],
    failed_videos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged_processed = _index_videos_by_id(existing_manifest.get("processed_videos", []))
    merged_failed = _index_videos_by_id(existing_manifest.get("failed_videos", []))

    for video in processed_videos:
        video_id = video["id"]
        merged_failed.pop(video_id, None)
        merged_processed[video_id] = video

    for video in failed_videos:
        video_id = video["id"]
        merged_processed.pop(video_id, None)
        merged_failed[video_id] = video

    return list(merged_processed.values()), list(merged_failed.values())


def resolve_openai_settings(config: DigestConfig) -> dict[str, str]:
    load_env_file()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or config.openai_base_url.strip()
    model = os.getenv("OPENAI_MODEL", "").strip() or config.openai_model.strip()
    missing = []
    if not api_key:
        missing.append("OPENAI_API_KEY")
    if not base_url:
        missing.append("OPENAI_BASE_URL")
    if not model:
        missing.append("OPENAI_MODEL")
    if missing:
        raise ConfigurationError(f"Missing runtime configuration: {', '.join(missing)}")
    return {"api_key": api_key, "base_url": base_url.rstrip("/"), "model": model}


def _openai_ssl_context() -> ssl.SSLContext:
    insecure = os.getenv("OPENAI_ALLOW_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes", "on"}
    if insecure:
        return ssl._create_unverified_context()
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _openai_headers(settings: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }


def _anthropic_headers(settings: dict[str, str]) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "x-api-key": settings["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }


def _api_endpoint(base_url: str, endpoint: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/{endpoint}"
    return f"{base}/v1/{endpoint}"


def _uses_anthropic_messages(model: str) -> bool:
    return model.lower().startswith("claude-")


def _response_input_from_messages(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    role_map = {"system": "developer", "user": "user", "assistant": "assistant", "developer": "developer"}
    items: list[dict[str, Any]] = []
    for message in messages:
        items.append(
            {
                "type": "message",
                "role": role_map.get(message.get("role", "user"), "user"),
                "content": [{"type": "input_text", "text": message.get("content", "")}],
            }
        )
    return items


def _extract_response_output_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = data.get("output", [])
    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and content.get("text"):
                text_parts.append(str(content["text"]).strip())
            elif content.get("type") == "text" and content.get("text"):
                text_parts.append(str(content["text"]).strip())
    return "\n".join(part for part in text_parts if part).strip()


def _response_contains_refusal(data: dict[str, Any]) -> bool:
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and content.get("type") == "refusal":
                return True
    return False


def _extract_anthropic_output_text(data: dict[str, Any]) -> str:
    text_parts = [
        str(item.get("text", "")).strip()
        for item in data.get("content", []) or []
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text")
    ]
    return "\n".join(part for part in text_parts if part).strip()


def _post_json(
    url: str,
    payload: dict[str, Any],
    settings: dict[str, str],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or _openai_headers(settings),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180, context=_openai_ssl_context()) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise ProviderModelResponseError(
            f"Model request failed with HTTP {exc.code}: {detail}",
            provider_status="http_error",
            stop_reason=str(exc.code),
        ) from exc
    except (
        urllib.error.URLError,
        TimeoutError,
        socket.timeout,
        ssl.SSLError,
        http.client.IncompleteRead,
        ConnectionError,
        UnicodeDecodeError,
    ) as exc:
        raise TransportModelResponseError(f"Model response transport failed: {exc}") from exc
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportModelResponseError("Model response contained incomplete or invalid JSON") from exc
    if not isinstance(data, dict):
        raise TransportModelResponseError("Model response JSON was not an object")
    return data


def _openai_request(
    messages: list[dict[str, str]],
    settings: dict[str, str],
    max_tokens: int = 1200,
) -> ModelResponse:
    if _uses_anthropic_messages(settings["model"]):
        system_parts = [
            message.get("content", "")
            for message in messages
            if message.get("role") in {"system", "developer"}
        ]
        anthropic_messages = [
            {
                "role": message.get("role", "user"),
                "content": message.get("content", ""),
            }
            for message in messages
            if message.get("role") in {"user", "assistant"}
        ]
        payload = {
            "model": settings["model"],
            "system": "\n\n".join(part for part in system_parts if part),
            "messages": anthropic_messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = _post_json(
            _api_endpoint(settings["base_url"], "messages"),
            payload,
            settings,
            headers=_anthropic_headers(settings),
        )
        text = _extract_anthropic_output_text(data)
        response_id = str(data["id"]) if data.get("id") else None
        stop_reason = str(data["stop_reason"]) if data.get("stop_reason") else None
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        provider_status = "missing" if stop_reason is None else "completed"
        metadata = {
            "response_id": response_id,
            "provider": "anthropic",
            "provider_status": provider_status,
            "stop_reason": stop_reason,
            "output_chars": len(text),
            "usage": usage,
        }
        if stop_reason == "max_tokens":
            raise IncompleteModelResponseError(
                "Anthropic response stopped because max_tokens was reached",
                **{**metadata, "provider_status": "incomplete"},
            )
        if stop_reason == "refusal":
            raise PolicyModelResponseError(
                "Anthropic response was refused",
                **{**metadata, "provider_status": "refused"},
            )
        if stop_reason not in {None, "end_turn"}:
            raise IncompleteModelResponseError(
                f"Anthropic response ended with unexpected stop_reason={stop_reason}",
                **{**metadata, "provider_status": "incomplete"},
            )
        if not text:
            raise IncompleteModelResponseError("Anthropic Messages API returned an empty response", **metadata)
        return ModelResponse(
            text=text,
            provider="anthropic",
            response_id=response_id,
            provider_status=provider_status,
            stop_reason=stop_reason,
            usage=usage,
        )

    responses_payload = {
        "model": settings["model"],
        "input": _response_input_from_messages(messages),
        "temperature": 0.2,
        "max_output_tokens": max_tokens,
    }
    data = _post_json(_api_endpoint(settings["base_url"], "responses"), responses_payload, settings)
    text = _extract_response_output_text(data)
    response_id = str(data["id"]) if data.get("id") else None
    status = str(data["status"]) if data.get("status") else None
    incomplete_details = data.get("incomplete_details")
    incomplete_reason = (
        str(incomplete_details.get("reason"))
        if isinstance(incomplete_details, dict) and incomplete_details.get("reason")
        else None
    )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    metadata = {
        "response_id": response_id,
        "provider": "openai",
        "provider_status": status or "missing",
        "stop_reason": incomplete_reason,
        "output_chars": len(text),
        "usage": usage,
    }
    if _response_contains_refusal(data):
        raise PolicyModelResponseError("OpenAI response contained a refusal", **metadata)
    if status == "incomplete":
        error_type = (
            PolicyModelResponseError
            if incomplete_reason in {"content_filter", "safety", "refusal"}
            else IncompleteModelResponseError
        )
        raise error_type(
            f"OpenAI response was incomplete: {incomplete_reason or 'reason missing'}",
            **metadata,
        )
    if status in {"failed", "cancelled"}:
        raise ProviderModelResponseError(f"OpenAI response ended with status={status}", **metadata)
    if status not in {None, "completed"}:
        raise IncompleteModelResponseError(f"OpenAI response ended with unexpected status={status}", **metadata)
    if not text:
        raise IncompleteModelResponseError("OpenAI Responses API returned an empty response", **metadata)
    return ModelResponse(
        text=text,
        provider="openai",
        response_id=response_id,
        provider_status=status or "missing",
        stop_reason=incomplete_reason,
        usage=usage,
    )


def _chunk_text(text: str, max_chars: int = SUMMARY_CHUNK_MAX_CHARS) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


def _to_simplified_chinese(text: str) -> str:
    return _SIMPLIFIED_CHINESE_CONVERTER.convert(text)


def _extract_display_title(summary_text: str, fallback_title: str) -> tuple[str, str]:
    cleaned = summary_text.strip()
    lines = cleaned.splitlines()
    if not lines:
        return fallback_title, cleaned

    first_line = lines[0].strip()
    for prefix in ("中文标题：", "中文标题:"):
        if first_line.startswith(prefix):
            display_title = first_line.removeprefix(prefix).strip()
            if display_title:
                return display_title, "\n".join(lines[1:]).strip()

    return fallback_title, cleaned


def _model_response_error_kwargs(
    response: ModelResponse,
    *,
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    metadata = {
        "response_id": response.response_id,
        "provider": response.provider,
        "provider_status": response.provider_status,
        "stop_reason": response.stop_reason,
        "output_chars": len(response.text),
        "usage": response.usage,
    }
    if validation_errors is not None:
        metadata["validation_errors"] = validation_errors
    return metadata


def _strip_required_completion_marker(response: ModelResponse, marker: str) -> str:
    text = response.text.rstrip()
    lines = text.splitlines()
    if not lines or lines[-1].strip() != marker or text.count(marker) != 1:
        raise IncompleteModelResponseError(
            f"Model response is missing the required final marker {marker}",
            validation_errors=["missing_or_misplaced_completion_marker"],
            **_model_response_error_kwargs(response),
        )
    article = "\n".join(lines[:-1]).rstrip()
    if not article:
        raise IncompleteModelResponseError(
            "Model response contained only the completion marker",
            validation_errors=["empty_content_before_completion_marker"],
            **_model_response_error_kwargs(response),
        )
    return article


def _summary_structure_errors(summary_text: str) -> list[str]:
    lines = summary_text.splitlines()
    errors: list[str] = []
    first_line = lines[0].strip() if lines else ""
    title_match = re.fullmatch(r"中文标题[:：]\s*(.+)", first_line)
    if not title_match or not title_match.group(1).strip():
        errors.append("missing_or_empty_chinese_title")

    core_heading_count = sum(line.strip() == "## 核心结论" for line in lines)
    if core_heading_count != 1:
        errors.append("core_conclusion_heading_must_appear_once")

    headings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^##(?:\s+(.*))?$", line.strip())
        if match:
            heading_text = (match.group(1) or "").strip()
            headings.append((index, heading_text))
            if not heading_text:
                errors.append("empty_level_two_heading")

    for position, (line_index, heading_text) in enumerate(headings):
        next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        section_lines = [line.strip() for line in lines[line_index + 1 : next_index] if line.strip()]
        if heading_text and not any(not line.startswith("#") for line in section_lines):
            errors.append(f"level_two_heading_without_body:{heading_text}")

    if summary_text.count("**") % 2:
        errors.append("unclosed_bold_marker")
    if len(re.findall(r"(?m)^\s*```", summary_text)) % 2:
        errors.append("unclosed_code_fence")
    return list(dict.fromkeys(errors))


def _validate_summary_article(summary_text: str, response: ModelResponse | None = None) -> None:
    errors = _summary_structure_errors(summary_text)
    if not errors:
        return
    kwargs = _model_response_error_kwargs(response) if response else {"output_chars": len(summary_text)}
    raise InvalidSummaryArticleError(
        "Generated summary failed structural validation: " + ", ".join(errors),
        validation_errors=errors,
        **kwargs,
    )


def summarize_transcript(
    transcript_text: str,
    video_title: str,
    settings: dict[str, str],
    playlist_name: str,
) -> GeneratedSummary:
    article_prompt = _load_prompt(SUMMARY_ARTICLE_PROMPT_PATH)
    chunks = _chunk_text(transcript_text)
    if len(chunks) == 1:
        response = _openai_request(
            [
                {
                    "role": "system",
                    "content": article_prompt,
                },
                {
                    "role": "user",
                    "content": (
                        f"播放列表：{playlist_name}\n视频标题：{video_title}\n\n"
                        "请根据下面的 transcript 输出文章：\n\n"
                        f"{transcript_text}"
                    ),
                },
            ],
            settings,
            max_tokens=SUMMARY_ARTICLE_MAX_TOKENS,
        )
        summary = _to_simplified_chinese(_strip_required_completion_marker(response, SUMMARY_COMPLETE_MARKER))
        _validate_summary_article(summary, response)
        return GeneratedSummary(summary, response)

    chunk_summaries = []
    evidence_prompt = _load_prompt(SUMMARY_EVIDENCE_PROMPT_PATH)
    for index, chunk in enumerate(chunks, start=1):
        response = _openai_request(
            [
                {
                    "role": "system",
                    "content": evidence_prompt,
                },
                {
                    "role": "user",
                    "content": f"视频标题：{video_title}\n第 {index}/{len(chunks)} 段 transcript：\n\n{chunk}",
                },
            ],
            settings,
            max_tokens=1600,
        )
        chunk_summary = _strip_required_completion_marker(response, EVIDENCE_COMPLETE_MARKER)
        chunk_summaries.append(_to_simplified_chinese(chunk_summary))
    response = _openai_request(
        [
            {
                "role": "system",
                "content": article_prompt,
            },
            {
                "role": "user",
                "content": (
                    f"播放列表：{playlist_name}\n视频标题：{video_title}\n\n"
                    "下面是从同一 transcript 逐段提取并合并的证据表；它是最终文章的唯一事实来源。"
                    "请基于这些证据生成文章，不要补充证据表之外的内容：\n\n"
                    + "\n\n".join(chunk_summaries)
                ),
            },
        ],
        settings,
        max_tokens=SUMMARY_ARTICLE_MAX_TOKENS,
    )
    final_summary = _to_simplified_chinese(
        _strip_required_completion_marker(response, SUMMARY_COMPLETE_MARKER)
    )
    _validate_summary_article(final_summary, response)
    return GeneratedSummary(final_summary, response)


def _parse_retry_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def _summary_retry_delay(attempt_count: int) -> int:
    if attempt_count <= 0:
        return SUMMARY_RETRY_BACKOFF_SECONDS[0]
    return SUMMARY_RETRY_BACKOFF_SECONDS[min(attempt_count - 1, len(SUMMARY_RETRY_BACKOFF_SECONDS) - 1)]


def _retry_delay_for_summary_error(exc: Exception, failure_index: int) -> int:
    if isinstance(exc, (IncompleteModelResponseError, InvalidSummaryArticleError)):
        return SUMMARY_INCOMPLETE_RETRY_BACKOFF_SECONDS[
            min(failure_index, len(SUMMARY_INCOMPLETE_RETRY_BACKOFF_SECONDS) - 1)
        ]
    return SUMMARY_RETRY_BACKOFF_SECONDS[min(failure_index, len(SUMMARY_RETRY_BACKOFF_SECONDS) - 1)]


def _is_non_retryable_summary_error(exc: Exception) -> bool:
    if isinstance(exc, (ConfigurationError, PolicyModelResponseError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in NON_RETRYABLE_SUMMARY_ERROR_MARKERS)


def is_transient_network_error(exc: Exception | str) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, http.client.IncompleteRead, ConnectionError)):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in TRANSIENT_NETWORK_ERROR_MARKERS)


def _append_summary_retry_history(retry_state: dict[str, Any]) -> dict[str, Any]:
    if not retry_state:
        return retry_state
    history = list(retry_state.get("history") or [])
    history.append({key: value for key, value in retry_state.items() if key != "history"})
    retry_state["history"] = history[-10:]
    return retry_state


def _summary_failure_metadata(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ModelResponseError):
        payload: dict[str, Any] = {
            "failure_kind": exc.failure_kind,
            "response_id": exc.response_id,
            "provider": exc.provider,
            "provider_status": exc.provider_status,
            "stop_reason": exc.stop_reason,
            "output_chars": exc.output_chars,
            "validation_errors": exc.validation_errors,
        }
        if exc.usage:
            payload["response_usage"] = exc.usage
        return payload
    if isinstance(exc, ConfigurationError):
        return {"failure_kind": "configuration_error"}
    if is_transient_network_error(exc):
        return {"failure_kind": "transport_error"}
    return {"failure_kind": "generation_error"}


def _summary_response_metadata(response: ModelResponse | None, summary_text: str) -> dict[str, Any]:
    if response is None:
        return {"output_chars": len(summary_text)}
    payload: dict[str, Any] = {
        "response_id": response.response_id,
        "provider": response.provider,
        "provider_status": response.provider_status,
        "stop_reason": response.stop_reason,
        "output_chars": len(summary_text),
    }
    if response.usage:
        payload["response_usage"] = response.usage
    return payload


def _summary_format_warnings(summary_text: str, transcript_text: str) -> list[str]:
    warnings: list[str] = []
    output_chars = len(summary_text)
    if output_chars > len(transcript_text):
        warnings.append("longer_than_transcript")
    if len(transcript_text) >= 600 and not 600 <= output_chars <= 1500:
        warnings.append("outside_preferred_600_1500_chars")
    heading_count = len(re.findall(r"(?m)^##\s+\S", summary_text))
    if not 2 <= heading_count <= 4:
        warnings.append("outside_preferred_2_4_level_two_headings")
    bold_count = summary_text.count("**") // 2
    if len(transcript_text) >= 600 and not 10 <= bold_count <= 18:
        warnings.append("outside_preferred_10_18_bold_phrases")
    return warnings


def summarize_transcript_with_retries(
    transcript_text: str,
    video_title: str,
    settings: dict[str, str],
    playlist_name: str,
    *,
    existing_retry: dict[str, Any] | None = None,
    max_attempts: int = SUMMARY_MAX_ATTEMPTS,
    run_attempt_limit: int = SUMMARY_INLINE_ATTEMPTS,
    force_retry: bool = False,
    force_retry_attempts: int = 1,
    clock: Callable[[], datetime] = beijing_now,
    sleep_fn: Callable[[int], None] = time.sleep,
    summarize_fn: Callable[
        [str, str, dict[str, str], str],
        str | GeneratedSummary,
    ] = summarize_transcript,
) -> tuple[str | None, dict[str, Any]]:
    retry_state = dict(existing_retry or {})
    attempt_count = int(retry_state.get("attempt_count") or 0)
    first_failed_at = _parse_retry_datetime(retry_state.get("first_failed_at"))
    now = clock()

    if force_retry:
        retry_state = _append_summary_retry_history(retry_state)
        retry_state.pop("next_retry_after", None)
        retry_state.pop("stopped_reason", None)
        retry_state.pop("next_step", None)
    elif attempt_count >= max_attempts:
        retry_state.update(
            {
                "attempt_count": attempt_count,
                "stopped_reason": "max_attempts",
                "next_step": "manual_review",
            }
        )
        return None, retry_state
    if not force_retry and first_failed_at and now - first_failed_at > SUMMARY_RETRY_WINDOW:
        retry_state.update(
            {
                "attempt_count": attempt_count,
                "stopped_reason": "retry_window_exceeded",
                "next_step": "manual_review",
            }
        )
        return None, retry_state

    if force_retry:
        attempts_this_run = min(max(force_retry_attempts, 1), run_attempt_limit)
    else:
        attempts_this_run = min(max_attempts - attempt_count, run_attempt_limit)
    next_delay: int | None = None
    for run_attempt_index in range(attempts_this_run):
        if next_delay is not None:
            sleep_fn(next_delay)
        try:
            generated = summarize_fn(transcript_text, video_title, settings, playlist_name)
            if isinstance(generated, GeneratedSummary):
                summary_text = generated.text
                response = generated.response
            else:
                summary_text = generated
                response = None
            attempt_count += 1
            success_retry = {
                "attempt_count": attempt_count,
                "last_success_at": clock().isoformat(),
                "last_error": None,
                "failure_kind": None,
                "validation_errors": [],
                "format_warnings": _summary_format_warnings(summary_text, transcript_text),
                **_summary_response_metadata(response, summary_text),
            }
            if retry_state.get("history"):
                success_retry["history"] = retry_state["history"]
            if retry_state.get("attempt_history"):
                success_retry["attempt_history"] = retry_state["attempt_history"]
            return summary_text, success_retry
        except Exception as exc:  # noqa: BLE001
            attempt_count += 1
            now = clock()
            if first_failed_at is None:
                first_failed_at = now
            failure_metadata = _summary_failure_metadata(exc)
            attempt_history = list(retry_state.get("attempt_history") or [])
            attempt_history.append(
                {
                    "attempt": attempt_count,
                    "attempted_at": now.isoformat(),
                    "outcome": "failure",
                    **failure_metadata,
                }
            )
            retry_state.update(
                {
                    "attempt_count": attempt_count,
                    "first_failed_at": first_failed_at.isoformat(),
                    "last_failure_at": now.isoformat(),
                    "last_error": str(exc),
                    "stopped_reason": None,
                    "next_step": "retry_pending_summaries",
                    "attempt_history": attempt_history[-10:],
                    **failure_metadata,
                }
            )

            if _is_non_retryable_summary_error(exc):
                retry_state["stopped_reason"] = "non_retryable_error"
                retry_state["next_step"] = "manual_review"
                retry_state.pop("next_retry_after", None)
                break
            if not force_retry and attempt_count >= max_attempts:
                retry_state["stopped_reason"] = "max_attempts"
                retry_state["next_step"] = "manual_review"
                retry_state.pop("next_retry_after", None)
                break
            if not force_retry and first_failed_at and now - first_failed_at > SUMMARY_RETRY_WINDOW:
                retry_state["stopped_reason"] = "retry_window_exceeded"
                retry_state["next_step"] = "manual_review"
                retry_state.pop("next_retry_after", None)
                break
            if run_attempt_index < attempts_this_run - 1:
                next_delay = _retry_delay_for_summary_error(exc, run_attempt_index)
                retry_state["next_retry_after"] = (
                    now + timedelta(seconds=next_delay)
                ).isoformat()
                retry_state["next_step"] = "retry_after_backoff"
            else:
                if force_retry:
                    retry_state["stopped_reason"] = "max_attempts"
                    retry_state["next_step"] = "manual_review"
                retry_state.pop("next_retry_after", None)

    return None, retry_state


def build_video_summary_markdown(
    video: dict[str, Any],
    summary_text: str,
    transcript_relative_path: str,
    display_title: str | None = None,
) -> str:
    added_text = video.get("playlist_added_text") or "未解析到"
    transcript_source = video.get("transcript_source", "unknown")
    title = display_title or video["title"]
    return (
        f"# {title}\n\n"
        "## 视频信息\n"
        f"- 频道: {video.get('channel_name') or 'Unknown'}\n"
        f"- 链接: {video.get('url')}\n"
        f"- 发布时间: {video.get('upload_date') or 'Unknown'}\n"
        f"- 时长: {video.get('duration_string') or video.get('duration') or 'Unknown'}\n"
        f"- 加入播放列表时间: {added_text}\n"
        f"- Transcript 来源: {transcript_source}\n\n"
        "## 中文总结\n"
        f"{summary_text.strip()}\n\n"
        "## 原始 Transcript\n"
        f"- 完整文本: `{transcript_relative_path}`\n"
    )


def _duration_seconds(started_at: float) -> float:
    return round(time.monotonic() - started_at, 3)


def write_video_outputs(
    run_dir: Path,
    video: dict[str, Any],
    transcript: TranscriptResult,
    summary_text: str | None,
    summary_status: str,
    summary_error: str | None = None,
    prebuilt_summary_markdown: bool = False,
) -> dict[str, Any]:
    video_dir = run_dir / "videos" / video["id"]
    video_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = video_dir / "transcript.original.txt"
    transcript_path.write_text(transcript.text, encoding="utf-8")

    summary_path = video_dir / "summary.zh-CN.md"
    legacy_report = video_dir / "report.md"
    cleaned_summary_text = summary_text.strip() if summary_text else ""
    display_title = str(video.get("display_title") or video["title"])
    if summary_text:
        if not prebuilt_summary_markdown:
            display_title, cleaned_summary_text = _extract_display_title(summary_text, video["title"])
        summary_markdown = (
            summary_text.strip() + "\n"
            if prebuilt_summary_markdown
            else build_video_summary_markdown(
                video,
                cleaned_summary_text,
                "transcript.original.txt",
                display_title=display_title,
            )
        )
        _atomic_write_text(legacy_report, summary_markdown)
        _atomic_write_text(summary_path, summary_markdown)
    else:
        summary_path.unlink(missing_ok=True)
        legacy_report.unlink(missing_ok=True)

    metadata_path = video_dir / "metadata.json"
    metadata_payload = {
        "id": video["id"],
        "title": video["title"],
        "display_title": display_title,
        "url": video["url"],
        "channel_name": video.get("channel_name"),
        "upload_date": video.get("upload_date"),
        "duration": video.get("duration_string") or video.get("duration"),
        "playlist_added_text": video.get("playlist_added_text"),
        "playlist_added_date": video.get("playlist_added_date").isoformat()
        if isinstance(video.get("playlist_added_date"), date)
        else None,
        "transcript_source": transcript.source,
        "transcript_language": transcript.language,
        "summary_path": str(summary_path.relative_to(run_dir)) if summary_text else None,
        "transcript_path": str(transcript_path.relative_to(run_dir)),
        "processed_at": beijing_now().isoformat(),
        "processing_status": summary_status,
        "summary_error": summary_error,
        "summary_source": video.get("summary_source"),
        "summary_retry": video.get("summary_retry", {}),
        "processing_metrics": video.get("processing_metrics", {}),
        "transcription_details": transcript.details,
        "transcript_diagnostics": video.get("transcript_diagnostics", {}),
    }
    _write_json(metadata_path, metadata_payload)

    return {
        **video,
        "display_title": display_title,
        "summary_text": cleaned_summary_text,
        "summary_path": str(summary_path.relative_to(run_dir)) if summary_text else None,
        "transcript_path": str(transcript_path.relative_to(run_dir)),
        "metadata_path": str(metadata_path.relative_to(run_dir)),
        "transcript_source": transcript.source,
        "transcript_language": transcript.language,
        "processing_status": summary_status,
        "summary_error": summary_error,
        "summary_source": video.get("summary_source"),
        "summary_retry": video.get("summary_retry", {}),
        "processing_metrics": video.get("processing_metrics", {}),
        "transcription_details": transcript.details,
        "transcript_diagnostics": video.get("transcript_diagnostics", {}),
    }


def cleanup_media(paths: list[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


def update_state(state: dict[str, Any], target_date: date, processed_videos: list[dict[str, Any]]) -> dict[str, Any]:
    state["last_run_at"] = beijing_now().isoformat()
    state["last_target_date"] = target_date.isoformat()
    video_state = state.setdefault("videos", {})
    for video in processed_videos:
        previous = video_state.get(video["id"], {})
        video_state[video["id"]] = {
            "title": video["title"],
            "last_status": video.get("processing_status") or "success",
            "last_processed_at": beijing_now().isoformat(),
            "last_target_date": target_date.isoformat(),
            "transcript_source": video.get("transcript_source"),
            "summary_path": video.get("summary_path"),
            "playlist_added_text": video.get("playlist_added_text"),
            "first_seen_at": previous.get("first_seen_at") or beijing_now().isoformat(),
            "first_seen_target_date": previous.get("first_seen_target_date") or target_date.isoformat(),
        }
    return state


def _summary_ready_videos(processed_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in processed_videos if item.get("processing_status") == "summary_ready"]


def _pending_summary_videos(processed_videos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in processed_videos if item.get("processing_status") == "pending_summary"]


def _manifest_has_pending_summaries(manifest: dict[str, Any]) -> bool:
    return int(manifest.get("pending_summary_count") or 0) > 0 or bool(
        _pending_summary_videos(manifest.get("processed_videos", []))
    )


def is_manifest_complete(manifest: dict[str, Any]) -> bool:
    return int(manifest.get("failed_count") or 0) == 0 and int(manifest.get("pending_summary_count") or 0) == 0


def manifest_completion_status(manifest: dict[str, Any]) -> str:
    return "success" if is_manifest_complete(manifest) else "partial"


def _build_manifest(
    target_date: date,
    config: DigestConfig,
    browser_mode: str,
    processed_videos: list[dict[str, Any]],
    failed_videos: list[dict[str, Any]],
    needs_review: list[dict[str, Any]],
    *,
    run_mode: str = "full",
    incremental_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pending_summary_videos = _pending_summary_videos(processed_videos)
    normalized_incremental_stats = _default_incremental_stats()
    if incremental_stats:
        for key in normalized_incremental_stats:
            value = incremental_stats.get(key, normalized_incremental_stats[key])
            normalized_incremental_stats[key] = int(value)
    manifest = {
        "target_date": target_date.isoformat(),
        "playlist_name": config.playlist_name,
        "playlist_url": config.playlist_url,
        "generated_at": beijing_now().isoformat(),
        "browser_mode": browser_mode,
        "run_mode": run_mode,
        "incremental_stats": normalized_incremental_stats,
        "processed_count": len(processed_videos),
        "summary_ready_count": len(_summary_ready_videos(processed_videos)),
        "pending_summary_count": len(pending_summary_videos),
        "failed_count": len(failed_videos),
        "transcript_failed_count": len(failed_videos),
        "needs_review_count": len(needs_review),
        "date_unverified_count": len(needs_review),
        "processed_videos": processed_videos,
        "pending_summary_videos": pending_summary_videos,
        "failed_videos": failed_videos,
        "needs_review_videos": needs_review,
    }
    manifest["completion_status"] = manifest_completion_status(manifest)
    manifest["needs_retry"] = manifest["completion_status"] != "success"
    return manifest


def retry_pending_summaries(
    config: DigestConfig,
    target_date: date,
    video_id: str | None = None,
    *,
    force_summary_retry: bool = False,
    regenerate_all: bool = False,
) -> dict[str, Any]:
    run_dir = config.output_root_path / target_date.isoformat()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise DigestError(f"No existing run manifest found for {target_date.isoformat()}: {manifest_path}")

    settings = resolve_openai_settings(config)
    manifest = _read_json(manifest_path, {})
    processed_videos = manifest.get("processed_videos", [])
    failed_videos = manifest.get("failed_videos", [])
    needs_review = manifest.get("needs_review_videos", [])

    selected_ids = {video_id} if video_id else None
    updated_processed: list[dict[str, Any]] = []
    retried_count = 0
    regenerated_success_count = 0
    regeneration_failed_count = 0
    for video in processed_videos:
        should_retry = regenerate_all or video.get("processing_status") != "summary_ready"
        if selected_ids is not None:
            should_retry = should_retry and video.get("id") in selected_ids
        if not should_retry:
            updated_processed.append(video)
            continue

        transcript_path = run_dir / str(video.get("transcript_path") or "")
        if not transcript_path.exists():
            if regenerate_all:
                regeneration_failed_count += 1
                updated_processed.append(
                    {
                        **video,
                        "summary_regeneration_error": f"Missing transcript file: {transcript_path}",
                    }
                )
                continue
            updated_processed.append(
                {
                    **video,
                    "processing_status": "pending_summary",
                    "summary_error": f"Missing transcript file: {transcript_path}",
                }
            )
            continue

        transcript = TranscriptResult(
            text=transcript_path.read_text(encoding="utf-8"),
            language=video.get("transcript_language", "unknown"),
            source=video.get("transcript_source", "unknown"),
            segments=[],
            details=video.get("transcription_details", {}),
        )
        merged = dict(video)
        processing_metrics = dict(merged.get("processing_metrics", {}))
        processing_metrics.setdefault("summary_seconds", 0.0)
        merged["processing_metrics"] = processing_metrics

        previous_attempt_count = int((merged.get("summary_retry") or {}).get("attempt_count") or 0)
        summary_started = time.monotonic()
        summary_text, summary_retry = summarize_transcript_with_retries(
            transcript.text,
            merged["title"],
            settings,
            config.playlist_name,
            existing_retry=merged.get("summary_retry") or {},
            max_attempts=SUMMARY_MAX_ATTEMPTS,
            run_attempt_limit=SUMMARY_INLINE_ATTEMPTS if regenerate_all else 1,
            force_retry=force_summary_retry or regenerate_all,
            force_retry_attempts=SUMMARY_INLINE_ATTEMPTS if regenerate_all else 1,
        )
        merged["processing_metrics"]["summary_seconds"] = _duration_seconds(summary_started)
        merged["summary_retry"] = summary_retry
        if int(summary_retry.get("attempt_count") or 0) > previous_attempt_count:
            retried_count += 1
        if summary_text is not None:
            merged.pop("summary_regeneration_error", None)
            if regenerate_all:
                regenerated_success_count += 1
            updated_processed.append(
                write_video_outputs(
                    run_dir,
                    merged,
                    transcript,
                    summary_text,
                    summary_status="summary_ready",
                    summary_error=None,
                )
            )
        elif regenerate_all:
            regeneration_failed_count += 1
            updated_processed.append(
                {
                    **video,
                    "summary_retry": summary_retry,
                    "summary_regeneration_error": summary_retry.get("last_error")
                    or summary_retry.get("stopped_reason"),
                }
            )
        else:
            updated_processed.append(
                write_video_outputs(
                    run_dir,
                    merged,
                    transcript,
                    None,
                    summary_status="pending_summary",
                    summary_error=summary_retry.get("last_error") or summary_retry.get("stopped_reason"),
                )
            )

    manifest = _build_manifest(
        target_date,
        config,
        manifest.get("browser_mode", "managed"),
        updated_processed,
        failed_videos,
        needs_review,
        run_mode=manifest.get("run_mode", "full"),
        incremental_stats=manifest.get("incremental_stats"),
    )
    _write_json(manifest_path, manifest)
    save_state(update_state(load_state(), target_date, updated_processed))
    manifest["retried_summary_count"] = retried_count
    if regenerate_all:
        manifest["regenerated_summary_count"] = regenerated_success_count
        manifest["regeneration_failed_count"] = regeneration_failed_count
    _write_json(manifest_path, manifest)
    return manifest


def adopt_summary_for_video(
    config: DigestConfig,
    target_date: date,
    video_id: str,
    summary_file: Path,
) -> dict[str, Any]:
    run_dir = config.output_root_path / target_date.isoformat()
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise DigestError(f"No existing run manifest found for {target_date.isoformat()}: {manifest_path}")
    if not summary_file.exists():
        raise DigestError(f"Manual summary file does not exist: {summary_file}")

    manual_summary = summary_file.read_text(encoding="utf-8").strip()
    if not manual_summary:
        raise DigestError(f"Manual summary file is empty: {summary_file}")

    manifest = _read_json(manifest_path, {})
    processed_videos = manifest.get("processed_videos", [])
    failed_videos = manifest.get("failed_videos", [])
    needs_review = manifest.get("needs_review_videos", [])

    updated_processed: list[dict[str, Any]] = []
    adopted = False
    for video in processed_videos:
        if video.get("id") != video_id:
            updated_processed.append(video)
            continue

        transcript_path = run_dir / str(video.get("transcript_path") or "")
        if not transcript_path.exists():
            raise DigestError(f"Missing transcript file for {video_id}: {transcript_path}")

        retry_state = dict(video.get("summary_retry") or {})
        if retry_state:
            retry_state = _append_summary_retry_history(retry_state)
        retry_state.update(
            {
                "manual_adopted_at": beijing_now().isoformat(),
                "last_error": None,
                "stopped_reason": None,
                "next_step": None,
            }
        )
        retry_state.pop("next_retry_after", None)

        transcript = TranscriptResult(
            text=transcript_path.read_text(encoding="utf-8"),
            language=video.get("transcript_language", "unknown"),
            source=video.get("transcript_source", "unknown"),
            segments=[],
            details=video.get("transcription_details", {}),
        )
        merged = {
            **video,
            "summary_source": "manual",
            "summary_retry": retry_state,
        }
        updated_processed.append(
            write_video_outputs(
                run_dir,
                merged,
                transcript,
                manual_summary,
                summary_status="summary_ready",
                summary_error=None,
                prebuilt_summary_markdown=True,
            )
        )
        adopted = True

    if not adopted:
        raise DigestError(f"Video {video_id} was not found in manifest for {target_date.isoformat()}")

    manifest = _build_manifest(
        target_date,
        config,
        manifest.get("browser_mode", "managed"),
        updated_processed,
        failed_videos,
        needs_review,
        run_mode=manifest.get("run_mode", "full"),
        incremental_stats=manifest.get("incremental_stats"),
    )
    manifest["adopted_summary_count"] = 1
    _write_json(manifest_path, manifest)

    save_state(update_state(load_state(), target_date, updated_processed))
    _write_json(manifest_path, manifest)
    return manifest


def run_knowledge_digest(
    target_date: date,
    playlist_url: str | None = None,
    youtube_auth: bool = False,
    seed_from_current_profile: bool = False,
    bootstrap_login: bool = False,
    attach_current_chrome: bool = False,
    retry_summaries: bool = False,
    regenerate_summaries: bool = False,
    allow_fallback_first_seen: bool = False,
    full_reprocess: bool = False,
    video_id: str | None = None,
    force_summary_retry: bool = False,
    adopt_summary_file: Path | None = None,
) -> dict[str, Any]:
    config = load_config(playlist_url=playlist_url)
    ensure_output_dirs(config)
    if youtube_auth:
        return bootstrap_youtube_auth(config)
    if seed_from_current_profile:
        return seed_automation_profile_from_current(config)
    if bootstrap_login:
        return bootstrap_managed_chrome_login(config)
    if adopt_summary_file is not None:
        if not video_id:
            raise DigestError("--adopt-summary-file requires --video-id.")
        return adopt_summary_for_video(config, target_date, video_id, adopt_summary_file)
    if retry_summaries:
        return retry_pending_summaries(
            config,
            target_date,
            video_id=video_id,
            force_summary_retry=force_summary_retry,
        )
    if regenerate_summaries:
        return retry_pending_summaries(
            config,
            target_date,
            video_id=video_id,
            force_summary_retry=True,
            regenerate_all=True,
        )

    run_dir = config.output_root_path / target_date.isoformat()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "videos").mkdir(parents=True, exist_ok=True)
    settings = resolve_openai_settings(config)
    state = load_state()
    existing_manifest = load_run_manifest(run_dir)

    browser_mode = "managed"
    yt_dlp_cookies_path: Path | None = None
    delete_yt_dlp_cookies = False
    run_mode = "full"
    incremental_stats = _default_incremental_stats()

    try:
        if video_id:
            existing_cookie_file = PLAYWRIGHT_TMP_DIR / "yt-dlp-cookies.txt"
            if existing_cookie_file.exists() and existing_cookie_file.stat().st_size > 0:
                browser_mode = "existing-cookies"
                yt_dlp_cookies_path = existing_cookie_file
            else:
                fetch_result = fetch_playlist_entries(config, attach_current_chrome=attach_current_chrome, interactive_login=False)
                browser_mode = fetch_result.browser_mode
                yt_dlp_cookies_path = fetch_result.cookie_file
                delete_yt_dlp_cookies = yt_dlp_cookies_path is not None
            entries = [{"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "title": video_id}]
            needs_review: list[dict[str, Any]] = []
            incremental_stats = _default_incremental_stats(selected_count=1, to_process_count=1)
        else:
            try:
                fetch_result = fetch_playlist_entries(config, attach_current_chrome=attach_current_chrome, interactive_login=False)
            except DigestError as exc:
                if (
                    not full_reprocess
                    and is_transient_network_error(exc)
                    and _manifest_has_pending_summaries(existing_manifest)
                ):
                    return retry_pending_summaries(
                        config,
                        target_date,
                        force_summary_retry=force_summary_retry,
                    )
                raise
            browser_mode = fetch_result.browser_mode
            yt_dlp_cookies_path = fetch_result.cookie_file
            delete_yt_dlp_cookies = yt_dlp_cookies_path is not None
            selected_entries, needs_review = select_entries_for_processing(
                fetch_result.entries,
                target_date,
                state,
                allow_fallback_first_seen=allow_fallback_first_seen,
            )
            run_mode, entries, incremental_stats = plan_run_entries(
                selected_entries,
                existing_manifest,
                full_reprocess=full_reprocess,
            )

        processed_videos: list[dict[str, Any]] = []
        failed_videos: list[dict[str, Any]] = []

        for entry in entries:
            temp_paths: list[Path] = []
            try:
                info_started = time.monotonic()
                info = fetch_video_info(entry["id"], browser=config.browser, cookies_path=yt_dlp_cookies_path)
                info_fetch_seconds = _duration_seconds(info_started)
                merged = {
                    **entry,
                    "title": info.get("title") or entry.get("title") or entry["id"],
                    "channel_name": info.get("channel") or entry.get("channel_name", ""),
                    "upload_date": info.get("upload_date"),
                    "duration_string": info.get("duration_string"),
                    "duration": info.get("duration"),
                    "url": f"https://www.youtube.com/watch?v={entry['id']}",
                }

                video_dir = run_dir / "videos" / entry["id"]
                video_dir.mkdir(parents=True, exist_ok=True)
                download_thumbnail(entry["id"], video_dir, browser=config.browser, cookies_path=yt_dlp_cookies_path)

                subtitle_started = time.monotonic()
                transcript, transcript_diagnostics = download_transcript(
                    entry["id"],
                    video_dir,
                    browser=config.browser,
                    cookies_path=yt_dlp_cookies_path,
                )
                subtitle_fetch_seconds = _duration_seconds(subtitle_started)
                audio_download_seconds = 0.0
                transcription_seconds = 0.0
                if transcript is None:
                    audio_started = time.monotonic()
                    source_audio = download_audio(
                        entry["id"],
                        video_dir,
                        browser=config.browser,
                        cookies_path=yt_dlp_cookies_path,
                    )
                    audio_download_seconds = _duration_seconds(audio_started)
                    temp_paths.append(source_audio)

                    transcription_started = time.monotonic()
                    transcript = transcribe_audio(source_audio, config.mlx_whisper_model)
                    transcription_seconds = _duration_seconds(transcription_started)
                    if transcript.details.get("used_wav_fallback"):
                        temp_paths.append(source_audio.with_suffix(".wav"))
                    transcript_diagnostics["fallback_reason"] = transcript_diagnostics.get("fallback_reason") or "subtitle_unavailable"
                transcript.details = {
                    **transcript.details,
                    "subtitle_attempts": transcript_diagnostics.get("attempts", []),
                }
                merged["transcript_source"] = transcript.source
                merged["transcript_diagnostics"] = transcript_diagnostics
                merged["processing_metrics"] = {
                    "info_fetch_seconds": info_fetch_seconds,
                    "subtitle_fetch_seconds": subtitle_fetch_seconds,
                    "audio_download_seconds": audio_download_seconds,
                    "transcription_seconds": transcription_seconds,
                    "summary_seconds": 0.0,
                }

                summary_started = time.monotonic()
                summary_text, summary_retry = summarize_transcript_with_retries(
                    transcript.text,
                    merged["title"],
                    settings,
                    config.playlist_name,
                    existing_retry=merged.get("summary_retry") or {},
                    max_attempts=SUMMARY_MAX_ATTEMPTS,
                    run_attempt_limit=SUMMARY_INLINE_ATTEMPTS,
                )
                merged["processing_metrics"]["summary_seconds"] = _duration_seconds(summary_started)
                merged["summary_retry"] = summary_retry
                if summary_text is not None:
                    processed_videos.append(
                        write_video_outputs(
                            run_dir,
                            merged,
                            transcript,
                            summary_text,
                            summary_status="summary_ready",
                            summary_error=None,
                        )
                    )
                else:
                    processed_videos.append(
                        write_video_outputs(
                            run_dir,
                            merged,
                            transcript,
                            None,
                            summary_status="pending_summary",
                            summary_error=summary_retry.get("last_error") or summary_retry.get("stopped_reason"),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                failed_videos.append(
                    {
                        "id": entry["id"],
                        "title": entry.get("title", entry["id"]),
                        "url": entry.get("url"),
                        "failure_stage": "transcript_failed",
                        "error": str(exc),
                    }
                )
            finally:
                cleanup_media(temp_paths)

        merged_processed_videos, merged_failed_videos = merge_run_results(
            existing_manifest,
            processed_videos,
            failed_videos,
        )
        manifest = _build_manifest(
            target_date,
            config,
            browser_mode,
            merged_processed_videos,
            merged_failed_videos,
            needs_review,
            run_mode=run_mode,
            incremental_stats=incremental_stats,
        )
        _write_json(run_dir / "manifest.json", manifest)

        save_state(update_state(state, target_date, processed_videos))
        if not video_id and int(manifest.get("pending_summary_count") or 0) > 0:
            manifest = retry_pending_summaries(config, target_date)
        return manifest
    finally:
        if delete_yt_dlp_cookies and yt_dlp_cookies_path is not None:
            yt_dlp_cookies_path.unlink(missing_ok=True)
