"""
KI-Controller Analyse-Module

Enthält alle Analyse-Komponenten:
- Volatilitäts-Monitor (ATR, Regime Detection)
- Volumen-Analyzer (Spikes, Anomalien)
- Tageszeit-Profil (Phasen, Empfehlungen)
- Pattern Matcher (Historische Muster)
"""

from .volatility_monitor import (
    VolatilityMonitor,
    VolatilitySnapshot,
    Candle,
)

from .volume_analyzer import (
    VolumeAnalyzer,
    VolumeSnapshot,
    VolumeCondition,
    VolumeTrend,
)

from .time_profile import (
    TimeProfile,
    TimeProfileSnapshot,
    TradingPhase,
    PhaseCharacteristics,
)

from .pattern_matcher import (
    PatternMatcher,
    PatternMatchResult,
    SituationFingerprint,
    HistoricalOutcome,
    MovementPattern,
)

__all__ = [
    # Volatility Monitor
    'VolatilityMonitor',
    'VolatilitySnapshot',
    'Candle',
    # Volume Analyzer
    'VolumeAnalyzer',
    'VolumeSnapshot',
    'VolumeCondition',
    'VolumeTrend',
    # Time Profile
    'TimeProfile',
    'TimeProfileSnapshot',
    'TradingPhase',
    'PhaseCharacteristics',
    # Pattern Matcher
    'PatternMatcher',
    'PatternMatchResult',
    'SituationFingerprint',
    'HistoricalOutcome',
    'MovementPattern',
]
