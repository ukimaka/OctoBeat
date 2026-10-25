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

"""Импорт музыки, CSV, YouTube и удалённых плейлистов."""

from pathlib import Path

from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
)

import workers
from api_client import ApiClient, ApiError
from dialogs import CustomConfirmDialog
from translations import tr


class _RemotePlaylistDownloadWorker(QObject):
    """Скачивает все треки удалённого плейлиста через yt-dlp."""

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, playlist_id: int, token: str | None, music_folder):
        super().__init__()
        self.playlist_id = playlist_id
        self.token = token
        self.music_folder = music_folder

    def run(self) -> None:
        from youtube_worker import YoutubeWorker

        try:
            data = ApiClient(token=self.token).get_playlist(
                self.playlist_id
            )
        except ApiError as exc:
            self.error.emit(str(exc))
            self.finished.emit([])
            return

        tracks = data.get("tracks") or []
        if not tracks:
            self.finished.emit([])
            return

        paths: list[str] = []
        failures: list[str] = []
        total = len(tracks)
        for index, track in enumerate(tracks):
            if QThread.currentThread().isInterruptionRequested():
                break
            source = str(track.get("source_id") or "").strip()
            if not source:
                continue
            if not source.lower().startswith(("http://", "https://")):
                source = f"https://www.youtube.com/watch?v={source}"

            self.progress.emit(index, total)
            worker = YoutubeWorker(source, self.music_folder)
            downloaded: list[str] = []
            errors: list[str] = []
            worker.finished.connect(downloaded.append)
            worker.error.connect(errors.append)
            worker.run()
            paths.extend(downloaded)
            failures.extend(errors)

        self.progress.emit(total, total)
        if not paths and failures:
            self.error.emit(failures[-1])
        self.finished.emit(paths)


class ImportFlow(QObject):
    """Все сценарии импорта и общий прогресс-диалог."""

    finished = pyqtSignal()
    library_changed = pyqtSignal()

    def __init__(
        self,
        parent_window,
        settings,
        music_folder,
        sync_library,
        parent=None,
    ):
        super().__init__(parent if parent is not None else parent_window)
        self.parent_window = parent_window
        self.settings = settings
        self.music_folder = Path(music_folder)
        self.sync_library = sync_library

        self._progress_dialog = None
        self._worker = None
        self._thread = None

    # ------------------------------------------------------------------
    #  Публичные сценарии
    # ------------------------------------------------------------------
    def import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self.parent_window,
            tr(
                "Select music files to import",
                self.settings.value("language", "en"),
            ),
            str(Path.home()),
            "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a);;All files (*)",
        )
        if not files:
            return
        self._run_worker_with_progress(
            workers.ImportWorker(files, self.music_folder),
            title=tr(
                "Importing files", self.settings.value("language", "en")
            ),
            on_finished=self._on_import_finished,
        )

    def import_csv(self) -> None:
        """Импорт плейлиста Spotify из CSV-файла Exportify."""
        lang = self.settings.value("language", "en")
        path, _ = QFileDialog.getOpenFileName(
            self.parent_window,
            tr("Select CSV file", lang),
            str(Path.home()),
            "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return
        self._run_worker_with_progress(
            workers.CsvImportWorker(path, self.music_folder),
            title=tr("Import from CSV", lang),
            on_finished=self._on_csv_import_finished,
        )

    def rescan(self) -> None:
        self._run_worker_with_progress(
            workers.RescanWorker(),
            title=tr(
                "Updating track info", self.settings.value("language", "en")
            ),
            on_finished=self._on_rescan_finished,
        )

    def youtube_dialog(self) -> None:
        from youtube_dialog import YoutubeDialog

        dialog = YoutubeDialog(
            self.parent_window, target_folder=self.music_folder
        )
        if dialog.exec_() != QDialog.Accepted:
            self.finished.emit()
            return

        path = dialog.downloaded_path
        if not path:
            self.finished.emit()
            return

        self.sync_library()
        self.library_changed.emit()
        self.finished.emit()

    def download_remote_playlist(self, playlist_id: int) -> None:
        """Скачивает все треки чужого публичного плейлиста."""
        worker = _RemotePlaylistDownloadWorker(
            playlist_id,
            self._token(),
            self.music_folder,
        )
        title = tr("Download", self.settings.value("language", "en"))
        self._run_worker_with_progress(
            worker, title, self._on_downloads_finished
        )

    # ------------------------------------------------------------------
    #  Завершение операций
    # ------------------------------------------------------------------
    def _on_csv_import_finished(self, added, failed):
        self.library_changed.emit()
        lang = self.settings.value("language", "en")
        print(f"[csv-import] added: {added}, failed: {failed}")

        lines = []
        if added:
            lines.append(tr("Tracks added: {n}", lang).format(n=added))
        if failed:
            lines.append(f"{tr('Error', lang)}: {failed}")
        if not lines:
            lines.append(tr("Nothing added", lang))

        CustomConfirmDialog.information(
            self.parent_window,
            tr("CSV import complete", lang),
            "\n".join(lines),
        )
        self.finished.emit()

    def _on_import_finished(
        self, added, already, name_taken, failed, conflicts
    ):
        self.library_changed.emit()
        print(f"[import] added: {added}, already: {already}, "
              f"name_taken: {name_taken}, failed: {failed}")

        lines = []
        if added:
            lines.append(f"✅ Добавлено: {added}")
        if already:
            lines.append(f"ℹ️  Уже в библиотеке: {already}")
        if name_taken:
            lines.append(f"⚠️  Имя занято: {name_taken}")
            if conflicts:
                preview = ", ".join(conflicts[:5])
                if len(conflicts) > 5:
                    preview += f" и ещё {len(conflicts) - 5}"
                lines.append(f"   ({preview})")
        if failed:
            lines.append(f"❌ Ошибок: {failed}")

        if not lines:
            lines.append(
                tr(
                    "Nothing added",
                    self.settings.value("language", "en"),
                )
            )

        CustomConfirmDialog.information(
            self.parent_window,
            tr(
                "Import complete",
                self.settings.value("language", "en"),
            ),
            "\n".join(lines),
        )
        self.finished.emit()

    def _on_rescan_finished(
        self, meta_updated, loudness_processed, loudness_failed
    ):
        self.library_changed.emit()
        print(f"[rescan] metadata: {meta_updated}, "
              f"loudness: {loudness_processed} ok / {loudness_failed} failed")
        lines = [f"Metadata обновлено: {meta_updated}"]
        if loudness_processed or loudness_failed:
            lines.append(f"Loudness обработано: {loudness_processed}")
            if loudness_failed:
                lines.append(f"Loudness ошибок: {loudness_failed}")
        CustomConfirmDialog.information(
            self.parent_window,
            tr(
                "Update complete",
                self.settings.value("language", "en"),
            ),
            "\n".join(lines),
        )
        self.finished.emit()

    def _on_downloads_finished(self, paths) -> None:
        if paths:
            self.sync_library()
            self.library_changed.emit()
        self.finished.emit()

    # ------------------------------------------------------------------
    #  Внутренние помощники
    # ------------------------------------------------------------------
    def _token(self) -> str | None:
        token = self.settings.value("api_token")
        if isinstance(token, str) and token.strip():
            return token
        return None

    def _run_worker_with_progress(self, worker, title, on_finished):
        cancel_text = tr("Cancel", self.settings.value("language", "en"))
        self._progress_dialog = QProgressDialog(
            title, cancel_text, 0, 100, self.parent_window
        )
        self._progress_dialog.setWindowTitle(title)
        self._progress_dialog.setWindowModality(Qt.WindowModal)
        self._progress_dialog.setMinimumDuration(0)
        self._progress_dialog.setValue(0)

        thread = QThread()
        worker.moveToThread(thread)

        def _on_progress(done, total):
            percent = int(done * 100 / total) if total else 0
            self._progress_dialog.setValue(percent)

        def _cleanup():
            thread.quit()
            thread.wait()

        worker.progress.connect(_on_progress)
        worker.finished.connect(on_finished)
        worker.finished.connect(_cleanup)
        if hasattr(worker, "error"):
            err_title = tr(
                "Error", self.settings.value("language", "en")
            )
            worker.error.connect(
                lambda msg: QMessageBox.warning(
                    self.parent_window, err_title, msg
                )
            )

        thread.started.connect(worker.run)
        self._progress_dialog.canceled.connect(
            lambda: thread.requestInterruption()
        )

        self._worker = worker
        self._thread = thread
        thread.start()
