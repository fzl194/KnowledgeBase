"""Test default extractor implementations: NoOpEntityExtractor, DefaultRoleClassifier, NoOpSegmentEnricher."""
from __future__ import annotations

from knowledge_mining.mining.extractors import (
    DefaultRoleClassifier,
    EntityExtractor,
    NoOpEntityExtractor,
    NoOpSegmentEnricher,
    RoleClassifier,
    SegmentEnricher,
)
from knowledge_mining.mining.models import CanonicalSegmentData, RawSegmentData


class TestNoOpEntityExtractor:
    def test_returns_empty_list(self):
        ext = NoOpEntityExtractor()
        result = ext.extract("ADD APN command", {})
        assert result == []

    def test_protocol_conformance(self):
        ext = NoOpEntityExtractor()
        assert isinstance(ext, EntityExtractor)

    def test_ignores_context(self):
        ext = NoOpEntityExtractor()
        result = ext.extract("anything", {"key": "value"})
        assert result == []


class TestDefaultRoleClassifier:
    def test_returns_unknown(self):
        cls = DefaultRoleClassifier()
        result = cls.classify("some text", "Section Title", "paragraph", {})
        assert result == "unknown"

    def test_protocol_conformance(self):
        cls = DefaultRoleClassifier()
        assert isinstance(cls, RoleClassifier)

    def test_ignores_all_inputs(self):
        cls = DefaultRoleClassifier()
        for block_type in ("paragraph", "table", "code", "list"):
            result = cls.classify("text", "title", block_type, {"extra": True})
            assert result == "unknown"


class TestNoOpSegmentEnricher:
    def test_returns_canonical_unchanged(self):
        enricher = NoOpSegmentEnricher()
        canon = CanonicalSegmentData(
            canonical_key="c000000",
            canonical_text="hello",
        )
        result = enricher.enrich(canon, [])
        assert result is canon

    def test_protocol_conformance(self):
        enricher = NoOpSegmentEnricher()
        assert isinstance(enricher, SegmentEnricher)

    def test_with_sources(self):
        enricher = NoOpSegmentEnricher()
        canon = CanonicalSegmentData(canonical_key="c000000")
        sources = [
            RawSegmentData(document_key="a.md", segment_index=0, raw_text="x"),
        ]
        result = enricher.enrich(canon, sources)
        assert result is canon
