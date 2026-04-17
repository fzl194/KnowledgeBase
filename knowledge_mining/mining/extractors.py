"""Pluggable content understanding interfaces for M1 Mining.

M1 provides default no-op implementations.
Future: replace with domain-specific extractors, NER models, or LLM-based classifiers.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from knowledge_mining.mining.models import CanonicalSegmentData, RawSegmentData


@runtime_checkable
class EntityExtractor(Protocol):
    """Extract entities from text. M1 default: returns empty list."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        """Return list of entity refs like [{"type": "command", "name": "ADD APN"}]."""
        ...


@runtime_checkable
class RoleClassifier(Protocol):
    """Classify semantic role of a segment. M1 default: returns 'unknown'."""

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str:
        """Return semantic_role from the v0.5 enum."""
        ...


@runtime_checkable
class SegmentEnricher(Protocol):
    """Enrich canonical segment with summary/quality_score. M1 default: no-op."""

    def enrich(
        self,
        canonical: CanonicalSegmentData,
        sources: list[RawSegmentData],
    ) -> CanonicalSegmentData:
        """Return enriched canonical (may be same instance if no changes)."""
        ...


class NoOpEntityExtractor:
    """M1 default: no entity extraction."""

    def extract(self, text: str, context: dict[str, Any]) -> list[dict[str, str]]:
        return []


class DefaultRoleClassifier:
    """M1 default: all segments get 'unknown' role."""

    def classify(
        self,
        text: str,
        section_title: str | None,
        block_type: str,
        context: dict[str, Any],
    ) -> str:
        return "unknown"


class NoOpSegmentEnricher:
    """M1 default: no enrichment."""

    def enrich(
        self,
        canonical: CanonicalSegmentData,
        sources: list[RawSegmentData],
    ) -> CanonicalSegmentData:
        return canonical
