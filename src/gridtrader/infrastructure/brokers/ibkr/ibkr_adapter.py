import nest_asyncio
nest_asyncio.apply()
"""
IBKR Broker Adapter für GridTrader V2.0
Echte Integration mit Interactive Brokers TWS/Gateway
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import asyncio
from dataclasses import dataclass
import pandas as pd

from ib_insync import (
    IB, Stock, MarketOrder, LimitOrder, 
    util, Contract, Order as IBOrder
)

from gridtrader.domain.models.order import (
    Order, Trade, Position,
    OrderSide, OrderType, OrderStatus
)


@dataclass
class IBKRConfig:
    """IBKR Verbindungskonfiguration"""
    host: str = "127.0.0.1"
    port: int = 7497  # 7497 für Paper, 7496 für Live
    client_id: int = 1
    account: str = ""
    paper_trading: bool = True


class IBKRBrokerAdapter:
    """
    IBKR Broker Adapter mit ib_insync
    Implementiert echte Verbindung zu TWS/Gateway
    """
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.ib = IB()
        self.connected = False
        self.event_loop = None  # Store event loop for thread-safe async operations

        # Cache für Contracts
        self._contract_cache: Dict[str, Contract] = {}
        
        # Order Tracking
        self._orders: Dict[str, IBOrder] = {}
        self._order_mapping: Dict[str, Order] = {}  # IB ID -> Domain Order
        
    async def connect(self) -> bool:
        """Verbinde mit TWS/Gateway"""
        try:
            await self.ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id
            )

            self.connected = True
            # Store event loop for thread-safe access by other modules (e.g., backtest)
            self.event_loop = asyncio.get_running_loop()
            
            # Hole Account-Info
            if not self.config.account:
                accounts = self.ib.managedAccounts()
                if accounts:
                    self.config.account = accounts[0]
                    print(f"📊 Verbunden mit Account: {self.config.account}")
            
            # Subscription für Updates
            self.ib.orderStatusEvent += self._on_order_status
            self.ib.execDetailsEvent += self._on_execution
            self.ib.commissionReportEvent += self._on_commission_report

            return True
            
        except Exception as e:
            print(f"❌ IBKR Verbindungsfehler: {e}")
            self.connected = False
            return False
    
    async def disconnect(self) -> None:
        """Trenne Verbindung"""
        if self.connected:
            self.ib.disconnect()
            self.connected = False
            self.event_loop = None
    
    def is_connected(self) -> bool:
        """Prüfe Verbindungsstatus"""
        return self.connected and self.ib.isConnected()
    
    async def _get_contract(self, symbol: str) -> Contract:
        """Hole oder erstelle Contract für Symbol (async mit Qualifizierung)"""
        if symbol not in self._contract_cache:
            contract = Stock(symbol, 'SMART', 'USD')
            # Qualifiziere Contract async - WICHTIG für Web API!
            try:
                qualified = await self.ib.qualifyContractsAsync(contract)
                if qualified:
                    contract = qualified[0]
                    print(f"✅ Contract qualifiziert: {symbol} (conId: {contract.conId})")
                else:
                    print(f"⚠️ Contract konnte nicht qualifiziert werden: {symbol}")
            except Exception as e:
                print(f"⚠️ Fehler bei Contract-Qualifizierung für {symbol}: {e}")
            self._contract_cache[symbol] = contract
        return self._contract_cache[symbol]
        
    async def get_market_data(self, symbol: str) -> Dict:
        """Hole aktuelle Marktdaten"""
        print(f"DEBUG: get_market_data called for {symbol}")
        
        if not self.is_connected():
            raise ConnectionError("Nicht mit IBKR verbunden")

        contract = await self._get_contract(symbol)

        # Request Market Data
        ticker = self.ib.reqMktData(contract, '', False, False)
        
        # Warte auf Daten (synchron mit ib.sleep!)
        timeout = 30  # 3 Sekunden
        while timeout > 0:
            self.ib.sleep(0.1)  # Process IB events
            # Prüfe ob wir Daten haben
            if ticker.last and ticker.last > 0:
                print(f"DEBUG: Got data for {symbol}: last={ticker.last}")
                break
            timeout -= 1
        
        # Cancel subscription
        self.ib.cancelMktData(ticker)
        
        # Return real data
        result = {
            'symbol': symbol,
            'bid': float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0.0,
            'ask': float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0.0,
            'last': float(ticker.last) if ticker.last and ticker.last > 0 else 0.0,
            'close': float(ticker.close) if ticker.close and ticker.close > 0 else 0.0,
            'volume': ticker.volume if ticker.volume else 0,
            'time': ticker.time
        }
        
        print(f"DEBUG: Returning market data: {result}")
        return result
 
    
    async def get_historical_data(
        self, 
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
        what_to_show: str = "TRADES",
        use_rth: bool = True
    ) -> pd.DataFrame:
        """
        Hole historische Daten von IBKR
        
        Args:
            symbol: Trading Symbol
            duration: z.B. "1 D", "1 W", "1 M"
            bar_size: z.B. "1 min", "5 mins", "1 hour", "1 day"
            what_to_show: TRADES, BID, ASK, MIDPOINT
            use_rth: Nur Regular Trading Hours
            
        Returns:
            DataFrame mit OHLCV-Daten
        """
        if not self.is_connected():
            raise ConnectionError("Nicht mit IBKR verbunden")

        contract = await self._get_contract(symbol)

        bars = await self.ib.reqHistoricalDataAsync(
            contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=use_rth,
            formatDate=1
        )
        
        if not bars:
            return pd.DataFrame()
        
        # Konvertiere zu DataFrame
        df = util.df(bars)
        df.set_index('date', inplace=True)
        
        return df
    
    async def place_order(self, order: Order) -> str:
        """
        Platziere Order bei IBKR

        Args:
            order: Domain Order Object

        Returns:
            Broker Order ID
        """
        print(f"DEBUG: ibkr_adapter.place_order() START")
        print(f"DEBUG: Order received: {order}")

        try:
            if not self.is_connected():
                raise ConnectionError("Nicht mit IBKR verbunden")

            # Contract erstellen (async mit Qualifizierung)
            print(f"DEBUG: Creating contract for {order.symbol}")
            contract = await self._get_contract(order.symbol)
            print(f"DEBUG: Contract created: {contract} (conId: {contract.conId})")

            # IB Order erstellen
            print(f"DEBUG: Creating IB order")
            if order.order_type == OrderType.MARKET:
                ib_order = MarketOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity
                )

                ib_order.transmit = True  # NEU: Auch bei Market Orders!
                ib_order.tif = 'DAY'      # NEU: Time in Force
                ib_order.account = self.config.account  # WICHTIG für Web API/Gateway!

                print("DEBUG: Market order created")
            elif order.order_type == OrderType.LIMIT:
                ib_order = LimitOrder(
                    action='BUY' if order.side == OrderSide.BUY else 'SELL',
                    totalQuantity=order.quantity,
                    lmtPrice=float(order.limit_price)
                )
                ib_order.transmit = True
                ib_order.tif = 'DAY'
                ib_order.outsideRth = False  # NEU: Nur während Handelszeiten
                ib_order.account = self.config.account  # WICHTIG für Web API/Gateway!
                print(f"DEBUG: Limit order created with price {order.limit_price}, transmit={ib_order.transmit}")

            else:
                raise ValueError(f"Unsupported order type: {order.order_type}")

            # Order platzieren mit Timeout
            print("DEBUG: About to call ib.placeOrder()")
            try:
                # UNTERSCHIEDLICHE BEHANDLUNG für Limit vs Market
                if order.order_type == OrderType.LIMIT:
                    # Limit Orders brauchen synchrone Platzierung
                    trade = self.ib.placeOrder(contract, ib_order)
                    self.ib.sleep(0.001)  # Process IB events
                    print(f"DEBUG: Limit order placed synchronously")
                else:
                    # Market Orders funktionieren async
                    trade = await asyncio.wait_for(
                        asyncio.to_thread(self.ib.placeOrder, contract, ib_order),
                        timeout=5.0
                    )
                
                print(f"DEBUG: placeOrder returned: {trade}")
               
                # Bei Limit Orders warten
                if order.order_type == OrderType.LIMIT:
                    # Warte kurz auf Status-Update
                    for _ in range(10):  # Max 1 Sekunde
                        await asyncio.sleep(0.1)
                        # Hole aktuellen Status vom trade object
                        if hasattr(trade, 'orderStatus') and trade.orderStatus.status != 'PendingSubmit':
                            print(f"DEBUG: Order status changed to: {trade.orderStatus.status}")
                            break
                    print(f"DEBUG: Final order status: {trade.orderStatus.status if hasattr(trade, 'orderStatus') else 'unknown'}")
                    
            except asyncio.TimeoutError:
                print("ERROR: placeOrder timeout after 5 seconds!")
                raise ConnectionError("IBKR placeOrder timeout - TWS nicht erreichbar?")

            # Tracking
            broker_order_id = str(trade.order.orderId)
            print(f"DEBUG: Broker order ID: {broker_order_id}")

            self._orders[broker_order_id] = ib_order
            self._order_mapping[broker_order_id] = order

            # Update Domain Order
            order.broker_order_id = broker_order_id
            order.status = OrderStatus.PLACED
            order.submitted_at = datetime.now()

            print(f"DEBUG: Order placed successfully, returning {broker_order_id}")
            return broker_order_id

        except Exception as e:
            print(f"ERROR in place_order: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def cancel_order(self, order_id: str) -> bool:
        """Storniere Order"""
        if order_id not in self._orders:
            return False
        
        ib_order = self._orders[order_id]
        self.ib.cancelOrder(ib_order)
        
        # Update Domain Order
        if order_id in self._order_mapping:
            domain_order = self._order_mapping[order_id]
            domain_order.status = OrderStatus.CANCELLED
            domain_order.cancelled_at = datetime.now()
        
        return True
    
    def _on_order_status(self, trade):
        """Callback für Order-Status Updates"""
        broker_order_id = str(trade.order.orderId)
        
        if broker_order_id in self._order_mapping:
            domain_order = self._order_mapping[broker_order_id]
            
            # Map IB Status zu Domain Status
            ib_status = trade.orderStatus.status
            
            if ib_status == 'Filled':
                domain_order.status = OrderStatus.FILLED
                domain_order.filled_at = datetime.now()
                domain_order.filled_quantity = trade.orderStatus.filled
                domain_order.avg_fill_price = Decimal(str(trade.orderStatus.avgFillPrice))
            elif ib_status == 'Cancelled':
                domain_order.status = OrderStatus.CANCELLED
            elif ib_status == 'PendingSubmit':
                domain_order.status = OrderStatus.PENDING
            elif ib_status == 'Submitted':
                domain_order.status = OrderStatus.PLACED
    
    def _on_execution(self, trade, fill):
        """Callback für Trade-Ausführungen"""
        # Erstelle Trade-Objekt
        broker_order_id = str(trade.order.orderId)

        if broker_order_id in self._order_mapping:
            domain_order = self._order_mapping[broker_order_id]

            # Commission kommt separat via commissionReportEvent
            # Hier nur initialisieren falls Report schon da ist (selten)
            commission_value = Decimal("0")
            if fill.commissionReport and fill.commissionReport.commission:
                commission_value = Decimal(str(fill.commissionReport.commission))
                domain_order.commission = commission_value

            trade_obj = Trade(
                order_id=domain_order.id,
                broker_trade_id=str(fill.execution.execId),
                symbol=domain_order.symbol,
                side=domain_order.side,
                quantity=fill.execution.shares,
                price=Decimal(str(fill.execution.price)),
                commission=commission_value,
                executed_at=datetime.now()
            )

            # TODO: Trade speichern

    def _on_commission_report(self, trade, fill, report):
        """Callback für CommissionReports (kommt separat nach Execution)"""
        broker_order_id = str(trade.order.orderId)

        if broker_order_id in self._order_mapping:
            domain_order = self._order_mapping[broker_order_id]

            # Aktualisiere Commission im Domain Order
            if report and report.commission:
                commission_value = Decimal(str(report.commission))
                # Addiere zur bestehenden Commission (für Teil-Fills)
                if domain_order.commission:
                    domain_order.commission += commission_value
                else:
                    domain_order.commission = commission_value
                print(f"💰 Commission Report: Order {broker_order_id} - Commission: ${commission_value:.2f} (Total: ${domain_order.commission:.2f})")
    
    async def get_account_summary(self) -> Dict:
        """Hole Account-Zusammenfassung"""
        if not self.is_connected():
            raise ConnectionError("Nicht mit IBKR verbunden")
        
        account_values = self.ib.accountValues(self.config.account)
        positions = self.ib.positions(self.config.account)
        
        # Parse Account Values
        summary = {
            'account': self.config.account,
            'buying_power': 0,
            'net_liquidation': 0,
            'cash': 0,
            'positions': []
        }
        
        for av in account_values:
            if av.tag == 'BuyingPower':
                summary['buying_power'] = float(av.value)
            elif av.tag == 'NetLiquidation':
                summary['net_liquidation'] = float(av.value)
            elif av.tag == 'CashBalance':
                summary['cash'] = float(av.value)
        
        # Parse Positions
        for pos in positions:
            summary['positions'].append({
                'symbol': pos.contract.symbol,
                'quantity': pos.position,
                'avg_cost': pos.avgCost if hasattr(pos, 'avgCost') else 0,
                'market_value': getattr(pos, 'marketValue', 0),
                'unrealized_pnl': getattr(pos, 'unrealizedPNL', 0),
                'realized_pnl': getattr(pos, 'realizedPNL', 0)
            })
        
        return summary
