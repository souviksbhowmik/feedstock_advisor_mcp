"""
tools/helpers.py
----------------
Helper / discovery tools for the Feedstock Advisor MCP Server.

Tools (7)
---------
1.  list_available_crudes       – all crude names, grouped by region
2.  list_available_refineries   – all refineries with id, name, location
3.  list_properties_and_yields  – canonical property and yield column names
4.  find_matching_crude         – fuzzy-match a user-typed crude name
5.  find_matching_property      – fuzzy-match a property or yield name
6.  find_matching_refinery      – fuzzy-match a refinery name / location
7.  get_refinery_id             – exact (case-insensitive) name → refinery ID

All tools accept a ``store`` parameter (any object that satisfies the
relevant provider ABCs) and return a plain dict conforming to the
standard response envelope::

    {"status": "success", "data": {...}}
    {"status": "failure", "error": "<message>"}

Fuzzy matching uses ``rapidfuzz`` WRatio scorer (0–100 internally,
normalised to 0–1 in responses).  Threshold is compared against the
normalised score.
"""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz, process

from config import FUZZY_MATCH_ALTERNATIVES, FUZZY_MATCH_THRESHOLD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static catalogue — property and yield names exposed to the agent
# ---------------------------------------------------------------------------

_PROPERTIES: list[dict[str, str]] = [
    {
        "name": "api_gravity",
        "description": "API gravity in degrees (higher = lighter crude)",
        "unit": "degrees",
    },
    {
        "name": "sulfur_content",
        "description": "Sulfur content (lower = sweeter crude)",
        "unit": "% weight",
    },
    {
        "name": "viscosity",
        "description": "Kinematic viscosity at 40 °C",
        "unit": "cSt",
    },
    {
        "name": "pour_point",
        "description": "Minimum temperature at which crude flows",
        "unit": "°C",
    },
    {
        "name": "tan",
        "description": "Total acid number — corrosivity indicator",
        "unit": "mg KOH/g",
    },
    {
        "name": "density_kg_m3",
        "description": "Density at 15 °C",
        "unit": "kg/m³",
    },
]

_YIELDS: list[dict[str, str]] = [
    {"name": "gasoline_yield",  "description": "Gasoline (motor spirit) yield", "unit": "% volume"},
    {"name": "diesel_yield",    "description": "Diesel (gasoil) yield",          "unit": "% volume"},
    {"name": "jet_fuel_yield",  "description": "Jet fuel / kerosene yield",       "unit": "% volume"},
    {"name": "fuel_oil_yield",  "description": "Residual fuel oil yield",         "unit": "% volume"},
    {"name": "lpg_yield",       "description": "Liquefied petroleum gas yield",   "unit": "% volume"},
    {"name": "naphtha_yield",   "description": "Naphtha yield",                   "unit": "% volume"},
    {"name": "other_yield",     "description": "Other products yield",            "unit": "% volume"},
]

# Common user-facing aliases mapped to canonical column names
_PROPERTY_ALIASES: dict[str, str] = {
    "api":            "api_gravity",
    "gravity":        "api_gravity",
    "api gravity":    "api_gravity",
    "sulfur":         "sulfur_content",
    "sulphur":        "sulfur_content",
    "sulphur content":"sulfur_content",
    "sulfur content": "sulfur_content",
    "s&p":            "sulfur_content",
    "visc":           "viscosity",
    "pour":           "pour_point",
    "acid":           "tan",
    "total acid":     "tan",
    "total acid number": "tan",
    "density":        "density_kg_m3",
    "specific gravity": "density_kg_m3",
    "diesel":         "diesel_yield",
    "gasoil":         "diesel_yield",
    "gas oil":        "diesel_yield",
    "gasoline":       "gasoline_yield",
    "petrol":         "gasoline_yield",
    "mogas":          "gasoline_yield",
    "jet":            "jet_fuel_yield",
    "jet fuel":       "jet_fuel_yield",
    "kerosene":       "jet_fuel_yield",
    "fuel oil":       "fuel_oil_yield",
    "residual":       "fuel_oil_yield",
    "lpg":            "lpg_yield",
    "naphtha":        "naphtha_yield",
}

# Pre-built search pool for property/yield fuzzy matching
# Each entry: (display_name, canonical_name, category)
_PROPERTY_POOL: list[tuple[str, str, str]] = (
    [(p["name"], p["name"], "property") for p in _PROPERTIES]
    + [(p["description"], p["name"], "property") for p in _PROPERTIES]
    + [(y["name"], y["name"], "yield")    for y in _YIELDS]
    + [(y["description"], y["name"], "yield") for y in _YIELDS]
    + [(alias, canonical, "alias") for alias, canonical in _PROPERTY_ALIASES.items()]
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_score(raw: float) -> float:
    """Convert rapidfuzz 0-100 score to 0-1."""
    return round(raw / 100.0, 4)


def _fuzzy_extract(
    query: str,
    choices: list[str],
    threshold: float,
    n_alternatives: int,
) -> tuple[str | None, float, list[dict[str, float]]]:
    """
    Run rapidfuzz WRatio extraction.

    Returns
    -------
    best_match      – best choice string, or None if below threshold
    best_score      – normalised score for best match (0–1)
    alternatives    – up to n_alternatives other matches below the best
    """
    results = process.extract(
        query,
        choices,
        scorer=fuzz.WRatio,
        limit=n_alternatives + 1,
    )
    # results: list of (match, score, index)
    if not results:
        return None, 0.0, []

    best_match, best_raw, _ = results[0]
    best_score = _normalise_score(best_raw)

    alternatives = [
        {"name": m, "score": _normalise_score(s)}
        for m, s, _ in results[1:]
        if _normalise_score(s) < best_score  # only strictly lower
    ]

    if best_score < threshold:
        return None, best_score, alternatives

    return best_match, best_score, alternatives


# ---------------------------------------------------------------------------
# Tool 1 — list_available_crudes
# ---------------------------------------------------------------------------

def list_available_crudes(store: Any) -> dict:
    """
    Return all available crude oil names grouped by region.

    Parameters
    ----------
    store : data provider (implements PropertiesProvider)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "crudes": ["Arab Light", "Basra Light", ...],
            "count": 10,
            "by_region": {
              "Africa":       ["Brent", "Bonny Light", "Forties"],
              "Asia":         ["Arab Light", ...],
              "Middle East":  ["WTI"]
            }
          }
        }
    """
    try:
        df = store.get_static_properties()
        crudes = sorted(df["crude_name"].dropna().unique().tolist())

        by_region: dict[str, list[str]] = {}
        for _, row in df.iterrows():
            region = str(row.get("region", "Unknown"))
            name = str(row["crude_name"])
            by_region.setdefault(region, [])
            if name not in by_region[region]:
                by_region[region].append(name)
        # Sort names within each region
        by_region = {r: sorted(v) for r, v in sorted(by_region.items())}

        return {
            "status": "success",
            "data": {
                "crudes": crudes,
                "count": len(crudes),
                "by_region": by_region,
            },
        }
    except Exception as exc:
        logger.error("[list_available_crudes] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool 2 — list_available_refineries
# ---------------------------------------------------------------------------

def list_available_refineries(store: Any) -> dict:
    """
    Return all available refineries with id, name, location, country,
    capacity and complexity index.

    Parameters
    ----------
    store : data provider (implements RefineryProvider)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "refineries": [
              {
                "id": "REF_001",
                "name": "Refinery A",
                "location": "Houston",
                "country": "USA",
                "capacity_bpd": 421844,
                "complexity_index": 5.77,
                "configuration_type": "Simple",
                "has_hydrocracker": false,
                "has_fcc": true,
                "has_coker": false
              },
              ...
            ],
            "count": 10
          }
        }
    """
    try:
        df = store.get_all_refineries()
        refineries = []
        for _, row in df.iterrows():
            refineries.append({
                "id":                 str(row["refinery_id"]),
                "name":               str(row["refinery_name"]),
                "location":           str(row.get("location", "")),
                "country":            str(row.get("country", "")),
                "capacity_bpd":       int(row.get("capacity_bpd", 0)),
                "complexity_index":   float(row.get("complexity_index", 0.0)),
                "configuration_type": str(row.get("configuration_type", "")),
                "has_hydrocracker":   bool(str(row.get("has_hydrocracker", "False")).lower() == "true"),
                "has_fcc":            bool(str(row.get("has_fcc", "False")).lower() == "true"),
                "has_coker":          bool(str(row.get("has_coker", "False")).lower() == "true"),
            })
        return {
            "status": "success",
            "data": {"refineries": refineries, "count": len(refineries)},
        }
    except Exception as exc:
        logger.error("[list_available_refineries] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool 3 — list_properties_and_yields
# ---------------------------------------------------------------------------

def list_properties_and_yields(_store: Any = None) -> dict:
    """
    Return canonical property and yield names with descriptions and units.

    Parameters
    ----------
    _store : unused (included for API consistency)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "properties": [
              {"name": "api_gravity", "description": "...", "unit": "degrees"},
              ...
            ],
            "yields": [
              {"name": "diesel_yield", "description": "...", "unit": "% volume"},
              ...
            ]
          }
        }
    """
    return {
        "status": "success",
        "data": {
            "properties": _PROPERTIES,
            "yields":     _YIELDS,
        },
    }


# ---------------------------------------------------------------------------
# Tool 4 — find_matching_crude
# ---------------------------------------------------------------------------

def find_matching_crude(
    store: Any,
    crude_name: str,
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> dict:
    """
    Fuzzy-match a user-supplied crude name against the canonical list.

    Parameters
    ----------
    store      : data provider (implements PropertiesProvider)
    crude_name : raw string from user query (may contain typos/variants)
    threshold  : minimum similarity score 0–1 to accept a match (default 0.6)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "extracted_name":  "brent crude",
            "matched_name":    "Brent",
            "similarity_score": 0.95,
            "alternatives": [
              {"name": "Bonny Light", "score": 0.45}
            ]
          }
        }

    Returns status "failure" when no match is found above the threshold.
    """
    try:
        df = store.get_static_properties()
        choices: list[str] = df["crude_name"].dropna().unique().tolist()

        # Check alias map first (exact / lower-cased)
        lower = crude_name.strip().lower()
        # Direct match in canonical list (case-insensitive)
        for c in choices:
            if c.lower() == lower:
                return {
                    "status": "success",
                    "data": {
                        "extracted_name":   crude_name,
                        "matched_name":     c,
                        "similarity_score": 1.0,
                        "alternatives":     [],
                    },
                }

        best, score, alternatives = _fuzzy_extract(
            crude_name, choices, threshold, FUZZY_MATCH_ALTERNATIVES
        )

        if best is None:
            return {
                "status": "failure",
                "error": (
                    f"No crude matching '{crude_name}' found above threshold "
                    f"{threshold}. Best score was {score:.2f}. "
                    f"Call list_available_crudes to see valid names."
                ),
            }

        return {
            "status": "success",
            "data": {
                "extracted_name":   crude_name,
                "matched_name":     best,
                "similarity_score": score,
                "alternatives":     alternatives,
            },
        }
    except Exception as exc:
        logger.error("[find_matching_crude] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool 5 — find_matching_property
# ---------------------------------------------------------------------------

def find_matching_property(
    _store: Any,
    property_name: str,
    category: str = "both",
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> dict:
    """
    Fuzzy-match a user-supplied property or yield name to a canonical name.

    Parameters
    ----------
    _store        : unused (included for API consistency)
    property_name : raw string from user query
                    Examples: "API", "sulphur", "diesel yield", "gasoline"
    category      : restrict search to "property", "yield", or "both" (default)
    threshold     : minimum similarity score 0–1 (default 0.6)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "extracted_name":   "API",
            "matched_name":     "api_gravity",
            "category":         "property",
            "description":      "API gravity in degrees",
            "unit":             "degrees",
            "similarity_score": 0.88,
            "alternatives": [
              {"name": "density_kg_m3", "category": "property", "score": 0.35}
            ]
          }
        }
    """
    try:
        lower = property_name.strip().lower()

        # Exact alias look-up first
        if lower in _PROPERTY_ALIASES:
            canonical = _PROPERTY_ALIASES[lower]
            meta = _resolve_property_meta(canonical)
            return {
                "status": "success",
                "data": {
                    "extracted_name":   property_name,
                    "matched_name":     canonical,
                    "category":         meta["category"],
                    "description":      meta["description"],
                    "unit":             meta["unit"],
                    "similarity_score": 1.0,
                    "alternatives":     [],
                },
            }

        # Build filtered search pool
        cat_lower = category.lower()
        if cat_lower == "property":
            pool = [(display, canon, cat) for display, canon, cat in _PROPERTY_POOL
                    if cat in ("property",)]
        elif cat_lower == "yield":
            pool = [(display, canon, cat) for display, canon, cat in _PROPERTY_POOL
                    if cat in ("yield",)]
        else:  # "both" or anything else
            pool = _PROPERTY_POOL

        choices = [display for display, _, _ in pool]
        best_display, score, alts_display = _fuzzy_extract(
            property_name, choices, threshold, FUZZY_MATCH_ALTERNATIVES
        )

        if best_display is None:
            return {
                "status": "failure",
                "error": (
                    f"No property/yield matching '{property_name}' found above "
                    f"threshold {threshold}. Call list_properties_and_yields "
                    f"to see valid names."
                ),
            }

        # Resolve canonical name and metadata for the best match
        canonical = pool[choices.index(best_display)][1]
        meta = _resolve_property_meta(canonical)

        # Resolve alternatives
        alternatives = []
        for alt in alts_display:
            try:
                alt_canon = pool[choices.index(alt["name"])][1]
                alt_meta = _resolve_property_meta(alt_canon)
                alternatives.append({
                    "name":     alt_canon,
                    "category": alt_meta["category"],
                    "score":    alt["score"],
                })
            except (ValueError, KeyError):
                pass

        return {
            "status": "success",
            "data": {
                "extracted_name":   property_name,
                "matched_name":     canonical,
                "category":         meta["category"],
                "description":      meta["description"],
                "unit":             meta["unit"],
                "similarity_score": score,
                "alternatives":     alternatives,
            },
        }
    except Exception as exc:
        logger.error("[find_matching_property] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


def _resolve_property_meta(canonical: str) -> dict[str, str]:
    """Return description, unit, and category for a canonical property name."""
    for p in _PROPERTIES:
        if p["name"] == canonical:
            return {"category": "property", "description": p["description"], "unit": p["unit"]}
    for y in _YIELDS:
        if y["name"] == canonical:
            return {"category": "yield", "description": y["description"], "unit": y["unit"]}
    return {"category": "unknown", "description": "", "unit": ""}


# ---------------------------------------------------------------------------
# Tool 6 — find_matching_refinery
# ---------------------------------------------------------------------------

def find_matching_refinery(
    store: Any,
    refinery_name: str,
    threshold: float = FUZZY_MATCH_THRESHOLD,
) -> dict:
    """
    Fuzzy-match a user-supplied refinery name or location to a canonical record.

    Matches against refinery_id, refinery_name, location, and country columns.

    Parameters
    ----------
    store          : data provider (implements RefineryProvider)
    refinery_name  : raw string from user query
                     Examples: "east coast", "REF001", "houston refinery"
    threshold      : minimum similarity score 0–1 (default 0.6)

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "extracted_name": "houston",
            "matched_refinery": {
              "id":       "REF_001",
              "name":     "Refinery A",
              "location": "Houston",
              "country":  "USA"
            },
            "similarity_score": 0.92,
            "alternatives": [
              {"id": "REF_008", "name": "Refinery H", "score": 0.55}
            ]
          }
        }
    """
    try:
        df = store.get_all_refineries()

        # Build a flat search pool: for each refinery row add multiple searchable strings
        # Format: (search_string, refinery_id)
        pool: list[tuple[str, str]] = []
        for _, row in df.iterrows():
            rid = str(row["refinery_id"])
            pool.append((str(row["refinery_id"]).lower(), rid))
            pool.append((str(row["refinery_name"]).lower(), rid))
            pool.append((str(row.get("location", "")).lower(), rid))
            pool.append((str(row.get("country", "")).lower(), rid))
            # Combined "name location" string
            pool.append((
                f"{row['refinery_name']} {row.get('location', '')}".lower(),
                rid,
            ))

        choices = [s for s, _ in pool]
        query_lower = refinery_name.strip().lower()

        # Exact match on refinery_id first (e.g. "REF_001", "ref001")
        normalised_query = query_lower.replace("_", "").replace(" ", "")
        for _, row in df.iterrows():
            rid = str(row["refinery_id"])
            if rid.lower().replace("_", "") == normalised_query:
                return {
                    "status": "success",
                    "data": {
                        "extracted_name": refinery_name,
                        "matched_refinery": {
                            "id":       rid,
                            "name":     str(row["refinery_name"]),
                            "location": str(row.get("location", "")),
                            "country":  str(row.get("country", "")),
                        },
                        "similarity_score": 1.0,
                        "alternatives": [],
                    },
                }

        best_choice, score, alt_choices = _fuzzy_extract(
            query_lower, choices, threshold, FUZZY_MATCH_ALTERNATIVES
        )

        if best_choice is None:
            return {
                "status": "failure",
                "error": (
                    f"No refinery matching '{refinery_name}' found above threshold "
                    f"{threshold}. Best score was {score:.2f}. "
                    f"Call list_available_refineries to see valid names."
                ),
            }

        best_rid = pool[choices.index(best_choice)][1]
        best_row = df[df["refinery_id"] == best_rid].iloc[0]

        alternatives = []
        seen_rids: set[str] = {best_rid}
        for alt in alt_choices:
            try:
                alt_rid = pool[choices.index(alt["name"])][1]
                if alt_rid in seen_rids:
                    continue
                seen_rids.add(alt_rid)
                alt_row = df[df["refinery_id"] == alt_rid].iloc[0]
                alternatives.append({
                    "id":    alt_rid,
                    "name":  str(alt_row["refinery_name"]),
                    "score": alt["score"],
                })
            except (ValueError, IndexError, KeyError):
                pass

        return {
            "status": "success",
            "data": {
                "extracted_name": refinery_name,
                "matched_refinery": {
                    "id":       best_rid,
                    "name":     str(best_row["refinery_name"]),
                    "location": str(best_row.get("location", "")),
                    "country":  str(best_row.get("country", "")),
                },
                "similarity_score": score,
                "alternatives":     alternatives,
            },
        }
    except Exception as exc:
        logger.error("[find_matching_refinery] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}


# ---------------------------------------------------------------------------
# Tool 7 — get_refinery_id
# ---------------------------------------------------------------------------

def get_refinery_id(store: Any, refinery_name: str) -> dict:
    """
    Get the refinery ID for a given refinery name using an exact
    case-insensitive match.

    Use ``find_matching_refinery`` instead when the name might contain
    typos or be only a partial match.

    Parameters
    ----------
    store          : data provider (implements RefineryProvider)
    refinery_name  : exact refinery name (case-insensitive)
                     Example: "Refinery A", "refinery a"

    Returns
    -------
    dict with status/data envelope::

        {
          "status": "success",
          "data": {
            "refinery_name": "Refinery A",
            "refinery_id":   "REF_001",
            "location":      "Houston",
            "country":       "USA"
          }
        }
    """
    try:
        df = store.get_all_refineries()
        lower_query = refinery_name.strip().lower()

        match = df[df["refinery_name"].str.lower() == lower_query]
        if match.empty:
            # Suggest using find_matching_refinery
            available = df["refinery_name"].tolist()
            return {
                "status": "failure",
                "error": (
                    f"No exact match for refinery name '{refinery_name}'. "
                    f"Available names: {available}. "
                    f"Use find_matching_refinery for fuzzy matching."
                ),
            }

        row = match.iloc[0]
        return {
            "status": "success",
            "data": {
                "refinery_name": str(row["refinery_name"]),
                "refinery_id":   str(row["refinery_id"]),
                "location":      str(row.get("location", "")),
                "country":       str(row.get("country", "")),
            },
        }
    except Exception as exc:
        logger.error("[get_refinery_id] %s", exc, exc_info=True)
        return {"status": "failure", "error": str(exc)}
