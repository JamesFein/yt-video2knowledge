from __future__ import annotations

import re
from dataclasses import dataclass, field


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]+\)")
_THEMATIC_BREAK_RE = re.compile(r"^([-*_])(?:\s*\1){2,}\s*$")
_LIST_ITEM_RE = re.compile(r"^(\s*)(?:([-*+])|(\d+)\.)\s+(.*)$")
_INLINE_STRONG_RE = re.compile(r"\*\*[^*]+\*\*|__[^_]+__")


@dataclass(frozen=True)
class TextRun:
    text: str
    strong: bool = False


@dataclass(frozen=True)
class ListItem:
    runs: tuple[TextRun, ...]
    level: int = 0


@dataclass(frozen=True)
class BodySegment:
    kind: str  # "paragraph" | "subhead" | "blockquote" | "list"
    runs: tuple[TextRun, ...] = ()
    items: tuple[ListItem, ...] = ()
    ordered: bool = False


@dataclass(frozen=True)
class MarkdownBlock:
    heading_level: int
    heading_text: str
    heading_path: str
    markdown: str
    plain_text: str
    body_plain_text: str
    heading_ancestors: tuple[str, ...] = ()
    body_segments: tuple[BodySegment, ...] = field(default=())


def split_markdown_blocks(markdown: str) -> list[MarkdownBlock]:
    lines = markdown.splitlines()
    headings: list[tuple[int, int, str, str, tuple[str, ...]]] = []
    path_by_level: dict[int, str] = {}

    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if level > 3:
            continue
        text = match.group(2).strip()
        path_by_level[level] = text
        for stale_level in [value for value in path_by_level if value > level]:
            del path_by_level[stale_level]
        path_parts = [path_by_level[key] for key in sorted(path_by_level)]
        path = " / ".join(path_parts)
        headings.append((index, level, text, path, tuple(path_parts[:-1])))

    if not headings:
        plain_text = markdown_to_plain_text(markdown)
        return [
            MarkdownBlock(
                heading_level=0,
                heading_text="Summary",
                heading_path="Summary",
                markdown=markdown.strip(),
                plain_text=plain_text,
                body_plain_text=plain_text,
            )
        ] if plain_text else []

    blocks: list[MarkdownBlock] = []
    for position, (start, level, text, path, ancestors) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body_markdown = "\n".join(lines[start + 1 : end]).strip()
        body_plain_text = markdown_to_plain_text(body_markdown)
        if not body_plain_text:
            continue
        block_markdown = "\n".join(lines[start:end]).strip()
        plain_text = markdown_to_plain_text(block_markdown)
        if plain_text:
            blocks.append(
                MarkdownBlock(
                    heading_level=level,
                    heading_text=text,
                    heading_path=path,
                    markdown=block_markdown,
                    plain_text=plain_text,
                    body_plain_text=body_plain_text,
                    heading_ancestors=ancestors,
                    body_segments=parse_body_segments(body_markdown),
                )
            )
    return blocks


def _inline_runs(text: str) -> tuple[TextRun, ...]:
    text = _LINK_RE.sub(r"\1", text)
    text = text.replace("`", "")
    runs: list[TextRun] = []
    last = 0
    for match in _INLINE_STRONG_RE.finditer(text):
        if match.start() > last:
            runs.append(TextRun(text[last : match.start()]))
        inner = match.group(0)[2:-2]
        if inner:
            runs.append(TextRun(inner, strong=True))
        last = match.end()
    if last < len(text):
        runs.append(TextRun(text[last:]))
    return tuple(run for run in runs if run.text) or (TextRun(""),)


def parse_body_segments(body_markdown: str) -> tuple[BodySegment, ...]:
    segments: list[BodySegment] = []
    paragraph: list[str] = []
    quote: list[str] = []
    items: list[ListItem] = []
    list_ordered = False
    in_code_block = False

    def flush_paragraph() -> None:
        if paragraph:
            segments.append(BodySegment("paragraph", runs=_inline_runs(" ".join(paragraph))))
            paragraph.clear()

    def flush_quote() -> None:
        if quote:
            segments.append(BodySegment("blockquote", runs=_inline_runs(" ".join(quote))))
            quote.clear()

    def flush_list() -> None:
        nonlocal items, list_ordered
        if items:
            segments.append(BodySegment("list", items=tuple(items), ordered=list_ordered))
            items = []
            list_ordered = False

    def flush_all() -> None:
        flush_paragraph()
        flush_quote()
        flush_list()

    for raw_line in body_markdown.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            paragraph.append(stripped)
            continue
        if not stripped or _THEMATIC_BREAK_RE.match(stripped):
            flush_all()
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            flush_all()
            segments.append(BodySegment("subhead", runs=_inline_runs(heading.group(2).strip())))
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quote.append(stripped.lstrip(">").strip())
            continue

        list_match = _LIST_ITEM_RE.match(raw_line)
        if list_match:
            flush_paragraph()
            flush_quote()
            indent, bullet, _, content = list_match.group(1), list_match.group(2), list_match.group(3), list_match.group(4)
            ordered = bullet is None
            if items and ordered != list_ordered:
                flush_list()
            list_ordered = ordered
            level = len(indent.replace("\t", "  ")) // 2
            items.append(ListItem(runs=_inline_runs(content.strip()), level=min(level, 2)))
            continue

        flush_quote()
        flush_list()
        paragraph.append(stripped)

    flush_all()
    return tuple(segments)


def markdown_to_plain_text(markdown: str) -> str:
    output: list[str] = []
    in_code_block = False

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if not in_code_block and _THEMATIC_BREAK_RE.match(stripped):
            continue
        if not stripped:
            if output and output[-1] != "":
                output.append("")
            continue
        if not in_code_block:
            stripped = re.sub(r"^#{1,6}\s+", "", stripped)
            stripped = re.sub(r"^[-*+]\s+", "", stripped)
            stripped = re.sub(r"^\d+\.\s+", "", stripped)
            stripped = _LINK_RE.sub(r"\1", stripped)
            stripped = stripped.replace("**", "").replace("__", "")
            stripped = stripped.replace("`", "")
        output.append(stripped)

    return "\n".join(output).strip()
