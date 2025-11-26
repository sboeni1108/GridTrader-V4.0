"""
Level-Pool System

Sammelt alle verfügbaren Levels aus allen Szenarien als "Lego-Steine"
für den KI-Controller.

Der Controller wählt aus diesem Pool die optimale Kombination von Levels
basierend auf der aktuellen Marktsituation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Any, Set
from uuid import uuid4
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker


class LevelPoolStatus(str, Enum):
    """Status eines Levels im Pool"""
    AVAILABLE = "AVAILABLE"          # Verfügbar für Aktivierung
    ACTIVE = "ACTIVE"                # Vom Controller aktiviert
    WAITING = "WAITING"              # Wartet auf Entry-Fill
    IN_POSITION = "IN_POSITION"      # Position offen
    COOLDOWN = "COOLDOWN"            # Kürzlich deaktiviert, kurze Pause
    BLOCKED = "BLOCKED"              # Temporär blockiert (z.B. Risk Limit)


@dataclass
class PoolLevel:
    """
    Ein einzelnes Level im Pool

    Enthält alle Informationen, die der Controller für seine
    Entscheidungen benötigt.
    """
    # Identifikation
    level_id: str
    scenario_id: str
    scenario_name: str

    # Basis-Daten
    symbol: str
    side: str  # "LONG" oder "SHORT"
    level_num: int

    # Prozentuale Werte (relativ zum Basis-Preis)
    entry_pct: float
    exit_pct: float
    guardian_pct: Optional[float] = None

    # Absolute Preise (werden bei Aktivierung berechnet)
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None
    guardian_price: Optional[Decimal] = None
    base_price: Optional[Decimal] = None

    # Konfiguration
    shares: int = 100

    # Status
    status: LevelPoolStatus = LevelPoolStatus.AVAILABLE
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None

    # Controller-Tracking
    activation_count: int = 0        # Wie oft wurde dieses Level aktiviert
    success_count: int = 0           # Wie oft war es erfolgreich (Exit erreicht)
    fail_count: int = 0              # Wie oft ist es fehlgeschlagen
    last_score: float = 0.0          # Letzter Bewertungs-Score
    avg_hold_time_sec: float = 0.0   # Durchschnittliche Haltezeit

    # Tags für Filterung
    tags: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dictionary"""
        return {
            'level_id': self.level_id,
            'scenario_id': self.scenario_id,
            'scenario_name': self.scenario_name,
            'symbol': self.symbol,
            'side': self.side,
            'level_num': self.level_num,
            'entry_pct': self.entry_pct,
            'exit_pct': self.exit_pct,
            'guardian_pct': self.guardian_pct,
            'entry_price': str(self.entry_price) if self.entry_price else None,
            'exit_price': str(self.exit_price) if self.exit_price else None,
            'guardian_price': str(self.guardian_price) if self.guardian_price else None,
            'base_price': str(self.base_price) if self.base_price else None,
            'shares': self.shares,
            'status': self.status.value,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'activation_count': self.activation_count,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'last_score': self.last_score,
            'avg_hold_time_sec': self.avg_hold_time_sec,
            'tags': list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PoolLevel':
        """Erstellt Instanz aus Dictionary"""
        level = cls(
            level_id=data['level_id'],
            scenario_id=data['scenario_id'],
            scenario_name=data['scenario_name'],
            symbol=data['symbol'],
            side=data['side'],
            level_num=data['level_num'],
            entry_pct=data['entry_pct'],
            exit_pct=data['exit_pct'],
            guardian_pct=data.get('guardian_pct'),
            shares=data.get('shares', 100),
            status=LevelPoolStatus(data.get('status', 'AVAILABLE')),
            activation_count=data.get('activation_count', 0),
            success_count=data.get('success_count', 0),
            fail_count=data.get('fail_count', 0),
            last_score=data.get('last_score', 0.0),
            avg_hold_time_sec=data.get('avg_hold_time_sec', 0.0),
            tags=set(data.get('tags', [])),
        )

        if data.get('entry_price'):
            level.entry_price = Decimal(data['entry_price'])
        if data.get('exit_price'):
            level.exit_price = Decimal(data['exit_price'])
        if data.get('guardian_price'):
            level.guardian_price = Decimal(data['guardian_price'])
        if data.get('base_price'):
            level.base_price = Decimal(data['base_price'])
        if data.get('activated_at'):
            level.activated_at = datetime.fromisoformat(data['activated_at'])
        if data.get('deactivated_at'):
            level.deactivated_at = datetime.fromisoformat(data['deactivated_at'])

        return level

    def calculate_prices(self, base_price: Decimal) -> None:
        """Berechnet absolute Preise basierend auf Basis-Preis"""
        self.base_price = base_price
        self.entry_price = base_price * (1 + Decimal(str(self.entry_pct / 100)))
        self.exit_price = base_price * (1 + Decimal(str(self.exit_pct / 100)))

        if self.guardian_pct is not None:
            self.guardian_price = base_price * (1 + Decimal(str(self.guardian_pct / 100)))

    def get_profit_potential_pct(self) -> float:
        """Berechnet das Profit-Potenzial in Prozent"""
        if self.side == "LONG":
            return self.exit_pct - self.entry_pct
        else:
            return self.entry_pct - self.exit_pct

    def get_step_size_pct(self) -> float:
        """Berechnet die Step-Größe (Abstand Entry zu Exit) in Prozent"""
        return abs(self.exit_pct - self.entry_pct)

    def get_success_rate(self) -> Optional[float]:
        """Berechnet die Erfolgsquote"""
        total = self.success_count + self.fail_count
        if total == 0:
            return None
        return self.success_count / total

    def mark_activated(self, score: float = 0.0) -> None:
        """Markiert Level als aktiviert"""
        self.status = LevelPoolStatus.ACTIVE
        self.activated_at = datetime.now()
        self.activation_count += 1
        self.last_score = score

    def mark_deactivated(self, success: bool = False) -> None:
        """Markiert Level als deaktiviert"""
        now = datetime.now()
        self.deactivated_at = now

        # Haltezeit berechnen
        if self.activated_at:
            hold_time = (now - self.activated_at).total_seconds()
            # Rolling Average
            if self.activation_count > 1:
                self.avg_hold_time_sec = (
                    (self.avg_hold_time_sec * (self.activation_count - 1) + hold_time)
                    / self.activation_count
                )
            else:
                self.avg_hold_time_sec = hold_time

        # Erfolg/Misserfolg tracken
        if success:
            self.success_count += 1
        else:
            self.fail_count += 1

        # Status auf Cooldown setzen
        self.status = LevelPoolStatus.COOLDOWN


class LevelPool(QObject):
    """
    Haupt-Klasse für den Level-Pool

    Verwaltet alle verfügbaren Levels und bietet Methoden
    für Filterung, Scoring und Auswahl.
    """

    # Signals
    level_added = Signal(str)       # level_id
    level_removed = Signal(str)     # level_id
    level_updated = Signal(str)     # level_id
    pool_reloaded = Signal(int)     # Anzahl Levels

    def __init__(self, parent=None):
        super().__init__(parent)

        # Level-Speicher
        self._levels: Dict[str, PoolLevel] = {}

        # Indizes für schnelle Suche
        self._by_symbol: Dict[str, Set[str]] = {}      # symbol -> {level_ids}
        self._by_scenario: Dict[str, Set[str]] = {}    # scenario_id -> {level_ids}
        self._by_status: Dict[LevelPoolStatus, Set[str]] = {
            status: set() for status in LevelPoolStatus
        }

        # Thread-Safety
        self._mutex = QMutex()

        # Persistenz
        self._data_dir = Path.home() / ".gridtrader"
        self._pool_file = self._data_dir / "level_pool.json"

    # ==================== CRUD OPERATIONS ====================

    def add_level(self, level: PoolLevel) -> bool:
        """
        Fügt ein Level zum Pool hinzu

        Returns:
            True wenn erfolgreich hinzugefügt
        """
        with QMutexLocker(self._mutex):
            if level.level_id in self._levels:
                return False  # Bereits vorhanden

            self._levels[level.level_id] = level

            # Indizes aktualisieren
            if level.symbol not in self._by_symbol:
                self._by_symbol[level.symbol] = set()
            self._by_symbol[level.symbol].add(level.level_id)

            if level.scenario_id not in self._by_scenario:
                self._by_scenario[level.scenario_id] = set()
            self._by_scenario[level.scenario_id].add(level.level_id)

            self._by_status[level.status].add(level.level_id)

        self.level_added.emit(level.level_id)
        return True

    def remove_level(self, level_id: str) -> bool:
        """Entfernt ein Level aus dem Pool"""
        with QMutexLocker(self._mutex):
            if level_id not in self._levels:
                return False

            level = self._levels[level_id]

            # Aus Indizes entfernen
            if level.symbol in self._by_symbol:
                self._by_symbol[level.symbol].discard(level_id)
            if level.scenario_id in self._by_scenario:
                self._by_scenario[level.scenario_id].discard(level_id)
            self._by_status[level.status].discard(level_id)

            del self._levels[level_id]

        self.level_removed.emit(level_id)
        return True

    def get_level(self, level_id: str) -> Optional[PoolLevel]:
        """Holt ein Level anhand der ID"""
        with QMutexLocker(self._mutex):
            return self._levels.get(level_id)

    def update_level_status(
        self,
        level_id: str,
        new_status: LevelPoolStatus,
        success: bool = False
    ) -> bool:
        """Aktualisiert den Status eines Levels"""
        with QMutexLocker(self._mutex):
            if level_id not in self._levels:
                return False

            level = self._levels[level_id]
            old_status = level.status

            # Status-Index aktualisieren
            self._by_status[old_status].discard(level_id)
            self._by_status[new_status].add(level_id)

            # Level aktualisieren
            if new_status == LevelPoolStatus.ACTIVE:
                level.mark_activated()
            elif old_status == LevelPoolStatus.ACTIVE and new_status in (
                LevelPoolStatus.AVAILABLE, LevelPoolStatus.COOLDOWN
            ):
                level.mark_deactivated(success=success)
            else:
                level.status = new_status

        self.level_updated.emit(level_id)
        return True

    # ==================== QUERY METHODS ====================

    def get_all_levels(self) -> List[PoolLevel]:
        """Gibt alle Levels zurück"""
        with QMutexLocker(self._mutex):
            return list(self._levels.values())

    def get_levels_by_symbol(self, symbol: str) -> List[PoolLevel]:
        """Gibt alle Levels für ein Symbol zurück"""
        with QMutexLocker(self._mutex):
            level_ids = self._by_symbol.get(symbol, set())
            return [self._levels[lid] for lid in level_ids if lid in self._levels]

    def get_levels_by_scenario(self, scenario_id: str) -> List[PoolLevel]:
        """Gibt alle Levels eines Szenarios zurück"""
        with QMutexLocker(self._mutex):
            level_ids = self._by_scenario.get(scenario_id, set())
            return [self._levels[lid] for lid in level_ids if lid in self._levels]

    def get_levels_by_status(self, status: LevelPoolStatus) -> List[PoolLevel]:
        """Gibt alle Levels mit einem bestimmten Status zurück"""
        with QMutexLocker(self._mutex):
            level_ids = self._by_status.get(status, set())
            return [self._levels[lid] for lid in level_ids if lid in self._levels]

    def get_available_levels(self, symbol: Optional[str] = None) -> List[PoolLevel]:
        """Gibt alle verfügbaren (aktivierbaren) Levels zurück"""
        with QMutexLocker(self._mutex):
            available_ids = self._by_status.get(LevelPoolStatus.AVAILABLE, set())

            if symbol:
                symbol_ids = self._by_symbol.get(symbol, set())
                level_ids = available_ids & symbol_ids
            else:
                level_ids = available_ids

            return [self._levels[lid] for lid in level_ids if lid in self._levels]

    def get_active_levels(self, symbol: Optional[str] = None) -> List[PoolLevel]:
        """Gibt alle aktuell aktiven Levels zurück"""
        with QMutexLocker(self._mutex):
            active_ids = (
                self._by_status.get(LevelPoolStatus.ACTIVE, set()) |
                self._by_status.get(LevelPoolStatus.WAITING, set()) |
                self._by_status.get(LevelPoolStatus.IN_POSITION, set())
            )

            if symbol:
                symbol_ids = self._by_symbol.get(symbol, set())
                level_ids = active_ids & symbol_ids
            else:
                level_ids = active_ids

            return [self._levels[lid] for lid in level_ids if lid in self._levels]

    # ==================== FILTERING ====================

    def filter_levels(
        self,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        status: Optional[LevelPoolStatus] = None,
        min_profit_pct: Optional[float] = None,
        max_step_pct: Optional[float] = None,
        min_step_pct: Optional[float] = None,
        tags: Optional[Set[str]] = None,
    ) -> List[PoolLevel]:
        """
        Filtert Levels nach verschiedenen Kriterien

        Args:
            symbol: Filter nach Symbol
            side: Filter nach Seite ("LONG" oder "SHORT")
            status: Filter nach Status
            min_profit_pct: Minimum Profit-Potenzial
            max_step_pct: Maximum Step-Größe
            min_step_pct: Minimum Step-Größe
            tags: Levels müssen alle diese Tags haben
        """
        with QMutexLocker(self._mutex):
            result = []

            for level in self._levels.values():
                # Symbol-Filter
                if symbol and level.symbol != symbol:
                    continue

                # Side-Filter
                if side and level.side != side:
                    continue

                # Status-Filter
                if status and level.status != status:
                    continue

                # Profit-Filter
                if min_profit_pct is not None:
                    if level.get_profit_potential_pct() < min_profit_pct:
                        continue

                # Step-Size Filter
                step = level.get_step_size_pct()
                if max_step_pct is not None and step > max_step_pct:
                    continue
                if min_step_pct is not None and step < min_step_pct:
                    continue

                # Tags-Filter
                if tags and not tags.issubset(level.tags):
                    continue

                result.append(level)

            return result

    # ==================== STATISTICS ====================

    def get_statistics(self) -> Dict[str, Any]:
        """Gibt Pool-Statistiken zurück"""
        with QMutexLocker(self._mutex):
            total = len(self._levels)
            by_status = {
                status.value: len(ids)
                for status, ids in self._by_status.items()
            }
            by_symbol = {
                symbol: len(ids)
                for symbol, ids in self._by_symbol.items()
            }

            # Erfolgsstatistiken
            total_activations = sum(l.activation_count for l in self._levels.values())
            total_successes = sum(l.success_count for l in self._levels.values())
            total_fails = sum(l.fail_count for l in self._levels.values())

            return {
                'total_levels': total,
                'by_status': by_status,
                'by_symbol': by_symbol,
                'total_activations': total_activations,
                'total_successes': total_successes,
                'total_fails': total_fails,
                'overall_success_rate': (
                    total_successes / (total_successes + total_fails)
                    if (total_successes + total_fails) > 0 else None
                ),
            }

    # ==================== IMPORT FROM SCENARIOS ====================

    def import_from_scenarios(self, scenarios: Dict[str, Dict[str, Any]]) -> int:
        """
        Importiert Levels aus Szenarien (Trading-Bot Format)

        Args:
            scenarios: Dict von Szenarien aus dem Trading-Bot

        Returns:
            Anzahl importierter Levels
        """
        imported = 0

        for scenario_name, scenario_data in scenarios.items():
            scenario_id = scenario_data.get('id', str(uuid4())[:8])
            symbol = scenario_data.get('symbol', 'UNKNOWN')
            levels = scenario_data.get('levels', [])

            for level_data in levels:
                level_num = level_data.get('level_num', 0)
                side = level_data.get('side', 'LONG')

                # Eindeutige Level-ID generieren
                level_id = f"{scenario_id}_{level_num}_{side}"

                # Existiert bereits?
                if level_id in self._levels:
                    continue

                # PoolLevel erstellen
                pool_level = PoolLevel(
                    level_id=level_id,
                    scenario_id=scenario_id,
                    scenario_name=scenario_name,
                    symbol=symbol,
                    side=side,
                    level_num=level_num,
                    entry_pct=level_data.get('entry_pct', 0),
                    exit_pct=level_data.get('exit_pct', 0),
                    guardian_pct=level_data.get('guardian_pct'),
                    shares=level_data.get('shares', 100),
                )

                # Tags aus Szenario übernehmen
                if 'tags' in scenario_data:
                    pool_level.tags.update(scenario_data['tags'])

                # Volatilitäts-Tags basierend auf Step-Größe
                step = pool_level.get_step_size_pct()
                if step > 0.8:
                    pool_level.tags.add('high_volatility')
                elif step > 0.4:
                    pool_level.tags.add('medium_volatility')
                else:
                    pool_level.tags.add('low_volatility')

                if self.add_level(pool_level):
                    imported += 1

        self.pool_reloaded.emit(len(self._levels))
        return imported

    # ==================== PERSISTENCE ====================

    def save(self, filepath: Optional[Path] = None) -> None:
        """Speichert den Pool in eine JSON-Datei"""
        if filepath is None:
            filepath = self._pool_file

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with QMutexLocker(self._mutex):
            data = {
                'version': '1.0',
                'saved_at': datetime.now().isoformat(),
                'levels': [level.to_dict() for level in self._levels.values()],
            }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self, filepath: Optional[Path] = None) -> int:
        """
        Lädt den Pool aus einer JSON-Datei

        Returns:
            Anzahl geladener Levels
        """
        if filepath is None:
            filepath = self._pool_file

        if not filepath.exists():
            return 0

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            levels_data = data.get('levels', [])

            with QMutexLocker(self._mutex):
                # Pool leeren
                self._levels.clear()
                self._by_symbol.clear()
                self._by_scenario.clear()
                for status in LevelPoolStatus:
                    self._by_status[status] = set()

            # Levels laden
            for level_data in levels_data:
                level = PoolLevel.from_dict(level_data)
                self.add_level(level)

            self.pool_reloaded.emit(len(self._levels))
            return len(self._levels)

        except Exception as e:
            print(f"Fehler beim Laden des Level-Pools: {e}")
            return 0

    def clear(self) -> None:
        """Leert den gesamten Pool"""
        with QMutexLocker(self._mutex):
            self._levels.clear()
            self._by_symbol.clear()
            self._by_scenario.clear()
            for status in LevelPoolStatus:
                self._by_status[status] = set()

        self.pool_reloaded.emit(0)

    # ==================== COOLDOWN MANAGEMENT ====================

    def check_cooldowns(self, cooldown_seconds: int = 60) -> int:
        """
        Prüft Cooldowns und setzt Levels wieder auf AVAILABLE

        Args:
            cooldown_seconds: Cooldown-Zeit in Sekunden

        Returns:
            Anzahl reaktivierter Levels
        """
        now = datetime.now()
        reactivated = 0

        with QMutexLocker(self._mutex):
            cooldown_ids = list(self._by_status.get(LevelPoolStatus.COOLDOWN, set()))

            for level_id in cooldown_ids:
                if level_id not in self._levels:
                    continue

                level = self._levels[level_id]
                if level.deactivated_at:
                    elapsed = (now - level.deactivated_at).total_seconds()
                    if elapsed >= cooldown_seconds:
                        # Cooldown abgelaufen
                        self._by_status[LevelPoolStatus.COOLDOWN].discard(level_id)
                        self._by_status[LevelPoolStatus.AVAILABLE].add(level_id)
                        level.status = LevelPoolStatus.AVAILABLE
                        reactivated += 1
                        self.level_updated.emit(level_id)

        return reactivated

    # ==================== CONVERSION FOR CONTROLLER ====================

    def to_controller_format(self) -> Dict[str, dict]:
        """
        Konvertiert den Pool in das Format für den Controller

        Returns:
            Dict[level_id, level_data]
        """
        with QMutexLocker(self._mutex):
            return {
                level_id: {
                    'level_id': level.level_id,
                    'scenario_name': level.scenario_name,
                    'symbol': level.symbol,
                    'side': level.side,
                    'level_num': level.level_num,
                    'entry_pct': level.entry_pct,
                    'exit_pct': level.exit_pct,
                    'entry_price': float(level.entry_price) if level.entry_price else None,
                    'exit_price': float(level.exit_price) if level.exit_price else None,
                    'shares': level.shares,
                    'status': level.status.value,
                    'success_rate': level.get_success_rate(),
                    'activation_count': level.activation_count,
                }
                for level_id, level in self._levels.items()
            }
