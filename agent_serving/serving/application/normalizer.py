"""Query Normalizer — extract entities, scope, and intent from queries.

Outputs a generic NormalizedQuery with entities[] + scope{} + intent.
Commands are just one entity type among many (command, feature, term, alarm).
build_plan() converts normalized query to a QueryPlan for repository use.
"""
from __future__ import annotations

import re

from agent_serving.serving.schemas.models import (
    EntityRef,
    EvidenceBudget,
    ExpansionConfig,
    NormalizedQuery,
    QueryPlan,
    QueryScope,
)

# --- Rule-based extraction patterns ---

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

INTENT_COMMAND_KEYWORDS = {"命令", "用法", "参数", "格式", "语法", "怎么写", "如何配置"}
INTENT_TROUBLESHOOT_KEYWORDS = {"故障", "排查", "告警", "错误", "异常", "处理"}
INTENT_CONCEPT_KEYWORDS = {"是什么", "什么是", "概念", "介绍", "概述", "原理"}
INTENT_PROCEDURE_KEYWORDS = {"步骤", "流程", "操作", "怎么做", "如何操作"}


class QueryNormalizer:
    def normalize(self, query: str) -> NormalizedQuery:
        entities = self._extract_entities(query)
        scope = self._extract_scope(query)
        intent = self._detect_intent(query, entities)
        keywords = self._extract_keywords(query)
        missing = self._find_missing(entities, scope, intent)
        desired_roles = self._desired_roles_for_intent(intent)

        return NormalizedQuery(
            intent=intent,
            entities=entities,
            scope=scope,
            keywords=keywords,
            desired_semantic_roles=desired_roles,
            missing_constraints=missing,
        )

    def _extract_entities(self, query: str) -> list[EntityRef]:
        entities: list[EntityRef] = []
        seen: set[str] = set()

        # Extract command entities
        cmd = self._extract_command(query)
        if cmd:
            key = f"command:{cmd}"
            if key not in seen:
                entities.append(EntityRef(type="command", name=cmd, normalized_name=cmd))
                seen.add(key)

        return entities

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

    def _extract_scope(self, query: str) -> QueryScope:
        products: list[str] = []
        product_versions: list[str] = []
        network_elements: list[str] = []

        for m in PRODUCT_RE.finditer(query):
            p = m.group(1).upper()
            if p not in products:
                products.append(p)

        v = VERSION_RE.search(query)
        if v:
            product_versions.append(v.group(1))

        for m in NE_RE.finditer(query):
            ne = m.group(1).upper()
            if ne not in products and ne not in network_elements:
                network_elements.append(ne)

        return QueryScope(
            products=products,
            product_versions=product_versions,
            network_elements=network_elements,
        )

    def _detect_intent(self, query: str, entities: list[EntityRef]) -> str:
        has_command = any(e.type == "command" for e in entities)

        if has_command:
            return "command_usage"

        for kw in INTENT_TROUBLESHOOT_KEYWORDS:
            if kw in query:
                return "troubleshooting"

        for kw in INTENT_PROCEDURE_KEYWORDS:
            if kw in query:
                return "procedure"

        for kw in INTENT_CONCEPT_KEYWORDS:
            if kw in query:
                return "concept_lookup"

        return "general"

    def _extract_keywords(self, query: str) -> list[str]:
        cleaned = query
        for pattern in [COMMAND_RE, PRODUCT_RE, VERSION_RE, NE_RE]:
            cleaned = pattern.sub("", cleaned)
        tokens = [t for t in re.split(r"[\s,，、？?。.！!]+", cleaned) if len(t) > 0]
        return tokens

    def _find_missing(
        self, entities: list[EntityRef], scope: QueryScope, intent: str
    ) -> list[str]:
        missing: list[str] = []
        if intent == "command_usage":
            if not scope.products:
                missing.append("product")
            if scope.products and not scope.product_versions:
                missing.append("product_version")
        return missing

    def _desired_roles_for_intent(self, intent: str) -> list[str]:
        role_map: dict[str, list[str]] = {
            "command_usage": ["parameter", "example", "procedure_step"],
            "troubleshooting": ["troubleshooting_step", "alarm", "constraint"],
            "concept_lookup": ["concept", "note"],
            "procedure": ["procedure_step", "parameter", "example"],
            "comparison": ["concept", "parameter", "constraint"],
            "general": [],
        }
        return role_map.get(intent, [])


def build_plan(normalized: NormalizedQuery) -> QueryPlan:
    """Convert a normalized query into a QueryPlan.

    M1 uses simple rule-based planning. Future M2+ can replace this
    with LLM planner, ontology expansion, or multi-agent orchestration.
    """
    variant_policy = "flag"
    if normalized.missing_constraints and normalized.intent == "command_usage":
        variant_policy = "require_disambiguation"

    return QueryPlan(
        intent=normalized.intent,
        retrieval_targets=["canonical_segments"],
        entity_constraints=[
            EntityRef(type=e.type, name=e.name, normalized_name=e.normalized_name)
            for e in normalized.entities
        ],
        scope_constraints=QueryScope(
            products=list(normalized.scope.products),
            product_versions=list(normalized.scope.product_versions),
            network_elements=list(normalized.scope.network_elements),
            projects=list(normalized.scope.projects),
            domains=list(normalized.scope.domains),
        ),
        semantic_role_preferences=list(normalized.desired_semantic_roles),
        block_type_preferences=list(normalized.desired_block_types),
        variant_policy=variant_policy,
        conflict_policy="flag_not_answer",
        evidence_budget=EvidenceBudget(canonical_limit=10, raw_per_canonical=3),
        expansion=ExpansionConfig(use_ontology=False, max_hops=0),
        keywords=list(normalized.keywords),
    )
