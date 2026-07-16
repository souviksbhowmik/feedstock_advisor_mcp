"""
data_access/csv_provider.py
---------------------------
Concrete implementation of all data provider ABCs backed by the bundled
CSV files in the data/ directory.

All DataFrames are loaded **once** at construction time and held in memory
for the lifetime of the server process.  Tool calls perform in-memory
pandas filtering — no file I/O per request.

This module is the ONLY place that knows about CSV file names and paths.
Swap this file (or add db_provider.py / api_provider.py) to change the
backend without touching any tool code.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from config import DATA_DIR
from data_access.base import (
    BlendProvider,
    MarketProvider,
    PriceProvider,
    PropertiesProvider,
    RefineryProvider,
    TransportProvider,
    YieldProvider,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _load(filename: str, data_dir: Path, **kwargs) -> pd.DataFrame:
    """Load a CSV file and log the outcome."""
    path = data_dir / filename
    df = pd.read_csv(path, **kwargs)
    logger.debug("Loaded %s — %d rows, %d cols", filename, len(df), len(df.columns))
    return df


def _parse_dates(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """Parse named columns to datetime in-place and return the DataFrame."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# CsvDataStore — implements all seven provider ABCs
# ---------------------------------------------------------------------------

class CsvDataStore(
    PriceProvider,
    PropertiesProvider,
    YieldProvider,
    BlendProvider,
    RefineryProvider,
    TransportProvider,
    MarketProvider,
):
    """
    Single data store backed by the 18 bundled CSV files.

    Instantiate once (in server.py) and pass to all tools via dependency
    injection.
    """

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        logger.info("CsvDataStore: loading all data files from %s", data_dir)

        # ── Price tables ────────────────────────────────────────────────────
        self._forecasted_prices = _parse_dates(
            _load("forecasted_prices.csv", data_dir),
            "forecast_date",
        )
        self._crude_price_forecasts = _parse_dates(
            _load("crude_price_forecasts.csv", data_dir),
            "forecast_date",
        )
        self._historical_prices = _parse_dates(
            _load("historical_prices.csv", data_dir),
            "date",
        )
        self._historical_prices_delivered = _parse_dates(
            _load("historical_prices_delivered.csv", data_dir),
            "observation_date",
        )

        # ── Properties tables ────────────────────────────────────────────────
        self._crude_properties = _load("crude_properties.csv", data_dir)
        self._crude_properties_forecast = _parse_dates(
            _load("crude_properties_forecast.csv", data_dir),
            "forecast_date",
        )
        self._crude_properties_delivered = _parse_dates(
            _load("crude_properties_delivered.csv", data_dir),
            "forecast_date",
        )
        self._forecasted_crude_properties = _parse_dates(
            _load("forecasted_crude_properties.csv", data_dir),
            "forecast_date",
        )

        # ── Yield tables ────────────────────────────────────────────────────
        self._historical_yields = _parse_dates(
            _load("historical_yields.csv", data_dir),
            "observation_date",
        )
        self._yield_forecasts = _parse_dates(
            _load("yield_forecasts.csv", data_dir),
            "forecast_date",
        )

        # ── Blend simulations ───────────────────────────────────────────────
        self._blend_simulations = _parse_dates(
            _load("blend_simulations.csv", data_dir),
            "simulation_date",
        )

        # ── Refinery tables ─────────────────────────────────────────────────
        self._refineries = _load("refineries.csv", data_dir)
        self._refinery_configs = _load("refinery_configs.csv", data_dir)
        self._quality_specs = _load("quality_specs.csv", data_dir)
        self._regulatory_limits = _parse_dates(
            _load("regulatory_limits.csv", data_dir),
            "forecast_date",
        )

        # ── Transport ───────────────────────────────────────────────────────
        self._transportation_costs = _parse_dates(
            _load("transportation_costs.csv", data_dir),
            "effective_date",
        )

        # ── Market ──────────────────────────────────────────────────────────
        self._market_trends = _parse_dates(
            _load("market_trends.csv", data_dir),
            "date",
        )
        self._supply_demand = _parse_dates(
            _load("supply_demand.csv", data_dir),
            "date",
        )

        logger.info("CsvDataStore: all data files loaded successfully.")

    # ── PriceProvider ────────────────────────────────────────────────────────

    def get_forecasted_prices(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        df = self._forecasted_prices
        mask = (
            (df["crude_name"] == crude_name)
            & (df["forecast_date"] >= pd.Timestamp(from_date))
            & (df["forecast_date"] <= pd.Timestamp(to_date))
        )
        return df[mask].reset_index(drop=True)

    def get_historical_prices(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        df = self._historical_prices
        mask = (
            (df["crude_name"] == crude_name)
            & (df["date"] >= pd.Timestamp(from_date))
            & (df["date"] <= pd.Timestamp(to_date))
        )
        return df[mask].reset_index(drop=True)

    def get_delivered_price_forecast(
        self,
        crude_name: str,
        refinery_id: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        df = self._crude_price_forecasts
        mask = (
            (df["crude_name"] == crude_name)
            & (df["refinery_id"] == refinery_id)
            & (df["forecast_date"] >= pd.Timestamp(from_date))
            & (df["forecast_date"] <= pd.Timestamp(to_date))
        )
        return df[mask].reset_index(drop=True)

    def get_all_forecasted_prices(self) -> pd.DataFrame:
        return self._forecasted_prices.copy()

    # ── PropertiesProvider ───────────────────────────────────────────────────

    def get_static_properties(
        self,
        crude_name: str | None = None,
    ) -> pd.DataFrame:
        df = self._crude_properties
        if crude_name is not None:
            df = df[df["crude_name"] == crude_name]
        return df.reset_index(drop=True)

    def get_forecasted_properties(
        self,
        crude_name: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        # Prefer the more detailed crude_properties_forecast table; fall back to
        # forecasted_crude_properties if the former has no matching rows.
        for source_df in (
            self._crude_properties_forecast,
            self._forecasted_crude_properties,
        ):
            date_col = "forecast_date"
            mask = (
                (source_df["crude_name"] == crude_name)
                & (source_df[date_col] >= pd.Timestamp(from_date))
                & (source_df[date_col] <= pd.Timestamp(to_date))
            )
            result = source_df[mask].reset_index(drop=True)
            if not result.empty:
                return result
        return pd.DataFrame()

    def get_all_forecasted_properties(self) -> pd.DataFrame:
        return self._crude_properties_forecast.copy()

    # ── YieldProvider ────────────────────────────────────────────────────────

    def get_yield_forecast(
        self,
        crude_name: str,
        refinery_id: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        df = self._yield_forecasts
        mask = (
            (df["crude_name"] == crude_name)
            & (df["refinery_id"] == refinery_id)
            & (df["forecast_date"] >= pd.Timestamp(from_date))
            & (df["forecast_date"] <= pd.Timestamp(to_date))
        )
        return df[mask].reset_index(drop=True)

    def get_historical_yields(
        self,
        crude_name: str,
        refinery_id: str,
    ) -> pd.DataFrame:
        df = self._historical_yields
        mask = (
            (df["crude_name"] == crude_name)
            & (df["refinery_id"] == refinery_id)
        )
        return df[mask].reset_index(drop=True)

    def get_all_yield_forecasts(self) -> pd.DataFrame:
        return self._yield_forecasts.copy()

    # ── BlendProvider ────────────────────────────────────────────────────────

    def get_blend_simulations(
        self,
        crude_names: list[str] | None = None,
    ) -> pd.DataFrame:
        df = self._blend_simulations
        if crude_names:
            # Filter to rows whose crude_mix string mentions at least one crude
            pattern = "|".join(crude_names)
            df = df[df["crude_mix"].str.contains(pattern, case=False, na=False)]
        return df.reset_index(drop=True)

    # ── RefineryProvider ─────────────────────────────────────────────────────

    def get_all_refineries(self) -> pd.DataFrame:
        return self._refineries.copy()

    def get_refinery_config(self, refinery_id: str) -> pd.DataFrame:
        df = self._refinery_configs
        return df[df["refinery_id"] == refinery_id].reset_index(drop=True)

    def get_quality_specs(
        self,
        product_type: str | None = None,
    ) -> pd.DataFrame:
        df = self._quality_specs
        if product_type is not None:
            df = df[df["product_type"].str.lower() == product_type.lower()]
        return df.reset_index(drop=True)

    def get_regulatory_limits(self) -> pd.DataFrame:
        return self._regulatory_limits.copy()

    # ── TransportProvider ────────────────────────────────────────────────────

    def get_transport_costs(
        self,
        origin: str | None = None,
        destination: str | None = None,
        transport_mode: str | None = None,
    ) -> pd.DataFrame:
        df = self._transportation_costs
        if origin is not None:
            df = df[df["origin"].str.lower() == origin.lower()]
        if destination is not None:
            df = df[df["destination"].str.lower() == destination.lower()]
        if transport_mode is not None:
            df = df[df["transport_mode"].str.lower() == transport_mode.lower()]
        return df.reset_index(drop=True)

    # ── MarketProvider ───────────────────────────────────────────────────────

    def get_market_trends(
        self,
        product_type: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        df = self._market_trends
        mask = (
            (df["product_type"].str.lower() == product_type.lower())
            & (df["date"] >= pd.Timestamp(from_date))
            & (df["date"] <= pd.Timestamp(to_date))
        )
        return df[mask].reset_index(drop=True)

    def get_supply_demand(
        self,
        crude_name: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> pd.DataFrame:
        df = self._supply_demand
        if crude_name is not None:
            df = df[df["crude_name"] == crude_name]
        if from_date is not None:
            df = df[df["date"] >= pd.Timestamp(from_date)]
        if to_date is not None:
            df = df[df["date"] <= pd.Timestamp(to_date)]
        return df.reset_index(drop=True)
