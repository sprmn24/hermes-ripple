"""Engine tests: sources, derivation, invalidation, rebuild, cycles, persistence."""

from __future__ import annotations

import pytest

from ripple import engine
from ripple.engine import (
    E_CYCLE,
    E_DEP_MISSING,
    E_STALE,
    KIND_ARTIFACT,
    KIND_COMPUTE,
    KIND_SOURCE,
    STATE_FRESH,
    STATE_STALE,
    RippleError,
)


def _build_small_graph(store):
    """s1 -> c1 -> c2, plus an unrelated branch s2 -> other."""
    store.put_source("s1", 2)
    store.put_source("s2", 7)
    store.derive("c1", KIND_COMPUTE, ["s1"], "sum")
    store.derive("c2", KIND_COMPUTE, ["c1"], "sum")
    store.derive("other", KIND_COMPUTE, ["s2"], "sum")


def _state(store, node_id):
    return store._node(node_id)["state"]


def test_put_source_creates_immutable_revisions(store):
    assert store.put_source("a", 1)["revision"] == 1
    assert store.put_source("a", 2)["revision"] == 2
    rows = store._conn.execute(
        "SELECT revision, value FROM ripple_source_revisions WHERE node_id='a'"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "1" and rows[1][1] == "2"


def test_exact_descendant_invalidation(store):
    _build_small_graph(store)
    store.put_source("s1", 99)

    impact = store.impact("s1")
    desc_ids = {d["node_id"] for d in impact["descendants"]}
    assert desc_ids == {"c1", "c2"}
    assert all(d["state"] == STATE_STALE for d in impact["descendants"])


def test_unrelated_node_untouched(store):
    _build_small_graph(store)
    before = store._node("other")
    store.put_source("s1", 99)
    after = store._node("other")
    assert after["revision"] == before["revision"]
    assert after["value"] == before["value"]
    assert after["state"] == STATE_FRESH


def test_derive_pins_input_revisions(store):
    store.put_source("a", 1)
    store.derive("c", KIND_COMPUTE, ["a"], "sum")
    edges = store._edges("c")
    assert edges == [("a", 1)]


def test_derive_rejects_missing_input(store):
    with pytest.raises(RippleError) as exc:
        store.derive("c", KIND_COMPUTE, ["nope"], "sum")
    assert exc.value.code == E_DEP_MISSING


def test_derive_rejects_cycle(store):
    store.put_source("a", 1)
    store.derive("b", KIND_COMPUTE, ["a"], "sum")
    store.derive("c", KIND_COMPUTE, ["b"], "sum")
    with pytest.raises(RippleError) as exc:
        store.derive("b", KIND_COMPUTE, ["c"], "sum")
    assert exc.value.code == E_CYCLE


def test_multiply_sum_threshold(store):
    store.put_source("u", 12)
    store.put_source("q", 100)
    store.put_source("budget", 1300)
    store.derive("total", KIND_COMPUTE, ["u", "q"], "multiply")
    store.derive("check", KIND_COMPUTE, ["total", "budget"], "threshold_check")
    assert store._node_value("total") == 1200
    assert store._node_value("check") == "pass"


def test_rebuild_recomputes_stale_in_topo_order(store):
    _build_small_graph(store)
    store.put_source("s1", 3)  # c1 -> 3, c2 -> 3
    result = store.rebuild()
    rebuilt = {r["node_id"]: r for r in result["rebuilt"]}
    assert set(rebuilt) == {"c1", "c2"}
    assert rebuilt["c1"]["value"] == 3
    assert rebuilt["c2"]["value"] == 3
    assert _state(store, "c1") == STATE_FRESH
    assert _state(store, "c2") == STATE_FRESH
    assert _state(store, "other") == STATE_FRESH


def test_rebuild_preserves_artifacts(store):
    store.put_source("u", 12)
    store.put_source("q", 100)
    store.derive("total", KIND_COMPUTE, ["u", "q"], "multiply")
    store.derive("quote.html", KIND_ARTIFACT, ["total", "u", "q"], "render_html",
                 params={"template": "total={total} u={u}"})
    store.put_source("u", 13)
    store.rebuild()
    html = store._node_value("quote.html")
    assert "total=1300" in html


def test_persistence_across_new_store_instance(tmp_path):
    s1 = engine.Store.from_path(tmp_path / "db.sqlite", releases_dir=tmp_path / "rel")
    s1.put_source("a", 5)
    s1.derive("c", KIND_COMPUTE, ["a"], "sum")
    s1.close()

    s2 = engine.Store.from_path(tmp_path / "db.sqlite", releases_dir=tmp_path / "rel")
    assert s2._node_value("a") == 5
    assert s2._node_value("c") == 5
    assert s2._edges("c") == [("a", 1)]
    s2.close()


def test_impact_returns_cause_path(store):
    _build_small_graph(store)
    store.put_source("s1", 99)
    impact = store.impact("s1")
    chains = impact["cause_path"]
    assert any(chain == ["s1", "c1", "c2"] for chain in chains)


def test_graph_snapshot(store):
    _build_small_graph(store)
    g = store.graph()
    ids = {n["node_id"] for n in g["nodes"]}
    assert ids == {"s1", "s2", "c1", "c2", "other"}
    kinds = {n["node_id"]: n["kind"] for n in g["nodes"]}
    assert kinds["s1"] == KIND_SOURCE
    assert kinds["c1"] == KIND_COMPUTE
