"""Document parser interface and factory for v0.5.

Dispatches parsing by file_type:
- markdown → MarkdownParser (structural chunking via markdown-it-py)
- txt → PlainTextParser (token-based chunking, GraphRAG-style)
- html/pdf/doc/docx → PassthroughParser (no segments, only raw_document registration)
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import ContentBlock, SectionNode

# Re-export structure parser for MarkdownParser
from knowledge_mining.mining.structure import parse_structure as _parse_md_structure


@runtime_checkable
class DocumentParser(Protocol):
    """Parse document content into structured sections or raw segments."""

    def parse(
        self, content: str, file_name: str, context: dict[str, Any],
    ) -> SectionNode | None:
        """Return a SectionNode tree for structured documents, or None for passthrough."""
        ...


class MarkdownParser:
    """Structural parser for Markdown using markdown-it-py."""

    def parse(
        self, content: str, file_name: str, context: dict[str, Any],
    ) -> SectionNode | None:
        if not content.strip():
            return None
        return _parse_md_structure(content)


class PlainTextParser:
    """Paragraph-based chunking for plain text.

    Splits text by blank lines into paragraphs. Paragraphs exceeding
    chunk_size tokens are split at token boundaries while preserving
    original text (no reconstruction from tokens).
    """

    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 30):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse(
        self, content: str, file_name: str, context: dict[str, Any],
    ) -> SectionNode | None:
        if not content.strip():
            return None

        paragraphs = _split_paragraphs(content)
        if not paragraphs:
            return None

        blocks: list[ContentBlock] = []
        for para_text in paragraphs:
            tc = _count_tokens(para_text)
            if tc <= self.chunk_size:
                blocks.append(ContentBlock(block_type="paragraph", text=para_text))
            else:
                # Split long paragraph by token-boundary windows on original text
                chunks = _split_long_text(para_text, self.chunk_size, self.chunk_overlap)
                for chunk in chunks:
                    blocks.append(ContentBlock(block_type="paragraph", text=chunk))

        return SectionNode(
            title=file_name,
            level=0,
            blocks=tuple(blocks),
        )


class PassthroughParser:
    """Parser for non-parsable file types (html/pdf/doc/docx).

    Returns None — no raw_segments are generated.
    """

    def parse(
        self, content: str, file_name: str, context: dict[str, Any],
    ) -> SectionNode | None:
        return None


def create_parser(file_type: str, **kwargs: Any) -> DocumentParser:
    """Factory: return appropriate parser for the given file_type."""
    if file_type == "markdown":
        return MarkdownParser()
    elif file_type == "txt":
        return PlainTextParser(
            chunk_size=kwargs.get("chunk_size", 300),
            chunk_overlap=kwargs.get("chunk_overlap", 30),
        )
    else:
        return PassthroughParser()


def _split_paragraphs(text: str) -> list[str]:
    """Split text by blank lines into paragraphs, preserving original text."""
    paragraphs = []
    current_lines: list[str] = []
    for line in text.split("\n"):
        if line.strip() == "":
            if current_lines:
                paragraphs.append("\n".join(current_lines))
                current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        paragraphs.append("\n".join(current_lines))
    return paragraphs


def _count_tokens(text: str) -> int:
    """Count tokens (CJK-aware). CJK chars count individually."""
    count = 0
    buf = False
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                count += 1
                buf = False
            count += 1
        elif ch.isalnum():
            buf = True
        else:
            if buf:
                count += 1
                buf = False
    if buf:
        count += 1
    return count


def _find_token_boundaries(text: str) -> list[int]:
    """Find character positions of token boundaries in text.

    Returns a list of character offsets where each token starts.
    Used for chunking while preserving original text.
    """
    boundaries = [0]  # Start of text is always a boundary
    i = 0
    in_token = False
    while i < len(text):
        ch = text[i]
        if "\u4e00" <= ch <= "\u9fff":
            if in_token:
                in_token = False
            boundaries.append(i)
            i += 1
            if i < len(text):
                boundaries.append(i)
        elif ch.isalnum():
            if not in_token:
                boundaries.append(i)
                in_token = True
            i += 1
        else:
            if in_token:
                in_token = False
            i += 1
    # Remove duplicates and sort
    return sorted(set(boundaries))


def _split_long_text(
    text: str, chunk_size: int, chunk_overlap: int,
) -> list[str]:
    """Split long text into chunks based on token boundaries.

    Preserves original text — does not reconstruct from tokens.
    """
    boundaries = _find_token_boundaries(text)
    total_tokens = len(boundaries)

    if total_tokens <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < total_tokens:
        end = min(start + chunk_size, total_tokens)
        char_start = boundaries[start]
        char_end = boundaries[end] if end < total_tokens else len(text)
        chunk = text[char_start:char_end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= total_tokens:
            break
        step = chunk_size - chunk_overlap
        start += step

    return chunks
