"""Live Data Widget - Simplified"""
from PySide6.QtWidgets import *
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QBrush
from datetime import datetime
import random

class LiveDataWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        
        # Control
        control = QHBoxLayout()
        control.addWidget(QLabel("Symbol:"))
        self.symbol_input = QLineEdit("AAPL")
        control.addWidget(self.symbol_input)
        self.add_btn = QPushButton("Add Symbol")
        self.add_btn.clicked.connect(self.add_symbol)
        control.addWidget(self.add_btn)
        control.addStretch()
        layout.addLayout(control)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Symbol", "Bid", "Ask", "Last", "Change", "Volume", "Time"])
        layout.addWidget(self.table)
        
        # Timer for updates
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(2000)
        
    def add_symbol(self):
        symbol = self.symbol_input.text().upper()
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(symbol))
        for col in range(1, 7):
            self.table.setItem(row, col, QTableWidgetItem("--"))
            
    def update_data(self):
        for row in range(self.table.rowCount()):
            # Simulate data
            last = round(100 + random.uniform(-5, 5), 2)
            bid = last - 0.01
            ask = last + 0.01
            change = round(random.uniform(-2, 2), 2)
            volume = random.randint(1000000, 5000000)
            
            self.table.item(row, 1).setText(f"${bid:.2f}")
            self.table.item(row, 2).setText(f"${ask:.2f}")
            self.table.item(row, 3).setText(f"${last:.2f}")
            
            change_item = QTableWidgetItem(f"${change:+.2f}")
            color = QColor(0, 150, 0) if change >= 0 else QColor(150, 0, 0)
            change_item.setForeground(QBrush(color))
            self.table.setItem(row, 4, change_item)
            
            self.table.item(row, 5).setText(f"{volume:,}")
            self.table.item(row, 6).setText(datetime.now().strftime("%H:%M:%S"))
