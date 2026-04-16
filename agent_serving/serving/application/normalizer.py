"""Query Normalizer — extract constraints from natural language queries."""
from __future__ import annotations

import re

from agent_serving.serving.schemas.models import NormalizedQuery

OP_MAP = {
    "新增": "ADD", "添加": "ADD", "创建": "ADD",
    "修改": "MOD", "更改": "MOD", "编辑": "MOD",
    "删除": "DEL", "移除": "DEL",
    "查询": "SHOW", "查看": "DSP", "显示": "LST",
    "设置": "SET", "配置": "SET",
}

COMMAND_RE = re.compile(
    r"\b(ADD|MOD|DEL|SET|SHOW|LST|DSP)\s+([A-Z][A-Z0-9_]*)\b", re.IGNORECASE
)

PRODUCT_RE = re.compile(
    r"\b(UDG|UNC|UPF|AMF|SMF|PCF|UDM|NRF|AUSF|BSF|NSSF)\b", re.IGNORECASE
)

VERSION_RE = re.compile(r"\b(V\d{3}R\d{3}C\d{2})\b")

NE_RE = re.compile(
    r"\b(AMF|SMF|UPF|UDM|PCF|NRF|AUSF|BSF|NSSF|SCP|UDSF|UDR)\b", re.IGNORECASE
)

PRODUCT_NAMES = {"UDG", "UNC", "UPF", "AMF", "SMF", "PCF", "UDM"}


class QueryNormalizer:
    def normalize(self, query: str) -> NormalizedQuery:
        command = self._extract_command(query)
        product = self._extract_product(query)
        product_version = self._extract_version(query)
        network_element = self._extract_ne(query, product)
        keywords = self._extract_keywords(query)
        missing = self._find_missing(command, product, product_version, network_element)

        return NormalizedQuery(
            command=command,
            product=product,
            product_version=product_version,
            network_element=network_element,
            keywords=keywords,
            missing_constraints=missing,
        )

    def _extract_command(self, query: str) -> str | None:
        match = COMMAND_RE.search(query)
        if match:
            return f"{match.group(1).upper()} {match.group(2).upper()}"

        for cn_word, cmd_prefix in OP_MAP.items():
            if cn_word in query:
                after = query.split(cn_word, 1)[-1]
                target_match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)", after)
                if target_match:
                    target = target_match.group(1).upper()
                    return f"{cmd_prefix} {target}"
                return cmd_prefix

        return None

    def _extract_product(self, query: str) -> str | None:
        match = PRODUCT_RE.search(query)
        return match.group(1).upper() if match else None

    def _extract_version(self, query: str) -> str | None:
        match = VERSION_RE.search(query)
        return match.group(1) if match else None

    def _extract_ne(self, query: str, product: str | None) -> str | None:
        for match in NE_RE.finditer(query):
            ne = match.group(1).upper()
            if ne != product:
                return ne
        return None

    def _extract_keywords(self, query: str) -> list[str]:
        cleaned = query
        for pattern in [COMMAND_RE, PRODUCT_RE, VERSION_RE, NE_RE]:
            cleaned = pattern.sub("", cleaned)
        tokens = [t for t in re.split(r"[\s,，、？?。.！!]+", cleaned) if len(t) > 0]
        return tokens

    def _find_missing(
        self,
        command: str | None,
        product: str | None,
        product_version: str | None,
        network_element: str | None,
    ) -> list[str]:
        missing: list[str] = []
        if command and not product:
            missing.append("product")
        if product and not product_version:
            missing.append("product_version")
        return missing
