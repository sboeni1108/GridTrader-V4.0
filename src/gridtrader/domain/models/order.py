"""
Order Domain Models für GridTrader V2.0
Verwaltet alle Order-bezogenen Entitäten
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


class OrderSide(str, Enum):
    """Order-Seite"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order-Typ"""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, Enum):
    """Order-Status"""
    NEW = "NEW"              # Neu erstellt, noch nicht gesendet
    PENDING = "PENDING"      # An Broker gesendet
    PLACED = "PLACED"        # Vom Broker akzeptiert
    PARTIAL = "PARTIAL"      # Teilweise ausgeführt
    FILLED = "FILLED"        # Vollständig ausgeführt
    CANCELLED = "CANCELLED"  # Storniert
    REJECTED = "REJECTED"    # Abgelehnt
    EXPIRED = "EXPIRED"      # Abgelaufen


class Order(BaseModel):
    """
    Repräsentiert eine Trading-Order
    """
    model_config = ConfigDict(from_attributes=True)
    
    # Identifikation
    id: UUID = Field(default_factory=uuid4)
    broker_order_id: Optional[str] = None
    cycle_id: Optional[UUID] = None
    level_index: Optional[int] = None
    
    # Order-Details
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int = Field(gt=0)
    
    # Preise
    limit_price: Optional[Decimal] = Field(default=None, gt=0)
    stop_price: Optional[Decimal] = Field(default=None, gt=0)
    
    # Status
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: int = Field(default=0, ge=0)
    remaining_quantity: int = Field(default=0, ge=0)
    
    # Execution Details
    avg_fill_price: Optional[Decimal] = None
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    
    # Metadata
    tags: dict = Field(default_factory=dict)
    
    def is_complete(self) -> bool:
        """Prüft ob Order komplett ausgeführt"""
        return self.status == OrderStatus.FILLED
    
    def is_active(self) -> bool:
        """Prüft ob Order aktiv ist"""
        return self.status in [OrderStatus.NEW, OrderStatus.PENDING, 
                              OrderStatus.PLACED, OrderStatus.PARTIAL]
    
    def can_cancel(self) -> bool:
        """Prüft ob Order storniert werden kann"""
        return self.status in [OrderStatus.PENDING, OrderStatus.PLACED, 
                              OrderStatus.PARTIAL]
    
    def calculate_remaining(self) -> int:
        """Berechnet verbleibende Menge"""
        return max(0, self.quantity - self.filled_quantity)


class Trade(BaseModel):
    """
    Repräsentiert eine ausgeführte Transaktion
    """
    model_config = ConfigDict(from_attributes=True)
    
    # Identifikation
    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    broker_trade_id: Optional[str] = None
    
    # Trade-Details
    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    
    # Kosten
    commission: Decimal = Field(default=Decimal("0"), ge=0)
    fees: Decimal = Field(default=Decimal("0"), ge=0)
    
    # P&L
    realized_pnl: Optional[Decimal] = None
    
    # Timestamps
    executed_at: datetime = Field(default_factory=datetime.now)
    settled_at: Optional[datetime] = None
    
    # Metadata
    exchange: Optional[str] = None
    tags: dict = Field(default_factory=dict)
    
    def get_total_cost(self) -> Decimal:
        """Berechnet Gesamtkosten inkl. Gebühren"""
        base_cost = self.quantity * self.price
        if self.side == OrderSide.BUY:
            return base_cost + self.commission + self.fees
        else:
            return base_cost - self.commission - self.fees
    
    def get_net_proceeds(self) -> Decimal:
        """Berechnet Netto-Erlös"""
        if self.side == OrderSide.SELL:
            return (self.quantity * self.price) - self.commission - self.fees
        return Decimal("0")


class Position(BaseModel):
    """
    Repräsentiert eine offene Position
    """
    model_config = ConfigDict(from_attributes=True)
    
    # Identifikation
    symbol: str
    cycle_id: Optional[UUID] = None
    
    # Position Details
    side: OrderSide  # LONG=BUY, SHORT=SELL initial
    quantity: int = Field(default=0)
    
    # Preise
    avg_entry_price: Decimal = Field(default=Decimal("0"), ge=0)
    current_price: Optional[Decimal] = Field(default=None, gt=0)
    
    # P&L
    realized_pnl: Decimal = Field(default=Decimal("0"))
    unrealized_pnl: Decimal = Field(default=Decimal("0"))
    
    # Kosten
    total_commission: Decimal = Field(default=Decimal("0"), ge=0)
    
    # Timestamps
    opened_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None
    
    def is_long(self) -> bool:
        """Prüft ob Long-Position"""
        return self.side == OrderSide.BUY
    
    def is_short(self) -> bool:
        """Prüft ob Short-Position"""
        return self.side == OrderSide.SELL
    
    def is_open(self) -> bool:
        """Prüft ob Position offen"""
        return self.quantity > 0
    
    def calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Berechnet unrealisierte P&L"""
        if not self.is_open() or not current_price:
            return Decimal("0")
        
        if self.is_long():
            return (current_price - self.avg_entry_price) * self.quantity
        else:
            return (self.avg_entry_price - current_price) * self.quantity
    
    def calculate_total_pnl(self) -> Decimal:
        """Berechnet Gesamt-P&L"""
        return self.realized_pnl + self.unrealized_pnl - self.total_commission
    
    def update_price(self, new_price: Decimal) -> None:
        """Aktualisiert Preis und unrealisierte P&L"""
        self.current_price = new_price
        self.unrealized_pnl = self.calculate_unrealized_pnl(new_price)
        self.updated_at = datetime.now()
