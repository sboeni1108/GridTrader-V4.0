"""
KI-Controller Widget

UI-Komponente für den KI-Trading-Controller.
Bietet:
- Ein/Aus Schalter und Modus-Auswahl
- Status-Anzeige
- Konfigurationspanel
- Live-Monitoring der Controller-Entscheidungen
- Alert-Bestätigung (im Alert-Modus)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QSpinBox,
    QDoubleSpinBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit,
    QTabWidget, QFormLayout, QSplitter, QFrame,
    QMessageBox, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QFont, QColor

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

# Import KI-Controller Module
try:
    from gridtrader.ki_controller import (
        KIControllerThread, KIControllerConfig, ControllerMode,
        KIControllerState, ControllerStatus, LevelPool,
        TradingBotAPIAdapter, RiskLimits,
        PaperTrader, PerformanceTracker
    )
    KI_CONTROLLER_AVAILABLE = True
except ImportError as e:
    print(f"KI-Controller Import Fehler: {e}")
    KI_CONTROLLER_AVAILABLE = False

# Import neue UI Widgets
try:
    from gridtrader.ui.widgets.decision_visualizer import DecisionVisualizerWidget
    from gridtrader.ui.widgets.statistics_widget import StatisticsWidget
    ADVANCED_WIDGETS_AVAILABLE = True
except ImportError as e:
    print(f"Advanced Widgets Import Fehler: {e}")
    ADVANCED_WIDGETS_AVAILABLE = False

# Styles
try:
    from gridtrader.ui.styles import (
        TITLE_STYLE, GROUPBOX_STYLE, TABLE_STYLE, LOG_STYLE,
        apply_table_style, apply_groupbox_style
    )
except ImportError:
    TITLE_STYLE = "font-weight: bold; font-size: 14px; color: #2196F3;"
    GROUPBOX_STYLE = ""
    TABLE_STYLE = ""
    LOG_STYLE = ""
    def apply_table_style(t): pass
    def apply_groupbox_style(g): pass


class KIControllerWidget(QWidget):
    """
    Haupt-Widget für den KI-Trading-Controller

    Struktur:
    - Oben: Status-Leiste mit Ein/Aus und Modus
    - Mitte: Tabs für verschiedene Ansichten
      - Dashboard: Übersicht und aktive Levels
      - Konfiguration: Alle Einstellungen
      - Log: Entscheidungs-Historie
    - Unten: Alert-Bereich (wenn Alerts pending)
    """

    # Signals für Kommunikation mit MainWindow
    controller_started = Signal()
    controller_stopped = Signal()
    alert_response = Signal(str, bool)  # alert_id, confirmed

    def __init__(self, trading_bot_widget=None, parent=None):
        super().__init__(parent)

        self._trading_bot = trading_bot_widget

        # Controller und Config
        self._controller: Optional[KIControllerThread] = None
        self._config: Optional[KIControllerConfig] = None
        self._level_pool: Optional[LevelPool] = None
        self._api_adapter: Optional[TradingBotAPIAdapter] = None

        # Paper Trading & Performance Tracking
        self._paper_trader: Optional[PaperTrader] = None
        self._performance_tracker: Optional[PerformanceTracker] = None

        # UI State
        self._pending_alerts: Dict[str, dict] = {}

        self._init_ui()
        self._load_config()
        self._init_testing_components()

        # Update Timer für Status
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._update_status_display)
        self._update_timer.start(1000)  # Jede Sekunde

    def _init_ui(self):
        """Initialisiert die UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        # ==================== HEADER ====================
        header = self._create_header()
        main_layout.addWidget(header)

        # ==================== MAIN CONTENT ====================
        splitter = QSplitter(Qt.Vertical)

        # Tabs für verschiedene Ansichten
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_dashboard_tab(), "Dashboard")
        self._tabs.addTab(self._create_config_tab(), "Konfiguration")
        self._tabs.addTab(self._create_log_tab(), "Log")

        # Erweiterte Tabs (wenn verfügbar)
        if ADVANCED_WIDGETS_AVAILABLE:
            self._decision_viz = DecisionVisualizerWidget()
            self._tabs.addTab(self._decision_viz, "Visualisierung")

            self._statistics_widget = StatisticsWidget()
            self._tabs.addTab(self._statistics_widget, "Statistiken")
        else:
            self._decision_viz = None
            self._statistics_widget = None

        splitter.addWidget(self._tabs)

        # Alert-Bereich (unten)
        self._alert_widget = self._create_alert_widget()
        self._alert_widget.setVisible(False)
        splitter.addWidget(self._alert_widget)

        splitter.setSizes([600, 150])
        main_layout.addWidget(splitter)

    def _create_header(self) -> QWidget:
        """Erstellt den Header mit Status und Kontrollen"""
        header = QFrame()
        header.setFrameStyle(QFrame.StyledPanel)
        layout = QHBoxLayout(header)

        # Titel
        title = QLabel("KI-Trading-Controller")
        title.setStyleSheet(TITLE_STYLE)
        layout.addWidget(title)

        layout.addStretch()

        # Status-Anzeige
        self._status_label = QLabel("Status: Gestoppt")
        self._status_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self._status_label)

        # Modus-Auswahl
        layout.addWidget(QLabel("Modus:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Aus", "Alert", "Autonom"])
        self._mode_combo.setCurrentIndex(0)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self._mode_combo.setMinimumWidth(100)
        layout.addWidget(self._mode_combo)

        # Paper Trading wird durch IBKR-Verbindung bestimmt (Paper Account vs Live Account)
        # Kein separates Checkbox mehr nötig

        # Start/Stop Button
        self._start_btn = QPushButton("Starten")
        self._start_btn.setMinimumWidth(100)
        self._start_btn.clicked.connect(self._on_start_stop_clicked)
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        layout.addWidget(self._start_btn)

        return header

    def _create_dashboard_tab(self) -> QWidget:
        """Erstellt das Dashboard Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # ==================== STATUS CARDS ====================
        cards_layout = QHBoxLayout()

        # Volatilitäts-Karte
        self._volatility_card = self._create_status_card(
            "Volatilität",
            "UNBEKANNT",
            "Aktuelles Regime"
        )
        cards_layout.addWidget(self._volatility_card)

        # Aktive Levels Karte
        self._active_levels_card = self._create_status_card(
            "Aktive Levels",
            "0",
            "Long: 0 / Short: 0"
        )
        cards_layout.addWidget(self._active_levels_card)

        # P&L Karte
        self._pnl_card = self._create_status_card(
            "Tages-P&L",
            "$0.00",
            "Realisiert: $0.00"
        )
        cards_layout.addWidget(self._pnl_card)

        # Entscheidungen Karte
        self._decisions_card = self._create_status_card(
            "Entscheidungen",
            "0",
            "Heute: 0 Aktivierungen"
        )
        cards_layout.addWidget(self._decisions_card)

        layout.addLayout(cards_layout)

        # ==================== AKTIVE LEVELS TABELLE ====================
        levels_group = QGroupBox("Aktive Levels (vom Controller verwaltet)")
        apply_groupbox_style(levels_group)
        levels_layout = QVBoxLayout(levels_group)

        self._active_table = QTableWidget()
        self._active_table.setColumnCount(8)
        self._active_table.setHorizontalHeaderLabels([
            "Symbol", "Seite", "Level", "Entry", "Exit", "Aktien", "Score", "Status"
        ])
        self._active_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._active_table.setAlternatingRowColors(True)
        apply_table_style(self._active_table)
        levels_layout.addWidget(self._active_table)

        layout.addWidget(levels_group)

        # ==================== MARKT-ANALYSE ====================
        analysis_group = QGroupBox("Markt-Analyse")
        apply_groupbox_style(analysis_group)
        analysis_layout = QHBoxLayout(analysis_group)

        # Linke Seite: Aktuelle Werte
        left_form = QFormLayout()
        self._current_price_label = QLabel("-")
        self._atr_label = QLabel("-")
        self._volume_label = QLabel("-")
        self._time_regime_label = QLabel("-")

        left_form.addRow("Aktueller Preis:", self._current_price_label)
        left_form.addRow("ATR (5):", self._atr_label)
        left_form.addRow("Volumen:", self._volume_label)
        left_form.addRow("Tageszeit-Regime:", self._time_regime_label)

        analysis_layout.addLayout(left_form)

        # Rechte Seite: Empfehlung
        right_box = QVBoxLayout()
        self._recommendation_label = QLabel("Keine aktive Analyse")
        self._recommendation_label.setWordWrap(True)
        self._recommendation_label.setStyleSheet("""
            padding: 10px;
            background-color: #f5f5f5;
            border-radius: 5px;
        """)
        right_box.addWidget(QLabel("Controller-Empfehlung:"))
        right_box.addWidget(self._recommendation_label)
        right_box.addStretch()

        analysis_layout.addLayout(right_box)
        layout.addWidget(analysis_group)

        return widget

    def _create_status_card(self, title: str, value: str, subtitle: str) -> QFrame:
        """Erstellt eine Status-Karte"""
        card = QFrame()
        card.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        card.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(title_label)

        value_label = QLabel(value)
        value_label.setObjectName("value")
        value_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        layout.addWidget(value_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("subtitle")
        subtitle_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(subtitle_label)

        return card

    def _create_config_tab(self) -> QWidget:
        """Erstellt das Konfigurations-Tab"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # ==================== RISK LIMITS ====================
        risk_group = QGroupBox("Risiko-Limits")
        apply_groupbox_style(risk_group)
        risk_layout = QFormLayout(risk_group)

        self._max_daily_loss_spin = QDoubleSpinBox()
        self._max_daily_loss_spin.setRange(0, 100000)
        self._max_daily_loss_spin.setValue(500)
        self._max_daily_loss_spin.setPrefix("$ ")
        risk_layout.addRow("Max. Tagesverlust:", self._max_daily_loss_spin)

        self._max_positions_spin = QSpinBox()
        self._max_positions_spin.setRange(1, 100000)
        self._max_positions_spin.setValue(2000)
        risk_layout.addRow("Max. offene Positionen:", self._max_positions_spin)

        self._max_exposure_spin = QDoubleSpinBox()
        self._max_exposure_spin.setRange(0, 1000000)
        self._max_exposure_spin.setValue(10000)
        self._max_exposure_spin.setPrefix("$ ")
        risk_layout.addRow("Max. Exposure/Symbol:", self._max_exposure_spin)

        self._max_levels_spin = QSpinBox()
        self._max_levels_spin.setRange(1, 100)
        self._max_levels_spin.setValue(20)
        risk_layout.addRow("Max. aktive Levels:", self._max_levels_spin)

        layout.addWidget(risk_group)

        # ==================== DECISION SETTINGS ====================
        decision_group = QGroupBox("Entscheidungs-Parameter")
        apply_groupbox_style(decision_group)
        decision_layout = QFormLayout(decision_group)

        self._reevaluation_spin = QSpinBox()
        self._reevaluation_spin.setRange(5, 300)
        self._reevaluation_spin.setValue(30)
        self._reevaluation_spin.setSuffix(" Sek")
        decision_layout.addRow("Re-Evaluation Intervall:", self._reevaluation_spin)

        self._min_hold_time_spin = QSpinBox()
        self._min_hold_time_spin.setRange(0, 3600)
        self._min_hold_time_spin.setValue(300)
        self._min_hold_time_spin.setSuffix(" Sek")
        decision_layout.addRow("Min. Haltezeit:", self._min_hold_time_spin)

        self._max_changes_spin = QSpinBox()
        self._max_changes_spin.setRange(1, 100)
        self._max_changes_spin.setValue(10)
        self._max_changes_spin.setSuffix(" /Std")
        decision_layout.addRow("Max. Änderungen:", self._max_changes_spin)

        self._slippage_spin = QDoubleSpinBox()
        self._slippage_spin.setRange(0, 1)
        self._slippage_spin.setValue(0.05)
        self._slippage_spin.setDecimals(3)
        self._slippage_spin.setSuffix(" %")
        decision_layout.addRow("Angenommene Slippage:", self._slippage_spin)

        layout.addWidget(decision_group)

        # ==================== ALERT SETTINGS ====================
        alert_group = QGroupBox("Alert-Einstellungen (für Alert-Modus)")
        apply_groupbox_style(alert_group)
        alert_layout = QFormLayout(alert_group)

        self._confirm_activate_check = QCheckBox()
        alert_layout.addRow("Bestätigung für Aktivierung:", self._confirm_activate_check)

        self._confirm_deactivate_check = QCheckBox()
        alert_layout.addRow("Bestätigung für Deaktivierung:", self._confirm_deactivate_check)

        self._confirm_stop_check = QCheckBox()
        self._confirm_stop_check.setChecked(True)
        alert_layout.addRow("Bestätigung für Trade-Stop:", self._confirm_stop_check)

        self._confirm_close_check = QCheckBox()
        self._confirm_close_check.setChecked(True)
        alert_layout.addRow("Bestätigung für Position-Close:", self._confirm_close_check)

        self._alert_timeout_spin = QSpinBox()
        self._alert_timeout_spin.setRange(10, 300)
        self._alert_timeout_spin.setValue(60)
        self._alert_timeout_spin.setSuffix(" Sek")
        alert_layout.addRow("Alert-Timeout:", self._alert_timeout_spin)

        layout.addWidget(alert_group)

        # ==================== BUTTONS ====================
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("Einstellungen speichern")
        save_btn.clicked.connect(self._save_config)
        btn_layout.addWidget(save_btn)

        reset_btn = QPushButton("Zurücksetzen")
        reset_btn.clicked.connect(self._reset_config)
        btn_layout.addWidget(reset_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        scroll.setWidget(widget)
        return scroll

    def _create_log_tab(self) -> QWidget:
        """Erstellt das Log-Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))

        self._log_filter_combo = QComboBox()
        self._log_filter_combo.addItems(["Alle", "Aktivierungen", "Deaktivierungen", "Warnungen", "Fehler"])
        self._log_filter_combo.currentIndexChanged.connect(self._filter_log)
        filter_layout.addWidget(self._log_filter_combo)

        filter_layout.addStretch()

        clear_btn = QPushButton("Log leeren")
        clear_btn.clicked.connect(self._clear_log)
        filter_layout.addWidget(clear_btn)

        export_btn = QPushButton("Exportieren")
        export_btn.clicked.connect(self._export_log)
        filter_layout.addWidget(export_btn)

        layout.addLayout(filter_layout)

        # Log-Anzeige
        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setStyleSheet(LOG_STYLE if LOG_STYLE else """
            QTextEdit {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
        """)
        layout.addWidget(self._log_text)

        return widget

    def _create_alert_widget(self) -> QWidget:
        """Erstellt den Alert-Bereich"""
        widget = QFrame()
        widget.setFrameStyle(QFrame.StyledPanel)
        widget.setStyleSheet("""
            QFrame {
                background-color: #fff3e0;
                border: 2px solid #ff9800;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(widget)

        # Header
        header_layout = QHBoxLayout()
        alert_icon = QLabel("⚠️")
        alert_icon.setStyleSheet("font-size: 20px;")
        header_layout.addWidget(alert_icon)

        self._alert_title = QLabel("Alert: Bestätigung erforderlich")
        self._alert_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_layout.addWidget(self._alert_title)
        header_layout.addStretch()

        layout.addLayout(header_layout)

        # Alert Details
        self._alert_details = QLabel("")
        self._alert_details.setWordWrap(True)
        layout.addWidget(self._alert_details)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._alert_reject_btn = QPushButton("Ablehnen")
        self._alert_reject_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
            }
        """)
        self._alert_reject_btn.clicked.connect(lambda: self._respond_to_alert(False))
        btn_layout.addWidget(self._alert_reject_btn)

        self._alert_accept_btn = QPushButton("Bestätigen")
        self._alert_accept_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                padding: 8px 20px;
                border-radius: 4px;
            }
        """)
        self._alert_accept_btn.clicked.connect(lambda: self._respond_to_alert(True))
        btn_layout.addWidget(self._alert_accept_btn)

        layout.addLayout(btn_layout)

        return widget

    # ==================== CONTROLLER MANAGEMENT ====================

    def _on_start_stop_clicked(self):
        """Start/Stop Button Handler"""
        if self._controller and self._controller.isRunning():
            self._stop_controller()
        else:
            self._start_controller()

    def _start_controller(self):
        """Startet den KI-Controller"""
        if not KI_CONTROLLER_AVAILABLE:
            QMessageBox.warning(
                self,
                "Nicht verfügbar",
                "KI-Controller Module konnten nicht geladen werden."
            )
            return

        # Config aus UI lesen
        self._update_config_from_ui()

        # Level Pool initialisieren
        self._level_pool = LevelPool()
        if self._trading_bot and hasattr(self._trading_bot, 'available_scenarios'):
            imported = self._level_pool.import_from_scenarios(
                self._trading_bot.available_scenarios
            )
            self._log(f"Level Pool: {imported} Levels importiert", "INFO")

        # API Adapter erstellen
        if self._trading_bot:
            self._api_adapter = TradingBotAPIAdapter(self._trading_bot)

        # Controller erstellen und starten
        self._controller = KIControllerThread(self._config)

        # Signals verbinden
        self._controller.status_changed.connect(self._on_status_changed)
        self._controller.log_message.connect(self._on_log_message)
        self._controller.decision_made.connect(self._on_decision_made)
        self._controller.alert_created.connect(self._on_alert_created)
        self._controller.market_analysis_update.connect(self._on_analysis_update)
        self._controller.volatility_regime_changed.connect(self._on_volatility_changed)
        self._controller.soft_limit_warning.connect(self._on_soft_limit_warning)
        self._controller.hard_limit_reached.connect(self._on_hard_limit_reached)

        # API und Level Pool setzen
        if self._api_adapter:
            self._controller.set_trading_bot_api(self._api_adapter)
        if self._level_pool:
            self._controller.set_level_pool(self._level_pool.to_controller_format())

        # Starten
        self._controller.start()

        # UI aktualisieren
        self._start_btn.setText("Stoppen")
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
        """)
        self._mode_combo.setEnabled(False)

        self.controller_started.emit()
        self._log("KI-Controller gestartet", "SUCCESS")

    def _stop_controller(self):
        """Stoppt den KI-Controller"""
        if self._controller:
            self._controller.stop()
            self._controller.wait(5000)  # Max 5 Sekunden warten
            self._controller = None

        # UI aktualisieren
        self._start_btn.setText("Starten")
        self._start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self._mode_combo.setEnabled(True)
        self._status_label.setText("Status: Gestoppt")
        self._status_label.setStyleSheet("font-weight: bold; padding: 5px; color: #666;")

        self.controller_stopped.emit()
        self._log("KI-Controller gestoppt", "INFO")

    def _on_mode_changed(self, index: int):
        """Handler für Modus-Änderung"""
        modes = [ControllerMode.OFF, ControllerMode.ALERT, ControllerMode.AUTONOMOUS]
        if self._config and index < len(modes):
            self._config.mode = modes[index]

    # ==================== SIGNAL HANDLERS ====================

    @Slot(str, str)
    def _on_status_changed(self, status: str, message: str):
        """Handler für Status-Änderungen"""
        color_map = {
            'RUNNING': '#4CAF50',
            'PAUSED': '#ff9800',
            'ALERT_PENDING': '#ff9800',
            'EMERGENCY': '#f44336',
            'ERROR': '#f44336',
            'STOPPED': '#666',
        }
        color = color_map.get(status, '#666')

        self._status_label.setText(f"Status: {status}")
        self._status_label.setStyleSheet(f"font-weight: bold; padding: 5px; color: {color};")

    @Slot(str, str)
    def _on_log_message(self, message: str, level: str):
        """Handler für Log-Nachrichten"""
        self._log(message, level)

    @Slot(dict)
    def _on_decision_made(self, decision: dict):
        """Handler für neue Entscheidungen"""
        decision_type = decision.get('decision_type', 'UNKNOWN')
        symbol = decision.get('symbol', '')
        timestamp = decision.get('timestamp', '')

        self._log(
            f"Entscheidung: {decision_type} für {symbol}",
            "INFO"
        )

        # Aktive Levels Tabelle aktualisieren
        self._update_active_levels_table()

    @Slot(dict)
    def _on_alert_created(self, alert: dict):
        """Handler für neue Alerts"""
        alert_id = alert.get('alert_id', '')
        decision = alert.get('decision', {})

        self._pending_alerts[alert_id] = alert

        # Alert-Widget anzeigen
        self._alert_title.setText(f"Alert: {decision.get('decision_type', 'Unbekannt')}")
        self._alert_details.setText(
            f"Symbol: {decision.get('symbol', '')}\n"
            f"Grund: {decision.get('reason', '')}\n"
            f"Timeout in {self._config.alerts.confirmation_timeout if self._config else 60} Sekunden"
        )
        self._alert_widget.setVisible(True)
        self._current_alert_id = alert_id

    @Slot(dict)
    def _on_analysis_update(self, analysis: dict):
        """Handler für Analyse-Updates"""
        symbol = analysis.get('symbol', '')
        price = analysis.get('price', 0)
        regime = analysis.get('volatility_regime', 'UNKNOWN')
        atr = analysis.get('atr_5', 0)
        volume_ratio = analysis.get('volume_ratio', 0)
        trading_phase = analysis.get('trading_phase', 'UNKNOWN')

        # Basis-Felder aktualisieren
        self._current_price_label.setText(f"${price:.2f}")
        self._atr_label.setText(f"{atr:.3f}%")

        # Volumen-Label aktualisieren
        if volume_ratio > 0:
            self._volume_label.setText(f"{volume_ratio:.1f}x")
            # Farbcodierung für Volumen
            if volume_ratio >= 2.5:
                self._volume_label.setStyleSheet("color: #f44336; font-weight: bold;")  # Rot für Spike
            elif volume_ratio >= 1.5:
                self._volume_label.setStyleSheet("color: #ff9800; font-weight: bold;")  # Orange für hoch
            else:
                self._volume_label.setStyleSheet("color: #4CAF50;")  # Grün für normal
        else:
            self._volume_label.setText("-")
            self._volume_label.setStyleSheet("")

        # Tageszeit-Regime Label aktualisieren
        phase_names = {
            'PRE_MARKET': 'Pre-Market',
            'OPEN': 'Eröffnung',
            'MORNING': 'Vormittag',
            'MIDDAY': 'Mittag',
            'AFTERNOON': 'Nachmittag',
            'CLOSE': 'Schluss',
            'AFTER_HOURS': 'After-Hours',
            'CLOSED': 'Geschlossen',
            'UNKNOWN': '-'
        }
        self._time_regime_label.setText(phase_names.get(trading_phase, trading_phase))

        # Volatilitäts-Card aktualisieren
        value_label = self._volatility_card.findChild(QLabel, "value")
        if value_label:
            value_label.setText(regime)

        # Decision Visualizer aktualisieren (wenn vorhanden)
        if self._decision_viz:
            self._decision_viz.update_market_data(analysis)

        # Statistics Widget aktualisieren (wenn vorhanden)
        if self._statistics_widget:
            self._statistics_widget.on_market_update(analysis)

    @Slot(str, str)
    def _on_volatility_changed(self, symbol: str, regime: str):
        """Handler für Volatilitäts-Regime Änderungen"""
        self._log(f"{symbol}: Volatilität → {regime}", "INFO")

        regime_colors = {
            'HIGH': '#f44336',
            'MEDIUM': '#ff9800',
            'LOW': '#4CAF50',
            'UNKNOWN': '#666',
        }

        value_label = self._volatility_card.findChild(QLabel, "value")
        if value_label:
            value_label.setText(regime)
            value_label.setStyleSheet(
                f"font-size: 24px; font-weight: bold; color: {regime_colors.get(regime, '#333')};"
            )

    @Slot(str, float)
    def _on_soft_limit_warning(self, limit_name: str, current_value: float):
        """Handler für Soft-Limit Warnungen"""
        self._log(f"WARNUNG: {limit_name} bei {current_value:.2f}", "WARNING")

    @Slot(str)
    def _on_hard_limit_reached(self, limit_name: str):
        """Handler für Hard-Limit Erreichen"""
        self._log(f"KRITISCH: {limit_name} erreicht!", "ERROR")
        QMessageBox.critical(
            self,
            "Hard Limit erreicht",
            f"Das Limit '{limit_name}' wurde erreicht.\n"
            "Der Controller wird gestoppt."
        )

    # ==================== ALERT HANDLING ====================

    def _respond_to_alert(self, confirmed: bool):
        """Reagiert auf einen Alert"""
        if hasattr(self, '_current_alert_id'):
            alert_id = self._current_alert_id

            if self._controller:
                self._controller.confirm_alert(alert_id, confirmed)

            action = "bestätigt" if confirmed else "abgelehnt"
            self._log(f"Alert {alert_id}: {action}", "INFO")

            # Alert-Widget verstecken
            self._alert_widget.setVisible(False)

            # Aus pending entfernen
            if alert_id in self._pending_alerts:
                del self._pending_alerts[alert_id]

            self.alert_response.emit(alert_id, confirmed)

    # ==================== CONFIG MANAGEMENT ====================

    def _load_config(self):
        """Lädt die Konfiguration"""
        if KI_CONTROLLER_AVAILABLE:
            self._config = KIControllerConfig.load()
            self._update_ui_from_config()

    def _save_config(self):
        """Speichert die Konfiguration"""
        self._update_config_from_ui()
        if self._config:
            self._config.save()
            self._log("Konfiguration gespeichert", "SUCCESS")

    def _reset_config(self):
        """Setzt Konfiguration auf Default zurück"""
        if KI_CONTROLLER_AVAILABLE:
            self._config = KIControllerConfig()
            self._update_ui_from_config()
            self._log("Konfiguration zurückgesetzt", "INFO")

    def _init_testing_components(self):
        """Initialisiert Paper Trading und Performance Tracking"""
        if not KI_CONTROLLER_AVAILABLE:
            return

        # Paper Trader
        self._paper_trader = PaperTrader(
            starting_capital=100000.0,
            commission_per_share=0.005,
            slippage_pct=0.01,
            realistic_fills=True,
        )

        # Performance Tracker
        self._performance_tracker = PerformanceTracker(max_history=10000)
        self._performance_tracker.set_starting_equity(100000.0)

        # Callbacks verbinden
        self._paper_trader.set_on_trade_closed(self._on_paper_trade_closed)

        self._log("Testing-Komponenten initialisiert", "INFO")

    def _on_paper_trade_closed(self, trade):
        """Callback wenn ein Paper Trade geschlossen wird"""
        if self._performance_tracker:
            self._performance_tracker.record_trade_exit(
                trade_id=trade.trade_id,
                exit_price=trade.exit_price,
                reason="Paper Trade",
                commission=trade.commission_total,
            )

        # Statistics Widget aktualisieren
        if self._statistics_widget:
            self._update_statistics_display()

    def _update_statistics_display(self):
        """Aktualisiert das Statistics Widget"""
        if not self._statistics_widget or not self._performance_tracker:
            return

        try:
            # Metriken
            metrics = self._performance_tracker.calculate_metrics()
            self._statistics_widget.update_metrics(metrics.to_dict())

            # Trades
            trades = self._performance_tracker.get_trades(100)
            self._statistics_widget.update_trades([t.to_dict() for t in trades])

            # Entscheidungen
            decisions = self._performance_tracker.get_decisions(100)
            self._statistics_widget.update_decisions([d.to_dict() for d in decisions])

            # Equity Curve
            equity_data = self._performance_tracker.get_equity_curve()
            self._statistics_widget.update_equity_curve(
                equity_data,
                self._performance_tracker._starting_equity
            )

            # Analysen
            self._statistics_widget.update_time_analysis(
                self._performance_tracker.get_trade_analysis_by_time()
            )
            self._statistics_widget.update_level_analysis(
                self._performance_tracker.get_trade_analysis_by_level()
            )
            self._statistics_widget.update_decision_quality(
                self._performance_tracker.get_decision_analysis()
            )
        except Exception as e:
            pass  # Stille Fehler bei Updates

    def _update_decision_visualizer(self, levels: list, predictions: dict, context: dict):
        """Aktualisiert den Decision Visualizer"""
        if not self._decision_viz:
            return

        try:
            self._decision_viz.update_level_scores(levels)
            self._decision_viz.update_predictions(predictions)
            self._decision_viz.update_market_context(context)
        except Exception as e:
            pass

    def _update_ui_from_config(self):
        """Aktualisiert UI aus Config"""
        if not self._config:
            return

        # Modus
        mode_index = {
            ControllerMode.OFF: 0,
            ControllerMode.ALERT: 1,
            ControllerMode.AUTONOMOUS: 2,
        }.get(self._config.mode, 0)
        self._mode_combo.setCurrentIndex(mode_index)

        # Risk Limits
        self._max_daily_loss_spin.setValue(float(self._config.risk_limits.max_daily_loss))
        self._max_positions_spin.setValue(self._config.risk_limits.max_open_positions)
        self._max_exposure_spin.setValue(float(self._config.risk_limits.max_exposure_per_symbol))
        self._max_levels_spin.setValue(self._config.risk_limits.max_active_levels)

        # Decision Settings
        self._reevaluation_spin.setValue(self._config.analysis.reevaluation_interval)
        self._min_hold_time_spin.setValue(self._config.decision.min_combination_hold_time_sec)
        self._max_changes_spin.setValue(self._config.decision.max_changes_per_hour)
        self._slippage_spin.setValue(self._config.decision.assumed_slippage_pct)

        # Alert Settings
        self._confirm_activate_check.setChecked(self._config.alerts.confirm_activate_level)
        self._confirm_deactivate_check.setChecked(self._config.alerts.confirm_deactivate_level)
        self._confirm_stop_check.setChecked(self._config.alerts.confirm_stop_trade)
        self._confirm_close_check.setChecked(self._config.alerts.confirm_close_position)
        self._alert_timeout_spin.setValue(self._config.alerts.confirmation_timeout)

    def _update_config_from_ui(self):
        """Aktualisiert Config aus UI"""
        if not self._config:
            if KI_CONTROLLER_AVAILABLE:
                self._config = KIControllerConfig()
            else:
                return

        # Modus
        modes = [ControllerMode.OFF, ControllerMode.ALERT, ControllerMode.AUTONOMOUS]
        self._config.mode = modes[self._mode_combo.currentIndex()]

        # Risk Limits
        self._config.risk_limits.max_daily_loss = Decimal(str(self._max_daily_loss_spin.value()))
        self._config.risk_limits.max_open_positions = self._max_positions_spin.value()
        self._config.risk_limits.max_exposure_per_symbol = Decimal(str(self._max_exposure_spin.value()))
        self._config.risk_limits.max_active_levels = self._max_levels_spin.value()

        # Decision Settings
        self._config.analysis.reevaluation_interval = self._reevaluation_spin.value()
        self._config.decision.min_combination_hold_time_sec = self._min_hold_time_spin.value()
        self._config.decision.max_changes_per_hour = self._max_changes_spin.value()
        self._config.decision.assumed_slippage_pct = self._slippage_spin.value()

        # Alert Settings
        self._config.alerts.confirm_activate_level = self._confirm_activate_check.isChecked()
        self._config.alerts.confirm_deactivate_level = self._confirm_deactivate_check.isChecked()
        self._config.alerts.confirm_stop_trade = self._confirm_stop_check.isChecked()
        self._config.alerts.confirm_close_position = self._confirm_close_check.isChecked()
        self._config.alerts.confirmation_timeout = self._alert_timeout_spin.value()

    # ==================== UI UPDATES ====================

    def _update_status_display(self):
        """Periodisches Update der Status-Anzeige"""
        if not self._controller or not self._controller.isRunning():
            return

        try:
            state = self._controller.get_state_snapshot()

            # Decisions Card
            perf = state.get('performance', {})
            value_label = self._decisions_card.findChild(QLabel, "value")
            if value_label:
                value_label.setText(str(perf.get('decisions_today', 0)))
            subtitle_label = self._decisions_card.findChild(QLabel, "subtitle")
            if subtitle_label:
                subtitle_label.setText(f"Aktivierungen: {perf.get('activations_today', 0)}")

            # Active Levels Card
            active_levels = state.get('active_levels', {})
            long_count = sum(1 for l in active_levels.values() if l.get('side') == 'LONG')
            short_count = sum(1 for l in active_levels.values() if l.get('side') == 'SHORT')

            value_label = self._active_levels_card.findChild(QLabel, "value")
            if value_label:
                value_label.setText(str(len(active_levels)))
            subtitle_label = self._active_levels_card.findChild(QLabel, "subtitle")
            if subtitle_label:
                subtitle_label.setText(f"Long: {long_count} / Short: {short_count}")

            # P&L Card
            realized = float(perf.get('realized_pnl_today', 0) or 0)
            unrealized = float(perf.get('unrealized_pnl', 0) or 0)
            total = realized + unrealized

            value_label = self._pnl_card.findChild(QLabel, "value")
            if value_label:
                color = '#4CAF50' if total >= 0 else '#f44336'
                value_label.setText(f"${total:,.2f}")
                value_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color};")
            subtitle_label = self._pnl_card.findChild(QLabel, "subtitle")
            if subtitle_label:
                subtitle_label.setText(f"Realisiert: ${realized:,.2f}")

        except Exception as e:
            pass  # Stille Fehler bei Updates

    def _update_active_levels_table(self):
        """Aktualisiert die Tabelle der aktiven Levels"""
        if not self._controller:
            return

        try:
            state = self._controller.get_state_snapshot()
            active_levels = state.get('active_levels', {})

            self._active_table.setRowCount(len(active_levels))

            for row, (level_id, level) in enumerate(active_levels.items()):
                self._active_table.setItem(row, 0, QTableWidgetItem(level.get('symbol', '')))
                self._active_table.setItem(row, 1, QTableWidgetItem(level.get('side', '')))
                self._active_table.setItem(row, 2, QTableWidgetItem(str(level.get('level_num', 0))))

                entry = level.get('entry_price')
                self._active_table.setItem(row, 3, QTableWidgetItem(
                    f"${entry:.2f}" if entry else "-"
                ))

                exit_p = level.get('exit_price')
                self._active_table.setItem(row, 4, QTableWidgetItem(
                    f"${exit_p:.2f}" if exit_p else "-"
                ))

                self._active_table.setItem(row, 5, QTableWidgetItem(str(level.get('shares', 0))))
                self._active_table.setItem(row, 6, QTableWidgetItem(f"{level.get('score', 0):.1f}"))
                self._active_table.setItem(row, 7, QTableWidgetItem(level.get('status', '')))

        except Exception as e:
            pass

    # ==================== LOGGING ====================

    def _log(self, message: str, level: str = "INFO"):
        """Fügt eine Log-Nachricht hinzu"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        color_map = {
            'INFO': '#d4d4d4',
            'SUCCESS': '#4ec9b0',
            'WARNING': '#dcdcaa',
            'ERROR': '#f44747',
        }
        color = color_map.get(level, '#d4d4d4')

        html = f'<span style="color: #858585;">[{timestamp}]</span> '
        html += f'<span style="color: {color};">[{level}]</span> '
        html += f'<span style="color: #d4d4d4;">{message}</span><br>'

        self._log_text.insertHtml(html)
        self._log_text.ensureCursorVisible()

    def _filter_log(self, index: int):
        """Filtert die Log-Anzeige"""
        # TODO: Implementierung
        pass

    def _clear_log(self):
        """Leert das Log"""
        self._log_text.clear()

    def _export_log(self):
        """Exportiert das Log"""
        # TODO: Implementierung
        self._log("Log-Export noch nicht implementiert", "WARNING")

    # ==================== CLEANUP ====================

    def closeEvent(self, event):
        """Aufräumen beim Schließen"""
        self._stop_controller()
        self._update_timer.stop()
        super().closeEvent(event)

    def set_trading_bot(self, trading_bot_widget):
        """Setzt die Trading-Bot Referenz"""
        self._trading_bot = trading_bot_widget
