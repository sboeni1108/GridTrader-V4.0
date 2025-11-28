"""
Historical Data Manager

Zentraler Manager für historische Kursdaten.
Wird von Backtesting, KI-Controller und UI gemeinsam genutzt.

Features:
- Einmaliges Laden, mehrfache Nutzung
- Intelligentes Caching mit TTL
- Automatisches Zusammenführen von Datenquellen
- Thread-safe für Multi-Threading
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Callable
from threading import Lock, RLock
from dataclasses import dataclass, field
from pathlib import Path
import pickle
import hashlib


@dataclass
class DataCacheEntry:
    """Ein Eintrag im Daten-Cache"""
    symbol: str
    timeframe: str  # "1min", "5min", "1day", etc.
    data: pd.DataFrame
    loaded_at: datetime
    source: str  # "BACKTEST", "IBKR", "MERGED"
    start_date: datetime
    end_date: datetime
    row_count: int

    def is_expired(self, ttl_minutes: int = 60) -> bool:
        """Prüft ob der Cache abgelaufen ist"""
        age = (datetime.now() - self.loaded_at).total_seconds() / 60
        return age > ttl_minutes

    def covers_range(self, start: datetime, end: datetime) -> bool:
        """Prüft ob der Cache einen Zeitraum abdeckt"""
        return self.start_date <= start and self.end_date >= end

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'loaded_at': self.loaded_at.isoformat(),
            'source': self.source,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'row_count': self.row_count,
        }


class HistoricalDataManager:
    """
    Zentraler Manager für historische Kursdaten.

    Singleton-Pattern für globalen Zugriff.

    Verwendung:
        manager = HistoricalDataManager.get_instance()

        # Daten vom Backtesting registrieren
        manager.register_backtest_data("AAPL", df)

        # Daten abrufen (nutzt Cache wenn verfügbar)
        data = manager.get_data("AAPL", days=30)

        # Erweiterte Historie für KI laden
        data = manager.get_extended_history("AAPL", days=365)
    """

    _instance = None
    _lock = Lock()

    @classmethod
    def get_instance(cls) -> 'HistoricalDataManager':
        """Gibt die Singleton-Instanz zurück"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Setzt die Instanz zurück (für Tests)"""
        with cls._lock:
            cls._instance = None

    def __init__(self):
        # Cache: {cache_key: DataCacheEntry}
        self._cache: Dict[str, DataCacheEntry] = {}
        self._cache_lock = RLock()

        # IBKR Service Referenz (wird lazy geladen)
        self._ibkr_service = None

        # Callbacks für Daten-Updates
        self._on_data_updated: List[Callable[[str, pd.DataFrame], None]] = []

        # Konfiguration
        self.cache_ttl_minutes = 60  # Cache-Gültigkeit
        self.max_cache_entries = 50  # Max. Einträge im Cache
        self.persist_cache = True    # Cache auf Disk speichern?
        self.cache_dir = Path.home() / ".gridtrader" / "data_cache"

        # Cache-Verzeichnis erstellen
        if self.persist_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ==================== CACHE KEY ====================

    def _make_cache_key(self, symbol: str, timeframe: str = "1min") -> str:
        """Erstellt einen Cache-Schlüssel"""
        return f"{symbol.upper()}_{timeframe}"

    # ==================== DATA REGISTRATION ====================

    def register_backtest_data(
        self,
        symbol: str,
        data: pd.DataFrame,
        timeframe: str = "1min"
    ) -> bool:
        """
        Registriert Daten vom Backtesting-Widget.

        Diese Methode wird vom Backtesting-Widget aufgerufen,
        wenn neue Daten heruntergeladen wurden.

        Args:
            symbol: Aktien-Symbol
            data: DataFrame mit OHLCV-Daten
            timeframe: Timeframe der Daten

        Returns:
            True wenn erfolgreich registriert
        """
        if data is None or data.empty:
            return False

        cache_key = self._make_cache_key(symbol, timeframe)

        with self._cache_lock:
            # Bestehende Daten prüfen
            existing = self._cache.get(cache_key)

            if existing:
                # Daten zusammenführen (neuere Daten haben Priorität)
                merged_data = self._merge_data(existing.data, data)
                source = "MERGED"
            else:
                merged_data = data
                source = "BACKTEST"

            # Index zu datetime konvertieren wenn nötig
            if not isinstance(merged_data.index, pd.DatetimeIndex):
                merged_data.index = pd.to_datetime(merged_data.index)

            # Sortieren
            merged_data = merged_data.sort_index()

            # Timezone entfernen (alle Daten als timezone-naive behandeln)
            if merged_data.index.tz is not None:
                merged_data.index = merged_data.index.tz_localize(None)

            # Start/End Daten extrahieren (als timezone-naive)
            start_dt = merged_data.index.min()
            end_dt = merged_data.index.max()

            # Konvertiere zu Python datetime (timezone-naive)
            if hasattr(start_dt, 'to_pydatetime'):
                start_dt = start_dt.to_pydatetime()
                if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo is not None:
                    start_dt = start_dt.replace(tzinfo=None)
            if hasattr(end_dt, 'to_pydatetime'):
                end_dt = end_dt.to_pydatetime()
                if hasattr(end_dt, 'tzinfo') and end_dt.tzinfo is not None:
                    end_dt = end_dt.replace(tzinfo=None)

            # Cache-Eintrag erstellen
            entry = DataCacheEntry(
                symbol=symbol.upper(),
                timeframe=timeframe,
                data=merged_data,
                loaded_at=datetime.now(),
                source=source,
                start_date=start_dt,
                end_date=end_dt,
                row_count=len(merged_data),
            )

            self._cache[cache_key] = entry

            # Callbacks benachrichtigen
            self._notify_data_updated(symbol, merged_data)

            print(f"HistoricalDataManager: {symbol} registriert ({len(merged_data)} Zeilen, {source})")

            return True

    def _merge_data(self, old_data: pd.DataFrame, new_data: pd.DataFrame) -> pd.DataFrame:
        """Führt alte und neue Daten zusammen"""
        # Index-Typen angleichen
        if not isinstance(old_data.index, pd.DatetimeIndex):
            old_data.index = pd.to_datetime(old_data.index)
        if not isinstance(new_data.index, pd.DatetimeIndex):
            new_data.index = pd.to_datetime(new_data.index)

        # Kombinieren (neue Daten überschreiben alte bei Duplikaten)
        combined = pd.concat([old_data, new_data])
        combined = combined[~combined.index.duplicated(keep='last')]
        combined = combined.sort_index()

        return combined

    # ==================== DATA RETRIEVAL ====================

    def get_data(
        self,
        symbol: str,
        timeframe: str = "1min",
        days: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Holt historische Daten aus dem Cache.

        Args:
            symbol: Aktien-Symbol
            timeframe: Timeframe ("1min", "5min", "1day", etc.)
            days: Anzahl Tage (alternativ zu start_date/end_date)
            start_date: Start-Datum
            end_date: End-Datum

        Returns:
            DataFrame mit OHLCV-Daten oder None
        """
        cache_key = self._make_cache_key(symbol, timeframe)

        with self._cache_lock:
            entry = self._cache.get(cache_key)

            if entry is None:
                return None

            data = entry.data.copy()

            # Zeitraum filtern
            if days is not None:
                cutoff = datetime.now() - timedelta(days=days)
                data = data[data.index >= cutoff]
            elif start_date is not None or end_date is not None:
                if start_date:
                    data = data[data.index >= start_date]
                if end_date:
                    data = data[data.index <= end_date]

            return data

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Holt den letzten bekannten Preis aus dem Cache"""
        data = self.get_data(symbol, days=1)
        if data is not None and not data.empty:
            return float(data['close'].iloc[-1])
        return None

    def has_data(self, symbol: str, timeframe: str = "1min") -> bool:
        """Prüft ob Daten für ein Symbol vorhanden sind"""
        cache_key = self._make_cache_key(symbol, timeframe)
        with self._cache_lock:
            return cache_key in self._cache

    def get_cache_info(self, symbol: str, timeframe: str = "1min") -> Optional[dict]:
        """Gibt Cache-Informationen zurück"""
        cache_key = self._make_cache_key(symbol, timeframe)
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry:
                return entry.to_dict()
            return None

    def get_all_symbols(self) -> List[str]:
        """Gibt alle gecachten Symbole zurück"""
        with self._cache_lock:
            symbols = set()
            for key in self._cache.keys():
                symbol = key.split('_')[0]
                symbols.add(symbol)
            return list(symbols)

    # ==================== EXTENDED HISTORY ====================

    def get_extended_history(
        self,
        symbol: str,
        days: int = 365,
        timeframe: str = "1min",
        force_reload: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        Holt erweiterte Historie für KI-Pattern-Matching.

        Wenn die gecachten Daten nicht ausreichen, werden
        zusätzliche Daten vom IBKR Service geladen.

        Args:
            symbol: Aktien-Symbol
            days: Gewünschte Anzahl Tage
            timeframe: Timeframe
            force_reload: Erzwingt Neuladung

        Returns:
            DataFrame mit erweiterter Historie
        """
        cache_key = self._make_cache_key(symbol, timeframe)

        with self._cache_lock:
            entry = self._cache.get(cache_key)

            # Berechne benötigten Zeitraum
            required_start = datetime.now() - timedelta(days=days)

            # Prüfe ob Cache ausreicht
            if entry and not force_reload:
                if entry.start_date <= required_start:
                    # Cache hat genug Daten
                    return self.get_data(symbol, timeframe, days=days)
                else:
                    # Cache zu kurz - müssen nachladen
                    gap_days = (entry.start_date - required_start).days
                    print(f"HistoricalDataManager: Lade {gap_days} zusätzliche Tage für {symbol}")

        # Vom IBKR Service nachladen
        extended_data = self._load_from_ibkr(symbol, days, timeframe)

        if extended_data is not None and not extended_data.empty:
            # Mit bestehendem Cache mergen
            self.register_backtest_data(symbol, extended_data, timeframe)
            return self.get_data(symbol, timeframe, days=days)

        # Fallback: Bestehende Daten zurückgeben
        return self.get_data(symbol, timeframe)

    def _load_from_ibkr(
        self,
        symbol: str,
        days: int,
        timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Lädt Daten vom IBKR Service"""
        # Lazy Import und Service-Verbindung
        if self._ibkr_service is None:
            try:
                from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service
                self._ibkr_service = get_ibkr_service()
            except Exception as e:
                print(f"HistoricalDataManager: IBKR Service nicht verfügbar: {e}")
                return None

        if not self._ibkr_service.is_connected():
            print(f"HistoricalDataManager: IBKR nicht verbunden")
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
                # Für längere Zeiträume: Wochen oder Monate
                if days <= 52 * 7:
                    weeks = days // 7
                    duration = f"{weeks} W"
                else:
                    months = days // 30
                    duration = f"{months} M"
            else:
                duration = "1 Y"

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

            print(f"HistoricalDataManager: Lade {symbol} ({duration}, {bar_size}) von IBKR...")

            # IBKR Service aufrufen
            df = self._ibkr_service.get_historical_data(
                symbol=symbol,
                duration=duration,
                bar_size=bar_size,
                what_to_show="TRADES",
                use_rth=True,
                timeout=120.0  # Längerer Timeout für große Requests
            )

            if df is not None and not df.empty:
                print(f"HistoricalDataManager: {len(df)} Datenpunkte von IBKR erhalten")
                return df

        except Exception as e:
            print(f"HistoricalDataManager: IBKR Fehler für {symbol}: {e}")

        return None

    # ==================== REAL-TIME UPDATES ====================

    def append_candle(
        self,
        symbol: str,
        candle: Dict[str, Any],
        timeframe: str = "1min"
    ):
        """
        Fügt eine neue Kerze hinzu (für Live-Updates).

        Args:
            symbol: Aktien-Symbol
            candle: Dict mit timestamp, open, high, low, close, volume
            timeframe: Timeframe
        """
        cache_key = self._make_cache_key(symbol, timeframe)

        with self._cache_lock:
            entry = self._cache.get(cache_key)

            if entry is None:
                # Neuen DataFrame erstellen
                timestamp = pd.to_datetime(candle.get('timestamp', datetime.now()))
                new_row = pd.DataFrame({
                    'open': [candle.get('open', 0)],
                    'high': [candle.get('high', 0)],
                    'low': [candle.get('low', 0)],
                    'close': [candle.get('close', 0)],
                    'volume': [candle.get('volume', 0)],
                }, index=[timestamp])

                self.register_backtest_data(symbol, new_row, timeframe)
            else:
                # An bestehenden DataFrame anhängen
                timestamp = pd.to_datetime(candle.get('timestamp', datetime.now()))
                new_row = pd.DataFrame({
                    'open': [candle.get('open', 0)],
                    'high': [candle.get('high', 0)],
                    'low': [candle.get('low', 0)],
                    'close': [candle.get('close', 0)],
                    'volume': [candle.get('volume', 0)],
                }, index=[timestamp])

                entry.data = pd.concat([entry.data, new_row])
                entry.data = entry.data[~entry.data.index.duplicated(keep='last')]
                entry.end_date = entry.data.index.max().to_pydatetime()
                entry.row_count = len(entry.data)

                # Callbacks benachrichtigen
                self._notify_data_updated(symbol, entry.data)

    # ==================== CALLBACKS ====================

    def on_data_updated(self, callback: Callable[[str, pd.DataFrame], None]):
        """Registriert einen Callback für Daten-Updates"""
        self._on_data_updated.append(callback)

    def _notify_data_updated(self, symbol: str, data: pd.DataFrame):
        """Benachrichtigt alle registrierten Callbacks"""
        for callback in self._on_data_updated:
            try:
                callback(symbol, data)
            except Exception as e:
                print(f"HistoricalDataManager: Callback-Fehler: {e}")

    # ==================== CACHE MANAGEMENT ====================

    def clear_cache(self, symbol: Optional[str] = None):
        """Löscht den Cache (komplett oder für ein Symbol)"""
        with self._cache_lock:
            if symbol:
                keys_to_remove = [
                    k for k in self._cache.keys()
                    if k.startswith(symbol.upper())
                ]
                for key in keys_to_remove:
                    del self._cache[key]
            else:
                self._cache.clear()

    def get_cache_stats(self) -> dict:
        """Gibt Cache-Statistiken zurück"""
        with self._cache_lock:
            total_rows = sum(e.row_count for e in self._cache.values())
            return {
                'entries': len(self._cache),
                'symbols': len(self.get_all_symbols()),
                'total_rows': total_rows,
                'cache_keys': list(self._cache.keys()),
            }

    # ==================== PERSISTENCE ====================

    def save_cache_to_disk(self):
        """Speichert Cache auf Disk"""
        if not self.persist_cache:
            return

        with self._cache_lock:
            for key, entry in self._cache.items():
                file_path = self.cache_dir / f"{key}.pkl"
                try:
                    with open(file_path, 'wb') as f:
                        pickle.dump(entry, f)
                except Exception as e:
                    print(f"HistoricalDataManager: Fehler beim Speichern von {key}: {e}")

    def load_cache_from_disk(self):
        """Lädt Cache von Disk"""
        if not self.persist_cache or not self.cache_dir.exists():
            return

        with self._cache_lock:
            for file_path in self.cache_dir.glob("*.pkl"):
                try:
                    with open(file_path, 'rb') as f:
                        entry = pickle.load(f)
                        if isinstance(entry, DataCacheEntry):
                            # Nur laden wenn nicht zu alt
                            if not entry.is_expired(ttl_minutes=24 * 60):  # 24 Stunden
                                self._cache[f"{entry.symbol}_{entry.timeframe}"] = entry
                except Exception as e:
                    print(f"HistoricalDataManager: Fehler beim Laden von {file_path}: {e}")


# Convenience-Funktion für globalen Zugriff
def get_data_manager() -> HistoricalDataManager:
    """Gibt die globale DataManager-Instanz zurück"""
    return HistoricalDataManager.get_instance()
