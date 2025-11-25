"""
GridTrader GUI Application Entry Point
"""
import sys
from PySide6.QtWidgets import QApplication
from gridtrader.ui.main_window import MainWindow


def main():
    """Haupteinstiegspunkt für die GUI"""
    app = QApplication(sys.argv)
    app.setApplicationName("GridTrader V2.0")
    app.setOrganizationName("GridTrader")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
