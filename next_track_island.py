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

"""Виджет «Next in queue» для тулбара библиотеки."""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QSizePolicy, QWidget,
)

from translations import tr
from ui_common import ElidedLabel


class NextTrackIsland(QWidget):
    """Островок «Далее в очереди»: подпись, обложка, название и артист."""

    def __init__(self, settings, icons, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.icons = icons

        lang = self.settings.value("language", "en")
        self.setObjectName("nextTrackContainer")
        self.hide()

        self.next_caption_label = QLabel(tr("Next in queue", lang))
        self.next_caption_label.setObjectName("nextTrackCaption")

        card = QWidget()
        card.setObjectName("nextTrackIsland")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedHeight(34)
        # Гибкая ширина в пределах min/max: карточка растёт под содержимое,
        # но не раздувается на весь экран.
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card.setMaximumWidth(350)
        card.setMinimumWidth(150)

        self.next_cover_label = QLabel()
        self.next_cover_label.setFixedSize(28, 28)

        # Текст обрезается самим ElidedLabel под текущую ширину,
        # поэтому здесь правит раскладка, а не ручной расчёт многоточия.
        self.next_title_label = ElidedLabel("—")
        self.next_title_label.setObjectName("nextTrackTitle")
        self.next_title_label.setWordWrap(False)
        self.next_title_label.setMinimumWidth(50)
        self.next_title_label.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )

        self.next_artist_label = ElidedLabel("—")
        self.next_artist_label.setObjectName("nextTrackArtist")
        self.next_artist_label.setMinimumWidth(60)
        self.next_artist_label.setSizePolicy(
            QSizePolicy.Preferred, QSizePolicy.Preferred
        )
        self.next_artist_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(6, 3, 10, 3)
        card_layout.setSpacing(8)
        card_layout.addWidget(self.next_cover_label)
        card_layout.addWidget(self.next_title_label, 0)
        card_layout.addWidget(self.next_artist_label, 0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.next_caption_label, 0, Qt.AlignVCenter)
        layout.addWidget(card, 0, Qt.AlignVCenter)

        self.next_card = card
        self.setToolTip(tr("Next in queue", lang))

    def set_track(self, title, artist, cover_path):
        """Показывает следующий трек и его обложку."""
        self.next_title_label.setText(title)
        self.next_artist_label.setText(artist)
        self.next_cover_label.setPixmap(
            self.icons.cover_pixmap(cover_path, 28)
        )
        self.show()

    def clear(self):
        self.hide()

    def apply_theme(self):
        """Обновляет подпись/подсказку после смены темы или языка."""
        lang = self.settings.value("language", "en")
        self.next_caption_label.setText(tr("Next in queue", lang))
        self.setToolTip(tr("Next in queue", lang))
