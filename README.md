# GridTrader V4.0

<div align="center">
  <h3>Professional Grid Trading Software mit IBKR Integration</h3>
  <p>Version mit funktionierenden Limit-Orders und angepasster Architektur</p>
</div>

---

## 🎯 Features

- ✅ **Multi-Symbol Grid Trading** (Long & Short parallel)
- ✅ **IBKR Integration** via TWS/Gateway API  
- ✅ **Umfassendes Backtesting** mit historischen Daten
- ✅ **Profit Guardian** System zum Schutz der Gewinne
- ✅ **Deutsche Excel-Reports** mit CH-Formatierung
- ✅ **Live Runtime-Edits** (Pause/Resume/Stop für jeden Zyklus)
- ✅ **Moderne PySide6 GUI** mit Live Cycle-Board
- ✅ **Clean Architecture** (Domain-Driven Design)

## 🏗️ Architektur
```
┌──────────────────────────────────────┐
│           UI Layer (PySide6)          │
├──────────────────────────────────────┤
│      Application Layer (Use Cases)    │
├──────────────────────────────────────┤
│       Domain Layer (Business Logic)   │
├──────────────────────────────────────┤
│    Infrastructure Layer (Adapters)    │
└──────────────────────────────────────┘
```

## 📋 System-Anforderungen

- **Python:** 3.11.9
- **OS:** Windows 10/11
- **Broker:** Interactive Brokers TWS oder IB Gateway
- **RAM:** Minimum 8GB
- **Speicher:** 500MB für Installation

## 🚀 Installation

### 1. Repository klonen
```bash
git clone https://github.com/sboeni1108/Gridtrader-V2.0.git
cd Gridtrader-V2.0
```

### 2. Virtual Environment einrichten
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

### 3. Dependencies installieren
```bash
pip install -r requirements.txt
```

### 4. Konfiguration
```bash
copy .env.example .env
# Bearbeite .env mit deinen IBKR Einstellungen
```

### 5. Datenbank initialisieren
```bash
python scripts/init_database.py
```

## 🎮 Verwendung

### GUI starten
```bash
python -m gridtrader.ui.main
```

### Tests ausführen
```bash
pytest tests/
```

## 📖 Dokumentation

- [User Guide](docs/user_guide/) - Benutzerhandbuch
- [API Docs](docs/api/) - Technische Dokumentation
- [Spezifikation](docs/Spezifikation.md) - Vollständige Projektspezifikation

## 🧪 Entwicklung

### Code-Formatierung
```bash
black src/ tests/
ruff check src/ tests/
```

### Type-Checking
```bash
mypy src/
```

## 📊 Projekt-Status

- [x] Projekt-Setup
- [ ] Domain Models
- [ ] Persistence Layer
- [ ] IBKR Integration
- [ ] Backtesting Engine
- [ ] GUI Implementation
- [ ] Testing & Documentation

## 📝 Lizenz

Proprietary - Alle Rechte vorbehalten

---

<div align="center">
  <p>GridTrader V2.0 © 2024</p>
</div>
