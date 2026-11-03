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

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

from paths import RESOURCE_DIR

THEMES_DIR = RESOURCE_DIR / "themes"
ICONS_DIR = RESOURCE_DIR / "icons"
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
_THEME_BG_RE = re.compile(
    r"QMainWindow\s*,\s*QWidget\s*,\s*QDialog\s*\{[^}]*?"
    r"background-color:\s*(#[0-9a-fA-F]{3,8})",
    re.S,
)
_THEME_TEXT_RE = re.compile(
    r"\*\s*\{[^}]*?\bcolor:\s*(#[0-9a-fA-F]{3,8})",
    re.S,
)
_THEME_FIELD_RE = re.compile(
    r"QLineEdit\s*,\s*QComboBox\s*\{[^}]*?"
    r"background-color:\s*(#[0-9a-fA-F]{3,8})",
    re.S,
)


def theme_background(theme_name):
    """Фоновый цвет темы — нужен для palette(window) в QSS."""
    name = str(theme_name or DEFAULT_THEME)
    path = THEMES_DIR / f"{name}.qss"
    if not path.is_file():
        path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        qss = path.read_text(encoding="utf-8")
    except OSError:
        return "#121212" if is_dark_theme(name) else "#F4F6F8"
    match = _THEME_BG_RE.search(qss)
    if match:
        return match.group(1)
    return "#121212" if is_dark_theme(name) else "#F4F6F8"


def theme_text(theme_name):
    """Основной цвет текста темы (из правила ``* { color: ... }``)."""
    name = str(theme_name or DEFAULT_THEME)
    path = THEMES_DIR / f"{name}.qss"
    if not path.is_file():
        path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        qss = path.read_text(encoding="utf-8")
    except OSError:
        return "#ffffff" if is_dark_theme(name) else "#000000"
    match = _THEME_TEXT_RE.search(qss)
    if match:
        return match.group(1)
    return "#ffffff" if is_dark_theme(name) else "#000000"


def theme_field(theme_name):
    """Фон полей ввода/редакторов темы (для QPalette.Base)."""
    name = str(theme_name or DEFAULT_THEME)
    path = THEMES_DIR / f"{name}.qss"
    if not path.is_file():
        path = THEMES_DIR / f"{DEFAULT_THEME}.qss"
    try:
        qss = path.read_text(encoding="utf-8")
    except OSError:
        return "#181818" if is_dark_theme(name) else "#ffffff"
    match = _THEME_FIELD_RE.search(qss)
    if match:
        return match.group(1)
    return "#181818" if is_dark_theme(name) else "#ffffff"


def _mix_color(first, second, ratio):
    """Смешивает два QColor: ``ratio`` — доля второго цвета."""
    ratio = max(0.0, min(1.0, ratio))
    return QColor(
        round(first.red() * (1 - ratio) + second.red() * ratio),
        round(first.green() * (1 - ratio) + second.green() * ratio),
        round(first.blue() * (1 - ratio) + second.blue() * ratio),
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
#profileDescription,
#playlistCard,
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

/* Заголовок и плеер не входят в жёсткий список выше: тонкую границу и
   фон задаёт каждая тема (.qss). Плеер всегда плоский — градиенты снимаем. */
#playerBar {
    background-image: none;
}

#globalAvatarButton {
    background: transparent;
    border: none;
}

QTabWidget::pane {
    border: none;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 2px solid palette(mid);
    border-radius: 4px;
    background: transparent;
}
QCheckBox::indicator:checked {
    border: 2px solid palette(highlight);
    background: transparent;
}

QSlider {
    background: transparent;
    border: none;
}
QSlider::groove:horizontal,
QSlider::groove:vertical {
    background: transparent;
    border: none;
}
QSlider::handle:horizontal {
    background: palette(highlight);
    border: none;
}
QSlider#volumeSlider,
QWidget#volumeBlock,
QSlider#volumeSlider::groove:horizontal {
    background: transparent;
    border: none;
}
QSlider#volumeSlider::sub-page:horizontal {
    background: palette(highlight);
    border: none;
}
QSlider#volumeSlider::add-page:horizontal {
    background: palette(mid);
    border: none;
}
QSlider#volumeSlider::handle:horizontal {
    background: palette(highlight);
    border: none;
    border-radius: 6px;
}
QSlider::add-page:horizontal,
QSlider::add-page:vertical,
QSlider::sub-page:horizontal,
QSlider::sub-page:vertical {
    background: palette(mid);
    border: none;
}
QSlider::sub-page:horizontal,
QSlider::sub-page:vertical {
    background: palette(highlight);
}

/* Вкладки: отключаем glitchy drawBase и держим верхнюю линию активной
   вкладки даже при наведении. Hover меняет только фон, без border. */
QTabBar {
    qproperty-drawBase: 0;
    qproperty-expanding: 0;
    /* Шрифт задаём и самому QTabBar, а не только subcontrol: иначе
       sizeHint вкладки считается по 13px, а рисуется текст 14px —
       буквы обрезаются слева и справа. */
    font-size: 14px;
    border: none;
}
QTabBar::tab {
    background: transparent;
    border: none;
    padding: 6px 16px;
    font-size: 14px;
}
QTabBar::tab:hover {
    background: rgba(127, 127, 127, 0.12);
    border: none;
}
QTabBar::tab:selected {
    border-top: 2px solid palette(highlight);
    color: palette(window-text);
}
QTabBar::tab:selected:hover {
    border-top: 2px solid palette(highlight);
    border-bottom: none;
    border-left: none;
    border-right: none;
    color: palette(window-text);
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

/* Редакторы диалогов (BBCode, About Me и т.п.) наследуют палитру темы,
   а не системный белый Base / чёрный Text. */
QTextEdit, QTextBrowser {
    background-color: palette(base);
    color: palette(text);
    selection-background-color: palette(highlight);
    selection-color: palette(highlighted-text);
}

/* ------------------------------------------------------------------
   Spotify-like glass surface, pill search and hover-only scrollbars.
   ------------------------------------------------------------------ */
/* Окно безрамочное и прозрачное; видимую поверхность рисует mainSurface.
   8 px внутреннего отступа (MainWindow) не даёт детям заходить в углы. */
QMainWindow#mainWindow {
    background: transparent;
    border: none;
}
QWidget#mainSurface {
    background-color: palette(window);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 18px;
}
QWidget#mainSurface[windowMaximized="true"] {
    border: none;
    border-radius: 0px;
}

#playerBar, #customTitleBar {
    background-color: rgba(255, 255, 255, 0.05);
    background-image: none;
    border: none;
    border-radius: 12px;
}

QLineEdit#searchEdit {
    border: none;
    border-radius: 15px;
    padding: 6px 14px;
}

QLineEdit#searchEdit:hover,
QLineEdit#searchEdit:focus {
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: transparent;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover,
QScrollBar::handle:vertical:pressed {
    background: palette(mid);
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    background: transparent;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 6px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: transparent;
    border-radius: 3px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover,
QScrollBar::handle:horizontal:pressed {
    background: palette(mid);
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
    background: transparent;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}

QScrollBar#profileScrollBar:vertical {
    background: transparent;
    width: 6px;
}

QScrollBar#profileScrollBar::handle:vertical {
    background: transparent;
    border-radius: 3px;
}

QScrollBar#profileScrollBar::handle:vertical:hover,
QScrollBar#profileScrollBar::handle:vertical:pressed {
    background: palette(mid);
}
"""


def available_themes():
    """Имена доступных тем (файлы ``themes/*.qss``), отсортированные."""
    if not THEMES_DIR.is_dir():
        return []
    return sorted(path.stem for path in THEMES_DIR.glob("*.qss"))


# ------------------------------------------------------------------
# Glassmorphism layer
# ------------------------------------------------------------------
# Qt QSS не умеет настоящий CSS backdrop-filter. Вместо размытия фона
# используем полупрозрачные слои, тонкую обводку и существующую тень QMenu;
# текст при этом остаётся полностью контрастным.
_GLASS_QSS = """
/* Парящие стеклянные меню (ПКМ, трей). */
QMenu {
    background-color: %(menu_bg)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 12px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 26px 7px 24px;
    background: transparent;
    border-radius: 7px;
}
QMenu::item:selected {
    background-color: %(hover)s;
}
QMenu::separator {
    height: 1px;
    background: %(border_soft)s;
    margin: 5px 8px;
}

/* Тултипы — та же капсула, чуть плотнее для читаемости. */
QToolTip {
    background-color: %(tooltip_bg)s;
    color: %(text)s;
    border: 1px solid %(tooltip_border)s;
    border-radius: 8px;
    padding: 6px 10px;
}

/* Страницы настроек и профиля — стеклянные капсулы внутри вкладки. */
QWidget#settingsPage, QWidget#profilePage {
    background-color: %(page_bg)s;
    border: 1px solid %(border_soft)s;
    border-radius: 14px;
}

/* Левая панель настроек — лёгкое стекло, не спорит с контентом. */
QListWidget#settingsNav {
    background-color: %(sidebar_bg)s;
    border: 1px solid %(border_soft)s;
    border-radius: 14px;
    padding: 8px;
}

/* Next in queue — отдельная стеклянная капсула в тулбаре. */
QWidget#nextTrackIsland {
    background-color: %(island_bg)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}
"""


def _rgba_color(color, alpha):
    """QColor → строка rgba() для QSS."""
    return (
        f"rgba({color.red()}, {color.green()}, {color.blue()}, "
        f"{max(0.0, min(1.0, alpha)):.2f})"
    )


def _glass_tint(theme_name, mix, alpha):
    """Смешивает фон темы с белым и добавляет прозрачность."""
    background = QColor(theme_background(theme_name))
    if not background.isValid():
        background = QColor("#121212")
    tint = _mix_color(background, QColor("#ffffff"), mix)
    return _rgba_color(tint, alpha)


def glass_qss(theme_name):
    """Возвращает QSS стеклянных слоёв для выбранной темы."""
    dark = is_dark_theme(theme_name)
    text = QColor(theme_text(theme_name))
    if not text.isValid():
        text = QColor("#ffffff" if dark else "#2E3440")
    accent = QColor(theme_accent(theme_name))
    border = "rgba(255, 255, 255, 0.14)" if dark else "rgba(46, 52, 64, 0.14)"
    border_soft = (
        "rgba(255, 255, 255, 0.09)" if dark else "rgba(46, 52, 64, 0.09)"
    )
    hover = (
        "rgba(255, 255, 255, 0.11)" if dark else "rgba(46, 52, 64, 0.08)"
    )
    return _GLASS_QSS % {
        "menu_bg": _glass_tint(theme_name, 0.10 if dark else 0.70, 0.84),
        "tooltip_bg": _glass_tint(theme_name, 0.06 if dark else 0.55, 0.85),
        "sidebar_bg": _glass_tint(theme_name, 0.05 if dark else 0.45, 0.72),
        "island_bg": _glass_tint(theme_name, 0.12 if dark else 0.62, 0.76),
        "page_bg": _glass_tint(theme_name, 0.035 if dark else 0.45, 0.70),
        "tooltip_border": _rgba_color(accent, 0.45),
        "border": border,
        "border_soft": border_soft,
        "hover": hover,
        "text": text.name(),
    }


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
    qss = (
        theme_qss + "\n" + BASE_QSS + "\n" + glass_qss(theme_name)
        if theme_qss
        else BASE_QSS + "\n" + glass_qss(theme_name)
    )
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
        background = QColor(theme_background(theme_name))
        text = QColor(theme_text(theme_name))
        base = QColor(theme_field(theme_name))
        if not background.isValid():
            background = QColor("#121212")
        if not text.isValid():
            text = QColor("#ffffff")
        if not base.isValid():
            base = _mix_color(background, text, 0.07)

        # Populate every text/base role.  Only setting Window left the
        # default system palette (black text, white Base) in place, which
        # made palette(windowText)/palette(text) render black on dark
        # dialogs and gave QTextEdit a white background.
        palette.setColor(QPalette.Window, background)
        palette.setColor(QPalette.Base, base)
        palette.setColor(QPalette.AlternateBase, _mix_color(base, text, 0.05))
        palette.setColor(QPalette.Text, text)
        palette.setColor(QPalette.WindowText, text)
        palette.setColor(QPalette.Button, background)
        palette.setColor(QPalette.ButtonText, text)
        palette.setColor(QPalette.ToolTipBase, base)
        palette.setColor(QPalette.ToolTipText, text)
        palette.setColor(QPalette.Mid, _mix_color(background, text, 0.28))
        palette.setColor(QPalette.Midlight, _mix_color(background, text, 0.14))
        palette.setColor(QPalette.Dark, _mix_color(background, QColor("#000000"), 0.25))
        palette.setColor(QPalette.Light, _mix_color(background, QColor("#ffffff"), 0.20))
        palette.setColor(QPalette.Highlight, accent)
        palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
        if hasattr(QPalette, "PlaceholderText"):
            placeholder = QColor(text)
            placeholder.setAlpha(140)
            palette.setColor(QPalette.PlaceholderText, placeholder)
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
