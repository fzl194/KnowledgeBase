"""Test canonicalization: three-layer dedup with v0.5 fields, singleton canonical, primary source uniqueness."""
from __future__ import annotations

from knowledge_mining.mining.canonicalization import canonicalize
from knowledge_mining.mining.models import (
    CanonicalSegmentData,
    DocumentProfile,
    RawSegmentData,
    SourceMappingData,
)
from knowledge_mining.mining.text_utils import (
    content_hash,
    normalized_hash,
    token_count,
)


def _make_seg(
    doc_key: str, idx: int, raw_text: str, **kwargs,
) -> RawSegmentData:
    return RawSegmentData(
        document_key=doc_key,
        segment_index=idx,
        block_type=kwargs.get("block_type", "paragraph"),
        semantic_role=kwargs.get("semantic_role", "unknown"),
        section_path=kwargs.get("section_path", [{"title": "Root", "level": 1}]),
        section_title=kwargs.get("section_title", "Root"),
        raw_text=raw_text,
        normalized_text=raw_text.lower().strip(),
        content_hash=content_hash(raw_text),
        normalized_hash=normalized_hash(raw_text),
        token_count=token_count(raw_text),
    )


def _make_profile(doc_key: str, **kwargs) -> DocumentProfile:
    return DocumentProfile(
        document_key=doc_key,
        source_type=kwargs.get("source_type", "other"),
        document_type=kwargs.get("document_type"),
        scope_json=kwargs.get("scope_json", {}),
        tags_json=kwargs.get("tags_json", []),
        structure_quality=kwargs.get("structure_quality", "unknown"),
        title=kwargs.get("title"),
    )


class TestCanonicalizationEmpty:
    def test_empty_input(self):
        canonicals, mappings = canonicalize([], {})
        assert canonicals == []
        assert mappings == []


class TestSingletonCanonical:
    def test_single_segment_creates_primary(self):
        segs = [_make_seg("a.md", 0, "Hello world")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        assert len(mappings) == 1
        assert mappings[0].relation_type == "primary"
        assert mappings[0].is_primary is True

    def test_singleton_has_raw_segment_ref(self):
        segs = [_make_seg("a.md", 0, "Hello")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, _ = canonicalize(segs, profiles)
        assert "a.md#0" in canonicals[0].raw_segment_refs


class TestExactDuplicate:
    def test_exact_duplicates_merged(self):
        text = "Identical content"
        segs = [
            _make_seg("a.md", 0, text),
            _make_seg("b.md", 0, text),
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        assert len(mappings) == 2
        rel_types = [m.relation_type for m in mappings]
        assert "primary" in rel_types
        assert "exact_duplicate" in rel_types

    def test_three_exact_duplicates(self):
        text = "Same text everywhere"
        segs = [
            _make_seg("a.md", 0, text),
            _make_seg("b.md", 0, text),
            _make_seg("c.md", 0, text),
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
            "c.md": _make_profile("c.md"),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        assert len(mappings) == 3


class TestNormalizedDuplicate:
    def test_normalized_layer_in_same_exact_group(self):
        """Within an exact-hash group, non-primary segments get relation_type
        based on normalized_hash comparison. If content_hash matches AND
        normalized_hash matches, relation is 'exact_duplicate'."""
        text = "Same content"
        segs = [
            _make_seg("a.md", 0, text),
            _make_seg("b.md", 0, text),
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        rel_types = [m.relation_type for m in mappings]
        assert "primary" in rel_types
        assert "exact_duplicate" in rel_types


class TestNoDuplicate:
    def test_independent_segments(self):
        segs = [
            _make_seg("a.md", 0, "Content A is about apples"),
            _make_seg("b.md", 0, "Content B is about oranges and bananas"),
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 2
        # Each has exactly one primary
        for m in mappings:
            assert m.relation_type == "primary"


class TestScopeVariant:
    def test_scope_variant_detected(self):
        text = "Same content different scopes"
        segs = [
            _make_seg("a.md", 0, text),
            _make_seg("b.md", 0, text),
        ]
        profiles = {
            "a.md": _make_profile("a.md", scope_json={"product": "UDG5000"}),
            "b.md": _make_profile("b.md", scope_json={"product": "UDG6000"}),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        assert canonicals[0].has_variants is True
        assert canonicals[0].variant_policy == "require_scope"
        rel_types = [m.relation_type for m in mappings]
        assert "scope_variant" in rel_types

    def test_no_scope_variant_same_scope(self):
        text = "Same content same scope"
        segs = [
            _make_seg("a.md", 0, text),
            _make_seg("b.md", 0, text),
        ]
        profiles = {
            "a.md": _make_profile("a.md", scope_json={"product": "UDG"}),
            "b.md": _make_profile("b.md", scope_json={"product": "UDG"}),
        }
        canonicals, mappings = canonicalize(segs, profiles)
        assert len(canonicals) == 1
        # Same scope → exact_duplicate, not scope_variant
        scope_variants = [m for m in mappings if m.relation_type == "scope_variant"]
        assert len(scope_variants) == 0


class TestPrimaryUniqueness:
    def test_each_canonical_has_exactly_one_primary(self):
        """Invariant: every canonical has exactly one is_primary=True mapping."""
        segs = [
            _make_seg("a.md", 0, "Content A unique enough text"),
            _make_seg("b.md", 0, "Content B unique enough text"),
            _make_seg("c.md", 0, "Content A unique enough text"),  # exact dup of a
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
            "c.md": _make_profile("c.md"),
        }
        canonicals, mappings = canonicalize(segs, profiles)

        # Group mappings by canonical_key
        by_canon: dict[str, list[SourceMappingData]] = {}
        for m in mappings:
            by_canon.setdefault(m.canonical_key, []).append(m)

        for canon_key, canon_mappings in by_canon.items():
            primaries = [m for m in canon_mappings if m.is_primary]
            assert len(primaries) == 1, (
                f"canonical {canon_key} has {len(primaries)} primaries"
            )


class TestV05FieldAlignment:
    def test_canonical_has_block_type_not_segment_type(self):
        segs = [_make_seg("a.md", 0, "text", block_type="paragraph")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, _ = canonicalize(segs, profiles)
        assert canonicals[0].block_type == "paragraph"
        assert not hasattr(canonicals[0], "segment_type")

    def test_canonical_has_semantic_role_not_section_role(self):
        segs = [_make_seg("a.md", 0, "text", semantic_role="concept")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, _ = canonicalize(segs, profiles)
        assert canonicals[0].semantic_role == "concept"
        assert not hasattr(canonicals[0], "section_role")

    def test_canonical_no_command_name(self):
        segs = [_make_seg("a.md", 0, "ADD APN command")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, _ = canonicalize(segs, profiles)
        assert not hasattr(canonicals[0], "command_name")

    def test_mapping_has_relation_type(self):
        segs = [_make_seg("a.md", 0, "text")]
        profiles = {"a.md": _make_profile("a.md")}
        _, mappings = canonicalize(segs, profiles)
        assert mappings[0].relation_type == "primary"

    def test_canonical_search_text_is_lowercase(self):
        segs = [_make_seg("a.md", 0, "Hello World UPPER")]
        profiles = {"a.md": _make_profile("a.md")}
        canonicals, _ = canonicalize(segs, profiles)
        assert canonicals[0].search_text == "hello world upper"

    def test_entity_refs_merged(self):
        segs = [
            _make_seg("a.md", 0, "cmd A", entity_refs_json=[{"type": "command", "name": "ADD"}]),
            _make_seg("b.md", 0, "cmd A", entity_refs_json=[{"type": "command", "name": "MOD"}]),
        ]
        profiles = {
            "a.md": _make_profile("a.md"),
            "b.md": _make_profile("b.md"),
        }
        # Make them exact duplicates by using same content
        text = "same content for entity merge"
        segs = [
            RawSegmentData(
                document_key="a.md", segment_index=0, raw_text=text,
                content_hash=content_hash(text), normalized_hash=normalized_hash(text),
                entity_refs_json=[{"type": "command", "name": "ADD"}],
            ),
            RawSegmentData(
                document_key="b.md", segment_index=0, raw_text=text,
                content_hash=content_hash(text), normalized_hash=normalized_hash(text),
                entity_refs_json=[{"type": "command", "name": "MOD"}],
            ),
        ]
        canonicals, _ = canonicalize(segs, profiles)
        entity_names = [e["name"] for e in canonicals[0].entity_refs_json]
        assert "ADD" in entity_names
        assert "MOD" in entity_names

    def test_scope_json_merged(self):
        text = "same content for scope merge"
        segs = [
            RawSegmentData(
                document_key="a.md", segment_index=0, raw_text=text,
                content_hash=content_hash(text), normalized_hash=normalized_hash(text),
            ),
            RawSegmentData(
                document_key="b.md", segment_index=0, raw_text=text,
                content_hash=content_hash(text), normalized_hash=normalized_hash(text),
            ),
        ]
        profiles = {
            "a.md": _make_profile("a.md", scope_json={"product": "UDG", "version": "V1"}),
            "b.md": _make_profile("b.md", scope_json={"product": "UDG", "region": "east"}),
        }
        canonicals, _ = canonicalize(segs, profiles)
        scope = canonicals[0].scope_json
        assert scope["product"] == "UDG"
        assert "version" in scope
        assert "region" in scope
