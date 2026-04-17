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
    """Token-based chunking for plain text (GraphRAG-style).

    Splits text into chunks of `chunk_size` tokens with `chunk_overlap` tokens overlap.
    Each chunk becomes a paragraph block.
    """

    def __init__(self, chunk_size: int = 300, chunk_overlap: int = 30):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse(
        self, content: str, file_name: str, context: dict[str, Any],
    ) -> SectionNode | None:
        if not content.strip():
            return None

        tokens = _simple_tokenize(content)
        if not tokens:
            return None

        chunks = _chunk_tokens(tokens, self.chunk_size, self.chunk_overlap)
        blocks = tuple(
            ContentBlock(block_type="paragraph", text=chunk)
            for chunk in chunks
        )
        return SectionNode(
            title=file_name,
            level=0,
            blocks=blocks,
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


def _simple_tokenize(text: str) -> list[str]:
    """Simple tokenizer: split on whitespace, CJK chars individually."""
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        elif ch.isalnum():
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            # Keep whitespace-only tokens for reconstruction
            if ch in (" ", "\n", "\t"):
                tokens.append(ch)
    if buf:
        tokens.append(buf)
    return tokens


def _chunk_tokens(
    tokens: list[str], chunk_size: int, chunk_overlap: int,
) -> list[str]:
    """Split token list into chunks with overlap, rejoining as strings."""
    # First, filter to only meaningful tokens for counting
    word_tokens = [t for t in tokens if t.strip()]

    if not word_tokens:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(word_tokens):
        end = min(start + chunk_size, len(word_tokens))
        chunk = " ".join(word_tokens[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - chunk_overlap
        if start >= len(word_tokens):
            break

    return chunks
