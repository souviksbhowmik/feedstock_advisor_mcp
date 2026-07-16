# New Helper Tools Specification

## Overview
These helper tools assist with parameter validation, name matching, and data discovery. They help the LLM extract and validate parameters correctly before calling main tools.

---

## 1. list_available_crudes

**Purpose:** Return list of all available crude oil names in the system

**Tool Name:** `list_available_crudes`

**Description:**
```
Get list of all available crude oil names in the system.

RETURNS: List of valid crude names that can be used in other tools.

PARAMETERS: None (no parameters required)

USAGE:
- Use when: Need to know what crude names are available
- Use when: User asks "what crudes do you have" or "list all crudes"
- Use before: Calling find_matching_crude to validate extracted names
- Use before: Any tool that requires crude_name parameter when unsure of exact name

RELATED TOOLS: find_matching_crude (to match extracted names against this list)
```

**Implementation:**
- Query data source for unique crude names
- Return sorted list
- Include both common names and aliases

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "crudes": [
      "Arab Light",
      "Bonny Light",
      "Brent",
      "Dubai",
      "Mars",
      "Urals",
      "WTI"
    ],
    "count": 7
  }
}
```

---

## 2. find_matching_crude

**Purpose:** Find best matching crude name using fuzzy matching

**Tool Name:** `find_matching_crude`

**Description:**
```
Find the best matching crude oil name from available crudes using fuzzy string matching.

RETURNS: Best matching crude name with confidence score.

PARAMETERS:
- extracted_name (string, required): Crude name extracted from user query
  Examples: "brent", "WTi", "West Texas", "dubai crude"
  Constraints: Any string, will be matched against available crudes
  
- threshold (float, optional): Minimum similarity score (0-1) to accept match
  Examples: 0.6, 0.8
  Default: 0.7
  Constraints: Must be between 0 and 1

LOOP REQUIREMENTS:
- Returns ONE best match per call
- For multiple extracted names, call once per name

USAGE:
- Use when: Extracted crude name might not be exact match
- Use when: User input has typos or variations (e.g., "WTi" instead of "WTI")
- Use after: Extracting crude name from query
- Use before: Calling tools that require exact crude_name

RELATED TOOLS: list_available_crudes (to get list of valid names first)
```

**Implementation:**
- Use fuzzy string matching (e.g., difflib.SequenceMatcher)
- Return best match with confidence score
- Return null if no match above threshold

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "extracted_name": "brent crude",
    "matched_name": "Brent",
    "confidence": 0.95,
    "alternatives": [
      {"name": "Bonny Light", "confidence": 0.45}
    ]
  }
}
```

---

## 3. list_available_refineries

**Purpose:** Return list of all available refinery IDs and names

**Tool Name:** `list_available_refineries`

**Description:**
```
Get list of all available refineries with their IDs and names.

RETURNS: List of refineries with ID and name mappings.

PARAMETERS: None (no parameters required)

USAGE:
- Use when: Need to know what refineries are available
- Use when: User asks about refineries
- Use before: Calling find_matching_refinery to validate extracted names
- Use before: Any tool that requires refinery_id parameter

RELATED TOOLS: find_matching_refinery (to match extracted names), get_refinery_id (to get ID from name)
```

**Implementation:**
- Query data source for refinery information
- Return list with ID and name pairs
- Include location if available

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "refineries": [
      {"id": "REF001", "name": "East Coast Refinery", "location": "US-East"},
      {"id": "REF002", "name": "Gulf Coast Refinery", "location": "US-Gulf"},
      {"id": "REF003", "name": "West Coast Refinery", "location": "US-West"}
    ],
    "count": 3
  }
}
```

---

## 4. find_matching_refinery

**Purpose:** Find best matching refinery using fuzzy matching

**Tool Name:** `find_matching_refinery`

**Description:**
```
Find the best matching refinery from available refineries using fuzzy string matching.

RETURNS: Best matching refinery with ID and confidence score.

PARAMETERS:
- extracted_name (string, required): Refinery name extracted from user query
  Examples: "east coast", "gulf refinery", "REF001"
  Constraints: Any string, will be matched against available refineries
  
- threshold (float, optional): Minimum similarity score (0-1) to accept match
  Examples: 0.6, 0.8
  Default: 0.7
  Constraints: Must be between 0 and 1

LOOP REQUIREMENTS:
- Returns ONE best match per call
- For multiple extracted names, call once per name

USAGE:
- Use when: Extracted refinery name might not be exact match
- Use when: User mentions refinery by location or partial name
- Use after: Extracting refinery name from query
- Use before: Calling tools that require refinery_id

RELATED TOOLS: list_available_refineries (to get list first), get_refinery_id (alternative for exact names)
```

**Implementation:**
- Match against both refinery IDs and names
- Use fuzzy string matching
- Return refinery ID and name

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "extracted_name": "east coast",
    "matched_refinery": {
      "id": "REF001",
      "name": "East Coast Refinery",
      "location": "US-East"
    },
    "confidence": 0.92,
    "alternatives": [
      {"id": "REF003", "name": "West Coast Refinery", "confidence": 0.45}
    ]
  }
}
```

---

## 5. get_refinery_id

**Purpose:** Get refinery ID from exact refinery name

**Tool Name:** `get_refinery_id`

**Description:**
```
Get refinery ID from exact refinery name (case-insensitive exact match).

RETURNS: Refinery ID for the given name.

PARAMETERS:
- refinery_name (string, required): Exact refinery name
  Examples: "East Coast Refinery", "Gulf Coast Refinery"
  Constraints: Must match available refinery name exactly (case-insensitive)

LOOP REQUIREMENTS:
- Returns ONE refinery ID per call
- For multiple names, call once per name

USAGE:
- Use when: Have exact refinery name and need ID
- Use when: Refinery name is clearly stated in query
- Don't use when: Name might have typos (use find_matching_refinery instead)

RELATED TOOLS: find_matching_refinery (for fuzzy matching), list_available_refineries (to see all options)
```

**Implementation:**
- Case-insensitive exact match
- Return refinery ID
- Error if no exact match found

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "refinery_name": "East Coast Refinery",
    "refinery_id": "REF001",
    "location": "US-East"
  }
}
```

---

## 6. list_properties_and_yields

**Purpose:** Get list of all available properties and yield types

**Tool Name:** `list_properties_and_yields`

**Description:**
```
Get list of all available crude properties and product yield types.

RETURNS: Lists of valid property names and yield types.

PARAMETERS: None (no parameters required)

USAGE:
- Use when: Need to know what properties/yields are available
- Use when: User asks about available metrics
- Use before: Calling find_matching_property to validate extracted names
- Use before: forecast_tool or blend_simulator when unsure of property names

RELATED TOOLS: find_matching_property (to match extracted names against these lists)
```

**Implementation:**
- Return list of crude properties (API gravity, sulfur content, etc.)
- Return list of product yields (gasoline, diesel, etc.)
- Include descriptions for each

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "properties": [
      {"name": "api_gravity", "description": "API gravity in degrees", "unit": "degrees"},
      {"name": "sulfur_content", "description": "Sulfur content", "unit": "percentage"},
      {"name": "viscosity", "description": "Kinematic viscosity", "unit": "cSt"},
      {"name": "density", "description": "Density at 15°C", "unit": "kg/m³"}
    ],
    "yields": [
      {"name": "gasoline", "description": "Gasoline yield", "unit": "percentage"},
      {"name": "diesel", "description": "Diesel yield", "unit": "percentage"},
      {"name": "jet_fuel", "description": "Jet fuel yield", "unit": "percentage"},
      {"name": "fuel_oil", "description": "Fuel oil yield", "unit": "percentage"}
    ]
  }
}
```

---

## 7. find_matching_property

**Purpose:** Find best matching property or yield name using fuzzy matching

**Tool Name:** `find_matching_property`

**Description:**
```
Find the best matching property or yield name using fuzzy string matching.

RETURNS: Best matching property/yield name with confidence score.

PARAMETERS:
- extracted_name (string, required): Property/yield name extracted from query
  Examples: "API", "sulphur", "diesel yield", "gasoline"
  Constraints: Any string, will be matched against available properties/yields
  
- category (string, optional): Category to search in
  Options: property, yield, both
  Default: both
  
- threshold (float, optional): Minimum similarity score (0-1) to accept match
  Examples: 0.6, 0.8
  Default: 0.7
  Constraints: Must be between 0 and 1

LOOP REQUIREMENTS:
- Returns ONE best match per call
- For multiple extracted names, call once per name

USAGE:
- Use when: Extracted property/yield name might not be exact match
- Use when: User uses variations (e.g., "API" for "api_gravity", "sulphur" for "sulfur_content")
- Use after: Extracting property/yield name from query
- Use before: Calling forecast_tool or blend_simulator

RELATED TOOLS: list_properties_and_yields (to get list of valid names first)
```

**Implementation:**
- Match against both properties and yields
- Use fuzzy string matching
- Handle common variations (API → api_gravity, sulphur → sulfur_content)

**Example Output:**
```json
{
  "status": "success",
  "data": {
    "extracted_name": "API",
    "matched_name": "api_gravity",
    "category": "property",
    "confidence": 0.88,
    "description": "API gravity in degrees",
    "alternatives": [
      {"name": "density", "category": "property", "confidence": 0.35}
    ]
  }
}
```

---

## Implementation Priority

### Phase 1 (HIGH Priority) - Name Validation
1. **list_available_crudes** - Essential for crude name validation
2. **find_matching_crude** - Critical for handling typos and variations

### Phase 2 (HIGH Priority) - Refinery Support
3. **list_available_refineries** - Needed for refinery-specific queries
4. **find_matching_refinery** - Handle refinery name variations
5. **get_refinery_id** - Quick ID lookup for exact names

### Phase 3 (MEDIUM Priority) - Property/Yield Support
6. **list_properties_and_yields** - Discover available metrics
7. **find_matching_property** - Handle property name variations

---

## Integration with Existing Tools

### Updated Tool Descriptions

**forecast_tool** should reference these helpers:
```
RELATED TOOLS: 
- list_available_crudes (to find valid crude names)
- find_matching_crude (to validate extracted crude name)
- list_properties_and_yields (to find valid metrics)
- find_matching_property (to validate extracted property name)
```

**blend_simulator** should reference:
```
RELATED TOOLS:
- list_available_crudes (to validate crude names in blend_components)
- find_matching_crude (to correct crude name typos)
```

**optimization_tool** should reference:
```
RELATED TOOLS:
- list_available_crudes (to validate available_crudes parameter)
- find_matching_crude (to correct crude names)
```

---

## Workflow Example

**Query:** "What will be the API gravity of brent crude in March 2025?"

**Improved Workflow with Helper Tools:**
1. Extract crude name: "brent crude"
2. Call `find_matching_crude(extracted_name="brent crude")`
   - Returns: `{"matched_name": "Brent", "confidence": 0.95}`
3. Extract property: "API gravity"
4. Call `find_matching_property(extracted_name="API gravity", category="property")`
   - Returns: `{"matched_name": "api_gravity", "confidence": 0.92}`
5. Call `forecast_tool(crude_name="Brent", target_date="2025-03-01", metric="properties")`
6. Extract api_gravity from result
7. Present answer

**Benefits:**
- Handles typos and variations automatically
- Validates parameters before main tool calls
- Reduces errors from invalid parameter values
- Provides better user experience

---

## Next Steps

1. Implement helper tools in order of priority
2. Update existing tool descriptions to reference helpers
3. Update parameter extraction logic to use helpers
4. Test with queries containing typos and variations
5. Measure improvement in parameter extraction accuracy