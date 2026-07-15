# Feedstock Advisor MCP Server

A Python-based **Model Context Protocol (MCP) server** that equips a Gen-AI feedstock consulting agent with 15 domain tools for the petrochemical trading industry.

The server answers questions such as:

- *"Which crude is most profitable in the next three months?"*
- *"Which crudes give the highest diesel yield under 1.5% sulfur in August 2026?"*
- *"What is the optimal blend to maximise diesel yield at Refinery A?"*
- *"Should I buy Brent in June 2026?"*
- *"What is the all-in cost of a 60/40 Brent/WTI blend delivered to REF_001?"*

---

## Quick Start

### 1. Prerequisites

- [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html) installed
- Python 3.11+ (managed via conda — no separate install needed)

### 2. Create the conda environment

```bash
conda env create -f environment.yml
conda activate feedstock_advisor
```

### 3. Run the server (manual test)

```bash
conda activate feedstock_advisor
python server.py
```

The server starts on **stdio** transport and logs to stderr. You will see:

```
Initialising data store…
CsvDataStore: loading all data files from …/data
CsvDataStore: all data files loaded successfully.
Data store ready.
Starting Feedstock Advisor MCP Server (stdio transport)…
```

Press `Ctrl+C` to stop.

---

## Exposing the Server via ngrok

The server supports two transports:

| Transport | Entry-point | Use case |
|---|---|---|
| **stdio** | `server.py` | Local MCP clients (Bob, Claude Desktop) |
| **HTTP** | `server_http.py` | Remote clients, ngrok tunnels, custom integrations |

### Step 1 — Install ngrok

1. Download from <https://ngrok.com/download> (Windows ZIP), extract `ngrok.exe` to a folder on `PATH` (e.g. `C:\Windows\System32\`).
2. Sign up free at <https://dashboard.ngrok.com> and copy your authtoken.
3. Authenticate once:
   ```powershell
   ngrok config add-authtoken <YOUR_NGROK_TOKEN>
   ```

### Step 2 — Start with the launcher script (recommended)

```powershell
conda activate feedstock_advisor
.\start_ngrok.ps1              # uses port 8000 by default
.\start_ngrok.ps1 -Port 9000  # custom port
```

The script will:
1. Start `server_http.py` in a new terminal window.
2. Wait for the server to accept connections.
3. Open an ngrok tunnel and print the public URLs.

Example output:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Feedstock Advisor MCP — Public Endpoints
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Streamable HTTP (preferred, MCP 2025-03):
    https://abc123.ngrok-free.app/mcp

  Legacy SSE (for older MCP clients):
    https://abc123.ngrok-free.app/sse

  ngrok dashboard : http://127.0.0.1:4040
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 3 — Start manually (alternative)

Terminal 1 — MCP HTTP server:
```powershell
conda activate feedstock_advisor
python server_http.py
# or on a custom port:
$env:MCP_PORT="9000"; python server_http.py
```

Terminal 2 — ngrok tunnel:
```powershell
ngrok http 8000
```

### Step 4 — Connect a remote MCP client

Use the public ngrok URL printed by ngrok.

**Streamable HTTP** (MCP spec 2025-03-26, preferred):
```
https://<id>.ngrok-free.app/mcp
```

**Legacy SSE** (for clients that haven't upgraded):
```
https://<id>.ngrok-free.app/sse
```

Example Claude Desktop `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "feedstock-advisor": {
      "url": "https://<id>.ngrok-free.app/mcp"
    }
  }
}
```

> **Note:** The free ngrok plan assigns a random URL each session.
> Upgrade to a paid plan for a stable subdomain (`https://feedstock.ngrok.app/mcp`).

---

## Project Structure

```
feedstock_advisor_mcp/
├── environment.yml              # Conda environment (Python 3.11 + all deps)
├── README.md                    # This file
├── PLAN_AND_REQUIREMENTS.md     # Full design and requirements document
├── server.py                    # MCP server — stdio transport (local clients)
├── server_http.py               # MCP server — HTTP transport (ngrok / remote)
├── start_ngrok.ps1              # PowerShell launcher: server + ngrok tunnel
├── config.py                    # Paths, env-var hooks, product prices, defaults
│
├── data/                        # Bundled dummy CSV data (18 files, read-only)
│
├── data_access/
│   ├── __init__.py              # Backend selector (csv / db / api via DATA_BACKEND)
│   ├── base.py                  # Abstract provider ABCs (7 provider classes)
│   └── csv_provider.py          # CsvDataStore — pandas implementation
│
├── tests/
│   └── test_tools.py            # pytest suite — 62 tests across all 15 tools
│
└── tools/
    ├── helpers.py               # 7 helper/discovery tools
    ├── forecast.py              # forecast_tool
    ├── blend_simulator.py       # blend_simulator_tool
    └── analysis.py              # 6 analysis tools
```

---

## Available Tools (15)

### Helper Tools (7)

| MCP Tool Name | Purpose |
|---|---|
| `list_available_crudes_tool` | All crude names grouped by region |
| `list_available_refineries_tool` | All refineries with id, name, location, capacity |
| `list_properties_and_yields_tool` | Canonical property and yield names with units |
| `find_matching_crude_tool` | Fuzzy-match a user-typed crude name (typo-tolerant) |
| `find_matching_property_tool` | Fuzzy-match a property/yield name (e.g. "sulphur" → sulfur_content) |
| `find_matching_refinery_tool` | Fuzzy-match a refinery name or location |
| `get_refinery_id_tool` | Exact name → refinery ID lookup |

### Forecasting Tool (1)

| MCP Tool Name | Purpose |
|---|---|
| `forecast_tool_mcp` | Price / properties / yield forecast for a crude in a target month |

### Blending Tool (1)

| MCP Tool Name | Purpose |
|---|---|
| `blend_simulator_tool_mcp` | Simulate blending ≥2 crudes; blended properties + product yields |

### Analysis Tools (6)

| MCP Tool Name | Purpose |
|---|---|
| `constraint_checker_tool_mcp` | Check a blend against property constraints (sulfur, API, etc.) |
| `price_calculator_tool_mcp` | Total delivered cost of a crude blend for a given volume |
| `profitability_calculator_tool_mcp` | Gross profit, margin, ROI for processing a blend |
| `optimizer_tool_mcp` | LP-based optimal blend (maximise yield/profit, minimise cost) |
| `get_high_yield_crudes_tool` | Rank crudes by product yield filtered by max sulfur |
| `get_market_context_tool` | Demand trend, price sentiment, buy/hold signal |

---

## Registering with Bob (MCP Client)

The workspace-level MCP config is at [`.bob/mcp.json`](.bob/mcp.json).

If Bob is already open, it will hot-reload the server automatically.
To register manually, add the following block to your global `~/.bob/settings/mcp.json`
(or use the workspace `.bob/mcp.json` included in this project):

```json
{
  "mcpServers": {
    "feedstock-advisor": {
      "command": "C:\\Users\\00586O744\\anaconda3\\envs\\feedstock_advisor\\python.exe",
      "args": [
        "C:\\Users\\00586O744\\Desktop\\feedstock_advisor_MCP\\feedstock_advisor_mcp\\server.py"
      ],
      "env": {
        "DATA_BACKEND": "csv"
      }
    }
  }
}
```

> **Note:** The `.bob/mcp.json` in this project uses the absolute path to the conda env's
> `python.exe`. Update the paths if you are on a different machine or installed conda elsewhere.

---

## Configuration

All settings are in [`config.py`](config.py) and can be overridden via environment variables:

| Env Var | Default | Description |
|---|---|---|
| `DATA_BACKEND` | `csv` | Data source: `csv` \| `db` \| `api` |
| `DATE_MATCH_TOLERANCE_DAYS` | `45` | ±days window for nearest forecast date |
| `FUZZY_MATCH_THRESHOLD` | `0.6` | Minimum fuzzy match score (0–1) |
| `DEFAULT_MAX_SULFUR` | `1.5` | Default sulfur cap for `get_high_yield_crudes` |
| `DEFAULT_TOP_N` | `5` | Default top-N results for `get_high_yield_crudes` |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `PRICE_DIESEL` | `120.0` | Reference diesel price USD/bbl |
| `PRICE_GASOLINE` | `110.0` | Reference gasoline price USD/bbl |
| `PRICE_JET_FUEL` | `115.0` | Reference jet fuel price USD/bbl |
| `PRICE_FUEL_OIL` | `70.0` | Reference fuel oil price USD/bbl |
| `PRICE_LPG` | `60.0` | Reference LPG price USD/bbl |
| `PRICE_NAPHTHA` | `85.0` | Reference naphtha price USD/bbl |

---

## Data Sources

All 18 CSV files are bundled in `data/` and loaded at server startup.

| File | Content |
|---|---|
| `crude_properties.csv` | Static crude physical properties (API, sulfur, viscosity, …) |
| `crude_properties_forecast.csv` | Forecasted crude properties per refinery |
| `forecasted_crude_properties.csv` | Simpler property forecasts (no refinery scope) |
| `forecasted_prices.csv` | Spot price forecasts |
| `crude_price_forecasts.csv` | Delivered price forecasts per refinery |
| `historical_prices.csv` | Historical spot prices |
| `historical_prices_delivered.csv` | Historical delivered prices |
| `yield_forecasts.csv` | Product yield forecasts per crude × refinery |
| `historical_yields.csv` | Historical product yields |
| `blend_simulations.csv` | Pre-computed blend simulation records |
| `refineries.csv` | Refinery master data |
| `refinery_configs.csv` | Detailed refinery configurations |
| `quality_specs.csv` | Product quality specifications |
| `regulatory_limits.csv` | Regulatory reference data |
| `transportation_costs.csv` | Origin–destination transport costs |
| `market_trends.csv` | Weekly product market trend data |
| `supply_demand.csv` | Crude supply/demand balance data |
| `crude_properties_delivered.csv` | Delivered crude property records |

---

## Swapping the Data Backend

The data access layer is fully abstracted. To use a live database or REST API:

1. Implement a new class in `data_access/` that inherits all 7 provider ABCs from
   [`data_access/base.py`](data_access/base.py).
2. Set `DATA_BACKEND=db` (or `api`) in your environment.
3. Add the import mapping in [`data_access/__init__.py`](data_access/__init__.py).

No tool code changes are required.

---

## Agent Workflow Patterns

### Buy/Hold recommendation
```
find_matching_crude_tool("brent crude")
  → forecast_tool_mcp("Brent", "2026-06-01", metric="price")
  → forecast_tool_mcp("Brent", "2026-06-01", metric="properties")
  → get_market_context_tool("Diesel", "2026-06-01", "2026-06-30", crude_name="Brent")
```

### Optimal blend for maximum diesel yield
```
list_available_crudes_tool()
  → optimizer_tool_mcp("maximize_yield", "diesel", {"sulfur_content": {"max": 1.5}}, refinery_id="REF_001")
  → constraint_checker_tool_mcp(blend, proportions, {"sulfur_content": {"max": 1.5}})
  → profitability_calculator_tool_mcp(blend, proportions, 10000, "REF_001")
```

### High-yield crude ranking
```
get_high_yield_crudes_tool("2026-08-01", "REF_001", product="diesel", max_sulfur=1.5, top_n=5)
  → forecast_tool_mcp(top_crude, "2026-08-01", metric="price")
```

---

## Testing

```powershell
conda activate feedstock_advisor
pytest tests/test_tools.py -v
```

62 tests covering all 15 tools — helpers, forecasting, blending, and all 6 analysis tools.

---

## Development

```bash
# Activate environment
conda activate feedstock_advisor

# Quick smoke-test a single tool
python -c "
import sys; sys.path.insert(0, '.')
from data_access import DataStore
from tools.helpers import list_available_crudes
store = DataStore()
print(list_available_crudes(store))
"
```

---

## Branch

This server is implemented on branch **`feature/init`**.

---

*Feedstock Advisor MCP Server — built for the petrochemical trading industry.*
