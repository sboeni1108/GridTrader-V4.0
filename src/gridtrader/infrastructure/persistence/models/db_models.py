"""
SQLAlchemy Database Models für GridTrader V2.0
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional
import uuid
import enum

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Boolean, 
    ForeignKey, Index, UniqueConstraint, Enum, DECIMAL
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class für alle Models"""
    pass


# Custom Types
class SQLiteDecimal(DECIMAL):
    """Decimal type für SQLite"""
    def __init__(self):
        super().__init__(precision=20, scale=8)


# Enums
class CycleStateDB(str, enum.Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


class OrderStatusDB(str, enum.Enum):
    NEW = "NEW"
    PENDING = "PENDING"
    PLACED = "PLACED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


# Database Models
class CycleTemplateDB(Base):
    """Cycle Template Tabelle"""
    __tablename__ = "cycle_templates"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    
    # Grid Parameters
    anchor_price: Mapped[Decimal] = mapped_column(SQLiteDecimal(), nullable=False)
    step: Mapped[Decimal] = mapped_column(SQLiteDecimal(), nullable=False)
    step_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    levels: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_per_level: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Guardian
    guardian_mode: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    guardian_value: Mapped[Optional[Decimal]] = mapped_column(SQLiteDecimal(), nullable=True)
    
    # Flags
    auto_restart: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_start_trigger: Mapped[Optional[Decimal]] = mapped_column(SQLiteDecimal(), nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # Relationships
    instances: Mapped[list["CycleInstanceDB"]] = relationship(back_populates="template")


class CycleInstanceDB(Base):
    """Cycle Instance Tabelle"""
    __tablename__ = "cycle_instances"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id: Mapped[str] = mapped_column(ForeignKey("cycle_templates.id"))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[CycleStateDB] = mapped_column(Enum(CycleStateDB), default=CycleStateDB.WAITING)
    
    # Status
    current_level: Mapped[int] = mapped_column(Integer, default=0)
    filled_levels: Mapped[int] = mapped_column(Integer, default=0)
    
    # Performance
    realized_pnl: Mapped[Decimal] = mapped_column(SQLiteDecimal(), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(SQLiteDecimal(), default=0)
    total_commission: Mapped[Decimal] = mapped_column(SQLiteDecimal(), default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    template: Mapped["CycleTemplateDB"] = relationship(back_populates="instances")
    orders: Mapped[list["OrderDB"]] = relationship(back_populates="cycle")


class OrderDB(Base):
    """Order Tabelle"""
    __tablename__ = "orders"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True)
    cycle_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cycle_instances.id"), nullable=True)
    
    # Order Details
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Preise
    limit_price: Mapped[Optional[Decimal]] = mapped_column(SQLiteDecimal(), nullable=True)
    avg_fill_price: Mapped[Optional[Decimal]] = mapped_column(SQLiteDecimal(), nullable=True)
    
    # Status
    status: Mapped[OrderStatusDB] = mapped_column(Enum(OrderStatusDB), default=OrderStatusDB.NEW)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    commission: Mapped[Decimal] = mapped_column(SQLiteDecimal(), default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    cycle: Mapped[Optional["CycleInstanceDB"]] = relationship(back_populates="orders")
