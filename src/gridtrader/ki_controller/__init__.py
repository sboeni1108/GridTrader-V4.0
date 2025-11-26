"""
KI-Trading-Controller für GridTrader V4.0

Ein adaptiver, regelbasierter Trading-Controller der:
- Echtzeit-Analyse von Kursverlauf, Kerzengröße und Volumen durchführt
- Dynamisch Levels aus bestehenden Szenarien aktiviert/deaktiviert
- Historische Muster mit aktueller Situation vergleicht
- Vorausdenkt und antizipiert basierend auf Patterns

Architektur:
- Läuft als separater Worker-Thread
- Kommuniziert über definierte API mit dem Trading-Bot
- Vollständig konfigurierbar mit Default-Werten
"""

from .config import KIControllerConfig, ControllerMode, RiskLimits, VolatilityRegime
from .state import KIControllerState, ControllerStatus, MarketState, ActiveLevelInfo
from .controller_thread import KIControllerThread
from .controller_api import ControllerAPI, TradingBotAPIAdapter
from .level_pool import LevelPool, PoolLevel, LevelPoolStatus

# Testing Module
from .testing import (
    PaperTrader, PaperPosition, PaperTrade, PaperPortfolio,
    PerformanceTracker, PerformanceMetrics, TradeRecord, DecisionRecord,
)

# Risk & Execution Module
from .risk import RiskManager, RiskLevel, Watchdog, WatchdogStatus
from .execution import ExecutionManager, CommandType, ExecutionPriority

__all__ = [
    # Config
    'KIControllerConfig',
    'ControllerMode',
    'RiskLimits',
    'VolatilityRegime',
    # State
    'KIControllerState',
    'ControllerStatus',
    'MarketState',
    'ActiveLevelInfo',
    # Controller
    'KIControllerThread',
    # API
    'ControllerAPI',
    'TradingBotAPIAdapter',
    # Level Pool
    'LevelPool',
    'PoolLevel',
    'LevelPoolStatus',
    # Testing
    'PaperTrader',
    'PaperPosition',
    'PaperTrade',
    'PaperPortfolio',
    'PerformanceTracker',
    'PerformanceMetrics',
    'TradeRecord',
    'DecisionRecord',
    # Risk
    'RiskManager',
    'RiskLevel',
    'Watchdog',
    'WatchdogStatus',
    # Execution
    'ExecutionManager',
    'CommandType',
    'ExecutionPriority',
]

__version__ = '1.0.0'
