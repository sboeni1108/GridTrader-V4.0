"""
Performance Tracker

Verfolgt und analysiert die Performance des KI-Controllers:
- Trade-Historie
- Entscheidungs-Historie
- Performance-Metriken
- "Was wäre wenn"-Analyse
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, List, Any, Tuple
from collections import deque
from threading import Lock
import json
import statistics


class DecisionType(str, Enum):
    """Art der Entscheidung"""
    ACTIVATE_LEVEL = "ACTIVATE_LEVEL"
    DEACTIVATE_LEVEL = "DEACTIVATE_LEVEL"
    SKIP_LEVEL = "SKIP_LEVEL"
    HOLD = "HOLD"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"
    RISK_REDUCTION = "RISK_REDUCTION"


class DecisionOutcome(str, Enum):
    """Ergebnis einer Entscheidung"""
    PENDING = "PENDING"      # Noch nicht ausgewertet
    CORRECT = "CORRECT"      # Richtige Entscheidung
    INCORRECT = "INCORRECT"  # Falsche Entscheidung
    NEUTRAL = "NEUTRAL"      # Keine klare Bewertung möglich
    MISSED = "MISSED"        # Verpasste Gelegenheit


@dataclass
class DecisionRecord:
    """Aufzeichnung einer Entscheidung"""
    decision_id: str
    timestamp: datetime
    decision_type: DecisionType
    level_id: Optional[str]
    symbol: Optional[str]

    # Kontext zum Zeitpunkt der Entscheidung
    price_at_decision: float
    volatility_regime: str
    risk_level: str
    confidence_score: float

    # Gründe für die Entscheidung
    reasons: List[str] = field(default_factory=list)
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    # Ergebnis (später ausgefüllt)
    outcome: DecisionOutcome = DecisionOutcome.PENDING
    outcome_details: str = ""
    price_after_5min: Optional[float] = None
    price_after_15min: Optional[float] = None
    price_after_30min: Optional[float] = None
    actual_pnl: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'decision_id': self.decision_id,
            'timestamp': self.timestamp.isoformat(),
            'decision_type': self.decision_type.value,
            'level_id': self.level_id,
            'symbol': self.symbol,
            'price_at_decision': self.price_at_decision,
            'volatility_regime': self.volatility_regime,
            'risk_level': self.risk_level,
            'confidence_score': self.confidence_score,
            'reasons': self.reasons,
            'score_breakdown': self.score_breakdown,
            'outcome': self.outcome.value,
            'outcome_details': self.outcome_details,
            'price_after_5min': self.price_after_5min,
            'price_after_15min': self.price_after_15min,
            'price_after_30min': self.price_after_30min,
            'actual_pnl': self.actual_pnl,
        }


@dataclass
class TradeRecord:
    """Aufzeichnung eines Trades"""
    trade_id: str
    level_id: str
    symbol: str
    direction: str  # LONG/SHORT

    # Entry
    entry_time: datetime
    entry_price: float
    entry_quantity: int
    entry_reason: str

    # Exit
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""

    # Performance
    realized_pnl: float = 0.0
    commission: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0

    # Holding
    holding_time_minutes: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0
    max_adverse_excursion: float = 0.0  # MAE
    max_favorable_excursion: float = 0.0  # MFE

    # Kontext
    market_conditions: Dict[str, Any] = field(default_factory=dict)
    decision_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'trade_id': self.trade_id,
            'level_id': self.level_id,
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_time': self.entry_time.isoformat(),
            'entry_price': self.entry_price,
            'entry_quantity': self.entry_quantity,
            'entry_reason': self.entry_reason,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'exit_price': self.exit_price,
            'exit_reason': self.exit_reason,
            'realized_pnl': self.realized_pnl,
            'commission': self.commission,
            'net_pnl': self.net_pnl,
            'return_pct': self.return_pct,
            'holding_time_minutes': self.holding_time_minutes,
            'max_profit': self.max_profit,
            'max_loss': self.max_loss,
            'mae': self.max_adverse_excursion,
            'mfe': self.max_favorable_excursion,
        }

    def is_closed(self) -> bool:
        return self.exit_time is not None


@dataclass
class PerformanceMetrics:
    """Performance-Metriken"""
    # Zeitraum
    period_start: datetime
    period_end: datetime
    trading_days: int = 0

    # Trade-Statistiken
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    break_even_trades: int = 0

    # P&L
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    # Ratios
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade: float = 0.0
    expectancy: float = 0.0

    # Risk
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Time
    avg_holding_time_min: float = 0.0
    avg_winning_time_min: float = 0.0
    avg_losing_time_min: float = 0.0

    # Decision Quality
    total_decisions: int = 0
    correct_decisions: int = 0
    incorrect_decisions: int = 0
    decision_accuracy: float = 0.0

    def to_dict(self) -> dict:
        return {
            'period': {
                'start': self.period_start.isoformat(),
                'end': self.period_end.isoformat(),
                'trading_days': self.trading_days,
            },
            'trades': {
                'total': self.total_trades,
                'winning': self.winning_trades,
                'losing': self.losing_trades,
                'break_even': self.break_even_trades,
            },
            'pnl': {
                'total': self.total_pnl,
                'commission': self.total_commission,
                'net': self.net_pnl,
                'gross_profit': self.gross_profit,
                'gross_loss': self.gross_loss,
            },
            'ratios': {
                'win_rate': self.win_rate,
                'profit_factor': self.profit_factor,
                'avg_win': self.avg_win,
                'avg_loss': self.avg_loss,
                'avg_trade': self.avg_trade,
                'expectancy': self.expectancy,
            },
            'risk': {
                'max_drawdown': self.max_drawdown,
                'max_drawdown_pct': self.max_drawdown_pct,
                'sharpe_ratio': self.sharpe_ratio,
                'sortino_ratio': self.sortino_ratio,
                'calmar_ratio': self.calmar_ratio,
            },
            'time': {
                'avg_holding_min': self.avg_holding_time_min,
                'avg_winning_min': self.avg_winning_time_min,
                'avg_losing_min': self.avg_losing_time_min,
            },
            'decisions': {
                'total': self.total_decisions,
                'correct': self.correct_decisions,
                'incorrect': self.incorrect_decisions,
                'accuracy': self.decision_accuracy,
            },
        }


class PerformanceTracker:
    """
    Verfolgt und analysiert die Performance des KI-Controllers.

    Features:
    - Trade-Aufzeichnung mit Details
    - Entscheidungs-Tracking
    - Performance-Metriken Berechnung
    - Equity-Kurve Tracking
    - Export-Funktionen
    """

    def __init__(self, max_history: int = 10000):
        self._max_history = max_history
        self._lock = Lock()

        # Records
        self._decisions: deque = deque(maxlen=max_history)
        self._trades: deque = deque(maxlen=max_history)
        self._open_trades: Dict[str, TradeRecord] = {}

        # Equity Tracking
        self._equity_curve: deque = deque(maxlen=max_history)
        self._daily_pnl: Dict[str, float] = {}  # Datum -> P&L
        self._starting_equity: float = 0.0
        self._current_equity: float = 0.0

        # Counters
        self._decision_counter = 0
        self._trade_counter = 0

        # Pending decision evaluations
        self._pending_evaluations: Dict[str, DecisionRecord] = {}

    # ==================== DECISION TRACKING ====================

    def record_decision(
        self,
        decision_type: DecisionType,
        level_id: Optional[str],
        symbol: Optional[str],
        price: float,
        volatility_regime: str,
        risk_level: str,
        confidence: float,
        reasons: List[str],
        score_breakdown: Optional[Dict[str, float]] = None,
    ) -> str:
        """
        Zeichnet eine Entscheidung auf.

        Returns:
            Decision ID für spätere Referenz
        """
        with self._lock:
            self._decision_counter += 1
            decision_id = f"D-{self._decision_counter:06d}"

            record = DecisionRecord(
                decision_id=decision_id,
                timestamp=datetime.now(),
                decision_type=decision_type,
                level_id=level_id,
                symbol=symbol,
                price_at_decision=price,
                volatility_regime=volatility_regime,
                risk_level=risk_level,
                confidence_score=confidence,
                reasons=reasons,
                score_breakdown=score_breakdown or {},
            )

            self._decisions.append(record)

            # Für spätere Evaluation merken
            if symbol:
                self._pending_evaluations[decision_id] = record

            return decision_id

    def evaluate_decision(
        self,
        decision_id: str,
        current_price: float,
        minutes_elapsed: int,
    ):
        """
        Evaluiert eine vergangene Entscheidung basierend auf Preisentwicklung.
        """
        with self._lock:
            if decision_id not in self._pending_evaluations:
                return

            record = self._pending_evaluations[decision_id]

            # Preis-Update je nach Zeit
            if minutes_elapsed >= 5 and record.price_after_5min is None:
                record.price_after_5min = current_price
            if minutes_elapsed >= 15 and record.price_after_15min is None:
                record.price_after_15min = current_price
            if minutes_elapsed >= 30 and record.price_after_30min is None:
                record.price_after_30min = current_price

            # Nach 30 Minuten: Entscheidung bewerten
            if record.price_after_30min is not None and record.outcome == DecisionOutcome.PENDING:
                self._evaluate_decision_outcome(record)
                del self._pending_evaluations[decision_id]

    def _evaluate_decision_outcome(self, record: DecisionRecord):
        """Bewertet das Ergebnis einer Entscheidung"""
        if record.price_after_30min is None:
            return

        price_change = record.price_after_30min - record.price_at_decision
        price_change_pct = (price_change / record.price_at_decision) * 100

        if record.decision_type == DecisionType.ACTIVATE_LEVEL:
            # War Aktivierung richtig?
            # Vereinfachte Logik: Preis bewegte sich in erwartete Richtung
            # TODO: Level-spezifische Bewertung
            if abs(price_change_pct) > 0.1:  # Signifikante Bewegung
                record.outcome = DecisionOutcome.CORRECT
                record.outcome_details = f"Preis bewegte sich {price_change_pct:.2f}%"
            else:
                record.outcome = DecisionOutcome.NEUTRAL
                record.outcome_details = "Keine signifikante Bewegung"

        elif record.decision_type == DecisionType.SKIP_LEVEL:
            # War Überspringen richtig?
            if abs(price_change_pct) < 0.1:
                record.outcome = DecisionOutcome.CORRECT
                record.outcome_details = "Richtig übersprungen, keine Bewegung"
            elif abs(price_change_pct) > 0.5:
                record.outcome = DecisionOutcome.MISSED
                record.outcome_details = f"Verpasste Bewegung: {price_change_pct:.2f}%"
            else:
                record.outcome = DecisionOutcome.NEUTRAL

        elif record.decision_type == DecisionType.EMERGENCY_EXIT:
            # Emergency Exit: Richtig wenn Preis weiter gefallen
            if price_change_pct < -0.5:
                record.outcome = DecisionOutcome.CORRECT
                record.outcome_details = f"Richtiger Exit, Preis fiel weiter {price_change_pct:.2f}%"
            elif price_change_pct > 0.5:
                record.outcome = DecisionOutcome.INCORRECT
                record.outcome_details = f"Falscher Exit, Preis stieg {price_change_pct:.2f}%"
            else:
                record.outcome = DecisionOutcome.NEUTRAL

        else:
            record.outcome = DecisionOutcome.NEUTRAL

    # ==================== TRADE TRACKING ====================

    def record_trade_entry(
        self,
        level_id: str,
        symbol: str,
        direction: str,
        entry_price: float,
        quantity: int,
        reason: str,
        market_conditions: Optional[Dict[str, Any]] = None,
        decision_id: Optional[str] = None,
    ) -> str:
        """
        Zeichnet einen Trade-Entry auf.

        Returns:
            Trade ID
        """
        with self._lock:
            self._trade_counter += 1
            trade_id = f"T-{self._trade_counter:06d}"

            record = TradeRecord(
                trade_id=trade_id,
                level_id=level_id,
                symbol=symbol,
                direction=direction,
                entry_time=datetime.now(),
                entry_price=entry_price,
                entry_quantity=quantity,
                entry_reason=reason,
                market_conditions=market_conditions or {},
                decision_id=decision_id,
            )

            self._open_trades[trade_id] = record
            return trade_id

    def record_trade_exit(
        self,
        trade_id: str,
        exit_price: float,
        reason: str,
        commission: float = 0.0,
    ):
        """Zeichnet einen Trade-Exit auf"""
        with self._lock:
            if trade_id not in self._open_trades:
                return

            record = self._open_trades.pop(trade_id)
            record.exit_time = datetime.now()
            record.exit_price = exit_price
            record.exit_reason = reason
            record.commission = commission

            # P&L berechnen
            if record.direction == "LONG":
                record.realized_pnl = (exit_price - record.entry_price) * record.entry_quantity
            else:
                record.realized_pnl = (record.entry_price - exit_price) * record.entry_quantity

            record.net_pnl = record.realized_pnl - commission
            record.return_pct = (record.net_pnl / (record.entry_price * record.entry_quantity)) * 100

            # Holding Time
            record.holding_time_minutes = (record.exit_time - record.entry_time).total_seconds() / 60

            # Trade speichern
            self._trades.append(record)

            # Equity aktualisieren
            self._current_equity += record.net_pnl
            self._equity_curve.append((datetime.now(), self._current_equity))

            # Daily P&L
            date_key = record.exit_time.strftime('%Y-%m-%d')
            self._daily_pnl[date_key] = self._daily_pnl.get(date_key, 0.0) + record.net_pnl

    def update_open_trade(
        self,
        trade_id: str,
        current_price: float,
    ):
        """Aktualisiert MAE/MFE für offenen Trade"""
        with self._lock:
            if trade_id not in self._open_trades:
                return

            record = self._open_trades[trade_id]

            # Aktueller P&L
            if record.direction == "LONG":
                current_pnl = (current_price - record.entry_price) * record.entry_quantity
            else:
                current_pnl = (record.entry_price - current_price) * record.entry_quantity

            # MAE/MFE aktualisieren
            if current_pnl > record.max_profit:
                record.max_profit = current_pnl
                record.max_favorable_excursion = current_pnl
            if current_pnl < record.max_loss:
                record.max_loss = current_pnl
                record.max_adverse_excursion = abs(current_pnl)

    # ==================== METRICS CALCULATION ====================

    def calculate_metrics(
        self,
        period_start: Optional[datetime] = None,
        period_end: Optional[datetime] = None,
    ) -> PerformanceMetrics:
        """
        Berechnet Performance-Metriken für einen Zeitraum.
        """
        with self._lock:
            # Zeitraum bestimmen
            if period_start is None:
                period_start = datetime.now() - timedelta(days=30)
            if period_end is None:
                period_end = datetime.now()

            # Trades im Zeitraum filtern
            trades = [
                t for t in self._trades
                if period_start <= t.entry_time <= period_end and t.is_closed()
            ]

            # Decisions im Zeitraum filtern
            decisions = [
                d for d in self._decisions
                if period_start <= d.timestamp <= period_end
            ]

            metrics = PerformanceMetrics(
                period_start=period_start,
                period_end=period_end,
            )

            if not trades:
                return metrics

            # Trade-Statistiken
            metrics.total_trades = len(trades)

            winning = [t for t in trades if t.net_pnl > 0]
            losing = [t for t in trades if t.net_pnl < 0]
            break_even = [t for t in trades if t.net_pnl == 0]

            metrics.winning_trades = len(winning)
            metrics.losing_trades = len(losing)
            metrics.break_even_trades = len(break_even)

            # P&L
            metrics.total_pnl = sum(t.realized_pnl for t in trades)
            metrics.total_commission = sum(t.commission for t in trades)
            metrics.net_pnl = sum(t.net_pnl for t in trades)
            metrics.gross_profit = sum(t.net_pnl for t in winning) if winning else 0
            metrics.gross_loss = abs(sum(t.net_pnl for t in losing)) if losing else 0

            # Ratios
            metrics.win_rate = (metrics.winning_trades / metrics.total_trades * 100) if metrics.total_trades > 0 else 0
            metrics.profit_factor = (metrics.gross_profit / metrics.gross_loss) if metrics.gross_loss > 0 else float('inf')
            metrics.avg_win = (metrics.gross_profit / metrics.winning_trades) if metrics.winning_trades > 0 else 0
            metrics.avg_loss = (metrics.gross_loss / metrics.losing_trades) if metrics.losing_trades > 0 else 0
            metrics.avg_trade = (metrics.net_pnl / metrics.total_trades) if metrics.total_trades > 0 else 0

            # Expectancy
            if metrics.total_trades > 0:
                win_rate_decimal = metrics.win_rate / 100
                metrics.expectancy = (win_rate_decimal * metrics.avg_win) - ((1 - win_rate_decimal) * metrics.avg_loss)

            # Time
            holding_times = [t.holding_time_minutes for t in trades]
            winning_times = [t.holding_time_minutes for t in winning]
            losing_times = [t.holding_time_minutes for t in losing]

            metrics.avg_holding_time_min = statistics.mean(holding_times) if holding_times else 0
            metrics.avg_winning_time_min = statistics.mean(winning_times) if winning_times else 0
            metrics.avg_losing_time_min = statistics.mean(losing_times) if losing_times else 0

            # Risk Metrics
            self._calculate_risk_metrics(metrics, trades)

            # Decision Quality
            evaluated = [d for d in decisions if d.outcome != DecisionOutcome.PENDING]
            metrics.total_decisions = len(evaluated)
            metrics.correct_decisions = len([d for d in evaluated if d.outcome == DecisionOutcome.CORRECT])
            metrics.incorrect_decisions = len([d for d in evaluated if d.outcome == DecisionOutcome.INCORRECT])
            metrics.decision_accuracy = (metrics.correct_decisions / metrics.total_decisions * 100) if metrics.total_decisions > 0 else 0

            # Trading Days
            unique_days = set(t.entry_time.strftime('%Y-%m-%d') for t in trades)
            metrics.trading_days = len(unique_days)

            return metrics

    def _calculate_risk_metrics(self, metrics: PerformanceMetrics, trades: List[TradeRecord]):
        """Berechnet Risiko-Metriken"""
        if not trades:
            return

        # Equity Curve simulieren
        equity = self._starting_equity
        peak = equity
        max_dd = 0
        max_dd_pct = 0
        equity_curve = [equity]
        returns = []

        for trade in sorted(trades, key=lambda t: t.exit_time or t.entry_time):
            equity += trade.net_pnl
            equity_curve.append(equity)

            if equity > peak:
                peak = equity

            dd = peak - equity
            dd_pct = (dd / peak * 100) if peak > 0 else 0

            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

            # Return für diesen Trade
            if equity_curve[-2] > 0:
                ret = (equity - equity_curve[-2]) / equity_curve[-2]
                returns.append(ret)

        metrics.max_drawdown = max_dd
        metrics.max_drawdown_pct = max_dd_pct

        # Sharpe Ratio (vereinfacht, annualisiert)
        if returns and len(returns) > 1:
            avg_return = statistics.mean(returns)
            std_return = statistics.stdev(returns)
            if std_return > 0:
                # Annahme: ~252 Trading Days
                metrics.sharpe_ratio = (avg_return / std_return) * (252 ** 0.5)

            # Sortino (nur Downside Deviation)
            negative_returns = [r for r in returns if r < 0]
            if negative_returns:
                downside_std = statistics.stdev(negative_returns) if len(negative_returns) > 1 else abs(negative_returns[0])
                if downside_std > 0:
                    metrics.sortino_ratio = (avg_return / downside_std) * (252 ** 0.5)

        # Calmar Ratio
        if max_dd_pct > 0 and metrics.trading_days > 0:
            annual_return = (metrics.net_pnl / self._starting_equity) * (252 / metrics.trading_days) * 100 if self._starting_equity > 0 else 0
            metrics.calmar_ratio = annual_return / max_dd_pct

    # ==================== GETTERS ====================

    def get_decisions(self, limit: int = 100) -> List[DecisionRecord]:
        """Gibt letzte Entscheidungen zurück"""
        return list(self._decisions)[-limit:]

    def get_trades(self, limit: int = 100) -> List[TradeRecord]:
        """Gibt letzte Trades zurück"""
        return list(self._trades)[-limit:]

    def get_open_trades(self) -> List[TradeRecord]:
        """Gibt offene Trades zurück"""
        return list(self._open_trades.values())

    def get_equity_curve(self) -> List[Tuple[datetime, float]]:
        """Gibt Equity-Kurve zurück"""
        return list(self._equity_curve)

    def get_daily_pnl(self) -> Dict[str, float]:
        """Gibt tägliche P&L zurück"""
        return dict(self._daily_pnl)

    def get_current_equity(self) -> float:
        """Gibt aktuelles Eigenkapital zurück"""
        return self._current_equity

    # ==================== ANALYSIS ====================

    def get_trade_analysis_by_level(self) -> Dict[str, Dict[str, Any]]:
        """Analysiert Trades nach Level"""
        analysis = {}

        for trade in self._trades:
            if trade.level_id not in analysis:
                analysis[trade.level_id] = {
                    'total_trades': 0,
                    'winning': 0,
                    'losing': 0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0,
                    'win_rate': 0.0,
                }

            level = analysis[trade.level_id]
            level['total_trades'] += 1
            level['total_pnl'] += trade.net_pnl

            if trade.net_pnl > 0:
                level['winning'] += 1
            elif trade.net_pnl < 0:
                level['losing'] += 1

        # Durchschnitte berechnen
        for level_id, data in analysis.items():
            if data['total_trades'] > 0:
                data['avg_pnl'] = data['total_pnl'] / data['total_trades']
                data['win_rate'] = data['winning'] / data['total_trades'] * 100

        return analysis

    def get_trade_analysis_by_time(self) -> Dict[int, Dict[str, Any]]:
        """Analysiert Trades nach Tageszeit (Stunde)"""
        analysis = {}

        for trade in self._trades:
            hour = trade.entry_time.hour

            if hour not in analysis:
                analysis[hour] = {
                    'total_trades': 0,
                    'winning': 0,
                    'losing': 0,
                    'total_pnl': 0.0,
                    'win_rate': 0.0,
                }

            data = analysis[hour]
            data['total_trades'] += 1
            data['total_pnl'] += trade.net_pnl

            if trade.net_pnl > 0:
                data['winning'] += 1
            elif trade.net_pnl < 0:
                data['losing'] += 1

        for hour, data in analysis.items():
            if data['total_trades'] > 0:
                data['win_rate'] = data['winning'] / data['total_trades'] * 100

        return analysis

    def get_decision_analysis(self) -> Dict[str, Dict[str, Any]]:
        """Analysiert Entscheidungsqualität nach Typ"""
        analysis = {}

        for decision in self._decisions:
            dtype = decision.decision_type.value

            if dtype not in analysis:
                analysis[dtype] = {
                    'total': 0,
                    'correct': 0,
                    'incorrect': 0,
                    'neutral': 0,
                    'missed': 0,
                    'pending': 0,
                    'accuracy': 0.0,
                }

            data = analysis[dtype]
            data['total'] += 1
            data[decision.outcome.value.lower()] += 1

        # Accuracy berechnen
        for dtype, data in analysis.items():
            evaluated = data['total'] - data['pending']
            if evaluated > 0:
                data['accuracy'] = data['correct'] / evaluated * 100

        return analysis

    # ==================== STATE ====================

    def set_starting_equity(self, equity: float):
        """Setzt Start-Eigenkapital"""
        self._starting_equity = equity
        self._current_equity = equity
        self._equity_curve.append((datetime.now(), equity))

    def reset(self):
        """Setzt Tracker zurück"""
        with self._lock:
            self._decisions.clear()
            self._trades.clear()
            self._open_trades.clear()
            self._equity_curve.clear()
            self._daily_pnl.clear()
            self._pending_evaluations.clear()
            self._decision_counter = 0
            self._trade_counter = 0
            self._current_equity = self._starting_equity

    def to_dict(self) -> dict:
        """Serialisiert Tracker"""
        return {
            'decisions': [d.to_dict() for d in list(self._decisions)[-100:]],
            'trades': [t.to_dict() for t in list(self._trades)[-100:]],
            'open_trades': [t.to_dict() for t in self._open_trades.values()],
            'equity_curve': [(t.isoformat(), e) for t, e in list(self._equity_curve)[-100:]],
            'daily_pnl': self._daily_pnl,
            'starting_equity': self._starting_equity,
            'current_equity': self._current_equity,
        }

    def save(self, filepath: str):
        """Speichert Tracker in Datei"""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    def get_summary(self) -> dict:
        """Gibt Zusammenfassung zurück"""
        metrics = self.calculate_metrics()
        return {
            'metrics': metrics.to_dict(),
            'trade_by_level': self.get_trade_analysis_by_level(),
            'trade_by_time': self.get_trade_analysis_by_time(),
            'decision_quality': self.get_decision_analysis(),
            'current_equity': self._current_equity,
            'open_trades_count': len(self._open_trades),
        }
