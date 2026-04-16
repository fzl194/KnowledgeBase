"""Read-only repository for asset tables (L0/L1/L2).

All queries enforce publish_version_id = active version per schema README.
Document-level constraints (product/product_version/network_element) are
obtained by joining raw_segments -> raw_documents, not from L2 metadata.
"""
from __future__ import annotations

from typing import Any

import aiosqlite


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
        self,
        *,
        command_name: str | None = None,
        keyword: str | None = None,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        if command_name:
            cursor = await self._db.execute(
                "SELECT * FROM asset_canonical_segments "
                "WHERE publish_version_id = ? AND command_name = ?",
                (pv_id, command_name),
            )
        elif keyword:
            cursor = await self._db.execute(
                "SELECT * FROM asset_canonical_segments "
                "WHERE publish_version_id = ? AND search_text LIKE ?",
                (pv_id, f"%{keyword}%"),
            )
        else:
            return []

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def drill_down(
        self,
        *,
        canonical_segment_id: str,
        product: str | None = None,
        product_version: str | None = None,
        network_element: str | None = None,
        exclude_conflict: bool = False,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        query = (
            "SELECT rs.*, rd.product, rd.product_version, rd.network_element, "
            "  rd.document_key, "
            "  csources.relation_type, csources.diff_summary "
            "FROM asset_canonical_segment_sources csources "
            "JOIN asset_raw_segments rs ON csources.raw_segment_id = rs.id "
            "JOIN asset_raw_documents rd ON rs.raw_document_id = rd.id "
            "WHERE csources.canonical_segment_id = ? "
            "AND csources.publish_version_id = ?"
        )
        params: list[Any] = [canonical_segment_id, pv_id]

        if exclude_conflict:
            query += " AND csources.relation_type != 'conflict_candidate'"

        if product:
            query += " AND rd.product = ?"
            params.append(product)
        if product_version:
            query += " AND rd.product_version = ?"
            params.append(product_version)
        if network_element:
            query += " AND rd.network_element = ?"
            params.append(network_element)

        query += " ORDER BY csources.is_primary DESC, csources.priority ASC"

        cursor = await self._db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_conflict_sources(
        self,
        *,
        canonical_segment_id: str,
        pv_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if pv_id is None:
            pv_id = await self.get_active_publish_version_id()
        if pv_id is None:
            return []

        cursor = await self._db.execute(
            "SELECT rs.raw_text, rs.segment_type, rs.command_name, "
            "  rd.product, rd.product_version, rd.network_element, "
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

    async def get_raw_segments_by_ids(
        self, ids: list[str]
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cursor = await self._db.execute(
            f"SELECT * FROM asset_raw_segments WHERE id IN ({placeholders})",
            ids,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_document_for_segment(
        self, raw_segment_id: str
    ) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT rd.* FROM asset_raw_documents rd "
            "JOIN asset_raw_segments rs ON rs.raw_document_id = rd.id "
            "WHERE rs.id = ?",
            (raw_segment_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
