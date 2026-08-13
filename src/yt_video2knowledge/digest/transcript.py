"""Acquire a Transcript from subtitles, downloaded audio, or local ASR."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yt_video2knowledge.digest.config import format_timestamp
from yt_video2knowledge.digest.errors import (
    DigestError,
    ExternalCommandError,
    MissingDependencyError,
)

YT_DLP_MEDIA_FORBIDDEN_MARKERS = (
    "http error 403",
    "unable to download video data",
    "sign in to confirm you’re not a bot",
    "sign in to confirm you're not a bot",
)
YT_DLP_AUDIO_FALLBACK_FORMATS = (
    "worst[language_preference>=10][protocol=m3u8_native]",
    "worst[language_preference=5][protocol=m3u8_native]",
    "worst[protocol=m3u8_native]",
)
DEFAULT_YT_DLP_AUDIO_TIMEOUT_SECONDS = 1800


@dataclass
class TranscriptResult:
    text: str
    language: str
    source: str
    segments: list[dict[str, Any]]
    details: dict[str, Any] = field(default_factory=dict)


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


def _yt_dlp_audio_timeout_seconds() -> int:
    raw_value = os.environ.get("YT_DLP_AUDIO_TIMEOUT_SECONDS")
    if raw_value is None:
        return DEFAULT_YT_DLP_AUDIO_TIMEOUT_SECONDS
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise DigestError("YT_DLP_AUDIO_TIMEOUT_SECONDS must be an integer") from exc
    if timeout <= 0:
        raise DigestError("YT_DLP_AUDIO_TIMEOUT_SECONDS must be greater than zero")
    return timeout


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
        _run_command(cmd, timeout=_yt_dlp_audio_timeout_seconds())
    except ExternalCommandError as exc:
        if "http error 403" not in str(exc).lower():
            raise
        _cleanup_partial_audio_downloads(output_dir)
        _run_command(cmd, timeout=_yt_dlp_audio_timeout_seconds())
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
    with redirect_stdout(sys.stderr):
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
