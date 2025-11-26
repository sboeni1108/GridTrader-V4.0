"""
KI-Controller Thread

Der Haupt-Worker-Thread des KI-Controllers.
Läuft autonom und kommuniziert über Signals mit dem Haupt-Thread.
"""

import time
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable, Tuple
from decimal import Decimal
from threading import Event

from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from .config import KIControllerConfig, ControllerMode, VolatilityRegime
from .state import (
    KIControllerState, ControllerStatus, MarketState,
    ActiveLevelInfo, DecisionRecord, PendingAlert, PerformanceStats
)

# Analyse-Module
from .analysis import (
    VolatilityMonitor, VolatilitySnapshot, Candle,
    VolumeAnalyzer, VolumeSnapshot, VolumeCondition,
    TimeProfile, TimeProfileSnapshot, TradingPhase,
    PatternMatcher, PatternMatchResult, SituationFingerprint, MovementPattern,
)

# Entscheidungs-Module
from .decision import (
    LevelScorer, LevelScore, MarketContext, ScorerConfig,
    LevelOptimizer, LevelCandidate, OptimizationResult, OptimizationConstraints,
    OptimizationStrategy, create_candidate_from_score,
    PricePredictor, PredictionContext, PredictionTimeframe, DirectionBias,
)

# Risk Management Module
from .risk import (
    RiskManager, RiskSnapshot, RiskLevel, RiskAction,
    Watchdog, WatchdogStatus, HealthCheckResult,
)

# Execution Module
from .execution import (
    ExecutionManager, CommandType, CommandStatus, ExecutionPriority,
)

# Timezone support
try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except ImportError:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")

# Historical Data Manager für zentrale Datenverwaltung
try:
    from gridtrader.infrastructure.data import get_data_manager, HistoricalDataManager
    DATA_MANAGER_AVAILABLE = True
except ImportError:
    DATA_MANAGER_AVAILABLE = False
    print("WARNUNG: HistoricalDataManager nicht verfügbar für KI-Controller")


class KIControllerSignals:
    """Container für alle Signals des Controllers"""
    pass


class KIControllerThread(QThread):
    """
    Worker-Thread für den KI-Trading-Controller

    Führt kontinuierlich folgende Aufgaben aus:
    1. Marktdaten analysieren (ATR, Volatilität, Volumen)
    2. Muster erkennen und mit Historie vergleichen
    3. Optimale Level-Kombination berechnen
    4. Entscheidungen treffen und ausführen (oder Alert senden)
    5. Risiko-Limits überwachen
    """

    # ==================== SIGNALS ====================

    # Status Updates
    status_changed = Signal(str, str)  # (status, message)
    heartbeat = Signal()               # Periodischer Heartbeat

    # Entscheidungen
    decision_made = Signal(dict)       # Neue Entscheidung getroffen
    alert_created = Signal(dict)       # Alert für User (im Alert-Modus)

    # Aktionen (für Trading-Bot)
    request_activate_level = Signal(dict)    # Level aktivieren
    request_deactivate_level = Signal(str)   # Level deaktivieren (level_id)
    request_stop_trade = Signal(str)         # Trade stoppen (level_id)
    request_close_position = Signal(str, int)  # Position schließen (symbol, qty)
    request_emergency_stop = Signal()        # Alles sofort stoppen!

    # Analyse-Updates (für UI)
    market_analysis_update = Signal(dict)    # Aktuelle Markt-Analyse
    volatility_regime_changed = Signal(str, str)  # (symbol, regime)
    pattern_detected = Signal(dict)          # Muster erkannt

    # Risiko-Warnungen
    soft_limit_warning = Signal(str, float)  # (limit_name, current_value)
    hard_limit_reached = Signal(str)         # (limit_name)

    # Logging
    log_message = Signal(str, str)  # (message, level: INFO/WARNING/ERROR/SUCCESS)

    def __init__(self, config: Optional[KIControllerConfig] = None):
        super().__init__()

        # Konfiguration
        self.config = config or KIControllerConfig.load()

        # State
        self.state = KIControllerState()
        self.state.session_id = str(uuid.uuid4())[:8]
        self.state.session_start = datetime.now()

        # Thread-Kontrolle
        self._stop_event = Event()
        self._pause_event = Event()
        self._mutex = QMutex()

        # Level-Pool Referenz (wird von außen gesetzt)
        self._level_pool: Dict[str, dict] = {}

        # Callbacks für Trading-Bot API
        self._trading_bot_api: Optional['ControllerAPI'] = None

        # Analyse-Cache (Legacy - wird durch neue Module ersetzt)
        self._candle_cache: Dict[str, List[dict]] = {}  # Symbol -> Liste von Kerzen
        self._price_history: Dict[str, List[tuple]] = {}  # Symbol -> [(timestamp, price), ...]

        # Decision-Tracking
        self._last_decision_time: Dict[str, datetime] = {}
        self._pending_confirmations: Dict[str, PendingAlert] = {}

        # ==================== ANALYSE-MODULE ====================
        # Volatilitäts-Monitor für ATR und Regime Detection
        self._volatility_monitor = VolatilityMonitor(
            atr_period_short=self.config.analysis.atr_period_short,
            atr_period_medium=self.config.analysis.atr_period_medium,
            atr_period_long=self.config.analysis.atr_period_long,
        )

        # Volumen-Analyzer für Spike und Anomalie Detection
        self._volume_analyzer = VolumeAnalyzer(
            ma_period_short=self.config.analysis.volume_ma_period,
            spike_threshold=self.config.analysis.volume_spike_threshold,
        )

        # Zeit-Profil für Tageszeit-basierte Anpassungen
        self._time_profile = TimeProfile()

        # Pattern Matcher für historische Muster-Erkennung
        self._pattern_matcher = PatternMatcher(
            similarity_threshold=self.config.analysis.pattern_similarity_threshold,
            lookback_days=self.config.analysis.pattern_lookback_days,
        )

        # ==================== ENTSCHEIDUNGS-MODULE ====================
        # Level Scorer für Multi-Faktor Bewertung
        scorer_config = ScorerConfig(
            min_score_for_recommendation=30.0,
            max_distance_pct=self.config.decision.min_level_distance_pct * 30,  # 3% bei 0.1% default
            min_profit_pct=self.config.decision.min_profit_margin_pct,
            commission_per_trade=1.0,  # $1 pro Trade (IBKR)
        )
        self._level_scorer = LevelScorer(config=scorer_config)

        # Optimizer für Level-Kombination
        optimizer_constraints = OptimizationConstraints(
            max_levels_total=self.config.risk_limits.max_active_levels,
            max_levels_per_symbol=self.config.decision.max_levels_per_decision,
            long_short_ratio_min=self.config.decision.long_short_ratio_min,
            long_short_ratio_max=self.config.decision.long_short_ratio_max,
            min_distance_between_levels_pct=self.config.decision.min_level_distance_pct,
            min_score_threshold=30.0,
        )
        self._level_optimizer = LevelOptimizer(
            constraints=optimizer_constraints,
            strategy=OptimizationStrategy.BALANCED,
        )

        # Predictor für Preis-Vorhersagen
        self._price_predictor = PricePredictor()

        # ==================== RISK & EXECUTION MODULE ====================
        # Risk Manager für Limit-Überwachung
        self._risk_manager = RiskManager(
            max_daily_loss=self.config.risk_limits.max_daily_loss,
            max_total_exposure=self.config.risk_limits.max_exposure_per_symbol * 5,
            max_symbol_exposure=self.config.risk_limits.max_exposure_per_symbol,
            max_positions=self.config.risk_limits.max_open_positions,
            max_active_levels=self.config.risk_limits.max_active_levels,
            soft_limit_ratio=self.config.risk_limits.soft_limit_threshold,
            black_swan_threshold=self.config.risk_limits.sudden_drop_threshold,
        )

        # Callbacks für Risk Manager
        self._risk_manager.set_on_warning(self._on_risk_warning)
        self._risk_manager.set_on_limit_breach(self._on_risk_breach)
        self._risk_manager.set_on_emergency(self._on_risk_emergency)

        # Watchdog für Fail-Safe
        self._watchdog = Watchdog(
            heartbeat_interval_sec=self.config.watchdog_heartbeat_sec,
            heartbeat_timeout_sec=self.config.watchdog_timeout_sec,
            health_check_interval_sec=60,
            max_recovery_attempts=3,
        )
        self._watchdog.set_on_emergency(self._on_watchdog_emergency)

        # Execution Manager für Befehlsausführung
        self._execution_manager = ExecutionManager(
            max_queue_size=100,
            default_timeout_sec=30,
            default_max_retries=3,
        )

        # Execution Handlers registrieren
        self._setup_execution_handlers()

    def _setup_execution_handlers(self):
        """Registriert Handler für Execution Manager"""
        self._execution_manager.register_handler(
            CommandType.ACTIVATE_LEVEL,
            self._handle_activate_level
        )
        self._execution_manager.register_handler(
            CommandType.DEACTIVATE_LEVEL,
            self._handle_deactivate_level
        )
        self._execution_manager.register_handler(
            CommandType.STOP_TRADE,
            self._handle_stop_trade
        )
        self._execution_manager.register_handler(
            CommandType.CLOSE_POSITION,
            self._handle_close_position
        )
        self._execution_manager.register_handler(
            CommandType.EMERGENCY_STOP,
            self._handle_emergency_stop
        )

    # ==================== THREAD LIFECYCLE ====================

    def run(self):
        """Haupt-Loop des Worker-Threads"""
        self._log("KI-Controller gestartet", "INFO")
        self._update_status(ControllerStatus.STARTING, "Initialisierung...")

        try:
            # Initialisierung
            self._initialize()
            self._update_status(ControllerStatus.RUNNING, "Bereit")

            # Haupt-Loop
            while not self._stop_event.is_set():
                loop_start = time.time()

                # Pause-Check
                if self._pause_event.is_set():
                    self._update_status(ControllerStatus.PAUSED, "Pausiert")
                    time.sleep(0.5)
                    continue

                # Heartbeat
                self.state.update_heartbeat()
                self.heartbeat.emit()

                # Handelszeiten prüfen
                self._check_trading_hours()

                if self.state.is_market_hours and self.config.mode != ControllerMode.OFF:
                    # Hauptarbeit nur während Handelszeiten und wenn aktiv
                    self._main_cycle()

                # Loop-Timing (Config-basiertes Intervall)
                elapsed = time.time() - loop_start
                sleep_time = max(0.1, self.config.analysis.reevaluation_interval - elapsed)
                time.sleep(sleep_time)

        except Exception as e:
            self._log(f"Kritischer Fehler im Controller: {e}", "ERROR")
            self._update_status(ControllerStatus.ERROR, str(e))

        finally:
            self._cleanup()
            self._log("KI-Controller beendet", "INFO")

    def stop(self):
        """Stoppt den Controller-Thread"""
        self._log("Stop-Signal empfangen", "INFO")
        self._stop_event.set()

    def pause(self):
        """Pausiert den Controller"""
        self._pause_event.set()
        self._log("Controller pausiert", "INFO")

    def resume(self):
        """Setzt den Controller fort"""
        self._pause_event.clear()
        self._log("Controller fortgesetzt", "INFO")

    # ==================== INITIALIZATION ====================

    def _initialize(self):
        """Initialisiert den Controller"""
        # Config validieren
        is_valid, errors = self.config.validate()
        if not is_valid:
            for error in errors:
                self._log(f"Config-Fehler: {error}", "WARNING")

        # State laden (falls vorhanden)
        # self.state = KIControllerState.load()  # Optional: State wiederherstellen

        # Performance-Stats für neuen Tag zurücksetzen
        self.state.reset_daily_stats()

        self._log(f"Modus: {self.config.mode.value}", "INFO")

        # Historische Daten für Pattern-Matching laden
        self._load_historical_data_for_analysis()

    def _load_historical_data_for_analysis(self):
        """
        Lädt historische Daten vom DataManager für Pattern-Matching.

        Verwendet:
        1. Primär: Bereits geladene Backtesting-Daten
        2. Sekundär: Erweiterte Historie vom IBKR Service (falls konfiguriert)
        """
        if not DATA_MANAGER_AVAILABLE:
            self._log("DataManager nicht verfügbar - Pattern-Matching eingeschränkt", "WARNING")
            return

        try:
            manager = get_data_manager()

            # Symbole aus Level-Pool ermitteln
            symbols = set()
            for level_data in self._level_pool.values():
                if 'symbol' in level_data:
                    symbols.add(level_data['symbol'])

            if not symbols:
                self._log("Keine Symbole im Level-Pool - überspringe Datenladung", "INFO")
                return

            self._log(f"Lade historische Daten für {len(symbols)} Symbol(e)...", "INFO")

            for symbol in symbols:
                self._initialize_symbol_data(manager, symbol)

        except Exception as e:
            self._log(f"Fehler beim Laden historischer Daten: {e}", "ERROR")

    def _initialize_symbol_data(self, manager: 'HistoricalDataManager', symbol: str):
        """
        Initialisiert Daten für ein einzelnes Symbol.

        Args:
            manager: Der HistoricalDataManager
            symbol: Aktien-Symbol
        """
        # Prüfen ob bereits Backtesting-Daten vorhanden
        if manager.has_data(symbol):
            cache_info = manager.get_cache_info(symbol)
            row_count = cache_info.get('row_count', 0) if cache_info else 0
            source = cache_info.get('source', 'UNKNOWN') if cache_info else 'UNKNOWN'
            self._log(f"✓ {symbol}: {row_count} Datenpunkte aus {source} vorhanden", "INFO")

            # Daten in Analyse-Module laden
            data = manager.get_data(symbol)
            if data is not None and not data.empty:
                self._feed_historical_data_to_analyzers(symbol, data)
        else:
            self._log(f"⚠ {symbol}: Keine Backtesting-Daten - lade von IBKR...", "INFO")

            # Erweiterte Historie laden (default: 30 Tage für Pattern-Matching)
            extended_days = getattr(self.config, 'pattern_history_days', 30)
            data = manager.get_extended_history(symbol, days=extended_days)

            if data is not None and not data.empty:
                self._log(f"✓ {symbol}: {len(data)} Datenpunkte von IBKR geladen", "SUCCESS")
                self._feed_historical_data_to_analyzers(symbol, data)
            else:
                self._log(f"✗ {symbol}: Keine historischen Daten verfügbar", "WARNING")

    def _feed_historical_data_to_analyzers(self, symbol: str, data):
        """
        Füttert die Analyse-Module mit historischen Daten.

        Args:
            symbol: Aktien-Symbol
            data: DataFrame mit OHLCV-Daten
        """
        import pandas as pd

        if data is None or data.empty:
            return

        candle_count = 0

        try:
            # Durch alle Kerzen iterieren und den Analyzern zuführen
            for timestamp, row in data.iterrows():
                candle = Candle(
                    timestamp=timestamp.to_pydatetime() if hasattr(timestamp, 'to_pydatetime') else timestamp,
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=int(row.get('volume', 0)),
                )

                # Zur Volatilitäts-Analyse hinzufügen
                self._volatility_monitor.add_candle(symbol, candle)

                # Volumen-Analyse aktualisieren
                price_change = candle.body_pct
                self._volume_analyzer.add_volume(
                    symbol=symbol,
                    volume=candle.volume,
                    price_change_pct=price_change,
                    timestamp=candle.timestamp,
                )

                candle_count += 1

            self._log(f"Pattern-Matching für {symbol}: {candle_count} Kerzen geladen", "INFO")

        except Exception as e:
            self._log(f"Fehler beim Laden der Kerzen für {symbol}: {e}", "ERROR")

    def load_extended_history(self, symbol: str, days: int = 365) -> bool:
        """
        Lädt erweiterte Historie für tieferes Pattern-Matching.

        Diese Methode kann manuell aufgerufen werden, um mehr
        historische Daten für bessere Muster-Erkennung zu laden.

        Args:
            symbol: Aktien-Symbol
            days: Anzahl Tage (max 365)

        Returns:
            True wenn erfolgreich geladen
        """
        if not DATA_MANAGER_AVAILABLE:
            self._log("DataManager nicht verfügbar", "ERROR")
            return False

        try:
            manager = get_data_manager()
            self._log(f"Lade erweiterte Historie für {symbol} ({days} Tage)...", "INFO")

            data = manager.get_extended_history(symbol, days=days, force_reload=True)

            if data is not None and not data.empty:
                self._feed_historical_data_to_analyzers(symbol, data)
                self._log(f"✓ {symbol}: {len(data)} Datenpunkte für {days} Tage geladen", "SUCCESS")
                return True
            else:
                self._log(f"✗ {symbol}: Konnte keine erweiterte Historie laden", "WARNING")
                return False

        except Exception as e:
            self._log(f"Fehler beim Laden erweiterter Historie: {e}", "ERROR")
            return False

    def _cleanup(self):
        """Aufräumen beim Beenden"""
        # State speichern
        try:
            self.state.save()
            self._log("State gespeichert", "INFO")
        except Exception as e:
            self._log(f"Fehler beim State-Speichern: {e}", "ERROR")

    # ==================== MAIN CYCLE ====================

    def _main_cycle(self):
        """
        Haupt-Arbeitszyklus

        1. Marktdaten aktualisieren
        2. Analyse durchführen
        3. Entscheidungen treffen
        4. Risiko prüfen
        5. Aktionen ausführen
        """
        try:
            # 1. Marktdaten aktualisieren
            self._update_market_data()

            # 2. Analyse
            for symbol in self.state.market_states.keys():
                self._analyze_symbol(symbol)

            # 3. Entscheidungen (für jedes Symbol)
            for symbol in self.state.market_states.keys():
                self._make_decisions(symbol)

            # 4. Risiko-Check
            self._check_risk_limits()

            # 5. Pending Alerts prüfen (Timeout)
            self._check_pending_alerts()

            # 6. State periodisch speichern
            if datetime.now().second % 30 == 0:  # Alle 30 Sekunden
                self.state.save()

        except Exception as e:
            self._log(f"Fehler im Main Cycle: {e}", "ERROR")

    # ==================== MARKET DATA ====================

    def _update_market_data(self):
        """
        Aktualisiert Marktdaten für alle überwachten Symbole

        Hinweis: Die tatsächlichen Daten kommen vom Trading-Bot via API.
        Diese Methode holt sie ab und verarbeitet sie.
        """
        if self._trading_bot_api is None:
            return

        # Symbole aus aktiven Levels ermitteln
        symbols = set()
        for level in self.state.active_levels.values():
            symbols.add(level.symbol)

        # Auch Symbole aus Level-Pool
        for level_data in self._level_pool.values():
            if 'symbol' in level_data:
                symbols.add(level_data['symbol'])

        # Marktdaten abrufen
        for symbol in symbols:
            try:
                data = self._trading_bot_api.get_market_data(symbol)
                if data:
                    self._process_market_data(symbol, data)
            except Exception as e:
                self._log(f"Fehler bei Marktdaten für {symbol}: {e}", "ERROR")

    def _process_market_data(self, symbol: str, data: dict):
        """Verarbeitet empfangene Marktdaten"""
        with QMutexLocker(self._mutex):
            if symbol not in self.state.market_states:
                self.state.market_states[symbol] = MarketState(symbol=symbol)

            ms = self.state.market_states[symbol]

            # Basis-Daten aktualisieren
            if 'price' in data:
                ms.current_price = Decimal(str(data['price']))
            if 'bid' in data:
                ms.bid = Decimal(str(data['bid']))
            if 'ask' in data:
                ms.ask = Decimal(str(data['ask']))
            if 'volume' in data:
                ms.volume_today = data['volume']

            # Spread berechnen
            if ms.bid > 0 and ms.ask > 0:
                ms.spread_pct = float((ms.ask - ms.bid) / ms.bid * 100)

            ms.last_update = datetime.now()

            # Preis-Historie aktualisieren
            if symbol not in self._price_history:
                self._price_history[symbol] = []
            self._price_history[symbol].append((datetime.now(), float(ms.current_price)))

            # Nur letzte 1000 Preise behalten
            if len(self._price_history[symbol]) > 1000:
                self._price_history[symbol] = self._price_history[symbol][-1000:]

    def receive_market_data(self, symbol: str, data: dict):
        """
        Empfängt Marktdaten vom Trading-Bot (wird von außen aufgerufen)

        Diese Methode ist Thread-safe und kann vom Haupt-Thread aufgerufen werden.
        """
        self._process_market_data(symbol, data)

    # ==================== ANALYSIS ====================

    def _analyze_symbol(self, symbol: str):
        """
        Führt vollständige Analyse für ein Symbol durch.

        Verwendet die neuen Analyse-Module:
        - VolatilityMonitor für ATR und Regime
        - VolumeAnalyzer für Volumen-Anomalien
        - TimeProfile für Tageszeit-Anpassung
        - PatternMatcher für historische Muster
        """
        if symbol not in self.state.market_states:
            return

        ms = self.state.market_states[symbol]
        now = datetime.now()

        # 1. Volatilitäts-Analyse
        vol_snapshot = self._volatility_monitor.get_snapshot(symbol)
        if vol_snapshot:
            # MarketState mit Volatilitätsdaten aktualisieren
            ms.atr_5 = vol_snapshot.atr_5
            ms.atr_14 = vol_snapshot.atr_14
            ms.atr_50 = vol_snapshot.atr_50
            ms.price_change_1min = vol_snapshot.price_change_1min
            ms.price_change_5min = vol_snapshot.price_change_5min
            ms.price_change_15min = vol_snapshot.price_change_15min
            ms.candle_range_pct = vol_snapshot.avg_candle_range_pct

            # Regime-Änderung prüfen
            old_regime = ms.volatility_regime
            ms.volatility_regime = vol_snapshot.regime

            if old_regime != ms.volatility_regime:
                self.volatility_regime_changed.emit(symbol, ms.volatility_regime.value)
                self._log(f"{symbol}: Volatilitäts-Regime → {ms.volatility_regime.value}", "INFO")

        # 2. Volumen-Analyse
        vol_analysis = self._volume_analyzer.get_snapshot(symbol)
        if vol_analysis:
            ms.volume_1min = vol_analysis.current_volume

            # Volumen-Spike Warnung
            if vol_analysis.is_spike:
                self._log(
                    f"{symbol}: Volumen-Spike ({vol_analysis.spike_magnitude:.1f}x normal)",
                    "WARNING"
                )

            # Prüfe ob Trading pausiert werden sollte
            should_pause, reason = self._volume_analyzer.should_pause_trading(symbol)
            if should_pause:
                self._log(f"{symbol}: {reason}", "WARNING")

        # 3. Tageszeit-Profil
        time_snapshot = self._time_profile.get_current_snapshot()

        # 4. Pattern Matching (wenn genug Daten vorhanden)
        pattern_result = self._try_pattern_match(symbol, ms, vol_snapshot, vol_analysis, time_snapshot)

        # 5. Analyse-Update an UI senden
        self.market_analysis_update.emit({
            'symbol': symbol,
            'price': float(ms.current_price),
            'volatility_regime': ms.volatility_regime.value,
            'atr_5': ms.atr_5,
            'atr_14': ms.atr_14 if hasattr(ms, 'atr_14') else 0,
            'price_change_5min': ms.price_change_5min,
            'trading_phase': time_snapshot.phase.value,
            'volume_ratio': vol_analysis.volume_ratio if vol_analysis else 1.0,
            'pattern': pattern_result.dominant_pattern.value if pattern_result else 'UNKNOWN',
            'pattern_confidence': pattern_result.confidence if pattern_result else 0,
        })

        # 6. Situation für Pattern-Learning aufzeichnen
        self._record_situation_for_learning(symbol, ms, vol_snapshot, vol_analysis, time_snapshot)

    def _try_pattern_match(
        self,
        symbol: str,
        ms: MarketState,
        vol_snapshot: Optional[VolatilitySnapshot],
        vol_analysis: Optional[VolumeSnapshot],
        time_snapshot: TimeProfileSnapshot
    ) -> Optional[PatternMatchResult]:
        """Versucht Pattern-Matching und gibt Ergebnis zurück."""
        if not vol_snapshot or float(ms.current_price) <= 0:
            return None

        try:
            # Situations-Fingerprint erstellen
            fingerprint = self._create_fingerprint(symbol, ms, vol_snapshot, vol_analysis, time_snapshot)

            # Ähnliche Situationen finden
            result = self._pattern_matcher.find_similar_situations(fingerprint)

            if result.match_count > 0 and result.confidence > 0.5:
                # Guter Match gefunden
                self.pattern_detected.emit({
                    'symbol': symbol,
                    'pattern': result.dominant_pattern.value,
                    'confidence': result.confidence,
                    'expected_5min': result.expected_5min_change,
                    'expected_15min': result.expected_15min_change,
                    'match_count': result.match_count,
                })

                if self.config.log_analysis_details:
                    self._log(
                        f"{symbol}: Pattern {result.dominant_pattern.value} "
                        f"(Confidence: {result.confidence:.0%}, {result.match_count} Matches)",
                        "INFO"
                    )

            return result

        except Exception as e:
            if self.config.log_analysis_details:
                self._log(f"Pattern Match Fehler für {symbol}: {e}", "WARNING")
            return None

    def _create_fingerprint(
        self,
        symbol: str,
        ms: MarketState,
        vol_snapshot: Optional[VolatilitySnapshot],
        vol_analysis: Optional[VolumeSnapshot],
        time_snapshot: TimeProfileSnapshot
    ) -> SituationFingerprint:
        """Erstellt einen Situations-Fingerprint für Pattern-Matching."""
        return SituationFingerprint(
            timestamp=datetime.now(),
            symbol=symbol,
            price_position_in_range=50.0,  # TODO: Berechnen aus Tages-High/Low
            atr_pct=vol_snapshot.atr_14 if vol_snapshot else 0,
            volatility_regime=ms.volatility_regime.value,
            volume_ratio=vol_analysis.volume_ratio if vol_analysis else 1.0,
            volume_condition=vol_analysis.condition.value if vol_analysis else "NORMAL",
            short_term_trend=vol_snapshot.price_change_5min if vol_snapshot else 0,
            medium_term_trend=vol_snapshot.price_change_15min if vol_snapshot else 0,
            trading_phase=time_snapshot.phase.value,
            minutes_since_open=time_snapshot.minutes_since_open,
            last_candle_body_pct=0,  # TODO: Aus Kerzen-Daten
            last_candle_range_pct=vol_snapshot.avg_candle_range_pct if vol_snapshot else 0,
        )

    def _record_situation_for_learning(
        self,
        symbol: str,
        ms: MarketState,
        vol_snapshot: Optional[VolatilitySnapshot],
        vol_analysis: Optional[VolumeSnapshot],
        time_snapshot: TimeProfileSnapshot
    ):
        """Zeichnet aktuelle Situation für späteres Lernen auf."""
        if not vol_snapshot:
            return

        # Nur alle 60 Sekunden aufzeichnen (nicht bei jedem Tick)
        last_record_key = f"_last_record_{symbol}"
        now = datetime.now()

        if hasattr(self, last_record_key):
            last_time = getattr(self, last_record_key)
            if (now - last_time).total_seconds() < 60:
                return

        setattr(self, last_record_key, now)

        # Fingerprint erstellen und speichern
        fingerprint = self._create_fingerprint(symbol, ms, vol_snapshot, vol_analysis, time_snapshot)
        self._pattern_matcher.record_situation(fingerprint)

        # Auch dem Time Profile melden (für Symbol-spezifisches Lernen)
        self._time_profile.record_observation(
            symbol=symbol,
            atr=vol_snapshot.atr_14,
            candle_range=vol_snapshot.avg_candle_range_pct,
        )

    def add_candle(self, symbol: str, candle_data: dict):
        """
        Fügt eine neue Kerze für die Analyse hinzu.

        Wird von außen aufgerufen (z.B. vom Trading-Bot bei neuen Kerzen).
        """
        try:
            candle = Candle(
                timestamp=candle_data.get('timestamp', datetime.now()),
                open=candle_data['open'],
                high=candle_data['high'],
                low=candle_data['low'],
                close=candle_data['close'],
                volume=candle_data.get('volume', 0),
            )

            # Zur Volatilitäts-Analyse hinzufügen
            self._volatility_monitor.add_candle(symbol, candle)

            # Volumen-Analyse aktualisieren
            price_change = candle.body_pct
            self._volume_analyzer.add_volume(
                symbol=symbol,
                volume=candle.volume,
                price_change_pct=price_change,
                timestamp=candle.timestamp,
            )

        except Exception as e:
            self._log(f"Fehler bei Kerzen-Verarbeitung für {symbol}: {e}", "ERROR")

    def _determine_volatility_regime(self, ms: MarketState) -> VolatilityRegime:
        """Bestimmt das Volatilitäts-Regime basierend auf Analyse"""
        # Kombiniere ATR und kurzfristige Preisänderungen
        volatility_score = abs(ms.atr_5) + abs(ms.price_change_5min) / 2

        if volatility_score > 2.0:
            return VolatilityRegime.HIGH
        elif volatility_score > 0.5:
            return VolatilityRegime.MEDIUM
        elif volatility_score > 0:
            return VolatilityRegime.LOW
        else:
            return VolatilityRegime.UNKNOWN

    # ==================== DECISION MAKING ====================

    def _make_decisions(self, symbol: str):
        """
        Trifft Entscheidungen für ein Symbol

        1. Aktuellen Zustand bewerten
        2. Optimale Level-Kombination berechnen
        3. Änderungen identifizieren
        4. Entscheidungen ausführen oder Alert senden
        """
        if self.config.mode == ControllerMode.OFF:
            return

        # Anti-Overtrading Check
        if not self._can_make_change():
            return

        # Mindest-Haltezeit prüfen
        last_decision = self._last_decision_time.get(symbol)
        if last_decision:
            elapsed = (datetime.now() - last_decision).total_seconds()
            if elapsed < self.config.decision.min_combination_hold_time_sec:
                return  # Zu früh für neue Entscheidung

        ms = self.state.market_states.get(symbol)
        if not ms or ms.current_price <= 0:
            return

        # Aktuelle aktive Levels für dieses Symbol
        current_levels = self.state.get_active_levels_for_symbol(symbol)

        # Verfügbare Levels aus Pool
        available_levels = self._get_available_levels_for_symbol(symbol)

        if not available_levels:
            return  # Keine Levels verfügbar

        # Optimale Kombination berechnen (vereinfacht - wird in Phase 3 ausgebaut)
        optimal_levels = self._calculate_optimal_levels(
            symbol, ms, available_levels, current_levels
        )

        # Änderungen identifizieren
        levels_to_activate = self._identify_levels_to_activate(current_levels, optimal_levels)
        levels_to_deactivate = self._identify_levels_to_deactivate(current_levels, optimal_levels)

        # Entscheidungen ausführen
        for level_data in levels_to_activate:
            self._execute_activate_level(level_data, ms)

        for level_info in levels_to_deactivate:
            self._execute_deactivate_level(level_info)

        # Entscheidungszeit merken
        if levels_to_activate or levels_to_deactivate:
            self._last_decision_time[symbol] = datetime.now()

    def _get_available_levels_for_symbol(self, symbol: str) -> List[dict]:
        """Gibt alle verfügbaren Levels aus dem Pool für ein Symbol zurück"""
        return [
            level for level in self._level_pool.values()
            if level.get('symbol') == symbol
        ]

    def _calculate_optimal_levels(
        self,
        symbol: str,
        market_state: MarketState,
        available_levels: List[dict],
        current_levels: List[ActiveLevelInfo]
    ) -> List[dict]:
        """
        Berechnet die optimale Level-Kombination.

        Verwendet die Decision-Module:
        - LevelScorer für Multi-Faktor Bewertung
        - LevelOptimizer für optimale Kombination
        - PricePredictor für Richtungs-Vorhersage
        """
        current_price = float(market_state.current_price)

        if current_price <= 0:
            return []

        # 1. Markt-Kontext erstellen
        market_context = self._create_market_context(symbol, market_state)

        # 2. Preis-Vorhersage abrufen
        prediction_context = self._create_prediction_context(symbol, market_state)
        prediction = self._price_predictor.predict(prediction_context)

        # Pattern-Info zum MarketContext hinzufügen
        if prediction.predictions:
            pred_5min = prediction.predictions.get(PredictionTimeframe.MINUTES_5)
            if pred_5min:
                market_context.pattern_prediction = pred_5min.direction.value
                market_context.pattern_confidence = pred_5min.confidence

        # 3. Alle Levels bewerten mit LevelScorer
        level_scores = self._level_scorer.score_levels(available_levels, market_context)

        # 4. LevelCandidates erstellen für Optimizer
        candidates = []
        for ls in level_scores:
            candidate = create_candidate_from_score(ls)
            candidates.append(candidate)

        # 5. Aktuelle aktive Levels in Candidates konvertieren
        current_candidates = []
        for active in current_levels:
            current_candidates.append(LevelCandidate(
                level_id=active.level_id,
                symbol=active.symbol,
                side=active.side,
                entry_price=float(active.entry_price),
                exit_price=float(active.exit_price),
                score=active.score,
                is_recommended=True,
                distance_pct=0,
                profit_pct=0,
            ))

        # 6. Optimizer ausführen
        optimization_result = self._level_optimizer.optimize(
            candidates=candidates,
            current_active=current_candidates,
            current_price=current_price,
        )

        # 7. Ergebnis in Level-Dicts konvertieren
        optimal = []
        for selected in optimization_result.selected_levels:
            # Original Level-Dict finden
            for level in available_levels:
                if level.get('level_id') == selected.level_id:
                    # Score hinzufügen für spätere Referenz
                    level['score'] = selected.score
                    optimal.append(level)
                    break

        # Log wenn interessant
        if self.config.log_analysis_details and optimization_result.selected_levels:
            self._log(
                f"{symbol}: Optimierung - {optimization_result.total_count} Levels, "
                f"Score: {optimization_result.total_score:.0f}, "
                f"L/S: {optimization_result.long_count}/{optimization_result.short_count}",
                "INFO"
            )

        return optimal

    def _create_market_context(self, symbol: str, ms: MarketState) -> MarketContext:
        """Erstellt MarketContext für den LevelScorer"""
        # Volumen-Daten
        vol_snapshot = self._volume_analyzer.get_snapshot(symbol)
        vol_ratio = vol_snapshot.volume_ratio if vol_snapshot else 1.0
        vol_condition = vol_snapshot.condition.value if vol_snapshot else "NORMAL"

        # Zeit-Profil
        time_snapshot = self._time_profile.get_current_snapshot()

        # Pattern-Info (falls verfügbar)
        pattern_result = self._pattern_matcher.get_latest_result(symbol) if hasattr(self._pattern_matcher, 'get_latest_result') else None

        return MarketContext(
            current_price=float(ms.current_price),
            atr_5=ms.atr_5,
            atr_14=getattr(ms, 'atr_14', ms.atr_5),
            atr_50=getattr(ms, 'atr_50', ms.atr_5),
            volatility_regime=ms.volatility_regime.value,
            volume_ratio=vol_ratio,
            volume_condition=vol_condition,
            trading_phase=time_snapshot.phase.value,
            caution_level=time_snapshot.caution_level,
            short_term_trend=ms.price_change_5min,
            medium_term_trend=ms.price_change_15min,
        )

    def _create_prediction_context(self, symbol: str, ms: MarketState) -> PredictionContext:
        """Erstellt PredictionContext für den Predictor"""
        vol_snapshot = self._volume_analyzer.get_snapshot(symbol)
        time_snapshot = self._time_profile.get_current_snapshot()

        # Pattern Matcher Ergebnisse holen (falls vorhanden)
        pattern_prediction = None
        pattern_confidence = 0.0
        expected_5min = 0.0
        expected_15min = 0.0

        return PredictionContext(
            symbol=symbol,
            current_price=float(ms.current_price),
            atr_5=ms.atr_5,
            atr_14=getattr(ms, 'atr_14', ms.atr_5),
            volatility_regime=ms.volatility_regime.value,
            volume_ratio=vol_snapshot.volume_ratio if vol_snapshot else 1.0,
            volume_condition=vol_snapshot.condition.value if vol_snapshot else "NORMAL",
            volume_trend=vol_snapshot.trend.value if vol_snapshot else "STABLE",
            price_change_1min=getattr(ms, 'price_change_1min', 0),
            price_change_5min=ms.price_change_5min,
            price_change_15min=ms.price_change_15min,
            trading_phase=time_snapshot.phase.value,
            minutes_since_open=time_snapshot.minutes_since_open,
            pattern_prediction=pattern_prediction,
            pattern_confidence=pattern_confidence,
            expected_5min_change=expected_5min,
            expected_15min_change=expected_15min,
        )

    def _score_level(self, level: dict, market_state: MarketState) -> float:
        """
        Bewertet ein einzelnes Level mit dem LevelScorer.

        Diese Methode ist jetzt ein Wrapper für den LevelScorer.
        """
        market_context = self._create_market_context(
            level.get('symbol', ''),
            market_state
        )

        level_score = self._level_scorer.score_level(level, market_context)
        return level_score.total_score

    def _identify_levels_to_activate(
        self,
        current: List[ActiveLevelInfo],
        optimal: List[dict]
    ) -> List[dict]:
        """Identifiziert Levels, die aktiviert werden sollen"""
        current_ids = {l.level_id for l in current}
        to_activate = []

        for level in optimal:
            level_id = level.get('level_id', '')
            if level_id and level_id not in current_ids:
                to_activate.append(level)

        return to_activate

    def _identify_levels_to_deactivate(
        self,
        current: List[ActiveLevelInfo],
        optimal: List[dict]
    ) -> List[ActiveLevelInfo]:
        """Identifiziert Levels, die deaktiviert werden sollen"""
        optimal_ids = {l.get('level_id', '') for l in optimal}
        to_deactivate = []

        for level_info in current:
            if level_info.level_id not in optimal_ids:
                # Mindest-Haltezeit prüfen
                if level_info.activated_at:
                    held_seconds = (datetime.now() - level_info.activated_at).total_seconds()
                    if held_seconds >= self.config.decision.min_level_hold_time_sec:
                        to_deactivate.append(level_info)

        return to_deactivate

    # ==================== EXECUTION ====================

    def _execute_activate_level(self, level_data: dict, market_state: MarketState):
        """Führt Level-Aktivierung aus oder erstellt Alert"""
        decision = DecisionRecord(
            timestamp=datetime.now(),
            decision_type="ACTIVATE_LEVEL",
            symbol=level_data.get('symbol', ''),
            details=level_data,
            reason=f"Score-basierte Auswahl bei {market_state.volatility_regime.value} Volatilität",
            market_state_snapshot=market_state.to_dict(),
        )

        if self.config.mode == ControllerMode.ALERT and self.config.alerts.confirm_activate_level:
            # Alert-Modus: User-Bestätigung anfordern
            self._create_alert(decision)
        else:
            # Autonom oder keine Bestätigung nötig: Direkt ausführen
            self._do_activate_level(level_data, decision)

    def _do_activate_level(self, level_data: dict, decision: DecisionRecord):
        """Führt die tatsächliche Level-Aktivierung durch"""
        level_id = level_data.get('level_id', str(uuid.uuid4())[:8])

        # ActiveLevelInfo erstellen
        level_info = ActiveLevelInfo(
            level_id=level_id,
            scenario_name=level_data.get('scenario_name', 'Unknown'),
            symbol=level_data.get('symbol', ''),
            side=level_data.get('side', 'LONG'),
            level_num=level_data.get('level_num', 0),
            entry_price=Decimal(str(level_data.get('entry_price', 0))),
            exit_price=Decimal(str(level_data.get('exit_price', 0))),
            shares=level_data.get('shares', 100),
            activated_at=datetime.now(),
            score=level_data.get('score', 0),
            reason=decision.reason,
        )

        # Zum State hinzufügen
        with QMutexLocker(self._mutex):
            self.state.active_levels[level_id] = level_info
            self.state.performance.activations_today += 1
            self.state.performance.record_change()

        # Entscheidung protokollieren
        decision.executed = True
        decision.execution_result = "Level aktiviert"
        self.state.add_decision(decision)

        # Signal an Trading-Bot senden
        self.request_activate_level.emit(level_data)
        self.decision_made.emit(decision.to_dict())

        self._log(f"Level aktiviert: {level_info.symbol} {level_info.side} L{level_info.level_num}", "SUCCESS")

    def _execute_deactivate_level(self, level_info: ActiveLevelInfo):
        """Führt Level-Deaktivierung aus oder erstellt Alert"""
        decision = DecisionRecord(
            timestamp=datetime.now(),
            decision_type="DEACTIVATE_LEVEL",
            symbol=level_info.symbol,
            details={'level_id': level_info.level_id, 'level_num': level_info.level_num},
            reason="Nicht mehr optimal basierend auf aktueller Analyse",
        )

        if self.config.mode == ControllerMode.ALERT and self.config.alerts.confirm_deactivate_level:
            self._create_alert(decision)
        else:
            self._do_deactivate_level(level_info, decision)

    def _do_deactivate_level(self, level_info: ActiveLevelInfo, decision: DecisionRecord):
        """Führt die tatsächliche Level-Deaktivierung durch"""
        level_id = level_info.level_id

        with QMutexLocker(self._mutex):
            if level_id in self.state.active_levels:
                self.state.active_levels[level_id].is_active = False
                del self.state.active_levels[level_id]
                self.state.performance.deactivations_today += 1
                self.state.performance.record_change()

        decision.executed = True
        decision.execution_result = "Level deaktiviert"
        self.state.add_decision(decision)

        self.request_deactivate_level.emit(level_id)
        self.decision_made.emit(decision.to_dict())

        self._log(f"Level deaktiviert: {level_info.symbol} {level_info.side} L{level_info.level_num}", "INFO")

    # ==================== ALERTS ====================

    def _create_alert(self, decision: DecisionRecord):
        """Erstellt einen Alert für User-Bestätigung"""
        alert_id = str(uuid.uuid4())[:8]
        now = datetime.now()
        expires = now + timedelta(seconds=self.config.alerts.confirmation_timeout)

        alert = PendingAlert(
            alert_id=alert_id,
            created_at=now,
            expires_at=expires,
            decision=decision,
        )

        with QMutexLocker(self._mutex):
            self.state.pending_alerts[alert_id] = alert
            self._pending_confirmations[alert_id] = alert

        self.state.status = ControllerStatus.ALERT_PENDING
        self.alert_created.emit(alert.to_dict())

        self._log(f"Alert erstellt: {decision.decision_type} - warte auf Bestätigung", "WARNING")

    def confirm_alert(self, alert_id: str, confirmed: bool):
        """
        Bestätigt oder lehnt einen Alert ab

        Wird von außen (UI) aufgerufen.
        """
        with QMutexLocker(self._mutex):
            if alert_id not in self._pending_confirmations:
                return

            alert = self._pending_confirmations[alert_id]
            alert.confirmed = confirmed
            alert.response_time = datetime.now()

            if confirmed:
                # Entscheidung ausführen
                decision = alert.decision
                if decision.decision_type == "ACTIVATE_LEVEL":
                    self._do_activate_level(decision.details, decision)
                elif decision.decision_type == "DEACTIVATE_LEVEL":
                    level_id = decision.details.get('level_id')
                    if level_id in self.state.active_levels:
                        self._do_deactivate_level(self.state.active_levels[level_id], decision)

            # Aufräumen
            del self._pending_confirmations[alert_id]
            if alert_id in self.state.pending_alerts:
                del self.state.pending_alerts[alert_id]

            if not self._pending_confirmations:
                self.state.status = ControllerStatus.RUNNING

    def _check_pending_alerts(self):
        """Prüft Timeout für pending Alerts"""
        now = datetime.now()
        expired = []

        with QMutexLocker(self._mutex):
            for alert_id, alert in self._pending_confirmations.items():
                if now > alert.expires_at:
                    expired.append(alert_id)

            for alert_id in expired:
                alert = self._pending_confirmations[alert_id]
                alert.confirmed = False  # Timeout = abgelehnt
                del self._pending_confirmations[alert_id]
                if alert_id in self.state.pending_alerts:
                    del self.state.pending_alerts[alert_id]

                self._log(f"Alert Timeout: {alert.decision.decision_type} abgelehnt", "WARNING")

            if not self._pending_confirmations and self.state.status == ControllerStatus.ALERT_PENDING:
                self.state.status = ControllerStatus.RUNNING

    # ==================== RISK MANAGEMENT ====================

    def _check_risk_limits(self):
        """Prüft alle Risiko-Limits"""
        limits = self.config.risk_limits
        perf = self.state.performance

        # Daily Loss Check
        total_loss = float(perf.realized_pnl_today + perf.unrealized_pnl)
        if total_loss < 0:
            loss = abs(total_loss)

            # Soft Limit
            soft_threshold = float(limits.max_daily_loss) * limits.soft_limit_threshold
            if loss >= soft_threshold and not self.state.soft_limit_warning:
                self.state.soft_limit_warning = True
                self.soft_limit_warning.emit("max_daily_loss", loss)
                self._log(f"Soft Limit Warnung: Tagesverlust ${loss:.2f}", "WARNING")

            # Hard Limit
            if loss >= float(limits.max_daily_loss):
                self.hard_limit_reached.emit("max_daily_loss")
                self._log(f"HARD LIMIT: Max Tagesverlust erreicht (${loss:.2f})", "ERROR")
                self._trigger_emergency_stop("Max Tagesverlust erreicht")

            # Emergency Threshold
            if loss >= float(limits.emergency_loss_threshold):
                self._trigger_emergency_stop("Emergency Loss Threshold erreicht")

        # Active Levels Check
        active_count = len(self.state.active_levels)
        if active_count >= limits.max_active_levels:
            self._log(f"Max aktive Levels erreicht ({active_count})", "WARNING")

    def _trigger_emergency_stop(self, reason: str):
        """Löst Emergency Stop aus"""
        if self.state.emergency_stop_triggered:
            return  # Bereits ausgelöst

        self.state.emergency_stop_triggered = True
        self._update_status(ControllerStatus.EMERGENCY, reason)

        self._log(f"EMERGENCY STOP: {reason}", "ERROR")

        # Signal senden
        self.request_emergency_stop.emit()

        # Alle aktiven Levels deaktivieren
        for level_id in list(self.state.active_levels.keys()):
            self.request_deactivate_level.emit(level_id)

    # ==================== TRADING HOURS ====================

    def _check_trading_hours(self):
        """Prüft ob innerhalb der Handelszeiten"""
        try:
            ny_now = datetime.now(NY_TZ)
            current_time = ny_now.time()

            is_market_hours = (
                self.config.trading_hours.market_open <= current_time <= self.config.trading_hours.market_close
            )

            # Wochenende?
            if ny_now.weekday() >= 5:  # Samstag oder Sonntag
                is_market_hours = False

            if is_market_hours != self.state.is_market_hours:
                self.state.is_market_hours = is_market_hours
                if is_market_hours:
                    self._log("Handelszeiten begonnen", "INFO")
                else:
                    self._log("Handelszeiten beendet", "INFO")

        except Exception as e:
            self._log(f"Fehler bei Handelszeitenprüfung: {e}", "ERROR")
            self.state.is_market_hours = True  # Im Zweifel handeln

    # ==================== UTILITY ====================

    def _can_make_change(self) -> bool:
        """Prüft ob eine Änderung erlaubt ist (Anti-Overtrading)"""
        perf = self.state.performance

        # Stunden-Limit prüfen
        if perf.changes_this_hour >= self.config.decision.max_changes_per_hour:
            return False

        return True

    def _update_status(self, status: ControllerStatus, message: str):
        """Aktualisiert den Controller-Status"""
        self.state.status = status
        self.state.status_message = message
        self.status_changed.emit(status.value, message)

    def _log(self, message: str, level: str = "INFO"):
        """Sendet Log-Nachricht"""
        if self.config.log_all_decisions or level in ("ERROR", "WARNING"):
            self.log_message.emit(message, level)

    # ==================== EXTERNAL API ====================

    def set_trading_bot_api(self, api: 'ControllerAPI'):
        """Setzt die API-Referenz zum Trading-Bot"""
        self._trading_bot_api = api

    def set_level_pool(self, pool: Dict[str, dict]):
        """Setzt den Level-Pool"""
        with QMutexLocker(self._mutex):
            self._level_pool = pool

    def update_level_pool(self, level_id: str, level_data: dict):
        """Aktualisiert ein einzelnes Level im Pool"""
        with QMutexLocker(self._mutex):
            self._level_pool[level_id] = level_data

    def remove_from_level_pool(self, level_id: str):
        """Entfernt ein Level aus dem Pool"""
        with QMutexLocker(self._mutex):
            if level_id in self._level_pool:
                del self._level_pool[level_id]

    def get_state_snapshot(self) -> dict:
        """Gibt einen Snapshot des aktuellen States zurück"""
        with QMutexLocker(self._mutex):
            return self.state.to_dict()

    def get_config(self) -> KIControllerConfig:
        """Gibt die aktuelle Konfiguration zurück"""
        return self.config

    def update_config(self, new_config: KIControllerConfig):
        """Aktualisiert die Konfiguration"""
        with QMutexLocker(self._mutex):
            self.config = new_config
            self.config.save()
        self._log("Konfiguration aktualisiert", "INFO")

    # ==================== RISK CALLBACKS ====================

    def _on_risk_warning(self, event):
        """Callback bei Risiko-Warnung"""
        self._log(f"Risiko-Warnung: {event.message}", "WARNING")
        self.soft_limit_warning.emit(event.limit_type.value if event.limit_type else "UNKNOWN", event.current_value)

    def _on_risk_breach(self, event):
        """Callback bei Limit-Verletzung"""
        self._log(f"Limit-Verletzung: {event.message}", "ERROR")
        self.hard_limit_reached.emit(event.limit_type.value if event.limit_type else "UNKNOWN")

    def _on_risk_emergency(self, reason: str):
        """Callback bei Risk Emergency"""
        self._trigger_emergency_stop(f"Risk Manager: {reason}")

    def _on_watchdog_emergency(self, reason: str):
        """Callback bei Watchdog Emergency"""
        self._trigger_emergency_stop(f"Watchdog: {reason}")

    # ==================== EXECUTION HANDLERS ====================

    def _handle_activate_level(self, payload: Dict) -> Tuple[bool, str]:
        """Handler für Level-Aktivierung"""
        try:
            level_id = payload.get('level_id', '')
            if not level_id:
                return False, "Keine Level-ID"

            # Signal an Trading-Bot senden
            self.request_activate_level.emit(payload)
            return True, f"Level {level_id} aktiviert"

        except Exception as e:
            return False, str(e)

    def _handle_deactivate_level(self, payload: Dict) -> Tuple[bool, str]:
        """Handler für Level-Deaktivierung"""
        try:
            level_id = payload.get('level_id', '')
            if not level_id:
                return False, "Keine Level-ID"

            self.request_deactivate_level.emit(level_id)
            return True, f"Level {level_id} deaktiviert"

        except Exception as e:
            return False, str(e)

    def _handle_stop_trade(self, payload: Dict) -> Tuple[bool, str]:
        """Handler für Trade-Stop"""
        try:
            level_id = payload.get('level_id', '')
            reason = payload.get('reason', 'Unbekannt')

            self.request_stop_trade.emit(level_id)
            return True, f"Trade {level_id} gestoppt: {reason}"

        except Exception as e:
            return False, str(e)

    def _handle_close_position(self, payload: Dict) -> Tuple[bool, str]:
        """Handler für Positions-Schließung"""
        try:
            symbol = payload.get('symbol', '')
            quantity = payload.get('quantity', 0)

            self.request_close_position.emit(symbol, quantity)
            return True, f"Position {symbol} ({quantity}) geschlossen"

        except Exception as e:
            return False, str(e)

    def _handle_emergency_stop(self, payload: Dict) -> Tuple[bool, str]:
        """Handler für Emergency Stop"""
        try:
            reason = payload.get('reason', 'Emergency Stop')

            self._trigger_emergency_stop(reason)
            return True, f"Emergency Stop ausgelöst: {reason}"

        except Exception as e:
            return False, str(e)

    # ==================== RISK & EXECUTION ACCESS ====================

    def get_risk_snapshot(self) -> Optional[RiskSnapshot]:
        """Gibt aktuellen Risk-Snapshot zurück"""
        return self._risk_manager.get_latest_snapshot()

    def get_risk_level(self) -> RiskLevel:
        """Gibt aktuelles Risiko-Level zurück"""
        return self._risk_manager.get_current_level()

    def get_watchdog_status(self) -> WatchdogStatus:
        """Gibt Watchdog-Status zurück"""
        return self._watchdog.get_status()

    def get_execution_stats(self):
        """Gibt Execution-Statistiken zurück"""
        return self._execution_manager.get_stats()

    def is_risk_emergency(self) -> bool:
        """Prüft ob Risk-Emergency aktiv"""
        return self._risk_manager.is_emergency()
