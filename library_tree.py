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

"""Дерево библиотеки с Drag & Drop и кликом по иконке Play."""

from PyQt5.QtCore import QItemSelectionModel, Qt, pyqtSignal
from PyQt5.QtWidgets import QTreeWidget

import db
from delegates import TrackDelegate


class LibraryTreeWidget(QTreeWidget):
    """Дерево библиотеки: папки — корневые элементы, треки — их дети или корень.

    Обрабатывает Drag & Drop: после визуального перетаскивания силами Qt
    дерево синхронизируется с БД (folder_id треков).
    """

    play_requested = pyqtSignal(object)  # QTreeWidgetItem с треком
    # Дерево изменило folder_id треков в БД (после drop).
    library_changed = pyqtSignal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self._sync_tree_to_db()
        self.library_changed.emit()

    def mouseReleaseEvent(self, event):
        """Одиночный клик по иконке Play слева запускает трек."""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None:
                data = item.data(0, Qt.UserRole)
                is_track = isinstance(data, dict) and not data.get("is_folder")
                if is_track and TrackDelegate.is_play_click(
                    event.pos(), self.visualItemRect(item)
                ):
                    self.play_requested.emit(item)
        super().mouseReleaseEvent(event)
        # CHANGED: обычный клик (без Ctrl/Shift) не оставляет выделение.
        if event.button() == Qt.LeftButton and not (
            event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)
        ):
            self.clearSelection()
        # CHANGED: сбрасываем устаревший hover после клика.
        self.viewport().update()

    def keyPressEvent(self, event):
        # CHANGED: Ctrl+A переключает «выбрать всё / снять выделение».
        if event.key() == Qt.Key_A and event.modifiers() == Qt.ControlModifier:
            total = self.topLevelItemCount() + sum(
                self.topLevelItem(i).childCount()
                for i in range(self.topLevelItemCount())
            )
            if total > 0 and len(self.selectedItems()) >= total:
                self.clearSelection()
            else:
                self.selectAll()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        """Позволяет перетаскивать треки.

        У дерева отключён режим выделения (NoSelection), чтобы клик не
        рисовал системную подсветку, но Qt начинает drag только для
        выделенного элемента. Поэтому трек под курсором помечаем
        выделенным программно: делегат подсветку выделения у треков не
        рисует, так что визуально ничего не меняется.
        """
        # CHANGED: ПКМ не должен визуально выделять трек.
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.pos())
            # Если кликнули по невыделенному треку, сбрасываем старое выделение
            if item is not None and not item.isSelected():
                self.clearSelection()
            # Не вызываем super(), чтобы Qt не рисовал фокус/выделение
            return
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            data = item.data(0, Qt.UserRole) if item is not None else None
            if isinstance(data, dict) and not data.get("is_folder"):
                if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                    # CHANGED: let Qt handle native multi-selection (Ctrl/Shift+click)
                    super().mousePressEvent(event)
                    self.viewport().update()
                    return
                self.selectionModel().select(
                    self.indexFromItem(item),
                    QItemSelectionModel.ClearAndSelect
                    | QItemSelectionModel.Rows,
                )
        super().mousePressEvent(event)
        # CHANGED: force repaint to clear stale hover state
        self.viewport().update()

    def leaveEvent(self, event):
        # CHANGED: clear stale hover state when the mouse leaves the view
        self.viewport().update()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        # CHANGED: view сам отслеживает наведение на иконку мусорки.
        super().mouseMoveEvent(event)
        index = self.indexAt(event.pos())
        delegate = self.itemDelegate()

        if index.isValid() and hasattr(delegate, "get_trash_rect_for_index"):
            trash_rect = delegate.get_trash_rect_for_index(self, index)

            old_index = delegate.hovered_trash_index
            old_rect = delegate.hovered_trash_rect

            if trash_rect and trash_rect.contains(event.pos()):
                delegate.hovered_trash_index = index
                delegate.hovered_trash_rect = trash_rect
            else:
                delegate.hovered_trash_index = None
                delegate.hovered_trash_rect = None

            if (
                old_index != delegate.hovered_trash_index
                or old_rect != delegate.hovered_trash_rect
            ):
                self.viewport().update()
        else:
            if (
                hasattr(delegate, "hovered_trash_index")
                and delegate.hovered_trash_index is not None
            ):
                delegate.hovered_trash_index = None
                delegate.hovered_trash_rect = None
                self.viewport().update()

    def _sync_tree_to_db(self):
        """Приводит folder_id треков в БД в соответствие с деревом."""
        for i in range(self.topLevelItemCount()):
            self._sync_item(self.topLevelItem(i), None)

    def _sync_item(self, item, parent_folder_id):
        if item is None:
            return
        data = item.data(0, Qt.UserRole) or {}

        if data.get("is_folder"):
            # Папка задаёт контекст для всех своих потомков.
            # Qt после внутреннего перемещения может сбросить флаги
            # элемента: папка всегда должна принимать drop.
            item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled
            )
            folder_id = data.get("id")
            for i in range(item.childCount()):
                self._sync_item(item.child(i), folder_id)
            return

        # Трек: сохраняем его папку (parent_folder_id=None — корень)
        track_id = data.get("id")
        if track_id is not None:
            db.move_track_to_folder(track_id, parent_folder_id)

        # Qt при перемещении пересоздаёт элемент и теряет прежние флаги:
        # возвращаем треку «только перетаскиваемый», чтобы его нельзя было
        # случайно вложить внутрь другого трека.
        item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
        )

        # На случай случайного вложения трека в трек — считаем потомков
        # лежащими в той же папке, что и родитель.
        for i in range(item.childCount()):
            self._sync_item(item.child(i), parent_folder_id)
