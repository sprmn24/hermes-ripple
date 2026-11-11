"""Approval + publication tests (human-only approvals, stale refusal, idempotency,
concurrent put_source vs publish)."""

from __future__ import annotations

import hashlib
import threading

import pytest

from ripple import engine
from ripple.engine import (
    E_BAD_KIND,
    E_NO_APPROVAL,
    E_STALE,
    E_UNTRACKED,
    KIND_ARTIFACT,
    KIND_COMPUTE,
    RippleError,
)
from ripple.demo import (
    QUOTE_HTML,
    SRC_UNIT_PRICE,
    load_demo,
)


def _build_quote(store):
    store.put_source(SRC_UNIT_PRICE, 12)
    store.put_source("src/quantity", 100)
    store.put_source("src/budget", 1300)
    store.derive("quote_total", KIND_COMPUTE, [SRC_UNIT_PRICE, "src/quantity"], "multiply")
    store.derive("budget_check", KIND_COMPUTE, ["quote_total", "src/budget"], "threshold_check")
    store.derive(QUOTE_HTML, KIND_ARTIFACT, ["quote_total"], "render_html",
                 params={"template": "total={quote_total}"})


def test_approve_rejects_non_artifact(store):
    store.put_source("a", 1)
    with pytest.raises(RippleError) as exc:
        store.approve("a", 1)
    assert exc.value.code == E_BAD_KIND


def test_approve_rejects_unknown(store):
    with pytest.raises(RippleError) as exc:
        store.approve("ghost", 1)
    assert exc.value.code == E_UNTRACKED


def test_approve_binds_input_revisions(store):
    _build_quote(store)
    res = store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    assert res["inputs"][SRC_UNIT_PRICE] == 1
    assert res["inputs"]["quote_total"] == 1


def test_publish_without_approval_refused(store):
    _build_quote(store)
    with pytest.raises(RippleError) as exc:
        store.publish(QUOTE_HTML)
    assert exc.value.code == E_NO_APPROVAL


def test_stale_approval_publish_refused(store):
    _build_quote(store)
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    store.put_source(SRC_UNIT_PRICE, 13)  # descendant stale + approval revoked
    with pytest.raises(RippleError) as exc:
        store.publish(QUOTE_HTML)
    assert exc.value.code in (E_STALE, E_NO_APPROVAL)
    assert store.list_releases() == []


def test_reapprove_then_publish_succeeds(store):
    _build_quote(store)
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    store.put_source(SRC_UNIT_PRICE, 13)
    store.rebuild()
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    res = store.publish(QUOTE_HTML)
    assert res["ok"] is True
    assert store.list_releases()[-1]["revision"] == store._revision(QUOTE_HTML)


def test_idempotent_publish(store):
    _build_quote(store)
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    first = store.publish(QUOTE_HTML)
    second = store.publish(QUOTE_HTML)
    assert first["already_published"] is False
    assert second["already_published"] is True
    assert second["content_hash"] == first["content_hash"]
    assert len(store.list_releases()) == 1


def test_publish_writes_html_file_with_hash(store):
    _build_quote(store)
    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    res = store.publish(QUOTE_HTML)
    html = store._node_value(QUOTE_HTML)
    assert res["content_hash"] == hashlib.sha256(html.encode("utf-8")).hexdigest()
    import os
    assert os.path.isfile(res["path"])


def test_concurrent_put_source_vs_publish_never_publishes_stale(tmp_path):
    fresh_hash = None
    for i in range(20):
        db = tmp_path / f"race{i}.db"
        s = engine.Store.from_path(db, releases_dir=tmp_path / "rel")
        load_demo(s, publish=False)
        fresh_hash = hashlib.sha256(
            s._node_value(QUOTE_HTML).encode("utf-8")
        ).hexdigest()

        barrier = threading.Barrier(2)
        results = {}

        def putter():
            t = engine.Store.from_path(db, releases_dir=tmp_path / "rel")
            barrier.wait()
            try:
                t.put_source(SRC_UNIT_PRICE, 13)
                results["put"] = "ok"
            finally:
                t.close()

        def publisher():
            t = engine.Store.from_path(db, releases_dir=tmp_path / "rel")
            barrier.wait()
            try:
                r = t.publish(QUOTE_HTML)
                results["publish"] = ("ok", r["revision"], r["content_hash"])
            except engine.RippleError as exc:
                results["publish"] = ("refused", exc.code)
            finally:
                t.close()

        t1 = threading.Thread(target=putter)
        t2 = threading.Thread(target=publisher)
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert results.get("put") == "ok"
        pub = results["publish"]
        if pub[0] == "ok":
            # published the pre-bump revision, with the pre-bump content
            assert pub[1] == 1
            assert pub[2] == fresh_hash
        else:
            # refused: must be stale or unapproved (approval was revoked)
            assert pub[1] in (E_STALE, E_NO_APPROVAL)
        s.close()


def test_publish_unknown_artifact(store):
    with pytest.raises(RippleError) as exc:
        store.publish("ghost")
    assert exc.value.code == E_UNTRACKED
