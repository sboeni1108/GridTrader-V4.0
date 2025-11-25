"""
Cycle Domain Models für GridTrader V2.0
Zentrale Geschäftslogik für Trading-Zyklen
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict, field_validator


# =====================================================
# Enums - Definieren alle möglichen Zustände
# =====================================================

class Side(str, Enum):
    """Trading-Seite"""
    LONG = "LONG"
    SHORT = "SHORT"


class ScaleMode(str, Enum):
    """Skalierungsmodus für Steps"""
    CENTS = "CENTS"      # Absoluter Wert in Cents
    PERCENT = "PERCENT"  # Prozentualer Wert


class CycleState(str, Enum):
    """Zyklus-Status"""
    WAITING = "WAITING"    # Wartet auf Start
    RUNNING = "RUNNING"    # Aktiv
    PAUSED = "PAUSED"      # Pausiert
    STOPPED = "STOPPED"    # Gestoppt
    COMPLETED = "COMPLETED" # Abgeschlossen


class LevelStatus(str, Enum):
    """Status einer einzelnen Grid-Stufe"""
    PLANNED = "PLANNED"           # Geplant
    ENTRY_PLACED = "ENTRY_PLACED" # Entry-Order platziert
    ENTRY_FILLED = "ENTRY_FILLED" # Entry-Order ausgeführt
    EXIT_PLACED = "EXIT_PLACED"   # Exit-Order platziert
    DONE = "DONE"                 # Komplett abgeschlossen
    CANCELLED = "CANCELLED"       # Abgebrochen


# =====================================================
# Domain Models
# =====================================================

class CycleTemplate(BaseModel):
    """
    Template für einen Trading-Zyklus
    Definiert die Parameter für eine Grid-Trading-Strategie
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    name: str
    symbol: str
    side: Side
    
    # Grid-Parameter
    anchor_price: Decimal = Field(gt=0, description="Anker-Preis für Grid")
    step: Decimal = Field(gt=0, description="Abstand zwischen Levels")
    step_mode: ScaleMode
    levels: int = Field(gt=0, le=100, description="Anzahl Grid-Levels")
    qty_per_level: int = Field(gt=0, description="Stückzahl pro Level")
    
    # Guardian (Profit-Schutz)
    guardian_mode: Optional[ScaleMode] = None
    guardian_value: Optional[Decimal] = Field(default=None, ge=0)
    
    # Verhaltens-Flags
    auto_restart: bool = False
    auto_start_trigger: Optional[Decimal] = Field(
        default=None, 
        ge=0, 
        le=100,
        description="Auto-Start wenn Intraday-Range >= X%"
    )
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    def calculate_step_absolute(self) -> Decimal:
        """Berechnet absoluten Step-Wert"""
        if self.step_mode == ScaleMode.CENTS:
            return self.step
        else:  # PERCENT
            return self.anchor_price * (self.step / 100)


class CycleInstance(BaseModel):
    """
    Laufende Instanz eines Zyklus
    Repräsentiert einen aktiven Trading-Zyklus
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(default_factory=uuid4)
    template_id: UUID
    symbol: str
    state: CycleState = CycleState.WAITING
    
    # Trading-Status
    current_level: int = 0
    filled_levels: int = 0
    
    # Performance
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_commission: Decimal = Decimal("0")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def can_start(self) -> bool:
        """Prüft ob Zyklus gestartet werden kann"""
        return self.state == CycleState.WAITING
    
    def can_pause(self) -> bool:
        """Prüft ob Zyklus pausiert werden kann"""
        return self.state == CycleState.RUNNING
    
    def can_resume(self) -> bool:
        """Prüft ob Zyklus fortgesetzt werden kann"""
        return self.state == CycleState.PAUSED
    
    def can_stop(self) -> bool:
        """Prüft ob Zyklus gestoppt werden kann"""
        return self.state in [CycleState.RUNNING, CycleState.PAUSED]


class CycleLevel(BaseModel):
    """
    Eine einzelne Stufe im Grid
    Repräsentiert einen Entry/Exit-Punkt
    """
    model_config = ConfigDict(from_attributes=True)
    
    cycle_id: UUID
    level_index: int = Field(ge=0, description="Index der Stufe (0-basiert)")
    
    # Preise
    entry_price: Decimal = Field(gt=0)
    exit_price: Decimal = Field(gt=0)
    guardian_price: Optional[Decimal] = None
    
    # Mengen
    qty_planned: int = Field(gt=0)
    qty_filled_entry: int = Field(ge=0, default=0)
    qty_filled_exit: int = Field(ge=0, default=0)
    
    # Status
    status: LevelStatus = LevelStatus.PLANNED
    
    # Order-IDs (für Tracking)
    entry_order_id: Optional[UUID] = None
    exit_order_id: Optional[UUID] = None
    
    # Timestamps
    entry_placed_at: Optional[datetime] = None
    entry_filled_at: Optional[datetime] = None
    exit_placed_at: Optional[datetime] = None
    exit_filled_at: Optional[datetime] = None
    
    def is_entry_complete(self) -> bool:
        """Prüft ob Entry komplett gefüllt"""
        return self.qty_filled_entry >= self.qty_planned
    
    def is_exit_complete(self) -> bool:
        """Prüft ob Exit komplett gefüllt"""
        return self.qty_filled_exit >= self.qty_planned
    
    def get_pending_entry_qty(self) -> int:
        """Berechnet noch zu füllende Entry-Menge"""
        return max(0, self.qty_planned - self.qty_filled_entry)
    
    def get_pending_exit_qty(self) -> int:
        """Berechnet noch zu füllende Exit-Menge"""
        return max(0, self.qty_filled_entry - self.qty_filled_exit)


class CycleSummary(BaseModel):
    """
    Zusammenfassung eines Zyklus für Reporting
    """
    model_config = ConfigDict(from_attributes=True)
    
    cycle_id: UUID
    template_name: str
    symbol: str
    side: Side
    state: CycleState
    
    # Grid-Info
    total_levels: int
    active_levels: int
    completed_levels: int
    
    # Performance
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    win_rate: Optional[float] = None
    
    # Statistik
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: Optional[Decimal] = None
    avg_loss: Optional[Decimal] = None
    
    # Zeit
    runtime_hours: Optional[float] = None
    created_at: datetime
    last_activity: datetime
    
    def calculate_metrics(self) -> None:
        """Berechnet Performance-Metriken"""
        self.total_pnl = self.realized_pnl + self.unrealized_pnl
        
        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100
