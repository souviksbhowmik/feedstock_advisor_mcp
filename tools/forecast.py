"""
tools/forecast.py
-----------------
Forecast tool for the Feedstock Advisor MCP Server.

Tools (1)
---------
1. forecast_tool  –  price / property / yield forecast for a crude in a
                     single target month.

Response envelope
-----------------
All tools return::

    {"status": "success", "data": {...}}
    {"status": "failure", "error": "<message>"}

Date matching
-------------
The data contains forecasts at fixed future dates (approx. monthly).
``forecast_tool`` finds the **nearest available record** within
``DATE_MATCH_TOLERANCE_DAYS`` (default 45) of the requested
``target_date``.  If no record is found within that window the tool
returns a failure with a helpful message listing the actual available
dates.

Data source priority
--------------------
metric="price"
    1. ``crude_price_forecasts.csv``  (refinery-specific delivered price)
       — used when ``refinery_id`` is provided
    2. ``forecasted_prices.csv``      (spot price, all refineries)

metric="properties"
    1. ``crude_properties_forecast.csv``  (refinery-specific, richer)
       — used when ``refinery_id`` is provided
    2. ``forecasted_crude_properties.csv``  (simpler, no refinery)

metric="yield"
    1. ``yield_forecasts.csv``  (requires ``refinery_id``)
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from config import DATE_MATCH_TOLERANCE_DAYS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal date-matching helper
# ---------------------------------------------------------------------------

def _nearest_row(
    df: pd.DataFrame,
    date_col: str,
    target: pd.Timestamp,
    tolerance_days: int = DATE_MATCH_TOLERANCE_DAYS,
) -> pd.Series | None:
    """
    Return the row whose ``date_col`` value is closest to ``target``,
    provided it lies within ``tolerance_days``.  Returns None otherwise.
    """
    if df.empty:
        return None
    df = df.copy()
    df["_delta"] = (df[date_col] - target).abs()
    nearest = df.loc[df["_delta"].idxmin()]
    if nearest["_delta"].days <= tolerance_days:
        return nearest
    return None


def _available_dates(df: pd.DataFrame, date_col: str) -> list[str]:
    """Return sorted list of unique date strings in a DataFrame column."""
    return sorted(df[date_col].dropna().dt.strftime("%Y-%m-%d").unique().tolist())


# ---------------------------------------------------------------------------
# Tool: forecast_tool
# ---------------------------------------------------------------------------

def forecast_tool(
    store: Any,
    crude_name: str,
    target_date: str,
    metric: str = "price",
    refinery_id: str | None = None,
) -> dict:
    """
    Forecast crude oil price, physical properties, or refinery yields for a
    single target month.

    Call this tool once per (crude_name, target_date) combination.
    For multiple months, call once per month.

    Parameters
    ----------
    store       : data provider (implements PriceProvider, PropertiesProvider,
                  YieldProvider)
    crude_name  : canonical crude name, e.g. "Brent", "WTI", "Dubai".
                  Use find_matching_crude first if the name may be a variant.
    target_date : target date in YYYY-MM-DD format.  The tool returns data
                  for the nearest available forecast date within
                  DATE_MATCH_TOLERANCE_DAYS (default 45 days).
    metric      : one of "price" | "properties" | "yield"
                  Default: "price"
    refinery_id : refinery ID, e.g. "REF_001".
                  - Required  when metric="yield"
                  - Optional  when metric="price"      (adds delivered price)
                  - Optional  when metric="properties" (adds delivered specs)

    Returns (metric="price")
    ------------------------
    ::

        {
          "status": "success",
          "data": {
            "crude_name":     "Brent",
            "target_date":    "2026-06-08",
            "metric":         "price",
            "spot_price":     82.5,
            "delivered_price": 90.2,          # null if no refinery_id
            "delivery_cost":  7.7,            # null if no refinery_id
            "confidence_interval": {
              "lower": 75.5,
              "upper": 89.5
            },
            "forecast_model":  "LSTM",
            "confidence_score": 0.89,
            "price_source":    "forecasted"   # "forecasted" | "historical"
          }
        }

    Returns (metric="properties")
    -----------------------------
    ::

        {
          "status": "success",
          "data": {
            "crude_name":    "WTI",
            "target_date":   "2026-06-08",
            "metric":        "properties",
            "refinery_id":   "REF_001",       # null if not provided
            "api_gravity":   38.8,
            "sulfur_content": 0.37,
            "viscosity":     7.3,
            "pour_point":    2.6,
            "tan":           0.3,
            "density_kg_m3": 830.7,           # null from simple table
            "confidence_api": {"lower": 37.4, "upper": 40.2},  # null from simple
            "confidence_sulfur": {"lower": 0.30, "upper": 0.44},
            "forecast_model":  "LSTM",
            "confidence_score": 0.89,
            "data_source":     "refinery_specific"  # or "generic"
          }
        }

    Returns (metric="yield")
    ------------------------
    ::

        {
          "status": "success",
          "data": {
            "crude_name":      "WTI",
            "refinery_id":     "REF_001",
            "target_date":     "2026-07-08",
            "metric":          "yield",
            "gasoline_yield":  34.6,
            "diesel_yield":    32.5,
            "jet_fuel_yield":  16.9,
            "fuel_oil_yield":  12.5,
            "lpg_yield":       3.4,
            "naphtha_yield":   3.4,
            "other_yield":     -3.3,
            "confidence_interval": {"lower": 30.1, "upper": 39.1},
            "forecast_model":  "LSTM",
            "confidence_score": 0.80
          }
        }
    """
    try:
        metric_lower = metric.strip().lower()
        if metric_lower not in ("price", "properties", "yield"):
            return {
                "status": "failure",
                "error": (
                    f"Invalid metric '{metric}'. "
                    "Must be one of: 'price', 'properties', 'yield'."
                ),
            }

        try:
            target_ts = pd.Timestamp(target_date)
        except Exception:
            return {
                "status": "failure",
                "error": (
                    f"Invalid target_date '{target_date}'. "
                    "Use YYYY-MM-DD format, e.g. '2026-06-01'."
                ),
            }

        if metric_lower == "price":
            return _forecast_price(store, crude_name, target_ts, refinery_id)
        elif metric_lower == "properties":
            return _forecast_properties(store, crude_name, target_ts, refinery_id)
        else:  # yield
            return _forecast_yield(store, crude_name, target_ts, refinery_id)

    except Exception as exc:
        logger.error("[forecast_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# metric="price"
# ---------------------------------------------------------------------------

def _forecast_price(
    store: Any,
    crude_name: str,
    target_ts: pd.Timestamp,
    refinery_id: str | None,
) -> dict:
    window = timedelta(days=DATE_MATCH_TOLERANCE_DAYS)
    from_dt = (target_ts - window).date()
    to_dt   = (target_ts + window).date()

    # ── Primary: delivered price per refinery ──────────────────────────────
    delivered_price = None
    delivery_cost   = None
    if refinery_id:
        df_del = store.get_delivered_price_forecast(crude_name, refinery_id, from_dt, to_dt)
        row_del = _nearest_row(df_del, "forecast_date", target_ts)
        if row_del is not None:
            delivered_price = _safe_float(row_del.get("total_predicted_price"))
            delivery_cost   = _safe_float(row_del.get("delivery_cost"))

    # ── Spot price (forecasted_prices.csv) ────────────────────────────────
    df_spot = store.get_forecasted_prices(crude_name, from_dt, to_dt)
    row_spot = _nearest_row(df_spot, "forecast_date", target_ts)

    if row_spot is not None:
        actual_date    = row_spot["forecast_date"].strftime("%Y-%m-%d")
        spot_price     = _safe_float(row_spot.get("predicted_price"))
        ci_lower       = _safe_float(row_spot.get("confidence_interval_lower"))
        ci_upper       = _safe_float(row_spot.get("confidence_interval_upper"))
        forecast_model = _safe_str(row_spot.get("forecast_model"))
        conf_score     = _safe_float(row_spot.get("confidence_score"))
        price_source   = "forecasted"
    else:
        # Fallback: historical prices
        hist_from = (target_ts - timedelta(days=90)).date()
        hist_to   = target_ts.date()
        df_hist = store.get_historical_prices(crude_name, hist_from, hist_to)
        if df_hist.empty:
            all_dates = _available_dates(
                store.get_all_forecasted_prices().query("crude_name == @crude_name"),
                "forecast_date",
            ) if hasattr(store, "get_all_forecasted_prices") else []
            return {
                "status": "failure",
                "error": (
                    f"No price forecast found for '{crude_name}' near "
                    f"{target_ts.date()}. "
                    + (f"Available forecast dates: {all_dates}" if all_dates else
                       "Check crude name with find_matching_crude.")
                ),
            }
        # Use latest historical row
        df_hist = df_hist.sort_values("date")
        row_hist = df_hist.iloc[-1]
        actual_date    = row_hist["date"].strftime("%Y-%m-%d")
        spot_price     = _safe_float(row_hist.get("price_usd_per_barrel"))
        ci_lower       = None
        ci_upper       = None
        forecast_model = "historical"
        conf_score     = None
        price_source   = "historical"

        # If no delivered price yet, use spot as proxy
        if delivered_price is None:
            delivered_price = spot_price

    return {
        "status": "success",
        "data": {
            "crude_name":         crude_name,
            "target_date":        actual_date,
            "metric":             "price",
            "spot_price":         spot_price,
            "delivered_price":    delivered_price,
            "delivery_cost":      delivery_cost,
            "refinery_id":        refinery_id,
            "confidence_interval": {
                "lower": ci_lower,
                "upper": ci_upper,
            },
            "forecast_model":     forecast_model,
            "confidence_score":   conf_score,
            "price_source":       price_source,
        },
    }


# ---------------------------------------------------------------------------
# metric="properties"
# ---------------------------------------------------------------------------

def _forecast_properties(
    store: Any,
    crude_name: str,
    target_ts: pd.Timestamp,
    refinery_id: str | None,
) -> dict:
    window  = timedelta(days=DATE_MATCH_TOLERANCE_DAYS)
    from_dt = (target_ts - window).date()
    to_dt   = (target_ts + window).date()

    df_props = store.get_forecasted_properties(crude_name, from_dt, to_dt)
    row = _nearest_row(df_props, "forecast_date", target_ts)

    # If refinery_id given, prefer rows that match it
    if refinery_id and row is not None and "refinery_id" in df_props.columns:
        df_ref = df_props[df_props["refinery_id"] == refinery_id]
        row_ref = _nearest_row(df_ref, "forecast_date", target_ts)
        if row_ref is not None:
            row = row_ref
            data_source = "refinery_specific"
        else:
            data_source = "generic"
    elif "refinery_id" in (df_props.columns if row is not None else []):
        data_source = "refinery_specific" if refinery_id else "generic"
    else:
        data_source = "generic"

    if row is None:
        all_dates = _available_dates(
            store.get_all_forecasted_properties().query("crude_name == @crude_name")
            if hasattr(store, "get_all_forecasted_properties") else pd.DataFrame(),
            "forecast_date",
        )
        return {
            "status": "failure",
            "error": (
                f"No property forecast found for '{crude_name}' near "
                f"{target_ts.date()}. "
                + (f"Available dates: {all_dates}" if all_dates else
                   "Check crude name with find_matching_crude.")
            ),
        }

    actual_date = row["forecast_date"].strftime("%Y-%m-%d")

    # Confidence bounds — present in crude_properties_forecast.csv but not
    # in forecasted_crude_properties.csv
    conf_api    = None
    conf_sulfur = None
    if "confidence_lower_api" in row.index:
        conf_api = {
            "lower": _safe_float(row.get("confidence_lower_api")),
            "upper": _safe_float(row.get("confidence_upper_api")),
        }
    if "confidence_lower_sulfur" in row.index:
        conf_sulfur = {
            "lower": _safe_float(row.get("confidence_lower_sulfur")),
            "upper": _safe_float(row.get("confidence_upper_sulfur")),
        }

    # confidence_score column name varies by table
    conf_score = _safe_float(
        row.get("confidence_score") if "confidence_score" in row.index
        else row.get("confidence_level")
    )

    return {
        "status": "success",
        "data": {
            "crude_name":         crude_name,
            "target_date":        actual_date,
            "metric":             "properties",
            "refinery_id":        refinery_id,
            "data_source":        data_source,
            "api_gravity":        _safe_float(row.get("api_gravity")),
            "sulfur_content":     _safe_float(row.get("sulfur_content")),
            "viscosity":          _safe_float(row.get("viscosity")),
            "pour_point":         _safe_float(row.get("pour_point")),
            "tan":                _safe_float(row.get("tan")),
            "density_kg_m3":      _safe_float(row.get("density_kg_m3")),
            "confidence_api":     conf_api,
            "confidence_sulfur":  conf_sulfur,
            "forecast_model":     _safe_str(row.get("forecast_model")),
            "confidence_score":   conf_score,
        },
    }


# ---------------------------------------------------------------------------
# metric="yield"
# ---------------------------------------------------------------------------

def _forecast_yield(
    store: Any,
    crude_name: str,
    target_ts: pd.Timestamp,
    refinery_id: str | None,
) -> dict:
    if not refinery_id:
        return {
            "status": "failure",
            "error": (
                "refinery_id is required when metric='yield'. "
                "Call list_available_refineries to get valid IDs."
            ),
        }

    window  = timedelta(days=DATE_MATCH_TOLERANCE_DAYS)
    from_dt = (target_ts - window).date()
    to_dt   = (target_ts + window).date()

    df_yield = store.get_yield_forecast(crude_name, refinery_id, from_dt, to_dt)
    row = _nearest_row(df_yield, "forecast_date", target_ts)

    if row is None:
        # Show what is actually available for this crude × refinery pair
        all_df = store.get_all_yield_forecasts()
        df_cr = all_df[
            (all_df["crude_name"]  == crude_name)
            & (all_df["refinery_id"] == refinery_id)
        ]
        available = _available_dates(df_cr, "forecast_date") if not df_cr.empty else []
        available_crudes_for_ref = (
            all_df[all_df["refinery_id"] == refinery_id]["crude_name"]
            .unique().tolist()
        )
        return {
            "status": "failure",
            "error": (
                f"No yield forecast for crude='{crude_name}', "
                f"refinery='{refinery_id}' near {target_ts.date()}. "
                + (f"Available dates for this pair: {available}. " if available else "")
                + (f"Crudes available for {refinery_id}: {available_crudes_for_ref}." if available_crudes_for_ref else "")
            ),
        }

    actual_date = row["forecast_date"].strftime("%Y-%m-%d")

    return {
        "status": "success",
        "data": {
            "crude_name":      crude_name,
            "refinery_id":     refinery_id,
            "target_date":     actual_date,
            "metric":          "yield",
            "gasoline_yield":  _safe_float(row.get("gasoline_yield")),
            "diesel_yield":    _safe_float(row.get("diesel_yield")),
            "jet_fuel_yield":  _safe_float(row.get("jet_fuel_yield")),
            "fuel_oil_yield":  _safe_float(row.get("fuel_oil_yield")),
            "lpg_yield":       _safe_float(row.get("lpg_yield")),
            "naphtha_yield":   _safe_float(row.get("naphtha_yield")),
            "other_yield":     _safe_float(row.get("other_yield")),
            "confidence_interval": {
                "lower": _safe_float(row.get("confidence_lower")),
                "upper": _safe_float(row.get("confidence_upper")),
            },
            "forecast_model":  _safe_str(row.get("forecast_model")),
            "confidence_score": _safe_float(row.get("confidence_score")),
        },
    }


# ---------------------------------------------------------------------------
# Type-safe value helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float | None:
    """Convert a value to float, returning None for NaN/None/missing."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else round(f, 4)
    except (ValueError, TypeError):
        return None


def _safe_str(val: Any) -> str | None:
    """Convert a value to str, returning None for NaN/None/missing."""
    if val is None:
        return None
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
    except TypeError:
        pass
    s = str(val).strip()
    return s if s and s.lower() != "nan" else None
