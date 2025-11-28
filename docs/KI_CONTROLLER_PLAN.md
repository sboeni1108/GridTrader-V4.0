# KI-Trading-Controller - Implementierungsplan

## Vision

Ein adaptiver, KI-gesteuerter Trading-Controller, der:
- **Echtzeit-Analyse**: Kursverlauf, Kerzengröße, Volumen kontinuierlich überwacht
- **Dynamische Level-Auswahl**: Einzelne Levels aus Szenarien intelligent aktiviert/deaktiviert
- **Trade-Management**: Laufende Trades stoppt, offene Positionen gewinnbringend schließt
- **Mustererkennung**: Historische Patterns mit aktueller Situation vergleicht
- **Vorausdenken**: Basierend auf historischen Daten und Mustern antizipiert

## Kernkonzept

Der Controller wählt **nicht** zwischen fertigen Szenarien, sondern:
1. Betrachtet alle verfügbaren Levels aus allen Szenarien als **Level-Pool**
2. Analysiert die aktuelle Marktsituation (ATR, Preis, Volumen, Tageszeit)
3. Vergleicht mit historischen Mustern ("Was passierte in ähnlichen Situationen?")
4. Wählt die **optimale Kombination** einzelner Long/Short Levels
5. Passt kontinuierlich an, wenn sich die Situation ändert

### Beispiel-Workflow
```
Situation: WULF @ $5.20, ATR letzte 10min: 0.8%
Historisches Muster: Ähnliche Situation am 15.11. um 10:30
Damals: Preis ging 0.5% runter, dann 0.3% rauf

ENTSCHEIDUNG: Aktiviere bei Startpreis $5.20:
- Long L1 ($5.15), L2 ($5.10), L3 ($5.05) → fängt Drop ab
- Short S1 ($5.25), S2 ($5.30) → falls Rebound überschießt

5 Minuten später: Preis bei $5.08, Volatilität sinkt
ANPASSUNG: Entferne L3, füge S3 ($5.35) hinzu
```

---

## Konfigurierte Entscheidungen

| Aspekt | Entscheidung |
|--------|-------------|
| Autonomie | Wählbar: Voll-autonom / Alert-Modus |
| News-Integration | Nicht jetzt, nur Architektur vorbereiten |
| Lernfähigkeit | Regelbasiert + Statistik, kein ML |
| Architektur | Separater Worker-Thread |
| Zeitrahmen | Solide (4-6 Wochen) |
| Testing | Paper-Trading zuerst |

### Priorität der Features
1. **A) Volatilitäts-basierte Level-Auswahl** (höchste Priorität)
2. **D) Tageszeit-Anpassung**
3. **E) Volumen-Anomalie Detection**
4. **B) Automatisches Stoppen von Trades**
5. **C) Schließen von Restpositionen bei Gewinn**

### Hard Limits (konfigurierbar)
- Max. Verlust pro Tag → alles stoppen
- Max. offene Positionen
- Max. Exposure pro Symbol
- Emergency Stop bei Black-Swan Events

---

## Architektur

```
┌─────────────────────────────────────────────────────────────────────┐
│                         GRIDTRADER APP                               │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │                    KI-CONTROLLER (Worker Thread)                │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐│ │
│  │  │   MONITOR    │ │   ANALYZER   │ │   DECISION ENGINE        ││ │
│  │  │              │ │              │ │                          ││ │
│  │  │ • Preis      │ │ • ATR Calc   │ │ • Level Scoring          ││ │
│  │  │ • Volumen    │ │ • Regime     │ │ • Optimale Kombination   ││ │
│  │  │ • Spread     │ │ • Pattern    │ │ • Vorausdenken           ││ │
│  │  │ • Kerzen     │ │   Matching   │ │ • Kontinuierliche        ││ │
│  │  │              │ │ • Tageszeit  │ │   Anpassung              ││ │
│  │  └──────┬───────┘ └──────┬───────┘ └────────────┬─────────────┘│ │
│  │         │                │                      │              │ │
│  │         ▼                ▼                      ▼              │ │
│  │  ┌─────────────────────────────────────────────────────────────┐  │ │
│  │  │                    RISK MANAGER                          │  │ │
│  │  │  • Hard Limits  • Soft Limits  • Emergency Stop          │  │ │
│  │  └─────────────────────────┬───────────────────────────────┘  │ │
│  │                            │                                   │ │
│  │                            ▼                                   │ │
│  │  ┌─────────────────────────────────────────────────────────┐  │ │
│  │  │                  EXECUTION MANAGER                       │  │ │
│  │  │  • activate_level()  • deactivate_level()               │  │ │
│  │  │  • stop_trade()      • close_position()                 │  │ │
│  │  └─────────────────────────┬───────────────────────────────┘  │ │
│  └────────────────────────────┼────────────────────────────────┘ │
│                               │                                   │
│                               ▼ CONTROLLER API                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                      TRADING-BOT                            │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │  │
│  │  │ LEVEL-POOL  │  │  SCENARIOS  │  │    IBKR SERVICE     │ │  │
│  │  │             │  │             │  │                     │ │  │
│  │  │ All Levels  │  │ Konfiguriert│  │ Orders, Positions   │ │  │
│  │  │ als Pool    │  │ vom User    │  │ Market Data         │ │  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Implementierungsphasen

### Phase 1: Foundation (Woche 1-2) ← AKTUELL

#### 1.1 Controller-Architektur
- [ ] `KIControllerThread` (Worker Thread)
- [ ] `ControllerAPI` (Schnittstelle zum Trading-Bot)
- [ ] `ConfigManager` (alle Parameter konfigurierbar)
- [ ] `StateManager` (aktueller Zustand, persistiert)

#### 1.2 Level-Pool System
- [ ] `LevelPool` Klasse (sammelt alle Levels aus allen Szenarien)
- [ ] Level-Status: `available`, `active`, `filled`, `closed`
- [ ] Dynamische Aktivierung/Deaktivierung einzelner Levels

#### 1.3 Basis-UI
- [ ] Neuer Tab "KI-Controller" in Main Window
- [ ] Ein/Aus Schalter (Autonom / Alert-Modus / Aus)
- [ ] Status-Anzeige (was macht der Controller gerade?)
- [ ] Konfigurationspanel (alle Parameter)

---

### Phase 2: Analyse-Engine (Woche 2-3)

#### 2.1 Echtzeit-Volatilitäts-Monitor
- [ ] Rolling ATR (1min, 5min, 15min)
- [ ] Kerzen-Range Tracking
- [ ] Volumen-Analyse
- [ ] Regime-Detection (hoch/mittel/niedrig)

#### 2.2 Tageszeit-Profil
- [ ] Morgen (09:30-10:30): Typisch hohe Volatilität
- [ ] Mittag (10:30-14:00): Typisch moderate Volatilität
- [ ] Nachmittag (14:00-16:00): Typisch niedrige Volatilität
- [ ] Anpassung basierend auf historischen Daten des Symbols

#### 2.3 Pattern Matcher
- [ ] Situations-Fingerprint erstellen (Preis, ATR, Volumen, Tageszeit)
- [ ] Ähnliche Situationen in historischen Daten finden
- [ ] "Was passierte danach?" analysieren
- [ ] Wahrscheinlichkeits-gewichtete Vorhersage

---

### Phase 3: Entscheidungs-Engine (Woche 3-4)

#### 3.1 Level-Auswahl-Algorithmus
- [ ] Input: Aktuelle Situation + Pattern-Vorhersage + verfügbare Levels
- [ ] Scoring: Jedes Level bekommt Score basierend auf:
  - Abstand zum aktuellen Preis
  - Erwartete Volatilität
  - Historische Erfolgsrate bei ähnlicher Situation
  - Risiko/Reward Verhältnis
- [ ] Optimierung: Wähle beste Kombination (Long + Short Balance)
- [ ] Output: Liste der zu aktivierenden Levels

#### 3.2 Kontinuierliche Anpassung
- [ ] Re-Evaluation alle X Sekunden (konfigurierbar, default 30s)
- [ ] "Sollte ich Levels hinzufügen?"
- [ ] "Sollte ich Levels entfernen?"
- [ ] "Hat sich die Situation fundamental geändert?"

#### 3.3 Vorausdenken (Prediction)
- [ ] "Wenn Preis Level X erreicht, was dann?"
- [ ] Vorbereitung von Aktionen für verschiedene Szenarien
- [ ] Schnelle Reaktion wenn Situation eintritt

---

### Phase 4: Risk Management & Execution (Woche 4-5)

#### 4.1 Risk Manager
- [ ] Hard Limits (Max Verlust, Max Position, Max Exposure)
- [ ] Soft Limits (Warnung bei Annäherung)
- [ ] Emergency Stop (alles schließen)
- [ ] Fail-Safe Watchdog

#### 4.2 Trade-Management
- [ ] Laufende Trades stoppen (wenn Situation sich ändert)
- [ ] Offene Positionen schließen bei Gewinn
- [ ] Verlust-Trades managen (halten vs. schließen)
- [ ] Kommunikation mit Trading-Bot via API

#### 4.3 Execution Manager
- [ ] Befehle an Trading-Bot senden
- [ ] Bestätigung abwarten
- [ ] Fehlerbehandlung
- [ ] Logging aller Aktionen

---

### Phase 5: Testing & Polish (Woche 5-6)

#### 5.1 Paper-Trading Modus
- [ ] Alle Entscheidungen loggen ohne echte Ausführung
- [ ] Performance-Tracking
- [ ] Vergleich: "Was hätte Controller gemacht?" vs "Was passierte?"
- [ ] Feintuning der Parameter

#### 5.2 Alert-Modus
- [ ] Controller schlägt vor, User bestätigt
- [ ] Notifications für kritische Entscheidungen
- [ ] Override-Möglichkeit

#### 5.3 Dokumentation & UI
- [ ] Vollständige Konfigurationsoberfläche
- [ ] Echtzeit-Visualisierung der Controller-Entscheidungen
- [ ] Historie: Was hat der Controller wann entschieden?
- [ ] Performance-Statistiken

---

## Wichtige Design-Prinzipien

### 1. Backtesting ≠ Live Trading
- Slippage von 0.02-0.05% annehmen
- Mindest-Wartezeit zwischen Entscheidungen
- Paper-Trading Modus zum Testen

### 2. Over-Trading Vermeiden
- Mindest-Haltezeit für Level-Kombinationen (konfigurierbar)
- Max. Wechsel pro Stunde (konfigurierbar)
- Kommissions-Impact in Entscheidung einbeziehen

### 3. Fail-Safe Architektur
```
ALWAYS-ON WATCHDOG (separater Thread):
├── Heartbeat alle 5 Sekunden
├── Wenn Trading-Bot nicht antwortet → ALLES STOPPEN
├── Wenn IBKR Verbindung verloren → ALERT + PAUSE
├── Wenn täglicher Verlust > Limit → HARD STOP
└── Wenn Position > Max → KEINE neuen Trades
```

---

## Dateistruktur (geplant)

```
src/gridtrader/
├── ki_controller/
│   ├── __init__.py
│   ├── controller_thread.py      # KIControllerThread
│   ├── controller_api.py         # Schnittstelle zum Trading-Bot
│   ├── config.py                 # ConfigManager
│   ├── state.py                  # StateManager
│   │
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── volatility_monitor.py # ATR, Regime Detection
│   │   ├── volume_analyzer.py    # Volumen-Anomalien
│   │   ├── time_profile.py       # Tageszeit-Profil
│   │   └── pattern_matcher.py    # Historische Muster
│   │
│   ├── decision/
│   │   ├── __init__.py
│   │   ├── level_scorer.py       # Level-Bewertung
│   │   ├── optimizer.py          # Optimale Kombination
│   │   └── predictor.py          # Vorausdenken
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── risk_manager.py       # Limits & Emergency
│   │   └── watchdog.py           # Fail-Safe
│   │
│   └── execution/
│       ├── __init__.py
│       └── execution_manager.py  # Befehle ausführen
│
├── ui/
│   └── widgets/
│       └── ki_controller_widget.py  # UI Tab
```

---

## Status-Tracking

| Phase | Status | Bemerkungen |
|-------|--------|-------------|
| Phase 1 | ✅ Abgeschlossen | Foundation - Grundstruktur, Level-Pool, UI |
| Phase 2 | ✅ Abgeschlossen | Analyse-Engine - ATR, Volatilität, Pattern |
| Phase 3 | ✅ Abgeschlossen | Entscheidungs-Engine - Scoring, Optimierung |
| Phase 4 | ✅ Abgeschlossen | Risk & Execution - Limits, Watchdog |
| Phase 5 | ✅ Abgeschlossen | Testing & Polish - Paper Trading, Stats |
| Integration | ✅ Abgeschlossen | IBKR, Orphan Positions, Bugfixes |
| Live-Daten | ✅ Abgeschlossen | Historische Daten, Level-Scores, Predictions |

### Phase 1 Ergebnisse

Folgende Komponenten wurden implementiert:

1. **KIControllerThread** (`controller_thread.py`)
   - Worker-Thread mit Haupt-Loop
   - Signal-basierte Kommunikation
   - Basis-Analyse und Entscheidungslogik
   - Anti-Overtrading Mechanismen

2. **Konfiguration** (`config.py`)
   - `KIControllerConfig` mit allen Sub-Konfigurationen
   - `RiskLimits` für Hard/Soft Limits
   - `DecisionConfig` für Entscheidungsparameter
   - `AlertConfig` für Alert-Modus
   - JSON-Persistierung

3. **State Management** (`state.py`)
   - `KIControllerState` für Laufzeit-Zustand
   - `MarketState` für Marktdaten pro Symbol
   - `ActiveLevelInfo` für aktive Levels
   - `DecisionRecord` für Entscheidungs-Historie

4. **Level-Pool** (`level_pool.py`)
   - `LevelPool` Klasse mit Thread-Safety
   - `PoolLevel` Datenstruktur
   - Import aus Trading-Bot Szenarien
   - Filterung und Statistiken

5. **Controller API** (`controller_api.py`)
   - `ControllerAPI` abstrakte Schnittstelle
   - `TradingBotAPIAdapter` konkrete Implementierung

6. **UI Widget** (`ki_controller_widget.py`)
   - Dashboard mit Status-Cards
   - Konfigurationspanel
   - Log-Ansicht
   - Alert-Bestätigung

---

## Waisen-Positionen (Orphan Positions)

Ein wichtiges Feature für das Trade-Management:

### Entstehung
Wenn ein **aktives Level** (mit offener Position) vom KI-Controller deaktiviert wird:
- Die Position wird NICHT automatisch geschlossen
- Stattdessen wird sie als "Waisen-Position" geführt
- Der KI-Controller überwacht diese Positionen separat

### Überwachung
- Alle Waisen-Positionen werden kontinuierlich auf Gewinn geprüft
- Konfigurierbare Mindest-Gewinn-Schwelle: **3 Cent pro Aktie** (default)
- Bei Erreichen der Schwelle: Position wird automatisch geschlossen

### Order-Typ
- Waisen-Positionen werden mit **LIMIT Orders** geschlossen (nicht MARKET)
- Der Limit-Preis ist der aktuelle Marktpreis zum Zeitpunkt der Schließung
- Dies gewährleistet bessere Ausführungspreise

### Anwendungsfall
```
Situation: KI-Controller hat Level L3 aktiviert, 100 Aktien @ $5.10 gekauft
Marktanalyse: Volatilität sinkt, Controller entscheidet L3 zu deaktivieren
→ Position wird Waise (100 Aktien @ $5.10)
Später: Preis steigt auf $5.15 (+5 Cent Gewinn pro Aktie)
→ KI-Controller schließt automatisch mit LIMIT SELL @ $5.15
```

---

## Historische Daten Integration

### Konfiguration
Die historischen Daten werden über `HistoricalDataConfig` konfiguriert:

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| history_days | 30 | Anzahl Tage historischer Daten |
| candle_size | "5min" | Kerzen-Größe (1min, 5min, 15min) |
| auto_load_on_start | True | Automatisch beim Start laden |
| min_candles_required | 100 | Mindest-Anzahl Kerzen für Analyse |
| cache_ttl_minutes | 60 | Cache-Gültigkeit in Minuten |

### Datenquellen
- **IBKR**: Live-Marktdaten von Interactive Brokers
- **BACKTEST**: Lokale/Test-Daten

### UI-Konfiguration
Im Config-Tab unter "Historische Daten":
- Eingabefeld für history_days
- Dropdown für candle_size
- Checkbox für auto_load_on_start
- Buttons: "Daten laden", "Cache leeren"
- Status-Anzeige mit Datenquelle, Zeitraum und Kerzen-Anzahl

---

## Level-Bewertungen und Vorhersagen

### Signal-Updates
Der Controller sendet zwei neue Signals für die UI-Visualisierung:

1. **level_scores_update** (list)
   - Enthält alle Level-Bewertungen mit Score-Breakdown
   - 8 Kategorien: price_proximity, volatility_fit, profit_potential, risk_reward, pattern_match, time_suitability, volume_context, trend_alignment
   - Status: ACTIVE, AVAILABLE, EXCLUDED

2. **predictions_update** (dict)
   - Preis-Vorhersagen für 4 Zeiträume (5min, 15min, 30min, 1h)
   - Jede Vorhersage enthält: direction, price_target, confidence
   - Overall-Bias: STRONG_UP, UP, NEUTRAL, DOWN, STRONG_DOWN

### Visualisierung
- **LevelScoreTable**: Tabelle mit allen Level-Scores und Breakdown
- **PredictionDisplay**: Richtungs-Anzeige mit Konfidenz-Balken
- **ScoreBars**: Markt-Kontext Faktoren (Volatilität, Volumen, Tageszeit, Pattern, Risiko)

---

*Letzte Aktualisierung: 2025-11-28*
