"""Markdown -> retrievable chunks.

Splitting on headings (rather than every N characters) keeps each chunk a
coherent unit of prose and gives it a heading path, which is what lets a hit be
cited precisely and re-embedded with its context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)(.*)$")
FRONTMATTER_DELIM = "---"

#: Chunks below this many characters are merged into their neighbour: a bare
#: heading with one line under it is not independently retrievable.
MIN_CHARS = 200
#: Soft ceiling. Sections above it are split on paragraph boundaries so no chunk
#: dominates the ranking or overflows the embedder's context.
MAX_CHARS = 2000
#: Hard ceiling, enforced even when there is no paragraph break to split on.
#: Embedders reject inputs past their context window, and the char-to-token
#: ratio swings wildly (a mermaid diagram tokenises far denser than prose), so
#: this is set well below any observed limit rather than tuned to one.
HARD_MAX_CHARS = 4000


@dataclass
class Section:
    heading_path: list[str]
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from the body.

    Only flat `key: value` pairs are read -- that is all Docusaurus frontmatter
    uses here, and it avoids a YAML dependency.
    """
    if not text.startswith(FRONTMATTER_DELIM):
        return {}, text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == FRONTMATTER_DELIM:
            meta: dict[str, str] = {}
            for line in lines[1:i]:
                key, sep, value = line.partition(":")
                if sep and not key.startswith((" ", "#", "-")):
                    meta[key.strip()] = value.strip().strip("\"'")
            return meta, "\n".join(lines[i + 1 :])
    return {}, text


def _strip_fenced(lines: list[str]) -> list[bool]:
    """Mark which lines sit inside a fenced code block.

    A `#` at the start of a shell snippet is a comment, not a heading; without
    this the document would be shredded at every commented line.
    """
    inside = [False] * len(lines)
    fence: str | None = None
    for i, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(2)
            if fence is None:
                fence = marker[:3]
                inside[i] = True
                continue
            if marker.startswith(fence):
                inside[i] = True
                fence = None
                continue
        inside[i] = fence is not None
    return inside


def split_sections(body: str) -> list[Section]:
    """Group lines under their heading trail."""
    lines = body.split("\n")
    fenced = _strip_fenced(lines)
    sections: list[Section] = []
    trail: list[str] = []
    current = Section(heading_path=[], lines=[])

    for line, in_code in zip(lines, fenced):
        match = None if in_code else HEADING_RE.match(line)
        if match:
            if current.text:
                sections.append(current)
            level = len(match.group(1))
            title = match.group(2).strip()
            trail = trail[: level - 1]
            while len(trail) < level - 1:
                trail.append("")
            trail.append(title)
            current = Section(heading_path=[t for t in trail if t], lines=[])
        else:
            current.lines.append(line)

    if current.text:
        sections.append(current)
    return sections


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Break an oversized section on blank lines, never mid-paragraph."""
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) > limit and buffer:
            parts.append(buffer)
            buffer = paragraph
        else:
            buffer = candidate
    if buffer:
        parts.append(buffer)
    return _enforce_hard_limit(parts or [text])


def _enforce_hard_limit(parts: list[str]) -> list[str]:
    """Break anything still above `HARD_MAX_CHARS`.

    Applies to the cases paragraph splitting cannot help with: a huge table, a
    long fenced block, a generated diagram. Falls back to line boundaries, then
    to a blunt character cut, so the function always terminates.
    """
    result: list[str] = []
    for part in parts:
        if len(part) <= HARD_MAX_CHARS:
            result.append(part)
            continue
        buffer = ""
        for line in part.split("\n"):
            while len(line) > HARD_MAX_CHARS:
                if buffer:
                    result.append(buffer)
                    buffer = ""
                result.append(line[:HARD_MAX_CHARS])
                line = line[HARD_MAX_CHARS:]
            candidate = f"{buffer}\n{line}" if buffer else line
            if len(candidate) > HARD_MAX_CHARS:
                result.append(buffer)
                buffer = line
            else:
                buffer = candidate
        if buffer.strip():
            result.append(buffer)
    return result


def chunk_markdown(body: str) -> list[tuple[str, str]]:
    """Return `(heading_path, text)` pairs ready to be embedded."""
    chunks: list[tuple[str, str]] = []
    pending: tuple[str, str] | None = None

    for section in split_sections(body):
        heading_path = " > ".join(section.heading_path)
        for part in _split_long(section.text):
            if pending is not None:
                prev_path, prev_text = pending
                merged = f"{prev_text}\n\n{part}".strip()
                # Merge the runt forward, keeping the earlier heading path so the
                # combined chunk is still attributable -- but never past the hard
                # ceiling, which the split above just finished enforcing.
                if len(prev_text) < MIN_CHARS and len(merged) <= HARD_MAX_CHARS:
                    pending = (prev_path, merged)
                    continue
                chunks.append(pending)
            pending = (heading_path, part)

    if pending is not None:
        prev_path, prev_text = pending
        merged = (
            f"{chunks[-1][1]}\n\n{prev_text}".strip() if chunks else prev_text
        )
        if len(prev_text) < MIN_CHARS and chunks and len(merged) <= HARD_MAX_CHARS:
            chunks[-1] = (chunks[-1][0], merged)
        else:
            chunks.append(pending)
    return chunks
