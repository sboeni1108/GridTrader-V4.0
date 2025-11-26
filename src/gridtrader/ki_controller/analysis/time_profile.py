"""
Time Profile

Analysiert und trackt Tageszeit-basierte Muster für Trading-Entscheidungen.

Typische Muster im US-Markt (NY Zeit):
- 09:30-10:30: Hohe Volatilität (Marktöffnung)
- 10:30-12:00: Moderate Volatilität
- 12:00-14:00: Niedrige Volatilität (Mittagspause)
- 14:00-15:30: Moderate Volatilität
- 15:30-16:00: Erhöhte Volatilität (Marktschluss)
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import defaultdict

# Timezone support
try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except ImportError:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")


class TradingPhase(str, Enum):
    """Handelsphase basierend auf Tageszeit"""
    PRE_MARKET = "PRE_MARKET"           # Vor 09:30
    MARKET_OPEN = "MARKET_OPEN"         # 09:30-10:30 (hohe Volatilität)
    MORNING = "MORNING"                  # 10:30-12:00
    MIDDAY = "MIDDAY"                   # 12:00-14:00 (Lunch, niedrige Vola)
    AFTERNOON = "AFTERNOON"             # 14:00-15:30
    MARKET_CLOSE = "MARKET_CLOSE"       # 15:30-16:00 (erhöhte Vola)
    AFTER_HOURS = "AFTER_HOURS"         # Nach 16:00


class DayOfWeek(str, Enum):
    """Wochentag"""
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


@dataclass
class PhaseCharacteristics:
    """Charakteristiken einer Handelsphase"""
    phase: TradingPhase
    typical_volatility: str  # "HIGH", "MEDIUM", "LOW"
    recommended_step_multiplier: float  # Multiplier für Step-Größe
    recommended_max_levels: int  # Empfohlene max. aktive Levels
    trading_allowed: bool = True
    notes: str = ""


@dataclass
class TimeProfileSnapshot:
    """Snapshot des aktuellen Zeit-Profils"""
    timestamp: datetime
    ny_time: datetime

    # Aktuelle Phase
    phase: TradingPhase
    phase_progress: float  # 0-1, wie weit in der Phase

    # Zeit bis zum nächsten Event
    minutes_since_open: int = 0
    minutes_until_close: int = 0
    minutes_in_phase: int = 0
    minutes_until_phase_change: int = 0

    # Empfehlungen
    recommended_volatility_assumption: str = "MEDIUM"
    recommended_step_multiplier: float = 1.0
    recommended_max_levels: int = 10
    trading_recommended: bool = True
    caution_level: int = 0  # 0-3, 0=normal, 3=sehr vorsichtig

    # Wochentag-spezifisch
    day_of_week: DayOfWeek = DayOfWeek.MONDAY
    is_friday_afternoon: bool = False  # Besondere Vorsicht
    is_monday_morning: bool = False    # Oft Gap-Risiko

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'ny_time': self.ny_time.isoformat(),
            'phase': self.phase.value,
            'phase_progress': self.phase_progress,
            'minutes_since_open': self.minutes_since_open,
            'minutes_until_close': self.minutes_until_close,
            'minutes_in_phase': self.minutes_in_phase,
            'minutes_until_phase_change': self.minutes_until_phase_change,
            'recommended_volatility_assumption': self.recommended_volatility_assumption,
            'recommended_step_multiplier': self.recommended_step_multiplier,
            'recommended_max_levels': self.recommended_max_levels,
            'trading_recommended': self.trading_recommended,
            'caution_level': self.caution_level,
            'day_of_week': self.day_of_week.value,
            'is_friday_afternoon': self.is_friday_afternoon,
            'is_monday_morning': self.is_monday_morning,
        }


class TimeProfile:
    """
    Analysiert Tageszeit-Muster und gibt Empfehlungen.

    Berücksichtigt:
    - Typische Volatilitätsmuster nach Tageszeit
    - Wochentag (Montag/Freitag besonders)
    - Historische Muster für spezifische Symbole
    """

    def __init__(self):
        # Phasen-Definition (NY Zeit)
        self._phase_schedule = [
            (time(0, 0), time(9, 30), TradingPhase.PRE_MARKET),
            (time(9, 30), time(10, 30), TradingPhase.MARKET_OPEN),
            (time(10, 30), time(12, 0), TradingPhase.MORNING),
            (time(12, 0), time(14, 0), TradingPhase.MIDDAY),
            (time(14, 0), time(15, 30), TradingPhase.AFTERNOON),
            (time(15, 30), time(16, 0), TradingPhase.MARKET_CLOSE),
            (time(16, 0), time(23, 59, 59), TradingPhase.AFTER_HOURS),
        ]

        # Charakteristiken pro Phase
        self._phase_characteristics: Dict[TradingPhase, PhaseCharacteristics] = {
            TradingPhase.PRE_MARKET: PhaseCharacteristics(
                phase=TradingPhase.PRE_MARKET,
                typical_volatility="UNKNOWN",
                recommended_step_multiplier=1.5,
                recommended_max_levels=5,
                trading_allowed=False,
                notes="Kein regulärer Handel"
            ),
            TradingPhase.MARKET_OPEN: PhaseCharacteristics(
                phase=TradingPhase.MARKET_OPEN,
                typical_volatility="HIGH",
                recommended_step_multiplier=1.5,
                recommended_max_levels=8,
                trading_allowed=True,
                notes="Höchste Volatilität, große Kerzen"
            ),
            TradingPhase.MORNING: PhaseCharacteristics(
                phase=TradingPhase.MORNING,
                typical_volatility="MEDIUM",
                recommended_step_multiplier=1.0,
                recommended_max_levels=12,
                trading_allowed=True,
                notes="Gute Trading-Zeit"
            ),
            TradingPhase.MIDDAY: PhaseCharacteristics(
                phase=TradingPhase.MIDDAY,
                typical_volatility="LOW",
                recommended_step_multiplier=0.7,
                recommended_max_levels=15,
                trading_allowed=True,
                notes="Ruhige Phase, kleinere Steps"
            ),
            TradingPhase.AFTERNOON: PhaseCharacteristics(
                phase=TradingPhase.AFTERNOON,
                typical_volatility="MEDIUM",
                recommended_step_multiplier=1.0,
                recommended_max_levels=12,
                trading_allowed=True,
                notes="Wieder mehr Aktivität"
            ),
            TradingPhase.MARKET_CLOSE: PhaseCharacteristics(
                phase=TradingPhase.MARKET_CLOSE,
                typical_volatility="HIGH",
                recommended_step_multiplier=1.3,
                recommended_max_levels=8,
                trading_allowed=True,
                notes="Erhöhte Volatilität, Vorsicht"
            ),
            TradingPhase.AFTER_HOURS: PhaseCharacteristics(
                phase=TradingPhase.AFTER_HOURS,
                typical_volatility="UNKNOWN",
                recommended_step_multiplier=1.5,
                recommended_max_levels=5,
                trading_allowed=False,
                notes="Kein regulärer Handel"
            ),
        }

        # Symbol-spezifische historische Daten
        # Dict[symbol][phase] = {"avg_atr": x, "avg_range": y, "sample_count": n}
        self._symbol_history: Dict[str, Dict[TradingPhase, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"avg_atr": 0, "avg_range": 0, "sample_count": 0})
        )

        # Cache für letzte Snapshots
        self._last_snapshot: Optional[TimeProfileSnapshot] = None
        self._last_update: Optional[datetime] = None

    def get_current_snapshot(self) -> TimeProfileSnapshot:
        """
        Gibt den aktuellen Zeit-Profil Snapshot zurück.

        Cached für 10 Sekunden um Berechnungen zu sparen.
        """
        now = datetime.now()

        # Cache prüfen
        if (self._last_snapshot and self._last_update and
                (now - self._last_update).total_seconds() < 10):
            return self._last_snapshot

        # Neuen Snapshot berechnen
        snapshot = self._calculate_snapshot(now)
        self._last_snapshot = snapshot
        self._last_update = now

        return snapshot

    def get_current_phase(self) -> TradingPhase:
        """Gibt die aktuelle Handelsphase zurück."""
        return self.get_current_snapshot().phase

    def get_phase_characteristics(
        self,
        phase: Optional[TradingPhase] = None
    ) -> PhaseCharacteristics:
        """Gibt die Charakteristiken einer Phase zurück."""
        if phase is None:
            phase = self.get_current_phase()
        return self._phase_characteristics[phase]

    def is_market_hours(self) -> bool:
        """Prüft ob aktuell Handelszeit ist."""
        phase = self.get_current_phase()
        return phase not in (TradingPhase.PRE_MARKET, TradingPhase.AFTER_HOURS)

    def is_high_volatility_expected(self) -> bool:
        """Prüft ob aktuell hohe Volatilität erwartet wird."""
        phase = self.get_current_phase()
        chars = self._phase_characteristics[phase]
        return chars.typical_volatility == "HIGH"

    def get_recommended_step_multiplier(self, symbol: Optional[str] = None) -> float:
        """
        Gibt den empfohlenen Step-Multiplier zurück.

        Args:
            symbol: Optional - für Symbol-spezifische Anpassung
        """
        chars = self.get_phase_characteristics()
        base_multiplier = chars.recommended_step_multiplier

        # Symbol-spezifische Anpassung
        if symbol and symbol in self._symbol_history:
            phase = self.get_current_phase()
            history = self._symbol_history[symbol][phase]
            if history["sample_count"] >= 10:
                # Anpassung basierend auf historischer Volatilität
                # TODO: Implementierung für Phase 3
                pass

        return base_multiplier

    def get_caution_level(self) -> int:
        """
        Gibt das Vorsichts-Level zurück (0-3).

        0 = Normal
        1 = Leicht erhöht (z.B. Marktöffnung)
        2 = Erhöht (z.B. Freitag Nachmittag)
        3 = Sehr hoch (z.B. kurz vor Marktschluss)
        """
        snapshot = self.get_current_snapshot()
        return snapshot.caution_level

    def should_reduce_positions(self) -> Tuple[bool, str]:
        """
        Prüft ob Positionen reduziert werden sollten basierend auf Zeit.

        Returns:
            (should_reduce, reason)
        """
        snapshot = self.get_current_snapshot()

        # Kurz vor Marktschluss
        if snapshot.minutes_until_close <= 15:
            return True, f"Nur noch {snapshot.minutes_until_close} Minuten bis Marktschluss"

        # Freitag Nachmittag
        if snapshot.is_friday_afternoon and snapshot.minutes_until_close <= 60:
            return True, "Freitag Nachmittag - Wochenend-Risiko"

        return False, ""

    def record_observation(
        self,
        symbol: str,
        atr: float,
        candle_range: float,
        phase: Optional[TradingPhase] = None
    ):
        """
        Zeichnet eine Beobachtung für Symbol-spezifisches Lernen auf.

        Args:
            symbol: Symbol
            atr: Beobachteter ATR
            candle_range: Beobachtete Kerzen-Range in %
            phase: Handelsphase (default: aktuell)
        """
        if phase is None:
            phase = self.get_current_phase()

        history = self._symbol_history[symbol][phase]

        # Running Average aktualisieren
        n = history["sample_count"]
        if n == 0:
            history["avg_atr"] = atr
            history["avg_range"] = candle_range
        else:
            # Exponential Moving Average (mehr Gewicht auf neuere Daten)
            alpha = 0.1  # 10% Gewicht auf neuen Wert
            history["avg_atr"] = alpha * atr + (1 - alpha) * history["avg_atr"]
            history["avg_range"] = alpha * candle_range + (1 - alpha) * history["avg_range"]

        history["sample_count"] = n + 1

    def get_symbol_phase_stats(
        self,
        symbol: str,
        phase: Optional[TradingPhase] = None
    ) -> Optional[dict]:
        """
        Gibt historische Statistiken für ein Symbol in einer Phase zurück.
        """
        if phase is None:
            phase = self.get_current_phase()

        if symbol not in self._symbol_history:
            return None

        return dict(self._symbol_history[symbol][phase])

    # ==================== PRIVATE METHODS ====================

    def _calculate_snapshot(self, now: datetime) -> TimeProfileSnapshot:
        """Berechnet einen neuen Snapshot."""
        # NY Zeit bestimmen
        try:
            if now.tzinfo is None:
                # Naive datetime - assume local, convert to NY
                ny_now = datetime.now(NY_TZ)
            else:
                ny_now = now.astimezone(NY_TZ)
        except Exception:
            ny_now = now  # Fallback

        ny_time = ny_now.time()
        ny_date = ny_now.date()

        # Phase bestimmen
        phase = self._get_phase_for_time(ny_time)
        phase_start, phase_end = self._get_phase_boundaries(phase)

        # Phase Progress
        if phase_start and phase_end:
            total_seconds = self._time_diff_seconds(phase_start, phase_end)
            elapsed_seconds = self._time_diff_seconds(phase_start, ny_time)
            phase_progress = elapsed_seconds / total_seconds if total_seconds > 0 else 0
            minutes_in_phase = int(elapsed_seconds / 60)
            minutes_until_change = int((total_seconds - elapsed_seconds) / 60)
        else:
            phase_progress = 0.5
            minutes_in_phase = 0
            minutes_until_change = 0

        # Zeit seit Marktöffnung / bis Schluss
        market_open = time(9, 30)
        market_close = time(16, 0)

        if market_open <= ny_time <= market_close:
            minutes_since_open = self._time_diff_seconds(market_open, ny_time) // 60
            minutes_until_close = self._time_diff_seconds(ny_time, market_close) // 60
        elif ny_time < market_open:
            minutes_since_open = 0
            minutes_until_close = self._time_diff_seconds(market_open, market_close) // 60
        else:
            minutes_since_open = self._time_diff_seconds(market_open, market_close) // 60
            minutes_until_close = 0

        # Wochentag
        weekday = ny_now.weekday()
        day_of_week = list(DayOfWeek)[weekday]

        # Besondere Situationen
        is_friday_afternoon = (
            weekday == 4 and
            ny_time >= time(14, 0)
        )
        is_monday_morning = (
            weekday == 0 and
            ny_time <= time(10, 30)
        )

        # Empfehlungen basierend auf Phase
        chars = self._phase_characteristics[phase]

        # Caution Level berechnen
        caution_level = 0
        if phase == TradingPhase.MARKET_OPEN:
            caution_level = 1
        if phase == TradingPhase.MARKET_CLOSE:
            caution_level = 2
        if minutes_until_close <= 15 and minutes_until_close > 0:
            caution_level = 3
        if is_friday_afternoon:
            caution_level = max(caution_level, 2)
        if is_monday_morning:
            caution_level = max(caution_level, 1)

        # Trading-Empfehlung
        trading_recommended = (
            chars.trading_allowed and
            weekday < 5 and  # Kein Wochenende
            minutes_until_close > 5  # Mindestens 5 Min bis Schluss
        )

        return TimeProfileSnapshot(
            timestamp=now,
            ny_time=ny_now,
            phase=phase,
            phase_progress=phase_progress,
            minutes_since_open=int(minutes_since_open),
            minutes_until_close=int(minutes_until_close),
            minutes_in_phase=minutes_in_phase,
            minutes_until_phase_change=minutes_until_change,
            recommended_volatility_assumption=chars.typical_volatility,
            recommended_step_multiplier=chars.recommended_step_multiplier,
            recommended_max_levels=chars.recommended_max_levels,
            trading_recommended=trading_recommended,
            caution_level=caution_level,
            day_of_week=day_of_week,
            is_friday_afternoon=is_friday_afternoon,
            is_monday_morning=is_monday_morning,
        )

    def _get_phase_for_time(self, t: time) -> TradingPhase:
        """Bestimmt die Phase für eine gegebene Zeit."""
        for start, end, phase in self._phase_schedule:
            if start <= t < end:
                return phase

        return TradingPhase.AFTER_HOURS

    def _get_phase_boundaries(
        self,
        phase: TradingPhase
    ) -> Tuple[Optional[time], Optional[time]]:
        """Gibt Start- und Endzeit einer Phase zurück."""
        for start, end, p in self._phase_schedule:
            if p == phase:
                return start, end
        return None, None

    def _time_diff_seconds(self, t1: time, t2: time) -> int:
        """Berechnet Differenz in Sekunden zwischen zwei Zeiten."""
        s1 = t1.hour * 3600 + t1.minute * 60 + t1.second
        s2 = t2.hour * 3600 + t2.minute * 60 + t2.second
        return s2 - s1

    def update_phase_characteristics(
        self,
        phase: TradingPhase,
        typical_volatility: Optional[str] = None,
        step_multiplier: Optional[float] = None,
        max_levels: Optional[int] = None
    ):
        """Erlaubt Anpassung der Phasen-Charakteristiken."""
        chars = self._phase_characteristics[phase]

        if typical_volatility:
            chars.typical_volatility = typical_volatility
        if step_multiplier is not None:
            chars.recommended_step_multiplier = step_multiplier
        if max_levels is not None:
            chars.recommended_max_levels = max_levels
