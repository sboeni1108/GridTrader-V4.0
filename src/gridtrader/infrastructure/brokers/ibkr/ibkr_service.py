"""
IBKR Service - Dedizierter Thread mit run_forever() Event Loop
=============================================================

ARCHITEKTUR (Neu - November 2024):
----------------------------------
- Ein dedizierter Thread mit asyncio.run_forever()
- Alle IB-Operationen werden im IB Thread ausgeführt
- Qt Main Thread kommuniziert via loop.call_soon_threadsafe()
- Market Data kommt via Callbacks (PUSH)
- Orders werden non-blocking platziert

WICHTIG:
- Der Qt Event Loop und IB Event Loop laufen komplett getrennt
- Keine asyncio Operationen im Qt Thread!
- Keine Qt Operationen im IB Thread (ausser Signals emittieren)

Verwendung:
-----------
```python
# Service holen (Singleton, startet automatisch)
service = get_ibkr_service()

# Signals verbinden
service.signals.connected.connect(on_connected)
service.signals.market_data_update.connect(on_market_data)
service.signals.order_placed.connect(on_order_placed)

# Verbinden (non-blocking)
config = IBKRConfig(host="127.0.0.1", port=7497, client_id=1)
service.connect(config)

# Market Data (PUSH via signals)
service.subscribe_market_data(["AAPL", "MSFT"])

# Order platzieren (non-blocking)
callback_id = service.place_order(order)
# Ergebnis kommt via signals.order_placed / signals.order_filled
```
"""
import asyncio
import nest_asyncio
nest_asyncio.apply()
import threading
import sys
from typing import Dict, Optional, List, Set, Any, Callable
import pandas as pd
import concurrent.futures
from dataclasses import dataclass
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
    IBKR Service mit dediziertem Thread und run_forever() Event Loop

    Löst das Event Loop Konflikt zwischen Qt und ib_insync:
    - Qt läuft im Main Thread mit seinem Event Loop
    - IB läuft in dediziertem Thread mit eigenem asyncio Event Loop
    - Kommunikation via loop.call_soon_threadsafe() und Qt Signals
    """

    _instance: Optional['IBKRService'] = None
    _instance_lock = threading.Lock()

    @classmethod
    def instance(cls) -> 'IBKRService':
        """Singleton - Thread-safe"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset Singleton (für Tests)"""
        with cls._instance_lock:
            if cls._instance:
                cls._instance.stop()
            cls._instance = None

    def __init__(self):
        if IBKRService._instance is not None:
            raise RuntimeError("Verwende IBKRService.instance() statt direkter Instanziierung")

        # Qt Signals
        self.signals = IBKRServiceSignals()

        # Konfiguration
        self._config: Optional[IBKRConfig] = None

        # IB State (NUR im IB Thread!)
        self._ib: Optional[IB] = None
        self._connected = False
        self._subscribed_symbols: Set[str] = set()
        self._contracts: Dict[str, Contract] = {}
        self._tickers: Dict[str, Any] = {}

        # Market Data Cache (thread-safe)
        self._market_data_cache: Dict[str, dict] = {}
        self._cache_lock = threading.Lock()

        # Order Tracking
        self._order_callbacks: Dict[str, str] = {}  # broker_id -> callback_id
        self._pending_orders: Dict[str, Order] = {}  # callback_id -> Order

        # Thread und Event Loop
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._loop_ready = threading.Event()  # Signalisiert wenn Loop bereit ist

        # IB Event Processing Task
        self._ib_task: Optional[asyncio.Task] = None

        print("IBKRService initialisiert")

    # ==================== Thread Management ====================

    def start(self):
        """Starte den IB Service Thread"""
        if self._thread and self._thread.is_alive():
            print("IBKRService läuft bereits")
            return

        self._running = True
        self._loop_ready.clear()

        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="IBKRService-Thread",
            daemon=True
        )
        self._thread.start()

        # Warte bis Event Loop bereit ist (max 5 Sekunden)
        if not self._loop_ready.wait(timeout=5.0):
            print("WARNUNG: Event Loop Start Timeout")
        else:
            print("IBKRService Thread gestartet")

    def stop(self):
        """Stoppe den IB Service Thread"""
        if not self._running:
            return

        print("Stoppe IBKRService...")
        self._running = False

        # Stoppe Loop im IB Thread
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        # Warte auf Thread
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                print("WARNUNG: IBKRService Thread konnte nicht sauber beendet werden")
            else:
                print("IBKRService Thread beendet")
            self._thread = None

    def _run_event_loop(self):
        """
        Hauptfunktion im dedizierten Thread

        Erstellt einen eigenen asyncio Event Loop der mit run_forever()
        läuft - komplett unabhängig vom Qt Event Loop.
        """
        print("IB Event Loop startet...")

        # Eigener Event Loop für diesen Thread
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            # Signalisiere dass Loop bereit ist
            self._loop_ready.set()

            # Starte IB Event Processor (läuft im Hintergrund)
            self._ib_task = self._loop.create_task(self._ib_event_processor())

            # run_forever() - blockiert bis stop() aufgerufen wird
            self._loop.run_forever()

        except Exception as e:
            print(f"IB Event Loop Fehler: {e}")
            traceback.print_exc()
            self.signals.service_error.emit(str(e))
        finally:
            # Cleanup
            self._cleanup_sync()

            # Pending Tasks canceln
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()

            # Loop schliessen
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()
            self._loop = None
            print("IB Event Loop beendet")

    def _cleanup_sync(self):
        """Synchrones Cleanup (im IB Thread)"""
        if self._ib:
            try:
                if self._ib.isConnected():
                    # Unsubscribe alle Market Data
                    for ticker in self._tickers.values():
                        try:
                            self._ib.cancelMktData(ticker.contract)
                        except:
                            pass
                    self._ib.disconnect()
            except Exception as e:
                print(f"Cleanup Fehler: {e}")
            self._ib = None

        self._connected = False
        self._subscribed_symbols.clear()
        self._tickers.clear()
        self._contracts.clear()
        with self._cache_lock:
            self._market_data_cache.clear()

    async def _ib_event_processor(self):
        """
        Hintergrund-Task der IB Events verarbeitet

        WICHTIG: Bei connectAsync() verarbeitet ib_insync Events automatisch
        über den asyncio Event Loop. Wir müssen nur regelmäßig yielden damit
        call_soon_threadsafe() Callbacks ausgeführt werden können.

        NICHT ib.sleep() verwenden - das verursacht "event loop already running"!
        """
        while self._running:
            try:
                # Yield zum Event Loop - ib_insync verarbeitet Events automatisch
                # bei async Verbindung (connectAsync)
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"IB Event Processor Fehler: {e}")
                await asyncio.sleep(0.5)

    # ==================== Connection ====================

    def connect(self, config: IBKRConfig):
        """
        Verbinde mit IB (aufgerufen vom Qt Thread)

        Non-blocking - Ergebnis kommt über signals.connected
        """
        if not self._running:
            self.start()

        if not self._loop or not self._loop.is_running():
            self.signals.connected.emit(False, "Event Loop nicht bereit")
            return

        # Schedule im IB Thread
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._do_connect(config), loop=self._loop)
        )

    async def _do_connect(self, config: IBKRConfig):
        """Verbinde mit IB (läuft im IB Thread)"""
        self._config = config

        # Falls bereits verbunden, erst trennen
        if self._ib and self._ib.isConnected():
            print("Trenne bestehende Verbindung...")
            self._ib.disconnect()
            self._connected = False

        self._ib = IB()

        try:
            print(f"Verbinde mit IB auf {config.host}:{config.port}...")

            await self._ib.connectAsync(
                host=config.host,
                port=config.port,
                clientId=config.client_id
            )

            self._connected = True

            # Event Handlers
            self._ib.orderStatusEvent += self._on_order_status
            self._ib.execDetailsEvent += self._on_execution
            self._ib.errorEvent += self._on_ib_error
            self._ib.disconnectedEvent += self._on_disconnected

            # Account
            if not config.account:
                accounts = self._ib.managedAccounts()
                if accounts:
                    self._config.account = accounts[0]
                    print(f"Account: {self._config.account}")

            mode = "Paper Trading" if config.paper_trading else "LIVE"
            msg = f"Verbunden ({mode}, Port {config.port})"
            print(f"OK: {msg}")

            self.signals.connected.emit(True, msg)

        except Exception as e:
            self._connected = False
            error_msg = f"Verbindungsfehler: {e}"
            print(f"FEHLER: {error_msg}")
            self.signals.connected.emit(False, error_msg)

    def disconnect(self):
        """
        Trenne Verbindung (aufgerufen vom Qt Thread)

        Non-blocking - Ergebnis kommt über signals.disconnected
        """
        if not self._loop or not self._loop.is_running():
            return

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._do_disconnect(), loop=self._loop)
        )

    async def _do_disconnect(self):
        """Trenne Verbindung (läuft im IB Thread)"""
        print("Trenne IB Verbindung...")

        if self._ib:
            # Unsubscribe alle Market Data
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
        print("IB Verbindung getrennt")
        self.signals.disconnected.emit()

    def _on_disconnected(self):
        """IB Callback bei Verbindungsverlust"""
        print("IB Verbindung verloren!")
        self._connected = False
        self.signals.connection_lost.emit()

    def _on_ib_error(self, reqId, errorCode, errorString, contract):
        """IB Error Callback"""
        # Info-Messages ignorieren
        if errorCode in [2104, 2106, 2158, 2119]:
            return

        print(f"IB Error {errorCode}: {errorString}")

        # Connection lost errors
        if errorCode in [1100, 1101, 1102, 2110]:
            self._connected = False
            self.signals.connection_lost.emit()

    # ==================== Market Data ====================

    def subscribe_market_data(self, symbols: List[str]):
        """
        Subscribiere Market Data (aufgerufen vom Qt Thread)

        Non-blocking - Updates kommen über signals.market_data_update
        """
        if not symbols:
            return

        if not self._loop or not self._loop.is_running():
            print("WARNUNG: Kann nicht subscribieren - Event Loop nicht bereit")
            return

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._do_subscribe(list(symbols)), loop=self._loop)
        )

    async def _do_subscribe(self, symbols: List[str]):
        """Subscribe Market Data (läuft im IB Thread)"""
        if not self._ib or not self._connected:
            print("Kann nicht subscribieren - nicht verbunden")
            return

        for symbol in symbols:
            if symbol in self._subscribed_symbols:
                print(f"{symbol} bereits subscribed")
                continue

            try:
                print(f"Subscribiere Market Data für {symbol}...")

                # Contract erstellen und qualifizieren
                contract = Stock(symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)

                if qualified:
                    contract = qualified[0]
                    self._contracts[symbol] = contract
                    print(f"Contract qualifiziert: {symbol} (conId: {contract.conId})")
                else:
                    print(f"Contract konnte nicht qualifiziert werden: {symbol}")
                    continue

                # Market Data subscribieren
                ticker = self._ib.reqMktData(contract, '', False, False)
                self._tickers[symbol] = ticker

                # Callback für Updates (PUSH!)
                ticker.updateEvent += lambda t, s=symbol: self._on_ticker_update(s, t)

                self._subscribed_symbols.add(symbol)
                print(f"Market Data subscribed: {symbol}")

            except Exception as e:
                print(f"Fehler beim Subscribieren von {symbol}: {e}")

    def _on_ticker_update(self, symbol: str, ticker):
        """
        Ticker Update Callback (PUSH!)

        Wird von ib_insync aufgerufen wenn neue Daten kommen.
        Emittiert Qt Signal für Thread-sichere Kommunikation.
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

            # Signal an Qt Thread
            self.signals.market_data_update.emit(data)

        except Exception as e:
            print(f"Ticker Update Fehler für {symbol}: {e}")

    def unsubscribe_market_data(self, symbols: List[str]):
        """Unsubscribe Market Data (aufgerufen vom Qt Thread)"""
        if not symbols or not self._loop or not self._loop.is_running():
            return

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._do_unsubscribe(list(symbols)), loop=self._loop)
        )

    async def _do_unsubscribe(self, symbols: List[str]):
        """Unsubscribe Market Data (läuft im IB Thread)"""
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

                print(f"Market Data unsubscribed: {symbol}")

            except Exception as e:
                print(f"Fehler beim Unsubscribe von {symbol}: {e}")

    # ==================== Orders ====================

    def place_order(self, order: Order) -> str:
        """
        Platziere Order (aufgerufen vom Qt Thread)

        Non-blocking - Ergebnis kommt über Signals:
        - signals.order_placed(callback_id, broker_order_id)
        - signals.order_status_changed(broker_id, status, details)
        - signals.order_filled(broker_id, fill_info)
        - signals.order_error(callback_id, error_message)

        Returns:
            callback_id für Tracking
        """
        import uuid
        callback_id = str(uuid.uuid4())

        print(f">>> place_order() aufgerufen: {order.side.value} {order.quantity}x {order.symbol}")
        print(f">>> callback_id: {callback_id[:8]}...")
        print(f">>> Loop running: {self._loop is not None and self._loop.is_running()}")
        print(f">>> Connected: {self._connected}")

        if not self._loop or not self._loop.is_running():
            print(">>> ERROR: Event Loop nicht bereit!")
            self.signals.order_error.emit(callback_id, "Event Loop nicht bereit")
            return callback_id

        print(">>> Scheduling _do_place_order via call_soon_threadsafe...")
        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                self._do_place_order(order, callback_id),
                loop=self._loop
            )
        )
        print(">>> call_soon_threadsafe() returned")

        return callback_id

    async def _do_place_order(self, order: Order, callback_id: str):
        """
        Platziere Order (läuft im IB Thread)

        WICHTIG: Da wir im IB Thread sind, blockiert ib.placeOrder()
        und ib.sleep() NICHT den Qt Thread!
        """
        print(f">>> _do_place_order GESTARTET für {callback_id[:8]}...")

        if not order:
            print(">>> ERROR: Keine Order übergeben")
            self.signals.order_error.emit(callback_id, "Keine Order übergeben")
            return

        if not self._connected or not self._ib:
            print(f">>> ERROR: Nicht verbunden (connected={self._connected}, ib={self._ib is not None})")
            self.signals.order_error.emit(callback_id, "Nicht mit IB verbunden")
            return

        # Zusätzliche Verbindungsprüfung
        if not self._ib.isConnected():
            print(">>> ERROR: IB.isConnected() = False")
            self.signals.order_error.emit(callback_id, "IB Verbindung verloren")
            return

        try:
            print(f">>> Order: {order.side.value} {order.quantity}x {order.symbol}")

            # Contract
            if order.symbol in self._contracts:
                contract = self._contracts[order.symbol]
                print(f">>> Contract aus Cache: {contract.symbol} (conId={contract.conId})")
            else:
                print(f">>> Qualifiziere Contract für {order.symbol}...")
                contract = Stock(order.symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]
                    self._contracts[order.symbol] = contract
                    print(f">>> Contract qualifiziert: {contract.symbol} (conId={contract.conId})")
                else:
                    print(f">>> ERROR: Contract für {order.symbol} nicht gefunden")
                    self.signals.order_error.emit(
                        callback_id,
                        f"Contract für {order.symbol} nicht gefunden"
                    )
                    return

            # IB Order erstellen
            if order.order_type == OrderType.LIMIT:
                # WICHTIG: Limitpreis auf 2 Dezimalstellen runden (Tick Size für US Aktien)
                limit_price = round(float(order.limit_price), 2)
                ib_order = LimitOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity,
                    lmtPrice=limit_price
                )
                print(f">>> Limit Order: {ib_order.action} {ib_order.totalQuantity}x @ ${limit_price:.2f}")
            else:
                ib_order = MarketOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity
                )
                print(f">>> Market Order: {ib_order.action} {ib_order.totalQuantity}x")

            ib_order.transmit = True
            ib_order.tif = 'DAY'
            if self._config and self._config.account:
                ib_order.account = self._config.account
                print(f">>> Account: {self._config.account}")

            # Order platzieren
            print(f">>> Rufe ib.placeOrder() auf...")
            trade = self._ib.placeOrder(contract, ib_order)
            broker_id = str(trade.order.orderId)
            print(f">>> placeOrder() zurückgekehrt, orderId={broker_id}")

            # WICHTIG: Tracking und order_placed SOFORT emittieren,
            # BEVOR auf Status gewartet wird! Sonst wird ein schneller Fill
            # verpasst, weil _on_order_status vor order_placed aufgerufen wird.
            self._order_callbacks[broker_id] = callback_id
            self._pending_orders[callback_id] = order
            self.signals.order_placed.emit(callback_id, broker_id)
            print(f">>> order_placed Signal emittiert für {broker_id}")

            # Warte auf initiale Bestätigung (max 2 Sekunden)
            # WICHTIG: await asyncio.sleep() statt ib.sleep() verwenden!
            print(">>> Warte auf Order-Bestätigung...")
            for i in range(20):
                await asyncio.sleep(0.1)  # NICHT ib.sleep() - verursacht "loop already running"
                status = trade.orderStatus.status
                if status not in ['PendingSubmit', '']:
                    print(f">>> Status nach {i*0.1:.1f}s: {status}")
                    break

            status = trade.orderStatus.status
            print(f">>> Order Status: ID={broker_id}, Status={status}")

            details = {
                'filled': trade.orderStatus.filled,
                'remaining': trade.orderStatus.remaining,
                'avg_fill_price': trade.orderStatus.avgFillPrice,
            }
            self.signals.order_status_changed.emit(broker_id, status, details)

        except Exception as e:
            error_msg = f"Order Fehler: {e}"
            print(f"FEHLER: {error_msg}")
            traceback.print_exc()
            self.signals.order_error.emit(callback_id, error_msg)

    def _on_order_status(self, trade):
        """Order Status Update Callback"""
        try:
            broker_id = str(trade.order.orderId)
            status = trade.orderStatus.status

            details = {
                'filled': trade.orderStatus.filled,
                'remaining': trade.orderStatus.remaining,
                'avg_fill_price': trade.orderStatus.avgFillPrice,
            }

            print(f"Order Status: ID={broker_id}, Status={status}")

            self.signals.order_status_changed.emit(broker_id, status, details)

            if status == 'Filled':
                self.signals.order_filled.emit(broker_id, details)

        except Exception as e:
            print(f"Order Status Callback Fehler: {e}")

    def _on_execution(self, trade, fill):
        """Trade Execution Callback"""
        try:
            broker_id = str(trade.order.orderId)

            fill_info = {
                'exec_id': fill.execution.execId,
                'shares': fill.execution.shares,
                'price': float(fill.execution.price),
                'commission': float(fill.commissionReport.commission) if fill.commissionReport else 0.0,
                'time': fill.execution.time,
            }

            print(f"Execution: ID={broker_id}, {fill_info['shares']}@${fill_info['price']:.2f}")

            self.signals.order_filled.emit(broker_id, fill_info)

        except Exception as e:
            print(f"Execution Callback Fehler: {e}")

    def cancel_order(self, broker_order_id: str):
        """Storniere Order (aufgerufen vom Qt Thread)"""
        if not self._loop or not self._loop.is_running():
            return

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(
                self._do_cancel_order(broker_order_id),
                loop=self._loop
            )
        )

    async def _do_cancel_order(self, broker_order_id: str):
        """Storniere Order (läuft im IB Thread)"""
        if not broker_order_id or not self._ib:
            return

        try:
            for trade in self._ib.trades():
                if str(trade.order.orderId) == broker_order_id:
                    self._ib.cancelOrder(trade.order)
                    print(f"Order {broker_order_id} storniert")
                    return

            print(f"Order {broker_order_id} nicht gefunden")

        except Exception as e:
            print(f"Cancel Order Fehler: {e}")

    # ==================== Account ====================

    def request_account_update(self):
        """Fordere Account Update an (aufgerufen vom Qt Thread)"""
        if not self._loop or not self._loop.is_running():
            return

        self._loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(self._do_get_account(), loop=self._loop)
        )

    async def _do_get_account(self):
        """Hole Account Info (läuft im IB Thread)"""
        if not self._ib or not self._connected:
            return

        try:
            account = self._config.account if self._config else None
            account_values = self._ib.accountValues(account)
            positions = self._ib.positions(account)

            summary = {
                'account': account,
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
            print(f"Account Info Fehler: {e}")

    # ==================== Historical Data ====================

    def get_historical_data(
        self,
        symbol: str,
        duration: str = "30 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
        timeout: float = 60.0
    ) -> Optional[pd.DataFrame]:
        """
        Hole historische Daten synchron (aufgerufen vom Qt Thread oder Worker Thread).

        BLOCKING - Wartet auf Ergebnis!

        Args:
            symbol: Aktien-Symbol (z.B. "AAPL")
            duration: Zeitraum (z.B. "30 D", "1 W", "6 M")
            bar_size: Kerzengröße (z.B. "1 min", "5 mins", "1 hour", "1 day")
            what_to_show: Datentyp ("TRADES", "MIDPOINT", "BID", "ASK")
            use_rth: Nur Regular Trading Hours
            timeout: Timeout in Sekunden

        Returns:
            DataFrame mit OHLCV Daten oder None bei Fehler
        """
        if not self._loop or not self._loop.is_running():
            print("ERROR: Event Loop nicht bereit für historische Daten")
            return None

        if not self._connected:
            print("ERROR: Nicht verbunden für historische Daten")
            return None

        # Führe async Funktion im IB Thread aus und warte auf Ergebnis
        future = concurrent.futures.Future()

        def run_async():
            asyncio.ensure_future(
                self._do_get_historical_data(
                    symbol, duration, bar_size, what_to_show, use_rth, future
                ),
                loop=self._loop
            )

        self._loop.call_soon_threadsafe(run_async)

        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print(f"Timeout beim Abruf historischer Daten für {symbol}")
            return None
        except Exception as e:
            print(f"Fehler beim Abruf historischer Daten: {e}")
            return None

    async def _do_get_historical_data(
        self,
        symbol: str,
        duration: str,
        bar_size: str,
        what_to_show: str,
        use_rth: bool,
        future: concurrent.futures.Future
    ):
        """Hole historische Daten (läuft im IB Thread)"""
        try:
            if not self._ib or not self._connected:
                future.set_result(None)
                return

            print(f"Hole historische Daten: {symbol}, {duration}, {bar_size}...")

            # Contract erstellen/aus Cache holen
            if symbol in self._contracts:
                contract = self._contracts[symbol]
            else:
                contract = Stock(symbol, 'SMART', 'USD')
                qualified = await self._ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]
                    self._contracts[symbol] = contract
                else:
                    print(f"Contract für {symbol} nicht gefunden")
                    future.set_result(None)
                    return

            # Historische Daten abrufen
            bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1
            )

            if not bars:
                print(f"Keine historischen Daten für {symbol}")
                future.set_result(None)
                return

            # Konvertiere zu DataFrame
            data = []
            for bar in bars:
                data.append({
                    'date': bar.date,
                    'open': bar.open,
                    'high': bar.high,
                    'low': bar.low,
                    'close': bar.close,
                    'volume': bar.volume
                })

            df = pd.DataFrame(data)

            # Setze date als Index
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)

            print(f"Historische Daten erhalten: {len(df)} Bars für {symbol}")
            future.set_result(df)

        except Exception as e:
            print(f"Fehler beim Abruf historischer Daten für {symbol}: {e}")
            traceback.print_exc()
            future.set_result(None)

    def get_event_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Hole den IB Event Loop (für Thread-safe async Aufrufe)"""
        return self._loop

    # ==================== Query Methods (Thread-safe) ====================

    def get_cached_market_data(self, symbol: str) -> Optional[dict]:
        """
        Hole gecachte Market Data (Thread-safe)

        Für Echtzeit-Updates signals.market_data_update verwenden!
        """
        with self._cache_lock:
            return self._market_data_cache.get(symbol)

    def get_all_cached_market_data(self) -> Dict[str, dict]:
        """Hole alle gecachten Market Data"""
        with self._cache_lock:
            return dict(self._market_data_cache)

    def is_connected(self) -> bool:
        """Prüfe Verbindungsstatus"""
        return self._connected

    def is_running(self) -> bool:
        """Prüfe ob Service läuft"""
        return self._running and self._thread is not None and self._thread.is_alive()

    def get_subscribed_symbols(self) -> Set[str]:
        """Hole subscribed Symbole"""
        return set(self._subscribed_symbols)


# ==================== Global Access ====================

_ibkr_service: Optional[IBKRService] = None

def get_ibkr_service() -> IBKRService:
    """
    Hole die globale IBKRService Instanz

    Startet den Service automatisch falls nicht laufend.
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

