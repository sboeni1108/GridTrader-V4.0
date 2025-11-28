"""
Statistics & History Widget

Zeigt Performance-Statistiken und Historie des KI-Controllers:
- Trade-Historie mit Details
- Performance-Metriken
- Equity-Kurve
- Analyse nach verschiedenen Kriterien
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QComboBox, QDateEdit, QTabWidget,
    QFrame, QScrollArea, QGridLayout, QSplitter,
    QProgressBar, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot, QDate
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json

# Styles
try:
    from gridtrader.ui.styles import (
        TITLE_STYLE, GROUPBOX_STYLE, TABLE_STYLE,
        apply_table_style, apply_groupbox_style
    )
except ImportError:
    TITLE_STYLE = "font-weight: bold; font-size: 14px; color: #2196F3;"
    GROUPBOX_STYLE = ""
    TABLE_STYLE = ""
    def apply_table_style(t): pass
    def apply_groupbox_style(g): pass


class EquityCurveWidget(QWidget):
    """Zeichnet eine Equity-Kurve"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_points: List[tuple] = []  # (timestamp, equity)
        self._starting_equity: float = 0.0
        self.setMinimumHeight(200)
        self.setMinimumWidth(400)

    def set_data(self, data_points: List[tuple], starting_equity: float = None):
        """Setzt die Datenpunkte für die Kurve"""
        self._data_points = data_points
        if starting_equity is not None:
            self._starting_equity = starting_equity
        elif data_points:
            self._starting_equity = data_points[0][1]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        margin = 40

        # Hintergrund
        painter.fillRect(0, 0, width, height, QColor("#fafafa"))

        if not self._data_points or len(self._data_points) < 2:
            painter.setPen(QPen(QColor("#666")))
            painter.drawText(width // 2 - 50, height // 2, "Keine Daten")
            return

        # Wertebereiche berechnen
        equities = [p[1] for p in self._data_points]
        min_equity = min(equities)
        max_equity = max(equities)

        # Etwas Padding
        range_equity = max_equity - min_equity
        if range_equity == 0:
            range_equity = 1
        min_equity -= range_equity * 0.1
        max_equity += range_equity * 0.1

        # Achsen
        painter.setPen(QPen(QColor("#ccc"), 1))
        painter.drawLine(margin, height - margin, width - margin, height - margin)  # X-Achse
        painter.drawLine(margin, margin, margin, height - margin)  # Y-Achse

        # Hilfslinie bei Starting Equity
        if self._starting_equity > 0:
            start_y = height - margin - int(
                (self._starting_equity - min_equity) / (max_equity - min_equity) * (height - 2 * margin)
            )
            painter.setPen(QPen(QColor("#999"), 1, Qt.DashLine))
            painter.drawLine(margin, start_y, width - margin, start_y)

            painter.setFont(QFont("Arial", 8))
            painter.drawText(5, start_y + 4, f"${self._starting_equity:,.0f}")

        # Y-Achsen Beschriftung
        painter.setPen(QPen(QColor("#666")))
        painter.setFont(QFont("Arial", 8))
        painter.drawText(5, margin + 5, f"${max_equity:,.0f}")
        painter.drawText(5, height - margin + 5, f"${min_equity:,.0f}")

        # Kurve zeichnen
        chart_width = width - 2 * margin
        chart_height = height - 2 * margin

        points = []
        for i, (timestamp, equity) in enumerate(self._data_points):
            x = margin + int(i / (len(self._data_points) - 1) * chart_width)
            y = height - margin - int(
                (equity - min_equity) / (max_equity - min_equity) * chart_height
            )
            points.append((x, y))

        # Linie zeichnen
        current_equity = self._data_points[-1][1] if self._data_points else 0
        line_color = QColor("#4CAF50") if current_equity >= self._starting_equity else QColor("#f44336")

        painter.setPen(QPen(line_color, 2))
        for i in range(len(points) - 1):
            painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])

        # Endpunkt markieren
        if points:
            last_x, last_y = points[-1]
            painter.setBrush(QBrush(line_color))
            painter.drawEllipse(last_x - 4, last_y - 4, 8, 8)

            # Aktueller Wert
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            painter.drawText(last_x + 10, last_y + 5, f"${current_equity:,.2f}")


class MetricCard(QFrame):
    """Zeigt eine einzelne Metrik als Karte"""

    def __init__(self, title: str, value: str = "-", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 8px;
                padding: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(3)

        self._title = QLabel(title)
        self._title.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self._title)

        self._value = QLabel(value)
        self._value.setStyleSheet("font-size: 20px; font-weight: bold; color: #333;")
        layout.addWidget(self._value)

        self._subtitle = QLabel(subtitle)
        self._subtitle.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self._subtitle)

    def set_value(self, value: str, color: str = "#333"):
        self._value.setText(value)
        self._value.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color};")

    def set_subtitle(self, text: str):
        self._subtitle.setText(text)


class TradeHistoryTable(QTableWidget):
    """Tabelle für Trade-Historie"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_table()

    def _setup_table(self):
        self.setColumnCount(11)
        self.setHorizontalHeaderLabels([
            "Trade ID", "Datum", "Symbol", "Seite", "Entry", "Exit",
            "Menge", "Brutto P&L", "Komm.", "Netto P&L", "Return %"
        ])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSortingEnabled(True)
        apply_table_style(self)

    def update_trades(self, trades: List[Dict[str, Any]]):
        """Aktualisiert die Trade-Historie"""
        self.setRowCount(len(trades))

        for row, trade in enumerate(trades):
            # Trade ID
            self.setItem(row, 0, QTableWidgetItem(trade.get('trade_id', '')[:8]))

            # Datum
            entry_time = trade.get('entry_time')
            if isinstance(entry_time, str):
                date_str = entry_time[:10]
            elif hasattr(entry_time, 'strftime'):
                date_str = entry_time.strftime('%Y-%m-%d')
            else:
                date_str = '-'
            self.setItem(row, 1, QTableWidgetItem(date_str))

            # Symbol
            self.setItem(row, 2, QTableWidgetItem(trade.get('symbol', '')))

            # Seite
            direction = trade.get('direction', '')
            side_item = QTableWidgetItem(direction)
            side_item.setForeground(
                QColor("#4CAF50") if direction == "LONG" else QColor("#f44336")
            )
            self.setItem(row, 3, side_item)

            # Entry/Exit Preise
            entry_price = trade.get('entry_price', 0)
            exit_price = trade.get('exit_price', 0)
            self.setItem(row, 4, QTableWidgetItem(f"${entry_price:.2f}"))
            self.setItem(row, 5, QTableWidgetItem(f"${exit_price:.2f}" if exit_price else "-"))

            # Menge
            self.setItem(row, 6, QTableWidgetItem(str(trade.get('entry_quantity', 0))))

            # P&L
            gross_pnl = trade.get('realized_pnl', 0)
            commission = trade.get('commission', 0)
            net_pnl = trade.get('net_pnl', 0)
            return_pct = trade.get('return_pct', 0)

            gross_item = QTableWidgetItem(f"${gross_pnl:,.2f}")
            gross_item.setForeground(QColor("#4CAF50") if gross_pnl >= 0 else QColor("#f44336"))
            self.setItem(row, 7, gross_item)

            self.setItem(row, 8, QTableWidgetItem(f"${commission:.2f}"))

            net_item = QTableWidgetItem(f"${net_pnl:,.2f}")
            net_item.setForeground(QColor("#4CAF50") if net_pnl >= 0 else QColor("#f44336"))
            self.setItem(row, 9, net_item)

            return_item = QTableWidgetItem(f"{return_pct:.2f}%")
            return_item.setForeground(QColor("#4CAF50") if return_pct >= 0 else QColor("#f44336"))
            self.setItem(row, 10, return_item)


class DecisionHistoryTable(QTableWidget):
    """Tabelle für Entscheidungs-Historie"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_table()

    def _setup_table(self):
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels([
            "ID", "Zeit", "Typ", "Symbol", "Preis", "Konfidenz", "Ergebnis", "Details"
        ])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        apply_table_style(self)

    def update_decisions(self, decisions: List[Dict[str, Any]]):
        """Aktualisiert die Entscheidungs-Historie"""
        self.setRowCount(len(decisions))

        outcome_colors = {
            'CORRECT': QColor("#4CAF50"),
            'INCORRECT': QColor("#f44336"),
            'NEUTRAL': QColor("#9E9E9E"),
            'MISSED': QColor("#FF9800"),
            'PENDING': QColor("#2196F3"),
        }

        for row, decision in enumerate(decisions):
            # ID
            self.setItem(row, 0, QTableWidgetItem(decision.get('decision_id', '')[:8]))

            # Zeit
            timestamp = decision.get('timestamp')
            if isinstance(timestamp, str):
                time_str = timestamp[11:19]  # HH:MM:SS
            elif hasattr(timestamp, 'strftime'):
                time_str = timestamp.strftime('%H:%M:%S')
            else:
                time_str = '-'
            self.setItem(row, 1, QTableWidgetItem(time_str))

            # Typ
            dtype = decision.get('decision_type', '')
            type_item = QTableWidgetItem(dtype)
            self.setItem(row, 2, type_item)

            # Symbol
            self.setItem(row, 3, QTableWidgetItem(decision.get('symbol', '')))

            # Preis
            price = decision.get('price_at_decision', 0)
            self.setItem(row, 4, QTableWidgetItem(f"${price:.2f}"))

            # Konfidenz
            confidence = decision.get('confidence_score', 0) * 100
            self.setItem(row, 5, QTableWidgetItem(f"{confidence:.0f}%"))

            # Ergebnis
            outcome = decision.get('outcome', 'PENDING')
            outcome_item = QTableWidgetItem(outcome)
            outcome_item.setForeground(outcome_colors.get(outcome, QColor("#333")))
            self.setItem(row, 6, outcome_item)

            # Details
            self.setItem(row, 7, QTableWidgetItem(decision.get('outcome_details', '')))


class StatisticsWidget(QWidget):
    """
    Hauptwidget für Statistiken und Historie.

    Tabs:
    - Übersicht: Key Metrics und Equity Curve
    - Trade-Historie: Alle ausgeführten Trades
    - Entscheidungen: Alle Controller-Entscheidungen
    - Analyse: Aufschlüsselung nach Zeit, Level, etc.
    """

    export_requested = Signal(str)  # filepath

    def __init__(self, parent=None):
        super().__init__(parent)
        self._metrics_data: Dict[str, Any] = {}
        self._trades_data: List[Dict] = []
        self._decisions_data: List[Dict] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header mit Filter
        header_layout = QHBoxLayout()

        title = QLabel("Performance & Historie")
        title.setStyleSheet(TITLE_STYLE)
        header_layout.addWidget(title)

        header_layout.addStretch()

        # Zeitraum-Filter
        header_layout.addWidget(QLabel("Zeitraum:"))
        self._period_combo = QComboBox()
        self._period_combo.addItems(["Heute", "Diese Woche", "Dieser Monat", "Alle", "Benutzerdefiniert"])
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        header_layout.addWidget(self._period_combo)

        # Custom Datum (nur bei "Benutzerdefiniert")
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDate(QDate.currentDate().addDays(-30))
        self._from_date.setVisible(False)
        header_layout.addWidget(self._from_date)

        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDate(QDate.currentDate())
        self._to_date.setVisible(False)
        header_layout.addWidget(self._to_date)

        # Export Button
        export_btn = QPushButton("Export")
        export_btn.clicked.connect(self._export_data)
        header_layout.addWidget(export_btn)

        # Refresh Button
        refresh_btn = QPushButton("Aktualisieren")
        refresh_btn.clicked.connect(self._refresh_data)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.addTab(self._create_overview_tab(), "Übersicht")
        self._tabs.addTab(self._create_trades_tab(), "Trades")
        self._tabs.addTab(self._create_decisions_tab(), "Entscheidungen")
        self._tabs.addTab(self._create_analysis_tab(), "Analyse")

        layout.addWidget(self._tabs)

    def _create_overview_tab(self) -> QWidget:
        """Erstellt den Übersicht-Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Metric Cards
        cards_layout = QGridLayout()

        self._cards = {}

        # Row 1
        self._cards['total_pnl'] = MetricCard("Gesamt P&L", "$0.00")
        cards_layout.addWidget(self._cards['total_pnl'], 0, 0)

        self._cards['win_rate'] = MetricCard("Win-Rate", "0%")
        cards_layout.addWidget(self._cards['win_rate'], 0, 1)

        self._cards['profit_factor'] = MetricCard("Profit Factor", "0.00")
        cards_layout.addWidget(self._cards['profit_factor'], 0, 2)

        self._cards['total_trades'] = MetricCard("Anzahl Trades", "0")
        cards_layout.addWidget(self._cards['total_trades'], 0, 3)

        # Row 2
        self._cards['avg_win'] = MetricCard("Ø Gewinn", "$0.00")
        cards_layout.addWidget(self._cards['avg_win'], 1, 0)

        self._cards['avg_loss'] = MetricCard("Ø Verlust", "$0.00")
        cards_layout.addWidget(self._cards['avg_loss'], 1, 1)

        self._cards['max_drawdown'] = MetricCard("Max Drawdown", "0%")
        cards_layout.addWidget(self._cards['max_drawdown'], 1, 2)

        self._cards['sharpe'] = MetricCard("Sharpe Ratio", "0.00")
        cards_layout.addWidget(self._cards['sharpe'], 1, 3)

        layout.addLayout(cards_layout)

        # Equity Curve
        equity_group = QGroupBox("Equity-Kurve")
        apply_groupbox_style(equity_group)
        equity_layout = QVBoxLayout(equity_group)

        self._equity_curve = EquityCurveWidget()
        equity_layout.addWidget(self._equity_curve)

        layout.addWidget(equity_group)

        return widget

    def _create_trades_tab(self) -> QWidget:
        """Erstellt den Trades-Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Filter
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Symbol:"))
        self._trade_symbol_combo = QComboBox()
        self._trade_symbol_combo.addItem("Alle")
        self._trade_symbol_combo.currentIndexChanged.connect(self._filter_trades)
        filter_layout.addWidget(self._trade_symbol_combo)

        filter_layout.addWidget(QLabel("Seite:"))
        self._trade_side_combo = QComboBox()
        self._trade_side_combo.addItems(["Alle", "LONG", "SHORT"])
        self._trade_side_combo.currentIndexChanged.connect(self._filter_trades)
        filter_layout.addWidget(self._trade_side_combo)

        filter_layout.addWidget(QLabel("Ergebnis:"))
        self._trade_result_combo = QComboBox()
        self._trade_result_combo.addItems(["Alle", "Gewinner", "Verlierer"])
        self._trade_result_combo.currentIndexChanged.connect(self._filter_trades)
        filter_layout.addWidget(self._trade_result_combo)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Tabelle
        self._trades_table = TradeHistoryTable()
        layout.addWidget(self._trades_table)

        # Summary
        summary_layout = QHBoxLayout()
        self._trades_summary = QLabel("")
        self._trades_summary.setStyleSheet("color: #666;")
        summary_layout.addWidget(self._trades_summary)
        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        return widget

    def _create_decisions_tab(self) -> QWidget:
        """Erstellt den Entscheidungen-Tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Filter
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Typ:"))
        self._decision_type_combo = QComboBox()
        self._decision_type_combo.addItems([
            "Alle", "ACTIVATE_LEVEL", "DEACTIVATE_LEVEL",
            "SKIP_LEVEL", "EMERGENCY_EXIT"
        ])
        self._decision_type_combo.currentIndexChanged.connect(self._filter_decisions)
        filter_layout.addWidget(self._decision_type_combo)

        filter_layout.addWidget(QLabel("Ergebnis:"))
        self._decision_outcome_combo = QComboBox()
        self._decision_outcome_combo.addItems([
            "Alle", "CORRECT", "INCORRECT", "NEUTRAL", "MISSED", "PENDING"
        ])
        self._decision_outcome_combo.currentIndexChanged.connect(self._filter_decisions)
        filter_layout.addWidget(self._decision_outcome_combo)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Tabelle
        self._decisions_table = DecisionHistoryTable()
        layout.addWidget(self._decisions_table)

        # Summary
        summary_layout = QHBoxLayout()
        self._decisions_summary = QLabel("")
        self._decisions_summary.setStyleSheet("color: #666;")
        summary_layout.addWidget(self._decisions_summary)
        summary_layout.addStretch()
        layout.addLayout(summary_layout)

        return widget

    def _create_analysis_tab(self) -> QWidget:
        """Erstellt den Analyse-Tab"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Analyse nach Tageszeit
        time_group = QGroupBox("Performance nach Tageszeit")
        apply_groupbox_style(time_group)
        time_layout = QVBoxLayout(time_group)

        self._time_analysis_table = QTableWidget()
        self._time_analysis_table.setColumnCount(5)
        self._time_analysis_table.setHorizontalHeaderLabels([
            "Stunde", "Trades", "Win-Rate", "P&L", "Ø Trade"
        ])
        self._time_analysis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        apply_table_style(self._time_analysis_table)
        time_layout.addWidget(self._time_analysis_table)

        layout.addWidget(time_group)

        # Analyse nach Level
        level_group = QGroupBox("Performance nach Level")
        apply_groupbox_style(level_group)
        level_layout = QVBoxLayout(level_group)

        self._level_analysis_table = QTableWidget()
        self._level_analysis_table.setColumnCount(5)
        self._level_analysis_table.setHorizontalHeaderLabels([
            "Level ID", "Trades", "Win-Rate", "P&L", "Ø Trade"
        ])
        self._level_analysis_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        apply_table_style(self._level_analysis_table)
        level_layout.addWidget(self._level_analysis_table)

        layout.addWidget(level_group)

        # Entscheidungs-Qualität
        decision_group = QGroupBox("Entscheidungs-Qualität")
        apply_groupbox_style(decision_group)
        decision_layout = QVBoxLayout(decision_group)

        self._decision_quality_table = QTableWidget()
        self._decision_quality_table.setColumnCount(5)
        self._decision_quality_table.setHorizontalHeaderLabels([
            "Typ", "Gesamt", "Korrekt", "Falsch", "Genauigkeit"
        ])
        self._decision_quality_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        apply_table_style(self._decision_quality_table)
        decision_layout.addWidget(self._decision_quality_table)

        layout.addWidget(decision_group)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    # ==================== DATA UPDATE METHODS ====================

    @Slot(dict)
    def update_metrics(self, metrics: Dict[str, Any]):
        """Aktualisiert die Metriken-Anzeige"""
        self._metrics_data = metrics

        # Cards aktualisieren
        pnl_data = metrics.get('pnl', {})
        total_pnl = pnl_data.get('net', 0)
        self._cards['total_pnl'].set_value(
            f"${total_pnl:,.2f}",
            "#4CAF50" if total_pnl >= 0 else "#f44336"
        )

        ratios = metrics.get('ratios', {})
        self._cards['win_rate'].set_value(f"{ratios.get('win_rate', 0):.1f}%")
        self._cards['profit_factor'].set_value(f"{ratios.get('profit_factor', 0):.2f}")
        self._cards['avg_win'].set_value(f"${ratios.get('avg_win', 0):,.2f}", "#4CAF50")
        self._cards['avg_loss'].set_value(f"${ratios.get('avg_loss', 0):,.2f}", "#f44336")

        trades_data = metrics.get('trades', {})
        self._cards['total_trades'].set_value(str(trades_data.get('total', 0)))
        self._cards['total_trades'].set_subtitle(
            f"W: {trades_data.get('winning', 0)} / L: {trades_data.get('losing', 0)}"
        )

        risk = metrics.get('risk', {})
        self._cards['max_drawdown'].set_value(
            f"{risk.get('max_drawdown_pct', 0):.2f}%",
            "#f44336" if risk.get('max_drawdown_pct', 0) > 10 else "#333"
        )
        self._cards['sharpe'].set_value(f"{risk.get('sharpe_ratio', 0):.2f}")

    @Slot(list)
    def update_trades(self, trades: List[Dict[str, Any]]):
        """Aktualisiert die Trade-Historie"""
        self._trades_data = trades
        self._trades_table.update_trades(trades)

        # Symbols für Filter aktualisieren
        symbols = set(t.get('symbol', '') for t in trades)
        current = self._trade_symbol_combo.currentText()
        self._trade_symbol_combo.clear()
        self._trade_symbol_combo.addItem("Alle")
        for s in sorted(symbols):
            if s:
                self._trade_symbol_combo.addItem(s)
        idx = self._trade_symbol_combo.findText(current)
        if idx >= 0:
            self._trade_symbol_combo.setCurrentIndex(idx)

        # Summary
        total = len(trades)
        total_pnl = sum(t.get('net_pnl', 0) for t in trades)
        self._trades_summary.setText(f"{total} Trades | Gesamt P&L: ${total_pnl:,.2f}")

    @Slot(list)
    def update_decisions(self, decisions: List[Dict[str, Any]]):
        """Aktualisiert die Entscheidungs-Historie"""
        self._decisions_data = decisions
        self._decisions_table.update_decisions(decisions)

        # Summary
        total = len(decisions)
        correct = sum(1 for d in decisions if d.get('outcome') == 'CORRECT')
        accuracy = (correct / total * 100) if total > 0 else 0
        self._decisions_summary.setText(
            f"{total} Entscheidungen | {correct} korrekt | Genauigkeit: {accuracy:.1f}%"
        )

    @Slot(list, float)
    def update_equity_curve(self, data_points: List[tuple], starting_equity: float):
        """Aktualisiert die Equity-Kurve"""
        self._equity_curve.set_data(data_points, starting_equity)

    @Slot(dict)
    def update_time_analysis(self, analysis: Dict[int, Dict[str, Any]]):
        """Aktualisiert die Tageszeit-Analyse"""
        self._time_analysis_table.setRowCount(len(analysis))

        for row, (hour, data) in enumerate(sorted(analysis.items())):
            self._time_analysis_table.setItem(
                row, 0, QTableWidgetItem(f"{hour:02d}:00")
            )
            self._time_analysis_table.setItem(
                row, 1, QTableWidgetItem(str(data.get('total_trades', 0)))
            )

            win_rate = data.get('win_rate', 0)
            win_item = QTableWidgetItem(f"{win_rate:.1f}%")
            win_item.setForeground(
                QColor("#4CAF50") if win_rate >= 50 else QColor("#f44336")
            )
            self._time_analysis_table.setItem(row, 2, win_item)

            pnl = data.get('total_pnl', 0)
            pnl_item = QTableWidgetItem(f"${pnl:,.2f}")
            pnl_item.setForeground(
                QColor("#4CAF50") if pnl >= 0 else QColor("#f44336")
            )
            self._time_analysis_table.setItem(row, 3, pnl_item)

            avg = pnl / data.get('total_trades', 1) if data.get('total_trades', 0) > 0 else 0
            self._time_analysis_table.setItem(
                row, 4, QTableWidgetItem(f"${avg:,.2f}")
            )

    @Slot(dict)
    def update_level_analysis(self, analysis: Dict[str, Dict[str, Any]]):
        """Aktualisiert die Level-Analyse"""
        self._level_analysis_table.setRowCount(len(analysis))

        for row, (level_id, data) in enumerate(analysis.items()):
            self._level_analysis_table.setItem(
                row, 0, QTableWidgetItem(level_id[:8])
            )
            self._level_analysis_table.setItem(
                row, 1, QTableWidgetItem(str(data.get('total_trades', 0)))
            )

            win_rate = data.get('win_rate', 0)
            win_item = QTableWidgetItem(f"{win_rate:.1f}%")
            win_item.setForeground(
                QColor("#4CAF50") if win_rate >= 50 else QColor("#f44336")
            )
            self._level_analysis_table.setItem(row, 2, win_item)

            pnl = data.get('total_pnl', 0)
            pnl_item = QTableWidgetItem(f"${pnl:,.2f}")
            pnl_item.setForeground(
                QColor("#4CAF50") if pnl >= 0 else QColor("#f44336")
            )
            self._level_analysis_table.setItem(row, 3, pnl_item)

            avg = data.get('avg_pnl', 0)
            self._level_analysis_table.setItem(
                row, 4, QTableWidgetItem(f"${avg:,.2f}")
            )

    @Slot(dict)
    def update_decision_quality(self, analysis: Dict[str, Dict[str, Any]]):
        """Aktualisiert die Entscheidungs-Qualitäts-Tabelle"""
        self._decision_quality_table.setRowCount(len(analysis))

        for row, (dtype, data) in enumerate(analysis.items()):
            self._decision_quality_table.setItem(row, 0, QTableWidgetItem(dtype))
            self._decision_quality_table.setItem(
                row, 1, QTableWidgetItem(str(data.get('total', 0)))
            )
            self._decision_quality_table.setItem(
                row, 2, QTableWidgetItem(str(data.get('correct', 0)))
            )
            self._decision_quality_table.setItem(
                row, 3, QTableWidgetItem(str(data.get('incorrect', 0)))
            )

            accuracy = data.get('accuracy', 0)
            acc_item = QTableWidgetItem(f"{accuracy:.1f}%")
            acc_item.setForeground(
                QColor("#4CAF50") if accuracy >= 60 else
                QColor("#FF9800") if accuracy >= 40 else
                QColor("#f44336")
            )
            self._decision_quality_table.setItem(row, 4, acc_item)

    # ==================== HANDLERS ====================

    def _on_period_changed(self, index: int):
        """Handler für Zeitraum-Änderung"""
        custom_visible = index == 4  # "Benutzerdefiniert"
        self._from_date.setVisible(custom_visible)
        self._to_date.setVisible(custom_visible)

        self._refresh_data()

    def _filter_trades(self):
        """Filtert die Trade-Tabelle"""
        symbol_filter = self._trade_symbol_combo.currentText()
        side_filter = self._trade_side_combo.currentText()
        result_filter = self._trade_result_combo.currentText()

        filtered = []
        for trade in self._trades_data:
            if symbol_filter != "Alle" and trade.get('symbol') != symbol_filter:
                continue
            if side_filter != "Alle" and trade.get('direction') != side_filter:
                continue
            if result_filter == "Gewinner" and trade.get('net_pnl', 0) <= 0:
                continue
            if result_filter == "Verlierer" and trade.get('net_pnl', 0) >= 0:
                continue
            filtered.append(trade)

        self._trades_table.update_trades(filtered)

        # Summary aktualisieren
        total = len(filtered)
        total_pnl = sum(t.get('net_pnl', 0) for t in filtered)
        self._trades_summary.setText(f"{total} Trades | Gesamt P&L: ${total_pnl:,.2f}")

    def _filter_decisions(self):
        """Filtert die Entscheidungs-Tabelle"""
        type_filter = self._decision_type_combo.currentText()
        outcome_filter = self._decision_outcome_combo.currentText()

        filtered = []
        for decision in self._decisions_data:
            if type_filter != "Alle" and decision.get('decision_type') != type_filter:
                continue
            if outcome_filter != "Alle" and decision.get('outcome') != outcome_filter:
                continue
            filtered.append(decision)

        self._decisions_table.update_decisions(filtered)

    def _refresh_data(self):
        """Fordert Daten-Aktualisierung an"""
        # Wird von außen verbunden
        pass

    def _export_data(self):
        """Exportiert Daten"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Export speichern",
            f"ki_controller_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON Files (*.json)"
        )

        if filepath:
            try:
                export_data = {
                    'exported_at': datetime.now().isoformat(),
                    'metrics': self._metrics_data,
                    'trades': self._trades_data,
                    'decisions': self._decisions_data,
                }

                with open(filepath, 'w') as f:
                    json.dump(export_data, f, indent=2, default=str)

                QMessageBox.information(
                    self,
                    "Export erfolgreich",
                    f"Daten exportiert nach:\n{filepath}"
                )
                self.export_requested.emit(filepath)

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export fehlgeschlagen",
                    f"Fehler beim Export:\n{str(e)}"
                )

    @Slot(dict)
    def on_market_update(self, data: dict):
        """
        Handler für Marktdaten-Updates.

        Aktualisiert relevante Statistik-Anzeigen basierend auf neuen Marktdaten.

        Args:
            data: Dictionary mit Marktdaten (symbol, price, volume_ratio, etc.)
        """
        # Speichere letzte Marktdaten für Referenz
        if not hasattr(self, '_last_market_data'):
            self._last_market_data = {}

        symbol = data.get('symbol', '')
        if symbol:
            self._last_market_data[symbol] = {
                'price': data.get('price', 0),
                'volume_ratio': data.get('volume_ratio', 1.0),
                'atr': data.get('atr_5', 0),
                'regime': data.get('volatility_regime', 'UNKNOWN'),
                'updated_at': datetime.now()
            }

        # Aktualisiere unrealized P&L basierend auf aktuellem Preis
        # (falls aktive Positionen vorhanden)
        self._update_unrealized_pnl()

    def _update_unrealized_pnl(self):
        """Aktualisiert die unrealized P&L Anzeige basierend auf aktuellen Marktdaten."""
        # Diese Methode kann erweitert werden, um unrealized P&L zu berechnen
        # basierend auf _last_market_data und aktiven Positionen
        pass
