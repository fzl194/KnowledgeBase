"""Pipeline data objects for M1 Knowledge Mining."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawDocumentData:
    """Output of ingestion: raw document content + metadata."""

    file_path: str
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    manifest_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentProfile:
    """Document classification: source_type, document_type, scope, tags."""

    file_path: str
    source_type: str = "other"
    document_type: str | None = None
    scope_json: dict[str, Any] = field(default_factory=dict)
    tags_json: list[str] = field(default_factory=list)
    product: str | None = None
    product_version: str | None = None
    network_element: str | None = None
    structure_quality: str = "unknown"


@dataclass(frozen=True)
class ContentBlock:
    """A parsed content block from the structure parser."""

    block_type: str  # heading, paragraph, list, table, html_table, code, blockquote, raw_html, unknown
    text: str
    language: str | None = None
    level: int | None = None  # heading level


@dataclass(frozen=True)
class SectionNode:
    """A section in the document tree."""

    title: str | None
    level: int
    children: tuple[SectionNode, ...] = ()
    blocks: tuple[ContentBlock, ...] = ()


@dataclass(frozen=True)
class RawSegmentData:
    """L0 segment output from segmentation."""

    document_file_path: str
    segment_index: int
    section_path: list[str]
    section_title: str | None
    heading_level: int | None
    segment_type: str  # command, parameter, example, note, table, paragraph, concept, other
    block_type: str = "unknown"
    section_role: str | None = None
    raw_text: str = ""
    normalized_text: str = ""
    content_hash: str = ""
    normalized_hash: str = ""
    token_count: int | None = None
    command_name: str | None = None
    structure_json: dict[str, Any] = field(default_factory=dict)
    source_offsets_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalSegmentData:
    """L1 canonical segment after dedup."""

    canonical_key: str
    segment_type: str
    title: str | None
    canonical_text: str
    search_text: str
    has_variants: bool
    variant_policy: str
    command_name: str | None
    raw_segment_refs: list[str]
    section_role: str | None = None


@dataclass(frozen=True)
class SourceMappingData:
    """L2 source mapping: canonical → raw segments."""

    canonical_key: str
    raw_segment_ref: str
    relation_type: str  # primary, exact_duplicate, near_duplicate, version_variant, product_variant, ne_variant
