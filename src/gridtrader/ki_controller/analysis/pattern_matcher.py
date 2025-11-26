"""
Pattern Matcher

Erkennt Muster in historischen Daten und vergleicht sie mit der aktuellen Situation.
Basiert auf "Situations-Fingerprints" - charakteristische Merkmal-Kombinationen.

Beispiel:
- Aktuelle Situation: ATR=1.2%, Preis nahe Tageshoch, Volumen steigend, 10:15 Uhr
- Historische ähnliche Situation: 15.11. um 10:20 Uhr
- Damals: Preis ging 0.5% runter, dann 0.3% rauf
- Empfehlung: Erwarte ähnliche Bewegung, aktiviere entsprechende Levels
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from collections import defaultdict
import statistics
import json
from pathlib import Path


class MovementPattern(str, Enum):
    """Erkannte Bewegungsmuster"""
    CONSOLIDATION = "CONSOLIDATION"      # Seitwärts
    BREAKOUT_UP = "BREAKOUT_UP"          # Ausbruch nach oben
    BREAKOUT_DOWN = "BREAKOUT_DOWN"      # Ausbruch nach unten
    TREND_UP = "TREND_UP"                # Aufwärtstrend
    TREND_DOWN = "TREND_DOWN"            # Abwärtstrend
    REVERSAL_UP = "REVERSAL_UP"          # Umkehr nach oben
    REVERSAL_DOWN = "REVERSAL_DOWN"      # Umkehr nach unten
    HIGH_VOLATILITY = "HIGH_VOLATILITY"  # Hohe Schwankung
    UNKNOWN = "UNKNOWN"


@dataclass
class SituationFingerprint:
    """
    Ein "Fingerabdruck" einer Marktsituation.

    Ermöglicht den Vergleich verschiedener Zeitpunkte.
    """
    timestamp: datetime
    symbol: str

    # Preis-Position (0-100, wo steht Preis im Tages-Range)
    price_position_in_range: float = 50.0  # 0=Low, 100=High

    # Volatilität
    atr_pct: float = 0.0
    volatility_regime: str = "UNKNOWN"  # HIGH/MEDIUM/LOW

    # Volumen
    volume_ratio: float = 1.0  # Aktuell/Durchschnitt
    volume_condition: str = "NORMAL"

    # Trend (letzte 5-15 Minuten)
    short_term_trend: float = 0.0  # Positive = up, negative = down
    medium_term_trend: float = 0.0

    # Zeit
    trading_phase: str = "UNKNOWN"
    minutes_since_open: int = 0

    # Kerzen-Charakteristik
    last_candle_body_pct: float = 0.0  # Positiv = bullish, negativ = bearish
    last_candle_range_pct: float = 0.0

    def to_vector(self) -> List[float]:
        """Konvertiert zu einem numerischen Vektor für Vergleiche."""
        return [
            self.price_position_in_range / 100,
            min(self.atr_pct / 3, 1.0),  # Normalisiert auf 0-1
            self.volume_ratio / 3,  # Normalisiert
            (self.short_term_trend + 5) / 10,  # -5% bis +5% → 0-1
            (self.medium_term_trend + 5) / 10,
            self.minutes_since_open / 390,  # 390 Min Handelstag
            self.last_candle_body_pct / 3,
            self.last_candle_range_pct / 5,
        ]

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'symbol': self.symbol,
            'price_position_in_range': self.price_position_in_range,
            'atr_pct': self.atr_pct,
            'volatility_regime': self.volatility_regime,
            'volume_ratio': self.volume_ratio,
            'volume_condition': self.volume_condition,
            'short_term_trend': self.short_term_trend,
            'medium_term_trend': self.medium_term_trend,
            'trading_phase': self.trading_phase,
            'minutes_since_open': self.minutes_since_open,
            'last_candle_body_pct': self.last_candle_body_pct,
            'last_candle_range_pct': self.last_candle_range_pct,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SituationFingerprint':
        return cls(
            timestamp=datetime.fromisoformat(data['timestamp']),
            symbol=data['symbol'],
            price_position_in_range=data.get('price_position_in_range', 50),
            atr_pct=data.get('atr_pct', 0),
            volatility_regime=data.get('volatility_regime', 'UNKNOWN'),
            volume_ratio=data.get('volume_ratio', 1),
            volume_condition=data.get('volume_condition', 'NORMAL'),
            short_term_trend=data.get('short_term_trend', 0),
            medium_term_trend=data.get('medium_term_trend', 0),
            trading_phase=data.get('trading_phase', 'UNKNOWN'),
            minutes_since_open=data.get('minutes_since_open', 0),
            last_candle_body_pct=data.get('last_candle_body_pct', 0),
            last_candle_range_pct=data.get('last_candle_range_pct', 0),
        )


@dataclass
class HistoricalOutcome:
    """
    Aufzeichnung was nach einer bestimmten Situation passiert ist.
    """
    fingerprint: SituationFingerprint

    # Was passierte danach?
    price_change_5min: float = 0.0   # % Änderung nach 5 Min
    price_change_15min: float = 0.0  # % Änderung nach 15 Min
    price_change_30min: float = 0.0  # % Änderung nach 30 Min

    # Extremwerte
    max_up_5min: float = 0.0    # Max. Aufwärtsbewegung in 5 Min
    max_down_5min: float = 0.0  # Max. Abwärtsbewegung in 5 Min
    max_up_15min: float = 0.0
    max_down_15min: float = 0.0

    # Erkanntes Muster
    pattern: MovementPattern = MovementPattern.UNKNOWN

    def to_dict(self) -> dict:
        return {
            'fingerprint': self.fingerprint.to_dict(),
            'price_change_5min': self.price_change_5min,
            'price_change_15min': self.price_change_15min,
            'price_change_30min': self.price_change_30min,
            'max_up_5min': self.max_up_5min,
            'max_down_5min': self.max_down_5min,
            'max_up_15min': self.max_up_15min,
            'max_down_15min': self.max_down_15min,
            'pattern': self.pattern.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'HistoricalOutcome':
        return cls(
            fingerprint=SituationFingerprint.from_dict(data['fingerprint']),
            price_change_5min=data.get('price_change_5min', 0),
            price_change_15min=data.get('price_change_15min', 0),
            price_change_30min=data.get('price_change_30min', 0),
            max_up_5min=data.get('max_up_5min', 0),
            max_down_5min=data.get('max_down_5min', 0),
            max_up_15min=data.get('max_up_15min', 0),
            max_down_15min=data.get('max_down_15min', 0),
            pattern=MovementPattern(data.get('pattern', 'UNKNOWN')),
        )


@dataclass
class PatternMatchResult:
    """
    Ergebnis eines Pattern-Matches.
    """
    current_fingerprint: SituationFingerprint
    similar_situations: List[HistoricalOutcome]
    match_count: int

    # Aggregierte Vorhersage
    expected_5min_change: float = 0.0
    expected_15min_change: float = 0.0
    confidence: float = 0.0  # 0-1

    # Wahrscheinlichkeiten
    prob_up_5min: float = 0.5
    prob_down_5min: float = 0.5
    prob_up_15min: float = 0.5
    prob_down_15min: float = 0.5

    # Erwartete Ranges
    expected_max_up: float = 0.0
    expected_max_down: float = 0.0

    # Dominantes Muster
    dominant_pattern: MovementPattern = MovementPattern.UNKNOWN

    def to_dict(self) -> dict:
        return {
            'current_fingerprint': self.current_fingerprint.to_dict(),
            'match_count': self.match_count,
            'expected_5min_change': self.expected_5min_change,
            'expected_15min_change': self.expected_15min_change,
            'confidence': self.confidence,
            'prob_up_5min': self.prob_up_5min,
            'prob_down_5min': self.prob_down_5min,
            'prob_up_15min': self.prob_up_15min,
            'prob_down_15min': self.prob_down_15min,
            'expected_max_up': self.expected_max_up,
            'expected_max_down': self.expected_max_down,
            'dominant_pattern': self.dominant_pattern.value,
        }


class PatternMatcher:
    """
    Vergleicht aktuelle Marktsituation mit historischen Daten.

    Workflow:
    1. Aktuelle Situation als Fingerprint erfassen
    2. Ähnliche historische Situationen finden
    3. Analysieren was damals passiert ist
    4. Vorhersage/Empfehlung ableiten
    """

    def __init__(
        self,
        similarity_threshold: float = 0.75,
        max_history_per_symbol: int = 1000,
        lookback_days: int = 30,
    ):
        """
        Args:
            similarity_threshold: Min. Ähnlichkeit für Match (0-1)
            max_history_per_symbol: Max. gespeicherte Situationen pro Symbol
            lookback_days: Wie weit zurück für Matches
        """
        self._similarity_threshold = similarity_threshold
        self._max_history = max_history_per_symbol
        self._lookback_days = lookback_days

        # Historische Daten: symbol -> Liste von HistoricalOutcome
        self._history: Dict[str, List[HistoricalOutcome]] = defaultdict(list)

        # Persistenz-Pfad
        self._data_dir = Path.home() / ".gridtrader" / "pattern_history"
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def record_situation(
        self,
        fingerprint: SituationFingerprint,
        outcome: Optional[HistoricalOutcome] = None
    ):
        """
        Zeichnet eine Situation auf.

        Wenn outcome None ist, wird nur der Fingerprint gespeichert
        und später mit Outcome ergänzt.
        """
        symbol = fingerprint.symbol

        if outcome:
            self._history[symbol].append(outcome)
        else:
            # Platzhalter-Outcome erstellen
            placeholder = HistoricalOutcome(fingerprint=fingerprint)
            self._history[symbol].append(placeholder)

        # History begrenzen
        if len(self._history[symbol]) > self._max_history:
            self._history[symbol] = self._history[symbol][-self._max_history:]

    def update_outcome(
        self,
        symbol: str,
        timestamp: datetime,
        price_change_5min: float,
        price_change_15min: float,
        price_change_30min: float,
        max_up_5min: float,
        max_down_5min: float,
        max_up_15min: float,
        max_down_15min: float,
    ):
        """
        Aktualisiert ein bestehendes Record mit dem tatsächlichen Outcome.
        """
        if symbol not in self._history:
            return

        # Finde passendes Record (innerhalb 1 Minute)
        for outcome in self._history[symbol]:
            time_diff = abs((outcome.fingerprint.timestamp - timestamp).total_seconds())
            if time_diff < 60:
                outcome.price_change_5min = price_change_5min
                outcome.price_change_15min = price_change_15min
                outcome.price_change_30min = price_change_30min
                outcome.max_up_5min = max_up_5min
                outcome.max_down_5min = max_down_5min
                outcome.max_up_15min = max_up_15min
                outcome.max_down_15min = max_down_15min
                outcome.pattern = self._classify_pattern(
                    price_change_5min, price_change_15min,
                    max_up_5min, max_down_5min
                )
                break

    def find_similar_situations(
        self,
        current: SituationFingerprint,
        min_matches: int = 5,
        max_matches: int = 20,
    ) -> PatternMatchResult:
        """
        Findet ähnliche historische Situationen.

        Args:
            current: Aktuelle Situation
            min_matches: Minimum benötigte Matches für Confidence
            max_matches: Maximum zurückgegebene Matches

        Returns:
            PatternMatchResult mit Vorhersagen
        """
        symbol = current.symbol
        history = self._history.get(symbol, [])

        if not history:
            return PatternMatchResult(
                current_fingerprint=current,
                similar_situations=[],
                match_count=0,
                confidence=0.0,
            )

        # Lookback-Filter
        cutoff = datetime.now() - timedelta(days=self._lookback_days)
        recent_history = [
            h for h in history
            if h.fingerprint.timestamp >= cutoff
        ]

        # Ähnlichkeiten berechnen
        scored: List[Tuple[float, HistoricalOutcome]] = []
        current_vector = current.to_vector()

        for outcome in recent_history:
            # Outcomes ohne echte Daten überspringen
            if outcome.price_change_5min == 0 and outcome.price_change_15min == 0:
                continue

            similarity = self._calculate_similarity(
                current_vector,
                outcome.fingerprint.to_vector()
            )

            if similarity >= self._similarity_threshold:
                scored.append((similarity, outcome))

        # Nach Ähnlichkeit sortieren
        scored.sort(key=lambda x: x[0], reverse=True)

        # Top N nehmen
        top_matches = [outcome for _, outcome in scored[:max_matches]]

        if not top_matches:
            return PatternMatchResult(
                current_fingerprint=current,
                similar_situations=[],
                match_count=0,
                confidence=0.0,
            )

        # Aggregierte Vorhersage berechnen
        result = self._aggregate_predictions(current, top_matches, min_matches)

        return result

    def get_prediction(
        self,
        current: SituationFingerprint
    ) -> Tuple[float, float, float]:
        """
        Schnelle Vorhersage für die erwartete Preisbewegung.

        Returns:
            (expected_5min, expected_15min, confidence)
        """
        result = self.find_similar_situations(current)
        return (
            result.expected_5min_change,
            result.expected_15min_change,
            result.confidence
        )

    def save_history(self, symbol: Optional[str] = None):
        """Speichert Historie persistent."""
        symbols = [symbol] if symbol else list(self._history.keys())

        for sym in symbols:
            if sym not in self._history:
                continue

            filepath = self._data_dir / f"{sym}_patterns.json"
            data = {
                'symbol': sym,
                'updated_at': datetime.now().isoformat(),
                'outcomes': [o.to_dict() for o in self._history[sym]]
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def load_history(self, symbol: str) -> int:
        """
        Lädt Historie für ein Symbol.

        Returns:
            Anzahl geladener Records
        """
        filepath = self._data_dir / f"{symbol}_patterns.json"

        if not filepath.exists():
            return 0

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            outcomes = [
                HistoricalOutcome.from_dict(o)
                for o in data.get('outcomes', [])
            ]

            self._history[symbol] = outcomes
            return len(outcomes)

        except Exception:
            return 0

    # ==================== PRIVATE METHODS ====================

    def _calculate_similarity(
        self,
        vec1: List[float],
        vec2: List[float]
    ) -> float:
        """
        Berechnet Ähnlichkeit zwischen zwei Vektoren (0-1).

        Verwendet gewichteten euklidischen Abstand.
        """
        if len(vec1) != len(vec2):
            return 0.0

        # Gewichte für verschiedene Features
        weights = [
            1.5,  # price_position_in_range
            2.0,  # atr_pct (wichtig!)
            1.0,  # volume_ratio
            1.5,  # short_term_trend
            1.0,  # medium_term_trend
            0.5,  # minutes_since_open
            1.0,  # last_candle_body
            1.0,  # last_candle_range
        ]

        # Gewichteter quadratischer Abstand
        weighted_sq_diff = sum(
            w * (a - b) ** 2
            for w, a, b in zip(weights, vec1, vec2)
        )

        # In Ähnlichkeit umwandeln (0-1)
        max_distance = sum(weights)  # Maximaler möglicher Abstand
        similarity = 1 - (weighted_sq_diff ** 0.5 / max_distance ** 0.5)

        return max(0, min(1, similarity))

    def _aggregate_predictions(
        self,
        current: SituationFingerprint,
        matches: List[HistoricalOutcome],
        min_matches: int
    ) -> PatternMatchResult:
        """Aggregiert Vorhersagen aus mehreren Matches."""
        n = len(matches)

        # Basis-Metriken
        changes_5 = [m.price_change_5min for m in matches]
        changes_15 = [m.price_change_15min for m in matches]
        ups_5 = [m.max_up_5min for m in matches]
        downs_5 = [m.max_down_5min for m in matches]
        ups_15 = [m.max_up_15min for m in matches]
        downs_15 = [m.max_down_15min for m in matches]
        patterns = [m.pattern for m in matches]

        # Durchschnittliche Vorhersage
        expected_5 = statistics.mean(changes_5) if changes_5 else 0
        expected_15 = statistics.mean(changes_15) if changes_15 else 0

        # Wahrscheinlichkeiten
        prob_up_5 = sum(1 for c in changes_5 if c > 0) / n if n > 0 else 0.5
        prob_down_5 = sum(1 for c in changes_5 if c < 0) / n if n > 0 else 0.5
        prob_up_15 = sum(1 for c in changes_15 if c > 0) / n if n > 0 else 0.5
        prob_down_15 = sum(1 for c in changes_15 if c < 0) / n if n > 0 else 0.5

        # Erwartete Extremwerte
        expected_max_up = statistics.mean(ups_15) if ups_15 else 0
        expected_max_down = statistics.mean(downs_15) if downs_15 else 0

        # Dominantes Muster
        pattern_counts: Dict[MovementPattern, int] = defaultdict(int)
        for p in patterns:
            pattern_counts[p] += 1

        dominant = max(pattern_counts.keys(), key=lambda p: pattern_counts[p])

        # Confidence
        # Höher wenn: mehr Matches, konsistente Ergebnisse
        if n >= min_matches:
            # Standardabweichung als Maß für Konsistenz
            std_5 = statistics.stdev(changes_5) if len(changes_5) > 1 else 1
            consistency = 1 / (1 + std_5)  # Niedrigere Std = höhere Confidence

            # Match-Anzahl Factor
            count_factor = min(1.0, n / (min_matches * 2))

            confidence = (consistency * 0.6 + count_factor * 0.4)
        else:
            confidence = n / min_matches * 0.5  # Max 50% bei zu wenig Matches

        return PatternMatchResult(
            current_fingerprint=current,
            similar_situations=matches,
            match_count=n,
            expected_5min_change=expected_5,
            expected_15min_change=expected_15,
            confidence=min(1.0, confidence),
            prob_up_5min=prob_up_5,
            prob_down_5min=prob_down_5,
            prob_up_15min=prob_up_15,
            prob_down_15min=prob_down_15,
            expected_max_up=expected_max_up,
            expected_max_down=expected_max_down,
            dominant_pattern=dominant,
        )

    def _classify_pattern(
        self,
        change_5: float,
        change_15: float,
        max_up: float,
        max_down: float
    ) -> MovementPattern:
        """Klassifiziert ein Bewegungsmuster."""
        # Hohe Volatilität
        if max_up > 1.5 and max_down > 1.5:
            return MovementPattern.HIGH_VOLATILITY

        # Breakouts
        if change_5 > 0.8 and change_15 > 1.0:
            return MovementPattern.BREAKOUT_UP
        if change_5 < -0.8 and change_15 < -1.0:
            return MovementPattern.BREAKOUT_DOWN

        # Trends
        if change_5 > 0.3 and change_15 > 0.5:
            return MovementPattern.TREND_UP
        if change_5 < -0.3 and change_15 < -0.5:
            return MovementPattern.TREND_DOWN

        # Reversals
        if change_5 < -0.3 and change_15 > 0.2:
            return MovementPattern.REVERSAL_UP
        if change_5 > 0.3 and change_15 < -0.2:
            return MovementPattern.REVERSAL_DOWN

        # Konsolidierung
        if abs(change_15) < 0.3:
            return MovementPattern.CONSOLIDATION

        return MovementPattern.UNKNOWN

    def get_statistics(self, symbol: str) -> Dict[str, Any]:
        """Gibt Statistiken für ein Symbol zurück."""
        history = self._history.get(symbol, [])

        if not history:
            return {'total_records': 0}

        # Outcomes mit Daten filtern
        valid = [h for h in history if h.price_change_5min != 0 or h.price_change_15min != 0]

        if not valid:
            return {
                'total_records': len(history),
                'valid_records': 0,
            }

        changes_5 = [h.price_change_5min for h in valid]
        changes_15 = [h.price_change_15min for h in valid]

        return {
            'total_records': len(history),
            'valid_records': len(valid),
            'avg_5min_change': statistics.mean(changes_5),
            'avg_15min_change': statistics.mean(changes_15),
            'std_5min': statistics.stdev(changes_5) if len(changes_5) > 1 else 0,
            'std_15min': statistics.stdev(changes_15) if len(changes_15) > 1 else 0,
            'up_probability_5min': sum(1 for c in changes_5 if c > 0) / len(changes_5),
            'up_probability_15min': sum(1 for c in changes_15 if c > 0) / len(changes_15),
        }

    def clear_symbol(self, symbol: str):
        """Löscht Historie für ein Symbol."""
        if symbol in self._history:
            del self._history[symbol]

        filepath = self._data_dir / f"{symbol}_patterns.json"
        if filepath.exists():
            filepath.unlink()
