"""
data_access
-----------
Data access layer for the Feedstock Advisor MCP Server.

Exports
-------
DataStore
    The concrete data store selected by DATA_BACKEND in config.py.
    Import this symbol everywhere instead of importing a concrete class
    directly — swapping backends requires only changing config.py.

Usage
-----
    from data_access import DataStore
    store = DataStore()
"""

from config import DATA_BACKEND

if DATA_BACKEND == "csv":
    from data_access.csv_provider import CsvDataStore as DataStore  # noqa: F401
elif DATA_BACKEND == "db":
    # Future: from data_access.db_provider import DbDataStore as DataStore
    raise NotImplementedError("DB backend is not yet implemented. Set DATA_BACKEND=csv.")
elif DATA_BACKEND == "api":
    # Future: from data_access.api_provider import ApiDataStore as DataStore
    raise NotImplementedError("API backend is not yet implemented. Set DATA_BACKEND=csv.")
else:
    raise ValueError(
        f"Unknown DATA_BACKEND='{DATA_BACKEND}'. Valid values: csv, db, api."
    )

__all__ = ["DataStore"]
