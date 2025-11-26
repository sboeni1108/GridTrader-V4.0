"""
KI-Controller Konfiguration

Alle Parameter sind konfigurierbar mit sinnvollen Default-Werten.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import time
import json
from pathlib import Path


class ControllerMode(str, Enum):
    """Betriebsmodus des KI-Controllers"""
    OFF = "OFF"                  # Controller deaktiviert
    ALERT = "ALERT"              # Controller schlägt vor, User bestätigt
    AUTONOMOUS = "AUTONOMOUS"    # Vollautomatisch


class VolatilityRegime(str, Enum):
    """Volatilitäts-Regime"""
    HIGH = "HIGH"      # Hohe Volatilität (z.B. Marktöffnung)
    MEDIUM = "MEDIUM"  # Moderate Volatilität
    LOW = "LOW"        # Niedrige Volatilität
    UNKNOWN = "UNKNOWN"


@dataclass
class RiskLimits:
    """Hard Limits für Risikomanagement"""

    # Maximaler Tagesverlust (absolut in USD)
    max_daily_loss: Decimal = Decimal("500.00")

    # Maximale offene Positionen (Anzahl Aktien)
    max_open_positions: int = 2000

    # Maximales Exposure pro Symbol (in USD)
    max_exposure_per_symbol: Decimal = Decimal("10000.00")

    # Maximale Anzahl aktiver Levels gleichzeitig
    max_active_levels: int = 20

    # Soft Limits (Warnung bei Annäherung, % von Hard Limit)
    soft_limit_threshold: float = 0.8  # Warnung bei 80%

    # Emergency Stop - sofort alles schließen wenn einer dieser Werte erreicht wird
    emergency_loss_threshold: Decimal = Decimal("1000.00")  # Doppelter max_daily_loss

    # Black Swan Detection
    sudden_drop_threshold: float = 5.0  # % Drop in 1 Minute = Alarm

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary für Serialisierung"""
        return {
            'max_daily_loss': str(self.max_daily_loss),
            'max_open_positions': self.max_open_positions,
            'max_exposure_per_symbol': str(self.max_exposure_per_symbol),
            'max_active_levels': self.max_active_levels,
            'soft_limit_threshold': self.soft_limit_threshold,
            'emergency_loss_threshold': str(self.emergency_loss_threshold),
            'sudden_drop_threshold': self.sudden_drop_threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RiskLimits':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            max_daily_loss=Decimal(data.get('max_daily_loss', '500.00')),
            max_open_positions=data.get('max_open_positions', 2000),
            max_exposure_per_symbol=Decimal(data.get('max_exposure_per_symbol', '10000.00')),
            max_active_levels=data.get('max_active_levels', 20),
            soft_limit_threshold=data.get('soft_limit_threshold', 0.8),
            emergency_loss_threshold=Decimal(data.get('emergency_loss_threshold', '1000.00')),
            sudden_drop_threshold=data.get('sudden_drop_threshold', 5.0),
        )


@dataclass
class TradingHoursConfig:
    """Handelszeiten-Konfiguration (NY Zeit)"""

    # Standard-Handelszeiten
    market_open: time = field(default_factory=lambda: time(9, 30))
    market_close: time = field(default_factory=lambda: time(16, 0))

    # Volatilitätsphasen
    high_volatility_start: time = field(default_factory=lambda: time(9, 30))
    high_volatility_end: time = field(default_factory=lambda: time(10, 30))

    medium_volatility_end: time = field(default_factory=lambda: time(14, 0))
    # Nach 14:00 = low volatility bis market close

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'market_open': self.market_open.isoformat(),
            'market_close': self.market_close.isoformat(),
            'high_volatility_start': self.high_volatility_start.isoformat(),
            'high_volatility_end': self.high_volatility_end.isoformat(),
            'medium_volatility_end': self.medium_volatility_end.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradingHoursConfig':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            market_open=time.fromisoformat(data.get('market_open', '09:30:00')),
            market_close=time.fromisoformat(data.get('market_close', '16:00:00')),
            high_volatility_start=time.fromisoformat(data.get('high_volatility_start', '09:30:00')),
            high_volatility_end=time.fromisoformat(data.get('high_volatility_end', '10:30:00')),
            medium_volatility_end=time.fromisoformat(data.get('medium_volatility_end', '14:00:00')),
        )


@dataclass
class AnalysisConfig:
    """Analyse-Parameter"""

    # ATR (Average True Range) Perioden
    atr_period_short: int = 5      # 5 Kerzen für kurzfristige Volatilität
    atr_period_medium: int = 14    # 14 Kerzen für mittelfristige Volatilität
    atr_period_long: int = 50      # 50 Kerzen für langfristige Volatilität

    # Kerzen-Timeframe für Analyse (in Minuten)
    candle_timeframe: int = 1      # 1-Minuten Kerzen

    # Volumen-Analyse
    volume_ma_period: int = 20     # Moving Average für Volumen
    volume_spike_threshold: float = 2.0  # Volumen > 2x MA = Spike

    # Pattern Matching
    pattern_lookback_days: int = 30      # Wie weit zurück für Muster suchen
    pattern_similarity_threshold: float = 0.75  # Min. Ähnlichkeit für Match

    # Re-Evaluation Intervall (Sekunden)
    reevaluation_interval: int = 30  # Alle 30 Sekunden neu bewerten

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'atr_period_short': self.atr_period_short,
            'atr_period_medium': self.atr_period_medium,
            'atr_period_long': self.atr_period_long,
            'candle_timeframe': self.candle_timeframe,
            'volume_ma_period': self.volume_ma_period,
            'volume_spike_threshold': self.volume_spike_threshold,
            'pattern_lookback_days': self.pattern_lookback_days,
            'pattern_similarity_threshold': self.pattern_similarity_threshold,
            'reevaluation_interval': self.reevaluation_interval,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisConfig':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            atr_period_short=data.get('atr_period_short', 5),
            atr_period_medium=data.get('atr_period_medium', 14),
            atr_period_long=data.get('atr_period_long', 50),
            candle_timeframe=data.get('candle_timeframe', 1),
            volume_ma_period=data.get('volume_ma_period', 20),
            volume_spike_threshold=data.get('volume_spike_threshold', 2.0),
            pattern_lookback_days=data.get('pattern_lookback_days', 30),
            pattern_similarity_threshold=data.get('pattern_similarity_threshold', 0.75),
            reevaluation_interval=data.get('reevaluation_interval', 30),
        )


@dataclass
class DecisionConfig:
    """Entscheidungs-Parameter"""

    # Level-Auswahl
    max_levels_per_decision: int = 10    # Max. Levels gleichzeitig aktivieren
    min_level_distance_pct: float = 0.1  # Min. Abstand zwischen Levels (%)

    # Long/Short Balance
    long_short_ratio_min: float = 0.3    # Min. 30% Long ODER Short
    long_short_ratio_max: float = 0.7    # Max. 70% Long ODER Short

    # Haltezeiten (Anti-Overtrading)
    min_level_hold_time_sec: int = 60       # Min. Zeit bevor Level entfernt wird
    min_combination_hold_time_sec: int = 300  # Min. Zeit für Level-Kombination (5 Min)
    max_changes_per_hour: int = 10            # Max. Änderungen pro Stunde

    # Slippage-Annahme für konservative Berechnungen
    assumed_slippage_pct: float = 0.05  # 0.05% Slippage annehmen

    # Mindest-Gewinnmarge nach Kosten
    min_profit_margin_pct: float = 0.1  # Min. 0.1% Gewinn nach Kommission

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'max_levels_per_decision': self.max_levels_per_decision,
            'min_level_distance_pct': self.min_level_distance_pct,
            'long_short_ratio_min': self.long_short_ratio_min,
            'long_short_ratio_max': self.long_short_ratio_max,
            'min_level_hold_time_sec': self.min_level_hold_time_sec,
            'min_combination_hold_time_sec': self.min_combination_hold_time_sec,
            'max_changes_per_hour': self.max_changes_per_hour,
            'assumed_slippage_pct': self.assumed_slippage_pct,
            'min_profit_margin_pct': self.min_profit_margin_pct,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DecisionConfig':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            max_levels_per_decision=data.get('max_levels_per_decision', 10),
            min_level_distance_pct=data.get('min_level_distance_pct', 0.1),
            long_short_ratio_min=data.get('long_short_ratio_min', 0.3),
            long_short_ratio_max=data.get('long_short_ratio_max', 0.7),
            min_level_hold_time_sec=data.get('min_level_hold_time_sec', 60),
            min_combination_hold_time_sec=data.get('min_combination_hold_time_sec', 300),
            max_changes_per_hour=data.get('max_changes_per_hour', 10),
            assumed_slippage_pct=data.get('assumed_slippage_pct', 0.05),
            min_profit_margin_pct=data.get('min_profit_margin_pct', 0.1),
        )


@dataclass
class AlertConfig:
    """Alert-Konfiguration (für Alert-Modus)"""

    # Welche Entscheidungen erfordern Bestätigung im Alert-Modus?
    confirm_activate_level: bool = False    # Level aktivieren
    confirm_deactivate_level: bool = False  # Level deaktivieren
    confirm_stop_trade: bool = True         # Trade stoppen (wichtig!)
    confirm_close_position: bool = True     # Position schließen (wichtig!)
    confirm_emergency_stop: bool = False    # Emergency = immer sofort handeln

    # Timeout für Bestätigung (Sekunden)
    confirmation_timeout: int = 60  # Nach 60s = automatisch ablehnen

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'confirm_activate_level': self.confirm_activate_level,
            'confirm_deactivate_level': self.confirm_deactivate_level,
            'confirm_stop_trade': self.confirm_stop_trade,
            'confirm_close_position': self.confirm_close_position,
            'confirm_emergency_stop': self.confirm_emergency_stop,
            'confirmation_timeout': self.confirmation_timeout,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AlertConfig':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            confirm_activate_level=data.get('confirm_activate_level', False),
            confirm_deactivate_level=data.get('confirm_deactivate_level', False),
            confirm_stop_trade=data.get('confirm_stop_trade', True),
            confirm_close_position=data.get('confirm_close_position', True),
            confirm_emergency_stop=data.get('confirm_emergency_stop', False),
            confirmation_timeout=data.get('confirmation_timeout', 60),
        )


@dataclass
class KIControllerConfig:
    """
    Haupt-Konfigurationsklasse für den KI-Controller

    Enthält alle Sub-Konfigurationen und bietet Methoden
    zum Laden/Speichern der Konfiguration.
    """

    # Betriebsmodus
    mode: ControllerMode = ControllerMode.OFF

    # Sub-Konfigurationen
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    trading_hours: TradingHoursConfig = field(default_factory=TradingHoursConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)

    # Watchdog
    watchdog_heartbeat_sec: int = 5  # Heartbeat alle 5 Sekunden
    watchdog_timeout_sec: int = 30   # Nach 30s ohne Response = Notfall

    # Logging
    log_all_decisions: bool = True   # Alle Entscheidungen loggen
    log_analysis_details: bool = False  # Detaillierte Analyse loggen (verbose)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert gesamte Config zu Dictionary"""
        return {
            'mode': self.mode.value,
            'risk_limits': self.risk_limits.to_dict(),
            'trading_hours': self.trading_hours.to_dict(),
            'analysis': self.analysis.to_dict(),
            'decision': self.decision.to_dict(),
            'alerts': self.alerts.to_dict(),
            'watchdog_heartbeat_sec': self.watchdog_heartbeat_sec,
            'watchdog_timeout_sec': self.watchdog_timeout_sec,
            'log_all_decisions': self.log_all_decisions,
            'log_analysis_details': self.log_analysis_details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KIControllerConfig':
        """Erstellt Instanz aus Dictionary"""
        return cls(
            mode=ControllerMode(data.get('mode', 'OFF')),
            risk_limits=RiskLimits.from_dict(data.get('risk_limits', {})),
            trading_hours=TradingHoursConfig.from_dict(data.get('trading_hours', {})),
            analysis=AnalysisConfig.from_dict(data.get('analysis', {})),
            decision=DecisionConfig.from_dict(data.get('decision', {})),
            alerts=AlertConfig.from_dict(data.get('alerts', {})),
            watchdog_heartbeat_sec=data.get('watchdog_heartbeat_sec', 5),
            watchdog_timeout_sec=data.get('watchdog_timeout_sec', 30),
            log_all_decisions=data.get('log_all_decisions', True),
            log_analysis_details=data.get('log_analysis_details', False),
        )

    def save(self, filepath: Optional[Path] = None) -> None:
        """Speichert Config in JSON-Datei"""
        if filepath is None:
            filepath = Path.home() / ".gridtrader" / "ki_controller_config.json"

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: Optional[Path] = None) -> 'KIControllerConfig':
        """Lädt Config aus JSON-Datei oder erstellt Default"""
        if filepath is None:
            filepath = Path.home() / ".gridtrader" / "ki_controller_config.json"

        if filepath.exists():
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return cls.from_dict(data)

        # Default Config zurückgeben
        return cls()

    def validate(self) -> tuple[bool, list[str]]:
        """
        Validiert die Konfiguration

        Returns:
            Tuple[bool, List[str]]: (ist_valide, liste_der_fehler)
        """
        errors = []

        # Risk Limits validieren
        if self.risk_limits.max_daily_loss <= 0:
            errors.append("max_daily_loss muss positiv sein")

        if self.risk_limits.max_open_positions <= 0:
            errors.append("max_open_positions muss positiv sein")

        if not 0 < self.risk_limits.soft_limit_threshold <= 1:
            errors.append("soft_limit_threshold muss zwischen 0 und 1 liegen")

        # Decision Config validieren
        if not 0 <= self.decision.long_short_ratio_min <= self.decision.long_short_ratio_max <= 1:
            errors.append("long_short_ratio Werte müssen zwischen 0 und 1 liegen und min <= max")

        if self.decision.max_changes_per_hour <= 0:
            errors.append("max_changes_per_hour muss positiv sein")

        # Trading Hours validieren
        if self.trading_hours.market_open >= self.trading_hours.market_close:
            errors.append("market_open muss vor market_close liegen")

        return len(errors) == 0, errors
