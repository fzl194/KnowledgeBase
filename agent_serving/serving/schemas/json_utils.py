"""Shared JSON parsing utilities for source refs and target refs."""
from __future__ import annotations

import json
from typing import Any


def parse_source_refs(source_refs_json: str | None) -> list[str]:
    """Parse source_refs_json to extract raw_segment_ids.

    source_refs_json format: {"raw_segment_ids": ["id1", "id2", ...]}
    """
    if not source_refs_json:
        return []
    try:
        data = json.loads(source_refs_json)
        if isinstance(data, dict):
            ids = data.get("raw_segment_ids", [])
            return [v for v in ids if isinstance(v, str)]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def parse_target_ref(target_ref_json: str | None) -> list[str]:
    """Parse target_ref_json to extract segment IDs.

    target_ref_json format: {"raw_segment_id": "id"} or {"raw_segment_ids": ["id1", ...]}
    """
    if not target_ref_json:
        return []
    try:
        data = json.loads(target_ref_json)
        if isinstance(data, dict):
            if "raw_segment_id" in data:
                v = data["raw_segment_id"]
                return [v] if isinstance(v, str) else []
            if "raw_segment_ids" in data:
                return [v for v in data["raw_segment_ids"] if isinstance(v, str)]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def safe_json_parse(raw: str | dict) -> dict:
    """Safely parse JSON string or pass through dict."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
