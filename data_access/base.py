"""
data_access/base.py
-------------------
Abstract base classes (ABCs) that define the data contract for the
Feedstock Advisor MCP Server.

Every concrete data backend (CSV, database, REST API) must implement
all seven provider ABCs below.  Tool modules depend only on these
abstract types — never on a concrete implementation — so swapping
backends requires zero changes in tool code.

Provider hierarchy
------------------
    PriceProvider        — spot prices, delivered prices, price forecasts
    PropertiesProvider   — crude physical/chemical properties (static + forecasted)
    YieldProvider        — refinery product yields (historical + forecasted)
    BlendProvider        — pre-computed blend simulation records
    RefineryProvider     — refinery configs, quality specs, regulatory limits
    TransportProvider    — transportation costs between origins and destinations
    MarketProvider       — market trends, supply/demand balance
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd


# ---------------------------------------------------------------------------
# PriceProvider
# ---------------------------------------------------------------------------

class PriceProvider(ABC):
    """Crude oil price data — historical and forecasted."""

    @abstractmethod
    def get_forecasted_prices(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return forecasted spot prices for a crude in a date range.

        Expected columns:
            crude_name, forecast_date, predicted_price,
            confidence_interval_lower, confidence_interval_upper,
            forecast_model, confidence_score
        """

    @abstractmethod
    def get_historical_prices(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return historical spot prices for a crude in a date range.

        Expected columns:
            crude_name, date, price_usd_per_barrel, volume_traded, currency
        """

    @abstractmethod
    def get_delivered_price_forecast(
        self,
        crude_name: str,
        refinery_id: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return forecasted delivered (spot + transport) prices for a crude at
        a specific refinery.

        Expected columns:
            forecast_date, crude_name, refinery_id, predicted_spot_price,
            delivery_cost, total_predicted_price, lower_bound, upper_bound,
            confidence_level, forecast_model
        """

    @abstractmethod
    def get_all_forecasted_prices(self) -> pd.DataFrame:
        """Return the full forecasted prices table (all crudes, all dates)."""


# ---------------------------------------------------------------------------
# PropertiesProvider
# ---------------------------------------------------------------------------

class PropertiesProvider(ABC):
    """Crude physical and chemical properties."""

    @abstractmethod
    def get_static_properties(
        self,
        crude_name: str | None = None,
    ) -> pd.DataFrame:
        """
        Return static (current/reference) crude properties.

        Expected columns:
            crude_name, api_gravity, sulfur_content, viscosity,
            pour_point, tan, region, density_kg_m3

        If crude_name is None, return all crudes.
        """

    @abstractmethod
    def get_forecasted_properties(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return forecasted crude properties for a date range.

        Expected columns:
            forecast_date, crude_name, api_gravity, sulfur_content,
            viscosity, pour_point, tan, confidence_level (or confidence_score)
        """

    @abstractmethod
    def get_all_forecasted_properties(self) -> pd.DataFrame:
        """Return the full forecasted properties table (all crudes, all dates)."""


# ---------------------------------------------------------------------------
# YieldProvider
# ---------------------------------------------------------------------------

class YieldProvider(ABC):
    """Refinery product yield data — historical and forecasted."""

    @abstractmethod
    def get_yield_forecast(
        self,
        crude_name: str,
        refinery_id: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return forecasted product yields for a crude at a refinery.

        Expected columns:
            forecast_date, crude_name, refinery_id, gasoline_yield,
            diesel_yield, jet_fuel_yield, fuel_oil_yield, lpg_yield,
            naphtha_yield, other_yield, confidence_lower, confidence_upper,
            forecast_model, confidence_score
        """

    @abstractmethod
    def get_historical_yields(
        self,
        crude_name: str,
        refinery_id: str,
    ) -> pd.DataFrame:
        """
        Return historical product yields for a crude at a refinery.

        Expected columns:
            observation_date, crude_name, refinery_id, gasoline_yield,
            diesel_yield, jet_fuel_yield, fuel_oil_yield, lpg_yield,
            naphtha_yield, other_yield, processing_volume_bpd
        """

    @abstractmethod
    def get_all_yield_forecasts(self) -> pd.DataFrame:
        """Return the full yield forecasts table (all crudes, all refineries, all dates)."""


# ---------------------------------------------------------------------------
# BlendProvider
# ---------------------------------------------------------------------------

class BlendProvider(ABC):
    """Pre-computed blend simulation records."""

    @abstractmethod
    def get_blend_simulations(
        self,
        crude_names: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        Return blend simulation records.

        Expected columns:
            simulation_id, simulation_date, crude_mix, diesel_yield,
            gasoline_yield, jet_fuel_yield, other_products_yield,
            total_cost, diesel_sulfur, gasoline_octane

        If crude_names is provided, filter to simulations that contain
        at least one of those crudes.
        """


# ---------------------------------------------------------------------------
# RefineryProvider
# ---------------------------------------------------------------------------

class RefineryProvider(ABC):
    """Refinery metadata, configurations, quality specs, and regulatory limits."""

    @abstractmethod
    def get_all_refineries(self) -> pd.DataFrame:
        """
        Return all refineries.

        Expected columns:
            refinery_id, refinery_name, location, country, capacity_bpd,
            complexity_index, configuration_type, has_hydrocracker,
            has_fcc, has_coker
        """

    @abstractmethod
    def get_refinery_config(self, refinery_id: str) -> pd.DataFrame:
        """
        Return detailed configuration for a single refinery.

        Expected columns:
            refinery_id, refinery_name, location, capacity_bpd,
            complexity_index, has_hydrocracker, has_fcc, has_coker,
            diesel_max_capacity, gasoline_max_capacity
        """

    @abstractmethod
    def get_quality_specs(
        self,
        product_type: str | None = None,
    ) -> pd.DataFrame:
        """
        Return product quality specifications.

        Expected columns:
            product_type, specification, min_value, max_value, unit

        If product_type is None, return all products.
        """

    @abstractmethod
    def get_regulatory_limits(self) -> pd.DataFrame:
        """
        Return regulatory limit records.

        Note: in the current dummy dataset this table contains price forecast
        data.  Implementations should expose whatever data is present; callers
        are responsible for interpretation.
        """


# ---------------------------------------------------------------------------
# TransportProvider
# ---------------------------------------------------------------------------

class TransportProvider(ABC):
    """Transportation cost data."""

    @abstractmethod
    def get_transport_costs(
        self,
        origin: str | None = None,
        destination: str | None = None,
        transport_mode: str | None = None,
    ) -> pd.DataFrame:
        """
        Return transportation costs.

        Expected columns:
            origin, destination, transport_mode, cost_per_barrel,
            transit_time_days, effective_date

        Any of the filter parameters may be None (returns all rows for that
        dimension).
        """


# ---------------------------------------------------------------------------
# MarketProvider
# ---------------------------------------------------------------------------

class MarketProvider(ABC):
    """Market trend and supply/demand balance data."""

    @abstractmethod
    def get_market_trends(
        self,
        product_type: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """
        Return market trend data for a product type in a date range.

        Expected columns:
            date, product_type, demand_trend, price_trend,
            market_sentiment, inventory_level
        """

    @abstractmethod
    def get_supply_demand(
        self,
        crude_name: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame:
        """
        Return supply/demand balance data.

        Expected columns:
            date, crude_name, supply_volume, demand_volume, unit, region

        All filter parameters are optional.
        """
