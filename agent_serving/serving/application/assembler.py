"""ContextAssembler — builds ContextPack from retrieval results.

v1.1 design:
- seed items from retrieval_candidates (retrieval_units)
- source drill-down via resolve_source_segments (parsed source_refs_json)
- context expansion via GraphExpander relations
- first-class relations list in output
- document attribution via document_snapshot_map
"""
from __future__ import annotations

import json
import logging
from typing import Any

from agent_serving.serving.schemas.models import (
    ActiveScope,
    ContextItem,
    ContextPack,
    ContextQuery,
    ContextRelation,
    Issue,
    NormalizedQuery,
    QueryPlan,
    RetrievalCandidate,
    SourceRef,
)
from agent_serving.serving.schemas.constants import (
    ISSUE_LOW_CONFIDENCE,
    ISSUE_NO_RESULT,
    KIND_RAW_SEGMENT,
    KIND_RETRIEVAL_UNIT,
    ROLE_CONTEXT,
    ROLE_SEED,
    ROLE_SUPPORT,
)
from agent_serving.serving.schemas.json_utils import safe_json_parse
from agent_serving.serving.repositories.asset_repo import AssetRepository
from agent_serving.serving.retrieval.graph_expander import (
    GraphExpander,
    parse_source_refs,
    parse_target_ref,
)

logger = logging.getLogger(__name__)


class ContextAssembler:
    """Assembles ContextPack from retrieval + expansion results."""

    def __init__(self, repo: AssetRepository, graph: GraphExpander) -> None:
        self._repo = repo
        self._graph = graph

    async def assemble(
        self,
        *,
        query: str,
        normalized: NormalizedQuery,
        plan: QueryPlan,
        scope: ActiveScope,
        candidates: list[RetrievalCandidate],
    ) -> ContextPack:
        """Full assembly pipeline: seed → source drill-down → expansion → pack."""
        # 1. Build seed items from retrieval candidates
        seed_items = self._build_seed_items(candidates)

        # 2. Source drill-down with 3-layer priority:
        #    a) raw_segment_ids from source_refs_json
        #    b) target_type/target_ref_json fallback
        #    c) snapshot-level fallback (all segments in snapshot)
        all_source_segment_ids: list[str] = []

        for candidate in candidates:
            seg_ids = self._resolve_candidate_sources(candidate)
            all_source_segment_ids.extend(seg_ids)

        # Deduplicate
        seen_segs: set[str] = set()
        unique_seg_ids: list[str] = []
        for sid in all_source_segment_ids:
            if sid not in seen_segs:
                seen_segs.add(sid)
                unique_seg_ids.append(sid)

        # 3. Fetch source segments (constrained to active build snapshots)
        source_segments = await self._repo.resolve_source_segments(
            json.dumps({"raw_segment_ids": unique_seg_ids}) if unique_seg_ids else None,
            snapshot_ids=scope.snapshot_ids,
        )
        source_seg_map = {str(s["id"]): s for s in source_segments}

        # Build source items
        source_items = self._build_source_items(source_segments)

        # 4. Graph expansion if enabled
        expanded_items: list[ContextItem] = []
        relation_items: list[ContextRelation] = []

        if plan.expansion.enable_relation_expansion and unique_seg_ids:
            expansions = await self._graph.expand(
                seed_segment_ids=unique_seg_ids,
                max_depth=plan.expansion.max_relation_depth,
                relation_types=plan.expansion.relation_types or None,
                max_results=plan.budget.max_expanded,
                snapshot_ids=scope.snapshot_ids,
            )

            # Fetch expanded segment data
            expanded_data = await self._graph.fetch_expanded_segments(expansions)
            expanded_items = self._build_expanded_items(expanded_data)

            # Build relation links from expansions
            for exp in expansions:
                relation_items.append(ContextRelation(
                    id=f"rel-{exp['from_segment_id']}-{exp['segment_id']}",
                    from_id=exp["from_segment_id"],
                    to_id=exp["segment_id"],
                    relation_type=exp["relation_type"],
                    distance=exp["depth"],
                ))

        # 5. Fetch direct relations for seed segments
        if unique_seg_ids:
            direct_relations = await self._repo.get_relations_for_segments(
                unique_seg_ids,
                relation_types=plan.expansion.relation_types or None,
            )
            for rel in direct_relations:
                rid = str(rel["id"])
                relation_items.append(ContextRelation(
                    id=rid,
                    from_id=str(rel["from_segment_id"]),
                    to_id=str(rel["to_segment_id"]),
                    relation_type=rel["relation_type"],
                    distance=0,
                ))

        # Deduplicate relations
        seen_rels: set[str] = set()
        unique_relations: list[ContextRelation] = []
        for r in relation_items:
            if r.id not in seen_rels:
                seen_rels.add(r.id)
                unique_relations.append(r)

        # 6. Build source references (document attribution)
        document_ids = set()
        for seg in source_segments:
            if seg.get("document_id"):
                document_ids.add(str(seg["document_id"]))

        doc_sources = await self._repo.get_document_sources(
            list(document_ids), snapshot_ids=scope.snapshot_ids,
        )
        sources = self._build_sources(doc_sources)

        # 7. Build issues
        issues = self._build_issues(seed_items, normalized)

        # 8. Assemble final pack
        all_items = seed_items + source_items + expanded_items
        # Truncate to budget
        all_items = all_items[:plan.budget.max_items + plan.budget.max_expanded]

        return ContextPack(
            query=ContextQuery(
                original=query,
                normalized=self._format_normalized(normalized),
                intent=normalized.intent,
                entities=normalized.entities,
                scope=normalized.scope,
                keywords=normalized.keywords,
            ),
            items=all_items,
            relations=unique_relations,
            sources=sources,
            issues=issues,
            suggestions=self._build_suggestions(issues),
        )

    def _build_seed_items(
        self, candidates: list[RetrievalCandidate],
    ) -> list[ContextItem]:
        items = []
        for c in candidates:
            items.append(ContextItem(
                id=c.retrieval_unit_id,
                kind=KIND_RETRIEVAL_UNIT,
                role=ROLE_SEED,
                text=c.metadata.get("text", ""),
                score=c.score,
                title=c.metadata.get("title"),
                block_type=c.metadata.get("block_type", "unknown"),
                semantic_role=c.metadata.get("semantic_role", "unknown"),
                source_refs=safe_json_parse(c.metadata.get("source_refs_json", "{}")),
            ))
        return items

    def _resolve_candidate_sources(self, candidate: RetrievalCandidate) -> list[str]:
        """Resolve source segment IDs with 3-layer priority.

        Priority:
        1. source_refs_json.raw_segment_ids (preferred)
        2. target_type/target_ref_json (fallback for summary/entity_card units)
        3. Returns empty list (snapshot-level fallback handled at assembly level)
        """
        # Layer 1: source_refs_json
        source_refs = candidate.metadata.get("source_refs_json", "{}")
        seg_ids = parse_source_refs(source_refs)
        if seg_ids:
            return seg_ids

        # Layer 2: target_ref_json
        target_type = candidate.metadata.get("target_type", "")
        target_ref = candidate.metadata.get("target_ref_json", "{}")
        if target_type and target_ref and target_ref != "{}":
            seg_ids = parse_target_ref(target_ref)
            if seg_ids:
                return seg_ids

        # Layer 3: No direct segment refs — returns empty
        # (snapshot-level fallback would fetch all segments from snapshot,
        # but is deferred until actual need arises)
        return []

    def _build_source_items(
        self, segments: list[dict[str, Any]],
    ) -> list[ContextItem]:
        items = []
        for seg in segments:
            items.append(ContextItem(
                id=str(seg["id"]),
                kind=KIND_RAW_SEGMENT,
                role=ROLE_CONTEXT,
                text=seg.get("raw_text", ""),
                score=0.0,
                title=seg.get("snapshot_title"),
                block_type=seg.get("block_type", "unknown"),
                semantic_role=seg.get("semantic_role", "unknown"),
                source_id=str(seg.get("document_id", "")),
                source_refs={},
            ))
        return items

    def _build_expanded_items(
        self, expanded: list[dict[str, Any]],
    ) -> list[ContextItem]:
        items = []
        for seg in expanded:
            items.append(ContextItem(
                id=str(seg["id"]),
                kind=KIND_RAW_SEGMENT,
                role=ROLE_SUPPORT,
                text=seg.get("raw_text", ""),
                score=0.0,
                title=seg.get("doc_title"),
                block_type=seg.get("block_type", "unknown"),
                semantic_role=seg.get("semantic_role", "unknown"),
                source_id=str(seg.get("document_id", "")),
                relation_to_seed=seg.get("expansion_relation_type", ""),
            ))
        return items

    def _build_sources(
        self, docs: list[dict[str, Any]],
    ) -> list[SourceRef]:
        seen: set[str] = set()
        sources = []
        for doc in docs:
            doc_id = str(doc["id"])
            if doc_id in seen:
                continue
            seen.add(doc_id)
            sources.append(SourceRef(
                id=doc_id,
                document_key=doc.get("document_key", ""),
                title=doc.get("title"),
                relative_path=doc.get("relative_path"),
                scope_json=safe_json_parse(doc.get("scope_json", "{}")),
            ))
        return sources

    def _build_issues(
        self,
        items: list[ContextItem],
        normalized: NormalizedQuery,
    ) -> list[Issue]:
        issues: list[Issue] = []

        if not items:
            issues.append(Issue(
                type=ISSUE_NO_RESULT,
                message="未找到相关内容",
                detail={"query": normalized.original_query},
            ))
        elif all(item.score < 0.1 for item in items):
            issues.append(Issue(
                type=ISSUE_LOW_CONFIDENCE,
                message="检索结果置信度较低",
                detail={"top_score": max(item.score for item in items)},
            ))

        return issues

    def _build_suggestions(self, issues: list[Issue]) -> list[str]:
        suggestions: list[str] = []
        for issue in issues:
            if issue.type == ISSUE_NO_RESULT:
                suggestions.append("尝试使用更通用的关键词")
            elif issue.type == ISSUE_LOW_CONFIDENCE:
                suggestions.append("尝试更精确的描述或添加产品/版本约束")
        return suggestions

    def _format_normalized(self, normalized: NormalizedQuery) -> str:
        parts = [f"intent={normalized.intent}"]
        for e in normalized.entities:
            parts.append(f"{e.type}={e.name}")
        parts.extend(normalized.keywords)
        return " ".join(parts)
