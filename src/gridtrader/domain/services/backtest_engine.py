"""
Backtesting Engine für GridTrader V2.0
Simuliert Grid-Trading Strategien mit historischen Daten
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from dataclasses import dataclass, field
from uuid import UUID

from gridtrader.domain.models.cycle import (
    CycleTemplate, CycleInstance, CycleLevel, 
    Side, ScaleMode, CycleState, LevelStatus
)
from gridtrader.domain.models.order import Order, Trade, OrderSide, OrderType
from gridtrader.domain.policies.price_ladder import PriceLadderPolicy, LadderConfig


@dataclass
class BacktestConfig:
    """Konfiguration für Backtest"""
    symbol: str
    start_date: str
    end_date: str
    initial_capital: Decimal = Decimal("100000")
    commission: Decimal = Decimal("1.0")  # USD pro Trade
    slippage: Decimal = Decimal("0.01")   # 1 Cent
    use_intraday: bool = False
    data_source: str = "IBKR"  # IBKR oder YAHOO
    
    # Trading Hours
    rth_only: bool = True  # Regular Trading Hours only
    session_start: str = "09:30"
    session_end: str = "16:00"
    
    # Risk Management
    max_positions: int = 100
    stop_loss_pct: Optional[Decimal] = None


@dataclass
class BacktestResult:
    """Ergebnis eines Backtests"""
    # Basis Info
    symbol: str
    side: str
    start_date: datetime
    end_date: datetime
    trading_days: int
    
    # Performance
    total_return: Decimal
    total_return_pct: Decimal
    annualized_return: Decimal
    
    # Risk Metrics
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    volatility: float
    
    # Trading Statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: Decimal
    avg_loss: Decimal
    profit_factor: float
    
    # Grid Statistics
    levels_triggered: int
    levels_completed: int
    avg_time_in_trade: float  # Stunden
    
    # Capital
    starting_capital: Decimal
    ending_capital: Decimal
    max_capital_used: Decimal
    
    # Details
    trades: List[Trade] = field(default_factory=list)
    daily_returns: pd.Series = field(default_factory=pd.Series)
    equity_curve: pd.Series = field(default_factory=pd.Series)


class BacktestEngine:
    """
    Hauptklasse für Backtesting
    Simuliert Grid-Trading mit historischen Daten
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.ladder_policy = PriceLadderPolicy()
        self._historical_data = None
        
        # State
        self.current_capital = config.initial_capital
        self.positions: Dict[str, int] = {}  # symbol -> quantity
        self.open_orders: List[Order] = []
        self.completed_trades: List[Trade] = []
        self.equity_curve: List[Tuple[datetime, Decimal]] = []
        
        # Cycle Management
        self.cycle_instance: Optional[CycleInstance] = None
        self.cycle_levels: List[CycleLevel] = []
        self.active_level_orders: Dict[int, Order] = {}  # level_index -> Order
        
    def run(self, template: CycleTemplate) -> BacktestResult:
        """
        Führt Backtest aus
        
        Args:
            template: Cycle Template mit Strategie-Parametern
            
        Returns:
            BacktestResult mit allen Metriken
        """
        # Daten laden
        data = self._load_historical_data()
        if data.empty:
            raise ValueError(f"Keine Daten für {self.config.symbol}")
        
        # Cycle initialisieren
        self._initialize_cycle(template)
        
        # Simulation
        print(f"🚀 Starte Backtest für {self.config.symbol}")
        print(f"   Zeitraum: {self.config.start_date} bis {self.config.end_date}")
        print(f"   Strategie: {template.side} Grid mit {template.levels} Levels")
        
        for timestamp, row in data.iterrows():
            self._process_tick(timestamp, row)
        
        # Ergebnis berechnen
        result = self._calculate_results(template)
        
        print(f"✅ Backtest abgeschlossen!")
        print(f"   Total Return: {result.total_return_pct:.2f}%")
        print(f"   Sharpe Ratio: {result.sharpe_ratio:.2f}")
        print(f"   Win Rate: {result.win_rate:.1f}%")
        
        return result
    
    def _load_historical_data(self) -> pd.DataFrame:
        """Lädt historische Daten"""
        if self.config.data_source == "YAHOO":
            return self._load_yahoo_data()
        else:
            return self._load_ibkr_data()
    
    def _load_yahoo_data(self) -> pd.DataFrame:
        """Lädt Daten von Yahoo Finance"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(self.config.symbol)
            
            if self.config.use_intraday:
                # 1-Minute Bars
                data = ticker.history(
                    start=self.config.start_date,
                    end=self.config.end_date,
                    interval="1m"
                )
            else:
                # Daily Bars
                data = ticker.history(
                    start=self.config.start_date,
                    end=self.config.end_date,
                    interval="1d"
                )
            
            # Spalten umbenennen für Konsistenz
            data.columns = data.columns.str.lower()
            
            return data
            
        except Exception as e:
            print(f"⚠️ Yahoo Finance Fehler: {e}")
            return pd.DataFrame()
    
    def _load_ibkr_data(self) -> pd.DataFrame:
        """Lädt Daten von IBKR (Mock für Tests)"""
        # TODO: Echte IBKR Integration
        # Für Tests generieren wir Mock-Daten
        dates = pd.date_range(
            start=self.config.start_date,
            end=self.config.end_date,
            freq='1min' if self.config.use_intraday else 'D'
        )
        
        # Simuliere Preisbewegung
        np.random.seed(42)
        prices = [Decimal("100.00")]
        
        for _ in range(len(dates) - 1):
            change = Decimal(str(np.random.randn() * 0.5))
            new_price = max(Decimal("1.00"), prices[-1] + change)
            prices.append(new_price)
        
        data = pd.DataFrame({
            'open': prices,
            'high': [p + Decimal("0.50") for p in prices],
            'low': [p - Decimal("0.50") for p in prices],
            'close': prices,
            'volume': np.random.randint(1000000, 5000000, len(dates))
        }, index=dates)
        
        return data
    
    def _initialize_cycle(self, template: CycleTemplate):
        """Initialisiert Cycle für Backtest"""
        # Cycle Instance
        self.cycle_instance = CycleInstance(
            template_id=template.id,
            symbol=self.config.symbol,
            state=CycleState.RUNNING
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
        
        self.cycle_levels = self.ladder_policy.build_ladder(config)
    
    def _process_tick(self, timestamp: datetime, row: pd.Series):
        """Verarbeitet einen Tick/Bar"""
        current_price = Decimal(str(row['close']))
        
        # Check Entry-Bedingungen für jedes Level
        for level in self.cycle_levels:
            if level.status == LevelStatus.PLANNED:
                if self._should_enter(level, current_price):
                    self._execute_entry(level, current_price, timestamp)
            
            elif level.status == LevelStatus.ENTRY_FILLED:
                if self._should_exit(level, current_price):
                    self._execute_exit(level, current_price, timestamp)
        
        # Equity Curve Update
        self._update_equity(timestamp, current_price)
    
    def _should_enter(self, level: CycleLevel, price: Decimal) -> bool:
        """Prüft ob Entry-Bedingung erfüllt"""
        if self.cycle_instance.state != CycleState.RUNNING:
            return False
            
        if self.cycle_instance.template_id in self.positions:
            # Schon Position offen
            return False
        
        template_side = self.cycle_levels[0].exit_price > self.cycle_levels[0].entry_price
        
        if template_side:  # LONG
            return price <= level.entry_price
        else:  # SHORT
            return price >= level.entry_price
    
    def _should_exit(self, level: CycleLevel, price: Decimal) -> bool:
        """Prüft ob Exit-Bedingung erfüllt"""
        template_side = self.cycle_levels[0].exit_price > self.cycle_levels[0].entry_price
        
        # Guardian Check
        if level.guardian_price:
            if template_side:  # LONG
                if price >= level.guardian_price:
                    return True
            else:  # SHORT
                if price <= level.guardian_price:
                    return True
        
        # Normal Exit
        if template_side:  # LONG
            return price >= level.exit_price
        else:  # SHORT
            return price <= level.exit_price
    
    def _execute_entry(self, level: CycleLevel, price: Decimal, timestamp: datetime):
        """Führt Entry aus"""
        # Slippage
        fill_price = price + self.config.slippage if level.exit_price > level.entry_price else price - self.config.slippage
        
        # Trade erstellen
        trade = Trade(
            order_id=level.entry_order_id or UUID('00000000-0000-0000-0000-000000000000'),
            symbol=self.config.symbol,
            side=OrderSide.BUY if level.exit_price > level.entry_price else OrderSide.SELL,
            quantity=level.qty_planned,
            price=fill_price,
            commission=self.config.commission,
            executed_at=timestamp
        )
        
        self.completed_trades.append(trade)
        
        # Level Status Update
        level.status = LevelStatus.ENTRY_FILLED
        level.qty_filled_entry = level.qty_planned
        level.entry_filled_at = timestamp
        
        # Capital Update
        cost = (fill_price * level.qty_planned) + self.config.commission
        if level.exit_price > level.entry_price:  # LONG
            self.current_capital -= cost
        else:  # SHORT (erhalten Capital)
            self.current_capital += cost
    
    def _execute_exit(self, level: CycleLevel, price: Decimal, timestamp: datetime):
        """Führt Exit aus"""
        # Slippage
        fill_price = price - self.config.slippage if level.exit_price > level.entry_price else price + self.config.slippage
        
        # Trade erstellen
        trade = Trade(
            order_id=level.exit_order_id or UUID('00000000-0000-0000-0000-000000000000'),
            symbol=self.config.symbol,
            side=OrderSide.SELL if level.exit_price > level.entry_price else OrderSide.BUY,
            quantity=level.qty_filled_entry,
            price=fill_price,
            commission=self.config.commission,
            executed_at=timestamp
        )
        
        self.completed_trades.append(trade)
        
        # P&L berechnen
        if level.exit_price > level.entry_price:  # LONG
            pnl = (fill_price - level.entry_price) * level.qty_filled_entry - (2 * self.config.commission)
        else:  # SHORT
            pnl = (level.entry_price - fill_price) * level.qty_filled_entry - (2 * self.config.commission)
        
        trade.realized_pnl = pnl
        
        # Level Status Update
        level.status = LevelStatus.DONE
        level.qty_filled_exit = level.qty_filled_entry
        level.exit_filled_at = timestamp
        
        # Capital Update
        proceeds = (fill_price * level.qty_filled_entry) - self.config.commission
        if level.exit_price > level.entry_price:  # LONG
            self.current_capital += proceeds
        else:  # SHORT
            self.current_capital -= proceeds
    
    def _update_equity(self, timestamp: datetime, current_price: Decimal):
        """Update Equity Curve"""
        self.equity_curve.append((timestamp, self.current_capital))
    
    def _calculate_results(self, template: CycleTemplate) -> BacktestResult:
        """Berechnet finale Ergebnisse"""
        # Basis Metriken
        starting_capital = self.config.initial_capital
        ending_capital = self.current_capital
        total_return = ending_capital - starting_capital
        total_return_pct = (total_return / starting_capital) * 100
        
        # Trade Statistiken
        winning_trades = [t for t in self.completed_trades if t.realized_pnl and t.realized_pnl > 0]
        losing_trades = [t for t in self.completed_trades if t.realized_pnl and t.realized_pnl < 0]
        
        win_rate = (len(winning_trades) / len(self.completed_trades) * 100) if self.completed_trades else 0
        
        avg_win = (sum(t.realized_pnl for t in winning_trades) / len(winning_trades)) if winning_trades else Decimal("0")
        avg_loss = (sum(t.realized_pnl for t in losing_trades) / len(losing_trades)) if losing_trades else Decimal("0")
        
        # Sharpe Ratio (vereinfacht)
        if self.equity_curve:
            returns = pd.Series([float(e[1]) for e in self.equity_curve]).pct_change().dropna()
            sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        else:
            sharpe = 0
        
        return BacktestResult(
            symbol=self.config.symbol,
            side=template.side.value,
            start_date=datetime.strptime(self.config.start_date, "%Y-%m-%d"),
            end_date=datetime.strptime(self.config.end_date, "%Y-%m-%d"),
            trading_days=len(self.equity_curve),
            total_return=total_return,
            total_return_pct=total_return_pct,
            annualized_return=total_return_pct,  # TODO: Korrekt annualisieren
            sharpe_ratio=sharpe,
            sortino_ratio=0,  # TODO: Implementieren
            max_drawdown=Decimal("0"),  # TODO: Implementieren
            max_drawdown_pct=Decimal("0"),
            volatility=0,
            total_trades=len(self.completed_trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            levels_triggered=sum(1 for l in self.cycle_levels if l.status != LevelStatus.PLANNED),
            levels_completed=sum(1 for l in self.cycle_levels if l.status == LevelStatus.DONE),
            avg_time_in_trade=0,  # TODO: Implementieren
            starting_capital=starting_capital,
            ending_capital=ending_capital,
            max_capital_used=starting_capital,  # TODO: Track max usage
            trades=self.completed_trades
        )
