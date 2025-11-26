"""
Risk Manager

Zentrale Risiko-Überwachung und -Steuerung:
- Hard Limits (absolut, sofortiger Stop)
- Soft Limits (Warnung, reduzierte Aktivität)
- Position Sizing
- Exposure Tracking
- Emergency Stop Logic
- Black Swan Detection
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple, Callable, Any
from collections import deque


class RiskLevel(str, Enum):
    """Risiko-Stufen"""
    NORMAL = "NORMAL"          # Alles im grünen Bereich
    ELEVATED = "ELEVATED"      # Erhöhte Aufmerksamkeit
    WARNING = "WARNING"        # Soft Limit erreicht
    CRITICAL = "CRITICAL"      # Nahe Hard Limit
    EMERGENCY = "EMERGENCY"    # Hard Limit überschritten


class LimitType(str, Enum):
    """Arten von Limits"""
    DAILY_LOSS = "DAILY_LOSS"
    TOTAL_EXPOSURE = "TOTAL_EXPOSURE"
    SYMBOL_EXPOSURE = "SYMBOL_EXPOSURE"
    POSITION_COUNT = "POSITION_COUNT"
    LEVEL_COUNT = "LEVEL_COUNT"
    DRAWDOWN = "DRAWDOWN"
    VOLATILITY = "VOLATILITY"


class RiskAction(str, Enum):
    """Aktionen bei Limit-Verletzung"""
    LOG_ONLY = "LOG_ONLY"              # Nur loggen
    REDUCE_ACTIVITY = "REDUCE_ACTIVITY"  # Weniger neue Trades
    STOP_NEW_TRADES = "STOP_NEW_TRADES"  # Keine neuen Trades
    CLOSE_LOSERS = "CLOSE_LOSERS"        # Verlierer schließen
    CLOSE_ALL = "CLOSE_ALL"              # Alles schließen
    EMERGENCY_STOP = "EMERGENCY_STOP"    # Sofort alles stoppen


@dataclass
class LimitConfig:
    """Konfiguration für ein einzelnes Limit"""
    limit_type: LimitType
    soft_value: float           # Soft Limit Wert
    hard_value: float           # Hard Limit Wert
    soft_action: RiskAction     # Aktion bei Soft Limit
    hard_action: RiskAction     # Aktion bei Hard Limit
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        return {
            'limit_type': self.limit_type.value,
            'soft_value': self.soft_value,
            'hard_value': self.hard_value,
            'soft_action': self.soft_action.value,
            'hard_action': self.hard_action.value,
            'enabled': self.enabled,
            'description': self.description,
        }


@dataclass
class RiskSnapshot:
    """Momentaufnahme der Risiko-Situation"""
    timestamp: datetime
    risk_level: RiskLevel

    # Finanzielle Metriken
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    daily_loss: Decimal = Decimal("0")

    # Exposure
    total_exposure: Decimal = Decimal("0")
    long_exposure: Decimal = Decimal("0")
    short_exposure: Decimal = Decimal("0")
    net_exposure: Decimal = Decimal("0")

    # Positionen
    position_count: int = 0
    active_level_count: int = 0

    # Limit-Status
    limits_breached: List[str] = field(default_factory=list)
    warnings_active: List[str] = field(default_factory=list)

    # Drawdown
    peak_pnl: Decimal = Decimal("0")
    current_drawdown: Decimal = Decimal("0")
    max_drawdown_today: Decimal = Decimal("0")

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'risk_level': self.risk_level.value,
            'realized_pnl': str(self.realized_pnl),
            'unrealized_pnl': str(self.unrealized_pnl),
            'total_pnl': str(self.total_pnl),
            'daily_loss': str(self.daily_loss),
            'total_exposure': str(self.total_exposure),
            'long_exposure': str(self.long_exposure),
            'short_exposure': str(self.short_exposure),
            'net_exposure': str(self.net_exposure),
            'position_count': self.position_count,
            'active_level_count': self.active_level_count,
            'limits_breached': self.limits_breached,
            'warnings_active': self.warnings_active,
            'current_drawdown': str(self.current_drawdown),
            'max_drawdown_today': str(self.max_drawdown_today),
        }


@dataclass
class RiskEvent:
    """Ein Risiko-Ereignis"""
    timestamp: datetime
    event_type: str              # "LIMIT_BREACH", "WARNING", "EMERGENCY", etc.
    limit_type: Optional[LimitType]
    current_value: float
    threshold_value: float
    action_taken: RiskAction
    message: str
    resolved: bool = False
    resolved_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'event_type': self.event_type,
            'limit_type': self.limit_type.value if self.limit_type else None,
            'current_value': self.current_value,
            'threshold_value': self.threshold_value,
            'action_taken': self.action_taken.value,
            'message': self.message,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
        }


class RiskManager:
    """
    Zentrale Risiko-Management Komponente.

    Überwacht alle Risiko-Metriken und löst Aktionen aus:
    - Täglicher Verlust
    - Gesamtexposure
    - Exposure pro Symbol
    - Anzahl Positionen/Levels
    - Drawdown
    - Plötzliche Preisbewegungen (Black Swan)
    """

    def __init__(
        self,
        max_daily_loss: Decimal = Decimal("500"),
        max_total_exposure: Decimal = Decimal("50000"),
        max_symbol_exposure: Decimal = Decimal("10000"),
        max_positions: int = 2000,
        max_active_levels: int = 20,
        soft_limit_ratio: float = 0.8,
        black_swan_threshold: float = 5.0,
    ):
        # Basis-Limits
        self._max_daily_loss = max_daily_loss
        self._max_total_exposure = max_total_exposure
        self._max_symbol_exposure = max_symbol_exposure
        self._max_positions = max_positions
        self._max_active_levels = max_active_levels
        self._soft_limit_ratio = soft_limit_ratio
        self._black_swan_threshold = black_swan_threshold

        # Limit-Konfigurationen
        self._limits: Dict[LimitType, LimitConfig] = self._create_default_limits()

        # State
        self._current_level = RiskLevel.NORMAL
        self._emergency_triggered = False
        self._emergency_reason: Optional[str] = None

        # Tracking
        self._peak_pnl = Decimal("0")
        self._max_drawdown = Decimal("0")
        self._events: deque = deque(maxlen=1000)
        self._snapshots: deque = deque(maxlen=100)

        # Price history für Black Swan Detection
        self._price_history: Dict[str, deque] = {}

        # Callbacks
        self._on_warning: Optional[Callable[[RiskEvent], None]] = None
        self._on_limit_breach: Optional[Callable[[RiskEvent], None]] = None
        self._on_emergency: Optional[Callable[[str], None]] = None

        # Per-Symbol Tracking
        self._symbol_exposure: Dict[str, Decimal] = {}

    def _create_default_limits(self) -> Dict[LimitType, LimitConfig]:
        """Erstellt Standard-Limit-Konfigurationen"""
        soft = self._soft_limit_ratio

        return {
            LimitType.DAILY_LOSS: LimitConfig(
                limit_type=LimitType.DAILY_LOSS,
                soft_value=float(self._max_daily_loss) * soft,
                hard_value=float(self._max_daily_loss),
                soft_action=RiskAction.REDUCE_ACTIVITY,
                hard_action=RiskAction.STOP_NEW_TRADES,
                description="Maximaler Tagesverlust",
            ),
            LimitType.TOTAL_EXPOSURE: LimitConfig(
                limit_type=LimitType.TOTAL_EXPOSURE,
                soft_value=float(self._max_total_exposure) * soft,
                hard_value=float(self._max_total_exposure),
                soft_action=RiskAction.LOG_ONLY,
                hard_action=RiskAction.STOP_NEW_TRADES,
                description="Maximales Gesamtexposure",
            ),
            LimitType.SYMBOL_EXPOSURE: LimitConfig(
                limit_type=LimitType.SYMBOL_EXPOSURE,
                soft_value=float(self._max_symbol_exposure) * soft,
                hard_value=float(self._max_symbol_exposure),
                soft_action=RiskAction.LOG_ONLY,
                hard_action=RiskAction.STOP_NEW_TRADES,
                description="Maximales Exposure pro Symbol",
            ),
            LimitType.POSITION_COUNT: LimitConfig(
                limit_type=LimitType.POSITION_COUNT,
                soft_value=self._max_positions * soft,
                hard_value=float(self._max_positions),
                soft_action=RiskAction.LOG_ONLY,
                hard_action=RiskAction.STOP_NEW_TRADES,
                description="Maximale Anzahl Positionen",
            ),
            LimitType.LEVEL_COUNT: LimitConfig(
                limit_type=LimitType.LEVEL_COUNT,
                soft_value=self._max_active_levels * soft,
                hard_value=float(self._max_active_levels),
                soft_action=RiskAction.LOG_ONLY,
                hard_action=RiskAction.STOP_NEW_TRADES,
                description="Maximale Anzahl aktiver Levels",
            ),
            LimitType.DRAWDOWN: LimitConfig(
                limit_type=LimitType.DRAWDOWN,
                soft_value=float(self._max_daily_loss) * 0.5,
                hard_value=float(self._max_daily_loss),
                soft_action=RiskAction.REDUCE_ACTIVITY,
                hard_action=RiskAction.CLOSE_LOSERS,
                description="Maximaler Drawdown",
            ),
        }

    # ==================== HAUPTMETHODEN ====================

    def check_risks(
        self,
        realized_pnl: Decimal,
        unrealized_pnl: Decimal,
        positions: Dict[str, Any],
        active_levels: int,
    ) -> RiskSnapshot:
        """
        Führt vollständige Risiko-Prüfung durch.

        Args:
            realized_pnl: Realisierter P&L heute
            unrealized_pnl: Unrealisierter P&L
            positions: Dict mit Position-Informationen
            active_levels: Anzahl aktiver Levels

        Returns:
            RiskSnapshot mit aktuellem Risiko-Status
        """
        now = datetime.now()
        total_pnl = realized_pnl + unrealized_pnl

        # Exposure berechnen
        long_exp, short_exp, total_exp = self._calculate_exposure(positions)
        net_exp = long_exp - short_exp

        # Drawdown aktualisieren
        if total_pnl > self._peak_pnl:
            self._peak_pnl = total_pnl

        current_drawdown = self._peak_pnl - total_pnl
        if current_drawdown > self._max_drawdown:
            self._max_drawdown = current_drawdown

        # Daily Loss
        daily_loss = Decimal("0")
        if total_pnl < 0:
            daily_loss = abs(total_pnl)

        # Snapshot erstellen
        snapshot = RiskSnapshot(
            timestamp=now,
            risk_level=RiskLevel.NORMAL,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_pnl=total_pnl,
            daily_loss=daily_loss,
            total_exposure=total_exp,
            long_exposure=long_exp,
            short_exposure=short_exp,
            net_exposure=net_exp,
            position_count=len(positions),
            active_level_count=active_levels,
            peak_pnl=self._peak_pnl,
            current_drawdown=current_drawdown,
            max_drawdown_today=self._max_drawdown,
        )

        # Limits prüfen
        self._check_all_limits(snapshot)

        # Risiko-Level bestimmen
        snapshot.risk_level = self._determine_risk_level(snapshot)
        self._current_level = snapshot.risk_level

        # Snapshot speichern
        self._snapshots.append(snapshot)

        return snapshot

    def can_open_new_trade(
        self,
        symbol: str,
        side: str,
        size: int,
        entry_price: float,
    ) -> Tuple[bool, str]:
        """
        Prüft ob ein neuer Trade eröffnet werden kann.

        Returns:
            (erlaubt, grund)
        """
        if self._emergency_triggered:
            return False, f"Emergency Stop aktiv: {self._emergency_reason}"

        if self._current_level == RiskLevel.EMERGENCY:
            return False, "Emergency Risk Level"

        if self._current_level == RiskLevel.CRITICAL:
            return False, "Kritisches Risiko-Level - keine neuen Trades"

        # Exposure prüfen
        trade_value = Decimal(str(size * entry_price))

        # Symbol-Exposure
        current_symbol_exp = self._symbol_exposure.get(symbol, Decimal("0"))
        new_symbol_exp = current_symbol_exp + trade_value

        limit = self._limits[LimitType.SYMBOL_EXPOSURE]
        if float(new_symbol_exp) > limit.hard_value:
            return False, f"Symbol-Exposure Limit überschritten ({new_symbol_exp})"

        # Gesamt-Exposure (vereinfacht)
        total_current = sum(self._symbol_exposure.values())
        new_total = total_current + trade_value

        limit = self._limits[LimitType.TOTAL_EXPOSURE]
        if float(new_total) > limit.hard_value:
            return False, f"Gesamt-Exposure Limit überschritten ({new_total})"

        return True, ""

    def record_price(self, symbol: str, price: float):
        """
        Zeichnet Preis für Black Swan Detection auf.
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=60)  # 60 Preise (1 Min bei 1s Updates)

        self._price_history[symbol].append((datetime.now(), price))

        # Black Swan Check
        self._check_black_swan(symbol)

    def trigger_emergency_stop(self, reason: str):
        """Löst Emergency Stop aus"""
        if self._emergency_triggered:
            return  # Bereits aktiv

        self._emergency_triggered = True
        self._emergency_reason = reason
        self._current_level = RiskLevel.EMERGENCY

        event = RiskEvent(
            timestamp=datetime.now(),
            event_type="EMERGENCY_STOP",
            limit_type=None,
            current_value=0,
            threshold_value=0,
            action_taken=RiskAction.EMERGENCY_STOP,
            message=f"Emergency Stop ausgelöst: {reason}",
        )
        self._events.append(event)

        if self._on_emergency:
            self._on_emergency(reason)

    def reset_emergency(self):
        """Setzt Emergency-Status zurück (nur manuell!)"""
        self._emergency_triggered = False
        self._emergency_reason = None
        self._current_level = RiskLevel.NORMAL

    def reset_daily(self):
        """Setzt tägliche Metriken zurück"""
        self._peak_pnl = Decimal("0")
        self._max_drawdown = Decimal("0")
        self._symbol_exposure.clear()

    # ==================== LIMIT CHECKS ====================

    def _check_all_limits(self, snapshot: RiskSnapshot):
        """Prüft alle konfigurierten Limits"""
        # Daily Loss
        self._check_limit(
            LimitType.DAILY_LOSS,
            float(snapshot.daily_loss),
            snapshot
        )

        # Total Exposure
        self._check_limit(
            LimitType.TOTAL_EXPOSURE,
            float(snapshot.total_exposure),
            snapshot
        )

        # Position Count
        self._check_limit(
            LimitType.POSITION_COUNT,
            float(snapshot.position_count),
            snapshot
        )

        # Level Count
        self._check_limit(
            LimitType.LEVEL_COUNT,
            float(snapshot.active_level_count),
            snapshot
        )

        # Drawdown
        self._check_limit(
            LimitType.DRAWDOWN,
            float(snapshot.current_drawdown),
            snapshot
        )

    def _check_limit(
        self,
        limit_type: LimitType,
        current_value: float,
        snapshot: RiskSnapshot
    ):
        """Prüft ein einzelnes Limit"""
        config = self._limits.get(limit_type)
        if not config or not config.enabled:
            return

        # Hard Limit Check
        if current_value >= config.hard_value:
            snapshot.limits_breached.append(limit_type.value)
            self._handle_limit_breach(config, current_value, is_hard=True)

        # Soft Limit Check
        elif current_value >= config.soft_value:
            snapshot.warnings_active.append(limit_type.value)
            self._handle_limit_breach(config, current_value, is_hard=False)

    def _handle_limit_breach(
        self,
        config: LimitConfig,
        current_value: float,
        is_hard: bool
    ):
        """Behandelt eine Limit-Verletzung"""
        threshold = config.hard_value if is_hard else config.soft_value
        action = config.hard_action if is_hard else config.soft_action
        event_type = "HARD_LIMIT_BREACH" if is_hard else "SOFT_LIMIT_WARNING"

        event = RiskEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            limit_type=config.limit_type,
            current_value=current_value,
            threshold_value=threshold,
            action_taken=action,
            message=f"{config.description}: {current_value:.2f} {'>' if is_hard else '>='} {threshold:.2f}",
        )
        self._events.append(event)

        # Callback auslösen
        if is_hard and self._on_limit_breach:
            self._on_limit_breach(event)
        elif not is_hard and self._on_warning:
            self._on_warning(event)

        # Emergency bei bestimmten Aktionen
        if action == RiskAction.EMERGENCY_STOP:
            self.trigger_emergency_stop(event.message)

    def _check_black_swan(self, symbol: str):
        """Prüft auf plötzliche extreme Preisbewegungen"""
        history = self._price_history.get(symbol)
        if not history or len(history) < 10:
            return

        prices = [p for _, p in history]
        recent_price = prices[-1]
        price_1min_ago = prices[0] if len(prices) >= 60 else prices[0]

        if price_1min_ago <= 0:
            return

        change_pct = abs(recent_price - price_1min_ago) / price_1min_ago * 100

        if change_pct >= self._black_swan_threshold:
            self.trigger_emergency_stop(
                f"Black Swan Detection: {symbol} bewegte sich {change_pct:.1f}% in 1 Minute"
            )

    # ==================== HELPERS ====================

    def _calculate_exposure(
        self,
        positions: Dict[str, Any]
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """Berechnet Long, Short und Total Exposure"""
        long_exp = Decimal("0")
        short_exp = Decimal("0")

        for symbol, pos in positions.items():
            if isinstance(pos, dict):
                size = pos.get('size', 0)
                price = pos.get('price', 0)
                value = Decimal(str(abs(size * price)))

                if size > 0:
                    long_exp += value
                else:
                    short_exp += value

                self._symbol_exposure[symbol] = value

        return long_exp, short_exp, long_exp + short_exp

    def _determine_risk_level(self, snapshot: RiskSnapshot) -> RiskLevel:
        """Bestimmt das Gesamt-Risiko-Level"""
        if self._emergency_triggered:
            return RiskLevel.EMERGENCY

        if snapshot.limits_breached:
            return RiskLevel.CRITICAL

        if len(snapshot.warnings_active) >= 3:
            return RiskLevel.WARNING

        if snapshot.warnings_active:
            return RiskLevel.ELEVATED

        return RiskLevel.NORMAL

    # ==================== CALLBACKS & CONFIG ====================

    def set_on_warning(self, callback: Callable[[RiskEvent], None]):
        """Setzt Callback für Warnungen"""
        self._on_warning = callback

    def set_on_limit_breach(self, callback: Callable[[RiskEvent], None]):
        """Setzt Callback für Limit-Verletzungen"""
        self._on_limit_breach = callback

    def set_on_emergency(self, callback: Callable[[str], None]):
        """Setzt Callback für Emergency Stop"""
        self._on_emergency = callback

    def update_limit(self, limit_type: LimitType, soft: float, hard: float):
        """Aktualisiert ein Limit"""
        if limit_type in self._limits:
            self._limits[limit_type].soft_value = soft
            self._limits[limit_type].hard_value = hard

    def get_current_level(self) -> RiskLevel:
        """Gibt aktuelles Risiko-Level zurück"""
        return self._current_level

    def get_latest_snapshot(self) -> Optional[RiskSnapshot]:
        """Gibt letzten Snapshot zurück"""
        return self._snapshots[-1] if self._snapshots else None

    def get_recent_events(self, count: int = 10) -> List[RiskEvent]:
        """Gibt letzte Ereignisse zurück"""
        return list(self._events)[-count:]

    def is_emergency(self) -> bool:
        """Prüft ob Emergency aktiv"""
        return self._emergency_triggered

    def get_emergency_reason(self) -> Optional[str]:
        """Gibt Emergency-Grund zurück"""
        return self._emergency_reason
