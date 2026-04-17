"""Read-only repository for asset tables (L0/L1/L2).

All queries enforce publish_version_id = active version per schema README.
Uses QueryPlan for search — no command-specific SQL paths.
Document-level scope is read from raw_documents.scope_json (v0.5).
"""
from __future__ import annotations

import json
from typing import Any

import aiosqlite

from agent_serving.serving.schemas.models import QueryPlan, QueryScope


class AssetRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get_active_publish_version_id(self) -> str | None:
        cursor = await self._db.execute(
            "SELECT id FROM asset_publish_versions WHERE status = 'active' LIMIT 1"
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    async def search_canonical(
        self, plan: QueryPlan, pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search canonical segments based on QueryPlan.

        Strategy: search_text LIKE recall, then Python-side JSON filtering.
        """
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        # Build WHERE clause for text recall
        conditions = ["cs.publish_version_id = ?"]
        params: list[Any] = [pv_id]

        # Entity name search via search_text
        entity_names = [e.name for e in plan.entity_constraints]
        if entity_names:
            like_clauses = " OR ".join("cs.search_text LIKE ?" for _ in entity_names)
            conditions.append(f"({like_clauses})")
            params.extend(f"%{name}%" for name in entity_names)
        elif plan.keywords:
            like_clauses = " OR ".join("cs.search_text LIKE ?" for _ in plan.keywords)
            conditions.append(f"({like_clauses})")
            params.extend(f"%{kw}%" for kw in plan.keywords)
        else:
            return []

        query = f"SELECT * FROM asset_canonical_segments cs WHERE {' AND '.join(conditions)}"
        query += f" LIMIT {plan.evidence_budget.canonical_limit}"

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        results = [dict(row) for row in rows]

        # Python-side JSON filtering for entity_refs and scope
        if plan.entity_constraints:
            results = self._filter_by_entities(results, plan.entity_constraints)

        if plan.semantic_role_preferences:
            results = self._filter_by_semantic_roles(results, plan.semantic_role_preferences)

        return results

    async def drill_down(
        self,
        canonical_segment_id: str,
        plan: QueryPlan,
        pv_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Drill down from canonical to raw evidence.

        Returns (evidence_rows, variant_rows, conflict_rows) separately.
        """
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return [], [], []

        query = (
            "SELECT rs.id, rs.block_type, rs.semantic_role, rs.raw_text, "
            "  rs.section_path, rs.section_title, rs.entity_refs_json, "
            "  rd.document_key, rd.relative_path, rd.scope_json AS doc_scope_json, "
            "  csources.relation_type, csources.diff_summary, csources.metadata_json AS source_metadata "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ? "
            "ORDER BY csources.is_primary DESC, csources.priority ASC"
        )
        cursor = await self._db.execute(query, (canonical_segment_id, pv_id))
        rows = await cursor.fetchall()

        evidence: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        for row in rows:
            r = dict(row)
            rel_type = r["relation_type"]

            if rel_type == "conflict_candidate":
                conflicts.append(r)
            elif rel_type == "scope_variant":
                # Apply scope filtering if constraints present
                if self._matches_scope(r, plan.scope_constraints):
                    evidence.append(r)
                else:
                    variants.append(r)
            else:
                # primary, exact_duplicate, normalized_duplicate, near_duplicate
                if self._matches_scope(r, plan.scope_constraints):
                    evidence.append(r)
                else:
                    variants.append(r)

        # Limit evidence per canonical
        limit = plan.evidence_budget.raw_per_canonical
        if len(evidence) > limit:
            evidence = evidence[:limit]

        return evidence, variants, conflicts

    async def get_conflict_sources(
        self, canonical_segment_id: str, pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get conflict candidates for a canonical segment."""
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        cursor = await self._db.execute(
            "SELECT rs.raw_text, rs.entity_refs_json, "
            "  rd.scope_json AS doc_scope_json, "
            "  csources.relation_type, csources.diff_summary "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ? "
            "AND csources.relation_type = 'conflict_candidate'",
            (canonical_segment_id, pv_id),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Private helpers ---

    def _filter_by_entities(
        self, results: list[dict], entity_constraints: list,
    ) -> list[dict]:
        """Filter canonical results by entity_refs_json match."""
        if not entity_constraints:
            return results

        filtered = []
        for r in results:
            try:
                refs = json.loads(r.get("entity_refs_json", "[]"))
            except (json.JSONDecodeError, TypeError):
                refs = []

            for constraint in entity_constraints:
                for ref in refs:
                    if (ref.get("type") == constraint.type
                            and ref.get("normalized_name", "").lower()
                            == constraint.normalized_name.lower()):
                        filtered.append(r)
                        break
                else:
                    continue
                break

        return filtered

    def _filter_by_semantic_roles(
        self, results: list[dict], preferred_roles: list[str],
    ) -> list[dict]:
        """Prefer results matching desired semantic roles but don't exclude others."""
        if not preferred_roles:
            return results

        preferred = []
        other = []
        for r in results:
            if r.get("semantic_role", "unknown") in preferred_roles:
                preferred.append(r)
            else:
                other.append(r)
        return preferred + other

    def _matches_scope(self, row: dict, scope: QueryScope) -> bool:
        """Check if a raw evidence row matches scope constraints.

        If no scope constraints specified, everything matches.
        Only filters on fields that are constrained.
        """
        if not scope.products and not scope.product_versions and not scope.network_elements:
            return True

        try:
            doc_scope = json.loads(row.get("doc_scope_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            doc_scope = {}

        if scope.products:
            doc_products = doc_scope.get("products", [])
            if not any(p in doc_products for p in scope.products):
                return False

        if scope.product_versions:
            doc_versions = doc_scope.get("product_versions", [])
            if not any(v in doc_versions for v in scope.product_versions):
                return False

        if scope.network_elements:
            doc_nes = doc_scope.get("network_elements", [])
            if not any(ne in doc_nes for ne in scope.network_elements):
                return False

        return True
