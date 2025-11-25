"""
Commands für GridTrader V2.0
Commands repräsentieren User-Intentionen
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID


@dataclass
class CreateCycleTemplateCommand:
    """Command: Neues Cycle Template erstellen"""
    name: str
    symbol: str
    side: str  # LONG/SHORT
    anchor_price: Decimal
    step: Decimal
    step_mode: str  # CENTS/PERCENT
    levels: int
    qty_per_level: int
    guardian_mode: Optional[str] = None
    guardian_value: Optional[Decimal] = None
    auto_restart: bool = False
    auto_start_trigger: Optional[Decimal] = None


@dataclass
class StartCycleCommand:
    """Command: Cycle starten"""
    template_id: UUID
    symbol: str
    broker_account: Optional[str] = None


@dataclass
class PauseCycleCommand:
    """Command: Cycle pausieren"""
    cycle_id: UUID


@dataclass
class ResumeCycleCommand:
    """Command: Cycle fortsetzen"""
    cycle_id: UUID


@dataclass
class StopCycleCommand:
    """Command: Cycle stoppen"""
    cycle_id: UUID
    cancel_open_orders: bool = True
    close_positions: bool = False


@dataclass
class UpdateCycleLevelCommand:
    """Command: Cycle Level anpassen"""
    cycle_id: UUID
    level_index: int
    new_quantity: Optional[int] = None
    new_exit_price: Optional[Decimal] = None


@dataclass
class PlaceOrderCommand:
    """Command: Order platzieren"""
    symbol: str
    side: str  # BUY/SELL
    order_type: str  # MARKET/LIMIT
    quantity: int
    limit_price: Optional[Decimal] = None
    cycle_id: Optional[UUID] = None
    level_index: Optional[int] = None


@dataclass
class CancelOrderCommand:
    """Command: Order stornieren"""
    order_id: UUID


@dataclass
class RunBacktestCommand:
    """Command: Backtest ausführen"""
    template_id: UUID
    symbol: str
    start_date: str
    end_date: str
    initial_capital: Decimal = Decimal("100000")
    use_intraday_data: bool = False
