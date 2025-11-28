"""
Decision Visualizer Widget

Echtzeit-Visualisierung der KI-Controller Entscheidungen:
- Level-Scores als Balkendiagramm
- Aktive vs. verfügbare Levels
- Entscheidungs-Timeline
- Preis-Vorhersage Anzeige
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QFrame, QScrollArea, QSizePolicy,
    QGridLayout, QSplitter
)
from PySide6.QtCore import Qt, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QFont

from datetime import datetime
from typing import Dict, List, Any, Optional
from collections import deque

# Styles
try:
    from gridtrader.ui.styles import (
        TITLE_STYLE, GROUPBOX_STYLE, apply_groupbox_style
    )
except ImportError:
    TITLE_STYLE = "font-weight: bold; font-size: 14px; color: #2196F3;"
    GROUPBOX_STYLE = ""
    def apply_groupbox_style(g): pass


class ScoreBar(QWidget):
    """Visualisiert einen Score als horizontalen Balken"""

    def __init__(self, label: str = "", value: float = 0.0, max_value: float = 1.0, parent=None):
        super().__init__(parent)
        self._label = label
        self._value = value
        self._max_value = max_value
        self._color = QColor("#4CAF50")
        self.setMinimumHeight(25)
        self.setMinimumWidth(150)

    def set_value(self, value: float):
        self._value = value
        self.update()

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Hintergrund
        painter.fillRect(0, 0, width, height, QColor("#e0e0e0"))

        # Wert-Balken
        if self._max_value > 0:
            bar_width = int((self._value / self._max_value) * width)
            bar_width = max(0, min(bar_width, width))
            painter.fillRect(0, 0, bar_width, height, self._color)

        # Label und Wert
        painter.setPen(QPen(QColor("#333")))
        painter.setFont(QFont("Arial", 9))

        text = f"{self._label}: {self._value:.2f}"
        painter.drawText(5, height - 7, text)


class PredictionDisplay(QFrame):
    """Zeigt Preis-Vorhersagen an"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        title = QLabel("Preis-Vorhersage")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        # Grid für Vorhersagen
        grid = QGridLayout()

        self._predictions = {}
        timeframes = ["5min", "15min", "30min", "1h"]
        for i, tf in enumerate(timeframes):
            label = QLabel(f"{tf}:")
            label.setStyleSheet("color: #666;")
            grid.addWidget(label, i, 0)

            direction = QLabel("-")
            direction.setObjectName(f"direction_{tf}")
            grid.addWidget(direction, i, 1)

            confidence = QProgressBar()
            confidence.setObjectName(f"confidence_{tf}")
            confidence.setMaximum(100)
            confidence.setValue(0)
            confidence.setMaximumHeight(15)
            confidence.setTextVisible(False)
            grid.addWidget(confidence, i, 2)

            self._predictions[tf] = {
                'direction': direction,
                'confidence': confidence
            }

        layout.addLayout(grid)

        # Gesamtbewertung
        self._overall_label = QLabel("Trend: NEUTRAL")
        self._overall_label.setStyleSheet("""
            font-weight: bold;
            padding: 5px;
            background-color: #f5f5f5;
            border-radius: 3px;
        """)
        layout.addWidget(self._overall_label)

    def update_predictions(self, predictions: Dict[str, Any]):
        """Aktualisiert die Vorhersage-Anzeige"""
        direction_colors = {
            'STRONG_UP': '#4CAF50',
            'UP': '#8BC34A',
            'NEUTRAL': '#9E9E9E',
            'DOWN': '#FF9800',
            'STRONG_DOWN': '#f44336',
        }

        for tf, data in predictions.items():
            if tf in self._predictions:
                direction = data.get('direction', 'NEUTRAL')
                confidence = data.get('confidence', 0) * 100

                dir_widget = self._predictions[tf]['direction']
                dir_widget.setText(direction)
                dir_widget.setStyleSheet(f"color: {direction_colors.get(direction, '#333')}; font-weight: bold;")

                conf_widget = self._predictions[tf]['confidence']
                conf_widget.setValue(int(confidence))

        # Overall
        overall = predictions.get('overall', {})
        bias = overall.get('bias', 'NEUTRAL')
        self._overall_label.setText(f"Trend: {bias}")
        self._overall_label.setStyleSheet(f"""
            font-weight: bold;
            padding: 5px;
            background-color: {direction_colors.get(bias, '#f5f5f5')};
            color: white;
            border-radius: 3px;
        """)


class DecisionTimeline(QWidget):
    """Zeigt Entscheidungs-Timeline an"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._decisions = deque(maxlen=50)
        self.setMinimumHeight(100)
        self.setMinimumWidth(400)

    def add_decision(self, decision_type: str, symbol: str, timestamp: datetime):
        """Fügt eine Entscheidung hinzu"""
        self._decisions.append({
            'type': decision_type,
            'symbol': symbol,
            'time': timestamp,
        })
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        # Hintergrund
        painter.fillRect(0, 0, width, height, QColor("#fafafa"))

        if not self._decisions:
            painter.setPen(QPen(QColor("#666")))
            painter.drawText(10, height // 2, "Keine Entscheidungen")
            return

        # Timeline zeichnen
        y_center = height // 2
        painter.setPen(QPen(QColor("#ccc"), 2))
        painter.drawLine(20, y_center, width - 20, y_center)

        # Entscheidungspunkte
        decision_colors = {
            'ACTIVATE_LEVEL': QColor("#4CAF50"),
            'DEACTIVATE_LEVEL': QColor("#FF9800"),
            'SKIP_LEVEL': QColor("#9E9E9E"),
            'EMERGENCY_EXIT': QColor("#f44336"),
        }

        decisions_list = list(self._decisions)
        if len(decisions_list) > 0:
            spacing = (width - 40) / max(len(decisions_list), 1)

            for i, decision in enumerate(decisions_list):
                x = 20 + int(i * spacing)
                color = decision_colors.get(decision['type'], QColor("#666"))

                # Punkt
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.darker(), 1))
                painter.drawEllipse(x - 5, y_center - 5, 10, 10)

                # Label
                painter.setPen(QPen(QColor("#333")))
                painter.setFont(QFont("Arial", 8))

                label = decision['symbol'][:6] if decision['symbol'] else decision['type'][:6]
                painter.drawText(x - 15, y_center + 20, label)

                time_str = decision['time'].strftime("%H:%M")
                painter.drawText(x - 15, y_center - 15, time_str)


class LevelScoreTable(QTableWidget):
    """Tabelle für Level-Scores"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_table()

    def _setup_table(self):
        self.setColumnCount(10)
        self.setHorizontalHeaderLabels([
            "Level ID", "Symbol", "Seite", "Score",
            "Preis-Nähe", "Vol-Fit", "Profit", "R/R",
            "Pattern", "Status"
        ])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setEditTriggers(QTableWidget.NoEditTriggers)

        # Styling
        self.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 4px;
            }
            QHeaderView::section {
                background-color: #f5f5f5;
                font-weight: bold;
                padding: 4px;
                border: 1px solid #e0e0e0;
            }
        """)

    def update_scores(self, levels: List[Dict[str, Any]]):
        """Aktualisiert die Level-Scores"""
        self.setRowCount(len(levels))

        for row, level in enumerate(levels):
            # Level ID - zeige Scenario-Name mit Level-Nummer
            scenario_name = level.get('scenario_name', '')
            level_num = level.get('level_num', 0)
            side = level.get('side', '')

            if scenario_name:
                # Vollständiger Name: "Scenario L1 LONG"
                display_id = f"{scenario_name} L{level_num}"
            else:
                # Fallback: Aus level_id extrahieren
                level_id = level.get('level_id', '')
                parts = level_id.split('_')
                if len(parts) >= 3:
                    display_id = f"L{parts[-2]}_{parts[-1]}"
                else:
                    display_id = level_id[:15]
            self.setItem(row, 0, QTableWidgetItem(display_id))

            # Symbol
            self.setItem(row, 1, QTableWidgetItem(level.get('symbol', '')))

            # Seite
            side = level.get('side', '')
            side_item = QTableWidgetItem(side)
            side_item.setForeground(
                QColor("#4CAF50") if side == "LONG" else QColor("#f44336")
            )
            self.setItem(row, 2, side_item)

            # Gesamt-Score
            score = level.get('total_score', 0)
            score_item = QTableWidgetItem(f"{score:.2f}")
            if score >= 0.7:
                score_item.setBackground(QColor("#C8E6C9"))
            elif score >= 0.5:
                score_item.setBackground(QColor("#FFF9C4"))
            else:
                score_item.setBackground(QColor("#FFCDD2"))
            self.setItem(row, 3, score_item)

            # Score-Breakdown
            breakdown = level.get('score_breakdown', {})
            self.setItem(row, 4, QTableWidgetItem(f"{breakdown.get('price_proximity', 0):.2f}"))
            self.setItem(row, 5, QTableWidgetItem(f"{breakdown.get('volatility_fit', 0):.2f}"))
            self.setItem(row, 6, QTableWidgetItem(f"{breakdown.get('profit_potential', 0):.2f}"))
            self.setItem(row, 7, QTableWidgetItem(f"{breakdown.get('risk_reward', 0):.2f}"))
            self.setItem(row, 8, QTableWidgetItem(f"{breakdown.get('pattern_match', 0):.2f}"))

            # Status
            status = level.get('status', 'AVAILABLE')
            status_item = QTableWidgetItem(status)
            status_colors = {
                'ACTIVE': QColor("#4CAF50"),
                'AVAILABLE': QColor("#2196F3"),
                'EXCLUDED': QColor("#9E9E9E"),
                'BLOCKED': QColor("#f44336"),
            }
            status_item.setForeground(status_colors.get(status, QColor("#333")))
            self.setItem(row, 9, status_item)


class DecisionVisualizerWidget(QWidget):
    """
    Hauptwidget für die Entscheidungs-Visualisierung.

    Zeigt:
    - Level-Scores in Echtzeit
    - Preis-Vorhersagen
    - Entscheidungs-Timeline
    - Markt-Kontext
    """

    decision_selected = Signal(str)  # level_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

        # Update Timer
        self._update_timer = QTimer()
        self._update_timer.timeout.connect(self._request_update)
        self._update_timer.start(2000)  # Alle 2 Sekunden

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Header
        header = QLabel("Entscheidungs-Visualisierung")
        header.setStyleSheet(TITLE_STYLE)
        layout.addWidget(header)

        # Splitter für Layout
        splitter = QSplitter(Qt.Horizontal)

        # ===== LINKE SEITE: Scores und Timeline =====
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Level Scores
        scores_group = QGroupBox("Level-Bewertungen")
        apply_groupbox_style(scores_group)
        scores_layout = QVBoxLayout(scores_group)

        self._score_table = LevelScoreTable()
        scores_layout.addWidget(self._score_table)

        left_layout.addWidget(scores_group, stretch=3)

        # Timeline
        timeline_group = QGroupBox("Entscheidungs-Timeline")
        apply_groupbox_style(timeline_group)
        timeline_layout = QVBoxLayout(timeline_group)

        self._timeline = DecisionTimeline()
        timeline_layout.addWidget(self._timeline)

        left_layout.addWidget(timeline_group, stretch=1)

        splitter.addWidget(left_widget)

        # ===== RECHTE SEITE: Vorhersagen und Kontext =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Vorhersagen
        self._prediction_display = PredictionDisplay()
        right_layout.addWidget(self._prediction_display)

        # Markt-Kontext
        context_group = QGroupBox("Markt-Kontext")
        apply_groupbox_style(context_group)
        context_layout = QVBoxLayout(context_group)

        # Score-Bars für verschiedene Faktoren
        self._context_bars = {}
        factors = [
            ("Volatilität", "volatility"),
            ("Volumen", "volume"),
            ("Tageszeit", "time_score"),
            ("Pattern-Match", "pattern"),
            ("Risiko-Level", "risk"),
        ]

        for label, key in factors:
            bar = ScoreBar(label, 0.5, 1.0)
            self._context_bars[key] = bar
            context_layout.addWidget(bar)

        right_layout.addWidget(context_group)

        # Aktuelle Empfehlung
        rec_group = QGroupBox("Aktuelle Empfehlung")
        apply_groupbox_style(rec_group)
        rec_layout = QVBoxLayout(rec_group)

        self._recommendation_label = QLabel("Keine aktive Empfehlung")
        self._recommendation_label.setWordWrap(True)
        self._recommendation_label.setStyleSheet("""
            padding: 10px;
            background-color: #f5f5f5;
            border-radius: 5px;
            font-size: 12px;
        """)
        rec_layout.addWidget(self._recommendation_label)

        self._action_label = QLabel("")
        self._action_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        rec_layout.addWidget(self._action_label)

        right_layout.addWidget(rec_group)
        right_layout.addStretch()

        splitter.addWidget(right_widget)
        splitter.setSizes([600, 300])

        layout.addWidget(splitter)

    def _request_update(self):
        """Fordert Update vom Controller an"""
        # Wird von außen verbunden
        pass

    # ==================== PUBLIC UPDATE METHODS ====================

    @Slot(list)
    def update_level_scores(self, levels: List[Dict[str, Any]]):
        """Aktualisiert Level-Score Anzeige"""
        self._score_table.update_scores(levels)

    @Slot(dict)
    def update_predictions(self, predictions: Dict[str, Any]):
        """Aktualisiert Vorhersage-Anzeige"""
        self._prediction_display.update_predictions(predictions)

    @Slot(dict)
    def update_market_context(self, context: Dict[str, Any]):
        """Aktualisiert Markt-Kontext Anzeige"""
        # Volatilität
        vol = context.get('volatility_score', 0.5)
        self._context_bars['volatility'].set_value(vol)
        self._context_bars['volatility'].set_color(
            QColor("#f44336") if vol > 0.7 else QColor("#4CAF50") if vol < 0.3 else QColor("#FF9800")
        )

        # Volumen
        vol_score = context.get('volume_score', 0.5)
        self._context_bars['volume'].set_value(vol_score)

        # Tageszeit
        time_score = context.get('time_score', 0.5)
        self._context_bars['time_score'].set_value(time_score)

        # Pattern
        pattern_score = context.get('pattern_score', 0.0)
        self._context_bars['pattern'].set_value(pattern_score)

        # Risiko
        risk_score = context.get('risk_score', 0.5)
        self._context_bars['risk'].set_value(risk_score)
        self._context_bars['risk'].set_color(
            QColor("#f44336") if risk_score > 0.7 else QColor("#4CAF50") if risk_score < 0.3 else QColor("#FF9800")
        )

    @Slot(str, str, object)
    def add_decision(self, decision_type: str, symbol: str, timestamp: datetime = None):
        """Fügt eine Entscheidung zur Timeline hinzu"""
        if timestamp is None:
            timestamp = datetime.now()
        self._timeline.add_decision(decision_type, symbol, timestamp)

    @Slot(str, str)
    def update_recommendation(self, recommendation: str, action: str = ""):
        """Aktualisiert die Empfehlung"""
        self._recommendation_label.setText(recommendation)

        if action:
            self._action_label.setText(action)
            action_colors = {
                'ACTIVATE': '#4CAF50',
                'DEACTIVATE': '#FF9800',
                'HOLD': '#2196F3',
                'EXIT': '#f44336',
            }
            for key, color in action_colors.items():
                if key in action.upper():
                    self._action_label.setStyleSheet(f"font-weight: bold; font-size: 14px; color: {color};")
                    break

    def get_update_interval(self) -> int:
        """Gibt Update-Intervall in ms zurück"""
        return self._update_timer.interval()

    def set_update_interval(self, ms: int):
        """Setzt Update-Intervall"""
        self._update_timer.setInterval(ms)

    @Slot(dict)
    def update_market_data(self, data: dict):
        """
        Aktualisiert die Marktdaten-Anzeige.

        Args:
            data: Dictionary mit Marktdaten (symbol, price, atr, volume_ratio, etc.)
        """
        symbol = data.get('symbol', '')
        price = data.get('price', 0)
        regime = data.get('volatility_regime', 'UNKNOWN')
        atr = data.get('atr_5', 0)
        volume_ratio = data.get('volume_ratio', 1.0)
        trading_phase = data.get('trading_phase', 'UNKNOWN')
        pattern = data.get('pattern', 'UNKNOWN')
        pattern_confidence = data.get('pattern_confidence', 0)

        # Konvertiere Daten zu Scores für die Score-Bars
        # Volatilität: HIGH -> 0.8, MEDIUM -> 0.5, LOW -> 0.2
        volatility_scores = {'EXTREME': 1.0, 'HIGH': 0.8, 'MEDIUM': 0.5, 'LOW': 0.2, 'UNKNOWN': 0.5}
        vol_score = volatility_scores.get(regime, 0.5)

        # Volumen: ratio normalisiert (1.0 = normal = 0.5)
        vol_ratio_score = min(1.0, volume_ratio / 2.0) if volume_ratio > 0 else 0.5

        # Tageszeit: MORNING, AFTERNOON = gut (0.7), OPEN, CLOSE = medium (0.5), andere = niedrig (0.3)
        time_scores = {
            'MORNING': 0.7, 'AFTERNOON': 0.7,
            'OPEN': 0.5, 'CLOSE': 0.5, 'MIDDAY': 0.4,
            'PRE_MARKET': 0.3, 'AFTER_HOURS': 0.2, 'CLOSED': 0.0, 'UNKNOWN': 0.5
        }
        time_score = time_scores.get(trading_phase, 0.5)

        # Pattern-Score basierend auf Confidence
        pattern_score = pattern_confidence if pattern != 'UNKNOWN' else 0.0

        # Risiko-Score (inverser Volatilitäts-Score)
        risk_score = vol_score  # Höhere Volatilität = höheres Risiko

        # Score-Bars aktualisieren
        if hasattr(self, '_context_bars') and self._context_bars:
            if 'volatility' in self._context_bars:
                self._context_bars['volatility'].set_value(vol_score)
                self._context_bars['volatility'].set_color(
                    QColor("#f44336") if vol_score > 0.7 else
                    QColor("#4CAF50") if vol_score < 0.3 else QColor("#FF9800")
                )
            if 'volume' in self._context_bars:
                self._context_bars['volume'].set_value(vol_ratio_score)
                self._context_bars['volume'].set_color(
                    QColor("#f44336") if vol_ratio_score > 0.8 else
                    QColor("#4CAF50") if vol_ratio_score < 0.3 else QColor("#2196F3")
                )
            if 'time_score' in self._context_bars:
                self._context_bars['time_score'].set_value(time_score)
                self._context_bars['time_score'].set_color(
                    QColor("#4CAF50") if time_score > 0.6 else
                    QColor("#FF9800") if time_score > 0.3 else QColor("#f44336")
                )
            if 'pattern' in self._context_bars:
                self._context_bars['pattern'].set_value(pattern_score)
                self._context_bars['pattern'].set_color(
                    QColor("#4CAF50") if pattern_score > 0.6 else QColor("#666")
                )
            if 'risk' in self._context_bars:
                self._context_bars['risk'].set_value(risk_score)
                self._context_bars['risk'].set_color(
                    QColor("#f44336") if risk_score > 0.7 else
                    QColor("#4CAF50") if risk_score < 0.3 else QColor("#FF9800")
                )

        # Empfehlung aktualisieren
        if hasattr(self, '_recommendation_label'):
            rec_parts = []
            rec_parts.append(f"Symbol: {symbol} @ ${price:.2f}")
            rec_parts.append(f"Volatilität: {regime}")
            if pattern != 'UNKNOWN':
                rec_parts.append(f"Pattern: {pattern} ({pattern_confidence:.0%})")
            else:
                rec_parts.append("Pattern: Kein Muster erkannt")
            self._recommendation_label.setText("\n".join(rec_parts))
