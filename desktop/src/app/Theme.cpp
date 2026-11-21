#include "Theme.h"

#include "ResourcePaths.h"

#include <QApplication>
#include <QColor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QPalette>
#include <QRegularExpression>
#include <QSettings>

namespace {

QString resourcesDir() {
    return ResourcePaths::root();
}

QString themesDir() {
    return QDir(resourcesDir()).filePath(QStringLiteral("themes"));
}

QString themePath(const QString &name) {
    const QString theme = name.isEmpty() ? QStringLiteral("dark") : name;
    const QString path = QDir(themesDir()).filePath(theme + QStringLiteral(".qss"));
    if (QFileInfo::exists(path)) {
        return path;
    }
    return QDir(themesDir()).filePath(QStringLiteral("dark.qss"));
}

QString readTheme(const QString &name) {
    QFile file(themePath(name));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
        return {};
    }
    return QString::fromUtf8(file.readAll());
}

QColor parseColor(const QString &source, const QString &pattern,
                  const QColor &fallback) {
    const QRegularExpression re(pattern,
                                QRegularExpression::CaseInsensitiveOption |
                                    QRegularExpression::DotMatchesEverythingOption);
    const QRegularExpressionMatch match = re.match(source);
    if (!match.hasMatch()) {
        return fallback;
    }
    const QColor color(match.captured(1));
    return color.isValid() ? color : fallback;
}

QColor mix(const QColor &first, const QColor &second, qreal ratio) {
    const qreal clamped = qBound(0.0, ratio, 1.0);
    return QColor(qRound(first.red() * (1.0 - clamped) + second.red() * clamped),
                  qRound(first.green() * (1.0 - clamped) + second.green() * clamped),
                  qRound(first.blue() * (1.0 - clamped) + second.blue() * clamped));
}

QString accentFor(const QString &name) {
    const QString qss = readTheme(name);
    const QRegularExpression marker(
        QStringLiteral("@accent:\\s*(#[0-9a-fA-F]{3,8})"));
    const QRegularExpressionMatch match = marker.match(qss);
    if (match.hasMatch()) {
        return match.captured(1);
    }
    return QStringLiteral("#5151ab");
}

QColor themeBackground(const QString &qss, bool dark) {
    return parseColor(
        qss,
        QStringLiteral("QMainWindow[^{]*\\{[^}]*background-color:\\s*(#[0-9a-fA-F]{3,8})"),
        QColor(dark ? QStringLiteral("#121212") : QStringLiteral("#F4F6F8")));
}

QColor themeText(const QString &qss, bool dark) {
    return parseColor(
        qss, QStringLiteral("\\*\\s*\\{[^}]*\\bcolor:\\s*(#[0-9a-fA-F]{3,8})"),
        QColor(dark ? QStringLiteral("#ffffff") : QStringLiteral("#2E3440")));
}

} // namespace

namespace Theme {

QStringList availableThemes() {
    QStringList names;
    const QStringList files = QDir(themesDir()).entryList(
        {QStringLiteral("*.qss")}, QDir::Files, QDir::Name);
    for (const QString &file : files) {
        names.push_back(QFileInfo(file).completeBaseName());
    }
    return names;
}

bool isDark(const QString &name) {
    const QString theme = name.isEmpty() ? current() : name;
    if (theme.contains(QStringLiteral("light"), Qt::CaseInsensitive)) {
        return false;
    }
    const QString qss = readTheme(theme);
    const QColor background = themeBackground(qss, true);
    return background.lightness() < 128;
}

QColor accent(const QString &name) {
    const QColor color(accentFor(name.isEmpty() ? current() : name));
    return color.isValid() ? color : QColor(QStringLiteral("#5151ab"));
}

QColor iconColor(const QString &name) {
    return isDark(name) ? QColor(215, 215, 225) : QColor(38, 38, 42);
}

QString styleSheet(const QString &name) {
    QString css = readTheme(name);
    if (css.isEmpty()) {
        return {};
    }
    const QString theme = name.isEmpty() ? QStringLiteral("dark") : name;
    css.replace(QStringLiteral("@ICONS_DIR@"),
                QDir(resourcesDir()).filePath(QStringLiteral("icons")));
    const bool dark = isDark(theme);
    const QString accentColor = accentFor(theme);
    const QString text = dark ? QStringLiteral("#ffffff") : QStringLiteral("#1a1a1a");
    const QString muted = dark ? QStringLiteral("#8a8a8a") : QStringLiteral("#6a6a72");
    const QString surfaceBorder =
        dark ? QStringLiteral("rgba(255, 255, 255, 26)")
             : QStringLiteral("rgba(0, 0, 0, 22)");
    const QString glass =
        dark ? QStringLiteral("rgba(255, 255, 255, 9)")
             : QStringLiteral("rgba(0, 0, 0, 7)");
    const QString glassBorder =
        dark ? QStringLiteral("rgba(255, 255, 255, 23)")
             : QStringLiteral("rgba(0, 0, 0, 20)");
    const QString playerBackground =
        dark ? QStringLiteral("#202020") : QStringLiteral("#E8EAEE");
    const QString scrollHandle =
        dark ? QStringLiteral("rgba(255, 255, 255, 0.30)")
             : QStringLiteral("rgba(0, 0, 0, 0.26)");
    const QString scrollHandleHover =
        dark ? QStringLiteral("rgba(255, 255, 255, 0.50)")
             : QStringLiteral("rgba(0, 0, 0, 0.42)");

    css += QStringLiteral(
               "QMainWindow#mainWindow { background: transparent; border: none; }"
               "QWidget#mainSurface { background-color: palette(window);"
               " border: 1px solid %1; border-radius: 18px; }"
               "QWidget#mainSurface[windowMaximized=\"true\"] {"
               " border: none; border-radius: 0px; }"
               "QWidget#settingsPage { background-color: %2;"
               " border: 1px solid %3; border-radius: 14px; }"
               "#playerBar { background-color: %7; background-image: none;"
               " border: none; border-radius: 12px; }"
               "QScrollBar:vertical { background: transparent; width: 8px;"
               " margin: 2px 0; border: none; border-radius: 4px; }"
               "QScrollBar::handle:vertical { background: %8; border: none;"
               " border-radius: 4px; min-height: 30px; }"
               "QScrollBar::handle:vertical:hover,"
               "QScrollBar::handle:vertical:pressed { background: %9; }"
               "QScrollBar:horizontal { background: transparent; height: 8px;"
               " margin: 0 2px; border: none; border-radius: 4px; }"
               "QScrollBar::handle:horizontal { background: %8; border: none;"
               " border-radius: 4px; min-width: 30px; }"
               "QScrollBar::handle:horizontal:hover,"
               "QScrollBar::handle:horizontal:pressed { background: %9; }"
               "QScrollBar::groove:vertical, QScrollBar::groove:horizontal,"
               "QAbstractScrollArea::corner, QScrollBar::add-page,"
               "QScrollBar::sub-page { background: transparent; border: none; }"
               "QListWidget#settingsNav { background-color: %2;"
               " border: 1px solid %3; border-radius: 14px; padding: 8px;"
               " selection-background-color: palette(highlight);"
               " selection-color: palette(highlighted-text); }"
               "QListWidget#settingsNav::item { color: %4; padding: 9px 14px;"
               " border-radius: 6px; }"
               "QListWidget#settingsNav::item:hover { color: %5;"
               " background-color: rgba(128, 128, 128, 0.15); }"
               "QListWidget#settingsNav::item:selected {"
               " background-color: palette(highlight);"
               " color: palette(highlighted-text); }"
               "QAbstractItemView { selection-background-color: palette(highlight);"
               " selection-color: palette(highlighted-text); }"
               "QListView::item:selected, QListWidget::item:selected,"
               "QTreeView::item:selected, QTreeWidget::item:selected,"
               "QTableView::item:selected { background-color: palette(highlight);"
               " color: palette(highlighted-text); }"
               "QTreeWidget#libraryList::item:selected,"
               "QListWidget#libraryList::item:selected,"
               "QListWidget#playlistTracks::item:selected,"
               "QListWidget#playlistGrid::item:selected {"
               " background: transparent; color: palette(text); }"
               "QListWidget#playlistTracks, QWidget#playlistDetail,"
               " QListWidget#playlistGrid { background: transparent;"
               " outline: none; }"
               "QListWidget#playlistGrid::item:hover,"
               "QListWidget#playlistGrid::item:selected,"
               "QListWidget#playlistGrid::item:focus {"
               " background: transparent; border: none; outline: none; }"
               "QLabel#settingsItemTitle { font-weight: 600; }"
               "QLabel#settingsItemDescription, QLabel#settingsPath { color: %4; }"
               "QLabel#settingsSectionTitle { color: %5; }"
               "QWidget#streamSearchBar { background: transparent; }"
               "QLineEdit#streamSearchField { background-color: %2;"
               " border: 1px solid %3; border-radius: 10px; padding: 7px 12px;"
               " color: %5; }"
               "QLineEdit#streamSearchField:focus { border: 1px solid"
               " palette(highlight); }"
               "QPushButton#streamSearchButton { background: transparent;"
               " border: none; border-radius: 8px; }"
               "QPushButton#streamSearchButton:hover { background-color: %2; }"
               "QPushButton#searchFilterButton { background: transparent;"
               " color: %4; border: 1px solid transparent; border-radius: 13px;"
               " padding: 4px 12px; }"
               "QPushButton#searchFilterButton:hover { background-color: %2;"
               " color: %5; }"
               "QPushButton#searchFilterButton:checked { background-color: %2;"
               " color: %5; border: 1px solid %3; }"
               "QLabel#homeGreeting, QLabel#homeSectionTitle { color: %5; }"
               "QLabel#homeHint, QLabel#homeEmpty, QLabel#streamEmpty,"
               " QLabel#streamViewSubtitle, QLabel#streamingStatus {"
               " color: %4; }"
               "QToolButton#streamBackButton { border: none;"
               " background: transparent; border-radius: 8px; }"
               "QToolButton#streamBackButton:hover { background-color: %2; }"
               "QScrollArea#streamHomeScroll, QScrollArea#homeCardScroll,"
               " QWidget#streamHomeContent { background: transparent;"
               " border: none; }"
               "QListWidget#streamSearchResults,"
               " QListWidget#streamCollectionList { background: transparent;"
               " border: none; outline: none; }"
               "QListWidget#streamSearchResults::item:selected,"
               " QListWidget#streamCollectionList::item:selected,"
               " QListWidget#searchOverlayList::item:selected {"
               " background: transparent; color: palette(text); }")
               .arg(surfaceBorder, glass, glassBorder, muted, text)
               .arg(playerBackground, scrollHandle, scrollHandleHover);

    return css;
}

void apply(const QString &name) {
    const QString theme = name.isEmpty() ? QStringLiteral("dark") : name;
    const QString qss = styleSheet(theme);
    if (QApplication *app = qobject_cast<QApplication *>(QApplication::instance())) {
        const bool dark = isDark(theme);
        const QColor background = themeBackground(readTheme(theme), dark);
        const QColor text = themeText(readTheme(theme), dark);
        const QColor base = mix(background, text, 0.07);
        const QColor accentColor = accent(theme);

        QPalette palette = app->palette();
        palette.setColor(QPalette::Window, background);
        palette.setColor(QPalette::Base, base);
        palette.setColor(QPalette::AlternateBase, mix(base, text, 0.05));
        palette.setColor(QPalette::Text, text);
        palette.setColor(QPalette::WindowText, text);
        palette.setColor(QPalette::Button, background);
        palette.setColor(QPalette::ButtonText, text);
        palette.setColor(QPalette::ToolTipBase, base);
        palette.setColor(QPalette::ToolTipText, text);
        palette.setColor(QPalette::Mid, mix(background, text, 0.28));
        palette.setColor(QPalette::Midlight, mix(background, text, 0.14));
        palette.setColor(QPalette::Dark, mix(background, QColor(Qt::black), 0.25));
        palette.setColor(QPalette::Light, mix(background, QColor(Qt::white), 0.20));
        palette.setColor(QPalette::Highlight, accentColor);
        palette.setColor(QPalette::HighlightedText, QColor(Qt::white));
        palette.setColor(QPalette::Link, accentColor);
        QColor placeholder = text;
        placeholder.setAlpha(140);
        palette.setColor(QPalette::PlaceholderText, placeholder);
        app->setPalette(palette);
        if (!qss.isEmpty()) {
            app->setStyleSheet(qss);
        }
    }
    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    settings.setValue(QStringLiteral("theme"), theme);
}

QString current() {
    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    QString theme =
        settings.value(QStringLiteral("theme"), QStringLiteral("dark")).toString();
    if (!availableThemes().contains(theme)) {
        theme = QStringLiteral("dark");
        settings.setValue(QStringLiteral("theme"), theme);
    }
    return theme;
}

} // namespace Theme
