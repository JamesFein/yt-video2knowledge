"""Generate, validate, and retry a Video Summary."""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from opencc import OpenCC

from yt_video2knowledge.digest.config import (
    BEIJING_TZ,
    DEFAULT_SUMMARY_ARTICLE_MAX_OUTPUT_TOKENS,
    DEFAULT_SUMMARY_TRANSCRIPT_TOKEN_LIMIT,
    DigestConfig,
    beijing_now,
    load_env_file,
)
from yt_video2knowledge.digest.errors import (
    ConfigurationError,
    IncompleteModelResponseError,
    InvalidSummaryArticleError,
    ModelResponseError,
    PolicyModelResponseError,
    ProviderModelResponseError,
    TranscriptTokenLimitError,
    TransportModelResponseError,
)
from yt_video2knowledge.paths import PROMPT_DIR

SUMMARY_INLINE_ATTEMPTS = 3
SUMMARY_MAX_ATTEMPTS = 3
SUMMARY_RETRY_WINDOW = timedelta(hours=24)
SUMMARY_RETRY_BACKOFF_SECONDS = (30, 120, 300)
SUMMARY_INCOMPLETE_RETRY_BACKOFF_SECONDS = (2, 5)
SUMMARY_COMPLETE_MARKER = "<!-- SUMMARY_COMPLETE -->"
SUMMARY_ARTICLE_PROMPT_PATH = Path("production/summary-article-v5.md")
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


def _load_prompt(relative_path: Path) -> str:
    path = PROMPT_DIR / relative_path
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ConfigurationError(f"Unable to read prompt file: {path}") from exc
    if not prompt:
        raise ConfigurationError(f"Prompt file is empty: {path}")
    return prompt


def resolve_openai_settings(config: DigestConfig) -> dict[str, Any]:
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
    return {
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "model": model,
        "summary_transcript_token_limit": config.summary_transcript_token_limit,
        "summary_article_max_output_tokens": config.summary_article_max_output_tokens,
    }


def _openai_ssl_context() -> ssl.SSLContext:
    insecure = os.getenv("OPENAI_ALLOW_INSECURE_SSL", "").strip().lower() in {"1", "true", "yes", "on"}
    if insecure:
        return ssl._create_unverified_context()
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _openai_headers(settings: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }


def _anthropic_headers(settings: dict[str, Any]) -> dict[str, str]:
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
    settings: dict[str, Any],
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
    settings: dict[str, Any],
    *,
    max_output_tokens: int,
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
            "max_tokens": max_output_tokens,
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
        "max_output_tokens": max_output_tokens,
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


def _estimate_transcript_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + 2) // 3


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
    settings: dict[str, Any],
    playlist_name: str,
) -> GeneratedSummary:
    transcript_token_limit = int(
        settings.get("summary_transcript_token_limit", DEFAULT_SUMMARY_TRANSCRIPT_TOKEN_LIMIT)
    )
    estimated_transcript_tokens = _estimate_transcript_tokens(transcript_text)
    if estimated_transcript_tokens >= transcript_token_limit:
        raise TranscriptTokenLimitError(estimated_transcript_tokens, transcript_token_limit)

    article_prompt = _load_prompt(SUMMARY_ARTICLE_PROMPT_PATH)
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
        max_output_tokens=int(
            settings.get(
                "summary_article_max_output_tokens",
                DEFAULT_SUMMARY_ARTICLE_MAX_OUTPUT_TOKENS,
            )
        ),
    )
    summary = _to_simplified_chinese(_strip_required_completion_marker(response, SUMMARY_COMPLETE_MARKER))
    _validate_summary_article(summary, response)
    return GeneratedSummary(summary, response)


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
    if isinstance(exc, (ConfigurationError, PolicyModelResponseError, TranscriptTokenLimitError)):
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
    if isinstance(exc, TranscriptTokenLimitError):
        return {
            "failure_kind": exc.failure_kind,
            "estimated_transcript_tokens": exc.estimated_transcript_tokens,
            "transcript_token_limit": exc.transcript_token_limit,
        }
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
    settings: dict[str, Any],
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
        [str, str, dict[str, Any], str],
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
