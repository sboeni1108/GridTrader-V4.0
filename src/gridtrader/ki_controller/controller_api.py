"""
Controller API

Schnittstelle zwischen KI-Controller und Trading-Bot.
Definiert alle Operationen, die der Controller am Trading-Bot ausführen kann.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any, Callable
from decimal import Decimal


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
        self._ibkr_service = None

    def set_ibkr_service(self, service):
        """Setzt die IBKR Service Referenz"""
        self._ibkr_service = service

    # ==================== MARKET DATA ====================

    def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Holt aktuelle Marktdaten"""
        # Aus dem Cache des Trading-Bots
        if hasattr(self._bot, '_last_market_prices'):
            price = self._bot._last_market_prices.get(symbol)
            if price:
                return {
                    'price': price,
                    'bid': price * 0.9999,  # Approximation
                    'ask': price * 1.0001,
                    'volume': 0,
                }

        # Oder via IBKR Service
        if self._ibkr_service and self._ibkr_service.is_connected():
            try:
                # Market Data Request (wenn implementiert)
                pass
            except Exception:
                pass

        return None

    def get_historical_data(
        self,
        symbol: str,
        days: int = 30,
        timeframe: str = "1min"
    ) -> Optional[List[Dict[str, Any]]]:
        """Holt historische Daten"""
        # TODO: Implementierung für Phase 2 (Pattern Matching)
        # Kann aus lokaler Datenbank oder IBKR geholt werden
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
        """Aktiviert ein Level"""
        try:
            # Konvertiere level_data in das Format des Trading-Bots
            symbol = level_data.get('symbol', '')
            entry_pct = level_data.get('entry_pct', 0)
            exit_pct = level_data.get('exit_pct', 0)
            shares = level_data.get('shares', 100)
            side = level_data.get('side', 'LONG')

            # Basis-Preis ermitteln
            if base_price is None:
                market_data = self.get_market_data(symbol)
                if market_data:
                    base_price = Decimal(str(market_data['price']))
                else:
                    return False

            # Entry/Exit Preise berechnen
            entry_price = float(base_price) * (1 + entry_pct / 100)
            exit_price = float(base_price) * (1 + exit_pct / 100)

            # Level-Daten für Trading-Bot vorbereiten
            level_for_bot = {
                'symbol': symbol,
                'side': side,
                'level_num': level_data.get('level_num', 0),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'shares': shares,
                'scenario_name': level_data.get('scenario_name', 'KI-Controller'),
                'activated_by': 'KI-Controller',
            }

            # Zur Waiting-Liste des Trading-Bots hinzufügen
            if hasattr(self._bot, 'waiting_levels'):
                self._bot.waiting_levels.append(level_for_bot)

                # UI aktualisieren (wenn Methode existiert)
                if hasattr(self._bot, '_update_waiting_table'):
                    self._bot._update_waiting_table()

                return True

        except Exception as e:
            print(f"Fehler bei Level-Aktivierung: {e}")

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
        """Stoppt einen laufenden Trade"""
        # TODO: Implementierung für Order-Cancellation
        return False

    def close_position(
        self,
        symbol: str,
        quantity: int,
        order_type: str = "MARKET"
    ) -> bool:
        """Schließt eine offene Position"""
        if not self._ibkr_service or not self._ibkr_service.is_connected():
            return False

        try:
            # Market Order zum Schließen
            # TODO: Über IBKRService implementieren
            return False

        except Exception as e:
            print(f"Fehler beim Position-Close: {e}")
            return False

    def get_open_positions(self) -> Dict[str, Dict[str, Any]]:
        """Holt alle offenen Positionen"""
        positions = {}

        # Aus active_levels des Trading-Bots
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
        """Cancelt eine Order"""
        if self._ibkr_service and self._ibkr_service.is_connected():
            try:
                # TODO: Über IBKRService implementieren
                return False
            except Exception:
                pass
        return False

    def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancelt alle Orders"""
        # TODO: Implementierung
        return 0

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
