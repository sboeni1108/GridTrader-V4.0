"""
Level Scorer

Bewertet Levels basierend auf mehreren Faktoren:
- Preis-Nähe (Abstand zum aktuellen Kurs)
- Volatilitäts-Anpassung (Level-Größe vs. ATR)
- Profit-Potenzial (Risk/Reward)
- Historische Performance (Pattern Match)
- Tageszeit-Eignung
- Volumen-Kontext
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any


class ScoreCategory(str, Enum):
    """Kategorien für Score-Komponenten"""
    PRICE_PROXIMITY = "PRICE_PROXIMITY"      # Nähe zum aktuellen Preis
    VOLATILITY_FIT = "VOLATILITY_FIT"        # Passt Level-Größe zur Volatilität?
    PROFIT_POTENTIAL = "PROFIT_POTENTIAL"    # Gewinnpotenzial
    RISK_REWARD = "RISK_REWARD"              # Risk/Reward Verhältnis
    PATTERN_MATCH = "PATTERN_MATCH"          # Historische Muster-Übereinstimmung
    TIME_SUITABILITY = "TIME_SUITABILITY"    # Tageszeit-Eignung
    VOLUME_CONTEXT = "VOLUME_CONTEXT"        # Volumen-Kontext
    TREND_ALIGNMENT = "TREND_ALIGNMENT"      # Trend-Ausrichtung


@dataclass
class ScoreBreakdown:
    """Aufschlüsselung der Score-Komponenten"""
    category: ScoreCategory
    raw_score: float          # Rohwert (-100 bis +100)
    weight: float             # Gewichtung (0 bis 1)
    weighted_score: float     # raw_score * weight
    reason: str               # Begründung

    def to_dict(self) -> dict:
        return {
            'category': self.category.value,
            'raw_score': self.raw_score,
            'weight': self.weight,
            'weighted_score': self.weighted_score,
            'reason': self.reason,
        }


@dataclass
class LevelScore:
    """Vollständige Bewertung eines Levels"""
    level_id: str
    symbol: str
    side: str                 # "LONG" oder "SHORT"
    entry_price: float
    exit_price: float

    # Gesamtscore
    total_score: float = 0.0  # Gewichtete Summe aller Komponenten

    # Score-Aufschlüsselung
    breakdowns: List[ScoreBreakdown] = field(default_factory=list)

    # Metadaten
    timestamp: datetime = field(default_factory=datetime.now)
    is_recommended: bool = False  # Empfohlen basierend auf Score?
    rejection_reason: str = ""    # Falls nicht empfohlen, warum?

    # Zusätzliche Informationen
    profit_pct: float = 0.0       # Profit in %
    risk_pct: float = 0.0         # Risiko in % (z.B. zum Stop)
    distance_pct: float = 0.0     # Abstand zum Entry in %

    def add_breakdown(self, breakdown: ScoreBreakdown):
        """Fügt eine Score-Komponente hinzu"""
        self.breakdowns.append(breakdown)
        self.total_score = sum(b.weighted_score for b in self.breakdowns)

    def to_dict(self) -> dict:
        return {
            'level_id': self.level_id,
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'exit_price': self.exit_price,
            'total_score': self.total_score,
            'breakdowns': [b.to_dict() for b in self.breakdowns],
            'timestamp': self.timestamp.isoformat(),
            'is_recommended': self.is_recommended,
            'rejection_reason': self.rejection_reason,
            'profit_pct': self.profit_pct,
            'risk_pct': self.risk_pct,
            'distance_pct': self.distance_pct,
        }


@dataclass
class ScorerConfig:
    """Konfiguration für den Level Scorer"""

    # Gewichtungen für Score-Kategorien (müssen nicht 1.0 ergeben)
    weights: Dict[ScoreCategory, float] = field(default_factory=lambda: {
        ScoreCategory.PRICE_PROXIMITY: 1.0,
        ScoreCategory.VOLATILITY_FIT: 0.8,
        ScoreCategory.PROFIT_POTENTIAL: 0.9,
        ScoreCategory.RISK_REWARD: 0.7,
        ScoreCategory.PATTERN_MATCH: 0.6,
        ScoreCategory.TIME_SUITABILITY: 0.5,
        ScoreCategory.VOLUME_CONTEXT: 0.4,
        ScoreCategory.TREND_ALIGNMENT: 0.7,
    })

    # Schwellenwerte für Empfehlung
    min_score_for_recommendation: float = 30.0
    max_distance_pct: float = 3.0          # Max. Abstand zum Entry
    min_profit_pct: float = 0.1            # Min. Profit-Potenzial

    # Preis-Nähe Parameter
    optimal_distance_pct: float = 0.3      # Optimaler Abstand zum Entry
    too_close_pct: float = 0.05            # Zu nah (riskant)

    # Volatilitäts-Fit Parameter
    optimal_level_size_atr_ratio: float = 1.5  # Level-Größe = 1.5x ATR ist optimal

    # Kommissionskosten (für Profit-Berechnung)
    commission_per_trade: float = 1.0      # $ pro Trade
    assumed_shares: int = 100              # Angenommene Shares pro Level


@dataclass
class MarketContext:
    """Marktkontext für Scoring"""
    current_price: float
    atr_5: float = 0.0
    atr_14: float = 0.0
    atr_50: float = 0.0
    volatility_regime: str = "MEDIUM"      # HIGH/MEDIUM/LOW
    volume_ratio: float = 1.0              # Aktuelles Volumen / Durchschnitt
    volume_condition: str = "NORMAL"       # VERY_LOW bis EXTREME
    trading_phase: str = "MIDDAY"          # Trading-Phase
    caution_level: int = 0                 # 0-3
    short_term_trend: float = 0.0          # Kurzfristiger Trend (%)
    medium_term_trend: float = 0.0         # Mittelfristiger Trend (%)
    pattern_prediction: Optional[str] = None   # Vorhergesagtes Pattern
    pattern_confidence: float = 0.0        # Konfidenz des Patterns


class LevelScorer:
    """
    Multi-Faktor Level-Bewertungssystem

    Bewertet jedes Level basierend auf:
    1. Preis-Nähe: Wie weit ist der Entry vom aktuellen Preis?
    2. Volatilitäts-Fit: Passt die Level-Größe zur aktuellen Volatilität?
    3. Profit-Potenzial: Wie viel kann verdient werden?
    4. Risk/Reward: Verhältnis von potenziellem Gewinn zu Risiko
    5. Pattern-Match: Was sagen historische Muster?
    6. Zeit-Eignung: Ist jetzt ein guter Zeitpunkt?
    7. Volumen-Kontext: Was sagt das Volumen?
    8. Trend-Alignment: Ist das Level mit dem Trend?
    """

    def __init__(self, config: Optional[ScorerConfig] = None):
        self.config = config or ScorerConfig()

        # Cache für berechnete Scores
        self._score_cache: Dict[str, LevelScore] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds: int = 5  # Cache für 5 Sekunden gültig

    def score_level(
        self,
        level: Dict[str, Any],
        context: MarketContext,
        use_cache: bool = True
    ) -> LevelScore:
        """
        Bewertet ein einzelnes Level.

        Args:
            level: Level-Daten (dict mit level_id, entry_price, exit_price, side, etc.)
            context: Aktueller Marktkontext
            use_cache: Cache verwenden?

        Returns:
            LevelScore mit detaillierter Bewertung
        """
        level_id = level.get('level_id', '')

        # Cache prüfen
        if use_cache and self._is_cache_valid(level_id):
            return self._score_cache[level_id]

        # Basis-Informationen extrahieren
        entry_price = float(level.get('entry_price', 0))
        exit_price = float(level.get('exit_price', 0))
        side = level.get('side', 'LONG')
        symbol = level.get('symbol', '')

        # Score-Objekt erstellen
        score = LevelScore(
            level_id=level_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
        )

        # Validierung
        if context.current_price <= 0 or entry_price <= 0 or exit_price <= 0:
            score.rejection_reason = "Ungültige Preisdaten"
            return score

        # Basis-Metriken berechnen
        score.distance_pct = self._calc_distance_pct(entry_price, context.current_price)
        score.profit_pct = self._calc_profit_pct(entry_price, exit_price, side)
        score.risk_pct = score.distance_pct  # Vereinfacht: Risiko = Abstand zum Entry

        # Score-Komponenten berechnen
        self._score_price_proximity(score, context)
        self._score_volatility_fit(score, context)
        self._score_profit_potential(score, context)
        self._score_risk_reward(score, context)
        self._score_pattern_match(score, context)
        self._score_time_suitability(score, context)
        self._score_volume_context(score, context)
        self._score_trend_alignment(score, context)

        # Empfehlung bestimmen
        self._determine_recommendation(score, context)

        # Cache aktualisieren
        self._score_cache[level_id] = score
        self._cache_timestamp = datetime.now()

        return score

    def score_levels(
        self,
        levels: List[Dict[str, Any]],
        context: MarketContext
    ) -> List[LevelScore]:
        """
        Bewertet mehrere Levels und sortiert nach Score.

        Returns:
            Liste von LevelScores, sortiert nach total_score (absteigend)
        """
        scores = [self.score_level(level, context) for level in levels]
        scores.sort(key=lambda s: s.total_score, reverse=True)
        return scores

    def get_recommended_levels(
        self,
        levels: List[Dict[str, Any]],
        context: MarketContext,
        max_levels: int = 10
    ) -> List[LevelScore]:
        """
        Gibt die besten empfohlenen Levels zurück.

        Args:
            levels: Liste aller verfügbaren Levels
            context: Aktueller Marktkontext
            max_levels: Maximale Anzahl zurückzugebender Levels

        Returns:
            Liste der besten LevelScores (nur empfohlene)
        """
        all_scores = self.score_levels(levels, context)
        recommended = [s for s in all_scores if s.is_recommended]
        return recommended[:max_levels]

    # ==================== SCORE-KOMPONENTEN ====================

    def _score_price_proximity(self, score: LevelScore, context: MarketContext):
        """
        Bewertet die Nähe des Entry-Preises zum aktuellen Kurs.

        Optimal: Nahe genug für baldige Ausführung, aber nicht zu nah (Spread-Risiko)
        """
        distance = score.distance_pct
        optimal = self.config.optimal_distance_pct
        too_close = self.config.too_close_pct
        max_dist = self.config.max_distance_pct

        if distance < too_close:
            # Zu nah - Spread und Slippage-Risiko
            raw_score = -50 + (distance / too_close) * 30
            reason = f"Zu nah am Entry ({distance:.2f}%), Spread-Risiko"
        elif distance <= optimal:
            # Guter Bereich - je näher am Optimum, desto besser
            raw_score = 80 + (1 - distance / optimal) * 20
            reason = f"Guter Abstand ({distance:.2f}%)"
        elif distance <= optimal * 2:
            # Noch akzeptabel
            excess = distance - optimal
            raw_score = 80 - (excess / optimal) * 40
            reason = f"Akzeptabler Abstand ({distance:.2f}%)"
        elif distance <= max_dist:
            # Weit, aber noch möglich
            excess = distance - optimal * 2
            max_excess = max_dist - optimal * 2
            raw_score = 40 - (excess / max_excess) * 40 if max_excess > 0 else 20
            reason = f"Weiter Abstand ({distance:.2f}%)"
        else:
            # Zu weit
            raw_score = -30
            reason = f"Zu weit entfernt ({distance:.2f}%)"

        weight = self.config.weights[ScoreCategory.PRICE_PROXIMITY]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.PRICE_PROXIMITY,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_volatility_fit(self, score: LevelScore, context: MarketContext):
        """
        Bewertet ob die Level-Größe zur aktuellen Volatilität passt.

        Bei hoher Volatilität: Größere Levels bevorzugen
        Bei niedriger Volatilität: Kleinere Levels bevorzugen
        """
        level_size = abs(score.exit_price - score.entry_price)
        level_size_pct = (level_size / score.entry_price) * 100

        # ATR als Referenz (14-Perioden als Standard)
        atr = context.atr_14 if context.atr_14 > 0 else context.atr_5

        if atr <= 0:
            # Keine Volatilitätsdaten
            raw_score = 0
            reason = "Keine Volatilitätsdaten verfügbar"
        else:
            # Verhältnis Level-Größe zu ATR
            ratio = level_size_pct / atr if atr > 0 else 1.0
            optimal_ratio = self.config.optimal_level_size_atr_ratio

            if context.volatility_regime == "HIGH":
                # Bei hoher Vola: Größere Levels bevorzugen (ratio > 1)
                if ratio >= optimal_ratio:
                    raw_score = 80
                    reason = f"Level-Größe passt zu hoher Volatilität (Ratio: {ratio:.1f})"
                elif ratio >= 1.0:
                    raw_score = 60
                    reason = f"Level-Größe akzeptabel bei hoher Volatilität"
                else:
                    raw_score = 20 - (1.0 - ratio) * 40
                    reason = f"Level zu klein für hohe Volatilität"

            elif context.volatility_regime == "LOW":
                # Bei niedriger Vola: Kleinere Levels bevorzugen (ratio < 1)
                if ratio <= 1.0:
                    raw_score = 80
                    reason = f"Level-Größe passt zu niedriger Volatilität"
                elif ratio <= optimal_ratio:
                    raw_score = 60
                    reason = f"Level-Größe akzeptabel bei niedriger Volatilität"
                else:
                    raw_score = 40 - (ratio - optimal_ratio) * 20
                    reason = f"Level zu groß für niedrige Volatilität"
            else:
                # Medium - flexibel
                deviation = abs(ratio - optimal_ratio)
                raw_score = max(0, 70 - deviation * 20)
                reason = f"Mittlere Volatilität, Ratio: {ratio:.1f}"

        weight = self.config.weights[ScoreCategory.VOLATILITY_FIT]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.VOLATILITY_FIT,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_profit_potential(self, score: LevelScore, context: MarketContext):
        """
        Bewertet das Gewinnpotenzial nach Kosten.
        """
        profit_pct = score.profit_pct
        min_profit = self.config.min_profit_pct

        # Kommissionskosten berücksichtigen
        shares = self.config.assumed_shares
        commission_total = self.config.commission_per_trade * 2  # Kauf + Verkauf
        trade_value = score.entry_price * shares
        commission_pct = (commission_total / trade_value) * 100 if trade_value > 0 else 0

        net_profit_pct = profit_pct - commission_pct

        if net_profit_pct < min_profit:
            raw_score = -20
            reason = f"Zu wenig Profit nach Kosten ({net_profit_pct:.2f}%)"
        elif net_profit_pct < min_profit * 2:
            raw_score = 30
            reason = f"Minimaler Profit ({net_profit_pct:.2f}%)"
        elif net_profit_pct < min_profit * 5:
            raw_score = 60
            reason = f"Guter Profit ({net_profit_pct:.2f}%)"
        else:
            raw_score = min(90, 60 + net_profit_pct * 5)
            reason = f"Hoher Profit ({net_profit_pct:.2f}%)"

        weight = self.config.weights[ScoreCategory.PROFIT_POTENTIAL]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.PROFIT_POTENTIAL,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_risk_reward(self, score: LevelScore, context: MarketContext):
        """
        Bewertet das Risk/Reward Verhältnis.

        Risk = Abstand zum Entry (potenzieller Verlust bei sofortiger Umkehr)
        Reward = Profit-Potenzial
        """
        risk = score.risk_pct
        reward = score.profit_pct

        if risk <= 0:
            raw_score = 0
            reason = "Kein Risiko definiert"
        else:
            ratio = reward / risk if risk > 0 else 0

            if ratio >= 2.0:
                raw_score = 90
                reason = f"Exzellentes R/R ({ratio:.1f}:1)"
            elif ratio >= 1.5:
                raw_score = 70
                reason = f"Gutes R/R ({ratio:.1f}:1)"
            elif ratio >= 1.0:
                raw_score = 50
                reason = f"Ausgeglichenes R/R ({ratio:.1f}:1)"
            elif ratio >= 0.5:
                raw_score = 20
                reason = f"Schwaches R/R ({ratio:.1f}:1)"
            else:
                raw_score = -20
                reason = f"Schlechtes R/R ({ratio:.1f}:1)"

        weight = self.config.weights[ScoreCategory.RISK_REWARD]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.RISK_REWARD,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_pattern_match(self, score: LevelScore, context: MarketContext):
        """
        Bewertet basierend auf historischen Mustern.
        """
        prediction = context.pattern_prediction
        confidence = context.pattern_confidence
        side = score.side

        if not prediction or confidence < 0.3:
            raw_score = 0
            reason = "Kein zuverlässiges Pattern erkannt"
        else:
            # Ist das Pattern mit der Trade-Richtung kompatibel?
            bullish_patterns = ["BREAKOUT_UP", "TREND_UP", "BOUNCE_UP", "REVERSAL_UP"]
            bearish_patterns = ["BREAKOUT_DOWN", "TREND_DOWN", "BOUNCE_DOWN", "REVERSAL_DOWN"]

            if side == "LONG" and prediction in bullish_patterns:
                raw_score = confidence * 100
                reason = f"Bullisches Pattern {prediction} unterstützt Long ({confidence:.0%})"
            elif side == "SHORT" and prediction in bearish_patterns:
                raw_score = confidence * 100
                reason = f"Bärisches Pattern {prediction} unterstützt Short ({confidence:.0%})"
            elif side == "LONG" and prediction in bearish_patterns:
                raw_score = -confidence * 50
                reason = f"Bärisches Pattern {prediction} gegen Long ({confidence:.0%})"
            elif side == "SHORT" and prediction in bullish_patterns:
                raw_score = -confidence * 50
                reason = f"Bullisches Pattern {prediction} gegen Short ({confidence:.0%})"
            else:
                raw_score = 0
                reason = f"Pattern {prediction} neutral"

        weight = self.config.weights[ScoreCategory.PATTERN_MATCH]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.PATTERN_MATCH,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_time_suitability(self, score: LevelScore, context: MarketContext):
        """
        Bewertet die Eignung basierend auf der Tageszeit.
        """
        phase = context.trading_phase
        caution = context.caution_level

        # Phasen-basierte Basis-Score
        phase_scores = {
            "PRE_MARKET": 20,        # Wenig Liquidität
            "MARKET_OPEN": 40,       # Volatil, aber Chancen
            "MORNING": 80,           # Gute Phase
            "MIDDAY": 60,            # Okay
            "AFTERNOON": 70,         # Gut
            "POWER_HOUR": 50,        # Volatil
            "CLOSE": 30,             # Gefährlich, Spread
            "AFTER_HOURS": 10,       # Kaum empfohlen
        }

        base_score = phase_scores.get(phase, 50)

        # Caution-Level reduziert Score
        caution_penalty = caution * 15
        raw_score = max(-20, base_score - caution_penalty)

        reason = f"Phase: {phase}, Vorsichtslevel: {caution}"

        weight = self.config.weights[ScoreCategory.TIME_SUITABILITY]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.TIME_SUITABILITY,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_volume_context(self, score: LevelScore, context: MarketContext):
        """
        Bewertet basierend auf dem Volumen-Kontext.
        """
        ratio = context.volume_ratio
        condition = context.volume_condition

        if condition == "EXTREME":
            raw_score = -30
            reason = f"Extremes Volumen - News? ({ratio:.1f}x)"
        elif condition == "SPIKE":
            raw_score = -10
            reason = f"Volumen-Spike ({ratio:.1f}x)"
        elif condition == "HIGH":
            raw_score = 60
            reason = f"Gutes Volumen ({ratio:.1f}x)"
        elif condition == "NORMAL":
            raw_score = 50
            reason = "Normales Volumen"
        elif condition == "LOW":
            raw_score = 20
            reason = f"Niedriges Volumen ({ratio:.1f}x)"
        else:  # VERY_LOW
            raw_score = -10
            reason = f"Sehr niedriges Volumen ({ratio:.1f}x)"

        weight = self.config.weights[ScoreCategory.VOLUME_CONTEXT]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.VOLUME_CONTEXT,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    def _score_trend_alignment(self, score: LevelScore, context: MarketContext):
        """
        Bewertet ob das Level mit dem aktuellen Trend übereinstimmt.
        """
        side = score.side
        short_trend = context.short_term_trend
        medium_trend = context.medium_term_trend

        # Kombinierter Trend (kurzfristig wichtiger)
        combined_trend = short_trend * 0.6 + medium_trend * 0.4

        if side == "LONG":
            if combined_trend > 0.3:
                raw_score = min(80, 50 + combined_trend * 50)
                reason = f"Long mit Aufwärtstrend (+{combined_trend:.1f}%)"
            elif combined_trend < -0.3:
                raw_score = max(-40, -20 - abs(combined_trend) * 30)
                reason = f"Long gegen Abwärtstrend ({combined_trend:.1f}%)"
            else:
                raw_score = 30
                reason = "Long in seitwärts Markt"
        else:  # SHORT
            if combined_trend < -0.3:
                raw_score = min(80, 50 + abs(combined_trend) * 50)
                reason = f"Short mit Abwärtstrend ({combined_trend:.1f}%)"
            elif combined_trend > 0.3:
                raw_score = max(-40, -20 - combined_trend * 30)
                reason = f"Short gegen Aufwärtstrend (+{combined_trend:.1f}%)"
            else:
                raw_score = 30
                reason = "Short in seitwärts Markt"

        weight = self.config.weights[ScoreCategory.TREND_ALIGNMENT]
        score.add_breakdown(ScoreBreakdown(
            category=ScoreCategory.TREND_ALIGNMENT,
            raw_score=raw_score,
            weight=weight,
            weighted_score=raw_score * weight,
            reason=reason
        ))

    # ==================== HELPER METHODS ====================

    def _calc_distance_pct(self, entry: float, current: float) -> float:
        """Berechnet Abstand in Prozent"""
        if current <= 0:
            return 100.0
        return abs(entry - current) / current * 100

    def _calc_profit_pct(self, entry: float, exit: float, side: str) -> float:
        """Berechnet Profit-Potenzial in Prozent"""
        if entry <= 0:
            return 0.0
        if side == "LONG":
            return (exit - entry) / entry * 100
        else:
            return (entry - exit) / entry * 100

    def _determine_recommendation(self, score: LevelScore, context: MarketContext):
        """Bestimmt ob ein Level empfohlen wird"""
        reasons = []

        # Mindest-Score
        if score.total_score < self.config.min_score_for_recommendation:
            reasons.append(f"Score zu niedrig ({score.total_score:.1f})")

        # Max Abstand
        if score.distance_pct > self.config.max_distance_pct:
            reasons.append(f"Abstand zu groß ({score.distance_pct:.2f}%)")

        # Min Profit
        if score.profit_pct < self.config.min_profit_pct:
            reasons.append(f"Profit zu gering ({score.profit_pct:.2f}%)")

        # Extreme Marktbedingungen
        if context.volume_condition == "EXTREME":
            reasons.append("Extremes Volumen")

        if context.caution_level >= 3:
            reasons.append(f"Hoher Vorsichtslevel ({context.caution_level})")

        if reasons:
            score.is_recommended = False
            score.rejection_reason = "; ".join(reasons)
        else:
            score.is_recommended = True

    def _is_cache_valid(self, level_id: str) -> bool:
        """Prüft ob der Cache noch gültig ist"""
        if level_id not in self._score_cache:
            return False
        if self._cache_timestamp is None:
            return False

        elapsed = (datetime.now() - self._cache_timestamp).total_seconds()
        return elapsed < self._cache_ttl_seconds

    def clear_cache(self):
        """Löscht den Score-Cache"""
        self._score_cache.clear()
        self._cache_timestamp = None

    def update_weights(self, new_weights: Dict[ScoreCategory, float]):
        """Aktualisiert die Gewichtungen"""
        self.config.weights.update(new_weights)
        self.clear_cache()
