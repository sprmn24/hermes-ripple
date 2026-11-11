"""pre_tool_call hook tests: early refusal for ripple_publish."""

from __future__ import annotations

from ripple import engine
from ripple.demo import QUOTE_HTML, load_demo
from ripple.hooks import pre_tool_call


def test_hook_blocks_missing_artifact_id(monkeypatch, store):
    monkeypatch.setattr(engine, "get_store", lambda: store)
    res = pre_tool_call("ripple_publish", {})
    assert res["action"] == "block"


def test_hook_blocks_unapproved(monkeypatch, store):
    load_demo(store, publish=False)
    # revoke approvals to simulate a fresh, unapproved artifact
    store._conn.execute("DELETE FROM ripple_approvals")
    monkeypatch.setattr(engine, "get_store", lambda: store)
    res = pre_tool_call("ripple_publish", {"artifact_id": QUOTE_HTML})
    assert res["action"] == "block"
    assert "approval" in res["message"]


def test_hook_allows_fresh_approved(monkeypatch, store):
    load_demo(store, publish=False)
    monkeypatch.setattr(engine, "get_store", lambda: store)
    res = pre_tool_call("ripple_publish", {"artifact_id": QUOTE_HTML})
    assert res["action"] == "allow"


def test_hook_blocks_stale_with_cause_path(monkeypatch, store):
    load_demo(store, publish=False)
    store.put_source("src/unit_price", 13)  # stale + approval revoked
    monkeypatch.setattr(engine, "get_store", lambda: store)
    res = pre_tool_call("ripple_publish", {"artifact_id": QUOTE_HTML})
    assert res["action"] == "block"
    assert "stale" in res["message"]
    assert "src/unit_price" in res["message"]
    assert "Ripple pane" in res["message"]


def test_hook_ignores_other_tools():
    assert pre_tool_call("ripple_graph", {}) == {"action": "allow"}
