"""
Shared IBKR Connection Manager - Eine Verbindung für alle Module
Mit automatischer Verbindungsüberwachung und Wiederverbindung
"""
import asyncio
from typing import Optional
import pandas as pd
from PySide6.QtCore import QObject, Signal, QTimer

from gridtrader.infrastructure.brokers.ibkr.ibkr_adapter import (
    IBKRBrokerAdapter, IBKRConfig
)


class ConnectionMonitor(QObject):
    """
    Signale für Verbindungsstatus-Änderungen
    Verwendet QObject für Thread-sichere Signal/Slot-Kommunikation
    """
    # Signale für UI-Updates
    connection_lost = Signal()  # Verbindung verloren
    connection_restored = Signal()  # Verbindung wiederhergestellt
    reconnecting = Signal(int)  # Versuche Wiederverbindung (Versuch-Nr.)
    reconnect_failed = Signal(str)  # Wiederverbindung fehlgeschlagen (Fehlermeldung)
    status_changed = Signal(str)  # Allgemeiner Status-Text


class SharedIBKRConnection:
    """Singleton für geteilte IBKR Verbindung mit automatischer Überwachung"""

    _instance = None
    _adapter = None
    _lock = asyncio.Lock()
    _config = None  # Speichere aktuelle Konfiguration
    _monitor = None  # ConnectionMonitor für Signale
    _check_timer = None  # Timer für regelmässige Prüfung
    _was_connected = False  # War vorher verbunden?
    _reconnect_attempts = 0  # Anzahl Wiederverbindungsversuche
    _max_reconnect_attempts = 5  # Maximale Versuche
    _is_reconnecting = False  # Verhindert parallele Reconnects
    _intentional_disconnect = False  # Benutzer hat absichtlich getrennt

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Erstelle Monitor einmalig
            cls._instance._monitor = ConnectionMonitor()
            cls._instance._setup_monitoring_timer()
        return cls._instance

    def _setup_monitoring_timer(self):
        """Erstelle Timer für regelmässige Verbindungsprüfung (60 Sekunden)"""
        self._check_timer = QTimer()
        self._check_timer.timeout.connect(self._check_connection)
        # Timer startet erst nach erster erfolgreicher Verbindung

    def start_monitoring(self):
        """Starte Verbindungsüberwachung"""
        if self._check_timer and not self._check_timer.isActive():
            self._check_timer.start(30000)  # 30 Sekunden
            print("🔍 Verbindungsüberwachung gestartet (Intervall: 30 Sekunden)")

    def stop_monitoring(self):
        """Stoppe Verbindungsüberwachung"""
        if self._check_timer and self._check_timer.isActive():
            self._check_timer.stop()
            print("⏹️ Verbindungsüberwachung gestoppt")

    def get_monitor(self):
        """Hole den ConnectionMonitor für Signal-Verbindungen"""
        return self._monitor

    def _check_connection(self):
        """Prüfe Verbindungsstatus (wird alle 60 Sekunden aufgerufen)"""
        if self._intentional_disconnect:
            return  # Benutzer hat absichtlich getrennt

        is_connected = self._adapter is not None and self._adapter.is_connected()

        if self._was_connected and not is_connected:
            # Verbindung verloren!
            print("⚠️ IBKR Verbindung verloren!")
            self._was_connected = False
            self._monitor.connection_lost.emit()
            self._monitor.status_changed.emit("Verbindung verloren - Versuche Wiederverbindung...")

            # Starte Wiederverbindung
            self._start_reconnect()

        elif not self._was_connected and is_connected:
            # Verbindung wiederhergestellt
            print("✅ IBKR Verbindung wiederhergestellt")
            self._was_connected = True
            self._reconnect_attempts = 0
            self._is_reconnecting = False
            self._monitor.connection_restored.emit()
            self._monitor.status_changed.emit("Verbindung aktiv")

    def _start_reconnect(self):
        """Starte asynchrone Wiederverbindung"""
        if self._is_reconnecting:
            return  # Bereits am Reconnecten

        self._is_reconnecting = True
        self._reconnect_attempts = 0

        # Starte Reconnect in asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._reconnect_loop())
            else:
                loop.run_until_complete(self._reconnect_loop())
        except Exception as e:
            print(f"⚠️ Fehler beim Starten der Wiederverbindung: {e}")
            # Fallback: Versuche mit create_task
            asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Wiederverbindungsschleife mit exponentiellen Backoff"""
        while self._reconnect_attempts < self._max_reconnect_attempts:
            self._reconnect_attempts += 1

            print(f"🔄 Wiederverbindungsversuch {self._reconnect_attempts}/{self._max_reconnect_attempts}...")
            self._monitor.reconnecting.emit(self._reconnect_attempts)

            try:
                # Trenne alte Verbindung falls vorhanden
                if self._adapter:
                    try:
                        await self._adapter.disconnect()
                    except:
                        pass
                    self._adapter = None

                # Versuche neue Verbindung
                if self._config:
                    self._adapter = IBKRBrokerAdapter(self._config)
                    connected = await self._adapter.connect()

                    if connected:
                        print(f"✅ Wiederverbindung erfolgreich nach {self._reconnect_attempts} Versuch(en)")
                        self._was_connected = True
                        self._reconnect_attempts = 0
                        self._is_reconnecting = False

                        # Update den globalen shared adapter
                        from gridtrader.infrastructure.brokers.ibkr import set_shared_adapter
                        set_shared_adapter(self._adapter)

                        self._monitor.connection_restored.emit()
                        self._monitor.status_changed.emit("Verbindung wiederhergestellt")
                        return
                else:
                    print("⚠️ Keine Konfiguration für Wiederverbindung verfügbar")
                    break

            except Exception as e:
                print(f"❌ Wiederverbindung fehlgeschlagen: {e}")

            # Warte vor nächstem Versuch (exponentieller Backoff: 5s, 10s, 20s, 40s, 80s)
            wait_time = 5 * (2 ** (self._reconnect_attempts - 1))
            print(f"⏳ Warte {wait_time} Sekunden vor nächstem Versuch...")
            await asyncio.sleep(wait_time)

        # Alle Versuche fehlgeschlagen
        self._is_reconnecting = False
        error_msg = f"Wiederverbindung nach {self._max_reconnect_attempts} Versuchen fehlgeschlagen"
        print(f"❌ {error_msg}")
        self._monitor.reconnect_failed.emit(error_msg)
        self._monitor.status_changed.emit(error_msg)

    def mark_intentional_disconnect(self):
        """Markiere dass der Benutzer absichtlich trennt"""
        self._intentional_disconnect = True
        self._was_connected = False
        self.stop_monitoring()

    async def clear_adapter(self):
        """Trenne und lösche den Adapter komplett (für manuelles Disconnect)"""
        self._intentional_disconnect = True
        self._was_connected = False
        self.stop_monitoring()

        if self._adapter:
            try:
                await self._adapter.disconnect()
                print("🔌 IBKR Adapter getrennt")
            except Exception as e:
                print(f"⚠️ Fehler beim Trennen des Adapters: {e}")
            finally:
                self._adapter = None

        # Lösche auch den globalen shared adapter
        from gridtrader.infrastructure.brokers.ibkr import clear_shared_adapter
        clear_shared_adapter()

    def is_monitoring_active(self):
        """Prüfe ob Monitoring aktiv ist"""
        return self._check_timer and self._check_timer.isActive()

    def configure(self, settings):
        """
        Konfiguriere die Verbindungseinstellungen

        Args:
            settings: IBKRConnectionSettings Objekt mit:
                - api_type: "TWS" oder "GATEWAY"
                - mode: "PAPER" oder "LIVE"
                - host: IP-Adresse
                - port: Port-Nummer
                - client_id: Client ID
                - account: Optional Account ID
        """
        # Berechne Port basierend auf Einstellungen
        if hasattr(settings, 'get_port'):
            port = settings.get_port()
        else:
            port = settings.port

        # Bestimme paper_trading basierend auf mode
        paper_trading = getattr(settings, 'mode', 'PAPER') == 'PAPER'

        self._config = IBKRConfig(
            host=getattr(settings, 'host', '127.0.0.1'),
            port=port,
            client_id=getattr(settings, 'client_id', 1),
            account=getattr(settings, 'account', '') or '',
            paper_trading=paper_trading
        )

        mode_str = "Paper Trading" if paper_trading else "LIVE Trading"
        print(f"🔧 IBKR Konfiguration: {mode_str} auf Port {port}")

        # Falls eine bestehende Verbindung existiert, trennen
        if self._adapter and self._adapter.is_connected():
            print("🔄 Trenne bestehende Verbindung für neue Konfiguration...")
            asyncio.create_task(self._disconnect_existing())

    async def _disconnect_existing(self):
        """Trenne bestehende Verbindung"""
        try:
            if self._adapter:
                await self._adapter.disconnect()
                self._adapter = None
        except Exception as e:
            print(f"⚠️ Fehler beim Trennen: {e}")
            self._adapter = None

    async def get_adapter(self):
        """Hole die geteilte Adapter-Instanz"""
        async with self._lock:
            if self._adapter is None or not self._adapter.is_connected():
                print("🔄 Erstelle neue IBKR Verbindung...")

                # Verwende gespeicherte Konfiguration oder Default (Paper Trading)
                if self._config is None:
                    print("⚠️ Keine Konfiguration gesetzt - verwende Default (Paper Trading)")
                    config = IBKRConfig(
                        host="127.0.0.1",
                        port=7497,  # Paper Trading
                        client_id=1,
                        paper_trading=True
                    )
                else:
                    config = self._config
                    mode_str = "Paper Trading" if config.paper_trading else "LIVE Trading"
                    print(f"📡 Verbinde mit {mode_str} auf Port {config.port}...")

                self._adapter = IBKRBrokerAdapter(config)
                connected = await self._adapter.connect()

                if not connected:
                    raise ConnectionError(f"Keine IBKR Verbindung auf Port {config.port} möglich")

                mode_str = "Paper Trading" if config.paper_trading else "LIVE Trading"
                print(f"✅ IBKR Verbindung hergestellt ({mode_str}, Port {config.port})")

                # Update den globalen shared adapter
                from gridtrader.infrastructure.brokers.ibkr import set_shared_adapter
                set_shared_adapter(self._adapter)

                # Starte Verbindungsüberwachung
                self._was_connected = True
                self._intentional_disconnect = False
                self.start_monitoring()
            else:
                print("♻️ Verwende existierende IBKR Verbindung")

            return self._adapter
    
    async def get_historical_data(self, symbol, duration="30 D", bar_size="1 min"):
        """Hole historische Daten"""
        adapter = await self.get_adapter()
        return await adapter.get_historical_data(
            symbol=symbol,
            duration=duration,
            bar_size=bar_size
        )


# Global Instance
shared_connection = SharedIBKRConnection()
