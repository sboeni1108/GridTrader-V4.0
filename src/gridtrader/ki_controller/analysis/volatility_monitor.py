"""
Volatility Monitor

Überwacht und analysiert die Volatilität von Symbolen in Echtzeit.
Berechnet ATR (Average True Range) und bestimmt das Volatilitäts-Regime.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import deque
import statistics

from ..config import VolatilityRegime


@dataclass
class Candle:
    """Eine einzelne Kerze (OHLCV)"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    @property
    def range(self) -> float:
        """Absolute Range (High - Low)"""
        return self.high - self.low

    @property
    def range_pct(self) -> float:
        """Range als Prozent vom Open"""
        if self.open > 0:
            return (self.range / self.open) * 100
        return 0.0

    @property
    def body(self) -> float:
        """Körper der Kerze (Close - Open)"""
        return self.close - self.open

    @property
    def body_pct(self) -> float:
        """Körper als Prozent vom Open"""
        if self.open > 0:
            return (self.body / self.open) * 100
        return 0.0

    @property
    def is_bullish(self) -> bool:
        """Ist die Kerze bullish (grün)?"""
        return self.close > self.open

    @property
    def upper_wick(self) -> float:
        """Oberer Docht"""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Unterer Docht"""
        return min(self.open, self.close) - self.low

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'range_pct': self.range_pct,
        }


@dataclass
class VolatilitySnapshot:
    """Snapshot der aktuellen Volatilitäts-Analyse"""
    symbol: str
    timestamp: datetime

    # ATR Werte (als Prozent vom Preis)
    atr_5: float = 0.0       # 5-Perioden ATR
    atr_14: float = 0.0      # 14-Perioden ATR (Standard)
    atr_50: float = 0.0      # 50-Perioden ATR (langfristig)

    # Kerzen-Statistiken
    avg_candle_range_pct: float = 0.0
    max_candle_range_pct: float = 0.0
    min_candle_range_pct: float = 0.0

    # Aktueller Zustand
    current_price: float = 0.0
    price_change_1min: float = 0.0
    price_change_5min: float = 0.0
    price_change_15min: float = 0.0

    # Regime
    regime: VolatilityRegime = VolatilityRegime.UNKNOWN
    regime_confidence: float = 0.0  # 0-1, wie sicher die Einschätzung ist

    # Trend
    is_expanding: bool = False  # Volatilität steigt
    is_contracting: bool = False  # Volatilität sinkt

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'atr_5': self.atr_5,
            'atr_14': self.atr_14,
            'atr_50': self.atr_50,
            'avg_candle_range_pct': self.avg_candle_range_pct,
            'max_candle_range_pct': self.max_candle_range_pct,
            'min_candle_range_pct': self.min_candle_range_pct,
            'current_price': self.current_price,
            'price_change_1min': self.price_change_1min,
            'price_change_5min': self.price_change_5min,
            'price_change_15min': self.price_change_15min,
            'regime': self.regime.value,
            'regime_confidence': self.regime_confidence,
            'is_expanding': self.is_expanding,
            'is_contracting': self.is_contracting,
        }


class VolatilityMonitor:
    """
    Überwacht die Volatilität für ein oder mehrere Symbole.

    Verwendet:
    - ATR (Average True Range) für absolute Volatilität
    - Kerzen-Range für kurzfristige Bewegungen
    - Rolling Windows für verschiedene Zeiträume
    """

    def __init__(
        self,
        atr_period_short: int = 5,
        atr_period_medium: int = 14,
        atr_period_long: int = 50,
        candle_buffer_size: int = 100,
    ):
        """
        Args:
            atr_period_short: Perioden für kurzfristigen ATR
            atr_period_medium: Perioden für mittelfristigen ATR
            atr_period_long: Perioden für langfristigen ATR
            candle_buffer_size: Maximale Anzahl Kerzen pro Symbol
        """
        self._atr_short = atr_period_short
        self._atr_medium = atr_period_medium
        self._atr_long = atr_period_long
        self._buffer_size = candle_buffer_size

        # Kerzen-Buffer pro Symbol
        self._candles: Dict[str, deque] = {}

        # Preis-Historie für schnelle Änderungsberechnung
        self._price_history: Dict[str, deque] = {}

        # True Range Historie für ATR
        self._true_ranges: Dict[str, deque] = {}

        # Letzte Snapshots
        self._snapshots: Dict[str, VolatilitySnapshot] = {}

        # Regime-Schwellwerte (konfigurierbar)
        self._regime_thresholds = {
            'high_atr': 1.5,      # ATR > 1.5% = HIGH
            'medium_atr': 0.5,    # ATR > 0.5% = MEDIUM
            'low_atr': 0.0,       # ATR > 0% = LOW

            'high_range': 2.0,    # Kerzen-Range > 2% = HIGH
            'medium_range': 0.8,  # Kerzen-Range > 0.8% = MEDIUM
        }

    def add_candle(self, symbol: str, candle: Candle) -> VolatilitySnapshot:
        """
        Fügt eine neue Kerze hinzu und aktualisiert die Analyse.

        Args:
            symbol: Symbol der Aktie
            candle: Kerzen-Daten

        Returns:
            Aktualisierter VolatilitySnapshot
        """
        # Buffer initialisieren wenn nötig
        if symbol not in self._candles:
            self._candles[symbol] = deque(maxlen=self._buffer_size)
            self._true_ranges[symbol] = deque(maxlen=self._buffer_size)
            self._price_history[symbol] = deque(maxlen=1000)

        candles = self._candles[symbol]
        true_ranges = self._true_ranges[symbol]

        # True Range berechnen
        if len(candles) > 0:
            prev_candle = candles[-1]
            tr = self._calculate_true_range(candle, prev_candle.close)
        else:
            tr = candle.range

        # Hinzufügen
        candles.append(candle)
        true_ranges.append(tr)

        # Preis-Historie aktualisieren
        self._price_history[symbol].append((candle.timestamp, candle.close))

        # Snapshot aktualisieren
        return self._update_snapshot(symbol, candle)

    def add_tick(self, symbol: str, price: float, timestamp: Optional[datetime] = None):
        """
        Fügt einen einzelnen Tick hinzu (für Preis-Änderungsberechnung).

        Args:
            symbol: Symbol
            price: Aktueller Preis
            timestamp: Zeitstempel (default: jetzt)
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Timezone-naive machen für konsistente Vergleiche
        if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)

        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=1000)

        self._price_history[symbol].append((timestamp, price))

    def get_snapshot(self, symbol: str) -> Optional[VolatilitySnapshot]:
        """Gibt den letzten Snapshot für ein Symbol zurück."""
        return self._snapshots.get(symbol)

    def get_regime(self, symbol: str) -> VolatilityRegime:
        """Gibt das aktuelle Volatilitäts-Regime zurück."""
        snapshot = self._snapshots.get(symbol)
        if snapshot:
            return snapshot.regime
        return VolatilityRegime.UNKNOWN

    def get_atr(self, symbol: str, period: str = 'medium') -> float:
        """
        Gibt den ATR für ein Symbol zurück.

        Args:
            symbol: Symbol
            period: 'short', 'medium', oder 'long'
        """
        snapshot = self._snapshots.get(symbol)
        if not snapshot:
            return 0.0

        if period == 'short':
            return snapshot.atr_5
        elif period == 'long':
            return snapshot.atr_50
        else:
            return snapshot.atr_14

    def is_high_volatility(self, symbol: str) -> bool:
        """Prüft ob hohe Volatilität vorliegt."""
        return self.get_regime(symbol) == VolatilityRegime.HIGH

    def is_low_volatility(self, symbol: str) -> bool:
        """Prüft ob niedrige Volatilität vorliegt."""
        return self.get_regime(symbol) == VolatilityRegime.LOW

    def get_recommended_step_range(self, symbol: str) -> Tuple[float, float]:
        """
        Gibt empfohlene Step-Größe basierend auf Volatilität zurück.

        Returns:
            Tuple (min_step_pct, max_step_pct)
        """
        regime = self.get_regime(symbol)
        atr = self.get_atr(symbol, 'medium')

        if regime == VolatilityRegime.HIGH:
            # Bei hoher Volatilität: größere Steps
            return (max(0.5, atr * 0.5), max(1.5, atr * 1.2))
        elif regime == VolatilityRegime.MEDIUM:
            # Bei mittlerer Volatilität: moderate Steps
            return (max(0.3, atr * 0.4), max(0.8, atr * 0.8))
        elif regime == VolatilityRegime.LOW:
            # Bei niedriger Volatilität: kleine Steps
            return (0.15, max(0.4, atr * 0.6))
        else:
            # Unbekannt: konservativ
            return (0.3, 0.8)

    # ==================== PRIVATE METHODS ====================

    def _calculate_true_range(self, candle: Candle, prev_close: float) -> float:
        """
        Berechnet True Range.

        TR = max(
            High - Low,
            |High - Previous Close|,
            |Low - Previous Close|
        )
        """
        return max(
            candle.high - candle.low,
            abs(candle.high - prev_close),
            abs(candle.low - prev_close)
        )

    def _calculate_atr(self, true_ranges: deque, period: int) -> float:
        """Berechnet ATR über die letzten N Perioden."""
        if len(true_ranges) < period:
            if len(true_ranges) == 0:
                return 0.0
            period = len(true_ranges)

        recent = list(true_ranges)[-period:]
        return sum(recent) / len(recent)

    def _calculate_atr_pct(self, atr: float, current_price: float) -> float:
        """Konvertiert ATR in Prozent vom aktuellen Preis."""
        if current_price > 0:
            return (atr / current_price) * 100
        return 0.0

    def _calculate_price_change(
        self,
        history: deque,
        current_price: float,
        minutes: int
    ) -> float:
        """Berechnet Preisänderung über X Minuten."""
        if not history or current_price <= 0:
            return 0.0

        cutoff = datetime.now() - timedelta(minutes=minutes)

        # Finde ältesten Preis innerhalb des Zeitfensters
        old_price = None
        for ts, price in history:
            # Timezone-naive machen für Vergleich
            ts_naive = ts.replace(tzinfo=None) if hasattr(ts, 'tzinfo') and ts.tzinfo else ts
            if ts_naive >= cutoff:
                old_price = price
                break

        if old_price and old_price > 0:
            return ((current_price - old_price) / old_price) * 100

        return 0.0

    def _update_snapshot(self, symbol: str, candle: Candle) -> VolatilitySnapshot:
        """Aktualisiert den Snapshot für ein Symbol."""
        candles = self._candles[symbol]
        true_ranges = self._true_ranges[symbol]
        price_history = self._price_history[symbol]

        # ATR berechnen
        atr_5_abs = self._calculate_atr(true_ranges, self._atr_short)
        atr_14_abs = self._calculate_atr(true_ranges, self._atr_medium)
        atr_50_abs = self._calculate_atr(true_ranges, self._atr_long)

        current_price = candle.close

        # ATR als Prozent
        atr_5 = self._calculate_atr_pct(atr_5_abs, current_price)
        atr_14 = self._calculate_atr_pct(atr_14_abs, current_price)
        atr_50 = self._calculate_atr_pct(atr_50_abs, current_price)

        # Kerzen-Statistiken
        recent_candles = list(candles)[-20:]  # Letzte 20 Kerzen
        ranges = [c.range_pct for c in recent_candles]

        if ranges:
            avg_range = statistics.mean(ranges)
            max_range = max(ranges)
            min_range = min(ranges)
        else:
            avg_range = max_range = min_range = 0.0

        # Preisänderungen
        price_change_1 = self._calculate_price_change(price_history, current_price, 1)
        price_change_5 = self._calculate_price_change(price_history, current_price, 5)
        price_change_15 = self._calculate_price_change(price_history, current_price, 15)

        # Regime bestimmen
        regime, confidence = self._determine_regime(
            atr_14, avg_range, price_change_5
        )

        # Trend (expandierend/kontrahierend)
        is_expanding = atr_5 > atr_14 > atr_50
        is_contracting = atr_5 < atr_14 < atr_50

        # Snapshot erstellen
        snapshot = VolatilitySnapshot(
            symbol=symbol,
            timestamp=datetime.now(),
            atr_5=atr_5,
            atr_14=atr_14,
            atr_50=atr_50,
            avg_candle_range_pct=avg_range,
            max_candle_range_pct=max_range,
            min_candle_range_pct=min_range,
            current_price=current_price,
            price_change_1min=price_change_1,
            price_change_5min=price_change_5,
            price_change_15min=price_change_15,
            regime=regime,
            regime_confidence=confidence,
            is_expanding=is_expanding,
            is_contracting=is_contracting,
        )

        self._snapshots[symbol] = snapshot
        return snapshot

    def _determine_regime(
        self,
        atr: float,
        avg_range: float,
        price_change_5: float
    ) -> Tuple[VolatilityRegime, float]:
        """
        Bestimmt das Volatilitäts-Regime.

        Kombiniert ATR, Kerzen-Range und Preisbewegung.
        """
        # Scoring für jedes Regime
        high_score = 0.0
        medium_score = 0.0
        low_score = 0.0

        # ATR-basiertes Scoring
        if atr >= self._regime_thresholds['high_atr']:
            high_score += 40
        elif atr >= self._regime_thresholds['medium_atr']:
            medium_score += 30
            high_score += 10
        else:
            low_score += 40

        # Range-basiertes Scoring
        if avg_range >= self._regime_thresholds['high_range']:
            high_score += 35
        elif avg_range >= self._regime_thresholds['medium_range']:
            medium_score += 25
            high_score += 10
        else:
            low_score += 35

        # Preisbewegung Scoring
        abs_change = abs(price_change_5)
        if abs_change >= 1.0:
            high_score += 25
        elif abs_change >= 0.3:
            medium_score += 20
        else:
            low_score += 25

        # Regime bestimmen
        total = high_score + medium_score + low_score
        if total == 0:
            return VolatilityRegime.UNKNOWN, 0.0

        if high_score >= medium_score and high_score >= low_score:
            return VolatilityRegime.HIGH, high_score / total
        elif medium_score >= low_score:
            return VolatilityRegime.MEDIUM, medium_score / total
        else:
            return VolatilityRegime.LOW, low_score / total

    def set_regime_thresholds(
        self,
        high_atr: Optional[float] = None,
        medium_atr: Optional[float] = None,
        high_range: Optional[float] = None,
        medium_range: Optional[float] = None
    ):
        """Erlaubt Anpassung der Regime-Schwellwerte."""
        if high_atr is not None:
            self._regime_thresholds['high_atr'] = high_atr
        if medium_atr is not None:
            self._regime_thresholds['medium_atr'] = medium_atr
        if high_range is not None:
            self._regime_thresholds['high_range'] = high_range
        if medium_range is not None:
            self._regime_thresholds['medium_range'] = medium_range

    def clear_symbol(self, symbol: str):
        """Löscht alle Daten für ein Symbol."""
        if symbol in self._candles:
            del self._candles[symbol]
        if symbol in self._true_ranges:
            del self._true_ranges[symbol]
        if symbol in self._price_history:
            del self._price_history[symbol]
        if symbol in self._snapshots:
            del self._snapshots[symbol]

    def get_candle_history(self, symbol: str, count: int = 20) -> List[Candle]:
        """Gibt die letzten N Kerzen für ein Symbol zurück."""
        if symbol not in self._candles:
            return []
        return list(self._candles[symbol])[-count:]
