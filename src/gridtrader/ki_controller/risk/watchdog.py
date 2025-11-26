"""
Watchdog

Fail-Safe Überwachung des KI-Controllers:
- Heartbeat Monitoring (Controller läuft noch?)
- Connection Monitoring (Broker-Verbindung aktiv?)
- State Consistency Checks (Daten konsistent?)
- Auto-Recovery (Neustart bei Problemen)
- Dead-Man-Switch (Notfall bei komplettem Ausfall)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable, List, Dict, Any
from threading import Timer, Lock
import time


class WatchdogStatus(str, Enum):
    """Status des Watchdogs"""
    INACTIVE = "INACTIVE"      # Watchdog nicht aktiv
    MONITORING = "MONITORING"  # Normal überwachend
    WARNING = "WARNING"        # Problem erkannt
    ALERT = "ALERT"           # Kritisches Problem
    TRIGGERED = "TRIGGERED"    # Notfall ausgelöst


class HealthCheckResult(str, Enum):
    """Ergebnis eines Health Checks"""
    OK = "OK"
    WARNING = "WARNING"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


@dataclass
class HealthStatus:
    """Gesundheitsstatus einer Komponente"""
    component: str
    status: HealthCheckResult
    last_check: datetime
    message: str = ""
    response_time_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            'component': self.component,
            'status': self.status.value,
            'last_check': self.last_check.isoformat(),
            'message': self.message,
            'response_time_ms': self.response_time_ms,
        }


@dataclass
class WatchdogState:
    """Aktueller Zustand des Watchdogs"""
    status: WatchdogStatus = WatchdogStatus.INACTIVE
    last_heartbeat: Optional[datetime] = None
    heartbeat_count: int = 0
    missed_heartbeats: int = 0
    last_health_check: Optional[datetime] = None
    health_results: Dict[str, HealthStatus] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)
    recovery_attempts: int = 0

    def to_dict(self) -> dict:
        return {
            'status': self.status.value,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'heartbeat_count': self.heartbeat_count,
            'missed_heartbeats': self.missed_heartbeats,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'health_results': {k: v.to_dict() for k, v in self.health_results.items()},
            'alerts': self.alerts,
            'recovery_attempts': self.recovery_attempts,
        }


class Watchdog:
    """
    Fail-Safe Überwachungssystem.

    Überwacht:
    1. Heartbeat des Controllers (läuft er noch?)
    2. Broker-Verbindung (können wir handeln?)
    3. Daten-Konsistenz (stimmen die Zahlen?)
    4. System-Ressourcen (genug Speicher?)

    Reagiert auf Probleme:
    - Warnung bei ersten Anzeichen
    - Auto-Recovery bei kurzen Ausfällen
    - Emergency Stop bei kritischen Problemen
    """

    def __init__(
        self,
        heartbeat_interval_sec: int = 5,
        heartbeat_timeout_sec: int = 30,
        health_check_interval_sec: int = 60,
        max_recovery_attempts: int = 3,
    ):
        self._heartbeat_interval = heartbeat_interval_sec
        self._heartbeat_timeout = heartbeat_timeout_sec
        self._health_check_interval = health_check_interval_sec
        self._max_recovery_attempts = max_recovery_attempts

        # State
        self._state = WatchdogState()
        self._lock = Lock()
        self._active = False

        # Timers
        self._heartbeat_timer: Optional[Timer] = None
        self._health_check_timer: Optional[Timer] = None

        # Callbacks
        self._on_warning: Optional[Callable[[str], None]] = None
        self._on_alert: Optional[Callable[[str], None]] = None
        self._on_emergency: Optional[Callable[[str], None]] = None
        self._on_recovery_needed: Optional[Callable[[], bool]] = None

        # Health Check Funktionen
        self._health_checks: Dict[str, Callable[[], HealthCheckResult]] = {}

        # Expected heartbeat time
        self._expected_heartbeat: Optional[datetime] = None

    # ==================== LIFECYCLE ====================

    def start(self):
        """Startet den Watchdog"""
        with self._lock:
            if self._active:
                return

            self._active = True
            self._state.status = WatchdogStatus.MONITORING
            self._state.last_heartbeat = datetime.now()
            self._expected_heartbeat = datetime.now() + timedelta(seconds=self._heartbeat_interval)

            # Timer starten
            self._start_heartbeat_timer()
            self._start_health_check_timer()

    def stop(self):
        """Stoppt den Watchdog"""
        with self._lock:
            self._active = False
            self._state.status = WatchdogStatus.INACTIVE

            # Timer stoppen
            if self._heartbeat_timer:
                self._heartbeat_timer.cancel()
                self._heartbeat_timer = None

            if self._health_check_timer:
                self._health_check_timer.cancel()
                self._health_check_timer = None

    def receive_heartbeat(self):
        """
        Empfängt einen Heartbeat vom Controller.

        Diese Methode muss regelmäßig vom Controller aufgerufen werden.
        """
        with self._lock:
            now = datetime.now()
            self._state.last_heartbeat = now
            self._state.heartbeat_count += 1
            self._state.missed_heartbeats = 0
            self._expected_heartbeat = now + timedelta(seconds=self._heartbeat_interval)

            # Zurück zu Normal wenn vorher Warning
            if self._state.status == WatchdogStatus.WARNING:
                self._state.status = WatchdogStatus.MONITORING
                self._state.recovery_attempts = 0

    # ==================== HEARTBEAT MONITORING ====================

    def _start_heartbeat_timer(self):
        """Startet den Heartbeat-Check Timer"""
        if not self._active:
            return

        self._heartbeat_timer = Timer(
            self._heartbeat_interval,
            self._check_heartbeat
        )
        self._heartbeat_timer.daemon = True
        self._heartbeat_timer.start()

    def _check_heartbeat(self):
        """Prüft ob Heartbeat rechtzeitig kam"""
        if not self._active:
            return

        with self._lock:
            now = datetime.now()
            last = self._state.last_heartbeat

            if last is None:
                self._handle_missed_heartbeat("Kein Heartbeat empfangen")
            else:
                elapsed = (now - last).total_seconds()

                if elapsed > self._heartbeat_timeout:
                    self._handle_missed_heartbeat(
                        f"Heartbeat Timeout: {elapsed:.0f}s seit letztem Heartbeat"
                    )
                elif elapsed > self._heartbeat_interval * 2:
                    self._state.missed_heartbeats += 1
                    self._handle_warning(
                        f"Heartbeat verspätet: {elapsed:.0f}s (erwartet: {self._heartbeat_interval}s)"
                    )

        # Timer neu starten
        self._start_heartbeat_timer()

    def _handle_missed_heartbeat(self, reason: str):
        """Behandelt fehlenden Heartbeat"""
        self._state.missed_heartbeats += 1

        if self._state.missed_heartbeats >= 3:
            # Kritisch - versuche Recovery
            if self._state.recovery_attempts < self._max_recovery_attempts:
                self._attempt_recovery(reason)
            else:
                self._trigger_emergency(f"Heartbeat verloren nach {self._max_recovery_attempts} Recovery-Versuchen: {reason}")
        else:
            self._handle_warning(reason)

    def _attempt_recovery(self, reason: str):
        """Versucht automatische Recovery"""
        self._state.status = WatchdogStatus.ALERT
        self._state.recovery_attempts += 1
        self._state.alerts.append(f"{datetime.now().isoformat()}: Recovery-Versuch {self._state.recovery_attempts}: {reason}")

        if self._on_recovery_needed:
            try:
                success = self._on_recovery_needed()
                if success:
                    self._state.status = WatchdogStatus.MONITORING
                    self._state.missed_heartbeats = 0
                else:
                    self._handle_warning(f"Recovery fehlgeschlagen: {reason}")
            except Exception as e:
                self._handle_warning(f"Recovery-Fehler: {e}")

    def _trigger_emergency(self, reason: str):
        """Löst Emergency aus"""
        self._state.status = WatchdogStatus.TRIGGERED
        self._state.alerts.append(f"{datetime.now().isoformat()}: EMERGENCY: {reason}")

        if self._on_emergency:
            self._on_emergency(reason)

    def _handle_warning(self, message: str):
        """Behandelt eine Warnung"""
        if self._state.status == WatchdogStatus.MONITORING:
            self._state.status = WatchdogStatus.WARNING

        if len(self._state.alerts) < 100:  # Limit alerts
            self._state.alerts.append(f"{datetime.now().isoformat()}: WARNING: {message}")

        if self._on_warning:
            self._on_warning(message)

    # ==================== HEALTH CHECKS ====================

    def _start_health_check_timer(self):
        """Startet den Health-Check Timer"""
        if not self._active:
            return

        self._health_check_timer = Timer(
            self._health_check_interval,
            self._run_health_checks
        )
        self._health_check_timer.daemon = True
        self._health_check_timer.start()

    def _run_health_checks(self):
        """Führt alle registrierten Health Checks durch"""
        if not self._active:
            return

        with self._lock:
            self._state.last_health_check = datetime.now()
            failed_checks = []

            for name, check_func in self._health_checks.items():
                start_time = time.time()
                try:
                    result = check_func()
                    response_time = (time.time() - start_time) * 1000

                    self._state.health_results[name] = HealthStatus(
                        component=name,
                        status=result,
                        last_check=datetime.now(),
                        response_time_ms=response_time,
                    )

                    if result == HealthCheckResult.FAILED:
                        failed_checks.append(name)

                except Exception as e:
                    self._state.health_results[name] = HealthStatus(
                        component=name,
                        status=HealthCheckResult.FAILED,
                        last_check=datetime.now(),
                        message=str(e),
                    )
                    failed_checks.append(name)

            # Warnung bei fehlgeschlagenen Checks
            if failed_checks:
                self._handle_warning(f"Health Checks fehlgeschlagen: {', '.join(failed_checks)}")

        # Timer neu starten
        self._start_health_check_timer()

    def register_health_check(
        self,
        name: str,
        check_func: Callable[[], HealthCheckResult]
    ):
        """Registriert einen Health Check"""
        self._health_checks[name] = check_func

    def unregister_health_check(self, name: str):
        """Entfernt einen Health Check"""
        if name in self._health_checks:
            del self._health_checks[name]

    # ==================== CALLBACKS ====================

    def set_on_warning(self, callback: Callable[[str], None]):
        """Setzt Callback für Warnungen"""
        self._on_warning = callback

    def set_on_alert(self, callback: Callable[[str], None]):
        """Setzt Callback für Alerts"""
        self._on_alert = callback

    def set_on_emergency(self, callback: Callable[[str], None]):
        """Setzt Callback für Emergency"""
        self._on_emergency = callback

    def set_on_recovery_needed(self, callback: Callable[[], bool]):
        """
        Setzt Callback für Recovery-Versuche.

        Der Callback sollte True zurückgeben wenn Recovery erfolgreich.
        """
        self._on_recovery_needed = callback

    # ==================== STATUS ====================

    def get_status(self) -> WatchdogStatus:
        """Gibt aktuellen Status zurück"""
        return self._state.status

    def get_state(self) -> WatchdogState:
        """Gibt vollständigen State zurück"""
        return self._state

    def is_healthy(self) -> bool:
        """Prüft ob System als gesund gilt"""
        return self._state.status in (WatchdogStatus.INACTIVE, WatchdogStatus.MONITORING)

    def get_seconds_since_heartbeat(self) -> float:
        """Gibt Sekunden seit letztem Heartbeat zurück"""
        if self._state.last_heartbeat is None:
            return float('inf')
        return (datetime.now() - self._state.last_heartbeat).total_seconds()

    def reset(self):
        """Setzt Watchdog zurück"""
        with self._lock:
            self._state = WatchdogState()
            if self._active:
                self._state.status = WatchdogStatus.MONITORING


# ==================== VORDEFINIERTE HEALTH CHECKS ====================

def create_connection_check(check_func: Callable[[], bool]) -> Callable[[], HealthCheckResult]:
    """Erstellt einen Verbindungs-Check"""
    def check() -> HealthCheckResult:
        try:
            if check_func():
                return HealthCheckResult.OK
            return HealthCheckResult.FAILED
        except Exception:
            return HealthCheckResult.FAILED
    return check


def create_memory_check(max_memory_mb: int = 1024) -> Callable[[], HealthCheckResult]:
    """Erstellt einen Speicher-Check"""
    def check() -> HealthCheckResult:
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024

            if memory_mb > max_memory_mb:
                return HealthCheckResult.FAILED
            elif memory_mb > max_memory_mb * 0.8:
                return HealthCheckResult.WARNING
            return HealthCheckResult.OK
        except ImportError:
            return HealthCheckResult.OK  # psutil nicht verfügbar
        except Exception:
            return HealthCheckResult.WARNING
    return check


def create_data_freshness_check(
    get_last_update: Callable[[], Optional[datetime]],
    max_age_seconds: int = 60
) -> Callable[[], HealthCheckResult]:
    """Erstellt einen Daten-Aktualitäts-Check"""
    def check() -> HealthCheckResult:
        try:
            last_update = get_last_update()
            if last_update is None:
                return HealthCheckResult.WARNING

            age = (datetime.now() - last_update).total_seconds()

            if age > max_age_seconds * 2:
                return HealthCheckResult.FAILED
            elif age > max_age_seconds:
                return HealthCheckResult.WARNING
            return HealthCheckResult.OK
        except Exception:
            return HealthCheckResult.FAILED
    return check
