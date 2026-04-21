"""Shared test fixtures: SQLite from shared DDL + v0.5 seed data.

Schema tables are created directly from
`databases/asset_core/schemas/001_asset_core.sqlite.sql`. This file only
inserts test data — no private DDL.

Seed data covers:
- command entity + feature entity (not command-only)
- scope_variant + conflict_candidate + require_scope
- multiple block_type/semantic_role combinations
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
import aiosqlite

from agent_serving.serving.repositories.schema_adapter import create_asset_tables_sqlite

# Fixed IDs for deterministic tests
ACTIVE_PV_ID = "11111111-1111-1111-1111-111111111111"
BATCH_ID = "99999999-9999-9999-9999-999999999999"

DOC_COMMAND_UDG = "22222222-2222-2222-2222-222222222222"
DOC_COMMAND_UNC = "33333333-3333-3333-3333-333333333333"
DOC_FEATURE = "44444444-4444-4444-4444-444444444444"
DOC_TROUBLESHOOT = "55555555-5555-5555-5555-555555555555"

# raw_segments
RS_ADD_APN_UDG = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
RS_ADD_APN_UNC = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RS_5G_CONCEPT = "cccccccc-cccc-cccc-cccc-cccccccccccc"
RS_CONFLICT = "dddddddd-dddd-dddd-dddd-dddddddddddd"
RS_DNN_FEATURE = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
RS_ALARM_STEP = "ffffffff-ffff-ffff-ffff-ffffffffffff"

# canonical_segments
CANON_ADD_APN = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CANON_5G = "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CANON_DNN = "33333333-cccc-cccc-cccc-cccccccccccc"
CANON_ALARM = "44444444-dddd-dddd-dddd-dddddddddddd"

# canonical_segment_sources
SRC_ADD_APN_UDG = "aaaa0000-0000-0000-0000-000000000001"
SRC_ADD_APN_UNC = "aaaa0000-0000-0000-0000-000000000002"
SRC_5G = "aaaa0000-0000-0000-0000-000000000003"
SRC_CONFLICT = "aaaa0000-0000-0000-0000-000000000004"
SRC_DNN = "aaaa0000-0000-0000-0000-000000000005"
SRC_ALARM = "aaaa0000-0000-0000-0000-000000000006"

SEED_IDS = {
    "active_pv_id": ACTIVE_PV_ID,
    "doc_command_udg": DOC_COMMAND_UDG,
    "doc_command_unc": DOC_COMMAND_UNC,
    "doc_feature": DOC_FEATURE,
    "doc_troubleshoot": DOC_TROUBLESHOOT,
    "rs_add_apn_udg": RS_ADD_APN_UDG,
    "rs_add_apn_unc": RS_ADD_APN_UNC,
    "rs_5g_concept": RS_5G_CONCEPT,
    "rs_conflict": RS_CONFLICT,
    "rs_dnn_feature": RS_DNN_FEATURE,
    "rs_alarm_step": RS_ALARM_STEP,
    "canon_add_apn": CANON_ADD_APN,
    "canon_5g": CANON_5G,
    "canon_dnn": CANON_DNN,
    "canon_alarm": CANON_ALARM,
    "src_add_apn_udg": SRC_ADD_APN_UDG,
    "src_add_apn_unc": SRC_ADD_APN_UNC,
    "src_5g": SRC_5G,
    "src_conflict": SRC_CONFLICT,
    "src_dnn": SRC_DNN,
    "src_alarm": SRC_ALARM,
}


async def _seed_data(db: aiosqlite.Connection) -> None:
    """Insert deterministic v0.5 seed data using parameterized queries."""

    # source_batches
    await db.execute(
        "INSERT INTO asset_source_batches (id, batch_code, source_type, description, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (BATCH_ID, "BATCH-2026-04-17-001", "folder_scan", "M1 test batch",
         "2026-04-17T00:00:00Z", json.dumps({
             "default_document_type": "command",
             "batch_scope": {"product": "CloudCore", "product_version": "V100R023"},
         })),
    )

    # publish_versions
    await db.execute(
        "INSERT INTO asset_publish_versions "
        "(id, version_code, status, source_batch_id, description, build_started_at, activated_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ACTIVE_PV_ID, "PV-2026-04-17-v1", "active", BATCH_ID, "M1 test seed",
         "2026-04-17T00:00:00Z", "2026-04-17T00:01:00Z", "{}"),
    )

    # raw_documents — v0.5: scope_json instead of product/product_version/network_element
    await db.executemany(
        "INSERT INTO asset_raw_documents "
        "(id, publish_version_id, document_key, source_uri, relative_path, file_name, file_type, "
        "source_type, title, document_type, content_hash, created_at, scope_json, tags_json, "
        "structure_quality, processing_profile_json, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # Command doc — UDG
            (DOC_COMMAND_UDG, ACTIVE_PV_ID, "UDG_OM_REF", "file:///docs/udg_om.md",
             "udg_om.md", "udg_om.md", "markdown", "folder_scan",
             "UDG OM参考手册", "command", "hash_udg_om", "2026-04-17T00:00:00Z",
             json.dumps({"products": ["UDG"], "product_versions": ["V100R023C10"],
                         "network_elements": ["UDM"], "projects": [], "domains": []}),
             json.dumps(["command", "core_network"]),
             "markdown_native", "{}", "{}"),
            # Command doc — UNC
            (DOC_COMMAND_UNC, ACTIVE_PV_ID, "UNC_OM_REF", "file:///docs/unc_om.md",
             "unc_om.md", "unc_om.md", "markdown", "folder_scan",
             "UNC OM参考手册", "command", "hash_unc_om", "2026-04-17T00:00:00Z",
             json.dumps({"products": ["UNC"], "product_versions": ["V100R023C20"],
                         "network_elements": ["AMF"], "projects": [], "domains": []}),
             json.dumps(["command", "core_network"]),
             "markdown_native", "{}", "{}"),
            # Feature doc
            (DOC_FEATURE, ACTIVE_PV_ID, "5G_FEATURES", "file:///docs/5g_features.md",
             "5g_features.md", "5g_features.md", "markdown", "folder_scan",
             "5G特性与功能", "feature", "hash_5g_features", "2026-04-17T00:00:00Z",
             json.dumps({"products": ["CloudCore"], "product_versions": ["V100R023"],
                         "network_elements": [], "projects": [], "domains": ["5G"]}),
             json.dumps(["feature", "5g"]),
             "markdown_native", "{}", "{}"),
            # Troubleshooting doc
            (DOC_TROUBLESHOOT, ACTIVE_PV_ID, "ALARM_GUIDE", "file:///docs/alarm_guide.md",
             "alarm_guide.md", "alarm_guide.md", "markdown", "folder_scan",
             "告警处理指南", "troubleshooting", "hash_alarm", "2026-04-17T00:00:00Z",
             json.dumps({"products": ["UDG"], "product_versions": ["V100R023C10"],
                         "network_elements": ["UDM"], "projects": [], "domains": ["OM"]}),
             json.dumps(["alarm", "troubleshooting"]),
             "markdown_native", "{}", "{}"),
        ],
    )

    # raw_segments — v0.5: block_type/semantic_role/entity_refs_json instead of command_name/segment_type
    await db.executemany(
        "INSERT INTO asset_raw_segments "
        "(id, publish_version_id, raw_document_id, segment_key, segment_index, "
        "section_path, section_title, block_type, semantic_role, raw_text, normalized_text, "
        "content_hash, normalized_hash, entity_refs_json, structure_json, source_offsets_json, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # ADD APN command on UDG
            (RS_ADD_APN_UDG, ACTIVE_PV_ID, DOC_COMMAND_UDG, "UDG_ADD_APN", 0,
             json.dumps([{"title": "MML命令", "level": 2}, {"title": "ADD APN", "level": 3}]),
             "ADD APN", "paragraph", "parameter",
             "ADD APN 命令用于在UDG上新增APN配置。语法：ADD APN=<apn-name>,[参数列表]",
             "add apn 命令用于在udg上新增apn配置",
             "hash_udg_add_apn", "nhash_udg_add_apn",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"},
                         {"type": "network_element", "name": "UDM", "normalized_name": "UDM"}]),
             "{}", "{}", "{}"),
            # ADD APN command on UNC
            (RS_ADD_APN_UNC, ACTIVE_PV_ID, DOC_COMMAND_UNC, "UNC_ADD_APN", 0,
             json.dumps([{"title": "MML命令", "level": 2}, {"title": "ADD APN", "level": 3}]),
             "ADD APN", "paragraph", "parameter",
             "ADD APN 命令用于在UNC上新增APN配置。语法与UDG版本有差异：ADD APN=<name>,TYPE=<type>,[参数列表]",
             "add apn 命令用于在unc上新增apn配置",
             "hash_unc_add_apn", "nhash_unc_add_apn",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"},
                         {"type": "network_element", "name": "AMF", "normalized_name": "AMF"}]),
             "{}", "{}", "{}"),
            # 5G concept
            (RS_5G_CONCEPT, ACTIVE_PV_ID, DOC_FEATURE, "5G_INTRO", 0,
             json.dumps([{"title": "5G概述", "level": 1}]),
             "5G概述", "paragraph", "concept",
             "5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。",
             "5g是第五代移动通信技术",
             "hash_5g", "nhash_5g",
             json.dumps([{"type": "term", "name": "5G", "normalized_name": "5g"},
                         {"type": "term", "name": "eMBB", "normalized_name": "embb"},
                         {"type": "term", "name": "mMTC", "normalized_name": "mmtc"}]),
             "{}", "{}", "{}"),
            # Conflict candidate
            (RS_CONFLICT, ACTIVE_PV_ID, DOC_COMMAND_UNC, "UNC_ADD_APN_CONFLICT", 1,
             json.dumps([{"title": "MML命令", "level": 2}, {"title": "ADD APN", "level": 3}]),
             "ADD APN", "paragraph", "parameter",
             "ADD APN 参数冲突版本：APN=<name>是必填参数，与UDG版本完全不同。",
             "add apn 参数冲突版本",
             "hash_conflict", "nhash_conflict",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             "{}", "{}", "{}"),
            # DNN feature
            (RS_DNN_FEATURE, ACTIVE_PV_ID, DOC_FEATURE, "DNN_FEATURE", 1,
             json.dumps([{"title": "DNN本地疏通", "level": 2}]),
             "DNN本地疏通", "paragraph", "example",
             "DNN本地疏通（Local Breakout）允许特定数据流在本地UPF疏导而不经过中心网关。"
             "配置步骤：1. 创建DNN profile 2. 绑定UPF 3. 配置路由策略。",
             "dnn本地疏通 local breakout 允许特定数据流在本地upf疏导",
             "hash_dnn", "nhash_dnn",
             json.dumps([{"type": "feature", "name": "Local Breakout", "normalized_name": "local breakout"},
                         {"type": "network_element", "name": "UPF", "normalized_name": "UPF"}]),
             "{}", "{}", "{}"),
            # Alarm troubleshooting step
            (RS_ALARM_STEP, ACTIVE_PV_ID, DOC_TROUBLESHOOT, "ALARM_CPU_HIGH", 0,
             json.dumps([{"title": "CPU过载告警", "level": 2}]),
             "CPU过载告警", "list", "troubleshooting_step",
             "CPU过载告警处理：1. 检查当前CPU使用率 SHOW CPU 2. 排查高负载进程 3. 执行流量控制或负载均衡。",
             "cpu过载告警处理 检查当前cpu使用率 排查高负载进程",
             "hash_alarm", "nhash_alarm",
             json.dumps([{"type": "alarm", "name": "CPU_OVERLOAD", "normalized_name": "cpu_overload"},
                         {"type": "command", "name": "SHOW CPU", "normalized_name": "SHOW CPU"}]),
             json.dumps({"ordered": True, "items": ["检查CPU使用率", "排查高负载进程", "执行流量控制"]}),
             "{}", "{}"),
        ],
    )

    # canonical_segments — v0.5: entity_refs_json/scope_json/block_type/semantic_role
    await db.executemany(
        "INSERT INTO asset_canonical_segments "
        "(id, publish_version_id, canonical_key, block_type, semantic_role, title, "
        "canonical_text, summary, search_text, entity_refs_json, scope_json, "
        "has_variants, variant_policy, quality_score, created_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # ADD APN canonical — has variants across products
            (CANON_ADD_APN, ACTIVE_PV_ID, "CANON_ADD_APN", "paragraph", "parameter",
             "ADD APN 命令", "ADD APN 命令用于新增APN配置。不同产品的参数列表有差异。",
             "ADD APN 归并命令参考", "ADD APN 命令 新增 APN 配置 参数",
             json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
             json.dumps({"products": ["UDG", "UNC"], "product_versions": ["V100R023C10", "V100R023C20"],
                         "network_elements": ["UDM", "AMF"], "projects": [], "domains": []}),
             1, "require_scope", 0.9, "2026-04-17T00:00:00Z",
             json.dumps({"canonicalization": {"method": "merge", "source_count": 3}})),
            # 5G concept canonical — no variants
            (CANON_5G, ACTIVE_PV_ID, "CANON_5G_CONCEPT", "paragraph", "concept",
             "5G概述", "5G是第五代移动通信技术，支持增强移动宽带、海量机器通信和超高可靠低时延通信三大场景。",
             "5G概念归并", "5G 第五代 移动通信 eMBB mMTC URLLC",
             json.dumps([{"type": "term", "name": "5G", "normalized_name": "5g"}]),
             json.dumps({"products": ["CloudCore"], "product_versions": [],
                         "network_elements": [], "projects": [], "domains": ["5G"]}),
             0, "none", 0.95, "2026-04-17T00:00:00Z",
             json.dumps({"canonicalization": {"method": "primary_only", "source_count": 1}})),
            # DNN feature canonical — no variants
            (CANON_DNN, ACTIVE_PV_ID, "CANON_DNN_LB", "paragraph", "example",
             "DNN本地疏通", "DNN本地疏通（Local Breakout）允许特定数据流在本地UPF疏导而不经过中心网关。",
             "DNN本地疏通配置", "DNN 本地疏通 Local Breakout UPF 配置",
             json.dumps([{"type": "feature", "name": "Local Breakout", "normalized_name": "local breakout"},
                         {"type": "network_element", "name": "UPF", "normalized_name": "UPF"}]),
             json.dumps({"products": ["CloudCore"], "product_versions": ["V100R023"],
                         "network_elements": ["UPF"], "projects": [], "domains": []}),
             0, "none", 0.88, "2026-04-17T00:00:00Z",
             json.dumps({"canonicalization": {"method": "primary_only", "source_count": 1}})),
            # Alarm troubleshooting canonical — no variants
            (CANON_ALARM, ACTIVE_PV_ID, "CANON_CPU_ALARM", "list", "troubleshooting_step",
             "CPU过载告警处理", "CPU过载告警处理步骤：检查CPU使用率、排查高负载进程、执行流量控制或负载均衡。",
             "CPU 过载 告警 处理 排查", "CPU过载 告警处理 排查 CPU使用率 流量控制",
             json.dumps([{"type": "alarm", "name": "CPU_OVERLOAD", "normalized_name": "cpu_overload"}]),
             json.dumps({"products": ["UDG"], "product_versions": ["V100R023C10"],
                         "network_elements": ["UDM"], "projects": [], "domains": ["OM"]}),
             0, "none", 0.85, "2026-04-17T00:00:00Z",
             json.dumps({"canonicalization": {"method": "primary_only", "source_count": 1}})),
        ],
    )

    # canonical_segment_sources (L2)
    await db.executemany(
        "INSERT INTO asset_canonical_segment_sources "
        "(id, publish_version_id, canonical_segment_id, raw_segment_id, "
        "relation_type, is_primary, priority, similarity_score, diff_summary, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # ADD APN: UDG primary
            (SRC_ADD_APN_UDG, ACTIVE_PV_ID, CANON_ADD_APN, RS_ADD_APN_UDG,
             "primary", 1, 100, 0.95, None,
             json.dumps({"variant_dimensions": []})),
            # ADD APN: UNC scope_variant
            (SRC_ADD_APN_UNC, ACTIVE_PV_ID, CANON_ADD_APN, RS_ADD_APN_UNC,
             "scope_variant", 0, 100, 0.92, "UNC版本语法与UDG有差异",
             json.dumps({"variant_dimensions": ["product_version", "network_elements"],
                         "primary_scope": {"product_versions": ["V100R023C10"], "network_elements": ["UDM"]},
                         "source_scope": {"product_versions": ["V100R023C20"], "network_elements": ["AMF"]}})),
            # 5G: primary
            (SRC_5G, ACTIVE_PV_ID, CANON_5G, RS_5G_CONCEPT,
             "primary", 1, 100, 1.0, None, "{}"),
            # ADD APN: conflict_candidate
            (SRC_CONFLICT, ACTIVE_PV_ID, CANON_ADD_APN, RS_CONFLICT,
             "conflict_candidate", 0, 50, 0.70, "同一命令在UNC上的参数描述存在矛盾",
             json.dumps({"primary_scope": {"product_versions": ["V100R023C10"]},
                         "source_scope": {"product_versions": ["V100R023C20"]}})),
            # DNN: primary
            (SRC_DNN, ACTIVE_PV_ID, CANON_DNN, RS_DNN_FEATURE,
             "primary", 1, 100, 1.0, None, "{}"),
            # Alarm: primary
            (SRC_ALARM, ACTIVE_PV_ID, CANON_ALARM, RS_ALARM_STEP,
             "primary", 1, 100, 1.0, None, "{}"),
        ],
    )

    await db.commit()


@pytest_asyncio.fixture
async def db_connection():
    """In-memory SQLite with schema from shared DDL + v0.5 seed data."""
    db = await aiosqlite.connect(":memory:")
    db.row_factory = aiosqlite.Row
    await create_asset_tables_sqlite(db)
    await _seed_data(db)
    yield db
    await db.close()


@pytest.fixture
def seed_ids():
    return SEED_IDS
