"""Segmentation module: split SectionNode tree into L0 RawSegmentData (v0.5).

Key changes from v1.1:
- Uses RoleClassifier plugin (M1 default: unknown)
- Uses EntityExtractor plugin (M1 default: empty)
- No segment_type, command_name, heading_level fields
- section_path is JSON array of {title, level}
- structure_json provides richer structural metadata
- source_offsets_json records parser/block_index/line info
"""
from __future__ import annotations

from typing import Any

from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    RoleClassifier,
)
from knowledge_mining.mining.models import ContentBlock, DocumentProfile, RawSegmentData, SectionNode
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalized_hash,
    token_count,
)


def segment_document(
    doc_root: SectionNode,
    profile: DocumentProfile,
    *,
    role_classifier: RoleClassifier | None = None,
    entity_extractor: EntityExtractor | None = None,
) -> list[RawSegmentData]:
    """Split document section tree into raw segments."""
    classifier = role_classifier or DefaultRoleClassifier()
    extractor = entity_extractor or NoOpEntityExtractor()

    segments: list[RawSegmentData] = []
    _walk_sections(doc_root, profile.document_key, [], segments, classifier, extractor)
    return [
        RawSegmentData(
            document_key=s.document_key,
            segment_index=idx,
            block_type=s.block_type,
            semantic_role=s.semantic_role,
            section_path=s.section_path,
            section_title=s.section_title,
            raw_text=s.raw_text,
            normalized_text=s.normalized_text,
            content_hash=s.content_hash,
            normalized_hash=s.normalized_hash,
            token_count=s.token_count,
            structure_json=s.structure_json,
            source_offsets_json=s.source_offsets_json,
            entity_refs_json=s.entity_refs_json,
            metadata_json=s.metadata_json,
        )
        for idx, s in enumerate(segments)
    ]


def _walk_sections(
    node: SectionNode,
    document_key: str,
    parent_path: list[dict[str, Any]],
    segments: list[RawSegmentData],
    classifier: RoleClassifier,
    extractor: EntityExtractor,
) -> None:
    """Recursively walk section tree, creating segments."""
    current_path = list(parent_path)
    if node.title:
        current_path.append({"title": node.title, "level": node.level})

    context: dict[str, Any] = {"section_path": current_path}
    current_group: list[ContentBlock] = []
    block_index = 0

    for block in node.blocks:
        if block.block_type in ("table", "html_table", "code"):
            # Flush pending grouped blocks
            if current_group:
                segments.append(
                    _make_segment(
                        document_key, current_path, node, current_group,
                        block_index, classifier, extractor, context,
                    )
                )
                block_index += 1
                current_group = []
            segments.append(
                _make_segment(
                    document_key, current_path, node, [block],
                    block_index, classifier, extractor, context,
                )
            )
            block_index += 1
        else:
            current_group.append(block)

    if current_group:
        segments.append(
            _make_segment(
                document_key, current_path, node, current_group,
                block_index, classifier, extractor, context,
            )
        )

    for child in node.children:
        _walk_sections(child, document_key, current_path, segments, classifier, extractor)


def _make_segment(
    document_key: str,
    section_path: list[dict[str, Any]],
    section: SectionNode,
    blocks: list[ContentBlock],
    block_index: int,
    classifier: RoleClassifier,
    extractor: EntityExtractor,
    context: dict[str, Any],
) -> RawSegmentData:
    """Create a RawSegmentData from a group of content blocks."""
    primary_block = blocks[0] if blocks else None
    block_type = primary_block.block_type if primary_block else "unknown"

    raw_text = "\n\n".join(b.text for b in blocks)
    norm_text = raw_text.lower().strip()

    semantic_role = classifier.classify(
        raw_text, section.title, block_type, context,
    )

    entity_refs = extractor.extract(raw_text, context)

    return RawSegmentData(
        document_key=document_key,
        segment_index=0,
        block_type=block_type,
        semantic_role=semantic_role,
        section_path=section_path,
        section_title=section.title,
        raw_text=raw_text,
        normalized_text=norm_text,
        content_hash=content_hash(raw_text),
        normalized_hash=normalized_hash(raw_text),
        token_count=token_count(raw_text),
        structure_json=_extract_structure_info(blocks),
        source_offsets_json={
            "block_index": block_index,
            "section_title": section.title,
        },
        entity_refs_json=entity_refs,
        metadata_json={},
    )


def _extract_structure_info(blocks: list[ContentBlock]) -> dict:
    """Extract structural metadata from blocks."""
    info: dict = {}
    for block in blocks:
        if block.block_type == "table":
            parts = block.text.split(" | ")
            info["col_count"] = len(parts)
            info["row_count"] = max(1, len(parts) // max(len(parts), 1))
        elif block.block_type == "html_table":
            info["raw_html_preserved"] = True
            info["row_count"] = max(1, block.text.lower().count("<tr"))
            info["col_count"] = max(1, block.text.lower().count("<td") // max(1, block.text.lower().count("<tr")))
        elif block.block_type == "code":
            if block.language:
                info["language"] = block.language
        elif block.block_type == "list":
            items = block.text.split("; ")
            info["ordered"] = False
            info["items"] = items
            info["item_count"] = len(items)
        elif block.block_type == "paragraph":
            info["paragraph_count"] = info.get("paragraph_count", 0) + 1
    return info
