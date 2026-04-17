"""Tests for QueryNormalizer — generic entity/scope extraction."""
import pytest
from agent_serving.serving.application.normalizer import QueryNormalizer, build_plan
from agent_serving.serving.schemas.models import EntityRef, QueryScope


@pytest.fixture
def normalizer():
    return QueryNormalizer()


def test_extract_command_with_product_and_version(normalizer):
    result = normalizer.normalize("UDG V100R023C10 ADD APN 怎么写")
    assert result.intent == "command_usage"
    assert any(e.type == "command" and e.name == "ADD APN" for e in result.entities)
    assert "UDG" in result.scope.products
    assert "V100R023C10" in result.scope.product_versions
    assert "product" not in result.missing_constraints


def test_extract_command_only(normalizer):
    result = normalizer.normalize("ADD APN 怎么写")
    assert result.intent == "command_usage"
    assert any(e.type == "command" for e in result.entities)
    assert "product" in result.missing_constraints


def test_extract_with_chinese_operation_word(normalizer):
    result = normalizer.normalize("新增APN怎么配置")
    assert result.intent == "command_usage"
    assert any(e.type == "command" and "ADD" in e.name for e in result.entities)


def test_extract_with_network_element(normalizer):
    result = normalizer.normalize("AMF ADD APN 怎么写")
    assert result.intent == "command_usage"
    assert any(e.type == "command" and e.name == "ADD APN" for e in result.entities)
    # AMF is a network element, not a product
    assert "AMF" in result.scope.network_elements
    assert "AMF" not in result.scope.products


def test_general_query_no_command(normalizer):
    result = normalizer.normalize("5G是什么")
    assert result.intent in ("concept_lookup", "general")
    assert not any(e.type == "command" for e in result.entities)
    assert any("5G" in kw for kw in result.keywords)


def test_mod_command(normalizer):
    result = normalizer.normalize("修改APN的参数")
    assert any(e.type == "command" and "MOD" in e.name for e in result.entities)


def test_del_command(normalizer):
    result = normalizer.normalize("删除APN配置")
    assert any(e.type == "command" and "DEL" in e.name for e in result.entities)


def test_troubleshooting_intent(normalizer):
    result = normalizer.normalize("CPU过载告警怎么排查")
    assert result.intent == "troubleshooting"


def test_concept_lookup_intent(normalizer):
    result = normalizer.normalize("5G是什么")
    assert result.intent == "concept_lookup"


def test_build_plan_from_normalized(normalizer):
    normalized = normalizer.normalize("UDG V100R023C10 ADD APN 怎么写")
    plan = build_plan(normalized)
    assert plan.intent == "command_usage"
    assert any(c.type == "command" and c.name == "ADD APN" for c in plan.entity_constraints)
    assert "UDG" in plan.scope_constraints.products
    assert "V100R023C10" in plan.scope_constraints.product_versions
    assert plan.conflict_policy == "flag_not_answer"
    assert plan.expansion.use_ontology is False


def test_build_plan_variant_policy_disambiguation(normalizer):
    normalized = normalizer.normalize("ADD APN 怎么写")
    plan = build_plan(normalized)
    assert plan.variant_policy == "require_disambiguation"


def test_desired_roles_for_command_usage(normalizer):
    result = normalizer.normalize("ADD APN 怎么写")
    assert "parameter" in result.desired_semantic_roles
    assert "example" in result.desired_semantic_roles


def test_desired_roles_for_troubleshooting(normalizer):
    result = normalizer.normalize("CPU过载告警怎么排查")
    assert "troubleshooting_step" in result.desired_semantic_roles


def test_smf_is_network_element_not_product(normalizer):
    result = normalizer.normalize("SMF 配置 S-NSSAI")
    assert "SMF" in result.scope.network_elements
    assert "SMF" not in result.scope.products


def test_cloudcore_recognized_as_product(normalizer):
    result = normalizer.normalize("CloudCore 5G 概念")
    assert "CLOUDCORE" in result.scope.products


def test_version_without_c_match(normalizer):
    result = normalizer.normalize("UDG V100R023 ADD APN")
    assert "V100R023" in result.scope.product_versions
