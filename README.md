# Ripple

Incremental build system for agent work: versioned sources -> typed computations
-> artifacts -> approvals bound to exact dependency revisions. A source change
marks descendants and their approvals stale; a pre_tool_call hook refuses stale
publication; deterministic nodes rebuild.

Phase 1 (risk gate): skeleton with `ripple_ping`, `ripple_publish` (stub) and a
pre_tool_call publish gate, plus a Desktop pane round trip. See CONTRACT.md for
the full model and REFERENCE.md for the API surface research.

## Layout
- `plugin.yaml` — manifest (tools + hooks must match what `register()` registers)
- `__init__.py` — `register(ctx)` entry point
- `ripple/` — engine (SQLite store + publish verdict), tools, hooks
- `desktop/plugin.js` — Desktop pane (one backend round-trip button)
- `dashboard/manifest.json` + `dashboard/plugin_api.py` — backend namespace
- `tests/` — pytest for the publish gate
- `CONTRACT.md`, `REFERENCE.md`, `PROGRESS.md`, `catalog-entry.draft.yaml`

## Dev
- Test: `pytest -q`
- Validate: `hermes plugins validate ~/hermes-ripple --install-deps`
- Test profile (never ripple-dev): `hermes profile create ripple-test --clone`
  then `hermes -p ripple-test -z "call ripple_ping"`
- Desktop pane (app-level): install the package, then `hermes -p ripple-test gui`
  inside WSL.

## Notes
- State lives in `<hermes home>/plugin-data/ripple/data.db` (survives updates).
- No privileged capabilities, no third-party deps, no credentials, no network.
