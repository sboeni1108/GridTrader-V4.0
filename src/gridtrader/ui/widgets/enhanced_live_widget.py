"""
Enhanced Live Data Widget mit IBKR Integration - FIXED
"""
from PySide6.QtWidgets import *
from PySide6.QtCore import QTimer, Qt, Signal, QThread
from PySide6.QtGui import QColor, QBrush
from datetime import datetime
import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from gridtrader.ui.dialogs.ibkr_connection_dialog import IBKRConnectionDialog, IBKRConnectionSettings
from gridtrader.infrastructure.brokers.ibkr import set_shared_adapter, clear_shared_adapter

from gridtrader.infrastructure.brokers.ibkr.shared_connection import shared_connection
from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRBrokerAdapter, IBKRConfig


class IBKRDataThread(QThread):
    """Thread für echte IBKR Daten"""
    
    data_received = Signal(dict)
    connection_status = Signal(bool, str)
    error_occurred = Signal(str)
    account_info = Signal(dict)
    
    def __init__(self, settings: IBKRConnectionSettings):
        super().__init__()
        self.settings = settings
        self.adapter = None
        self.symbols = []
        self.running = False
        
    def set_symbols(self, symbols):
        self.symbols = symbols
        print(f"Thread symbols updated: {symbols}")
    
    async def connect_ibkr(self):
        """Verbinde mit IBKR"""
        try:
            # WICHTIG: Konfiguriere shared_connection mit den Benutzereinstellungen
            shared_connection.configure(self.settings)

            # Verwende shared_connection für geteilte Verbindung
            self.adapter = await shared_connection.get_adapter()
            connected = self.adapter.is_connected()
            
            if connected:
                # Setze als shared adapter für andere Module
                set_shared_adapter(self.adapter)
                
                # Hole Account Info - mit Fehlerbehandlung
                try:
                    account_data = await self.adapter.get_account_summary()
                    self.account_info.emit(account_data)
                except Exception as e:
                    print(f"Account info error: {e}")
                
                api_type = self.settings.api_type
                mode = self.settings.mode
                self.connection_status.emit(True, f"Verbunden mit {api_type} ({mode})")
                return True
            else:
                self.connection_status.emit(False, "Verbindung fehlgeschlagen")
                return False
                
        except Exception as e:
            self.connection_status.emit(False, str(e))
            return False
    
    async def fetch_data_loop(self):
        """Hauptschleife für Daten-Abruf"""
        connection_lost_reported = False  # Track ob bereits gemeldet

        while self.running:
            try:
                # Prüfe Verbindungsstatus ZUERST
                if not self.adapter or not self.adapter.is_connected():
                    # Versuche Adapter vom shared_connection neu zu holen
                    # (falls Reconnect stattgefunden hat)
                    try:
                        new_adapter = await shared_connection.get_adapter()
                        if new_adapter and new_adapter.is_connected():
                            self.adapter = new_adapter
                            print("🔄 Adapter vom shared_connection neu geholt")
                            # Verbindung wiederhergestellt - reset flag
                            if connection_lost_reported:
                                print("✅ IBKR Verbindung wiederhergestellt")
                                api_type = getattr(self.settings, 'api_type', 'IBKR')
                                mode = getattr(self.settings, 'mode', 'PAPER')
                                self.connection_status.emit(True, f"Verbunden mit {api_type} ({mode})")
                                connection_lost_reported = False
                            continue  # Weiter mit Daten-Abruf
                    except Exception as e:
                        print(f"⚠️ Konnte Adapter nicht neu holen: {e}")

                    # Immer noch nicht verbunden - melde Verlust
                    if not connection_lost_reported:
                        print("⚠️ IBKR Verbindung verloren im fetch_data_loop")
                        self.connection_status.emit(False, "Verbindung verloren")
                        connection_lost_reported = True
                    await asyncio.sleep(5)  # Warte vor nächstem Check
                    continue

                # Verbindung ist OK - reset flag falls nötig
                if connection_lost_reported:
                    print("✅ IBKR Verbindung wiederhergestellt")
                    api_type = getattr(self.settings, 'api_type', 'IBKR')
                    mode = getattr(self.settings, 'mode', 'PAPER')
                    self.connection_status.emit(True, f"Verbunden mit {api_type} ({mode})")
                    connection_lost_reported = False

                for symbol in self.symbols:
                    # Nochmal prüfen (könnte sich während der Schleife ändern)
                    if not self.adapter or not self.adapter.is_connected():
                        break

                    # Verwende ib_insync direkt ohne extra async
                    try:
                        # Hole Ticker direkt von IB (async!)
                        contract = await self.adapter._get_contract(symbol)
                        ticker = self.adapter.ib.reqMktData(contract, '', False, False)
                        await asyncio.sleep(0.5)  # Kurz warten auf Daten

                        # Extrahiere Werte
                        bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else None
                        ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else None
                        last = float(ticker.last) if ticker.last and ticker.last > 0 else None
                        close = float(ticker.close) if ticker.close and ticker.close > 0 else None
                        high = float(ticker.high) if ticker.high and ticker.high > 0 else None
                        low = float(ticker.low) if ticker.low and ticker.low > 0 else None

                        # Fallback: Wenn kein last verfügbar, verwende close
                        # (z.B. am Wochenende wenn Markt geschlossen)
                        display_price = last if last else close

                        data = {
                            'symbol': symbol,
                            'bid': bid,
                            'ask': ask,
                            'last': display_price,  # Fallback auf close
                            'close': close,
                            'volume': ticker.volume if ticker.volume else 0,
                            'high': high,
                            'low': low,
                            'market_closed': last is None and close is not None  # Info-Flag
                        }

                        # Debug-Ausgabe wenn Markt geschlossen
                        if data['market_closed'] and display_price:
                            print(f"📊 {symbol}: Markt geschlossen - zeige Close: ${display_price:.2f}")

                        self.data_received.emit(data)
                    except Exception as e:
                        print(f"Ticker error {symbol}: {e}")

                await asyncio.sleep(2)  # Alle 2 Sekunden updaten

            except Exception as e:
                print(f"Loop error: {e}")
                await asyncio.sleep(5)
    
    def run(self):
        """Thread Hauptfunktion"""
        self.running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Verbinde
        connected = loop.run_until_complete(self.connect_ibkr())
        
        if connected:
            # Starte Daten-Loop
            loop.run_until_complete(self.fetch_data_loop())
        
        loop.close()
    
    def stop(self):
        """Stoppe Thread sauber"""
        self.running = False
        # Trenne Adapter vollständig über shared_connection
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(shared_connection.clear_adapter())
            loop.close()
        except Exception as e:
            print(f"⚠️ Fehler beim Trennen: {e}")
            # Fallback: Nur globalen Adapter löschen
            clear_shared_adapter()


class EnhancedLiveDataWidget(QWidget):
    """Erweitertes Live Data Widget mit IBKR Integration"""
    
    def __init__(self):
        super().__init__()
        self.ibkr_thread = None
        self.connection_settings = None
        self.watched_symbols = []
        self.is_connected = False
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        
        # Connection Bar
        conn_layout = QHBoxLayout()
        
        self.connection_label = QLabel("🔴 Nicht verbunden")
        self.connection_label.setStyleSheet("font-weight: bold; padding: 5px;")
        conn_layout.addWidget(self.connection_label)
        
        self.account_label = QLabel("")
        conn_layout.addWidget(self.account_label)
        
        conn_layout.addStretch()
        
        self.connect_button = QPushButton("🔌 Mit IBKR verbinden")
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
        self.symbol_input.returnPressed.connect(self._add_symbol)  # Enter-Taste
        symbol_layout.addWidget(self.symbol_input)
        
        self.add_symbol_button = QPushButton("➕ Hinzufügen")
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
        
        # Spalten anpassen
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
    
    def _toggle_connection(self):
        """Toggle Verbindung"""
        if self.is_connected and self.ibkr_thread:
            self._disconnect_ibkr()
        else:
            self._show_connection_dialog()
    
    def _show_connection_dialog(self):
        """Zeige Connection Dialog"""
        dialog = IBKRConnectionDialog(self)
        dialog.connection_requested.connect(self._connect_to_ibkr)
        dialog.exec()
    
    def _connect_to_ibkr(self, settings: IBKRConnectionSettings):
        """Verbinde mit IBKR"""
        self.connection_settings = settings
        
        # UI Update
        self.connection_label.setText("🟡 Verbinde...")
        self.connect_button.setEnabled(False)
        
        # Starte Thread
        self.ibkr_thread = IBKRDataThread(settings)
        self.ibkr_thread.connection_status.connect(self._on_connection_status)
        self.ibkr_thread.data_received.connect(self._update_market_data)
        self.ibkr_thread.error_occurred.connect(self._on_error)
        self.ibkr_thread.account_info.connect(self._update_account_info)
        
        # Setze Symbole falls vorhanden
        if self.watched_symbols:
            self.ibkr_thread.set_symbols(self.watched_symbols)
        
        self.ibkr_thread.start()
    
    def _disconnect_ibkr(self):
        """Trenne Verbindung"""
        if self.ibkr_thread:
            self.ibkr_thread.stop()
            self.ibkr_thread.wait()
            self.ibkr_thread = None
        
        self.is_connected = False
        self.connection_label.setText("🔴 Nicht verbunden")
        self.connect_button.setText("🔌 Mit IBKR verbinden")
        self.connect_button.setEnabled(True)
    
    def _on_connection_status(self, success: bool, message: str):
        """Handle Connection Status"""
        if success:
            self.is_connected = True
            self.connection_label.setText(f"🟢 {message}")
            self.connection_label.setStyleSheet("color: green; font-weight: bold; padding: 5px;")
            self.connect_button.setText("🔌 Trennen")
            self.connect_button.setEnabled(True)
            # Aktiviere Symbol-Eingabe
            self.add_symbol_button.setEnabled(True)
            self.symbol_input.setEnabled(True)
        else:
            self.is_connected = False
            self.connection_label.setText(f"🔴 {message}")
            self.connection_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")
            self.connect_button.setText("🔌 Mit IBKR verbinden")
            self.connect_button.setEnabled(True)
            
            QMessageBox.critical(self, "Verbindungsfehler", message)
    
    def _add_symbol(self):
        """Füge Symbol hinzu"""
        symbol = self.symbol_input.text().upper().strip()
        
        if not symbol:
            return
            
        if not self.is_connected:
            QMessageBox.warning(self, "Warnung", "Bitte erst mit IBKR verbinden!")
            return
        
        if symbol in self.watched_symbols:
            QMessageBox.information(self, "Info", f"{symbol} ist bereits in der Watchlist")
            return
        
        # Füge Symbol hinzu
        self.watched_symbols.append(symbol)
        
        # Update Label
        self.symbol_list_label.setText(", ".join(self.watched_symbols))
        
        # Add to table
        row = self.market_table.rowCount()
        self.market_table.insertRow(row)
        
        for col in range(self.market_table.columnCount()):
            item = QTableWidgetItem(symbol if col == 0 else "--")
            self.market_table.setItem(row, col, item)
        
        # Update Thread
        if self.ibkr_thread and self.ibkr_thread.isRunning():
            self.ibkr_thread.set_symbols(self.watched_symbols)
            print(f"Added symbol: {symbol}")
        
        self.symbol_input.clear()
        self.symbol_input.setFocus()
    
    def _update_market_data(self, data: dict):
        """Update Market Data in Table"""
        symbol = data.get('symbol', '')
        
        # Finde Zeile
        for row in range(self.market_table.rowCount()):
            if self.market_table.item(row, 0) and self.market_table.item(row, 0).text() == symbol:
                # Update Daten mit Null-Checks
                if data.get('bid'):
                    self.market_table.item(row, 1).setText(f"${data['bid']:.2f}")
                if data.get('ask'):
                    self.market_table.item(row, 2).setText(f"${data['ask']:.2f}")
                if data.get('last'):
                    self.market_table.item(row, 3).setText(f"${data['last']:.2f}")
                
                # Change berechnen
                if data.get('last') and data.get('close'):
                    change = data['last'] - data['close']
                    change_pct = (change / data['close']) * 100
                    
                    change_item = QTableWidgetItem(f"${change:+.2f}")
                    change_pct_item = QTableWidgetItem(f"{change_pct:+.2f}%")
                    
                    color = QColor(0, 150, 0) if change >= 0 else QColor(150, 0, 0)
                    change_item.setForeground(QBrush(color))
                    change_pct_item.setForeground(QBrush(color))
                    
                    self.market_table.setItem(row, 4, change_item)
                    self.market_table.setItem(row, 5, change_pct_item)
                
                if data.get('volume'):
                    self.market_table.item(row, 6).setText(f"{data['volume']:,}")
                if data.get('high'):
                    self.market_table.item(row, 7).setText(f"${data['high']:.2f}")
                if data.get('low'):
                    self.market_table.item(row, 8).setText(f"${data['low']:.2f}")
                
                break
    
    def _update_account_info(self, data: dict):
        """Update Account Info"""
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
                # Konvertiere USD zu CHF (ungefähr 1:0.9)
                chf_factor = 0.9
                if 'net_liquidation' in data:
                    chf_capital = data['net_liquidation'] * chf_factor
                    main_window.capital_label.setText(f"💰 Capital: CHF {chf_capital:,.2f}")
                
                chf_pnl = total_pnl * chf_factor
                main_window.pnl_label.setText(f"📊 P&L Today: CHF {chf_pnl:+,.2f}")
        except Exception as e:
            print(f"Dashboard update error: {e}")
    
    def _on_error(self, error_msg: str):
        """Handle Errors - nur kritische anzeigen"""
        print(f"Error: {error_msg}")
        # Zeige nur kritische Fehler
        if "critical" in error_msg.lower() or "failed" in error_msg.lower():
            QMessageBox.critical(self, "IBKR Fehler", error_msg)
