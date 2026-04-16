"""Verify data models instantiate correctly with v0.4 fields."""
from knowledge_mining.mining.models import (
    CanonicalSegmentData,
    ContentBlock,
    DocumentProfile,
    RawDocumentData,
    RawSegmentData,
    SectionNode,
    SourceMappingData,
)


def test_raw_document_data_with_manifest():
    doc = RawDocumentData(
        file_path="test.md",
        content="# Hello",
        manifest_meta={"doc_id": "D001", "doc_type": "command", "nf": ["UDG5000"]},
    )
    assert doc.file_path == "test.md"
    assert doc.manifest_meta["doc_id"] == "D001"
    assert doc.frontmatter == {}


def test_document_profile_generic_scope():
    profile = DocumentProfile(
        file_path="test.md",
        source_type="expert_authored",
        document_type="expert_note",
        scope_json={"author": "Zhang San", "scenario": "5GC"},
        tags_json=["5G", "core"],
    )
    assert profile.source_type == "expert_authored"
    assert profile.product is None
    assert "5G" in profile.tags_json


def test_document_profile_product_facet():
    profile = DocumentProfile(
        file_path="cmd.md",
        source_type="productdoc_export",
        document_type="command",
        scope_json={"product": "UDG5000", "version": "V100R005"},
        product="UDG5000",
        product_version="V100R005",
    )
    assert profile.product == "UDG5000"


def test_content_block_html_table():
    block = ContentBlock(block_type="html_table", text="<table><tr><td>val</td></tr></table>")
    assert block.block_type == "html_table"
    assert "<table>" in block.text


def test_content_block_unknown():
    block = ContentBlock(block_type="unknown", text="some raw text")
    assert block.block_type == "unknown"


def test_raw_segment_data_block_type_and_section_role():
    seg = RawSegmentData(
        document_file_path="test.md",
        segment_index=0,
        section_path=["Root", "Parameters"],
        section_title="Parameters",
        heading_level=2,
        segment_type="parameter",
        block_type="table",
        section_role="parameter",
        raw_text="param | value",
        content_hash="abc123",
    )
    assert seg.block_type == "table"
    assert seg.section_role == "parameter"
    assert seg.structure_json == {}
    assert seg.source_offsets_json == {}


def test_canonical_segment_data_with_section_role():
    canon = CanonicalSegmentData(
        canonical_key="c1",
        segment_type="command",
        section_role="procedure_step",
        title="ADD APN",
        canonical_text="ADD APN ...",
        search_text="add apn",
        has_variants=False,
        variant_policy="merge",
        command_name="ADD APN",
        raw_segment_refs=["s1", "s2"],
    )
    assert canon.section_role == "procedure_step"
    assert len(canon.raw_segment_refs) == 2


def test_source_mapping_data():
    mapping = SourceMappingData(
        canonical_key="c1",
        raw_segment_ref="s1",
        relation_type="exact_duplicate",
    )
    assert mapping.relation_type == "exact_duplicate"


def test_section_node_tree():
    child = SectionNode(title="Sub", level=2, blocks=())
    parent = SectionNode(title="Root", level=1, children=(child,))
    assert parent.children[0].title == "Sub"
