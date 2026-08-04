"""Resolve Knowledge Playlist entries and select them for a Target Date."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from yt_video2knowledge.digest.config import (
    BEIJING_TZ,
    DEFAULT_CHROME_SOURCE_PROFILE_DIR,
    DigestConfig,
    _write_json,
    beijing_now,
    extract_playlist_id,
    normalize_playlist_url,
    parse_target_date,
)
from yt_video2knowledge.digest.errors import (
    BrowserConnectionError,
    ConfigurationError,
    DigestError,
    MissingDependencyError,
)
from yt_video2knowledge.paths import (
    BROWSER_DIAGNOSTICS_DIR,
    PLAYWRIGHT_TMP_DIR,
    PROJECT_ROOT,
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
YOUTUBE_READONLY_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]
PLAYWRIGHT_IGNORE_DEFAULT_ARGS = [
    "--enable-automation",
    "--disable-extensions",
    "--disable-component-extensions-with-background-pages",
    "--disable-sync",
    "--password-store=basic",
    "--use-mock-keychain",
]
DEVTOOLS_ACTIVE_PORT_CANDIDATES = [
    Path.home() / "Library/Application Support/Google/Chrome/DevToolsActivePort",
    Path.home() / "Library/Application Support/Google/Chrome/Default/DevToolsActivePort",
]


@dataclass
class PlaylistFetchResult:
    entries: list[dict[str, Any]]
    cookie_file: Path | None
    browser_mode: str
    diagnostics_dir: Path | None = None


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
    return path if path.is_absolute() else PROJECT_ROOT / path


def _youtube_client_secrets_path(config: DigestConfig) -> Path:
    path = Path(config.youtube_client_secrets_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _youtube_token_path(config: DigestConfig) -> Path:
    path = Path(config.youtube_token_path).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _source_profile_root(config: DigestConfig) -> Path:
    path = Path(config.chrome_source_profile_dir).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


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
            f"{client_secrets_path} and run `uv run yt-video2knowledge digest --youtube-auth` once."
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
            "`uv run yt-video2knowledge digest --seed-from-current-profile`。"
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
            "`uv run yt-video2knowledge digest --seed-from-current-profile`。"
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
