"""Markdown -> retrievable chunks.

Splitting on headings (rather than every N characters) keeps each chunk a
coherent unit of prose and gives it a heading path, which is what lets a hit be
cited precisely and re-embedded with its context.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
# Any indentation is accepted on purpose. Markdown caps a top-level fence at
# three spaces, but the docs nest fences deeper inside list items and MDX
# components (`<TabItem>`), where they are just as real. Telling those apart
# takes a full Markdown parser; treating a four-space-indented sample as a
# fence costs nothing next to missing a nested one.
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


def _fence_openers(lines: list[str]) -> list[int | None]:
    """For each line, the index of the line that opened its fenced code block.

    None outside a block; the delimiters themselves count as inside. A `#` at
    the start of a shell snippet is a comment, not a heading, and a blank line
    in a code sample is not a paragraph break; without this the document would
    be shredded at both.

    A block is closed only by a fence of the same character, at least as long
    as the one that opened it and with nothing after it. That is what lets a
    four-backtick block show a three-backtick one, or a sample quote a line
    like "```php", without ending early.
    """
    openers: list[int | None] = [None] * len(lines)
    fence: str | None = None
    opener: int | None = None
    for i, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(2)
            if fence is None:
                fence, opener = marker, i
            elif (
                marker[0] == fence[0]
                and len(marker) >= len(fence)
                and not match.group(3).strip()
            ):
                openers[i] = opener
                fence = opener = None
                continue
        openers[i] = opener
    return openers


def split_sections(body: str) -> list[Section]:
    """Group lines under their heading trail."""
    lines = body.split("\n")
    openers = _fence_openers(lines)
    sections: list[Section] = []
    trail: list[str] = []
    current = Section(heading_path=[], lines=[])

    for line, opener in zip(lines, openers):
        match = None if opener is not None else HEADING_RE.match(line)
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


def _paragraphs(text: str) -> list[str]:
    """Split on blank lines, keeping a fenced code block in one piece."""
    lines = text.split("\n")
    paragraphs: list[str] = []
    current: list[str] = []
    for line, opener in zip(lines, _fence_openers(lines)):
        if opener is None and not line.strip():
            if current:
                paragraphs.append("\n".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def _split_long(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Break an oversized section on blank lines, never mid-paragraph."""
    paragraphs = _paragraphs(text)
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

    A cut inside a fenced block closes the fence and reopens it in the next
    chunk, so each half still reads as code in its original language.
    """
    result: list[str] = []
    for part in parts:
        if len(part) <= HARD_MAX_CHARS:
            result.append(part)
            continue
        lines = part.split("\n")
        openers = _fence_openers(lines)
        # Room kept free for the fence line a cut adds to each side of it.
        reserve = max((len(lines[o]) + 1 for o in openers if o is not None), default=0)
        if reserve * 2 >= HARD_MAX_CHARS:
            openers, reserve = [None] * len(lines), 0
        limit = HARD_MAX_CHARS - reserve
        width = limit - reserve
        pieces = [
            (line[start : start + width], opener)
            for line, opener in zip(lines, openers)
            for start in range(0, max(len(line), 1), width)
        ]

        buffer = ""
        previous: int | None = None
        for text, opener in pieces:
            candidate = f"{buffer}\n{text}" if buffer else text
            if len(candidate) <= limit:
                buffer = candidate
            elif opener is not None and opener == previous:
                fence = FENCE_RE.match(lines[opener])
                result.append(f"{buffer}\n{fence.group(1)}{fence.group(2)}")
                buffer = f"{lines[opener]}\n{text}"
            else:
                result.append(buffer)
                buffer = text
            previous = opener
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
