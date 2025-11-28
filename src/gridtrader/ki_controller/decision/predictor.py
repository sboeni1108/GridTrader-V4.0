"""
Price Predictor

Kombiniert verschiedene Signale für Vorhersagen:
- Historische Muster (Pattern Matcher)
- Volatilitäts-Trends
- Volumen-Signale
- Tageszeit-basierte Tendenzen
- Momentum-Indikatoren

Gibt probabilistische Vorhersagen für verschiedene Zeiträume.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from collections import deque
import statistics


class PredictionTimeframe(str, Enum):
    """Vorhersage-Zeiträume"""
    MINUTES_5 = "5min"
    MINUTES_15 = "15min"
    MINUTES_30 = "30min"
    HOUR_1 = "1h"


class DirectionBias(str, Enum):
    """Richtungs-Tendenz"""
    STRONG_UP = "STRONG_UP"
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"


@dataclass
class MovementPrediction:
    """Vorhersage für eine Preisbewegung"""
    timeframe: PredictionTimeframe
    direction: DirectionBias
    expected_change_pct: float       # Erwartete Änderung in %
    confidence: float                # Konfidenz (0-1)
    range_low_pct: float = 0.0       # Untere Erwartung
    range_high_pct: float = 0.0      # Obere Erwartung

    # Komponenten der Vorhersage
    pattern_signal: float = 0.0      # -1 bis +1
    volume_signal: float = 0.0       # -1 bis +1
    momentum_signal: float = 0.0     # -1 bis +1
    time_signal: float = 0.0         # -1 bis +1

    def to_dict(self) -> dict:
        return {
            'timeframe': self.timeframe.value,
            'direction': self.direction.value,
            'expected_change_pct': self.expected_change_pct,
            'confidence': self.confidence,
            'range_low_pct': self.range_low_pct,
            'range_high_pct': self.range_high_pct,
            'signals': {
                'pattern': self.pattern_signal,
                'volume': self.volume_signal,
                'momentum': self.momentum_signal,
                'time': self.time_signal,
            }
        }


@dataclass
class PredictionContext:
    """Kontext für Vorhersagen"""
    symbol: str
    current_price: float
    timestamp: datetime = field(default_factory=datetime.now)

    # Volatilität
    atr_5: float = 0.0
    atr_14: float = 0.0
    volatility_regime: str = "MEDIUM"

    # Volumen
    volume_ratio: float = 1.0
    volume_condition: str = "NORMAL"
    volume_trend: str = "STABLE"     # INCREASING/STABLE/DECREASING

    # Trends
    price_change_1min: float = 0.0
    price_change_5min: float = 0.0
    price_change_15min: float = 0.0

    # Tageszeit
    trading_phase: str = "MIDDAY"
    minutes_since_open: int = 0

    # Pattern Matcher Ergebnisse
    pattern_prediction: Optional[str] = None
    pattern_confidence: float = 0.0
    expected_5min_change: float = 0.0
    expected_15min_change: float = 0.0


@dataclass
class PredictionResult:
    """Vollständiges Vorhersage-Ergebnis"""
    symbol: str
    timestamp: datetime
    predictions: Dict[PredictionTimeframe, MovementPrediction] = field(default_factory=dict)

    # Zusammenfassung
    dominant_direction: DirectionBias = DirectionBias.NEUTRAL
    average_confidence: float = 0.0

    # Empfehlungen
    suggested_action: str = "HOLD"   # BUY/SELL/HOLD
    action_confidence: float = 0.0
    action_reason: str = ""

    def get_prediction(self, timeframe: PredictionTimeframe) -> Optional[MovementPrediction]:
        return self.predictions.get(timeframe)

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timestamp': self.timestamp.isoformat(),
            'predictions': {k.value: v.to_dict() for k, v in self.predictions.items()},
            'dominant_direction': self.dominant_direction.value,
            'average_confidence': self.average_confidence,
            'suggested_action': self.suggested_action,
            'action_confidence': self.action_confidence,
            'action_reason': self.action_reason,
        }


class PricePredictor:
    """
    Kombiniert verschiedene Signale für Preisvorhersagen.

    Verwendet:
    - Historische Pattern-Matches
    - Volumen-Analyse
    - Momentum (Preisänderungen)
    - Tageszeit-Profile
    - Volatilitäts-Kontext
    """

    def __init__(self, history_size: int = 100):
        self._history_size = history_size

        # Historische Vorhersagen für Tracking
        self._prediction_history: Dict[str, deque] = {}

        # Gewichtungen für Signal-Kombination
        self._weights = {
            'pattern': 0.35,
            'momentum': 0.30,
            'volume': 0.20,
            'time': 0.15,
        }

        # Phasen-basierte Bewegungstendenzen
        self._phase_tendencies = {
            "PRE_MARKET": 0.0,       # Keine klare Tendenz
            "MARKET_OPEN": 0.1,      # Leicht bullish (Gap-fills)
            "MORNING": 0.05,         # Tendenz zur Trendfortsetzung
            "MIDDAY": 0.0,           # Neutral, geringe Bewegung
            "AFTERNOON": 0.0,        # Neutral
            "POWER_HOUR": -0.05,     # Leicht erhöhte Volatilität
            "CLOSE": -0.1,           # Oft Gewinnmitnahmen
            "AFTER_HOURS": 0.0,      # Unvorhersehbar
        }

    def predict(self, context: PredictionContext) -> PredictionResult:
        """
        Erstellt Vorhersagen für alle Zeiträume.

        Args:
            context: Aktueller Marktkontext

        Returns:
            PredictionResult mit Vorhersagen für 5min, 15min, 30min, 1h
        """
        result = PredictionResult(
            symbol=context.symbol,
            timestamp=context.timestamp,
        )

        # Vorhersagen für jeden Zeitraum
        for timeframe in PredictionTimeframe:
            prediction = self._predict_timeframe(context, timeframe)
            result.predictions[timeframe] = prediction

        # Zusammenfassung berechnen
        self._summarize_predictions(result)

        # Tracking
        self._record_prediction(context.symbol, result)

        return result

    def predict_single(
        self,
        context: PredictionContext,
        timeframe: PredictionTimeframe
    ) -> MovementPrediction:
        """Vorhersage für einen einzelnen Zeitraum"""
        return self._predict_timeframe(context, timeframe)

    def get_direction_for_trade(
        self,
        context: PredictionContext,
        min_confidence: float = 0.5
    ) -> Tuple[DirectionBias, float]:
        """
        Gibt die empfohlene Handelsrichtung zurück.

        Returns:
            (Richtung, Konfidenz)
        """
        result = self.predict(context)

        # Fokus auf 5min und 15min für kurzfristigen Handel
        pred_5min = result.predictions.get(PredictionTimeframe.MINUTES_5)
        pred_15min = result.predictions.get(PredictionTimeframe.MINUTES_15)

        if not pred_5min or not pred_15min:
            return DirectionBias.NEUTRAL, 0.0

        # Kombinierte Richtung
        combined_signal = (
            pred_5min.expected_change_pct * 0.6 +
            pred_15min.expected_change_pct * 0.4
        )

        # Kombinierte Konfidenz
        combined_confidence = (
            pred_5min.confidence * 0.6 +
            pred_15min.confidence * 0.4
        )

        if combined_confidence < min_confidence:
            return DirectionBias.NEUTRAL, combined_confidence

        direction = self._signal_to_direction(combined_signal)
        return direction, combined_confidence

    # ==================== SIGNAL BERECHNUNG ====================

    def _predict_timeframe(
        self,
        context: PredictionContext,
        timeframe: PredictionTimeframe
    ) -> MovementPrediction:
        """Berechnet Vorhersage für einen Zeitraum"""

        # Signal-Komponenten berechnen
        pattern_signal = self._calculate_pattern_signal(context, timeframe)
        momentum_signal = self._calculate_momentum_signal(context, timeframe)
        volume_signal = self._calculate_volume_signal(context)
        time_signal = self._calculate_time_signal(context)

        # Gewichtete Kombination
        combined_signal = (
            pattern_signal * self._weights['pattern'] +
            momentum_signal * self._weights['momentum'] +
            volume_signal * self._weights['volume'] +
            time_signal * self._weights['time']
        )

        # Volatilitäts-Skalierung
        volatility_multiplier = self._get_volatility_multiplier(context, timeframe)
        expected_change = combined_signal * volatility_multiplier

        # Konfidenz berechnen
        confidence = self._calculate_confidence(
            pattern_signal, momentum_signal, volume_signal, time_signal,
            context
        )

        # Range berechnen
        range_width = volatility_multiplier * (1 - confidence) * 2
        range_low = expected_change - range_width / 2
        range_high = expected_change + range_width / 2

        # Richtung bestimmen
        direction = self._signal_to_direction(combined_signal)

        return MovementPrediction(
            timeframe=timeframe,
            direction=direction,
            expected_change_pct=expected_change,
            confidence=confidence,
            range_low_pct=range_low,
            range_high_pct=range_high,
            pattern_signal=pattern_signal,
            volume_signal=volume_signal,
            momentum_signal=momentum_signal,
            time_signal=time_signal,
        )

    def _calculate_pattern_signal(
        self,
        context: PredictionContext,
        timeframe: PredictionTimeframe
    ) -> float:
        """
        Berechnet Signal basierend auf Pattern-Match.

        Returns:
            Signal zwischen -1 (bearish) und +1 (bullish)
        """
        if not context.pattern_prediction or context.pattern_confidence < 0.3:
            return 0.0

        # Pattern-basierte Erwartungen
        if timeframe in (PredictionTimeframe.MINUTES_5,):
            expected = context.expected_5min_change
        elif timeframe in (PredictionTimeframe.MINUTES_15, PredictionTimeframe.MINUTES_30):
            expected = context.expected_15min_change
        else:
            expected = context.expected_15min_change * 1.5

        # Normalisieren auf -1 bis +1 (angenommen max 2% Bewegung)
        signal = max(-1, min(1, expected / 2.0))

        # Mit Pattern-Konfidenz skalieren
        return signal * context.pattern_confidence

    def _calculate_momentum_signal(
        self,
        context: PredictionContext,
        timeframe: PredictionTimeframe
    ) -> float:
        """
        Berechnet Momentum-Signal basierend auf Preisänderungen.

        Trend-Continuation vs. Mean-Reversion Logik.
        """
        # Kurzfristiger Momentum
        short_momentum = context.price_change_5min
        # Mittelfristiger Momentum
        medium_momentum = context.price_change_15min

        # Für kürzere Zeiträume: Trend-Continuation
        # Für längere Zeiträume: Mean-Reversion Komponente

        if timeframe == PredictionTimeframe.MINUTES_5:
            # Kurzfristig: Momentum fortsetzen
            signal = short_momentum * 0.5
        elif timeframe == PredictionTimeframe.MINUTES_15:
            # 15min: Mix aus Momentum und leichter Mean-Reversion
            signal = short_momentum * 0.3 + medium_momentum * 0.2
        elif timeframe == PredictionTimeframe.MINUTES_30:
            # 30min: Stärkere Mean-Reversion
            signal = medium_momentum * 0.2 - short_momentum * 0.1
        else:
            # 1h: Mean-Reversion dominiert
            signal = medium_momentum * 0.1 - short_momentum * 0.2

        # Normalisieren (angenommen max 1% kurzfristiger Bewegung)
        return max(-1, min(1, signal))

    def _calculate_volume_signal(self, context: PredictionContext) -> float:
        """
        Berechnet Signal basierend auf Volumen.

        Hohes Volumen = stärkere Bewegung wahrscheinlich
        """
        ratio = context.volume_ratio
        condition = context.volume_condition
        trend = context.volume_trend

        # Basis-Signal von Volumen-Condition
        condition_signals = {
            "VERY_LOW": 0.0,      # Keine klare Richtung
            "LOW": 0.0,
            "NORMAL": 0.0,
            "HIGH": 0.1,          # Leicht positiv (Aktivität)
            "SPIKE": 0.15,        # Mehr Aktivität
            "EXTREME": 0.0,       # Unvorhersehbar
        }

        signal = condition_signals.get(condition, 0.0)

        # Volumen-Trend verstärkt
        if trend == "INCREASING":
            signal += 0.1
        elif trend == "DECREASING":
            signal -= 0.05

        # Kombination mit aktuellem Preis-Trend
        # (steigendes Volumen + steigender Preis = bullish)
        if context.price_change_5min > 0 and ratio > 1.2:
            signal += 0.15
        elif context.price_change_5min < 0 and ratio > 1.2:
            signal -= 0.15

        return max(-1, min(1, signal))

    def _calculate_time_signal(self, context: PredictionContext) -> float:
        """
        Berechnet Signal basierend auf Tageszeit.
        """
        phase = context.trading_phase
        base_tendency = self._phase_tendencies.get(phase, 0.0)

        # Modifikation basierend auf Zeit innerhalb der Phase
        minutes = context.minutes_since_open

        # Erste 30 Min nach Open: Erhöhte Volatilität
        if minutes < 30:
            base_tendency *= 1.5

        # Letzte 30 Min vor Close: Erhöhte Volatilität
        if phase == "POWER_HOUR" and minutes > 360:  # Nach 15:30
            base_tendency *= 1.3

        return base_tendency

    def _get_volatility_multiplier(
        self,
        context: PredictionContext,
        timeframe: PredictionTimeframe
    ) -> float:
        """
        Skaliert erwartete Bewegung basierend auf Volatilität und Zeitraum.
        """
        # Basis: ATR als Prozent vom Preis
        atr_pct = context.atr_14 if context.atr_14 > 0 else 0.5

        # Zeitraum-Skalierung (längere Zeiträume = größere Bewegungen)
        timeframe_multipliers = {
            PredictionTimeframe.MINUTES_5: 0.3,
            PredictionTimeframe.MINUTES_15: 0.5,
            PredictionTimeframe.MINUTES_30: 0.7,
            PredictionTimeframe.HOUR_1: 1.0,
        }

        # Volatilitäts-Regime Anpassung
        regime_multipliers = {
            "HIGH": 1.5,
            "MEDIUM": 1.0,
            "LOW": 0.6,
            "EXTREME": 2.0,
        }

        base = atr_pct * timeframe_multipliers.get(timeframe, 0.5)
        regime_mult = regime_multipliers.get(context.volatility_regime, 1.0)

        return base * regime_mult

    def _calculate_confidence(
        self,
        pattern_signal: float,
        momentum_signal: float,
        volume_signal: float,
        time_signal: float,
        context: PredictionContext
    ) -> float:
        """
        Berechnet die Konfidenz der Vorhersage.

        Höhere Konfidenz wenn:
        - Signale übereinstimmen
        - Historisches Pattern stark
        - Normale Marktbedingungen
        """
        # Basis-Konfidenz
        base_confidence = 0.4

        # Signal-Übereinstimmung (gleiche Richtung = höhere Konfidenz)
        signals = [pattern_signal, momentum_signal, volume_signal, time_signal]
        non_zero = [s for s in signals if abs(s) > 0.1]

        if len(non_zero) >= 2:
            # Prüfe ob alle gleiche Richtung
            positive = sum(1 for s in non_zero if s > 0)
            negative = len(non_zero) - positive

            if positive == len(non_zero) or negative == len(non_zero):
                base_confidence += 0.2  # Alle gleiche Richtung
            elif abs(positive - negative) >= 2:
                base_confidence += 0.1  # Mehrheit gleiche Richtung

        # Pattern-Konfidenz einfließen
        if context.pattern_confidence > 0:
            base_confidence += context.pattern_confidence * 0.2

        # Marktbedingungen
        if context.volatility_regime == "HIGH":
            base_confidence -= 0.1  # Unsicherer bei hoher Vola
        elif context.volatility_regime == "LOW":
            base_confidence += 0.05  # Stabiler bei niedriger Vola

        if context.volume_condition == "EXTREME":
            base_confidence -= 0.2  # News? Unvorhersehbar

        # Tageszeit
        if context.trading_phase in ("MARKET_OPEN", "POWER_HOUR", "CLOSE"):
            base_confidence -= 0.1  # Volatilere Phasen

        return max(0.1, min(0.95, base_confidence))

    # ==================== HELPER METHODS ====================

    def _signal_to_direction(self, signal: float) -> DirectionBias:
        """Konvertiert Signal zu DirectionBias"""
        if signal > 0.5:
            return DirectionBias.STRONG_UP
        elif signal > 0.15:
            return DirectionBias.UP
        elif signal < -0.5:
            return DirectionBias.STRONG_DOWN
        elif signal < -0.15:
            return DirectionBias.DOWN
        else:
            return DirectionBias.NEUTRAL

    def _summarize_predictions(self, result: PredictionResult):
        """Berechnet Zusammenfassung der Vorhersagen"""
        if not result.predictions:
            return

        # Durchschnittliche Konfidenz
        confidences = [p.confidence for p in result.predictions.values()]
        result.average_confidence = sum(confidences) / len(confidences)

        # Dominante Richtung (gewichtet nach Zeitraum - kurzfristig wichtiger)
        weights = {
            PredictionTimeframe.MINUTES_5: 0.4,
            PredictionTimeframe.MINUTES_15: 0.3,
            PredictionTimeframe.MINUTES_30: 0.2,
            PredictionTimeframe.HOUR_1: 0.1,
        }

        weighted_signal = sum(
            p.expected_change_pct * weights.get(t, 0.25)
            for t, p in result.predictions.items()
        )

        result.dominant_direction = self._signal_to_direction(weighted_signal)

        # Handlungsempfehlung
        if result.average_confidence >= 0.6:
            if result.dominant_direction in (DirectionBias.STRONG_UP, DirectionBias.UP):
                result.suggested_action = "BUY"
                result.action_confidence = result.average_confidence
                result.action_reason = f"Bullische Signale mit {result.average_confidence:.0%} Konfidenz"
            elif result.dominant_direction in (DirectionBias.STRONG_DOWN, DirectionBias.DOWN):
                result.suggested_action = "SELL"
                result.action_confidence = result.average_confidence
                result.action_reason = f"Bärische Signale mit {result.average_confidence:.0%} Konfidenz"
            else:
                result.suggested_action = "HOLD"
                result.action_reason = "Keine klare Richtung"
        else:
            result.suggested_action = "HOLD"
            result.action_confidence = result.average_confidence
            result.action_reason = f"Niedrige Konfidenz ({result.average_confidence:.0%})"

    def _record_prediction(self, symbol: str, result: PredictionResult):
        """Speichert Vorhersage für spätere Analyse"""
        if symbol not in self._prediction_history:
            self._prediction_history[symbol] = deque(maxlen=self._history_size)

        self._prediction_history[symbol].append({
            'timestamp': result.timestamp,
            'predictions': {
                t.value: {
                    'expected': p.expected_change_pct,
                    'confidence': p.confidence,
                    'direction': p.direction.value,
                }
                for t, p in result.predictions.items()
            }
        })

    def get_prediction_accuracy(self, symbol: str) -> Dict[str, float]:
        """
        Berechnet historische Vorhersage-Genauigkeit.

        Hinweis: Benötigt tatsächliche Preisdaten für Vergleich.
        Diese Methode ist ein Platzhalter für spätere Implementierung.
        """
        # TODO: Implementieren wenn tatsächliche Preisdaten verfügbar
        return {
            '5min_direction_accuracy': 0.0,
            '15min_direction_accuracy': 0.0,
            'average_error_pct': 0.0,
        }

    def update_weights(self, new_weights: Dict[str, float]):
        """Aktualisiert die Signal-Gewichtungen"""
        self._weights.update(new_weights)

    def clear_history(self, symbol: Optional[str] = None):
        """Löscht Vorhersage-Historie"""
        if symbol:
            if symbol in self._prediction_history:
                self._prediction_history[symbol].clear()
        else:
            self._prediction_history.clear()
