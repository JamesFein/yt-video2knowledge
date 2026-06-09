from __future__ import annotations

import re
from dataclasses import dataclass


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]+\)")
_THEMATIC_BREAK_RE = re.compile(r"^([-*_])(?:\s*\1){2,}\s*$")


@dataclass(frozen=True)
class MarkdownBlock:
    heading_level: int
    heading_text: str
    heading_path: str
    markdown: str
    plain_text: str
    heading_ancestors: tuple[str, ...] = ()


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
            )
        ] if plain_text else []

    blocks: list[MarkdownBlock] = []
    for position, (start, level, text, path, ancestors) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body_markdown = "\n".join(lines[start + 1 : end]).strip()
        if not markdown_to_plain_text(body_markdown):
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
                    heading_ancestors=ancestors,
                )
            )
    return blocks


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
