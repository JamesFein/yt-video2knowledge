#!/usr/bin/env python3
"""Run the repository-local summary prompt experiment.

This script is intentionally scoped to this experiment. It does not import or
modify the production digest workflow and never writes beneath data/runs.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import re
import shutil
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[2]
TRACKED_DIR = Path(__file__).resolve().parent
PROMPT_DIR = TRACKED_DIR / "prompts"
EXPERIMENT_DIR = ROOT / "data" / "experiments" / "summary-prompt-v1"
SAMPLE_DIR = EXPERIMENT_DIR / "samples"
ROBUSTNESS_DIR = EXPERIMENT_DIR / "robustness"
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
EVALUATION_DIR = EXPERIMENT_DIR / "evaluations"
RUNS_DIR = ROOT / "data" / "runs"
MODEL_CONFIG_PATH = ROOT / "新的文字简写模型.txt"
OPENAI_ENV_PATH = ROOT / ".env.local"
DATABASE_PATH = ROOT / "data" / "knowledge.sqlite3"

SEED = 20260802
SAMPLE_SIZE = 60
CORE_PER_CATEGORY = 6
MAX_DIRECT_CHARS = 120_000
MIN_ARTICLE_CHARS = 600
MAX_ARTICLE_CHARS = 1_500
MODEL_TEMPERATURE = 0.2
MODEL_MAX_TOKENS = 4096
GPT_V5_MODEL = "gpt-5.6-sol"
_SIMPLIFIED_CHINESE_CONVERTER = OpenCC("t2s")

CATEGORIES = ("argument", "tutorial", "briefing", "narrative")
CATEGORY_LABELS = {
    "argument": "观点/解释",
    "tutorial": "教程/演示",
    "briefing": "资讯/市场",
    "narrative": "叙事/访谈",
}
SCORE_KEYS = (
    "core_insight",
    "best_evidence",
    "memorable_material",
    "standalone_article",
    "conciseness",
)

V4_TARGETS = {
    "S027-TUWDpYDTQEk": "代价与教训：关系、职业与心理健康",
    "S036-MvjjO5wgUsE": "代价与教训：线上服务与工程失败",
    "S010-PnwOldwLuVM": "代价与教训：产品与商业失败",
    "S052-c-MnSFGTSN8": "代价与教训＋人物背景",
    "S019-C0gErQtnNFE": "人物背景",
    "S045-08SVa45XimY": "人物背景",
    "S046-WL3AGmQBJLQ": "人物背景来源边界（原计划负例）",
    "S022-rQKis2Cfpeo": "人物背景",
    "S005-fDQaadKysSA": "关键概念格式",
    "S013-501pDaIMCQw": "关键概念格式",
    "S002-7I3G21RyARs": "普通观点回归",
    "S003-TD4S8dj8D70": "多资讯回归",
}

CONFIG_RE = re.compile(
    r"模型[：:]\s*(?P<model>\S+)\s+密钥[：:]\s*(?P<key>\S+)\s+Base\s+URL\s*(?P<base>https?://\S+)",
    re.IGNORECASE,
)
TIMESTAMP_PREFIX_RE = re.compile(r"^\s*\[\d{1,3}:\d{2}(?::\d{2})?]\s*")
TIMESTAMP_NEAR_RE = re.compile(r"[（(\[]\d{1,3}:\d{2}(?::\d{2})?[）)\]]")
H1_RE = re.compile(r"^#\s+\S", re.MULTILINE)
H2_RE = re.compile(r"^##\s+\S", re.MULTILINE)
QUOTE_RE = re.compile(r"“([^”\n]{1,100})”|「([^」\n]{1,100})」|『([^』\n]{1,100})』|\"([^\"\n]{1,100})\"")


class ExperimentError(RuntimeError):
    pass


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_prompt(relative_path: str | Path) -> str:
    path = PROMPT_DIR / relative_path
    try:
        prompt = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ExperimentError(f"Unable to read prompt file: {path}") from exc
    if not prompt.strip():
        raise ExperimentError(f"Prompt file is empty: {path}")
    return prompt


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_snapshot(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if _sha256_file(source) != _sha256_file(target):
            raise ExperimentError(f"Immutable snapshot differs: {target}")
        return
    shutil.copy2(source, target)


def _load_model_config() -> dict[str, str]:
    if not MODEL_CONFIG_PATH.exists():
        raise ExperimentError(f"Missing model config: {MODEL_CONFIG_PATH}")
    match = CONFIG_RE.search(_read_text(MODEL_CONFIG_PATH).strip())
    if not match:
        raise ExperimentError("Model config must contain 模型、密钥 and Base URL")
    return {
        "model": match.group("model"),
        "api_key": match.group("key"),
        "base_url": match.group("base").rstrip("/"),
    }


def _load_gpt_v5_config() -> dict[str, str]:
    values: dict[str, str] = {}
    if OPENAI_ENV_PATH.exists():
        for raw_line in _read_text(OPENAI_ENV_PATH).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

    settings = {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip() or values.get("OPENAI_API_KEY", ""),
        "base_url": os.getenv("OPENAI_BASE_URL", "").strip() or values.get("OPENAI_BASE_URL", ""),
        "model": os.getenv("OPENAI_MODEL", "").strip() or values.get("OPENAI_MODEL", ""),
    }
    missing = [key for key, value in settings.items() if not value]
    if missing:
        raise ExperimentError(f"Missing GPT v5 configuration: {', '.join(missing)}")
    if settings["model"] != GPT_V5_MODEL:
        raise ExperimentError(
            f"generate-gpt-v5 requires model {GPT_V5_MODEL}, found {settings['model']}"
        )
    settings["base_url"] = settings["base_url"].rstrip("/")
    return settings


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ExperimentError("Model response did not contain a JSON object")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExperimentError(f"Model response contained invalid JSON: {exc}") from exc


def _call_model(system: str, user: str) -> dict[str, Any]:
    settings = _load_model_config()
    payload = {
        "model": settings["model"],
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "max_tokens": MODEL_MAX_TOKENS,
        "temperature": MODEL_TEMPERATURE,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{settings['base_url']}/v1/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": settings["api_key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        import certifi

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=300, context=ssl_context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1000]
        raise ExperimentError(f"Model request failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ExperimentError(f"Model request failed: {exc}") from exc

    parts = [
        str(block.get("text", "")).strip()
        for block in data.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
    ]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise ExperimentError("Model returned no text content")
    return {
        "text": text,
        "model": data.get("model") or settings["model"],
        "usage": data.get("usage", {}),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _extract_responses_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content["text"]).strip())
    return "\n".join(part for part in parts if part).strip()


def _call_gpt_v5(system: str, user: str) -> dict[str, Any]:
    settings = _load_gpt_v5_config()
    payload = {
        "model": settings["model"],
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": system}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": user}],
            },
        ],
        "temperature": MODEL_TEMPERATURE,
        "max_output_tokens": MODEL_MAX_TOKENS,
    }
    request = urllib.request.Request(
        f"{settings['base_url']}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        import certifi

        ssl_context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=300, context=ssl_context) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:1000]
        raise ExperimentError(f"GPT v5 request failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ExperimentError(f"GPT v5 request failed: {exc}") from exc

    text = _extract_responses_text(data)
    if not text:
        raise ExperimentError("GPT v5 returned no text content")
    return {
        "text": text,
        "requested_model": settings["model"],
        "response_model": data.get("model") or settings["model"],
        "usage": data.get("usage", {}),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _transcript_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = TIMESTAMP_PREFIX_RE.sub("", raw).strip()
        if line:
            lines.append(line)
    return lines


def _initial_quality(text: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if len(text) < 600:
        return "edge_short", ["transcript shorter than 600 characters"]
    if len(text) > MAX_DIRECT_CHARS:
        return "edge_long", [f"transcript longer than {MAX_DIRECT_CHARS} characters"]

    lines = _transcript_lines(text)
    if "�" in text:
        reasons.append("contains replacement characters")
    if len(lines) >= 20:
        repeated_ratio = 1 - len(set(lines)) / len(lines)
        if repeated_ratio >= 0.45:
            reasons.append(f"high repeated-line ratio {repeated_ratio:.2f}")
    if reasons:
        return "suspect_asr", reasons
    return "clean", []


def _length_bucket(length: int) -> str:
    if length < 6_000:
        return "short"
    if length < 18_000:
        return "medium"
    if length < 60_000:
        return "long"
    return "very_long"


def _meta_summary_signals() -> dict[str, dict[str, Any]]:
    if not DATABASE_PATH.exists():
        return {}
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT v.video_id, v.title, m.content, m.updated_at
            FROM video_meta_summaries AS m
            JOIN videos AS v ON v.video_id = m.video_id
            WHERE length(trim(m.content)) > 0
            ORDER BY v.video_id
            """
        ).fetchall()
    return {
        row[0]: {
            "video_id": row[0],
            "title": row[1],
            "content": row[2],
            "content_chars": len(row[2]),
            "updated_at": row[3],
        }
        for row in rows
    }


def _scan_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for metadata_path in sorted(RUNS_DIR.glob("*/videos/*/metadata.json")):
        video_dir = metadata_path.parent
        transcript_path = video_dir / "transcript.original.txt"
        summary_path = video_dir / "summary.zh-CN.md"
        if not transcript_path.exists() or not summary_path.exists():
            continue
        metadata = _read_json(metadata_path)
        transcript = _read_text(transcript_path)
        old_summary = _read_text(summary_path)
        quality, quality_reasons = _initial_quality(transcript)
        date_value = metadata_path.parents[2].name
        source = str(metadata.get("transcript_source") or "unknown")
        candidates.append(
            {
                "video_id": str(metadata.get("id") or video_dir.name),
                "date": date_value,
                "month": date_value[:7],
                "title": str(metadata.get("title") or ""),
                "channel_name": str(metadata.get("channel_name") or ""),
                "transcript_source": source,
                "transcript_chars": len(transcript),
                "old_summary_chars": len(old_summary),
                "length_bucket": _length_bucket(len(transcript)),
                "input_quality": quality,
                "quality_reasons": quality_reasons,
                "transcript_sha256": _sha256_text(transcript),
                "old_summary_sha256": _sha256_text(old_summary),
                "source_metadata": _relative(metadata_path),
                "source_transcript": _relative(transcript_path),
                "source_old_summary": _relative(summary_path),
            }
        )
    return candidates


def _stratified_sample(candidates: list[dict[str, Any]], excluded_ids: set[str]) -> list[dict[str, Any]]:
    eligible = [
        item
        for item in candidates
        if item["input_quality"] == "clean" and item["video_id"] not in excluded_ids
    ]
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        key = (item["month"], item["transcript_source"], item["length_bucket"])
        strata[key].append(item)

    for key, items in strata.items():
        random.Random(f"{SEED}:{key}").shuffle(items)

    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    channel_counts: Counter[str] = Counter()
    keys = sorted(strata)
    while len(selected) < SAMPLE_SIZE and any(strata.values()):
        for key in keys:
            if len(selected) >= SAMPLE_SIZE:
                break
            if not strata[key]:
                continue
            item = strata[key].pop()
            channel = item["channel_name"] or "unknown"
            if channel_counts[channel] >= 3:
                deferred.append(item)
                continue
            selected.append(item)
            channel_counts[channel] += 1

    for item in deferred:
        if len(selected) >= SAMPLE_SIZE:
            break
        selected.append(item)

    if len(selected) != SAMPLE_SIZE:
        raise ExperimentError(f"Expected {SAMPLE_SIZE} eligible samples, found {len(selected)}")
    return selected


def _snapshot_record(item: dict[str, Any], sample_id: str, target_root: Path) -> dict[str, Any]:
    target = target_root / sample_id
    metadata_source = ROOT / item["source_metadata"]
    transcript_source = ROOT / item["source_transcript"]
    summary_source = ROOT / item["source_old_summary"]
    _copy_snapshot(metadata_source, target / "metadata.json")
    _copy_snapshot(transcript_source, target / "transcript.original.txt")
    _copy_snapshot(summary_source, target / "summary.old.md")
    record = dict(item)
    record.update(
        {
            "sample_id": sample_id,
            "snapshot_metadata": _relative(target / "metadata.json"),
            "snapshot_transcript": _relative(target / "transcript.original.txt"),
            "snapshot_old_summary": _relative(target / "summary.old.md"),
        }
    )
    return record


def stage_sample() -> None:
    candidates = _scan_candidates()
    meta_signals = _meta_summary_signals()
    selected = _stratified_sample(candidates, set(meta_signals))
    rows = [
        _snapshot_record(item, f"S{index:03d}-{item['video_id']}", SAMPLE_DIR)
        for index, item in enumerate(selected, start=1)
    ]

    manifest_path = EXPERIMENT_DIR / "sample-manifest.jsonl"
    if manifest_path.exists():
        existing = _read_jsonl(manifest_path)
        old_fingerprints = [(row["sample_id"], row["transcript_sha256"]) for row in existing]
        new_fingerprints = [(row["sample_id"], row["transcript_sha256"]) for row in rows]
        if old_fingerprints != new_fingerprints:
            raise ExperimentError("Existing sample manifest differs from deterministic selection")
    else:
        _write_jsonl(manifest_path, rows)

    _write_jsonl(EXPERIMENT_DIR / "meta-summary-signals.jsonl", list(meta_signals.values()))

    robustness = [item for item in candidates if item["input_quality"] != "clean"]
    robustness.sort(key=lambda item: (item["input_quality"], item["transcript_chars"], item["video_id"]))
    robustness_rows = [
        _snapshot_record(item, f"R{index:03d}-{item['video_id']}", ROBUSTNESS_DIR)
        for index, item in enumerate(robustness[:8], start=1)
    ]
    _write_jsonl(EXPERIMENT_DIR / "robustness-manifest.jsonl", robustness_rows)

    source_counts = Counter(row["transcript_source"] for row in rows)
    length_counts = Counter(row["length_bucket"] for row in rows)
    month_counts = Counter(row["month"] for row in rows)
    _write_json(
        EXPERIMENT_DIR / "sample-summary.json",
        {
            "seed": SEED,
            "paired_candidates": len(candidates),
            "sample_count": len(rows),
            "meta_summary_signal_count": len(meta_signals),
            "robustness_count": len(robustness_rows),
            "transcript_sources": dict(sorted(source_counts.items())),
            "length_buckets": dict(sorted(length_counts.items())),
            "months": dict(sorted(month_counts.items())),
        },
    )
    print(f"Sampled {len(rows)} transcripts; preserved {len(meta_signals)} Meta Summary signals.")


def _require_sample_manifest() -> list[dict[str, Any]]:
    rows = _read_jsonl(EXPERIMENT_DIR / "sample-manifest.jsonl")
    if not rows:
        raise ExperimentError("Run the sample stage first")
    return rows


def _classification_user(record: dict[str, Any]) -> str:
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    return f"视频标题：{record['title']}\n\n完整 transcript：\n\n{transcript}"


def _write_classification_report(rows: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["category"]].append(row)
    lines = ["# Classification Report", "", f"共分类 {len(rows)} 篇。", ""]
    for category in CATEGORIES:
        items = grouped.get(category, [])
        lines.extend([f"## {CATEGORY_LABELS[category]} ({len(items)})", ""])
        if not items:
            lines.extend(["暂无样本。", ""])
            continue
        for item in items[:8]:
            lines.append(f"- **{item['title']}**：{item['reason']}")
        merge_counts = Counter(item.get("merge_candidate", "") for item in items)
        lines.extend(["", f"常见合并判断：{dict(merge_counts.most_common(3))}", ""])
    (TRACKED_DIR / "classification-report.md").write_text("\n".join(lines), encoding="utf-8")


def _select_core_samples(manifest: list[dict[str, Any]], classifications: list[dict[str, Any]]) -> None:
    by_id = {row["sample_id"]: row for row in manifest}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for classification in classifications:
        source = by_id[classification["sample_id"]]
        if classification["input_quality"] != "clean":
            continue
        grouped[classification["category"]].append({**source, **classification})

    core: list[dict[str, Any]] = []
    for category in CATEGORIES:
        items = grouped.get(category, [])
        random.Random(f"{SEED}:core:{category}").shuffle(items)
        if len(items) < CORE_PER_CATEGORY:
            raise ExperimentError(
                f"Category {category} has {len(items)} clean samples; needs {CORE_PER_CATEGORY}. "
                "Review classification and add a deterministic top-up before generation."
            )
        core.extend(items[:CORE_PER_CATEGORY])
    core.sort(key=lambda row: (CATEGORIES.index(row["category"]), row["sample_id"]))
    _write_jsonl(EXPERIMENT_DIR / "core-samples.jsonl", core)

    stability = []
    for category in CATEGORIES:
        stability.extend([row for row in core if row["category"] == category][:2])
    _write_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl", stability)


def stage_classify() -> None:
    manifest = _require_sample_manifest()
    path = EXPERIMENT_DIR / "classifications.jsonl"
    existing = {row["sample_id"]: row for row in _read_jsonl(path)}
    system = _read_prompt("classifier.md")
    settings = _load_model_config()

    for record in manifest:
        sample_id = record["sample_id"]
        if sample_id in existing:
            continue
        response = _call_model(system, _classification_user(record))
        raw_path = EXPERIMENT_DIR / "classification-responses" / f"{sample_id}.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(response["text"] + "\n", encoding="utf-8")
        parsed = _extract_json(response["text"])
        category = parsed.get("category")
        if category not in CATEGORIES:
            raise ExperimentError(f"Invalid category for {sample_id}: {category}")
        input_quality = parsed.get("input_quality")
        if input_quality not in {"clean", "suspect_asr"}:
            raise ExperimentError(f"Invalid input_quality for {sample_id}: {input_quality}")
        row = {
            "sample_id": sample_id,
            "video_id": record["video_id"],
            "title": record["title"],
            "category": category,
            "confidence": parsed.get("confidence"),
            "input_quality": input_quality,
            "reason": str(parsed.get("reason") or ""),
            "compression_need": str(parsed.get("compression_need") or ""),
            "merge_candidate": str(parsed.get("merge_candidate") or ""),
            "model": response["model"],
            "usage": response["usage"],
            "elapsed_seconds": response["elapsed_seconds"],
            "response_path": _relative(raw_path),
        }
        _append_jsonl(path, row)
        existing[sample_id] = row
        print(f"Classified {sample_id}: {category}")

    classifications = [existing[row["sample_id"]] for row in manifest]
    _write_classification_report(classifications)
    _select_core_samples(manifest, classifications)
    print(f"Classified {len(classifications)} samples with {settings['model']}.")


def _generation_system(variant: str, category: str) -> str:
    if variant == "current":
        return _read_prompt("current-production.md").strip()
    base = _read_prompt("general-v1.md").strip()
    if variant == "general":
        return base
    if variant == "general_v2":
        return _read_prompt("general-v2.md").strip()
    if variant == "general_v3":
        return _read_prompt("general-v3.md").strip()
    if variant == "general_v4":
        return _read_prompt("general-v4.md").strip()
    if variant == "gpt_general_v5":
        return _read_prompt("general-v5.md").strip()
    if variant == "category":
        delta = _read_prompt(Path("categories") / f"{category}-v1.md").strip()
        return f"{base}\n\n针对这类 transcript：{delta}"
    raise ExperimentError(f"Unknown generation variant: {variant}")


def _generation_user(record: dict[str, Any]) -> str:
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    return f"视频标题：{record['title']}\n\ntranscript：\n\n{transcript}"


def _generate_one(record: dict[str, Any], variant: str, run_number: int) -> None:
    sample_id = record["sample_id"]
    target = OUTPUT_DIR / variant / sample_id / f"run-{run_number}.md"
    metadata_path = target.with_suffix(".json")
    if target.exists() and metadata_path.exists():
        return
    system = _generation_system(variant, record["category"])
    response = _call_model(system, _generation_user(record))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(response["text"].strip() + "\n", encoding="utf-8")
    _write_json(
        metadata_path,
        {
            "sample_id": sample_id,
            "variant": variant,
            "category": record["category"],
            "run_number": run_number,
            "prompt_sha256": _sha256_text(system),
            "model": response["model"],
            "temperature": MODEL_TEMPERATURE,
            "max_tokens": MODEL_MAX_TOKENS,
            "usage": response["usage"],
            "elapsed_seconds": response["elapsed_seconds"],
            "generated_at": datetime.now().astimezone().isoformat(),
        },
    )
    print(f"Generated {variant} run {run_number} for {sample_id}")


def stage_generate() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run and review the classify stage first")
    jobs = []
    for record in core:
        for variant in ("current", "general", "category"):
            jobs.append((record, variant, 1))
        if record["sample_id"] in stability_ids:
            jobs.append((record, "category", 2))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_generate_one, *job) for job in jobs]
        for future in as_completed(futures):
            future.result()


def stage_generate_v2() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run the v1 classify stage first")
    jobs = [(record, "general_v2", 1) for record in core]
    jobs.extend((record, "general_v2", 2) for record in core if record["sample_id"] in stability_ids)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_generate_one, *job) for job in jobs]
        for future in as_completed(futures):
            future.result()


def stage_generate_v3() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run the v1 classify stage first")
    jobs = [(record, "general_v3", 1) for record in core]
    jobs.extend((record, "general_v3", 2) for record in core if record["sample_id"] in stability_ids)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_generate_one, *job) for job in jobs]
        for future in as_completed(futures):
            future.result()


def stage_generate_v4() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    record_index = {row["sample_id"]: row for row in core}
    missing = [sample_id for sample_id in V4_TARGETS if sample_id not in record_index]
    if missing:
        raise ExperimentError(f"Missing v4 target samples: {missing}")
    jobs = [(record_index[sample_id], "general_v4", 1) for sample_id in V4_TARGETS]
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_generate_one, *job) for job in jobs]
        for future in as_completed(futures):
            future.result()


def _generate_gpt_v5_one(record: dict[str, Any]) -> None:
    sample_id = record["sample_id"]
    target = OUTPUT_DIR / "gpt_general_v5" / sample_id / "run-1.md"
    metadata_path = target.with_suffix(".json")
    if target.exists() and metadata_path.exists():
        return

    system = _generation_system("gpt_general_v5", record["category"])
    response = _call_gpt_v5(system, _generation_user(record))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(response["text"].strip() + "\n", encoding="utf-8")
    _write_json(
        metadata_path,
        {
            "sample_id": sample_id,
            "variant": "gpt_general_v5",
            "category": record["category"],
            "run_number": 1,
            "prompt_sha256": _sha256_text(system),
            "requested_model": response["requested_model"],
            "response_model": response["response_model"],
            "temperature": MODEL_TEMPERATURE,
            "max_output_tokens": MODEL_MAX_TOKENS,
            "usage": response["usage"],
            "elapsed_seconds": response["elapsed_seconds"],
            "generated_at": datetime.now().astimezone().isoformat(),
            "raw_output": True,
            "opencc_applied": False,
        },
    )
    print(f"Generated GPT v5 run 1 for {sample_id}")


def stage_generate_gpt_v5() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    record_index = {row["sample_id"]: row for row in core}
    missing = [sample_id for sample_id in V4_TARGETS if sample_id not in record_index]
    if missing:
        raise ExperimentError(f"Missing GPT v5 target samples: {missing}")
    _load_gpt_v5_config()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_generate_gpt_v5_one, record_index[sample_id])
            for sample_id in V4_TARGETS
        ]
        for future in as_completed(futures):
            future.result()


def _normalized_quote(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u3400-\u9fff]", "", text).lower()


def _automatic_checks(
    record: dict[str, Any],
    variant: str,
    run_number: int = 1,
    require_quote_timestamp: bool = True,
) -> dict[str, Any]:
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    output_path = OUTPUT_DIR / variant / record["sample_id"] / f"run-{run_number}.md"
    article = _read_text(output_path).strip()
    h1_count = len(H1_RE.findall(article))
    h2_count = len(H2_RE.findall(article))
    failures: list[str] = []
    if len(article) > len(transcript):
        failures.append("output_longer_than_transcript")
    if len(transcript) >= MIN_ARTICLE_CHARS and not (MIN_ARTICLE_CHARS <= len(article) <= MAX_ARTICLE_CHARS):
        failures.append("outside_600_1500_chars")
    if h1_count != 1:
        failures.append("requires_exactly_one_h1")
    if not 2 <= h2_count <= 4:
        failures.append("requires_two_to_four_h2")

    transcript_normalized = _normalized_quote(transcript)
    quote_results = []
    for match in QUOTE_RE.finditer(article):
        quote = next(group for group in match.groups() if group is not None)
        normalized = _normalized_quote(quote)
        if len(normalized) < 8:
            continue
        traceable = bool(normalized) and normalized in transcript_normalized
        nearby = article[max(0, match.start() - 40) : min(len(article), match.end() + 40)]
        timestamped = bool(TIMESTAMP_NEAR_RE.search(nearby))
        quote_results.append({"quote": quote, "traceable": traceable, "timestamped": timestamped})
        if not traceable:
            failures.append("untraceable_direct_quote")
        if require_quote_timestamp and not timestamped:
            failures.append("direct_quote_without_timestamp")

    return {
        "sample_id": record["sample_id"],
        "category": record["category"],
        "variant": variant,
        "run_number": run_number,
        "transcript_chars": len(transcript),
        "article_chars": len(article),
        "h1_count": h1_count,
        "h2_count": h2_count,
        "quotes": quote_results,
        "hard_failures": sorted(set(failures)),
        "passed": not failures,
    }


def _automatic_checks_v4(record: dict[str, Any]) -> dict[str, Any]:
    result = _automatic_checks(record, "general_v4", 1, require_quote_timestamp=False)
    article = _read_text(
        OUTPUT_DIR / "general_v4" / record["sample_id"] / "run-1.md"
    ).strip()
    bold_spans = re.findall(r"\*\*([^*\n]+)\*\*", article)
    blockquote_count = len(re.findall(r"^>\s+", article, re.MULTILINE))
    full_bold_paragraphs = [
        paragraph
        for paragraph in re.split(r"\n\s*\n", article)
        if re.fullmatch(r"\s*\*\*[^*\n]+\*\*\s*", paragraph)
    ]
    failures = list(result["hard_failures"])
    if len(bold_spans) < 2:
        failures.append("requires_at_least_two_bold_spans")
    if full_bold_paragraphs:
        failures.append("entire_paragraph_bolded")
    if blockquote_count > 1:
        failures.append("more_than_one_blockquote")
    if TIMESTAMP_NEAR_RE.search(article):
        failures.append("quote_timestamp_present")
    result.update(
        {
            "bold_span_count": len(bold_spans),
            "blockquote_count": blockquote_count,
            "full_bold_paragraph_count": len(full_bold_paragraphs),
            "hard_failures": sorted(set(failures)),
            "passed": not failures,
        }
    )
    return result


def _article_metrics(record: dict[str, Any], variant: str, *, enforce_v5: bool) -> dict[str, Any]:
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    article = _read_text(OUTPUT_DIR / variant / record["sample_id"] / "run-1.md").strip()
    bold_spans = re.findall(r"\*\*([^*\n]+)\*\*", article)
    blockquote_count = len(re.findall(r"^>\s+", article, re.MULTILINE))
    full_bold_paragraphs = [
        paragraph
        for paragraph in re.split(r"\n\s*\n", article)
        if re.fullmatch(r"\s*\*\*[^*\n]+\*\*\s*", paragraph)
    ]
    full_bold_sentences = re.findall(r"\*\*[^*\n]{12,}[。！？!?]\*\*", article)

    substantive_paragraphs = []
    for index, paragraph in enumerate(re.split(r"\n\s*\n", article), start=1):
        stripped = paragraph.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(">"):
            continue
        plain = re.sub(r"[`*_>#-]", "", stripped)
        plain = re.sub(r"\s+", "", plain)
        if len(plain) < 60:
            continue
        substantive_paragraphs.append(
            {
                "paragraph": index,
                "chars": len(plain),
                "bold_span_count": len(re.findall(r"\*\*([^*\n]+)\*\*", stripped)),
            }
        )

    converted = _SIMPLIFIED_CHINESE_CONVERTER.convert(article)
    changes = []
    for source_char, converted_char in zip(article, converted):
        if source_char != converted_char:
            change = f"{source_char}→{converted_char}"
            if change not in changes:
                changes.append(change)
        if len(changes) == 12:
            break

    failures: list[str] = []
    article_chars = len(article)
    h1_count = len(H1_RE.findall(article))
    h2_count = len(H2_RE.findall(article))
    if article_chars > len(transcript):
        failures.append("output_longer_than_transcript")
    if len(transcript) >= MIN_ARTICLE_CHARS and not (
        MIN_ARTICLE_CHARS <= article_chars <= MAX_ARTICLE_CHARS
    ):
        failures.append("outside_600_1500_chars")
    if h1_count != 1:
        failures.append("requires_exactly_one_h1")
    if not 2 <= h2_count <= 4:
        failures.append("requires_two_to_four_h2")
    if blockquote_count > 1:
        failures.append("more_than_one_blockquote")
    if TIMESTAMP_NEAR_RE.search(article):
        failures.append("quote_timestamp_present")
    if full_bold_paragraphs:
        failures.append("entire_paragraph_bolded")
    if full_bold_sentences:
        failures.append("entire_sentence_bolded")
    if enforce_v5:
        if converted != article:
            failures.append("contains_traditional_chinese")
        if not 10 <= len(bold_spans) <= 18:
            failures.append("bold_count_outside_10_18")
        if any(not 2 <= row["bold_span_count"] <= 4 for row in substantive_paragraphs):
            failures.append("paragraph_bold_density_outside_2_4")

    return {
        "sample_id": record["sample_id"],
        "variant": variant,
        "transcript_chars": len(transcript),
        "article_chars": article_chars,
        "h1_count": h1_count,
        "h2_count": h2_count,
        "bold_span_count": len(bold_spans),
        "blockquote_count": blockquote_count,
        "full_bold_paragraph_count": len(full_bold_paragraphs),
        "full_bold_sentence_count": len(full_bold_sentences),
        "substantive_paragraphs": substantive_paragraphs,
        "simplified_chinese": converted == article,
        "traditional_change_examples": changes,
        "format_failures": sorted(set(failures)),
        "format_passed": not failures,
    }


def _inline_markdown_to_html(text: str) -> str:
    rendered = html.escape(text)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"`([^`]+)`", r"<code>\1</code>", rendered)
    return rendered


def _article_markdown_to_html(markdown: str) -> str:
    blocks: list[str] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []

    def flush_paragraph() -> None:
        if paragraph_lines:
            blocks.append(f"<p>{_inline_markdown_to_html(' '.join(paragraph_lines))}</p>")
            paragraph_lines.clear()

    def flush_list() -> None:
        if list_items:
            items = "".join(f"<li>{_inline_markdown_to_html(item)}</li>" for item in list_items)
            blocks.append(f"<ul>{items}</ul>")
            list_items.clear()

    for raw_line in markdown.strip().splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
        elif line.startswith("## "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h4>{_inline_markdown_to_html(line[3:])}</h4>")
        elif line.startswith("# "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<h3>{_inline_markdown_to_html(line[2:])}</h3>")
        elif line.startswith("> "):
            flush_paragraph()
            flush_list()
            blocks.append(f"<blockquote>{_inline_markdown_to_html(line[2:])}</blockquote>")
        elif line.startswith("- "):
            flush_paragraph()
            list_items.append(line[2:])
        else:
            flush_list()
            paragraph_lines.append(line)
    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def _judge_pair(record: dict[str, Any], left: str, right: str) -> dict[str, Any]:
    sample_id = record["sample_id"]
    pair_name = f"{left}__{right}"
    target = EVALUATION_DIR / "pairs" / f"{sample_id}__{pair_name}.json"
    if target.exists():
        return _read_json(target)

    variants = [left, right]
    random.Random(f"{SEED}:judge:{sample_id}:{pair_name}").shuffle(variants)
    mapping = {"A": variants[0], "B": variants[1]}
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    article_a = _read_text(OUTPUT_DIR / mapping["A"] / sample_id / "run-1.md")
    article_b = _read_text(OUTPUT_DIR / mapping["B"] / sample_id / "run-1.md")
    user = (
        f"视频标题：{record['title']}\n\n"
        f"完整 transcript：\n{transcript}\n\n"
        f"候选文章 A：\n{article_a}\n\n"
        f"候选文章 B：\n{article_b}"
    )
    response = _call_model(_read_prompt("judge-pair.md"), user)
    parsed = _extract_json(response["text"])
    if parsed.get("preferred") not in {"A", "B", "tie"}:
        raise ExperimentError(f"Invalid judge preference for {sample_id} {pair_name}")
    payload = {
        "sample_id": sample_id,
        "category": record["category"],
        "pair": pair_name,
        "mapping": mapping,
        "judge": parsed,
        "model": response["model"],
        "usage": response["usage"],
        "elapsed_seconds": response["elapsed_seconds"],
    }
    _write_json(target, payload)
    print(f"Judged {sample_id}: {pair_name}")
    return payload


def _judge_stability(
    record: dict[str, Any],
    variant: str = "category",
    result_directory: str = "stability",
) -> dict[str, Any]:
    sample_id = record["sample_id"]
    target = EVALUATION_DIR / result_directory / f"{sample_id}.json"
    if target.exists():
        return _read_json(target)
    transcript = _read_text(ROOT / record["snapshot_transcript"])
    first = _read_text(OUTPUT_DIR / variant / sample_id / "run-1.md")
    second = _read_text(OUTPUT_DIR / variant / sample_id / "run-2.md")
    system = _read_prompt("judge-stability.md").strip()
    user = f"完整 transcript：\n{transcript}\n\n文章 A：\n{first}\n\n文章 B：\n{second}"
    response = _call_model(system, user)
    parsed = _extract_json(response["text"])
    payload = {
        "sample_id": sample_id,
        "category": record["category"],
        "judge": parsed,
        "model": response["model"],
        "usage": response["usage"],
        "elapsed_seconds": response["elapsed_seconds"],
    }
    _write_json(target, payload)
    print(f"Judged stability for {sample_id}")
    return payload


def stage_evaluate() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run the generate stage first")

    automatic = []
    for record in core:
        for variant in ("current", "general", "category"):
            automatic.append(_automatic_checks(record, variant, 1))
        if record["sample_id"] in stability_ids:
            automatic.append(_automatic_checks(record, "category", 2))
    _write_jsonl(EVALUATION_DIR / "automatic-checks.jsonl", automatic)

    jobs = []
    for record in core:
        jobs.extend(
            [
                (_judge_pair, (record, "current", "general")),
                (_judge_pair, (record, "general", "category")),
                (_judge_pair, (record, "current", "category")),
            ]
        )
        if record["sample_id"] in stability_ids:
            jobs.append((_judge_stability, (record,)))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(function, *arguments) for function, arguments in jobs]
        for future in as_completed(futures):
            future.result()


def stage_evaluate_v2() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run the v2 generate stage first")

    automatic = [_automatic_checks(record, "general_v2", 1) for record in core]
    automatic.extend(
        _automatic_checks(record, "general_v2", 2)
        for record in core
        if record["sample_id"] in stability_ids
    )
    _write_jsonl(EVALUATION_DIR / "automatic-checks-v2.jsonl", automatic)

    jobs = []
    for record in core:
        jobs.extend(
            [
                (_judge_pair, (record, "current", "general_v2")),
                (_judge_pair, (record, "general", "general_v2")),
            ]
        )
        if record["sample_id"] in stability_ids:
            jobs.append((_judge_stability, (record, "general_v2", "stability-v2")))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(function, *arguments) for function, arguments in jobs]
        for future in as_completed(futures):
            future.result()


def stage_evaluate_v3() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    stability_ids = {row["sample_id"] for row in _read_jsonl(EXPERIMENT_DIR / "stability-samples.jsonl")}
    if not core:
        raise ExperimentError("Run the v3 generate stage first")

    automatic = [_automatic_checks(record, "general_v3", 1) for record in core]
    automatic.extend(
        _automatic_checks(record, "general_v3", 2)
        for record in core
        if record["sample_id"] in stability_ids
    )
    _write_jsonl(EVALUATION_DIR / "automatic-checks-v3.jsonl", automatic)

    jobs = []
    for record in core:
        jobs.extend(
            [
                (_judge_pair, (record, "current", "general_v3")),
                (_judge_pair, (record, "general", "general_v3")),
            ]
        )
        if record["sample_id"] in stability_ids:
            jobs.append((_judge_stability, (record, "general_v3", "stability-v3")))
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(function, *arguments) for function, arguments in jobs]
        for future in as_completed(futures):
            future.result()


def _candidate_payload(pair: dict[str, Any], variant: str) -> dict[str, Any]:
    label = next(label for label, value in pair["mapping"].items() if value == variant)
    return pair["judge"][f"candidate_{label.lower()}"]


def _candidate_score(pair: dict[str, Any], variant: str) -> float:
    payload = _candidate_payload(pair, variant)
    values = [float(payload["scores"][key]) for key in SCORE_KEYS]
    return sum(values) / len(values)


def _preferred_variant(pair: dict[str, Any]) -> str:
    preferred = pair["judge"]["preferred"]
    return "tie" if preferred == "tie" else pair["mapping"][preferred]


def stage_report() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    if not core:
        raise ExperimentError("No core samples found")
    pair_files = sorted((EVALUATION_DIR / "pairs").glob("*.json"))
    if not pair_files:
        raise ExperimentError("Run the evaluate stage first")
    pairs = [_read_json(path) for path in pair_files]
    pair_index = {(row["sample_id"], row["pair"]): row for row in pairs}
    automatic = {
        (row["sample_id"], row["variant"], row["run_number"]): row
        for row in _read_jsonl(EVALUATION_DIR / "automatic-checks.jsonl")
    }

    category_results: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        records = [row for row in core if row["category"] == category]
        comparisons = [pair_index[(row["sample_id"], "general__category")] for row in records]
        wins = sum(_preferred_variant(pair) == "category" for pair in comparisons)
        average_gain = sum(
            _candidate_score(pair, "category") - _candidate_score(pair, "general")
            for pair in comparisons
        ) / len(comparisons)
        new_fidelity_failures = sum(
            not bool(_candidate_payload(pair, "category").get("faithful"))
            and bool(_candidate_payload(pair, "general").get("faithful"))
            for pair in comparisons
        )
        retained = wins >= 4 and average_gain >= 0.25 and new_fidelity_failures == 0
        category_results[category] = {
            "wins": wins,
            "average_gain": round(average_gain, 3),
            "new_fidelity_failures": new_fidelity_failures,
            "retained": retained,
        }

    final_hard_failures = 0
    final_preferences = 0
    final_comparisons = 0
    scored_records: list[tuple[float, dict[str, Any], str]] = []
    for record in core:
        category = record["category"]
        final_variant = "category" if category_results[category]["retained"] else "general"
        pair_name = f"current__{final_variant}"
        pair = pair_index[(record["sample_id"], pair_name)]
        final_comparisons += 1
        final_preferences += _preferred_variant(pair) == final_variant
        model_payload = _candidate_payload(pair, final_variant)
        auto_payload = automatic[(record["sample_id"], final_variant, 1)]
        if not model_payload.get("faithful") or auto_payload["hard_failures"]:
            final_hard_failures += 1
        scored_records.append((_candidate_score(pair, final_variant), record, final_variant))

    stability_files = sorted((EVALUATION_DIR / "stability").glob("*.json"))
    stability = [_read_json(path) for path in stability_files]
    stable_count = sum(
        bool(row["judge"].get("run_a_faithful"))
        and bool(row["judge"].get("run_b_faithful"))
        and bool(row["judge"].get("same_core_insight"))
        for row in stability
    )

    review_rows = []
    for category in CATEGORIES:
        candidates = [item for item in scored_records if item[1]["category"] == category]
        candidates.sort(key=lambda item: (-item[0], item[1]["sample_id"]))
        for score, record, final_variant in candidates[:3]:
            review_rows.append(
                {
                    "category": category,
                    "category_label": CATEGORY_LABELS[category],
                    "sample_id": record["sample_id"],
                    "title": record["title"],
                    "score": round(score, 3),
                    "transcript": record["snapshot_transcript"],
                    "historical_summary": record["snapshot_old_summary"],
                    "current_prompt_output": _relative(OUTPUT_DIR / "current" / record["sample_id"] / "run-1.md"),
                    "general_prompt_output": _relative(OUTPUT_DIR / "general" / record["sample_id"] / "run-1.md"),
                    "category_prompt_output": _relative(OUTPUT_DIR / "category" / record["sample_id"] / "run-1.md"),
                    "recommended_output": _relative(OUTPUT_DIR / final_variant / record["sample_id"] / "run-1.md"),
                }
            )
    _write_jsonl(EXPERIMENT_DIR / "review-index.jsonl", review_rows)

    preference_rate = final_preferences / final_comparisons if final_comparisons else 0.0
    lines = [
        "# Summary Prompt V1 Results",
        "",
        "## 类别提示词判定",
        "",
        "| 类别 | 胜出篇数 | 平均提升 | 新增忠实性失败 | 保留 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for category in CATEGORIES:
        result = category_results[category]
        lines.append(
            f"| {CATEGORY_LABELS[category]} | {result['wins']}/6 | {result['average_gain']:.3f} | "
            f"{result['new_fidelity_failures']} | {'是' if result['retained'] else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 总体验收",
            "",
            f"- 最终候选忠实性或自动硬失败：{final_hard_failures}/24",
            f"- 相对当前提示词同模型基线的匿名偏好率：{preference_rate:.1%}",
            f"- 稳定性通过：{stable_count}/{len(stability)}",
            f"- 内容自动条件通过：{'是' if final_hard_failures == 0 else '否'}",
            f"- 偏好率达到 70%：{'是' if preference_rate >= 0.70 else '否'}",
            f"- 稳定性达到 7/8：{'是' if stable_count >= 7 else '否'}",
            "",
            "## 人工复核",
            "",
            "每类得分最高的 3 组完整材料已写入 `data/experiments/summary-prompt-v1/review-index.jsonl`。",
            "用户复核完成前，本报告不宣布提示词最终通过，也不接入生产。",
        ]
    )
    (TRACKED_DIR / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(
        EXPERIMENT_DIR / "result-summary.json",
        {
            "category_results": category_results,
            "final_hard_failures": final_hard_failures,
            "preference_rate": round(preference_rate, 4),
            "stable_count": stable_count,
            "stability_total": len(stability),
            "human_review_complete": False,
        },
    )
    print("Wrote results.md and review-index.jsonl")


def stage_report_v2() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    automatic = {
        (row["sample_id"], row["run_number"]): row
        for row in _read_jsonl(EVALUATION_DIR / "automatic-checks-v2.jsonl")
    }
    pairs = [_read_json(path) for path in (EVALUATION_DIR / "pairs").glob("*.json")]
    pair_index = {(row["sample_id"], row["pair"]): row for row in pairs}
    stability = [
        _read_json(path) for path in sorted((EVALUATION_DIR / "stability-v2").glob("*.json"))
    ]
    if not core or any((row["sample_id"], "current__general_v2") not in pair_index for row in core):
        raise ExperimentError("Run the v2 evaluate stage first")

    hard_failures = 0
    preferred_over_current = 0
    preferred_over_v1 = 0
    score_gains = []
    scored_records = []
    for record in core:
        sample_id = record["sample_id"]
        current_pair = pair_index[(sample_id, "current__general_v2")]
        v1_pair = pair_index[(sample_id, "general__general_v2")]
        v2_payload = _candidate_payload(current_pair, "general_v2")
        if not v2_payload.get("faithful") or automatic[(sample_id, 1)]["hard_failures"]:
            hard_failures += 1
        preferred_over_current += _preferred_variant(current_pair) == "general_v2"
        preferred_over_v1 += _preferred_variant(v1_pair) == "general_v2"
        gain = _candidate_score(v1_pair, "general_v2") - _candidate_score(v1_pair, "general")
        score_gains.append(gain)
        scored_records.append((_candidate_score(current_pair, "general_v2"), record))

    stable_count = sum(
        bool(row["judge"].get("run_a_faithful"))
        and bool(row["judge"].get("run_b_faithful"))
        and bool(row["judge"].get("same_core_insight"))
        for row in stability
    )
    review_rows = []
    for category in CATEGORIES:
        candidates = [item for item in scored_records if item[1]["category"] == category]
        candidates.sort(key=lambda item: (-item[0], item[1]["sample_id"]))
        for score, record in candidates[:3]:
            review_rows.append(
                {
                    "category": category,
                    "category_label": CATEGORY_LABELS[category],
                    "sample_id": record["sample_id"],
                    "title": record["title"],
                    "score": round(score, 3),
                    "transcript": record["snapshot_transcript"],
                    "historical_summary": record["snapshot_old_summary"],
                    "current_prompt_output": _relative(OUTPUT_DIR / "current" / record["sample_id"] / "run-1.md"),
                    "v1_general_output": _relative(OUTPUT_DIR / "general" / record["sample_id"] / "run-1.md"),
                    "v2_recommended_output": _relative(OUTPUT_DIR / "general_v2" / record["sample_id"] / "run-1.md"),
                }
            )
    _write_jsonl(EXPERIMENT_DIR / "review-index-v2.jsonl", review_rows)

    current_rate = preferred_over_current / len(core)
    v1_rate = preferred_over_v1 / len(core)
    average_gain = sum(score_gains) / len(score_gains)
    passed = hard_failures == 0 and current_rate >= 0.70 and stable_count >= 7
    lines = [
        "# Summary Prompt V2 Results",
        "",
        "## 最少类别结论",
        "",
        "v1 的四个类别增量均未达到保留门槛，v2 因此采用一个自适应通用提示词。四类标签只用于分层评测，不参与运行时路由。",
        "",
        "## 验收结果",
        "",
        f"- 忠实性或自动硬失败：{hard_failures}/24",
        f"- 相对当前生产提示词同模型基线的匿名偏好率：{current_rate:.1%}",
        f"- 相对 v1 通用提示词的匿名偏好率：{v1_rate:.1%}",
        f"- 相对 v1 通用提示词的平均评分提升：{average_gain:.3f}/5",
        f"- 稳定性通过：{stable_count}/{len(stability)}",
        f"- 自动验收：{'通过' if passed else '未通过'}",
        "",
        "## 人工复核",
        "",
        "每个结构类别得分最高的 3 组材料保存在 `data/experiments/summary-prompt-v1/review-index-v2.jsonl`。",
        "用户完成匿名复核前，不接入生产。",
    ]
    (TRACKED_DIR / "results-v2.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(
        EXPERIMENT_DIR / "result-summary-v2.json",
        {
            "final_category_count": 1,
            "hard_failures": hard_failures,
            "preference_rate_over_current": round(current_rate, 4),
            "preference_rate_over_v1": round(v1_rate, 4),
            "average_score_gain_over_v1": round(average_gain, 4),
            "stable_count": stable_count,
            "stability_total": len(stability),
            "automatic_acceptance": passed,
            "human_review_complete": False,
        },
    )
    print("Wrote results-v2.md and review-index-v2.jsonl")


def stage_report_v3() -> None:
    model_settings = _load_model_config()
    _write_json(
        EXPERIMENT_DIR / "model-config.snapshot.json",
        {
            "source": _relative(MODEL_CONFIG_PATH),
            "requested_model": model_settings["model"],
            "base_url": model_settings["base_url"],
            "endpoint": "/v1/messages",
            "api_key": "omitted",
        },
    )
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    automatic = {
        (row["sample_id"], row["run_number"]): row
        for row in _read_jsonl(EVALUATION_DIR / "automatic-checks-v3.jsonl")
    }
    pairs = [_read_json(path) for path in (EVALUATION_DIR / "pairs").glob("*.json")]
    pair_index = {(row["sample_id"], row["pair"]): row for row in pairs}
    stability = [
        _read_json(path) for path in sorted((EVALUATION_DIR / "stability-v3").glob("*.json"))
    ]
    if not core or any((row["sample_id"], "current__general_v3") not in pair_index for row in core):
        raise ExperimentError("Run the v3 evaluate stage first")

    hard_failures = 0
    judged_fidelity_failures = 0
    automatic_failures = 0
    preferred_over_current = 0
    preferred_over_v1 = 0
    score_gains = []
    scored_records = []
    for record in core:
        sample_id = record["sample_id"]
        current_pair = pair_index[(sample_id, "current__general_v3")]
        v1_pair = pair_index[(sample_id, "general__general_v3")]
        v3_payload = _candidate_payload(current_pair, "general_v3")
        judged_failed = not (
            v3_payload.get("faithful")
            and v3_payload.get("attribution_correct")
            and v3_payload.get("quotes_traceable")
        )
        automatic_failed = bool(automatic[(sample_id, 1)]["hard_failures"])
        judged_fidelity_failures += judged_failed
        automatic_failures += automatic_failed
        hard_failures += judged_failed or automatic_failed
        preferred_over_current += _preferred_variant(current_pair) == "general_v3"
        preferred_over_v1 += _preferred_variant(v1_pair) == "general_v3"
        gain = _candidate_score(v1_pair, "general_v3") - _candidate_score(v1_pair, "general")
        score_gains.append(gain)
        scored_records.append((_candidate_score(current_pair, "general_v3"), record))

    stable_count = sum(
        bool(row["judge"].get("run_a_faithful"))
        and bool(row["judge"].get("run_b_faithful"))
        and bool(row["judge"].get("same_core_insight"))
        for row in stability
    )
    review_rows = []
    for category in CATEGORIES:
        candidates = [item for item in scored_records if item[1]["category"] == category]
        candidates.sort(key=lambda item: (-item[0], item[1]["sample_id"]))
        for score, record in candidates[:3]:
            review_rows.append(
                {
                    "category": category,
                    "category_label": CATEGORY_LABELS[category],
                    "sample_id": record["sample_id"],
                    "title": record["title"],
                    "score": round(score, 3),
                    "transcript": record["snapshot_transcript"],
                    "historical_summary": record["snapshot_old_summary"],
                    "current_prompt_output": _relative(OUTPUT_DIR / "current" / record["sample_id"] / "run-1.md"),
                    "v1_general_output": _relative(OUTPUT_DIR / "general" / record["sample_id"] / "run-1.md"),
                    "v1_category_output": _relative(OUTPUT_DIR / "category" / record["sample_id"] / "run-1.md"),
                    "v2_general_output": _relative(OUTPUT_DIR / "general_v2" / record["sample_id"] / "run-1.md"),
                    "v3_recommended_output": _relative(OUTPUT_DIR / "general_v3" / record["sample_id"] / "run-1.md"),
                }
            )
    _write_jsonl(EXPERIMENT_DIR / "review-index-v3.jsonl", review_rows)

    blind_dir = EXPERIMENT_DIR / "blind-review-v3"
    blind_rows = []
    blind_keys = []
    blind_index = [
        "# V3 匿名人工复核",
        "",
        "先读原文与历史旧总结，再比较候选 A、B。请记录偏好、忠实性问题和最主要理由；完成前不要打开 `answer-key.jsonl`。",
        "",
        "| 结构标签 | 样本 | 材料 |",
        "| --- | --- | --- |",
    ]
    for row in review_rows:
        sample_id = row["sample_id"]
        sample_dir = blind_dir / sample_id
        _copy_snapshot(ROOT / row["transcript"], sample_dir / "transcript.md")
        _copy_snapshot(ROOT / row["historical_summary"], sample_dir / "historical-summary.md")
        candidates = [
            ("current", ROOT / row["current_prompt_output"]),
            ("general_v3", ROOT / row["v3_recommended_output"]),
        ]
        random.Random(f"{SEED}:human-review:{sample_id}").shuffle(candidates)
        mapping = {}
        for label, (variant, source) in zip(("A", "B"), candidates):
            target = sample_dir / f"candidate-{label.lower()}.md"
            _copy_snapshot(source, target)
            mapping[label] = variant
        blind_rows.append(
            {
                "category_label": row["category_label"],
                "sample_id": sample_id,
                "title": row["title"],
                "transcript": _relative(sample_dir / "transcript.md"),
                "historical_summary": _relative(sample_dir / "historical-summary.md"),
                "candidate_a": _relative(sample_dir / "candidate-a.md"),
                "candidate_b": _relative(sample_dir / "candidate-b.md"),
            }
        )
        blind_keys.append({"sample_id": sample_id, "mapping": mapping})
        table_title = row["title"].replace("|", "\\|")
        blind_index.append(
            f"| {row['category_label']} | {sample_id} · {table_title} | "
            f"[原文]({sample_id}/transcript.md) · [旧总结]({sample_id}/historical-summary.md) · "
            f"[候选 A]({sample_id}/candidate-a.md) · [候选 B]({sample_id}/candidate-b.md) |"
        )
    _write_jsonl(blind_dir / "manifest.jsonl", blind_rows)
    _write_jsonl(blind_dir / "answer-key.jsonl", blind_keys)
    (blind_dir / "index.md").write_text("\n".join(blind_index) + "\n", encoding="utf-8")

    current_rate = preferred_over_current / len(core)
    v1_rate = preferred_over_v1 / len(core)
    average_gain = sum(score_gains) / len(score_gains)
    passed = hard_failures == 0 and current_rate >= 0.70 and stable_count >= 7
    lines = [
        "# Summary Prompt V3 Results",
        "",
        "## 最少类别结论",
        "",
        "四个类别增量均未达到保留门槛。最终候选是一个通用懒提示词；四类标签只用于分层评测。",
        "",
        "## 验收结果",
        "",
        f"- 模型判定的忠实性硬失败：{judged_fidelity_failures}/24",
        f"- 格式、长度或引语自动硬失败：{automatic_failures}/24",
        f"- 两类硬失败去重：{hard_failures}/24",
        f"- 相对当前生产提示词同模型基线的匿名偏好率：{current_rate:.1%}",
        f"- 相对 v1 通用提示词的匿名偏好率：{v1_rate:.1%}",
        f"- 相对 v1 通用提示词的平均评分提升：{average_gain:.3f}/5",
        f"- 稳定性通过：{stable_count}/{len(stability)}",
        f"- 自动验收：{'通过' if passed else '未通过'}",
        "",
        "## 人工复核",
        "",
        "每个结构类别得分最高的 3 组完整材料保存在 `data/experiments/summary-prompt-v1/review-index-v3.jsonl`。",
        "用户完成匿名复核前，不接入生产。",
    ]
    (TRACKED_DIR / "results-v3.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(
        EXPERIMENT_DIR / "result-summary-v3.json",
        {
            "final_category_count": 1,
            "judged_fidelity_failures": judged_fidelity_failures,
            "automatic_failures": automatic_failures,
            "hard_failures": hard_failures,
            "preference_rate_over_current": round(current_rate, 4),
            "preference_rate_over_v1": round(v1_rate, 4),
            "average_score_gain_over_v1": round(average_gain, 4),
            "stable_count": stable_count,
            "stability_total": len(stability),
            "automatic_acceptance": passed,
            "human_review_complete": False,
        },
    )
    print("Wrote results-v3.md and review-index-v3.jsonl")


def stage_report_v4() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    record_index = {row["sample_id"]: row for row in core}
    missing = [sample_id for sample_id in V4_TARGETS if sample_id not in record_index]
    if missing:
        raise ExperimentError(f"Missing v4 target samples: {missing}")

    records = [record_index[sample_id] for sample_id in V4_TARGETS]
    metadata_rows = []
    for record in records:
        output_path = OUTPUT_DIR / "general_v4" / record["sample_id"] / "run-1.md"
        metadata_path = output_path.with_suffix(".json")
        if not output_path.exists():
            raise ExperimentError(f"Missing v4 output: {output_path}")
        if not metadata_path.exists():
            raise ExperimentError(f"Missing v4 metadata: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("variant") != "general_v4":
            raise ExperimentError(f"Unexpected v4 metadata variant: {metadata_path}")
        metadata_rows.append(metadata)

    prompt_hashes = {row.get("prompt_sha256") for row in metadata_rows}
    if len(prompt_hashes) != 1:
        raise ExperimentError(f"V4 outputs used different prompt hashes: {prompt_hashes}")
    configured_model = _load_model_config()["model"]
    response_models = sorted({str(row.get("model")) for row in metadata_rows})

    checks = [_automatic_checks_v4(record) for record in records]
    _write_jsonl(EVALUATION_DIR / "automatic-checks-v4.jsonl", checks)
    check_index = {row["sample_id"]: row for row in checks}
    audit_rows = _read_jsonl(EXPERIMENT_DIR / "manual-audit-v4.jsonl")
    audit_index = {row["sample_id"]: row for row in audit_rows}

    review_lines = [
        "# V4 定向文章复核",
        "",
        "本文件只展示 12 篇 v4 新文章，不包含 v3 对照。人物与事实只能来自 transcript；所有引用均不带时间戳。",
        "",
        "- [v4 提示词](../../../experiments/summary-prompt-v1/prompts/general-v4.md)",
        "- [v4 静态结果](../../../experiments/summary-prompt-v1/results-v4.md)",
        "",
        "| 样本 | 定向能力 | v4 文章 | 原 transcript |",
        "| --- | --- | --- | --- |",
    ]
    for record in records:
        sample_id = record["sample_id"]
        title = record["title"].replace("|", "\\|")
        review_lines.append(
            f"| {sample_id} · {title} | {V4_TARGETS[sample_id]} | "
            f"[单独打开](outputs/general_v4/{sample_id}/run-1.md) | "
            f"[原文](samples/{sample_id}/transcript.original.txt) |"
        )
    for record in records:
        sample_id = record["sample_id"]
        article = _read_text(OUTPUT_DIR / "general_v4" / sample_id / "run-1.md").strip()
        rendered = re.sub(r"^##\s+", "#### ", article, flags=re.MULTILINE)
        rendered = re.sub(r"^#\s+", "### ", rendered, flags=re.MULTILINE)
        review_lines.extend(
            [
                "",
                "---",
                "",
                f"## {sample_id} · {record['title']}",
                "",
                f"**定向能力：** {V4_TARGETS[sample_id]}",
                "",
                f"[打开原 transcript](samples/{sample_id}/transcript.original.txt) · "
                f"[打开独立 v4 文件](outputs/general_v4/{sample_id}/run-1.md)",
                "",
                rendered,
            ]
        )
    (EXPERIMENT_DIR / "v4-review.md").write_text(
        "\n".join(review_lines) + "\n", encoding="utf-8"
    )

    passed = sum(row["passed"] for row in checks)
    within_length = sum(
        MIN_ARTICLE_CHARS <= row["article_chars"] <= MAX_ARTICLE_CHARS for row in checks
    )
    bold_ok = sum(row["bold_span_count"] >= 2 for row in checks)
    timestamp_free = sum("quote_timestamp_present" not in row["hard_failures"] for row in checks)
    blockquote_ok = sum(row["blockquote_count"] <= 1 for row in checks)
    lines = [
        "# Summary Prompt V4 Results",
        "",
        "## 范围",
        "",
        "v4 只验证新增的代价与教训、人物背景和 Markdown 强调能力。共生成 12 篇，不重新生成或展示 v3。",
        "",
        f"- 12/12 篇请求均读取唯一配置模型 `{configured_model}`；API 响应模型标识为 `{', '.join(response_models)}`。",
        f"- 12/12 篇使用同一提示词哈希：`{next(iter(prompt_hashes))}`。",
        "- 元数据仅记录模型、提示词哈希、耗时、生成参数和 token 用量，不记录 API 密钥。",
        "",
        "## 自动检查",
        "",
        f"- 全部自动条件通过：{passed}/12",
        f"- 位于 600–1,500 字符：{within_length}/12",
        f"- 至少两处加粗：{bold_ok}/12",
        f"- 至多一处块引用：{blockquote_ok}/12",
        f"- 不含引用时间戳：{timestamp_free}/12",
        "- 自动引语匹配只验证同语种逐字片段；英文 transcript 的中文翻译引语仍需人工核对。",
        "",
        "| 样本 | 字符数 | 加粗 | 块引用 | 自动失败 | 助手定向核对 |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for record in records:
        sample_id = record["sample_id"]
        check = check_index[sample_id]
        audit = audit_index.get(sample_id)
        audit_status = audit.get("status", "待检查") if audit else "待检查"
        failures = "、".join(check["hard_failures"]) or "无"
        lines.append(
            f"| {sample_id} | {check['article_chars']} | {check['bold_span_count']} | "
            f"{check['blockquote_count']} | {failures} | {audit_status} |"
        )
    lines.extend(
        [
            "",
            "## 逐篇来源核对（助手）",
            "",
        ]
    )
    if audit_rows:
        for row in audit_rows:
            lines.append(f"- **{row['sample_id']} · {row['status']}**：{row['note']}")
        lines.extend(
            [
                "",
                "以上是助手逐篇对照 transcript 的核对结果，不等于用户已经完成人工确认。",
            ]
        )
    else:
        lines.append("尚未完成。用户确认前，v4 不接入生产。")
    lines.extend(
        [
            "",
            "## 阅读入口",
            "",
            "完整 12 篇文章见 `data/experiments/summary-prompt-v1/v4-review.md`。",
            "用户确认前，v4 仍是研究候选，不接入生产。",
        ]
    )
    (TRACKED_DIR / "results-v4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(
        EXPERIMENT_DIR / "result-summary-v4.json",
        {
            "sample_count": len(records),
            "configured_model": configured_model,
            "response_models": response_models,
            "prompt_sha256": next(iter(prompt_hashes)),
            "automatic_passed": passed,
            "within_length": within_length,
            "bold_ok": bold_ok,
            "blockquote_ok": blockquote_ok,
            "timestamp_free": timestamp_free,
            "assistant_manual_audit_complete": len(audit_rows) == len(records),
            "user_review_complete": False,
        },
    )
    print("Wrote results-v4.md and v4-review.md")


def stage_report_gpt_v5() -> None:
    core = _read_jsonl(EXPERIMENT_DIR / "core-samples.jsonl")
    record_index = {row["sample_id"]: row for row in core}
    missing = [sample_id for sample_id in V4_TARGETS if sample_id not in record_index]
    if missing:
        raise ExperimentError(f"Missing GPT v5 target samples: {missing}")
    records = [record_index[sample_id] for sample_id in V4_TARGETS]

    metadata_rows = []
    for record in records:
        sample_id = record["sample_id"]
        gpt_path = OUTPUT_DIR / "gpt_general_v5" / sample_id / "run-1.md"
        claude_path = OUTPUT_DIR / "general_v4" / sample_id / "run-1.md"
        metadata_path = gpt_path.with_suffix(".json")
        for required in (gpt_path, claude_path, metadata_path):
            if not required.exists():
                raise ExperimentError(f"Missing comparison artifact: {required}")
        metadata = _read_json(metadata_path)
        if metadata.get("requested_model") != GPT_V5_MODEL:
            raise ExperimentError(f"Unexpected GPT v5 model in {metadata_path}")
        if metadata.get("variant") != "gpt_general_v5":
            raise ExperimentError(f"Unexpected GPT v5 variant in {metadata_path}")
        if metadata.get("opencc_applied") is not False:
            raise ExperimentError(f"GPT v5 output is not marked raw: {metadata_path}")
        metadata_rows.append(metadata)

    expected_prompt_hash = _sha256_text(_read_prompt("general-v5.md").strip())
    prompt_hashes = {row.get("prompt_sha256") for row in metadata_rows}
    if prompt_hashes != {expected_prompt_hash}:
        raise ExperimentError(f"GPT v5 prompt hash mismatch: {prompt_hashes}")

    gpt_checks = [
        _article_metrics(record, "gpt_general_v5", enforce_v5=True) for record in records
    ]
    claude_checks = [
        _article_metrics(record, "general_v4", enforce_v5=False) for record in records
    ]
    _write_jsonl(EVALUATION_DIR / "automatic-checks-gpt-v5.jsonl", gpt_checks)
    gpt_index = {row["sample_id"]: row for row in gpt_checks}
    claude_index = {row["sample_id"]: row for row in claude_checks}

    simplified_count = sum(row["simplified_chinese"] for row in gpt_checks)
    length_count = sum(
        MIN_ARTICLE_CHARS <= row["article_chars"] <= MAX_ARTICLE_CHARS for row in gpt_checks
    )
    heading_count = sum(row["h1_count"] == 1 and 2 <= row["h2_count"] <= 4 for row in gpt_checks)
    blockquote_count = sum(row["blockquote_count"] <= 1 for row in gpt_checks)
    timestamp_count = sum("quote_timestamp_present" not in row["format_failures"] for row in gpt_checks)
    bold_range_count = sum(10 <= row["bold_span_count"] <= 18 for row in gpt_checks)
    paragraph_density_count = sum(
        bool(row["substantive_paragraphs"])
        and all(2 <= item["bold_span_count"] <= 4 for item in row["substantive_paragraphs"])
        for row in gpt_checks
    )
    format_pass_count = sum(row["format_passed"] for row in gpt_checks)
    bold_increase_count = sum(
        gpt_index[sample_id]["bold_span_count"] > claude_index[sample_id]["bold_span_count"]
        for sample_id in V4_TARGETS
    )
    claude_bold_average = sum(row["bold_span_count"] for row in claude_checks) / len(claude_checks)
    gpt_bold_average = sum(row["bold_span_count"] for row in gpt_checks) / len(gpt_checks)
    response_models = sorted({str(row.get("response_model")) for row in metadata_rows})

    result_lines = [
        "# GPT-5.6 Sol V5 Comparison Results",
        "",
        "## 结论边界",
        "",
        "本轮只生成 GPT‑5.6 Sol v5，并与已有 Claude v4 并排展示。由于模型和提示词版本同时变化，结果只能用于选择更喜欢的最终产物，不能把差异严格归因于模型。没有使用 LLM 评分。",
        "",
        f"- 请求模型：`{GPT_V5_MODEL}`；API 响应模型：`{', '.join(response_models)}`。",
        f"- 12 篇使用同一 v5 提示词哈希：`{expected_prompt_hash}`。",
        "- GPT 文章保留原始输出，没有执行 OpenCC 转换。",
        "",
        "## 自动检查",
        "",
        f"- 全部 v5 格式条件通过：{format_pass_count}/12",
        f"- 完全使用简体中文：{simplified_count}/12",
        f"- 位于 600–1,500 字符：{length_count}/12",
        f"- 一级/二级标题符合要求：{heading_count}/12",
        f"- 至多一处块引用：{blockquote_count}/12",
        f"- 不含引用时间戳：{timestamp_count}/12",
        f"- 全文有 10–18 处加粗：{bold_range_count}/12",
        f"- 每个实质段落有 2–4 处加粗：{paragraph_density_count}/12",
        f"- GPT v5 加粗数高于对应 Claude v4：{bold_increase_count}/12",
        f"- 平均加粗数：Claude v4 {claude_bold_average:.2f} → GPT v5 {gpt_bold_average:.2f}",
        "",
        "| 样本 | GPT 字符 | 简体 | 加粗 Claude→GPT | 实质段落密度 | GPT 格式失败 |",
        "| --- | ---: | --- | ---: | --- | --- |",
    ]
    for record in records:
        sample_id = record["sample_id"]
        gpt = gpt_index[sample_id]
        claude = claude_index[sample_id]
        density = ", ".join(
            str(item["bold_span_count"]) for item in gpt["substantive_paragraphs"]
        ) or "无实质段落"
        failures = "、".join(gpt["format_failures"]) or "无"
        result_lines.append(
            f"| {sample_id} | {gpt['article_chars']} | "
            f"{'是' if gpt['simplified_chinese'] else '否'} | "
            f"{claude['bold_span_count']}→{gpt['bold_span_count']} | {density} | {failures} |"
        )
    result_lines.extend(
        [
            "",
            "## 阅读入口",
            "",
            "双栏全文对比见 `data/experiments/summary-prompt-v1/gpt-v5-vs-claude-v4.html`。",
            "用户选定模型和提示词前，本实验不接入生产。",
        ]
    )
    (TRACKED_DIR / "results-gpt-v5.md").write_text(
        "\n".join(result_lines) + "\n", encoding="utf-8"
    )

    summary_cards = "".join(
        [
            f'<div class="summary-card"><strong>{format_pass_count}/12</strong><span>GPT v5 全部格式通过</span></div>',
            f'<div class="summary-card"><strong>{simplified_count}/12</strong><span>原始输出全为简体</span></div>',
            f'<div class="summary-card"><strong>{bold_increase_count}/12</strong><span>加粗数量高于 Claude v4</span></div>',
            f'<div class="summary-card"><strong>{claude_bold_average:.2f} → {gpt_bold_average:.2f}</strong><span>平均加粗数量</span></div>',
        ]
    )
    options = "".join(
        f'<option value="{html.escape(record["sample_id"])}">{html.escape(record["sample_id"])} · {html.escape(record["title"])}</option>'
        for record in records
    )
    sample_sections = []
    for record in records:
        sample_id = record["sample_id"]
        gpt = gpt_index[sample_id]
        claude = claude_index[sample_id]
        claude_article = _read_text(
            OUTPUT_DIR / "general_v4" / sample_id / "run-1.md"
        ).strip()
        gpt_article = _read_text(
            OUTPUT_DIR / "gpt_general_v5" / sample_id / "run-1.md"
        ).strip()

        def metric(label: str, value: str, ok: bool = True) -> str:
            state = "ok" if ok else "bad"
            return f'<span class="metric {state}">{html.escape(label)} {html.escape(value)}</span>'

        claude_metrics = "".join(
            [
                metric("字符", str(claude["article_chars"])),
                metric("加粗", str(claude["bold_span_count"])),
                metric("简体", "✓" if claude["simplified_chinese"] else "✕", claude["simplified_chinese"]),
                metric("H2", str(claude["h2_count"]), 2 <= claude["h2_count"] <= 4),
                metric("引用块", str(claude["blockquote_count"]), claude["blockquote_count"] <= 1),
            ]
        )
        density_ok = bool(gpt["substantive_paragraphs"]) and all(
            2 <= item["bold_span_count"] <= 4 for item in gpt["substantive_paragraphs"]
        )
        gpt_metrics = "".join(
            [
                metric("字符", str(gpt["article_chars"]), MIN_ARTICLE_CHARS <= gpt["article_chars"] <= MAX_ARTICLE_CHARS),
                metric("加粗", str(gpt["bold_span_count"]), 10 <= gpt["bold_span_count"] <= 18),
                metric("简体", "✓" if gpt["simplified_chinese"] else "✕", gpt["simplified_chinese"]),
                metric("段落密度", "✓" if density_ok else "✕", density_ok),
                metric("H2", str(gpt["h2_count"]), 2 <= gpt["h2_count"] <= 4),
                metric("引用块", str(gpt["blockquote_count"]), gpt["blockquote_count"] <= 1),
            ]
        )
        failures = "、".join(gpt["format_failures"]) or "无"
        sample_sections.append(
            f'''
            <section class="sample" id="{html.escape(sample_id)}" data-sample="{html.escape(sample_id)}">
              <header class="sample-header">
                <div><span class="sample-id">{html.escape(sample_id)}</span><h2>{html.escape(record['title'])}</h2></div>
                <div class="sample-links"><span>{html.escape(V4_TARGETS[sample_id])}</span><a href="samples/{html.escape(sample_id)}/transcript.original.txt">原 transcript ↗</a></div>
              </header>
              <div class="comparison-grid">
                <article class="model-card claude">
                  <div class="model-heading"><div><span class="model-kicker">现有结果</span><h3>Claude · v4</h3></div><a href="outputs/general_v4/{html.escape(sample_id)}/run-1.md">Markdown ↗</a></div>
                  <div class="metrics">{claude_metrics}</div>
                  <div class="article-body">{_article_markdown_to_html(claude_article)}</div>
                </article>
                <article class="model-card gpt">
                  <div class="model-heading"><div><span class="model-kicker">本轮原始输出</span><h3>GPT‑5.6 Sol · v5</h3></div><a href="outputs/gpt_general_v5/{html.escape(sample_id)}/run-1.md">Markdown ↗</a></div>
                  <div class="metrics">{gpt_metrics}</div>
                  <p class="failure-line"><strong>自动失败：</strong>{html.escape(failures)}</p>
                  <div class="article-body">{_article_markdown_to_html(gpt_article)}</div>
                </article>
              </div>
            </section>'''
        )

    report_html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Claude v4 vs GPT-5.6 Sol v5</title>
  <style>
    :root { --ink:#172033; --muted:#697386; --line:#dfe4ec; --paper:#f5f7fb; --card:#fff; --claude:#8b5cf6; --gpt:#0f9f75; --warn:#fff1c8; --bad:#b42318; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; color:var(--ink); background:var(--paper); font:15px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
    a { color:inherit; }
    .hero { padding:48px max(24px,calc((100vw - 1500px)/2)); color:#fff; background:linear-gradient(135deg,#111827,#1f3b55); }
    .hero h1 { max-width:1000px; margin:0 0 12px; font-size:clamp(30px,5vw,58px); line-height:1.08; }
    .hero p { max-width:980px; color:#d8e1ee; font-size:17px; }
    .warning { max-width:1500px; margin:22px auto 0; padding:16px 18px; color:#5d4300; background:var(--warn); border:1px solid #e7c35d; border-radius:14px; }
    .summary-grid { max-width:1500px; margin:22px auto; padding:0 20px; display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
    .summary-card { padding:18px; background:var(--card); border:1px solid var(--line); border-radius:14px; box-shadow:0 4px 18px #1720330a; }
    .summary-card strong { display:block; font-size:25px; }
    .summary-card span { color:var(--muted); }
    .toolbar { position:sticky; top:0; z-index:10; display:flex; gap:10px; align-items:center; max-width:1500px; margin:0 auto 24px; padding:12px 20px; background:#f5f7fbeF; backdrop-filter:blur(12px); }
    select,button,.toolbar a { min-height:40px; padding:8px 12px; border:1px solid var(--line); border-radius:9px; background:#fff; color:var(--ink); }
    select { flex:1; min-width:0; }
    button { cursor:pointer; }
    main { max-width:1500px; margin:auto; padding:0 20px 80px; }
    .sample { margin:0 0 42px; scroll-margin-top:74px; }
    .sample-header { display:flex; justify-content:space-between; gap:24px; align-items:end; padding:0 4px 12px; }
    .sample-header h2 { margin:4px 0 0; font-size:22px; line-height:1.25; }
    .sample-id,.model-kicker { color:var(--muted); font-weight:700; letter-spacing:.04em; }
    .sample-links { display:flex; gap:14px; align-items:center; color:var(--muted); text-align:right; }
    .comparison-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:start; }
    .model-card { min-width:0; background:var(--card); border:1px solid var(--line); border-top:5px solid; border-radius:16px; overflow:hidden; box-shadow:0 6px 24px #1720330d; }
    .model-card.claude { border-top-color:var(--claude); }
    .model-card.gpt { border-top-color:var(--gpt); }
    .model-heading { display:flex; justify-content:space-between; align-items:center; gap:14px; padding:18px 22px 10px; }
    .model-heading h3 { margin:2px 0 0; font-size:20px; }
    .metrics { display:flex; flex-wrap:wrap; gap:7px; padding:0 22px 14px; border-bottom:1px solid var(--line); }
    .metric { padding:3px 8px; border-radius:999px; background:#edf7f3; color:#126149; font-size:12px; font-weight:700; }
    .metric.bad { color:var(--bad); background:#fff0ee; }
    .failure-line { margin:0; padding:10px 22px; color:var(--muted); background:#fafbfc; border-bottom:1px solid var(--line); font-size:12px; overflow-wrap:anywhere; }
    .article-body { padding:8px 24px 28px; font-size:16px; }
    .article-body h3 { margin:18px 0 12px; font-size:25px; line-height:1.25; }
    .article-body h4 { margin:26px 0 8px; font-size:19px; }
    .article-body p { margin:12px 0; }
    .article-body strong { padding:0 .08em; color:#0b3f65; background:linear-gradient(transparent 62%,#bfe5ff 62%); }
    .gpt .article-body strong { color:#07533d; background:linear-gradient(transparent 62%,#b9efd8 62%); }
    blockquote { margin:18px 0; padding:12px 16px; border-left:4px solid #99a5b7; background:#f6f8fa; }
    code { padding:1px 5px; background:#eef1f5; border-radius:4px; }
    .hidden { display:none; }
    @media (max-width:900px) { .summary-grid { grid-template-columns:1fr 1fr; } .comparison-grid { grid-template-columns:1fr; } .sample-header { align-items:start; flex-direction:column; } .sample-links { text-align:left; flex-wrap:wrap; } }
    @media (max-width:520px) { .summary-grid { grid-template-columns:1fr; } .toolbar { flex-wrap:wrap; } .toolbar select { flex-basis:100%; } .article-body { padding-inline:18px; } }
    @media print { .toolbar { display:none; } .sample { break-before:page; } .model-card { box-shadow:none; } }
  </style>
</head>
<body>
""" + f"""
  <header class="hero">
    <h1>Claude v4 vs GPT‑5.6 Sol v5</h1>
    <p>同一组 12 篇 transcript 的完整文章对照。左侧是已有 Claude v4，右侧是本轮 GPT‑5.6 Sol 使用 v5 提示词生成的未经 OpenCC 处理的原始输出。</p>
  </header>
  <aside class="warning"><strong>比较限制：</strong>本轮同时改变了模型和提示词版本。它适合帮助你选择更喜欢的最终文章，不足以证明差异完全由模型造成。</aside>
  <section class="summary-grid">{summary_cards}</section>
  <nav class="toolbar">
    <select id="samplePicker"><option value="all">显示全部 12 组</option>{options}</select>
    <button type="button" id="showAll">全部展开</button>
    <a href="../../../experiments/summary-prompt-v1/prompts/general-v5.md">v5 提示词</a>
    <a href="../../../experiments/summary-prompt-v1/results-gpt-v5.md">检查结果</a>
  </nav>
  <main>{''.join(sample_sections)}</main>
  <script>
    const picker = document.getElementById('samplePicker');
    const samples = [...document.querySelectorAll('.sample')];
    function show(value) {{
      samples.forEach(section => section.classList.toggle('hidden', value !== 'all' && section.dataset.sample !== value));
      if (value !== 'all') document.getElementById(value).scrollIntoView();
    }}
    picker.addEventListener('change', () => show(picker.value));
    document.getElementById('showAll').addEventListener('click', () => {{ picker.value='all'; show('all'); }});
  </script>
</body>
</html>
"""
    (EXPERIMENT_DIR / "gpt-v5-vs-claude-v4.html").write_text(report_html, encoding="utf-8")
    _write_json(
        EXPERIMENT_DIR / "result-summary-gpt-v5.json",
        {
            "sample_count": len(records),
            "requested_model": GPT_V5_MODEL,
            "response_models": response_models,
            "prompt_sha256": expected_prompt_hash,
            "raw_output": True,
            "opencc_applied": False,
            "format_passed": format_pass_count,
            "simplified_chinese": simplified_count,
            "within_length": length_count,
            "heading_ok": heading_count,
            "blockquote_ok": blockquote_count,
            "timestamp_free": timestamp_count,
            "bold_10_18": bold_range_count,
            "paragraph_bold_density_2_4": paragraph_density_count,
            "bold_increase_over_claude_v4": bold_increase_count,
            "claude_v4_average_bold": round(claude_bold_average, 3),
            "gpt_v5_average_bold": round(gpt_bold_average, 3),
            "llm_judge_used": False,
            "user_decision_complete": False,
        },
    )
    print("Wrote results-gpt-v5.md and gpt-v5-vs-claude-v4.html")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Summary Prompt V1 experiment")
    parser.add_argument(
        "stage",
        choices=(
            "sample",
            "classify",
            "generate",
            "evaluate",
            "report",
            "generate-v2",
            "evaluate-v2",
            "report-v2",
            "generate-v3",
            "evaluate-v3",
            "report-v3",
            "generate-v4",
            "report-v4",
            "generate-gpt-v5",
            "report-gpt-v5",
        ),
    )
    parser.add_argument(
        "--allow-config-key",
        action="store_true",
        help="Confirm that the user explicitly authorized using the key stored in the model config.",
    )
    args = parser.parse_args()
    if args.stage in {"classify", "generate", "evaluate", "generate-v2", "evaluate-v2", "generate-v3", "evaluate-v3", "generate-v4", "generate-gpt-v5"} and not args.allow_config_key:
        raise ExperimentError(
            "Live model stages require --allow-config-key after explicit user authorization."
        )

    stages = {
        "sample": stage_sample,
        "classify": stage_classify,
        "generate": stage_generate,
        "evaluate": stage_evaluate,
        "report": stage_report,
        "generate-v2": stage_generate_v2,
        "evaluate-v2": stage_evaluate_v2,
        "report-v2": stage_report_v2,
        "generate-v3": stage_generate_v3,
        "evaluate-v3": stage_evaluate_v3,
        "report-v3": stage_report_v3,
        "generate-v4": stage_generate_v4,
        "report-v4": stage_report_v4,
        "generate-gpt-v5": stage_generate_gpt_v5,
        "report-gpt-v5": stage_report_gpt_v5,
    }
    stages[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
