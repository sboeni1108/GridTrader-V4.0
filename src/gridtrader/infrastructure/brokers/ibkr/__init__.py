"""
IBKR Infrastructure Module

Enthält:
- IBKRBrokerAdapter: Legacy Adapter (wird schrittweise ersetzt)
- IBKRService: Neuer Service mit dediziertem Thread (EMPFOHLEN)
- SharedIBKRConnection: Verbindungsmanagement
"""
from typing import Optional
from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRBrokerAdapter, IBKRConfig

# Legacy Shared Adapter (für Rückwärtskompatibilität)
_shared_adapter: Optional[IBKRBrokerAdapter] = None

def set_shared_adapter(adapter: IBKRBrokerAdapter):
    """Setze den gemeinsamen Adapter (Legacy)"""
    global _shared_adapter
    _shared_adapter = adapter
    print("✅ Shared IBKR Adapter gesetzt")

def get_shared_adapter() -> Optional[IBKRBrokerAdapter]:
    """Hole den gemeinsamen Adapter (Legacy)"""
    return _shared_adapter

def clear_shared_adapter():
    """Lösche den gemeinsamen Adapter (Legacy)"""
    global _shared_adapter
    _shared_adapter = None


# Neuer IBKRService Export
from gridtrader.infrastructure.brokers.ibkr.ibkr_service import (
    IBKRService,
    IBKRServiceSignals,
    get_ibkr_service,
    stop_ibkr_service,
)

__all__ = [
    # Legacy
    'IBKRBrokerAdapter',
    'IBKRConfig',
    'set_shared_adapter',
    'get_shared_adapter',
    'clear_shared_adapter',
    # Neu (empfohlen)
    'IBKRService',
    'IBKRServiceSignals',
    'get_ibkr_service',
    'stop_ibkr_service',
]
