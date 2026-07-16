"""
tools/analysis.py
-----------------
Analysis tools for the Feedstock Advisor MCP Server.

Tools (6)
---------
1. constraint_checker_tool      – check blend against property / quality constraints
2. price_calculator_tool        – total delivered cost of a crude blend
3. profitability_calculator_tool – gross profit, margin, ROI for a blend at a refinery
4. optimizer_tool               – LP-based optimal blend (maximize yield/profit,
                                  minimize cost) subject to constraints
5. get_high_yield_crudes        – rank crudes by product yield filtered by max sulfur
6. get_market_context           – demand trend, price sentiment, supply/demand balance

Response envelope
-----------------
All tools return::

    {"status": "success", "data": {...}}
    {"status": "failure", "error": "<message>"}
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from config import (
    DATE_MATCH_TOLERANCE_DAYS,
    DEFAULT_MAX_SULFUR,
    DEFAULT_OPTIMISE_PRODUCT,
    DEFAULT_TOP_N,
    PRODUCT_PRICES_USD_PER_BBL,
)
from tools.blend_simulator import (
    _PROP_COLS,
    _YIELD_COLS,
    _blend_properties,
    _yields_from_forecasts,
    _yields_from_history,
)
from tools.forecast import _nearest_row, _safe_float, _safe_str

logger = logging.getLogger(__name__)

# Map yield column names → product price key in PRODUCT_PRICES_USD_PER_BBL
_YIELD_TO_PRICE_KEY: dict[str, str] = {
    "gasoline_yield":  "gasoline",
    "diesel_yield":    "diesel",
    "jet_fuel_yield":  "jet_fuel",
    "fuel_oil_yield":  "fuel_oil",
    "lpg_yield":       "lpg",
    "naphtha_yield":   "naphtha",
    "other_yield":     "other",
}

# Crude properties that can appear in user constraints
_CONSTRAINABLE_PROPS = set(_PROP_COLS)

# Map spec specification names → property column names (for quality_specs.csv)
_SPEC_TO_PROP: dict[str, str] = {
    "sulfur content": "sulfur_content",
    "api gravity":    "api_gravity",
    "viscosity":      "viscosity",
    "pour point":     "pour_point",
    "tan":            "tan",
    "density":        "density_kg_m3",
}


# ---------------------------------------------------------------------------
# Shared date helpers
# ---------------------------------------------------------------------------

def _window_dates(
    target_date: str | None,
    tolerance_days: int = DATE_MATCH_TOLERANCE_DAYS,
) -> tuple[pd.Timestamp, date, date]:
    """Return (target_ts, from_dt, to_dt) for a date string or today."""
    if target_date:
        try:
            ts = pd.Timestamp(target_date)
        except Exception:
            ts = pd.Timestamp.now()
    else:
        ts = pd.Timestamp.now()
    window  = timedelta(days=tolerance_days)
    from_dt = (ts - window).date()
    to_dt   = (ts + window).date()
    return ts, from_dt, to_dt


def _get_spot_price(
    store: Any,
    crude_name: str,
    target_ts: pd.Timestamp,
    refinery_id: str | None = None,
) -> float | None:
    """
    Return best available price for crude at target_ts.
    Preference: delivered (refinery-specific) > forecasted spot > historical.
    """
    window  = timedelta(days=DATE_MATCH_TOLERANCE_DAYS)
    from_dt = (target_ts - window).date()
    to_dt   = (target_ts + window).date()

    # 1. Delivered price for this refinery
    if refinery_id:
        df = store.get_delivered_price_forecast(crude_name, refinery_id, from_dt, to_dt)
        row = _nearest_row(df, "forecast_date", target_ts)
        if row is not None:
            p = _safe_float(row.get("total_predicted_price"))
            if p:
                return p

    # 2. Spot forecast
    df = store.get_forecasted_prices(crude_name, from_dt, to_dt)
    row = _nearest_row(df, "forecast_date", target_ts)
    if row is not None:
        p = _safe_float(row.get("predicted_price"))
        if p:
            return p

    # 3. Recent historical
    hist_from = (target_ts - timedelta(days=90)).date()
    df = store.get_historical_prices(crude_name, hist_from, target_ts.date())
    if not df.empty:
        df = df.sort_values("date")
        return _safe_float(df.iloc[-1].get("price_usd_per_barrel"))

    return None


def _get_delivery_cost(
    store: Any,
    refinery_location: str,
    crude_region: str | None = None,
) -> float:
    """
    Return the cheapest delivery cost per barrel for a given refinery location.
    Falls back to 0.0 if no route found.
    """
    df = store.get_transport_costs(destination=refinery_location)
    if df.empty:
        # Try partial match on destination column
        all_df = store.get_transport_costs()
        df = all_df[
            all_df["destination"].str.lower().str.contains(
                refinery_location.lower(), na=False
            )
        ]
    if df.empty:
        return 0.0
    # Return the lowest cost_per_barrel
    return float(df["cost_per_barrel"].min())


# ---------------------------------------------------------------------------
# 1. constraint_checker_tool
# ---------------------------------------------------------------------------

def constraint_checker_tool(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    constraints: dict,
) -> dict:
    """
    Check whether a crude blend satisfies the specified property constraints.

    Parameters
    ----------
    store        : data provider
    crude_names  : crudes in the blend
    proportions  : volume fractions (must sum to 1.0 ±0.05)
    constraints  : dict mapping property name → bound dict.
                   Each bound dict may have "min" and/or "max" keys.
                   Example::

                       {
                         "sulfur_content": {"max": 1.5},
                         "api_gravity":    {"min": 30, "max": 45}
                       }

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "all_constraints_satisfied": false,
            "blend_properties": {"api_gravity": 38.1, "sulfur_content": 1.82, ...},
            "constraint_results": [
              {"property": "sulfur_content", "limit": {"max": 1.5},
               "actual": 1.82, "passed": false},
              {"property": "api_gravity", "limit": {"min": 30},
               "actual": 38.1, "passed": true}
            ],
            "violations": [
              {"property": "sulfur_content", "limit": {"max": 1.5},
               "actual": 1.82, "excess": 0.32}
            ]
          }
        }
    """
    try:
        # Validate proportions
        if len(crude_names) != len(proportions):
            return {"status": "failure",
                    "error": "crude_names and proportions must have the same length."}
        total = sum(proportions)
        if abs(total - 1.0) > 0.05:
            return {"status": "failure",
                    "error": f"Proportions sum to {total:.4f}; must be 1.0 (±0.05)."}
        proportions = [p / total for p in proportions]

        props = _blend_properties(store, crude_names, proportions)

        constraint_results = []
        violations = []

        for prop_name, bounds in constraints.items():
            actual = props.get(prop_name)
            passed = True
            excess = None

            if actual is None:
                constraint_results.append({
                    "property": prop_name,
                    "limit":    bounds,
                    "actual":   None,
                    "passed":   False,
                    "note":     "Property not found in blend data.",
                })
                violations.append({"property": prop_name, "note": "data unavailable"})
                continue

            lo = bounds.get("min")
            hi = bounds.get("max")

            if lo is not None and actual < lo:
                passed = False
                excess = round(lo - actual, 4)
            if hi is not None and actual > hi:
                passed = False
                excess = round(actual - hi, 4)

            constraint_results.append({
                "property": prop_name,
                "limit":    bounds,
                "actual":   actual,
                "passed":   passed,
            })
            if not passed:
                violations.append({
                    "property": prop_name,
                    "limit":    bounds,
                    "actual":   actual,
                    "excess":   excess,
                })

        all_ok = all(r["passed"] for r in constraint_results)

        return {
            "status": "success",
            "data": {
                "all_constraints_satisfied": all_ok,
                "blend_properties":          props,
                "constraint_results":        constraint_results,
                "violations":                violations,
            },
        }

    except Exception as exc:
        logger.error("[constraint_checker_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# 2. price_calculator_tool
# ---------------------------------------------------------------------------

def price_calculator_tool(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    volume: float,
    target_date: str | None = None,
    refinery_id: str | None = None,
) -> dict:
    """
    Calculate the total delivered cost of a crude blend at a refinery
    for a given volume.

    Parameters
    ----------
    store        : data provider
    crude_names  : crudes in the blend
    proportions  : volume fractions (must sum to 1.0 ±0.05)
    volume       : total volume in barrels
    target_date  : YYYY-MM-DD; uses nearest forecast (default: today)
    refinery_id  : adds refinery-specific delivered price and transport cost

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "total_cost_usd":  840500.0,
            "cost_per_barrel": 84.05,
            "currency":        "USD",
            "volume_bbl":      10000,
            "breakdown": [
              {
                "crude_name":       "Brent",
                "proportion":       0.6,
                "price_per_barrel": 90.2,
                "volume_bbl":       6000,
                "subtotal_usd":     541200.0,
                "price_source":     "forecasted_delivered"
              },
              ...
            ],
            "refinery_id":  "REF_001",
            "target_date":  "2026-06-08"
          }
        }
    """
    try:
        if len(crude_names) != len(proportions):
            return {"status": "failure",
                    "error": "crude_names and proportions must have the same length."}
        total_prop = sum(proportions)
        if abs(total_prop - 1.0) > 0.05:
            return {"status": "failure",
                    "error": f"Proportions sum to {total_prop:.4f}; must be 1.0 (±0.05)."}
        if volume <= 0:
            return {"status": "failure", "error": "volume must be a positive number."}

        proportions = [p / total_prop for p in proportions]
        target_ts, _, _ = _window_dates(target_date)

        breakdown = []
        total_cost = 0.0
        actual_date_used = None

        for crude, prop in zip(crude_names, proportions):
            price = _get_spot_price(store, crude, target_ts, refinery_id)

            # Determine price source label
            if price is None:
                price_source = "unavailable"
                price = 0.0
            elif refinery_id:
                df_del = store.get_delivered_price_forecast(
                    crude, refinery_id,
                    (target_ts - timedelta(days=DATE_MATCH_TOLERANCE_DAYS)).date(),
                    (target_ts + timedelta(days=DATE_MATCH_TOLERANCE_DAYS)).date(),
                )
                row = _nearest_row(df_del, "forecast_date", target_ts)
                price_source = "forecasted_delivered" if row is not None else "forecasted_spot"
                if actual_date_used is None and row is not None:
                    actual_date_used = row["forecast_date"].strftime("%Y-%m-%d")
            else:
                price_source = "forecasted_spot"

            crude_vol  = volume * prop
            subtotal   = price * crude_vol
            total_cost += subtotal

            breakdown.append({
                "crude_name":       crude,
                "proportion":       round(prop, 4),
                "price_per_barrel": round(price, 4),
                "volume_bbl":       round(crude_vol, 2),
                "subtotal_usd":     round(subtotal, 2),
                "price_source":     price_source,
            })

        return {
            "status": "success",
            "data": {
                "total_cost_usd":  round(total_cost, 2),
                "cost_per_barrel": round(total_cost / volume, 4) if volume else None,
                "currency":        "USD",
                "volume_bbl":      volume,
                "breakdown":       breakdown,
                "refinery_id":     refinery_id,
                "target_date":     actual_date_used or target_ts.strftime("%Y-%m-%d"),
            },
        }

    except Exception as exc:
        logger.error("[price_calculator_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# 3. profitability_calculator_tool
# ---------------------------------------------------------------------------

def profitability_calculator_tool(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    volume: float,
    refinery_id: str,
    target_date: str | None = None,
) -> dict:
    """
    Calculate the gross profitability of processing a crude blend at a
    refinery: revenue from refined products minus crude procurement cost.

    Parameters
    ----------
    store        : data provider
    crude_names  : crudes in the blend
    proportions  : volume fractions (must sum to 1.0 ±0.05)
    volume       : processing volume in barrels
    refinery_id  : refinery ID (required)
    target_date  : YYYY-MM-DD (default: nearest future forecast)

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "total_revenue_usd":  1050000.0,
            "total_cost_usd":      840500.0,
            "gross_profit_usd":    209500.0,
            "profit_margin_pct":      19.95,
            "roi_pct":               24.92,
            "product_revenues": {
              "diesel":   {"yield_pct": 34.2, "volume_bbl": 3420,
                           "price_per_bbl": 120.0, "revenue_usd": 410400.0},
              ...
            },
            "cost_breakdown": {
              "crude_cost_usd": 800000.0
            },
            "refinery_id":  "REF_001",
            "target_date":  "2026-06-08",
            "yield_source": "forecasted"
          }
        }
    """
    try:
        if len(crude_names) != len(proportions):
            return {"status": "failure",
                    "error": "crude_names and proportions must have the same length."}
        total_prop = sum(proportions)
        if abs(total_prop - 1.0) > 0.05:
            return {"status": "failure",
                    "error": f"Proportions sum to {total_prop:.4f}; must be 1.0 (±0.05)."}
        if volume <= 0:
            return {"status": "failure", "error": "volume must be a positive number."}

        proportions = [p / total_prop for p in proportions]
        target_ts, from_dt, to_dt = _window_dates(target_date)

        # ── Crude cost ────────────────────────────────────────────────────
        price_result = price_calculator_tool(
            store, crude_names, proportions, volume, target_date, refinery_id
        )
        if price_result["status"] != "success":
            return price_result
        crude_cost = price_result["data"]["total_cost_usd"]
        actual_date = price_result["data"]["target_date"]

        # ── Yields ────────────────────────────────────────────────────────
        yields, yield_source, _ = _yields_from_forecasts(
            store, crude_names, proportions, refinery_id
        )
        if not any(v is not None for v in yields.values()):
            yields, yield_source = _yields_from_history(
                store, crude_names, proportions, refinery_id
            )

        # ── Revenue ───────────────────────────────────────────────────────
        product_revenues: dict[str, dict] = {}
        total_revenue = 0.0

        for yield_col, price_key in _YIELD_TO_PRICE_KEY.items():
            yield_pct = yields.get(yield_col)
            if yield_pct is None or yield_pct <= 0:
                continue
            prod_vol  = volume * (yield_pct / 100.0)
            price_bbl = PRODUCT_PRICES_USD_PER_BBL.get(price_key, 0.0)
            revenue   = prod_vol * price_bbl
            total_revenue += revenue
            product_name  = price_key
            product_revenues[product_name] = {
                "yield_pct":    round(yield_pct, 4),
                "volume_bbl":   round(prod_vol, 2),
                "price_per_bbl": price_bbl,
                "revenue_usd":  round(revenue, 2),
            }

        gross_profit   = total_revenue - crude_cost
        profit_margin  = (gross_profit / total_revenue * 100) if total_revenue else 0.0
        roi            = (gross_profit / crude_cost * 100) if crude_cost else 0.0

        return {
            "status": "success",
            "data": {
                "total_revenue_usd":  round(total_revenue, 2),
                "total_cost_usd":     round(crude_cost, 2),
                "gross_profit_usd":   round(gross_profit, 2),
                "profit_margin_pct":  round(profit_margin, 4),
                "roi_pct":            round(roi, 4),
                "product_revenues":   product_revenues,
                "cost_breakdown": {
                    "crude_cost_usd": round(crude_cost, 2),
                },
                "refinery_id":  refinery_id,
                "target_date":  actual_date,
                "yield_source": yield_source,
            },
        }

    except Exception as exc:
        logger.error("[profitability_calculator_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# 4. optimizer_tool
# ---------------------------------------------------------------------------

def optimizer_tool(
    store: Any,
    objective: str,
    target_product: str = DEFAULT_OPTIMISE_PRODUCT,
    constraints: dict | None = None,
    available_crudes: list[str] | None = None,
    refinery_id: str | None = None,
    target_date: str | None = None,
) -> dict:
    """
    Find the optimal crude blend using linear programming (scipy linprog).

    Objectives
    ----------
    - ``"maximize_yield"``  – maximise the yield of ``target_product``
    - ``"minimize_cost"``   – minimise blended crude cost per barrel
    - ``"maximize_profit"`` – maximise gross profit margin

    Parameters
    ----------
    store            : data provider
    objective        : one of "maximize_yield" | "minimize_cost" | "maximize_profit"
    target_product   : product to optimise (for maximize_yield); default "diesel"
    constraints      : property bounds dict, e.g.
                       ``{"sulfur_content": {"max": 1.5}, "api_gravity": {"min": 30}}``
    available_crudes : subset of crudes to consider; default = all crudes
    refinery_id      : refinery for yield/cost lookup
    target_date      : YYYY-MM-DD

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "optimal_blend": {
              "crude_names":  ["Bonny Light", "WTI"],
              "proportions":  [0.65, 0.35]
            },
            "objective_value":      35.8,
            "blend_properties":     {...},
            "product_yields":       {...},
            "constraints_satisfied": true,
            "target_product":       "diesel",
            "objective":            "maximize_yield",
            "solver_status":        "optimal"
          }
        }
    """
    try:
        valid_objectives = ("maximize_yield", "minimize_cost", "maximize_profit")
        if objective not in valid_objectives:
            return {"status": "failure",
                    "error": f"objective must be one of {valid_objectives}."}

        constraints  = constraints or {}
        target_ts, from_dt, to_dt = _window_dates(target_date)

        # ── Build crude universe ──────────────────────────────────────────
        all_crudes_df = store.get_static_properties()
        all_crudes    = all_crudes_df["crude_name"].dropna().unique().tolist()
        crudes = available_crudes if available_crudes else all_crudes
        # Filter to crudes that actually have properties
        crudes = [c for c in crudes if not all_crudes_df[all_crudes_df["crude_name"] == c].empty]

        n = len(crudes)
        if n == 0:
            return {"status": "failure", "error": "No valid crudes available for optimisation."}

        # ── Build data matrices ───────────────────────────────────────────
        # yields[i][col] and prices[i] for each crude i
        yield_col = f"{target_product}_yield" if not target_product.endswith("_yield") else target_product

        yield_vec   = np.zeros(n)
        price_vec   = np.zeros(n)
        prop_matrix = {col: np.zeros(n) for col in _PROP_COLS}

        for i, crude in enumerate(crudes):
            # Yield
            df_y = store.get_yield_forecast(
                crude, refinery_id, from_dt, to_dt
            ) if refinery_id else pd.DataFrame()

            if df_y.empty:
                # Try any refinery
                all_y = store.get_all_yield_forecasts()
                df_y = all_y[all_y["crude_name"] == crude]

            if not df_y.empty:
                row_y = _nearest_row(df_y, "forecast_date", target_ts)
                if row_y is not None and yield_col in row_y.index:
                    v = _safe_float(row_y.get(yield_col))
                    yield_vec[i] = v if v is not None else 0.0

            # Price
            p = _get_spot_price(store, crude, target_ts, refinery_id)
            price_vec[i] = p if p is not None else 999.0

            # Properties
            prop_row = all_crudes_df[all_crudes_df["crude_name"] == crude]
            if not prop_row.empty:
                for col in _PROP_COLS:
                    v = _safe_float(prop_row.iloc[0].get(col))
                    prop_matrix[col][i] = v if v is not None else 0.0

        # ── Objective vector (linprog minimises, so negate for maximise) ─
        if objective == "maximize_yield":
            c = -yield_vec
        elif objective == "minimize_cost":
            c = price_vec
        else:  # maximize_profit — proxy: maximise (yield × product_price - crude_price)
            prod_price = PRODUCT_PRICES_USD_PER_BBL.get(target_product, 120.0)
            c = -(yield_vec / 100.0 * prod_price - price_vec)

        # ── Bounds: each proportion in [0, 1] ────────────────────────────
        bounds = [(0.0, 1.0)] * n

        # ── Equality constraint: proportions sum to 1 ────────────────────
        A_eq = np.ones((1, n))
        b_eq = np.array([1.0])

        # ── Property inequality constraints ───────────────────────────────
        A_ub_rows = []
        b_ub_rows = []

        for prop_name, bounds_dict in constraints.items():
            if prop_name not in prop_matrix:
                continue
            prop_vec = prop_matrix[prop_name]
            lo = bounds_dict.get("min")
            hi = bounds_dict.get("max")
            # Ax <= b form
            # max bound: prop_vec @ x <= hi  →  prop_vec @ x <= hi
            if hi is not None:
                A_ub_rows.append(prop_vec)
                b_ub_rows.append(hi)
            # min bound: -prop_vec @ x <= -lo
            if lo is not None:
                A_ub_rows.append(-prop_vec)
                b_ub_rows.append(-lo)

        A_ub = np.array(A_ub_rows) if A_ub_rows else None
        b_ub = np.array(b_ub_rows) if b_ub_rows else None

        # ── Solve ─────────────────────────────────────────────────────────
        result = linprog(
            c,
            A_ub=A_ub, b_ub=b_ub,
            A_eq=A_eq, b_eq=b_eq,
            bounds=bounds,
            method="highs",
        )

        if not result.success:
            return {
                "status": "failure",
                "error": (
                    f"LP solver could not find a feasible solution: {result.message}. "
                    "Try relaxing the constraints."
                ),
            }

        raw_props = result.x
        # Round tiny values to 0, re-normalise
        raw_props = np.where(raw_props < 1e-4, 0.0, raw_props)
        if raw_props.sum() < 1e-6:
            return {"status": "failure", "error": "Solver returned zero proportions."}
        raw_props = raw_props / raw_props.sum()

        # ── Pick crudes with non-trivial proportion (>1%) ─────────────────
        selected = [(crudes[i], float(raw_props[i]))
                    for i in range(n) if raw_props[i] >= 0.01]
        if not selected:
            selected = [(crudes[int(np.argmax(raw_props))], 1.0)]

        sel_names = [s[0] for s in selected]
        sel_props_raw = [s[1] for s in selected]
        total_sel = sum(sel_props_raw)
        sel_props = [p / total_sel for p in sel_props_raw]

        # ── Compute achieved objective value ──────────────────────────────
        achieved_yield = sum(
            yield_vec[crudes.index(c)] * p
            for c, p in zip(sel_names, sel_props)
            if c in crudes
        )
        achieved_cost = sum(
            price_vec[crudes.index(c)] * p
            for c, p in zip(sel_names, sel_props)
            if c in crudes
        )
        if objective == "maximize_yield":
            obj_value = round(achieved_yield, 4)
        elif objective == "minimize_cost":
            obj_value = round(achieved_cost, 4)
        else:
            prod_price = PRODUCT_PRICES_USD_PER_BBL.get(target_product, 120.0)
            obj_value = round(achieved_yield / 100.0 * prod_price - achieved_cost, 4)

        # ── Blend properties & yields for selected blend ──────────────────
        blend_props = _blend_properties(store, sel_names, sel_props)

        blend_yields: dict[str, float | None] = {}
        if refinery_id:
            fy, _, _ = _yields_from_forecasts(store, sel_names, sel_props, refinery_id)
            blend_yields = fy if any(v for v in fy.values()) else {}
        if not blend_yields:
            for yield_col_check in _YIELD_COLS:
                idx_sum = 0.0
                val_sum = 0.0
                for c, p in zip(sel_names, sel_props):
                    if c in crudes:
                        i = crudes.index(c)
                        row_check = store.get_all_yield_forecasts()
                        row_check = row_check[row_check["crude_name"] == c]
                        if not row_check.empty:
                            row_near = _nearest_row(row_check, "forecast_date", target_ts)
                            if row_near is not None:
                                v = _safe_float(row_near.get(yield_col_check))
                                if v is not None:
                                    val_sum += v * p
                                    idx_sum += p
                blend_yields[yield_col_check] = round(val_sum / idx_sum, 4) if idx_sum > 0 else None

        # ── Verify constraints on the solution (1% relative tolerance) ────
        _TOL = 0.01
        constraints_satisfied = True
        for prop_name, bounds_dict in constraints.items():
            actual = blend_props.get(prop_name)
            if actual is None:
                continue
            hi = bounds_dict.get("max")
            lo = bounds_dict.get("min")
            if hi is not None and actual > hi * (1 + _TOL):
                constraints_satisfied = False
            if lo is not None and actual < lo * (1 - _TOL):
                constraints_satisfied = False

        return {
            "status": "success",
            "data": {
                "optimal_blend": {
                    "crude_names":  sel_names,
                    "proportions":  [round(p, 4) for p in sel_props],
                },
                "objective_value":        obj_value,
                "blend_properties":       blend_props,
                "product_yields":         blend_yields,
                "constraints_satisfied":  constraints_satisfied,
                "target_product":         target_product,
                "objective":              objective,
                "solver_status":          "optimal",
            },
        }

    except Exception as exc:
        logger.error("[optimizer_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# 5. get_high_yield_crudes
# ---------------------------------------------------------------------------

def get_high_yield_crudes(
    store: Any,
    target_month: str,
    refinery_id: str,
    product: str = "diesel",
    max_sulfur: float = DEFAULT_MAX_SULFUR,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """
    Rank all crudes by their forecasted yield of a target product in a
    given month, filtered by a maximum sulfur threshold.

    Directly answers: "Which crudes give the highest diesel yield under
    1.5% sulfur in August 2026?"

    Parameters
    ----------
    store        : data provider
    target_month : YYYY-MM-DD (month is derived from this date)
    refinery_id  : refinery to use for yield data
    product      : product to rank by — "diesel", "gasoline", "jet_fuel",
                   "fuel_oil", "lpg", "naphtha" (default: "diesel")
    max_sulfur   : maximum sulfur content in % weight (default: 1.5)
    top_n        : number of results to return (default: 5)

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "target_month":     "2026-08-07",
            "refinery_id":      "REF_001",
            "product":          "diesel",
            "max_sulfur_filter": 1.5,
            "results": [
              {
                "rank":            1,
                "crude_name":      "Bonny Light",
                "yield_pct":       38.2,
                "sulfur_content":  0.37,
                "forecasted_price": 81.2,
                "confidence_score": 0.85
              },
              ...
            ],
            "total_candidates":  10,
            "filtered_out":       7
          }
        }
    """
    try:
        yield_col = f"{product}_yield" if not product.endswith("_yield") else product

        target_ts, from_dt, to_dt = _window_dates(target_month)

        # ── Load all yield forecasts for this refinery ────────────────────
        all_yields = store.get_all_yield_forecasts()
        if all_yields.empty:
            return {"status": "failure", "error": "No yield forecast data available."}

        # Keep rows for the target refinery only
        ref_yields = all_yields[all_yields["refinery_id"] == refinery_id]
        if ref_yields.empty:
            available_refs = all_yields["refinery_id"].unique().tolist()
            return {
                "status": "failure",
                "error": (
                    f"No yield data for refinery '{refinery_id}'. "
                    f"Available refineries: {available_refs}."
                ),
            }

        # For each crude pick the nearest forecast row to target_month
        crudes = ref_yields["crude_name"].unique().tolist()
        total_candidates = len(crudes)
        rows = []
        for crude in crudes:
            df_crude = ref_yields[ref_yields["crude_name"] == crude]
            row = _nearest_row(df_crude, "forecast_date", target_ts)
            if row is None:
                continue

            yield_val = _safe_float(row.get(yield_col))
            if yield_val is None:
                continue

            # Get forecasted sulfur (prefer crude_properties_forecast, else static)
            sulfur = None
            df_prop = store.get_forecasted_properties(crude, from_dt, to_dt)
            if not df_prop.empty:
                prop_row = _nearest_row(df_prop, "forecast_date", target_ts)
                if prop_row is not None:
                    sulfur = _safe_float(prop_row.get("sulfur_content"))

            if sulfur is None:
                static = store.get_static_properties(crude)
                if not static.empty:
                    sulfur = _safe_float(static.iloc[0].get("sulfur_content"))

            if sulfur is None:
                sulfur = 9999.0   # unknown sulfur → filtered out

            rows.append({
                "crude_name":      crude,
                "yield_pct":       yield_val,
                "sulfur_content":  sulfur,
                "forecast_date":   row["forecast_date"].strftime("%Y-%m-%d"),
                "confidence_score": _safe_float(row.get("confidence_score")),
            })

        # ── Apply sulfur filter ───────────────────────────────────────────
        filtered_out = sum(1 for r in rows if r["sulfur_content"] > max_sulfur)
        passing = [r for r in rows if r["sulfur_content"] <= max_sulfur]

        if not passing:
            return {
                "status": "failure",
                "error": (
                    f"No crudes pass the max_sulfur={max_sulfur}% filter for "
                    f"refinery '{refinery_id}'. "
                    f"Checked {len(rows)} crudes; all exceeded the limit."
                ),
            }

        # ── Sort by yield descending ──────────────────────────────────────
        passing.sort(key=lambda r: r["yield_pct"], reverse=True)
        top = passing[:top_n]

        # ── Enrich with forecasted prices ─────────────────────────────────
        results = []
        for rank, r in enumerate(top, start=1):
            price = _get_spot_price(store, r["crude_name"], target_ts, refinery_id)
            results.append({
                "rank":             rank,
                "crude_name":       r["crude_name"],
                "yield_pct":        round(r["yield_pct"], 4),
                "sulfur_content":   round(r["sulfur_content"], 4),
                "forecasted_price": round(price, 4) if price else None,
                "confidence_score": r["confidence_score"],
                "forecast_date":    r["forecast_date"],
            })

        actual_date = top[0]["forecast_date"] if top else target_ts.strftime("%Y-%m-%d")

        return {
            "status": "success",
            "data": {
                "target_month":     actual_date,
                "refinery_id":      refinery_id,
                "product":          product,
                "max_sulfur_filter": max_sulfur,
                "results":          results,
                "total_candidates": total_candidates,
                "filtered_out":     filtered_out,
            },
        }

    except Exception as exc:
        logger.error("[get_high_yield_crudes] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# 6. get_market_context
# ---------------------------------------------------------------------------

def get_market_context(
    store: Any,
    product_type: str,
    from_date: str,
    to_date: str,
    crude_name: str | None = None,
) -> dict:
    """
    Return market context for a product over a date range: demand trend,
    price sentiment, inventory levels, and an overall buy/hold/caution signal.

    Optionally includes crude-level supply/demand balance.

    Parameters
    ----------
    store        : data provider
    product_type : product name matching market_trends.csv, e.g. "Diesel",
                   "Gasoline", "Jet Fuel"
    from_date    : start date YYYY-MM-DD
    to_date      : end date YYYY-MM-DD
    crude_name   : optional — also returns supply/demand balance for this crude

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "product_type": "Diesel",
            "date_range": {"from": "2026-06-01", "to": "2026-06-30"},
            "market_trends": [
              {"date": "2026-06-01", "demand_trend": "Increasing",
               "price_trend": "Bullish", "market_sentiment": 0.79,
               "inventory_level": "Normal"}
            ],
            "summary": {
              "dominant_demand_trend": "Increasing",
              "dominant_price_trend":  "Bullish",
              "avg_sentiment":          0.62,
              "recommendation_signal": "BUY"
            },
            "supply_demand": [...]   // only if crude_name provided
          }
        }
    """
    try:
        try:
            from_dt = pd.Timestamp(from_date).date()
            to_dt   = pd.Timestamp(to_date).date()
        except Exception:
            return {"status": "failure",
                    "error": "Invalid date format. Use YYYY-MM-DD for from_date and to_date."}

        if from_dt > to_dt:
            return {"status": "failure",
                    "error": "from_date must be before to_date."}

        # ── Market trends ─────────────────────────────────────────────────
        df_trends = store.get_market_trends(product_type, from_dt, to_dt)

        if df_trends.empty:
            # Try broader window ±90 days around midpoint
            mid = from_dt + (to_dt - from_dt) / 2
            broad_from = (pd.Timestamp(mid) - timedelta(days=90)).date()
            broad_to   = (pd.Timestamp(mid) + timedelta(days=90)).date()
            df_trends  = store.get_market_trends(product_type, broad_from, broad_to)
            if df_trends.empty:
                avail_products = store.get_market_trends(
                    product_type, date(2020, 1, 1), date(2030, 12, 31)
                )
                return {
                    "status": "failure",
                    "error": (
                        f"No market trend data found for product_type='{product_type}' "
                        f"in the requested date range. "
                        f"Try 'Diesel', 'Gasoline', or 'Jet Fuel'."
                    ),
                }

        trend_records = []
        for _, row in df_trends.iterrows():
            trend_records.append({
                "date":             row["date"].strftime("%Y-%m-%d"),
                "demand_trend":     _safe_str(row.get("demand_trend")),
                "price_trend":      _safe_str(row.get("price_trend")),
                "market_sentiment": _safe_float(row.get("market_sentiment")),
                "inventory_level":  _safe_str(row.get("inventory_level")),
            })

        # ── Summary statistics ────────────────────────────────────────────
        demand_counts  = Counter(r["demand_trend"] for r in trend_records if r["demand_trend"])
        price_counts   = Counter(r["price_trend"]  for r in trend_records if r["price_trend"])
        sentiments     = [r["market_sentiment"] for r in trend_records if r["market_sentiment"] is not None]

        dominant_demand = demand_counts.most_common(1)[0][0] if demand_counts else "Unknown"
        dominant_price  = price_counts.most_common(1)[0][0]  if price_counts  else "Unknown"
        avg_sentiment   = round(sum(sentiments) / len(sentiments), 4) if sentiments else None

        # Derive recommendation signal
        signal = _recommendation_signal(dominant_demand, dominant_price, avg_sentiment)

        # ── Supply / demand balance (if crude_name provided) ──────────────
        supply_demand_data = None
        if crude_name:
            df_sd = store.get_supply_demand(crude_name, from_dt, to_dt)
            if df_sd.empty:
                # Broader window
                broad_from = (pd.Timestamp(from_dt) - timedelta(days=180)).date()
                broad_to   = (pd.Timestamp(to_dt)   + timedelta(days=180)).date()
                df_sd = store.get_supply_demand(crude_name, broad_from, broad_to)

            if not df_sd.empty:
                supply_demand_data = []
                for _, row in df_sd.iterrows():
                    sup = _safe_float(row.get("supply_volume"))
                    dem = _safe_float(row.get("demand_volume"))
                    supply_demand_data.append({
                        "date":           row["date"].strftime("%Y-%m-%d"),
                        "crude_name":     crude_name,
                        "supply_volume":  sup,
                        "demand_volume":  dem,
                        "balance":        round(sup - dem, 2) if sup and dem else None,
                        "region":         _safe_str(row.get("region")),
                    })

        result_data: dict = {
            "product_type": product_type,
            "date_range":   {"from": from_date, "to": to_date},
            "market_trends": trend_records,
            "summary": {
                "dominant_demand_trend":  dominant_demand,
                "dominant_price_trend":   dominant_price,
                "avg_sentiment":          avg_sentiment,
                "recommendation_signal":  signal,
            },
        }
        if supply_demand_data is not None:
            result_data["supply_demand"] = supply_demand_data

        return {"status": "success", "data": result_data}

    except Exception as exc:
        logger.error("[get_market_context] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


def _recommendation_signal(
    demand_trend: str,
    price_trend: str,
    avg_sentiment: float | None,
) -> str:
    """
    Derive a simple buy/hold/caution signal from market trends.

    BUY      – demand Increasing AND price Bullish (or Neutral with positive sentiment)
    CAUTION  – demand Decreasing OR price Bearish
    HOLD     – otherwise (Stable / Neutral)
    """
    d = (demand_trend or "").lower()
    p = (price_trend  or "").lower()
    s = avg_sentiment if avg_sentiment is not None else 0.0

    if d == "increasing" and p in ("bullish", "neutral") and s >= 0:
        return "BUY"
    if d == "decreasing" or p == "bearish":
        return "CAUTION"
    return "HOLD"
