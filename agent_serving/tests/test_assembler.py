"""Tests for ContextAssembler — context pack + conflict handling."""
import pytest
from agent_serving.serving.application.assembler import ContextAssembler
from agent_serving.serving.schemas.models import NormalizedQuery


def _make_canon(**overrides):
    base = {
        "id": "c1", "segment_type": "command", "title": "ADD APN",
        "canonical_text": "ADD APN 归并文本", "command_name": "ADD APN",
        "has_variants": 1, "variant_policy": "require_product_version",
    }
    base.update(overrides)
    return base


def _make_raw(**overrides):
    base = {
        "id": "r1", "segment_type": "command", "raw_text": "ADD APN 原始文本",
        "command_name": "ADD APN",
        "section_path": '["OM参考","ADD APN"]', "section_title": "ADD APN",
        "product": "UDG", "product_version": "V100R023C10",
        "network_element": "UDM", "document_key": "UDG_OM_REF",
        "relation_type": "version_variant", "diff_summary": None,
    }
    base.update(overrides)
    return base


def test_assemble_no_variants():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="5G是什么", intent="general",
        normalized=NormalizedQuery(keywords=["5G"]),
        canonical_hits=[_make_canon(has_variants=0, variant_policy="none")],
        drill_results=[], conflict_sources=[],
    )
    assert len(pack.answer_materials.canonical_segments) == 1
    assert len(pack.uncertainties) == 0


def test_assemble_with_variants_and_constraints_met():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="UDG V100R023C10 ADD APN", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", product="UDG", product_version="V100R023C10"),
        canonical_hits=[_make_canon()],
        drill_results=[_make_raw()], conflict_sources=[],
    )
    assert len(pack.answer_materials.raw_segments) == 1
    assert len(pack.uncertainties) == 0


def test_assemble_variants_but_missing_constraints():
    asm = ContextAssembler()
    pack = asm.assemble(
        query="ADD APN 怎么写", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN", missing_constraints=["product", "product_version"]),
        canonical_hits=[_make_canon()],
        drill_results=[], conflict_sources=[],
    )
    assert len(pack.uncertainties) > 0
    assert any(u.field == "product" for u in pack.uncertainties)


def test_assemble_conflict_candidates_become_uncertainties():
    """conflict_candidate must NOT appear as regular answer material."""
    asm = ContextAssembler()
    conflict = {
        "raw_text": "冲突版本文本", "segment_type": "command",
        "command_name": "ADD APN", "product": "UNC",
        "product_version": "V100R023C20", "network_element": "AMF",
        "relation_type": "conflict_candidate",
        "diff_summary": "同一命令在UNC上的参数描述存在矛盾",
    }
    pack = asm.assemble(
        query="ADD APN 参数说明", intent="command_usage",
        normalized=NormalizedQuery(command="ADD APN"),
        canonical_hits=[_make_canon()],
        drill_results=[], conflict_sources=[conflict],
    )
    assert len(pack.answer_materials.raw_segments) == 0
    assert any("冲突" in u.reason or "conflict" in u.reason.lower() for u in pack.uncertainties)
