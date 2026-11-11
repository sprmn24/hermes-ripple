"""Ripple — incremental build system for agent work (Hermes plugin entry point)."""

from __future__ import annotations

from typing import Any


def register(ctx: Any) -> None:
    from .ripple import hooks, tools

    ctx.register_hook("pre_tool_call", hooks.pre_tool_call)
    ctx.register_tool(
        name="ripple_put_source",
        toolset="ripple",
        schema=tools.PUT_SOURCE_SCHEMA,
        handler=tools.handle_put_source,
        description=(
            "Record a new value for a source node (a fact that changed in the world, "
            "e.g. a supplier price or a quantity). Bumps the source revision and marks "
            "every dependent computation, artifact and approval stale. Use this whenever "
            "a real-world input value changes."
        ),
    )
    ctx.register_tool(
        name="ripple_derive",
        toolset="ripple",
        schema=tools.DERIVE_SCHEMA,
        handler=tools.handle_derive,
        description="Create or re-derive a compute/artifact node from a typed recipe, pinning the exact input revisions used.",
    )
    ctx.register_tool(
        name="ripple_impact",
        toolset="ripple",
        schema=tools.IMPACT_SCHEMA,
        handler=tools.handle_impact,
        description="Show which downstream nodes a given node affects and the cause path of the staleness it produces.",
    )
    ctx.register_tool(
        name="ripple_rebuild",
        toolset="ripple",
        schema=tools.REBUILD_SCHEMA,
        handler=tools.handle_rebuild,
        description=(
            "Recompute all stale computations and artifacts from their current inputs, "
            "in dependency order. Call this after changing a source (ripple_put_source) "
            "to bring values up to date; afterwards artifacts are fresh but still need a "
            "human to re-approve in the Ripple pane before publishing."
        ),
    )
    ctx.register_tool(
        name="ripple_publish",
        toolset="ripple",
        schema=tools.PUBLISH_SCHEMA,
        handler=tools.handle_publish,
        description=(
            "Publish an artifact to the releases directory. Refuses if the artifact is "
            "stale or lacks a fresh human approval (a pre_tool_call hook blocks early "
            "with the cause path)."
        ),
    )
    ctx.register_tool(
        name="ripple_graph",
        toolset="ripple",
        schema=tools.GRAPH_SCHEMA,
        handler=tools.handle_graph,
        description=(
            "Read the current Ripple build graph: each node's value, revision, state, "
            "staleness cause, approval status, and published releases. Use this to answer "
            "questions about the build state (e.g. whether the budget still passes)."
        ),
    )
