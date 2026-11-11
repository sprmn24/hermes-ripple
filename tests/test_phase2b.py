"""Phase 2b: full demo sequence end-to-end through the engine, plus the
fresh-only approval rule and the pane-oriented graph fields."""

from __future__ import annotations

import pytest

from ripple import demo, engine

SRC_UNIT_PRICE = demo.SRC_UNIT_PRICE
SRC_QUANTITY = demo.SRC_QUANTITY
SRC_BUDGET = demo.SRC_BUDGET
QUOTE_TOTAL = demo.QUOTE_TOTAL
BUDGET_CHECK = demo.BUDGET_CHECK
QUOTE_HTML = demo.QUOTE_HTML
BUDGET_HTML = demo.BUDGET_HTML


def _by_node(graph: dict) -> dict:
    return {n["node_id"]: n for n in graph["nodes"]}


def test_graph_includes_pane_fields(store):
    demo.load_demo(store, publish=False, approve=False)
    g = store.graph()
    by = _by_node(g)
    for nid, node in by.items():
        assert "summary" in node, nid
        assert "fresh" in node, nid
        assert "cause" in node, nid
        assert "cause_path" in node, nid
        assert "approved_revision" in node, nid
    # fresh + unapproved artifact is reported as not approved
    assert by[QUOTE_HTML]["fresh"] is True
    assert by[QUOTE_HTML]["approved_revision"] is None


def test_full_demo_sequence_end_to_end(store):
    # 1. Reset demo: fresh, unapproved, unpublished.
    demo.load_demo(store, publish=False, approve=False)
    by = _by_node(store.graph())
    assert by[QUOTE_TOTAL]["value"] == 1200
    assert by[BUDGET_CHECK]["value"] == "pass"
    assert by[QUOTE_HTML]["state"] == "fresh"
    assert by[QUOTE_HTML]["approved_revision"] is None
    assert store.list_releases() == []

    # 2. Human approves quote.html in the pane; publish succeeds.
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    assert store.publish(QUOTE_HTML)["ok"] is True
    assert any(r["artifact_id"] == QUOTE_HTML for r in store.list_releases())

    # 3. Supplier raises the unit price: dependent nodes + approval go stale.
    store.put_source(SRC_UNIT_PRICE, 15)
    by = _by_node(store.graph())
    for nid in (QUOTE_TOTAL, BUDGET_CHECK, QUOTE_HTML, BUDGET_HTML):
        assert by[nid]["state"] == "stale", nid
        assert by[nid]["fresh"] is False, nid
    assert by[SRC_QUANTITY]["state"] == "fresh"
    assert by[SRC_BUDGET]["state"] == "fresh"
    assert by[QUOTE_HTML]["approved_revision"] is None
    assert SRC_UNIT_PRICE in (by[QUOTE_HTML]["cause_path"] or [])

    # 4. Publish refused with a cause path naming the changed input.
    reason = store.publish_block_reason(QUOTE_HTML)
    assert reason is not None
    msg, path = reason
    assert "stale" in msg.lower()
    assert "Ripple pane" in msg
    assert SRC_UNIT_PRICE in msg
    assert path is not None and SRC_UNIT_PRICE in path

    # 5. Rebuild -> budget now fails (1500 > 1300).
    store.rebuild()
    by = _by_node(store.graph())
    assert by[QUOTE_TOTAL]["value"] == 1500
    assert by[BUDGET_CHECK]["value"] == "fail"
    assert by[QUOTE_HTML]["state"] == "fresh"

    # 6. Reduce quantity to 80 and rebuild -> 1200, budget passes, unapproved.
    store.put_source(SRC_QUANTITY, 80)
    store.rebuild()
    by = _by_node(store.graph())
    assert by[QUOTE_TOTAL]["value"] == 1200
    assert by[BUDGET_CHECK]["value"] == "pass"
    assert by[QUOTE_HTML]["state"] == "fresh"
    assert by[QUOTE_HTML]["approved_revision"] is None

    # 7. Re-approve (fresh now) then publish succeeds; a new release is written.
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    assert store.publish(QUOTE_HTML)["ok"] is True
    releases = [r for r in store.list_releases() if r["artifact_id"] == QUOTE_HTML]
    assert len(releases) == 2
    assert releases[-1]["revision"] == store._revision(QUOTE_HTML)


def test_approve_rejects_stale_artifact(store):
    demo.load_demo(store, publish=False, approve=False)
    store.put_source(SRC_UNIT_PRICE, 15)  # artifacts now stale
    with pytest.raises(engine.RippleError) as exc:
        store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    assert exc.value.code == engine.E_STALE
