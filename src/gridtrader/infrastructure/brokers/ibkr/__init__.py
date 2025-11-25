"""
Shared IBKR Adapter - Singleton für eine gemeinsame Verbindung
"""
from typing import Optional
from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRBrokerAdapter

_shared_adapter: Optional[IBKRBrokerAdapter] = None

def set_shared_adapter(adapter: IBKRBrokerAdapter):
    """Setze den gemeinsamen Adapter"""
    global _shared_adapter
    _shared_adapter = adapter
    print("✅ Shared IBKR Adapter gesetzt")

def get_shared_adapter() -> Optional[IBKRBrokerAdapter]:
    """Hole den gemeinsamen Adapter"""
    return _shared_adapter

def clear_shared_adapter():
    """Lösche den gemeinsamen Adapter"""
    global _shared_adapter
    _shared_adapter = None
