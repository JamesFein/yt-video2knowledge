#!/usr/bin/env python3
"""Run the repository-local summary prompt experiment.

This script is intentionally scoped to this experiment. It does not import or
modify the production digest workflow and never writes beneath data/runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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


ROOT = Path(__file__).resolve().parents[2]
TRACKED_DIR = ROOT / "experiments" / "summary-prompt-v1"
PROMPT_DIR = TRACKED_DIR / "prompts"
EXPERIMENT_DIR = ROOT / "data" / "experiments" / "summary-prompt-v1"
SAMPLE_DIR = EXPERIMENT_DIR / "samples"
ROBUSTNESS_DIR = EXPERIMENT_DIR / "robustness"
OUTPUT_DIR = EXPERIMENT_DIR / "outputs"
EVALUATION_DIR = EXPERIMENT_DIR / "evaluations"
RUNS_DIR = ROOT / "data" / "runs"
MODEL_CONFIG_PATH = ROOT / "新的文字简写模型.txt"
DATABASE_PATH = ROOT / "data" / "knowledge.sqlite3"

SEED = 20260802
SAMPLE_SIZE = 60
CORE_PER_CATEGORY = 6
MAX_DIRECT_CHARS = 120_000
MIN_ARTICLE_CHARS = 600
MAX_ARTICLE_CHARS = 1_500
MODEL_TEMPERATURE = 0.2
MODEL_MAX_TOKENS = 4096

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

CONFIG_RE = re.compile(
    r"模型[：:]\s*(?P<model>\S+)\s+密钥[：:]\s*(?P<key>\S+)\s+Base\s+URL\s*(?P<base>https?://\S+)",
    re.IGNORECASE,
)
TIMESTAMP_PREFIX_RE = re.compile(r"^\s*\[\d{1,3}:\d{2}(?::\d{2})?]\s*")
TIMESTAMP_NEAR_RE = re.compile(r"[（(\[]\d{1,3}:\d{2}(?::\d{2})?[）)\]]")
H1_RE = re.compile(r"^#\s+\S", re.MULTILINE)
H2_RE = re.compile(r"^##\s+\S", re.MULTILINE)
QUOTE_RE = re.compile(r"“([^”\n]{8,100})”|「([^」\n]{8,100})」|『([^』\n]{8,100})』|\"([^\"\n]{8,100})\"")


class ExperimentError(RuntimeError):
    pass


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


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
    system = _read_text(PROMPT_DIR / "classifier.md")
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
        return _read_text(PROMPT_DIR / "current-production.md").strip()
    base = _read_text(PROMPT_DIR / "general-v1.md").strip()
    if variant == "general":
        return base
    if variant == "general_v2":
        return _read_text(PROMPT_DIR / "general-v2.md").strip()
    if variant == "general_v3":
        return _read_text(PROMPT_DIR / "general-v3.md").strip()
    if variant == "category":
        delta = _read_text(PROMPT_DIR / "categories" / f"{category}-v1.md").strip()
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


def _normalized_quote(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z_\u3400-\u9fff]", "", text).lower()


def _automatic_checks(record: dict[str, Any], variant: str, run_number: int = 1) -> dict[str, Any]:
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
        traceable = bool(normalized) and normalized in transcript_normalized
        nearby = article[max(0, match.start() - 40) : min(len(article), match.end() + 40)]
        timestamped = bool(TIMESTAMP_NEAR_RE.search(nearby))
        quote_results.append({"quote": quote, "traceable": traceable, "timestamped": timestamped})
        if not traceable:
            failures.append("untraceable_direct_quote")
        if not timestamped:
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
    response = _call_model(_read_text(TRACKED_DIR / "rubric.md"), user)
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
    system = (
        "比较同一 transcript 在同一提示词下生成的两篇文章。只依据 transcript 判断两篇是否忠实，"
        "以及它们是否选择了实质相同的核心认识。只输出 JSON："
        '{"run_a_faithful":true,"run_b_faithful":true,"same_core_insight":true,"reason":"..."}'
    )
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
        ),
    )
    parser.add_argument(
        "--allow-config-key",
        action="store_true",
        help="Confirm that the user explicitly authorized using the key stored in the model config.",
    )
    args = parser.parse_args()
    if args.stage in {"classify", "generate", "evaluate", "generate-v2", "evaluate-v2", "generate-v3", "evaluate-v3"} and not args.allow_config_key:
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
    }
    stages[args.stage]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
