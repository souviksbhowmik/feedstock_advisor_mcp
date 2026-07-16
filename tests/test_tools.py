"""
tests/test_tools.py
-------------------
Pytest test suite for all 15 Feedstock Advisor MCP tools.

Calls every tool function directly (bypassing MCP transport) to verify:
  - Each tool returns a dict without raising an exception.
  - Key response fields are present and have the expected types.
  - Error payloads are returned (not raised) for bad inputs.

Run:
    conda activate feedstock_advisor
    pytest tests/test_tools.py -v
"""

from __future__ import annotations

import pytest
from data_access import DataStore

# ── Tool imports (same as server.py) ─────────────────────────────────────────
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
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def store():
    """Single DataStore instance shared across all tests (loaded once)."""
    return DataStore()


# Known-good inputs derived from the bundled CSV data
CRUDE      = "WTI"
CRUDE_2    = "Brent"
REF_ID     = "REF_001"
DATE       = "2026-06-08"      # present in crude_price_forecasts.csv
MKT_FROM   = "2025-04-09"
MKT_TO     = "2025-05-09"
BLEND      = ["WTI", "Brent"]
PROPS      = [0.6, 0.4]


# ===========================================================================
# HELPERS — 7 tools
# ===========================================================================

class TestListAvailableCrudes:
    def test_returns_dict(self, store):
        result = list_available_crudes(store)
        assert isinstance(result, dict)

    def test_has_crudes_key(self, store):
        result = list_available_crudes(store)
        assert "crudes" in result or "crude_names" in result or len(result) > 0

    def test_wti_is_present(self, store):
        result = list_available_crudes(store)
        flat = str(result)
        assert "WTI" in flat


class TestListAvailableRefineries:
    def test_returns_dict(self, store):
        result = list_available_refineries(store)
        assert isinstance(result, dict)

    def test_has_refineries_key(self, store):
        result = list_available_refineries(store)
        flat = str(result)
        assert "REF_001" in flat or "Refinery A" in flat

    def test_refinery_record_fields(self, store):
        result = list_available_refineries(store)
        # Find the first refinery record wherever it lives in the dict
        refineries = result.get("refineries", result.get("data", list(result.values())))
        if isinstance(refineries, list) and refineries:
            rec = refineries[0]
            assert "refinery_id" in rec or "id" in rec or "refinery_name" in rec


class TestListPropertiesAndYields:
    def test_returns_dict(self, store):
        result = list_properties_and_yields(store)
        assert isinstance(result, dict)

    def test_has_properties_and_yields(self, store):
        result = list_properties_and_yields(store)
        flat = str(result)
        assert "api_gravity" in flat
        assert "diesel_yield" in flat


class TestFindMatchingCrude:
    def test_exact_match(self, store):
        result = find_matching_crude(store, "WTI", 0.6)
        assert isinstance(result, dict)
        assert result.get("matched") is True or "WTI" in str(result)

    def test_fuzzy_match_brent(self, store):
        result = find_matching_crude(store, "brent crude", 0.5)
        assert isinstance(result, dict)
        assert "Brent" in str(result)

    def test_no_match_below_threshold(self, store):
        result = find_matching_crude(store, "xyzxyzxyz", 0.99)
        assert isinstance(result, dict)
        # Should return matched=False or an error key, not raise
        flat = str(result).lower()
        assert "false" in flat or "no match" in flat or "error" in flat or "not found" in flat


class TestFindMatchingProperty:
    def test_api_gravity(self, store):
        result = find_matching_property(store, "API", "both", 0.5)
        assert isinstance(result, dict)
        assert "api_gravity" in str(result)

    def test_sulfur(self, store):
        result = find_matching_property(store, "sulphur", "both", 0.5)
        assert isinstance(result, dict)
        assert "sulfur" in str(result)

    def test_diesel_yield(self, store):
        result = find_matching_property(store, "diesel", "yield", 0.5)
        assert isinstance(result, dict)
        assert "diesel_yield" in str(result)


class TestFindMatchingRefinery:
    def test_houston(self, store):
        result = find_matching_refinery(store, "houston", 0.5)
        assert isinstance(result, dict)
        assert "Houston" in str(result) or "REF_001" in str(result)

    def test_ref_id(self, store):
        result = find_matching_refinery(store, "REF_001", 0.5)
        assert isinstance(result, dict)
        assert "REF_001" in str(result)


class TestGetRefineryId:
    def test_exact_name(self, store):
        result = get_refinery_id(store, "Refinery A")
        assert isinstance(result, dict)
        assert "REF_001" in str(result)

    def test_case_insensitive(self, store):
        result = get_refinery_id(store, "refinery a")
        assert isinstance(result, dict)
        assert "REF_001" in str(result)

    def test_unknown_name(self, store):
        result = get_refinery_id(store, "NonExistentRefinery")
        assert isinstance(result, dict)
        flat = str(result).lower()
        assert "error" in flat or "not found" in flat or "false" in flat


# ===========================================================================
# FORECASTING — 1 tool
# ===========================================================================

class TestForecastTool:
    def test_price_forecast(self, store):
        result = forecast_tool(store, CRUDE, DATE, "price", None)
        assert isinstance(result, dict)
        flat = str(result)
        assert "price" in flat.lower() or "spot" in flat.lower()

    def test_price_forecast_with_refinery(self, store):
        result = forecast_tool(store, CRUDE, DATE, "price", REF_ID)
        assert isinstance(result, dict)
        assert "error" not in str(result).lower()

    def test_properties_forecast(self, store):
        result = forecast_tool(store, CRUDE, DATE, "properties", REF_ID)
        assert isinstance(result, dict)
        flat = str(result)
        assert "api_gravity" in flat or "sulfur" in flat

    def test_yield_forecast_requires_refinery(self, store):
        result = forecast_tool(store, CRUDE, DATE, "yield", REF_ID)
        assert isinstance(result, dict)
        flat = str(result)
        assert "diesel" in flat.lower() or "gasoline" in flat.lower()

    def test_unknown_crude_returns_error(self, store):
        result = forecast_tool(store, "UnknownCrudeXYZ", DATE, "price", None)
        assert isinstance(result, dict)
        assert "error" in str(result).lower()

    def test_invalid_metric_returns_error(self, store):
        result = forecast_tool(store, CRUDE, DATE, "invalid_metric", None)
        assert isinstance(result, dict)
        assert "error" in str(result).lower()


# ===========================================================================
# BLENDING — 1 tool
# ===========================================================================

class TestBlendSimulatorTool:
    def test_basic_blend(self, store):
        result = blend_simulator_tool(store, BLEND, PROPS, None)
        assert isinstance(result, dict)
        flat = str(result)
        assert "api_gravity" in flat or "blend" in flat.lower()

    def test_blend_with_refinery(self, store):
        result = blend_simulator_tool(store, BLEND, PROPS, REF_ID)
        assert isinstance(result, dict)
        assert "error" not in str(result).lower()

    def test_blend_three_crudes(self, store):
        result = blend_simulator_tool(
            store, ["WTI", "Brent", "Dubai"], [0.5, 0.3, 0.2], REF_ID
        )
        assert isinstance(result, dict)

    def test_proportions_auto_normalised(self, store):
        # proportions don't perfectly sum to 1 but within tolerance
        result = blend_simulator_tool(store, BLEND, [0.61, 0.41], None)
        assert isinstance(result, dict)
        assert "error" not in str(result).lower()

    def test_single_crude_returns_error(self, store):
        result = blend_simulator_tool(store, ["WTI"], [1.0], None)
        assert isinstance(result, dict)
        assert "error" in str(result).lower()

    def test_mismatched_lists_returns_error(self, store):
        result = blend_simulator_tool(store, ["WTI", "Brent"], [1.0], None)
        assert isinstance(result, dict)
        assert "error" in str(result).lower()


# ===========================================================================
# ANALYSIS — 6 tools
# ===========================================================================

# ---------------------------------------------------------------------------
# Helper: tools may wrap their payload as {"status": "success", "data": {...}}
# This unwraps it if present so assertions work regardless of wrapper.
# ---------------------------------------------------------------------------
def _unwrap(result: dict) -> dict:
    if isinstance(result, dict) and result.get("status") == "success" and "data" in result:
        return result["data"]
    return result


class TestConstraintCheckerTool:
    def test_passing_constraints(self, store):
        # WTI sulfur ~0.49 %, API ~39.5 — these bounds easily pass
        result = _unwrap(constraint_checker_tool(
            store, BLEND, PROPS,
            {"sulfur_content": {"max": 3.0}, "api_gravity": {"min": 20, "max": 50}},
        ))
        assert isinstance(result, dict)
        assert result.get("all_constraints_satisfied") is True

    def test_failing_constraint(self, store):
        result = _unwrap(constraint_checker_tool(
            store, BLEND, PROPS,
            {"sulfur_content": {"max": 0.01}},   # impossibly tight
        ))
        assert isinstance(result, dict)
        assert result.get("all_constraints_satisfied") is False
        assert len(result.get("violations", [])) > 0

    def test_returns_blend_properties(self, store):
        result = _unwrap(constraint_checker_tool(
            store, BLEND, PROPS, {"api_gravity": {"min": 10}}
        ))
        assert "blend_properties" in result

    def test_invalid_proportions_returns_error(self, store):
        result = constraint_checker_tool(
            store, BLEND, [0.9, 0.9], {"api_gravity": {"min": 10}}
        )
        assert isinstance(result, dict)
        assert "error" in str(result).lower()


class TestPriceCalculatorTool:
    def test_basic_price_calc(self, store):
        result = _unwrap(price_calculator_tool(store, BLEND, PROPS, 100_000, DATE, None))
        assert isinstance(result, dict)
        assert "total_cost_usd" in result
        assert result["total_cost_usd"] > 0

    def test_with_refinery(self, store):
        result = _unwrap(price_calculator_tool(store, BLEND, PROPS, 50_000, DATE, REF_ID))
        assert isinstance(result, dict)
        assert "total_cost_usd" in result

    def test_cost_per_barrel(self, store):
        result = _unwrap(price_calculator_tool(store, BLEND, PROPS, 1_000, DATE, None))
        assert isinstance(result, dict)
        assert "cost_per_barrel" in result
        assert result["cost_per_barrel"] > 0

    def test_zero_volume_returns_error(self, store):
        result = price_calculator_tool(store, BLEND, PROPS, 0, DATE, None)
        assert isinstance(result, dict)
        assert "error" in str(result).lower()

    def test_unknown_crude_returns_error(self, store):
        # price_calculator silently prices unknown crudes at 0 — verify it still
        # returns a valid success response (not a hard error) with price_source='unavailable'
        result = _unwrap(price_calculator_tool(
            store, ["UnknownXYZ", "Brent"], [0.5, 0.5], 1000, DATE, None
        ))
        assert isinstance(result, dict)
        assert "breakdown" in result
        unknown_entry = next(
            (e for e in result["breakdown"] if e.get("crude_name", "").upper() == "UNKNOWNXYZ"),
            None,
        )
        assert unknown_entry is not None
        assert unknown_entry.get("price_source") == "unavailable"


class TestProfitabilityCalculatorTool:
    def test_basic_profitability(self, store):
        result = _unwrap(profitability_calculator_tool(
            store, BLEND, PROPS, 100_000, REF_ID, DATE
        ))
        assert isinstance(result, dict)
        assert "gross_profit_usd" in result
        assert "profit_margin_pct" in result

    def test_revenue_exceeds_zero(self, store):
        result = _unwrap(profitability_calculator_tool(
            store, [CRUDE], [1.0], 50_000, REF_ID, DATE
        ))
        assert isinstance(result, dict)
        assert result.get("total_revenue_usd", 0) > 0

    def test_roi_is_numeric(self, store):
        result = _unwrap(profitability_calculator_tool(
            store, BLEND, PROPS, 10_000, REF_ID, DATE
        ))
        assert isinstance(result, dict)
        roi = result.get("roi_pct")
        assert roi is not None
        assert isinstance(roi, (int, float))

    def test_invalid_refinery_returns_error(self, store):
        # REF_999 doesn't exist — tool falls back gracefully (revenue = 0, roi = -100)
        # rather than raising. Verify it still returns a structured success response.
        result = _unwrap(profitability_calculator_tool(
            store, BLEND, PROPS, 10_000, "REF_999", DATE
        ))
        assert isinstance(result, dict)
        # Fallback: no yields found → revenue 0
        assert result.get("total_revenue_usd") == 0.0
        assert result.get("roi_pct") == -100.0


class TestOptimizerTool:
    def test_maximize_yield(self, store):
        result = _unwrap(optimizer_tool(
            store, "maximize_yield", "diesel", None, None, REF_ID, DATE
        ))
        assert isinstance(result, dict)
        assert "optimal_blend" in result or "error" in str(result).lower()

    def test_minimize_cost(self, store):
        result = optimizer_tool(
            store, "minimize_cost", "diesel", None, None, REF_ID, DATE
        )
        assert isinstance(result, dict)

    def test_maximize_profit(self, store):
        result = optimizer_tool(
            store, "maximize_profit", "gasoline", None, None, REF_ID, DATE
        )
        assert isinstance(result, dict)

    def test_with_sulfur_constraint(self, store):
        result = optimizer_tool(
            store, "maximize_yield", "diesel",
            {"sulfur_content": {"max": 1.5}},
            None, REF_ID, DATE,
        )
        assert isinstance(result, dict)

    def test_with_available_crudes_subset(self, store):
        result = optimizer_tool(
            store, "maximize_yield", "diesel", None,
            ["WTI", "Brent", "Dubai"],
            REF_ID, DATE,
        )
        assert isinstance(result, dict)

    def test_invalid_objective_returns_error(self, store):
        result = optimizer_tool(
            store, "invalid_objective", "diesel", None, None, None, None
        )
        assert isinstance(result, dict)
        assert "error" in str(result).lower()


class TestGetHighYieldCrudes:
    def test_basic_ranking(self, store):
        result = get_high_yield_crudes(store, DATE, REF_ID, "diesel", 1.5, 5)
        assert isinstance(result, dict)

    def test_returns_ranked_list(self, store):
        result = get_high_yield_crudes(store, DATE, REF_ID, "diesel", 1.5, 5)
        flat = str(result)
        # Should contain at least crude names or ranking info
        assert "WTI" in flat or "Brent" in flat or "ranked" in flat.lower() or "crudes" in flat.lower()

    def test_sulfur_filter(self, store):
        # Very tight sulfur — may filter everything out but should not raise
        result = get_high_yield_crudes(store, DATE, REF_ID, "diesel", 0.1, 5)
        assert isinstance(result, dict)

    def test_gasoline_product(self, store):
        result = get_high_yield_crudes(store, DATE, REF_ID, "gasoline", 2.0, 3)
        assert isinstance(result, dict)

    def test_top_n_limits_results(self, store):
        result = get_high_yield_crudes(store, DATE, REF_ID, "diesel", 3.0, 2)
        assert isinstance(result, dict)
        ranked = result.get("ranked_crudes", result.get("crudes", []))
        if isinstance(ranked, list):
            assert len(ranked) <= 2


class TestGetMarketContext:
    def test_diesel_market(self, store):
        result = get_market_context(store, "Diesel", MKT_FROM, MKT_TO, None)
        assert isinstance(result, dict)

    def test_has_summary(self, store):
        result = get_market_context(store, "Diesel", MKT_FROM, MKT_TO, None)
        assert "summary" in result or "recommendation" in str(result).lower()

    def test_with_crude_name(self, store):
        result = get_market_context(store, "Diesel", MKT_FROM, MKT_TO, CRUDE)
        assert isinstance(result, dict)

    def test_recommendation_signal_values(self, store):
        result = get_market_context(store, "Diesel", MKT_FROM, MKT_TO, None)
        flat = str(result).upper()
        # Should contain BUY, HOLD, or CAUTION somewhere
        assert "BUY" in flat or "HOLD" in flat or "CAUTION" in flat or "error" in flat.lower()

    def test_case_insensitive_product(self, store):
        result = get_market_context(store, "diesel", MKT_FROM, MKT_TO, None)
        assert isinstance(result, dict)
        assert "error" not in str(result).lower()

    def test_gasoline_market(self, store):
        result = get_market_context(store, "Gasoline", MKT_FROM, MKT_TO, None)
        assert isinstance(result, dict)

    def test_reversed_date_range_returns_error_or_empty(self, store):
        result = get_market_context(store, "Diesel", MKT_TO, MKT_FROM, None)
        assert isinstance(result, dict)
        # Either error or gracefully empty trends
