"""
Volume Analyzer

Analysiert Volumen-Daten zur Erkennung von:
- Volumen-Spikes (ungewöhnlich hohes Volumen)
- Volumen-Trends (steigend/fallend)
- Volumen-Anomalien (potenzieller Indikator für News/Events)
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import deque
from enum import Enum
import statistics


class VolumeCondition(str, Enum):
    """Volumen-Zustand"""
    VERY_LOW = "VERY_LOW"      # < 50% des Durchschnitts
    LOW = "LOW"                # 50-80% des Durchschnitts
    NORMAL = "NORMAL"          # 80-120% des Durchschnitts
    HIGH = "HIGH"              # 120-200% des Durchschnitts
    SPIKE = "SPIKE"            # > 200% des Durchschnitts
    EXTREME = "EXTREME"        # > 300% des Durchschnitts


class VolumeTrend(str, Enum):
    """Volumen-Trend"""
    INCREASING = "INCREASING"
    STABLE = "STABLE"
    DECREASING = "DECREASING"


@dataclass
class VolumeSnapshot:
    """Snapshot der aktuellen Volumen-Analyse"""
    symbol: str
    timestamp: datetime

    # Absolute Werte
    current_volume: int = 0           # Letztes 1-Min Volumen
    volume_5min: int = 0              # Summe letzte 5 Min
    volume_15min: int = 0             # Summe letzte 15 Min
    volume_today: int = 0             # Gesamtes Tages-Volumen

    # Durchschnitte
    volume_ma_20: float = 0.0         # 20-Perioden Moving Average
    volume_ma_50: float = 0.0         # 50-Perioden Moving Average

    # Relative Werte
    volume_ratio: float = 1.0         # Aktuell / MA (1.0 = normal)
    volume_percentile: float = 50.0   # Wo liegt aktuelles Vol. im Vergleich (0-100)

    # Zustand
    condition: VolumeCondition = VolumeCondition.NORMAL
    trend: VolumeTrend = VolumeTrend.STABLE

    # Anomalie-Detection
    is_spike: bool = False
    spike_magnitude: float = 0.0      # Um wie viel höher als normal
    consecutive_high_volume: int = 0   # Anzahl aufeinanderfolgender hoher Vol.-Kerzen

    # Preis-Volumen Korrelation
    price_volume_correlation: float = 0.0  # -1 bis +1

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'current_volume': self.current_volume,
            'volume_5min': self.volume_5min,
            'volume_15min': self.volume_15min,
            'volume_today': self.volume_today,
            'volume_ma_20': self.volume_ma_20,
            'volume_ma_50': self.volume_ma_50,
            'volume_ratio': self.volume_ratio,
            'volume_percentile': self.volume_percentile,
            'condition': self.condition.value,
            'trend': self.trend.value,
            'is_spike': self.is_spike,
            'spike_magnitude': self.spike_magnitude,
            'consecutive_high_volume': self.consecutive_high_volume,
            'price_volume_correlation': self.price_volume_correlation,
        }


class VolumeAnalyzer:
    """
    Analysiert Volumen-Daten für Trading-Entscheidungen.

    Erkennt:
    - Ungewöhnliches Volumen (Spikes)
    - Volumen-Trends
    - Preis-Volumen Divergenzen
    """

    def __init__(
        self,
        ma_period_short: int = 20,
        ma_period_long: int = 50,
        spike_threshold: float = 2.0,
        extreme_threshold: float = 3.0,
        buffer_size: int = 100,
    ):
        """
        Args:
            ma_period_short: Perioden für kurzfristigen MA
            ma_period_long: Perioden für langfristigen MA
            spike_threshold: Ab welchem Vielfachen des MA = Spike
            extreme_threshold: Ab welchem Vielfachen = Extrem
            buffer_size: Maximale Anzahl gespeicherter Werte
        """
        self._ma_short = ma_period_short
        self._ma_long = ma_period_long
        self._spike_threshold = spike_threshold
        self._extreme_threshold = extreme_threshold
        self._buffer_size = buffer_size

        # Volume-Buffer pro Symbol: (timestamp, volume, price_change)
        self._volume_history: Dict[str, deque] = {}

        # Tages-Volumen Tracking
        self._daily_volume: Dict[str, int] = {}
        self._daily_date: Dict[str, datetime] = {}

        # Letzte Snapshots
        self._snapshots: Dict[str, VolumeSnapshot] = {}

        # Spike-Tracking
        self._consecutive_high: Dict[str, int] = {}

    def add_volume(
        self,
        symbol: str,
        volume: int,
        price_change_pct: float = 0.0,
        timestamp: Optional[datetime] = None
    ) -> VolumeSnapshot:
        """
        Fügt einen neuen Volumen-Datenpunkt hinzu.

        Args:
            symbol: Symbol der Aktie
            volume: Volumen (z.B. 1-Minuten-Volumen)
            price_change_pct: Preisänderung in % (für Korrelation)
            timestamp: Zeitstempel (default: jetzt)

        Returns:
            Aktualisierter VolumeSnapshot
        """
        if timestamp is None:
            timestamp = datetime.now()

        # Buffer initialisieren
        if symbol not in self._volume_history:
            self._volume_history[symbol] = deque(maxlen=self._buffer_size)
            self._consecutive_high[symbol] = 0

        # Tages-Volumen zurücksetzen bei neuem Tag
        today = timestamp.date()
        if symbol not in self._daily_date or self._daily_date[symbol].date() != today:
            self._daily_volume[symbol] = 0
            self._daily_date[symbol] = timestamp

        # Hinzufügen
        self._volume_history[symbol].append((timestamp, volume, price_change_pct))
        self._daily_volume[symbol] = self._daily_volume.get(symbol, 0) + volume

        # Snapshot aktualisieren
        return self._update_snapshot(symbol, volume, price_change_pct, timestamp)

    def get_snapshot(self, symbol: str) -> Optional[VolumeSnapshot]:
        """Gibt den letzten Snapshot zurück."""
        return self._snapshots.get(symbol)

    def get_condition(self, symbol: str) -> VolumeCondition:
        """Gibt den aktuellen Volumen-Zustand zurück."""
        snapshot = self._snapshots.get(symbol)
        return snapshot.condition if snapshot else VolumeCondition.NORMAL

    def is_spike(self, symbol: str) -> bool:
        """Prüft ob aktuell ein Volumen-Spike vorliegt."""
        snapshot = self._snapshots.get(symbol)
        return snapshot.is_spike if snapshot else False

    def is_high_volume(self, symbol: str) -> bool:
        """Prüft ob das Volumen überdurchschnittlich ist."""
        condition = self.get_condition(symbol)
        return condition in (VolumeCondition.HIGH, VolumeCondition.SPIKE, VolumeCondition.EXTREME)

    def is_low_volume(self, symbol: str) -> bool:
        """Prüft ob das Volumen unterdurchschnittlich ist."""
        condition = self.get_condition(symbol)
        return condition in (VolumeCondition.LOW, VolumeCondition.VERY_LOW)

    def get_volume_ratio(self, symbol: str) -> float:
        """Gibt das Verhältnis aktuelles Volumen / Durchschnitt zurück."""
        snapshot = self._snapshots.get(symbol)
        return snapshot.volume_ratio if snapshot else 1.0

    def should_pause_trading(self, symbol: str) -> Tuple[bool, str]:
        """
        Prüft ob Trading pausiert werden sollte basierend auf Volumen.

        Returns:
            (should_pause, reason)
        """
        snapshot = self._snapshots.get(symbol)
        if not snapshot:
            return False, ""

        # Bei extremem Volumen (mögliche News) → Pause empfohlen
        if snapshot.condition == VolumeCondition.EXTREME:
            return True, f"Extremes Volumen ({snapshot.spike_magnitude:.1f}x normal)"

        # Bei anhaltendem hohen Volumen → Vorsicht
        if snapshot.consecutive_high_volume >= 5:
            return True, f"Anhaltendes hohes Volumen ({snapshot.consecutive_high_volume} Kerzen)"

        return False, ""

    # ==================== PRIVATE METHODS ====================

    def _update_snapshot(
        self,
        symbol: str,
        current_volume: int,
        price_change_pct: float,
        timestamp: datetime
    ) -> VolumeSnapshot:
        """Aktualisiert den Snapshot für ein Symbol."""
        history = self._volume_history[symbol]

        # Moving Averages berechnen
        volumes = [v for _, v, _ in history]

        ma_20 = self._calculate_ma(volumes, self._ma_short)
        ma_50 = self._calculate_ma(volumes, self._ma_long)

        # Volume Summen für verschiedene Zeiträume
        volume_5min = self._sum_volume_minutes(history, 5, timestamp)
        volume_15min = self._sum_volume_minutes(history, 15, timestamp)

        # Volume Ratio
        volume_ratio = current_volume / ma_20 if ma_20 > 0 else 1.0

        # Percentile berechnen
        percentile = self._calculate_percentile(volumes, current_volume)

        # Condition bestimmen
        condition = self._determine_condition(volume_ratio)

        # Spike Detection
        is_spike = volume_ratio >= self._spike_threshold
        spike_magnitude = volume_ratio if is_spike else 0.0

        # Consecutive High Volume
        if condition in (VolumeCondition.HIGH, VolumeCondition.SPIKE, VolumeCondition.EXTREME):
            self._consecutive_high[symbol] = self._consecutive_high.get(symbol, 0) + 1
        else:
            self._consecutive_high[symbol] = 0

        # Trend bestimmen
        trend = self._determine_trend(history)

        # Preis-Volumen Korrelation
        correlation = self._calculate_price_volume_correlation(history)

        # Snapshot erstellen
        snapshot = VolumeSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            current_volume=current_volume,
            volume_5min=volume_5min,
            volume_15min=volume_15min,
            volume_today=self._daily_volume.get(symbol, 0),
            volume_ma_20=ma_20,
            volume_ma_50=ma_50,
            volume_ratio=volume_ratio,
            volume_percentile=percentile,
            condition=condition,
            trend=trend,
            is_spike=is_spike,
            spike_magnitude=spike_magnitude,
            consecutive_high_volume=self._consecutive_high.get(symbol, 0),
            price_volume_correlation=correlation,
        )

        self._snapshots[symbol] = snapshot
        return snapshot

    def _calculate_ma(self, values: List[int], period: int) -> float:
        """Berechnet Moving Average."""
        if not values:
            return 0.0
        period = min(period, len(values))
        return sum(values[-period:]) / period

    def _sum_volume_minutes(
        self,
        history: deque,
        minutes: int,
        current_time: datetime
    ) -> int:
        """Summiert Volumen über X Minuten."""
        cutoff = current_time - timedelta(minutes=minutes)
        total = 0
        for ts, vol, _ in history:
            if ts >= cutoff:
                total += vol
        return total

    def _calculate_percentile(self, values: List[int], current: int) -> float:
        """Berechnet in welchem Percentil der aktuelle Wert liegt."""
        if not values or len(values) < 2:
            return 50.0

        count_below = sum(1 for v in values if v < current)
        return (count_below / len(values)) * 100

    def _determine_condition(self, ratio: float) -> VolumeCondition:
        """Bestimmt den Volumen-Zustand basierend auf Ratio."""
        if ratio >= self._extreme_threshold:
            return VolumeCondition.EXTREME
        elif ratio >= self._spike_threshold:
            return VolumeCondition.SPIKE
        elif ratio >= 1.2:
            return VolumeCondition.HIGH
        elif ratio >= 0.8:
            return VolumeCondition.NORMAL
        elif ratio >= 0.5:
            return VolumeCondition.LOW
        else:
            return VolumeCondition.VERY_LOW

    def _determine_trend(self, history: deque) -> VolumeTrend:
        """Bestimmt den Volumen-Trend (steigend/fallend/stabil)."""
        if len(history) < 10:
            return VolumeTrend.STABLE

        # Vergleiche Durchschnitt der letzten 5 vs. vorherige 5
        recent = [v for _, v, _ in list(history)[-5:]]
        previous = [v for _, v, _ in list(history)[-10:-5]]

        if not recent or not previous:
            return VolumeTrend.STABLE

        recent_avg = sum(recent) / len(recent)
        previous_avg = sum(previous) / len(previous)

        if previous_avg == 0:
            return VolumeTrend.STABLE

        change = (recent_avg - previous_avg) / previous_avg

        if change > 0.2:
            return VolumeTrend.INCREASING
        elif change < -0.2:
            return VolumeTrend.DECREASING
        else:
            return VolumeTrend.STABLE

    def _calculate_price_volume_correlation(self, history: deque) -> float:
        """
        Berechnet Korrelation zwischen Preisänderung und Volumen.

        Positive Korrelation: Preis und Volumen bewegen sich zusammen
        Negative Korrelation: Divergenz (potenzielles Warnsignal)
        """
        if len(history) < 10:
            return 0.0

        recent = list(history)[-20:]
        volumes = [v for _, v, _ in recent]
        price_changes = [p for _, _, p in recent]

        if not volumes or not price_changes:
            return 0.0

        try:
            # Einfache Pearson-Korrelation
            n = len(volumes)
            mean_vol = sum(volumes) / n
            mean_price = sum(price_changes) / n

            numerator = sum(
                (v - mean_vol) * (p - mean_price)
                for v, p in zip(volumes, price_changes)
            )

            std_vol = (sum((v - mean_vol) ** 2 for v in volumes) / n) ** 0.5
            std_price = (sum((p - mean_price) ** 2 for p in price_changes) / n) ** 0.5

            if std_vol == 0 or std_price == 0:
                return 0.0

            return numerator / (n * std_vol * std_price)

        except Exception:
            return 0.0

    def clear_symbol(self, symbol: str):
        """Löscht alle Daten für ein Symbol."""
        if symbol in self._volume_history:
            del self._volume_history[symbol]
        if symbol in self._daily_volume:
            del self._daily_volume[symbol]
        if symbol in self._daily_date:
            del self._daily_date[symbol]
        if symbol in self._snapshots:
            del self._snapshots[symbol]
        if symbol in self._consecutive_high:
            del self._consecutive_high[symbol]

    def reset_daily(self, symbol: Optional[str] = None):
        """Setzt tägliche Statistiken zurück."""
        if symbol:
            self._daily_volume[symbol] = 0
        else:
            self._daily_volume.clear()
