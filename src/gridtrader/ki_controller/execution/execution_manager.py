"""
Execution Manager

Verwaltet die Ausführung von Befehlen an den Trading-Bot:
- Level aktivieren/deaktivieren
- Trades stoppen
- Positionen schließen
- Emergency Stop
- Retry-Logik bei Fehlern
- Ausführungs-Queue
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable, List, Dict, Any, Tuple
from collections import deque
from threading import Lock
import uuid


class CommandType(str, Enum):
    """Arten von Befehlen"""
    ACTIVATE_LEVEL = "ACTIVATE_LEVEL"
    DEACTIVATE_LEVEL = "DEACTIVATE_LEVEL"
    STOP_TRADE = "STOP_TRADE"
    CLOSE_POSITION = "CLOSE_POSITION"
    MODIFY_LEVEL = "MODIFY_LEVEL"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class CommandStatus(str, Enum):
    """Status eines Befehls"""
    PENDING = "PENDING"          # Wartet auf Ausführung
    EXECUTING = "EXECUTING"      # Wird gerade ausgeführt
    COMPLETED = "COMPLETED"      # Erfolgreich abgeschlossen
    FAILED = "FAILED"            # Fehlgeschlagen
    RETRYING = "RETRYING"        # Retry läuft
    CANCELLED = "CANCELLED"      # Abgebrochen
    TIMEOUT = "TIMEOUT"          # Timeout


class ExecutionPriority(str, Enum):
    """Priorität von Befehlen"""
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"        # Sofort ausführen (Emergency)


@dataclass
class ExecutionCommand:
    """Ein auszuführender Befehl"""
    command_id: str
    command_type: CommandType
    priority: ExecutionPriority
    created_at: datetime
    payload: Dict[str, Any]

    # Ausführungs-Status
    status: CommandStatus = CommandStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Retry-Tracking
    attempt: int = 0
    max_attempts: int = 3
    last_error: str = ""

    # Timeout
    timeout_seconds: int = 30

    # Ergebnis
    result: Optional[Dict[str, Any]] = None
    success: bool = False

    def to_dict(self) -> dict:
        return {
            'command_id': self.command_id,
            'command_type': self.command_type.value,
            'priority': self.priority.value,
            'created_at': self.created_at.isoformat(),
            'status': self.status.value,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'attempt': self.attempt,
            'max_attempts': self.max_attempts,
            'last_error': self.last_error,
            'success': self.success,
            'payload': self.payload,
        }

    def is_expired(self) -> bool:
        """Prüft ob Befehl abgelaufen ist"""
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            return elapsed > self.timeout_seconds
        return False

    def can_retry(self) -> bool:
        """Prüft ob Retry möglich"""
        return self.attempt < self.max_attempts


@dataclass
class ExecutionStats:
    """Ausführungs-Statistiken"""
    total_commands: int = 0
    successful_commands: int = 0
    failed_commands: int = 0
    retried_commands: int = 0
    average_execution_time_ms: float = 0.0
    commands_per_minute: float = 0.0

    def to_dict(self) -> dict:
        return {
            'total_commands': self.total_commands,
            'successful_commands': self.successful_commands,
            'failed_commands': self.failed_commands,
            'retried_commands': self.retried_commands,
            'average_execution_time_ms': self.average_execution_time_ms,
            'commands_per_minute': self.commands_per_minute,
        }


class ExecutionManager:
    """
    Verwaltet die Ausführung von Trading-Befehlen.

    Features:
    - Prioritäts-basierte Ausführung
    - Retry bei Fehlern
    - Timeout-Handling
    - Command-Queue
    - Callback-basierte Ausführung
    """

    def __init__(
        self,
        max_queue_size: int = 100,
        default_timeout_sec: int = 30,
        default_max_retries: int = 3,
        retry_delay_sec: float = 1.0,
    ):
        self._max_queue_size = max_queue_size
        self._default_timeout = default_timeout_sec
        self._default_max_retries = default_max_retries
        self._retry_delay = retry_delay_sec

        # Command Queue (nach Priorität sortiert)
        self._queue: List[ExecutionCommand] = []
        self._lock = Lock()

        # History
        self._history: deque = deque(maxlen=1000)

        # Execution Handlers (Command Type -> Handler Function)
        self._handlers: Dict[CommandType, Callable[[Dict], Tuple[bool, str]]] = {}

        # Stats
        self._stats = ExecutionStats()
        self._execution_times: deque = deque(maxlen=100)
        self._command_timestamps: deque = deque(maxlen=100)

        # State
        self._paused = False
        self._emergency_mode = False

    # ==================== COMMAND CREATION ====================

    def create_command(
        self,
        command_type: CommandType,
        payload: Dict[str, Any],
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        timeout_sec: Optional[int] = None,
        max_retries: Optional[int] = None,
    ) -> ExecutionCommand:
        """Erstellt einen neuen Befehl"""
        return ExecutionCommand(
            command_id=str(uuid.uuid4())[:8],
            command_type=command_type,
            priority=priority,
            created_at=datetime.now(),
            payload=payload,
            timeout_seconds=timeout_sec or self._default_timeout,
            max_attempts=max_retries or self._default_max_retries,
        )

    def activate_level(
        self,
        level_id: str,
        level_data: Dict[str, Any],
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> str:
        """Erstellt Befehl zum Level-Aktivieren"""
        cmd = self.create_command(
            CommandType.ACTIVATE_LEVEL,
            {'level_id': level_id, **level_data},
            priority,
        )
        self.enqueue(cmd)
        return cmd.command_id

    def deactivate_level(
        self,
        level_id: str,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> str:
        """Erstellt Befehl zum Level-Deaktivieren"""
        cmd = self.create_command(
            CommandType.DEACTIVATE_LEVEL,
            {'level_id': level_id},
            priority,
        )
        self.enqueue(cmd)
        return cmd.command_id

    def stop_trade(
        self,
        level_id: str,
        reason: str = "",
        priority: ExecutionPriority = ExecutionPriority.HIGH,
    ) -> str:
        """Erstellt Befehl zum Trade-Stoppen"""
        cmd = self.create_command(
            CommandType.STOP_TRADE,
            {'level_id': level_id, 'reason': reason},
            priority,
        )
        self.enqueue(cmd)
        return cmd.command_id

    def close_position(
        self,
        symbol: str,
        quantity: int,
        reason: str = "",
        priority: ExecutionPriority = ExecutionPriority.HIGH,
    ) -> str:
        """Erstellt Befehl zum Positions-Schließen"""
        cmd = self.create_command(
            CommandType.CLOSE_POSITION,
            {'symbol': symbol, 'quantity': quantity, 'reason': reason},
            priority,
        )
        self.enqueue(cmd)
        return cmd.command_id

    def emergency_stop(self, reason: str = "Emergency Stop") -> str:
        """Erstellt Emergency-Stop Befehl"""
        self._emergency_mode = True

        cmd = self.create_command(
            CommandType.EMERGENCY_STOP,
            {'reason': reason, 'timestamp': datetime.now().isoformat()},
            ExecutionPriority.CRITICAL,
            timeout_sec=5,  # Kurzer Timeout
            max_retries=1,  # Kein Retry
        )

        # Emergency kommt an den Anfang der Queue
        with self._lock:
            self._queue.insert(0, cmd)

        return cmd.command_id

    # ==================== QUEUE MANAGEMENT ====================

    def enqueue(self, command: ExecutionCommand) -> bool:
        """
        Fügt Befehl zur Queue hinzu.

        Returns:
            True wenn erfolgreich, False wenn Queue voll
        """
        with self._lock:
            if len(self._queue) >= self._max_queue_size:
                # Bei voller Queue: Niedrig-priorisierte Befehle entfernen
                low_priority = [
                    c for c in self._queue
                    if c.priority == ExecutionPriority.LOW
                ]
                if low_priority:
                    self._queue.remove(low_priority[0])
                else:
                    return False

            self._queue.append(command)
            self._sort_queue()
            return True

    def _sort_queue(self):
        """Sortiert Queue nach Priorität"""
        priority_order = {
            ExecutionPriority.CRITICAL: 0,
            ExecutionPriority.HIGH: 1,
            ExecutionPriority.NORMAL: 2,
            ExecutionPriority.LOW: 3,
        }
        self._queue.sort(key=lambda c: (priority_order[c.priority], c.created_at))

    def get_next_command(self) -> Optional[ExecutionCommand]:
        """Holt nächsten Befehl aus der Queue"""
        with self._lock:
            if self._paused and not self._emergency_mode:
                return None

            if not self._queue:
                return None

            # Bei Emergency: Nur Emergency-Befehle
            if self._emergency_mode:
                for cmd in self._queue:
                    if cmd.command_type == CommandType.EMERGENCY_STOP:
                        self._queue.remove(cmd)
                        return cmd
                return None

            return self._queue.pop(0)

    def cancel_command(self, command_id: str) -> bool:
        """Bricht einen Befehl ab"""
        with self._lock:
            for cmd in self._queue:
                if cmd.command_id == command_id:
                    cmd.status = CommandStatus.CANCELLED
                    self._queue.remove(cmd)
                    self._history.append(cmd)
                    return True
        return False

    def clear_queue(self, keep_critical: bool = True):
        """Leert die Queue"""
        with self._lock:
            if keep_critical:
                self._queue = [
                    c for c in self._queue
                    if c.priority == ExecutionPriority.CRITICAL
                ]
            else:
                self._queue.clear()

    # ==================== EXECUTION ====================

    def execute_next(self) -> Optional[ExecutionCommand]:
        """
        Führt den nächsten Befehl aus.

        Returns:
            Der ausgeführte Befehl oder None
        """
        cmd = self.get_next_command()
        if not cmd:
            return None

        return self.execute_command(cmd)

    def execute_command(self, cmd: ExecutionCommand) -> ExecutionCommand:
        """
        Führt einen einzelnen Befehl aus.

        Returns:
            Der aktualisierte Befehl
        """
        cmd.status = CommandStatus.EXECUTING
        cmd.started_at = datetime.now()
        cmd.attempt += 1

        try:
            # Handler für diesen Command-Typ finden
            handler = self._handlers.get(cmd.command_type)

            if not handler:
                cmd.status = CommandStatus.FAILED
                cmd.last_error = f"Kein Handler für {cmd.command_type.value}"
                cmd.success = False
            else:
                # Handler ausführen
                success, message = handler(cmd.payload)

                if success:
                    cmd.status = CommandStatus.COMPLETED
                    cmd.success = True
                    cmd.result = {'message': message}
                    self._stats.successful_commands += 1
                else:
                    # Fehlgeschlagen - Retry?
                    if cmd.can_retry():
                        cmd.status = CommandStatus.RETRYING
                        cmd.last_error = message
                        self._stats.retried_commands += 1
                        # Wieder in Queue einreihen
                        self.enqueue(cmd)
                        return cmd
                    else:
                        cmd.status = CommandStatus.FAILED
                        cmd.last_error = message
                        cmd.success = False
                        self._stats.failed_commands += 1

        except Exception as e:
            cmd.last_error = str(e)

            if cmd.can_retry():
                cmd.status = CommandStatus.RETRYING
                self._stats.retried_commands += 1
                self.enqueue(cmd)
                return cmd
            else:
                cmd.status = CommandStatus.FAILED
                cmd.success = False
                self._stats.failed_commands += 1

        # Abschluss
        cmd.completed_at = datetime.now()
        self._stats.total_commands += 1

        # Execution Time tracking
        if cmd.started_at:
            exec_time = (cmd.completed_at - cmd.started_at).total_seconds() * 1000
            self._execution_times.append(exec_time)

        self._command_timestamps.append(datetime.now())
        self._history.append(cmd)

        return cmd

    def execute_all_pending(self) -> List[ExecutionCommand]:
        """Führt alle wartenden Befehle aus"""
        results = []
        while True:
            cmd = self.execute_next()
            if not cmd:
                break
            results.append(cmd)
        return results

    # ==================== HANDLERS ====================

    def register_handler(
        self,
        command_type: CommandType,
        handler: Callable[[Dict], Tuple[bool, str]]
    ):
        """
        Registriert einen Handler für einen Command-Typ.

        Handler Signatur: (payload: Dict) -> (success: bool, message: str)
        """
        self._handlers[command_type] = handler

    def unregister_handler(self, command_type: CommandType):
        """Entfernt einen Handler"""
        if command_type in self._handlers:
            del self._handlers[command_type]

    # ==================== STATE ====================

    def pause(self):
        """Pausiert die Ausführung"""
        self._paused = True

    def resume(self):
        """Setzt die Ausführung fort"""
        self._paused = False

    def enter_emergency_mode(self):
        """Aktiviert Emergency-Modus"""
        self._emergency_mode = True

    def exit_emergency_mode(self):
        """Beendet Emergency-Modus"""
        self._emergency_mode = False

    def is_paused(self) -> bool:
        """Prüft ob pausiert"""
        return self._paused

    def is_emergency(self) -> bool:
        """Prüft ob Emergency-Modus aktiv"""
        return self._emergency_mode

    # ==================== STATS & INFO ====================

    def get_queue_length(self) -> int:
        """Gibt Anzahl wartender Befehle zurück"""
        return len(self._queue)

    def get_pending_commands(self) -> List[ExecutionCommand]:
        """Gibt wartende Befehle zurück"""
        with self._lock:
            return list(self._queue)

    def get_stats(self) -> ExecutionStats:
        """Gibt Ausführungs-Statistiken zurück"""
        # Durchschnittliche Ausführungszeit berechnen
        if self._execution_times:
            self._stats.average_execution_time_ms = (
                sum(self._execution_times) / len(self._execution_times)
            )

        # Commands pro Minute berechnen
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        recent_commands = [
            t for t in self._command_timestamps
            if t > minute_ago
        ]
        self._stats.commands_per_minute = len(recent_commands)

        return self._stats

    def get_recent_history(self, count: int = 20) -> List[ExecutionCommand]:
        """Gibt letzte ausgeführte Befehle zurück"""
        return list(self._history)[-count:]

    def get_command_status(self, command_id: str) -> Optional[CommandStatus]:
        """Gibt Status eines Befehls zurück"""
        # In Queue suchen
        with self._lock:
            for cmd in self._queue:
                if cmd.command_id == command_id:
                    return cmd.status

        # In History suchen
        for cmd in self._history:
            if cmd.command_id == command_id:
                return cmd.status

        return None
