"""Verify SQLite schema creation from shared DDL and basic CRUD."""
import tempfile
from pathlib import Path

from knowledge_mining.mining.db import MiningDB


def test_create_tables_from_shared_ddl():
    """Schema must be loaded from the shared SQLite DDL file."""
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor]
            assert "asset_source_batches" in tables
            assert "asset_publish_versions" in tables
            assert "asset_raw_documents" in tables
            assert "asset_raw_segments" in tables
            assert "asset_canonical_segments" in tables
            assert "asset_canonical_segment_sources" in tables
        finally:
            conn.close()


def test_insert_and_query_publish_version():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
            cursor = conn.execute(
                "SELECT version_code, status FROM asset_publish_versions WHERE id = ?",
                (pv_id,),
            )
            row = cursor.fetchone()
            assert row == ("v1", "staging")
        finally:
            conn.close()


def test_raw_documents_has_v04_fields():
    """Verify v0.4 fields exist: scope_json, tags_json, source_type, structure_quality."""
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
            db.insert_raw_document(
                conn,
                publish_version_id=pv_id,
                document_key="test_doc",
                source_uri="/test.md",
                file_name="test.md",
                file_type="markdown",
                content_hash="abc",
                source_type="synthetic_coldstart",
                scope_json={"product": "UDG"},
                tags_json=["5G"],
                structure_quality="markdown_native",
            )
            cursor = conn.execute(
                "SELECT scope_json, tags_json, source_type, structure_quality FROM asset_raw_documents WHERE document_key = ?",
                ("test_doc",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert "product" in row[0]
        finally:
            conn.close()


def test_raw_segments_has_block_type_and_section_role():
    """Verify raw_segments has block_type, section_role, structure_json, source_offsets_json."""
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            pv_id = db.create_publish_version(conn, version_code="v1", status="staging")
            doc_id = db.insert_raw_document(
                conn,
                publish_version_id=pv_id,
                document_key="test_doc",
                source_uri="/test.md",
                file_name="test.md",
                file_type="markdown",
                content_hash="abc",
            )
            db.insert_raw_segment(
                conn,
                publish_version_id=pv_id,
                raw_document_id=doc_id,
                segment_key="test_doc#0",
                segment_index=0,
                segment_type="paragraph",
                block_type="table",
                raw_text="some text",
                normalized_text="some text",
                content_hash="hash123",
                normalized_hash="nhash123",
                section_path=["Root"],
                section_title="Root",
                section_role="parameter",
                structure_json={"rows": 3},
                source_offsets_json={"start": 0, "end": 100},
            )
            cursor = conn.execute(
                "SELECT block_type, section_role, structure_json FROM asset_raw_segments WHERE segment_key = ?",
                ("test_doc#0",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == "table"
            assert row[1] == "parameter"
            assert "rows" in row[2]
        finally:
            conn.close()


def test_create_source_batch():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            batch_id = db.create_source_batch(
                conn, batch_code="batch-001", source_type="productdoc_export",
            )
            cursor = conn.execute(
                "SELECT batch_code, source_type FROM asset_source_batches WHERE id = ?",
                (batch_id,),
            )
            row = cursor.fetchone()
            assert row == ("batch-001", "productdoc_export")
        finally:
            conn.close()


def test_publish_version_with_batch():
    with tempfile.TemporaryDirectory() as tmp:
        db = MiningDB(Path(tmp) / "test.sqlite")
        db.create_tables()
        conn = db.connect()
        try:
            batch_id = db.create_source_batch(
                conn, batch_code="batch-002", source_type="folder_scan",
            )
            pv_id = db.create_publish_version(
                conn, version_code="v2", status="staging", source_batch_id=batch_id,
            )
            cursor = conn.execute(
                "SELECT source_batch_id FROM asset_publish_versions WHERE id = ?",
                (pv_id,),
            )
            row = cursor.fetchone()
            assert row[0] == batch_id
        finally:
            conn.close()
