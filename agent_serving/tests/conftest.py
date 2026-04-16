"""Shared test fixtures: SQLite from shared schema + seed data.

Schema tables are created by schema_adapter from the shared
`knowledge_assets/schemas/001_asset_core.sql`. This file only
inserts test data — no private DDL.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite

# Fixed IDs for deterministic tests
ACTIVE_PV_ID = "11111111-1111-1111-1111-111111111111"
DOC_UDG_ID = "22222222-2222-2222-2222-222222222222"
DOC_UNC_ID = "33333333-3333-3333-3333-333333333333"
RAW_SEG_ADD_APN_UDG = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RAW_SEG_ADD_APN_UNC = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RAW_SEG_5G_CONCEPT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
RAW_SEG_CONFLICT = "44444444-4444-4444-4444-444444444444"
CANON_ADD_APN = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CANON_5G = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
CANON_PARAM = "55555555-5555-5555-5555-555555555555"
SOURCE_ADD_APN_UDG = "ffffffff-ffff-ffff-ffff-ffffffffffff"
SOURCE_ADD_APN_UNC = "00000000-0000-0000-0000-000000000001"
SOURCE_5G = "00000000-0000-0000-0000-000000000002"
SOURCE_CONFLICT = "00000000-0000-0000-0000-000000000003"

SEED_IDS = {
    "active_pv_id": ACTIVE_PV_ID,
    "doc_udg_id": DOC_UDG_ID,
    "doc_unc_id": DOC_UNC_ID,
    "raw_seg_add_apn_udg": RAW_SEG_ADD_APN_UDG,
    "raw_seg_add_apn_unc": RAW_SEG_ADD_APN_UNC,
    "raw_seg_5g_concept": RAW_SEG_5G_CONCEPT,
    "raw_seg_conflict": RAW_SEG_CONFLICT,
    "canon_add_apn": CANON_ADD_APN,
    "canon_5g": CANON_5G,
    "canon_param": CANON_PARAM,
    "source_add_apn_udg": SOURCE_ADD_APN_UDG,
    "source_add_apn_unc": SOURCE_ADD_APN_UNC,
    "source_5g": SOURCE_5G,
    "source_conflict": SOURCE_CONFLICT,
}


async def _seed_data(db: aiosqlite.Connection) -> None:
    """Insert deterministic test data using parameterized queries."""

    # publish_versions
    await db.execute(
        "INSERT INTO asset_publish_versions (id, version_code, status, description) "
        "VALUES (?, ?, ?, ?)",
        (ACTIVE_PV_ID, "PV-2026-04-15-v1", "active", "M1 test seed"),
    )

    # raw_documents
    await db.executemany(
        "INSERT INTO asset_raw_documents "
        "(id, publish_version_id, document_key, source_uri, file_name, file_type, "
        "product, product_version, network_element, document_type, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (DOC_UDG_ID, ACTIVE_PV_ID, "UDG_OM_REF", "file:///docs/udg_om.md",
             "udg_om.md", "markdown", "UDG", "V100R023C10", "UDM",
             "command_manual", "hash_udg_om"),
            (DOC_UNC_ID, ACTIVE_PV_ID, "UNC_OM_REF", "file:///docs/unc_om.md",
             "unc_om.md", "markdown", "UNC", "V100R023C20", "AMF",
             "command_manual", "hash_unc_om"),
        ],
    )

    # raw_segments
    await db.executemany(
        "INSERT INTO asset_raw_segments "
        "(id, publish_version_id, raw_document_id, segment_key, segment_index, "
        "section_path, section_title, segment_type, command_name, raw_text, "
        "normalized_text, content_hash, normalized_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (RAW_SEG_ADD_APN_UDG, ACTIVE_PV_ID, DOC_UDG_ID, "UDG_ADD_APN", 0,
             '["OM参考","MML命令","ADD APN"]', "ADD APN", "command", "ADD APN",
             "ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]",
             "add apn 命令用于在udg上新增apn配置",
             "hash_udg_add_apn", "nhash_udg_add_apn"),
            (RAW_SEG_ADD_APN_UNC, ACTIVE_PV_ID, DOC_UNC_ID, "UNC_ADD_APN", 0,
             '["OM参考","MML命令","ADD APN"]', "ADD APN", "command", "ADD APN",
             "ADD APN 命令用于在UNC上新增APN配置。语法与UDG版本有差异：ADD APN=<name>,TYPE=<type>,[参数列表]",
             "add apn 命令用于在unc上新增apn配置",
             "hash_unc_add_apn", "nhash_unc_add_apn"),
            (RAW_SEG_5G_CONCEPT, ACTIVE_PV_ID, DOC_UDG_ID, "UDG_5G_INTRO", 1,
             '["基础知识","5G概述"]', "5G概述", "concept", None,
             "5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。",
             "5g是第五代移动通信技术", "hash_5g", "nhash_5g"),
            (RAW_SEG_CONFLICT, ACTIVE_PV_ID, DOC_UNC_ID, "UNC_ADD_APN_CONFLICT", 1,
             '["OM参考","MML命令","ADD APN"]', "ADD APN", "command", "ADD APN",
             "ADD APN 参数冲突版本：APN=<name>是必填参数，与UDG版本完全不同。",
             "add apn 参数冲突版本", "hash_conflict", "nhash_conflict"),
        ],
    )

    # canonical_segments
    await db.executemany(
        "INSERT INTO asset_canonical_segments "
        "(id, publish_version_id, canonical_key, segment_type, title, command_name, "
        "canonical_text, summary, search_text, has_variants, variant_policy) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (CANON_ADD_APN, ACTIVE_PV_ID, "CANON_ADD_APN", "command",
             "ADD APN 命令", "ADD APN",
             "ADD APN 命令用于新增APN配置。不同产品的参数列表有差异。",
             "ADD APN 归并命令参考",
             "ADD APN 命令 新增 APN 配置 参数", 1, "require_product_version"),
            (CANON_5G, ACTIVE_PV_ID, "CANON_5G_CONCEPT", "concept",
             "5G概述", None,
             "5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。",
             "5G概念归并",
             "5G 第五代 移动通信 eMBB mMTC URLLC", 0, "none"),
            (CANON_PARAM, ACTIVE_PV_ID, "CANON_SET_PARAM", "parameter",
             "SET PARAM 命令参数", "SET PARAM",
             "SET PARAM 用于配置系统参数。",
             "SET PARAM 参考",
             "SET PARAM 配置 参数", 0, "none"),
        ],
    )

    # canonical_segment_sources (L2)
    await db.executemany(
        "INSERT INTO asset_canonical_segment_sources "
        "(id, publish_version_id, canonical_segment_id, raw_segment_id, "
        "relation_type, is_primary, priority, similarity_score, diff_summary, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (SOURCE_ADD_APN_UDG, ACTIVE_PV_ID, CANON_ADD_APN, RAW_SEG_ADD_APN_UDG,
             "version_variant", 1, 100, 0.95,
             "UDG版本参数列表与UNC不同", "{}"),
            (SOURCE_ADD_APN_UNC, ACTIVE_PV_ID, CANON_ADD_APN, RAW_SEG_ADD_APN_UNC,
             "version_variant", 0, 100, 0.92,
             "UNC版本语法与UDG有差异", "{}"),
            (SOURCE_5G, ACTIVE_PV_ID, CANON_5G, RAW_SEG_5G_CONCEPT,
             "primary", 1, 100, 1.0, None, "{}"),
            (SOURCE_CONFLICT, ACTIVE_PV_ID, CANON_ADD_APN, RAW_SEG_CONFLICT,
             "conflict_candidate", 0, 50, 0.70,
             "同一命令在UNC上的参数描述存在矛盾", "{}"),
        ],
    )

    await db.commit()


@pytest_asyncio.fixture
async def db_connection():
    """In-memory SQLite with schema from shared contract + seed data."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_data(db)
    yield db
    await db.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
