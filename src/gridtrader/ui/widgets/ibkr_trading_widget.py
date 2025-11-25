"""
IBKR Trading Widget mit echter Order-Platzierung
Behebt alle kritischen Probleme:
1. Orders erreichen IBKR wirklich
2. Keine 'str' object Fehler
3. Kein blockierender Code
4. Duplicate Order Prevention
5. Level ID Tracking
"""
from PySide6.QtWidgets import *
from PySide6.QtCore import QTimer, Qt, Signal, QThread
from PySide6.QtGui import QColor
from datetime import datetime
import asyncio
from typing import Dict, Optional
from gridtrader.ui.styles import (
    TITLE_STYLE, GROUPBOX_STYLE, TABLE_STYLE, LOG_STYLE,
    SUCCESS_BUTTON_STYLE, apply_table_style, apply_groupbox_style,
    apply_title_style, apply_log_style, SUCCESS_COLOR, ERROR_COLOR
)

from gridtrader.infrastructure.brokers.ibkr.shared_connection import shared_connection
from gridtrader.domain.models.order import Order, OrderSide, OrderType, OrderStatus


class OrderPlacementThread(QThread):
    """Async Thread für Order-Platzierung - verhindert GUI-Blockierung"""

    order_placed = Signal(str, str)  # display_order_id, broker_id
    order_failed = Signal(str, str)  # display_order_id, error_message

    def __init__(self, order: Order, display_order_id: str):
        super().__init__()
        self.order = order
        self.display_order_id = display_order_id

    def run(self):
        """Platziere Order asynchron"""
        print(f"DEBUG: OrderPlacementThread.run() started for order UUID {self.order.id}, display_id {self.display_order_id}")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            print("DEBUG: Running async _place_order()")
            broker_id = loop.run_until_complete(self._place_order())
            print(f"DEBUG: _place_order() returned broker_id = {broker_id}")
            if broker_id:
                print(f"DEBUG: Emitting order_placed signal for display_id {self.display_order_id}")
                self.order_placed.emit(self.display_order_id, broker_id)
            else:
                print(f"DEBUG: No broker_id - emitting order_failed signal")
                self.order_failed.emit(self.display_order_id, "Keine Broker ID erhalten")
        except Exception as e:
            print(f"DEBUG: Exception in run(): {e}")
            self.order_failed.emit(self.display_order_id, str(e))
        finally:
            loop.close()
            print("DEBUG: OrderPlacementThread.run() completed")

    async def _place_order(self) -> Optional[str]:
        """Interne Order-Platzierung"""
        try:
            print(f"DEBUG: _place_order() START")
            print("DEBUG: Getting adapter from shared_connection")
            adapter = await shared_connection.get_adapter()
            print(f"DEBUG: Got adapter: {adapter}")

            if not adapter:
                print("ERROR: No adapter available!")
                raise ConnectionError("IBKR Adapter nicht verfügbar!")

            if not adapter.is_connected():
                print("ERROR: Adapter not connected!")
                raise ConnectionError("IBKR nicht verbunden!")

            print(f"DEBUG: Order to send: {self.order}")
            print(f"DEBUG: Order symbol: {self.order.symbol}")
            print(f"DEBUG: Order side: {self.order.side}")
            print(f"DEBUG: Order quantity: {self.order.quantity}")

            print("DEBUG: About to call adapter.place_order()...")

            try:
                broker_order_id = await adapter.place_order(self.order)
                print(f"DEBUG: adapter.place_order() returned: {broker_order_id}")
            except Exception as e:
                print(f"ERROR in adapter.place_order(): {e}")
                import traceback
                traceback.print_exc()
                raise

            print(f"✅ IBKR Order gesendet: {broker_order_id}")
            return broker_order_id

        except Exception as e:
            print(f"❌ Order-Fehler: {e}")
            import traceback
            traceback.print_exc()
            raise


class IBKRTradingWidget(QWidget):
    """Trading Widget mit echter IBKR Integration"""

    def __init__(self):
        super().__init__()

        # WICHTIG: Verwende dict für pending_orders, NICHT string!
        self.pending_orders: Dict[str, dict] = {}
        self.active_levels: list = []  # Track aktive Levels
        self.live_trading_enabled = True  # Setze auf False für Simulation
        self.order_counter = 0

        self._setup_ui()

        # Timer für Status-Updates (NON-BLOCKING)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._check_pending_orders_sync)
        self.update_timer.start(1000)  # Jede Sekunde

    def _setup_ui(self):
        """Setup UI"""
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("📊 IBKR Live Trading")
        apply_title_style(title)
        layout.addWidget(title)

        # Trading Mode Indicator
        mode_layout = QHBoxLayout()
        self.mode_label = QLabel("🟢 LIVE TRADING ENABLED" if self.live_trading_enabled else "🟡 SIMULATION MODE")
        self.mode_label.setStyleSheet(
            "color: green; font-weight: bold;" if self.live_trading_enabled
            else "color: orange; font-weight: bold;"
        )
        mode_layout.addWidget(self.mode_label)

        toggle_btn = QPushButton("Toggle Mode")
        toggle_btn.clicked.connect(self._toggle_trading_mode)
        mode_layout.addWidget(toggle_btn)
        mode_layout.addStretch()

        layout.addLayout(mode_layout)

        # Order Entry
        entry_group = QGroupBox("Order Entry")
        apply_groupbox_style(entry_group)
        entry_layout = QVBoxLayout()

        # Symbol and Quantity
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Symbol:"))
        self.symbol_input = QLineEdit("AAPL")
        self.symbol_input.setMaximumWidth(100)
        row1.addWidget(self.symbol_input)

        row1.addWidget(QLabel("Quantity:"))
        self.qty_input = QSpinBox()
        self.qty_input.setRange(1, 10000)
        self.qty_input.setValue(100)
        row1.addWidget(self.qty_input)

        row1.addStretch()
        entry_layout.addLayout(row1)

        # Side and Type
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Side:"))
        self.side_combo = QComboBox()
        self.side_combo.addItems(["BUY", "SELL"])
        row2.addWidget(self.side_combo)

        row2.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["MARKET", "LIMIT"])
        self.type_combo.currentTextChanged.connect(self._on_order_type_changed)
        row2.addWidget(self.type_combo)

        row2.addWidget(QLabel("Limit Price:"))
        self.price_input = QDoubleSpinBox()
        self.price_input.setRange(0.01, 1000000)
        self.price_input.setValue(150.00)
        self.price_input.setEnabled(False)
        row2.addWidget(self.price_input)

        row2.addStretch()
        entry_layout.addLayout(row2)

        # Place Order Button
        self.place_btn = QPushButton("🚀 Place Order")
        self.place_btn.setStyleSheet(SUCCESS_BUTTON_STYLE)
        self.place_btn.clicked.connect(self._on_place_order_clicked)
        entry_layout.addWidget(self.place_btn)
        print("DEBUG: Place Order button created and connected to _on_place_order_clicked()")

        entry_group.setLayout(entry_layout)
        layout.addWidget(entry_group)

        # Pending Orders Table
        pending_group = QGroupBox("Pending Orders")
        apply_groupbox_style(pending_group)
        pending_layout = QVBoxLayout()

        self.pending_table = QTableWidget()
        self.pending_table.setColumnCount(8)
        self.pending_table.setHorizontalHeaderLabels([
            "Order ID", "Symbol", "Side", "Qty", "Price", "Type", "Status", "Broker ID"
        ])
        apply_table_style(self.pending_table)
        pending_layout.addWidget(self.pending_table)

        pending_group.setLayout(pending_layout)
        layout.addWidget(pending_group)

        # Log
        log_group = QGroupBox("Log")
        apply_groupbox_style(log_group)
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        apply_log_style(self.log_text)
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

    def _toggle_trading_mode(self):
        """Toggle zwischen Live und Simulation"""
        self.live_trading_enabled = not self.live_trading_enabled

        if self.live_trading_enabled:
            self.mode_label.setText("🟢 LIVE TRADING ENABLED")
            self.mode_label.setStyleSheet("color: green; font-weight: bold;")
            self.log_message("⚠️ LIVE TRADING aktiviert - Orders werden wirklich gesendet!", "WARNING")
        else:
            self.mode_label.setText("🟡 SIMULATION MODE")
            self.mode_label.setStyleSheet("color: orange; font-weight: bold;")
            self.log_message("✅ Simulation Mode aktiviert - Keine echten Orders", "INFO")

    def _on_order_type_changed(self, order_type: str):
        """Enable/Disable Limit Price Input"""
        self.price_input.setEnabled(order_type == "LIMIT")

    def _on_place_order_clicked(self):
        """
        Button Click Handler - ruft place_ibkr_order() ohne level_index auf
        (für manuelle Orders)
        """
        print("DEBUG: _on_place_order_clicked() called")
        symbol = self.symbol_input.text().upper().strip()
        print(f"DEBUG: Symbol = '{symbol}'")

        if not symbol:
            print("DEBUG: No symbol - showing warning")
            QMessageBox.warning(self, "Fehler", "Bitte Symbol eingeben!")
            return

        print("DEBUG: Calling place_ibkr_order() with level_index=None")
        self.place_ibkr_order(level_index=None)

    def place_ibkr_order(self, level_index: int = None):
        """
        Platziere Order bei IBKR
        KRITISCH: Stellt sicher, dass Orders wirklich gesendet werden!
        Mit Duplicate Prevention!
        """
        print(f"DEBUG: place_ibkr_order() called with level_index={level_index}")

        symbol = self.symbol_input.text().upper().strip()
        print(f"DEBUG: Symbol from input = '{symbol}'")

        if not symbol:
            print("DEBUG: Empty symbol - returning early")
            QMessageBox.warning(self, "Fehler", "Bitte Symbol eingeben!")
            return

        # KRITISCH: DUPLICATE PREVENTION!
        side = self.side_combo.currentText()
        quantity = self.qty_input.value()
        order_type_str = self.type_combo.currentText()
        limit_price = self.price_input.value() if order_type_str == "LIMIT" else None

        print(f"DEBUG: Order params - Side={side}, Qty={quantity}, Type={order_type_str}, Price={limit_price}")

        # Erstelle Level ID für Duplicate Check
        level_id = f"{symbol}_{side}_{level_index if level_index is not None else 'MANUAL'}"
        print(f"DEBUG: Level ID = {level_id}")

        # Check ob für diesen Level bereits eine pending Order existiert
        print(f"DEBUG: Checking {len(self.pending_orders)} pending orders for duplicates")
        for existing_order_id, order_info in self.pending_orders.items():
            if not isinstance(order_info, dict):
                continue

            existing_level_id = order_info.get('level_id', '')
            existing_status = order_info.get('status', '')

            if existing_level_id == level_id and existing_status not in ['FAILED', 'CANCELLED', 'FILLED']:
                print(f"DEBUG: DUPLICATE detected! Level {level_id} already has order {existing_order_id}")
                self.log_message(f"⚠️ DUPLICATE PREVENTED! Level {level_id} hat bereits Order {existing_order_id}", "WARNING")
                QMessageBox.warning(self, "Duplicate Order",
                    f"Für diesen Level existiert bereits Order {existing_order_id}!\n"
                    f"Status: {existing_status}")
                return  # STOP! Keine neue Order!

        # Check in active_levels
        print(f"DEBUG: Checking {len(self.active_levels)} active levels")
        for active in self.active_levels:
            if isinstance(active, dict) and active.get('level_id') == level_id:
                print(f"DEBUG: Level {level_id} already active")
                self.log_message(f"⚠️ DUPLICATE PREVENTED! Level {level_id} ist bereits aktiv", "WARNING")
                QMessageBox.warning(self, "Duplicate Order",
                    f"Level {level_id} ist bereits aktiv!")
                return  # STOP! Level ist schon aktiv!

        print("DEBUG: No duplicates found - proceeding with order creation")

        # Erstelle Display Order ID (String für UI)
        self.order_counter += 1
        display_order_id = f"ORD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.order_counter}"
        print(f"DEBUG: Created Display Order ID = {display_order_id}")

        # Erstelle Domain Order (id wird automatisch als UUID generiert!)
        print("DEBUG: Creating Domain Order object")
        order = Order(
            # KEINE id - wird von Pydantic automatisch als UUID generiert!
            symbol=symbol,
            side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET if order_type_str == "MARKET" else OrderType.LIMIT,
            limit_price=limit_price,
            status=OrderStatus.PENDING
        )
        print(f"DEBUG: Domain Order created - {order} (UUID: {order.id})")

        # SIMULATION MODE CHECK
        print(f"DEBUG: live_trading_enabled = {self.live_trading_enabled}")
        if not self.live_trading_enabled:
            print("DEBUG: SIMULATION MODE - creating simulated order")
            # Nur Simulation - keine echte Order
            sim_id = f"SIM_{datetime.now().strftime('%H%M%S')}"
            order.broker_order_id = sim_id
            order.status = OrderStatus.PLACED

            # WICHTIG: Speichere als dict mit display_order_id als Key!
            self.pending_orders[display_order_id] = {
                'order': order,  # order.id ist die UUID
                'display_id': display_order_id,  # String für UI
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'limit_price': limit_price,
                'order_type': order_type_str,
                'level_id': level_id,  # WICHTIG für Duplicate Prevention!
                'level_index': level_index,
                'status': 'SIMULATED',
                'broker_id': sim_id,
                'timestamp': datetime.now()
            }

            print(f"DEBUG: Simulated order added to pending_orders: {display_order_id}")
            self.log_message(f"🟡 Simulation: Order {display_order_id} ({symbol} {side} {quantity})", "INFO")
            self.update_pending_display()
            print("DEBUG: Pending display updated - returning")
            return

        # LIVE TRADING MODE - Sende Order wirklich an IBKR!
        print("DEBUG: LIVE TRADING MODE - preparing to send order to IBKR")
        self.log_message(f"📤 Sende Order an IBKR: {symbol} {side} {quantity}...", "INFO")

        # WICHTIG: Speichere Order als dict VOR dem Senden mit display_order_id als Key!
        print("DEBUG: Adding order to pending_orders dict")
        self.pending_orders[display_order_id] = {
            'order': order,  # order.id ist die UUID
            'display_id': display_order_id,  # String für UI
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'limit_price': limit_price,
            'order_type': order_type_str,
            'level_id': level_id,  # WICHTIG für Duplicate Prevention!
            'level_index': level_index,
            'status': 'SENDING',
            'broker_id': None,
            'timestamp': datetime.now(),
            'thread': None  # Wird gleich gesetzt
        }
        print(f"DEBUG: Order {display_order_id} added to pending_orders (UUID: {order.id})")

        # Erstelle Thread für async Order-Platzierung (verhindert Blockierung!)
        print("DEBUG: Creating OrderPlacementThread with display_order_id")
        order_thread = OrderPlacementThread(order, display_order_id)
        order_thread.order_placed.connect(self._on_order_placed)
        order_thread.order_failed.connect(self._on_order_failed)
        print("DEBUG: Thread signals connected")

        # Speichere Thread-Referenz
        self.pending_orders[display_order_id]['thread'] = order_thread

        # Starte Thread (NON-BLOCKING!)
        print("DEBUG: Starting OrderPlacementThread")
        order_thread.start()
        print("DEBUG: Thread started")

        self.update_pending_display()
        print("DEBUG: place_ibkr_order() completed")

    def _on_order_placed(self, order_id: str, broker_id: str):
        """Callback wenn Order erfolgreich platziert wurde"""
        # WICHTIG: Prüfe ob order_id existiert und ist ein dict!
        if order_id in self.pending_orders and isinstance(self.pending_orders[order_id], dict):
            order_info = self.pending_orders[order_id]
            order_info['status'] = 'PLACED'
            order_info['broker_id'] = broker_id

            # Update Order Object
            if 'order' in order_info:
                order_info['order'].broker_order_id = broker_id
                order_info['order'].status = OrderStatus.PLACED

            self.log_message(f"✅ Order {order_id} platziert! Broker ID: {broker_id}", "SUCCESS")
            self.update_pending_display()
        else:
            self.log_message(f"❌ ERROR: Order {order_id} nicht gefunden oder ungültig!", "ERROR")

    def _on_order_failed(self, order_id: str, error_msg: str):
        """Callback wenn Order fehlgeschlagen ist"""
        # WICHTIG: Prüfe ob order_id existiert und ist ein dict!
        if order_id in self.pending_orders and isinstance(self.pending_orders[order_id], dict):
            order_info = self.pending_orders[order_id]
            order_info['status'] = 'FAILED'

            # Update Order Object
            if 'order' in order_info:
                order_info['order'].status = OrderStatus.REJECTED

            self.log_message(f"❌ Order {order_id} fehlgeschlagen: {error_msg}", "ERROR")
            self.update_pending_display()
        else:
            self.log_message(f"❌ ERROR: Order {order_id} nicht gefunden oder ungültig!", "ERROR")

    def update_pending_display(self):
        """
        Update Pending Orders Table
        KRITISCH: Keine blocking operations! Nur Display-Update.
        """
        self.pending_table.setRowCount(0)

        for order_id, order_info in self.pending_orders.items():
            # WICHTIG: Prüfe ob order_info ein dict ist!
            if not isinstance(order_info, dict):
                self.log_message(f"❌ ERROR: order_info für {order_id} ist kein dict: {type(order_info)}", "ERROR")
                continue

            row = self.pending_table.rowCount()
            self.pending_table.insertRow(row)

            # Hole Order Object sicher
            order = order_info.get('order')
            if not order:
                continue

            # Fülle Table - Spalten: Order ID, Symbol, Side, Qty, Price, Type, Status, Broker ID
            self.pending_table.setItem(row, 0, QTableWidgetItem(order_id))
            self.pending_table.setItem(row, 1, QTableWidgetItem(order.symbol))
            self.pending_table.setItem(row, 2, QTableWidgetItem(order.side.value))
            self.pending_table.setItem(row, 3, QTableWidgetItem(str(order.quantity)))

            # Preis-Spalte (NEU!)
            order_type = order_info.get('order_type', 'MARKET')
            limit_price = order_info.get('limit_price')

            if order_type == 'LIMIT' and limit_price is not None:
                price_text = f"${limit_price:.2f}"
            else:
                price_text = "MARKET"

            self.pending_table.setItem(row, 4, QTableWidgetItem(price_text))
            self.pending_table.setItem(row, 5, QTableWidgetItem(order_type))

            # Status mit Farbe
            status = order_info.get('status', 'UNKNOWN')
            status_item = QTableWidgetItem(status)

            if status == 'PLACED' or status == 'SIMULATED':
                status_item.setForeground(QColor(0, 150, 0))  # Grün
            elif status == 'FAILED':
                status_item.setForeground(QColor(150, 0, 0))  # Rot
            elif status == 'SENDING':
                status_item.setForeground(QColor(0, 0, 150))  # Blau

            self.pending_table.setItem(row, 6, status_item)

            # Broker ID
            broker_id = order_info.get('broker_id', '--')
            self.pending_table.setItem(row, 7, QTableWidgetItem(str(broker_id) if broker_id else '--'))

    def _check_pending_orders_sync(self):
        """
        Prüfe Status von pending orders
        KRITISCH: MUSS schnell sein - KEINE blocking operations!
        KEIN await, KEIN asyncio.sleep()!
        """
        # Nur Display-Update, keine Netzwerk-Calls!
        # Die Status-Updates kommen bereits über die Callbacks

        # Optional: Alte Orders entfernen (z.B. nach 5 Minuten)
        current_time = datetime.now()
        orders_to_remove = []

        for order_id, order_info in list(self.pending_orders.items()):
            if not isinstance(order_info, dict):
                continue

            timestamp = order_info.get('timestamp')
            if timestamp and (current_time - timestamp).total_seconds() > 300:  # 5 Minuten
                status = order_info.get('status')
                if status in ['PLACED', 'FAILED', 'SIMULATED']:
                    orders_to_remove.append(order_id)

        # Entferne alte Orders
        for order_id in orders_to_remove:
            del self.pending_orders[order_id]

        # Update Display nur wenn nötig
        if orders_to_remove:
            self.update_pending_display()

    def log_message(self, message: str, level: str = "INFO"):
        """Log Message mit Timestamp"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        color = "black"
        if level == "ERROR":
            color = "red"
        elif level == "SUCCESS":
            color = "green"
        elif level == "WARNING":
            color = "orange"

        html = f'<span style="color: {color};">[{timestamp}] {message}</span>'
        self.log_text.append(html)
