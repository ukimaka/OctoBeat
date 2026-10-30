# OctoBeat - музыкальный плеер
# Copyright (C) 2026 ukimaka
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Страница друзей: поиск, список друзей и входящие заявки."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt5.QtCore import (
    QPoint,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QIcon
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
        # CHANGED: кнопка «Профиль» с текстом и иконкой user.svg.
        self.profile_button = QPushButton(tr("Profile", _lang()))
        self.profile_button.setCursor(Qt.PointingHandCursor)
        self.profile_button.setToolTip(tr("View Profile", _lang()))
        self.profile_button.setIconSize(QSize(14, 14))
        self.profile_button.setIcon(colored_icon("user.svg", color))
        self.profile_button.setFixedHeight(28)
        self.profile_button.setStyleSheet(
            "QPushButton {"
            " background: transparent;"
            f" color: {color};"
            f" border: 1px solid {color};"
            " border-radius: 14px;"
            " padding: 4px 12px;"
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
        self._pending_search_query: str | None = None  # CHANGED

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

        # CHANGED: отдельной страницы результатов поиска больше нет —
        # остались только друзья и входящие заявки.
        self.pages = QStackedWidget()
        self.pages.setObjectName("friendsPages")

        self.friends_list = self._make_list("friendsList")
        self.requests_list = self._make_list("friendsRequestsList")

        self.friends_page = self._make_page(self.friends_list)
        self.requests_page = self._make_page(self.requests_list)

        self.pages.addWidget(self.friends_page)
        self.pages.addWidget(self.requests_page)
        self.pages.setCurrentIndex(0)
        body_layout.addWidget(self.pages, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("friendsStatusLabel")
        self.status_label.setWordWrap(True)
        body_layout.addWidget(self.status_label)

        root.addWidget(self.body, 1)

        # CHANGED: всплывающий список результатов поиска (как в Google).
        self.search_popup = QListWidget(self)
        self.search_popup.setObjectName("friendsSearchPopup")
        self.search_popup.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.search_popup.setFocusPolicy(Qt.NoFocus)
        self.search_popup.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.search_popup.setIconSize(QSize(32, 32))
        self.search_popup.setSpacing(2)
        self.search_popup.setUniformItemSizes(True)
        self.search_popup.hide()
        self._apply_search_popup_style()
        self.search_popup.itemClicked.connect(
            self._on_search_result_clicked
        )

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
        # CHANGED: выпадашка тоже должна следовать теме.
        if getattr(self, "search_popup", None) is not None:
            self._apply_search_popup_style()
        if self._friends:
            self._populate_friends()

    def _apply_search_popup_style(self) -> None:
        # CHANGED: оформление всплывающего поиска под текущую тему.
        dark = _icon_color() == "#ffffff"
        popup_bg = "#1f1f1f" if dark else "#ffffff"
        popup_border = "#333333" if dark else "#d0d0d0"
        popup_hover = (
            "rgba(255, 255, 255, 0.10)"
            if dark
            else "rgba(0, 0, 0, 0.06)"
        )
        self.search_popup.setStyleSheet(
            "QListWidget {"
            f" background-color: {popup_bg};"
            f" border: 1px solid {popup_border};"
            " border-radius: 8px;"
            " padding: 4px;"
            " }"
            "QListWidget::item { padding: 6px 8px; border-radius: 6px; }"
            f"QListWidget::item:hover, QListWidget::item:selected"
            f" {{ background: {popup_hover}; }}"
        )

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
            # CHANGED: чистим и прячем выпадающий поиск вместо страницы.
            self._search_timer.stop()
            self.search_popup.clear()
            self._hide_search_popup()
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

    # CHANGED: результаты поиска теперь живут во всплывающем списке.
    def _populate_search_popup(self) -> None:
        self.search_popup.clear()
        for user in self._search_results:
            user_id = user.get("id")
            if user_id is None:
                continue
            username = str(user.get("username") or "")
            nickname = str(user.get("nickname") or username)
            item = QListWidgetItem(
                QIcon(_round_avatar_pixmap(user.get("avatar_path"), 32)),
                f"{nickname}   @{username}",
            )
            item.setData(Qt.UserRole, int(user_id))
            item.setSizeHint(QSize(0, 44))
            self.search_popup.addItem(item)

        if self.search_popup.count() == 0:
            self._hide_search_popup()
        else:
            self._show_search_popup()

    def _show_search_popup(self) -> None:
        if self.search_popup.count() == 0:
            return
        rows = min(self.search_popup.count(), 6)
        height = rows * 44 + 10
        pos = self.search_edit.mapToGlobal(
            QPoint(0, self.search_edit.height() + 2)
        )
        self.search_popup.setGeometry(
            pos.x(), pos.y(), self.search_edit.width(), height
        )
        self.search_popup.show()
        self.search_popup.raise_()

    def _hide_search_popup(self) -> None:
        if self.search_popup.isVisible():
            self.search_popup.hide()

    def _on_search_result_clicked(self, item: QListWidgetItem) -> None:
        self._hide_search_popup()
        user_id = item.data(Qt.UserRole)
        if user_id is not None:
            self._send_request(int(user_id))

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
        # CHANGED: друзья теперь первая страница.
        self._hide_search_popup()
        self.pages.setCurrentIndex(0)
        self.refresh()

    def _show_requests(self) -> None:
        if not self._ensure_auth():
            return
        self._search_timer.stop()
        # CHANGED: заявки теперь вторая страница.
        self._hide_search_popup()
        self.pages.setCurrentIndex(1)
        self.refresh()

    # CHANGED: дебаунс 500 мс + выпадающий список вместо страницы.
    def _on_search_text_changed(self, text: str) -> None:
        """Поиск с задержкой: не шлём запрос на каждое нажатие клавиши."""
        if not text.strip():
            self._search_timer.stop()
            self._pending_search_query = None
            self._hide_search_popup()
            self._set_status("")
            return
        self._search_timer.start()

    def _on_search_now(self) -> None:
        """Enter в поле поиска — искать немедленно."""
        self._search_timer.stop()
        self._on_search()

    def _on_search(self) -> None:
        if not self._ensure_auth():
            return

        lang = _lang()
        query = self.search_edit.text().strip()

        if not query:
            self._hide_search_popup()
            return

        # Если запрос уже в полёте — выполним последний введённый позже.
        if self._search_worker is not None:
            self._pending_search_query = query
            return

        self._set_status(tr("Searching...", lang))
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).search_users(query),
            lambda users, q=query: self._on_search_success(users, q),
        )
        self._search_worker = worker
        worker.start()

    def _on_search_success(
        self, users: list[dict[str, Any]], query: str
    ) -> None:
        # Пока запрос летел, пользователь мог изменить строку поиска.
        if query != self.search_edit.text().strip():
            return
        self._search_results = users
        if users:
            self._set_status("")
            self._populate_search_popup()
        else:
            self.search_popup.clear()
            self._hide_search_popup()
            self._set_status(tr("No users found", _lang()), error=True)

    def _send_request(
        self, user_id: int, button: QPushButton | None = None
    ) -> None:
        if not self._ensure_auth() or self._action_worker is not None:
            return

        lang = _lang()
        self._set_status(tr("Sending request...", lang))
        if button is not None:
            button.setEnabled(False)
        token = self._token()
        worker = self._prepare_worker(
            lambda: ApiClient(token=token).send_friend_request(user_id),
            self._on_request_sent,
        )
        if button is not None:
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
            # CHANGED: выполняем поиск, отложенный во время запроса.
            if self._pending_search_query is not None:
                self._pending_search_query = None
                QTimer.singleShot(0, self._on_search)
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
