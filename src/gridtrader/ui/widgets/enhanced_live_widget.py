"""
Enhanced Live Data Widget mit IBKR Integration
Verwendet den neuen IBKRService für Event-basierte Architektur
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTableWidget, QTableWidgetItem, QFrame, QMessageBox
)
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QBrush
from datetime import datetime
from typing import Optional, Dict
from gridtrader.ui.styles import (
    TABLE_STYLE, STATUS_CONNECTED_STYLE, STATUS_DISCONNECTED_STYLE,
    apply_table_style, SUCCESS_COLOR, ERROR_COLOR
)

from gridtrader.ui.dialogs.ibkr_connection_dialog import IBKRConnectionDialog, IBKRConnectionSettings
from gridtrader.infrastructure.brokers.ibkr import set_shared_adapter, clear_shared_adapter
from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRConfig

# NEU: Import des IBKRService
try:
    from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service, IBKRService
    IBKR_SERVICE_AVAILABLE = True
except ImportError:
    IBKR_SERVICE_AVAILABLE = False
    get_ibkr_service = None
    IBKRService = None


class EnhancedLiveDataWidget(QWidget):
    """
    Erweitertes Live Data Widget mit IBKR Integration

    Verwendet den IBKRService für:
    - Event-basierte Market Data (Push statt Poll)
    - Thread-sichere Verbindung
    - Keine Event Loop Konflikte mit Qt
    """

    def __init__(self):
        super().__init__()
        self.connection_settings: Optional[IBKRConnectionSettings] = None
        self.watched_symbols = []
        self.is_connected = False

        # IBKRService Referenz
        self._ibkr_service: Optional[IBKRService] = None

        # Market Data Cache für Anzeige
        self._market_data: Dict[str, dict] = {}

        self._setup_ui()
        self._setup_service()

    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)

        # Connection Bar
        conn_layout = QHBoxLayout()

        self.connection_label = QLabel("Nicht verbunden")
        self.connection_label.setStyleSheet("font-weight: bold; padding: 5px;")
        conn_layout.addWidget(self.connection_label)

        self.account_label = QLabel("")
        conn_layout.addWidget(self.account_label)

        conn_layout.addStretch()

        self.connect_button = QPushButton("Mit IBKR verbinden")
        self.connect_button.clicked.connect(self._toggle_connection)
        conn_layout.addWidget(self.connect_button)

        layout.addLayout(conn_layout)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # Symbol Management
        symbol_layout = QHBoxLayout()

        symbol_layout.addWidget(QLabel("Symbol:"))
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("z.B. AAPL, MSFT, TSLA")
        self.symbol_input.setMaximumWidth(150)
        self.symbol_input.returnPressed.connect(self._add_symbol)
        symbol_layout.addWidget(self.symbol_input)

        self.add_symbol_button = QPushButton("Hinzufuegen")
        self.add_symbol_button.clicked.connect(self._add_symbol)
        symbol_layout.addWidget(self.add_symbol_button)

        symbol_layout.addWidget(QLabel("Watchlist:"))
        self.symbol_list_label = QLabel("Keine Symbole")
        symbol_layout.addWidget(self.symbol_list_label)

        symbol_layout.addStretch()

        layout.addLayout(symbol_layout)

        # Market Data Table
        self.market_table = QTableWidget()
        self.market_table.setColumnCount(9)
        self.market_table.setHorizontalHeaderLabels([
            "Symbol", "Bid", "Ask", "Last", "Change", "Change %", "Volume", "High", "Low"
        ])
        apply_table_style(self.market_table)

        header = self.market_table.horizontalHeader()
        header.setStretchLastSection(True)

        layout.addWidget(self.market_table)

        # Account Info Bar
        account_layout = QHBoxLayout()

        self.info_labels = {
            'buying_power': QLabel("Kaufkraft: --"),
            'net_liq': QLabel("Portfolio: --"),
            'cash': QLabel("Cash: --"),
            'pnl': QLabel("P&L: --")
        }

        for label in self.info_labels.values():
            label.setStyleSheet("padding: 5px; font-weight: bold;")
            account_layout.addWidget(label)

        layout.addLayout(account_layout)

    def _setup_service(self):
        """Initialisiere IBKRService"""
        if not IBKR_SERVICE_AVAILABLE:
            print("IBKRService nicht verfuegbar")
            return

        try:
            self._ibkr_service = get_ibkr_service()

            # Verbinde Signals
            self._ibkr_service.signals.connected.connect(self._on_connected)
            self._ibkr_service.signals.disconnected.connect(self._on_disconnected)
            self._ibkr_service.signals.connection_lost.connect(self._on_connection_lost)
            self._ibkr_service.signals.market_data_update.connect(self._on_market_data_update)
            self._ibkr_service.signals.account_update.connect(self._on_account_update)

            print("IBKRService fuer Live Widget initialisiert")

        except Exception as e:
            print(f"IBKRService Setup Fehler: {e}")

    def _toggle_connection(self):
        """Toggle Verbindung"""
        if self.is_connected:
            self._disconnect_ibkr()
        else:
            self._show_connection_dialog()

    def _show_connection_dialog(self):
        """Zeige Connection Dialog"""
        dialog = IBKRConnectionDialog(self)
        dialog.connection_requested.connect(self._connect_to_ibkr)
        dialog.exec()

    def _connect_to_ibkr(self, settings: IBKRConnectionSettings):
        """Verbinde mit IBKR ueber IBKRService"""
        self.connection_settings = settings

        # UI Update
        self.connection_label.setText("Verbinde...")
        self.connection_label.setStyleSheet("color: orange; font-weight: bold; padding: 5px;")
        self.connect_button.setEnabled(False)

        if not self._ibkr_service:
            QMessageBox.critical(self, "Fehler", "IBKRService nicht verfuegbar")
            self._reset_connection_ui()
            return

        # Erstelle IBKRConfig aus Settings
        config = IBKRConfig(
            host=getattr(settings, 'host', '127.0.0.1'),
            port=settings.get_port() if hasattr(settings, 'get_port') else settings.port,
            client_id=getattr(settings, 'client_id', 1),
            account=getattr(settings, 'account', '') or '',
            paper_trading=getattr(settings, 'mode', 'PAPER') == 'PAPER'
        )

        # Verbinde ueber Service (non-blocking!)
        self._ibkr_service.connect(config)

    def _disconnect_ibkr(self):
        """Trenne Verbindung"""
        if self._ibkr_service:
            # Unsubscribe alle Symbole
            if self.watched_symbols:
                self._ibkr_service.unsubscribe_market_data(self.watched_symbols)

            self._ibkr_service.disconnect()

        self._reset_connection_ui()

    def _reset_connection_ui(self):
        """Reset Connection UI"""
        self.is_connected = False
        self.connection_label.setText("Nicht verbunden")
        self.connection_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")
        self.connect_button.setText("Mit IBKR verbinden")
        self.connect_button.setEnabled(True)

    def _on_connected(self, success: bool, message: str):
        """Callback wenn Verbindung hergestellt"""
        self.connect_button.setEnabled(True)

        if success:
            self.is_connected = True
            self.connection_label.setText(f"Verbunden: {message}")
            self.connection_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
            self.connect_button.setText("Trennen")

            # Aktiviere Symbol-Eingabe
            self.add_symbol_button.setEnabled(True)
            self.symbol_input.setEnabled(True)

            # Re-subscribe bereits hinzugefuegte Symbole
            if self.watched_symbols:
                self._ibkr_service.subscribe_market_data(self.watched_symbols)

            # Account Info anfordern
            self._ibkr_service.request_account_update()

        else:
            self._reset_connection_ui()
            QMessageBox.critical(self, "Verbindungsfehler", message)

    def _on_disconnected(self):
        """Callback wenn Verbindung getrennt"""
        self._reset_connection_ui()

    def _on_connection_lost(self):
        """Callback wenn Verbindung verloren"""
        self.is_connected = False
        self.connection_label.setText("Verbindung verloren!")
        self.connection_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")

    def _add_symbol(self):
        """Fuege Symbol hinzu"""
        symbol = self.symbol_input.text().upper().strip()

        if not symbol:
            return

        if not self.is_connected:
            QMessageBox.warning(self, "Warnung", "Bitte erst mit IBKR verbinden!")
            return

        if symbol in self.watched_symbols:
            QMessageBox.information(self, "Info", f"{symbol} ist bereits in der Watchlist")
            return

        # Fuege Symbol hinzu
        self.watched_symbols.append(symbol)

        # Update Label
        self.symbol_list_label.setText(", ".join(self.watched_symbols))

        # Add to table
        row = self.market_table.rowCount()
        self.market_table.insertRow(row)

        for col in range(self.market_table.columnCount()):
            item = QTableWidgetItem(symbol if col == 0 else "--")
            self.market_table.setItem(row, col, item)

        # Subscribe bei Service
        if self._ibkr_service and self.is_connected:
            self._ibkr_service.subscribe_market_data([symbol])
            print(f"Symbol subscribed: {symbol}")

        self.symbol_input.clear()
        self.symbol_input.setFocus()

    def _on_market_data_update(self, data: dict):
        """Callback fuer Market Data Updates (PUSH vom Service)"""
        symbol = data.get('symbol', '')
        if not symbol or symbol not in self.watched_symbols:
            return

        # Cache aktualisieren
        self._market_data[symbol] = data

        # Finde Zeile
        for row in range(self.market_table.rowCount()):
            if self.market_table.item(row, 0) and self.market_table.item(row, 0).text() == symbol:
                # Update Daten mit Null-Checks
                bid = data.get('bid', 0)
                ask = data.get('ask', 0)
                last = data.get('last', 0)
                close = data.get('close', 0)
                volume = data.get('volume', 0)
                high = data.get('high', 0)
                low = data.get('low', 0)

                if bid and bid > 0:
                    self.market_table.item(row, 1).setText(f"${bid:.2f}")
                if ask and ask > 0:
                    self.market_table.item(row, 2).setText(f"${ask:.2f}")
                if last and last > 0:
                    self.market_table.item(row, 3).setText(f"${last:.2f}")

                # Change berechnen
                if last and last > 0 and close and close > 0:
                    change = last - close
                    change_pct = (change / close) * 100

                    change_item = QTableWidgetItem(f"${change:+.2f}")
                    change_pct_item = QTableWidgetItem(f"{change_pct:+.2f}%")

                    color = QColor(0, 150, 0) if change >= 0 else QColor(150, 0, 0)
                    change_item.setForeground(QBrush(color))
                    change_pct_item.setForeground(QBrush(color))

                    self.market_table.setItem(row, 4, change_item)
                    self.market_table.setItem(row, 5, change_pct_item)

                if volume and volume > 0:
                    self.market_table.item(row, 6).setText(f"{int(volume):,}")
                if high and high > 0:
                    self.market_table.item(row, 7).setText(f"${high:.2f}")
                if low and low > 0:
                    self.market_table.item(row, 8).setText(f"${low:.2f}")

                break

    def _on_account_update(self, data: dict):
        """Callback fuer Account Updates"""
        # Update Live Widget Labels
        if 'buying_power' in data:
            self.info_labels['buying_power'].setText(f"Kaufkraft: ${data['buying_power']:,.2f}")
        if 'net_liquidation' in data:
            self.info_labels['net_liq'].setText(f"Portfolio: ${data['net_liquidation']:,.2f}")
        if 'cash' in data:
            self.info_labels['cash'].setText(f"Cash: ${data['cash']:,.2f}")

        # Berechne P&L
        total_pnl = 0
        if 'positions' in data:
            for pos in data['positions']:
                if isinstance(pos, dict) and 'unrealized_pnl' in pos:
                    total_pnl += pos.get('unrealized_pnl', 0)
            self.info_labels['pnl'].setText(f"P&L: ${total_pnl:+,.2f}")

        # Update Dashboard im Main Window
        try:
            main_window = self.parent()
            while main_window and not hasattr(main_window, 'capital_label'):
                main_window = main_window.parent()

            if main_window and hasattr(main_window, 'capital_label'):
                # Konvertiere USD zu CHF (ungefaehr 1:0.9)
                chf_factor = 0.9
                if 'net_liquidation' in data:
                    chf_capital = data['net_liquidation'] * chf_factor
                    main_window.capital_label.setText(f"Capital: CHF {chf_capital:,.2f}")

                chf_pnl = total_pnl * chf_factor
                main_window.pnl_label.setText(f"P&L Today: CHF {chf_pnl:+,.2f}")
        except Exception as e:
            print(f"Dashboard update error: {e}")

    def closeEvent(self, event):
        """Cleanup beim Schliessen"""
        if self._ibkr_service and self.watched_symbols:
            self._ibkr_service.unsubscribe_market_data(self.watched_symbols)
        super().closeEvent(event)
