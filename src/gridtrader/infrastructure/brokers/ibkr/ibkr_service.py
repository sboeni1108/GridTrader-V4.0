"""
IBKR Service - Dedizierter Thread mit eigenem Event Loop
Löst das Qt/asyncio Event Loop Konflikt-Problem

Architektur:
- Ein dedizierter Thread für alle IB-Operationen
- Eigener asyncio Event Loop im IB Thread
- Thread-safe Kommunikation via Queues und Qt Signals
- Market Data wird per PUSH (Callbacks) statt POLL geliefert
- Orders werden non-blocking für Qt platziert
"""
import asyncio
import threading
import queue
import sys
from typing import Dict, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
from datetime import datetime
import traceback

from PySide6.QtCore import QObject, Signal

# Windows Event Loop Policy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from ib_insync import IB, Stock, Contract, MarketOrder, LimitOrder

from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import IBKRConfig
from gridtrader.domain.models.order import Order, OrderSide, OrderType, OrderStatus


class CommandType(Enum):
    """Befehle für den IB Thread"""
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    PLACE_ORDER = "place_order"
    CANCEL_ORDER = "cancel_order"
    SUBSCRIBE_MARKET_DATA = "subscribe"
    UNSUBSCRIBE_MARKET_DATA = "unsubscribe"
    GET_ACCOUNT = "get_account"
    GET_MARKET_DATA_SNAPSHOT = "get_snapshot"
    STOP = "stop"


@dataclass
class IBCommand:
    """Thread-safe Befehl für IB Service"""
    type: CommandType
    data: dict = field(default_factory=dict)
    callback_id: str = ""


class IBKRServiceSignals(QObject):
    """
    Qt Signals für Thread-sichere Kommunikation

    Alle Signals werden im Qt Main Thread empfangen,
    auch wenn sie vom IB Thread emittiert werden.
    """
    # Connection
    connected = Signal(bool, str)  # success, message
    disconnected = Signal()
    connection_lost = Signal()

    # Market Data (Push!)
    market_data_update = Signal(dict)  # {symbol, bid, ask, last, ...}

    # Orders
    order_placed = Signal(str, str)  # callback_id, broker_order_id
    order_status_changed = Signal(str, str, dict)  # broker_id, status, details
    order_filled = Signal(str, dict)  # broker_id, fill_info
    order_error = Signal(str, str)  # callback_id, error_message

    # Account
    account_update = Signal(dict)

    # Errors
    service_error = Signal(str)  # error_message


class IBKRService:
    """
    Singleton IBKR Service mit dediziertem Thread

    Löst das Problem des Event Loop Konflikts zwischen Qt und ib_insync:
    - Qt läuft im Main Thread mit seinem Event Loop
    - IB läuft in einem dedizierten Thread mit eigenem asyncio Event Loop
    - Kommunikation erfolgt über thread-safe Queues und Qt Signals

    Verwendung:
    -----------
    ```python
    # Service holen (Singleton)
    service = IBKRService.instance()

    # Signals verbinden (im Qt Main Thread)
    service.signals.connected.connect(on_connected)
    service.signals.market_data_update.connect(on_market_data)
    service.signals.order_filled.connect(on_order_filled)

    # Service starten
    service.start()

    # Verbinden
    config = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
    service.connect(config)

    # Market Data subscribieren (Push!)
    service.subscribe_market_data(["AAPL", "MSFT", "GOOGL"])

    # Order platzieren (non-blocking)
    callback_id = service.place_order(order)
    ```
    """

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> 'IBKRService':
        """Singleton Pattern - Thread-safe"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset Singleton (für Tests)"""
        with cls._lock:
            if cls._instance:
                cls._instance.stop()
            cls._instance = None

    def __init__(self):
        if IBKRService._instance is not None:
            raise RuntimeError("Verwende IBKRService.instance() statt direkter Instanziierung")

        # Qt Signals für Thread-sichere Kommunikation
        self.signals = IBKRServiceSignals()

        # Konfiguration
        self._config: Optional[IBKRConfig] = None

        # Thread-safe Communication
        self._command_queue: queue.Queue = queue.Queue()

        # IB State (NUR im IB Thread zugreifbar!)
        self._ib: Optional[IB] = None
        self._connected = False
        self._subscribed_symbols: Set[str] = set()
        self._contracts: Dict[str, Contract] = {}  # symbol -> qualified contract
        self._tickers: Dict[str, any] = {}  # symbol -> ticker

        # Market Data Cache (thread-safe read, IB Thread write)
        self._market_data_cache: Dict[str, dict] = {}
        self._cache_lock = threading.Lock()

        # Order Tracking
        self._order_callbacks: Dict[str, str] = {}  # broker_id -> callback_id
        self._pending_orders: Dict[str, Order] = {}  # callback_id -> domain order

        # Dedizierter Thread
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

        print("🔧 IBKRService initialisiert")

    def start(self):
        """Starte den IB Service Thread"""
        if self._thread and self._thread.is_alive():
            print("⚠️ IBKRService läuft bereits")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_ib_loop,
            name="IBKRService-Thread",
            daemon=True
        )
        self._thread.start()
        print("✅ IBKRService Thread gestartet")

    def stop(self):
        """Stoppe den IB Service Thread"""
        if not self._running:
            return

        print("🛑 Stoppe IBKRService...")
        self._running = False
        self._command_queue.put(IBCommand(type=CommandType.STOP))

        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                print("⚠️ IBKRService Thread konnte nicht sauber beendet werden")
            else:
                print("✅ IBKRService Thread beendet")
            self._thread = None

    def _run_ib_loop(self):
        """
        Hauptschleife im dedizierten Thread

        Erstellt einen eigenen asyncio Event Loop der unabhängig
        vom Qt Event Loop läuft.
        """
        print("🔄 IB Event Loop startet...")

        # Eigener Event Loop für diesen Thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._process_commands())
        except Exception as e:
            print(f"❌ IB Event Loop Fehler: {e}")
            traceback.print_exc()
            self.signals.service_error.emit(str(e))
        finally:
            # Cleanup
            if self._ib and self._ib.isConnected():
                self._ib.disconnect()
            self._loop.close()
            self._loop = None
            print("🔄 IB Event Loop beendet")

    async def _process_commands(self):
        """
        Verarbeite Befehle aus der Queue

        Diese Methode läuft im IB Thread und verarbeitet:
        - Commands aus der Queue (von Qt Thread gesendet)
        - IB Events (über ib.sleep())
        """
        while self._running:
            try:
                # Non-blocking check für Commands
                try:
                    cmd = self._command_queue.get_nowait()
                except queue.Empty:
                    # Keine Commands - IB Events verarbeiten
                    if self._ib and self._connected:
                        self._ib.sleep(0.01)  # Process IB events - OK im IB Thread!
                    else:
                        await asyncio.sleep(0.1)
                    continue

                # Command verarbeiten
                await self._handle_command(cmd)

            except Exception as e:
                print(f"❌ Command Processing Error: {e}")
                traceback.print_exc()
                await asyncio.sleep(0.1)

    async def _handle_command(self, cmd: IBCommand):
        """Verarbeite einzelnen Command"""
        try:
            if cmd.type == CommandType.STOP:
                await self._do_disconnect()
                self._running = False

            elif cmd.type == CommandType.CONNECT:
                await self._do_connect(cmd.data)

            elif cmd.type == CommandType.DISCONNECT:
                await self._do_disconnect()

            elif cmd.type == CommandType.PLACE_ORDER:
                await self._do_place_order(cmd.data, cmd.callback_id)

            elif cmd.type == CommandType.CANCEL_ORDER:
                await self._do_cancel_order(cmd.data)

            elif cmd.type == CommandType.SUBSCRIBE_MARKET_DATA:
                await self._do_subscribe(cmd.data)

            elif cmd.type == CommandType.UNSUBSCRIBE_MARKET_DATA:
                await self._do_unsubscribe(cmd.data)

            elif cmd.type == CommandType.GET_ACCOUNT:
                await self._do_get_account()

            elif cmd.type == CommandType.GET_MARKET_DATA_SNAPSHOT:
                await self._do_get_snapshot(cmd.data, cmd.callback_id)

        except Exception as e:
            print(f"❌ Command {cmd.type} failed: {e}")
            traceback.print_exc()

    # ==================== Connection ====================

    async def _do_connect(self, data: dict):
        """Verbinde mit IB (im IB Thread)"""
        config = data.get('config')
        if not config:
            self.signals.connected.emit(False, "Keine Konfiguration")
            return

        self._config = config

        # Falls bereits verbunden, erst trennen
        if self._ib and self._ib.isConnected():
            print("🔄 Trenne bestehende Verbindung...")
            self._ib.disconnect()

        self._ib = IB()

        try:
            print(f"🔌 Verbinde mit IB auf {config.host}:{config.port}...")

            await self._ib.connectAsync(
                host=config.host,
                port=config.port,
                clientId=config.client_id
            )

            self._connected = True

            # Event Handlers registrieren
            self._ib.orderStatusEvent += self._on_order_status
            self._ib.execDetailsEvent += self._on_execution
            self._ib.errorEvent += self._on_ib_error
            self._ib.disconnectedEvent += self._on_disconnected

            # Account holen
            if not config.account:
                accounts = self._ib.managedAccounts()
                if accounts:
                    self._config.account = accounts[0]
                    print(f"📊 Account: {self._config.account}")

            mode = "Paper Trading" if config.paper_trading else "LIVE"
            msg = f"Verbunden ({mode}, Port {config.port})"
            print(f"✅ {msg}")

            self.signals.connected.emit(True, msg)

        except Exception as e:
            self._connected = False
            error_msg = f"Verbindungsfehler: {e}"
            print(f"❌ {error_msg}")
            self.signals.connected.emit(False, error_msg)

    async def _do_disconnect(self):
        """Trenne Verbindung (im IB Thread)"""
        print("🔌 Trenne IB Verbindung...")

        if self._ib:
            # Unsubscribe all market data
            for symbol in list(self._subscribed_symbols):
                if symbol in self._tickers:
                    try:
                        self._ib.cancelMktData(self._tickers[symbol].contract)
                    except:
                        pass

            self._subscribed_symbols.clear()
            self._tickers.clear()
            self._contracts.clear()

            with self._cache_lock:
                self._market_data_cache.clear()

            if self._ib.isConnected():
                self._ib.disconnect()
            self._ib = None

        self._connected = False
        print("✅ IB Verbindung getrennt")
        self.signals.disconnected.emit()

    def _on_disconnected(self):
        """Callback wenn IB Verbindung verloren geht"""
        print("⚠️ IB Verbindung verloren!")
        self._connected = False
        self.signals.connection_lost.emit()

    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        """Callback für IB Fehler"""
        # Ignoriere Info-Messages (Codes 2104, 2106, 2158)
        if errorCode in [2104, 2106, 2158]:
            return

        print(f"⚠️ IB Error {errorCode}: {errorString}")

        # Connection lost errors
        if errorCode in [1100, 1101, 1102, 2110]:
            self._connected = False
            self.signals.connection_lost.emit()

    # ==================== Market Data (PUSH!) ====================

    async def _do_subscribe(self, data: dict):
        """
        Subscribiere Market Data für Symbole

        Verwendet Callbacks (PUSH) statt Polling für Market Data Updates.
        Das ist effizienter und blockiert nicht.
        """
        symbols = data.get('symbols', [])

        if not self._ib or not self._connected:
            print("⚠️ Kann nicht subscribieren - nicht verbunden")
            return

        for symbol in symbols:
            if symbol in self._subscribed_symbols:
                print(f"ℹ️ {symbol} bereits subscribed")
                continue

            try:
                print(f"📊 Subscribiere Market Data für {symbol}...")

                # Contract erstellen und qualifizieren
                contract = Stock(symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)

                if qualified:
                    contract = qualified[0]
                    self._contracts[symbol] = contract
                    print(f"✅ Contract qualifiziert: {symbol} (conId: {contract.conId})")
                else:
                    print(f"⚠️ Contract konnte nicht qualifiziert werden: {symbol}")
                    continue

                # Market Data subscribieren
                ticker = self._ib.reqMktData(contract, '', False, False)
                self._tickers[symbol] = ticker

                # Callback für Updates registrieren (PUSH!)
                ticker.updateEvent += lambda t, s=symbol: self._on_ticker_update(s, t)

                self._subscribed_symbols.add(symbol)
                print(f"✅ Market Data subscribed: {symbol}")

            except Exception as e:
                print(f"❌ Fehler beim Subscribieren von {symbol}: {e}")

    def _on_ticker_update(self, symbol: str, ticker):
        """
        Callback wenn Ticker Update kommt (PUSH!)

        Wird von ib_insync aufgerufen wenn neue Daten kommen.
        Emittiert Qt Signal für Thread-sichere Kommunikation mit UI.
        """
        try:
            data = {
                'symbol': symbol,
                'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0.0,
                'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0.0,
                'last': float(ticker.last) if ticker.last and ticker.last > 0 else 0.0,
                'close': float(ticker.close) if ticker.close and ticker.close > 0 else 0.0,
                'volume': ticker.volume if ticker.volume else 0,
                'high': float(ticker.high) if ticker.high and ticker.high > 0 else 0.0,
                'low': float(ticker.low) if ticker.low and ticker.low > 0 else 0.0,
                'timestamp': datetime.now().isoformat(),
            }

            # Cache aktualisieren (thread-safe)
            with self._cache_lock:
                self._market_data_cache[symbol] = data

            # Signal an Qt Thread (Thread-safe!)
            self.signals.market_data_update.emit(data)

        except Exception as e:
            print(f"❌ Ticker Update Fehler für {symbol}: {e}")

    async def _do_unsubscribe(self, data: dict):
        """Unsubscribe Market Data"""
        symbols = data.get('symbols', [])

        for symbol in symbols:
            if symbol not in self._subscribed_symbols:
                continue

            try:
                if symbol in self._tickers:
                    ticker = self._tickers.pop(symbol)
                    self._ib.cancelMktData(ticker.contract)

                self._subscribed_symbols.discard(symbol)
                self._contracts.pop(symbol, None)

                with self._cache_lock:
                    self._market_data_cache.pop(symbol, None)

                print(f"✅ Market Data unsubscribed: {symbol}")

            except Exception as e:
                print(f"❌ Fehler beim Unsubscribe von {symbol}: {e}")

    async def _do_get_snapshot(self, data: dict, callback_id: str):
        """
        Hole einmaligen Market Data Snapshot

        Für Fälle wo kein Subscription nötig ist.
        """
        symbol = data.get('symbol')

        if not self._ib or not self._connected:
            return

        try:
            # Contract
            if symbol in self._contracts:
                contract = self._contracts[symbol]
            else:
                contract = Stock(symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]

            # Snapshot request
            ticker = self._ib.reqMktData(contract, '', True, False)  # snapshot=True

            # Warte auf Daten
            for _ in range(30):  # Max 3 Sekunden
                self._ib.sleep(0.1)
                if ticker.last and ticker.last > 0:
                    break

            data = {
                'symbol': symbol,
                'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0.0,
                'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0.0,
                'last': float(ticker.last) if ticker.last and ticker.last > 0 else 0.0,
                'close': float(ticker.close) if ticker.close and ticker.close > 0 else 0.0,
            }

            # Signal emittieren
            self.signals.market_data_update.emit(data)

        except Exception as e:
            print(f"❌ Snapshot Fehler für {symbol}: {e}")

    # ==================== Orders (NON-BLOCKING für Qt!) ====================

    async def _do_place_order(self, data: dict, callback_id: str):
        """
        Platziere Order (im IB Thread - non-blocking für Qt!)

        Wichtig: Diese Methode läuft im IB Thread, daher ist
        self.ib.placeOrder() und self.ib.sleep() hier OK!
        """
        order: Order = data.get('order')

        if not order:
            self.signals.order_error.emit(callback_id, "Keine Order übergeben")
            return

        if not self._connected or not self._ib:
            self.signals.order_error.emit(callback_id, "Nicht mit IB verbunden")
            return

        try:
            print(f"📝 Platziere Order: {order.side.value} {order.quantity}x {order.symbol}")

            # Contract
            if order.symbol in self._contracts:
                contract = self._contracts[order.symbol]
            else:
                contract = Stock(order.symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]
                    self._contracts[order.symbol] = contract
                else:
                    self.signals.order_error.emit(callback_id, f"Contract für {order.symbol} nicht gefunden")
                    return

            # IB Order erstellen
            if order.order_type == OrderType.LIMIT:
                ib_order = LimitOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity,
                    lmtPrice=float(order.limit_price)
                )
                print(f"   Limit Order @ ${order.limit_price}")
            else:
                ib_order = MarketOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity
                )
                print(f"   Market Order")

            ib_order.transmit = True
            ib_order.tif = 'DAY'
            ib_order.account = self._config.account

            # Order platzieren - SYNCHRON im IB Thread (blockiert NICHT Qt!)
            trade = self._ib.placeOrder(contract, ib_order)

            # Kurz warten auf initiale Bestätigung
            for _ in range(20):  # Max 2 Sekunden
                self._ib.sleep(0.1)
                if hasattr(trade, 'orderStatus') and trade.orderStatus.status not in ['PendingSubmit', '']:
                    break

            broker_id = str(trade.order.orderId)
            status = trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'Unknown'

            print(f"✅ Order platziert: ID={broker_id}, Status={status}")

            # Tracking
            self._order_callbacks[broker_id] = callback_id
            self._pending_orders[callback_id] = order

            # Signal an Qt Thread
            self.signals.order_placed.emit(callback_id, broker_id)

            # Auch Status Signal senden
            details = {
                'filled': trade.orderStatus.filled if hasattr(trade, 'orderStatus') else 0,
                'remaining': trade.orderStatus.remaining if hasattr(trade, 'orderStatus') else order.quantity,
                'avg_fill_price': trade.orderStatus.avgFillPrice if hasattr(trade, 'orderStatus') else 0,
            }
            self.signals.order_status_changed.emit(broker_id, status, details)

        except Exception as e:
            error_msg = f"Order Fehler: {e}"
            print(f"❌ {error_msg}")
            traceback.print_exc()
            self.signals.order_error.emit(callback_id, error_msg)

    def _on_order_status(self, trade):
        """Callback für Order Status Updates von IB"""
        try:
            broker_id = str(trade.order.orderId)
            status = trade.orderStatus.status

            details = {
                'filled': trade.orderStatus.filled,
                'remaining': trade.orderStatus.remaining,
                'avg_fill_price': trade.orderStatus.avgFillPrice,
            }

            print(f"📋 Order Status Update: ID={broker_id}, Status={status}")

            # Signal an Qt Thread
            self.signals.order_status_changed.emit(broker_id, status, details)

            # Bei Filled auch fill Signal
            if status == 'Filled':
                self.signals.order_filled.emit(broker_id, details)

        except Exception as e:
            print(f"❌ Order Status Callback Fehler: {e}")

    def _on_execution(self, trade, fill):
        """Callback für Trade Executions"""
        try:
            broker_id = str(trade.order.orderId)

            fill_info = {
                'exec_id': fill.execution.execId,
                'shares': fill.execution.shares,
                'price': float(fill.execution.price),
                'commission': float(fill.commissionReport.commission) if fill.commissionReport else 0.0,
                'time': fill.execution.time,
            }

            print(f"💰 Execution: ID={broker_id}, {fill_info['shares']}@${fill_info['price']:.2f}")

            # Signal an Qt Thread
            self.signals.order_filled.emit(broker_id, fill_info)

        except Exception as e:
            print(f"❌ Execution Callback Fehler: {e}")

    async def _do_cancel_order(self, data: dict):
        """Storniere Order"""
        broker_id = data.get('broker_order_id')

        if not broker_id or not self._ib:
            return

        try:
            # Finde Trade
            for trade in self._ib.trades():
                if str(trade.order.orderId) == broker_id:
                    self._ib.cancelOrder(trade.order)
                    print(f"🚫 Order {broker_id} storniert")
                    return

            print(f"⚠️ Order {broker_id} nicht gefunden")

        except Exception as e:
            print(f"❌ Cancel Order Fehler: {e}")

    async def _do_get_account(self):
        """Hole Account Info"""
        if not self._ib or not self._connected:
            return

        try:
            account_values = self._ib.accountValues(self._config.account)
            positions = self._ib.positions(self._config.account)

            summary = {
                'account': self._config.account,
                'buying_power': 0.0,
                'net_liquidation': 0.0,
                'cash': 0.0,
                'positions': []
            }

            for av in account_values:
                if av.tag == 'BuyingPower':
                    summary['buying_power'] = float(av.value)
                elif av.tag == 'NetLiquidation':
                    summary['net_liquidation'] = float(av.value)
                elif av.tag == 'CashBalance':
                    summary['cash'] = float(av.value)

            for pos in positions:
                summary['positions'].append({
                    'symbol': pos.contract.symbol,
                    'quantity': pos.position,
                    'avg_cost': pos.avgCost if hasattr(pos, 'avgCost') else 0,
                })

            self.signals.account_update.emit(summary)

        except Exception as e:
            print(f"❌ Account Info Fehler: {e}")

    # ==================== Public API (Thread-safe!) ====================
    # Diese Methoden werden vom Qt Thread aufgerufen

    def connect(self, config: IBKRConfig):
        """
        Verbinde mit IB (von Qt Thread aufgerufen)

        Non-blocking - Ergebnis kommt über signals.connected
        """
        if not self._running:
            self.start()

        self._command_queue.put(IBCommand(
            type=CommandType.CONNECT,
            data={'config': config}
        ))

    def disconnect(self):
        """
        Trenne Verbindung (von Qt Thread aufgerufen)

        Non-blocking - Ergebnis kommt über signals.disconnected
        """
        self._command_queue.put(IBCommand(type=CommandType.DISCONNECT))

    def subscribe_market_data(self, symbols: List[str]):
        """
        Subscribiere Market Data (von Qt Thread aufgerufen)

        Non-blocking - Updates kommen über signals.market_data_update
        """
        if not symbols:
            return

        self._command_queue.put(IBCommand(
            type=CommandType.SUBSCRIBE_MARKET_DATA,
            data={'symbols': list(symbols)}
        ))

    def unsubscribe_market_data(self, symbols: List[str]):
        """Unsubscribe Market Data"""
        if not symbols:
            return

        self._command_queue.put(IBCommand(
            type=CommandType.UNSUBSCRIBE_MARKET_DATA,
            data={'symbols': list(symbols)}
        ))

    def place_order(self, order: Order) -> str:
        """
        Platziere Order (von Qt Thread aufgerufen)

        Non-blocking - Ergebnis kommt über:
        - signals.order_placed (callback_id, broker_order_id)
        - signals.order_status_changed (broker_id, status, details)
        - signals.order_filled (broker_id, fill_info)
        - signals.order_error (callback_id, error_message)

        Returns:
            callback_id für Tracking
        """
        import uuid
        callback_id = str(uuid.uuid4())

        self._command_queue.put(IBCommand(
            type=CommandType.PLACE_ORDER,
            data={'order': order},
            callback_id=callback_id
        ))

        return callback_id

    def cancel_order(self, broker_order_id: str):
        """Storniere Order"""
        self._command_queue.put(IBCommand(
            type=CommandType.CANCEL_ORDER,
            data={'broker_order_id': broker_order_id}
        ))

    def request_account_update(self):
        """Fordere Account Update an"""
        self._command_queue.put(IBCommand(type=CommandType.GET_ACCOUNT))

    def get_cached_market_data(self, symbol: str) -> Optional[dict]:
        """
        Hole gecachte Market Data (Thread-safe read)

        Synchroner Zugriff auf den letzten bekannten Preis.
        Für Echtzeit-Updates sollten signals.market_data_update verwendet werden.
        """
        with self._cache_lock:
            return self._market_data_cache.get(symbol)

    def get_all_cached_market_data(self) -> Dict[str, dict]:
        """Hole alle gecachten Market Data"""
        with self._cache_lock:
            return dict(self._market_data_cache)

    def is_connected(self) -> bool:
        """Prüfe Verbindungsstatus (Thread-safe)"""
        return self._connected

    def is_running(self) -> bool:
        """Prüfe ob Service läuft"""
        return self._running and self._thread is not None and self._thread.is_alive()

    def get_subscribed_symbols(self) -> Set[str]:
        """Hole Liste der subscribierten Symbole"""
        return set(self._subscribed_symbols)


# ==================== Global Access ====================

_ibkr_service: Optional[IBKRService] = None

def get_ibkr_service() -> IBKRService:
    """
    Hole die globale IBKRService Instanz

    Startet den Service automatisch falls noch nicht laufend.

    Verwendung:
    ```python
    from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service

    service = get_ibkr_service()
    service.signals.market_data_update.connect(my_handler)
    service.connect(config)
    ```
    """
    global _ibkr_service
    if _ibkr_service is None:
        _ibkr_service = IBKRService.instance()
    if not _ibkr_service.is_running():
        _ibkr_service.start()
    return _ibkr_service


def stop_ibkr_service():
    """Stoppe den globalen IBKRService"""
    global _ibkr_service
    if _ibkr_service:
        _ibkr_service.stop()
        _ibkr_service = None
