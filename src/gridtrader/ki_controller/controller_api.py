"""
Controller API

Schnittstelle zwischen KI-Controller und Trading-Bot.
Definiert alle Operationen, die der Controller am Trading-Bot ausführen kann.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Callable
from decimal import Decimal

# IBKR Service Import
try:
    from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service, IBKRService
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    print("WARNUNG: IBKR Service nicht verfügbar")


class ControllerAPI(ABC):
    """
    Abstrakte API-Klasse für die Kommunikation mit dem Trading-Bot

    Der Trading-Bot muss diese Schnittstelle implementieren,
    damit der KI-Controller ihn steuern kann.
    """

    # ==================== MARKET DATA ====================

    @abstractmethod
    def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Holt aktuelle Marktdaten für ein Symbol

        Returns:
            Dict mit:
                - price: Aktueller Preis
                - bid: Bid-Preis
                - ask: Ask-Preis
                - volume: Tages-Volumen
                - high: Tageshoch
                - low: Tagestief
        """
        pass

    @abstractmethod
    def get_historical_data(
        self,
        symbol: str,
        days: int = 30,
        timeframe: str = "1min"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Holt historische Daten für Pattern-Matching

        Returns:
            Liste von Kerzen mit:
                - timestamp: Zeitstempel
                - open, high, low, close: OHLC
                - volume: Volumen
        """
        pass

    # ==================== LEVEL POOL ====================

    @abstractmethod
    def get_all_available_levels(self) -> Dict[str, Dict[str, Any]]:
        """
        Holt alle verfügbaren Levels aus allen Szenarien

        Returns:
            Dict[level_id, level_data] mit:
                - level_id: Eindeutige ID
                - scenario_name: Name des Quell-Szenarios
                - symbol: Symbol
                - side: "LONG" oder "SHORT"
                - level_num: Level-Nummer
                - entry_pct: Entry-Prozent vom Basis-Preis
                - exit_pct: Exit-Prozent vom Basis-Preis
                - shares: Anzahl Aktien
        """
        pass

    @abstractmethod
    def get_levels_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Holt alle verfügbaren Levels für ein bestimmtes Symbol"""
        pass

    # ==================== LEVEL MANAGEMENT ====================

    @abstractmethod
    def activate_level(
        self,
        level_data: Dict[str, Any],
        base_price: Optional[Decimal] = None
    ) -> bool:
        """
        Aktiviert ein Level

        Args:
            level_data: Level-Informationen (aus get_all_available_levels)
            base_price: Optionaler Basis-Preis (sonst aktueller Marktpreis)

        Returns:
            True wenn erfolgreich aktiviert
        """
        pass

    @abstractmethod
    def deactivate_level(self, level_id: str) -> bool:
        """
        Deaktiviert ein Level

        Args:
            level_id: ID des zu deaktivierenden Levels

        Returns:
            True wenn erfolgreich deaktiviert
        """
        pass

    @abstractmethod
    def get_active_levels(self) -> List[Dict[str, Any]]:
        """
        Holt alle aktuell aktiven Levels

        Returns:
            Liste von aktiven Levels mit Status-Informationen
        """
        pass

    # ==================== TRADE MANAGEMENT ====================

    @abstractmethod
    def stop_trade(self, level_id: str) -> bool:
        """
        Stoppt einen laufenden Trade (Entry-Order canceln)

        Args:
            level_id: ID des Levels dessen Trade gestoppt werden soll

        Returns:
            True wenn erfolgreich
        """
        pass

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET"
    ) -> bool:
        """
        Schließt eine offene Position

        Args:
            symbol: Symbol
            quantity: Anzahl zu schließender Aktien (positiv)
            order_type: "MARKET" oder "LIMIT"

        Returns:
            True wenn Order platziert
        """
        pass

    @abstractmethod
    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """
        Holt alle offenen Positionen

        Returns:
            Dict[symbol, position_data] mit:
                - quantity: Anzahl Aktien
                - avg_price: Durchschnittlicher Einstiegspreis
                - unrealized_pnl: Unrealisierter Gewinn/Verlust
                - side: "LONG" oder "SHORT"
        """
        pass

    # ==================== ORDER MANAGEMENT ====================

    @abstractmethod
    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """
        Holt alle offenen Orders

        Returns:
            Liste von Orders mit Status-Informationen
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancelt eine Order

        Args:
            order_id: ID der zu cancelnden Order

        Returns:
            True wenn erfolgreich
        """
        pass

    @abstractmethod
    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancelt alle Orders (optional für ein Symbol)

        Args:
            symbol: Optional - nur Orders für dieses Symbol

        Returns:
            Anzahl gecancelter Orders
        """
        pass

    # ==================== EMERGENCY ====================

    @abstractmethod
    def emergency_stop(self) -> bool:
        """
        Notfall-Stop: Cancelt alle Orders und schließt alle Positionen

        Returns:
            True wenn erfolgreich ausgeführt
        """
        pass

    # ==================== WAISEN-POSITIONEN (ORPHAN POSITIONS) ====================

    @abstractmethod
    def get_orphan_positions(self) -> List[Dict[str, Any]]:
        """
        Holt alle offenen Waisen-Positionen.

        Waisen-Positionen entstehen wenn ein aktives Level deaktiviert wird,
        aber die Position offen bleibt (für spätere Gewinnmitnahme).

        Returns:
            Liste von Waisen-Positionen mit:
                - id: Eindeutige ID
                - symbol: Aktien-Symbol
                - side: "LONG" oder "SHORT"
                - shares: Anzahl Aktien
                - entry_price: Einstiegspreis
                - current_price: Aktueller Preis (wenn bekannt)
                - unrealized_pnl: Unrealisierter P&L
                - profit_per_share: Gewinn pro Aktie in $
                - min_profit_cents: Mindestgewinn in Cent pro Aktie
        """
        pass

    @abstractmethod
    def close_orphan_position(self, orphan_id: str) -> bool:
        """
        Schließt eine Waisen-Position durch Market-Order.

        Args:
            orphan_id: ID der Waisen-Position

        Returns:
            True wenn Order platziert wurde
        """
        pass

    @abstractmethod
    def deactivate_level_keep_position(self, level_id: str, reason: str = "") -> bool:
        """
        Deaktiviert ein aktives Level, behält aber die Position als Waise.

        Args:
            level_id: ID des zu deaktivierenden Levels
            reason: Grund für die Deaktivierung

        Returns:
            True wenn erfolgreich
        """
        pass

    @abstractmethod
    def should_close_orphan(self, orphan: Dict[str, Any]) -> bool:
        """
        Prüft ob eine Waisen-Position geschlossen werden sollte.

        Kriterium: Gewinn pro Aktie >= min_profit_cents

        Args:
            orphan: Die Waisen-Position

        Returns:
            True wenn Position geschlossen werden sollte
        """
        pass

    # ==================== STATUS ====================

    @abstractmethod
    def is_connected(self) -> bool:
        """Prüft ob Verbindung zum Broker besteht"""
        pass

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Holt Account-Informationen

        Returns:
            Dict mit:
                - buying_power: Verfügbare Kaufkraft
                - cash: Cash-Bestand
                - total_value: Gesamtwert
                - day_pnl: Tages-P&L
        """
        pass


class TradingBotAPIAdapter(ControllerAPI):
    """
    Konkrete Implementierung der ControllerAPI

    Verbindet den KI-Controller mit dem TradingBotWidget.
    """

    def __init__(self, trading_bot_widget: 'TradingBotWidget'):
        """
        Args:
            trading_bot_widget: Referenz zum TradingBotWidget
        """
        self._bot = trading_bot_widget
        self._ibkr_service: Optional[IBKRService] = None
        self._connect_ibkr_service()

    def _connect_ibkr_service(self):
        """Verbindet automatisch mit dem IBKR Service"""
        if IBKR_AVAILABLE:
            try:
                self._ibkr_service = get_ibkr_service()
                print("TradingBotAPIAdapter: IBKR Service verbunden")
            except Exception as e:
                print(f"TradingBotAPIAdapter: IBKR Service Fehler: {e}")
                self._ibkr_service = None

    def set_ibkr_service(self, service):
        """Setzt die IBKR Service Referenz manuell"""
        self._ibkr_service = service

    # ==================== MARKET DATA ====================

    def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Holt aktuelle Marktdaten"""
        # Priorität 1: IBKR Service (Live Daten)
        if self._ibkr_service and self._ibkr_service.is_connected():
            try:
                cached_data = self._ibkr_service.get_cached_market_data(symbol)
                if cached_data:
                    return {
                        'price': cached_data.get('last', 0) or cached_data.get('close', 0),
                        'bid': cached_data.get('bid', 0),
                        'ask': cached_data.get('ask', 0),
                        'volume': cached_data.get('volume', 0),
                        'high': cached_data.get('high', 0),
                        'low': cached_data.get('low', 0),
                        'timestamp': cached_data.get('timestamp', ''),
                    }
            except Exception as e:
                print(f"IBKR Market Data Fehler: {e}")

        # Priorität 2: Trading-Bot Cache (Fallback)
        if hasattr(self._bot, '_last_market_prices'):
            price = self._bot._last_market_prices.get(symbol)
            if price:
                return {
                    'price': price,
                    'bid': price * 0.9999,  # Approximation
                    'ask': price * 1.0001,
                    'volume': 0,
                }

        return None

    def get_historical_data(
        self,
        symbol: str,
        days: int = 30,
        timeframe: str = "1min"
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Holt historische Daten für Pattern-Matching.

        Args:
            symbol: Aktien-Symbol
            days: Anzahl Tage (max 365)
            timeframe: Kerzengröße ("1min", "5min", "15min", "30min", "1hour", "1day")

        Returns:
            Liste von Kerzen mit timestamp, open, high, low, close, volume
        """
        if not self._ibkr_service or not self._ibkr_service.is_connected():
            print(f"Keine IBKR Verbindung für historische Daten ({symbol})")
            return None

        try:
            # Duration String erstellen
            if days <= 1:
                duration = "1 D"
            elif days <= 7:
                duration = f"{days} D"
            elif days <= 30:
                duration = f"{days} D"
            elif days <= 365:
                duration = f"{days} D"
            else:
                duration = "365 D"  # Max 1 Jahr

            # Bar Size konvertieren
            bar_size_map = {
                "1min": "1 min",
                "5min": "5 mins",
                "15min": "15 mins",
                "30min": "30 mins",
                "1hour": "1 hour",
                "1day": "1 day",
            }
            bar_size = bar_size_map.get(timeframe, "1 min")

            print(f"Hole historische Daten: {symbol}, {duration}, {bar_size}")

            # IBKR Service aufrufen (blocking)
            df = self._ibkr_service.get_historical_data(
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
                what_to_show="TRADES",
                use_rth=True,
                timeout=60.0
            )

            if df is None or df.empty:
                print(f"Keine historischen Daten für {symbol}")
                return None

            # DataFrame zu Liste von Dicts konvertieren
            result = []
            for idx, row in df.iterrows():
                result.append({
                    'timestamp': idx.isoformat() if hasattr(idx, 'isoformat') else str(idx),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume']),
                })

            print(f"Historische Daten erhalten: {len(result)} Kerzen für {symbol}")
            return result

        except Exception as e:
            print(f"Fehler beim Abruf historischer Daten für {symbol}: {e}")
            return None

    # ==================== LEVEL POOL ====================

    def get_all_available_levels(self) -> Dict[str, Dict[str, Any]]:
        """Holt alle verfügbaren Levels aus allen Szenarien"""
        all_levels = {}

        # Aus available_scenarios des Trading-Bots extrahieren
        if hasattr(self._bot, 'available_scenarios'):
            for scenario_name, scenario_data in self._bot.available_scenarios.items():
                levels = scenario_data.get('levels', [])
                symbol = scenario_data.get('symbol', 'UNKNOWN')

                for level in levels:
                    level_id = f"{scenario_name}_{level.get('level_num', 0)}_{level.get('side', 'LONG')}"

                    all_levels[level_id] = {
                        'level_id': level_id,
                        'scenario_name': scenario_name,
                        'symbol': symbol,
                        'side': level.get('side', 'LONG'),
                        'level_num': level.get('level_num', 0),
                        'entry_pct': level.get('entry_pct', 0),
                        'exit_pct': level.get('exit_pct', 0),
                        'shares': level.get('shares', 100),
                    }

        return all_levels

    def get_levels_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Holt alle verfügbaren Levels für ein Symbol"""
        all_levels = self.get_all_available_levels()
        return [
            level for level in all_levels.values()
            if level.get('symbol') == symbol
        ]

    # ==================== LEVEL MANAGEMENT ====================

    def activate_level(
        self,
        level_data: Dict[str, Any],
        base_price: Optional[Decimal] = None
    ) -> bool:
        """
        Aktiviert ein Level im Trading-Bot.

        Verwendet den aktuellen Marktpreis als Basis.
        """
        try:
            symbol = level_data.get('symbol', '')
            shares = level_data.get('shares', 100)
            side = level_data.get('side', 'LONG')

            # Basis-Preis ermitteln (aktueller Marktpreis)
            if base_price is None:
                market_data = self.get_market_data(symbol)
                if market_data and market_data.get('price'):
                    base_price = float(market_data['price'])
                else:
                    print(f"Kein Marktpreis für {symbol} verfügbar")
                    return False
            else:
                base_price = float(base_price)

            # Level-Daten im Format das _add_to_waiting_table erwartet
            level_for_bot = {
                'scenario_name': level_data.get('scenario_name', 'KI-Controller'),
                'level_num': level_data.get('level_num', 0),
                'entry_pct': level_data.get('entry_pct', 0),
                'exit_pct': level_data.get('exit_pct', 0),
                'type': side,  # Trading-Bot verwendet 'type' statt 'side'
            }

            # Config wie vom ActivationDialog erwartet
            config = {
                'symbol': symbol,
                'shares': shares,
                'use_market_price': False,  # Wir haben bereits einen Preis
                'fixed_price': base_price,
            }

            # Verwende die Trading-Bot Methode wenn verfügbar
            if hasattr(self._bot, '_add_to_waiting_table'):
                self._bot._add_to_waiting_table(level_for_bot, config, base_price)

                # Market Data Subscription sicherstellen
                if hasattr(self._bot, '_ibkr_service') and self._bot._ibkr_service:
                    if hasattr(self._bot._ibkr_service, 'subscribe_market_data'):
                        self._bot._ibkr_service.subscribe_market_data([symbol])

                # Tabelle sortieren
                if hasattr(self._bot, '_sort_waiting_table'):
                    self._bot._sort_waiting_table()

                print(f"Level aktiviert: {level_for_bot['scenario_name']} L{level_for_bot['level_num']} {side}")
                return True
            else:
                print("Trading-Bot hat keine _add_to_waiting_table Methode")
                return False

        except Exception as e:
            print(f"Fehler bei Level-Aktivierung: {e}")
            import traceback
            traceback.print_exc()

        return False

    def deactivate_level(self, level_id: str) -> bool:
        """Deaktiviert ein Level"""
        try:
            # Level in waiting_levels suchen und entfernen
            if hasattr(self._bot, 'waiting_levels'):
                for i, level in enumerate(self._bot.waiting_levels):
                    # Level-ID rekonstruieren
                    l_id = f"{level.get('scenario_name', '')}_{level.get('level_num', 0)}_{level.get('side', 'LONG')}"
                    if l_id == level_id:
                        self._bot.waiting_levels.pop(i)
                        if hasattr(self._bot, '_update_waiting_table'):
                            self._bot._update_waiting_table()
                        return True

            return False

        except Exception as e:
            print(f"Fehler bei Level-Deaktivierung: {e}")
            return False

    def get_active_levels(self) -> List[Dict[str, Any]]:
        """Holt alle aktuell aktiven Levels"""
        active = []

        if hasattr(self._bot, 'waiting_levels'):
            active.extend(self._bot.waiting_levels)

        if hasattr(self._bot, 'active_levels'):
            active.extend(self._bot.active_levels)

        return active

    # ==================== TRADE MANAGEMENT ====================

    def stop_trade(self, level_id: str) -> bool:
        """
        Stoppt einen laufenden Trade (cancelt pending Entry-Order).

        Args:
            level_id: ID des Levels dessen Trade gestoppt werden soll

        Returns:
            True wenn erfolgreich
        """
        try:
            # Level in waiting_levels suchen
            if hasattr(self._bot, 'waiting_levels'):
                for i, level in enumerate(self._bot.waiting_levels):
                    l_id = f"{level.get('scenario_name', '')}_{level.get('level_num', 0)}_{level.get('side', 'LONG')}"
                    if l_id == level_id:
                        # Wenn eine Order-ID existiert, canceln
                        order_id = level.get('broker_order_id')
                        if order_id and self._ibkr_service and self._ibkr_service.is_connected():
                            self._ibkr_service.cancel_order(order_id)
                            print(f"Order {order_id} für Level {level_id} gecancelt")

                        # Level aus waiting_levels entfernen
                        self._bot.waiting_levels.pop(i)
                        if hasattr(self._bot, '_update_waiting_table'):
                            self._bot._update_waiting_table()
                        return True

            # Level in active_levels suchen
            if hasattr(self._bot, 'active_levels'):
                for i, level in enumerate(self._bot.active_levels):
                    l_id = f"{level.get('scenario_name', '')}_{level.get('level_num', 0)}_{level.get('side', 'LONG')}"
                    if l_id == level_id:
                        # Exit-Order canceln falls vorhanden
                        exit_order_id = level.get('exit_order_id')
                        if exit_order_id and self._ibkr_service and self._ibkr_service.is_connected():
                            self._ibkr_service.cancel_order(exit_order_id)
                            print(f"Exit-Order {exit_order_id} für Level {level_id} gecancelt")
                        return True

            print(f"Level {level_id} nicht gefunden für stop_trade")
            return False

        except Exception as e:
            print(f"Fehler bei stop_trade für {level_id}: {e}")
            return False

    def close_position(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET"
    ) -> bool:
        """
        Schließt eine offene Position.

        Args:
            symbol: Symbol
            quantity: Anzahl Aktien (positiv)
            order_type: "MARKET" oder "LIMIT"

        Returns:
            True wenn Order platziert
        """
        if not self._ibkr_service or not self._ibkr_service.is_connected():
            print(f"Kann Position {symbol} nicht schließen - nicht verbunden")
            return False

        try:
            from gridtrader.domain.models.order import Order, OrderSide, OrderType as OT, OrderStatus

            # Bestimme Seite der Position
            positions = self.get_open_positions()
            if symbol not in positions:
                print(f"Keine offene Position für {symbol}")
                return False

            position = positions[symbol]
            pos_side = position.get('side', 'LONG')

            # Gegenorder erstellen
            if pos_side == 'LONG':
                order_side = OrderSide.SELL
            else:
                order_side = OrderSide.BUY

            close_order = Order(
                symbol=symbol,
                side=order_side,
                quantity=quantity,
                order_type=OT.MARKET if order_type == "MARKET" else OT.LIMIT,
            )

            # Order platzieren
            callback_id = self._ibkr_service.place_order(close_order)
            print(f"Close-Order für {symbol} platziert: {callback_id}")

            return True

        except Exception as e:
            print(f"Fehler beim Schließen der Position {symbol}: {e}")
            return False

    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Holt alle offenen Positionen"""
        positions = {}

        # Priorität 1: IBKR Account Positionen
        if self._ibkr_service and self._ibkr_service.is_connected():
            # TODO: Account Positionen via Service abrufen
            pass

        # Priorität 2: Aus active_levels des Trading-Bots
        if hasattr(self._bot, 'active_levels'):
            for level in self._bot.active_levels:
                symbol = level.get('symbol', '')
                if symbol not in positions:
                    positions[symbol] = {
                        'quantity': 0,
                        'avg_price': 0,
                        'unrealized_pnl': 0,
                        'side': level.get('side', 'LONG'),
                    }
                positions[symbol]['quantity'] += level.get('filled_shares', 0)

        return positions

    # ==================== ORDER MANAGEMENT ====================

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Holt alle offenen Orders"""
        if hasattr(self._bot, 'pending_orders'):
            return list(self._bot.pending_orders.values())
        return []

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancelt eine Order.

        Args:
            order_id: Broker Order-ID

        Returns:
            True wenn erfolgreich
        """
        if not order_id:
            return False

        if self._ibkr_service and self._ibkr_service.is_connected():
            try:
                self._ibkr_service.cancel_order(order_id)
                print(f"Order {order_id} Cancel-Request gesendet")
                return True
            except Exception as e:
                print(f"Fehler beim Canceln von Order {order_id}: {e}")

        return False

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancelt alle Orders (optional für ein Symbol).

        Args:
            symbol: Optional - nur Orders für dieses Symbol

        Returns:
            Anzahl gecancelter Orders
        """
        cancelled = 0

        # Pending Orders vom Trading-Bot
        pending = self.get_pending_orders()
        for order in pending:
            order_symbol = order.get('symbol', '')
            order_id = order.get('broker_order_id', order.get('order_id', ''))

            if symbol and order_symbol != symbol:
                continue

            if order_id and self.cancel_order(order_id):
                cancelled += 1

        print(f"{cancelled} Orders gecancelt" + (f" für {symbol}" if symbol else ""))
        return cancelled

    # ==================== EMERGENCY ====================

    def emergency_stop(self) -> bool:
        """Notfall-Stop"""
        try:
            # Alle wartenden Levels löschen
            if hasattr(self._bot, 'waiting_levels'):
                self._bot.waiting_levels.clear()

            # Alle offenen Orders canceln
            self.cancel_all_orders()

            # UI aktualisieren
            if hasattr(self._bot, '_update_waiting_table'):
                self._bot._update_waiting_table()
            if hasattr(self._bot, '_update_active_table'):
                self._bot._update_active_table()

            # Log
            if hasattr(self._bot, 'log_message'):
                self._bot.log_message("EMERGENCY STOP ausgeführt", "ERROR")

            return True

        except Exception as e:
            print(f"Fehler bei Emergency Stop: {e}")
            return False

    # ==================== STATUS ====================

    def is_connected(self) -> bool:
        """Prüft Broker-Verbindung"""
        if self._ibkr_service:
            return self._ibkr_service.is_connected()
        return False

    def get_account_info(self) -> Dict[str, Any]:
        """Holt Account-Informationen"""
        # TODO: Via IBKRService implementieren
        return {
            'buying_power': 0,
            'cash': 0,
            'total_value': 0,
            'day_pnl': 0,
        }

    # ==================== WAISEN-POSITIONEN (ORPHAN POSITIONS) ====================

    def get_orphan_positions(self) -> List[Dict[str, Any]]:
        """
        Holt alle offenen Waisen-Positionen.

        Returns:
            Liste von Waisen-Positionen
        """
        if hasattr(self._bot, 'get_orphan_positions'):
            return self._bot.get_orphan_positions()
        return []

    def close_orphan_position(self, orphan_id: str) -> bool:
        """
        Schließt eine Waisen-Position durch Market-Order.

        Args:
            orphan_id: ID der Waisen-Position

        Returns:
            True wenn Order platziert wurde
        """
        if hasattr(self._bot, 'close_orphan_position'):
            return self._bot.close_orphan_position(orphan_id)
        return False

    def deactivate_level_keep_position(self, level_id: str, reason: str = "") -> bool:
        """
        Deaktiviert ein aktives Level, behält aber die Position als Waise.

        Args:
            level_id: ID des zu deaktivierenden Levels
            reason: Grund für die Deaktivierung

        Returns:
            True wenn erfolgreich
        """
        if hasattr(self._bot, 'deactivate_level_keep_position'):
            return self._bot.deactivate_level_keep_position(level_id, reason)
        return False

    def should_close_orphan(self, orphan: Dict[str, Any]) -> bool:
        """
        Prüft ob eine Waisen-Position geschlossen werden sollte.

        Kriterium: Gewinn pro Aktie >= min_profit_cents

        Args:
            orphan: Die Waisen-Position

        Returns:
            True wenn Position geschlossen werden sollte
        """
        if hasattr(self._bot, 'should_close_orphan'):
            return self._bot.should_close_orphan(orphan)

        # Fallback-Logik
        profit_per_share = orphan.get('profit_per_share', 0)
        min_profit_cents = orphan.get('min_profit_cents', 3) / 100  # Cent -> Dollar
        return profit_per_share >= min_profit_cents

    def update_orphan_prices(self, market_prices: Dict[str, float]):
        """
        Aktualisiert die Preise der Waisen-Positionen.

        Args:
            market_prices: Dict {symbol: current_price}
        """
        if hasattr(self._bot, 'update_orphan_position_prices'):
            self._bot.update_orphan_position_prices(market_prices)
