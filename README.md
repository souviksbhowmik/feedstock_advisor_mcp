# Feedstock Advisor MCP Server

A Python-based **Model Context Protocol (MCP) server** that equips a Gen-AI feedstock consulting agent with 15 domain tools for the petrochemical trading industry.

The server answers questions such as:

- *"Which crude is most profitable in the next three months?"*
- *"Which crudes give the highest diesel yield under 1.5% sulfur in August 2026?"*
- *"What is the optimal blend to maximise diesel yield at Refinery A?"*
- *"Should I buy Brent in June 2026?"*
- *"What is the all-in cost of a 60/40 Brent/WTI blend delivered to REF_001?"*

---

## Table of Contents

1. [Project Structure](#project-structure)
2. [One-Time Setup](#one-time-setup)
3. [Running Locally (stdio)](#running-locally-stdio)
4. [Running with ngrok (HTTP + Bearer Auth)](#running-with-ngrok-http--bearer-auth)
5. [Registering with watsonx / ICA](#registering-with-watsonx--ica)
6. [Registering with Bob (local)](#registering-with-bob-local)
7. [Available Tools (15)](#available-tools-15)
8. [Configuration Reference](#configuration-reference)
9. [Testing](#testing)
10. [Agent Workflow Patterns](#agent-workflow-patterns)
11. [Data Sources](#data-sources)

---

## Project Structure

```
feedstock_advisor_mcp/
├── environment.yml        # Conda environment (Python 3.11 + all deps)
├── .env.example           # Template for environment variables — copy to .env
├── README.md              # This file
├── server.py              # MCP server — stdio transport (Bob, Claude Desktop)
├── server_http.py         # MCP server — HTTP transport (ngrok / watsonx / ICA)
├── start_ngrok.ps1        # PowerShell one-command launcher (server + tunnel)
├── config.py              # Paths, env-var hooks, product prices, defaults
│
├── data/                  # 18 bundled CSV data files (read-only)
├── data_access/           # Data provider abstraction (csv / db / api)
├── tests/
│   └── test_tools.py      # pytest suite — 62 tests across all 15 tools
└── tools/
    ├── helpers.py         # 7 helper / discovery tools
    ├── forecast.py        # forecast_tool
    ├── blend_simulator.py # blend_simulator_tool
    └── analysis.py        # 6 analysis tools
```

---

## One-Time Setup

### Prerequisites

- [Miniconda or Anaconda](https://docs.conda.io/en/latest/miniconda.html)
- Git
- Windows (PowerShell or Command Prompt)

### 1 — Clone the repo

```cmd
git clone https://github.com/souviksbhowmik/feedstock_advisor_mcp.git
cd feedstock_advisor_mcp
```

### 2 — Create the conda environment

```cmd
conda env create -f environment.yml
```

This installs Python 3.11 and all dependencies (pandas, scipy, mcp, uvicorn, etc.).

### 3 — Install ngrok (for HTTP / remote access)

1. Download the Windows ZIP from <https://ngrok.com/download>
2. Extract `ngrok.exe` — copy it to any folder already on your `PATH`
   (e.g. `C:\Windows\System32\` or `C:\Users\<you>\AppData\Roaming\Python\Scripts\`)
3. Sign up free at <https://dashboard.ngrok.com> → copy your **Authtoken**
4. Authenticate once (run this in any terminal):
   ```cmd
   ngrok config add-authtoken YOUR_NGROK_TOKEN_HERE
   ```

---

## Running Locally (stdio)

Use this when connecting Bob or Claude Desktop on the **same machine**.

```cmd
conda activate feedstock_advisor
python server.py
```

Expected output:
```
Initialising data store…
CsvDataStore: all data files loaded successfully.
Data store ready.
```

Press `Ctrl+C` to stop.

---

## Running with ngrok (HTTP + Bearer Auth)

Use this to expose the server publicly so **watsonx, ICA, or any remote agent**
can connect to it from anywhere.

### Step 1 — Choose your Bearer token

The Bearer token is a shared secret. Anyone who wants to connect the server to
their agent needs this value. Pick any string — keep it private.

**Option A — use the team token (recommended for shared repos):** ( Option 1 is used in this case)
```
W*ts*nx_*hal*en*e_20*6
```

**Option B — generate a cryptographically random token:**
```cmd
conda activate feedstock_advisor
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
Copy the output (e.g. `jFhl9FMWZr8zuZDD5-nCp3DBRWywJ21D5kjozoVoP6o`) and share it
with your teammates via a secure channel (Slack DM, not in the repo).

---

### Step 2 — Open Terminal 1 and start the MCP HTTP server

```cmd
cd C:\path\to\feedstock_advisor_mcp
conda activate feedstock_advisor
set MCP_API_KEY=<Token Shared by Team>
python server_http.py
```

Expected output:
```
[INFO]  Bearer token authentication ENABLED.
[INFO]  Starting Feedstock Advisor MCP server (HTTP transport)…
[INFO]  Streamable HTTP : http://127.0.0.1:8000/mcp
[INFO]  Legacy SSE      : http://127.0.0.1:8000/sse
```

> ⚠️ **Keep this terminal open.** The server must stay running.

---

### Step 3 — Open Terminal 2 and start the ngrok tunnel

```cmd
ngrok http 8000
```

ngrok will print something like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

**Your public MCP endpoint is:**
```
https://abc123.ngrok-free.app/mcp
```

> ⚠️ The free ngrok plan gives a **new random URL every time** ngrok restarts.
> Update the URL in your watsonx / ICA registration after each restart.
> To always get the current URL, run:
> ```cmd
> curl http://127.0.0.1:4040/api/tunnels
> ```

---

### Step 4 — (Optional) One-command launcher

Instead of Steps 2 and 3 separately, you can use the PowerShell launcher
which starts both the server and ngrok and prints the URL automatically:

```powershell
conda activate feedstock_advisor
$env:MCP_API_KEY = "Wa*so*x_*ha*len*e_20*6"
.\start_ngrok.ps1
```

---

## Registering with watsonx / ICA

Use these values in the MCP server registration form.

| Field | Value |
|---|---|
| **MCP Server Name** | `feedstock-advisor` |
| **MCP Server URL** | `https://<your-ngrok-id>.ngrok-free.app/mcp` |
| **Description** | Feedstock Advisor — 15 tools for crude oil trading, blending, yield forecasting, pricing, and profitability |
| **Tags** | `petrochemical`, `crude-oil`, `blending`, `forecasting`, `optimizer`, `refinery` |
| **Transport Type** | `Streamable HTTP` |
| **Authentication Type** | `Bearer Token` |
| **Token value** | `Watsonx_Challenge_2026` *(or your chosen token)* |
| **Passthrough Headers** | `ngrok-skip-browser-warning: true` |
| **CA Certificate** | *(leave blank — ngrok uses Let's Encrypt)* |

### Testing a tool in the ICA "Test Tool" UI

ICA's built-in tool tester requires the Bearer token in the **Passthrough Headers** box.
In the text area labelled *"Passthrough Headers (Optional)"*, enter:

```
Authorization: Bearer Watsonx_Challenge_2026
```

Then click **Run**. Every tool test requires this header.

> **Note:** The "Test Tool" button sends a bare connection test — this is different
> from a real agent call. When a real ICA/watsonx agent uses the tools, the token
> is sent automatically from the server registration.

---

## Registering with Bob (local)

For local use with the IBM Bob IDE on the **same machine**, use the stdio transport
(`server.py`) — no ngrok or token needed.

Update the paths in [`.bob/mcp.json`](.bob/mcp.json) to match your machine:

```json
{
  "mcpServers": {
    "feedstock-advisor": {
      "command": "C:\\Users\\<YOUR_USER>\\anaconda3\\envs\\feedstock_advisor\\python.exe",
      "args": [
        "C:\\path\\to\\feedstock_advisor_mcp\\server.py"
      ],
      "env": {
        "DATA_BACKEND": "csv",
        "LOG_LEVEL": "INFO"
      },
      "timeout": 30000
    }
  }
}
```

To find the correct Python path, run:
```cmd
conda activate feedstock_advisor
where python
```

---

## Available Tools (15)

### Helper Tools (7)

| Tool Name | Purpose |
|---|---|
| `list_available_crudes_tool` | All crude names grouped by region |
| `list_available_refineries_tool` | All refineries with id, name, location, capacity |
| `list_properties_and_yields_tool` | Canonical property and yield names with units |
| `find_matching_crude_tool` | Fuzzy-match a user-typed crude name (typo-tolerant) |
| `find_matching_property_tool` | Fuzzy-match a property/yield name (e.g. "sulphur" → `sulfur_content`) |
| `find_matching_refinery_tool` | Fuzzy-match a refinery name or location |
| `get_refinery_id_tool` | Exact name → refinery ID lookup |

### Forecasting Tool (1)

| Tool Name | Purpose |
|---|---|
| `forecast_tool_mcp` | Price / properties / yield forecast for a crude in a target month |

### Blending Tool (1)

| Tool Name | Purpose |
|---|---|
| `blend_simulator_tool_mcp` | Simulate blending ≥2 crudes; blended properties + product yields |

### Analysis Tools (6)

| Tool Name | Purpose |
|---|---|
| `constraint_checker_tool_mcp` | Check a blend against property constraints (sulfur, API, etc.) |
| `price_calculator_tool_mcp` | Total delivered cost of a crude blend for a given volume |
| `profitability_calculator_tool_mcp` | Gross profit, margin, ROI for processing a blend at a refinery |
| `optimizer_tool_mcp` | LP-based optimal blend (maximise yield/profit, minimise cost) |
| `get_high_yield_crudes_tool` | Rank crudes by product yield filtered by max sulfur |
| `get_market_context_tool` | Demand trend, price sentiment, BUY / HOLD / CAUTION signal |

---

## Configuration Reference

All settings can be overridden via environment variables.
Copy [`.env.example`](.env.example) to `.env` and edit it.

| Env Var | Default | Description |
|---|---|---|
| `MCP_API_KEY` | *(empty)* | Bearer token for HTTP server auth. **Required for ngrok.** Leave empty to disable auth (local testing only). |
| `MCP_HOST` | `127.0.0.1` | Bind address for HTTP server |
| `MCP_PORT` | `8000` | Port for HTTP server |
| `MCP_ALLOWED_HOSTS` | `*` | Allowed `Host` headers — `*` disables DNS-rebinding protection (safe with ngrok) |
| `DATA_BACKEND` | `csv` | Data source: `csv` \| `db` \| `api` |
| `DATE_MATCH_TOLERANCE_DAYS` | `45` | ±days window for nearest forecast date lookup |
| `FUZZY_MATCH_THRESHOLD` | `0.6` | Minimum fuzzy match score (0–1) |
| `DEFAULT_MAX_SULFUR` | `1.5` | Default sulfur cap for `get_high_yield_crudes` |
| `DEFAULT_TOP_N` | `5` | Default top-N results for `get_high_yield_crudes` |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `PRICE_DIESEL` | `120.0` | Reference diesel price USD/bbl (profitability calc) |
| `PRICE_GASOLINE` | `110.0` | Reference gasoline price USD/bbl |
| `PRICE_JET_FUEL` | `115.0` | Reference jet fuel price USD/bbl |
| `PRICE_FUEL_OIL` | `70.0` | Reference fuel oil price USD/bbl |
| `PRICE_LPG` | `60.0` | Reference LPG price USD/bbl |
| `PRICE_NAPHTHA` | `85.0` | Reference naphtha price USD/bbl |

---

## Testing

### Unit tests (all 15 tools)

```cmd
conda activate feedstock_advisor
pytest tests/test_tools.py -v
```

62 tests, ~2 seconds. No server or ngrok needed.

### Smoke-test the live HTTP server

With the server running, verify the endpoint responds:

```cmd
curl -s http://127.0.0.1:8000/mcp
```

Expected: `{"server":"feedstock-advisor","version":"1.28.1",...}`

### Smoke-test through ngrok

```cmd
curl -s https://<your-ngrok-id>.ngrok-free.app/mcp -H "ngrok-skip-browser-warning: true"
```

Expected: same JSON response.

---

## Agent Workflow Patterns

### Buy / Hold recommendation
```
find_matching_crude_tool("brent crude")
  → forecast_tool_mcp("Brent", "2026-06-01", metric="price")
  → forecast_tool_mcp("Brent", "2026-06-01", metric="properties")
  → get_market_context_tool("Diesel", "2026-06-01", "2026-06-30", crude_name="Brent")
```

### Optimal blend for maximum diesel yield
```
optimizer_tool_mcp("maximize_yield", "diesel",
                   constraints={"sulfur_content": {"max": 1.5}},
                   refinery_id="REF_001")
  → constraint_checker_tool_mcp(blend, proportions, {"sulfur_content": {"max": 1.5}})
  → profitability_calculator_tool_mcp(blend, proportions, 100000, "REF_001")
```

### High-yield crude ranking + profitability
```
get_high_yield_crudes_tool("2026-08-01", "REF_001", product="diesel", max_sulfur=1.5, top_n=5)
  → blend_simulator_tool_mcp([top1, top2], [0.6, 0.4], refinery_id="REF_001")
  → profitability_calculator_tool_mcp([top1, top2], [0.6, 0.4], 50000, "REF_001")
```

---

## Data Sources

All 18 CSV files are bundled in `data/` and loaded at server startup (~0.5 s).

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
| `refinery_configs.csv` | Detailed refinery unit configurations |
| `quality_specs.csv` | Product quality specifications |
| `regulatory_limits.csv` | Regulatory reference data |
| `transportation_costs.csv` | Origin–destination transport costs |
| `market_trends.csv` | Weekly product market trend data |
| `supply_demand.csv` | Crude supply/demand balance data |
| `crude_properties_delivered.csv` | Delivered crude property records |

---

*Feedstock Advisor MCP Server — built for the petrochemical trading industry.*


sample questions : 
What crude oils are available, grouped by region?
What is the forecasted price of WTI in June 2026?
Simulate a 60/40 WTI/Brent blend — properties and yields?
Which crude gives the highest diesel yield at Refinery A in August 2026 under 1.5% sulfur?
What is the diesel market sentiment April–May 2025? Buy or hold?