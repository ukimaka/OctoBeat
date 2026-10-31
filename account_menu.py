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

"""Аватарка в углу вкладок, меню аккаунта и фоновые проверки."""

from PyQt5.QtCore import QObject, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter
from PyQt5.QtWidgets import QMenu, QPushButton, QSizePolicy

import db
from api_client import ApiClient, ApiError
from pixmap_utils import new_pixmap
from profile_ui import _round_avatar_pixmap
from translations import tr
from ui_common import apply_menu_depth


class _TokenCheckWorker(QThread):
    """Проверяет сохранённый токен в фоне, не блокируя запуск приложения."""

    checked = pyqtSignal(bool, str, int)  # ok, username/error, HTTP status

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.token = token

    def run(self) -> None:
        try:
            user = ApiClient(token=self.token, timeout=5).get_me()
        except ApiError as exc:
            self.checked.emit(False, str(exc), exc.status_code or 0)
        except Exception as exc:  # noqa: BLE001 - ошибка не должна ронять старт
            self.checked.emit(False, str(exc), 0)
        else:
            self.checked.emit(True, str(user.get("username", "")), 200)


class AccountMenu(QObject):
    """Управляет глобальной аватаркой и всем, что связано с аккаунтом.

    Класс сам подписывается на сигналы страниц профиля, друзей и настроек,
    поэтому ``MainWindow`` остаётся только композиционным корнем.
    """

    def __init__(
        self,
        parent_window,
        settings,
        tabs,
        friends_page,
        profile_page,
        settings_page,
        icons,
    ):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.settings = settings
        self.tabs = tabs
        self.friends_page = friends_page
        self.profile_page = profile_page
        self.settings_page = settings_page
        self.icons = icons

        self._token_worker = None
        self._friends_menu_action = None

        self.avatar_button = self._build_avatar_button()

        # Фоновая проверка входящих заявок для бейджа в меню аватарки.
        self._notifications_timer = QTimer(self)
        self._notifications_timer.setInterval(30_000)
        self._notifications_timer.timeout.connect(self.check_incoming_requests)

        # Периодическая синхронизация локальной статистики с сервером.
        self._stats_sync_timer = QTimer(self)
        self._stats_sync_timer.setInterval(5 * 60 * 1000)
        self._stats_sync_timer.timeout.connect(self.sync_stats)

        # Страницы сообщают о событиях аккаунта через сигналы.
        self.profile_page.avatar_changed.connect(
            lambda _path: self.update_avatar()
        )
        self.friends_page.auth_expired.connect(self._on_auth_expired)
        self.friends_page.incoming_requests_changed.connect(
            lambda _count: self.update_friends_menu_action()
        )
        self.settings_page.logged_out.connect(self.logout)

    # ------------------------------------------------------------------
    #  Токен и стартовая проверка
    # ------------------------------------------------------------------
    def check_stored_token(self) -> None:
        token = self.settings.value("api_token")
        if not isinstance(token, str) or not token.strip():
            return

        self._token_worker = _TokenCheckWorker(token, self)
        self._token_worker.checked.connect(self._on_stored_token_checked)
        self._token_worker.finished.connect(self._on_token_worker_finished)
        self._token_worker.start()

    def _on_stored_token_checked(
        self, ok: bool, value: str, status_code: int
    ) -> None:
        if ok:
            self.settings.setValue("api_username", value)
            self.profile_page.set_authenticated(value)
            self.settings_page.refresh_auth_state()
            self.update_tooltip()
            self.friends_page.refresh(silent=True)
            self.profile_page.sync_stats_to_server()
        elif status_code == 401:
            # Токен протух или отозван — удаляем его из настроек.
            self._forget_token()
            self.profile_page.reset_auth_button()
            self.settings_page.refresh_auth_state()
            self.update_tooltip()
        else:
            # Сервер недоступен: токен оставляем, но кнопку входа показываем.
            self.profile_page.reset_auth_button()
            self.settings_page.refresh_auth_state()

    def _on_token_worker_finished(self) -> None:
        worker = self._token_worker
        self._token_worker = None
        if worker is not None:
            worker.deleteLater()

    def start_timers(self) -> None:
        self._notifications_timer.start()
        self._stats_sync_timer.start()

    def shutdown(self) -> None:
        if self._token_worker is not None and self._token_worker.isRunning():
            self._token_worker.wait(6000)

    # ------------------------------------------------------------------
    #  Аватарка
    # ------------------------------------------------------------------
    def _build_avatar_button(self):
        """Маленькая круглая аватарка для правого верхнего угла вкладок."""
        self.avatar_button = QPushButton()
        self.avatar_button.setObjectName("globalAvatarButton")
        self.avatar_button.setFlat(True)
        self.avatar_button.setFixedSize(32, 32)
        self.avatar_button.setIconSize(QSize(32, 32))
        # CHANGED: фиксированный размер не должен растягиваться/сжиматься layout'ом.
        self.avatar_button.setSizePolicy(
            QSizePolicy.Fixed, QSizePolicy.Fixed
        )
        self.avatar_button.setCursor(Qt.PointingHandCursor)
        self.avatar_button.setStyleSheet(
            "QPushButton#globalAvatarButton {"
            " border: none; background: transparent; border-radius: 16px;"
            " padding: 0px;"
            "}"
            "QPushButton#globalAvatarButton:hover {"
            " background: rgba(128, 128, 128, 0.2); }"
        )
        self.avatar_button.clicked.connect(self._show_account_menu)

        self.update_avatar()
        self.update_tooltip()
        return self.avatar_button

    def update_avatar(self) -> None:
        """Обновляет аватарку в углу вкладок по локальному профилю."""
        try:
            profile = db.get_profile()
        except Exception:  # noqa: BLE001 - панель не должна ронять окно
            profile = None
        path = profile["avatar_path"] if profile else None
        self.avatar_button.setIcon(QIcon(_round_avatar_pixmap(path, 32)))

    def update_tooltip(self) -> None:
        lang = self.settings.value("language", "en")
        if self.token() is None:
            self.avatar_button.setToolTip(tr("Account", lang))
            return
        username = self.settings.value("api_username")
        self.avatar_button.setToolTip(
            str(username) if username else tr("Account", lang)
        )

    def token(self) -> str | None:
        token = self.settings.value("api_token")
        if isinstance(token, str) and token.strip():
            return token
        return None

    # ------------------------------------------------------------------
    #  Меню аккаунта
    # ------------------------------------------------------------------
    def _show_account_menu(self) -> None:
        lang = self.settings.value("language", "en")
        menu = QMenu(self.parent_window)
        apply_menu_depth(menu)

        profile_action = menu.addAction(
            self.icons.icon("user.svg"), tr("Profile", lang)
        )
        friends_action = menu.addAction(
            self._friends_menu_icon(), self._friends_menu_text()
        )

        logout_action = None
        if self.token() is not None:
            menu.addSeparator()
            logout_action = menu.addAction(tr("Log Out", lang))

        # Держим ссылку, чтобы таймер мог обновить бейдж у открытого меню.
        self._friends_menu_action = friends_action
        try:
            chosen = menu.exec_(
                self.avatar_button.mapToGlobal(
                    self.avatar_button.rect().bottomLeft()
                )
            )
        finally:
            self._friends_menu_action = None

        if chosen is None:
            return
        if chosen is profile_action:
            self.show_user_page(self.profile_page)
            self.profile_page.reload_stats()
        elif chosen is friends_action:
            self.show_user_page(self.friends_page)
            self.friends_page.refresh()
        elif logout_action is not None and chosen is logout_action:
            self.logout()

    def _friends_menu_text(self) -> str:
        return tr("Friends", self.settings.value("language", "en"))

    def _red_dot_icon(self) -> QIcon:
        """Маленький красный кружок для пункта Friends."""
        # Рендерим крупно, чтобы QMenu не растягивал готовый кружок.
        size = 64
        pixmap = new_pixmap(size, size)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#ff4d4d"))
        margin = size * 0.1
        painter.drawEllipse(
            QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
        )
        painter.end()
        return QIcon(pixmap)

    def _friends_menu_icon(self) -> QIcon:
        if self.friends_page.get_incoming_requests_count() > 0:
            return self._red_dot_icon()
        return self.icons.icon("friends.svg")

    def update_friends_menu_action(self) -> None:
        """Обновляет текст и индикатор пункта Friends, если меню открыто."""
        if self._friends_menu_action is not None:
            self._friends_menu_action.setText(self._friends_menu_text())
            self._friends_menu_action.setIcon(self._friends_menu_icon())

    # ------------------------------------------------------------------
    #  Фоновые проверки
    # ------------------------------------------------------------------
    def check_incoming_requests(self) -> None:
        """Фоновое обновление входящих заявок для индикатора в меню."""
        if self.token() is not None:
            self.friends_page.refresh(silent=True)
        self.update_friends_menu_action()

    def sync_stats(self) -> None:
        """Периодически отправляет статистику прослушиваний на сервер."""
        if self.token() is not None:
            self.profile_page.sync_stats_to_server()

    # ------------------------------------------------------------------
    #  Навигация и выход
    # ------------------------------------------------------------------
    def show_user_page(self, page) -> None:
        """Показывает страницу, скрытую из tab bar.

        Виджет мог быть убран через ``removeTab`` — в этом случае возвращаем
        его в стек как невидимую вкладку, чтобы ``setCurrentWidget`` работал.
        """
        if self.tabs.indexOf(page) == -1:
            index = self.tabs.addTab(page, "")
            self.tabs.tabBar().setTabVisible(index, False)
        self.tabs.setCurrentWidget(page)

    def _forget_token(self) -> None:
        self.settings.remove("api_token")
        self.settings.remove("api_username")

    def _on_auth_expired(self) -> None:
        self.logout(switch_to_library=False)

    def logout(self, switch_to_library: bool = True) -> None:
        """Выход из аккаунта: чистим токен и обновляем зависимые виджеты."""
        self._forget_token()
        self.profile_page.reset_auth_button()
        self.friends_page.refresh_auth_state()
        self.settings_page.refresh_auth_state()
        self.update_tooltip()
        if switch_to_library:
            self.tabs.setCurrentIndex(0)
