"""Demo fixture: the two-chat supplier/quote/budget scenario.

``load_demo`` builds the graph, has the human approve both artifacts, and
publishes them so the Desktop pane starts from a fully published state. A
later ``put_source`` on ``src/unit_price`` drives the stale-propagation demo.
"""

from __future__ import annotations

from . import engine

SRC_UNIT_PRICE = "src/unit_price"
SRC_QUANTITY = "src/quantity"
SRC_BUDGET = "src/budget"
QUOTE_TOTAL = "quote_total"
BUDGET_CHECK = "budget_check"
QUOTE_HTML = "quote.html"
BUDGET_HTML = "budget.html"

UNIT_PRICE = 12
QUANTITY = 100
BUDGET = 1300
EXPECTED_QUOTE_TOTAL = 1200
EXPECTED_BUDGET_CHECK = "pass"

_QUOTE_TEMPLATE = (
    "<html><body><h1>Quote</h1>"
    "<p>unit price: {src/unit_price}</p>"
    "<p>quantity: {src/quantity}</p>"
    "<p>total: {quote_total}</p>"
    "</body></html>"
)

_BUDGET_TEMPLATE = (
    "<html><body><h1>Budget</h1>"
    "<p>quote total: {quote_total}</p>"
    "<p>budget: {src/budget}</p>"
    "<p>check: {budget_check}</p>"
    "</body></html>"
)


def load_demo(store: "engine.Store", publish: bool = True) -> dict:
    """Reset the store and load the supplier fixture, approving and (optionally)
    publishing both artifacts. Returns the graph snapshot."""
    store.reset_all()
    store.put_source(SRC_UNIT_PRICE, UNIT_PRICE)
    store.put_source(SRC_QUANTITY, QUANTITY)
    store.put_source(SRC_BUDGET, BUDGET)
    store.derive(QUOTE_TOTAL, engine.KIND_COMPUTE,
                 [SRC_UNIT_PRICE, SRC_QUANTITY], "multiply")
    store.derive(BUDGET_CHECK, engine.KIND_COMPUTE,
                 [QUOTE_TOTAL, SRC_BUDGET], "threshold_check")
    store.derive(QUOTE_HTML, engine.KIND_ARTIFACT,
                 [QUOTE_TOTAL, SRC_UNIT_PRICE, SRC_QUANTITY], "render_html",
                 params={"template": _QUOTE_TEMPLATE})
    store.derive(BUDGET_HTML, engine.KIND_ARTIFACT,
                 [BUDGET_CHECK, QUOTE_TOTAL, SRC_BUDGET], "render_html",
                 params={"template": _BUDGET_TEMPLATE})

    store.approve(QUOTE_HTML, store._revision(QUOTE_HTML))
    store.approve(BUDGET_HTML, store._revision(BUDGET_HTML))
    if publish:
        store.publish(QUOTE_HTML)
        store.publish(BUDGET_HTML)
    return store.graph()
