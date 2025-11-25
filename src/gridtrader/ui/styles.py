"""
GridTrader V2.0 - Zentrale UI Styles
Konsistente Gestaltung für alle Widgets, Tabellen und Fenster
"""

# ==============================================================================
# FARBEN
# ==============================================================================

# Primärfarben
PRIMARY_COLOR = "#2563eb"          # Blau - Haupt-Akzentfarbe
PRIMARY_DARK = "#1d4ed8"           # Dunkleres Blau
PRIMARY_LIGHT = "#3b82f6"          # Helleres Blau

# Sekundärfarben
SECONDARY_COLOR = "#475569"        # Grau-Blau für GroupBox Headers
SECONDARY_LIGHT = "#64748b"        # Helleres Grau-Blau

# Header-Farben
HEADER_BG = "#e2e8f0"              # Heller Hintergrund für Tabellen-Header
HEADER_BG_DARK = "#cbd5e1"         # Etwas dunkler für Hover
GROUPBOX_HEADER_BG = "#f1f5f9"     # Sehr heller Hintergrund für GroupBox
TITLE_BG = "#dbeafe"               # Blauer Hintergrund für Haupttitel

# Status-Farben
SUCCESS_COLOR = "#16a34a"          # Grün für positive Werte
ERROR_COLOR = "#dc2626"            # Rot für negative Werte/Fehler
WARNING_COLOR = "#f59e0b"          # Orange für Warnungen
INFO_COLOR = "#0ea5e9"             # Hellblau für Info

# Text-Farben
TEXT_PRIMARY = "#1e293b"           # Dunkler Text
TEXT_SECONDARY = "#64748b"         # Sekundärer Text
TEXT_LIGHT = "#f8fafc"             # Heller Text auf dunklem Hintergrund

# Hintergrundfarben
BG_WHITE = "#ffffff"
BG_LIGHT = "#f8fafc"
BG_GRAY = "#f1f5f9"

# ==============================================================================
# STYLESHEET-STRINGS
# ==============================================================================

# Haupttitel-Style (z.B. "GridTrader Dashboard")
TITLE_STYLE = f"""
    QLabel {{
        font-size: 18px;
        font-weight: bold;
        color: {TEXT_PRIMARY};
        background-color: {TITLE_BG};
        padding: 12px 15px;
        border-radius: 6px;
        border-left: 4px solid {PRIMARY_COLOR};
    }}
"""

# Untertitel-Style (z.B. für Sektions-Überschriften)
SUBTITLE_STYLE = f"""
    QLabel {{
        font-size: 14px;
        font-weight: bold;
        color: {TEXT_PRIMARY};
        background-color: {GROUPBOX_HEADER_BG};
        padding: 8px 12px;
        border-radius: 4px;
    }}
"""

# GroupBox-Style mit farbigem Header
GROUPBOX_STYLE = f"""
    QGroupBox {{
        font-weight: bold;
        font-size: 13px;
        color: {TEXT_PRIMARY};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 6px;
        margin-top: 12px;
        padding-top: 10px;
        background-color: {BG_WHITE};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 10px;
        padding: 4px 12px;
        background-color: {GROUPBOX_HEADER_BG};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        color: {SECONDARY_COLOR};
    }}
"""

# Tabellen-Style mit fett formatiertem, farbigem Header
TABLE_STYLE = f"""
    QTableWidget {{
        background-color: {BG_WHITE};
        alternate-background-color: {BG_LIGHT};
        gridline-color: {HEADER_BG};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        selection-background-color: {PRIMARY_LIGHT};
        selection-color: {TEXT_LIGHT};
    }}
    QTableWidget::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {HEADER_BG};
    }}
    QTableWidget::item:selected {{
        background-color: {PRIMARY_LIGHT};
        color: {TEXT_LIGHT};
    }}
    QHeaderView::section {{
        background-color: {HEADER_BG};
        color: {TEXT_PRIMARY};
        font-weight: bold;
        font-size: 12px;
        padding: 8px 6px;
        border: none;
        border-bottom: 2px solid {PRIMARY_COLOR};
        border-right: 1px solid {HEADER_BG_DARK};
    }}
    QHeaderView::section:hover {{
        background-color: {HEADER_BG_DARK};
    }}
    QHeaderView::section:first {{
        border-top-left-radius: 4px;
    }}
    QHeaderView::section:last {{
        border-top-right-radius: 4px;
        border-right: none;
    }}
"""

# TreeWidget-Style (für hierarchische Daten)
TREE_STYLE = f"""
    QTreeWidget {{
        background-color: {BG_WHITE};
        alternate-background-color: {BG_LIGHT};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        selection-background-color: {PRIMARY_LIGHT};
        selection-color: {TEXT_LIGHT};
    }}
    QTreeWidget::item {{
        padding: 4px 6px;
        border-bottom: 1px solid {HEADER_BG};
    }}
    QTreeWidget::item:selected {{
        background-color: {PRIMARY_LIGHT};
        color: {TEXT_LIGHT};
    }}
    QHeaderView::section {{
        background-color: {HEADER_BG};
        color: {TEXT_PRIMARY};
        font-weight: bold;
        font-size: 12px;
        padding: 8px 6px;
        border: none;
        border-bottom: 2px solid {PRIMARY_COLOR};
        border-right: 1px solid {HEADER_BG_DARK};
    }}
"""

# ListWidget-Style
LIST_STYLE = f"""
    QListWidget {{
        background-color: {BG_WHITE};
        alternate-background-color: {BG_LIGHT};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        selection-background-color: {PRIMARY_LIGHT};
        selection-color: {TEXT_LIGHT};
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {HEADER_BG};
    }}
    QListWidget::item:selected {{
        background-color: {PRIMARY_LIGHT};
        color: {TEXT_LIGHT};
    }}
"""

# Tab-Widget Style
TAB_STYLE = f"""
    QTabWidget::pane {{
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        background-color: {BG_WHITE};
        padding: 5px;
    }}
    QTabBar::tab {{
        background-color: {BG_GRAY};
        color: {TEXT_SECONDARY};
        font-weight: bold;
        padding: 10px 20px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        border: 1px solid {HEADER_BG_DARK};
        border-bottom: none;
    }}
    QTabBar::tab:selected {{
        background-color: {BG_WHITE};
        color: {PRIMARY_COLOR};
        border-bottom: 2px solid {PRIMARY_COLOR};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {HEADER_BG};
        color: {TEXT_PRIMARY};
    }}
"""

# Button-Styles
PRIMARY_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {PRIMARY_COLOR};
        color: {TEXT_LIGHT};
        font-weight: bold;
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: {PRIMARY_DARK};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_DARK};
    }}
    QPushButton:disabled {{
        background-color: {HEADER_BG_DARK};
        color: {TEXT_SECONDARY};
    }}
"""

SECONDARY_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {BG_LIGHT};
        color: {TEXT_PRIMARY};
        font-weight: bold;
        padding: 8px 16px;
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: {HEADER_BG};
        border-color: {SECONDARY_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {HEADER_BG_DARK};
    }}
"""

SUCCESS_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {SUCCESS_COLOR};
        color: {TEXT_LIGHT};
        font-weight: bold;
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: #15803d;
    }}
"""

DANGER_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {ERROR_COLOR};
        color: {TEXT_LIGHT};
        font-weight: bold;
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: #b91c1c;
    }}
"""

# Status-Labels
STATUS_CONNECTED_STYLE = f"""
    QLabel {{
        color: {SUCCESS_COLOR};
        font-weight: bold;
        padding: 5px 10px;
        background-color: #dcfce7;
        border-radius: 4px;
    }}
"""

STATUS_DISCONNECTED_STYLE = f"""
    QLabel {{
        color: {ERROR_COLOR};
        font-weight: bold;
        padding: 5px 10px;
        background-color: #fee2e2;
        border-radius: 4px;
    }}
"""

STATUS_WARNING_STYLE = f"""
    QLabel {{
        color: {WARNING_COLOR};
        font-weight: bold;
        padding: 5px 10px;
        background-color: #fef3c7;
        border-radius: 4px;
    }}
"""

# Status-Bar Style
STATUSBAR_STYLE = f"""
    QLabel {{
        padding: 8px 12px;
        background-color: {BG_GRAY};
        border-radius: 4px;
        color: {TEXT_SECONDARY};
    }}
"""

# Log/TextEdit Style
LOG_STYLE = f"""
    QTextEdit {{
        background-color: {BG_LIGHT};
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 11px;
        padding: 8px;
        color: {TEXT_PRIMARY};
    }}
"""

# Input-Styles
INPUT_STYLE = f"""
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        padding: 6px 10px;
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        background-color: {BG_WHITE};
        color: {TEXT_PRIMARY};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {PRIMARY_COLOR};
        outline: none;
    }}
"""

# Progress-Bar Style
PROGRESS_STYLE = f"""
    QProgressBar {{
        border: 1px solid {HEADER_BG_DARK};
        border-radius: 4px;
        text-align: center;
        background-color: {BG_GRAY};
    }}
    QProgressBar::chunk {{
        background-color: {PRIMARY_COLOR};
        border-radius: 3px;
    }}
"""

# ==============================================================================
# UTILITY-FUNKTIONEN
# ==============================================================================

def apply_table_style(table):
    """Wendet den Standard-Tabellen-Style auf ein QTableWidget an"""
    table.setStyleSheet(TABLE_STYLE)
    table.setAlternatingRowColors(True)
    # Header-Schriftart explizit setzen
    header = table.horizontalHeader()
    if header:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        header.setFont(font)


def apply_tree_style(tree):
    """Wendet den Standard-Style auf ein QTreeWidget an"""
    tree.setStyleSheet(TREE_STYLE)
    tree.setAlternatingRowColors(True)
    # Header-Schriftart explizit setzen
    header = tree.header()
    if header:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        header.setFont(font)


def apply_list_style(listwidget):
    """Wendet den Standard-Style auf ein QListWidget an"""
    listwidget.setStyleSheet(LIST_STYLE)
    listwidget.setAlternatingRowColors(True)


def apply_groupbox_style(groupbox):
    """Wendet den Standard-Style auf eine QGroupBox an"""
    groupbox.setStyleSheet(GROUPBOX_STYLE)


def apply_title_style(label):
    """Wendet den Titel-Style auf ein QLabel an"""
    label.setStyleSheet(TITLE_STYLE)


def apply_subtitle_style(label):
    """Wendet den Untertitel-Style auf ein QLabel an"""
    label.setStyleSheet(SUBTITLE_STYLE)


def apply_log_style(textedit):
    """Wendet den Log-Style auf ein QTextEdit an"""
    textedit.setStyleSheet(LOG_STYLE)


def apply_widget_styles(widget):
    """
    Wendet Styles auf alle Child-Widgets eines Containers an.
    Nützlich für neue Widgets oder beim Initialisieren.
    """
    from PySide6.QtWidgets import (
        QTableWidget, QTreeWidget, QListWidget,
        QGroupBox, QTextEdit, QTabWidget
    )

    # Finde und style alle Tables
    for table in widget.findChildren(QTableWidget):
        apply_table_style(table)

    # Finde und style alle Trees
    for tree in widget.findChildren(QTreeWidget):
        apply_tree_style(tree)

    # Finde und style alle Lists
    for listw in widget.findChildren(QListWidget):
        apply_list_style(listw)

    # Finde und style alle GroupBoxes
    for groupbox in widget.findChildren(QGroupBox):
        apply_groupbox_style(groupbox)

    # Finde und style alle TextEdits (Logs)
    for textedit in widget.findChildren(QTextEdit):
        apply_log_style(textedit)


def get_value_color(value: float, positive_is_good: bool = True):
    """
    Gibt die passende Farbe für einen Wert zurück.

    Args:
        value: Der numerische Wert
        positive_is_good: True wenn positive Werte grün sein sollen

    Returns:
        QColor Objekt
    """
    from PySide6.QtGui import QColor

    if value == 0:
        return QColor(TEXT_SECONDARY)

    if positive_is_good:
        return QColor(SUCCESS_COLOR) if value > 0 else QColor(ERROR_COLOR)
    else:
        return QColor(ERROR_COLOR) if value > 0 else QColor(SUCCESS_COLOR)
