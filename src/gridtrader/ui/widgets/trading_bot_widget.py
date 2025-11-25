"""
GridTrader V2.0 - Trading Bot Widget
Verwaltung und Monitoring von Trading-Szenarien
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QGroupBox, QLabel, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QMessageBox, QDialog, QFormLayout,
    QRadioButton, QButtonGroup, QDoubleSpinBox,
    QSpinBox, QLineEdit, QDialogButtonBox, QTextEdit,
    QFrame, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QFont, QColor, QTextCursor
from datetime import datetime, date, time
from typing import Dict, List, Optional
from pathlib import Path
import json
import asyncio

# Timezone support for NY trading hours
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    NY_TZ = ZoneInfo("America/New_York")
except ImportError:
    import pytz
    NY_TZ = pytz.timezone("America/New_York")

# IBKR imports (optional)
try:
    from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRBrokerAdapter, IBKRConfig
    # NUR IBKRService verwenden - KEINE shared_connection mehr!
    from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service, IBKRService
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    get_ibkr_service = None
    IBKRService = None

# Trading Log Excel Export
from gridtrader.infrastructure.reports.trading_log import TradingLogExporter


class ActivationDialog(QDialog):
    """Dialog für Level-Aktivierung mit Preis- und Aktien-Konfiguration"""

    def __init__(self, selected_levels: List[dict], parent=None):
        super().__init__(parent)
        self.selected_levels = selected_levels
        self.setWindowTitle("Levels aktivieren")
        self.setMinimumWidth(450)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Info über Auswahl
        info_label = QLabel(f"{len(self.selected_levels)} Level(s) ausgewählt")
        info_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(info_label)

        # Symbol (aus erstem Level)
        symbol = self.selected_levels[0]['symbol'] if self.selected_levels else 'N/A'
        form_layout = QFormLayout()

        self.symbol_edit = QLineEdit(symbol)
        form_layout.addRow("Symbol:", self.symbol_edit)

        # Preis-Auswahl
        price_group = QGroupBox("Basis-Preis")
        price_layout = QVBoxLayout()

        self.price_btn_group = QButtonGroup(self)

        # Option 1: Aktueller Marktpreis
        self.market_price_radio = QRadioButton("Aktueller Marktpreis (wird bei Aktivierung abgefragt)")
        self.price_btn_group.addButton(self.market_price_radio, 1)
        price_layout.addWidget(self.market_price_radio)

        # Option 2: Fixpreis
        fixed_layout = QHBoxLayout()
        self.fixed_price_radio = QRadioButton("Fixpreis:")
        self.price_btn_group.addButton(self.fixed_price_radio, 2)
        fixed_layout.addWidget(self.fixed_price_radio)

        self.fixed_price_spin = QDoubleSpinBox()
        self.fixed_price_spin.setRange(0.01, 99999.99)
        self.fixed_price_spin.setDecimals(2)
        self.fixed_price_spin.setValue(100.00)
        self.fixed_price_spin.setPrefix("$ ")
        self.fixed_price_spin.setEnabled(False)
        fixed_layout.addWidget(self.fixed_price_spin)
        fixed_layout.addStretch()

        price_layout.addLayout(fixed_layout)

        # Radio-Button Logik
        self.fixed_price_radio.toggled.connect(self.fixed_price_spin.setEnabled)
        self.market_price_radio.setChecked(True)

        price_group.setLayout(price_layout)
        layout.addWidget(price_group)

        # Aktien pro Trade
        shares_group = QGroupBox("Aktien-Konfiguration")
        shares_layout = QFormLayout()

        self.shares_spin = QSpinBox()
        self.shares_spin.setRange(1, 100000)
        # Default aus erstem Level
        default_shares = self.selected_levels[0].get('shares', 100) if self.selected_levels else 100
        self.shares_spin.setValue(default_shares)
        shares_layout.addRow("Aktien pro Level:", self.shares_spin)

        shares_group.setLayout(shares_layout)
        layout.addWidget(shares_group)

        form_layout_widget = QWidget()
        form_layout_widget.setLayout(form_layout)
        layout.insertWidget(1, form_layout_widget)

        # Vorschau der Levels
        preview_group = QGroupBox("Level-Vorschau (Prozentuale Werte)")
        preview_layout = QVBoxLayout()

        preview_text = ""
        for level in self.selected_levels[:5]:  # Max 5 anzeigen
            preview_text += f"Level {level['level_num']}: Entry {level['entry_pct']:+.2f}%, Exit {level['exit_pct']:+.2f}%\n"
        if len(self.selected_levels) > 5:
            preview_text += f"... und {len(self.selected_levels) - 5} weitere"

        preview_label = QLabel(preview_text)
        preview_label.setStyleSheet("font-family: monospace;")
        preview_layout.addWidget(preview_label)

        preview_group.setLayout(preview_layout)
        layout.addWidget(preview_group)

        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_configuration(self) -> dict:
        """Gibt die Konfiguration zurück"""
        use_market = self.market_price_radio.isChecked()

        return {
            'symbol': self.symbol_edit.text(),
            'use_market_price': use_market,
            # WICHTIG: Wenn Market Price gewählt ist, MUSS fixed_price None sein
            'fixed_price': None if use_market else self.fixed_price_spin.value(),
            'shares': self.shares_spin.value()
        }


class TradingBotWidget(QWidget):
    """Haupt-Widget für Trading Bot Management"""

    # Signal wenn Szenario importiert werden soll
    scenario_imported = Signal(dict)

    def __init__(self):
        super().__init__()
        self.available_scenarios = {}  # Importierte Szenarien
        self.waiting_levels = []  # Aktivierte Levels, die auf Einstieg warten
        self.active_levels = []  # Levels mit offenen Positionen
        self.pending_orders = {}  # Track pending orders

        # Order-Tracking für Level-Protection
        self._orders_placed_for_levels = set()  # HIER initialisieren!

        # Market Data Cache für Waiting Table Updates
        self._last_market_prices = {}  # {symbol: last_price}


        # Pfad für persistente Daten
        self.data_dir = Path.home() / ".gridtrader"
        self.scenarios_file = self.data_dir / "trading_bot_scenarios.json"
        self.logs_dir = self.data_dir / "logs"

        # Daily Statistics
        self.daily_stats = {
            'date': date.today().isoformat(),
            'total_pnl': 0.0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_commissions': 0.0,
            'total_volume': 0.0,  # Anzahl Aktien * Preis
            'total_shares': 0
        }

        # Log messages
        self.log_messages = []

        # Trade history für persistente Logs
        self.trade_history = []

        # IBKR Connection (verwendet Shared Connection vom Live Trading Tab)
        self.live_trading_enabled = False
        self.market_data_timer: Optional[QTimer] = None
        self.connection_check_timer: Optional[QTimer] = None
        self.status_check_task = None  # Async Task für Order Status Checking

        # NEU: IBKRService Referenz (Event-basierte Architektur)
        self._ibkr_service: Optional[IBKRService] = None
        self._service_connected = False
        self._order_callbacks: Dict[str, dict] = {}  # callback_id -> order_info

        # Trading Hours (NY Zeit) - Default: 9:30-16:00
        self.trading_hours_start = time(9, 30)  # 9:30 AM NY
        self.trading_hours_end = time(16, 0)    # 4:00 PM NY
        self.enforce_trading_hours = True        # Trading nur während Handelszeiten

        # Log Files initialisieren
        self._init_log_files()

        # Excel Trading Log Exporter initialisieren
        self.trading_log_exporter = TradingLogExporter(self.logs_dir)

        self.init_ui()

        # NEU: Starte Order Status Monitor
        # OrderStatusMonitor deaktiviert (Event Loop Konflikt)
        self.status_monitor = None

        # Lade gespeicherte Szenarien beim Start
        self.load_scenarios_from_file()

        # Log initial message
        self.log_message("Trading-Bot gestartet", "INFO")

        if IBKR_AVAILABLE:
            self.log_message("IBKR-Integration verfügbar", "INFO")
            # NUR IBKRService verwenden (Event-basierte Architektur)
            self._setup_ibkr_service()
            # KEIN Legacy-Timer mehr! Market Data kommt per Push via IBKRService
        else:
            self.log_message("IBKR nicht verfügbar - pip install ib_insync", "WARNING")

        # Starte NY Zeit Update Timer (jede Sekunde)
        self.ny_time_timer = QTimer()
        self.ny_time_timer.timeout.connect(self._update_ny_time_display)
        self.ny_time_timer.start(1000)  # Jede Sekunde
        self._update_ny_time_display()  # Sofort einmal aktualisieren

        # Auto-Save Timer (alle 5 Minuten) - schützt vor Datenverlust bei Absturz
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self._auto_save_logs)
        self.autosave_timer.start(5 * 60 * 1000)  # 5 Minuten in Millisekunden
        self.log_message("Auto-Save aktiviert (alle 5 Minuten)", "INFO")

    def _init_log_files(self):
        """Initialisiere Log-Dateien für Daily und Yearly Tracking"""
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)

            # Daily Log - neues File bei jedem Start
            today = date.today()
            start_time = datetime.now().strftime("%H%M%S")
            self.daily_log_file = self.logs_dir / f"daily_{today.isoformat()}_{start_time}.json"

            # Yearly Log - fortlaufend, neues File per 1.1.
            year = today.year
            self.yearly_log_file = self.logs_dir / f"yearly_{year}.json"

            # Daily Log initialisieren
            daily_header = {
                'session_start': datetime.now().isoformat(),
                'date': today.isoformat(),
                'trades': []
            }
            with open(self.daily_log_file, 'w', encoding='utf-8') as f:
                json.dump(daily_header, f, indent=2, ensure_ascii=False)

            # Yearly Log initialisieren oder laden
            if not self.yearly_log_file.exists():
                yearly_header = {
                    'year': year,
                    'created_at': datetime.now().isoformat(),
                    'sessions': [],
                    'trades': [],
                    'daily_summaries': []
                }
                with open(self.yearly_log_file, 'w', encoding='utf-8') as f:
                    json.dump(yearly_header, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"Log-File Initialisierung fehlgeschlagen: {e}")

    def _write_trade_to_logs(self, trade_data: dict):
        """Schreibe Trade in Daily und Yearly Log"""
        try:
            # Daily Log aktualisieren
            if hasattr(self, 'daily_log_file') and self.daily_log_file.exists():
                with open(self.daily_log_file, 'r', encoding='utf-8') as f:
                    daily_data = json.load(f)

                daily_data['trades'].append(trade_data)

                with open(self.daily_log_file, 'w', encoding='utf-8') as f:
                    json.dump(daily_data, f, indent=2, ensure_ascii=False)

            # Yearly Log aktualisieren
            if hasattr(self, 'yearly_log_file') and self.yearly_log_file.exists():
                with open(self.yearly_log_file, 'r', encoding='utf-8') as f:
                    yearly_data = json.load(f)

                yearly_data['trades'].append(trade_data)

                with open(self.yearly_log_file, 'w', encoding='utf-8') as f:
                    json.dump(yearly_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            self.log_message(f"Fehler beim Log-Schreiben: {e}", "ERROR")

    def _write_session_summary(self):
        """Schreibe Session-Zusammenfassung beim Beenden"""
        try:
            summary = {
                'session_end': datetime.now().isoformat(),
                'date': self.daily_stats['date'],
                'total_trades': self.daily_stats['total_trades'],
                'total_pnl': self.daily_stats['total_pnl'],
                'realized_pnl': self.daily_stats['realized_pnl'],
                'winning_trades': self.daily_stats['winning_trades'],
                'losing_trades': self.daily_stats['losing_trades'],
                'total_commissions': self.daily_stats['total_commissions'],
                'total_volume': self.daily_stats['total_volume'],
                'total_shares': self.daily_stats['total_shares']
            }

            # Daily Log Summary
            if hasattr(self, 'daily_log_file') and self.daily_log_file.exists():
                with open(self.daily_log_file, 'r', encoding='utf-8') as f:
                    daily_data = json.load(f)

                daily_data['session_end'] = summary['session_end']
                daily_data['summary'] = summary

                with open(self.daily_log_file, 'w', encoding='utf-8') as f:
                    json.dump(daily_data, f, indent=2, ensure_ascii=False)

            # Yearly Log Session hinzufügen
            if hasattr(self, 'yearly_log_file') and self.yearly_log_file.exists():
                with open(self.yearly_log_file, 'r', encoding='utf-8') as f:
                    yearly_data = json.load(f)

                yearly_data['sessions'].append(summary)

                # Daily Summary für diesen Tag aktualisieren
                today_iso = date.today().isoformat()
                daily_found = False
                for ds in yearly_data['daily_summaries']:
                    if ds['date'] == today_iso:
                        # Bestehenden Tag aktualisieren
                        ds['total_trades'] += summary['total_trades']
                        ds['total_pnl'] += summary['total_pnl']
                        ds['winning_trades'] += summary['winning_trades']
                        ds['losing_trades'] += summary['losing_trades']
                        ds['total_commissions'] += summary['total_commissions']
                        ds['total_volume'] += summary['total_volume']
                        ds['total_shares'] += summary['total_shares']
                        daily_found = True
                        break

                if not daily_found:
                    yearly_data['daily_summaries'].append({
                        'date': today_iso,
                        'total_trades': summary['total_trades'],
                        'total_pnl': summary['total_pnl'],
                        'winning_trades': summary['winning_trades'],
                        'losing_trades': summary['losing_trades'],
                        'total_commissions': summary['total_commissions'],
                        'total_volume': summary['total_volume'],
                        'total_shares': summary['total_shares']
                    })

                with open(self.yearly_log_file, 'w', encoding='utf-8') as f:
                    json.dump(yearly_data, f, indent=2, ensure_ascii=False)

            self.log_message("Session-Summary gespeichert", "SUCCESS")

        except Exception as e:
            self.log_message(f"Fehler beim Summary-Schreiben: {e}", "ERROR")

    def _auto_save_logs(self):
        """Automatisches Speichern der Logs (wird vom Timer aufgerufen)"""
        if hasattr(self, 'trading_log_exporter'):
            try:
                self.trading_log_exporter.save_intermediate()
                self.log_message("Auto-Save: Logs gespeichert", "INFO")
            except Exception as e:
                self.log_message(f"Auto-Save Fehler: {e}", "ERROR")

    # ========== NEU: IBKR SERVICE INTEGRATION ==========

    def _setup_ibkr_service(self):
        """
        Initialisiere IBKRService und verbinde Signals

        Der IBKRService verwendet einen dedizierten Thread mit eigenem Event Loop,
        wodurch Qt/asyncio Event Loop Konflikte vermieden werden.
        """
        if not IBKR_AVAILABLE or get_ibkr_service is None:
            self.log_message("IBKRService nicht verfügbar", "WARNING")
            return

        try:
            self._ibkr_service = get_ibkr_service()

            # Verbinde Signals (Thread-safe über Qt Signal/Slot)
            self._ibkr_service.signals.connected.connect(self._on_service_connected)
            self._ibkr_service.signals.disconnected.connect(self._on_service_disconnected)
            self._ibkr_service.signals.connection_lost.connect(self._on_service_connection_lost)
            self._ibkr_service.signals.market_data_update.connect(self._on_market_data_update)
            self._ibkr_service.signals.order_placed.connect(self._on_order_placed)
            self._ibkr_service.signals.order_status_changed.connect(self._on_order_status_changed)
            self._ibkr_service.signals.order_filled.connect(self._on_order_filled)
            self._ibkr_service.signals.order_error.connect(self._on_order_error)

            self.log_message("IBKRService initialisiert (Event-basierte Architektur)", "SUCCESS")

        except Exception as e:
            self.log_message(f"IBKRService Initialisierung fehlgeschlagen: {e}", "ERROR")

    def _on_service_connected(self, success: bool, message: str):
        """Callback wenn IBKRService verbunden ist"""
        self._service_connected = success

        if success:
            self.log_message(f"IBKRService: {message}", "SUCCESS")

            # UI aktualisieren
            if hasattr(self, 'ibkr_status_label'):
                self.ibkr_status_label.setText("Verbunden (Service)")
                self.ibkr_status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #0a0;")
            if hasattr(self, 'live_trading_cb'):
                self.live_trading_cb.setEnabled(True)

            # Stoppe Legacy Market Data Timer (falls laufend)
            if self.market_data_timer:
                self.market_data_timer.stop()
                self.market_data_timer = None
                self.log_message("Legacy Market Data Timer gestoppt", "INFO")

            # Subscribiere Market Data für alle aktiven Symbole
            self._subscribe_active_symbols()
        else:
            self.log_message(f"IBKRService Verbindungsfehler: {message}", "ERROR")

    def _on_service_disconnected(self):
        """Callback wenn IBKRService getrennt wird"""
        self._service_connected = False
        self.log_message("IBKRService getrennt", "INFO")

        # UI aktualisieren
        if hasattr(self, 'ibkr_status_label'):
            self.ibkr_status_label.setText("Nicht verbunden")
            self.ibkr_status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #c00;")
        if hasattr(self, 'live_trading_cb'):
            self.live_trading_cb.setEnabled(False)
            self.live_trading_cb.setChecked(False)
            self.live_trading_enabled = False

    def _on_service_connection_lost(self):
        """Callback wenn IBKRService Verbindung verliert"""
        self._service_connected = False
        self.log_message("IBKRService: Verbindung verloren!", "ERROR")

        # UI aktualisieren
        if hasattr(self, 'ibkr_status_label'):
            self.ibkr_status_label.setText("Verbindung verloren!")
            self.ibkr_status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #c00;")

    def _subscribe_active_symbols(self):
        """Subscribiere Market Data für alle aktiven Symbole"""
        if not self._ibkr_service or not self._service_connected:
            return

        # Sammle alle Symbole
        symbols = set()
        for level in self.waiting_levels:
            symbols.add(level['symbol'])
        for level in self.active_levels:
            symbols.add(level.get('symbol', ''))

        if symbols:
            self._ibkr_service.subscribe_market_data(list(symbols))
            self.log_message(f"Market Data subscribed: {', '.join(symbols)}", "INFO")

    def _on_market_data_update(self, data: dict):
        """
        Callback für Market Data Updates (PUSH von IBKRService)

        Diese Methode wird automatisch aufgerufen wenn neue Kursdaten kommen.
        Kein Polling mehr nötig!
        """
        symbol = data.get('symbol', '')
        if not symbol:
            return

        # Cache aktualisieren (für UI-Anzeige)
        self._last_market_prices[symbol] = {
            'bid': data.get('bid', 0),
            'ask': data.get('ask', 0),
            'last': data.get('last', 0),
            'mid': (data.get('bid', 0) + data.get('ask', 0)) / 2 if data.get('bid') and data.get('ask') else data.get('last', 0)
        }

        # Update Basis-Preise für wartende Levels ohne Preis
        for level in self.waiting_levels:
            if level['symbol'] == symbol and level.get('base_price') is None:
                current_price = data.get('last', 0) or data.get('close', 0)
                if current_price > 0:
                    level['base_price'] = current_price
                    level['entry_price'] = current_price * (1 + level['entry_pct'] / 100)
                    level['exit_price'] = level['entry_price'] * (1 + level['exit_pct'] / 100)

                    self.log_message(
                        f"Level {level.get('scenario_name')} initialisiert mit ${current_price:.2f}",
                        "INFO"
                    )

        # Waiting Table aktualisieren
        self._update_waiting_table_prices(symbol)

        # Active Table aktualisieren (Preise, P&L, Diff)
        self._update_active_table_prices(symbol, data)

        # Entry/Exit Conditions prüfen (synchron - kein async nötig!)
        self._check_entry_conditions_sync(data)
        self._check_exit_conditions_sync(data)

    def _check_entry_conditions_sync(self, market_data: dict):
        """
        Prüfe Entry-Bedingungen synchron (von Market Data Update aufgerufen)

        Diese Methode ersetzt die async Version für den Service-Modus.
        """
        # Prüfe Trading-Stunden
        if not self.is_market_open():
            return

        symbol = market_data.get('symbol', '')
        if not symbol:
            return

        levels_to_activate = []

        for i, level in enumerate(self.waiting_levels):
            if level.get('status') == 'paused':
                continue

            if level['symbol'] != symbol:
                continue

            # Eindeutiger Level-Identifier
            scenario_name = level.get('scenario_name', 'unknown')
            level_num = level.get('level_num', 0)
            unique_level_id = f"{scenario_name}_L{level_num}"

            if unique_level_id in self._orders_placed_for_levels:
                continue

            entry_price = level.get('entry_price')
            if entry_price is None:
                continue

            level_type = level['type']
            triggered = False
            check_price = 0

            # Entry-Bedingung prüfen
            if level_type == 'LONG':
                check_price = market_data.get('ask', 0) or market_data.get('last', 0)
                if check_price > 0 and check_price <= entry_price:
                    triggered = True
                    self.log_message(
                        f"LONG ENTRY: {symbol} ASK=${check_price:.2f} <= Ziel=${entry_price:.2f}",
                        "TRADE"
                    )
            elif level_type == 'SHORT':
                check_price = market_data.get('bid', 0) or market_data.get('last', 0)
                if check_price > 0 and check_price >= entry_price:
                    triggered = True
                    self.log_message(
                        f"SHORT ENTRY: {symbol} BID=${check_price:.2f} >= Ziel=${entry_price:.2f}",
                        "TRADE"
                    )

            if triggered:
                levels_to_activate.append((i, level, check_price))

        # Aktiviere Levels
        for idx, level, price in levels_to_activate:
            self._place_entry_order_via_service(level, price)

    def _check_exit_conditions_sync(self, market_data: dict):
        """
        Prüfe Exit-Bedingungen synchron (von Market Data Update aufgerufen)
        """
        if not self.is_market_open():
            return

        symbol = market_data.get('symbol', '')
        if not symbol:
            return

        levels_to_exit = []

        for i, level in enumerate(self.active_levels):
            if level.get('symbol') != symbol:
                continue

            if level.get('exit_order_placed'):
                continue

            exit_price = level.get('exit_price')
            if exit_price is None:
                continue

            level_type = level.get('type', 'LONG')
            triggered = False
            check_price = 0

            if level_type == 'LONG':
                check_price = market_data.get('bid', 0) or market_data.get('last', 0)
                if check_price > 0 and check_price >= exit_price:
                    triggered = True
                    self.log_message(
                        f"LONG EXIT: {symbol} BID=${check_price:.2f} >= Ziel=${exit_price:.2f}",
                        "TRADE"
                    )
            elif level_type == 'SHORT':
                check_price = market_data.get('ask', 0) or market_data.get('last', 0)
                if check_price > 0 and check_price <= exit_price:
                    triggered = True
                    self.log_message(
                        f"SHORT EXIT: {symbol} ASK=${check_price:.2f} <= Ziel=${exit_price:.2f}",
                        "TRADE"
                    )

            if triggered:
                levels_to_exit.append((i, level, check_price))

        # Exit Orders platzieren
        for idx, level, price in levels_to_exit:
            self._place_exit_order_via_service(level, price)

    def _place_entry_order_via_service(self, level: dict, trigger_price: float):
        """Platziere Entry Order über IBKRService"""
        if not self._ibkr_service or not self._service_connected:
            self.log_message("IBKRService nicht verbunden - keine Order platziert", "ERROR")
            return

        if not self.live_trading_enabled:
            self.log_message(
                f"ORDER (Simulation): {level['type']} {level.get('shares', 100)}x {level['symbol']}",
                "TRADE"
            )
            return

        try:
            from gridtrader.domain.models.order import Order, OrderSide, OrderType
            from decimal import Decimal

            # Level-Schutz
            scenario_name = level.get('scenario_name', 'unknown')
            level_num = level.get('level_num', 0)
            unique_level_id = f"{scenario_name}_L{level_num}"

            if unique_level_id in self._orders_placed_for_levels:
                return

            self._orders_placed_for_levels.add(unique_level_id)

            # Domain Order erstellen
            # WICHTIG: Order-Typ basierend auf UI-Auswahl (RadioButton)
            use_limit_order = self.limit_order_rb.isChecked() if hasattr(self, 'limit_order_rb') else True

            order = Order(
                symbol=level['symbol'],
                side=OrderSide.BUY if level['type'] == 'LONG' else OrderSide.SELL,
                order_type=OrderType.LIMIT if use_limit_order else OrderType.MARKET,
                quantity=level.get('shares', 100)
            )

            if use_limit_order:
                order.limit_price = Decimal(str(level['entry_price']))

            # Order via Service platzieren (non-blocking!)
            callback_id = self._ibkr_service.place_order(order)
            print(f">>> _place_entry_order: callback_id={callback_id[:8]}... erstellt")

            # Tracking
            self._order_callbacks[callback_id] = {
                'level': level,
                'type': 'ENTRY',
                'order': order,
                'unique_level_id': unique_level_id
            }
            print(f">>> _place_entry_order: callback zu _order_callbacks hinzugefügt, jetzt {len(self._order_callbacks)} Einträge")

            self.log_message(
                f"ENTRY ORDER: {level['type']} {level.get('shares', 100)}x {level['symbol']} @ ${level['entry_price']:.2f}",
                "TRADE"
            )

        except Exception as e:
            self.log_message(f"Entry Order Fehler: {e}", "ERROR")

    def _place_exit_order_via_service(self, level: dict, trigger_price: float):
        """Platziere Exit Order über IBKRService"""
        if not self._ibkr_service or not self._service_connected:
            return

        if not self.live_trading_enabled:
            return

        try:
            from gridtrader.domain.models.order import Order, OrderSide, OrderType
            from decimal import Decimal

            # Markiere Level als Exit-Order platziert
            level['exit_order_placed'] = True

            # Domain Order erstellen
            order = Order(
                symbol=level['symbol'],
                side=OrderSide.SELL if level['type'] == 'LONG' else OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=level.get('shares', 100)
            )
            order.limit_price = Decimal(str(level['exit_price']))

            # Order via Service platzieren
            callback_id = self._ibkr_service.place_order(order)

            # Tracking
            self._order_callbacks[callback_id] = {
                'level': level,
                'type': 'EXIT',
                'order': order
            }

            self.log_message(
                f"EXIT ORDER: {level.get('shares', 100)}x {level['symbol']} @ ${level['exit_price']:.2f}",
                "TRADE"
            )

        except Exception as e:
            self.log_message(f"Exit Order Fehler: {e}", "ERROR")

    def _on_order_placed(self, callback_id: str, broker_order_id: str):
        """Callback wenn Order bei IB platziert wurde"""
        print(f">>> _on_order_placed: callback_id={callback_id[:8]}..., broker_id={broker_order_id}")
        print(f">>> _order_callbacks hat {len(self._order_callbacks)} Einträge")
        print(f">>> callback_id in _order_callbacks: {callback_id in self._order_callbacks}")

        if callback_id in self._order_callbacks:
            order_info = self._order_callbacks[callback_id]
            order_info['broker_order_id'] = broker_order_id

            self.log_message(
                f"Order bestätigt: {broker_order_id} ({order_info['type']})",
                "SUCCESS"
            )

            # Füge zu pending_orders hinzu für Anzeige
            level = order_info['level']
            self.pending_orders[broker_order_id] = {
                'symbol': level['symbol'],
                'type': level.get('type', 'LONG'),
                'side': 'BUY' if order_info['type'] == 'ENTRY' and level['type'] == 'LONG' else 'SELL',
                'quantity': level.get('shares', 100),
                'status': 'SUBMITTED',
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'level_name': f"{level.get('scenario_name', 'N/A')} L{level.get('level_num', 0)}",
                'order_object': order_info['order'],
                'level_data': level,
                'callback_id': callback_id
            }

            # ENTRY Order: Level aus Warten entfernen (wird jetzt in Pending angezeigt)
            if order_info['type'] == 'ENTRY':
                if level in self.waiting_levels:
                    self.waiting_levels.remove(level)
                    self.update_waiting_levels_display()
                    self.log_message(
                        f"Level {level.get('scenario_name', 'N/A')} L{level.get('level_num', 0)} -> Pending",
                        "INFO"
                    )

            self.update_pending_display()

            # Prüfe ob es einen gespeicherten Fill für diese Order gibt (Race Condition Fix)
            if hasattr(self, '_pending_fills') and broker_order_id in self._pending_fills:
                fill_info = self._pending_fills.pop(broker_order_id)
                print(f">>> Verarbeite gespeicherten Fill für {broker_order_id}")
                self.log_message(f"Verarbeite zwischengespeicherten Fill für {broker_order_id}", "INFO")
                # Rekursiv _on_order_filled aufrufen - jetzt ist die Order in pending_orders
                self._on_order_filled(broker_order_id, fill_info)

    def _on_order_status_changed(self, broker_id: str, status: str, details: dict):
        """Callback für Order Status Updates"""
        if broker_id in self.pending_orders:
            self.pending_orders[broker_id]['status'] = status
            self.update_pending_display()

            self.log_message(f"Order {broker_id}: {status}", "INFO")

            # Bei Cancelled: Level-Tracking entfernen und zurück zu Warten
            if status == 'Cancelled':
                order_info = self.pending_orders[broker_id]
                callback_id = order_info.get('callback_id')
                level_data = order_info.get('level_data')

                if callback_id and callback_id in self._order_callbacks:
                    cb_info = self._order_callbacks[callback_id]
                    unique_level_id = cb_info.get('unique_level_id')
                    level = cb_info.get('level')

                    # Level-Schutz entfernen -> Level kann wieder getriggert werden
                    if unique_level_id:
                        self._orders_placed_for_levels.discard(unique_level_id)

                    # Level zurück zu waiting_levels hinzufügen (für ENTRY orders)
                    if cb_info.get('type') == 'ENTRY' and level:
                        if level not in self.waiting_levels:
                            self.waiting_levels.append(level)
                            self.update_waiting_levels_display()
                            self.log_message(
                                f"Order {broker_id} cancelled - Level zurück zu Warten",
                                "WARNING"
                            )

                    # Cleanup
                    del self._order_callbacks[callback_id]

                # Aus pending_orders entfernen
                del self.pending_orders[broker_id]
                self.update_pending_display()

    def _on_order_filled(self, broker_id: str, fill_info: dict):
        """Callback wenn Order gefüllt wurde"""
        print(f">>> _on_order_filled: broker_id={broker_id}")
        print(f">>> pending_orders hat {len(self.pending_orders)} Einträge: {list(self.pending_orders.keys())}")
        print(f">>> broker_id in pending_orders: {broker_id in self.pending_orders}")

        if broker_id not in self.pending_orders:
            # Fill kam bevor order_placed verarbeitet wurde - speichere für später
            print(f">>> WARNUNG: broker_id {broker_id} noch nicht in pending_orders - speichere Fill")
            if not hasattr(self, '_pending_fills'):
                self._pending_fills = {}
            self._pending_fills[broker_id] = fill_info
            self.log_message(f"Fill für {broker_id} zwischengespeichert (Order noch nicht registriert)", "WARNING")
            return

        order_info = self.pending_orders[broker_id]
        callback_id = order_info.get('callback_id')

        if callback_id and callback_id in self._order_callbacks:
            cb_info = self._order_callbacks[callback_id]
            level = cb_info['level']
            order_type = cb_info['type']

            fill_price = fill_info.get('price', 0) or fill_info.get('avg_fill_price', 0)
            commission = fill_info.get('commission', 0)

            if order_type == 'ENTRY':
                # Entry gefüllt -> Level wird aktiv
                self._handle_entry_fill(level, fill_price, commission)
            elif order_type == 'EXIT':
                # Exit gefüllt -> Level wird recycelt
                self._handle_exit_fill(level, fill_price, commission)

            # Cleanup
            del self._order_callbacks[callback_id]

        # Aus pending entfernen
        if broker_id in self.pending_orders:
            del self.pending_orders[broker_id]
            self.update_pending_display()

    def _handle_entry_fill(self, level: dict, fill_price: float, commission: float):
        """Verarbeite gefüllten Entry"""
        print(f">>> _handle_entry_fill: {level.get('scenario_name')}_L{level.get('level_num')}")
        print(f">>> waiting_levels hat {len(self.waiting_levels)} Einträge")
        print(f">>> active_levels hat {len(self.active_levels)} Einträge")

        self.log_message(
            f"ENTRY FILLED: {level['symbol']} @ ${fill_price:.2f} (Comm: ${commission:.2f})",
            "SUCCESS"
        )

        # Level zu aktiv verschieben
        level['entry_fill_price'] = fill_price
        level['entry_commission'] = commission
        level['entry_time'] = datetime.now().isoformat()
        level['exit_order_placed'] = False

        # Aus waiting entfernen und zu active hinzufügen
        if level in self.waiting_levels:
            self.waiting_levels.remove(level)
            print(f">>> Level aus waiting_levels entfernt")
        else:
            print(f">>> Level war NICHT in waiting_levels!")
        self.active_levels.append(level)
        print(f">>> Level zu active_levels hinzugefügt, jetzt {len(self.active_levels)} aktive")

        # Level-Schutz entfernen
        scenario_name = level.get('scenario_name', 'unknown')
        level_num = level.get('level_num', 0)
        unique_level_id = f"{scenario_name}_L{level_num}"
        self._orders_placed_for_levels.discard(unique_level_id)

        # UI aktualisieren
        self.update_waiting_levels_display()
        self.update_active_levels_display()

        # Daily Stats
        self.daily_stats['total_trades'] += 1
        self.daily_stats['total_commissions'] += commission
        self.daily_stats['total_shares'] += level.get('shares', 100)

    def _handle_exit_fill(self, level: dict, fill_price: float, commission: float):
        """Verarbeite gefüllten Exit"""
        entry_price = level.get('entry_fill_price', level.get('entry_price', 0))
        shares = level.get('shares', 100)

        # P&L berechnen
        if level['type'] == 'LONG':
            pnl = (fill_price - entry_price) * shares - commission - level.get('entry_commission', 0)
        else:
            pnl = (entry_price - fill_price) * shares - commission - level.get('entry_commission', 0)

        self.log_message(
            f"EXIT FILLED: {level['symbol']} @ ${fill_price:.2f}, P&L: ${pnl:+.2f}",
            "SUCCESS" if pnl >= 0 else "WARNING"
        )

        # Level aus active entfernen
        if level in self.active_levels:
            self.active_levels.remove(level)

        # Trade loggen
        trade_data = {
            'timestamp': datetime.now().isoformat(),
            'symbol': level['symbol'],
            'type': level['type'],
            'shares': shares,
            'entry_price': entry_price,
            'exit_price': fill_price,
            'pnl': pnl,
            'commission': commission + level.get('entry_commission', 0),
            'scenario': level.get('scenario_name', 'N/A'),
            'level': level.get('level_num', 0)
        }

        # JSON Logs schreiben
        self._write_trade_to_logs(trade_data)

        # Excel Trading Log schreiben
        if hasattr(self, 'trading_log_exporter'):
            self.trading_log_exporter.add_trade(trade_data)

        # Daily Stats
        self.daily_stats['realized_pnl'] += pnl
        self.daily_stats['total_pnl'] += pnl
        self.daily_stats['total_commissions'] += commission
        if pnl >= 0:
            self.daily_stats['winning_trades'] += 1
        else:
            self.daily_stats['losing_trades'] += 1

        # Level recyceln (zurück zu waiting)
        level['base_price'] = None
        level['entry_price'] = None
        level['exit_price'] = None
        level['entry_fill_price'] = None
        level['entry_commission'] = None
        level['entry_time'] = None
        level['exit_order_placed'] = False

        self.waiting_levels.append(level)

        # UI aktualisieren
        self.update_active_levels_display()
        self.update_waiting_levels_display()
        self._update_daily_stats_display()

    def _on_order_error(self, callback_id: str, error_msg: str):
        """Callback für Order Fehler"""
        self.log_message(f"Order Fehler: {error_msg}", "ERROR")

        # Level-Schutz entfernen bei Fehler
        if callback_id in self._order_callbacks:
            cb_info = self._order_callbacks[callback_id]
            unique_level_id = cb_info.get('unique_level_id')
            if unique_level_id:
                self._orders_placed_for_levels.discard(unique_level_id)
            del self._order_callbacks[callback_id]

    # ========== ENDE: IBKR SERVICE INTEGRATION ==========

    def save_logs_now(self):
        """Manuelles Speichern der Logs (für Dashboard-Button)"""
        if hasattr(self, 'trading_log_exporter'):
            try:
                self.trading_log_exporter.save_intermediate()
                self.log_message("Logs manuell gespeichert", "SUCCESS")
                return True
            except Exception as e:
                self.log_message(f"Fehler beim Speichern: {e}", "ERROR")
                return False
        return False

    def closeEvent(self, event):
        """Override: Beim Schliessen Session-Summary speichern"""
        self._write_session_summary()

        # Excel Trading Logs finalisieren (Totals schreiben)
        if hasattr(self, 'trading_log_exporter'):
            self.trading_log_exporter.finalize_session()

        super().closeEvent(event)

    def init_ui(self):
        """UI initialisieren"""
        layout = QVBoxLayout()

        # Header
        header = QLabel("Trading-Bot - Szenario Management")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # === OBEN: Daily Statistics Panel ===
        stats_panel = self.create_statistics_panel()
        layout.addWidget(stats_panel)

        # Haupt-Splitter (Links/Mitte/Rechts)
        main_splitter = QSplitter(Qt.Horizontal)

        # === LINKE SEITE: Verfügbare Szenarien ===
        left_widget = self.create_scenarios_panel()
        main_splitter.addWidget(left_widget)

        # === MITTE: Aktive & Wartende Levels ===
        middle_widget = self.create_levels_panel()
        main_splitter.addWidget(middle_widget)

        # === RECHTE SEITE: Log Terminal ===
        right_widget = self.create_log_terminal()
        main_splitter.addWidget(right_widget)

        # Splitter-Proportionen (30% links, 40% mitte, 30% rechts)
        # Benutzer kann diese mit der Maus anpassen
        main_splitter.setSizes([300, 400, 300])

        layout.addWidget(main_splitter)

        # Status Bar
        self.status_label = QLabel("Bereit - Keine Szenarien geladen")
        self.status_label.setStyleSheet("padding: 5px; background: #f0f0f0;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def create_scenarios_panel(self):
        """Linkes Panel: Verfügbare Szenarien (hierarchisch)"""
        widget = QWidget()
        layout = QVBoxLayout()

        # GroupBox für Szenarien
        group = QGroupBox("Verfügbare Szenarien")
        group_layout = QVBoxLayout()

        # TreeWidget für hierarchische Darstellung
        self.scenarios_tree = QTreeWidget()
        self.scenarios_tree.setHeaderLabels([
            "Name / Level", "Typ", "Symbol", "Aktien", "Einstieg %", "Ausstieg %"
        ])

        # Mehrfachauswahl aktivieren (Ctrl+Klick für einzelne, Shift+Klick für Bereiche)
        self.scenarios_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)

        # Header-Breiten anpassen
        header = self.scenarios_tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, 6):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        group_layout.addWidget(self.scenarios_tree)

        # Buttons für Szenario-Management
        btn_layout = QHBoxLayout()

        self.activate_btn = QPushButton("Aktivieren")
        self.activate_btn.setToolTip("Ausgewähltes Szenario/Level zum Trading aktivieren")
        self.activate_btn.clicked.connect(self.activate_selected)
        btn_layout.addWidget(self.activate_btn)

        self.remove_btn = QPushButton("Entfernen")
        self.remove_btn.setToolTip("Ausgewähltes Szenario entfernen")
        self.remove_btn.clicked.connect(self.remove_selected)
        btn_layout.addWidget(self.remove_btn)

        group_layout.addLayout(btn_layout)

        # Buttons für Speicherung
        storage_layout = QHBoxLayout()

        self.save_btn = QPushButton("💾 Speichern")
        self.save_btn.setToolTip("Szenarien manuell speichern")
        self.save_btn.clicked.connect(self.save_scenarios_to_file)
        storage_layout.addWidget(self.save_btn)

        self.reload_btn = QPushButton("🔄 Neu laden")
        self.reload_btn.setToolTip("Szenarien aus Datei neu laden")
        self.reload_btn.clicked.connect(self.load_scenarios_from_file)
        storage_layout.addWidget(self.reload_btn)

        self.clear_btn = QPushButton("🗑️ Löschen")
        self.clear_btn.setToolTip("Gespeicherte Szenarien-Datei löschen")
        self.clear_btn.clicked.connect(self.clear_saved_scenarios)
        storage_layout.addWidget(self.clear_btn)

        group_layout.addLayout(storage_layout)

        # Info Label
        self.scenario_info_label = QLabel("0 Szenarien verfügbar")
        group_layout.addWidget(self.scenario_info_label)

        group.setLayout(group_layout)
        layout.addWidget(group)

        widget.setLayout(layout)
        return widget

    def create_levels_panel(self):
        """Rechtes Panel: Aktive und Wartende Levels"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Vertikaler Splitter für oben/unten
        splitter = QSplitter(Qt.Vertical)

        # === OBEN: Aktive Levels ===
        active_group = QGroupBox("Aktive Levels (Offene Positionen)")
        active_layout = QVBoxLayout()

        self.active_table = QTableWidget()
        self.active_table.setColumnCount(10)
        self.active_table.setHorizontalHeaderLabels([
            "Symbol", "Typ", "Einstiegspreis", "Zielpreis", "Akt. Preis",
            "Akt. P&L", "Diff. zum Ziel", "Dauer", "Status", "Szenario"
        ])
        self.active_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.active_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        # Header anpassen
        active_header = self.active_table.horizontalHeader()
        active_header.setStretchLastSection(True)
        for i in range(9):
            active_header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        active_layout.addWidget(self.active_table)

        # Kontroll-Buttons für aktive Levels
        active_btn_layout = QHBoxLayout()
        self.pause_active_btn = QPushButton("⏸️ Pausieren")
        self.pause_active_btn.setToolTip("Ausgewählte aktive Levels pausieren/fortsetzen")
        self.pause_active_btn.clicked.connect(self.toggle_pause_active)
        active_btn_layout.addWidget(self.pause_active_btn)

        self.stop_active_btn = QPushButton("⏹️ Stoppen")
        self.stop_active_btn.setToolTip("Ausgewählte aktive Levels sofort schliessen")
        self.stop_active_btn.clicked.connect(self.stop_active_levels)
        active_btn_layout.addWidget(self.stop_active_btn)

        active_layout.addLayout(active_btn_layout)

        self.active_count_label = QLabel("0 aktive Positionen")
        active_layout.addWidget(self.active_count_label)

        active_group.setLayout(active_layout)
        splitter.addWidget(active_group)

        # === MITTE: Pending Orders (Platziert, warten auf Ausführung) ===
        pending_group = QGroupBox("Pending Orders (Platziert, warten auf Ausführung)")
        pending_layout = QVBoxLayout()

        self.pending_table = QTableWidget()
        self.pending_table.setColumnCount(9)
        self.pending_table.setHorizontalHeaderLabels([
            "Symbol", "Typ", "Aktion", "Shares", "Preis", "Order ID", "Status", "Zeit", "Level"
        ])
        self.pending_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pending_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        # Header formatting
        pending_header = self.pending_table.horizontalHeader()
        pending_header.setStretchLastSection(True)
        for i in range(8):
            pending_header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        pending_layout.addWidget(self.pending_table)

        self.pending_count_label = QLabel("0 pending orders")
        pending_layout.addWidget(self.pending_count_label)

        pending_group.setLayout(pending_layout)
        splitter.addWidget(pending_group)

        # === UNTEN: Wartende Levels ===
        waiting_group = QGroupBox("Wartende Levels (Warten auf Einstieg)")
        waiting_layout = QVBoxLayout()

        self.waiting_table = QTableWidget()
        self.waiting_table.setColumnCount(8)
        self.waiting_table.setHorizontalHeaderLabels([
            "Symbol", "Typ", "Zielpreis (Einstieg)", "Ausstiegspreis", "Akt. Preis",
            "Diff. zum Einstieg", "Status", "Szenario"
        ])
        self.waiting_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.waiting_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)

        # Header anpassen
        waiting_header = self.waiting_table.horizontalHeader()
        waiting_header.setStretchLastSection(True)
        for i in range(7):
            waiting_header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

        waiting_layout.addWidget(self.waiting_table)

        # Kontroll-Buttons für wartende Levels
        waiting_btn_layout = QHBoxLayout()
        self.pause_waiting_btn = QPushButton("⏸️ Pausieren")
        self.pause_waiting_btn.setToolTip("Ausgewählte wartende Levels pausieren/fortsetzen")
        self.pause_waiting_btn.clicked.connect(self.toggle_pause_waiting)
        waiting_btn_layout.addWidget(self.pause_waiting_btn)

        self.remove_waiting_btn = QPushButton("🗑️ Entfernen")
        self.remove_waiting_btn.setToolTip("Ausgewählte wartende Levels entfernen")
        self.remove_waiting_btn.clicked.connect(self.remove_waiting_levels)
        waiting_btn_layout.addWidget(self.remove_waiting_btn)

        waiting_layout.addLayout(waiting_btn_layout)

        self.waiting_count_label = QLabel("0 wartende Levels")
        waiting_layout.addWidget(self.waiting_count_label)

        waiting_group.setLayout(waiting_layout)
        splitter.addWidget(waiting_group)

        # Splitter-Proportionen (active / pending / waiting)
        splitter.setSizes([300, 200, 300])

        layout.addWidget(splitter)
        widget.setLayout(layout)
        return widget

    def create_statistics_panel(self):
        """Oberes Panel: Daily Statistics - KOMPAKT"""
        group = QGroupBox("Tagesstatistik")
        group.setMaximumHeight(180)  # Begrenzte Höhe!

        # Grid Layout für kompakte 2-spaltige Darstellung
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(5)
        grid.setContentsMargins(5, 5, 5, 5)

        # Kompakter Style
        label_style = "font-size: 9px; padding: 1px;"
        value_style = "font-size: 11px; font-weight: bold; padding: 1px;"

        row = 0

        # P&L
        grid.addWidget(QLabel("P&L:"), row, 0)
        self.total_pnl_label = QLabel("$0.00")
        self.total_pnl_label.setStyleSheet(value_style + " color: #000;")
        grid.addWidget(self.total_pnl_label, row, 1)

        # Trades
        grid.addWidget(QLabel("Trades:"), row, 2)
        self.total_trades_label = QLabel("0")
        self.total_trades_label.setStyleSheet(value_style)
        grid.addWidget(self.total_trades_label, row, 3)

        row += 1

        # Realisiert
        grid.addWidget(QLabel("Realisiert:"), row, 0)
        self.realized_pnl_label = QLabel("$0.00")
        self.realized_pnl_label.setStyleSheet(label_style)
        grid.addWidget(self.realized_pnl_label, row, 1)

        # Win/Loss
        grid.addWidget(QLabel("W/L:"), row, 2)
        self.win_lose_label = QLabel("0 / 0")
        self.win_lose_label.setStyleSheet(label_style)
        grid.addWidget(self.win_lose_label, row, 3)

        row += 1

        # Unrealisiert
        grid.addWidget(QLabel("Unrealisiert:"), row, 0)
        self.unrealized_pnl_label = QLabel("$0.00")
        self.unrealized_pnl_label.setStyleSheet(label_style)
        grid.addWidget(self.unrealized_pnl_label, row, 1)

        # Win Rate
        grid.addWidget(QLabel("Win-Rate:"), row, 2)
        self.win_rate_label = QLabel("0%")
        self.win_rate_label.setStyleSheet(label_style)
        grid.addWidget(self.win_rate_label, row, 3)

        row += 1

        # Kommissionen
        grid.addWidget(QLabel("Komm.:"), row, 0)
        self.commissions_label = QLabel("$0.00")
        self.commissions_label.setStyleSheet(label_style + " color: #c00;")
        grid.addWidget(self.commissions_label, row, 1)

        # Volumen
        grid.addWidget(QLabel("Volumen:"), row, 2)
        self.volume_label = QLabel("$0.00")
        self.volume_label.setStyleSheet(label_style)
        grid.addWidget(self.volume_label, row, 3)

        row += 1

        # Netto P&L
        grid.addWidget(QLabel("Netto:"), row, 0)
        self.net_pnl_label = QLabel("$0.00")
        self.net_pnl_label.setStyleSheet(label_style)
        grid.addWidget(self.net_pnl_label, row, 1)

        # Shares
        grid.addWidget(QLabel("Aktien:"), row, 2)
        self.shares_label = QLabel("0")
        self.shares_label.setStyleSheet(label_style)
        grid.addWidget(self.shares_label, row, 3)

        # Vertikale Linie zwischen den Spalten
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        grid.addWidget(line, 0, 4, row + 1, 1)

        # IBKR Connection Section (kompakt rechts)
        ibkr_col = 5

        grid.addWidget(QLabel("IBKR:"), 0, ibkr_col)
        self.ibkr_status_label = QLabel("Nicht verbunden")
        self.ibkr_status_label.setStyleSheet("font-size: 9px; font-weight: bold; color: #c00;")
        grid.addWidget(self.ibkr_status_label, 0, ibkr_col + 1)

        self.live_trading_cb = QCheckBox("Live Trading")
        self.live_trading_cb.setEnabled(False)
        self.live_trading_cb.setStyleSheet("font-size: 9px;")
        self.live_trading_cb.toggled.connect(self.toggle_live_trading)
        grid.addWidget(self.live_trading_cb, 1, ibkr_col, 1, 2)

        # Order Type Selection (kompakt)
        self.order_type_group = QButtonGroup(self)

        order_layout = QHBoxLayout()
        self.market_order_rb = QRadioButton("Market")
        self.market_order_rb.setChecked(True)
        self.market_order_rb.setStyleSheet("font-size: 9px;")
        self.order_type_group.addButton(self.market_order_rb, 1)
        order_layout.addWidget(self.market_order_rb)

        self.limit_order_rb = QRadioButton("Limit")
        self.limit_order_rb.setStyleSheet("font-size: 9px;")
        self.order_type_group.addButton(self.limit_order_rb, 2)
        order_layout.addWidget(self.limit_order_rb)

        grid.addLayout(order_layout, 2, ibkr_col, 1, 2)

        # Trading Hours (kompakt)
        self.hours_start_spin = QSpinBox()
        self.hours_start_spin.setRange(0, 23)
        self.hours_start_spin.setValue(9)
        self.hours_start_spin.setPrefix("Start: ")
        self.hours_start_spin.setSuffix(":30")
        self.hours_start_spin.setMaximumWidth(100)
        self.hours_start_spin.setStyleSheet("font-size: 9px;")
        self.hours_start_spin.valueChanged.connect(self._update_trading_hours)
        grid.addWidget(self.hours_start_spin, 3, ibkr_col)

        self.hours_end_spin = QSpinBox()
        self.hours_end_spin.setRange(0, 23)
        self.hours_end_spin.setValue(16)
        self.hours_end_spin.setPrefix("End: ")
        self.hours_end_spin.setSuffix(":00")
        self.hours_end_spin.setMaximumWidth(100)
        self.hours_end_spin.setStyleSheet("font-size: 9px;")
        self.hours_end_spin.valueChanged.connect(self._update_trading_hours)
        grid.addWidget(self.hours_end_spin, 3, ibkr_col + 1)

        # NY Time Display
        self.ny_time_label = QLabel("NY: --:--:--")
        self.ny_time_label.setStyleSheet("font-size: 9px; color: #666;")
        grid.addWidget(self.ny_time_label, 4, ibkr_col, 1, 2)

        # Enforce Hours Checkbox
        self.enforce_hours_cb = QCheckBox("Nur Handelsz.")
        self.enforce_hours_cb.setChecked(True)
        self.enforce_hours_cb.setStyleSheet("font-size: 9px;")
        self.enforce_hours_cb.setToolTip("Trading nur während Handelszeiten (9:30-16:00 NY)")
        self.enforce_hours_cb.toggled.connect(self._toggle_enforce_hours)
        grid.addWidget(self.enforce_hours_cb, 5, ibkr_col, 1, 2)

        # Market Data Refresh Rate (kompakt)
        self.refresh_rate_spin = QDoubleSpinBox()
        self.refresh_rate_spin.setRange(0.5, 10.0)
        self.refresh_rate_spin.setSingleStep(0.5)
        self.refresh_rate_spin.setValue(2.0)
        self.refresh_rate_spin.setSuffix(" s")
        self.refresh_rate_spin.setPrefix("Refresh: ")
        self.refresh_rate_spin.setMaximumWidth(120)
        self.refresh_rate_spin.setStyleSheet("font-size: 9px;")
        self.refresh_rate_spin.setToolTip("Aktualisierungsrate für Marktdaten")
        self.refresh_rate_spin.valueChanged.connect(self._on_refresh_rate_changed)
        grid.addWidget(self.refresh_rate_spin, 6, ibkr_col, 1, 2)

        # Vertikale Linie vor Reset Button
        line2 = QFrame()
        line2.setFrameShape(QFrame.VLine)
        line2.setFrameShadow(QFrame.Sunken)
        grid.addWidget(line2, 0, ibkr_col + 2, row + 1, 1)

        # Reset Button (kompakt rechts)
        reset_btn = QPushButton("🔄")
        reset_btn.setMaximumWidth(40)
        reset_btn.setToolTip("Tagesstatistik zurücksetzen")
        reset_btn.clicked.connect(self.reset_daily_stats)
        grid.addWidget(reset_btn, 0, ibkr_col + 3, row + 1, 1)

        group.setLayout(grid)
        return group

    def create_log_terminal(self):
        """Rechtes Panel: Log Terminal"""
        group = QGroupBox("Log Terminal")
        layout = QVBoxLayout()

        # Log Text Area
        self.log_terminal = QTextEdit()
        self.log_terminal.setReadOnly(True)
        self.log_terminal.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #333;
            }
        """)
        self.log_terminal.setMinimumWidth(200)
        layout.addWidget(self.log_terminal)

        # Control Buttons
        btn_layout = QHBoxLayout()

        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.clicked.connect(self.clear_log_terminal)
        btn_layout.addWidget(clear_btn)

        export_btn = QPushButton("💾 Export")
        export_btn.clicked.connect(self.export_log)
        btn_layout.addWidget(export_btn)

        layout.addLayout(btn_layout)

        group.setLayout(layout)
        return group

    def log_message(self, message: str, level: str = "INFO"):
        """Füge Nachricht zum Log Terminal hinzu"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Farbe basierend auf Level
        colors = {
            "INFO": "#00ff00",      # Grün
            "TRADE": "#00ffff",     # Cyan
            "WARNING": "#ffff00",   # Gelb
            "ERROR": "#ff0000",     # Rot
            "SUCCESS": "#00ff88"    # Hellgrün
        }
        color = colors.get(level, "#ffffff")

        # Format: [HH:MM:SS] [LEVEL] Message
        formatted_msg = f'<span style="color: #888;">[{timestamp}]</span> ' \
                       f'<span style="color: {color};">[{level}]</span> ' \
                       f'<span style="color: #ddd;">{message}</span><br>'

        # Speichere für Export
        self.log_messages.append({
            'timestamp': timestamp,
            'level': level,
            'message': message
        })

        # Füge zum Terminal hinzu
        if hasattr(self, 'log_terminal'):
            self.log_terminal.insertHtml(formatted_msg)
            # Auto-scroll to bottom
            cursor = self.log_terminal.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_terminal.setTextCursor(cursor)

    def clear_log_terminal(self):
        """Lösche Log Terminal"""
        self.log_terminal.clear()
        self.log_messages.clear()
        self.log_message("Log Terminal geleert", "INFO")

    def export_log(self):
        """Exportiere Log in Datei"""
        if not self.log_messages:
            QMessageBox.information(self, "Info", "Keine Log-Nachrichten zum Exportieren.")
            return

        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.logs_dir / f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

            with open(log_file, 'w', encoding='utf-8') as f:
                for entry in self.log_messages:
                    f.write(f"[{entry['timestamp']}] [{entry['level']}] {entry['message']}\n")

            self.log_message(f"Log exportiert: {log_file.name}", "SUCCESS")
            QMessageBox.information(self, "Export", f"Log gespeichert:\n{log_file}")
        except Exception as e:
            self.log_message(f"Export fehlgeschlagen: {e}", "ERROR")

    def reset_daily_stats(self):
        """Setze Tagesstatistik zurück"""
        reply = QMessageBox.question(
            self,
            "Statistik zurücksetzen",
            "Tagesstatistik wirklich zurücksetzen?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.daily_stats = {
                'date': date.today().isoformat(),
                'total_pnl': 0.0,
                'realized_pnl': 0.0,
                'unrealized_pnl': 0.0,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_commissions': 0.0,
                'total_volume': 0.0,
                'total_shares': 0
            }
            self.update_statistics_display()
            self.log_message("Tagesstatistik zurückgesetzt", "INFO")

    def update_statistics_display(self):
        """Aktualisiere Statistics Panel"""
        stats = self.daily_stats

        # P&L mit Farbe
        total_pnl = stats['total_pnl']
        if total_pnl >= 0:
            self.total_pnl_label.setText(f"${total_pnl:,.2f}")
            self.total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #0a0;")
        else:
            self.total_pnl_label.setText(f"-${abs(total_pnl):,.2f}")
            self.total_pnl_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #c00;")

        self.realized_pnl_label.setText(f"Realisiert: ${stats['realized_pnl']:,.2f}")
        self.unrealized_pnl_label.setText(f"Unrealisiert: ${stats['unrealized_pnl']:,.2f}")

        # Trades
        self.total_trades_label.setText(str(stats['total_trades']))
        self.win_lose_label.setText(f"W: {stats['winning_trades']} / L: {stats['losing_trades']}")

        if stats['total_trades'] > 0:
            win_rate = (stats['winning_trades'] / stats['total_trades']) * 100
            self.win_rate_label.setText(f"Win-Rate: {win_rate:.1f}%")
        else:
            self.win_rate_label.setText("Win-Rate: 0%")

        # Commissions
        self.commissions_label.setText(f"${stats['total_commissions']:,.2f}")
        net_pnl = stats['total_pnl'] - stats['total_commissions']
        self.net_pnl_label.setText(f"Netto P&L: ${net_pnl:,.2f}")

        # Volume
        self.volume_label.setText(f"${stats['total_volume']:,.2f}")
        self.shares_label.setText(f"{stats['total_shares']:,} Aktien")

    def _update_dashboard(self, market_data: Dict[str, dict]):
        """Update Dashboard panels with current data"""
        try:
            # Find MainWindow
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'update_dashboard_levels'):
                main_window = main_window.parent()

            if not main_window:
                return

            # 1. Update Active Levels with current prices
            levels_with_prices = []
            for level in self.active_levels:
                level_copy = level.copy()
                symbol = level.get('symbol', '')
                if symbol in market_data:
                    # Für Anzeige: last price verwenden
                    level_copy['current_price'] = market_data[symbol]['last']
                else:
                    level_copy['current_price'] = level.get('entry_price', 0)
                levels_with_prices.append(level_copy)

            main_window.update_dashboard_levels(levels_with_prices)

            # 2. Update Stock Information for symbols with waiting/active levels
            symbols = set()

            # Get symbols from waiting levels
            for level in self.waiting_levels:
                symbol = level.get('symbol', '')
                if symbol:
                    symbols.add(symbol)

            # Get symbols from active levels
            for level in self.active_levels:
                symbol = level.get('symbol', '')
                if symbol:
                    symbols.add(symbol)

            # Create stock data dict
            stock_data = {}
            for symbol in symbols:
                if symbol in market_data:
                    prices = market_data[symbol]
                    stock_data[symbol] = {
                        'last': prices['last'],
                        'bid': prices['bid'],
                        'ask': prices['ask'],
                        'change': 0,
                        'change_pct': 0,
                        'volume': 0,
                        'high': prices['last'],
                        'low': prices['last']
                    }

            if stock_data:
                main_window.update_dashboard_stocks(stock_data)

        except Exception as e:
            # Silently ignore dashboard update errors
            pass

    def record_trade(self, trade_data: dict):
        """Erfasse einen abgeschlossenen Trade"""
        pnl = trade_data.get('pnl', 0.0)
        shares = trade_data.get('shares', 0)
        price = trade_data.get('price', 0.0)
        commission = trade_data.get('commission', 0.0)

        # Update Stats
        self.daily_stats['total_trades'] += 1
        self.daily_stats['realized_pnl'] += pnl
        self.daily_stats['total_pnl'] = self.daily_stats['realized_pnl'] + self.daily_stats['unrealized_pnl']
        self.daily_stats['total_commissions'] += commission
        self.daily_stats['total_volume'] += shares * price
        self.daily_stats['total_shares'] += shares

        if pnl >= 0:
            self.daily_stats['winning_trades'] += 1
        else:
            self.daily_stats['losing_trades'] += 1

        # Log
        symbol = trade_data.get('symbol', 'N/A')
        trade_type = trade_data.get('type', 'N/A')
        self.log_message(
            f"TRADE: {symbol} {trade_type} {shares}x @ ${price:.2f} | P&L: ${pnl:.2f} | Komm: ${commission:.2f}",
            "TRADE"
        )

        # Persistente Log-Datei schreiben
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'type': trade_type,
            'shares': shares,
            'entry_price': trade_data.get('entry_price', 0.0),
            'exit_price': price,
            'pnl': pnl,
            'commission': commission,
            'scenario': trade_data.get('scenario', 'N/A'),
            'level': trade_data.get('level', 0)
        }
        self._write_trade_to_logs(log_entry)

        # Excel Trading Log schreiben
        if hasattr(self, 'trading_log_exporter'):
            self.trading_log_exporter.add_trade(trade_data)

        # Update Display
        self.update_statistics_display()

    def import_scenarios(self, scenarios_list: list):
        """
        Importiere mehrere Szenarien aus dem Backtesting

        Args:
            scenarios_list: Liste von Tupeln (scenario_name, scenario_config, backtest_result)
        """
        imported_count = 0
        for scenario_data in scenarios_list:
            if len(scenario_data) >= 2:
                scenario_name = scenario_data[0]
                scenario_config = scenario_data[1]
                backtest_result = scenario_data[2] if len(scenario_data) > 2 else None

                self.import_scenario(scenario_name, scenario_config, backtest_result)
                imported_count += 1

        if imported_count > 0:
            # Auto-Save nach Import
            self.save_scenarios_to_file()

        self.update_status(f"{imported_count} Szenario(s) importiert und gespeichert")

    def import_scenario(self, scenario_name: str, scenario_config: dict, backtest_result: dict = None):
        """
        Importiere ein Szenario aus dem Backtesting

        Args:
            scenario_name: Name des Szenarios (z.B. "L_100_0.5_0.7_5")
            scenario_config: Konfiguration mit type, shares, step, exit, levels
            backtest_result: Optional - Backtest-Ergebnisse
        """
        # Speichere Szenario
        self.available_scenarios[scenario_name] = {
            'config': scenario_config,
            'result': backtest_result,
            'imported_at': datetime.now().isoformat(),
            'levels': self._generate_levels(scenario_config, backtest_result)
        }

        # Update Tree
        self._update_scenarios_tree()
        self.update_status(f"Szenario '{scenario_name}' importiert")

    def _generate_levels(self, config: dict, result: dict = None) -> List[dict]:
        """
        Generiere Level-Details für ein Szenario

        Returns:
            Liste von Level-Dictionaries mit entry_pct, exit_pct, etc.
        """
        levels = []
        max_levels = config.get('levels', 5)
        step_pct = config.get('step', 0.5)
        exit_pct = config.get('exit', 0.7)
        shares = config.get('shares', 100)
        side = config.get('type', 'LONG')

        # Symbol aus Result oder default
        symbol = result.get('symbol', 'N/A') if result else 'N/A'

        for i in range(max_levels):
            level_num = i + 1

            if side == 'LONG':
                # Long: Kauf bei -step%, Verkauf bei +exit% vom Entry
                entry_pct = -(step_pct * level_num)  # z.B. -0.5%, -1.0%, -1.5%
                exit_pct_level = exit_pct  # z.B. +0.7%
            else:  # SHORT
                # Short: Verkauf bei +step%, Rückkauf bei -exit% vom Entry
                entry_pct = step_pct * level_num  # z.B. +0.5%, +1.0%, +1.5%
                exit_pct_level = -exit_pct  # z.B. -0.7%

            levels.append({
                'level_num': level_num,
                'type': side,
                'symbol': symbol,
                'shares': shares,
                'entry_pct': entry_pct,
                'exit_pct': exit_pct_level,
                'status': 'waiting'  # waiting, active, completed
            })

        return levels

    def _update_scenarios_tree(self):
        """Aktualisiere den TreeWidget mit allen Szenarien"""
        self.scenarios_tree.clear()

        for scenario_name, scenario_data in self.available_scenarios.items():
            config = scenario_data['config']
            levels = scenario_data['levels']

            # Hauptknoten für Szenario
            scenario_item = QTreeWidgetItem([
                scenario_name,
                config.get('type', 'N/A'),
                levels[0]['symbol'] if levels else 'N/A',
                str(config.get('shares', 0)),
                f"{config.get('step', 0)}%",
                f"{config.get('exit', 0)}%"
            ])

            # Farbe basierend auf Typ
            if config.get('type') == 'LONG':
                scenario_item.setForeground(0, QColor(0, 128, 0))  # Grün
            else:
                scenario_item.setForeground(0, QColor(128, 0, 0))  # Rot

            # Font fett für Hauptknoten
            font = scenario_item.font(0)
            font.setBold(True)
            scenario_item.setFont(0, font)

            # Kind-Knoten für jeden Level
            for level in levels:
                level_item = QTreeWidgetItem([
                    f"  Level {level['level_num']}",
                    level['type'],
                    level['symbol'],
                    str(level['shares']),
                    f"{level['entry_pct']:.2f}%",
                    f"{level['exit_pct']:.2f}%"
                ])
                scenario_item.addChild(level_item)

            self.scenarios_tree.addTopLevelItem(scenario_item)

        # Alle expandieren
        self.scenarios_tree.expandAll()

        # Update Counter
        self.scenario_info_label.setText(f"{len(self.available_scenarios)} Szenarien verfügbar")

    def activate_selected(self):
        """Aktiviere ausgewählte Szenarien oder Levels"""
        selected_items = self.scenarios_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein oder mehrere Szenarien/Levels aus.")
            return

        # Sammle alle ausgewählten Levels
        levels_to_activate = []

        for item in selected_items:
            if item.parent() is None:
                # Top-Level Item = Ganzes Szenario
                scenario_name = item.text(0)
                if scenario_name in self.available_scenarios:
                    scenario_data = self.available_scenarios[scenario_name]
                    for level in scenario_data['levels']:
                        # Füge Szenario-Name hinzu für Referenz
                        level_copy = level.copy()
                        level_copy['scenario_name'] = scenario_name
                        levels_to_activate.append(level_copy)
            else:
                # Kind-Item = Einzelnes Level
                parent = item.parent()
                scenario_name = parent.text(0)
                level_text = item.text(0).strip()  # "  Level X"

                # Extrahiere Level-Nummer
                try:
                    level_num = int(level_text.replace("Level", "").strip())
                except ValueError:
                    continue

                if scenario_name in self.available_scenarios:
                    scenario_data = self.available_scenarios[scenario_name]
                    for level in scenario_data['levels']:
                        if level['level_num'] == level_num:
                            level_copy = level.copy()
                            level_copy['scenario_name'] = scenario_name
                            levels_to_activate.append(level_copy)
                            break

        if not levels_to_activate:
            QMessageBox.warning(self, "Warnung", "Keine gültigen Levels ausgewählt.")
            return

        # Entferne Duplikate (falls Szenario UND dessen Level ausgewählt)
        unique_levels = []
        seen = set()
        for level in levels_to_activate:
            key = (level['scenario_name'], level['level_num'])
            if key not in seen:
                seen.add(key)
                unique_levels.append(level)

        # Zeige Aktivierungs-Dialog
        dialog = ActivationDialog(unique_levels, self)
        if dialog.exec() == QDialog.Accepted:
            config = dialog.get_configuration()
            self._activate_levels(unique_levels, config)

    def _activate_levels(self, levels: List[dict], config: dict):
        """Aktiviere Levels mit der gegebenen Konfiguration"""
        if config['use_market_price']:
            # Für Market Price: Placeholder, wird später durch echten Preis ersetzt
            base_price = None

            # SICHERHEITS-CHECK: Stelle sicher, dass fixed_price auch None ist
            if config.get('fixed_price') is not None:
                self.log_message(
                    f"WARNUNG: use_market_price=True, aber fixed_price={config['fixed_price']} gesetzt. Wird ignoriert.",
                    "WARNING"
                )

            QMessageBox.information(
                self,
                "Marktpreis",
                "Levels werden mit aktuellem Marktpreis aktiviert.\n"
                "Der Preis wird bei der nächsten Marktdaten-Aktualisierung gesetzt."
            )
        else:
            base_price = config['fixed_price']
            # SICHERHEITS-CHECK: Stelle sicher, dass ein fixer Preis gesetzt ist
            if base_price is None:
                QMessageBox.critical(
                    self,
                    "Fehler",
                    "Fixpreis-Modus gewählt, aber kein Preis angegeben!"
                )
                return

        # Füge Levels zur Waiting-Tabelle hinzu
        activated_count = 0
        symbols_to_subscribe = set()
        for level in levels:
            self._add_to_waiting_table(level, config, base_price)
            activated_count += 1
            symbols_to_subscribe.add(config['symbol'])

        # Sortiere Tabelle nach Symbol und Einstiegspreis
        self._sort_waiting_table()

        # NEU: Subscribiere Market Data beim IBKRService
        if self._ibkr_service and self._service_connected and symbols_to_subscribe:
            self._ibkr_service.subscribe_market_data(list(symbols_to_subscribe))
            self.log_message(f"Market Data subscribed: {', '.join(symbols_to_subscribe)}", "INFO")

        self.update_status(f"{activated_count} Level(s) aktiviert und warten auf Einstieg")

    def _add_to_waiting_table(self, level: dict, config: dict, base_price: float = None):
        """Füge ein Level zur Waiting-Tabelle hinzu"""

        # DEBUG-LOGGING: Zeige was übergeben wurde
        use_market = config.get('use_market_price', False)
        fixed = config.get('fixed_price', 'N/A')
        self.log_message(
            f"DEBUG: _add_to_waiting_table - Level {level['level_num']}, "
            f"use_market_price={use_market}, fixed_price={fixed}, base_price={base_price}",
            "DEBUG"
        )

        # SICHERHEITS-CHECK: Wenn base_price None sein sollte, stelle sicher dass es auch None ist
        if use_market and base_price is not None:
            self.log_message(
                f"FEHLER: base_price sollte None sein (use_market_price=True), ist aber {base_price}!",
                "ERROR"
            )
            # Korrigiere den Fehler
            base_price = None

        # Berechne absolute Preise wenn base_price vorhanden
        if base_price is not None:
            entry_price = base_price * (1 + level['entry_pct'] / 100)
            exit_price = entry_price * (1 + level['exit_pct'] / 100)
            diff_to_entry = "N/A"  # Wird später mit Live-Preis berechnet
        else:
            entry_price = None
            exit_price = None
            diff_to_entry = "Warte auf Preis"

        # Speichere Waiting Level Daten
        waiting_level_data = {
            'scenario_name': level.get('scenario_name', 'N/A'),
            'level_num': level['level_num'],
            'symbol': config['symbol'],
            'type': level['type'],
            'shares': config['shares'],
            'entry_pct': level['entry_pct'],
            'exit_pct': level['exit_pct'],
            'base_price': base_price,  # Garantiert None wenn use_market_price=True
            'entry_price': entry_price,
            'exit_price': exit_price,
            'activated_at': datetime.now().isoformat(),
            'status': 'waiting'  # waiting, paused
        }
        # WICHTIG: Speichere original_level für Recycling bei Cancel!
        waiting_level_data['original_level'] = waiting_level_data.copy()
        self.waiting_levels.append(waiting_level_data)

        # Füge Zeile zur Tabelle hinzu
        row = self.waiting_table.rowCount()
        self.waiting_table.insertRow(row)

        # Symbol
        self.waiting_table.setItem(row, 0, QTableWidgetItem(config['symbol']))

        # Typ (LONG/SHORT)
        type_item = QTableWidgetItem(level['type'])
        if level['type'] == 'LONG':
            type_item.setForeground(QColor(0, 128, 0))
        else:
            type_item.setForeground(QColor(128, 0, 0))
        self.waiting_table.setItem(row, 1, type_item)

        # Zielpreis (Einstieg)
        if entry_price is not None:
            entry_text = f"${entry_price:.2f} ({level['entry_pct']:+.2f}%)"
        else:
            entry_text = f"({level['entry_pct']:+.2f}%)"
        self.waiting_table.setItem(row, 2, QTableWidgetItem(entry_text))

        # Ausstiegspreis (Spalte 3)
        if exit_price is not None:
            exit_text = f"${exit_price:.2f}"
        else:
            exit_text = f"({level['exit_pct']:+.2f}%)"
        self.waiting_table.setItem(row, 3, QTableWidgetItem(exit_text))

        # Aktueller Preis (Spalte 4) - Initial leer, wird durch Market Data aktualisiert
        self.waiting_table.setItem(row, 4, QTableWidgetItem("--"))

        # Differenz zum Einstieg (Spalte 5)
        self.waiting_table.setItem(row, 5, QTableWidgetItem(diff_to_entry))

        # Status (Spalte 6)
        status_item = QTableWidgetItem("Wartend")
        status_item.setForeground(QColor(0, 128, 0))  # Grün für aktiv wartend
        self.waiting_table.setItem(row, 6, status_item)

        # Szenario (Spalte 7)
        scenario_text = f"{level.get('scenario_name', 'N/A')} L{level['level_num']}"
        self.waiting_table.setItem(row, 7, QTableWidgetItem(scenario_text))

        # Update Counter
        self.waiting_count_label.setText(f"{self.waiting_table.rowCount()} wartende Levels")

    def _update_waiting_table_prices(self, symbol: str = None):
        """
        Aktualisiere die Waiting Table mit berechneten Preisen und aktuellen Marktdaten

        Args:
            symbol: Optional - nur dieses Symbol aktualisieren, sonst alle
        """
        try:
            for row in range(self.waiting_table.rowCount()):
                if row >= len(self.waiting_levels):
                    continue

                level_data = self.waiting_levels[row]

                # Filter nach Symbol wenn angegeben
                if symbol and level_data['symbol'] != symbol:
                    continue

                # Update Entry Price (Spalte 2)
                entry_price = level_data.get('entry_price')
                entry_pct = level_data.get('entry_pct', 0)
                if entry_price is not None:
                    entry_text = f"${entry_price:.2f} ({entry_pct:+.2f}%)"
                else:
                    entry_text = f"({entry_pct:+.2f}%)"
                self.waiting_table.item(row, 2).setText(entry_text)

                # Update Exit Price (Spalte 3)
                exit_price = level_data.get('exit_price')
                exit_pct = level_data.get('exit_pct', 0)
                if exit_price is not None:
                    exit_text = f"${exit_price:.2f}"
                else:
                    exit_text = f"({exit_pct:+.2f}%)"
                self.waiting_table.item(row, 3).setText(exit_text)

                # Hole aktuellen Marktpreis wenn verfügbar
                current_market_price = None
                if hasattr(self, '_last_market_prices') and level_data['symbol'] in self._last_market_prices:
                    price_data = self._last_market_prices[level_data['symbol']]
                    # Handle both dict format (from IBKRService) and float format (legacy)
                    if isinstance(price_data, dict):
                        current_market_price = price_data.get('last', 0) or price_data.get('mid', 0)
                    else:
                        current_market_price = float(price_data) if price_data else None

                # Update Aktueller Preis (Spalte 4)
                price_item = self.waiting_table.item(row, 4)
                if price_item:
                    if current_market_price is not None and current_market_price > 0:
                        price_item.setText(f"${current_market_price:.2f}")
                    else:
                        price_item.setText("--")

                # Update Differenz zum Einstieg (Spalte 5)
                if entry_price is not None and current_market_price is not None:
                    diff = current_market_price - entry_price
                    diff_pct = (diff / entry_price) * 100
                    diff_text = f"${diff:+.2f} ({diff_pct:+.2f}%)"

                    # Färbe je nach Typ und Differenz
                    diff_item = self.waiting_table.item(row, 5)
                    if diff_item:
                        if level_data['type'] == 'LONG':
                            # LONG: Grün wenn unter Entry (günstiger), Rot wenn drüber
                            color = QColor(0, 128, 0) if diff < 0 else QColor(128, 0, 0)
                        else:  # SHORT
                            # SHORT: Grün wenn über Entry, Rot wenn drunter
                            color = QColor(0, 128, 0) if diff > 0 else QColor(128, 0, 0)
                        diff_item.setForeground(color)
                        diff_item.setText(diff_text)
                elif entry_price is not None:
                    diff_item = self.waiting_table.item(row, 5)
                    if diff_item:
                        diff_item.setText("Warte auf Marktdaten")
                else:
                    diff_item = self.waiting_table.item(row, 5)
                    if diff_item:
                        diff_item.setText("Warte auf Preis")

        except Exception as e:
            self.log_message(f"Fehler beim Aktualisieren der Waiting Table: {e}", "ERROR")
            print(f"ERROR _update_waiting_table_prices: {e}")
            import traceback
            traceback.print_exc()

    def _update_active_table_prices(self, symbol: str, market_data: dict):
        """
        Aktualisiere die Active Table mit aktuellen Marktdaten, P&L und Diff zum Ziel

        Args:
            symbol: Das Symbol das aktualisiert wurde
            market_data: Dict mit bid, ask, last Preisen
        """
        try:
            for row in range(self.active_table.rowCount()):
                if row >= len(self.active_levels):
                    continue

                level = self.active_levels[row]

                # Filter nach Symbol
                if level.get('symbol') != symbol:
                    continue

                level_type = level.get('type', 'LONG')
                entry_price = level.get('entry_fill_price') or level.get('entry_price', 0)
                exit_price = level.get('exit_price', 0)
                shares = level.get('shares', 100)

                # Bestimme korrekten Preis für P&L Berechnung
                # LONG: BID (was wir beim Verkauf bekommen würden)
                # SHORT: ASK (was wir beim Rückkauf zahlen würden)
                if level_type == 'LONG':
                    current_price = market_data.get('bid', 0) or market_data.get('last', 0)
                else:  # SHORT
                    current_price = market_data.get('ask', 0) or market_data.get('last', 0)

                if current_price <= 0:
                    continue

                # P&L berechnen
                if level_type == 'LONG':
                    pnl = (current_price - entry_price) * shares
                    diff_to_target = ((exit_price - current_price) / current_price) * 100 if current_price > 0 else 0
                else:  # SHORT
                    pnl = (entry_price - current_price) * shares
                    diff_to_target = ((current_price - exit_price) / current_price) * 100 if current_price > 0 else 0

                # Update Aktueller Preis (Spalte 4)
                price_item = self.active_table.item(row, 4)
                if price_item:
                    price_item.setText(f"${current_price:.2f}")

                # Update P&L (Spalte 5)
                pnl_item = self.active_table.item(row, 5)
                if pnl_item:
                    pnl_text = f"${pnl:+,.2f}"
                    pnl_item.setText(pnl_text)
                    if pnl >= 0:
                        pnl_item.setForeground(QColor(0, 128, 0))
                    else:
                        pnl_item.setForeground(QColor(200, 0, 0))

                # Update Diff zum Ziel (Spalte 6)
                diff_item = self.active_table.item(row, 6)
                if diff_item:
                    diff_item.setText(f"{diff_to_target:+.2f}%")

                # Update Dauer (Spalte 7)
                entry_time_str = level.get('entry_time', '')
                if entry_time_str:
                    try:
                        entry_time = datetime.fromisoformat(entry_time_str)
                        duration = datetime.now() - entry_time
                        minutes = int(duration.total_seconds() / 60)
                        if minutes < 60:
                            duration_text = f"{minutes}m"
                        else:
                            hours = minutes // 60
                            mins = minutes % 60
                            duration_text = f"{hours}h {mins}m"

                        duration_item = self.active_table.item(row, 7)
                        if duration_item:
                            duration_item.setText(duration_text)
                    except:
                        pass

        except Exception as e:
            print(f"ERROR _update_active_table_prices: {e}")
            import traceback
            traceback.print_exc()

    def toggle_pause_waiting(self):
        """Pausiere/Fortsetze ausgewählte wartende Levels"""
        selected_rows = set()
        for item in self.waiting_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein oder mehrere Levels aus.")
            return

        paused_count = 0
        resumed_count = 0

        for row in sorted(selected_rows):
            if row < len(self.waiting_levels):
                level_data = self.waiting_levels[row]
                status_item = self.waiting_table.item(row, 6)  # Status ist jetzt Spalte 6

                if level_data['status'] == 'waiting':
                    # Pausieren
                    level_data['status'] = 'paused'
                    status_item.setText("Pausiert")
                    status_item.setForeground(QColor(255, 165, 0))  # Orange
                    paused_count += 1
                else:
                    # Fortsetzen
                    level_data['status'] = 'waiting'
                    status_item.setText("Wartend")
                    status_item.setForeground(QColor(0, 128, 0))  # Grün
                    resumed_count += 1

        if paused_count > 0 and resumed_count > 0:
            self.update_status(f"{paused_count} Level(s) pausiert, {resumed_count} fortgesetzt")
        elif paused_count > 0:
            self.update_status(f"{paused_count} Level(s) pausiert")
        else:
            self.update_status(f"{resumed_count} Level(s) fortgesetzt")

    def remove_waiting_levels(self):
        """Entferne ausgewählte wartende Levels"""
        selected_rows = set()
        for item in self.waiting_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein oder mehrere Levels aus.")
            return

        reply = QMessageBox.question(
            self,
            "Levels entfernen",
            f"{len(selected_rows)} Level(s) wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # Von hinten nach vorne löschen um Index-Probleme zu vermeiden
            for row in sorted(selected_rows, reverse=True):
                if row < len(self.waiting_levels):
                    level = self.waiting_levels[row]

                    # Tracking entfernen damit Level bei Reaktivierung neu getriggert werden kann
                    scenario_name = level.get('scenario_name', 'unknown')
                    level_num = level.get('level_num', 0)
                    unique_level_id = f"{scenario_name}_L{level_num}"
                    self._orders_placed_for_levels.discard(unique_level_id)

                    del self.waiting_levels[row]
                    self.waiting_table.removeRow(row)

            self.waiting_count_label.setText(f"{self.waiting_table.rowCount()} wartende Levels")
            self.update_status(f"{len(selected_rows)} Level(s) entfernt")

    def toggle_pause_active(self):
        """Pausiere/Fortsetze ausgewählte aktive Levels"""
        selected_rows = set()
        for item in self.active_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein oder mehrere Levels aus.")
            return

        paused_count = 0
        resumed_count = 0

        for row in sorted(selected_rows):
            if row < len(self.active_levels):
                level_data = self.active_levels[row]
                status_item = self.active_table.item(row, 7)  # Status ist Spalte 7

                if level_data.get('status') == 'active':
                    # Pausieren - Verkauf wird nicht getriggert
                    level_data['status'] = 'paused'
                    status_item.setText("Pausiert")
                    status_item.setForeground(QColor(255, 165, 0))  # Orange
                    paused_count += 1
                else:
                    # Fortsetzen
                    level_data['status'] = 'active'
                    status_item.setText("Aktiv")
                    status_item.setForeground(QColor(0, 128, 0))  # Grün
                    resumed_count += 1

        if paused_count > 0 and resumed_count > 0:
            self.update_status(f"{paused_count} Position(en) pausiert, {resumed_count} fortgesetzt")
        elif paused_count > 0:
            self.update_status(f"{paused_count} Position(en) pausiert (kein Auto-Verkauf)")
        else:
            self.update_status(f"{resumed_count} Position(en) fortgesetzt")

    def stop_active_levels(self):
        """Stoppe ausgewählte aktive Levels (Market-Order zum Schliessen)"""
        selected_rows = set()
        for item in self.active_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein oder mehrere Positionen aus.")
            return

        reply = QMessageBox.question(
            self,
            "Positionen schliessen",
            f"{len(selected_rows)} Position(en) sofort schliessen?\n\n"
            "ACHTUNG: Dies wird Market-Orders senden!",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # TODO: Implementiere echtes Order-Sending
            # Für jetzt nur aus der Tabelle entfernen
            for row in sorted(selected_rows, reverse=True):
                if row < len(self.active_levels):
                    del self.active_levels[row]
                    self.active_table.removeRow(row)

            self.active_count_label.setText(f"{self.active_table.rowCount()} aktive Positionen")
            self.update_status(f"{len(selected_rows)} Position(en) geschlossen")

    def remove_selected(self):
        """Entferne ausgewähltes Szenario"""
        current = self.scenarios_tree.currentItem()
        if not current:
            QMessageBox.warning(self, "Warnung", "Bitte wähle ein Szenario aus.")
            return

        # Prüfe ob es ein Top-Level Item ist (Szenario)
        if current.parent() is None:
            scenario_name = current.text(0)

            reply = QMessageBox.question(
                self,
                "Szenario entfernen",
                f"Szenario '{scenario_name}' wirklich entfernen?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                if scenario_name in self.available_scenarios:
                    del self.available_scenarios[scenario_name]
                    self._update_scenarios_tree()
                    self.update_status(f"Szenario '{scenario_name}' entfernt")
        else:
            QMessageBox.information(self, "Info", "Einzelne Levels können nicht entfernt werden.")

    def update_status(self, message: str):
        """Update Status Label"""
        self.status_label.setText(message)

    def save_scenarios_to_file(self):
        """Speichere Szenarien in JSON-Datei"""
        try:
            # Erstelle Verzeichnis falls nicht vorhanden
            self.data_dir.mkdir(parents=True, exist_ok=True)

            # Konvertiere Szenarien in serialisierbares Format
            save_data = {
                'version': '1.0',
                'saved_at': datetime.now().isoformat(),
                'scenarios': self.available_scenarios
            }

            with open(self.scenarios_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)

            self.update_status(f"Szenarien gespeichert in {self.scenarios_file}")
        except Exception as e:
            QMessageBox.warning(
                self,
                "Speicherfehler",
                f"Szenarien konnten nicht gespeichert werden:\n{str(e)}"
            )

    def load_scenarios_from_file(self):
        """Lade Szenarien aus JSON-Datei"""
        if not self.scenarios_file.exists():
            self.update_status("Keine gespeicherten Szenarien gefunden")
            return

        try:
            with open(self.scenarios_file, 'r', encoding='utf-8') as f:
                save_data = json.load(f)

            # Lade Szenarien
            loaded_scenarios = save_data.get('scenarios', {})

            if loaded_scenarios:
                self.available_scenarios = loaded_scenarios
                self._update_scenarios_tree()

                saved_at = save_data.get('saved_at', 'unbekannt')
                self.update_status(f"{len(loaded_scenarios)} Szenario(s) geladen (gespeichert: {saved_at[:19]})")
            else:
                self.update_status("Keine Szenarien in Datei gefunden")

        except json.JSONDecodeError as e:
            reply = QMessageBox.warning(
                self,
                "Ladefehler",
                f"JSON-Datei ist beschädigt:\n{str(e)}\n\n"
                f"Möchten Sie die beschädigte Datei löschen und neu starten?\n"
                f"(Gespeicherte Szenarien gehen verloren)",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                try:
                    self.scenarios_file.unlink()
                    self.update_status("Beschädigte Datei gelöscht - neu starten möglich")
                    self.log_message("Beschädigte JSON-Datei gelöscht", "WARNING")
                except Exception as del_e:
                    self.log_message(f"Datei konnte nicht gelöscht werden: {del_e}", "ERROR")
        except Exception as e:
            QMessageBox.warning(
                self,
                "Ladefehler",
                f"Szenarien konnten nicht geladen werden:\n{str(e)}"
            )

    def clear_saved_scenarios(self):
        """Lösche gespeicherte Szenarien-Datei"""
        if self.scenarios_file.exists():
            reply = QMessageBox.question(
                self,
                "Gespeicherte Szenarien löschen",
                "Alle gespeicherten Szenarien wirklich löschen?\n"
                "Dies kann nicht rückgängig gemacht werden.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.scenarios_file.unlink()
                self.update_status("Gespeicherte Szenarien gelöscht")

    def get_scenario_count(self) -> int:
        """Gibt Anzahl der verfügbaren Szenarien zurück"""
        return len(self.available_scenarios)

    # ========== IBKR INTEGRATION (NUR IBKRService!) ==========
    # KEINE Legacy-Adapter mehr! Alles über IBKRService Signals.

    def is_market_open(self) -> bool:
        """
        Prüft ob der Markt in New York geöffnet ist.

        Returns:
            True wenn innerhalb der konfigurierten Trading-Stunden (NY Zeit)
        """
        if not self.enforce_trading_hours:
            return True  # Trading-Stunden-Prüfung deaktiviert

        # Aktuelle Zeit in New York
        now_ny = datetime.now(NY_TZ)
        current_time = now_ny.time()

        # Prüfe ob innerhalb der Handelszeiten
        is_open = self.trading_hours_start <= current_time <= self.trading_hours_end

        # Zusätzlich: Wochentag prüfen (Mo-Fr = 0-4)
        is_weekday = now_ny.weekday() < 5

        return is_open and is_weekday

    def get_ny_time_str(self) -> str:
        """Gibt aktuelle New York Zeit als String zurück"""
        now_ny = datetime.now(NY_TZ)
        return now_ny.strftime("%H:%M:%S")

    def _update_trading_hours(self):
        """Update Trading-Stunden basierend auf UI SpinBoxes"""
        start_hour = self.hours_start_spin.value()
        end_hour = self.hours_end_spin.value()

        # Update die Zeit-Objekte
        self.trading_hours_start = time(start_hour, 30)  # Immer mit :30
        self.trading_hours_end = time(end_hour, 0)       # Immer mit :00

        self.log_message(
            f"⏰ Trading-Stunden aktualisiert: {self.trading_hours_start.strftime('%H:%M')}-{self.trading_hours_end.strftime('%H:%M')} NY",
            "INFO"
        )

    def _toggle_enforce_hours(self, enabled: bool):
        """Toggle ob Trading-Stunden erzwungen werden"""
        self.enforce_trading_hours = enabled
        if enabled:
            self.log_message(
                f"⏰ Trading-Stunden-Prüfung AKTIVIERT: "
                f"{self.trading_hours_start.strftime('%H:%M')}-{self.trading_hours_end.strftime('%H:%M')} NY",
                "INFO"
            )
        else:
            self.log_message("⚠️ Trading-Stunden-Prüfung DEAKTIVIERT - Bot kann jederzeit traden!", "WARNING")

    def _update_ny_time_display(self):
        """Update NY Zeit Anzeige in der UI"""
        if hasattr(self, 'ny_time_label'):
            ny_time = self.get_ny_time_str()
            now_ny = datetime.now(NY_TZ)
            day_name = now_ny.strftime("%a")  # Mo, Di, etc.

            # Zeige auch ob Markt offen
            if self.is_market_open():
                status = "🟢 Offen"
            elif now_ny.weekday() >= 5:
                status = "🔴 Wochenende"
            else:
                status = "🔴 Geschlossen"

            self.ny_time_label.setText(f"NY Zeit: {ny_time} ({day_name}) - {status}")

    def toggle_live_trading(self, enabled: bool):
        """Aktiviere/Deaktiviere Live-Trading"""
        if enabled:
            # Sicherheitswarnung
            reply = QMessageBox.warning(
                self,
                "⚠️ Live Trading aktivieren",
                "WARNUNG: Du aktivierst jetzt Live-Trading!\n\n"
                "Der Bot wird echte Orders an IBKR senden.\n"
                "Stelle sicher, dass du Paper-Trading verwendest zum Testen.\n\n"
                "Wirklich aktivieren?",
                QMessageBox.Yes | QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.live_trading_enabled = True
                self.log_message("🟢 LIVE TRADING AKTIVIERT", "WARNING")

                # Starte Order Status Checker Timer
                if not self.status_check_task:
                    self.status_check_task = QTimer()
                    self.status_check_task.timeout.connect(self._check_pending_orders_sync)
                    self.status_check_task.start(1000)  # Jede Sekunde
                    self.log_message("Order Status Checker gestartet", "INFO")
            else:
                self.live_trading_cb.setChecked(False)
        else:
            self.live_trading_enabled = False
            self.log_message("Live Trading deaktiviert", "INFO")

            # Stoppe Order Status Checker Timer
            if self.status_check_task:
                self.status_check_task.stop()
                self.status_check_task = None
                self.log_message("Order Status Checker gestoppt", "INFO")

    def _on_refresh_rate_changed(self):
        """Update Timer wenn Rate geändert wird - NICHT MEHR VERWENDET"""
        # Legacy - Market Data kommt jetzt per Push via IBKRService
        pass

    def _start_market_data_timer(self):
        """LEGACY - NICHT MEHR VERWENDEN! Market Data kommt per Push via IBKRService."""
        print("DEBUG BOT: _start_market_data_timer IGNORIERT - IBKRService wird verwendet")
        # Starte KEINEN Timer - alles über IBKRService Signals!

    def _update_market_data(self):
        """LEGACY - NICHT MEHR VERWENDEN! Market Data kommt per Push via IBKRService."""
        # Diese Methode sollte nie aufgerufen werden
        print("DEBUG BOT: _update_market_data IGNORIERT - IBKRService wird verwendet")

    async def _async_update_market_data(self, adapter, symbols: List[str]):
        """LEGACY - NICHT MEHR VERWENDEN! Market Data kommt per Push via IBKRService."""
        print("DEBUG BOT: _async_update_market_data IGNORIERT - IBKRService wird verwendet")

    async def _check_entry_conditions(self, market_data: Dict[str, dict]):
        """Prüfe Entry-Bedingungen für wartende Levels

        WICHTIG: Verwendet korrekte Preise für Order-Typ:
        - LONG (BUY): Prüft ASK-Preis (was man beim Kauf zahlt)
        - SHORT (SELL): Prüft BID-Preis (was man beim Verkauf erhält)
        """

        # WICHTIG: Prüfe Trading-Stunden BEVOR Orders platziert werden
        if not self.is_market_open():
            ny_time = self.get_ny_time_str()
            # Log nur einmal pro Minute
            if not hasattr(self, '_last_market_closed_log') or \
            (datetime.now() - self._last_market_closed_log).seconds > 60:
                self.log_message(
                    f"⏰ Markt geschlossen (NY Zeit: {ny_time}). "
                    f"Trading-Stunden: {self.trading_hours_start.strftime('%H:%M')}-{self.trading_hours_end.strftime('%H:%M')} NY",
                    "WARNING"
                )
                self._last_market_closed_log = datetime.now()
            return  # Keine Entries außerhalb der Handelszeiten

        levels_to_activate = []

        for i, level in enumerate(self.waiting_levels):
            if level.get('status') == 'paused':
                continue

            # Eindeutiger Level-Identifier (HIER ist es richtig!)
            scenario_name = level.get('scenario_name', 'unknown')
            level_num = level.get('level_num', 0)
            unique_level_id = f"{scenario_name}_L{level_num}"

            if unique_level_id in self._orders_placed_for_levels:
                continue  # Skip - bereits Order für dieses Level platziert

            symbol = level['symbol']

            if symbol not in market_data:
                continue

            prices = market_data[symbol]
            entry_price = level['entry_price']

            if entry_price is None:
                continue

            level_type = level['type']

            # Entry-Bedingung prüfen mit KORREKTEN Preisen:
            # LONG (BUY): Verwende ASK-Preis - das ist was wir zahlen müssen
            # SHORT (SELL): Verwende BID-Preis - das ist was wir erhalten
            triggered = False

            if level_type == 'LONG':
                # Für LONG/BUY: ASK muss auf oder unter Entry-Preis fallen
                check_price = prices['ask'] if prices['ask'] > 0 else prices['last']
                if check_price <= entry_price:
                    triggered = True
                    self.log_message(
                        f"📈 LONG ENTRY: {symbol} ASK=${check_price:.2f} <= Ziel=${entry_price:.2f}",
                        "TRADE"
                    )
            elif level_type == 'SHORT':
                # Für SHORT/SELL: BID muss auf oder über Entry-Preis steigen
                check_price = prices['bid'] if prices['bid'] > 0 else prices['last']
                if check_price >= entry_price:
                    triggered = True
                    self.log_message(
                        f"📉 SHORT ENTRY: {symbol} BID=${check_price:.2f} >= Ziel=${entry_price:.2f}",
                        "TRADE"
                    )

            if triggered:
                levels_to_activate.append((i, level, check_price))

        # Aktiviere getriggerte Levels
        for idx, level, entry_price in reversed(levels_to_activate):
            await self._execute_entry(idx, level, entry_price)

    async def _execute_entry(self, waiting_idx: int, level: dict, actual_entry_price: float):
        """Führe Entry-Order aus und verschiebe Level zu Active"""
        
           
        # DEBUG: Prüfe ob wir in einem neuen/alten Kontext sind
        self.log_message(f"DEBUG: Execute Entry START für {level.get('scenario_name')}_L{level.get('level_num')}", "INFO")
        self.log_message(f"DEBUG: Anzahl Orders im Tracking: {len(self._orders_placed_for_levels)}", "INFO")
    



        # Eindeutiger Key aus Szenario + Level
        scenario_name = level.get('scenario_name', 'unknown')
        level_num = level.get('level_num', 0)
        unique_level_id = f"{scenario_name}_L{level_num}"  # z.B. "S_300_0.5_0.7_10_WULF_L1"
        
        self._orders_placed_for_levels.add(unique_level_id)

        # NEU: Markiere Level als "hat Order" HIER!
        symbol = level['symbol']
        
        # ALLES ANDERE BLEIBT! Nur die 4 Zeilen oben hinzufügen
        shares = level['shares']
        level_type = level['type']
        theoretical_entry = level['entry_price']  # Original Entry-Preis
        theoretical_exit = level['exit_price']    # Original Exit-Preis

        # Order platzieren
        if level_type == 'LONG':
            side = 'BUY'
        else:  # SHORT
            side = 'SELL'

        # Level-Name für Pending Orders
        level_name = f"{scenario_name}_L{level_num}"

        # Platziere Order (simuliert oder echt)
        # Bei Limit-Orders: setze Limit auf theoretischen Entry-Preis
        if self.limit_order_rb.isChecked():
            order_result = self.place_ibkr_order(
                symbol, side, shares, "LIMIT", theoretical_entry, level_name,
                level_data=level  # Übergebe vollständige Level-Daten!
            )
        else:
            order_result = self.place_ibkr_order(
                symbol, side, shares, "MARKET", None, level_name,
                level_data=level  # Übergebe vollständige Level-Daten!
            )

        # Prüfe ob Order platziert wurde (nicht ob gefüllt!)
        if not order_result:
            # WICHTIG: Level-Tracking zurücksetzen, sonst bleibt es ewig blockiert
            if unique_level_id in self._orders_placed_for_levels:
                self._orders_placed_for_levels.discard(unique_level_id)
                self.log_message(
                    f"DEBUG: Order-Tracking für {unique_level_id} nach ENTRY-Fehler zurückgesetzt",
                    "DEBUG"
                )
            self.log_message(f"❌ ENTRY FEHLGESCHLAGEN: {symbol} - Order konnte nicht platziert werden", "ERROR")
            return

        broker_order_id = order_result

        # WICHTIG: Order ist nur PENDING, nicht gefüllt!
        # Füge NUR zu Pending Orders hinzu, NICHT zu Active!
        self.log_message(f"Order {broker_order_id} wartet auf Ausführung", "INFO")

        # Entferne aus Waiting
        del self.waiting_levels[waiting_idx]
        self.waiting_table.removeRow(waiting_idx)
        self.waiting_count_label.setText(f"{self.waiting_table.rowCount()} wartende Levels")

        # FERTIG! Nicht zu Active hinzufügen bis Order wirklich gefüllt ist!
        return

        # Order wurde platziert - verwende theoretische Werte vorerst
        broker_order_id = order_result
        actual_entry_price = theoretical_entry  # Wird später durch echten Fill-Preis ersetzt
        entry_commission = 0.0  # Wird später aktualisiert

        # Verwende echten Fill-Preis von IBKR (nicht Marktpreis!)
       
        self.log_message(f"IBKR FILL: {symbol} @ ${actual_entry_price:.2f} (Komm: ${entry_commission:.2f})", "INFO")

        # Berechne tatsächlichen Exit-Preis basierend auf Ausführungsqualität
        # LONG: besser = niedriger Preis → Exit auf theoretischem
        #       schlechter = höherer Preis → Exit auf tatsächlichem
        # SHORT: besser = höherer Preis → Exit auf theoretischem
        #        schlechter = niedriger Preis → Exit auf tatsächlichem
        if level_type == 'LONG':
            if actual_entry_price <= theoretical_entry:
                # Besserer oder gleicher Preis → Exit auf theoretischem Entry berechnen
                exit_diff = theoretical_exit - theoretical_entry
                calculated_exit = theoretical_entry + exit_diff
                self.log_message(f"LONG besserer Entry: ${actual_entry_price:.2f} <= ${theoretical_entry:.2f}, Exit auf theoretisch: ${calculated_exit:.2f}", "INFO")
            else:
                # Schlechterer Preis → Exit auf tatsächlichem Entry berechnen
                exit_diff = theoretical_exit - theoretical_entry
                calculated_exit = actual_entry_price + exit_diff
                self.log_message(f"LONG schlechterer Entry: ${actual_entry_price:.2f} > ${theoretical_entry:.2f}, Exit angepasst: ${calculated_exit:.2f}", "WARNING")
        else:  # SHORT
            if actual_entry_price >= theoretical_entry:
                # Besserer oder gleicher Preis → Exit auf theoretischem Entry berechnen
                exit_diff = theoretical_entry - theoretical_exit
                calculated_exit = theoretical_entry - exit_diff
                self.log_message(f"SHORT besserer Entry: ${actual_entry_price:.2f} >= ${theoretical_entry:.2f}, Exit auf theoretisch: ${calculated_exit:.2f}", "INFO")
            else:
                # Schlechterer Preis → Exit auf tatsächlichem Entry berechnen
                exit_diff = theoretical_entry - theoretical_exit
                calculated_exit = actual_entry_price - exit_diff
                self.log_message(f"SHORT schlechterer Entry: ${actual_entry_price:.2f} < ${theoretical_entry:.2f}, Exit angepasst: ${calculated_exit:.2f}", "WARNING")

        # Erstelle Active Level
        active_level = {
            'scenario_name': level['scenario_name'],
            'level_num': level['level_num'],
            'symbol': symbol,
            'type': level_type,
            'shares': shares,
            'entry_price': actual_entry_price,
            'theoretical_entry': theoretical_entry,  # Original Entry für Neustart
            'exit_price': calculated_exit,
            'theoretical_exit': theoretical_exit,    # Original Exit für Neustart
            'entry_time': datetime.now().isoformat(),
            'status': 'active',
            'order_id': broker_order_id,  # Verwende broker_order_id statt order_id
            'entry_commission': entry_commission,    # Echte IBKR Commission speichern
            # Speichere Original-Level für Neustart
            'original_level': level.copy()
        }
        self.active_levels.append(active_level)

        # Füge zur Active Table hinzu
        self._add_to_active_table(active_level, actual_entry_price)

        # Entferne aus Waiting
        del self.waiting_levels[waiting_idx]
        self.waiting_table.removeRow(waiting_idx)
        self.waiting_count_label.setText(f"{self.waiting_table.rowCount()} wartende Levels")

        self.log_message(
            f"✅ Position eröffnet: {level_type} {shares}x {symbol} @ ${actual_entry_price:.2f} → Exit: ${calculated_exit:.2f}",
            "SUCCESS"
        )

    def _add_to_active_table(self, level: dict, current_price: float):
        """Füge Level zur Active-Tabelle hinzu"""
        row = self.active_table.rowCount()
        self.active_table.insertRow(row)

        # Symbol (Spalte 0)
        self.active_table.setItem(row, 0, QTableWidgetItem(level['symbol']))

        # Typ (Spalte 1)
        type_item = QTableWidgetItem(level['type'])
        if level['type'] == 'LONG':
            type_item.setForeground(QColor(0, 128, 0))
        else:
            type_item.setForeground(QColor(128, 0, 0))
        self.active_table.setItem(row, 1, type_item)

        # Einstiegspreis (Spalte 2)
        self.active_table.setItem(row, 2, QTableWidgetItem(f"${level['entry_price']:.2f}"))

        # Zielpreis (Exit) (Spalte 3)
        self.active_table.setItem(row, 3, QTableWidgetItem(f"${level['exit_price']:.2f}"))

        # Aktueller Preis (Spalte 4) - NEU
        self.active_table.setItem(row, 4, QTableWidgetItem(f"${current_price:.2f}"))

        # Akt. P&L (Spalte 5) - wird aktualisiert
        pnl_item = QTableWidgetItem("$0.00")
        self.active_table.setItem(row, 5, pnl_item)

        # Diff. zum Ziel (Spalte 6)
        diff_to_target = ((level['exit_price'] - current_price) / current_price) * 100
        self.active_table.setItem(row, 6, QTableWidgetItem(f"{diff_to_target:+.2f}%"))

        # Dauer (Spalte 7)
        self.active_table.setItem(row, 7, QTableWidgetItem("0m"))

        # Status (Spalte 8)
        status_item = QTableWidgetItem("Aktiv")
        status_item.setForeground(QColor(0, 128, 0))
        self.active_table.setItem(row, 8, status_item)

        # Szenario (Spalte 9)
        scenario_text = f"{level['scenario_name']} L{level['level_num']}"
        self.active_table.setItem(row, 9, QTableWidgetItem(scenario_text))

        # Update Counter
        self.active_count_label.setText(f"{self.active_table.rowCount()} aktive Positionen")

    async def _check_exit_conditions(self, market_data: Dict[str, dict]):
        """Prüfe Exit-Bedingungen für aktive Levels und aktualisiere P&L

        WICHTIG: Verwendet korrekte Preise für Order-Typ:
        - LONG Exit (SELL): Prüft BID-Preis (was man beim Verkauf erhält)
        - SHORT Exit (BUY): Prüft ASK-Preis (was man beim Kauf zahlt)
        """
        levels_to_close = []

        for i, level in enumerate(self.active_levels):
            if level.get('status') == 'paused':
                continue

            # FIX: Skip levels that are already being exited to prevent duplicate orders
            if level.get('status') == 'EXITING':
                continue

            symbol = level.get('symbol', '')
            if symbol not in market_data:
                continue

            prices = market_data[symbol]
            entry_price = level['entry_price']
            exit_price = level['exit_price']
            shares = level['shares']
            level_type = level['type']

            # Für P&L-Berechnung verwenden wir den realistischen Verkaufs-/Kaufpreis
            # Last-Preis für Anzeige
            last_price = prices['last'] if prices['last'] > 0 else 0

            if level_type == 'LONG':
                # LONG verkauft zum BID
                current_price = prices['bid'] if prices['bid'] > 0 else prices['last']
                pnl = (current_price - entry_price) * shares
                diff_to_target = ((exit_price - current_price) / current_price) * 100 if current_price > 0 else 0
            else:  # SHORT
                # SHORT kauft zurück zum ASK
                current_price = prices['ask'] if prices['ask'] > 0 else prices['last']
                pnl = (entry_price - current_price) * shares
                diff_to_target = ((current_price - exit_price) / current_price) * 100 if current_price > 0 else 0

            # Update Tabelle (mit Last-Preis für Anzeige)
            self._update_active_table_row(i, pnl, diff_to_target, level, last_price)

            # Exit-Bedingung mit KORREKTEN Preisen:
            # LONG Exit (SELL): BID muss auf oder über Exit-Level steigen
            # SHORT Exit (BUY): ASK muss auf oder unter Exit-Level fallen
            triggered = False

            if level_type == 'LONG' and current_price >= exit_price:
                triggered = True
                self.log_message(
                    f"🎯 LONG EXIT: {symbol} BID=${current_price:.2f} >= Ziel=${exit_price:.2f}",
                    "TRADE"
                )
            elif level_type == 'SHORT' and current_price <= exit_price:
                triggered = True
                self.log_message(
                    f"🎯 SHORT EXIT: {symbol} ASK=${current_price:.2f} <= Ziel=${exit_price:.2f}",
                    "TRADE"
                )

            if triggered:
                # FIX: Mark level as EXITING IMMEDIATELY to prevent duplicate exit orders
                level['status'] = 'EXITING'
                levels_to_close.append((i, level, current_price, pnl))

        # Update unrealized P&L in stats
        total_unrealized = sum(
            self._calculate_unrealized_pnl(level, market_data)
            for level in self.active_levels
        )
        self.daily_stats['unrealized_pnl'] = total_unrealized
        self.daily_stats['total_pnl'] = self.daily_stats['realized_pnl'] + total_unrealized
        self.update_statistics_display()

        # Update Dashboard panels
        self._update_dashboard(market_data)

        # Schliesse getriggerte Positionen (von hinten nach vorne)
        for idx, level, exit_price, pnl in reversed(levels_to_close):
            await self._execute_exit(idx, level, exit_price, pnl)

    def _calculate_unrealized_pnl(self, level: dict, market_data: Dict[str, dict]) -> float:
        """Berechne unrealisierten P&L für ein Level

        Verwendet korrekte Preise:
        - LONG: BID-Preis (was man beim Verkauf erhalten würde)
        - SHORT: ASK-Preis (was man beim Rückkauf zahlen würde)
        """
        symbol = level.get('symbol', '')
        if symbol not in market_data:
            return 0.0

        prices = market_data[symbol]
        entry_price = level['entry_price']
        shares = level['shares']

        if level['type'] == 'LONG':
            # LONG verkauft zum BID
            current_price = prices['bid'] if prices['bid'] > 0 else prices['last']
            return (current_price - entry_price) * shares
        else:  # SHORT
            # SHORT kauft zurück zum ASK
            current_price = prices['ask'] if prices['ask'] > 0 else prices['last']
            return (entry_price - current_price) * shares

    def _update_active_table_row(self, row: int, pnl: float, diff_to_target: float, level: dict, current_price: float = 0):
        """Aktualisiere eine Zeile in der Active-Tabelle"""
        if row >= self.active_table.rowCount():
            return

        # Aktueller Preis (Spalte 4)
        price_item = self.active_table.item(row, 4)
        if price_item and current_price > 0:
            price_item.setText(f"${current_price:.2f}")

        # P&L (Spalte 5)
        pnl_item = self.active_table.item(row, 5)
        if pnl_item:
            pnl_text = f"${pnl:+,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
            pnl_item.setText(pnl_text)
            if pnl >= 0:
                pnl_item.setForeground(QColor(0, 128, 0))
            else:
                pnl_item.setForeground(QColor(128, 0, 0))

        # Diff. zum Ziel (Spalte 6)
        diff_item = self.active_table.item(row, 6)
        if diff_item:
            diff_item.setText(f"{diff_to_target:+.2f}%")

        # Dauer (Spalte 7)
        entry_time_str = level.get('entry_time', '')
        if entry_time_str:
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                duration = datetime.now() - entry_time
                minutes = int(duration.total_seconds() / 60)
                if minutes < 60:
                    duration_text = f"{minutes}m"
                else:
                    hours = minutes // 60
                    mins = minutes % 60
                    duration_text = f"{hours}h {mins}m"

                duration_item = self.active_table.item(row, 7)
                if duration_item:
                    duration_item.setText(duration_text)
            except:
                pass

        # FIX: Update status display based on level status (Spalte 8)
        status_item = self.active_table.item(row, 8)
        if status_item:
            level_status = level.get('status', 'active')
            if level_status == 'EXITING':
                status_item.setText("Schließen...")
                status_item.setForeground(QColor(255, 165, 0))  # Orange
            elif level_status == 'paused':
                status_item.setText("Pausiert")
                status_item.setForeground(QColor(128, 128, 128))  # Grau
            else:
                status_item.setText("Aktiv")
                status_item.setForeground(QColor(0, 128, 0))  # Grün

    async def _execute_exit(self, active_idx: int, level: dict, actual_exit_price: float, pnl: float):
        """Führe Exit-Order aus und entferne Level"""
        symbol = level['symbol']
        shares = level['shares']
        level_type = level['type']

        # Order platzieren (umgekehrte Richtung)
        if level_type == 'LONG':
            side = 'SELL'
        else:  # SHORT
            side = 'BUY'

        # Level-Name für Pending Orders
        level_name = f"{level.get('scenario_name', 'Exit')}_L{level.get('level_num', 0)}_EXIT"

        # FIX: Erstelle exit_level_data mit allen nötigen Infos für Recycling
        exit_level_data = {
            'is_exit': True,  # Flag für Exit-Order
            'active_idx': active_idx,
            'symbol': symbol,
            'type': level_type,
            'shares': shares,
            'entry_price': level['entry_price'],
            'exit_price': level['exit_price'],
            'exit_pct': level.get('exit_pct', 0),
            'scenario_name': level.get('scenario_name', 'N/A'),
            'level_num': level.get('level_num', 0),
            'entry_time': level.get('entry_time'),
            'entry_commission': level.get('entry_commission', 0.0),
            'original_level': level.get('original_level')  # Für Recycling!
        }

        # Platziere Order
        # Bei Limit-Orders: setze Limit auf berechneten Exit-Preis
        if self.limit_order_rb.isChecked():
            target_exit = level['exit_price']  # Der berechnete Exit-Preis
            order_result = self.place_ibkr_order(
                symbol, side, shares, "LIMIT", target_exit, level_name,
                level_data=exit_level_data  # FIX: Übergebe Level-Daten!
            )
        else:
            order_result = self.place_ibkr_order(
                symbol, side, shares, "MARKET", None, level_name,
                level_data=exit_level_data  # FIX: Übergebe Level-Daten!
            )

        # Prüfe ob Order platziert wurde (nicht ob gefüllt!)
        if not order_result:
            self.log_message(f"❌ EXIT FEHLGESCHLAGEN: {symbol} - Order konnte nicht platziert werden", "ERROR")
            # Reset status so level can be processed again
            level['status'] = 'active'
            return

        broker_order_id = order_result

        # WICHTIG: Order ist nur PENDING, nicht gefüllt!
        # handle_order_filled() wird aufgerufen wenn Order gefüllt
        self.log_message(f"Exit-Order {broker_order_id} wartet auf Ausführung für {level_name}", "INFO")

        # Entferne aus Active (Order ist platziert)
        del self.active_levels[active_idx]
        self.active_table.removeRow(active_idx)
        self.active_count_label.setText(f"{self.active_table.rowCount()} aktive Positionen")

    def _add_waiting_level_to_table(self, level: dict):
        """Füge ein einzelnes Level zur Waiting-Tabelle hinzu (für Neustart)"""
        row = self.waiting_table.rowCount()
        self.waiting_table.insertRow(row)

        # Symbol
        self.waiting_table.setItem(row, 0, QTableWidgetItem(level['symbol']))

        # Typ
        type_item = QTableWidgetItem(level['type'])
        if level['type'] == 'LONG':
            type_item.setForeground(QColor(0, 128, 0))
        else:
            type_item.setForeground(QColor(128, 0, 0))
        self.waiting_table.setItem(row, 1, type_item)

        # Zielpreis (Entry) (Spalte 2)
        entry_price = level.get('entry_price', 0)
        self.waiting_table.setItem(row, 2, QTableWidgetItem(f"${entry_price:.2f}"))

        # Ausstiegspreis (Spalte 3)
        exit_price = level.get('exit_price', 0)
        self.waiting_table.setItem(row, 3, QTableWidgetItem(f"${exit_price:.2f}"))

        # Aktueller Preis (Spalte 4) - wird live aktualisiert
        self.waiting_table.setItem(row, 4, QTableWidgetItem("--"))

        # Differenz zum Einstieg (Spalte 5) - wird live aktualisiert
        self.waiting_table.setItem(row, 5, QTableWidgetItem("--"))

        # Status (Spalte 6)
        status_item = QTableWidgetItem("Wartend")
        status_item.setForeground(QColor(0, 128, 0))
        self.waiting_table.setItem(row, 6, status_item)

        # Szenario (Spalte 7)
        scenario_text = f"{level.get('scenario_name', 'N/A')} L{level['level_num']}"
        self.waiting_table.setItem(row, 7, QTableWidgetItem(scenario_text))

        # Update Counter
        self.waiting_count_label.setText(f"{self.waiting_table.rowCount()} wartende Levels")

        # Sortiere Tabelle nach Symbol und Einstiegspreis
        self._sort_waiting_table()

    def _sort_waiting_table(self):
        """Sortiert die Waiting-Tabelle nach Symbol und Einstiegspreis"""
        if not self.waiting_levels:
            return

        # Sortiere waiting_levels nach Symbol und entry_price
        self.waiting_levels.sort(key=lambda x: (
            x.get('symbol', ''),
            x.get('entry_price', 0) if x.get('entry_price') is not None else float('inf')
        ))

        # Tabelle komplett neu aufbauen
        self.waiting_table.setRowCount(0)

        for level in self.waiting_levels:
            row = self.waiting_table.rowCount()
            self.waiting_table.insertRow(row)

            # Symbol
            self.waiting_table.setItem(row, 0, QTableWidgetItem(level['symbol']))

            # Typ
            type_item = QTableWidgetItem(level['type'])
            if level['type'] == 'LONG':
                type_item.setForeground(QColor(0, 128, 0))
            else:
                type_item.setForeground(QColor(128, 0, 0))
            self.waiting_table.setItem(row, 1, type_item)

            # Zielpreis (Entry)
            entry_price = level.get('entry_price')
            if entry_price is not None:
                entry_pct = level.get('entry_pct', 0)
                entry_text = f"${entry_price:.2f} ({entry_pct:+.2f}%)"
            else:
                entry_pct = level.get('entry_pct', 0)
                entry_text = f"({entry_pct:+.2f}%)"
            self.waiting_table.setItem(row, 2, QTableWidgetItem(entry_text))

            # Ausstiegspreis (Spalte 3)
            exit_price = level.get('exit_price')
            if exit_price is not None:
                self.waiting_table.setItem(row, 3, QTableWidgetItem(f"${exit_price:.2f}"))
            else:
                exit_pct = level.get('exit_pct', 0)
                self.waiting_table.setItem(row, 3, QTableWidgetItem(f"({exit_pct:+.2f}%)"))

            # Aktueller Preis (Spalte 4) - wird live aktualisiert
            self.waiting_table.setItem(row, 4, QTableWidgetItem("--"))

            # Differenz zum Einstieg (Spalte 5) - wird live aktualisiert
            self.waiting_table.setItem(row, 5, QTableWidgetItem("--"))

            # Status (Spalte 6)
            status_text = "Wartend" if level.get('status') == 'waiting' else level.get('status', 'Wartend').capitalize()
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(0, 128, 0))
            self.waiting_table.setItem(row, 6, status_item)

            # Szenario (Spalte 7)
            scenario_text = f"{level.get('scenario_name', 'N/A')} L{level['level_num']}"
            self.waiting_table.setItem(row, 7, QTableWidgetItem(scenario_text))

    def place_ibkr_order_via_service(self, symbol: str, side: str, quantity: int, order_type: str = "MARKET", limit_price: float = None, level_name: str = "Manual", level_data: dict = None) -> Optional[str]:
        """
        Platziere Order über IBKRService (NON-BLOCKING!)

        Verwendet den neuen IBKRService statt des Legacy-Adapters.
        Returns callback_id für Tracking - das Ergebnis kommt via Signals.
        """
        print(f"DEBUG BOT: place_ibkr_order_via_service called - type={order_type}, limit_price={limit_price}")

        if not self.live_trading_enabled:
            self.log_message(f"ORDER (Simulation): {side} {quantity}x {symbol}", "TRADE")
            return None

        # Prüfe IBKRService Verbindung
        if not self._ibkr_service or not self._service_connected:
            self.log_message("IBKRService nicht verbunden - Verbinde im Live Trading Tab", "ERROR")
            return None

        try:
            from gridtrader.domain.models.order import Order, OrderSide, OrderType
            from decimal import Decimal

            # Erstelle Domain Order
            order = Order(
                symbol=symbol,
                side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                order_type=OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT,
                quantity=quantity
            )

            if limit_price:
                order.limit_price = Decimal(str(limit_price))

            # Platziere Order über IBKRService (NON-BLOCKING!)
            callback_id = self._ibkr_service.place_order(order)

            self.log_message(
                f"ORDER GESENDET: {side} {quantity}x {symbol} @ {f'${limit_price:.2f}' if limit_price else 'Market'} (Callback: {callback_id[:8]}...)",
                "TRADE"
            )

            # Speichere Order-Info für Callback-Verarbeitung
            self._order_callbacks[callback_id] = {
                'level': level_data,
                'type': 'MANUAL',
                'order': order,
                'level_name': level_name,
                'symbol': symbol,
                'side': side,
                'quantity': quantity
            }

            return callback_id

        except Exception as e:
            self.log_message(f"Order-Fehler: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return None

    # Legacy async method - redirects to service method
    def place_ibkr_order(self, symbol: str, side: str, quantity: int, order_type: str = "MARKET", limit_price: float = None, level_name: str = "Manual", level_data: dict = None):
        """
        LEGACY - Redirects to IBKRService

        Diese Methode ist für Abwärtskompatibilität.
        Verwendet intern place_ibkr_order_via_service().
        """
        return self.place_ibkr_order_via_service(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            level_name=level_name,
            level_data=level_data
        )

    def update_pending_display(self):
        """Aktualisiere Pending Orders Anzeige"""
        self.pending_table.setRowCount(len(self.pending_orders))
        for row, (order_id, order_info) in enumerate(self.pending_orders.items()):
            self.pending_table.setItem(row, 0, QTableWidgetItem(order_info.get('symbol', '')))
            self.pending_table.setItem(row, 1, QTableWidgetItem(order_info.get('type', '')))
            self.pending_table.setItem(row, 2, QTableWidgetItem(order_info.get('side', '')))
            self.pending_table.setItem(row, 3, QTableWidgetItem(str(order_info.get('quantity', 0))))

            # Preis-Spalte: "Market" für Market Orders, Limitpreis für Limit Orders
            price_text = "Market"
            order_object = order_info.get('order_object')
            if order_object:
                from gridtrader.domain.models.order import OrderType
                if order_object.order_type == OrderType.LIMIT and order_object.limit_price:
                    price_text = f"${order_object.limit_price:.2f}"
            self.pending_table.setItem(row, 4, QTableWidgetItem(price_text))

            self.pending_table.setItem(row, 5, QTableWidgetItem(str(order_id)))
            self.pending_table.setItem(row, 6, QTableWidgetItem(order_info.get('status', 'PENDING')))
            self.pending_table.setItem(row, 7, QTableWidgetItem(order_info.get('timestamp', '')))
            self.pending_table.setItem(row, 8, QTableWidgetItem(order_info.get('level_name', '')))

        # Update count label
        self.pending_count_label.setText(f"{len(self.pending_orders)} pending orders")

    def update_waiting_levels_display(self):
        """Aktualisiere Wartende Levels Anzeige basierend auf self.waiting_levels"""
        self.waiting_table.setRowCount(0)  # Clear table

        for level in self.waiting_levels:
            row = self.waiting_table.rowCount()
            self.waiting_table.insertRow(row)

            # Symbol
            self.waiting_table.setItem(row, 0, QTableWidgetItem(level.get('symbol', '')))

            # Typ (LONG/SHORT)
            type_item = QTableWidgetItem(level.get('type', ''))
            if level.get('type') == 'LONG':
                type_item.setForeground(QColor(0, 128, 0))
            else:
                type_item.setForeground(QColor(128, 0, 0))
            self.waiting_table.setItem(row, 1, type_item)

            # Zielpreis (Einstieg)
            entry_price = level.get('entry_price')
            entry_text = f"${entry_price:.2f}" if entry_price else "Warte..."
            self.waiting_table.setItem(row, 2, QTableWidgetItem(entry_text))

            # Ausstiegspreis
            exit_price = level.get('exit_price')
            exit_text = f"${exit_price:.2f}" if exit_price else "Warte..."
            self.waiting_table.setItem(row, 3, QTableWidgetItem(exit_text))

            # Akt. Preis (wird später durch Market Data aktualisiert)
            self.waiting_table.setItem(row, 4, QTableWidgetItem("--"))

            # Diff. zum Einstieg
            self.waiting_table.setItem(row, 5, QTableWidgetItem("--"))

            # Status
            status = level.get('status', 'waiting')
            status_item = QTableWidgetItem(status)
            self.waiting_table.setItem(row, 6, status_item)

            # Szenario
            scenario_text = f"{level.get('scenario_name', 'N/A')} L{level.get('level_num', 0)}"
            self.waiting_table.setItem(row, 7, QTableWidgetItem(scenario_text))

        # Update count label
        self.waiting_count_label.setText(f"{len(self.waiting_levels)} wartende Levels")

    def update_active_levels_display(self):
        """Aktualisiere Aktive Levels Anzeige basierend auf self.active_levels"""
        self.active_table.setRowCount(0)  # Clear table

        for level in self.active_levels:
            row = self.active_table.rowCount()
            self.active_table.insertRow(row)

            # Symbol
            self.active_table.setItem(row, 0, QTableWidgetItem(level.get('symbol', '')))

            # Typ (LONG/SHORT)
            type_item = QTableWidgetItem(level.get('type', ''))
            if level.get('type') == 'LONG':
                type_item.setForeground(QColor(0, 128, 0))
            else:
                type_item.setForeground(QColor(128, 0, 0))
            self.active_table.setItem(row, 1, type_item)

            # Einstiegspreis
            entry_price = level.get('entry_fill_price') or level.get('entry_price', 0)
            self.active_table.setItem(row, 2, QTableWidgetItem(f"${entry_price:.2f}"))

            # Zielpreis (Exit)
            exit_price = level.get('exit_price', 0)
            self.active_table.setItem(row, 3, QTableWidgetItem(f"${exit_price:.2f}"))

            # Akt. Preis (wird später durch Market Data aktualisiert)
            self.active_table.setItem(row, 4, QTableWidgetItem("--"))

            # Akt. P&L (wird später berechnet)
            self.active_table.setItem(row, 5, QTableWidgetItem("--"))

            # Diff. zum Ziel
            self.active_table.setItem(row, 6, QTableWidgetItem("--"))

            # Dauer
            entry_time = level.get('entry_time')
            if entry_time:
                try:
                    entry_dt = datetime.fromisoformat(entry_time)
                    duration = datetime.now() - entry_dt
                    duration_str = str(duration).split('.')[0]  # Remove microseconds
                except:
                    duration_str = "--"
            else:
                duration_str = "--"
            self.active_table.setItem(row, 7, QTableWidgetItem(duration_str))

            # Status
            status = "Aktiv" if not level.get('exit_order_placed') else "Exit platziert"
            self.active_table.setItem(row, 8, QTableWidgetItem(status))

            # Szenario
            scenario_text = f"{level.get('scenario_name', 'N/A')} L{level.get('level_num', 0)}"
            self.active_table.setItem(row, 9, QTableWidgetItem(scenario_text))

        # Update count label
        self.active_count_label.setText(f"{len(self.active_levels)} aktive Levels")

    def add_pending_order(self, order_id: str, order_info: dict):
        """Füge Order zu Pending hinzu"""
        self.pending_orders[order_id] = order_info
        self.update_pending_display()
        self.log_message(f"Order {order_id} zu Pending hinzugefügt", "INFO")

    def remove_pending_order(self, order_id: str):
        """Entferne Order aus Pending"""
        if order_id in self.pending_orders:
            del self.pending_orders[order_id]
            self.update_pending_display()

    def _add_filled_order_to_dashboard(self, order_info: dict, fill_price: float, commission: float):
        """Add filled order to Dashboard trades panel"""
        try:
            # Find MainWindow
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'add_dashboard_trade'):
                main_window = main_window.parent()

            if not main_window:
                return

            dashboard_trade = {
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'symbol': order_info.get('symbol', 'N/A'),
                'shares': order_info.get('quantity', 0),
                'side': order_info.get('side', 'N/A'),
                'price': fill_price,
                'commission': commission
            }

            main_window.add_dashboard_trade(dashboard_trade)

        except Exception as e:
            # Silently ignore dashboard update errors
            pass

    def handle_order_filled(self, order_id: str, order_info: dict):
        """Handle gefüllte Order"""
        from gridtrader.domain.models.order import OrderStatus

        order_obj = order_info.get('order_object')
        if not order_obj or order_obj.status != OrderStatus.FILLED:
            return

        fill_price = float(order_obj.avg_fill_price) if order_obj.avg_fill_price else None

        # Extrahiere Commission aus dem Order-Objekt
        commission = float(order_obj.commission) if order_obj.commission else 0.0
        order_info['commission'] = commission

        self.log_message(
            f"✅ ORDER GEFÜLLT: {order_info['side']} {order_info['quantity']}x {order_info['symbol']} @ ${fill_price:.2f} (Komm: ${commission:.2f}) (ID: {order_id})",
            "SUCCESS"
        )

        # Add filled order to Dashboard trades panel
        self._add_filled_order_to_dashboard(order_info, fill_price, commission)

        # Prüfe ob dies ein Level-Entry oder Exit war
        level_data = order_info.get('level_data')

        if level_data:
            if level_data.get('is_exit'):
                # FIX: Dies war eine Exit-Order! Recycle das Level
                self._handle_exit_filled(level_data, fill_price, order_id, order_info)
            else:
                # Dies war ein Level-Entry! Verschiebe zu Active
                self._move_to_active_levels(level_data, fill_price, order_id, order_info)
        else:
            # Manuelle Order - nur loggen
            self.log_message(f"Order {order_id} gefüllt (manuelle Order)", "INFO")

        # Entferne aus pending
        self.remove_pending_order(order_id)

    def _handle_exit_filled(self, level_data: dict, fill_price: float, order_id: str, order_info: dict):
        """Handle gefüllte Exit-Order und recycle das Level"""
        symbol = level_data['symbol']
        level_type = level_data['type']
        shares = level_data['shares']
        entry_price = level_data['entry_price']
        scenario_name = level_data.get('scenario_name', 'N/A')
        level_num = level_data.get('level_num', 0)

        # NEU: Level-Protection für dieses Level zurücksetzen,
        # sonst blockiert das Rezyklat den nächsten Entry
        unique_level_id = f"{scenario_name}_L{level_num}"
        if hasattr(self, "_orders_placed_for_levels"):
            if unique_level_id in self._orders_placed_for_levels:
                self._orders_placed_for_levels.discard(unique_level_id)
                self.log_message(
                    f"DEBUG: Order-Tracking für {unique_level_id} vor Recycling zurückgesetzt",
                    "DEBUG"
                )

        # Berechne echten P&L mit Fill-Preis
        if level_type == 'LONG':
            real_pnl = (fill_price - entry_price) * shares
        else:  # SHORT
            real_pnl = (entry_price - fill_price) * shares

        # Commission aus Entry und Exit zusammenrechnen
        entry_commission = level_data.get('entry_commission', 0.0)
        exit_commission = order_info.get('commission', 0.0)  # Exit-Commission aus IBKR
        total_commission = entry_commission + exit_commission

        # Trade aufzeichnen
        trade_data = {
            'symbol': symbol,
            'type': level_type,
            'shares': shares,
            'entry_price': entry_price,
            'price': fill_price,
            'pnl': real_pnl - total_commission,
            'commission': total_commission,
            'scenario': scenario_name,
            'level': level_num
        }
        self.record_trade(trade_data)

        pnl = real_pnl - total_commission

        self.log_message(
            f"✅ Position geschlossen: {level_type} {shares}x {symbol} @ ${fill_price:.2f} | P&L: ${pnl:+.2f}",
            "SUCCESS"
        )

        # === LEVEL NEUSTART: Füge Level wieder zur Waiting-Liste hinzu ===
        original_level = level_data.get('original_level')
        if original_level:
            # Erstelle neues Waiting Level mit Original-Preisen
            waiting_level_data = {
                'scenario_name': original_level.get('scenario_name', scenario_name),
                'level_num': original_level.get('level_num', level_num),
                'symbol': symbol,
                'type': level_type,
                'shares': shares,
                'entry_pct': original_level.get('entry_pct', 0),
                'exit_pct': original_level.get('exit_pct', 0),
                'base_price': original_level.get('base_price', level_data.get('entry_price', 0)),
                'entry_price': original_level.get('entry_price', level_data.get('entry_price', 0)),
                'exit_price': original_level.get('exit_price', level_data.get('exit_price', 0)),
                'activated_at': datetime.now().isoformat(),
                'status': 'waiting',
                'original_level': original_level  # Behalte für nächsten Cycle!
            }
            self.waiting_levels.append(waiting_level_data)

            # Füge zur Waiting Table hinzu
            self._add_waiting_level_to_table(waiting_level_data)

            self.log_message(
                f"♻️ Level recycled: {scenario_name} L{level_num} @ Entry: ${waiting_level_data['entry_price']:.2f}",
                "INFO"
            )
        else:
            self.log_message(
                f"⚠️ Level {scenario_name} L{level_num} konnte nicht recycled werden (kein original_level)",
                "WARNING"
            )

    def _move_to_active_levels(self, level_data: dict, fill_price: float, order_id: str, order_info: dict):
        """Verschiebe ein gefülltes Level von Pending zu Active"""

        symbol = level_data['symbol']
        level_type = level_data['type']
        shares = order_info['quantity']
        scenario_name = level_data.get('scenario_name', 'N/A')
        level_num = level_data.get('level_num', 0)

        # Berechne Exit-Preis basierend auf theoretischen Werten
        exit_pct = level_data.get('exit_pct', 0)
        theoretical_exit = level_data.get('exit_price')

        # Extrahiere Entry-Commission aus order_info
        entry_commission = order_info.get('commission', 0.0)

        # Erstelle Active Level
        active_level = {
            'symbol': symbol,
            'type': level_type,
            'scenario_name': scenario_name,
            'level_num': level_num,
            'shares': shares,
            'entry_price': fill_price,
            'exit_price': theoretical_exit,
            'exit_pct': exit_pct,
            'entry_time': datetime.now().isoformat(),
            'entry_order_id': order_id,
            'status': 'active',
            'unrealized_pnl': 0.0,
            'entry_commission': entry_commission,  # IBKR Entry-Commission speichern
            # FIX: Speichere original_level für Recycling nach Exit!
            'original_level': level_data.copy()
        }

        # Füge zu active_levels hinzu
        self.active_levels.append(active_level)

        # Füge zu Active Table hinzu
        row = self.active_table.rowCount()
        self.active_table.insertRow(row)

        # Symbol (Spalte 0)
        self.active_table.setItem(row, 0, QTableWidgetItem(symbol))

        # Typ (Spalte 1)
        type_item = QTableWidgetItem(level_type)
        type_item.setForeground(QColor(0, 128, 0) if level_type == 'LONG' else QColor(128, 0, 0))
        self.active_table.setItem(row, 1, type_item)

        # Einstiegspreis (Spalte 2)
        self.active_table.setItem(row, 2, QTableWidgetItem(f"${fill_price:.2f}"))

        # Zielpreis (Spalte 3)
        if theoretical_exit:
            self.active_table.setItem(row, 3, QTableWidgetItem(f"${theoretical_exit:.2f}"))
        else:
            self.active_table.setItem(row, 3, QTableWidgetItem("N/A"))

        # Aktueller Preis (Spalte 4) - Initial mit Fill-Preis
        self.active_table.setItem(row, 4, QTableWidgetItem(f"${fill_price:.2f}"))

        # Akt. P&L (Spalte 5)
        self.active_table.setItem(row, 5, QTableWidgetItem("$0.00"))

        # Diff. zum Ziel (Spalte 6)
        self.active_table.setItem(row, 6, QTableWidgetItem("--"))

        # Dauer (Spalte 7)
        self.active_table.setItem(row, 7, QTableWidgetItem("0m"))

        # Status (Spalte 8)
        status_item = QTableWidgetItem("Aktiv")
        status_item.setForeground(QColor(0, 128, 0))
        self.active_table.setItem(row, 8, status_item)

        # Szenario (Spalte 9)
        scenario_text = f"{scenario_name} L{level_num}"
        self.active_table.setItem(row, 9, QTableWidgetItem(scenario_text))

        # Update Counter
        self.active_count_label.setText(f"{self.active_table.rowCount()} aktive Levels")

        self.log_message(
            f"📊 LEVEL AKTIV: {scenario_name} L{level_num} - {level_type} {shares}x {symbol} @ ${fill_price:.2f}",
            "SUCCESS"
        )

        # TODO: Optional - Platziere automatische Exit-Order
        # Wenn Auto-Exit aktiviert ist, könnte hier eine Limit-Order für den Exit platziert werden

    def _check_pending_orders_sync(self):
        """Prüft Status aller pending orders (wird von QTimer aufgerufen)"""
        from gridtrader.domain.models.order import OrderStatus

        if not self.live_trading_enabled:
            return

        try:
            for order_id, order_info in list(self.pending_orders.items()):
                try:
                    order_obj = order_info.get('order_object')

                    if not order_obj:
                        continue

                    # Prüfe Status
                    if order_obj.status == OrderStatus.FILLED:
                        # Warte auf Commission Report (kommt separat bei IBKR)
                        # Markiere Order als "filled_pending_commission" beim ersten Mal
                        if not order_info.get('_filled_seen'):
                            order_info['_filled_seen'] = True
                            order_info['_filled_wait_cycles'] = 0
                            continue  # Warte auf nächsten Zyklus für Commission

                        # Warte max 3 Zyklen (3 Sekunden) auf Commission
                        order_info['_filled_wait_cycles'] = order_info.get('_filled_wait_cycles', 0) + 1
                        if order_info['_filled_wait_cycles'] < 3 and not order_obj.commission:
                            continue  # Warte noch auf Commission

                        # Order wurde gefüllt!
                        self.handle_order_filled(order_id, order_info)

                    elif order_obj.status in [OrderStatus.CANCELLED, OrderStatus.REJECTED]:
                        # Order wurde storniert/abgelehnt
                        self.log_message(f"❌ ORDER {order_obj.status}: {order_id}", "ERROR")

                        # NEU: Order-Tracking für dieses Level zurücksetzen,
                        # damit bei erneutem Erreichen des Preises wieder eine Order platziert werden kann
                        level_data = order_info.get("level_data")
                        if level_data:
                            scenario_name = level_data.get("scenario_name", "unknown")
                            level_num = level_data.get("level_num", 0)
                            unique_level_id = f"{scenario_name}_L{level_num}"
                            if hasattr(self, "_orders_placed_for_levels") and unique_level_id in self._orders_placed_for_levels:
                                self._orders_placed_for_levels.discard(unique_level_id)
                                self.log_message(
                                    f"DEBUG: Order-Tracking für {unique_level_id} nach {order_obj.status} zurückgesetzt",
                                    "DEBUG"
                                )

                            # === LEVEL RECYCLING: Füge Level zurück zur Waiting-Liste hinzu ===
                            # Nur für Entry-Orders (Exit-Orders haben is_exit=True)
                            is_exit_order = level_data.get('is_exit', False)
                            original_level = level_data.get('original_level')

                            if not is_exit_order and original_level:
                                # Erstelle neues Waiting Level mit Original-Preisen
                                symbol = level_data.get('symbol', original_level.get('symbol', ''))
                                level_type = level_data.get('type', original_level.get('type', ''))
                                shares = level_data.get('shares', original_level.get('shares', 0))

                                waiting_level_data = {
                                    'scenario_name': original_level.get('scenario_name', scenario_name),
                                    'level_num': original_level.get('level_num', level_num),
                                    'symbol': symbol,
                                    'type': level_type,
                                    'shares': shares,
                                    'entry_pct': original_level.get('entry_pct', 0),
                                    'exit_pct': original_level.get('exit_pct', 0),
                                    'base_price': original_level.get('base_price', level_data.get('entry_price', 0)),
                                    'entry_price': original_level.get('entry_price', level_data.get('entry_price', 0)),
                                    'exit_price': original_level.get('exit_price', level_data.get('exit_price', 0)),
                                    'activated_at': datetime.now().isoformat(),
                                    'status': 'waiting',
                                    'original_level': original_level  # Behalte für nächsten Cycle!
                                }
                                self.waiting_levels.append(waiting_level_data)

                                # Füge zur Waiting Table hinzu
                                self._add_waiting_level_to_table(waiting_level_data)

                                self.log_message(
                                    f"♻️ Level recycled (nach {order_obj.status}): {scenario_name} L{level_num} @ Entry: ${waiting_level_data['entry_price']:.2f}",
                                    "INFO"
                                )
                            elif not is_exit_order:
                                self.log_message(
                                    f"⚠️ Level {scenario_name} L{level_num} konnte nicht recycled werden (kein original_level)",
                                    "WARNING"
                                )

                        self.remove_pending_order(order_id)

                    else:
                        # Update Status in Tabelle
                        order_info['status'] = str(order_obj.status)
                        self.update_pending_display()

                except Exception as e:
                    self.log_message(f"Status-Check Fehler für Order {order_id}: {e}", "ERROR")

        except Exception as e:
            self.log_message(f"Order Status Checker Fehler: {e}", "ERROR")


 
"""
Test Entry Point
"""
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    widget = TradingBotWidget()

    # Test: Füge ein Demo-Szenario hinzu
    demo_config = {
        'type': 'LONG',
        'shares': 100,
        'step': 0.5,
        'exit': 0.7,
        'levels': 5
    }
    demo_result = {
        'symbol': 'AAPL',
        'pnl_percent': 5.2,
        'net_pnl': 520.0
    }
    widget.import_scenario("L_100_0.5_0.7_5", demo_config, demo_result)

    # Zweites Demo-Szenario (SHORT)
    demo_config2 = {
        'type': 'SHORT',
        'shares': 50,
        'step': 0.3,
        'exit': 0.5,
        'levels': 3
    }
    demo_result2 = {
        'symbol': 'AAPL',
        'pnl_percent': 3.1,
        'net_pnl': 310.0
    }
    widget.import_scenario("S_50_0.3_0.5_3", demo_config2, demo_result2)

    widget.resize(1200, 700)
    widget.show()
    sys.exit(app.exec())
