"""GridTrader V2.0 Main Window"""
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QAction, QColor
from datetime import datetime
from pathlib import Path
import subprocess
import platform
import os
from gridtrader.ui.widgets.enhanced_live_widget import EnhancedLiveDataWidget
from gridtrader.ui.widgets.advanced_backtest_widget import AdvancedBacktestWidget
from gridtrader.ui.widgets.trading_bot_widget import TradingBotWidget
from gridtrader.ui.widgets.ibkr_trading_widget import IBKRTradingWidget
from gridtrader.infrastructure.brokers.ibkr.shared_connection import shared_connection
from gridtrader.ui.styles import (
    TITLE_STYLE, GROUPBOX_STYLE, TABLE_STYLE, TAB_STYLE, LIST_STYLE,
    STATUSBAR_STYLE, apply_table_style, apply_groupbox_style, apply_list_style,
    apply_title_style, SUCCESS_COLOR, ERROR_COLOR
)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GridTrader V2.0 - Professional Grid Trading Software")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central Widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Connection Warning Banner (hidden by default)
        self._create_connection_banner(layout)

        # Tab Widget mit Styling
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TAB_STYLE)
        layout.addWidget(self.tabs)
        
        # Create all tabs
        self._create_dashboard()
        self._create_analyse()
        self._create_backtest()
        self._create_trading_bot()
        self._create_live()
        self._create_trading()
        self._create_reports()
        
        # Menu
        self._create_menu()
        
        # Status Bar
        self.statusBar().showMessage("GridTrader V2.0 - Bereit")

        # Connect to connection monitor signals
        self._setup_connection_monitoring()
        
    def _create_dashboard(self):
        dashboard = QWidget()
        layout = QVBoxLayout(dashboard)

        # Title and Status Bar
        header_layout = QHBoxLayout()
        title = QLabel("📊 GridTrader Dashboard")
        apply_title_style(title)
        header_layout.addWidget(title)

        # Status indicators
        self.capital_label = QLabel("💰 Capital: CHF --")
        header_layout.addWidget(self.capital_label)
        self.pnl_label = QLabel("📊 P&L Today: CHF --")
        header_layout.addWidget(self.pnl_label)

        header_layout.addStretch()

        # Manual save button
        save_logs_btn = QPushButton("💾 Logs Schreiben")
        save_logs_btn.setToolTip("Speichert alle Logs sofort (Auto-Save läuft alle 5 Min)")
        save_logs_btn.clicked.connect(self._save_logs_manually)
        header_layout.addWidget(save_logs_btn)

        layout.addLayout(header_layout)

        # ============================================
        # 1. TOP PANEL: Stock Information
        # ============================================
        stock_group = QGroupBox("Aktien-Information (Symbole mit wartenden/aktiven Levels)")
        apply_groupbox_style(stock_group)
        stock_layout = QVBoxLayout()

        self.dashboard_stock_table = QTableWidget()
        self.dashboard_stock_table.setColumnCount(9)
        self.dashboard_stock_table.setHorizontalHeaderLabels([
            "Symbol", "Bid", "Ask", "Last", "Change", "Change %", "Volume", "High", "Low"
        ])
        apply_table_style(self.dashboard_stock_table)
        self.dashboard_stock_table.horizontalHeader().setStretchLastSection(True)
        self.dashboard_stock_table.setMaximumHeight(150)
        stock_layout.addWidget(self.dashboard_stock_table)

        stock_group.setLayout(stock_layout)
        layout.addWidget(stock_group)

        # ============================================
        # 2. MIDDLE PANEL: Active Levels
        # ============================================
        levels_group = QGroupBox("Aktive Levels")
        apply_groupbox_style(levels_group)
        levels_layout = QVBoxLayout()

        self.dashboard_levels_table = QTableWidget()
        self.dashboard_levels_table.setColumnCount(10)
        self.dashboard_levels_table.setHorizontalHeaderLabels([
            "Symbol", "Typ", "Anzahl", "Einstieg", "Ziel", "Akt. Preis",
            "P&L", "Diff. zum Ziel", "Dauer", "Szenario"
        ])
        apply_table_style(self.dashboard_levels_table)
        self.dashboard_levels_table.horizontalHeader().setStretchLastSection(True)
        levels_layout.addWidget(self.dashboard_levels_table)

        levels_group.setLayout(levels_layout)
        layout.addWidget(levels_group)

        # ============================================
        # 3. BOTTOM PANEL: Executed Trades
        # ============================================
        trades_group = QGroupBox("Ausgeführte Trades")
        apply_groupbox_style(trades_group)
        trades_layout = QVBoxLayout()

        self.dashboard_trades_table = QTableWidget()
        self.dashboard_trades_table.setColumnCount(9)
        self.dashboard_trades_table.setHorizontalHeaderLabels([
            "Zeit", "Symbol", "Level", "Typ", "Seite", "Anzahl", "Preis", "Total", "Kommission"
        ])
        apply_table_style(self.dashboard_trades_table)
        self.dashboard_trades_table.horizontalHeader().setStretchLastSection(True)
        self.dashboard_trades_table.setMaximumHeight(250)
        trades_layout.addWidget(self.dashboard_trades_table)

        trades_group.setLayout(trades_layout)
        layout.addWidget(trades_group)

        # Initialize trades list
        self.dashboard_trades = []

        self.tabs.addTab(dashboard, "Dashboard")

    def update_dashboard_stocks(self, symbols_data: dict):
        """Update Dashboard stock information table

        Args:
            symbols_data: Dict with symbol -> market data
        """
        if not hasattr(self, 'dashboard_stock_table'):
            return

        self.dashboard_stock_table.setRowCount(len(symbols_data))

        for row, (symbol, data) in enumerate(symbols_data.items()):
            # Symbol
            self.dashboard_stock_table.setItem(row, 0, QTableWidgetItem(symbol))

            # Bid, Ask, Last
            self.dashboard_stock_table.setItem(row, 1, QTableWidgetItem(f"${data.get('bid', 0):.2f}"))
            self.dashboard_stock_table.setItem(row, 2, QTableWidgetItem(f"${data.get('ask', 0):.2f}"))
            self.dashboard_stock_table.setItem(row, 3, QTableWidgetItem(f"${data.get('last', 0):.2f}"))

            # Change and Change %
            change = data.get('change', 0)
            change_pct = data.get('change_pct', 0)

            change_item = QTableWidgetItem(f"${change:+.2f}")
            change_pct_item = QTableWidgetItem(f"{change_pct:+.2f}%")

            color = QColor(0, 128, 0) if change >= 0 else QColor(200, 0, 0)
            change_item.setForeground(color)
            change_pct_item.setForeground(color)

            self.dashboard_stock_table.setItem(row, 4, change_item)
            self.dashboard_stock_table.setItem(row, 5, change_pct_item)

            # Volume, High, Low
            self.dashboard_stock_table.setItem(row, 6, QTableWidgetItem(f"{data.get('volume', 0):,}"))
            self.dashboard_stock_table.setItem(row, 7, QTableWidgetItem(f"${data.get('high', 0):.2f}"))
            self.dashboard_stock_table.setItem(row, 8, QTableWidgetItem(f"${data.get('low', 0):.2f}"))

    def update_dashboard_levels(self, active_levels: list):
        """Update Dashboard active levels table

        Args:
            active_levels: List of active level dictionaries
        """
        if not hasattr(self, 'dashboard_levels_table'):
            return

        self.dashboard_levels_table.setRowCount(len(active_levels))

        for row, level in enumerate(active_levels):
            symbol = level.get('symbol', 'N/A')
            level_type = level.get('type', 'N/A')
            shares = level.get('shares', 0)
            entry_price = level.get('entry_price', 0)
            exit_price = level.get('exit_price', 0)
            current_price = level.get('current_price', entry_price)
            scenario = level.get('scenario_name', 'N/A')
            level_num = level.get('level_num', 0)
            entry_time = level.get('entry_time', '')

            # Calculate P&L
            if level_type == 'LONG':
                pnl = (current_price - entry_price) * shares
                diff_to_target = exit_price - current_price
            else:  # SHORT
                pnl = (entry_price - current_price) * shares
                diff_to_target = current_price - exit_price

            # Calculate duration
            duration = "--"
            if entry_time:
                try:
                    entry_dt = datetime.fromisoformat(entry_time)
                    duration_mins = int((datetime.now() - entry_dt).total_seconds() / 60)
                    if duration_mins < 60:
                        duration = f"{duration_mins}m"
                    else:
                        duration = f"{duration_mins // 60}h {duration_mins % 60}m"
                except:
                    pass

            # Symbol
            self.dashboard_levels_table.setItem(row, 0, QTableWidgetItem(symbol))

            # Type with color
            type_item = QTableWidgetItem(level_type)
            type_item.setForeground(QColor(0, 128, 0) if level_type == 'LONG' else QColor(200, 0, 0))
            self.dashboard_levels_table.setItem(row, 1, type_item)

            # Shares
            self.dashboard_levels_table.setItem(row, 2, QTableWidgetItem(str(shares)))

            # Entry, Target, Current
            self.dashboard_levels_table.setItem(row, 3, QTableWidgetItem(f"${entry_price:.2f}"))
            self.dashboard_levels_table.setItem(row, 4, QTableWidgetItem(f"${exit_price:.2f}"))
            self.dashboard_levels_table.setItem(row, 5, QTableWidgetItem(f"${current_price:.2f}"))

            # P&L with color
            pnl_item = QTableWidgetItem(f"${pnl:+.2f}")
            pnl_item.setForeground(QColor(0, 128, 0) if pnl >= 0 else QColor(200, 0, 0))
            self.dashboard_levels_table.setItem(row, 6, pnl_item)

            # Diff to target
            self.dashboard_levels_table.setItem(row, 7, QTableWidgetItem(f"${diff_to_target:.2f}"))

            # Duration
            self.dashboard_levels_table.setItem(row, 8, QTableWidgetItem(duration))

            # Scenario
            self.dashboard_levels_table.setItem(row, 9, QTableWidgetItem(f"{scenario} L{level_num}"))

    def add_dashboard_trade(self, trade_data: dict):
        """Add a trade to the Dashboard trades table

        Args:
            trade_data: Dict with trade information:
                - timestamp: Zeit des Trades
                - symbol: Aktien-Symbol
                - level: Level-Name (z.B. "Scenario1 L2")
                - type: LONG oder SHORT
                - side: BUY oder SELL
                - shares: Anzahl Aktien
                - price: Ausführungspreis
                - total: Gesamtkosten (shares * price)
                - commission: Kommission
        """
        if not hasattr(self, 'dashboard_trades_table'):
            return

        # Add to list (most recent first)
        self.dashboard_trades.insert(0, trade_data)

        # Limit to 100 trades
        if len(self.dashboard_trades) > 100:
            self.dashboard_trades = self.dashboard_trades[:100]

        # Update table
        self.dashboard_trades_table.setRowCount(len(self.dashboard_trades))

        for row, trade in enumerate(self.dashboard_trades):
            # Zeit
            timestamp = trade.get('timestamp', datetime.now().strftime('%H:%M:%S'))
            if isinstance(timestamp, str) and 'T' in timestamp:
                timestamp = timestamp.split('T')[1][:8]
            self.dashboard_trades_table.setItem(row, 0, QTableWidgetItem(str(timestamp)))

            # Symbol
            self.dashboard_trades_table.setItem(row, 1, QTableWidgetItem(trade.get('symbol', 'N/A')))

            # Level (Scenario + Level Nummer)
            level_name = trade.get('level', 'N/A')
            self.dashboard_trades_table.setItem(row, 2, QTableWidgetItem(level_name))

            # Typ (LONG/SHORT) mit Farbe
            trade_type = trade.get('type', 'N/A')
            type_item = QTableWidgetItem(trade_type)
            type_item.setForeground(QColor(0, 128, 0) if trade_type == 'LONG' else QColor(200, 0, 0))
            self.dashboard_trades_table.setItem(row, 3, type_item)

            # Side (Buy/Sell) mit Farbe
            side = trade.get('side', 'N/A')
            side_item = QTableWidgetItem(side)
            side_item.setForeground(QColor(0, 128, 0) if side == 'BUY' else QColor(200, 0, 0))
            self.dashboard_trades_table.setItem(row, 4, side_item)

            # Anzahl Aktien
            shares = trade.get('shares', 0)
            self.dashboard_trades_table.setItem(row, 5, QTableWidgetItem(str(shares)))

            # Preis
            price = trade.get('price', 0)
            self.dashboard_trades_table.setItem(row, 6, QTableWidgetItem(f"${price:.2f}"))

            # Total (shares * price)
            total = trade.get('total', shares * price)
            self.dashboard_trades_table.setItem(row, 7, QTableWidgetItem(f"${total:.2f}"))

            # Kommission
            commission = trade.get('commission', 0)
            self.dashboard_trades_table.setItem(row, 8, QTableWidgetItem(f"${commission:.2f}"))
        
    def _create_analyse(self):
        analyse = QWidget()
        layout = QVBoxLayout(analyse)
        
        # Input
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Symbol:"))
        input_layout.addWidget(QLineEdit("AAPL"))
        input_layout.addWidget(QLabel("Side:"))
        
        side_combo = QComboBox()
        side_combo.addItems(["LONG", "SHORT"])
        input_layout.addWidget(side_combo)
        
        input_layout.addWidget(QLabel("Levels:"))
        levels = QSpinBox()
        levels.setRange(2, 100)
        levels.setValue(5)
        input_layout.addWidget(levels)
        
        input_layout.addWidget(QPushButton("🔍 Analyse"))
        input_layout.addStretch()
        
        layout.addLayout(input_layout)
        
        # Results
        results = QTextEdit()
        results.setPlaceholderText("Analysis results will appear here...")
        layout.addWidget(results)
        
        self.tabs.addTab(analyse, "Analyse")
        
    def _create_backtest(self):
        # Use Backtest Widget
        self.backtest_widget = AdvancedBacktestWidget()
        self.tabs.addTab(self.backtest_widget, "Backtest")

    def _create_trading_bot(self):
        # Use Trading Bot Widget
        self.trading_bot_widget = TradingBotWidget()
        self.tabs.addTab(self.trading_bot_widget, "Trading-Bot")

        # Verbinde Export-Signal vom Backtest zum Trading-Bot (Mehrfachauswahl)
        if hasattr(self, 'backtest_widget'):
            self.backtest_widget.export_to_trading_bot.connect(
                self.trading_bot_widget.import_scenarios
            )

    def _create_live(self):
        # Use the Live Data Widget
        live_widget = EnhancedLiveDataWidget()
        self.tabs.addTab(live_widget, "Live Data")

    def _create_trading(self):
        # Use the IBKR Trading Widget
        trading_widget = IBKRTradingWidget()
        self.tabs.addTab(trading_widget, "Live Trading")

    def _create_reports(self):
        reports = QWidget()
        layout = QVBoxLayout(reports)

        # Logs directory
        self.logs_dir = Path.home() / ".gridtrader" / "logs"

        # Title
        title = QLabel("📋 Trading Logs & Reports")
        apply_title_style(title)
        layout.addWidget(title)

        # Action buttons
        buttons_layout = QHBoxLayout()

        refresh_btn = QPushButton("🔄 Aktualisieren")
        refresh_btn.clicked.connect(self._refresh_log_lists)
        buttons_layout.addWidget(refresh_btn)

        open_excel_btn = QPushButton("📊 In Excel öffnen")
        open_excel_btn.clicked.connect(self._open_selected_in_excel)
        buttons_layout.addWidget(open_excel_btn)

        email_btn = QPushButton("📧 Per E-Mail senden")
        email_btn.clicked.connect(self._email_selected_logs)
        buttons_layout.addWidget(email_btn)

        open_folder_btn = QPushButton("📁 Ordner öffnen")
        open_folder_btn.clicked.connect(self._open_logs_folder)
        buttons_layout.addWidget(open_folder_btn)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        # ============================================
        # TOP PANEL: Daily Logs
        # ============================================
        daily_group = QGroupBox("Tages-Logs")
        apply_groupbox_style(daily_group)
        daily_layout = QVBoxLayout()

        self.daily_logs_list = QListWidget()
        apply_list_style(self.daily_logs_list)
        self.daily_logs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.daily_logs_list.setMinimumHeight(200)
        daily_layout.addWidget(self.daily_logs_list)

        daily_group.setLayout(daily_layout)
        layout.addWidget(daily_group)

        # ============================================
        # BOTTOM PANEL: Yearly Logs
        # ============================================
        yearly_group = QGroupBox("Jahres-Logs")
        apply_groupbox_style(yearly_group)
        yearly_layout = QVBoxLayout()

        self.yearly_logs_list = QListWidget()
        apply_list_style(self.yearly_logs_list)
        self.yearly_logs_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.yearly_logs_list.setMinimumHeight(150)
        yearly_layout.addWidget(self.yearly_logs_list)

        yearly_group.setLayout(yearly_layout)
        layout.addWidget(yearly_group)

        # Status label
        self.logs_status_label = QLabel("")
        layout.addWidget(self.logs_status_label)

        self.tabs.addTab(reports, "Logs - Reports")

        # Initial load of log files
        QTimer.singleShot(100, self._refresh_log_lists)

    def _refresh_log_lists(self):
        """Refresh the lists of log files"""
        self.daily_logs_list.clear()
        self.yearly_logs_list.clear()

        if not self.logs_dir.exists():
            self.logs_status_label.setText("Log-Verzeichnis nicht gefunden")
            return

        # Get all Excel files
        excel_files = list(self.logs_dir.glob("*.xlsx"))

        daily_files = []
        yearly_files = []

        for file in excel_files:
            filename = file.name

            # Check if it's a daily or yearly file
            if "Tagestrades" in filename or "Tages PL" in filename:
                daily_files.append(file)
            elif "Jahrestrades" in filename or "Jahres PL" in filename:
                yearly_files.append(file)

        # Sort by modification time (newest first)
        daily_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        yearly_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # Add to daily list
        for file in daily_files:
            item = QListWidgetItem(file.name)
            item.setData(Qt.UserRole, str(file))
            self.daily_logs_list.addItem(item)

        # Add to yearly list
        for file in yearly_files:
            item = QListWidgetItem(file.name)
            item.setData(Qt.UserRole, str(file))
            self.yearly_logs_list.addItem(item)

        total_files = len(daily_files) + len(yearly_files)
        self.logs_status_label.setText(f"{total_files} Log-Dateien gefunden ({len(daily_files)} Tages, {len(yearly_files)} Jahres)")

    def _get_selected_files(self) -> list:
        """Get all selected files from both lists"""
        selected_files = []

        # From daily list
        for item in self.daily_logs_list.selectedItems():
            file_path = item.data(Qt.UserRole)
            if file_path:
                selected_files.append(Path(file_path))

        # From yearly list
        for item in self.yearly_logs_list.selectedItems():
            file_path = item.data(Qt.UserRole)
            if file_path:
                selected_files.append(Path(file_path))

        return selected_files

    def _open_selected_in_excel(self):
        """Open selected log files in Excel"""
        selected_files = self._get_selected_files()

        if not selected_files:
            QMessageBox.warning(self, "Keine Auswahl", "Bitte wählen Sie mindestens eine Datei aus.")
            return

        opened_count = 0
        for file_path in selected_files:
            if file_path.exists():
                try:
                    if platform.system() == 'Windows':
                        os.startfile(str(file_path))
                    elif platform.system() == 'Darwin':  # macOS
                        subprocess.run(['open', str(file_path)])
                    else:  # Linux
                        subprocess.run(['xdg-open', str(file_path)])
                    opened_count += 1
                except Exception as e:
                    QMessageBox.warning(self, "Fehler", f"Fehler beim Öffnen von {file_path.name}: {e}")

        if opened_count > 0:
            self.logs_status_label.setText(f"{opened_count} Datei(en) in Excel geöffnet")

    def _email_selected_logs(self):
        """Prepare email with selected log files as attachments"""
        selected_files = self._get_selected_files()

        if not selected_files:
            QMessageBox.warning(self, "Keine Auswahl", "Bitte wählen Sie mindestens eine Datei aus.")
            return

        # Create mailto link with file paths in body
        # Note: mailto doesn't support attachments directly, so we show a dialog
        file_names = [f.name for f in selected_files]
        file_paths = [str(f) for f in selected_files]

        # Show dialog with file paths for manual attachment
        dialog = QDialog(self)
        dialog.setWindowTitle("E-Mail senden")
        dialog.setMinimumWidth(500)

        dialog_layout = QVBoxLayout(dialog)

        # Info label
        info = QLabel("Ausgewählte Dateien für E-Mail-Anhang:")
        info.setStyleSheet("font-weight: bold;")
        dialog_layout.addWidget(info)

        # File list
        file_list = QTextEdit()
        file_list.setReadOnly(True)
        file_list.setPlainText("\n".join(file_paths))
        file_list.setMaximumHeight(150)
        dialog_layout.addWidget(file_list)

        # Instructions
        instructions = QLabel(
            "Sie können:\n"
            "1. Die Dateipfade kopieren und manuell an eine E-Mail anhängen\n"
            "2. Oder 'Standard-Mail-App öffnen' klicken und die Dateien manuell anhängen"
        )
        dialog_layout.addWidget(instructions)

        # Buttons
        btn_layout = QHBoxLayout()

        copy_btn = QPushButton("📋 Pfade kopieren")
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard("\n".join(file_paths)))
        btn_layout.addWidget(copy_btn)

        mail_btn = QPushButton("📧 Mail-App öffnen")
        mail_btn.clicked.connect(lambda: self._open_mail_app(file_names))
        btn_layout.addWidget(mail_btn)

        close_btn = QPushButton("Schließen")
        close_btn.clicked.connect(dialog.close)
        btn_layout.addWidget(close_btn)

        dialog_layout.addLayout(btn_layout)

        dialog.exec()

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.logs_status_label.setText("Pfade in Zwischenablage kopiert")

    def _open_mail_app(self, file_names: list):
        """Open default mail application"""
        import webbrowser

        subject = f"GridTrader Trading Logs - {datetime.now().strftime('%Y-%m-%d')}"
        body = f"Anbei die folgenden Trading Logs:\n\n" + "\n".join(f"- {name}" for name in file_names)
        body += "\n\nBitte die Dateien manuell anhängen."

        # URL encode
        import urllib.parse
        mailto_url = f"mailto:?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"

        webbrowser.open(mailto_url)
        self.logs_status_label.setText("Mail-App geöffnet")

    def _open_logs_folder(self):
        """Open the logs folder in file explorer"""
        if not self.logs_dir.exists():
            self.logs_dir.mkdir(parents=True, exist_ok=True)

        try:
            if platform.system() == 'Windows':
                os.startfile(str(self.logs_dir))
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', str(self.logs_dir)])
            else:  # Linux
                subprocess.run(['xdg-open', str(self.logs_dir)])

            self.logs_status_label.setText("Log-Ordner geöffnet")
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Fehler beim Öffnen des Ordners: {e}")
        
    def _create_menu(self):
        menubar = self.menuBar()
        
        # File Menu
        file_menu = menubar.addMenu("File")
        
        new_action = QAction("New Cycle", self)
        new_action.setShortcut("Ctrl+N")
        file_menu.addAction(new_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools Menu
        tools_menu = menubar.addMenu("Tools")
        tools_menu.addAction("Connect IBKR")
        tools_menu.addAction("Settings")
        
        # Help Menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("Documentation")
        help_menu.addAction("About")
    def update_account_display(self, net_liq, pnl):
        """Update Dashboard Account Info"""
        if hasattr(self, 'capital_label'):
            self.capital_label.setText(f"💰 Capital: CHF {net_liq:,.2f}")
        if hasattr(self, 'pnl_label'):
            self.pnl_label.setText(f"📊 P&L Today: CHF {pnl:+,.2f}")

    def _save_logs_manually(self):
        """Manuell Logs speichern via Dashboard Button"""
        if hasattr(self, 'trading_bot_widget'):
            if self.trading_bot_widget.save_logs_now():
                QMessageBox.information(self, "Logs gespeichert",
                    "Trading Logs wurden erfolgreich gespeichert.\n\n"
                    "Hinweis: Auto-Save läuft automatisch alle 5 Minuten.")
            else:
                QMessageBox.warning(self, "Fehler",
                    "Logs konnten nicht gespeichert werden.\n"
                    "Prüfen Sie das Log-Fenster für Details.")
        else:
            QMessageBox.warning(self, "Nicht verfügbar",
                "Trading-Bot Widget nicht gefunden.")

    def _create_connection_banner(self, parent_layout):
        """Erstelle das Verbindungs-Warnbanner"""
        # Banner Container
        self.connection_banner = QFrame()
        self.connection_banner.setFrameStyle(QFrame.StyledPanel)
        self.connection_banner.setStyleSheet("""
            QFrame {
                background-color: #ff6b6b;
                border: 2px solid #c92a2a;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
            QLabel {
                color: white;
                font-weight: bold;
            }
        """)

        banner_layout = QHBoxLayout(self.connection_banner)
        banner_layout.setContentsMargins(15, 10, 15, 10)

        # Warning Icon
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 24px;")
        banner_layout.addWidget(icon_label)

        # Message Label
        self.connection_message = QLabel("IBKR Verbindung verloren!")
        self.connection_message.setStyleSheet("font-size: 14px;")
        banner_layout.addWidget(self.connection_message)

        # Status Label (for reconnection attempts)
        self.reconnect_status = QLabel("")
        self.reconnect_status.setStyleSheet("font-size: 12px;")
        banner_layout.addWidget(self.reconnect_status)

        banner_layout.addStretch()

        # Manual reconnect button
        self.manual_reconnect_btn = QPushButton("Jetzt verbinden")
        self.manual_reconnect_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #c92a2a;
                border: none;
                padding: 5px 15px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #f1f1f1;
            }
        """)
        self.manual_reconnect_btn.clicked.connect(self._manual_reconnect)
        banner_layout.addWidget(self.manual_reconnect_btn)

        # Hide banner initially
        self.connection_banner.hide()

        # Add to layout at top
        parent_layout.addWidget(self.connection_banner)

    def _setup_connection_monitoring(self):
        """Verbinde mit den Connection Monitor Signalen"""
        monitor = shared_connection.get_monitor()
        if monitor:
            monitor.connection_lost.connect(self._on_connection_lost)
            monitor.connection_restored.connect(self._on_connection_restored)
            monitor.reconnecting.connect(self._on_reconnecting)
            monitor.reconnect_failed.connect(self._on_reconnect_failed)
            monitor.status_changed.connect(self._on_connection_status_changed)

    def _on_connection_lost(self):
        """Handler wenn Verbindung verloren"""
        self.connection_banner.setStyleSheet("""
            QFrame {
                background-color: #ff6b6b;
                border: 2px solid #c92a2a;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
            QLabel {
                color: white;
                font-weight: bold;
            }
        """)
        self.connection_message.setText("IBKR Verbindung verloren!")
        self.reconnect_status.setText("Versuche automatische Wiederverbindung...")
        self.manual_reconnect_btn.show()
        self.connection_banner.show()
        self.statusBar().showMessage("⚠️ IBKR Verbindung verloren - Wiederverbindung läuft...")

    def _on_connection_restored(self):
        """Handler wenn Verbindung wiederhergestellt"""
        # Kurz grüne Erfolgsmeldung zeigen
        self.connection_banner.setStyleSheet("""
            QFrame {
                background-color: #51cf66;
                border: 2px solid #2f9e44;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
            QLabel {
                color: white;
                font-weight: bold;
            }
        """)
        self.connection_message.setText("✅ IBKR Verbindung wiederhergestellt!")
        self.reconnect_status.setText("")
        self.manual_reconnect_btn.hide()
        self.statusBar().showMessage("✅ IBKR Verbindung wiederhergestellt")

        # Banner nach 5 Sekunden ausblenden
        QTimer.singleShot(5000, self.connection_banner.hide)

    def _on_reconnecting(self, attempt: int):
        """Handler während Wiederverbindungsversuchen"""
        self.reconnect_status.setText(f"Versuch {attempt}/5...")
        self.statusBar().showMessage(f"🔄 Wiederverbindung Versuch {attempt}/5...")

    def _on_reconnect_failed(self, error_msg: str):
        """Handler wenn alle Wiederverbindungsversuche fehlgeschlagen"""
        self.connection_banner.setStyleSheet("""
            QFrame {
                background-color: #c92a2a;
                border: 2px solid #862e2e;
                border-radius: 8px;
                padding: 10px;
                margin: 5px;
            }
            QLabel {
                color: white;
                font-weight: bold;
            }
        """)
        self.connection_message.setText("❌ IBKR Wiederverbindung fehlgeschlagen!")
        self.reconnect_status.setText("Bitte manuell verbinden")
        self.manual_reconnect_btn.show()
        self.statusBar().showMessage(f"❌ {error_msg}")

    def _on_connection_status_changed(self, status: str):
        """Handler für allgemeine Statusänderungen"""
        # Update Status Bar
        self.statusBar().showMessage(status)

    def _manual_reconnect(self):
        """Manuelle Wiederverbindung über Button"""
        # Wechsle zum Trading-Bot Tab und versuche dort zu verbinden
        if hasattr(self, 'trading_bot_widget'):
            # Find Trading-Bot tab index
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "Trading-Bot":
                    self.tabs.setCurrentIndex(i)
                    break

            # Trigger connection via Trading Bot
            if hasattr(self.trading_bot_widget, '_connect_to_ibkr'):
                self.trading_bot_widget._connect_to_ibkr()
        else:
            QMessageBox.information(self, "Verbindung",
                "Bitte verbinden Sie sich über den Trading-Bot Tab mit IBKR.")
