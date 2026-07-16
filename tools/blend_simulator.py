"""
tools/blend_simulator.py
------------------------
Blend simulation tool for the Feedstock Advisor MCP Server.

Tools (1)
---------
1. blend_simulator_tool  –  Simulate blending two or more crude oils and
                            predict blended properties + product yields.

Response envelope
-----------------
All tools return::

    {"status": "success", "data": {...}}
    {"status": "failure", "error": "<message>"}

Blend logic
-----------
Properties
~~~~~~~~~~
All crude physical properties (API gravity, sulfur content, viscosity,
pour point, TAN, density) are combined using **volume-weighted linear
averaging**::

    blended_prop = Σ (proportion_i × property_i)

This is an industry-standard approximation.  Non-linear blending effects
(e.g. viscosity blending index) are not modelled in this version.

Yields (priority order)
~~~~~~~~~~~~~~~~~~~~~~~
1. **Forecasted yields** (``yield_forecasts.csv``) — when ``refinery_id``
   is supplied AND the crude appears in the forecast table.  The nearest
   future date is used for each crude.

2. **Historical average yields** (``historical_yields.csv``) — when
   ``refinery_id`` is supplied but no forecast row exists.  Computes a
   simple mean across all historical observations.

3. **Blend-simulation lookup** (``blend_simulations.csv``) — when no
   ``refinery_id`` is supplied, or when neither forecast nor history exist.
   Finds the stored simulation whose ``crude_mix`` proportions have the
   smallest cosine distance from the requested blend, then scales yields
   by the actual proportions of matching crudes.

The ``yield_source`` key in the response indicates which path was taken:
``"forecasted"``, ``"historical_average"``, or ``"blend_simulation_lookup"``.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from config import DATE_MATCH_TOLERANCE_DAYS
from tools.forecast import _nearest_row, _safe_float, _safe_str   # reuse helpers

logger = logging.getLogger(__name__)

# Yield columns present in both historical and forecast tables
_YIELD_COLS = [
    "gasoline_yield",
    "diesel_yield",
    "jet_fuel_yield",
    "fuel_oil_yield",
    "lpg_yield",
    "naphtha_yield",
    "other_yield",
]

# Property columns available in crude_properties.csv
_PROP_COLS = [
    "api_gravity",
    "sulfur_content",
    "viscosity",
    "pour_point",
    "tan",
    "density_kg_m3",
]


# ---------------------------------------------------------------------------
# Blend mix parser (for blend_simulations.csv)
# ---------------------------------------------------------------------------

def _parse_crude_mix(mix_str: str) -> dict[str, float]:
    """
    Parse a crude_mix string like ``"Brent:0.26, Maya:0.74"``
    into ``{"Brent": 0.26, "Maya": 0.74}``.
    """
    result: dict[str, float] = {}
    for part in mix_str.split(","):
        part = part.strip()
        match = re.match(r"^(.+?)\s*:\s*([0-9.]+)$", part)
        if match:
            name  = match.group(1).strip()
            ratio = float(match.group(2))
            result[name] = ratio
    return result


def _blend_similarity(
    requested: dict[str, float],
    stored: dict[str, float],
) -> float:
    """
    Return a similarity score between two crude mixes (0 = no overlap,
    1 = identical composition).

    Uses the sum of min(proportion_i) across shared crudes — i.e. the
    total proportion that both blends have in common.
    """
    shared = set(requested) & set(stored)
    if not shared:
        return 0.0
    return sum(min(requested[c], stored[c]) for c in shared)


# ---------------------------------------------------------------------------
# Yield computation helpers
# ---------------------------------------------------------------------------

def _yields_from_forecasts(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    refinery_id: str,
) -> tuple[dict[str, float | None], str, float | None]:
    """
    Compute weighted-average yields using yield_forecasts.csv.

    Returns (yield_dict, source_label, avg_confidence_score).
    """
    window  = timedelta(days=DATE_MATCH_TOLERANCE_DAYS * 2)  # wider window for blends
    today   = date.today()
    from_dt = today
    to_dt   = (pd.Timestamp(today) + window).date()

    weighted: dict[str, float] = {col: 0.0 for col in _YIELD_COLS}
    covered_weight = 0.0
    confidence_scores: list[float] = []

    for crude, prop in zip(crude_names, proportions):
        df = store.get_yield_forecast(crude, refinery_id, from_dt, to_dt)
        # Also try a broader historical window for the nearest future date
        if df.empty:
            broad_to = (pd.Timestamp(today) + timedelta(days=365)).date()
            df = store.get_yield_forecast(crude, refinery_id, from_dt, broad_to)
        if df.empty:
            continue

        row = _nearest_row(df, "forecast_date", pd.Timestamp(today))
        if row is None:
            continue

        for col in _YIELD_COLS:
            val = _safe_float(row.get(col))
            if val is not None:
                weighted[col] += prop * val

        conf = _safe_float(row.get("confidence_score"))
        if conf is not None:
            confidence_scores.append(conf * prop)
        covered_weight += prop

    if covered_weight < 0.01:
        return {}, "forecasted", None

    # Re-normalise if not all crudes had forecast data
    if covered_weight < 0.99:
        factor = 1.0 / covered_weight
        weighted = {k: round(v * factor, 4) for k, v in weighted.items()}
    else:
        weighted = {k: round(v, 4) for k, v in weighted.items()}

    avg_conf = round(sum(confidence_scores), 4) if confidence_scores else None
    return weighted, "forecasted", avg_conf


def _yields_from_history(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    refinery_id: str,
) -> tuple[dict[str, float | None], str]:
    """
    Compute weighted-average yields using historical_yields.csv averages.

    Returns (yield_dict, source_label).
    """
    weighted: dict[str, float] = {col: 0.0 for col in _YIELD_COLS}
    covered_weight = 0.0

    for crude, prop in zip(crude_names, proportions):
        df = store.get_historical_yields(crude, refinery_id)
        if df.empty:
            continue
        for col in _YIELD_COLS:
            if col in df.columns:
                mean_val = df[col].mean()
                if not pd.isna(mean_val):
                    weighted[col] += prop * mean_val
        covered_weight += prop

    if covered_weight < 0.01:
        return {}, "historical_average"

    if covered_weight < 0.99:
        factor = 1.0 / covered_weight
        weighted = {k: round(v * factor, 4) for k, v in weighted.items()}
    else:
        weighted = {k: round(v, 4) for k, v in weighted.items()}

    return weighted, "historical_average"


def _yields_from_blend_sims(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
) -> tuple[dict[str, float | None], str, str | None]:
    """
    Find the closest stored blend simulation and return its yields.

    Returns (yield_dict, source_label, matched_sim_id).
    """
    df = store.get_blend_simulations(crude_names)
    if df.empty:
        df = store.get_blend_simulations()   # all simulations

    if df.empty:
        return {col: None for col in _YIELD_COLS}, "blend_simulation_lookup", None

    requested = dict(zip(crude_names, proportions))

    best_score = -1.0
    best_idx   = None
    for idx, row in df.iterrows():
        stored = _parse_crude_mix(str(row["crude_mix"]))
        score  = _blend_similarity(requested, stored)
        if score > best_score:
            best_score = score
            best_idx   = idx

    if best_idx is None:
        return {col: None for col in _YIELD_COLS}, "blend_simulation_lookup", None

    best_row = df.loc[best_idx]
    sim_id   = _safe_str(best_row.get("simulation_id"))

    # Map blend_simulations columns to standard yield names
    col_map = {
        "diesel_yield":   "diesel_yield",
        "gasoline_yield": "gasoline_yield",
        "jet_fuel_yield": "jet_fuel_yield",
    }
    yields: dict[str, float | None] = {}
    for std_col in _YIELD_COLS:
        # blend_simulations only has diesel, gasoline, jet_fuel
        val = _safe_float(best_row.get(std_col))
        yields[std_col] = val

    return yields, "blend_simulation_lookup", sim_id


# ---------------------------------------------------------------------------
# Properties computation
# ---------------------------------------------------------------------------

def _blend_properties(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
) -> dict[str, float | None]:
    """
    Compute volume-weighted average blend properties from static property table.
    """
    weighted: dict[str, float] = {col: 0.0 for col in _PROP_COLS}
    covered_weight = 0.0
    missing: list[str] = []

    for crude, prop in zip(crude_names, proportions):
        df = store.get_static_properties(crude)
        if df.empty:
            missing.append(crude)
            continue
        row = df.iloc[0]
        for col in _PROP_COLS:
            val = _safe_float(row.get(col))
            if val is not None:
                weighted[col] += prop * val
        covered_weight += prop

    if covered_weight < 0.01:
        return {col: None for col in _PROP_COLS}

    if covered_weight < 0.99:
        factor = 1.0 / covered_weight
        result = {k: round(v * factor, 4) for k, v in weighted.items()}
    else:
        result = {k: round(v, 4) for k, v in weighted.items()}

    if missing:
        logger.warning(
            "[blend_simulator] Properties not found for: %s — excluded from blend.",
            missing,
        )

    return result


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def blend_simulator_tool(
    store: Any,
    crude_names: list[str],
    proportions: list[float],
    refinery_id: str | None = None,
) -> dict:
    """
    Simulate blending two or more crude oils and predict the blended
    physical properties and product yield profile.

    Parameters
    ----------
    store       : data provider (implements PropertiesProvider, YieldProvider,
                  BlendProvider)
    crude_names : list of 2+ canonical crude names.
                  Use find_matching_crude to validate names first.
                  Example: ["Brent", "WTI"]
    proportions : volume fractions for each crude, must sum to 1.0 (±0.01
                  tolerance is applied automatically).
                  Example: [0.6, 0.4]
    refinery_id : refinery ID, e.g. "REF_001".
                  When provided, yields are calculated from refinery-specific
                  forecasted or historical data.  When omitted, yields are
                  estimated from the nearest stored blend simulation record.

    Returns
    -------
    ::

        {
          "status": "success",
          "data": {
            "blend_composition": [
              {"crude_name": "Brent", "proportion": 0.6},
              {"crude_name": "WTI",   "proportion": 0.4}
            ],
            "blend_properties": {
              "api_gravity":    38.86,
              "sulfur_content": 0.397,
              "viscosity":      28.02,
              "pour_point":    -10.5,
              "tan":            0.797,
              "density_kg_m3": 830.48
            },
            "product_yields": {
              "gasoline_yield":  33.1,
              "diesel_yield":    34.6,
              "jet_fuel_yield":  17.1,
              "fuel_oil_yield":   8.9,
              "lpg_yield":        6.1,
              "naphtha_yield":    3.0,
              "other_yield":     -2.8
            },
            "refinery_id":     "REF_001",
            "yield_source":    "forecasted",
            "confidence_score": 0.875,
            "notes": []
          }
        }
    """
    try:
        # ── Input validation ───────────────────────────────────────────────
        if not crude_names or len(crude_names) < 2:
            return {
                "status": "failure",
                "error": "crude_names must contain at least 2 crude names.",
            }

        if len(crude_names) != len(proportions):
            return {
                "status": "failure",
                "error": (
                    f"crude_names ({len(crude_names)}) and proportions "
                    f"({len(proportions)}) must have the same length."
                ),
            }

        if any(p < 0 for p in proportions):
            return {
                "status": "failure",
                "error": "All proportions must be non-negative.",
            }

        total = sum(proportions)
        if abs(total - 1.0) > 0.05:
            return {
                "status": "failure",
                "error": (
                    f"Proportions sum to {total:.4f} — they must sum to 1.0 "
                    "(±0.05 tolerance)."
                ),
            }

        # Auto-normalise within ±0.05 tolerance
        proportions = [p / total for p in proportions]

        # Deduplicate crude names (sum proportions for duplicates)
        dedup: dict[str, float] = {}
        for name, prop in zip(crude_names, proportions):
            dedup[name] = dedup.get(name, 0.0) + prop
        crude_names  = list(dedup.keys())
        proportions  = list(dedup.values())

        notes: list[str] = []

        # ── Properties (volume-weighted average) ──────────────────────────
        props = _blend_properties(store, crude_names, proportions)

        # Warn about crudes not in static property table
        missing_props = [
            c for c in crude_names
            if store.get_static_properties(c).empty
        ]
        if missing_props:
            notes.append(
                f"Static properties not found for: {missing_props}. "
                "They were excluded from property blending."
            )

        # ── Yields ────────────────────────────────────────────────────────
        yields: dict[str, float | None] = {}
        yield_source    = "unknown"
        conf_score      = None
        sim_id_used     = None

        if refinery_id:
            # Try forecasted yields first
            yields, yield_source, conf_score = _yields_from_forecasts(
                store, crude_names, proportions, refinery_id
            )
            # Fall back to historical average if forecasts incomplete
            if not any(v is not None for v in yields.values()):
                yields, yield_source = _yields_from_history(
                    store, crude_names, proportions, refinery_id
                )
                if not any(v is not None for v in yields.values()):
                    notes.append(
                        f"No yield data found for refinery '{refinery_id}'. "
                        "Falling back to blend simulation lookup."
                    )
                    yields, yield_source, sim_id_used = _yields_from_blend_sims(
                        store, crude_names, proportions
                    )
        else:
            yields, yield_source, sim_id_used = _yields_from_blend_sims(
                store, crude_names, proportions
            )

        if sim_id_used:
            notes.append(
                f"Yields estimated from blend simulation '{sim_id_used}' "
                "(nearest match by crude composition)."
            )

        if not any(v is not None for v in yields.values()):
            notes.append(
                "Could not compute yield estimates — insufficient data. "
                "Provide a refinery_id for better results."
            )
            yields = {col: None for col in _YIELD_COLS}

        # ── Assemble response ─────────────────────────────────────────────
        blend_composition = [
            {"crude_name": c, "proportion": round(p, 4)}
            for c, p in zip(crude_names, proportions)
        ]

        return {
            "status": "success",
            "data": {
                "blend_composition": blend_composition,
                "blend_properties":  props,
                "product_yields":    yields,
                "refinery_id":       refinery_id,
                "yield_source":      yield_source,
                "confidence_score":  conf_score,
                "notes":             notes,
            },
        }

    except Exception as exc:
        logger.error("[blend_simulator_tool] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}
