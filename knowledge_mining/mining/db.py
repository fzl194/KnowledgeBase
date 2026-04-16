"""SQLite database adapter for M1 Mining — reads shared DDL."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4


class MiningDB:
    """SQLite dev-mode database using shared schema DDL."""

    _SHARED_SCHEMA_PATH = (
        Path(__file__).resolve().parents[2]
        / "knowledge_assets"
        / "schemas"
        / "001_asset_core.sqlite.sql"
    )

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create_tables(self) -> None:
        schema_sql = self._SHARED_SCHEMA_PATH.read_text(encoding="utf-8")
        conn = self.connect()
        conn.executescript(schema_sql)
        conn.close()

    @staticmethod
    def create_source_batch(
        conn: sqlite3.Connection,
        batch_code: str,
        source_type: str,
        description: str | None = None,
    ) -> str:
        batch_id = str(uuid4())
        conn.execute(
            """INSERT INTO asset_source_batches
               (id, batch_code, source_type, description, created_at, metadata_json)
               VALUES (?, ?, ?, ?, datetime('now'), '{}')""",
            (batch_id, batch_code, source_type, description),
        )
        conn.commit()
        return batch_id

    @staticmethod
    def create_publish_version(
        conn: sqlite3.Connection,
        version_code: str,
        status: str = "staging",
        source_batch_id: str | None = None,
    ) -> str:
        pv_id = str(uuid4())
        conn.execute(
            """INSERT INTO asset_publish_versions
               (id, version_code, status, source_batch_id,
                build_started_at, metadata_json)
               VALUES (?, ?, ?, ?, datetime('now'), '{}')""",
            (pv_id, version_code, status, source_batch_id),
        )
        conn.commit()
        return pv_id

    @staticmethod
    def insert_raw_document(
        conn: sqlite3.Connection,
        publish_version_id: str,
        document_key: str,
        source_uri: str,
        file_name: str,
        file_type: str,
        content_hash: str,
        source_type: str | None = None,
        scope_json: dict | None = None,
        tags_json: list | None = None,
        structure_quality: str = "unknown",
    ) -> str:
        doc_id = str(uuid4())
        conn.execute(
            """INSERT INTO asset_raw_documents
               (id, publish_version_id, document_key, source_uri, file_name,
                file_type, content_hash, source_type, scope_json, tags_json,
                structure_quality, created_at, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), '{}')""",
            (
                doc_id,
                publish_version_id,
                document_key,
                source_uri,
                file_name,
                file_type,
                content_hash,
                source_type,
                json.dumps(scope_json or {}),
                json.dumps(tags_json or []),
                structure_quality,
            ),
        )
        conn.commit()
        return doc_id

    @staticmethod
    def insert_raw_segment(
        conn: sqlite3.Connection,
        publish_version_id: str,
        raw_document_id: str,
        segment_key: str,
        segment_index: int,
        segment_type: str,
        block_type: str,
        raw_text: str,
        normalized_text: str,
        content_hash: str,
        normalized_hash: str,
        section_path: list | None = None,
        section_title: str | None = None,
        heading_level: int | None = None,
        section_role: str | None = None,
        command_name: str | None = None,
        token_count: int | None = None,
        structure_json: dict | None = None,
        source_offsets_json: dict | None = None,
    ) -> str:
        seg_id = str(uuid4())
        conn.execute(
            """INSERT INTO asset_raw_segments
               (id, publish_version_id, raw_document_id, segment_key,
                segment_index, section_path, section_title, heading_level,
                segment_type, block_type, section_role, command_name,
                raw_text, normalized_text, content_hash, normalized_hash,
                token_count, structure_json, source_offsets_json, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')""",
            (
                seg_id,
                publish_version_id,
                raw_document_id,
                segment_key,
                segment_index,
                json.dumps(section_path or []),
                section_title,
                heading_level,
                segment_type,
                block_type,
                section_role,
                command_name,
                raw_text,
                normalized_text,
                content_hash,
                normalized_hash,
                token_count,
                json.dumps(structure_json or {}),
                json.dumps(source_offsets_json or {}),
            ),
        )
        conn.commit()
        return seg_id
