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

    def mousePressEvent(self, event):
        """Позволяет перетаскивать треки.

        У дерева отключён режим выделения (NoSelection), чтобы клик не
        рисовал системную подсветку, но Qt начинает drag только для
        выделенного элемента. Поэтому трек под курсором помечаем
        выделенным программно: делегат подсветку выделения у треков не
        рисует, так что визуально ничего не меняется.
        """
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            data = item.data(0, Qt.UserRole) if item is not None else None
            if isinstance(data, dict) and not data.get("is_folder"):
                self.selectionModel().select(
                    self.indexFromItem(item),
                    QItemSelectionModel.ClearAndSelect
                    | QItemSelectionModel.Rows,
                )
        super().mousePressEvent(event)

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
