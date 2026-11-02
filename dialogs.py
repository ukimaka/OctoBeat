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

"""Публичный фасад диалогов и делегатов плейлистов."""

from bulk_dialogs import (
    BulkAddDialog,
    _BulkListWidget,
    _BulkTrackDelegate,
)
from dialog_base import (
    ICON_RENDER_SIZE,
    ICONS_DIR,
    CustomConfirmDialog,
    CustomInputDialog,
    DimmedFileDialog,
    DimmedProgressDialog,
    _CUSTOM_DIALOG_QSS_TEMPLATE,
    _CustomTitleBar,
    _DimmedDialog,
    _FramelessDialog,
    _custom_dialog_qss,
    _dialog_lang,
    _mix_color,
    _rgba,
    colored_icon,
    colored_pixmap,
)
from playlist_widgets import PlaylistCoverDelegate
