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

"""Загрузка пользовательских QSS-тем из папки ``themes``.

Темы — обычные файлы ``*.qss``; имя файла без расширения и есть имя темы,
которое хранится в ``QSettings("theme")``. Внутри QSS можно использовать
плейсхолдер ``@ICONS_DIR@`` — при загрузке он заменяется на абсолютный путь
к папке ``icons`` (нужно для кроссплатформенных ``url(...)``).
"""

import os
import re
from pathlib import Path

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

THEMES_DIR = Path(__file__).resolve().parent / "themes"
ICONS_DIR = Path(__file__).resolve().parent / "icons"
DEFAULT_THEME = "dark"


def is_dark_theme(theme_name):
    """Светлая тема — если в имени файла есть ``light`` (напр. soft_light)."""
    return "light" not in str(theme_name or DEFAULT_THEME).lower()


DEFAULT_ACCENT = "#5151ab"
_ACCENT_MARKER_RE = re.compile(r"@accent:\s*(#[0-9a-fA-F]{3,8})")
_ACCENT_TAB_RE = re.compile(
    r"QTabBar::tab:selected\s*\{[^}]*?border-top:[^;]*?(#[0-9a-fA-F]{3,8})",
    re.S,
)
_ACCENT_NAV_RE = re.compile(
    r"#settingsNav::item:selected\s*\{[^}]*?background-color:\s*(#[0-9a-fA-F]{3,8})",
    re.S,
)


def theme_accent(theme_name):
    """Акцентный цвет темы.

    Ищем маркер ``/* @accent: #rrggbb */`` в файле темы, затем цвет
    подчёркивания активной вкладки, затем фон выбранного пункта настроек.
    Если ничего не найдено — фирменный фиолетовый OctoBeat.
    """
    name = str(theme_name or DEFAULT_THEME)
    path = THEMES_DIR / f"{name}.qss"
    if not path.is_file():
        path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        qss = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_ACCENT
    for regex in (_ACCENT_MARKER_RE, _ACCENT_TAB_RE, _ACCENT_NAV_RE):
        match = regex.search(qss)
        if match:
            return match.group(1)
    return DEFAULT_ACCENT

# Жёсткая база для наших кастомных элементов. Применяется ДО темы и
# защищает интерфейс от сторонних .qss: убирает системные рамки, синие
# фокусные обводки и фон, который тема могла бы навязать панелям.
BASE_QSS = """
#globalAvatarButton,
#settingsNav,
#playlistDetail,
#nextTrackContainer,
#nextTrackIsland,
#bbRoot,
#bbSplitter,
#bbTool,
#bbClose,
#bbTitle,
#bbHint,
#bbEditor,
#bbPreview,
#bbSave,
#bbCancel,
#profileScrollBar,
#profileBackButton,
#profileNickname,
#profileStatusLabel,
#profileAuthButton,
#profileDescription,
#playlistCard,
#remotePlaylistCard,
#overlayLyricsView,
#overlayCloseButton,
#karaokeView,
#karaokeCloseButton,
#trimTitle,
#trimHint,
#trimTime,
#trimPlay,
#currentTrack,
#contextLabel,
#nextTrackCaption,
#nextTrackTitle,
#nextTrackArtist,
#lyricsView,
#cdRoot,
#cdTitle,
#cdMessage,
#cdHint,
#cdClose,
#cdInput,
#cdBulkList,
#cdConfirm,
#cdCancel {
    border: none;
}

/* Панели (заголовок/плеер) намеренно не входят в жёсткий список выше:
   их фон-градиент и тонкую границу задаёт каждая тема (.qss). */
#globalAvatarButton {
    background: transparent;
    border: none;
}

QTabWidget::pane {
    border: none;
}

/* Вкладки: убираем любые рамки у обычного и наведённого состояния
   (иначе сторонние темы рисуют белые полосы), активную подчёркиваем
   цветом акцента текущей темы через palette(highlight). */
QTabBar::tab {
    border: none;
}
QTabBar::tab:hover {
    border: none;
}
QTabBar::tab:selected {
    border: none;
    border-top: 2px solid palette(highlight);
}

/* Settings navigation — цвета берутся из каждой темы (.qss).
   Здесь только жёсткие правила, которые не должны зависеть от темы. */
#settingsNav {
    border: none;
    outline: none;
    padding: 8px;
}
#settingsNav::item {
    padding: 9px 14px;
    border-radius: 6px;
}
#settingsNav::item:selected {
    /* palette(highlight) подхватывает акцент активной QSS-темы */
    background-color: palette(highlight);
    color: palette(highlighted-text);
}

QTreeView, QListView {
    border: none;
    outline: none;
}
"""


def available_themes():
    """Имена доступных тем (файлы ``themes/*.qss``), отсортированные."""
    if not THEMES_DIR.is_dir():
        return []
    return sorted(path.stem for path in THEMES_DIR.glob("*.qss"))


_URL_RE = re.compile(r"""url\(\s*([\"']?)([^)\"']+)\1\s*\)""")


def _resolve_urls(qss):
    """Делает относительные пути в url(...) абсолютными от папки themes."""
    def replace(match):
        value = match.group(2)
        if value.startswith(("data:", "http:", "https:", "file:")):
            return match.group(0)
        if os.path.isabs(value):
            return match.group(0)
        absolute = (THEMES_DIR / value).resolve().as_posix()
        return f'url("{absolute}")'

    return _URL_RE.sub(replace, qss)


def load_theme_qss(theme_name):
    """Читает QSS темы и подставляет абсолютные пути к ресурсам."""
    name = str(theme_name or DEFAULT_THEME)
    path = THEMES_DIR / f"{name}.qss"
    if not path.is_file():
        path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        qss = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    qss = qss.replace("@ICONS_DIR@", ICONS_DIR.as_posix())
    return _resolve_urls(qss)


def load_theme(theme_name, app=None):
    """Применяет выбранную тему, а поверх — защитную базу.

    База идёт последней, иначе сторонняя тема (например,
    GentlyColorDarkCyan) своим ``QTabWidget::pane { border: 1px ... }``
    перебивает её и вокруг панелей снова появляются синие рамки.
    """
    theme_qss = load_theme_qss(theme_name)
    qss = theme_qss + "\n" + BASE_QSS if theme_qss else BASE_QSS
    if app is None:
        app = QApplication.instance()
    if app is not None:
        # Акцент темы кладём в палитру приложения: тогда palette(highlight)
        # в QSS и option.palette.highlight() в делегатах берут цвет именно
        # выбранной темы, а не системный синий Qt.
        accent = QColor(theme_accent(theme_name))
        if not accent.isValid():
            accent = QColor(DEFAULT_ACCENT)
        palette = app.palette()
        palette.setColor(QPalette.Highlight, accent)
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        app.setPalette(palette)
        app.setStyleSheet(qss)
    return qss


# ----------------------------------------------------------------------
#  Предустановленные темы
# ----------------------------------------------------------------------
# Создаются при запуске из шаблона dark.qss, если файла ещё нет. Пользователь
# может свободно редактировать их — существующие файлы не перезаписываются.
PRESET_THEMES = {
    "soft_light": {
        "background": "#F4F6F8",
        "card": "#FFFFFF",
        "text": "#2E3440",
        "accent": "#5151ab",
        "hover": "#E5E7EB",
        "muted": "#6B7280",
        "arrow": "black",
    },
    "dracula": {
        "background": "#282a36",
        "card": "#282a36",
        "text": "#f8f8f2",
        "accent": "#bd93f9",
        "hover": "#44475a",
        "muted": "#6272a4",
        "arrow": "white",
    },
    "base2tone_evening": {
        "background": "#1e1e2e",
        "card": "#1e1e2e",
        "text": "#cdd6f4",
        "accent": "#fab387",
        "hover": "#313244",
        "muted": "#7f849c",
        "arrow": "white",
    },
    "catppuccin_macchiato": {
        "background": "#24273a",
        "card": "#24273a",
        "text": "#cad3f5",
        "accent": "#8aadf4",
        "hover": "#363a4f",
        "muted": "#8087a2",
        "arrow": "white",
    },
}


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _mix(color, other, ratio):
    """Смешивает два цвета: ratio — доля ``other`` (0..1)."""
    first = _hex_to_rgb(color)
    second = _hex_to_rgb(other)
    mixed = [
        round(a + (b - a) * ratio) for a, b in zip(first, second)
    ]
    return "#{:02x}{:02x}{:02x}".format(*mixed)


def _rgba(color, alpha):
    red, green, blue = _hex_to_rgb(color)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _build_preset_theme(template, spec):
    card_alt = _mix(spec["card"], spec["text"], 0.06)
    border = _mix(spec["card"], spec["text"], 0.16)
    accent_hover = _mix(spec["accent"], spec["text"], 0.18)

    qss = template.replace(
        "/white/chevron-down.svg", f"/{spec['arrow']}/chevron-down.svg"
    )
    qss = qss.replace(
        "rgba(81, 81, 171, 0.4)", _rgba(spec["accent"], 0.4)
    )
    for alpha in ("0.05", "0.06", "0.08", "0.10", "0.1", "0.14"):
        qss = qss.replace(f"rgba(255, 255, 255, {alpha})", spec["hover"])

    colors = {
        "#121212": spec["background"],
        "#181818": spec["card"],
        "#1f1f1f": card_alt,
        "#202020": card_alt,
        "#282828": spec["hover"],
        "#2a2a2a": border,
        "#333333": border,
        "#3e3e3e": spec["hover"],
        "#8a8a8a": spec["muted"],
        "#b3b3b3": spec["muted"],
        "#777777": spec["muted"],
        "#ffffff": spec["text"],
        "#5151ab": spec["accent"],
        "#6161c4": accent_hover,
    }
    for old, new in colors.items():
        qss = qss.replace(old, new)
    return qss


def ensure_preset_themes():
    """Создаёт недостающие предустановленные темы в папке ``themes``."""
    template_path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError:
        return []

    created = []
    for name, spec in PRESET_THEMES.items():
        path = THEMES_DIR / f"{name}.qss"
        if path.exists():
            continue
        try:
            THEMES_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(
                _build_preset_theme(template, spec), encoding="utf-8"
            )
            created.append(name)
        except OSError:
            continue
    return created


# Совместимость со старым API: темы читаются из файлов при импорте.
DARK_THEME = load_theme_qss("dark")
LIGHT_THEME = load_theme_qss("light")
