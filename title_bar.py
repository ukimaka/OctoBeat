from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(36)
        self.setStyleSheet("background-color: #2b2b2b; color: white; border-bottom: 1px solid #1a1a1a;")

        self.title_label = QLabel("OctoBeat")
        self.title_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 13px; background: transparent; border: none; margin-left: 10px;")

        self.minimize_button = QPushButton("–")
        self.maximize_button = QPushButton("□")
        self.close_button = QPushButton("✕")

        # Базовый стиль для кнопок с нормальным шрифтом
        button_style = """
            QPushButton {
                background-color: transparent; border: none;
                color: #ffffff; font-family: Arial, sans-serif;
                font-size: 16px; font-weight: bold;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); }
        """
        self.minimize_button.setStyleSheet(button_style)
        self.maximize_button.setStyleSheet(button_style)

        # Отдельный стиль для кнопки закрытия (красный при наведении)
        self.close_button.setStyleSheet("""
            QPushButton {
                background-color: transparent; border: none;
                color: #ffffff; font-family: Arial, sans-serif;
                font-size: 14px; font-weight: bold;
            }
            QPushButton:hover { background-color: #e81123; }
        """)

        self.minimize_button.setFixedSize(46, 36)
        self.maximize_button.setFixedSize(46, 36)
        self.close_button.setFixedSize(46, 36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

        self.minimize_button.clicked.connect(lambda checked=False: self.window().showMinimized())
        self.maximize_button.clicked.connect(self._toggle_max)
        self.close_button.clicked.connect(lambda checked=False: self.window().close())  # pyright: ignore[reportArgumentType]
        self.drag_pos = QPoint()

    def _toggle_max(self):
        if self.window().isMaximized():
            self.window().showNormal()
        else:
            self.window().showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_pos'):
            self.window().move(event.globalPos() - self.drag_pos)
            event.accept()
