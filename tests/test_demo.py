"""Demo fixture tests: the supplier/quote/budget scenario and reset behavior."""

from __future__ import annotations

from ripple.demo import (
    BUDGET_CHECK,
    BUDGET_HTML,
    EXPECTED_BUDGET_CHECK,
    EXPECTED_QUOTE_TOTAL,
    QUOTE_HTML,
    QUOTE_TOTAL,
    load_demo,
)


def test_demo_produces_expected_values(store):
    g = load_demo(store, publish=False)
    values = {n["node_id"]: n["value"] for n in g["nodes"]}
    assert values[QUOTE_TOTAL] == EXPECTED_QUOTE_TOTAL
    assert values[BUDGET_CHECK] == EXPECTED_BUDGET_CHECK
    assert "1200" in values[QUOTE_HTML]
    assert "pass" in values[BUDGET_HTML]
    assert QUOTE_HTML in values and BUDGET_HTML in values


def test_demo_publish_creates_releases(store):
    load_demo(store, publish=True)
    releases = store.list_releases()
    released_ids = {r["artifact_id"] for r in releases}
    assert released_ids == {QUOTE_HTML, BUDGET_HTML}


def test_demo_reset_is_idempotent(store):
    load_demo(store, publish=True)
    load_demo(store, publish=True)
    # a second reset must not accumulate duplicate nodes/releases
    g = store.graph()
    assert len(g["nodes"]) == 7  # 3 sources + 2 computes + 2 artifacts
    assert len(g["releases"]) == 2
