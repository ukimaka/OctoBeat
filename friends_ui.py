"""Страница друзей: поиск, список друзей и входящие заявки."""

from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QSettings, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from api_client import ApiClient, ApiError
from dialogs import colored_icon
from profile_ui import _round_avatar_pixmap
from translations import tr


def _lang() -> str:
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return settings.value("language", "en")


def _icon_color() -> str:
    settings = QSettings("MusicPlayer", "MusicPlayer")
    return "#ffffff" if settings.value("theme", "dark") != "light" else "#000000"


class _RequestWorker(QThread):
    """Выполняет один сетевой запрос вне главного потока."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str, int)  # сообщение, HTTP-статус (0 — сеть)

    def __init__(self, func: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._func = func

    def run(self) -> None:
        try:
            result = self._func()
        except ApiError as exc:
            self.failed.emit(str(exc), exc.status_code or 0)
        except Exception as exc:  # noqa: BLE001 - UI не должен падать из-за потока
            self.failed.emit(f"Unexpected error: {exc}", 0)
        else:
            self.succeeded.emit(result)


class FriendListItemWidget(QWidget):
    """Строка друга: аватарка, никнейм с @username и кнопка профиля."""

    profile_requested = pyqtSignal(int)

    def __init__(self, user: dict[str, Any], parent=None):
        super().__init__(parent)
        self._user_id = int(user.get("id") or 0)
        self.setStyleSheet("background: transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)

        avatar = QLabel()
        avatar.setFixedSize(32, 32)
        avatar.setPixmap(
            _round_avatar_pixmap(user.get("avatar_path"), 32)
        )
        row.addWidget(avatar)

        username = str(user.get("username") or "")
        nickname = str(user.get("nickname") or username)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        nickname_label = QLabel(nickname)
        nickname_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        username_label = QLabel(f"@{username}")
        username_label.setStyleSheet("color: #9a9a9a;")
        text_col.addWidget(nickname_label)
        text_col.addWidget(username_label)
        row.addLayout(text_col, 1)

        color = _icon_color()
        hover = (
            "rgba(255, 255, 255, 0.12)"
            if color == "#ffffff"
            else "rgba(0, 0, 0, 0.08)"
        )
        self.profile_button = QPushButton()
        self.profile_button.setFixedSize(24, 24)
        self.profile_button.setCursor(Qt.PointingHandCursor)
        self.profile_button.setToolTip(tr("View Profile", _lang()))
        self.profile_button.setIconSize(QSize(12, 12))
        self.profile_button.setIcon(colored_icon("user.svg", color))
        self.profile_button.setStyleSheet(
            "QPushButton {"
            " background: transparent;"
            f" border: 1px solid {color};"
            " border-radius: 12px;"
            " }"
            f"QPushButton:hover {{ background: {hover}; }}"
        )
        self.profile_button.clicked.connect(self._on_profile_clicked)
        row.addWidget(self.profile_button)

    def _on_profile_clicked(self) -> None:
        if self._user_id:
            self.profile_requested.emit(self._user_id)


class FriendsPage(QWidget):
    """Вкладка «Друзья» с поиском, друзьями и входящими заявками."""

    auth_expired = pyqtSignal()
    incoming_requests_changed = pyqtSignal(int)
    profile_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("MusicPlayer", "MusicPlayer")
        self._workers: set[_RequestWorker] = set()
        self._refresh_worker: _RequestWorker | None = None
        self._refresh_pending = False
        self._refresh_pending_silent = True
        self._search_worker: _RequestWorker | None = None
        self._action_worker: _RequestWorker | None = None
        self._status_after_refresh: str | None = None

        self._me: dict[str, Any] | None = None
        self._friends: list[dict[str, Any]] = []
        self._incoming: list[dict[str, Any]] = []
        self._search_results: list[dict[str, Any]] = []

        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(500)
        self._search_timer.timeout.connect(self._on_search)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.refresh_auth_state()

    # ------------------------------------------------------------------
    #  Построение интерфейса
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        lang = _lang()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        self.auth_label = QLabel(tr("Please log in to see friends", lang))
        self.auth_label.setObjectName("friendsAuthLabel")
        self.auth_label.setAlignment(Qt.AlignCenter)
        self.auth_label.setWordWrap(True)
        root.addWidget(self.auth_label, 1)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        # --- Верхняя панель ---
        top = QHBoxLayout()
        top.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("friendsSearchEdit")
        self.search_edit.setPlaceholderText(tr("Search users...", lang))
        self.search_icon_action = self.search_edit.addAction(
            colored_icon("search.svg", _icon_color()), QLineEdit.LeadingPosition
        )
        self.search_edit.returnPressed.connect(self._on_search_now)
        self.my_friends_button = QPushButton(tr("My Friends", lang))
        self.my_friends_button.setObjectName("friendsMyFriendsButton")
        self.my_friends_button.setCursor(Qt.PointingHandCursor)
        self.my_friends_button.clicked.connect(self._show_friends)

        self.requests_button = QPushButton(tr("Requests", lang))
        self.requests_button.setObjectName("friendsRequestsButton")
        self.requests_button.setCursor(Qt.PointingHandCursor)
        self.requests_button.clicked.connect(self._show_requests)

        top.addWidget(self.search_edit, 1)
        top.addSpacing(8)
        top.addWidget(self.my_friends_button)
        top.addWidget(self.requests_button)
        body_layout.addLayout(top)

        # --- Центральная часть: три страницы ---
        self.pages = QStackedWidget()
        self.pages.setObjectName("friendsPages")

        self.search_list = self._make_list("friendsSearchResults")
        self.friends_list = self._make_list("friendsList")
        self.requests_list = self._make_list("friendsRequestsList")

        self.search_page = self._make_page(self.search_list)
        self.friends_page = self._make_page(self.friends_list)
        self.requests_page = self._make_page(self.requests_list)

        # Порядок страниц: результаты поиска, друзья, входящие заявки.
        self.pages.addWidget(self.search_page)
        self.pages.addWidget(self.friends_page)
        self.pages.addWidget(self.requests_page)
        self.pages.setCurrentIndex(1)
        body_layout.addWidget(self.pages, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("friendsStatusLabel")
        self.status_label.setWordWrap(True)
        body_layout.addWidget(self.status_label)

        root.addWidget(self.body, 1)

    def _make_list(self, object_name: str) -> QListWidget:
        widget = QListWidget()
        widget.setObjectName(object_name)
        widget.setSelectionMode(QAbstractItemView.NoSelection)
        widget.setSpacing(4)
        return widget

    @staticmethod
    def _make_page(list_widget: QListWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(list_widget)
        return page

    def refresh_icons(self) -> None:
        """Перекрашивает иконку поиска и строки друзей под текущую тему."""
        if getattr(self, "search_icon_action", None) is not None:
            self.search_icon_action.setIcon(
                colored_icon("search.svg", _icon_color())
            )
        if self._friends:
            self._populate_friends()

    # ------------------------------------------------------------------
    #  Авторизация
    # ------------------------------------------------------------------
    def _token(self) -> str | None:
        token = self.settings.value("api_token")
        if isinstance(token, str) and token.strip():
            return token
        return None

    def refresh_auth_state(self) -> bool:
        """Показывает заглушку или интерфейс в зависимости от наличия токена."""
        authenticated = self._token() is not None
        self.auth_label.setVisible(not authenticated)
        self.body.setVisible(authenticated)

        if not authenticated:
            self._me = None
            self._friends = []
            self._incoming = []
            self._search_results = []
            self.search_list.clear()
            self.friends_list.clear()
            self.requests_list.clear()
            self._set_status("")
            self.incoming_requests_changed.emit(0)
        return authenticated

    def get_incoming_requests_count(self) -> int:
        """Количество входящих заявок в друзья (последние загруженные данные)."""
        return len(self._incoming)

    def _ensure_auth(self) -> bool:
        return self.refresh_auth_state()

    # ------------------------------------------------------------------
    #  Загрузка данных
    # ------------------------------------------------------------------
    def refresh(self, silent: bool = False) -> None:
        """Проверяет токен и перезагружает друзей и заявки.

        ``silent`` — фоновая проверка (например, таймером уведомлений):
        не показывает «Loading...» и не сбрасывает текущий статус.
        """
        if not self.refresh_auth_state():
            return
        if self._refresh_worker is not None:
            self._refresh_pending = True
            self._refresh_pending_silent = self._refresh_pending_silent and silent
            return

        token = self._token()
        lang = _lang()
        if not silent:
            self._set_status(tr("Loading...", lang))
        worker = self._prepare_worker(
            lambda: self._load_all(token),
            lambda data: self._on_refresh_success(data, silent),
        )
        self._refresh_worker = worker
        worker.start()

    def _load_all(self, token: str | None) -> dict[str, Any]:
        client = ApiClient(token=token)
        return {
            "me": client.get_me(),
            "friends": client.get_friends(),
            "requests": client.get_incoming_requests(),
        }

    def _on_refresh_success(
        self, data: dict[str, Any], silent: bool = False
    ) -> None:
        self._me = data.get("me") or {}
        self._friends = data.get("friends") or []
        self._incoming = data.get("requests") or []
        self._populate_friends()
        self._populate_requests()
        self.incoming_requests_changed.emit(len(self._incoming))

        if self._status_after_refresh:
            self._set_status(self._status_after_refresh)
            self._status_after_refresh = None
        elif not silent:
            self._set_status("")

    # ------------------------------------------------------------------
    #  Списки
    # ------------------------------------------------------------------
    def _populate_friends(self) -> None:
        lang = _lang()
        self.friends_list.clear()
        if not self._friends:
            self._add_placeholder(
                self.friends_list, tr("No friends yet", lang)
            )
            return
        for user in self._friends:
            user_id = user.get("id")
            if user_id is None:
                continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, int(user_id))
            self.friends_list.addItem(item)

            widget = FriendListItemWidget(user, self.friends_list)
            widget.profile_requested.connect(self.profile_requested.emit)
            item.setSizeHint(QSize(0, 52))
            self.friends_list.setItemWidget(item, widget)

    def _populate_requests(self) -> None:
        lang = _lang()
        self.requests_list.clear()
        if not self._incoming:
            self._add_placeholder(
                self.requests_list, tr("No incoming requests", lang)
            )
            return
        for user in self._incoming:
            self._add_user_row(
                self.requests_list,
                user,
                [
                    (tr("Accept", lang), self._accept_request, True),
                    (tr("Reject", lang), self._reject_request, False),
                ],
            )

    def _populate_search(self) -> None:
        lang = _lang()
        self.search_list.clear()
        for user in self._search_results:
            self._add_user_row(
                self.search_list,
                user,
                [(tr("Send Request", lang), self._send_request, True)],
            )

    def _add_placeholder(self, list_widget: QListWidget, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.NoItemFlags)
        item.setTextAlignment(Qt.AlignCenter)
        list_widget.addItem(item)

    def _add_user_row(
        self,
        list_widget: QListWidget,
        user: dict[str, Any],
        actions: list[tuple[str, Callable[[int, QPushButton], None], bool]],
    ) -> None:
        user_id = user.get("id")
        if user_id is None:
            return

        username = str(user.get("username") or "")
        nickname = str(user.get("nickname") or username)

        item = QListWidgetItem()
        item.setData(Qt.UserRole, int(user_id))
        list_widget.addItem(item)

        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        nickname_label = QLabel(nickname)
        nickname_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        username_label = QLabel(f"@{username}")
        username_label.setStyleSheet("color: #9a9a9a;")
        text_col.addWidget(nickname_label)
        text_col.addWidget(username_label)
        row_layout.addLayout(text_col, 1)

        for text, callback, primary in actions:
            button = self._action_button(text, primary)
            button.clicked.connect(
                lambda _checked=False, cb=callback, uid=int(user_id), b=button: (
                    cb(uid, b)
                )
            )
            row_layout.addWidget(button)

        item.setSizeHint(QSize(0, max(52, row.sizeHint().height())))
        list_widget.setItemWidget(item, row)

    @staticmethod
    def _action_button(text: str, primary: bool) -> QPushButton:
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        if primary:
            button.setStyleSheet(
                "QPushButton { background-color: #5151ab; color: #ffffff;"
                " border: none; border-radius: 12px; padding: 5px 14px; }"
                "QPushButton:hover { background-color: #6363c6; }"
                "QPushButton:disabled { background-color: #333333; color: #888888; }"
            )
        else:
            button.setStyleSheet(
                "QPushButton { background-color: transparent; color: #e05a5a;"
                " border: 1px solid #7a3b3b; border-radius: 12px;"
                " padding: 5px 14px; }"
                "QPushButton:hover { background-color: rgba(224, 90, 90, 0.12); }"
            )
        return button

    # ------------------------------------------------------------------
    #  Действия
    # ------------------------------------------------------------------
    def _show_friends(self) -> None:
        if not self._ensure_auth():
            return
        self._search_timer.stop()
        self.pages.setCurrentIndex(1)
        self.refresh()

    def _show_requests(self) -> None:
        if not self._ensure_auth():
            return
        self._search_timer.stop()
        self.pages.setCurrentIndex(2)
        self.refresh()

    def _on_search_text_changed(self, _text: str) -> None:
        """Поиск с задержкой: не шлём запрос на каждое нажатие клавиши."""
        self._search_timer.start()

    def _on_search_now(self) -> None:
        """Enter в поле поиска — искать немедленно."""
        self._search_timer.stop()
        self._on_search()

    def _on_search(self) -> None:
        if not self._ensure_auth():
            return
        if self._search_worker is not None:
            return

        lang = _lang()
        query = self.search_edit.text().strip()
        self.pages.setCurrentIndex(0)

        if not query:
            self._set_status(tr("Enter a username to search.", lang), error=True)
            return

        self._set_status(tr("Searching...", lang))
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).search_users(query),
            self._on_search_success,
        )
        self._search_worker = worker
        worker.start()

    def _on_search_success(self, users: list[dict[str, Any]]) -> None:
        self._search_results = users
        self._populate_search()
        if users:
            self._set_status("")
        else:
            self._set_status(tr("No users found", _lang()), error=True)

    def _send_request(self, user_id: int, button: QPushButton) -> None:
        if not self._ensure_auth() or self._action_worker is not None:
            return

        lang = _lang()
        self._set_status(tr("Sending request...", lang))
        button.setEnabled(False)
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).send_friend_request(user_id),
            self._on_request_sent,
        )
        worker.finished.connect(lambda: button.setEnabled(True))
        self._action_worker = worker
        worker.start()

    def _on_request_sent(self, result: dict[str, Any]) -> None:
        lang = _lang()
        status = result.get("status") if isinstance(result, dict) else None
        if status == "already friends":
            self._status_after_refresh = tr("You are already friends", lang)
        else:
            self._status_after_refresh = tr("Request sent", lang)
        self.refresh()

    def _accept_request(self, user_id: int, button: QPushButton) -> None:
        if not self._ensure_auth() or self._action_worker is not None:
            return

        self._set_status(tr("Accepting request...", _lang()))
        button.setEnabled(False)
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).accept_friend_request(user_id),
            lambda _result: self._on_friend_action_done(
                tr("Friend request accepted", _lang())
            ),
        )
        worker.finished.connect(lambda: button.setEnabled(True))
        self._action_worker = worker
        worker.start()

    def _reject_request(self, user_id: int, button: QPushButton) -> None:
        if not self._ensure_auth() or self._action_worker is not None:
            return

        self._set_status(tr("Rejecting request...", _lang()))
        button.setEnabled(False)
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).reject_friend_request(user_id),
            lambda _result: self._on_friend_action_done(
                tr("Friend request rejected", _lang())
            ),
        )
        worker.finished.connect(lambda: button.setEnabled(True))
        self._action_worker = worker
        worker.start()

    def _on_friend_action_done(self, message: str) -> None:
        self._status_after_refresh = message
        self.refresh()

    # ------------------------------------------------------------------
    #  Воркеры и ошибки
    # ------------------------------------------------------------------
    def _prepare_worker(
        self,
        func: Callable[[], Any],
        on_success: Callable[[Any], None],
    ) -> _RequestWorker:
        worker = _RequestWorker(func, self)
        self._workers.add(worker)
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._on_request_error)
        worker.finished.connect(lambda w=worker: self._finish_worker(w))
        return worker

    def _finish_worker(self, worker: _RequestWorker) -> None:
        self._workers.discard(worker)
        if self._refresh_worker is worker:
            self._refresh_worker = None
            if self._refresh_pending:
                pending_silent = self._refresh_pending_silent
                self._refresh_pending = False
                self._refresh_pending_silent = True
                self.refresh(silent=pending_silent)
        if self._search_worker is worker:
            self._search_worker = None
        if self._action_worker is worker:
            self._action_worker = None
        worker.deleteLater()

    def _on_request_error(self, message: str, status_code: int) -> None:
        self._status_after_refresh = None
        if status_code == 401:
            # Токен больше недействителен — возвращаемся к заглушке.
            self.settings.remove("api_token")
            self.refresh_auth_state()
            self.auth_expired.emit()
            return
        self._set_status(message, error=True)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color: #e05a5a;" if error else "color: #9a9a9a;"
        )

    # ------------------------------------------------------------------
    #  Завершение
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Дожидается завершения фоновых запросов при закрытии приложения."""
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(11000)
            except RuntimeError:
                pass
