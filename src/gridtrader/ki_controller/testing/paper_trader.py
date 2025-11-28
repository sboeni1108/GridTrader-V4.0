"""
Paper Trading Simulator

Simuliert Trading ohne echte Orders:
- Virtuelle Positionen und Trades
- Realistische Fill-Simulation
- P&L Tracking
- Slippage-Modellierung
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any, Callable
from threading import Lock
from collections import deque
import random
import json


class TradeDirection(str, Enum):
    """Handelsrichtung"""
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(str, Enum):
    """Order-Typ"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    """Order-Status"""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    """Position-Status"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PARTIAL = "PARTIAL"


@dataclass
class PaperOrder:
    """Eine simulierte Order"""
    order_id: str
    symbol: str
    direction: TradeDirection
    order_type: OrderType
    quantity: int
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None

    # Status
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    # Tracking
    level_id: Optional[str] = None
    commission: float = 0.0
    slippage: float = 0.0

    def to_dict(self) -> dict:
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'direction': self.direction.value,
            'order_type': self.order_type.value,
            'quantity': self.quantity,
            'limit_price': self.limit_price,
            'stop_price': self.stop_price,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'filled_price': self.filled_price,
            'created_at': self.created_at.isoformat(),
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'level_id': self.level_id,
            'commission': self.commission,
            'slippage': self.slippage,
        }


@dataclass
class PaperTrade:
    """Ein ausgeführter Paper Trade"""
    trade_id: str
    symbol: str
    direction: TradeDirection
    quantity: int
    entry_price: float
    entry_time: datetime

    # Exit
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None

    # P&L
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    commission_total: float = 0.0

    # Tracking
    level_id: Optional[str] = None
    entry_order_id: Optional[str] = None
    exit_order_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'trade_id': self.trade_id,
            'symbol': self.symbol,
            'direction': self.direction.value,
            'quantity': self.quantity,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat(),
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'commission_total': self.commission_total,
            'level_id': self.level_id,
        }

    def is_closed(self) -> bool:
        return self.exit_price is not None


@dataclass
class PaperPosition:
    """Eine simulierte Position"""
    symbol: str
    direction: TradeDirection
    quantity: int
    avg_entry_price: float

    # Status
    status: PositionStatus = PositionStatus.OPEN

    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_commission: float = 0.0

    # Timing
    opened_at: datetime = field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None

    # Tracking
    level_id: Optional[str] = None
    trade_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction.value,
            'quantity': self.quantity,
            'avg_entry_price': self.avg_entry_price,
            'status': self.status.value,
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'total_commission': self.total_commission,
            'opened_at': self.opened_at.isoformat(),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'level_id': self.level_id,
            'trade_ids': self.trade_ids,
        }

    def update_unrealized_pnl(self, current_price: float):
        """Aktualisiert unrealized P&L basierend auf aktuellem Preis"""
        if self.direction == TradeDirection.LONG:
            self.unrealized_pnl = (current_price - self.avg_entry_price) * self.quantity
        else:  # SHORT
            self.unrealized_pnl = (self.avg_entry_price - current_price) * self.quantity


@dataclass
class PaperTradeResult:
    """Ergebnis einer Trade-Aktion"""
    success: bool
    message: str
    order_id: Optional[str] = None
    trade_id: Optional[str] = None
    fill_price: Optional[float] = None
    fill_quantity: Optional[int] = None
    commission: float = 0.0

    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'message': self.message,
            'order_id': self.order_id,
            'trade_id': self.trade_id,
            'fill_price': self.fill_price,
            'fill_quantity': self.fill_quantity,
            'commission': self.commission,
        }


@dataclass
class PaperPortfolio:
    """Gesamtes Paper Portfolio"""
    starting_capital: float
    current_capital: float
    positions: Dict[str, PaperPosition] = field(default_factory=dict)

    # Statistiken
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    total_commission: float = 0.0

    # Peaks für Drawdown
    peak_capital: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    def to_dict(self) -> dict:
        return {
            'starting_capital': self.starting_capital,
            'current_capital': self.current_capital,
            'positions': {k: v.to_dict() for k, v in self.positions.items()},
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'total_realized_pnl': self.total_realized_pnl,
            'total_unrealized_pnl': self.total_unrealized_pnl,
            'total_commission': self.total_commission,
            'peak_capital': self.peak_capital,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'win_rate': self.get_win_rate(),
            'profit_factor': self.get_profit_factor(),
        }

    def get_win_rate(self) -> float:
        """Berechnet Win-Rate"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades * 100

    def get_profit_factor(self) -> float:
        """Berechnet Profit Factor"""
        # Vereinfacht: Gewinn / Verlust Verhältnis
        if self.losing_trades == 0:
            return float('inf') if self.winning_trades > 0 else 0.0
        return self.winning_trades / self.losing_trades if self.losing_trades > 0 else 0.0

    def get_total_equity(self) -> float:
        """Berechnet Gesamt-Eigenkapital"""
        return self.current_capital + self.total_unrealized_pnl


class PaperTrader:
    """
    Paper Trading Simulator.

    Simuliert Trading ohne echte Orders:
    - Realistische Fill-Simulation mit Slippage
    - P&L Tracking
    - Position Management
    - Commission-Berechnung
    """

    def __init__(
        self,
        starting_capital: float = 100000.0,
        commission_per_share: float = 0.005,
        min_commission: float = 1.0,
        slippage_pct: float = 0.01,  # 0.01% default slippage
        realistic_fills: bool = True,
    ):
        self._starting_capital = starting_capital
        self._commission_per_share = commission_per_share
        self._min_commission = min_commission
        self._slippage_pct = slippage_pct
        self._realistic_fills = realistic_fills

        # Portfolio
        self._portfolio = PaperPortfolio(
            starting_capital=starting_capital,
            current_capital=starting_capital,
            peak_capital=starting_capital,
        )

        # Orders & Trades
        self._pending_orders: Dict[str, PaperOrder] = {}
        self._filled_orders: deque = deque(maxlen=1000)
        self._trades: Dict[str, PaperTrade] = {}
        self._closed_trades: deque = deque(maxlen=1000)

        # Prices (simuliert)
        self._current_prices: Dict[str, float] = {}
        self._price_history: Dict[str, deque] = {}

        # State
        self._lock = Lock()
        self._order_counter = 0
        self._trade_counter = 0
        self._active = True

        # Callbacks
        self._on_fill: Optional[Callable[[PaperOrder], None]] = None
        self._on_trade_closed: Optional[Callable[[PaperTrade], None]] = None
        self._on_position_update: Optional[Callable[[PaperPosition], None]] = None

    # ==================== ORDER MANAGEMENT ====================

    def place_order(
        self,
        symbol: str,
        direction: TradeDirection,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        level_id: Optional[str] = None,
    ) -> PaperTradeResult:
        """
        Platziert eine Paper Order.

        Market Orders werden sofort gefüllt (wenn Preis verfügbar).
        Limit/Stop Orders werden in Queue gestellt.
        """
        with self._lock:
            if not self._active:
                return PaperTradeResult(False, "Paper Trader nicht aktiv")

            # Order ID generieren
            self._order_counter += 1
            order_id = f"PO-{self._order_counter:06d}"

            # Order erstellen
            order = PaperOrder(
                order_id=order_id,
                symbol=symbol,
                direction=direction,
                order_type=order_type,
                quantity=quantity,
                limit_price=limit_price,
                stop_price=stop_price,
                level_id=level_id,
            )

            # Market Order sofort ausführen
            if order_type == OrderType.MARKET:
                return self._execute_market_order(order)

            # Limit/Stop Orders in Queue
            self._pending_orders[order_id] = order
            return PaperTradeResult(
                success=True,
                message=f"Order {order_id} platziert",
                order_id=order_id,
            )

    def cancel_order(self, order_id: str) -> PaperTradeResult:
        """Storniert eine pending Order"""
        with self._lock:
            if order_id not in self._pending_orders:
                return PaperTradeResult(False, f"Order {order_id} nicht gefunden")

            order = self._pending_orders.pop(order_id)
            order.status = OrderStatus.CANCELLED
            self._filled_orders.append(order)

            return PaperTradeResult(
                success=True,
                message=f"Order {order_id} storniert",
                order_id=order_id,
            )

    def _execute_market_order(self, order: PaperOrder) -> PaperTradeResult:
        """Führt eine Market Order aus"""
        # Preis ermitteln
        current_price = self._current_prices.get(order.symbol)
        if current_price is None:
            order.status = OrderStatus.REJECTED
            return PaperTradeResult(False, f"Kein Preis für {order.symbol}")

        # Slippage anwenden
        fill_price = self._apply_slippage(current_price, order.direction)

        # Commission berechnen
        commission = self._calculate_commission(order.quantity)

        # Order füllen
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.filled_at = datetime.now()
        order.commission = commission
        order.slippage = abs(fill_price - current_price)

        self._filled_orders.append(order)

        # Position aktualisieren
        self._update_position(order)

        # Callback
        if self._on_fill:
            self._on_fill(order)

        return PaperTradeResult(
            success=True,
            message=f"Order {order.order_id} gefüllt bei {fill_price:.2f}",
            order_id=order.order_id,
            fill_price=fill_price,
            fill_quantity=order.quantity,
            commission=commission,
        )

    def _apply_slippage(self, price: float, direction: TradeDirection) -> float:
        """Wendet Slippage auf Preis an"""
        if not self._realistic_fills:
            return price

        # Zufällige Slippage zwischen 0 und max
        slippage_factor = random.uniform(0, self._slippage_pct / 100)

        # Slippage ist immer gegen den Trader
        if direction == TradeDirection.LONG:
            return price * (1 + slippage_factor)  # Höherer Kaufpreis
        else:
            return price * (1 - slippage_factor)  # Niedrigerer Verkaufspreis

    def _calculate_commission(self, quantity: int) -> float:
        """Berechnet Commission"""
        commission = quantity * self._commission_per_share
        return max(commission, self._min_commission)

    # ==================== POSITION MANAGEMENT ====================

    def _update_position(self, order: PaperOrder):
        """Aktualisiert Position basierend auf gefüllter Order"""
        symbol = order.symbol
        position = self._portfolio.positions.get(symbol)

        if position is None:
            # Neue Position eröffnen
            self._open_position(order)
        else:
            # Bestehende Position aktualisieren
            if position.direction == order.direction:
                # Position vergrößern
                self._add_to_position(position, order)
            else:
                # Position verkleinern oder schließen
                self._reduce_position(position, order)

    def _open_position(self, order: PaperOrder):
        """Eröffnet neue Position"""
        self._trade_counter += 1
        trade_id = f"PT-{self._trade_counter:06d}"

        # Trade erstellen
        trade = PaperTrade(
            trade_id=trade_id,
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.filled_quantity,
            entry_price=order.filled_price,
            entry_time=datetime.now(),
            level_id=order.level_id,
            entry_order_id=order.order_id,
            commission_total=order.commission,
        )
        self._trades[trade_id] = trade

        # Position erstellen
        position = PaperPosition(
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.filled_quantity,
            avg_entry_price=order.filled_price,
            level_id=order.level_id,
            total_commission=order.commission,
            trade_ids=[trade_id],
        )
        self._portfolio.positions[order.symbol] = position

        # Capital aktualisieren
        self._portfolio.current_capital -= order.commission
        self._portfolio.total_commission += order.commission

        if self._on_position_update:
            self._on_position_update(position)

    def _add_to_position(self, position: PaperPosition, order: PaperOrder):
        """Fügt zu bestehender Position hinzu"""
        # Neuen Durchschnittspreis berechnen
        total_value = (position.avg_entry_price * position.quantity +
                      order.filled_price * order.filled_quantity)
        new_quantity = position.quantity + order.filled_quantity
        position.avg_entry_price = total_value / new_quantity
        position.quantity = new_quantity
        position.total_commission += order.commission

        # Neuer Trade
        self._trade_counter += 1
        trade_id = f"PT-{self._trade_counter:06d}"
        trade = PaperTrade(
            trade_id=trade_id,
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.filled_quantity,
            entry_price=order.filled_price,
            entry_time=datetime.now(),
            level_id=order.level_id,
            entry_order_id=order.order_id,
            commission_total=order.commission,
        )
        self._trades[trade_id] = trade
        position.trade_ids.append(trade_id)

        # Capital aktualisieren
        self._portfolio.current_capital -= order.commission
        self._portfolio.total_commission += order.commission

        if self._on_position_update:
            self._on_position_update(position)

    def _reduce_position(self, position: PaperPosition, order: PaperOrder):
        """Reduziert oder schließt Position"""
        close_quantity = min(order.filled_quantity, position.quantity)

        # P&L berechnen
        if position.direction == TradeDirection.LONG:
            pnl = (order.filled_price - position.avg_entry_price) * close_quantity
        else:
            pnl = (position.avg_entry_price - order.filled_price) * close_quantity

        pnl -= order.commission  # Commission abziehen

        # Trade(s) schließen
        self._close_trades_for_position(position, close_quantity, order.filled_price, order.commission)

        # Position aktualisieren
        position.quantity -= close_quantity
        position.realized_pnl += pnl
        position.total_commission += order.commission

        # Portfolio aktualisieren
        self._portfolio.current_capital += pnl
        self._portfolio.total_realized_pnl += pnl
        self._portfolio.total_commission += order.commission
        self._portfolio.total_trades += 1

        if pnl > 0:
            self._portfolio.winning_trades += 1
        else:
            self._portfolio.losing_trades += 1

        # Drawdown prüfen
        self._update_drawdown()

        if position.quantity == 0:
            position.status = PositionStatus.CLOSED
            position.closed_at = datetime.now()
            del self._portfolio.positions[position.symbol]

        if self._on_position_update:
            self._on_position_update(position)

    def _close_trades_for_position(
        self,
        position: PaperPosition,
        close_quantity: int,
        exit_price: float,
        commission: float,
    ):
        """Schließt Trades für eine Position (FIFO)"""
        remaining = close_quantity
        commission_per_share = commission / close_quantity if close_quantity > 0 else 0

        for trade_id in list(position.trade_ids):
            if remaining <= 0:
                break

            trade = self._trades.get(trade_id)
            if trade is None or trade.is_closed():
                continue

            # Wie viel von diesem Trade schließen?
            trade_close = min(remaining, trade.quantity)

            # Trade schließen
            trade.exit_price = exit_price
            trade.exit_time = datetime.now()

            # P&L berechnen
            if trade.direction == TradeDirection.LONG:
                trade.realized_pnl = (exit_price - trade.entry_price) * trade_close
            else:
                trade.realized_pnl = (trade.entry_price - exit_price) * trade_close

            trade.commission_total += commission_per_share * trade_close
            trade.realized_pnl -= commission_per_share * trade_close

            # Trade archivieren
            self._closed_trades.append(trade)
            del self._trades[trade_id]
            position.trade_ids.remove(trade_id)

            if self._on_trade_closed:
                self._on_trade_closed(trade)

            remaining -= trade_close

    def _update_drawdown(self):
        """Aktualisiert Drawdown-Statistiken"""
        current_equity = self._portfolio.get_total_equity()

        if current_equity > self._portfolio.peak_capital:
            self._portfolio.peak_capital = current_equity

        drawdown = self._portfolio.peak_capital - current_equity
        drawdown_pct = (drawdown / self._portfolio.peak_capital * 100) if self._portfolio.peak_capital > 0 else 0

        if drawdown > self._portfolio.max_drawdown:
            self._portfolio.max_drawdown = drawdown
            self._portfolio.max_drawdown_pct = drawdown_pct

    # ==================== PRICE UPDATES ====================

    def update_price(self, symbol: str, price: float):
        """Aktualisiert den Preis für ein Symbol"""
        with self._lock:
            self._current_prices[symbol] = price

            # History speichern
            if symbol not in self._price_history:
                self._price_history[symbol] = deque(maxlen=1000)
            self._price_history[symbol].append((datetime.now(), price))

            # Unrealized P&L aktualisieren
            if symbol in self._portfolio.positions:
                position = self._portfolio.positions[symbol]
                position.update_unrealized_pnl(price)

            # Pending Orders prüfen
            self._check_pending_orders(symbol, price)

    def _check_pending_orders(self, symbol: str, price: float):
        """Prüft ob pending Orders ausgeführt werden können"""
        orders_to_execute = []

        for order_id, order in list(self._pending_orders.items()):
            if order.symbol != symbol:
                continue

            should_fill = False

            if order.order_type == OrderType.LIMIT:
                # Limit Order: Kaufen wenn Preis <= Limit, Verkaufen wenn Preis >= Limit
                if order.direction == TradeDirection.LONG and price <= order.limit_price:
                    should_fill = True
                elif order.direction == TradeDirection.SHORT and price >= order.limit_price:
                    should_fill = True

            elif order.order_type == OrderType.STOP:
                # Stop Order: Kaufen wenn Preis >= Stop, Verkaufen wenn Preis <= Stop
                if order.direction == TradeDirection.LONG and price >= order.stop_price:
                    should_fill = True
                elif order.direction == TradeDirection.SHORT and price <= order.stop_price:
                    should_fill = True

            if should_fill:
                orders_to_execute.append(order_id)

        # Orders ausführen
        for order_id in orders_to_execute:
            order = self._pending_orders.pop(order_id)
            order.order_type = OrderType.MARKET  # Konvertiere zu Market für Ausführung
            self._execute_market_order(order)

    # ==================== CLOSE POSITIONS ====================

    def close_position(
        self,
        symbol: str,
        quantity: Optional[int] = None,
        reason: str = "",
    ) -> PaperTradeResult:
        """Schließt eine Position (ganz oder teilweise)"""
        with self._lock:
            if symbol not in self._portfolio.positions:
                return PaperTradeResult(False, f"Keine Position für {symbol}")

            position = self._portfolio.positions[symbol]
            close_qty = quantity if quantity else position.quantity

            # Gegenorder platzieren
            opposite_direction = (
                TradeDirection.SHORT if position.direction == TradeDirection.LONG
                else TradeDirection.LONG
            )

        # Order außerhalb des Locks platzieren
        return self.place_order(
            symbol=symbol,
            direction=opposite_direction,
            quantity=close_qty,
            order_type=OrderType.MARKET,
            level_id=position.level_id,
        )

    def close_all_positions(self, reason: str = "") -> List[PaperTradeResult]:
        """Schließt alle offenen Positionen"""
        results = []
        symbols = list(self._portfolio.positions.keys())

        for symbol in symbols:
            result = self.close_position(symbol, reason=reason)
            results.append(result)

        return results

    # ==================== GETTERS ====================

    def get_portfolio(self) -> PaperPortfolio:
        """Gibt Portfolio zurück"""
        # Unrealized P&L aktualisieren
        self._portfolio.total_unrealized_pnl = sum(
            p.unrealized_pnl for p in self._portfolio.positions.values()
        )
        return self._portfolio

    def get_position(self, symbol: str) -> Optional[PaperPosition]:
        """Gibt Position für Symbol zurück"""
        return self._portfolio.positions.get(symbol)

    def get_all_positions(self) -> Dict[str, PaperPosition]:
        """Gibt alle offenen Positionen zurück"""
        return dict(self._portfolio.positions)

    def get_pending_orders(self) -> List[PaperOrder]:
        """Gibt alle pending Orders zurück"""
        return list(self._pending_orders.values())

    def get_open_trades(self) -> List[PaperTrade]:
        """Gibt alle offenen Trades zurück"""
        return list(self._trades.values())

    def get_closed_trades(self, limit: int = 100) -> List[PaperTrade]:
        """Gibt geschlossene Trades zurück"""
        return list(self._closed_trades)[-limit:]

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Gibt aktuellen Preis zurück"""
        return self._current_prices.get(symbol)

    # ==================== CALLBACKS ====================

    def set_on_fill(self, callback: Callable[[PaperOrder], None]):
        """Setzt Callback für Order-Fills"""
        self._on_fill = callback

    def set_on_trade_closed(self, callback: Callable[[PaperTrade], None]):
        """Setzt Callback für geschlossene Trades"""
        self._on_trade_closed = callback

    def set_on_position_update(self, callback: Callable[[PaperPosition], None]):
        """Setzt Callback für Position-Updates"""
        self._on_position_update = callback

    # ==================== STATE ====================

    def start(self):
        """Aktiviert Paper Trader"""
        self._active = True

    def stop(self):
        """Deaktiviert Paper Trader"""
        self._active = False

    def reset(self):
        """Setzt Paper Trader zurück"""
        with self._lock:
            self._portfolio = PaperPortfolio(
                starting_capital=self._starting_capital,
                current_capital=self._starting_capital,
                peak_capital=self._starting_capital,
            )
            self._pending_orders.clear()
            self._filled_orders.clear()
            self._trades.clear()
            self._closed_trades.clear()
            self._current_prices.clear()
            self._price_history.clear()
            self._order_counter = 0
            self._trade_counter = 0

    def to_dict(self) -> dict:
        """Serialisiert Paper Trader State"""
        return {
            'portfolio': self._portfolio.to_dict(),
            'pending_orders': [o.to_dict() for o in self._pending_orders.values()],
            'open_trades': [t.to_dict() for t in self._trades.values()],
            'closed_trades_count': len(self._closed_trades),
            'current_prices': dict(self._current_prices),
            'active': self._active,
        }

    def save_state(self, filepath: str):
        """Speichert State in Datei"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_summary(self) -> dict:
        """Gibt Zusammenfassung zurück"""
        portfolio = self.get_portfolio()
        return {
            'capital': {
                'starting': portfolio.starting_capital,
                'current': portfolio.current_capital,
                'total_equity': portfolio.get_total_equity(),
            },
            'pnl': {
                'realized': portfolio.total_realized_pnl,
                'unrealized': portfolio.total_unrealized_pnl,
                'total': portfolio.total_realized_pnl + portfolio.total_unrealized_pnl,
            },
            'trades': {
                'total': portfolio.total_trades,
                'winning': portfolio.winning_trades,
                'losing': portfolio.losing_trades,
                'win_rate': portfolio.get_win_rate(),
            },
            'risk': {
                'max_drawdown': portfolio.max_drawdown,
                'max_drawdown_pct': portfolio.max_drawdown_pct,
                'total_commission': portfolio.total_commission,
            },
            'positions': {
                'open': len(portfolio.positions),
                'symbols': list(portfolio.positions.keys()),
            },
        }
