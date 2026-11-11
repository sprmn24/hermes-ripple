"""Agent tool handlers for the Ripple engine.

Every handler returns a JSON string. Domain errors (``RippleError``) are
returned as ``{"ok": false, ...}`` so the agent sees the cause path; there is
no tool that creates an approval.
"""

from __future__ import annotations

import json

from . import engine


def _err(exc: engine.RippleError) -> str:
    return json.dumps({
        "ok": False,
        "error": exc.code,
        "message": exc.message,
        "cause_path": exc.cause_path,
    })


def _ok(payload: dict) -> str:
    payload.setdefault("ok", True)
    return json.dumps(payload)


def _compact_node(node: dict) -> dict:
    """Trim a graph node for agent tool output: artifact HTML bodies become a
    short summary, and recipe/edge bookkeeping is dropped."""
    value = node["summary"] if node["kind"] == engine.KIND_ARTIFACT else node["value"]
    return {
        "node_id": node["node_id"],
        "kind": node["kind"],
        "revision": node["revision"],
        "state": node["state"],
        "value": value,
        "fresh": node["fresh"],
        "cause": node["cause"],
        "approved_revision": node["approved_revision"],
    }


def _trim_value(value):
    if isinstance(value, str) and len(value) > 120:
        return engine._summary_of(value)
    return value


def handle_put_source(args: dict, **_kw) -> str:
    try:
        result = engine.get_store().put_source(args["node_id"], args["content"])
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


def handle_derive(args: dict, **_kw) -> str:
    try:
        result = engine.get_store().derive(
            args["node_id"],
            args["kind"],
            args["inputs"],
            args["compute"],
            args.get("params"),
        )
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


def handle_impact(args: dict, **_kw) -> str:
    try:
        result = engine.get_store().impact(args["node_id"])
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


def handle_rebuild(_args: dict, **_kw) -> str:
    try:
        result = engine.get_store().rebuild()
        result["rebuilt"] = [
            {**entry, "value": _trim_value(entry["value"])}
            for entry in result["rebuilt"]
        ]
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


def handle_publish(args: dict, **_kw) -> str:
    try:
        result = engine.get_store().publish(args["artifact_id"])
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


def handle_graph(_args: dict, **_kw) -> str:
    try:
        result = engine.get_store().graph()
        result["nodes"] = [_compact_node(n) for n in result["nodes"]]
    except engine.RippleError as exc:
        return _err(exc)
    return _ok(result)


PUT_SOURCE_SCHEMA = {
    "type": "object",
    "required": ["node_id", "content"],
    "properties": {
        "node_id": {"type": "string", "description": "Source node id (e.g. src/unit_price)"},
        "content": {"description": "JSON value stored as the new immutable revision"},
    },
}

DERIVE_SCHEMA = {
    "type": "object",
    "required": ["node_id", "kind", "inputs", "compute"],
    "properties": {
        "node_id": {"type": "string", "description": "Node id to create or re-derive"},
        "kind": {"type": "string", "enum": ["compute", "artifact"]},
        "inputs": {"type": "array", "items": {"type": "string"}, "description": "Input node ids"},
        "compute": {"type": "string", "enum": ["multiply", "sum", "threshold_check", "render_html"]},
        "params": {"type": "object", "description": "Recipe params (e.g. template for render_html)"},
    },
}

IMPACT_SCHEMA = {
    "type": "object",
    "required": ["node_id"],
    "properties": {
        "node_id": {"type": "string", "description": "Node whose descendants and cause path to return"},
    },
}

REBUILD_SCHEMA = {"type": "object", "properties": {}}

PUBLISH_SCHEMA = {
    "type": "object",
    "required": ["artifact_id"],
    "properties": {
        "artifact_id": {"type": "string", "description": "Artifact node id to publish"},
    },
}

GRAPH_SCHEMA = {"type": "object", "properties": {}}
