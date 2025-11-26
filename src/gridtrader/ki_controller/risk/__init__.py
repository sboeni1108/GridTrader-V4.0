"""
KI-Controller Risk Management Module

Enthält:
- Risk Manager: Hard/Soft Limits, Emergency Stop, Black Swan Detection
- Watchdog: Fail-Safe Überwachung, Heartbeat, Health Checks
"""

from .risk_manager import (
    RiskManager,
    RiskSnapshot,
    RiskEvent,
    RiskLevel,
    RiskAction,
    LimitType,
    LimitConfig,
)

from .watchdog import (
    Watchdog,
    WatchdogStatus,
    WatchdogState,
    HealthStatus,
    HealthCheckResult,
    create_connection_check,
    create_memory_check,
    create_data_freshness_check,
)

__all__ = [
    # Risk Manager
    'RiskManager',
    'RiskSnapshot',
    'RiskEvent',
    'RiskLevel',
    'RiskAction',
    'LimitType',
    'LimitConfig',
    # Watchdog
    'Watchdog',
    'WatchdogStatus',
    'WatchdogState',
    'HealthStatus',
    'HealthCheckResult',
    'create_connection_check',
    'create_memory_check',
    'create_data_freshness_check',
]
