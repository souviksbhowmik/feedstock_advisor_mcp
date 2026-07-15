"""
server_http.py
--------------
Feedstock Advisor MCP Server — HTTP transport entry-point.

Runs the same 15 tools as server.py but over HTTP instead of stdio,
making the server reachable from any MCP client that supports the
Streamable-HTTP or SSE transports (Claude.ai, custom clients, ngrok tunnels).

Transports exposed
------------------
  Streamable HTTP  POST  http://HOST:PORT/mcp        ← preferred (MCP spec 2025-03)
  Legacy SSE       GET   http://HOST:PORT/sse         ← for older clients
  SSE messages     POST  http://HOST:PORT/messages/

Configuration (environment variables)
--------------------------------------
  MCP_HOST   bind address  (default: 127.0.0.1)
  MCP_PORT   listen port   (default: 8000)
  DATA_BACKEND              (default: csv)
  LOG_LEVEL                 (default: INFO)

Usage
-----
  # Activate conda environment first:
  #   conda activate feedstock_advisor

  # Run locally (stdio clients still use server.py):
  python server_http.py

  # Override host/port:
  MCP_HOST=0.0.0.0 MCP_PORT=9000 python server_http.py

  # Then in a separate terminal tunnel via ngrok:
  ngrok http 8000
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from config import LOG_LEVEL
from data_access import DataStore

# ── Tool imports ─────────────────────────────────────────────────────────────
from tools.helpers import (
    find_matching_crude,
    find_matching_property,
    find_matching_refinery,
    get_refinery_id,
    list_available_crudes,
    list_available_refineries,
    list_properties_and_yields,
)
from tools.forecast import forecast_tool
from tools.blend_simulator import blend_simulator_tool
from tools.analysis import (
    constraint_checker_tool,
    get_high_yield_crudes,
    get_market_context,
    optimizer_tool,
    price_calculator_tool,
    profitability_calculator_tool,
)

# ---------------------------------------------------------------------------
# Logging  (stderr only)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared data store
# ---------------------------------------------------------------------------
logger.info("Initialising data store…")
store = DataStore()
logger.info("Data store ready.")

# ---------------------------------------------------------------------------
# HTTP / port config  (override via env vars)
# ---------------------------------------------------------------------------
_HOST: str = os.environ.get("MCP_HOST", "127.0.0.1")
_PORT: int = int(os.environ.get("MCP_PORT", "8000"))

# ---------------------------------------------------------------------------
# Transport security — allowed hosts
# ---------------------------------------------------------------------------
# By default only localhost is trusted (DNS-rebinding protection).
# Set MCP_ALLOWED_HOSTS to a comma-separated list of extra hosts to allow,
# e.g. the current ngrok subdomain:
#   $env:MCP_ALLOWED_HOSTS = "backward-steadier-clear.ngrok-free.dev"
#   $env:MCP_ALLOWED_HOSTS = "*"   ← disables host checking entirely
#
# The wildcard "*" is the easiest option when using ngrok (URL changes every
# session). It is safe because the server only binds to 127.0.0.1 and ngrok
# is the only thing that can reach it from outside.

from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

_raw_hosts: str = os.environ.get("MCP_ALLOWED_HOSTS", "*")
_allowed_hosts: list[str] = [h.strip() for h in _raw_hosts.split(",") if h.strip()]

_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=("*" not in _allowed_hosts),
    allowed_hosts=_allowed_hosts if "*" not in _allowed_hosts else [],
)

# ---------------------------------------------------------------------------
# MCP server instance — HTTP transport
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="feedstock-advisor",
    instructions=(
        "You are a smart feedstock advisor for the petrochemical industry. "
        "Use the available tools to answer questions about crude oil trading, "
        "blending, yield forecasting, pricing, and profitability. "
        "When a user mentions a crude or refinery by a variant name or with a "
        "typo, call find_matching_crude or find_matching_refinery first to "
        "resolve the canonical name before calling other tools."
    ),
    host=_HOST,
    port=_PORT,
    # Streamable HTTP endpoint (MCP spec 2025-03-26)
    streamable_http_path="/mcp",
    # Legacy SSE endpoints (for clients that haven't upgraded)
    sse_path="/sse",
    message_path="/messages/",
    transport_security=_transport_security,
)

# ===========================================================================
# HELPERS — 7 tools
# ===========================================================================

@mcp.tool()
def list_available_crudes_tool() -> dict:
    """
    Get the list of all available crude oil names in the system, grouped by region.

    RETURNS:
        List of canonical crude names and a region breakdown.

    USAGE:
        - Use when the user asks 'what crudes do you have' or 'list all crudes'.
        - Use before calling find_matching_crude to know what names are valid.

    RELATED TOOLS: find_matching_crude (to match a user-typed name to this list)
    """
    return list_available_crudes(store)


@mcp.tool()
def list_available_refineries_tool() -> dict:
    """
    Get the list of all available refineries with their IDs, names, locations,
    capacity, and unit configuration.

    RETURNS:
        List of refinery records each containing id, name, location, country,
        capacity_bpd, complexity_index, has_hydrocracker, has_fcc, has_coker.

    USAGE:
        - Use when any tool requires a refinery_id parameter.
        - Use when the user asks about available refineries.

    RELATED TOOLS: find_matching_refinery, get_refinery_id
    """
    return list_available_refineries(store)


@mcp.tool()
def list_properties_and_yields_tool() -> dict:
    """
    Get the canonical names, descriptions, and units for all crude properties
    and refinery product yield types available in the system.

    RETURNS:
        Two lists — 'properties' (api_gravity, sulfur_content, etc.) and
        'yields' (diesel_yield, gasoline_yield, etc.) — each with name,
        description, and unit.

    USAGE:
        - Use before calling find_matching_property to see valid names.
        - Use when the user asks what metrics or properties are available.

    RELATED TOOLS: find_matching_property
    """
    return list_properties_and_yields(store)


@mcp.tool()
def find_matching_crude_tool(crude_name: str, threshold: float = 0.6) -> dict:
    """
    Find the best matching canonical crude oil name using fuzzy string matching.

    Use this tool when the user mentions a crude by a non-exact, abbreviated,
    or misspelled name (e.g. 'brent crude', 'WTi', 'west texas', 'arab lite').

    PARAMETERS:
        crude_name : str   — crude name as typed by the user
        threshold  : float — minimum similarity score 0–1 to accept (default 0.6)

    RETURNS:
        Best matching canonical name with similarity score and alternatives.

    LOOP REQUIREMENTS:
        For multiple crude names, call once per name.

    RELATED TOOLS: list_available_crudes (to see all valid names)
    """
    return find_matching_crude(store, crude_name, threshold)


@mcp.tool()
def find_matching_property_tool(
    property_name: str,
    category: str = "both",
    threshold: float = 0.6,
) -> dict:
    """
    Find the best matching canonical property or yield name using fuzzy matching.

    Handles common variations such as 'API' → api_gravity, 'sulphur' → sulfur_content,
    'diesel' → diesel_yield, 'kerosene' → jet_fuel_yield.

    PARAMETERS:
        property_name : str   — property/yield name as typed by the user
        category      : str   — restrict search to 'property', 'yield', or 'both'
                                (default 'both')
        threshold     : float — minimum similarity score 0–1 (default 0.6)

    RETURNS:
        Matched canonical name, category (property/yield), description, unit,
        similarity score, and alternatives.

    LOOP REQUIREMENTS:
        For multiple property names, call once per name.

    RELATED TOOLS: list_properties_and_yields (to see all valid names)
    """
    return find_matching_property(store, property_name, category, threshold)


@mcp.tool()
def find_matching_refinery_tool(refinery_name: str, threshold: float = 0.6) -> dict:
    """
    Find the best matching refinery from available refineries using fuzzy matching.

    Matches against refinery ID, name, location, and country. Handles inputs like
    'houston', 'REF001', 'gulf coast refinery', 'Singapore plant'.

    PARAMETERS:
        refinery_name : str   — refinery name, ID, or location typed by the user
        threshold     : float — minimum similarity score 0–1 (default 0.6)

    RETURNS:
        Matched refinery record (id, name, location, country) with similarity score
        and alternatives.

    LOOP REQUIREMENTS:
        For multiple refinery names, call once per name.

    RELATED TOOLS: list_available_refineries, get_refinery_id
    """
    return find_matching_refinery(store, refinery_name, threshold)


@mcp.tool()
def get_refinery_id_tool(refinery_name: str) -> dict:
    """
    Get the refinery ID for a given refinery name using exact case-insensitive match.

    Use this when you already have the exact refinery name and need its ID.
    Use find_matching_refinery_tool instead when the name may have typos.

    PARAMETERS:
        refinery_name : str — exact refinery name, e.g. 'Refinery A'

    RETURNS:
        refinery_id, confirmed name, location, and country.

    RELATED TOOLS: find_matching_refinery_tool (for fuzzy / partial names)
    """
    return get_refinery_id(store, refinery_name)


# ===========================================================================
# FORECASTING — 1 tool
# ===========================================================================

@mcp.tool()
def forecast_tool_mcp(
    crude_name: str,
    target_date: str,
    metric: str = "price",
    refinery_id: Optional[str] = None,
) -> dict:
    """
    Forecast crude oil price, physical properties, or refinery yields for a
    SINGLE target month. Call once per (crude_name, target_date) combination.

    PARAMETERS:
        crude_name  : str  — canonical crude name, e.g. 'Brent', 'WTI', 'Dubai'.
                             Use find_matching_crude_tool first if unsure of the name.
        target_date : str  — target date in YYYY-MM-DD format.
                             Returns data for the nearest available forecast date
                             within ±45 days.
        metric      : str  — one of 'price' | 'properties' | 'yield'
                             Default: 'price'
        refinery_id : str  — refinery ID (e.g. 'REF_001').
                             REQUIRED when metric='yield'.
                             Optional for 'price' (adds delivered price) and
                             'properties' (adds refinery-specific specs).

    RETURNS (metric='price'):
        spot_price, delivered_price, delivery_cost, confidence_interval,
        forecast_model, confidence_score, price_source.

    RETURNS (metric='properties'):
        api_gravity, sulfur_content, viscosity, pour_point, tan, density_kg_m3,
        confidence_api, confidence_sulfur, forecast_model, confidence_score.

    RETURNS (metric='yield'):
        gasoline_yield, diesel_yield, jet_fuel_yield, fuel_oil_yield,
        lpg_yield, naphtha_yield, other_yield, confidence_interval,
        forecast_model, confidence_score.

    USAGE:
        - For multiple months: call once per month.
        - For buy/hold decisions: combine with get_market_context_tool.

    RELATED TOOLS:
        find_matching_crude_tool, list_available_refineries_tool,
        get_market_context_tool
    """
    return forecast_tool(store, crude_name, target_date, metric, refinery_id)


# ===========================================================================
# BLENDING — 1 tool
# ===========================================================================

@mcp.tool()
def blend_simulator_tool_mcp(
    crude_names: list[str],
    proportions: list[float],
    refinery_id: Optional[str] = None,
) -> dict:
    """
    Simulate blending two or more crude oils. Returns blended physical properties
    and estimated product yield profile.

    PARAMETERS:
        crude_names : list[str]   — 2 or more canonical crude names.
                                    Use find_matching_crude_tool to validate names.
                                    Example: ['Brent', 'WTI']
        proportions : list[float] — volume fractions for each crude, must sum to 1.0
                                    (±0.05 tolerance; auto-normalised).
                                    Example: [0.6, 0.4]
        refinery_id : str         — optional refinery ID for refinery-specific yields.
                                    When omitted, yields come from stored blend simulations.

    RETURNS:
        blend_composition, blend_properties (api_gravity, sulfur_content, viscosity,
        pour_point, tan, density_kg_m3), product_yields (gasoline, diesel, jet_fuel,
        fuel_oil, lpg, naphtha, other), yield_source, confidence_score, notes.

    USAGE:
        - Use to evaluate a specific crude mix before purchasing.
        - Combine with constraint_checker_tool to verify spec compliance.

    RELATED TOOLS:
        find_matching_crude_tool, constraint_checker_tool,
        profitability_calculator_tool
    """
    return blend_simulator_tool(store, crude_names, proportions, refinery_id)


# ===========================================================================
# ANALYSIS — 6 tools
# ===========================================================================

@mcp.tool()
def constraint_checker_tool_mcp(
    crude_names: list[str],
    proportions: list[float],
    constraints: dict,
) -> dict:
    """
    Check whether a crude blend satisfies specified physical property constraints.

    PARAMETERS:
        crude_names  : list[str]   — crudes in the blend
        proportions  : list[float] — volume fractions (must sum to 1.0 ±0.05)
        constraints  : dict        — property bounds.
                                     Keys are property names (api_gravity,
                                     sulfur_content, viscosity, pour_point,
                                     tan, density_kg_m3).
                                     Values are dicts with 'min' and/or 'max'.
                                     Example:
                                       {
                                         'sulfur_content': {'max': 1.5},
                                         'api_gravity':    {'min': 30, 'max': 45}
                                       }

    RETURNS:
        all_constraints_satisfied (bool), blend_properties, constraint_results
        (per-property pass/fail), violations (list of exceeded limits with excess).

    USAGE:
        - Use after blend_simulator_tool to verify spec compliance.
        - Use after optimizer_tool to validate the optimal blend.

    RELATED TOOLS:
        blend_simulator_tool_mcp, optimizer_tool_mcp,
        list_properties_and_yields_tool
    """
    return constraint_checker_tool(store, crude_names, proportions, constraints)


@mcp.tool()
def price_calculator_tool_mcp(
    crude_names: list[str],
    proportions: list[float],
    volume: float,
    target_date: Optional[str] = None,
    refinery_id: Optional[str] = None,
) -> dict:
    """
    Calculate the total delivered cost of a crude blend for a given volume.

    PARAMETERS:
        crude_names  : list[str]   — crudes in the blend
        proportions  : list[float] — volume fractions (must sum to 1.0 ±0.05)
        volume       : float       — total volume in barrels (must be > 0)
        target_date  : str         — YYYY-MM-DD; uses nearest available price forecast.
                                     Defaults to today if omitted.
        refinery_id  : str         — optional; uses refinery-specific delivered prices
                                     (spot + transport cost) when provided.

    RETURNS:
        total_cost_usd, cost_per_barrel, currency ('USD'), volume_bbl,
        per-crude breakdown (proportion, price_per_barrel, volume_bbl,
        subtotal_usd, price_source), refinery_id, target_date.

    USAGE:
        - Use to evaluate procurement cost for a candidate blend.
        - Combine with profitability_calculator_tool for full P&L.

    RELATED TOOLS:
        profitability_calculator_tool_mcp, forecast_tool_mcp
    """
    return price_calculator_tool(
        store, crude_names, proportions, volume, target_date, refinery_id
    )


@mcp.tool()
def profitability_calculator_tool_mcp(
    crude_names: list[str],
    proportions: list[float],
    volume: float,
    refinery_id: str,
    target_date: Optional[str] = None,
) -> dict:
    """
    Calculate the gross profitability of processing a crude blend at a refinery.
    Revenue from refined products minus crude procurement cost.

    PARAMETERS:
        crude_names  : list[str]   — crudes in the blend
        proportions  : list[float] — volume fractions (must sum to 1.0 ±0.05)
        volume       : float       — processing volume in barrels
        refinery_id  : str         — refinery ID (required)
        target_date  : str         — YYYY-MM-DD (defaults to nearest future forecast)

    RETURNS:
        total_revenue_usd, total_cost_usd, gross_profit_usd, profit_margin_pct,
        roi_pct, per-product revenues (yield_pct, volume_bbl, price_per_bbl,
        revenue_usd), cost_breakdown, refinery_id, target_date, yield_source.

    USAGE:
        - Use to compare which crude or blend is most profitable.
        - Use after optimizer_tool to quantify profit of the optimal blend.

    RELATED TOOLS:
        optimizer_tool_mcp, price_calculator_tool_mcp, forecast_tool_mcp
    """
    return profitability_calculator_tool(
        store, crude_names, proportions, volume, refinery_id, target_date
    )


@mcp.tool()
def optimizer_tool_mcp(
    objective: str,
    target_product: str = "diesel",
    constraints: Optional[dict] = None,
    available_crudes: Optional[list[str]] = None,
    refinery_id: Optional[str] = None,
    target_date: Optional[str] = None,
) -> dict:
    """
    Find the optimal crude blend using linear programming.

    Supports three objectives:
      - 'maximize_yield'  : maximise product yield (e.g. diesel) subject to constraints
      - 'minimize_cost'   : minimise blended crude cost per barrel
      - 'maximize_profit' : maximise gross profit (yield value minus crude cost)

    PARAMETERS:
        objective        : str        — 'maximize_yield' | 'minimize_cost' | 'maximize_profit'
        target_product   : str        — product for maximize_yield / maximize_profit
                                        ('diesel', 'gasoline', 'jet_fuel', 'fuel_oil',
                                         'lpg', 'naphtha'). Default: 'diesel'
        constraints      : dict       — optional property bounds, e.g.:
                                          {'sulfur_content': {'max': 1.5},
                                           'api_gravity':    {'min': 30}}
        available_crudes : list[str]  — optional subset of crudes to consider.
                                        Default: all 10 available crudes.
        refinery_id      : str        — optional refinery for yield and price data
        target_date      : str        — YYYY-MM-DD (defaults to nearest future forecast)

    RETURNS:
        optimal_blend (crude_names + proportions), objective_value, blend_properties,
        product_yields, constraints_satisfied, target_product, objective, solver_status.

    USAGE:
        - For 'What is the optimal blend to maximise diesel yield under 1.5% sulfur?'
        - Follow up with constraint_checker_tool to verify and profitability_calculator_tool for P&L.

    RELATED TOOLS:
        constraint_checker_tool_mcp, profitability_calculator_tool_mcp,
        get_high_yield_crudes_tool
    """
    return optimizer_tool(
        store, objective, target_product, constraints,
        available_crudes, refinery_id, target_date,
    )


@mcp.tool()
def get_high_yield_crudes_tool(
    target_month: str,
    refinery_id: str,
    product: str = "diesel",
    max_sulfur: float = 1.5,
    top_n: int = 5,
) -> dict:
    """
    Rank all available crudes by their forecasted yield of a target product in
    a given month, filtered by a maximum sulfur content.

    Directly answers: 'Which crudes give the highest diesel yield under 1.5%
    sulfur in August 2026?'

    PARAMETERS:
        target_month : str   — YYYY-MM-DD; data for the nearest forecast date is used
        refinery_id  : str   — refinery ID (required for yield lookup)
        product      : str   — product to rank by: 'diesel', 'gasoline', 'jet_fuel',
                               'fuel_oil', 'lpg', 'naphtha'. Default: 'diesel'
        max_sulfur   : float — maximum sulfur content in % weight (default: 1.5)
        top_n        : int   — number of top results to return (default: 5)

    RETURNS:
        Ranked list of crudes with yield_pct, sulfur_content, forecasted_price,
        confidence_score; plus total_candidates and filtered_out counts.

    USAGE:
        - Use as a fast single-call alternative to looping forecast_tool over all crudes.
        - Follow up with blend_simulator_tool to evaluate the top candidates as a blend.

    RELATED TOOLS:
        forecast_tool_mcp, blend_simulator_tool_mcp, optimizer_tool_mcp
    """
    return get_high_yield_crudes(
        store, target_month, refinery_id, product, max_sulfur, top_n
    )


@mcp.tool()
def get_market_context_tool(
    product_type: str,
    from_date: str,
    to_date: str,
    crude_name: Optional[str] = None,
) -> dict:
    """
    Return market context for a refined product over a date range:
    demand trend, price sentiment, inventory levels, average sentiment score,
    and an overall recommendation signal (BUY / HOLD / CAUTION).

    Optionally includes crude-level supply/demand balance.

    PARAMETERS:
        product_type : str — product matching available data: 'Diesel', 'Gasoline',
                             'Jet Fuel'. Case-insensitive partial match attempted.
        from_date    : str — start date YYYY-MM-DD
        to_date      : str — end date YYYY-MM-DD
        crude_name   : str — optional; if provided, also returns supply/demand
                             balance (supply_volume, demand_volume, balance) for
                             that crude in the date range.

    RETURNS:
        market_trends (list of weekly records), summary (dominant_demand_trend,
        dominant_price_trend, avg_sentiment, recommendation_signal),
        and optionally supply_demand list.

    USAGE:
        - Use for buy/hold decisions on a product.
        - Combine with forecast_tool_mcp for a complete market picture.

    RELATED TOOLS: forecast_tool_mcp, get_high_yield_crudes_tool
    """
    return get_market_context(store, product_type, from_date, to_date, crude_name)


# ===========================================================================
# HEAD-probe middleware
# ===========================================================================
# watsonx (and other API gateways) send a HEAD request to validate the endpoint
# before registering it.  FastMCP/Starlette returns 405 on HEAD, which causes
# the gateway to report a 502.  This thin ASGI wrapper intercepts HEAD requests
# to /mcp and /sse and replies 200 OK so the health-check passes.

class HeadProbeMiddleware:
    """Return 200 OK for HEAD requests to MCP paths (gateway health checks)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "HEAD":
            path = scope.get("path", "")
            if path in ("/mcp", "/sse", "/messages/"):
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-length", b"0"),
                        (b"content-type", b"application/json"),
                        (b"x-mcp-server", b"feedstock-advisor"),
                    ],
                })
                await send({"type": "http.response.body", "body": b""})
                return
        await self.app(scope, receive, send)


# ===========================================================================
# Entry-point
# ===========================================================================

if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Feedstock Advisor MCP server (HTTP transport)…")
    logger.info("  Streamable HTTP : http://%s:%d/mcp", _HOST, _PORT)
    logger.info("  Legacy SSE      : http://%s:%d/sse", _HOST, _PORT)
    logger.info("Press Ctrl+C to stop.")

    # Build the ASGI app from FastMCP, wrap it with the HEAD middleware, then
    # hand it directly to uvicorn so we keep full control over the app stack.
    asgi_app = HeadProbeMiddleware(mcp.streamable_http_app())
    uvicorn.run(asgi_app, host=_HOST, port=_PORT)
