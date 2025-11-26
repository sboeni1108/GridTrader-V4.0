"""
GridTrader V2.0 - Advanced Backtest Widget
Multi-Szenario Testing mit LONG/SHORT Vergleich
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QLineEdit, QPushButton,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QTextEdit, QProgressBar,
    QTabWidget, QCheckBox, QSplitter, QDateEdit,
    QMessageBox, QListWidget, QFrame
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QColor
from gridtrader.ui.styles import (
    TITLE_STYLE, GROUPBOX_STYLE, TABLE_STYLE, TAB_STYLE, LOG_STYLE,
    STATUSBAR_STYLE, PROGRESS_STYLE, PRIMARY_BUTTON_STYLE,
    apply_table_style, apply_groupbox_style, apply_title_style, apply_log_style,
    SUCCESS_COLOR, ERROR_COLOR
)
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import pickle
from pathlib import Path
# NOTE: IBKRService wird dynamisch importiert in DataFetcher.fetch_historical_data()


class BacktestWorker(QThread):
    """Worker Thread für Backtest-Berechnungen"""
    progress_update = Signal(str)
    results_ready = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, scenarios, historical_data, symbol, commission_per_share=0.005):
        super().__init__()
        self.scenarios = scenarios
        self.historical_data = historical_data
        self.symbol = symbol
        self.commission_per_share = commission_per_share  # Übernimmt Wert vom Setup Tab
        
    def run(self):
        """Führe Backtest für alle Szenarien aus"""
        try:
            results = {}
            total = len(self.scenarios)
            
            for i, (name, config) in enumerate(self.scenarios.items()):
                self.progress_update.emit(f"Teste Szenario {name} ({i+1}/{total})...")
                
                # Simuliere Backtest
                result = self._run_backtest(config)
                results[name] = result
                
            self.results_ready.emit(results)
            
        except Exception as e:
            self.error_occurred.emit(f"Fehler im Backtest: {str(e)}")
    
    def _run_backtest(self, config):
        """Einzelner Backtest-Durchlauf mit Grid-Trading Simulation"""

        if self.historical_data is None or self.historical_data.empty:
            return self._generate_placeholder_result(config)

        # Filter zu RTH only (9:30 - 16:00 EST)
        df = self._filter_rth_only(self.historical_data)

        if df.empty:
            return self._generate_placeholder_result(config)

        # Simuliere Grid Trading mit Level Recycling
        result = self._simulate_grid_trading(df, config)

        return result

    def _filter_rth_only(self, df):
        """Filtere Daten zu Regular Trading Hours (9:30-16:00 EST)"""
        # Stelle sicher dass Index datetime ist
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Filtere zu RTH (9:30 - 16:00 EST)
        # Hinweis: IBKR liefert bereits RTH wenn use_rth=True, aber double-check
        rth_data = df.between_time('09:30', '16:00')

        return rth_data

    def _get_daily_start_points(self, day_data, hours_offset=0):
        """
        Gibt 1-2 Startpunkte für den Tag zurück

        Args:
            day_data: DataFrame mit Daten eines Tages
            hours_offset: Stunden nach Marktöffnung für 2. Start (0 = nur ein Start)

        Returns:
            list of (timestamp, price) tuples
        """
        start_points = []

        # Startpunkt 1: Marktöffnung (erste Kerze >= 9:30)
        market_open_data = day_data.between_time('09:30', '09:35')
        if not market_open_data.empty:
            market_open = market_open_data.index[0]
            start_points.append((market_open, float(day_data.loc[market_open, 'close'])))

        # Startpunkt 2: X Stunden später (optional)
        if hours_offset > 0 and start_points:
            target_time = pd.Timestamp(start_points[0][0]) + pd.Timedelta(hours=hours_offset)
            # Finde nächste Kerze nach target_time
            later_data = day_data[day_data.index >= target_time]
            if not later_data.empty:
                second_start = later_data.index[0]
                start_points.append((second_start, float(day_data.loc[second_start, 'close'])))

        return start_points

    def _create_grid_levels(self, base_price, step_pct, exit_pct, max_levels, side):
        """Erstelle Grid-Levels mit KONSTANTEN Abständen vom Basis-Preis"""
        levels = []

        for i in range(max_levels):
            level_number = i + 1

            if side == 'LONG':
                # Jedes Level ist step% unter dem vorherigen
                # Level 1: base * (1 - 0.5%), Level 2: base * (1 - 1.0%), etc.
                entry_price = base_price * (1 - (step_pct * level_number / 100))
                exit_price = entry_price * (1 + exit_pct / 100)
            else:  # SHORT
                # Level 1: base * (1 + 0.5%), Level 2: base * (1 + 1.0%), etc.
                entry_price = base_price * (1 + (step_pct * level_number / 100))
                exit_price = entry_price * (1 - exit_pct / 100)

            levels.append({
                'level': level_number,
                'entry': entry_price,
                'exit': exit_price,
                'position': 0,
                'entry_fills': []  # Liste der tatsächlichen Fill-Preise
            })

        return levels

    def _simulate_day_trading(self, day_data, levels, shares_per_level, side):
        """
        Simuliere Trading für einen Tag

        Returns:
            (trades, remaining_positions)
        """
        trades = []
        closed_trades = []

        for timestamp, row in day_data.iterrows():
            current_price = float(row['close'])

            # Check alle Levels
            for level in levels:
                if side == 'LONG':
                    # Entry: Kaufe wenn Preis <= Entry Price
                    if level['position'] == 0 and current_price <= level['entry']:
                        level['position'] = shares_per_level
                        level['entry_fills'].append(current_price)
                        trades.append({
                            'time': timestamp,
                            'type': 'BUY',
                            'price': current_price,
                            'shares': shares_per_level
                        })

                    # Exit: Verkaufe wenn Preis >= Exit Price
                    elif level['position'] > 0 and current_price >= level['exit']:
                        avg_entry = sum(level['entry_fills']) / len(level['entry_fills'])
                        profit = (current_price - avg_entry) * level['position']

                        closed_trades.append({
                            'profit': profit,
                            'winner': profit > 0
                        })

                        trades.append({
                            'time': timestamp,
                            'type': 'SELL',
                            'price': current_price,
                            'shares': level['position']
                        })

                        # Level Recycling: Reaktivieren
                        level['position'] = 0
                        level['entry_fills'] = []

                else:  # SHORT
                    # Entry: Verkaufe wenn Preis >= Entry Price
                    if level['position'] == 0 and current_price >= level['entry']:
                        level['position'] = -shares_per_level
                        level['entry_fills'].append(current_price)
                        trades.append({
                            'time': timestamp,
                            'type': 'SELL',
                            'price': current_price,
                            'shares': shares_per_level
                        })

                    # Exit: Kaufe zurück wenn Preis <= Exit Price
                    elif level['position'] < 0 and current_price <= level['exit']:
                        avg_entry = sum(level['entry_fills']) / len(level['entry_fills'])
                        profit = (avg_entry - current_price) * abs(level['position'])

                        closed_trades.append({
                            'profit': profit,
                            'winner': profit > 0
                        })

                        trades.append({
                            'time': timestamp,
                            'type': 'BUY',
                            'price': current_price,
                            'shares': abs(level['position'])
                        })

                        # Level Recycling
                        level['position'] = 0
                        level['entry_fills'] = []

        # Sammle verbleibende Positionen am Tagesende
        remaining_positions = []
        for level in levels:
            if level['position'] != 0:
                avg_entry = sum(level['entry_fills']) / len(level['entry_fills']) if level['entry_fills'] else 0
                remaining_positions.append({
                    'shares': abs(level['position']),
                    'avg_price': avg_entry,
                    'side': side
                })

        # Letzter Preis des Tages (für mark-to-market Bewertung)
        last_price = float(day_data.iloc[-1]['close']) if len(day_data) > 0 else 0

        return {
            'trades': trades,
            'closed_trades': closed_trades,
            'remaining': remaining_positions,
            'last_price': last_price  # NEU: Für unrealized P&L Berechnung
        }

    def _calculate_final_metrics(self, all_daily_results, final_close_price, side, config):
        """Aggregiere finale Metriken über alle Tage"""

        # Sammle alle Trades und closed_trades
        all_trades = []
        all_closed_trades = []

        for daily in all_daily_results:
            all_trades.extend(daily['trades'])
            all_closed_trades.extend(daily['closed_trades'])

        # DEBUG: Trade-Anzahl
        print(f"\n🔍 DEBUG Trade-Statistiken:")
        print(f"   Total Trades: {len(all_trades)} (alle BUY+SELL Transaktionen)")
        print(f"   Closed Levels: {len(all_closed_trades)} (komplette Entry+Exit Paare)")

        # Realized P&L
        total_profit_usd = sum(t['profit'] for t in all_closed_trades) if all_closed_trades else 0

        # Win Rate
        winning_trades = sum(1 for t in all_closed_trades if t['winner'])
        total_closed = len(all_closed_trades)
        win_rate = (winning_trades / total_closed * 100) if total_closed > 0 else 0

        # Sammle alle verbleibenden Positionen (von allen Tagen)
        total_remaining_shares = 0
        total_entry_value = 0

        for daily in all_daily_results:
            for pos in daily['remaining']:
                total_remaining_shares += pos['shares']
                total_entry_value += pos['shares'] * pos['avg_price']

        # Gewichteter Durchschnitt für Restbestände
        avg_remaining_price = (total_entry_value / total_remaining_shares) if total_remaining_shares > 0 else 0

        # DEBUG: Restaktien
        print(f"   Finale Akkumulation: {total_remaining_shares} Rest-Aktien gesamt")
        print(f"   Ø Entry-Preis Rest: ${avg_remaining_price:.2f}")

        # Unrealized P&L mit letztem Close
        if side == 'LONG':
            unrealized_pnl = (final_close_price - avg_remaining_price) * total_remaining_shares if total_remaining_shares > 0 else 0
        else:  # SHORT
            unrealized_pnl = (avg_remaining_price - final_close_price) * total_remaining_shares if total_remaining_shares > 0 else 0

        # Kommission
        total_shares_traded = sum(t['shares'] for t in all_trades)
        commission_total = total_shares_traded * self.commission_per_share

        # DEBUG: Kommission
        print(f"   Kommission: {total_shares_traded} shares × ${self.commission_per_share:.4f}/share = ${commission_total:.2f}")

        # Netto P&L
        net_pnl = total_profit_usd - commission_total + unrealized_pnl

        # P&L % - Berechne Initial Capital dynamisch basierend auf maximaler Position
        shares_per_level = config.get('shares', 100)
        max_levels = config.get('levels', 5)
        # Verwende ersten Tagespreis als Basis (repräsentativ für Zeitraum)
        first_day_price = all_daily_results[0]['start_price'] if all_daily_results else final_close_price
        initial_capital = shares_per_level * max_levels * first_day_price

        # DEBUG: Capital Berechnung
        print(f"   Initial Capital: {shares_per_level} shares × {max_levels} levels × ${first_day_price:.2f} = ${initial_capital:.2f}")

        total_return = (net_pnl / initial_capital * 100) if initial_capital > 0 else 0

        # NEUER CODE: Berechne kumulativen Max Drawdown mit Mark-to-Market
        # Erstelle Equity Curve (realized + unrealized P&L)
        equity_curve = []
        running_realized_pnl = 0

        # Gehe durch alle Tage chronologisch
        for daily in all_daily_results:
            # Tages P&L (realized)
            daily_realized = sum(t['profit'] for t in daily['closed_trades']) if daily['closed_trades'] else 0
            running_realized_pnl += daily_realized

            # Unrealized P&L am Tagesende (mark-to-market)
            daily_unrealized = 0
            last_price = daily.get('last_price', 0)

            for pos in daily['remaining']:
                if side == 'LONG':
                    daily_unrealized += (last_price - pos['avg_price']) * pos['shares']
                else:  # SHORT
                    daily_unrealized += (pos['avg_price'] - last_price) * pos['shares']

            # Gesamte Equity an diesem Tag = Realized + Unrealized
            total_equity = running_realized_pnl + daily_unrealized
            equity_curve.append(total_equity)

        # Berechne Max Drawdown aus Equity Curve
        if equity_curve:
            # Peak startet bei 0 (Ausgangspunkt = Initial Capital ohne P&L)
            peak = 0
            max_drawdown_amount = 0

            for value in equity_curve:
                # Update Peak (höchster erreichter P&L)
                if value > peak:
                    peak = value

                # Berechne Drawdown vom Peak (immer positiv oder 0)
                drawdown = peak - value

                # Update Max Drawdown (größter Rückgang vom Peak)
                if drawdown > max_drawdown_amount:
                    max_drawdown_amount = drawdown

            # Max Drawdown in Prozent (negativ für Anzeige)
            max_drawdown_pct = -(max_drawdown_amount / initial_capital * 100) if initial_capital > 0 else 0
        else:
            max_drawdown_amount = 0
            max_drawdown_pct = 0

        # DEBUG: Drawdown mit Equity Curve (Mark-to-Market)
        if equity_curve:
            print(f"   Equity Curve (MTM): {[f'${v:.2f}' for v in equity_curve[:5]]}{'...' if len(equity_curve) > 5 else ''}")
            print(f"   Peak erreicht: ${peak:.2f}")
            print(f"   Lowest point: ${min(equity_curve):.2f}")
        print(f"   Max Drawdown: ${max_drawdown_amount:.2f} ({max_drawdown_pct:.2f}%)")

        # DEBUG: P&L Zusammenfassung
        print(f"   Realized P&L: ${total_profit_usd:.2f}")
        print(f"   Unrealized P&L: ${unrealized_pnl:.2f}")
        print(f"   Net P&L: ${net_pnl:.2f} ({total_return:.2f}%)")

        return {
            'symbol': self.symbol,
            'initial_capital': initial_capital,  # NEU: Initial Capital ausgeben
            'pnl_percent': total_return,
            'pnl_usd': total_profit_usd,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown_pct,  # Bereits negativ berechnet
            'trades': len(all_trades),
            'remaining_shares': total_remaining_shares,
            'avg_entry_price': avg_remaining_price,
            'last_price': final_close_price,
            'unrealized_pnl': unrealized_pnl,
            'net_pnl': net_pnl,
            'commission': commission_total
        }

    def _simulate_grid_trading(self, df, config):
        """Simuliere Grid Trading mit täglichem Reset"""

        # Parameter extrahieren
        shares_per_level = config.get('shares', 100)
        step_percent = config.get('step', 0.5)
        exit_percent = config.get('exit', 0.7)
        max_levels = config.get('levels', 5)
        side = config['type']

        # Sammle Resultate
        all_daily_results = []

        # Verarbeite jeden Tag separat
        daily_groups = df.groupby(df.index.date)

        for date, day_data in daily_groups:
            # Hole Startpunkte für diesen Tag (nur Marktöffnung, kein zweiter Start)
            start_points = self._get_daily_start_points(day_data, hours_offset=0)

            if not start_points:
                continue  # Überspringe Tage ohne Daten

            # Verwende ersten (und einzigen) Startpunkt
            start_time, start_price = start_points[0]

            # Initialisiere Grid für diesen Tag
            levels = self._create_grid_levels(
                start_price, step_percent, exit_percent, max_levels, side
            )

            # Simuliere Trading für den gesamten Tag
            day_subset = day_data[day_data.index >= start_time]
            day_result = self._simulate_day_trading(
                day_subset, levels, shares_per_level, side
            )

            # Speichere Tagesresultate
            day_result['date'] = date
            day_result['start_time'] = start_time
            day_result['start_price'] = start_price
            all_daily_results.append(day_result)

            # Debug Output - Tägliche Statistiken mit Equity Tracking
            daily_pnl = sum(t['profit'] for t in day_result['closed_trades']) if day_result['closed_trades'] else 0
            remaining_count = sum(pos['shares'] for pos in day_result['remaining'])
            daily_trades = len(day_result['trades'])
            closed_levels = len(day_result['closed_trades'])

            # Berechne kumulatives P&L über alle bisherigen Tage
            cumulative_pnl = sum(sum(t['profit'] for t in dr['closed_trades'])
                                 for dr in all_daily_results if dr['closed_trades'])

            # Console Debug mit kumulativem P&L
            print(f"📅 Tag {date}: P&L: ${daily_pnl:.2f}, Kumulativ: ${cumulative_pnl:.2f}, "
                  f"{daily_trades} Trades, {closed_levels} Levels, {remaining_count} Rest-Aktien")

            # GUI Progress Update
            self.progress_update.emit(
                f"📅 {date}: {daily_trades} Trades, {closed_levels} Levels, "
                f"P&L: ${daily_pnl:.2f}, Rest: {remaining_count} Aktien"
            )

        # Aggregiere finale Metriken
        if not all_daily_results:
            return self._generate_placeholder_result(config)

        final_close = float(df.iloc[-1]['close'])
        return self._calculate_final_metrics(all_daily_results, final_close, side, config)

    def _generate_placeholder_result(self, config):
        """Fallback wenn keine Daten verfügbar"""
        return {
            'symbol': self.symbol,
            'initial_capital': 0.0,  # NEU: Initial Capital
            'pnl_percent': 0.0,
            'pnl_usd': 0.0,
            'win_rate': 0.0,
            'max_drawdown': 0.0,
            'trades': 0,
            'remaining_shares': 0,
            'avg_entry_price': 0.0,
            'last_price': 0.0,
            'unrealized_pnl': 0.0,
            'net_pnl': 0.0,
            'commission': 0.0
        }


class DataFetcher(QThread):
    """Worker Thread für Daten-Abruf - verwendet IBKRService"""
    progress_update = Signal(str)
    data_ready = Signal(object)
    error_occurred = Signal(str)
    ask_use_cache = Signal(str, float)  # (cache_name, age_hours) -> User wird gefragt

    def __init__(self, symbol, timeframe_days, candle_minutes):
        super().__init__()
        self.symbol = symbol
        self.timeframe_days = timeframe_days
        self.candle_minutes = candle_minutes
        self.use_cache_response = False  # Wird vom Main-Thread gesetzt

    def run(self):
        """Hole historische Daten über IBKRService"""
        try:
            data = self.fetch_historical_data()

            if data is not None:
                self.data_ready.emit(data)
            else:
                self.error_occurred.emit("Keine Daten erhalten")

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.error_occurred.emit(f"❌ Fehler beim Datenabruf: {str(e)}")
            print(f"DEBUG Error Details:\n{error_details}")

    def fetch_historical_data(self):
        """Hole historische Daten von IBKR oder Cache - verwendet IBKRService"""
        import time

        # Cache-Pfad konstruieren
        cache_dir = Path("cache")
        cache_dir.mkdir(exist_ok=True)

        # Cache-Dateiname-Pattern
        cache_pattern = f"{self.symbol}_{self.timeframe_days}d_{self.candle_minutes}min_*.pkl"
        existing_caches = sorted(cache_dir.glob(cache_pattern))

        # Prüfe ob frischer Cache existiert
        if existing_caches:
            newest_cache = existing_caches[-1]
            cache_age_hours = (datetime.now() - datetime.fromtimestamp(newest_cache.stat().st_mtime)).total_seconds() / 3600

            if cache_age_hours < 24:
                # Cache ist frisch genug
                self.progress_update.emit(f"📦 Cache gefunden: {newest_cache.name} ({cache_age_hours:.1f}h alt)")

                # Signal senden - Main-Thread fragt User
                self.ask_use_cache.emit(newest_cache.name, cache_age_hours)

                # Kurz warten damit Main-Thread Zeit hat zu antworten
                time.sleep(0.5)

                if self.use_cache_response:
                    # Cache verwenden
                    self.progress_update.emit(f"📦 Lade aus Cache...")
                    with open(newest_cache, 'rb') as f:
                        data = pickle.load(f)
                    self.progress_update.emit(f"✅ {len(data)} Datenpunkte aus Cache geladen!")
                    return data

        # Kein Cache oder User will neu laden - hole von IBKR
        self.progress_update.emit(f"📊 Hole historische Daten für {self.symbol}...")

        # Hole IBKRService (verwendet bestehende Verbindung vom Live Trading Tab)
        try:
            from gridtrader.infrastructure.brokers.ibkr.ibkr_service import get_ibkr_service
            service = get_ibkr_service()
        except ImportError:
            self.error_occurred.emit("❌ IBKRService nicht verfügbar!")
            return self._try_fallback_cache(existing_caches)

        # Check ob Service verbunden ist
        if not service.is_connected():
            # IBKR nicht verbunden - nutze neuesten Cache falls vorhanden
            if existing_caches:
                self.progress_update.emit("⚠️ IBKR nicht verbunden - nutze letzten Cache")
                with open(existing_caches[-1], 'rb') as f:
                    data = pickle.load(f)
                self.progress_update.emit(f"✅ {len(data)} Datenpunkte aus Fallback-Cache")
                return data
            self.error_occurred.emit("❌ Keine IBKR Verbindung! Bitte erst im Live Trading Tab verbinden.")
            return None

        self.progress_update.emit(f"♻️ Nutze existierende IBKR Verbindung...")

        # Hole Daten von IBKRService
        # IBKR Format: "1 min" (ohne 's') aber "2 mins", "3 mins", etc. (mit 's')
        bar_size = "1 min" if self.candle_minutes == 1 else f"{self.candle_minutes} mins"

        self.progress_update.emit(f"🔄 Anfrage: {self.symbol}, {self.timeframe_days}D, {bar_size}...")

        df = service.get_historical_data(
            symbol=self.symbol,
            duration=f"{self.timeframe_days} D",
            bar_size=bar_size,
            what_to_show="TRADES",
            use_rth=True,
            timeout=60.0
        )

        if df is None:
            # IBKR-Abruf fehlgeschlagen - nutze neuesten Cache falls vorhanden
            if existing_caches:
                self.progress_update.emit("⚠️ IBKR Abruf fehlgeschlagen - nutze letzten Cache")
                with open(existing_caches[-1], 'rb') as f:
                    data = pickle.load(f)
                self.progress_update.emit(f"✅ {len(data)} Datenpunkte aus Fallback-Cache")
                return data
            self.error_occurred.emit(f"⚠️ get_historical_data gab None zurück für {self.symbol}")
            return None

        if df.empty:
            self.error_occurred.emit(f"⚠️ Leeres DataFrame für {self.symbol} erhalten")
            return None

        # Speichere in Cache
        cache_file = cache_dir / f"{self.symbol}_{self.timeframe_days}d_{self.candle_minutes}min_{datetime.now():%Y%m%d}.pkl"
        with open(cache_file, 'wb') as f:
            pickle.dump(df, f)
        self.progress_update.emit(f"💾 Cache gespeichert: {cache_file.name}")

        # Cleanup alte Cache-Dateien
        self._cleanup_old_cache(cache_dir, days=7)

        self.progress_update.emit(f"✅ {len(df)} Datenpunkte erfolgreich geladen!")
        return df

    def _try_fallback_cache(self, existing_caches):
        """Versuche Cache zu laden wenn IBKR nicht verfügbar"""
        if existing_caches:
            self.progress_update.emit("⚠️ IBKR nicht verfügbar - nutze letzten Cache")
            with open(existing_caches[-1], 'rb') as f:
                data = pickle.load(f)
            self.progress_update.emit(f"✅ {len(data)} Datenpunkte aus Fallback-Cache")
            return data
        return None

    def _cleanup_old_cache(self, cache_dir: Path, days: int = 7):
        """Löscht alte Cache-Dateien"""
        cutoff = datetime.now() - timedelta(days=days)
        for cache_file in cache_dir.glob("*.pkl"):
            if datetime.fromtimestamp(cache_file.stat().st_mtime) < cutoff:
                cache_file.unlink()
                self.progress_update.emit(f"🗑️ Alter Cache gelöscht: {cache_file.name}")
    
    def get_id(self) -> str:
        """Eindeutige ID für diesen Worker"""
        return f"{self.symbol}_{self.timeframe_days}d_{self.candle_minutes}m"


class ScenarioBuilder(QWidget):
    """Widget zum Erstellen von Backtest-Szenarien"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        """UI initialisieren"""
        layout = QVBoxLayout()
        
        # Basis-Parameter
        base_group = QGroupBox("Basis-Parameter")
        base_layout = QGridLayout()
        
        base_layout.addWidget(QLabel("Symbol:"), 0, 0)
        self.symbol_edit = QLineEdit("AAPL")
        base_layout.addWidget(self.symbol_edit, 0, 1)
        
        base_layout.addWidget(QLabel("Zeitraum (Tage):"), 1, 0)
        self.timeframe_spin = QSpinBox()
        self.timeframe_spin.setRange(1, 365)
        self.timeframe_spin.setValue(30)
        base_layout.addWidget(self.timeframe_spin, 1, 1)
        
        base_group.setLayout(base_layout)
        layout.addWidget(base_group)
        
        # Szenario-Parameter
        scenario_group = QGroupBox("Szenario-Parameter")
        scenario_layout = QGridLayout()
        
        # Grid-Parameter
        scenario_layout.addWidget(QLabel("Aktien pro Level:"), 0, 0)
        self.shares_spin = QSpinBox()
        self.shares_spin.setRange(1, 1000)
        self.shares_spin.setValue(100)
        scenario_layout.addWidget(self.shares_spin, 0, 1)
        
        scenario_layout.addWidget(QLabel("Step %:"), 1, 0)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 10.0)
        self.step_spin.setValue(0.5)
        self.step_spin.setSuffix("%")
        scenario_layout.addWidget(self.step_spin, 1, 1)
        
        scenario_group.setLayout(scenario_layout)
        layout.addWidget(scenario_group)
        
        self.setLayout(layout)


class AdvancedBacktestWidget(QWidget):
    """Haupt-Widget für Advanced Backtest"""

    # Signal für Export zum Trading-Bot (Liste von Szenarien)
    export_to_trading_bot = Signal(list)  # Liste von (scenario_name, config, result) Tupeln

    def __init__(self):
        super().__init__()
        print("🔴 ADVANCED_BACKTEST_WIDGET INITIALISIERT!")
        self.historical_data = None
        self.scenarios = {}
        self.scenario_origins = {}  # NEU: Speichert Ursprung pro Szenario ("User" oder "KI")
        self.backtest_results = {}
        self.last_results = None
        self.last_symbol = None
        self.last_timeframe = None
        self.last_candle_minutes = None
        self.voranalyse_stats = None  # NEU: Speichert Voranalyse-Statistiken
        self.init_ui()
        
    def init_ui(self):
        """UI initialisieren"""
        layout = QVBoxLayout()

        # Header
        header = QLabel("Advanced Backtest - Multi-Szenario Analyse")
        apply_title_style(header)
        layout.addWidget(header)

        # Tabs für verschiedene Bereiche
        tabs = QTabWidget()
        tabs.setStyleSheet(TAB_STYLE)

        # Tab 1: Daten & Setup
        setup_tab = self.create_setup_tab()
        tabs.addTab(setup_tab, "Setup")

        # Tab 2: Voranalyse & Szenarien
        scenarios_tab = self.create_scenarios_tab()
        tabs.addTab(scenarios_tab, "Voranalyse & Szenarien")

        # Tab 3: Ergebnisse
        results_tab = self.create_results_tab()
        tabs.addTab(results_tab, "Ergebnisse")

        layout.addWidget(tabs)

        # Status Bar
        self.status_label = QLabel("Bereit")
        self.status_label.setStyleSheet(STATUSBAR_STYLE)
        layout.addWidget(self.status_label)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(PROGRESS_STYLE)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)
        
    def create_setup_tab(self):
        """Setup Tab erstellen"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Daten-Abruf Sektion
        data_group = QGroupBox("Historische Daten")
        apply_groupbox_style(data_group)
        data_layout = QGridLayout()
        
        data_layout.addWidget(QLabel("Symbol:"), 0, 0)
        self.symbol_edit = QLineEdit("AAPL")
        data_layout.addWidget(self.symbol_edit, 0, 1)
        
        data_layout.addWidget(QLabel("Zeitraum (Tage):"), 1, 0)
        self.timeframe_spin = QSpinBox()
        self.timeframe_spin.setRange(1, 365)
        self.timeframe_spin.setValue(30)
        data_layout.addWidget(self.timeframe_spin, 1, 1)
        
        data_layout.addWidget(QLabel("Kerzen-Minuten:"), 2, 0)
        self.candle_spin = QSpinBox()
        self.candle_spin.setRange(1, 60)
        self.candle_spin.setValue(5)
        data_layout.addWidget(self.candle_spin, 2, 1)
        
        self.fetch_btn = QPushButton("📊 Daten Laden")
        self.fetch_btn.clicked.connect(self.fetch_data)
        data_layout.addWidget(self.fetch_btn, 3, 0, 1, 2)

        self.data_status_label = QLabel("Keine Daten geladen")
        data_layout.addWidget(self.data_status_label, 4, 0, 1, 2)

        # Cache-Status
        self.cache_status_label = QLabel("📦 Cache: Prüfe...")
        self.cache_status_label.setStyleSheet("color: #666; font-size: 11px;")
        data_layout.addWidget(self.cache_status_label, 5, 0, 1, 2)

        # Cache-Buttons in einer Zeile
        cache_btn_layout = QHBoxLayout()

        # Cache laden Button
        self.load_cache_btn = QPushButton("📦 Cache Laden")
        self.load_cache_btn.clicked.connect(self.load_from_cache)
        cache_btn_layout.addWidget(self.load_cache_btn)

        # Cache leeren Button
        self.clear_cache_btn = QPushButton("🗑️ Cache leeren")
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        cache_btn_layout.addWidget(self.clear_cache_btn)

        data_layout.addLayout(cache_btn_layout, 6, 0, 1, 2)

        data_group.setLayout(data_layout)
        layout.addWidget(data_group)

        # Initial Cache-Status aktualisieren
        self.update_cache_status()
        
        # Basis-Einstellungen
        base_group = QGroupBox("Basis-Einstellungen")
        apply_groupbox_style(base_group)
        base_layout = QGridLayout()
        
        base_layout.addWidget(QLabel("Initial-Kapital:"), 0, 0)
        self.capital_spin = QSpinBox()
        self.capital_spin.setRange(1000, 1000000)
        self.capital_spin.setValue(10000)
        self.capital_spin.setSuffix(" $")
        base_layout.addWidget(self.capital_spin, 0, 1)
        
        base_layout.addWidget(QLabel("Kommission/Aktie:"), 1, 0)
        self.commission_spin = QDoubleSpinBox()
        self.commission_spin.setRange(0.001, 0.01)
        self.commission_spin.setValue(0.005)
        self.commission_spin.setSingleStep(0.001)
        self.commission_spin.setDecimals(3)
        self.commission_spin.setPrefix("$")
        self.commission_spin.setSuffix(" /Aktie")
        base_layout.addWidget(self.commission_spin, 1, 1)
        
        base_group.setLayout(base_layout)
        layout.addWidget(base_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
        
    def create_scenarios_tab(self):
        """Voranalyse & Szenarien Tab erstellen mit Splitter-Layout"""
        widget = QWidget()
        main_layout = QHBoxLayout()

        # Splitter für Links (Voranalyse) und Rechts (Szenarien)
        splitter = QSplitter(Qt.Horizontal)

        # ============================================
        # LINKE SEITE: Voranalyse Panel (ca. 1/3)
        # ============================================
        voranalyse_widget = QWidget()
        voranalyse_layout = QVBoxLayout()

        # Voranalyse Header
        voranalyse_title = QLabel("📊 Voranalyse")
        apply_title_style(voranalyse_title)
        voranalyse_layout.addWidget(voranalyse_title)

        # Parameter-Gruppe
        param_group = QGroupBox("Parameter")
        apply_groupbox_style(param_group)
        param_layout = QGridLayout()

        # Minimum Gewinn in Cents
        param_layout.addWidget(QLabel("Min. Gewinn (Cents):"), 0, 0)
        self.min_profit_cents_spin = QSpinBox()
        self.min_profit_cents_spin.setRange(1, 100)
        self.min_profit_cents_spin.setValue(3)
        self.min_profit_cents_spin.setSuffix(" ¢")
        param_layout.addWidget(self.min_profit_cents_spin, 0, 1)

        # Anzahl Aktien
        param_layout.addWidget(QLabel("Anzahl Aktien:"), 1, 0)
        self.ki_shares_spin = QSpinBox()
        self.ki_shares_spin.setRange(50, 1000)
        self.ki_shares_spin.setSingleStep(50)
        self.ki_shares_spin.setValue(200)
        param_layout.addWidget(self.ki_shares_spin, 1, 1)

        # Minimum Levels
        param_layout.addWidget(QLabel("Min. Levels:"), 2, 0)
        self.ki_min_levels_spin = QSpinBox()
        self.ki_min_levels_spin.setRange(2, 20)
        self.ki_min_levels_spin.setValue(5)
        param_layout.addWidget(self.ki_min_levels_spin, 2, 1)

        # Maximum Levels
        param_layout.addWidget(QLabel("Max. Levels:"), 3, 0)
        self.ki_max_levels_spin = QSpinBox()
        self.ki_max_levels_spin.setRange(2, 20)
        self.ki_max_levels_spin.setValue(10)
        param_layout.addWidget(self.ki_max_levels_spin, 3, 1)

        # Max Szenarien
        param_layout.addWidget(QLabel("Max. Szenarien:"), 4, 0)
        self.ki_max_scenarios_spin = QSpinBox()
        self.ki_max_scenarios_spin.setRange(1, 20)
        self.ki_max_scenarios_spin.setValue(6)
        param_layout.addWidget(self.ki_max_scenarios_spin, 4, 1)

        param_group.setLayout(param_layout)
        voranalyse_layout.addWidget(param_group)

        # Voranalyse starten Button
        self.voranalyse_btn = QPushButton("🔬 Voranalyse starten")
        self.voranalyse_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.voranalyse_btn.clicked.connect(self.run_voranalyse)
        voranalyse_layout.addWidget(self.voranalyse_btn)

        # Statistik-Tabelle
        stats_group = QGroupBox("Kerzen-Statistiken")
        apply_groupbox_style(stats_group)
        stats_layout = QVBoxLayout()

        self.voranalyse_table = QTableWidget()
        self.voranalyse_table.setColumnCount(2)
        self.voranalyse_table.setHorizontalHeaderLabels(["Metrik", "Wert"])
        self.voranalyse_table.horizontalHeader().setStretchLastSection(True)
        self.voranalyse_table.setAlternatingRowColors(True)
        apply_table_style(self.voranalyse_table)
        stats_layout.addWidget(self.voranalyse_table)

        # Analyse-Umfang Label
        self.analyse_info_label = QLabel("Keine Analyse durchgeführt")
        self.analyse_info_label.setStyleSheet("color: #666; font-style: italic;")
        stats_layout.addWidget(self.analyse_info_label)

        stats_group.setLayout(stats_layout)
        voranalyse_layout.addWidget(stats_group)

        voranalyse_layout.addStretch()
        voranalyse_widget.setLayout(voranalyse_layout)

        # ============================================
        # RECHTE SEITE: Szenarien (ca. 2/3)
        # ============================================
        szenarien_widget = QWidget()
        szenarien_layout = QVBoxLayout()

        # Szenario-Generator
        gen_group = QGroupBox("Szenario-Generator (Manuell)")
        apply_groupbox_style(gen_group)
        gen_layout = QGridLayout()

        # Grid-Parameter Ranges
        gen_layout.addWidget(QLabel("Aktien/Level:"), 0, 0)
        self.shares_from_spin = QSpinBox()
        self.shares_from_spin.setRange(50, 500)
        self.shares_from_spin.setSingleStep(50)
        self.shares_from_spin.setValue(100)
        gen_layout.addWidget(self.shares_from_spin, 0, 1)

        gen_layout.addWidget(QLabel("bis"), 0, 2)
        self.shares_to_spin = QSpinBox()
        self.shares_to_spin.setRange(50, 500)
        self.shares_to_spin.setSingleStep(50)
        self.shares_to_spin.setValue(300)
        gen_layout.addWidget(self.shares_to_spin, 0, 3)

        gen_layout.addWidget(QLabel("Step %:"), 1, 0)
        self.step_from_spin = QDoubleSpinBox()
        self.step_from_spin.setRange(0.1, 1.2)
        self.step_from_spin.setSingleStep(0.1)
        self.step_from_spin.setValue(0.3)
        self.step_from_spin.setSuffix("%")
        gen_layout.addWidget(self.step_from_spin, 1, 1)

        gen_layout.addWidget(QLabel("bis"), 1, 2)
        self.step_to_spin = QDoubleSpinBox()
        self.step_to_spin.setRange(0.1, 1.2)
        self.step_to_spin.setSingleStep(0.1)
        self.step_to_spin.setValue(0.7)
        self.step_to_spin.setSuffix("%")
        gen_layout.addWidget(self.step_to_spin, 1, 3)

        gen_layout.addWidget(QLabel("Exit %:"), 2, 0)
        self.exit_from_spin = QDoubleSpinBox()
        self.exit_from_spin.setRange(0.1, 1.2)
        self.exit_from_spin.setSingleStep(0.1)
        self.exit_from_spin.setValue(0.5)
        self.exit_from_spin.setSuffix("%")
        gen_layout.addWidget(self.exit_from_spin, 2, 1)

        gen_layout.addWidget(QLabel("bis"), 2, 2)
        self.exit_to_spin = QDoubleSpinBox()
        self.exit_to_spin.setRange(0.1, 1.2)
        self.exit_to_spin.setSingleStep(0.1)
        self.exit_to_spin.setValue(1.0)
        self.exit_to_spin.setSuffix("%")
        gen_layout.addWidget(self.exit_to_spin, 2, 3)

        gen_layout.addWidget(QLabel("Max Levels:"), 3, 0)
        self.levels_from_spin = QSpinBox()
        self.levels_from_spin.setRange(2, 15)
        self.levels_from_spin.setValue(5)
        gen_layout.addWidget(self.levels_from_spin, 3, 1)

        gen_layout.addWidget(QLabel("bis"), 3, 2)
        self.levels_to_spin = QSpinBox()
        self.levels_to_spin.setRange(2, 15)
        self.levels_to_spin.setValue(10)
        gen_layout.addWidget(self.levels_to_spin, 3, 3)

        # Optionen
        self.long_check = QCheckBox("LONG Szenarien")
        self.long_check.setChecked(True)
        gen_layout.addWidget(self.long_check, 4, 0, 1, 2)

        self.short_check = QCheckBox("SHORT Szenarien")
        self.short_check.setChecked(True)
        gen_layout.addWidget(self.short_check, 4, 2, 1, 2)

        # Buttons für Szenario-Management
        buttons_layout = QHBoxLayout()

        self.generate_btn = QPushButton("📊 Szenarien generieren")
        self.generate_btn.clicked.connect(self.generate_scenarios)
        buttons_layout.addWidget(self.generate_btn)

        self.add_scenarios_btn = QPushButton("➕ Weitere hinzufügen")
        self.add_scenarios_btn.clicked.connect(self.add_scenarios)
        buttons_layout.addWidget(self.add_scenarios_btn)

        gen_layout.addLayout(buttons_layout, 5, 0, 1, 4)

        gen_group.setLayout(gen_layout)
        szenarien_layout.addWidget(gen_group)

        # Szenarien-Liste mit Ursprung-Spalte
        list_group = QGroupBox("Generierte Szenarien")
        apply_groupbox_style(list_group)
        list_layout = QVBoxLayout()

        self.scenarios_table = QTableWidget()
        self.scenarios_table.setColumnCount(7)  # +1 für Ursprung
        self.scenarios_table.setHorizontalHeaderLabels([
            "Name", "Typ", "Aktien/Level", "Step %", "Exit %", "Max Levels", "Ursprung"
        ])
        # Multi-Selection aktivieren
        self.scenarios_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.scenarios_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        apply_table_style(self.scenarios_table)
        list_layout.addWidget(self.scenarios_table)

        # Footer mit Count und Delete-Button
        footer_layout = QHBoxLayout()
        self.scenario_count_label = QLabel("0 Szenarien")
        footer_layout.addWidget(self.scenario_count_label)

        footer_layout.addStretch()

        self.delete_selected_btn = QPushButton("🗑️ Ausgewählte löschen")
        self.delete_selected_btn.clicked.connect(self.delete_selected_scenarios)
        footer_layout.addWidget(self.delete_selected_btn)

        self.clear_scenarios_btn = QPushButton("🗑️ Alle löschen")
        self.clear_scenarios_btn.clicked.connect(self.clear_scenarios)
        footer_layout.addWidget(self.clear_scenarios_btn)

        list_layout.addLayout(footer_layout)

        list_group.setLayout(list_layout)
        szenarien_layout.addWidget(list_group)

        szenarien_widget.setLayout(szenarien_layout)

        # Widgets zum Splitter hinzufügen
        splitter.addWidget(voranalyse_widget)
        splitter.addWidget(szenarien_widget)

        # Splitter-Verhältnis: 1/3 links, 2/3 rechts
        splitter.setSizes([300, 600])

        main_layout.addWidget(splitter)
        widget.setLayout(main_layout)
        return widget
        
    def create_results_tab(self):
        """Ergebnis Tab erstellen"""
        widget = QWidget()
        layout = QVBoxLayout()

        # Control Buttons
        control_layout = QHBoxLayout()

        self.run_btn = QPushButton("▶️ Backtest Starten")
        self.run_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self.run_btn.clicked.connect(self.run_backtest)
        control_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹️ Stoppen")
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)

        self.export_btn = QPushButton("📊 Excel Export")
        self.export_btn.clicked.connect(self.export_to_excel)
        control_layout.addWidget(self.export_btn)

        self.export_trading_bot_btn = QPushButton("🤖 Export to Trading-Bot")
        self.export_trading_bot_btn.setToolTip("Ausgewähltes Szenario zum Trading-Bot exportieren")
        self.export_trading_bot_btn.clicked.connect(self.export_selected_to_trading_bot)
        control_layout.addWidget(self.export_trading_bot_btn)

        control_layout.addStretch()
        layout.addLayout(control_layout)

        # Ergebnis-Tabelle mit 16 Spalten (inkl. Initial Capital)
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(16)
        self.results_table.setHorizontalHeaderLabels([
            "Rang", "Szenario", "Symbol", "Typ", "Initial Capital $", "Net P&L %", "Realized P&L $",
            "Win Rate %", "Max DD %", "Trades (BUY+SELL)", "Rest Aktien",
            "Ø Kurs Rest", "Letzter Kurs", "Unrealized P&L $", "Net P&L $", "Kommission $"
        ])
        apply_table_style(self.results_table)
        # Mehrfachauswahl aktivieren
        self.results_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QTableWidget.SelectionMode.MultiSelection)
        # Spaltenbreiten anpassen
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(False)
        for i in range(16):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.results_table)

        # Statistik-Bereich
        stats_group = QGroupBox("Statistiken")
        apply_groupbox_style(stats_group)
        stats_layout = QGridLayout()

        self.best_long_label = QLabel("Bestes LONG: -")
        stats_layout.addWidget(self.best_long_label, 0, 0)

        self.best_short_label = QLabel("Bestes SHORT: -")
        stats_layout.addWidget(self.best_short_label, 0, 1)

        self.avg_return_label = QLabel("Ø Return: -")
        stats_layout.addWidget(self.avg_return_label, 1, 0)

        self.total_scenarios_label = QLabel("Getestet: 0")
        stats_layout.addWidget(self.total_scenarios_label, 1, 1)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        # Log-Bereich
        self.log_text = QTextEdit()
        apply_log_style(self.log_text)
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        
        widget.setLayout(layout)
        return widget
        
    def fetch_data(self):
        """Historische Daten abrufen"""
        symbol = self.symbol_edit.text()
        timeframe = self.timeframe_spin.value()
        candles = self.candle_spin.value()

        if not symbol:
            self.update_status("❌ Bitte Symbol eingeben")
            return

        # Stop existierenden Thread falls vorhanden
        if hasattr(self, 'data_fetcher') and self.data_fetcher is not None:
            if self.data_fetcher.isRunning():
                self.data_fetcher.wait(1000)  # Warte max 1 Sekunde

        # Starte Worker Thread
        self.data_fetcher = DataFetcher(symbol, timeframe, candles)
        self.data_fetcher.progress_update.connect(self.update_status)
        self.data_fetcher.data_ready.connect(self.on_data_received)
        self.data_fetcher.error_occurred.connect(self.on_error)
        self.data_fetcher.finished.connect(self.on_fetch_finished)
        self.data_fetcher.ask_use_cache.connect(self.on_ask_use_cache)  # Cache-Frage Handler

        self.fetch_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.data_fetcher.start()
        
    def on_data_received(self, data):
        """Callback wenn Daten empfangen"""
        self.historical_data = data
        self.data_status_label.setText(f"✅ {len(data)} Datenpunkte geladen")
        self.update_status(f"Daten für {self.symbol_edit.text()} erfolgreich geladen")
        self.log(f"Daten geladen: {len(data)} Kerzen")

    def on_fetch_finished(self):
        """Callback wenn DataFetcher Thread beendet"""
        self.fetch_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.update_cache_status()  # Cache-Status aktualisieren

    def on_ask_use_cache(self, cache_name: str, age_hours: float):
        """Handler für Cache-Frage - läuft im Main-Thread"""
        reply = QMessageBox.question(
            self,
            "Cache-Daten verfügbar",
            f"Cache-Datei gefunden:\n\n{cache_name}\nAlter: {age_hours:.1f} Stunden\n\nCache verwenden?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        # Setze Response im Worker
        if hasattr(self, 'data_fetcher'):
            self.data_fetcher.use_cache_response = (reply == QMessageBox.Yes)

    def load_from_cache(self):
        """Lädt Daten direkt aus dem neuesten Cache"""
        symbol = self.symbol_edit.text()
        timeframe = self.timeframe_spin.value()
        candles = self.candle_spin.value()

        if not symbol:
            QMessageBox.warning(self, "Fehler", "Bitte Symbol eingeben!")
            return

        cache_dir = Path("cache")
        if not cache_dir.exists():
            QMessageBox.warning(self, "Kein Cache", "Cache-Verzeichnis existiert nicht!")
            return

        # Suche nach Cache für dieses Symbol/Timeframe
        cache_pattern = f"{symbol}_{timeframe}d_{candles}min_*.pkl"
        existing_caches = sorted(cache_dir.glob(cache_pattern))

        if not existing_caches:
            QMessageBox.warning(
                self,
                "Kein Cache",
                f"Kein Cache gefunden für:\n{symbol}, {timeframe} Tage, {candles} min"
            )
            return

        # Lade neuesten Cache
        newest_cache = existing_caches[-1]
        cache_age_hours = (datetime.now() - datetime.fromtimestamp(newest_cache.stat().st_mtime)).total_seconds() / 3600

        try:
            self.update_status(f"📦 Lade aus Cache: {newest_cache.name}")
            with open(newest_cache, 'rb') as f:
                data = pickle.load(f)

            # Setze Daten
            # Handle verschiedene PKL-Formate
            if isinstance(data, dict):
                if 'data' in data:
                    # Unser Format: DataFrame ist unter 'data' key
                    self.historical_data = data['data']
                    actual_length = len(self.historical_data)
                else:
                    # Versuche dict als DataFrame zu interpretieren
                    self.historical_data = pd.DataFrame(data)
                    actual_length = len(self.historical_data)
            else:
                # Direkt ein DataFrame
                self.historical_data = data
                actual_length = len(self.historical_data)
            
            # Zeige korrekte Anzahl
            self.data_status_label.setText(f"✅ {actual_length} Datenpunkte aus Cache ({cache_age_hours:.1f}h alt)")
            self.update_status(f"✅ Cache geladen: {actual_length} Datenpunkte")
            self.log(f"Cache geladen: {newest_cache.name} ({actual_length} Kerzen)")

        except Exception as e:
            error_msg = f"Fehler beim Laden des Cache: {str(e)}"
            self.update_status(f"❌ {error_msg}")
            QMessageBox.critical(self, "Cache-Fehler", error_msg)
            import traceback
            print(f"Cache Load Error:\n{traceback.format_exc()}")

    def clear_cache(self):
        """Löscht alle Cache-Dateien"""
        cache_dir = Path("cache")
        if not cache_dir.exists():
            self.update_status("📦 Cache-Verzeichnis existiert nicht")
            return

        cache_files = list(cache_dir.glob("*.pkl"))
        if not cache_files:
            self.update_status("📦 Cache ist bereits leer")
            return

        # Frage User
        reply = QMessageBox.question(
            self,
            "Cache leeren",
            f"Möchten Sie wirklich {len(cache_files)} Cache-Datei(en) löschen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            for cache_file in cache_files:
                try:
                    cache_file.unlink()
                except Exception as e:
                    self.log(f"❌ Fehler beim Löschen von {cache_file.name}: {e}")

            self.update_status(f"🗑️ {len(cache_files)} Cache-Datei(en) gelöscht")
            self.log(f"Cache geleert: {len(cache_files)} Dateien gelöscht")
            self.update_cache_status()

    def update_cache_status(self):
        """Aktualisiert Cache-Status in UI"""
        cache_dir = Path("cache")
        if not cache_dir.exists():
            self.cache_status_label.setText("📦 Cache: Leer")
            return

        cache_files = list(cache_dir.glob("*.pkl"))
        if not cache_files:
            self.cache_status_label.setText("📦 Cache: Leer")
            return

        # Berechne Gesamtgröße
        total_size = sum(f.stat().st_size for f in cache_files) / (1024 * 1024)  # MB

        # Neuester Cache
        newest = max(cache_files, key=lambda f: f.stat().st_mtime)
        age_hours = (datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)).total_seconds() / 3600

        self.cache_status_label.setText(
            f"📦 Cache: {len(cache_files)} Datei(en) ({total_size:.1f} MB) - Neuester: {age_hours:.1f}h alt"
        )

    def generate_scenarios(self):
        """Generiere Backtest-Szenarien mit flexibleren Ranges (User-Ursprung)"""

        # Hole Symbol für Szenario-Namen
        symbol = self.symbol_edit.text() or "XXX"

        # NEU: Wenn kein Reset gewünscht, behalte existierende Szenarien
        if not hasattr(self, 'scenarios'):
            self.scenarios = {}
        if not hasattr(self, 'scenario_origins'):
            self.scenario_origins = {}

        new_scenarios = {}

        # Parameter-Ranges mit feinerer Granularität
        # Aktien: 50 bis 500 in 50er Schritten
        shares_range = range(
            max(50, (self.shares_from_spin.value() // 50) * 50),
            min(500, self.shares_to_spin.value()) + 1,
            50
        )

        # Step: 0.1% bis 1.2% in 0.1er Schritten
        step_values = [round(x * 0.1, 1) for x in range(
            max(1, int(self.step_from_spin.value() * 10)),
            min(12, int(self.step_to_spin.value() * 10)) + 1
        )]

        # Exit: 0.1% bis 1.2% in 0.1er Schritten
        exit_values = [round(x * 0.1, 1) for x in range(
            max(1, int(self.exit_from_spin.value() * 10)),
            min(12, int(self.exit_to_spin.value() * 10)) + 1
        )]

        # Levels: 2 bis 15 in 1er Schritten
        level_values = range(
            max(2, self.levels_from_spin.value()),
            min(15, self.levels_to_spin.value()) + 1
        )

        counter = 0

        # LONG Szenarien
        if self.long_check.isChecked():
            for shares in shares_range:
                for step in step_values:
                    for exit_pct in exit_values:
                        for levels in level_values:
                            # Name mit Symbol am Ende
                            name = f"L_{shares}_{step}_{exit_pct}_{levels}_{symbol}"
                            new_scenarios[name] = {
                                'type': 'LONG',
                                'shares': shares,
                                'step': step,
                                'exit': exit_pct,
                                'levels': levels
                            }
                            self.scenario_origins[name] = "User"  # NEU: Ursprung setzen
                            counter += 1

        # SHORT Szenarien
        if self.short_check.isChecked():
            for shares in shares_range:
                for step in step_values:
                    for exit_pct in exit_values:
                        for levels in level_values:
                            # Name mit Symbol am Ende
                            name = f"S_{shares}_{step}_{exit_pct}_{levels}_{symbol}"
                            new_scenarios[name] = {
                                'type': 'SHORT',
                                'shares': shares,
                                'step': step,
                                'exit': exit_pct,
                                'levels': levels
                            }
                            self.scenario_origins[name] = "User"  # NEU: Ursprung setzen
                            counter += 1

        # Füge neue Szenarien zu bestehenden hinzu
        self.scenarios.update(new_scenarios)

        # Update UI
        self.update_scenarios_table()
        self.scenario_count_label.setText(f"{len(self.scenarios)} Szenarien (neu: {counter})")
        self.update_status(f"✅ {counter} neue Szenarien generiert (Total: {len(self.scenarios)})")
        self.log(f"Generiert: {counter} neue Szenarien für {symbol} (Total: {len(self.scenarios)})")

    def add_scenarios(self):
        """Füge weitere Szenarien zu bestehenden hinzu"""
        self.generate_scenarios()  # Nutzt die aktualisierte Methode die nicht resettet

    def clear_scenarios(self):
        """Lösche alle Szenarien"""
        self.scenarios = {}
        self.scenario_origins = {}  # NEU: Auch Origins löschen
        self.update_scenarios_table()
        self.scenario_count_label.setText("0 Szenarien")
        self.update_status("🗑️ Alle Szenarien gelöscht")
        self.log("Alle Szenarien gelöscht")

    def delete_selected_scenarios(self):
        """Lösche ausgewählte Szenarien aus der Tabelle"""
        # Sammle ausgewählte Zeilen
        selected_rows = set()
        for item in self.scenarios_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(
                self,
                "Keine Auswahl",
                "Bitte wähle mindestens ein Szenario zum Löschen aus.\n\n"
                "Tipp: Mit Ctrl+Klick kannst du mehrere Szenarien auswählen."
            )
            return

        # Bestätigung
        reply = QMessageBox.question(
            self,
            "Szenarien löschen",
            f"Möchtest du wirklich {len(selected_rows)} Szenario(s) löschen?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        # Sammle Namen der zu löschenden Szenarien
        names_to_delete = []
        for row in selected_rows:
            name_item = self.scenarios_table.item(row, 0)
            if name_item:
                names_to_delete.append(name_item.text())

        # Lösche Szenarien
        deleted_count = 0
        for name in names_to_delete:
            if name in self.scenarios:
                del self.scenarios[name]
                deleted_count += 1
            if name in self.scenario_origins:
                del self.scenario_origins[name]

        # Update UI
        self.update_scenarios_table()
        self.scenario_count_label.setText(f"{len(self.scenarios)} Szenarien")
        self.update_status(f"🗑️ {deleted_count} Szenario(s) gelöscht")
        self.log(f"Gelöscht: {deleted_count} Szenarien")

    def run_voranalyse(self):
        """Führe Voranalyse der historischen Daten durch und generiere KI-Szenarien"""
        # Prüfe ob Daten vorhanden
        if self.historical_data is None:
            QMessageBox.warning(
                self,
                "Keine Daten",
                "Bitte lade zuerst historische Daten im Setup-Tab!"
            )
            return

        df = self.historical_data
        if isinstance(df, dict):
            df = pd.DataFrame(df)

        if df.empty:
            QMessageBox.warning(self, "Keine Daten", "DataFrame ist leer!")
            return

        self.update_status("🔬 Führe Voranalyse durch...")

        # ============================================
        # KERZEN-STATISTIKEN BERECHNEN
        # ============================================
        try:
            # Berechne Kerzen-Range (High - Low) in Prozent
            df['candle_range_pct'] = ((df['high'] - df['low']) / df['low']) * 100

            # Berechne Tages-Ranges
            if isinstance(df.index, pd.DatetimeIndex):
                daily_groups = df.groupby(df.index.date)
                daily_highs = daily_groups['high'].max()
                daily_lows = daily_groups['low'].min()
                daily_ranges_pct = ((daily_highs - daily_lows) / daily_lows) * 100
            else:
                daily_ranges_pct = df['candle_range_pct']

            # Berechne typischen Rebound (Close vs Low für bullish candles)
            bullish_mask = df['close'] > df['open']
            if bullish_mask.any():
                bullish_rebounds = ((df.loc[bullish_mask, 'close'] - df.loc[bullish_mask, 'low']) /
                                   df.loc[bullish_mask, 'low']) * 100
                typical_rebound = bullish_rebounds.mean()
            else:
                typical_rebound = df['candle_range_pct'].mean() * 0.5

            # Statistiken sammeln
            stats = {
                'symbol': self.symbol_edit.text(),
                'analysezeitraum': f"{self.timeframe_spin.value()} Tage",
                'von_datum': df.index.min().strftime('%d.%m.%Y') if isinstance(df.index, pd.DatetimeIndex) else 'N/A',
                'bis_datum': df.index.max().strftime('%d.%m.%Y') if isinstance(df.index, pd.DatetimeIndex) else 'N/A',
                'timeframe': f"{self.candle_spin.value()} Minuten",
                'tages_range_avg': daily_ranges_pct.mean(),
                'kerzen_range_avg': df['candle_range_pct'].mean(),
                'percentile_25': df['candle_range_pct'].quantile(0.25),
                'percentile_50': df['candle_range_pct'].quantile(0.50),
                'percentile_75': df['candle_range_pct'].quantile(0.75),
                'percentile_90': df['candle_range_pct'].quantile(0.90),
                'typical_rebound': typical_rebound,
                'bullish_pct': (bullish_mask.sum() / len(df)) * 100,
                'extreme_days': (daily_ranges_pct > daily_ranges_pct.quantile(0.90)).sum() if len(daily_ranges_pct) > 0 else 0,
                'avg_price': df['close'].mean()
            }

            self.voranalyse_stats = stats

            # ============================================
            # STATISTIK-TABELLE AKTUALISIEREN
            # ============================================
            rows = [
                ("ANALYSE-UMFANG", ""),
                ("Symbol", stats['symbol']),
                ("Analysezeitraum", stats['analysezeitraum']),
                ("von Datum", stats['von_datum']),
                ("bis Datum", stats['bis_datum']),
                ("Timeframe", stats['timeframe']),
                ("", ""),
                ("KERZEN-STATISTIKEN", ""),
                ("Ø Tages-Range", f"{stats['tages_range_avg']:.2f}%"),
                ("Ø Kerzen-Range", f"{stats['kerzen_range_avg']:.2f}%"),
                ("25% Perzentil", f"{stats['percentile_25']:.2f}%"),
                ("50% Perzentil", f"{stats['percentile_50']:.2f}%"),
                ("75% Perzentil", f"{stats['percentile_75']:.2f}%"),
                ("90% Perzentil", f"{stats['percentile_90']:.2f}%"),
                ("Typischer Rebound", f"{stats['typical_rebound']:.2f}%"),
                ("Bullish Kerzen", f"{stats['bullish_pct']:.1f}%"),
                ("Extreme Tage", f"{stats['extreme_days']}")
            ]

            self.voranalyse_table.setRowCount(len(rows))
            for row_idx, (metric, value) in enumerate(rows):
                metric_item = QTableWidgetItem(metric)
                value_item = QTableWidgetItem(str(value))

                # Header-Zeilen fett und farbig
                if metric in ["ANALYSE-UMFANG", "KERZEN-STATISTIKEN"]:
                    font = metric_item.font()
                    font.setBold(True)
                    metric_item.setFont(font)
                    metric_item.setBackground(QColor(220, 220, 220))
                    value_item.setBackground(QColor(220, 220, 220))

                self.voranalyse_table.setItem(row_idx, 0, metric_item)
                self.voranalyse_table.setItem(row_idx, 1, value_item)

            self.analyse_info_label.setText(f"✅ Analyse abgeschlossen - {len(df)} Kerzen analysiert")

            # ============================================
            # KI-SZENARIEN GENERIEREN
            # ============================================
            self._generate_ki_scenarios(stats)

        except Exception as e:
            import traceback
            error_msg = f"Fehler bei Voranalyse: {str(e)}"
            self.update_status(f"❌ {error_msg}")
            self.log(f"ERROR: {error_msg}\n{traceback.format_exc()}")
            QMessageBox.critical(self, "Fehler", error_msg)

    def _generate_ki_scenarios(self, stats):
        """Generiere KI-basierte Szenarien basierend auf Voranalyse-Statistiken"""

        # Hole Parameter aus UI
        min_profit_cents = self.min_profit_cents_spin.value() / 100  # In Dollar
        shares = self.ki_shares_spin.value()
        min_levels = self.ki_min_levels_spin.value()
        max_levels = self.ki_max_levels_spin.value()
        max_scenarios = self.ki_max_scenarios_spin.value()
        symbol = self.symbol_edit.text() or "XXX"
        avg_price = stats.get('avg_price', 100)

        # Berechne minimales Exit% basierend auf min_profit_cents
        # min_profit = shares * avg_price * exit_pct/100
        # => exit_pct = min_profit * 100 / (shares * avg_price)
        min_exit_pct = (min_profit_cents * 100) / avg_price
        min_exit_pct = max(0.1, round(min_exit_pct, 2))  # Mindestens 0.1%

        self.log(f"KI-Szenario-Generierung: Min Exit% = {min_exit_pct:.2f}% (basierend auf ${min_profit_cents:.2f} Gewinn bei Ø Preis ${avg_price:.2f})")

        # ============================================
        # STRATEGIE: Maximale Trade-Frequenz
        # ============================================
        # Da Restaktien OK sind, optimieren wir auf häufige Fills und schnelle Exits

        kerzen_range = stats['kerzen_range_avg']
        typical_rebound = stats['typical_rebound']
        tages_range = stats['tages_range_avg']

        # Berechne optimale Step-Werte (aggressiv für viele Fills)
        # Aggressive: 50% der Kerzen-Range (häufige Fills)
        # Moderat: 75% der Kerzen-Range
        # Konservativ: 100% der Kerzen-Range (weniger Fills aber sicherer)
        step_aggressive = max(0.1, round(kerzen_range * 0.5, 1))
        step_moderate = max(0.1, round(kerzen_range * 0.75, 1))
        step_conservative = max(0.2, round(kerzen_range, 1))

        # Berechne optimale Exit-Werte (basierend auf Rebound)
        # Schnelle Exits für hohes Cycling
        exit_aggressive = max(min_exit_pct, round(typical_rebound * 0.5, 1))
        exit_moderate = max(min_exit_pct, round(typical_rebound * 0.75, 1))
        exit_conservative = max(min_exit_pct, round(typical_rebound, 1))

        # Berechne Level-Vorschläge basierend auf Tages-Range
        # Mehr Levels = mehr Kapazität (Restaktien sind OK)
        levels_by_range = int(tages_range / step_moderate) if step_moderate > 0 else 5
        levels_by_range = max(min_levels, min(max_levels, levels_by_range))

        # ============================================
        # SZENARIO-SETS ERSTELLEN
        # ============================================
        ki_scenarios = []

        # Set 1: Aggressiv (maximale Trade-Frequenz)
        ki_scenarios.append({
            'name': f"KI_aggressiv_L",
            'type': 'LONG',
            'shares': shares,
            'step': step_aggressive,
            'exit': exit_aggressive,
            'levels': max_levels
        })
        ki_scenarios.append({
            'name': f"KI_aggressiv_S",
            'type': 'SHORT',
            'shares': shares,
            'step': step_aggressive,
            'exit': exit_aggressive,
            'levels': max_levels
        })

        # Set 2: Moderat (ausgewogen)
        ki_scenarios.append({
            'name': f"KI_moderat_L",
            'type': 'LONG',
            'shares': shares,
            'step': step_moderate,
            'exit': exit_moderate,
            'levels': levels_by_range
        })
        ki_scenarios.append({
            'name': f"KI_moderat_S",
            'type': 'SHORT',
            'shares': shares,
            'step': step_moderate,
            'exit': exit_moderate,
            'levels': levels_by_range
        })

        # Set 3: Konservativ (sicherer)
        ki_scenarios.append({
            'name': f"KI_konservativ_L",
            'type': 'LONG',
            'shares': shares,
            'step': step_conservative,
            'exit': exit_conservative,
            'levels': min_levels
        })
        ki_scenarios.append({
            'name': f"KI_konservativ_S",
            'type': 'SHORT',
            'shares': shares,
            'step': step_conservative,
            'exit': exit_conservative,
            'levels': min_levels
        })

        # Limitiere auf max_scenarios
        ki_scenarios = ki_scenarios[:max_scenarios]

        # ============================================
        # SZENARIEN ZUR LISTE HINZUFÜGEN
        # ============================================
        added_count = 0
        for scenario in ki_scenarios:
            name = f"{scenario['name']}_{symbol}"
            self.scenarios[name] = {
                'type': scenario['type'],
                'shares': scenario['shares'],
                'step': scenario['step'],
                'exit': scenario['exit'],
                'levels': scenario['levels']
            }
            self.scenario_origins[name] = "KI"  # Ursprung als KI markieren
            added_count += 1

        # Update UI
        self.update_scenarios_table()
        self.scenario_count_label.setText(f"{len(self.scenarios)} Szenarien")
        self.update_status(f"✅ Voranalyse abgeschlossen - {added_count} KI-Szenarien generiert")
        self.log(f"KI generierte {added_count} optimierte Szenarien basierend auf Statistiken:")
        self.log(f"   Step-Range: {step_aggressive}-{step_conservative}%, Exit-Range: {exit_aggressive}-{exit_conservative}%")

    def update_scenarios_table(self):
        """Aktualisiere Szenarien-Tabelle mit Ursprung-Spalte"""
        self.scenarios_table.setRowCount(len(self.scenarios))

        for row, (name, config) in enumerate(self.scenarios.items()):
            self.scenarios_table.setItem(row, 0, QTableWidgetItem(name))
            self.scenarios_table.setItem(row, 1, QTableWidgetItem(config['type']))
            self.scenarios_table.setItem(row, 2, QTableWidgetItem(str(config['shares'])))
            self.scenarios_table.setItem(row, 3, QTableWidgetItem(f"{config['step']}%"))
            self.scenarios_table.setItem(row, 4, QTableWidgetItem(f"{config['exit']}%"))
            self.scenarios_table.setItem(row, 5, QTableWidgetItem(str(config['levels'])))

            # Ursprung-Spalte mit Farbkodierung
            origin = self.scenario_origins.get(name, "User")
            origin_item = QTableWidgetItem(origin)
            if origin == "KI":
                origin_item.setBackground(QColor(200, 230, 255))  # Hellblau für KI
            else:
                origin_item.setBackground(QColor(255, 255, 200))  # Hellgelb für User
            self.scenarios_table.setItem(row, 6, origin_item)
            
    def run_backtest(self):
        """Starte Backtest für alle Szenarien"""
        if self.historical_data is None:
            self.update_status("❌ Bitte erst Daten laden!")
            return
        if isinstance(self.historical_data, pd.DataFrame) and self.historical_data.empty:
            self.update_status("❌ DataFrame ist leer!")
            return
        if isinstance(self.historical_data, dict) and len(self.historical_data) == 0:
            self.update_status("❌ Keine Daten im Dictionary!")
            return

        if not self.scenarios:
            self.update_status("❌ Bitte erst Szenarien generieren!")
            return
        
        self.log(f"Starte Backtest mit {len(self.scenarios)} Szenarien...")
        
        # UI Update
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(self.scenarios))
        
        # Starte Worker mit Symbol
        symbol = self.symbol_edit.text()
        commission = self.commission_spin.value() if hasattr(self, 'commission_spin') else 0.005

        self.last_symbol = symbol
        self.last_timeframe = self.timeframe_spin.value()
        self.last_candle_minutes = self.candle_spin.value()

        # DEBUG: Kommission
        print(f"\n💰 Backtest startet mit Kommission: ${commission:.4f} pro Aktie pro Trade")

        self.backtest_worker = BacktestWorker(
            self.scenarios,
            self.historical_data,
            symbol,
            commission_per_share=commission
        )
        self.backtest_worker.progress_update.connect(self.update_status)
        self.backtest_worker.results_ready.connect(self.on_results_ready)
        self.backtest_worker.error_occurred.connect(self.on_error)
        self.backtest_worker.start()
        
    def on_results_ready(self, results):
        """Callback wenn Ergebnisse fertig"""
        self.log(f"✅ Backtest abgeschlossen - {len(results)} Ergebnisse")

        # Speichere Ergebnisse für späteren Export
        self.backtest_results = results
        self.last_results = results


        # DEBUG: Print first result to see what data we have
        if results:
            first_key = list(results.keys())[0]
            first_result = results[first_key]
            print(f"\n🔍 DEBUG - Backtest Result Structure:")
            print(f"   Keys: {first_result.keys()}")
            print(f"   Sample: {first_result}")
            self.log(f"DEBUG: Result keys = {list(first_result.keys())}")

        # Sortiere nach Netto P&L
        sorted_results = sorted(
            results.items(),
            key=lambda x: x[1].get('net_pnl', 0),
            reverse=True
        )

        # Update Tabelle
        self.results_table.setRowCount(len(sorted_results))

        best_long = None
        best_short = None
        total_return = 0

        for row, (name, result) in enumerate(sorted_results):
            config = self.scenarios[name]

            # Extrahiere alle 16 Werte (inkl. Initial Capital)
            symbol = result.get('symbol', 'N/A')
            initial_capital = result.get('initial_capital', 0.0)  # NEU
            pnl_percent = result.get('pnl_percent', 0.0)
            pnl_usd = result.get('pnl_usd', 0.0)
            win_rate = result.get('win_rate', 0.0)
            max_dd = result.get('max_drawdown', 0.0)
            trades_count = result.get('trades', 0)
            remaining_shares = result.get('remaining_shares', 0)
            avg_entry = result.get('avg_entry_price', 0.0)
            last_price = result.get('last_price', 0.0)
            unrealized_pnl = result.get('unrealized_pnl', 0.0)
            net_pnl = result.get('net_pnl', 0.0)
            commission = result.get('commission', 0.0)

            # DEBUG für erste Zeile
            if row == 0:
                print(f"\n   🔍 Row 0 Data Mapping:")
                print(f"      Symbol: {symbol}")
                print(f"      Initial Capital: ${initial_capital:,.2f}")
                print(f"      Net P&L %: {pnl_percent:.2f}%")
                print(f"      Realized P&L $: ${pnl_usd:,.2f}")
                print(f"      Win Rate: {win_rate:.1f}%")
                print(f"      Max DD: {max_dd:.1f}%")
                print(f"      Trades: {trades_count}")
                print(f"      Rest Aktien: {remaining_shares}")
                print(f"      Ø Entry: ${avg_entry:.2f}")
                print(f"      Last Price: ${last_price:.2f}")
                print(f"      Unrealized: ${unrealized_pnl:,.2f}")
                print(f"      Net P&L: ${net_pnl:,.2f}")
                print(f"      Commission: ${commission:,.2f}")

            # Farbe basierend auf Netto P&L
            color = QColor(0, 255, 0, 50) if net_pnl > 0 else QColor(255, 0, 0, 50)

            # 16 Spalten Mapping (inkl. Initial Capital)
            items = [
                QTableWidgetItem(str(row + 1)),                     # Col 0: Rang
                QTableWidgetItem(name),                             # Col 1: Szenario
                QTableWidgetItem(symbol),                           # Col 2: Symbol
                QTableWidgetItem(config['type']),                   # Col 3: Typ
                QTableWidgetItem(f"${initial_capital:,.2f}"),      # Col 4: Initial Capital $ (NEU!)
                QTableWidgetItem(f"{pnl_percent:.2f}%"),           # Col 5: Net P&L %
                QTableWidgetItem(f"${pnl_usd:,.2f}"),              # Col 6: Realized P&L $
                QTableWidgetItem(f"{win_rate:.1f}%"),              # Col 7: Win Rate %
                QTableWidgetItem(f"{max_dd:.1f}%"),                # Col 8: Max DD %
                QTableWidgetItem(str(trades_count)),                # Col 9: Trades (BUY+SELL)
                QTableWidgetItem(str(remaining_shares)),            # Col 10: Rest Aktien
                QTableWidgetItem(f"${avg_entry:.2f}"),             # Col 11: Ø Kurs Rest
                QTableWidgetItem(f"${last_price:.2f}"),            # Col 12: Letzter Kurs
                QTableWidgetItem(f"${unrealized_pnl:,.2f}"),       # Col 13: Unrealized P&L $
                QTableWidgetItem(f"${net_pnl:,.2f}"),              # Col 14: Net P&L $
                QTableWidgetItem(f"${commission:,.2f}")            # Col 15: Kommission $
            ]

            for col, item in enumerate(items):
                if col >= 4:  # Färbe nur Ergebnis-Spalten (ab P&L %)
                    item.setBackground(color)
                self.results_table.setItem(row, col, item)

            # Track bestes Long/Short basierend auf Netto P&L
            if config['type'] == 'LONG' and (best_long is None or net_pnl > best_long[1]):
                best_long = (name, net_pnl)
            elif config['type'] == 'SHORT' and (best_short is None or net_pnl > best_short[1]):
                best_short = (name, net_pnl)

            total_return += pnl_percent

        # Update Statistiken
        if best_long:
            self.best_long_label.setText(f"Bestes LONG: {best_long[0]} (${best_long[1]:,.2f})")
        if best_short:
            self.best_short_label.setText(f"Bestes SHORT: {best_short[0]} (${best_short[1]:,.2f})")

        avg_return = total_return / len(results) if results else 0
        self.avg_return_label.setText(f"Ø Return: {avg_return:.2f}%")
        self.total_scenarios_label.setText(f"Getestet: {len(results)}")

        # UI Reset
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.update_status("✅ Backtest erfolgreich abgeschlossen")
        
    def export_to_excel(self):
        """Export nach Excel"""
        print("DEBUG: export_to_excel wurde aufgerufen!")  # <-- FÜGE DIESE ZEILE HINZU
        self.log("DEBUG: In export_to_excel Methode")      # <-- UND DIESE

        if not self.last_results:
            self.update_status("❌ Keine Backtest-Ergebnisse vorhanden!")
            return
        
        try:
            from gridtrader.infrastructure.reports.excel_export_adapter import ExcelExportAdapter
            
            adapter = ExcelExportAdapter()
            filepath = adapter.export_backtest_results(
                results=self.last_results,
                scenarios=self.scenarios,
                symbol=self.last_symbol or "UNKNOWN",
                timeframe_days=self.last_timeframe or 30,
                candle_minutes=self.last_candle_minutes or 5,
                historical_data=self.historical_data
            )
            
            self.update_status(f"✅ Excel-Report erstellt: {filepath}")
            self.log(f"Excel-Export erfolgreich: {filepath}")
            
        except Exception as e:
            self.update_status(f"❌ Excel-Export fehlgeschlagen: {str(e)}")
            self.log(f"Fehler beim Excel-Export: {str(e)}")

    def export_selected_to_trading_bot(self):
        """Exportiere ausgewählte Szenarien zum Trading-Bot"""
        # Prüfe ob Ergebnisse vorhanden
        if not self.backtest_results:
            QMessageBox.warning(
                self,
                "Keine Ergebnisse",
                "Bitte zuerst einen Backtest durchführen."
            )
            return

        # Hole alle ausgewählten Zeilen
        selected_rows = set()
        for item in self.results_table.selectedItems():
            selected_rows.add(item.row())

        if not selected_rows:
            QMessageBox.warning(
                self,
                "Keine Auswahl",
                "Bitte wähle mindestens ein Szenario aus der Ergebnistabelle aus.\n\n"
                "Tipp: Mit Ctrl+Klick kannst du mehrere Szenarien auswählen."
            )
            return

        # Sammle alle ausgewählten Szenarien
        scenarios_to_export = []
        for row in sorted(selected_rows):
            scenario_name_item = self.results_table.item(row, 1)
            if not scenario_name_item:
                continue

            scenario_name = scenario_name_item.text()

            # Prüfe ob Szenario existiert
            if scenario_name not in self.scenarios:
                self.log(f"⚠️ Szenario '{scenario_name}' nicht gefunden, überspringe...")
                continue

            # Hole Config und Result
            config = self.scenarios[scenario_name]
            result = self.backtest_results.get(scenario_name, {})

            scenarios_to_export.append((scenario_name, config, result))

        if not scenarios_to_export:
            QMessageBox.warning(
                self,
                "Fehler",
                "Keine gültigen Szenarien zum Exportieren gefunden."
            )
            return

        # Emittiere Signal mit Liste
        self.export_to_trading_bot.emit(scenarios_to_export)

        # Feedback
        count = len(scenarios_to_export)
        names = ", ".join([s[0] for s in scenarios_to_export[:3]])
        if count > 3:
            names += f" ... (+{count - 3} weitere)"

        self.update_status(f"✅ {count} Szenario(s) zum Trading-Bot exportiert")
        self.log(f"Exportiert: {count} Szenarien -> Trading-Bot")

        QMessageBox.information(
            self,
            "Export erfolgreich",
            f"{count} Szenario(s) wurden zum Trading-Bot exportiert:\n\n"
            f"{names}\n\n"
            f"Wechsle zum Trading-Bot Tab um sie zu sehen."
        )

    def update_status(self, message):
        """Update Status Label"""
        self.status_label.setText(message)
        
    def log(self, message):
        """Füge Log-Eintrag hinzu"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
    def on_error(self, error_msg):
        """Error Handler"""
        self.update_status(f"❌ {error_msg}")
        self.log(f"ERROR: {error_msg}")
        self.fetch_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)


"""
Test Entry Point
"""
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys
    
    app = QApplication(sys.argv)
    widget = AdvancedBacktestWidget()
    widget.show()
    sys.exit(app.exec())