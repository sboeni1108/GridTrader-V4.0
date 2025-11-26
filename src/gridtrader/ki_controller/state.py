"""
KI-Controller Zustandsverwaltung

Verwaltet den aktuellen Zustand des Controllers und persistiert ihn.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any
from decimal import Decimal
from pathlib import Path
import json

from .config import VolatilityRegime


class ControllerStatus(str, Enum):
    """Status des Controllers"""
    STOPPED = "STOPPED"          # Controller gestoppt
    STARTING = "STARTING"        # Controller startet
    RUNNING = "RUNNING"          # Controller läuft normal
    PAUSED = "PAUSED"            # Controller pausiert (z.B. außerhalb Handelszeiten)
    ALERT_PENDING = "ALERT_PENDING"  # Wartet auf User-Bestätigung
    EMERGENCY = "EMERGENCY"      # Notfall-Modus (alles stoppen)
    ERROR = "ERROR"              # Fehler aufgetreten


@dataclass
class MarketState:
    """Aktueller Marktzustand für ein Symbol"""
    symbol: str
    current_price: Decimal = Decimal("0")
    bid: Decimal = Decimal("0")
    ask: Decimal = Decimal("0")
    spread_pct: float = 0.0
    volume_today: int = 0
    volume_1min: int = 0

    # Volatilität
    atr_5: float = 0.0       # ATR 5 Perioden
    atr_14: float = 0.0      # ATR 14 Perioden
    atr_50: float = 0.0      # ATR 50 Perioden
    volatility_regime: VolatilityRegime = VolatilityRegime.UNKNOWN

    # Kerzen-Daten (letzte Kerze)
    candle_open: Decimal = Decimal("0")
    candle_high: Decimal = Decimal("0")
    candle_low: Decimal = Decimal("0")
    candle_close: Decimal = Decimal("0")
    candle_range_pct: float = 0.0

    # Trend-Indikatoren
    price_change_1min: float = 0.0   # % Änderung letzte Minute
    price_change_5min: float = 0.0   # % Änderung letzte 5 Minuten
    price_change_15min: float = 0.0  # % Änderung letzte 15 Minuten

    # Timestamps
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'symbol': self.symbol,
            'current_price': str(self.current_price),
            'bid': str(self.bid),
            'ask': str(self.ask),
            'spread_pct': self.spread_pct,
            'volume_today': self.volume_today,
            'volume_1min': self.volume_1min,
            'atr_5': self.atr_5,
            'atr_14': self.atr_14,
            'atr_50': self.atr_50,
            'volatility_regime': self.volatility_regime.value,
            'candle_open': str(self.candle_open),
            'candle_high': str(self.candle_high),
            'candle_low': str(self.candle_low),
            'candle_close': str(self.candle_close),
            'candle_range_pct': self.candle_range_pct,
            'price_change_1min': self.price_change_1min,
            'price_change_5min': self.price_change_5min,
            'price_change_15min': self.price_change_15min,
            'last_update': self.last_update.isoformat() if self.last_update else None,
        }


@dataclass
class ActiveLevelInfo:
    """Information über ein aktiv gemanagtes Level"""
    level_id: str                    # Eindeutige ID des Levels
    scenario_name: str               # Name des Quell-Szenarios
    symbol: str
    side: str                        # "LONG" oder "SHORT"
    level_num: int
    entry_price: Decimal
    exit_price: Decimal
    shares: int

    # Status
    is_active: bool = True
    has_entry_order: bool = False
    has_exit_order: bool = False
    entry_filled: bool = False
    position_qty: int = 0

    # Controller-Tracking
    activated_at: Optional[datetime] = None
    score: float = 0.0               # Bewertungs-Score bei Aktivierung
    reason: str = ""                 # Grund für Aktivierung

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'level_id': self.level_id,
            'scenario_name': self.scenario_name,
            'symbol': self.symbol,
            'side': self.side,
            'level_num': self.level_num,
            'entry_price': str(self.entry_price),
            'exit_price': str(self.exit_price),
            'shares': self.shares,
            'is_active': self.is_active,
            'has_entry_order': self.has_entry_order,
            'has_exit_order': self.has_exit_order,
            'entry_filled': self.entry_filled,
            'position_qty': self.position_qty,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'score': self.score,
            'reason': self.reason,
        }


@dataclass
class DecisionRecord:
    """Aufzeichnung einer Entscheidung des Controllers"""
    timestamp: datetime
    decision_type: str  # "ACTIVATE", "DEACTIVATE", "STOP_TRADE", "CLOSE_POSITION", etc.
    symbol: str
    details: Dict[str, Any]
    reason: str
    market_state_snapshot: Optional[Dict[str, Any]] = None

    # Ausführung
    executed: bool = False
    execution_result: Optional[str] = None
    confirmed_by_user: Optional[bool] = None  # Nur im Alert-Modus relevant

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'decision_type': self.decision_type,
            'symbol': self.symbol,
            'details': self.details,
            'reason': self.reason,
            'market_state_snapshot': self.market_state_snapshot,
            'executed': self.executed,
            'execution_result': self.execution_result,
            'confirmed_by_user': self.confirmed_by_user,
        }


@dataclass
class PerformanceStats:
    """Performance-Statistiken des Controllers"""
    # Tages-Statistiken
    decisions_today: int = 0
    activations_today: int = 0
    deactivations_today: int = 0
    trades_stopped_today: int = 0
    positions_closed_today: int = 0

    # P&L (vom Controller verwaltete Trades)
    realized_pnl_today: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_commissions_today: Decimal = Decimal("0")

    # Erfolgsmetriken
    successful_predictions: int = 0
    failed_predictions: int = 0

    # Timing
    avg_decision_time_ms: float = 0.0
    last_decision_time: Optional[datetime] = None

    # Changes tracking (für Anti-Overtrading)
    changes_this_hour: int = 0
    hour_started: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'decisions_today': self.decisions_today,
            'activations_today': self.activations_today,
            'deactivations_today': self.deactivations_today,
            'trades_stopped_today': self.trades_stopped_today,
            'positions_closed_today': self.positions_closed_today,
            'realized_pnl_today': str(self.realized_pnl_today),
            'unrealized_pnl': str(self.unrealized_pnl),
            'total_commissions_today': str(self.total_commissions_today),
            'successful_predictions': self.successful_predictions,
            'failed_predictions': self.failed_predictions,
            'avg_decision_time_ms': self.avg_decision_time_ms,
            'last_decision_time': self.last_decision_time.isoformat() if self.last_decision_time else None,
            'changes_this_hour': self.changes_this_hour,
            'hour_started': self.hour_started.isoformat() if self.hour_started else None,
        }

    def record_change(self) -> None:
        """Registriert eine Änderung für Anti-Overtrading Tracking"""
        now = datetime.now()

        # Neue Stunde?
        if self.hour_started is None or now.hour != self.hour_started.hour:
            self.hour_started = now
            self.changes_this_hour = 1
        else:
            self.changes_this_hour += 1


@dataclass
class PendingAlert:
    """Ein Alert, der auf User-Bestätigung wartet"""
    alert_id: str
    created_at: datetime
    expires_at: datetime
    decision: DecisionRecord
    confirmed: Optional[bool] = None
    response_time: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'alert_id': self.alert_id,
            'created_at': self.created_at.isoformat(),
            'expires_at': self.expires_at.isoformat(),
            'decision': self.decision.to_dict(),
            'confirmed': self.confirmed,
            'response_time': self.response_time.isoformat() if self.response_time else None,
        }


@dataclass
class KIControllerState:
    """
    Haupt-Zustandsklasse des KI-Controllers

    Enthält alle Laufzeit-Informationen und wird periodisch persistiert.
    """

    # Controller-Status
    status: ControllerStatus = ControllerStatus.STOPPED
    status_message: str = ""
    last_heartbeat: Optional[datetime] = None

    # Marktzustände (pro Symbol)
    market_states: Dict[str, MarketState] = field(default_factory=dict)

    # Aktive Levels (vom Controller verwaltet)
    active_levels: Dict[str, ActiveLevelInfo] = field(default_factory=dict)

    # Entscheidungs-Historie (letzte N Entscheidungen)
    decision_history: List[DecisionRecord] = field(default_factory=list)
    max_history_size: int = 1000

    # Performance
    performance: PerformanceStats = field(default_factory=PerformanceStats)

    # Pending Alerts (im Alert-Modus)
    pending_alerts: Dict[str, PendingAlert] = field(default_factory=dict)

    # Session-Info
    session_start: Optional[datetime] = None
    session_id: str = ""

    # Flags
    is_market_hours: bool = False
    emergency_stop_triggered: bool = False
    soft_limit_warning: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für Persistierung"""
        return {
            'status': self.status.value,
            'status_message': self.status_message,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'market_states': {k: v.to_dict() for k, v in self.market_states.items()},
            'active_levels': {k: v.to_dict() for k, v in self.active_levels.items()},
            'decision_history': [d.to_dict() for d in self.decision_history[-100:]],  # Nur letzte 100
            'performance': self.performance.to_dict(),
            'pending_alerts': {k: v.to_dict() for k, v in self.pending_alerts.items()},
            'session_start': self.session_start.isoformat() if self.session_start else None,
            'session_id': self.session_id,
            'is_market_hours': self.is_market_hours,
            'emergency_stop_triggered': self.emergency_stop_triggered,
            'soft_limit_warning': self.soft_limit_warning,
        }

    def add_decision(self, decision: DecisionRecord) -> None:
        """Fügt eine Entscheidung zur Historie hinzu"""
        self.decision_history.append(decision)

        # Begrenze Historie-Größe
        if len(self.decision_history) > self.max_history_size:
            self.decision_history = self.decision_history[-self.max_history_size:]

        # Performance-Tracking
        self.performance.decisions_today += 1
        self.performance.last_decision_time = decision.timestamp

    def get_active_levels_for_symbol(self, symbol: str) -> List[ActiveLevelInfo]:
        """Gibt alle aktiven Levels für ein Symbol zurück"""
        return [
            level for level in self.active_levels.values()
            if level.symbol == symbol and level.is_active
        ]

    def get_active_long_count(self, symbol: str) -> int:
        """Zählt aktive Long-Levels für ein Symbol"""
        return len([
            l for l in self.get_active_levels_for_symbol(symbol)
            if l.side == "LONG"
        ])

    def get_active_short_count(self, symbol: str) -> int:
        """Zählt aktive Short-Levels für ein Symbol"""
        return len([
            l for l in self.get_active_levels_for_symbol(symbol)
            if l.side == "SHORT"
        ])

    def update_heartbeat(self) -> None:
        """Aktualisiert den Heartbeat"""
        self.last_heartbeat = datetime.now()

    def save(self, filepath: Optional[Path] = None) -> None:
        """Speichert State in JSON-Datei"""
        if filepath is None:
            filepath = Path.home() / ".gridtrader" / "ki_controller_state.json"

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: Optional[Path] = None) -> 'KIControllerState':
        """Lädt State aus JSON-Datei oder erstellt neuen"""
        if filepath is None:
            filepath = Path.home() / ".gridtrader" / "ki_controller_state.json"

        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Basis-State erstellen
                state = cls()
                state.status = ControllerStatus(data.get('status', 'STOPPED'))
                state.status_message = data.get('status_message', '')
                state.session_id = data.get('session_id', '')
                state.is_market_hours = data.get('is_market_hours', False)
                state.emergency_stop_triggered = data.get('emergency_stop_triggered', False)
                state.soft_limit_warning = data.get('soft_limit_warning', False)

                # Timestamps
                if data.get('last_heartbeat'):
                    state.last_heartbeat = datetime.fromisoformat(data['last_heartbeat'])
                if data.get('session_start'):
                    state.session_start = datetime.fromisoformat(data['session_start'])

                return state

            except Exception:
                # Bei Fehler: neuen State erstellen
                return cls()

        return cls()

    def reset_daily_stats(self) -> None:
        """Setzt tägliche Statistiken zurück"""
        self.performance = PerformanceStats()
        self.decision_history.clear()
        self.emergency_stop_triggered = False
        self.soft_limit_warning = False
