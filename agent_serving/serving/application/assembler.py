"""ContextAssembler — build context pack with conflict handling."""
from __future__ import annotations

import json

from agent_serving.serving.schemas.models import (
    AnswerMaterials,
    CanonicalSegmentRef,
    ContextPack,
    KeyObjects,
    NormalizedQuery,
    RawSegmentRef,
    SourceRef,
    Uncertainty,
)


class ContextAssembler:
    def assemble(
        self,
        *,
        query: str,
        intent: str,
        normalized: NormalizedQuery,
        canonical_hits: list[dict],
        drill_results: list[dict],
        conflict_sources: list[dict],
    ) -> ContextPack:
        key_objects = KeyObjects(
            command=normalized.command,
            product=normalized.product,
            product_version=normalized.product_version,
            network_element=normalized.network_element,
        )

        canon_refs = [
            CanonicalSegmentRef(
                id=str(h["id"]),
                segment_type=h["segment_type"],
                title=h.get("title"),
                canonical_text=h["canonical_text"],
                command_name=h.get("command_name"),
                has_variants=bool(h.get("has_variants")),
                variant_policy=h.get("variant_policy", "none"),
            )
            for h in canonical_hits
        ]

        raw_refs = [
            RawSegmentRef(
                id=str(r["id"]),
                segment_type=r["segment_type"],
                raw_text=r["raw_text"],
                command_name=r.get("command_name"),
                section_path=_parse_section_path(r.get("section_path", "[]")),
                section_title=r.get("section_title"),
            )
            for r in drill_results
        ]

        sources = self._build_sources(drill_results)
        uncertainties = self._build_uncertainties(normalized, canonical_hits)
        conflict_uncertainties = self._build_conflict_uncertainties(conflict_sources)
        uncertainties.extend(conflict_uncertainties)

        followups = self._build_followups(uncertainties)

        return ContextPack(
            query=query,
            intent=intent,
            normalized_query=self._build_normalized_str(normalized),
            key_objects=key_objects,
            answer_materials=AnswerMaterials(
                canonical_segments=canon_refs,
                raw_segments=raw_refs,
            ),
            sources=sources,
            uncertainties=uncertainties,
            suggested_followups=followups,
        )

    def _build_sources(self, drill_results: list[dict]) -> list[SourceRef]:
        return [
            SourceRef(
                document_key=r.get("document_key", ""),
                section_path=_parse_section_path(r.get("section_path", "[]")),
                segment_type=r["segment_type"],
                product=r.get("product"),
                product_version=r.get("product_version"),
                network_element=r.get("network_element"),
            )
            for r in drill_results
        ]

    def _build_uncertainties(
        self, normalized: NormalizedQuery, hits: list[dict]
    ) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = []
        has_variants_hit = any(h.get("has_variants") for h in hits)

        if has_variants_hit and normalized.missing_constraints:
            if "product" in normalized.missing_constraints:
                uncertainties.append(
                    Uncertainty(
                        field="product",
                        reason="该命令在不同产品上有差异，需要指定产品",
                        suggested_options=["UDG", "UNC", "UPF"],
                    )
                )
            if "product_version" in normalized.missing_constraints:
                uncertainties.append(
                    Uncertainty(
                        field="product_version",
                        reason="该命令参数在不同版本间可能有差异",
                        suggested_options=[],
                    )
                )
        return uncertainties

    def _build_conflict_uncertainties(
        self, conflict_sources: list[dict]
    ) -> list[Uncertainty]:
        uncertainties: list[Uncertainty] = []
        for cs in conflict_sources:
            product = cs.get("product", "未知产品")
            diff = cs.get("diff_summary", "存在内容矛盾")
            uncertainties.append(
                Uncertainty(
                    field="conflict",
                    reason=f"知识库中存在冲突来源（{product}）：{diff}",
                    suggested_options=[product],
                )
            )
        return uncertainties

    def _build_followups(self, uncertainties: list[Uncertainty]) -> list[str]:
        if not uncertainties:
            return []
        conflict_fields = [u.field for u in uncertainties if u.field != "conflict"]
        conflict_count = sum(1 for u in uncertainties if u.field == "conflict")
        parts = []
        if conflict_fields:
            parts.append(f"请确认{'/'.join(conflict_fields)}以获取精确答案")
        if conflict_count > 0:
            parts.append(f"发现 {conflict_count} 处知识冲突，建议核实产品版本后重新查询")
        return parts

    def _build_normalized_str(self, normalized: NormalizedQuery) -> str:
        parts: list[str] = []
        if normalized.command:
            parts.append(normalized.command)
        if normalized.product:
            parts.append(normalized.product)
        if normalized.product_version:
            parts.append(normalized.product_version)
        if normalized.network_element:
            parts.append(normalized.network_element)
        parts.extend(normalized.keywords)
        return " ".join(parts)


def _parse_section_path(raw: str | list) -> list[str]:
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
