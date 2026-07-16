# Smart Feedstock Assistant - Tools Reference

This document provides a comprehensive reference for all tools available in the Smart Feedstock Assistant system using LangChain function calling architecture.

## Table of Contents

1. [Overview](#overview)
2. [Tool Architecture](#tool-architecture)
3. [Available Tools](#available-tools)
   - [Forecasting Tools](#forecasting-tools)
   - [Helper Tools](#helper-tools)
   - [Blending Tools](#blending-tools)
   - [Analysis Tools](#analysis-tools)
4. [Tool Discovery System](#tool-discovery-system)
5. [Adding New Tools](#adding-new-tools)

---

## Overview

The Smart Feedstock Assistant uses **LangChain's native function calling** with automatic tool discovery. Each tool is a Python function decorated with `@tool` that the LLM can call directly to perform specific tasks.

### Key Features

- **🔄 Dynamic Discovery**: Tools are automatically discovered at runtime
- **🎯 Function Calling**: LLM natively calls tools (no text parsing)
- **📝 Self-Documenting**: Tool docstrings become LLM-visible descriptions
- **✅ Type Safety**: LangChain validates parameters automatically
- **🚀 Zero Configuration**: Add a tool, restart app - it's available!

### Current Tool Count

**Total: 13 Tools** across 4 modules

---

## Tool Architecture

### LangChain Tool Structure

```python
from langchain_core.tools import tool
from typing import Dict, Any

@tool
def tool_name(param1: str, param2: int = 10) -> Dict[str, Any]:
    """Tool description that LLM sees.
    
    Args:
        param1: Parameter description
        param2: Parameter description (default: 10)
    
    Returns:
        dict: Return value structure
    """
    # Implementation
    return {"result": "data", "status": "success"}
```

### Tool Modules

| Module | Purpose | Tools Count |
|--------|---------|-------------|
| `forecast_langchain.py` | Forecasting | 1 |
| `helpers_langchain.py` | Helper/Utility | 7 |
| `blend_simulator_langchain.py` | Blending | 1 |
| `analysis_langchain.py` | Analysis/Optimization | 4 |

---

## Available Tools

### Forecasting Tools

#### 1. forecast_tool

**File**: `src/tools/forecast_langchain.py`

**Purpose**: Forecast crude oil prices, properties, or yields for a SINGLE future month.

**Parameters**:
- `crude_name` (str, required): Name of crude oil (e.g., "Brent", "WTI", "Dubai")
- `target_date` (str, required): Target date in YYYY-MM-DD format (e.g., "2026-09-01")
- `metric` (str, optional): Type of forecast - "price", "properties", or "yield" (default: "price")
- `refinery_id` (str, optional): Refinery ID for yield forecasts (e.g., "REF001")

**Returns**:
```python
# For metric="price"
{
    "spot_price": float,
    "delivered_price": float,
    "confidence_interval": dict
}

# For metric="properties"
{
    "api_gravity": float,
    "sulfur_content": float,
    "viscosity": float,
    "pour_point": float,
    "tan": float
}

# For metric="yield"
{
    "diesel": float,
    "gasoline": float,
    "jet_fuel": float,
    "fuel_oil": float,
    "naphtha": float
}
```

**Example Usage**:
```python
# Get price forecast
result = forecast_tool(
    crude_name="Brent",
    target_date="2026-09-01",
    metric="price"
)

# Get property forecast
result = forecast_tool(
    crude_name="WTI",
    target_date="2026-10-01",
    metric="properties"
)
```

**Important Notes**:
- Returns data for ONE month only
- For multiple months, call multiple times
- Use `find_matching_crude` if unsure about crude name
- Use `list_available_refineries` to get refinery IDs

---

### Helper Tools

#### 2. find_matching_crude

**File**: `src/tools/helpers_langchain.py`

**Purpose**: Find the best matching crude oil name using fuzzy string matching (typo-tolerant).

**Parameters**:
- `crude_name` (str, required): Crude name to match (can have typos)
- `threshold` (float, optional): Minimum similarity score 0.0-1.0 (default: 0.6)

**Returns**:
```python
{
    "matched_name": str,        # Exact name from database
    "similarity_score": float,  # 0.0 to 1.0
    "alternatives": List[str]   # Other possible matches
}
```

**Example**:
```python
result = find_matching_crude(crude_name="brent crude")
# Returns: {"matched_name": "Brent", "similarity_score": 0.95, ...}
```

---

#### 3. find_matching_property

**File**: `src/tools/helpers_langchain.py`

**Purpose**: Find the best matching property name using fuzzy matching.

**Parameters**:
- `property_name` (str, required): Property name to match
- `threshold` (float, optional): Minimum similarity (default: 0.6)

**Returns**:
```python
{
    "matched_name": str,
    "similarity_score": float,
    "alternatives": List[str]
}
```

---

#### 4. find_matching_refinery

**File**: `src/tools/helpers_langchain.py`

**Purpose**: Find the best matching refinery using fuzzy matching.

**Parameters**:
- `refinery_name` (str, required): Refinery name to match
- `threshold` (float, optional): Minimum similarity (default: 0.6)

**Returns**:
```python
{
    "matched_name": str,
    "similarity_score": float,
    "alternatives": List[str]
}
```

---

#### 5. get_refinery_id

**File**: `src/tools/helpers_langchain.py`

**Purpose**: Get the refinery ID for a given refinery name (needed for yield forecasts).

**Parameters**:
- `refinery_name` (str, required): Exact refinery name

**Returns**:
```python
{
    "refinery_id": str,      # e.g., "REF001"
    "refinery_name": str,    # Confirmed name
    "location": str          # Refinery location
}
```

**Example**:
```python
result = get_refinery_id(refinery_name="Houston Refinery")
# Returns: {"refinery_id": "REF001", ...}
```

---

#### 6. list_available_crudes

**File**: `src/tools/helpers_langchain.py`

**Purpose**: List all available crude oils in the system.

**Parameters**: None

**Returns**:
```python
{
    "crudes": List[str],                    # All crude names
    "count": int,                           # Total count
    "categories": Dict[str, List[str]]      # Grouped by region/type
}
```

**Example**:
```python
result = list_available_crudes()
# Returns: {"crudes": ["Brent", "WTI", "Dubai", ...], "count": 10, ...}
```

---

#### 7. list_available_refineries

**File**: `src/tools/helpers_langchain.py`

**Purpose**: List all available refineries in the system.

**Parameters**: None

**Returns**:
```python
{
    "refineries": List[dict],  # List of refinery info
    "count": int               # Total count
}
```

---

#### 8. list_properties_and_yields

**File**: `src/tools/helpers_langchain.py`

**Purpose**: List all available crude properties and product yields.

**Parameters**: None

**Returns**:
```python
{
    "properties": List[str],              # e.g., ["api_gravity", "sulfur_content", ...]
    "yields": List[str],                  # e.g., ["diesel", "gasoline", ...]
    "property_descriptions": Dict[str, str]  # Human-readable descriptions
}
```

---

### Blending Tools

#### 9. blend_simulator_tool

**File**: `src/tools/blend_simulator_langchain.py`

**Purpose**: Simulate blending multiple crude oils and predict resulting properties and yields.

**Parameters**:
- `crude_names` (List[str], required): List of crude names to blend
- `proportions` (List[float], required): Proportions for each crude (must sum to 1.0)
- `refinery_id` (str, optional): Refinery ID for yield calculations

**Returns**:
```python
{
    "blend_properties": {
        "api_gravity": float,
        "sulfur_content": float,
        "viscosity": float,
        "pour_point": float,
        "tan": float
    },
    "product_yields": {
        "diesel": float,
        "gasoline": float,
        "jet_fuel": float,
        "fuel_oil": float,
        "naphtha": float
    },
    "blend_composition": List[dict],  # Details per crude
    "total_volume": float
}
```

**Example**:
```python
result = blend_simulator_tool(
    crude_names=["Brent", "WTI"],
    proportions=[0.6, 0.4]
)
```

**Important Notes**:
- Proportions must sum to 1.0
- Uses volume-weighted averaging for properties
- Requires refinery_id for yield calculations

---

### Analysis Tools

#### 10. optimizer_tool

**File**: `src/tools/analysis_langchain.py`

**Purpose**: Find the optimal crude oil blend to maximize/minimize an objective while satisfying constraints.

**Parameters**:
- `objective` (str, required): What to optimize - "maximize_yield", "minimize_cost", "maximize_profit"
- `target_product` (str, optional): Product to optimize (e.g., "diesel", "gasoline")
- `constraints` (dict, optional): Constraints to satisfy
- `available_crudes` (List[str], optional): Crudes to consider
- `refinery_id` (str, optional): Refinery for yield calculations

**Returns**:
```python
{
    "optimal_blend": {
        "crude_names": List[str],
        "proportions": List[float]
    },
    "objective_value": float,
    "blend_properties": dict,
    "product_yields": dict,
    "constraints_satisfied": bool
}
```

**Example**:
```python
result = optimizer_tool(
    objective="maximize_yield",
    target_product="diesel",
    constraints={"sulfur_content": {"max": 1.5}}
)
```

---

#### 11. constraint_checker_tool

**File**: `src/tools/analysis_langchain.py`

**Purpose**: Check if a crude oil blend satisfies specified constraints.

**Parameters**:
- `crude_names` (List[str], required): Crudes in the blend
- `proportions` (List[float], required): Proportions (must sum to 1.0)
- `constraints` (dict, required): Constraints to check

**Returns**:
```python
{
    "all_constraints_satisfied": bool,
    "constraint_results": List[dict],  # Per-constraint results
    "blend_properties": dict,
    "violations": List[dict]           # If any constraints violated
}
```

**Example**:
```python
result = constraint_checker_tool(
    crude_names=["Brent", "WTI"],
    proportions=[0.6, 0.4],
    constraints={
        "sulfur_content": {"max": 1.5},
        "api_gravity": {"min": 30, "max": 40}
    }
)
```

---

#### 12. price_calculator_tool

**File**: `src/tools/analysis_langchain.py`

**Purpose**: Calculate the total cost of a crude oil blend based on market prices.

**Parameters**:
- `crude_names` (List[str], required): Crudes in the blend
- `proportions` (List[float], required): Proportions (must sum to 1.0)
- `volume` (float, required): Total volume in barrels
- `target_date` (str, optional): Date for price lookup (YYYY-MM-DD)
- `refinery_id` (str, optional): Refinery for delivery costs

**Returns**:
```python
{
    "total_cost": float,           # Total cost in USD
    "cost_per_barrel": float,      # Average cost per barrel
    "breakdown": List[dict],       # Cost per crude
    "delivery_cost": float,        # If refinery specified
    "currency": str                # "USD"
}
```

**Example**:
```python
result = price_calculator_tool(
    crude_names=["Brent", "WTI"],
    proportions=[0.6, 0.4],
    volume=10000
)
```

---

#### 13. profitability_calculator_tool

**File**: `src/tools/analysis_langchain.py`

**Purpose**: Calculate the profitability of processing a crude oil blend.

**Parameters**:
- `crude_names` (List[str], required): Crudes in the blend
- `proportions` (List[float], required): Proportions (must sum to 1.0)
- `volume` (float, required): Volume in barrels
- `refinery_id` (str, required): Refinery ID for processing
- `target_date` (str, optional): Date for price lookup

**Returns**:
```python
{
    "total_revenue": float,        # Revenue from products
    "total_cost": float,           # Cost of crude + processing
    "gross_profit": float,         # Revenue - Cost
    "profit_margin": float,        # Percentage
    "roi": float,                  # Return on investment
    "product_revenues": dict,      # Revenue per product
    "cost_breakdown": dict         # Detailed costs
}
```

**Example**:
```python
result = profitability_calculator_tool(
    crude_names=["Brent"],
    proportions=[1.0],
    volume=10000,
    refinery_id="REF001"
)
```

---

## Tool Discovery System

### How It Works

The system uses **dynamic tool discovery** to automatically find and load all tools:

```python
# src/tools/discovery.py

def discover_langchain_tools() -> List[BaseTool]:
    """Automatically discover all @tool decorated functions."""
    
    tool_modules = [
        'src.tools.forecast_langchain',
        'src.tools.helpers_langchain',
        'src.tools.blend_simulator_langchain',
        'src.tools.analysis_langchain',
    ]
    
    tools = []
    for module_name in tool_modules:
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module):
            if isinstance(obj, BaseTool):
                tools.append(obj)
    
    return tools
```

### Usage in Application

```python
from src.tools.discovery import get_tools
from src.llm.function_calling import initialize_llm_with_tools

# Get all tools automatically
tools = get_tools()  # Returns 13 tools

# Bind to LLM
llm = initialize_llm_with_tools(tools, model="qwen3:8b")

# Use with LangGraph
from langgraph.prebuilt import ToolNode
tool_node = ToolNode(tools)
```

### Benefits

✅ **Zero Configuration**: No manual registration
✅ **Automatic**: Add tool → restart → available
✅ **Type Safe**: LangChain validates parameters
✅ **Self-Documenting**: Docstrings become descriptions
✅ **Extensible**: Easy to add new tools

---

## Adding New Tools

### Quick Guide

See **[ADDING_NEW_TOOLS.md](./ADDING_NEW_TOOLS.md)** for comprehensive instructions.

### Quick Steps

1. **Add to existing module** or create new one
2. **Use `@tool` decorator**:
```python
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> Dict[str, Any]:
    """Clear description of what the tool does."""
    return {"result": "data"}
```
3. **Restart application** - tool is automatically discovered!

### Requirements

- ✅ Use `@tool` decorator
- ✅ Synchronous function (use `asyncio.run()` for async operations)
- ✅ Return `Dict[str, Any]`
- ✅ Comprehensive docstring
- ✅ Error handling

---

## Tool Usage Patterns

### Pattern 1: Single Tool Call

```python
# User: "What is the price of Brent crude?"
# Agent calls: forecast_tool(crude_name="Brent", target_date="2026-05-01", metric="price")
```

### Pattern 2: Helper + Main Tool

```python
# User: "What is the price of brent crude?" (typo)
# Agent calls:
# 1. find_matching_crude(crude_name="brent crude")  # Returns "Brent"
# 2. forecast_tool(crude_name="Brent", ...)
```

### Pattern 3: Multi-Tool Analysis

```python
# User: "Is a 60-40 blend of Brent and WTI profitable?"
# Agent calls:
# 1. blend_simulator_tool(crude_names=["Brent", "WTI"], proportions=[0.6, 0.4])
# 2. price_calculator_tool(crude_names=["Brent", "WTI"], proportions=[0.6, 0.4], volume=10000)
# 3. profitability_calculator_tool(crude_names=["Brent", "WTI"], proportions=[0.6, 0.4], volume=10000, refinery_id="REF001")
```

### Pattern 4: Optimization Workflow

```python
# User: "Find the best blend to maximize diesel yield under 1.5% sulfur"
# Agent calls:
# 1. list_available_crudes()  # Get available crudes
# 2. optimizer_tool(objective="maximize_yield", target_product="diesel", constraints={"sulfur_content": {"max": 1.5}})
# 3. constraint_checker_tool(...)  # Verify constraints
```

---

## Tool Categories Summary

| Category | Tools | Primary Use Cases |
|----------|-------|-------------------|
| **Forecasting** | 1 tool | Price predictions, property forecasts, yield estimates |
| **Helpers** | 7 tools | Name matching, listing options, getting IDs |
| **Blending** | 1 tool | Simulate crude blends, predict properties |
| **Analysis** | 4 tools | Optimization, constraints, costs, profitability |

---

## Data Sources

Tools access data through the `CSVDataSource` class:

| Data File | Purpose | Used By |
|-----------|---------|---------|
| `crude_properties.csv` | Current crude properties | blend_simulator, helpers |
| `forecasted_crude_properties.csv` | Property forecasts | forecast_tool |
| `historical_prices.csv` | Historical prices | price_calculator |
| `forecasted_prices.csv` | Price forecasts | forecast_tool, price_calculator |
| `refinery_crude_yields.csv` | Yield data | forecast_tool, blend_simulator |
| `refineries.csv` | Refinery information | helpers |
| `delivery_costs.csv` | Transportation costs | price_calculator |

---

## Error Handling

All tools follow consistent error handling:

```python
try:
    # Tool logic
    return {"result": data, "status": "success"}
except ValueError as e:
    return {"error": f"Invalid parameters: {str(e)}", "status": "failure"}
except DataNotFoundError as e:
    return {"error": f"Data not available: {str(e)}", "status": "failure"}
except Exception as e:
    logger.error(f"Error: {str(e)}", exc_info=True)
    return {"error": str(e), "status": "failure"}
```

---

## Performance Considerations

- **Caching**: Data source uses caching to avoid repeated file reads
- **Async Operations**: Underlying tools use async for I/O operations
- **Shared Data Source**: Single data source instance shared across tools
- **Lazy Loading**: Tools only loaded when needed

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0 | 2026-04-14 | Updated for LangChain function calling architecture |
| 1.0 | 2026-04-10 | Initial version with old architecture |

---

**Last Updated**: 2026-04-14  
**Architecture**: LangChain Function Calling with Dynamic Discovery  
**Total Tools**: 13