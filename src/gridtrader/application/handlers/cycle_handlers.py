"""
Command Handlers für GridTrader V2.0
Handlers orchestrieren die Ausführung von Commands
"""
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime

from gridtrader.application.commands.cycle_commands import (
    CreateCycleTemplateCommand,
    StartCycleCommand,
    PauseCycleCommand,
    StopCycleCommand
)
from gridtrader.domain.models.cycle import (
    CycleTemplate, CycleInstance, CycleState, Side, ScaleMode
)
from gridtrader.domain.policies.price_ladder import PriceLadderPolicy, LadderConfig


class CycleCommandHandler:
    """Handler für Cycle-bezogene Commands"""
    
    def __init__(self, db_session=None, broker=None):
        """
        Args:
            db_session: Database Session
            broker: Broker Adapter
        """
        self.db_session = db_session
        self.broker = broker
        self.ladder_policy = PriceLadderPolicy()
        
        # In-Memory Storage für Tests
        self.templates = {}
        self.cycles = {}
    
    def handle_create_template(self, command: CreateCycleTemplateCommand) -> UUID:
        """Erstelle neues Cycle Template"""
        template = CycleTemplate(
            name=command.name,
            symbol=command.symbol,
            side=Side(command.side),
            anchor_price=command.anchor_price,
            step=command.step,
            step_mode=ScaleMode(command.step_mode),
            levels=command.levels,
            qty_per_level=command.qty_per_level,
            guardian_mode=ScaleMode(command.guardian_mode) if command.guardian_mode else None,
            guardian_value=command.guardian_value,
            auto_restart=command.auto_restart,
            auto_start_trigger=command.auto_start_trigger
        )
        
        # Speichern (in-memory für Tests)
        self.templates[template.id] = template
        
        # TODO: In Datenbank speichern wenn db_session vorhanden
        
        return template.id
    
    def handle_start_cycle(self, command: StartCycleCommand) -> UUID:
        """Starte einen neuen Cycle"""
        # Template holen
        template = self.templates.get(command.template_id)
        if not template:
            raise ValueError(f"Template {command.template_id} nicht gefunden")
        
        # Cycle Instance erstellen
        cycle = CycleInstance(
            template_id=template.id,
            symbol=command.symbol or template.symbol,
            state=CycleState.WAITING
        )
        
        # Ladder berechnen
        config = LadderConfig(
            side=template.side,
            anchor_price=template.anchor_price,
            step=template.step,
            step_mode=template.step_mode,
            levels=template.levels,
            qty_per_level=template.qty_per_level
        )
        
        levels = self.ladder_policy.build_ladder(config)
        
        # Status auf RUNNING
        cycle.state = CycleState.RUNNING
        cycle.started_at = datetime.now()
        
        # Speichern
        self.cycles[cycle.id] = (cycle, levels)
        
        # TODO: Orders platzieren wenn broker vorhanden
        
        return cycle.id
    
    def handle_pause_cycle(self, command: PauseCycleCommand) -> bool:
        """Pausiere laufenden Cycle"""
        if command.cycle_id not in self.cycles:
            raise ValueError(f"Cycle {command.cycle_id} nicht gefunden")
        
        cycle, levels = self.cycles[command.cycle_id]
        
        if not cycle.can_pause():
            return False
        
        cycle.state = CycleState.PAUSED
        cycle.paused_at = datetime.now()
        
        # TODO: Offene Orders canceln wenn broker vorhanden
        
        return True
    
    def handle_stop_cycle(self, command: StopCycleCommand) -> bool:
        """Stoppe Cycle"""
        if command.cycle_id not in self.cycles:
            raise ValueError(f"Cycle {command.cycle_id} nicht gefunden")
        
        cycle, levels = self.cycles[command.cycle_id]
        
        if not cycle.can_stop():
            return False
        
        cycle.state = CycleState.STOPPED
        cycle.stopped_at = datetime.now()
        
        # TODO: Orders/Positionen handhaben wenn broker vorhanden
        
        return True
    
    def get_cycle_status(self, cycle_id: UUID) -> dict:
        """Hole Cycle Status"""
        if cycle_id not in self.cycles:
            return None
        
        cycle, levels = self.cycles[cycle_id]
        
        return {
            "id": str(cycle.id),
            "state": cycle.state.value,
            "symbol": cycle.symbol,
            "levels_total": len(levels),
            "current_level": cycle.current_level,
            "pnl": float(cycle.realized_pnl + cycle.unrealized_pnl)
        }
