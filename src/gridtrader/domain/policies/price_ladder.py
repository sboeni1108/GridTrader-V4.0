"""Price Ladder Policy - Vereinfacht zum Testen"""
from decimal import Decimal
from typing import List
from dataclasses import dataclass
from gridtrader.domain.models.cycle import Side, ScaleMode, CycleLevel, LevelStatus
from uuid import uuid4

@dataclass
class LadderConfig:
    side: Side
    anchor_price: Decimal
    step: Decimal
    step_mode: ScaleMode
    levels: int
    qty_per_level: int
    tick_size: Decimal = Decimal("0.01")

class PriceLadderPolicy:
    def __init__(self, tick_size: Decimal = Decimal("0.01")):
        self.tick_size = tick_size
    
    def build_ladder(self, config: LadderConfig) -> List[CycleLevel]:
        levels = []
        step_abs = config.step if config.step_mode == ScaleMode.CENTS else config.anchor_price * (config.step / 100)
        
        for i in range(config.levels):
            if config.side == Side.LONG:
                entry = config.anchor_price - (step_abs * i)
                exit_price = entry + step_abs
            else:
                entry = config.anchor_price + (step_abs * i)
                exit_price = entry - step_abs
            
            level = CycleLevel(
                cycle_id=uuid4(),
                level_index=i,
                entry_price=entry,
                exit_price=exit_price,
                qty_planned=config.qty_per_level
            )
            levels.append(level)
        
        return levels