import random
"""
Backtest Widget für GridTrader V2.0
Mit IBKR Historical Data Integration
"""
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, Signal, QThread, QDate
from PySide6.QtGui import QFont
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
import asyncio

from gridtrader.domain.models.cycle import CycleTemplate, Side, ScaleMode
from gridtrader.domain.services.backtest_engine import BacktestEngine, BacktestConfig
from gridtrader.domain.services.grid_calculator import OriginalGridCalculator, GridCalculationInput
from gridtrader.infrastructure.reports.excel_reporter import ExcelReporter
from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRBrokerAdapter, IBKRConfig
from gridtrader.infrastructure.brokers.ibkr.shared_connection import shared_connection


class BacktestThread(QThread):
    """Thread für Backtest-Ausführung"""
    
    progress_update = Signal(str)
    result_ready = Signal(dict)
    error_occurred = Signal(str)
    
    def __init__(self, config, template, use_ibkr_data=True):
        super().__init__()
        self.config = config
        self.template = template
        self.use_ibkr_data = use_ibkr_data
        self.adapter = None
        
    async def fetch_historical_data(self):
        """Hole historische Daten von IBKR"""
        try:
            # Verwende shared_connection für geteilte Verbindung
            self.adapter = await shared_connection.get_adapter()

            if not self.adapter.is_connected():
                self.error_occurred.emit("Konnte nicht mit IBKR verbinden")
                return None
            
            self.progress_update.emit("📊 Lade historische Daten...")
            
            # Berechne Duration
            start_date = datetime.strptime(self.config.start_date, "%Y-%m-%d")
            end_date = datetime.strptime(self.config.end_date, "%Y-%m-%d")
            days_diff = (end_date - start_date).days
            
            # IBKR Duration String
            if days_diff <= 1:
                duration = "1 D"
                bar_size = "1 min"
            elif days_diff <= 7:
                duration = f"{days_diff} D"
                bar_size = "5 mins"
            elif days_diff <= 30:
                duration = "1 M"
                bar_size = "1 hour"
            else:
                duration = f"{days_diff//30} M"
                bar_size = "1 day"
            
            # Hole Daten
            data = await self.adapter.get_historical_data(
                symbol=self.config.symbol,
                duration=duration,
                bar_size=bar_size,
                what_to_show="TRADES",
                use_rth=True
            )
            
            await self.adapter.disconnect()
            return data
            
        except Exception as e:
            self.error_occurred.emit(f"Fehler beim Datenabruf: {str(e)}")
            return None
    

    def _generate_mock_data(self):
        """Generiere Mock-Daten als Fallback"""
        import numpy as np
        
        start_date = datetime.strptime(self.config.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(self.config.end_date, "%Y-%m-%d")
        
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        base_price = 100.0
        prices = []
        for i in range(len(date_range)):
            change = np.random.normal(0, 2)
            base_price = max(50, base_price + change)
            prices.append(base_price)
        
        data = pd.DataFrame({
            'open': prices,
            'high': [p + abs(np.random.normal(0, 1)) for p in prices],
            'low': [p - abs(np.random.normal(0, 1)) for p in prices],
            'close': [p + np.random.normal(0, 0.5) for p in prices],
            'volume': np.random.randint(1000000, 5000000, len(date_range))
        }, index=date_range)
        
        return data

    def run(self):
        """Führe Backtest aus"""
        try:
            self.progress_update.emit("🚀 Starte Backtest...")
            
            if self.use_ibkr_data:
                # Hole echte Daten
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                historical_data = loop.run_until_complete(self.fetch_historical_data())
                loop.close()
                
                if historical_data is None or historical_data.empty:
                    self.progress_update.emit("⚠️ Verwende Mock-Daten als Fallback")
                    historical_data = self._generate_mock_data()
                
                self.progress_update.emit(f"✅ {len(historical_data)} Datenpunkte geladen")
            
            # Führe Backtest aus
            self.progress_update.emit("📈 Berechne Backtest...")
            engine = BacktestEngine(self.config)
            result = engine.run(self.template)
            
            # Konvertiere Result zu Dict für Signal
            result_dict = {
                'symbol': result.symbol,
                'side': result.side,
                'start_date': result.start_date.strftime("%Y-%m-%d"),
                'end_date': result.end_date.strftime("%Y-%m-%d"),
                'total_return': float(result.total_return),
                'total_return_pct': float(result.total_return_pct),
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown_pct': float(result.max_drawdown_pct),
                'win_rate': result.win_rate,
                'total_trades': result.total_trades,
                'profit_factor': result.profit_factor,
                'starting_capital': float(result.starting_capital),
                'ending_capital': float(result.ending_capital),
                '_result_object': result  # Für Excel Export
            }
            
            self.result_ready.emit(result_dict)
            self.progress_update.emit("✅ Backtest abgeschlossen!")
            
        except Exception as e:
            self.error_occurred.emit(str(e))


class BacktestWidget(QWidget):
    """Backtest Widget mit IBKR Integration"""
    
    def __init__(self):
        super().__init__()
        self.backtest_thread = None
        self.last_result = None
        self._setup_ui()
        
    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("📊 Backtest mit historischen Daten")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Parameters Group
        params_group = QGroupBox("Backtest Parameter")
        params_layout = QGridLayout()
        
        # Symbol
        params_layout.addWidget(QLabel("Symbol:"), 0, 0)
        self.symbol_input = QLineEdit("AAPL")
        params_layout.addWidget(self.symbol_input, 0, 1)
        
        # Side
        params_layout.addWidget(QLabel("Seite:"), 0, 2)
        self.side_combo = QComboBox()
        self.side_combo.addItems(["LONG", "SHORT"])
        params_layout.addWidget(self.side_combo, 0, 3)
        
        # Dates
        params_layout.addWidget(QLabel("Start:"), 1, 0)
        self.start_date = QDateEdit()
        self.start_date.setDate(QDate.currentDate().addMonths(-1))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        params_layout.addWidget(self.start_date, 1, 1)
        
        params_layout.addWidget(QLabel("Ende:"), 1, 2)
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        params_layout.addWidget(self.end_date, 1, 3)
        
        # Grid Parameters
        params_layout.addWidget(QLabel("Levels:"), 2, 0)
        self.levels_spin = QSpinBox()
        self.levels_spin.setRange(2, 100)
        self.levels_spin.setValue(5)
        params_layout.addWidget(self.levels_spin, 2, 1)
        
        params_layout.addWidget(QLabel("Menge/Level:"), 2, 2)
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10000)
        self.qty_spin.setValue(100)
        params_layout.addWidget(self.qty_spin, 2, 3)
        
        # Capital
        params_layout.addWidget(QLabel("Startkapital:"), 3, 0)
        self.capital_spin = QDoubleSpinBox()
        self.capital_spin.setRange(1000, 10000000)
        self.capital_spin.setValue(100000)
        self.capital_spin.setPrefix("$ ")
        params_layout.addWidget(self.capital_spin, 3, 1)
        
        # Data Source
        params_layout.addWidget(QLabel("Datenquelle:"), 3, 2)
        self.data_source_combo = QComboBox()
        self.data_source_combo.addItems(["IBKR Live", "Mock Data"])
        params_layout.addWidget(self.data_source_combo, 3, 3)
        
        params_group.setLayout(params_layout)
        layout.addWidget(params_group)
        
        # Control Buttons
        button_layout = QHBoxLayout()
        
        self.run_button = QPushButton("🚀 Backtest starten")
        self.run_button.clicked.connect(self._run_backtest)
        button_layout.addWidget(self.run_button)
        
        self.export_button = QPushButton("📊 Excel Export")
        self.export_button.clicked.connect(self._export_excel)
        self.export_button.setEnabled(False)
        button_layout.addWidget(self.export_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Progress/Status
        self.status_label = QLabel("Bereit für Backtest")
        self.status_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
        layout.addWidget(self.status_label)
        
        # Results Display
        results_group = QGroupBox("Backtest Ergebnisse")
        results_layout = QVBoxLayout()
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        results_layout.addWidget(self.results_text)
        
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
    
    def _run_backtest(self):
        """Starte Backtest"""
        if self.backtest_thread and self.backtest_thread.isRunning():
            QMessageBox.warning(self, "Warnung", "Backtest läuft bereits!")
            return
        
        # Erstelle Config
        config = BacktestConfig(
            symbol=self.symbol_input.text(),
            start_date=self.start_date.date().toString("yyyy-MM-dd"),
            end_date=self.end_date.date().toString("yyyy-MM-dd"),
            initial_capital=Decimal(str(self.capital_spin.value()))
        )
        
        # Erstelle Template
        template = CycleTemplate(
            name=f"Backtest {self.symbol_input.text()}",
            symbol=self.symbol_input.text(),
            side=Side[self.side_combo.currentText()],
            anchor_price=Decimal("100.00"),  # Wird aus Daten bestimmt
            step=Decimal("1.00"),
            step_mode=ScaleMode.CENTS,
            levels=self.levels_spin.value(),
            qty_per_level=self.qty_spin.value()
        )
        
        # UI Update
        self.run_button.setEnabled(False)
        self.results_text.clear()
        
        # Starte Thread
        use_ibkr = self.data_source_combo.currentText() == "IBKR Live"
        self.backtest_thread = BacktestThread(config, template, use_ibkr)
        self.backtest_thread.progress_update.connect(self._on_progress)
        self.backtest_thread.result_ready.connect(self._on_result)
        self.backtest_thread.error_occurred.connect(self._on_error)
        self.backtest_thread.start()
    
    def _on_progress(self, message):
        """Update Progress"""
        self.status_label.setText(message)
        self.results_text.append(message)
    
    def _on_result(self, result_dict):
        """Handle Backtest Result"""
        self.last_result = result_dict
        
        # Formatiere Ergebnis
        result_text = f"""
═══════════════════════════════════════════
📊 BACKTEST ERGEBNIS
═══════════════════════════════════════════

Symbol: {result_dict['symbol']}
Seite: {result_dict['side']}
Zeitraum: {result_dict['start_date']} bis {result_dict['end_date']}

💰 KAPITAL
────────────────────
Startkapital: ${result_dict['starting_capital']:,.2f}
Endkapital: ${result_dict['ending_capital']:,.2f}
Total Return: ${result_dict['total_return']:,.2f}
Total Return %: {result_dict['total_return_pct']:.2f}%

📈 PERFORMANCE
────────────────────
Sharpe Ratio: {result_dict['sharpe_ratio']:.2f}
Max Drawdown: {result_dict['max_drawdown_pct']:.2f}%
Win Rate: {result_dict['win_rate']:.1f}%
Profit Factor: {result_dict['profit_factor']:.2f}

📊 TRADING
────────────────────
Anzahl Trades: {result_dict['total_trades']}

═══════════════════════════════════════════
"""
        
        self.results_text.append(result_text)
        
        # Enable Export
        self.export_button.setEnabled(True)
        self.run_button.setEnabled(True)
    
    def _on_error(self, error_msg):
        """Handle Error"""
        self.status_label.setText(f"❌ Fehler: {error_msg}")
        self.results_text.append(f"\n❌ FEHLER: {error_msg}")
        self.run_button.setEnabled(True)
        QMessageBox.critical(self, "Backtest Fehler", error_msg)
    
    def _export_excel(self):
        """Export zu Excel"""
        if not self.last_result or '_result_object' not in self.last_result:
            return
        
        try:
            reporter = ExcelReporter()
            filepath = reporter.create_backtest_report(self.last_result['_result_object'])
            
            self.status_label.setText(f"✅ Excel exportiert: {filepath}")
            QMessageBox.information(self, "Export erfolgreich", f"Report gespeichert:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Fehler", str(e))
