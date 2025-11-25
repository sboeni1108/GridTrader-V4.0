"""
IBKR Connection Dialog - Auswahl von API-Typ und Trading-Modus
"""
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, Signal, QTimer
from dataclasses import dataclass
from typing import Optional


@dataclass
class IBKRConnectionSettings:
    """Settings für IBKR Verbindung"""
    api_type: str  # "TWS" oder "GATEWAY"
    mode: str  # "PAPER" oder "LIVE"
    host: str = "127.0.0.1"
    port: int = 7497  # Default Paper TWS
    client_id: int = 1
    username: Optional[str] = None
    account: Optional[str] = None
    
    def get_port(self) -> int:
        """Bestimmt Port basierend auf Einstellungen"""
        if self.api_type == "TWS":
            return 7497 if self.mode == "PAPER" else 7496
        else:  # GATEWAY
            return 4002 if self.mode == "PAPER" else 4001


class IBKRConnectionDialog(QDialog):
    """Dialog für IBKR Verbindungseinstellungen"""
    
    connection_requested = Signal(object)  # Sendet IBKRConnectionSettings
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IBKR Verbindung konfigurieren")
        self.setModal(True)
        self.setMinimumWidth(500)
        
        self._setup_ui()
        
    def _setup_ui(self):
        """UI Setup"""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("🏦 Interactive Brokers Verbindung")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # API Type Selection
        api_group = QGroupBox("API Typ auswählen")
        api_layout = QVBoxLayout()
        
        self.tws_radio = QRadioButton("TWS (Trader Workstation)")
        self.tws_radio.setChecked(True)
        self.tws_radio.toggled.connect(self._update_port)
        api_layout.addWidget(self.tws_radio)
        
        self.gateway_radio = QRadioButton("IB Gateway")
        self.gateway_radio.toggled.connect(self._update_port)
        api_layout.addWidget(self.gateway_radio)
        
        api_info = QLabel("ℹ️ TWS: Vollständige Trading-Plattform mit UI\n"
                         "ℹ️ Gateway: Minimale Ressourcen, nur API")
        api_info.setStyleSheet("color: gray; font-size: 11px; padding: 5px;")
        api_layout.addWidget(api_info)
        
        api_group.setLayout(api_layout)
        layout.addWidget(api_group)
        
        # Trading Mode Selection
        mode_group = QGroupBox("Trading Modus")
        mode_layout = QVBoxLayout()
        
        self.paper_radio = QRadioButton("📝 Paper Trading (Simulated)")
        self.paper_radio.setChecked(True)
        self.paper_radio.toggled.connect(self._update_port)
        mode_layout.addWidget(self.paper_radio)
        
        self.live_radio = QRadioButton("💰 Live Trading (Real Money)")
        self.live_radio.toggled.connect(self._update_port)
        mode_layout.addWidget(self.live_radio)
        
        # Warning for Live Trading
        self.warning_label = QLabel("⚠️ WARNUNG: Live Trading verwendet echtes Geld!")
        self.warning_label.setStyleSheet("color: red; font-weight: bold; padding: 5px;")
        self.warning_label.setVisible(False)
        mode_layout.addWidget(self.warning_label)
        
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        # Connection Settings
        settings_group = QGroupBox("Verbindungseinstellungen")
        settings_layout = QGridLayout()
        
        # Host
        settings_layout.addWidget(QLabel("Host:"), 0, 0)
        self.host_input = QLineEdit("127.0.0.1")
        settings_layout.addWidget(self.host_input, 0, 1)
        
        # Port
        settings_layout.addWidget(QLabel("Port:"), 1, 0)
        self.port_input = QSpinBox()
        self.port_input.setRange(1000, 9999)
        self.port_input.setValue(7497)
        settings_layout.addWidget(self.port_input, 1, 1)
        
        # Client ID
        settings_layout.addWidget(QLabel("Client ID:"), 2, 0)
        self.client_id_input = QSpinBox()
        self.client_id_input.setRange(0, 999)
        # Client ID standardmässig auf 1
        self.client_id_input.setValue(1)
        settings_layout.addWidget(self.client_id_input, 2, 1)
        
        # Account (optional)
        settings_layout.addWidget(QLabel("Account (optional):"), 3, 0)
        self.account_input = QLineEdit()
        self.account_input.setPlaceholderText("Leave empty for auto-detection")
        settings_layout.addWidget(self.account_input, 3, 1)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # Status Check
        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Nicht verbunden")
        self.status_label.setStyleSheet("padding: 5px;")
        status_layout.addWidget(self.status_label)
        
        self.test_button = QPushButton("🔍 Verbindung testen")
        self.test_button.clicked.connect(self._test_connection)
        status_layout.addWidget(self.test_button)
        
        layout.addLayout(status_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.connect_button = QPushButton("🔌 Verbinden")
        self.connect_button.clicked.connect(self._connect)
        button_layout.addWidget(self.connect_button)
        
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
    
    def _update_port(self):
        """Update Port basierend auf Auswahl"""
        api_type = "TWS" if self.tws_radio.isChecked() else "GATEWAY"
        mode = "PAPER" if self.paper_radio.isChecked() else "LIVE"
        
        settings = IBKRConnectionSettings(api_type=api_type, mode=mode)
        self.port_input.setValue(settings.get_port())
        
        # Show/Hide warning
        self.warning_label.setVisible(mode == "LIVE")
    
    def _test_connection(self):
        """Test die Verbindung"""
        self.status_label.setText("Status: Teste Verbindung...")
        
        settings = self._get_settings()
        
        # Hier würde der echte Test kommen
        # Für Demo: Simuliere Test
        QTimer.singleShot(1000, lambda: self._show_test_result(True))
    
    def _show_test_result(self, success):
        """Zeige Test-Ergebnis"""
        if success:
            self.status_label.setText("✅ Verbindung erfolgreich!")
            self.status_label.setStyleSheet("color: green; padding: 5px;")
        else:
            self.status_label.setText("❌ Verbindung fehlgeschlagen!")
            self.status_label.setStyleSheet("color: red; padding: 5px;")
    
    def _connect(self):
        """Verbinde mit IBKR"""
        settings = self._get_settings()
        
        # Bei Live Trading - Extra Warnung
        if settings.mode == "LIVE":
            reply = QMessageBox.warning(
                self,
                "Live Trading Warnung",
                "Sie sind dabei, eine Verbindung zum LIVE Trading herzustellen!\n\n"
                "Dies wird ECHTES GELD verwenden.\n\n"
                "Sind Sie sicher?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
        
        self.connection_requested.emit(settings)
        self.accept()
    
    def _get_settings(self) -> IBKRConnectionSettings:
        """Hole aktuelle Settings"""
        return IBKRConnectionSettings(
            api_type="TWS" if self.tws_radio.isChecked() else "GATEWAY",
            mode="PAPER" if self.paper_radio.isChecked() else "LIVE",
            host=self.host_input.text(),
            port=self.port_input.value(),
            client_id=self.client_id_input.value(),
            account=self.account_input.text() if self.account_input.text() else None
        )
