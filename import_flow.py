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

"""Импорт музыки, CSV и YouTube."""

from pathlib import Path

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QDialog

import workers
from dialogs import CustomConfirmDialog, DimmedProgressDialog
from translations import tr
from qt_diagnostics import hold_worker, note, track_thread
from qt_lifecycle import retire_thread, widget_alive
from ui_common import get_open_file_name, get_open_file_names


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
        self._youtube_dialog = None
        self._progress_depth = 0
        self._finish_pending = None

    # ------------------------------------------------------------------
    #  Публичные сценарии
    # ------------------------------------------------------------------
    def import_files(self) -> None:
        files, _ = get_open_file_names(
            self.parent_window,
            tr(
                "Select music files to import",
                self.settings.value("language", "en"),
            ),
            str(Path.home()),
            "Audio files (*.mp3 *.flac *.ogg *.wav *.m4a *.webm *.opus);;All files (*)",
        )
        if not files:
            return
        self._run_worker_with_progress(
            workers.ImportWorker(files, self.music_folder),
            title=tr(
                "Importing files", self.settings.value("language", "en")
            ),
            on_finished=self._on_import_finished,
            thread_name="import-files",
        )

    def import_csv(self) -> None:
        """Импорт плейлиста Spotify из CSV-файла Exportify."""
        lang = self.settings.value("language", "en")
        path, _ = get_open_file_name(
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
            thread_name="import-csv",
        )

    def rescan(self) -> None:
        note("rescan requested")
        # libVLC must drop the file before the worker rewrites tags/renames
        # it.  Rewriting a file while VLC decodes it can crash the decoder
        # thread (SIGSEGV), and a blocking cross-thread release signal can
        # deadlock the worker.  Release once on the GUI thread instead.
        try:
            self.parent_window.controller.media_player.release()
        except Exception as exc:
            print(f"[rescan] player release failed: {exc}")
        worker = workers.RescanWorker(
            self.settings.value("language", "en")
        )
        self._run_worker_with_progress(
            worker,
            title=tr(
                "Updating track info", self.settings.value("language", "en")
            ),
            on_finished=self._on_rescan_finished,
            thread_name="rescan",
        )

    def youtube_dialog(self) -> None:
        from youtube_dialog import YoutubeDialog

        dialog = YoutubeDialog(
            self.parent_window, target_folder=self.music_folder
        )
        self._youtube_dialog = dialog
        try:
            accepted = dialog.exec_() == QDialog.Accepted
        finally:
            if self._youtube_dialog is dialog:
                self._youtube_dialog = None
        if not accepted:
            self.finished.emit()
            return

        path = dialog.downloaded_path
        if not path:
            self.finished.emit()
            return

        self.sync_library()
        self.library_changed.emit()
        self.finished.emit()

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
        note(
            f"rescan UI finished: meta={meta_updated} "
            f"loudness={loudness_processed} failed={loudness_failed}"
        )
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

    # ------------------------------------------------------------------
    #  Внутренние помощники
    # ------------------------------------------------------------------
    def _stop_current_worker(self) -> None:
        """Просит текущий воркер завершиться (кнопка Cancel/закрытие)."""
        worker = self._worker
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
        if worker is None:
            return
        stop = getattr(worker, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass

    def shutdown(self) -> None:
        """Останавливает импорт/скачивание при закрытии приложения."""
        dialog = self._youtube_dialog
        if dialog is not None:
            try:
                dialog.shutdown()
            except RuntimeError:
                pass
            self._youtube_dialog = None
        self._stop_current_worker()
        thread = self._thread
        self._thread = None
        self._worker = None
        if thread is not None:
            retire_thread(thread, 2000)
        self._close_progress()

    def _close_progress(self, dialog=None) -> None:
        """Закрывает диалог только после завершения текущего setValue().

        QProgressDialog::setValue() для модального диалога вызывает
        QApplication::processEvents(). Внутри него может прийти finished,
        который раньше закрывал/удалял диалог прямо посреди setValue() —
        отсюда use-after-free в QProgressBar::maximum(). Поэтому удаление
        откладывается до выхода из самого внешнего setValue().
        """
        if self._progress_depth:
            self._finish_pending = (
                lambda d=dialog: self._close_progress(d)
            )
            return
        if dialog is None:
            dialog = self._progress_dialog
        if self._progress_dialog is dialog:
            self._progress_dialog = None
        if not widget_alive(dialog):
            return
        try:
            dialog.setAutoClose(False)
            dialog.setAutoReset(False)
            dialog.close()
            dialog.deleteLater()
        except RuntimeError:
            pass

    def _run_worker_with_progress(
        self, worker, title, on_finished, thread_name="import-worker"
    ):
        cancel_text = tr("Cancel", self.settings.value("language", "en"))
        dialog = DimmedProgressDialog(
            title, cancel_text, 0, 100, self.parent_window
        )
        self._progress_dialog = dialog
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)

        thread = QThread()
        track_thread(thread, thread_name)
        worker.moveToThread(thread)
        hold_worker(thread, worker, f"{thread_name}-worker")
        thread.finished.connect(worker.deleteLater)

        def _on_progress(done, total):
            if self._progress_dialog is not dialog or not widget_alive(dialog):
                return
            # Не входим повторно в processEvents() из QProgressDialog:
            # события, пришедшие во вложенном цикле, обновят значение
            # следующим штатным сигналом.
            if self._progress_depth:
                return
            percent = int(done * 100 / total) if total else 0
            self._progress_depth += 1
            try:
                dialog.setValue(percent)
            except RuntimeError:
                pass
            finally:
                self._progress_depth -= 1
                if self._progress_depth == 0:
                    pending = self._finish_pending
                    self._finish_pending = None
                    if pending is not None:
                        pending()

        def _on_status(text):
            if self._progress_dialog is not dialog or not widget_alive(dialog):
                return
            try:
                dialog.setLabelText(text)
            except RuntimeError:
                pass

        finish_state = {"done": False}

        def _finish_operation(*args):
            # finished мог быть доставлен внутри dialog.setValue().
            # Замыкание должно сохранить аргументы сигнала: у разных
            # воркеров finished() имеет разный набор параметров.
            if self._progress_depth:
                self._finish_pending = (
                    lambda: _finish_operation(*args)
                )
                return
            if finish_state["done"]:
                return
            finish_state["done"] = True
            try:
                worker.progress.disconnect(_on_progress)
            except (TypeError, RuntimeError):
                pass
            if hasattr(worker, "status"):
                try:
                    worker.status.disconnect(_on_status)
                except (TypeError, RuntimeError):
                    pass
            if self._thread is thread:
                self._thread = None
                self._worker = None
            self._close_progress(dialog)
            retire_thread(thread, 2000)
            on_finished(*args)

        worker.progress.connect(_on_progress)
        if hasattr(worker, "status"):
            worker.status.connect(_on_status)
        # Cleanup и completion выполняются одной функцией, чтобы между
        # удалением диалога и открытием модального окна не было гонки.
        worker.finished.connect(_finish_operation)
        if hasattr(worker, "error"):
            err_title = tr(
                "Error", self.settings.value("language", "en")
            )
            worker.error.connect(
                lambda msg: CustomConfirmDialog.information(
                    self.parent_window, err_title, msg
                )
            )

        thread.started.connect(worker.run)
        dialog.canceled.connect(self._stop_current_worker)

        self._worker = worker
        self._thread = thread
        thread.start()
