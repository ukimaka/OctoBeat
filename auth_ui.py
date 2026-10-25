"""Диалог входа и регистрации с фоновыми сетевыми запросами."""

from __future__ import annotations

from PyQt5.QtCore import QSettings, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient, ApiError


class _AuthWorker(QThread):
    """Выполняет регистрацию/вход вне главного потока."""

    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, mode: str, username: str, password: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.username = username
        self.password = password

    def run(self) -> None:
        client = ApiClient()
        try:
            if self.mode == "register":
                # После регистрации сразу получаем токен, чтобы пользователь
                # не вводил данные повторно.
                client.register(self.username, self.password)
            data = client.login(self.username, self.password)
        except ApiError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - UI не должен падать из-за потока
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.succeeded.emit(data)


class AuthDialog(QDialog):
    """Модальный диалог с вкладками Login и Register."""

    logged_in = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log In / Register")
        self.setMinimumWidth(380)
        self._worker: _AuthWorker | None = None
        self._submit_buttons: list[QPushButton] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.login_tab = self._build_tab("Login")
        self.register_tab = self._build_tab("Register")
        self.tabs.addTab(self.login_tab, "Login")
        self.tabs.addTab(self.register_tab, "Register")
        layout.addWidget(self.tabs)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #e05a5a;")
        self.error_label.setMinimumHeight(18)
        layout.addWidget(self.error_label)

    # ------------------------------------------------------------------
    #  Построение вкладки
    # ------------------------------------------------------------------
    def _build_tab(self, title: str) -> QWidget:
        mode = "login" if title == "Login" else "register"
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 12, 4, 4)
        layout.setSpacing(8)

        username = QLineEdit()
        username.setPlaceholderText("Username")
        username.setObjectName(f"{mode}Username")

        password = QLineEdit()
        password.setPlaceholderText("Password")
        password.setEchoMode(QLineEdit.Password)
        password.setObjectName(f"{mode}Password")

        submit = QPushButton("Submit")
        submit.setObjectName(f"{mode}Submit")
        submit.setCursor(Qt.PointingHandCursor)

        submit.clicked.connect(lambda: self._submit(mode))
        username.returnPressed.connect(lambda: self._submit(mode))
        password.returnPressed.connect(lambda: self._submit(mode))

        layout.addWidget(QLabel("Username"))
        layout.addWidget(username)
        layout.addWidget(QLabel("Password"))
        layout.addWidget(password)
        layout.addSpacing(4)
        layout.addWidget(submit)

        setattr(self, f"{mode}_username", username)
        setattr(self, f"{mode}_password", password)
        setattr(self, f"{mode}_submit", submit)
        self._submit_buttons.append(submit)

        return tab

    # ------------------------------------------------------------------
    #  Отправка запроса
    # ------------------------------------------------------------------
    def _submit(self, mode: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        username = getattr(self, f"{mode}_username").text().strip()
        password = getattr(self, f"{mode}_password").text()

        if not username or not password:
            self.error_label.setText("Enter username and password.")
            return

        self.error_label.setText("")
        self._set_busy(True)

        self._worker = _AuthWorker(mode, username, password, self)
        self._worker.succeeded.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _set_busy(self, busy: bool) -> None:
        for button in self._submit_buttons:
            button.setEnabled(not busy)
        self.tabs.setEnabled(not busy)

    def _on_success(self, data: dict) -> None:
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            self._on_failure("The server response does not contain an access token.")
            return

        QSettings("MusicPlayer", "MusicPlayer").setValue("api_token", token)
        self.logged_in.emit(token)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.error_label.setText(message)
        self._set_busy(False)

    def _on_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
        self._set_busy(False)

    # ------------------------------------------------------------------
    #  Закрытие во время запроса
    # ------------------------------------------------------------------
    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)
