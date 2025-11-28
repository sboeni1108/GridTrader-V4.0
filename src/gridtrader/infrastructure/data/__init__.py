"""
Data Infrastructure Module

Zentrales Datenmanagement für GridTrader.
"""

from .historical_data_manager import (
    HistoricalDataManager,
    DataCacheEntry,
    get_data_manager,
)

__all__ = [
    'HistoricalDataManager',
    'DataCacheEntry',
    'get_data_manager',
]
