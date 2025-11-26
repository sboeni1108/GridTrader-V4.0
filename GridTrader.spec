# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec-Datei für GridTrader V4.0
Erstellt eine standalone Windows-EXE mit allen Abhängigkeiten.

Verwendung:
    pyinstaller GridTrader.spec

oder für einen sauberen Build:
    pyinstaller --clean GridTrader.spec
"""

import sys
from pathlib import Path

# Block cipher für Verschlüsselung (optional, None = keine Verschlüsselung)
block_cipher = None

# Projektpfad
PROJECT_ROOT = Path(SPECPATH)
SRC_PATH = PROJECT_ROOT / 'src'

# Hidden Imports - Module die PyInstaller nicht automatisch erkennt
hidden_imports = [
    # PySide6 / Qt
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtSql',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',

    # Interactive Brokers
    'ib_insync',
    'ib_insync.wrapper',
    'ib_insync.client',
    'ib_insync.contract',
    'ib_insync.order',
    'ib_insync.ticker',
    'ib_insync.objects',
    'ib_insync.util',
    'ib_insync.event',
    'ib_insync.flexreport',

    # Async Support (KRITISCH für Windows!)
    'nest_asyncio',
    'asyncio',
    'aiofiles',

    # Datenbank
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.sql.default_comparator',
    'sqlalchemy.ext.asyncio',
    'sqlmodel',
    'alembic',

    # Data Science
    'numpy',
    'numpy.lib.format',
    'pandas',
    'pandas.plotting',
    'pandas.io.formats.style',
    'scipy',
    'scipy.special',
    'scipy.stats',

    # Konfiguration & Validierung
    'pydantic',
    'pydantic.deprecated',
    'pydantic_settings',
    'pydantic_core',
    'dotenv',
    'yaml',

    # Excel & Reports
    'openpyxl',
    'openpyxl.styles',
    'openpyxl.utils',
    'openpyxl.workbook',
    'openpyxl.worksheet',
    'xlsxwriter',
    'jinja2',
    'reportlab',
    'reportlab.lib',
    'reportlab.lib.styles',
    'reportlab.lib.units',
    'reportlab.platypus',
    'reportlab.pdfgen',

    # Marktdaten
    'yfinance',

    # Utilities
    'pytz',
    'dateutil',
    'dateutil.parser',
    'dateutil.tz',
    'colorlog',
    'rich',
    'click',

    # Eigene Module (GridTrader)
    'gridtrader',
    'gridtrader.ui',
    'gridtrader.ui.app',
    'gridtrader.ui.main_window',
    'gridtrader.ui.styles',
    'gridtrader.ui.widgets',
    'gridtrader.ui.views',
    'gridtrader.ui.dialogs',
    'gridtrader.ui.viewmodels',
    'gridtrader.domain',
    'gridtrader.domain.models',
    'gridtrader.domain.services',
    'gridtrader.application',
    'gridtrader.infrastructure',
    'gridtrader.infrastructure.brokers',
    'gridtrader.infrastructure.brokers.ibkr',
    'gridtrader.infrastructure.persistence',
    'gridtrader.infrastructure.reports',
    'gridtrader.cli',
]

# Module die ausgeschlossen werden sollen (Development/Testing)
excludes = [
    'pytest',
    'pytest_asyncio',
    'pytest_cov',
    'pytest_mock',
    'pytest_qt',
    'faker',
    'black',
    'ruff',
    'mypy',
    'pre_commit',
    'ipython',
    'ipdb',
    'matplotlib',  # Falls nicht benötigt
    'tkinter',     # Nicht benötigt bei PySide6
    'qt_material', # Nicht verwendet, verursacht Import-Warnung
]

# Binärdateien die ausgeschlossen werden sollen (nicht benötigte SQL-Treiber)
# Diese eliminieren die "Library not found" Warnungen für PostgreSQL, Oracle, etc.
binaries_exclude = [
    'qsqlmimer',   # Mimer SQL (MIMAPI64.dll)
    'qsqlpsql',    # PostgreSQL (LIBPQ.dll)
    'qsqloci',     # Oracle (OCI.dll)
    'qsqlibase',   # Firebird/InterBase (fbclient.dll)
    'qsqlmysql',   # MySQL
    'qsqlodbc',    # ODBC
]

# Analyse der Hauptdatei
a = Analysis(
    [str(SRC_PATH / 'gridtrader' / 'ui' / 'app.py')],
    pathex=[str(SRC_PATH)],
    binaries=[],
    datas=[
        # Falls du später Ressourcen hinzufügst:
        # (str(PROJECT_ROOT / 'resources'), 'resources'),
        # (str(PROJECT_ROOT / 'config'), 'config'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filtere nicht benötigte SQL-Treiber aus den Binaries
# Dies eliminiert die "Library not found" Warnungen für PostgreSQL, Oracle, Mimer, etc.
a.binaries = [
    (name, path, typ) for name, path, typ in a.binaries
    if not any(excluded in name.lower() for excluded in binaries_exclude)
]

# Python-Bytecode zusammenstellen
pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# EXE erstellen
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GridTrader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,  # Komprimierung aktivieren (UPX muss installiert sein)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # False = GUI ohne Konsole, True = mit Konsole (für Debugging)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='resources/icon.ico',  # Aktivieren wenn Icon vorhanden
)

# Optional: COLLECT für --onedir Modus (falls du später darauf umsteigst)
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='GridTrader',
# )
