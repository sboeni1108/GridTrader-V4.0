"""
Original Grid-Logik für GridTrader V2.0
Basiert auf Eröffnungskurs und zweitem Preis
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
from dataclasses import dataclass
import pandas as pd
import numpy as np

from gridtrader.domain.models.cycle import CycleLevel, LevelStatus


@dataclass
class GridCalculationInput:
    """Input für Grid-Berechnung"""
    symbol: str
    side: str  # LONG oder SHORT
    
    # Preise
    open_price: Decimal  # Eröffnungskurs
    second_price: Decimal  # Preis nach X Stunden
    
    # Grid-Parameter
    num_levels: int
    qty_per_level: int
    
    # Optional - alle mit Defaults am Ende
    second_price_delay_hours: float = 1.0  # Default 1 Stunde
    min_step: Decimal = Decimal("0.01")  # Minimum Abstand
    tick_size: Decimal = Decimal("0.01")


class OriginalGridCalculator:
    """
    Berechnet Grid-Levels basierend auf der Original-Logik:
    - Startpreis = Eröffnungskurs
    - Zweiter Preis = Manuell oder nach X Stunden
    - Grid wird zwischen diesen Preisen aufgespannt
    """
    
    def calculate_grid(self, input_data: GridCalculationInput) -> List[CycleLevel]:
        """
        Berechnet Grid-Levels nach Original-Logik
        
        Returns:
            Liste von CycleLevel-Objekten
        """
        levels = []
        
        # Berechne Preisdifferenz
        price_diff = abs(input_data.second_price - input_data.open_price)
        
        if price_diff < input_data.min_step:
            raise ValueError(f"Preisdifferenz {price_diff} zu klein (min: {input_data.min_step})")
        
        # Bestimme Richtung
        if input_data.side == "LONG":
            # Bei LONG: Kaufe wenn Preis fällt
            if input_data.second_price < input_data.open_price:
                # Preis gefallen - normal LONG Grid
                start_price = input_data.open_price
                step = -price_diff / (input_data.num_levels - 1) if input_data.num_levels > 1 else -price_diff
            else:
                # Preis gestiegen - inverse Logik oder Warnung
                start_price = input_data.second_price
                step = -price_diff / (input_data.num_levels - 1) if input_data.num_levels > 1 else -price_diff
                
        else:  # SHORT
            # Bei SHORT: Verkaufe wenn Preis steigt
            if input_data.second_price > input_data.open_price:
                # Preis gestiegen - normal SHORT Grid
                start_price = input_data.open_price
                step = price_diff / (input_data.num_levels - 1) if input_data.num_levels > 1 else price_diff
            else:
                # Preis gefallen - inverse Logik oder Warnung
                start_price = input_data.second_price
                step = price_diff / (input_data.num_levels - 1) if input_data.num_levels > 1 else price_diff
        
        # Erstelle Levels
        for i in range(input_data.num_levels):
            if input_data.side == "LONG":
                # LONG: Entry-Preise fallen, Exit = Entry + Step
                entry_price = start_price + (step * i)
                exit_price = entry_price - step  # Exit höher als Entry
                
                # Korrektur: Bei LONG sollte Exit > Entry
                if step < 0:  # Normaler Fall
                    exit_price = entry_price + abs(step)
            else:
                # SHORT: Entry-Preise steigen, Exit = Entry - Step  
                entry_price = start_price + (step * i)
                exit_price = entry_price - abs(step)  # Exit niedriger als Entry
            
            # Runde auf Tick-Size
            entry_price = self._round_to_tick(entry_price, input_data.tick_size)
            exit_price = self._round_to_tick(exit_price, input_data.tick_size)
            
            # Erstelle Level
            from uuid import uuid4
            level = CycleLevel(
                cycle_id=uuid4(),
                level_index=i,
                entry_price=entry_price,
                exit_price=exit_price,
                qty_planned=input_data.qty_per_level,
                status=LevelStatus.PLANNED
            )
            
            levels.append(level)
        
        return levels
    
    def _round_to_tick(self, price: Decimal, tick_size: Decimal) -> Decimal:
        """Rundet auf Tick-Size"""
        return (price / tick_size).quantize(Decimal('1')) * tick_size
    
    def calculate_from_historical_data(
        self, 
        data: pd.DataFrame,
        symbol: str,
        side: str,
        num_levels: int,
        qty_per_level: int,
        second_price_delay_minutes: int = 60
    ) -> List[CycleLevel]:
        """
        Berechnet Grid aus historischen Daten
        
        Args:
            data: DataFrame mit OHLCV-Daten (1-Minuten Bars)
            second_price_delay_minutes: Verzögerung für zweiten Preis in Minuten
            
        Returns:
            Liste von CycleLevel-Objekten
        """
        # Finde Handelstag-Start (9:30)
        trading_start = data.between_time('09:30', '09:31').iloc[0] if not data.empty else None
        
        if trading_start is None:
            raise ValueError("Keine Daten für Handelsstart gefunden")
        
        open_price = Decimal(str(trading_start['open']))
        
        # Finde zweiten Preis
        target_time = trading_start.name + timedelta(minutes=second_price_delay_minutes)
        second_price_data = data.loc[data.index >= target_time].iloc[0] if not data.empty else None
        
        if second_price_data is None:
            # Fallback: Nutze Close des ersten Bars
            second_price = Decimal(str(trading_start['close']))
        else:
            second_price = Decimal(str(second_price_data['close']))
        
        # Berechne Grid
        input_data = GridCalculationInput(
            symbol=symbol,
            side=side,
            open_price=open_price,
            second_price=second_price,
            second_price_delay_hours=second_price_delay_minutes / 60,
            num_levels=num_levels,
            qty_per_level=qty_per_level
        )
        
        return self.calculate_grid(input_data)


class GridAnalyzer:
    """Analysiert Grid-Performance"""
    
    def analyze_grid_spacing(self, levels: List[CycleLevel]) -> dict:
        """Analysiert Grid-Abstände"""
        if len(levels) < 2:
            return {}
        
        steps = []
        for i in range(len(levels) - 1):
            step = abs(levels[i+1].entry_price - levels[i].entry_price)
            steps.append(float(step))
        
        return {
            "avg_step": np.mean(steps),
            "min_step": np.min(steps),
            "max_step": np.max(steps),
            "step_std": np.std(steps),
            "uniform": np.std(steps) < 0.01  # Gleichmäßig wenn Std < 1 Cent
        }
    
    def calculate_required_capital(
        self, 
        levels: List[CycleLevel],
        include_commission: Decimal = Decimal("1.0")
    ) -> Decimal:
        """Berechnet benötigtes Kapital für alle Levels"""
        total_capital = Decimal("0")
        
        for level in levels:
            # Kapital pro Level = Entry-Preis * Menge + Kommission
            level_capital = (level.entry_price * level.qty_planned) + include_commission
            total_capital += level_capital
        
        return total_capital
    
    def calculate_potential_profit(
        self,
        levels: List[CycleLevel],
        commission: Decimal = Decimal("1.0")
    ) -> Decimal:
        """Berechnet potenziellen Profit wenn alle Levels ausgeführt werden"""
        total_profit = Decimal("0")
        
        for level in levels:
            # Profit = (Exit - Entry) * Menge - 2*Kommission
            gross_profit = (level.exit_price - level.entry_price) * level.qty_planned
            net_profit = gross_profit - (2 * commission)
            total_profit += net_profit
        
        return total_profit
