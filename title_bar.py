from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class CustomTitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setObjectName("customTitleBar")
        self.setFixedHeight(36)

        self.title_label = QLabel("OctoBeat")
        self.title_label.setObjectName("titleBarLabel")

        self.minimize_button = QPushButton("–")
        self.maximize_button = QPushButton("□")
        self.close_button = QPushButton("✕")
        self.close_button.setObjectName("titleBarClose")

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

        self.minimize_button.clicked.connect(
            lambda checked=False: self.window().showMinimized()
        )
        self.maximize_button.clicked.connect(self._toggle_max)
        self.close_button.clicked.connect(
            lambda checked=False: self.window().close()
        )  # pyright: ignore[reportArgumentType]
        self.drag_pos = QPoint()

        self.apply_theme(True)

    def apply_theme(self, is_dark):
        """Перекрашивает заголовок под текущую тему.
        Фон и рамки задаются в QSS-теме (styles.BASE_QSS + theme.qss).
        Здесь только цвет текста и hover-эффекты кнопок.
        """
        if is_dark:
            foreground = "#ffffff"
            hover = "rgba(255, 255, 255, 0.10)"
        else:
            foreground = "#2E3440"
            hover = "rgba(0, 0, 0, 0.08)"

        self.setStyleSheet(f"""
            QWidget#customTitleBar {{
                /* background и border заданы в QSS-теме */
            }}
            QLabel#titleBarLabel {{
                color: {foreground};
                font-weight: bold;
                font-size: 13px;
                background: transparent;
                border: none;
                margin-left: 10px;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {foreground};
                font-family: Arial, sans-serif;
                font-size: 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton#titleBarClose {{
                font-size: 14px;
            }}
            QPushButton#titleBarClose:hover {{
                background-color: #e81123;
                color: #ffffff;
            }}
        """)

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
