# Data Access Guide

This document explains how to point the Feedstock Advisor MCP Server at external data instead of the bundled demo CSV files.

---

## Architecture Overview

The system uses a three-layer provider abstraction that keeps all tool code decoupled from the data source:

| Layer | File | Role |
|---|---|---|
| Contracts | [`data_access/base.py`](data_access/base.py) | 7 abstract provider ABCs |
| Implementation | [`data_access/csv_provider.py`](data_access/csv_provider.py) | Concrete backend (reads 18 CSV files from `data/`) |
| Backend selector | [`data_access/__init__.py`](data_access/__init__.py) | Picks the backend via `DATA_BACKEND` env var |

The `data/` directory is currently empty. Swapping backends requires **zero changes to tool code** — only the data layer changes.

---

## Option A — Drop-in CSV Replacement (Quickest Path)

Place your real data files in the `data/` directory using the exact filenames that [`CsvDataStore.__init__`](data_access/csv_provider.py) expects. The required columns for each file are defined in the abstract methods in [`data_access/base.py`](data_access/base.py).

### Required Files and Column Schemas

#### Price Tables

**`forecasted_prices.csv`**
```
crude_name, forecast_date, predicted_price, confidence_interval_lower,
confidence_interval_upper, forecast_model, confidence_score
```

**`crude_price_forecasts.csv`**
```
crude_name, forecast_date, predicted_price, confidence_interval_lower,
confidence_interval_upper, forecast_model, confidence_score
```

**`historical_prices.csv`**
```
crude_name, date, price_usd_per_barrel, volume_traded, currency
```

**`historical_prices_delivered.csv`**
```
forecast_date, crude_name, refinery_id, predicted_spot_price, delivery_cost,
total_predicted_price, lower_bound, upper_bound, confidence_level, forecast_model
```

#### Properties Tables

**`crude_properties.csv`**
```
crude_name, api_gravity, sulfur_content, viscosity, pour_point, tan, region, density_kg_m3
```

**`crude_properties_forecast.csv`**
```
forecast_date, crude_name, api_gravity, sulfur_content, viscosity,
pour_point, tan, confidence_level
```

**`crude_properties_delivered.csv`**
```
forecast_date, crude_name, api_gravity, sulfur_content, viscosity,
pour_point, tan, confidence_level
```

**`forecasted_crude_properties.csv`**
```
forecast_date, crude_name, api_gravity, sulfur_content, viscosity,
pour_point, tan, confidence_score
```

#### Yield Tables

**`historical_yields.csv`**
```
observation_date, crude_name, refinery_id, gasoline_yield, diesel_yield,
jet_fuel_yield, fuel_oil_yield, lpg_yield, naphtha_yield, other_yield,
processing_volume_bpd
```

**`yield_forecasts.csv`**
```
forecast_date, crude_name, refinery_id, gasoline_yield, diesel_yield,
jet_fuel_yield, fuel_oil_yield, lpg_yield, naphtha_yield, other_yield,
confidence_lower, confidence_upper, forecast_model, confidence_score
```

#### Blend Simulations

**`blend_simulations.csv`**
```
simulation_id, simulation_date, crude_mix, diesel_yield, gasoline_yield,
jet_fuel_yield, other_products_yield, total_cost, diesel_sulfur, gasoline_octane
```

#### Refinery Tables

**`refineries.csv`**
```
refinery_id, refinery_name, location, country, capacity_bpd, complexity_index,
configuration_type, has_hydrocracker, has_fcc, has_coker
```

**`refinery_configs.csv`**
```
refinery_id, refinery_name, location, capacity_bpd, complexity_index,
has_hydrocracker, has_fcc, has_coker, diesel_max_capacity, gasoline_max_capacity
```

**`quality_specs.csv`**
```
product_type, specification, min_value, max_value, unit
```

**`regulatory_limits.csv`**
```
forecast_date, [regulatory limit fields]
```

#### Transport

**`transportation_costs.csv`**
```
origin, destination, transport_mode, cost_per_barrel, transit_time_days, effective_date
```

#### Market

**`market_trends.csv`**
```
date, product_type, demand_trend, price_trend, market_sentiment, inventory_level
```

**`supply_demand.csv`**
```
date, crude_name, supply_volume, demand_volume, unit, region
```

### Using a Custom Data Directory

By default, the server reads from the `data/` folder next to `config.py`. To point to a different path, either:

- Change `DATA_DIR` in [`config.py`](config.py):
  ```python
  DATA_DIR: Path = Path("/your/external/data/path")
  ```
- Or pass it directly when constructing the store (e.g. in a custom entry point):
  ```python
  store = CsvDataStore(data_dir=Path("/your/external/data/path"))
  ```

No other code changes are needed — restart the server and it will load from the new location.

---

## Option B — Database Backend

The `db` backend slot is reserved in the backend selector but not yet implemented.

**Steps:**

1. Create `data_access/db_provider.py` implementing all 7 ABCs from [`data_access/base.py`](data_access/base.py) using SQLAlchemy (or any DB library of your choice).
2. Add your connection string to `.env`:
   ```
   DATABASE_URL=postgresql://user:password@host:5432/dbname
   ```
3. Set the backend in `.env`:
   ```
   DATA_BACKEND=db
   ```
4. Replace the stub in [`data_access/__init__.py`](data_access/__init__.py):
   ```python
   elif DATA_BACKEND == "db":
       from data_access.db_provider import DbDataStore as DataStore
   ```

---

## Option C — REST API Backend

The `api` backend slot is reserved in the backend selector but not yet implemented.

**Steps:**

1. Create `data_access/api_provider.py` implementing all 7 ABCs from [`data_access/base.py`](data_access/base.py) using `httpx` or `requests`.
2. Add your API credentials to `.env`:
   ```
   DATA_API_BASE_URL=https://your-data-api.example.com
   DATA_API_KEY=your-api-key
   ```
3. Set the backend in `.env`:
   ```
   DATA_BACKEND=api
   ```
4. Replace the stub in [`data_access/__init__.py`](data_access/__init__.py):
   ```python
   elif DATA_BACKEND == "api":
       from data_access.api_provider import ApiDataStore as DataStore
   ```

---

## Selecting a Backend

The backend is controlled by the `DATA_BACKEND` environment variable in your `.env` file (see [`.env.example`](.env.example)):

```
# Options: csv | db | api
DATA_BACKEND=csv
```

The [`data_access/__init__.py`](data_access/__init__.py) module reads this value at startup and imports the corresponding concrete class as `DataStore`. All tool modules import only `DataStore` — they are unaware of which backend is active.

---

## Summary

| Path | Effort | When to use |
|---|---|---|
| **Option A** — Populate `data/` with 18 CSV files | Minimal — no code changes | Data is available as flat files or easily exportable to CSV |
| **Option B** — Implement `db_provider.py` | Medium — implement 7 ABCs | Data lives in a relational database |
| **Option C** — Implement `api_provider.py` | Medium — implement 7 ABCs | Data is served by an internal or external REST API |
