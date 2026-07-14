"""
config.py
---------
Central configuration for the Feedstock Advisor MCP Server.

All path resolution, environment-variable hooks, and shared constants
live here so every other module has a single import point.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Root of the project (the directory that contains this file)
BASE_DIR: Path = Path(__file__).resolve().parent

# Directory that holds the bundled CSV data files
DATA_DIR: Path = BASE_DIR / "data"

# ---------------------------------------------------------------------------
# Data backend selection
# ---------------------------------------------------------------------------
# Set DATA_BACKEND=csv   → use CsvDataStore (default, bundled CSVs)
# Set DATA_BACKEND=db    → use DbDataStore  (future: SQLAlchemy)
# Set DATA_BACKEND=api   → use ApiDataStore (future: REST / GraphQL)

DATA_BACKEND: str = os.environ.get("DATA_BACKEND", "csv").lower()

# ---------------------------------------------------------------------------
# Date matching tolerance
# ---------------------------------------------------------------------------
# When looking up forecasts by date, accept the nearest record within this
# many days of the requested target date.

DATE_MATCH_TOLERANCE_DAYS: int = int(os.environ.get("DATE_MATCH_TOLERANCE_DAYS", "45"))

# ---------------------------------------------------------------------------
# Product reference prices (USD / barrel)
# These are representative market constants used by profitability_calculator_tool.
# Override via env-vars to update without changing code.
# ---------------------------------------------------------------------------

PRODUCT_PRICES_USD_PER_BBL: dict[str, float] = {
    "diesel":    float(os.environ.get("PRICE_DIESEL",    "120.0")),
    "gasoline":  float(os.environ.get("PRICE_GASOLINE",  "110.0")),
    "jet_fuel":  float(os.environ.get("PRICE_JET_FUEL",  "115.0")),
    "fuel_oil":  float(os.environ.get("PRICE_FUEL_OIL",   "70.0")),
    "lpg":       float(os.environ.get("PRICE_LPG",        "60.0")),
    "naphtha":   float(os.environ.get("PRICE_NAPHTHA",    "85.0")),
    "other":     float(os.environ.get("PRICE_OTHER",       "55.0")),
}

# ---------------------------------------------------------------------------
# Fuzzy-matching defaults
# ---------------------------------------------------------------------------

FUZZY_MATCH_THRESHOLD: float = float(os.environ.get("FUZZY_MATCH_THRESHOLD", "0.6"))

# Number of alternative matches to include in fuzzy-match responses
FUZZY_MATCH_ALTERNATIVES: int = int(os.environ.get("FUZZY_MATCH_ALTERNATIVES", "3"))

# ---------------------------------------------------------------------------
# Optimiser defaults
# ---------------------------------------------------------------------------

# Default product to optimise when target_product is not specified
DEFAULT_OPTIMISE_PRODUCT: str = "diesel"

# Default maximum sulfur constraint used by get_high_yield_crudes
DEFAULT_MAX_SULFUR: float = float(os.environ.get("DEFAULT_MAX_SULFUR", "1.5"))

# Default number of top results returned by get_high_yield_crudes
DEFAULT_TOP_N: int = int(os.environ.get("DEFAULT_TOP_N", "5"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()
