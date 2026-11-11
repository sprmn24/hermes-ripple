"""Ripple backend engine: versioned sources, typed computations, artifacts,
human-only approvals, and authoritative publication.

The store is a single SQLite database (WAL mode). Sources are immutable: every
``put_source`` appends a new revision and never mutates an old one. Computation
and artifact nodes carry a typed recipe and pin the exact revision of each
input they were derived against. Any revision bump walks the dependency graph
and marks descendants stale while revoking approvals bound to the old
revisions.

Approvals are created *only* by humans: :meth:`Store.approve` is the Python
API consumed by ``dashboard/plugin_api.py`` and by tests — there is no agent
tool that can approve. :meth:`Store.publish` is the authoritative gate; it
re-validates freshness and approval inside the same ``BEGIN IMMEDIATE``
transaction that writes the release.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from . import paths

# ---- constants -----------------------------------------------------------

KIND_SOURCE = "source"
KIND_COMPUTE = "compute"
KIND_ARTIFACT = "artifact"

STATE_FRESH = "fresh"
STATE_STALE = "stale"
STATE_REBUILDING = "rebuilding"
STATE_UNTRACKED = "untracked"

OPS = ("multiply", "sum", "threshold_check", "render_html")

# error codes (stable contract)
E_UNTRACKED = "E_UNTRACKED"
E_STALE = "E_STALE"
E_NO_APPROVAL = "E_NO_APPROVAL"
E_CYCLE = "E_CYCLE"
E_DEP_MISSING = "E_DEP_MISSING"
E_BAD_KIND = "E_BAD_KIND"
E_NON_DETERMINISTIC = "E_NON_DETERMINISTIC"
E_INTERNAL = "E_INTERNAL"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ripple_nodes (
    node_id  TEXT PRIMARY KEY,
    kind     TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    state    TEXT NOT NULL,
    recipe   TEXT,
    value    TEXT
);
CREATE TABLE IF NOT EXISTS ripple_source_revisions (
    node_id  TEXT NOT NULL,
    revision INTEGER NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (node_id, revision)
);
CREATE TABLE IF NOT EXISTS ripple_edges (
    dependent       TEXT NOT NULL,
    input           TEXT NOT NULL,
    pinned_revision INTEGER NOT NULL,
    PRIMARY KEY (dependent, input)
);
CREATE TABLE IF NOT EXISTS ripple_approvals (
    artifact_id  TEXT PRIMARY KEY,
    revision     INTEGER NOT NULL,
    inputs_json  TEXT NOT NULL,
    approved_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ripple_releases (
    artifact_id   TEXT NOT NULL,
    revision      INTEGER NOT NULL,
    published_at  REAL NOT NULL,
    content_hash  TEXT NOT NULL,
    path          TEXT NOT NULL,
    PRIMARY KEY (artifact_id, revision)
);
"""


class RippleError(Exception):
    """Domain error with a stable machine-readable code and optional cause path."""

    def __init__(self, code: str, message: str, cause_path: Optional[list] = None):
        self.code = code
        self.message = message
        self.cause_path = cause_path
        super().__init__(f"{code}: {message}")


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _summary_of(value: Any) -> str:
    """Short human-readable rendering for pane rows and compact tool results."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        s = value
        if s.lstrip().startswith("<") and ">" in s:
            text = re.sub(r"<[^>]+>", " ", s)
            s = " ".join(text.split())
        return s if len(s) <= 80 else s[:77] + "…"
    return json.dumps(value)


def _num(value: Any) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise RippleError(E_INTERNAL, f"non-numeric input: {value!r}")
    raise RippleError(E_INTERNAL, f"non-numeric input: {value!r}")


class Store:
    """Owns one SQLite connection and the Ripple graph.

    Prefer :meth:`Store.from_path` (tests) or :meth:`Store.from_default`
    (running plugin / dashboard backend). All mutating methods run inside a
    single ``BEGIN IMMEDIATE`` transaction.
    """

    def __init__(self, conn, releases_dir: Optional[Path] = None):
        self._conn = conn
        self._releases_dir = Path(releases_dir) if releases_dir else paths.releases_dir()
        self._releases_dir.mkdir(parents=True, exist_ok=True)
        self._conn.executescript(_SCHEMA)

    # -- constructors ------------------------------------------------------
    @classmethod
    def from_path(cls, path, releases_dir: Optional[Path] = None) -> "Store":
        return cls(paths.connect(Path(path)), releases_dir=releases_dir)

    @classmethod
    def from_default(cls) -> "Store":
        return cls(paths.open_connection())

    @staticmethod
    def default_db_path() -> Path:
        return paths.db_path()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # -- transaction helper -------------------------------------------------
    @contextmanager
    def _tx(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    # -- low-level row helpers ----------------------------------------------
    def _node(self, node_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT node_id, kind, revision, state, recipe, value "
            "FROM ripple_nodes WHERE node_id=?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "node_id": row[0],
            "kind": row[1],
            "revision": row[2],
            "state": row[3],
            "recipe": row[4],
            "value": row[5],
        }

    def _revision(self, node_id: str) -> int:
        node = self._node(node_id)
        return node["revision"] if node else 0

    def _edges(self, node_id: str) -> list:
        return [
            (r[0], r[1])
            for r in self._conn.execute(
                "SELECT input, pinned_revision FROM ripple_edges WHERE dependent=?",
                (node_id,),
            ).fetchall()
        ]

    def _node_value(self, node_id: str) -> Any:
        node = self._node(node_id)
        if node is None or node["value"] is None:
            return None
        return json.loads(node["value"])

    # -- graph traversal ----------------------------------------------------
    def _descendants(self, node_id: str) -> list:
        """Transitive dependents in topological (input-before-dependent) order."""
        order: list = []
        seen = {node_id}
        dq = deque([node_id])
        while dq:
            cur = dq.popleft()
            for (dep,) in self._conn.execute(
                "SELECT dependent FROM ripple_edges WHERE input=?", (cur,)
            ).fetchall():
                if dep not in seen:
                    seen.add(dep)
                    order.append(dep)
                    dq.append(dep)
        return order

    def _depends_on(self, node_id: str, ancestor: str) -> bool:
        """True if ``ancestor`` is a transitive input of ``node_id``."""
        if node_id == ancestor:
            return True
        seen = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur == ancestor:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            for (inp,) in self._conn.execute(
                "SELECT input FROM ripple_edges WHERE dependent=?", (cur,)
            ).fetchall():
                stack.append(inp)
        return False

    def _is_fresh(self, node_id: str) -> bool:
        """Authoritative freshness: every input's current revision equals its
        pinned revision, recursively (sources are always fresh)."""
        node = self._node(node_id)
        if node is None:
            return False
        if node["kind"] == KIND_SOURCE:
            return True
        for inp, pinned in self._edges(node_id):
            inode = self._node(inp)
            if inode is None or inode["revision"] != pinned:
                return False
            if not self._is_fresh(inp):
                return False
        return True

    def _stale_chain(self, node_id: str) -> Optional[list]:
        """Upstream cause chain [changed_input, ..., node_id], or None if fresh."""
        node = self._node(node_id)
        if node is None:
            return None
        for inp, pinned in self._edges(node_id):
            inode = self._node(inp)
            if inode is None:
                return [inp, node_id]
            if inode["revision"] != pinned:
                return [inp, node_id]
            sub = self._stale_chain(inp)
            if sub:
                return sub + [node_id]
        return None

    def stale_cause(self, node_id: str):
        """(description, chain) for a stale node, or (None, None) if fresh.

        ``description`` reads like ``"src/unit_price changed r1 -> r2"`` and
        ``chain`` is the node-id path from the changed input down to ``node_id``.
        """
        node = self._node(node_id)
        if node is None:
            return None, None
        for inp, pinned in self._edges(node_id):
            inode = self._node(inp)
            if inode is None:
                return f"{inp} is missing", [inp, node_id]
            if inode["revision"] != pinned:
                return (
                    f"{inp} changed r{pinned} -> r{inode['revision']}",
                    [inp, node_id],
                )
            sub_desc, sub_chain = self.stale_cause(inp)
            if sub_chain:
                return sub_desc, sub_chain + [node_id]
        return None, None

    def _stale_message(self, node_id: str) -> Optional[str]:
        """One-line human-readable cause path, or None if the node is fresh."""
        desc, chain = self.stale_cause(node_id)
        if not chain:
            return None
        return f"{node_id} is stale: {desc} -> " + " -> ".join(chain[1:])

    def _transitive_input_pins(self, node_id: str) -> dict:
        pins: dict = {}
        seen = {node_id}
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for (inp,) in self._conn.execute(
                "SELECT input FROM ripple_edges WHERE dependent=?", (cur,)
            ).fetchall():
                if inp in seen:
                    continue
                seen.add(inp)
                inode = self._node(inp)
                if inode is not None:
                    pins[inp] = inode["revision"]
                stack.append(inp)
        return pins

    def _bump_and_invalidate(self, node_id: str) -> None:
        """Revoke this node's own approval (its revision changed) and mark every
        descendant stale while revoking their approvals. Runs inside a tx."""
        self._conn.execute(
            "DELETE FROM ripple_approvals WHERE artifact_id=?", (node_id,)
        )
        for dep in self._descendants(node_id):
            self._conn.execute(
                "UPDATE ripple_nodes SET state=? WHERE node_id=?",
                (STATE_STALE, dep),
            )
            self._conn.execute(
                "DELETE FROM ripple_approvals WHERE artifact_id=?", (dep,)
            )

    # -- recipe evaluation ----------------------------------------------------
    def _evaluate(self, recipe: dict) -> Any:
        op = recipe.get("op")
        inputs = recipe.get("inputs", [])
        params = recipe.get("params") or {}
        if op == "multiply":
            acc = 1.0
            for i in inputs:
                acc *= _num(self._node_value(i))
            return int(acc) if acc == int(acc) else acc
        if op == "sum":
            total = sum(_num(self._node_value(i)) for i in inputs)
            return int(total) if total == int(total) else total
        if op == "threshold_check":
            if len(inputs) < 2:
                raise RippleError(E_INTERNAL, "threshold_check needs [value, threshold]")
            return "pass" if _num(self._node_value(inputs[0])) <= _num(self._node_value(inputs[1])) else "fail"
        if op == "render_html":
            template = params.get("template", "")
            for i in inputs:
                template = template.replace("{" + i + "}", _display(self._node_value(i)))
            return template
        raise RippleError(E_INTERNAL, f"unknown recipe op: {op!r}")

    # -- sources ---------------------------------------------------------------
    def put_source(self, node_id: str, content: Any) -> dict:
        """Append a new immutable source revision, then in ONE transaction mark
        every descendant stale and revoke approvals bound to old revisions."""
        value = json.dumps(content, sort_keys=True)
        with self._tx():
            existing = self._node(node_id)
            if existing is not None and existing["kind"] != KIND_SOURCE:
                raise RippleError(
                    E_BAD_KIND,
                    f"node {node_id!r} already exists as {existing['kind']!r}",
                )
            new_rev = (existing["revision"] if existing else 0) + 1
            self._conn.execute(
                "INSERT INTO ripple_source_revisions(node_id, revision, value) VALUES(?,?,?)",
                (node_id, new_rev, value),
            )
            self._conn.execute(
                "INSERT INTO ripple_nodes(node_id, kind, revision, state, recipe, value) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(node_id) DO UPDATE SET revision=excluded.revision, "
                "state=excluded.state, value=excluded.value",
                (node_id, KIND_SOURCE, new_rev, STATE_FRESH, None, value),
            )
            self._bump_and_invalidate(node_id)
            stale = self._descendants(node_id)
        return {"ok": True, "node_id": node_id, "revision": new_rev,
                "stale": stale}

    # -- derive -----------------------------------------------------------------
    def derive(self, node_id: str, kind: str, inputs: list, compute: str,
               params: Optional[dict] = None) -> dict:
        """Derive a compute/artifact node from a typed recipe, pinning input
        revisions. Rejects cycles and stale inputs."""
        if kind not in (KIND_COMPUTE, KIND_ARTIFACT):
            raise RippleError(E_BAD_KIND, f"unknown node kind: {kind!r}")
        if compute not in OPS:
            raise RippleError(E_INTERNAL, f"unknown compute op: {compute!r}")
        if not inputs:
            raise RippleError(E_INTERNAL, "derive requires at least one input")

        recipe = {"op": compute, "inputs": list(inputs), "params": params or {}}
        with self._tx():
            for inp in inputs:
                if self._depends_on(inp, node_id):
                    raise RippleError(
                        E_CYCLE,
                        f"cycle: {node_id!r} would depend on its own input {inp!r}",
                    )
            pinned: dict = {}
            for inp in inputs:
                inode = self._node(inp)
                if inode is None:
                    raise RippleError(E_DEP_MISSING, f"input node {inp!r} does not exist")
                if not self._is_fresh(inp):
                    chain = self._stale_chain(inp) or [inp]
                    raise RippleError(
                        E_STALE,
                        f"input {inp!r} is stale; rebuild its inputs first. Path: "
                        + " -> ".join(chain),
                        cause_path=chain,
                    )
                pinned[inp] = inode["revision"]

            value = self._evaluate(recipe)
            new_rev = self._revision(node_id) + 1
            self._conn.execute(
                "DELETE FROM ripple_edges WHERE dependent=?", (node_id,)
            )
            for inp, rev in pinned.items():
                self._conn.execute(
                    "INSERT INTO ripple_edges(dependent, input, pinned_revision) "
                    "VALUES(?,?,?)",
                    (node_id, inp, rev),
                )
            self._conn.execute(
                "INSERT INTO ripple_nodes(node_id, kind, revision, state, recipe, value) "
                "VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(node_id) DO UPDATE SET kind=excluded.kind, "
                "revision=excluded.revision, state=excluded.state, "
                "recipe=excluded.recipe, value=excluded.value",
                (node_id, kind, new_rev, STATE_FRESH, json.dumps(recipe),
                 json.dumps(value)),
            )
            self._bump_and_invalidate(node_id)
        return {"ok": True, "node_id": node_id, "kind": kind, "revision": new_rev,
                "state": STATE_FRESH, "value": value}

    # -- impact / rebuild --------------------------------------------------------
    def impact(self, node_id: str) -> dict:
        node = self._node(node_id)
        if node is None:
            raise RippleError(E_UNTRACKED, f"node {node_id!r} does not exist")
        descendants = self._descendants(node_id)
        desc_info = []
        for d in descendants:
            dn = self._node(d)
            desc_info.append({
                "node_id": d,
                "kind": dn["kind"],
                "revision": dn["revision"],
                "state": dn["state"],
            })
        # downstream cause chains: node_id -> each stale descendant
        parent = {node_id: None}
        dq = deque([node_id])
        while dq:
            cur = dq.popleft()
            for (dep,) in self._conn.execute(
                "SELECT dependent FROM ripple_edges WHERE input=?", (cur,)
            ).fetchall():
                if dep not in parent:
                    parent[dep] = cur
                    dq.append(dep)
        cause_path = []
        for d in descendants:
            dn = self._node(d)
            if dn["state"] == STATE_STALE:
                chain = [d]
                while chain[-1] != node_id and chain[-1] in parent:
                    chain.append(parent[chain[-1]])
                cause_path.append(list(reversed(chain)))
        return {
            "ok": True,
            "node_id": node_id,
            "revision": node["revision"],
            "state": node["state"],
            "descendants": desc_info,
            "cause_path": cause_path,
        }

    def _topo_order(self, node_ids: list) -> list:
        ids = set(node_ids)
        indegree = {n: 0 for n in ids}
        adj = {n: [] for n in ids}
        for n in ids:
            for (inp,) in self._conn.execute(
                "SELECT input FROM ripple_edges WHERE dependent=?", (n,)
            ).fetchall():
                if inp in ids:
                    adj[inp].append(n)
                    indegree[n] += 1
        dq = deque(n for n in ids if indegree[n] == 0)
        order = []
        while dq:
            n = dq.popleft()
            order.append(n)
            for m in adj[n]:
                indegree[m] -= 1
                if indegree[m] == 0:
                    dq.append(m)
        if len(order) != len(ids):
            order += [n for n in ids if n not in order]
        return order

    def rebuild(self) -> dict:
        """Recompute every stale compute/artifact node in topological order."""
        with self._tx():
            stale = [
                r[0]
                for r in self._conn.execute(
                    "SELECT node_id FROM ripple_nodes "
                    "WHERE state=? AND kind IN (?,?)",
                    (STATE_STALE, KIND_COMPUTE, KIND_ARTIFACT),
                ).fetchall()
            ]
            rebuilt = []
            for nid in self._topo_order(stale):
                node = self._node(nid)
                recipe = json.loads(node["recipe"])
                value = self._evaluate(recipe)
                new_rev = node["revision"] + 1
                for inp, _ in self._edges(nid):
                    inode = self._node(inp)
                    self._conn.execute(
                        "UPDATE ripple_edges SET pinned_revision=? "
                        "WHERE dependent=? AND input=?",
                        (inode["revision"], nid, inp),
                    )
                self._conn.execute(
                    "UPDATE ripple_nodes SET revision=?, state=?, value=? "
                    "WHERE node_id=?",
                    (new_rev, STATE_FRESH, json.dumps(value), nid),
                )
                self._bump_and_invalidate(nid)
                rebuilt.append({"node_id": nid, "revision": new_rev,
                                "value": value, "summary": _summary_of(value)})
        return {"ok": True, "rebuilt": rebuilt}

    # -- approvals (HUMAN-ONLY) ---------------------------------------------------
    def approve(self, artifact_id: str, revision: int) -> dict:
        """Record a human approval binding the artifact revision plus all input
        revisions. No agent tool calls this."""
        with self._tx():
            node = self._node(artifact_id)
            if node is None or node["revision"] == 0:
                raise RippleError(
                    E_UNTRACKED,
                    f"artifact {artifact_id!r} has no recorded revision",
                )
            if node["kind"] != KIND_ARTIFACT:
                raise RippleError(
                    E_BAD_KIND,
                    f"node {artifact_id!r} is not an artifact (kind={node['kind']!r})",
                )
            if int(revision) != node["revision"]:
                raise RippleError(
                    E_STALE,
                    f"cannot approve r{revision}: current revision is r{node['revision']}",
                )
            if not self._is_fresh(artifact_id):
                chain = self._stale_chain(artifact_id) or [artifact_id]
                raise RippleError(
                    E_STALE,
                    "cannot approve a stale artifact. Path: " + " -> ".join(chain),
                    cause_path=chain,
                )
            inputs = self._transitive_input_pins(artifact_id)
            now = time.time()
            self._conn.execute(
                "INSERT INTO ripple_approvals(artifact_id, revision, inputs_json, approved_at) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(artifact_id) DO UPDATE SET revision=excluded.revision, "
                "inputs_json=excluded.inputs_json, approved_at=excluded.approved_at",
                (artifact_id, node["revision"], json.dumps(inputs), now),
            )
        return {
            "ok": True,
            "artifact_id": artifact_id,
            "revision": node["revision"],
            "approved_at": now,
            "inputs": inputs,
        }

    # -- publication ----------------------------------------------------------------
    def _approval(self, artifact_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT artifact_id, revision, inputs_json, approved_at "
            "FROM ripple_approvals WHERE artifact_id=?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row[0],
            "revision": row[1],
            "inputs": json.loads(row[2]),
            "approved_at": row[3],
        }

    def _release(self, artifact_id: str, revision: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT artifact_id, revision, published_at, content_hash, path "
            "FROM ripple_releases WHERE artifact_id=? AND revision=?",
            (artifact_id, revision),
        ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row[0],
            "revision": row[1],
            "published_at": row[2],
            "content_hash": row[3],
            "path": row[4],
        }

    def publish_block_reason(self, artifact_id: str):
        """Read-only check used by the pre_tool_call hook for early refusal.
        Returns (message, cause_path) or None when publication is allowed."""
        node = self._node(artifact_id)
        if node is None or node["revision"] == 0:
            return (
                f"Refusing publish: {artifact_id!r} has no recorded revision. "
                "Derive the artifact and have a human approve it in the Ripple pane first.",
                None,
            )
        if node["kind"] != KIND_ARTIFACT:
            return (
                f"Refusing publish: {artifact_id!r} is not an artifact "
                f"(kind={node['kind']!r}).",
                None,
            )
        # staleness first: give the cause path
        if not self._is_fresh(artifact_id):
            msg = self._stale_message(artifact_id) or (
                f"Refusing publish: {artifact_id!r} is stale."
            )
            return (
                msg + ". A human must re-approve in the Ripple pane after a rebuild.",
                self.stale_cause(artifact_id)[1],
            )
        approval = self._approval(artifact_id)
        if approval is None:
            return (
                f"Refusing publish: no human approval recorded for {artifact_id!r}. "
                "Approve it in the Ripple pane first.",
                None,
            )
        if approval["revision"] != node["revision"]:
            return (
                f"Refusing publish: {artifact_id!r} was re-derived since approval "
                f"(approved r{approval['revision']}, now r{node['revision']}). "
                "A human must re-approve in the Ripple pane.",
                [artifact_id],
            )
        for inp, rev in approval["inputs"].items():
            inode = self._node(inp)
            if inode is None or inode["revision"] != rev:
                chain = self._stale_chain(artifact_id) or [inp, artifact_id]
                return (
                    f"Refusing publish: approval-bound input {inp!r} changed since "
                    "approval. A human must re-approve in the Ripple pane. Path: "
                    + " -> ".join(chain),
                    chain,
                )
        return None

    def publish(self, artifact_id: str) -> dict:
        """Authoritative publication: re-validates inside the same BEGIN IMMEDIATE
        transaction as the write. Idempotent for the same artifact revision."""
        with self._tx():
            node = self._node(artifact_id)
            if node is None or node["revision"] == 0:
                raise RippleError(
                    E_UNTRACKED,
                    f"artifact {artifact_id!r} has no recorded revision",
                )
            if node["kind"] != KIND_ARTIFACT:
                raise RippleError(
                    E_BAD_KIND,
                    f"node {artifact_id!r} is not an artifact (kind={node['kind']!r})",
                )
            approval = self._approval(artifact_id)
            if approval is None:
                raise RippleError(
                    E_NO_APPROVAL,
                    f"no human approval recorded for {artifact_id!r}",
                )
            if approval["revision"] != node["revision"]:
                raise RippleError(
                    E_STALE,
                    f"artifact {artifact_id!r} was re-derived since approval "
                    f"(approved r{approval['revision']}, now r{node['revision']})",
                    cause_path=[artifact_id],
                )
            for inp, rev in approval["inputs"].items():
                inode = self._node(inp)
                if inode is None or inode["revision"] != rev:
                    chain = self._stale_chain(artifact_id) or [inp, artifact_id]
                    raise RippleError(
                        E_STALE,
                        f"approval-bound input {inp!r} changed since approval. "
                        "Path: " + " -> ".join(chain),
                        cause_path=chain,
                    )
            if not self._is_fresh(artifact_id):
                chain = self._stale_chain(artifact_id) or [artifact_id]
                raise RippleError(
                    E_STALE,
                    "artifact is stale. Path: " + " -> ".join(chain),
                    cause_path=chain,
                )

            existing = self._release(artifact_id, node["revision"])
            if existing is not None:
                return {**existing, "ok": True, "already_published": True}

            html = json.loads(node["value"])
            content_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
            safe_id = artifact_id.replace("/", "__")
            fname = f"{safe_id}.r{node['revision']}.html"
            out_path = self._releases_dir / fname
            out_path.write_text(html, encoding="utf-8")
            now = time.time()
            self._conn.execute(
                "INSERT INTO ripple_releases(artifact_id, revision, published_at, "
                "content_hash, path) VALUES(?,?,?,?,?)",
                (artifact_id, node["revision"], now, content_hash, str(out_path)),
            )
            release = {
                "artifact_id": artifact_id,
                "revision": node["revision"],
                "published_at": now,
                "content_hash": content_hash,
                "path": str(out_path),
            }
        return {**release, "ok": True, "already_published": False}

    def list_releases(self) -> list:
        rows = self._conn.execute(
            "SELECT artifact_id, revision, published_at, content_hash, path "
            "FROM ripple_releases ORDER BY published_at"
        ).fetchall()
        return [
            {
                "artifact_id": r[0],
                "revision": r[1],
                "published_at": r[2],
                "content_hash": r[3],
                "path": r[4],
            }
            for r in rows
        ]

    # -- snapshot -------------------------------------------------------------------
    def graph(self) -> dict:
        approvals = [
            {"artifact_id": r[0], "revision": r[1],
             "inputs": json.loads(r[2]), "approved_at": r[3]}
            for r in self._conn.execute(
                "SELECT artifact_id, revision, inputs_json, approved_at "
                "FROM ripple_approvals"
            ).fetchall()
        ]
        approved_rev = {a["artifact_id"]: a["revision"] for a in approvals}

        nodes = []
        for r in self._conn.execute(
            "SELECT node_id, kind, revision, state, recipe, value FROM ripple_nodes"
        ).fetchall():
            node_id, kind, revision, state = r[0], r[1], r[2], r[3]
            value = json.loads(r[5]) if r[5] is not None else None
            cause = None
            cause_path = None
            if state == STATE_STALE:
                cause, cause_path = self.stale_cause(node_id)
            nodes.append({
                "node_id": node_id,
                "kind": kind,
                "revision": revision,
                "state": state,
                "recipe": json.loads(r[4]) if r[4] else None,
                "value": value,
                "summary": _summary_of(value),
                "fresh": self._is_fresh(node_id),
                "cause": cause,
                "cause_path": cause_path,
                "approved_revision": (
                    approved_rev.get(node_id) if kind == KIND_ARTIFACT else None
                ),
            })
        edges = [
            {"dependent": r[0], "input": r[1], "pinned_revision": r[2]}
            for r in self._conn.execute(
                "SELECT dependent, input, pinned_revision FROM ripple_edges"
            ).fetchall()
        ]
        return {
            "nodes": nodes,
            "edges": edges,
            "approvals": approvals,
            "releases": self.list_releases(),
        }

    # -- reset (demo) ----------------------------------------------------------------
    def reset_all(self) -> None:
        with self._tx():
            for table in (
                "ripple_releases",
                "ripple_approvals",
                "ripple_edges",
                "ripple_source_revisions",
                "ripple_nodes",
            ):
                self._conn.execute(f"DELETE FROM {table}")
        for f in self._releases_dir.glob("*.html"):
            try:
                f.unlink()
            except OSError:
                pass


# process-wide default (agent tools / hook). Tests use Store.from_path.
_default_store: Optional[Store] = None


def get_store() -> Store:
    global _default_store
    if _default_store is None:
        _default_store = Store.from_default()
    return _default_store


def resolve_db_path() -> Path:
    """Exposed so a test can assert agent + dashboard share one helper."""
    return paths.db_path()
