"""
Level Optimizer

Findet die optimale Kombination von Levels unter Berücksichtigung von:
- Long/Short Balance
- Maximale Anzahl aktiver Levels
- Minimaler Abstand zwischen Levels (Overlap-Vermeidung)
- Risikolimits
- Diversifikation
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from enum import Enum
import itertools


@dataclass
class OptimizationConstraints:
    """Constraints für die Optimierung"""

    # Anzahl-Limits
    max_levels_total: int = 20           # Max. aktive Levels insgesamt
    max_levels_per_symbol: int = 10      # Max. Levels pro Symbol
    max_levels_per_side: int = 15        # Max. Long oder Short

    # Long/Short Balance
    long_short_ratio_min: float = 0.3    # Min. 30% einer Seite
    long_short_ratio_max: float = 0.7    # Max. 70% einer Seite

    # Abstand zwischen Levels
    min_distance_between_levels_pct: float = 0.1  # Min. 0.1% Abstand

    # Score-Schwelle
    min_score_threshold: float = 30.0    # Min. Score für Berücksichtigung

    # Diversifikation
    max_exposure_per_price_zone_pct: float = 30.0  # Max. 30% in einer Preiszone


class OptimizationStrategy(str, Enum):
    """Optimierungs-Strategien"""
    GREEDY = "GREEDY"            # Beste Levels zuerst
    BALANCED = "BALANCED"        # Long/Short ausgleichen
    CONSERVATIVE = "CONSERVATIVE"  # Weniger, aber sichere Levels
    AGGRESSIVE = "AGGRESSIVE"    # Mehr Levels, höheres Risiko


@dataclass
class LevelCandidate:
    """Ein Level-Kandidat für die Optimierung"""
    level_id: str
    symbol: str
    side: str                    # LONG oder SHORT
    entry_price: float
    exit_price: float
    score: float                 # Gesamtscore vom LevelScorer
    is_recommended: bool
    distance_pct: float          # Abstand zum aktuellen Preis
    profit_pct: float            # Profit-Potenzial

    @property
    def price_zone(self) -> int:
        """Gibt die Preiszone zurück (für Diversifikation)"""
        # Teile Preisbereich in 10 Zonen ein
        return int(self.entry_price // (self.entry_price * 0.01))  # 1% Zonen


@dataclass
class OptimizationResult:
    """Ergebnis der Optimierung"""
    selected_levels: List[LevelCandidate] = field(default_factory=list)
    rejected_levels: List[Tuple[LevelCandidate, str]] = field(default_factory=list)

    # Statistiken
    total_score: float = 0.0
    long_count: int = 0
    short_count: int = 0
    long_ratio: float = 0.5
    symbols: Set[str] = field(default_factory=set)

    # Metadaten
    strategy: OptimizationStrategy = OptimizationStrategy.BALANCED
    timestamp: datetime = field(default_factory=datetime.now)
    iterations: int = 0
    optimization_time_ms: float = 0.0

    @property
    def total_count(self) -> int:
        return len(self.selected_levels)

    def to_dict(self) -> dict:
        return {
            'selected_levels': [
                {
                    'level_id': l.level_id,
                    'symbol': l.symbol,
                    'side': l.side,
                    'score': l.score,
                }
                for l in self.selected_levels
            ],
            'rejected_count': len(self.rejected_levels),
            'total_score': self.total_score,
            'long_count': self.long_count,
            'short_count': self.short_count,
            'long_ratio': self.long_ratio,
            'symbols': list(self.symbols),
            'strategy': self.strategy.value,
            'timestamp': self.timestamp.isoformat(),
            'iterations': self.iterations,
            'optimization_time_ms': self.optimization_time_ms,
        }


class LevelOptimizer:
    """
    Optimiert die Auswahl von Levels für maximale Effizienz.

    Der Optimizer wählt aus einer Liste von bewerteten Levels
    die optimale Kombination unter Berücksichtigung aller Constraints.
    """

    def __init__(
        self,
        constraints: Optional[OptimizationConstraints] = None,
        strategy: OptimizationStrategy = OptimizationStrategy.BALANCED
    ):
        self.constraints = constraints or OptimizationConstraints()
        self.strategy = strategy

        # Cache für bereits aktive Levels
        self._active_levels: Dict[str, LevelCandidate] = {}

    def optimize(
        self,
        candidates: List[LevelCandidate],
        current_active: Optional[List[LevelCandidate]] = None,
        current_price: float = 0.0
    ) -> OptimizationResult:
        """
        Findet die optimale Level-Kombination.

        Args:
            candidates: Liste aller Level-Kandidaten (bereits bewertet)
            current_active: Bereits aktive Levels (optional)
            current_price: Aktueller Preis für Distanz-Berechnungen

        Returns:
            OptimizationResult mit ausgewählten Levels
        """
        import time
        start_time = time.time()

        result = OptimizationResult(strategy=self.strategy)

        # Bereits aktive Levels vormerken
        if current_active:
            for level in current_active:
                self._active_levels[level.level_id] = level

        # Filter: Nur empfohlene Levels mit ausreichendem Score
        filtered = self._filter_candidates(candidates)

        # Sortiere nach Score (absteigend)
        filtered.sort(key=lambda x: x.score, reverse=True)

        # Wähle basierend auf Strategie
        if self.strategy == OptimizationStrategy.GREEDY:
            self._optimize_greedy(filtered, result)
        elif self.strategy == OptimizationStrategy.BALANCED:
            self._optimize_balanced(filtered, result)
        elif self.strategy == OptimizationStrategy.CONSERVATIVE:
            self._optimize_conservative(filtered, result)
        else:  # AGGRESSIVE
            self._optimize_aggressive(filtered, result)

        # Statistiken berechnen
        self._calculate_statistics(result)

        result.optimization_time_ms = (time.time() - start_time) * 1000
        return result

    def suggest_changes(
        self,
        candidates: List[LevelCandidate],
        current_active: List[LevelCandidate],
        current_price: float = 0.0
    ) -> Tuple[List[LevelCandidate], List[LevelCandidate]]:
        """
        Schlägt Änderungen zur aktuellen Auswahl vor.

        Returns:
            (to_add, to_remove): Levels zum Hinzufügen und Entfernen
        """
        # Optimale Kombination berechnen
        optimal = self.optimize(candidates, current_active, current_price)

        optimal_ids = {l.level_id for l in optimal.selected_levels}
        current_ids = {l.level_id for l in current_active}

        # Zu hinzufügende Levels
        to_add = [l for l in optimal.selected_levels if l.level_id not in current_ids]

        # Zu entfernende Levels
        to_remove = [l for l in current_active if l.level_id not in optimal_ids]

        return to_add, to_remove

    # ==================== OPTIMIERUNGS-STRATEGIEN ====================

    def _optimize_greedy(self, candidates: List[LevelCandidate], result: OptimizationResult):
        """
        Greedy-Strategie: Nimm die besten Levels der Reihe nach.
        """
        selected_entries: Set[float] = set()  # Für Overlap-Check

        for candidate in candidates:
            result.iterations += 1

            # Prüfe alle Constraints
            violation = self._check_constraints(candidate, result, selected_entries)

            if violation:
                result.rejected_levels.append((candidate, violation))
            else:
                result.selected_levels.append(candidate)
                selected_entries.add(candidate.entry_price)

                # Max-Limit erreicht?
                if len(result.selected_levels) >= self.constraints.max_levels_total:
                    break

    def _optimize_balanced(self, candidates: List[LevelCandidate], result: OptimizationResult):
        """
        Balanced-Strategie: Achte auf Long/Short-Balance.
        """
        selected_entries: Set[float] = set()
        long_candidates = [c for c in candidates if c.side == "LONG"]
        short_candidates = [c for c in candidates if c.side == "SHORT"]

        # Alternierend hinzufügen für bessere Balance
        long_idx = 0
        short_idx = 0
        prefer_long = True  # Starte mit Long

        while len(result.selected_levels) < self.constraints.max_levels_total:
            result.iterations += 1

            # Wähle nächsten Kandidaten
            if prefer_long and long_idx < len(long_candidates):
                candidate = long_candidates[long_idx]
                long_idx += 1
            elif not prefer_long and short_idx < len(short_candidates):
                candidate = short_candidates[short_idx]
                short_idx += 1
            elif long_idx < len(long_candidates):
                candidate = long_candidates[long_idx]
                long_idx += 1
            elif short_idx < len(short_candidates):
                candidate = short_candidates[short_idx]
                short_idx += 1
            else:
                break  # Keine Kandidaten mehr

            # Prüfe Constraints
            violation = self._check_constraints(candidate, result, selected_entries)

            if not violation:
                result.selected_levels.append(candidate)
                selected_entries.add(candidate.entry_price)
                prefer_long = not prefer_long  # Wechsle Präferenz
            else:
                result.rejected_levels.append((candidate, violation))

    def _optimize_conservative(self, candidates: List[LevelCandidate], result: OptimizationResult):
        """
        Conservative-Strategie: Weniger Levels, höhere Qualität.
        """
        # Erhöhe Score-Schwelle
        high_quality = [c for c in candidates if c.score >= self.constraints.min_score_threshold * 1.5]

        # Reduzierte Max-Levels
        original_max = self.constraints.max_levels_total
        self.constraints.max_levels_total = min(10, original_max // 2)

        self._optimize_balanced(high_quality, result)

        # Wiederherstellen
        self.constraints.max_levels_total = original_max

    def _optimize_aggressive(self, candidates: List[LevelCandidate], result: OptimizationResult):
        """
        Aggressive-Strategie: Mehr Levels, auch mit niedrigerem Score.
        """
        # Reduziere Score-Schwelle und min. Abstand
        original_threshold = self.constraints.min_score_threshold
        original_distance = self.constraints.min_distance_between_levels_pct

        self.constraints.min_score_threshold = max(10, original_threshold * 0.5)
        self.constraints.min_distance_between_levels_pct = original_distance * 0.5

        self._optimize_greedy(candidates, result)

        # Wiederherstellen
        self.constraints.min_score_threshold = original_threshold
        self.constraints.min_distance_between_levels_pct = original_distance

    # ==================== CONSTRAINT CHECKING ====================

    def _check_constraints(
        self,
        candidate: LevelCandidate,
        result: OptimizationResult,
        selected_entries: Set[float]
    ) -> Optional[str]:
        """
        Prüft alle Constraints für einen Kandidaten.

        Returns:
            None wenn alle Constraints erfüllt, sonst Grund für Ablehnung
        """
        # 1. Score-Schwelle
        if candidate.score < self.constraints.min_score_threshold:
            return f"Score zu niedrig ({candidate.score:.1f})"

        # 2. Max Levels total
        if len(result.selected_levels) >= self.constraints.max_levels_total:
            return "Max. Levels erreicht"

        # 3. Max Levels pro Side
        current_side_count = sum(1 for l in result.selected_levels if l.side == candidate.side)
        if current_side_count >= self.constraints.max_levels_per_side:
            return f"Max. {candidate.side} Levels erreicht"

        # 4. Long/Short Balance
        if len(result.selected_levels) > 0:
            new_long = sum(1 for l in result.selected_levels if l.side == "LONG")
            new_short = sum(1 for l in result.selected_levels if l.side == "SHORT")

            if candidate.side == "LONG":
                new_long += 1
            else:
                new_short += 1

            total = new_long + new_short
            long_ratio = new_long / total

            if long_ratio > self.constraints.long_short_ratio_max:
                return f"Long-Ratio zu hoch ({long_ratio:.0%})"
            if long_ratio < self.constraints.long_short_ratio_min and new_short > 0:
                return f"Long-Ratio zu niedrig ({long_ratio:.0%})"

        # 5. Max Levels pro Symbol
        symbol_count = sum(1 for l in result.selected_levels if l.symbol == candidate.symbol)
        if symbol_count >= self.constraints.max_levels_per_symbol:
            return f"Max. Levels für {candidate.symbol} erreicht"

        # 6. Min Abstand zwischen Levels (Overlap-Check)
        for existing_price in selected_entries:
            distance = abs(candidate.entry_price - existing_price) / candidate.entry_price * 100
            if distance < self.constraints.min_distance_between_levels_pct:
                return f"Zu nah an bestehendem Level ({distance:.2f}%)"

        # 7. Diversifikation (Preiszonen)
        zone = candidate.price_zone
        zone_count = sum(1 for l in result.selected_levels if l.price_zone == zone)
        total_count = len(result.selected_levels) + 1
        zone_ratio = (zone_count + 1) / total_count * 100

        if zone_ratio > self.constraints.max_exposure_per_price_zone_pct:
            return f"Zu viel in Preiszone {zone} ({zone_ratio:.0f}%)"

        return None

    # ==================== HELPER METHODS ====================

    def _filter_candidates(self, candidates: List[LevelCandidate]) -> List[LevelCandidate]:
        """Filtert ungeeignete Kandidaten heraus"""
        filtered = []
        for c in candidates:
            # Empfohlene Levels bevorzugen
            if not c.is_recommended and c.score < self.constraints.min_score_threshold * 1.2:
                continue

            # Bereits aktive Levels nicht nochmal auswählen
            if c.level_id in self._active_levels:
                continue

            filtered.append(c)

        return filtered

    def _calculate_statistics(self, result: OptimizationResult):
        """Berechnet Statistiken für das Ergebnis"""
        if not result.selected_levels:
            return

        result.total_score = sum(l.score for l in result.selected_levels)
        result.long_count = sum(1 for l in result.selected_levels if l.side == "LONG")
        result.short_count = sum(1 for l in result.selected_levels if l.side == "SHORT")

        total = result.long_count + result.short_count
        result.long_ratio = result.long_count / total if total > 0 else 0.5

        result.symbols = {l.symbol for l in result.selected_levels}

    def set_strategy(self, strategy: OptimizationStrategy):
        """Ändert die Optimierungs-Strategie"""
        self.strategy = strategy

    def update_constraints(self, **kwargs):
        """Aktualisiert einzelne Constraints"""
        for key, value in kwargs.items():
            if hasattr(self.constraints, key):
                setattr(self.constraints, key, value)

    def clear_active(self):
        """Löscht Cache der aktiven Levels"""
        self._active_levels.clear()


# ==================== UTILITY FUNCTIONS ====================

def create_candidate_from_score(level_score: Any) -> LevelCandidate:
    """
    Erstellt einen LevelCandidate aus einem LevelScore.

    Args:
        level_score: LevelScore-Objekt vom LevelScorer

    Returns:
        LevelCandidate für den Optimizer
    """
    return LevelCandidate(
        level_id=level_score.level_id,
        symbol=level_score.symbol,
        side=level_score.side,
        entry_price=level_score.entry_price,
        exit_price=level_score.exit_price,
        score=level_score.total_score,
        is_recommended=level_score.is_recommended,
        distance_pct=level_score.distance_pct,
        profit_pct=level_score.profit_pct,
    )


def optimize_for_symbol(
    candidates: List[LevelCandidate],
    symbol: str,
    max_levels: int = 5
) -> List[LevelCandidate]:
    """
    Optimiert Levels für ein einzelnes Symbol.

    Vereinfachte Funktion für Symbol-spezifische Optimierung.
    """
    symbol_candidates = [c for c in candidates if c.symbol == symbol]

    constraints = OptimizationConstraints(
        max_levels_total=max_levels,
        max_levels_per_symbol=max_levels,
    )

    optimizer = LevelOptimizer(constraints=constraints)
    result = optimizer.optimize(symbol_candidates)

    return result.selected_levels
