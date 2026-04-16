"""Tests for QueryNormalizer — constraint extraction from natural language."""
import pytest
from agent_serving.serving.application.normalizer import QueryNormalizer


@pytest.fixture
def normalizer():
    return QueryNormalizer()


def test_extract_command_with_product_and_version(normalizer):
    result = normalizer.normalize("UDG V100R023C10 ADD APN 怎么写")
    assert result.command == "ADD APN"
    assert result.product == "UDG"
    assert result.product_version == "V100R023C10"
    assert "product" not in result.missing_constraints


def test_extract_command_only(normalizer):
    result = normalizer.normalize("ADD APN 怎么写")
    assert result.command == "ADD APN"
    assert "product" in result.missing_constraints
    # product_version only flagged when product is present
    assert "product_version" not in result.missing_constraints


def test_extract_with_chinese_operation_word(normalizer):
    result = normalizer.normalize("新增APN怎么配置")
    assert result.command == "ADD APN"


def test_extract_with_network_element_after_space(normalizer):
    result = normalizer.normalize("AMF ADD APN 怎么写")
    assert result.command == "ADD APN"
    # AMF is in both product and NE regex; matched as product first
    assert result.product == "AMF"


def test_general_query_no_command(normalizer):
    result = normalizer.normalize("5G是什么")
    assert result.command is None
    # Keywords include the full remaining text token
    assert any("5G" in kw for kw in result.keywords)


def test_mod_command(normalizer):
    result = normalizer.normalize("修改APN的参数")
    assert result.command == "MOD APN"


def test_del_command(normalizer):
    result = normalizer.normalize("删除APN配置")
    assert result.command == "DEL APN"


def test_show_command(normalizer):
    result = normalizer.normalize("查询APN配置")
    assert result.command in ("SHOW APN", "LST APN", "DSP APN")


def test_version_extraction(normalizer):
    result = normalizer.normalize("UPF V200R001C00 SET PROFILE 怎么配")
    assert result.product == "UPF"
    assert result.product_version == "V200R001C00"
    assert result.command == "SET PROFILE"
