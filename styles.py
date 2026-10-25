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

"""Тёмная и светлая темы (QSS) для приложения."""

DARK_THEME = """
* {
    color: #ffffff;
    font-family: sans-serif;
    font-size: 13px;
}

QMainWindow, QWidget, QDialog {
    background-color: #121212;
}

QTabWidget::pane {
    border: none;
    background-color: #121212;
    margin-top: 4px;
}

QTabBar::tab {
    background: transparent;
    color: #b3b3b3;
    padding: 6px 14px;
    border: none;
}

QTabBar::tab:selected {
    color: #ffffff;
}

QTabBar::tab:hover {
    background: rgba(255, 255, 255, 0.05);
}

QListWidget {
    background-color: #181818;
    border: none;
    outline: none;
    selection-background-color: transparent;
    selection-color: inherit;
}

QListWidget::item {
    padding: 6px 8px;
}

QTreeView, QTreeWidget {
    outline: none;
    border: none;
    show-decoration-selected: 0;
}

QTreeView::item:focus, QTreeView::item:selected, QTreeView::item:hover {
    outline: none;
    border: none;
}

QTreeView::item:selected, QTreeView::item:focus,
QTreeWidget::item:selected, QListView::item:selected {
    background: transparent;
    outline: none;
    border: none;
    selection-background-color: transparent;
    selection-color: inherit;
}

QLineEdit, QComboBox {
    background-color: #181818;
    border: none;
    border-radius: 4px;
    padding: 4px 8px;
    color: #ffffff;
}

QLineEdit:focus, QComboBox:focus {
    background-color: #202020;
}

QLineEdit:hover, QComboBox:hover {
    border: 1px solid #5151ab;
}

QWidget#playlistDetail {
    background: transparent;
}

QTextEdit#playlistDescription {
    background: transparent;
    border: none;
    color: #ffffff;
    font-size: 13px;
    padding: 0;
}

QTextEdit#playlistDescription:focus {
    background: transparent;
    border: none;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QComboBox QAbstractItemView {
    background-color: #181818;
    border: none;
    outline: none;
    selection-background-color: #282828;
    selection-color: #ffffff;
}

QPushButton {
    background: transparent;
    border: none;
    padding: 4px;
}

QPushButton:hover {
    background: rgba(255, 255, 255, 0.1);
    border-radius: 6px;
}

QLabel {
    background: transparent;
}

QMenu {
    background-color: #282828;
    color: #ffffff;
    border: none;
}

QMenu::item {
    padding: 6px 24px 6px 24px;
    background: transparent;
}

QMenu::item:selected {
    background-color: rgba(255, 255, 255, 0.1);
}

QSlider::groove:horizontal {
    height: 4px;
    background: transparent;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #5151ab;
    border-radius: 2px;
    height: 4px;
}

QSlider::add-page:horizontal {
    background: #282828;
    border-radius: 2px;
    height: 4px;
}

QSlider::handle:horizontal {
    background: #ffffff;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}

QSlider::handle:horizontal:hover {
    background: #5151ab;
    width: 14px;
    margin: -6px 0;
}

QProgressDialog {
    background-color: #121212;
}

QScrollBar:vertical {
    background: #121212;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #282828;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QToolTip {
    background-color: #282828;
    color: #ffffff;
    border: 1px solid #5151ab;
    padding: 4px;
    border-radius: 4px;
}

QLabel#currentTrack {
    color: #ffffff;
}

QLabel#contextLabel {
    color: #8a8a8a;
}

QWidget#nextTrackIsland {
    background-color: rgba(255, 255, 255, 0.06);
    border-radius: 8px;
}

QLabel#nextTrackCaption {
    color: #8a8a8a;
    font-size: 11px;
}

QLabel#nextTrackTitle {
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
}

QLabel#nextTrackArtist {
    color: #8a8a8a;
    font-size: 11px;
}

QTextBrowser#lyricsView {
    background: transparent;
    border: none;
    color: #8a8a8a;
    padding: 6px 14px;
}

QScrollBar#profileScrollBar:vertical {
    background: #121212;
    width: 6px;
    margin: 2px 0;
}

QScrollBar#profileScrollBar::handle:vertical {
    background: #3e3e3e;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar#profileScrollBar::handle:vertical:hover {
    background: #5151ab;
}

QScrollBar#profileScrollBar::add-line:vertical,
QScrollBar#profileScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar#profileScrollBar::add-page:vertical,
QScrollBar#profileScrollBar::sub-page:vertical {
    background: transparent;
}
"""


LIGHT_THEME = """
* {
    color: #000000;
    font-family: sans-serif;
    font-size: 13px;
}

QMainWindow, QWidget, QDialog {
    background-color: #ffffff;
}

QTabWidget::pane {
    border: none;
    background-color: #ffffff;
    margin-top: 4px;
}

QTabBar::tab {
    background: transparent;
    color: #555555;
    padding: 6px 14px;
    border: none;
}

QTabBar::tab:selected {
    color: #000000;
}

QTabBar::tab:hover {
    background: rgba(0, 0, 0, 0.05);
}

QListWidget {
    background-color: #f5f5f5;
    border: none;
    outline: none;
    selection-background-color: transparent;
    selection-color: inherit;
}

QListWidget::item {
    padding: 6px 8px;
}

QTreeView, QTreeWidget {
    outline: none;
    border: none;
    show-decoration-selected: 0;
}

QTreeView::item:focus, QTreeView::item:selected, QTreeView::item:hover {
    outline: none;
    border: none;
}

QTreeView::item:selected, QTreeView::item:focus,
QTreeWidget::item:selected, QListView::item:selected {
    background: transparent;
    outline: none;
    border: none;
    selection-background-color: transparent;
    selection-color: inherit;
}

QLineEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    padding: 4px 8px;
    color: #000000;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #999999;
}

QLineEdit:hover, QComboBox:hover {
    border: 1px solid #5151ab;
}

QWidget#playlistDetail {
    background: transparent;
}

QTextEdit#playlistDescription {
    background: transparent;
    border: none;
    color: #000000;
    font-size: 13px;
    padding: 0;
}

QTextEdit#playlistDescription:focus {
    background: transparent;
    border: none;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    outline: none;
    selection-background-color: #e0e0e0;
    selection-color: #000000;
}

QPushButton {
    background: transparent;
    border: none;
    padding: 4px;
}

QPushButton:hover {
    background: rgba(0, 0, 0, 0.08);
    border-radius: 6px;
}

QLabel {
    background: transparent;
}

QMenu {
    background-color: #ffffff;
    color: #000000;
    border: none;
}

QMenu::item {
    padding: 6px 24px 6px 24px;
    background: transparent;
}

QMenu::item:selected {
    background-color: #e0e0e0;
}

QSlider::groove:horizontal {
    height: 4px;
    background: transparent;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #5151ab;
    border-radius: 2px;
    height: 4px;
}

QSlider::add-page:horizontal {
    background: #cccccc;
    border-radius: 2px;
    height: 4px;
}

QSlider::handle:horizontal {
    background: #000000;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}

QSlider::handle:horizontal:hover {
    background: #5151ab;
    width: 14px;
    margin: -6px 0;
}

QProgressDialog {
    background-color: #ffffff;
}

QScrollBar:vertical {
    background: #ffffff;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #cccccc;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QToolTip {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #cccccc;
    padding: 4px;
    border-radius: 4px;
}

QLabel#currentTrack, QLabel#contextLabel {
    color: #000000;
}

QWidget#nextTrackIsland {
    background-color: rgba(0, 0, 0, 0.05);
    border-radius: 8px;
}

QLabel#nextTrackCaption {
    color: #8a8a8a;
    font-size: 11px;
}

QLabel#nextTrackTitle {
    color: #000000;
    font-size: 12px;
    font-weight: 600;
}

QLabel#nextTrackArtist {
    color: #777777;
    font-size: 11px;
}

QMenu::item:selected {
    background-color: #e0e0e0;
}

QScrollBar:vertical {
    background: #ffffff;
}

QScrollBar::handle:vertical {
    background: #cccccc;
}

QTextBrowser#lyricsView {
    background: transparent;
    border: none;
    color: #777777;
    padding: 6px 14px;
}

QScrollBar#profileScrollBar:vertical {
    background: #f5f5f5;
    width: 6px;
    margin: 2px 0;
}

QScrollBar#profileScrollBar::handle:vertical {
    background: #c4c4c4;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar#profileScrollBar::handle:vertical:hover {
    background: #5151ab;
}

QScrollBar#profileScrollBar::add-line:vertical,
QScrollBar#profileScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar#profileScrollBar::add-page:vertical,
QScrollBar#profileScrollBar::sub-page:vertical {
    background: transparent;
}
"""
