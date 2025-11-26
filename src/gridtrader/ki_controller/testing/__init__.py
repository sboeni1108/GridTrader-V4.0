"""
Testing Module für KI-Controller

Enthält:
- Paper Trading Simulator
- Performance Tracker
- Backtesting Utilities
"""

from .paper_trader import (
    PaperTrader,
    PaperPosition,
    PaperTrade,
    PaperTradeResult,
    PaperPortfolio,
)

from .performance_tracker import (
    PerformanceTracker,
    PerformanceMetrics,
    TradeRecord,
    DecisionRecord,
)

__all__ = [
    # Paper Trading
    'PaperTrader',
    'PaperPosition',
    'PaperTrade',
    'PaperTradeResult',
    'PaperPortfolio',
    # Performance Tracking
    'PerformanceTracker',
    'PerformanceMetrics',
    'TradeRecord',
    'DecisionRecord',
]
