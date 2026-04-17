"""Tests for EvidenceAssembler — evidence pack + conflict/variant handling."""
import json
import pytest
from agent_serving.serving.application.assembler import EvidenceAssembler
from agent_serving.serving.schemas.models import (
    EntityRef, NormalizedQuery, QueryPlan, QueryScope,
)


def _make_canon(**overrides):
    base = {
        "id": "c1", "canonical_key": "CANON_TEST",
        "block_type": "paragraph", "semantic_role": "parameter",
        "title": "ADD APN", "canonical_text": "ADD APN 归并文本",
        "summary": None, "search_text": "ADD APN",
        "entity_refs_json": json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
        "scope_json": json.dumps({"products": ["UDG", "UNC"], "product_versions": [],
                                  "network_elements": [], "projects": [], "domains": []}),
        "has_variants": 1, "variant_policy": "require_scope",
        "quality_score": 0.9,
    }
    base.update(overrides)
    return base


def _make_evidence(**overrides):
    base = {
        "id": "r1", "block_type": "paragraph", "semantic_role": "parameter",
        "raw_text": "ADD APN 原始文本",
        "section_path": json.dumps([{"title": "OM参考", "level": 2}, {"title": "ADD APN", "level": 3}]),
        "section_title": "ADD APN",
        "entity_refs_json": json.dumps([{"type": "command", "name": "ADD APN", "normalized_name": "ADD APN"}]),
        "structure_json": "{}",
        "source_offsets_json": "{}",
        "document_key": "UDG_OM_REF", "relative_path": "udg_om.md",
        "file_type": "markdown", "document_type": "command",
        "tags_json": json.dumps(["command", "core_network"]),
        "doc_scope_json": json.dumps({"products": ["UDG"], "product_versions": ["V100R023C10"],
                                      "network_elements": ["UDM"], "projects": [], "domains": []}),
        "relation_type": "primary", "diff_summary": None, "source_metadata": "{}",
    }
    base.update(overrides)
    return base


def _make_plan(**overrides):
    defaults = {
        "intent": "command_usage",
        "entity_constraints": [EntityRef(type="command", name="ADD APN", normalized_name="ADD APN")],
        "scope_constraints": QueryScope(products=["UDG"], product_versions=["V100R023C10"]),
    }
    defaults.update(overrides)
    return QueryPlan(**defaults)


def _make_normalized(**overrides):
    defaults = {
        "intent": "command_usage",
        "entities": [EntityRef(type="command", name="ADD APN", normalized_name="ADD APN")],
        "scope": QueryScope(products=["UDG"], product_versions=["V100R023C10"]),
        "keywords": [],
        "missing_constraints": [],
    }
    defaults.update(overrides)
    return NormalizedQuery(**defaults)


def test_assemble_basic_evidence():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([_make_evidence()], [], [])],
    )
    assert len(pack.canonical_items) == 1
    assert len(pack.evidence_items) == 1
    assert pack.canonical_items[0].block_type == "paragraph"
    assert pack.evidence_items[0].raw_text == "ADD APN 原始文本"


def test_assemble_no_variants():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="5G是什么", intent="concept_lookup",
        normalized=_make_normalized(intent="concept_lookup", entities=[], missing_constraints=[]),
        plan=_make_plan(intent="concept_lookup", entity_constraints=[]),
        canonical_hits=[_make_canon(has_variants=0, variant_policy="none")],
        drill_results=[],
    )
    assert len(pack.canonical_items) == 1
    assert len(pack.gaps) == 0


def test_assemble_conflict_not_in_evidence():
    """conflict_candidate must NOT appear as evidence, only in conflicts."""
    asm = EvidenceAssembler()
    conflict_row = _make_evidence(
        raw_text="冲突版本文本",
        doc_scope_json=json.dumps({"products": ["UNC"], "product_versions": ["V100R023C20"],
                                   "network_elements": ["AMF"], "projects": [], "domains": []}),
        relation_type="conflict_candidate",
        diff_summary="同一命令在UNC上的参数描述存在矛盾",
    )
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([_make_evidence()], [], [conflict_row])],
    )
    assert len(pack.evidence_items) == 1
    assert len(pack.conflicts) == 1
    assert "冲突" in pack.conflicts[0].raw_text
    # Conflict must not appear in evidence
    evidence_texts = [e.raw_text for e in pack.evidence_items]
    assert all("冲突版本文本" not in t for t in evidence_texts)


def test_assemble_gaps_for_missing_scope():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="ADD APN 怎么写", intent="command_usage",
        normalized=_make_normalized(
            scope=QueryScope(), missing_constraints=["product", "product_version"],
        ),
        plan=_make_plan(scope_constraints=QueryScope()),
        canonical_hits=[_make_canon()],
        drill_results=[],
    )
    assert len(pack.gaps) >= 1
    gap_fields = [g.field for g in pack.gaps]
    assert "product" in gap_fields


def test_assemble_source_has_scope():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="UDG ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([_make_evidence()], [], [])],
    )
    assert len(pack.sources) == 1
    assert "UDG" in pack.sources[0].scope.products
    assert pack.sources[0].document_key == "UDG_OM_REF"


def test_assemble_matched_entities():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[],
    )
    assert any(e.type == "command" and e.name == "ADD APN" for e in pack.matched_entities)


def test_assemble_followups_on_conflict():
    asm = EvidenceAssembler()
    conflict_row = _make_evidence(
        raw_text="冲突版本文本", relation_type="conflict_candidate",
        diff_summary="参数矛盾",
    )
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([], [], [conflict_row])],
    )
    assert len(pack.suggested_followups) > 0
    assert any("冲突" in f for f in pack.suggested_followups)


def test_assemble_structure_preserved():
    """structure_json must pass through to EvidenceItem."""
    asm = EvidenceAssembler()
    ev = _make_evidence(
        block_type="table",
        structure_json=json.dumps({"columns": ["参数", "类型"], "rows": [["APN", "string"]]}),
        source_offsets_json=json.dumps({"start": 10, "end": 200}),
    )
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([ev], [], [])],
    )
    assert pack.evidence_items[0].structure["columns"] == ["参数", "类型"]
    assert pack.evidence_items[0].source_offsets["start"] == 10


def test_assemble_unparsed_docs():
    """Unparsed documents should appear in the pack."""
    asm = EvidenceAssembler()
    unparsed = [
        {"id": "doc-1", "document_key": "SAMPLE_PDF", "relative_path": "sample.pdf",
         "file_type": "pdf", "document_type": "reference",
         "scope_json": json.dumps({"products": ["UDG"]})},
    ]
    pack = asm.assemble(
        query="5G是什么", intent="concept_lookup",
        normalized=_make_normalized(intent="concept_lookup", entities=[], missing_constraints=[]),
        plan=_make_plan(intent="concept_lookup", entity_constraints=[]),
        canonical_hits=[], drill_results=[],
        unparsed_docs=unparsed,
    )
    assert len(pack.unparsed_documents) == 1
    assert pack.unparsed_documents[0].document_key == "SAMPLE_PDF"
    assert pack.unparsed_documents[0].file_type == "pdf"


def test_assemble_source_has_file_type():
    asm = EvidenceAssembler()
    pack = asm.assemble(
        query="ADD APN", intent="command_usage",
        normalized=_make_normalized(),
        plan=_make_plan(),
        canonical_hits=[_make_canon()],
        drill_results=[([_make_evidence()], [], [])],
    )
    assert pack.sources[0].file_type == "markdown"
    assert pack.sources[0].document_type == "command"
    assert "command" in pack.sources[0].tags
