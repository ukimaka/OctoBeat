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

"""Слежение за папкой музыки и точечный авто-скан новых файлов.

``QFileSystemWatcher`` не умеет рекурсию, поэтому здесь поддерживается
собственный набор каталогов: корень плюс все подпапки. При появлении новой
папки watcher сразу ставит под наблюдение и её поддерево, а наверх отдаёт
только изменившиеся каталоги/файлы — не всю библиотеку.

События копирования приходят пачками, поэтому сканирование запускается
после «тишины» длиной ``debounce_ms`` (по умолчанию 2.5 с).
"""

import os
from pathlib import Path

from PyQt5.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal

from qt_diagnostics import note
from workers import AUDIO_EXTS

DEFAULT_DEBOUNCE_MS = 2500
DEFAULT_MAX_WATCHED_DIRS = 2048


class MusicFolderWatcher(QObject):
    """Рекурсивно следит за папкой музыки и сообщает, что сканировать."""

    # dict: {"folders": [пути для рекурсивного скана],
    #        "files":   [отдельные новые/изменённые аудиофайлы]}
    scan_requested = pyqtSignal(object)

    def __init__(
        self,
        root,
        parent=None,
        debounce_ms=DEFAULT_DEBOUNCE_MS,
        max_watched_dirs=DEFAULT_MAX_WATCHED_DIRS,
    ):
        super().__init__(parent)
        self._root = None
        self._max_watched_dirs = max(1, int(max_watched_dirs))
        self._limit_warned = False
        self._watched_dirs = {}
        self._pending_dirs = set()
        self._pending_files = set()

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watcher.fileChanged.connect(self._on_file_changed)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(max(100, int(debounce_ms)))
        self._debounce.timeout.connect(self._emit_scan)

        self.set_root(root)

    # ------------------------------------------------------------------
    #  Публичный API
    # ------------------------------------------------------------------
    @property
    def root(self):
        return self._root

    @property
    def watched_dir_count(self):
        return len(self._watched_dirs)

    def set_root(self, root):
        """Переключает наблюдение на новую корневую папку."""
        new_root = (
            os.path.abspath(os.path.expanduser(str(root))) if root else None
        )
        old_key = self._key(self._root) if self._root else None
        if new_root is not None and old_key == self._key(new_root):
            return

        self._debounce.stop()
        self._pending_dirs.clear()
        self._pending_files.clear()
        self._clear_watches()
        self._limit_warned = False
        self._root = new_root

        if new_root and os.path.isdir(new_root):
            self._add_watch_tree(new_root)
            note(
                f"music watcher: root={new_root} "
                f"dirs={len(self._watched_dirs)}"
            )
        elif new_root:
            note(f"music watcher: root does not exist yet: {new_root}")

    def stop(self):
        """Снимает все наблюдения при закрытии приложения."""
        self._debounce.stop()
        self._pending_dirs.clear()
        self._pending_files.clear()
        self._clear_watches()
        self._root = None

    # ------------------------------------------------------------------
    #  События QFileSystemWatcher
    # ------------------------------------------------------------------
    def _on_directory_changed(self, path):
        self._pending_dirs.add(path)
        self._schedule()

    def _on_file_changed(self, path):
        self._pending_files.add(path)
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            self._pending_dirs.add(parent)
        self._schedule()

    def _schedule(self):
        # start() перезапускает таймер: скан стартует только после того,
        # как копирование действительно закончилось.
        self._debounce.start()

    def _emit_scan(self):
        if not self._root or not os.path.isdir(self._root):
            return
        targets = self._collect_scan_targets()
        if targets["folders"] or targets["files"]:
            self.scan_requested.emit(targets)

    # ------------------------------------------------------------------
    #  Вычисление целей скана
    # ------------------------------------------------------------------
    def _collect_scan_targets(self):
        previous_known = set(self._watched_dirs)
        folder_targets = {}
        file_targets = {}

        pending_dirs = list(self._pending_dirs)
        pending_files = list(self._pending_files)
        self._pending_dirs.clear()
        self._pending_files.clear()

        for raw in pending_dirs:
            path = os.path.abspath(str(raw))
            key = self._key(path)
            if not os.path.isdir(path):
                self._watched_dirs.pop(key, None)
                continue

            # Совершенно новый каталог (или его ещё не успели добавить в
            # наблюдение) — сканируем рекурсивно целиком.
            if key not in previous_known:
                folder_targets[key] = path
                continue

            # Известный каталог: проверяем только его прямых детей.
            # Изменения внутри старых подпапок придут своим событием.
            current_children = set()
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                suffix = Path(entry.name).suffix.lower()
                                if suffix in AUDIO_EXTS:
                                    file_targets[self._key(entry.path)] = (
                                        entry.path
                                    )
                            elif entry.is_dir(follow_symlinks=False):
                                child = os.path.abspath(entry.path)
                                child_key = self._key(child)
                                current_children.add(child_key)
                                if child_key not in previous_known:
                                    folder_targets[child_key] = child
                        except OSError:
                            continue
            except OSError:
                continue

            # Удалённую/переименованную подпапку забываем. Если её создадут
            # снова, следующее событие родителя распознает её как новую.
            for known_key in list(self._watched_dirs):
                if (
                    os.path.dirname(known_key) == key
                    and known_key not in current_children
                ):
                    self._watched_dirs.pop(known_key, None)

        for raw in pending_files:
            path = os.path.abspath(str(raw))
            if (
                os.path.isfile(path)
                and Path(path).suffix.lower() in AUDIO_EXTS
                and self._inside_root(path)
            ):
                file_targets[self._key(path)] = path

        # Ставим новые каталоги под наблюдение до запуска скана: если
        # копирование ещё идёт, следующие события попадут в watcher.
        for path in folder_targets.values():
            self._add_watch_tree(path)

        return {
            "folders": sorted(folder_targets.values(), key=str.casefold),
            "files": sorted(file_targets.values(), key=str.casefold),
        }

    # ------------------------------------------------------------------
    #  Набор наблюдаемых каталогов
    # ------------------------------------------------------------------
    def _add_watch_tree(self, root):
        """Добавляет ``root`` и всё его поддерево в QFileSystemWatcher."""
        stack = [os.path.abspath(str(root))]
        to_add = []

        while stack:
            path = stack.pop()
            key = self._key(path)
            if key in self._watched_dirs:
                continue
            if not os.path.isdir(path):
                continue
            if len(self._watched_dirs) >= self._max_watched_dirs:
                if not self._limit_warned:
                    self._limit_warned = True
                    note(
                        "music watcher: directory limit reached "
                        f"({self._max_watched_dirs}); deep folders are "
                        "not watched"
                    )
                break

            self._watched_dirs[key] = path
            to_add.append(path)
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue

        if to_add:
            failed = self._watcher.addPaths(to_add)
            for path in failed:
                self._watched_dirs.pop(self._key(path), None)

    def _clear_watches(self):
        if self._watched_dirs:
            try:
                self._watcher.removePaths(list(self._watched_dirs.values()))
            except RuntimeError:
                pass
        self._watched_dirs.clear()

    def _inside_root(self, path):
        if not self._root:
            return False
        root_key = self._key(self._root)
        key = self._key(path)
        return key == root_key or key.startswith(root_key + os.sep)

    @staticmethod
    def _key(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))
