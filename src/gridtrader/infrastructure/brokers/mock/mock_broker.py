"""
Mock Broker Adapter für GridTrader V2.0
Simuliert einen Broker für Testing und Entwicklung
"""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Set
from uuid import UUID, uuid4
import random
import asyncio
from enum import Enum

from gridtrader.domain.models.order import (
    Order, Trade, Position, 
    OrderSide, OrderType, OrderStatus
)


class MockBrokerState(str, Enum):
    """Broker Verbindungsstatus"""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


class MockBroker:
    """
    Mock Broker für Testing
    Simuliert Order-Ausführung und Position-Tracking
    """
    
    def __init__(self, 
                 initial_balance: Decimal = Decimal("100000"),
                 commission: Decimal = Decimal("1.0"),
                 simulate_delays: bool = True):
        """
        Args:
            initial_balance: Start-Kapital
            commission: Kommission pro Trade
            simulate_delays: Simuliere realistische Verzögerungen
        """
        self.state = MockBrokerState.DISCONNECTED
        self.balance = initial_balance
        self.commission = commission
        self.simulate_delays = simulate_delays
        
        # Order & Trade Management
        self.orders: Dict[UUID, Order] = {}
        self.trades: List[Trade] = []
        self.positions: Dict[str, Position] = {}
        
        # Market Data (Mock-Preise)
        self.market_prices: Dict[str, Decimal] = {}
        self.bid_ask_spread = Decimal("0.01")
        
        # Execution Settings
        self.fill_probability = 0.95  # 95% Chance dass Limit-Order filled
        self.partial_fill_probability = 0.1  # 10% Chance auf Partial Fill
        
    async def connect(self) -> bool:
        """Verbindung simulieren"""
        self.state = MockBrokerState.CONNECTING
        
        if self.simulate_delays:
            await asyncio.sleep(0.5)  # Simuliere Verbindungsaufbau
            
        self.state = MockBrokerState.CONNECTED
        return True
    
    async def disconnect(self) -> None:
        """Verbindung trennen"""
        self.state = MockBrokerState.DISCONNECTED
    
    def is_connected(self) -> bool:
        """Prüfe Verbindungsstatus"""
        return self.state == MockBrokerState.CONNECTED
    
    def set_market_price(self, symbol: str, price: Decimal) -> None:
        """Setze Mock-Marktpreis für Symbol"""
        self.market_prices[symbol] = price
    
    def get_market_price(self, symbol: str) -> Optional[Decimal]:
        """Hole aktuellen Mock-Marktpreis"""
        # Wenn kein Preis gesetzt, generiere einen
        if symbol not in self.market_prices:
            self.market_prices[symbol] = Decimal("100.00")
        
        # Simuliere kleine Preisbewegungen
        current = self.market_prices[symbol]
        if random.random() > 0.5:
            change = Decimal(str(random.uniform(-0.5, 0.5)))
            self.market_prices[symbol] = max(Decimal("0.01"), current + change)
        
        return self.market_prices[symbol]
    
    async def place_order(self, order: Order) -> str:
        """
        Platziere Order
        Returns: Broker Order ID
        """
        if not self.is_connected():
            raise ConnectionError("Broker nicht verbunden")
        
        # Generiere Broker Order ID
        broker_order_id = f"MOCK_{uuid4().hex[:8]}"
        order.broker_order_id = broker_order_id
        order.status = OrderStatus.PENDING
        order.submitted_at = datetime.now()
        
        # Speichere Order
        self.orders[order.id] = order
        
        if self.simulate_delays:
            await asyncio.sleep(0.1)  # Simuliere Netzwerk-Latenz
        
        # Order akzeptiert
        order.status = OrderStatus.PLACED
        
        # Simuliere Ausführung
        asyncio.create_task(self._simulate_execution(order))
        
        return broker_order_id
    
    async def cancel_order(self, order_id: UUID) -> bool:
        """Storniere Order"""
        if order_id not in self.orders:
            return False
        
        order = self.orders[order_id]
        
        if order.status not in [OrderStatus.PLACED, OrderStatus.PARTIAL]:
            return False  # Kann nicht storniert werden
        
        if self.simulate_delays:
            await asyncio.sleep(0.05)
        
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = datetime.now()
        
        return True
    
    async def _simulate_execution(self, order: Order) -> None:
        """Simuliere Order-Ausführung"""
        if order.order_type == OrderType.MARKET:
            # Market Order - sofort ausführen
            await self._fill_order(order, self.get_market_price(order.symbol))
            
        elif order.order_type == OrderType.LIMIT:
            # Limit Order - warte auf Preis
            max_attempts = 10
            for _ in range(max_attempts):
                if order.status in [OrderStatus.CANCELLED, OrderStatus.FILLED]:
                    break
                    
                await asyncio.sleep(0.5)  # Check alle 500ms
                
                market_price = self.get_market_price(order.symbol)
                
                # Prüfe ob Limit-Preis erreicht
                if self._check_limit_price(order, market_price):
                    if random.random() < self.fill_probability:
                        await self._fill_order(order, order.limit_price)
                        break
    
    def _check_limit_price(self, order: Order, market_price: Decimal) -> bool:
        """Prüfe ob Limit-Preis erreicht wurde"""
        if order.side == OrderSide.BUY:
            return market_price <= order.limit_price
        else:  # SELL
            return market_price >= order.limit_price
    
    async def _fill_order(self, order: Order, fill_price: Decimal) -> None:
        """Führe Order aus und erstelle Trade"""
        # Partial Fill simulieren?
        fill_quantity = order.quantity
        if random.random() < self.partial_fill_probability:
            fill_quantity = order.quantity // 2
            order.status = OrderStatus.PARTIAL
        else:
            order.status = OrderStatus.FILLED
            order.filled_at = datetime.now()
        
        order.filled_quantity = fill_quantity
        order.remaining_quantity = order.quantity - fill_quantity
        order.avg_fill_price = fill_price
        order.commission = self.commission
        
        # Erstelle Trade
        trade = Trade(
            order_id=order.id,
            broker_trade_id=f"TRADE_{uuid4().hex[:8]}",
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
            commission=self.commission,
            executed_at=datetime.now()
        )
        
        self.trades.append(trade)
        
        # Update Position
        self._update_position(trade)
        
        # Update Balance
        if order.side == OrderSide.BUY:
            self.balance -= (fill_price * fill_quantity + self.commission)
        else:
            self.balance += (fill_price * fill_quantity - self.commission)
    
    def _update_position(self, trade: Trade) -> None:
        """Update oder erstelle Position basierend auf Trade"""
        symbol = trade.symbol
        
        if symbol not in self.positions:
            # Neue Position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=trade.side,
                quantity=trade.quantity,
                avg_entry_price=trade.price
            )
        else:
            # Update existierende Position
            pos = self.positions[symbol]
            
            if trade.side == pos.side:
                # Position erweitern
                total_cost = (pos.avg_entry_price * pos.quantity) + (trade.price * trade.quantity)
                pos.quantity += trade.quantity
                pos.avg_entry_price = total_cost / pos.quantity
            else:
                # Position reduzieren oder schließen
                if trade.quantity >= pos.quantity:
                    # Position geschlossen
                    realized_pnl = self._calculate_pnl(pos, trade.price)
                    pos.realized_pnl += realized_pnl
                    pos.quantity = 0
                else:
                    # Teilweise geschlossen
                    closed_qty = trade.quantity
                    realized_pnl = self._calculate_pnl_partial(pos, trade.price, closed_qty)
                    pos.realized_pnl += realized_pnl
                    pos.quantity -= closed_qty
    
    def _calculate_pnl(self, position: Position, exit_price: Decimal) -> Decimal:
        """Berechne P&L für Position"""
        if position.is_long():
            return (exit_price - position.avg_entry_price) * position.quantity
        else:
            return (position.avg_entry_price - exit_price) * position.quantity
    
    def _calculate_pnl_partial(self, position: Position, exit_price: Decimal, quantity: int) -> Decimal:
        """Berechne P&L für teilweise geschlossene Position"""
        if position.is_long():
            return (exit_price - position.avg_entry_price) * quantity
        else:
            return (position.avg_entry_price - exit_price) * quantity
    
    def get_account_summary(self) -> Dict:
        """Hole Account-Zusammenfassung"""
        total_unrealized_pnl = sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )
        total_realized_pnl = sum(
            pos.realized_pnl for pos in self.positions.values()
        )
        
        return {
            "balance": self.balance,
            "positions": len(self.positions),
            "open_orders": sum(1 for o in self.orders.values() if o.is_active()),
            "total_trades": len(self.trades),
            "unrealized_pnl": total_unrealized_pnl,
            "realized_pnl": total_realized_pnl,
            "total_pnl": total_unrealized_pnl + total_realized_pnl
        }
