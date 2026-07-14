# Feedstock Advisor MCP Server — Plan & Requirements Document

**Version:** 1.0  
**Date:** 2026-04-14  
**Branch:** feature/init  
**Status:** Approved for Implementation  

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [System Architecture](#3-system-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [Data Sources](#6-data-sources)
7. [Data Access Layer](#7-data-access-layer)
8. [Tool Specifications](#8-tool-specifications)
   - 8.1 [Forecasting Tools](#81-forecasting-tools)
   - 8.2 [Helper Tools](#82-helper-tools)
   - 8.3 [Blending Tools](#83-blending-tools)
   - 8.4 [Analysis Tools](#84-analysis-tools)
   - 8.5 [Additional Tools](#85-additional-tools)
9. [Error Handling Standard](#9-error-handling-standard)
10. [Environment Setup](#10-environment-setup)
11. [Build Phases & Milestones](#11-build-phases--milestones)
12. [Future Extension Points](#12-future-extension-points)
13. [Constraints & Assumptions](#13-constraints--assumptions)

---

## 1. Project Overview

The **Feedstock Advisor MCP Server** is a Python-based Model Context Protocol (MCP) server that
exposes domain-specific tools for a Gen-AI feedstock consulting agent operating in the
petrochemical trading industry.

The agent (to be built separately) will call these tools to answer consultants' questions such as:

- *"Which crude is most profitable in the next three months?"*
- *"Which crude will give the best blending result?"*
- *"Should I buy Brent crude in June 2026?"*
- *"Which crudes give the highest diesel yield under 1.5% sulfur in future months?"*
- *"What is the optimal crude blend for August 2026 to maximise diesel yield?"*

The MCP server provides **15 tools** across four categories — Forecasting, Helpers,
Blending, and Analysis — identical in interface and behaviour to the LangGraph/LangChain
tool set defined in `TOOLS_REFERENCE.md` and `NEW_HELPER_TOOLS_SPEC.md`, with two
additional tools to cover query patterns not addressed by those specs.

---

## 2. Goals & Non-Goals

### Goals

| # | Goal |
|---|------|
| G1 | Implement all 13 tools defined in `TOOLS_REFERENCE.md` and `NEW_HELPER_TOOLS_SPEC.md` with identical names, parameters, and return shapes |
| G2 | Add 2 supplementary tools (`get_high_yield_crudes`, `get_market_context`) that address query patterns not covered by the 13 spec tools |
| G3 | Bundle all dummy CSV data inside the server package so no external setup is needed to run it |
| G4 | Design the data access layer so every data source can be swapped to a live database or REST API with zero changes to tool logic |
| G5 | Manage the Python environment using a Conda `environment.yml` file |
| G6 | Run as an MCP stdio server, registerable in `mcp.json` for use by Bob or any MCP-compatible agent |

### Non-Goals

| # | Non-Goal |
|---|----------|
| NG1 | Building the AI agent itself — the agent is a separate project |
| NG2 | Real-time market data feeds or live API integrations in this phase |
| NG3 | Authentication / authorisation (no multi-user isolation required) |
| NG4 | A web UI or REST API layer |
| NG5 | Persistent user sessions or conversation history |

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────┐
│                  AI Agent Layer                  │
│  (LangGraph / Claude / GPT — calls MCP tools)   │
└──────────────────────┬───────────────────────────┘
                       │  JSON-RPC over stdio
┌──────────────────────▼───────────────────────────┐
│               MCP Server  (server.py)            │
│  FastMCP · stdio transport · auto JSON Schema    │
│  from Python type hints · Pydantic validation    │
└──┬───────────────┬──────────────┬────────────────┘
   │               │              │
┌──▼────┐  ┌──────▼─────┐  ┌────▼──────────────────┐
│tools/ │  │tools/      │  │tools/                 │
│fore-  │  │helpers.py  │  │blend_simulator.py     │
│cast.py│  │(7 tools)   │  │analysis.py (6 tools)  │
└──┬────┘  └──────┬─────┘  └────┬──────────────────┘
   └──────────────┴──────────────┘
                  │  Dependency Injection
┌─────────────────▼────────────────────────────────┐
│          Data Access Layer                       │
│  data_access/base.py   ← Abstract providers      │
│  data_access/csv_provider.py  ← CsvDataStore     │
│  (future: db_provider.py / api_provider.py)      │
└─────────────────┬────────────────────────────────┘
                  │  pandas read_csv (once at startup)
┌─────────────────▼────────────────────────────────┐
│              data/  (18 CSV files)               │
└──────────────────────────────────────────────────┘
```

### Key Architectural Principles

1. **Separation of concerns** — Tool logic, data access, and server registration are in separate
   modules. Changing one does not require touching the others.

2. **Singleton DataStore** — All 18 CSV files are loaded into pandas DataFrames exactly once
   when the server starts. Tools receive the DataStore via constructor injection; no file I/O
   occurs per tool call.

3. **Swappable data backend** — A `DATA_BACKEND` environment variable selects between
   `csv` (default), `db`, or `api` backends. The abstract base classes in
   `data_access/base.py` define the contract; only the implementation changes.

4. **Consistent response envelope** — Every tool returns a Python `dict` with at minimum:
   `{"status": "success"|"failure", "data": {...}}` or `{"status": "failure", "error": "..."}`.

---

## 4. Technology Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| Language | Python | 3.11 | Stable LTS; matches conda-forge availability |
| MCP SDK | `mcp[cli]` FastMCP | ≥ 1.6 | Official Python MCP SDK; decorator API mirrors LangChain `@tool` pattern |
| Transport | stdio | — | Local agent deployment; no network overhead |
| Data manipulation | `pandas` | 2.2 | De-facto standard for tabular CSV work |
| Numerical / LP solver | `numpy` + `scipy` | 1.26 / 1.13 | `scipy.optimize.linprog` for `optimizer_tool` |
| Fuzzy matching | `rapidfuzz` | ≥ 3.9 | 10–100× faster than `difflib`; handles abbreviations, partial names, case variants |
| Input validation | `pydantic` | ≥ 2.7 | FastMCP generates JSON Schema automatically from Pydantic models |
| Environment manager | Conda / Miniconda | — | `environment.yml` ensures fully reproducible env |

---

## 5. Project Structure

```
feedstock_advisor_mcp/
│
├── environment.yml              # Conda environment definition
├── README.md                    # Setup and usage guide
├── PLAN_AND_REQUIREMENTS.md     # This document
├── TOOLS_REFERENCE.md           # LangGraph tool spec (reference)
├── NEW_HELPER_TOOLS_SPEC.md     # Helper tool spec (reference)
│
├── server.py                    # MCP server entry-point
│                                #   - Instantiates CsvDataStore
│                                #   - Creates FastMCP instance
│                                #   - Registers all 15 tools
│                                #   - Calls mcp.run(transport="stdio")
│
├── config.py                    # Central config
│                                #   - DATA_DIR path resolution
│                                #   - DATA_BACKEND env-var ("csv"|"db"|"api")
│                                #   - Product price constants (for profitability calc)
│
├── data/                        # Bundled dummy CSV files (18 files — read-only)
│   ├── blend_simulations.csv
│   ├── crude_price_forecasts.csv
│   ├── crude_properties.csv
│   ├── crude_properties_delivered.csv
│   ├── crude_properties_forecast.csv
│   ├── forecasted_crude_properties.csv
│   ├── forecasted_prices.csv
│   ├── historical_prices.csv
│   ├── historical_prices_delivered.csv
│   ├── historical_yields.csv
│   ├── market_trends.csv
│   ├── quality_specs.csv
│   ├── refineries.csv
│   ├── refinery_configs.csv
│   ├── regulatory_limits.csv
│   ├── supply_demand.csv
│   ├── transportation_costs.csv
│   └── yield_forecasts.csv
│
├── data_access/
│   ├── __init__.py
│   ├── base.py                  # Abstract base classes for all data providers
│   └── csv_provider.py          # CsvDataStore — pandas implementations of all ABCs
│
└── tools/
    ├── __init__.py
    ├── forecast.py              # Tool: forecast_tool
    ├── helpers.py               # Tools: list_available_crudes, list_available_refineries,
    │                            #         list_properties_and_yields, find_matching_crude,
    │                            #         find_matching_property, find_matching_refinery,
    │                            #         get_refinery_id
    ├── blend_simulator.py       # Tool: blend_simulator_tool
    └── analysis.py              # Tools: optimizer_tool, constraint_checker_tool,
                                 #         price_calculator_tool, profitability_calculator_tool,
                                 #         get_high_yield_crudes, get_market_context
```

---

## 6. Data Sources

All 18 CSV files are bundled in `data/`. The table below documents each file's schema,
content, and which tools consume it.

| File | Key Columns | Used By Tool(s) |
|------|-------------|-----------------|
| `crude_properties.csv` | crude_name, api_gravity, sulfur_content, viscosity, pour_point, tan, region, density_kg_m3 | blend_simulator_tool, constraint_checker_tool, find_matching_crude, list_available_crudes |
| `crude_properties_forecast.csv` | forecast_date, crude_name, refinery_id, api_gravity, sulfur_content, viscosity, pour_point, tan, density_kg_m3, confidence_score | forecast_tool (metric=properties), constraint_checker_tool, get_high_yield_crudes |
| `crude_properties_delivered.csv` | observation_date, crude_name, refinery_id, api_gravity, sulfur_content, contamination_factor, confidence_score | constraint_checker_tool |
| `forecasted_crude_properties.csv` | crude_name, forecast_date, api_gravity, sulfur_content, viscosity, pour_point, tan, confidence_level | forecast_tool (metric=properties), get_high_yield_crudes |
| `forecasted_prices.csv` | crude_name, forecast_date, predicted_price, confidence_interval_lower, confidence_interval_upper, forecast_model, confidence_score | forecast_tool (metric=price), price_calculator_tool, get_high_yield_crudes |
| `crude_price_forecasts.csv` | forecast_date, crude_name, refinery_id, predicted_spot_price, delivery_cost, total_predicted_price, lower_bound, upper_bound, confidence_level, forecast_model | price_calculator_tool, profitability_calculator_tool, optimizer_tool |
| `historical_prices.csv` | crude_name, date, price_usd_per_barrel, volume_traded, currency | price_calculator_tool (fallback), get_market_context |
| `historical_prices_delivered.csv` | observation_date, crude_name, refinery_id, spot_price, delivery_cost, total_delivered_price, volume_delivered_bpd | price_calculator_tool (historical baseline) |
| `historical_yields.csv` | observation_date, crude_name, refinery_id, gasoline_yield, diesel_yield, jet_fuel_yield, fuel_oil_yield, lpg_yield, naphtha_yield | blend_simulator_tool (historical basis) |
| `yield_forecasts.csv` | forecast_date, crude_name, refinery_id, gasoline_yield, diesel_yield, jet_fuel_yield, fuel_oil_yield, lpg_yield, naphtha_yield, confidence_lower, confidence_upper | forecast_tool (metric=yield), blend_simulator_tool, optimizer_tool, profitability_calculator_tool, get_high_yield_crudes |
| `blend_simulations.csv` | simulation_id, simulation_date, crude_mix, diesel_yield, gasoline_yield, jet_fuel_yield, total_cost, diesel_sulfur, gasoline_octane | blend_simulator_tool (nearest-match lookup), optimizer_tool |
| `quality_specs.csv` | product_type, specification, min_value, max_value, unit | constraint_checker_tool, get_high_yield_crudes |
| `regulatory_limits.csv` | forecast_date, crude_name, refinery_id, predicted_spot_price, delivery_cost, total_predicted_price, confidence_level | constraint_checker_tool (price-based regulatory signals) |
| `refineries.csv` | refinery_id, refinery_name, location, country, capacity_bpd, complexity_index, has_hydrocracker, has_fcc, has_coker | list_available_refineries, find_matching_refinery, get_refinery_id |
| `refinery_configs.csv` | refinery_id, refinery_name, location, capacity_bpd, complexity_index, has_hydrocracker, has_fcc, has_coker, diesel_max_capacity, gasoline_max_capacity | optimizer_tool, profitability_calculator_tool, constraint_checker_tool |
| `transportation_costs.csv` | origin, destination, transport_mode, cost_per_barrel, transit_time_days, effective_date | price_calculator_tool, profitability_calculator_tool |
| `market_trends.csv` | date, product_type, demand_trend, price_trend, market_sentiment, inventory_level | get_market_context |
| `supply_demand.csv` | date, crude_name, supply_volume, demand_volume, unit, region | get_market_context |

---

## 7. Data Access Layer

### 7.1 Abstract Base Classes (`data_access/base.py`)

Seven abstract provider classes define the data contract. Each method is typed and
returns a `pandas.DataFrame`.

```python
class PriceProvider(ABC):
    def get_forecasted_prices(self, crude_name: str, from_date: date, to_date: date) -> pd.DataFrame: ...
    def get_historical_prices(self, crude_name: str, from_date: date, to_date: date) -> pd.DataFrame: ...
    def get_delivered_price_forecast(self, crude_name: str, refinery_id: str, target_date: date) -> pd.DataFrame: ...

class PropertiesProvider(ABC):
    def get_static_properties(self, crude_name: str | None = None) -> pd.DataFrame: ...
    def get_forecasted_properties(self, crude_name: str, target_date: date) -> pd.DataFrame: ...

class YieldProvider(ABC):
    def get_yield_forecast(self, crude_name: str, refinery_id: str, target_date: date) -> pd.DataFrame: ...
    def get_historical_yields(self, crude_name: str, refinery_id: str) -> pd.DataFrame: ...

class BlendProvider(ABC):
    def get_blend_simulations(self, crude_names: list[str] | None = None) -> pd.DataFrame: ...

class RefineryProvider(ABC):
    def get_all_refineries(self) -> pd.DataFrame: ...
    def get_refinery_config(self, refinery_id: str) -> pd.DataFrame: ...
    def get_quality_specs(self, product_type: str | None = None) -> pd.DataFrame: ...

class TransportProvider(ABC):
    def get_transport_costs(self, origin: str, destination: str) -> pd.DataFrame: ...

class MarketProvider(ABC):
    def get_market_trends(self, product_type: str, from_date: date, to_date: date) -> pd.DataFrame: ...
    def get_supply_demand(self, crude_name: str, from_date: date, to_date: date) -> pd.DataFrame: ...
```

### 7.2 CSV Implementation (`data_access/csv_provider.py`)

`CsvDataStore` implements all seven ABCs. All DataFrames are loaded at construction time.
Date columns are parsed to `datetime` and indexed for fast range lookups.

```python
class CsvDataStore(PriceProvider, PropertiesProvider, YieldProvider,
                   BlendProvider, RefineryProvider, TransportProvider, MarketProvider):
    def __init__(self, data_dir: Path = DATA_DIR):
        # Load all 18 CSVs once
        self._forecasted_prices = pd.read_csv(data_dir / "forecasted_prices.csv", parse_dates=["forecast_date"])
        # ... remaining 17 files
```

### 7.3 Future Backend Swap

Set env-var `DATA_BACKEND=db` and `server.py` will import `DbDataStore` instead of
`CsvDataStore`. Tool modules never import from `csv_provider` directly; they only depend
on the abstract types in `base.py`.

---

## 8. Tool Specifications

All tools follow this response envelope:

```json
// Success
{ "status": "success", "data": { ... } }

// Failure
{ "status": "failure", "error": "<human-readable message>" }
```

---

### 8.1 Forecasting Tools

#### `forecast_tool`

**Category:** Forecasting  
**File:** `tools/forecast.py`  
**Description:** Forecast crude oil price, physical properties, or refinery yields for a
single target month. For multiple months call once per month.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `crude_name` | `str` | Yes | — | Canonical crude name (use `find_matching_crude` if uncertain) |
| `target_date` | `str` | Yes | — | Target date `YYYY-MM-DD`; month is derived from this date |
| `metric` | `str` | No | `"price"` | One of `"price"`, `"properties"`, `"yield"` |
| `refinery_id` | `str` | No | `None` | Required when `metric="yield"` |

**Returns (metric=price):**
```json
{
  "status": "success",
  "data": {
    "crude_name": "Brent",
    "target_date": "2026-06-01",
    "spot_price": 82.5,
    "delivered_price": 90.2,
    "confidence_interval": { "lower": 75.5, "upper": 89.5 },
    "forecast_model": "LSTM",
    "confidence_score": 0.89
  }
}
```

**Returns (metric=properties):**
```json
{
  "status": "success",
  "data": {
    "crude_name": "Brent",
    "target_date": "2026-06-01",
    "api_gravity": 38.8,
    "sulfur_content": 0.37,
    "viscosity": 20.1,
    "pour_point": -22.9,
    "tan": 1.3,
    "confidence_score": 0.89
  }
}
```

**Returns (metric=yield):**
```json
{
  "status": "success",
  "data": {
    "crude_name": "WTI",
    "refinery_id": "REF_001",
    "target_date": "2026-07-01",
    "diesel_yield": 34.2,
    "gasoline_yield": 33.6,
    "jet_fuel_yield": 17.3,
    "fuel_oil_yield": 8.7,
    "lpg_yield": 6.4,
    "naphtha_yield": 2.7,
    "confidence_lower": 32.1,
    "confidence_upper": 35.1,
    "forecast_model": "LSTM",
    "confidence_score": 0.9
  }
}
```

**Logic:**
- Find the closest available forecast date to `target_date` (within ±45 days) in the
  relevant CSV.
- If `metric="yield"` and `refinery_id` is absent, return `status: failure`.
- If no data found within the date window, return `status: failure` with a message.

---

### 8.2 Helper Tools

#### `list_available_crudes`

**File:** `tools/helpers.py`  
**Parameters:** None  
**Returns:**
```json
{
  "status": "success",
  "data": {
    "crudes": ["Arab Light", "Basra Light", "Bonny Light", "Brent", "Dubai",
               "Forties", "Maya", "Oman", "Urals", "WTI"],
    "count": 10,
    "by_region": {
      "Africa": ["Brent", "Bonny Light", "Forties"],
      "Asia":   ["Arab Light", "Basra Light", "Dubai", "Maya", "Oman", "Urals"],
      "Middle East": ["WTI"]
    }
  }
}
```
**Logic:** Unique `crude_name` values from `crude_properties.csv`, sorted alphabetically,
grouped by `region`.

---

#### `list_available_refineries`

**File:** `tools/helpers.py`  
**Parameters:** None  
**Returns:**
```json
{
  "status": "success",
  "data": {
    "refineries": [
      { "id": "REF_001", "name": "Refinery A", "location": "Houston", "country": "USA",
        "capacity_bpd": 421844, "complexity_index": 5.77 },
      ...
    ],
    "count": 4
  }
}
```
**Logic:** All rows from `refineries.csv`.

---

#### `list_properties_and_yields`

**File:** `tools/helpers.py`  
**Parameters:** None  
**Returns:**
```json
{
  "status": "success",
  "data": {
    "properties": [
      { "name": "api_gravity",    "description": "API gravity in degrees", "unit": "degrees" },
      { "name": "sulfur_content", "description": "Sulfur content",          "unit": "% weight" },
      { "name": "viscosity",      "description": "Kinematic viscosity",     "unit": "cSt" },
      { "name": "pour_point",     "description": "Pour point",              "unit": "°C" },
      { "name": "tan",            "description": "Total acid number",        "unit": "mg KOH/g" },
      { "name": "density_kg_m3",  "description": "Density at 15°C",         "unit": "kg/m³" }
    ],
    "yields": [
      { "name": "diesel_yield",    "description": "Diesel yield",    "unit": "% volume" },
      { "name": "gasoline_yield",  "description": "Gasoline yield",  "unit": "% volume" },
      { "name": "jet_fuel_yield",  "description": "Jet fuel yield",  "unit": "% volume" },
      { "name": "fuel_oil_yield",  "description": "Fuel oil yield",  "unit": "% volume" },
      { "name": "lpg_yield",       "description": "LPG yield",       "unit": "% volume" },
      { "name": "naphtha_yield",   "description": "Naphtha yield",   "unit": "% volume" }
    ]
  }
}
```
**Logic:** Static definition embedded in the tool (properties come from column headers of
`crude_properties.csv`; yields from `yield_forecasts.csv`).

---

#### `find_matching_crude`

**File:** `tools/helpers.py`  
**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `crude_name` | `str` | Yes | — | Raw name from user query (may have typos) |
| `threshold` | `float` | No | `0.6` | Minimum `rapidfuzz` WRatio score (0–1) |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "extracted_name": "brent crude",
    "matched_name": "Brent",
    "similarity_score": 0.95,
    "alternatives": [
      { "name": "Bonny Light", "score": 0.45 }
    ]
  }
}
```
**Logic:** `rapidfuzz.process.extractOne` against all names from `list_available_crudes`.
Return top match if score ≥ `threshold`; top-3 alternatives (below threshold) always
included. If no match ≥ threshold, `status: failure`.

---

#### `find_matching_property`

**File:** `tools/helpers.py`  
**Parameters:**

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `property_name` | `str` | Yes | — |
| `category` | `str` | No | `"both"` — `"property"`, `"yield"`, or `"both"` |
| `threshold` | `float` | No | `0.6` |

**Returns:** Same envelope as `find_matching_crude` plus `category` field.  
**Logic:** Match against canonical names from `list_properties_and_yields`. Common aliases
pre-mapped: `"API" → "api_gravity"`, `"sulphur" → "sulfur_content"`, `"S&P" → "sulfur_content"`.

---

#### `find_matching_refinery`

**File:** `tools/helpers.py`  
**Parameters:**

| Parameter | Type | Required | Default |
|-----------|------|----------|---------|
| `refinery_name` | `str` | Yes | — |
| `threshold` | `float` | No | `0.6` |

**Returns:** Same envelope as `find_matching_crude` plus `refinery_id` and `location` fields.  
**Logic:** Match against both `refinery_name` and `location` columns from `refineries.csv`;
also matches `refinery_id` directly (e.g. "REF001", "ref_001").

---

#### `get_refinery_id`

**File:** `tools/helpers.py`  
**Parameters:**

| Parameter | Type | Required |
|-----------|------|----------|
| `refinery_name` | `str` | Yes |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "refinery_name": "Refinery A",
    "refinery_id": "REF_001",
    "location": "Houston",
    "country": "USA"
  }
}
```
**Logic:** Case-insensitive exact match on `refinery_name` in `refineries.csv`.
Error if no exact match found (suggest using `find_matching_refinery` instead).

---

### 8.3 Blending Tools

#### `blend_simulator_tool`

**File:** `tools/blend_simulator.py`  
**Description:** Simulate blending two or more crude oils. Computes volume-weighted average
properties and estimates product yields either from historical yield data or from the
nearest matching blend simulation record.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `crude_names` | `List[str]` | Yes | — | 2+ canonical crude names |
| `proportions` | `List[float]` | Yes | — | Must sum to 1.0 (±0.01 tolerance) |
| `refinery_id` | `str` | No | `None` | If provided, yields are refinery-specific from `historical_yields.csv` |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "blend_properties": {
      "api_gravity": 37.2,
      "sulfur_content": 0.41,
      "viscosity": 29.5,
      "pour_point": -12.0,
      "tan": 0.87,
      "density_kg_m3": 836.0
    },
    "product_yields": {
      "diesel_yield": 32.4,
      "gasoline_yield": 30.1,
      "jet_fuel_yield": 16.8,
      "fuel_oil_yield": 9.5,
      "lpg_yield": 5.2,
      "naphtha_yield": 3.1
    },
    "blend_composition": [
      { "crude_name": "Brent", "proportion": 0.6 },
      { "crude_name": "WTI",   "proportion": 0.4 }
    ],
    "yield_source": "historical_average"
  }
}
```

**Logic:**
1. Validate `proportions` sum to 1.0 (±0.01).
2. Blend properties = volume-weighted average of static properties from
   `crude_properties.csv`.
3. For yields: if `refinery_id` provided, compute weighted average from
   `historical_yields.csv` per crude. Otherwise use `blend_simulations.csv`
   nearest-match lookup by `crude_mix` composition.

---

### 8.4 Analysis Tools

#### `optimizer_tool`

**File:** `tools/analysis.py`  
**Description:** Find the optimal crude blend that maximises yield, minimises cost, or
maximises profit, subject to user-specified constraints. Uses `scipy.optimize.linprog`
(LP relaxation; proportions treated as continuous 0–1).

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `objective` | `str` | Yes | — | `"maximize_yield"` \| `"minimize_cost"` \| `"maximize_profit"` |
| `target_product` | `str` | No | `"diesel"` | Product yield to optimise (for maximize_yield) |
| `constraints` | `dict` | No | `{}` | Property constraints e.g. `{"sulfur_content": {"max": 1.5}, "api_gravity": {"min": 30}}` |
| `available_crudes` | `List[str]` | No | all crudes | Subset of crudes to consider |
| `refinery_id` | `str` | No | `None` | Scopes yields to refinery config |
| `target_date` | `str` | No | nearest available | `YYYY-MM-DD` for forecasted data |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "optimal_blend": {
      "crude_names": ["Brent", "Bonny Light"],
      "proportions": [0.65, 0.35]
    },
    "objective_value": 35.8,
    "blend_properties": { "api_gravity": 39.5, "sulfur_content": 0.36 },
    "product_yields": { "diesel_yield": 35.8, "gasoline_yield": 32.1 },
    "constraints_satisfied": true,
    "target_product": "diesel"
  }
}
```

**Logic:**
- Build a yield / cost matrix across `available_crudes` from `yield_forecasts.csv` and
  `crude_price_forecasts.csv`.
- Formulate LP: maximise/minimise objective vector subject to proportion-sum = 1,
  each proportion ∈ [0, 1], and property constraints (linear in proportions via
  weighted average).
- Solve with `scipy.optimize.linprog` (HiGHS method).

---

#### `constraint_checker_tool`

**File:** `tools/analysis.py`  
**Description:** Check whether a specific crude blend meets defined constraints (sulfur
limits, API range, product quality specs, regulatory thresholds).

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `crude_names` | `List[str]` | Yes | Crudes in the blend |
| `proportions` | `List[float]` | Yes | Must sum to 1.0 |
| `constraints` | `dict` | Yes | e.g. `{"sulfur_content": {"max": 1.5}, "api_gravity": {"min": 30, "max": 40}}` |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "all_constraints_satisfied": false,
    "blend_properties": { "api_gravity": 38.1, "sulfur_content": 1.82 },
    "constraint_results": [
      { "property": "sulfur_content", "limit": {"max": 1.5}, "actual": 1.82, "passed": false },
      { "property": "api_gravity",    "limit": {"min": 30},  "actual": 38.1, "passed": true  }
    ],
    "violations": [
      { "property": "sulfur_content", "excess": 0.32 }
    ]
  }
}
```

**Logic:** Compute blended properties (volume-weighted average). Evaluate each constraint.
Also cross-check against `quality_specs.csv` for the nominated product type (if provided).

---

#### `price_calculator_tool`

**File:** `tools/analysis.py`  
**Description:** Calculate total delivered cost of a crude blend at a refinery for a given
volume, using forecasted or historical prices plus transportation costs.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `crude_names` | `List[str]` | Yes | — | |
| `proportions` | `List[float]` | Yes | — | Must sum to 1.0 |
| `volume` | `float` | Yes | — | Total volume in barrels |
| `target_date` | `str` | No | nearest future | `YYYY-MM-DD` |
| `refinery_id` | `str` | No | `None` | Adds delivery / transport cost from `transportation_costs.csv` |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "total_cost_usd": 840500.0,
    "cost_per_barrel": 84.05,
    "currency": "USD",
    "breakdown": [
      { "crude_name": "Brent", "proportion": 0.6, "spot_price": 82.5,
        "delivery_cost": 7.7, "total_per_barrel": 90.2, "volume_bbl": 6000, "subtotal": 541200.0 },
      { "crude_name": "WTI",   "proportion": 0.4, "spot_price": 78.6,
        "delivery_cost": 7.7, "total_per_barrel": 86.3, "volume_bbl": 4000, "subtotal": 345200.0 }
    ],
    "price_source": "forecasted"
  }
}
```

**Logic:** For each crude: look up `crude_price_forecasts.csv` for closest `target_date`;
add `transportation_costs.csv` delivery cost if `refinery_id` provided.
Fallback to `historical_prices_delivered.csv` if forecast not available.

---

#### `profitability_calculator_tool`

**File:** `tools/analysis.py`  
**Description:** Full P&L: revenue from refined products minus crude cost and transport.
Uses forecasted product prices (product price constants in `config.py`, representative
market values) and yield forecast per crude.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `crude_names` | `List[str]` | Yes | |
| `proportions` | `List[float]` | Yes | Must sum to 1.0 |
| `volume` | `float` | Yes | Barrels |
| `refinery_id` | `str` | Yes | |
| `target_date` | `str` | No | Nearest future date |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "total_revenue_usd": 1050000.0,
    "total_cost_usd": 840500.0,
    "gross_profit_usd": 209500.0,
    "profit_margin_pct": 19.9,
    "roi_pct": 24.9,
    "product_revenues": {
      "diesel":   { "yield_pct": 34.2, "volume_bbl": 3420, "price_per_bbl": 120.0, "revenue": 410400.0 },
      "gasoline": { "yield_pct": 33.6, "volume_bbl": 3360, "price_per_bbl": 110.0, "revenue": 369600.0 }
    },
    "cost_breakdown": {
      "crude_cost":      800000.0,
      "transport_cost":   40500.0
    }
  }
}
```

**Logic:**
1. Call `price_calculator_tool` logic internally for crude cost.
2. Compute product volumes = blend yield (weighted average from `yield_forecasts.csv`) × total volume.
3. Revenue = product volume × product price (from `config.py`).
4. Gross profit = Revenue − Total cost.

---

### 8.5 Additional Tools

#### `get_high_yield_crudes`

**Category:** Analysis (additional)  
**File:** `tools/analysis.py`  
**Description:** Rank all crudes by a target product's forecasted yield in a given month,
filtered by a maximum sulfur threshold. Directly answers queries like *"Which crudes give
the highest diesel yield under 1.5% sulfur?"* without requiring the agent to loop over
`forecast_tool` for every crude.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `target_month` | `str` | Yes | — | `YYYY-MM-DD` |
| `refinery_id` | `str` | Yes | — | |
| `product` | `str` | No | `"diesel"` | Yield column: `"diesel"`, `"gasoline"`, `"jet_fuel"`, `"fuel_oil"`, `"lpg"`, `"naphtha"` |
| `max_sulfur` | `float` | No | `1.5` | Maximum sulfur content (% weight) |
| `top_n` | `int` | No | `5` | Number of results to return |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "target_month": "2026-08-01",
    "refinery_id": "REF_001",
    "product": "diesel",
    "max_sulfur_filter": 1.5,
    "results": [
      { "rank": 1, "crude_name": "Bonny Light", "diesel_yield": 38.2, "sulfur_content": 0.37, "forecasted_price": 81.2 },
      { "rank": 2, "crude_name": "WTI",         "diesel_yield": 35.5, "sulfur_content": 0.49, "forecasted_price": 78.6 },
      { "rank": 3, "crude_name": "Brent",        "diesel_yield": 34.9, "sulfur_content": 0.37, "forecasted_price": 82.5 }
    ],
    "total_candidates": 10,
    "filtered_out": 7
  }
}
```

**Logic:**
1. Load `yield_forecasts.csv` filtered to `refinery_id` and closest date to `target_month`.
2. Join with `crude_properties_forecast.csv` (or `forecasted_crude_properties.csv`) to get
   forecasted sulfur values.
3. Filter rows where `sulfur_content ≤ max_sulfur`.
4. Sort descending by `{product}_yield`. Return top `top_n` rows plus price from
   `forecasted_prices.csv`.

---

#### `get_market_context`

**Category:** Analysis (additional)  
**File:** `tools/analysis.py`  
**Description:** Return product-level demand trend, price sentiment, inventory levels, and
(optionally) crude-level supply/demand balance for a date range. Provides the market
narrative needed for buy/hold signals, which no other tool in the spec covers.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `product_type` | `str` | Yes | `"Diesel"`, `"Gasoline"`, `"Jet Fuel"`, etc. (matches `market_trends.csv`) |
| `from_date` | `str` | Yes | `YYYY-MM-DD` |
| `to_date` | `str` | Yes | `YYYY-MM-DD` |
| `crude_name` | `str` | No | If provided, also returns supply/demand balance |

**Returns:**
```json
{
  "status": "success",
  "data": {
    "product_type": "Diesel",
    "date_range": { "from": "2026-06-01", "to": "2026-06-30" },
    "market_trends": [
      { "date": "2026-06-01", "demand_trend": "Increasing", "price_trend": "Bullish",
        "market_sentiment": 0.79, "inventory_level": "Normal" }
    ],
    "summary": {
      "dominant_demand_trend": "Increasing",
      "dominant_price_trend": "Bullish",
      "avg_sentiment": 0.62,
      "recommendation_signal": "BUY"
    },
    "supply_demand": [
      { "date": "2026-06-01", "crude_name": "Brent", "supply_volume": 4100000,
        "demand_volume": 3900000, "balance": 200000, "region": "Europe" }
    ]
  }
}
```

**Logic:**
1. Filter `market_trends.csv` by `product_type` and date range.
2. Derive `recommendation_signal`: `"BUY"` if dominant trend is Increasing + Bullish;
   `"HOLD"` if Stable/Neutral; `"CAUTION"` if Decreasing or Bearish.
3. If `crude_name` provided, filter `supply_demand.csv` for that crude in the date range.

---

## 9. Error Handling Standard

All tools must implement this try/except pattern:

```python
try:
    # Tool logic
    return {"status": "success", "data": result}
except ValueError as e:
    return {"status": "failure", "error": f"Invalid parameter: {e}"}
except KeyError as e:
    return {"status": "failure", "error": f"Data not found: {e}"}
except Exception as e:
    logger.error(f"[{tool_name}] Unexpected error: {e}", exc_info=True)
    return {"status": "failure", "error": str(e)}
```

**Rules:**
- Never raise exceptions out of a tool — always return `status: failure` so the agent can
  retry or report cleanly.
- Use Python's `logging` module (not `print`) — FastMCP routes `stderr` safely.
- Include the tool name in log messages for easy tracing.

---

## 10. Environment Setup

### `environment.yml`

```yaml
name: feedstock_advisor
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - pandas=2.2
  - numpy=1.26
  - scipy=1.13
  - pip
  - pip:
    - mcp[cli]>=1.6
    - pydantic>=2.7
    - rapidfuzz>=3.9
```

### Setup Commands

```bash
# Create environment (once)
conda env create -f environment.yml

# Activate
conda activate feedstock_advisor

# Run the server
python server.py
```

### MCP Registration (`mcp.json`)

```json
{
  "mcpServers": {
    "feedstock-advisor": {
      "command": "python",
      "args": ["<absolute-path-to>/server.py"],
      "env": {
        "DATA_BACKEND": "csv"
      }
    }
  }
}
```

---

## 11. Build Phases & Milestones

| Phase | Deliverable | Files Created / Modified |
|-------|-------------|--------------------------|
| 1 — Scaffold | Project skeleton, conda env, empty modules | `environment.yml`, `config.py`, `data_access/__init__.py`, `tools/__init__.py` |
| 2 — Data Layer | Abstract providers + CsvDataStore | `data_access/base.py`, `data_access/csv_provider.py` |
| 3 — Helpers | 7 list/find/get tools | `tools/helpers.py` |
| 4 — Forecast | `forecast_tool` with price/properties/yield | `tools/forecast.py` |
| 5 — Blend | `blend_simulator_tool` | `tools/blend_simulator.py` |
| 6 — Analysis | 6 analysis tools (LP optimizer, constraints, price, profitability, yield ranking, market context) | `tools/analysis.py` |
| 7 — Server | Wire all tools into FastMCP | `server.py` |
| 8 — Docs & Register | README, mcp.json snippet | `README.md` |

---

## 12. Future Extension Points

| Extension | How to Add |
|-----------|------------|
| Live price feed | Implement `ApiPriceProvider(PriceProvider)` and set `DATA_BACKEND=api` |
| Database backend | Implement `DbDataStore` with SQLAlchemy, set `DATA_BACKEND=db` |
| New crude / refinery data | Add rows to the relevant CSV; no code change needed |
| New tool | Add function to relevant `tools/*.py` module, register in `server.py` |
| Additional forecast models | Extend `YieldProvider.get_yield_forecast()` to call ML model endpoint |
| Authentication | Add API-key env-var check in `server.py` before `mcp.run()` |

---

## 13. Constraints & Assumptions

| # | Statement |
|---|-----------|
| C1 | All dummy CSV data is considered read-only; the server does not write back to any file |
| C2 | Date matching uses nearest-available-date logic (within ±45 days); exact date matches are not required |
| C3 | Property blending uses linear volume-weighted averaging; no non-linear blending correlations are modelled |
| C4 | `optimizer_tool` LP relaxation treats crude proportions as continuous; minimum-lot-size constraints are not modelled |
| C5 | Product prices for profitability calculation are fixed constants in `config.py` (representative market values) and are not forecasted dynamically |
| C6 | The `regulatory_limits.csv` file currently contains price forecast data (matching `crude_price_forecasts.csv`); `constraint_checker_tool` will use `quality_specs.csv` as the primary regulatory source and treat `regulatory_limits.csv` as a supplementary price-based signal |
| C7 | The server runs in a single process; no concurrent request handling is required for the initial release |
| C8 | All monetary values are in USD |

---

*Document maintained by the Feedstock Advisor MCP development team.*  
*Next review: after Phase 7 completion.*
