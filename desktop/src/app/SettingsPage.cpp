#include "SettingsPage.h"

#include "IconUtils.h"
#include "Theme.h"

#include <QCheckBox>
#include <QComboBox>
#include <QCoreApplication>
#include <QDesktopServices>
#include <QDir>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFont>
#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSettings>
#include <QSizePolicy>
#include <QStackedWidget>
#include <QUrl>
#include <QVBoxLayout>

namespace {

QLabel *sectionTitle(const QString &text, QWidget *parent) {
    auto *label = new QLabel(text, parent);
    label->setObjectName(QStringLiteral("settingsSectionTitle"));
    label->setStyleSheet(
        QStringLiteral("font-size: 22px; font-weight: 700;"));
    return label;
}

QLabel *pathLabel(const QString &path, QWidget *parent) {
    auto *label = new QLabel(path, parent);
    label->setWordWrap(true);
    label->setTextInteractionFlags(Qt::TextSelectableByMouse);
    label->setObjectName(QStringLiteral("settingsPath"));
    return label;
}

QWidget *makeTextColumn(const QString &title,
                        const QString &description,
                        QWidget *parent) {
    auto *container = new QWidget(parent);
    container->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    auto *layout = new QVBoxLayout(container);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(2);

    auto *titleLabel = new QLabel(title, container);
    titleLabel->setObjectName(QStringLiteral("settingsItemTitle"));
    titleLabel->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    layout->addWidget(titleLabel);

    if (!description.isEmpty()) {
        auto *descriptionLabel = new QLabel(description, container);
        descriptionLabel->setObjectName(QStringLiteral("settingsItemDescription"));
        descriptionLabel->setWordWrap(true);
        descriptionLabel->setSizePolicy(QSizePolicy::Ignored,
                                        QSizePolicy::Preferred);
        layout->addWidget(descriptionLabel);
    }
    return container;
}

QWidget *makeRow(const QString &title,
                 const QString &description,
                 QWidget *control,
                 QWidget *parent) {
    auto *row = new QWidget(parent);
    auto *layout = new QHBoxLayout(row);
    layout->setContentsMargins(0, 10, 0, 10);
    layout->setSpacing(16);
    layout->addWidget(makeTextColumn(title, description, row), 1);
    if (control) {
        control->setSizePolicy(QSizePolicy::Maximum, QSizePolicy::Fixed);
        layout->addWidget(control, 0, Qt::AlignRight | Qt::AlignVCenter);
    }
    return row;
}

QWidget *makePage(const QString &heading, QWidget *parent, QVBoxLayout *&layout) {
    auto *content = new QWidget(parent);
    content->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    layout = new QVBoxLayout(content);
    layout->setContentsMargins(32, 28, 32, 28);
    layout->setSpacing(0);
    layout->addWidget(sectionTitle(heading, content));
    layout->addSpacing(16);

    auto *scroll = new QScrollArea(parent);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    scroll->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    scroll->setWidget(content);
    return scroll;
}

void configureCombo(QComboBox *combo, int width = 220) {
    combo->setMinimumWidth(120);
    combo->setMaximumWidth(width);
    combo->setSizeAdjustPolicy(
        QComboBox::AdjustToMinimumContentsLengthWithIcon);
    combo->setMinimumContentsLength(6);
}

void showRestartMessage(QWidget *parent) {
    QMessageBox::information(parent, QObject::tr("Restart required"),
                             QObject::tr("The change will take effect after "
                                         "the application restarts."));
}

} // namespace

SettingsPage::SettingsPage(const QString &dataDir,
                           const QString &musicDir,
                           QWidget *parent)
    : QWidget(parent), m_dataDir(dataDir), m_musicDir(musicDir) {
    setObjectName(QStringLiteral("settingsPage"));
    setAttribute(Qt::WA_StyledBackground, true);

    auto *root = new QHBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(8);

    auto *nav = new QListWidget(this);
    nav->setObjectName(QStringLiteral("settingsNav"));
    nav->setMinimumWidth(150);
    nav->setMaximumWidth(220);
    nav->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Expanding);
    nav->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    nav->addItem(tr("General"));
    nav->addItem(tr("Appearance"));
    nav->addItem(tr("YouTube"));
    nav->addItem(tr("Data"));
    nav->addItem(tr("About"));
    nav->setCurrentRow(0);
    root->addWidget(nav, 0);

    m_stack = new QStackedWidget(this);
    m_stack->addWidget(buildGeneral());
    m_stack->addWidget(buildAppearance());
    m_stack->addWidget(buildYouTube());
    m_stack->addWidget(buildData());
    m_stack->addWidget(buildAbout());
    root->addWidget(m_stack, 1);

    connect(nav, &QListWidget::currentRowChanged,
            m_stack, &QStackedWidget::setCurrentIndex);
}

QWidget *SettingsPage::buildGeneral() {
    QVBoxLayout *layout = nullptr;
    QWidget *page = makePage(tr("General"), this, layout);

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));

    auto *language = new QComboBox(page);
    configureCombo(language);
    language->addItem(QStringLiteral("English"), QStringLiteral("en"));
    language->addItem(QStringLiteral("Русский"), QStringLiteral("ru"));
    const int languageIndex = language->findData(
        settings.value(QStringLiteral("language"), QStringLiteral("en")).toString());
    language->setCurrentIndex(languageIndex >= 0 ? languageIndex : 0);
    connect(language, &QComboBox::currentIndexChanged, this,
            [this, language](int index) {
                QSettings s(QStringLiteral("MusicPlayer"),
                            QStringLiteral("MusicPlayer"));
                s.setValue(QStringLiteral("language"),
                           language->itemData(index));
                showRestartMessage(this);
            });
    layout->addWidget(makeRow(
        tr("Language"), tr("Choose the language of the interface."),
        language, page));

    auto *crossfade = new QCheckBox(tr("Enable Crossfade"), page);
    crossfade->setChecked(
        settings.value(QStringLiteral("enable_crossfade"), true).toBool());
    crossfade->setCursor(Qt::PointingHandCursor);
    crossfade->setToolTip(
        tr("Smoothly blend the end of the current track into the next one."));
    connect(crossfade, &QCheckBox::toggled, this, [this](bool enabled) {
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("enable_crossfade"), enabled);
        emit crossfadeChanged(enabled);
    });
    layout->addWidget(makeRow(
        tr("Crossfade"),
        tr("Smoothly blend the end of the current track into the next one."),
        crossfade, page));

    const QColor iconColor = Theme::iconColor();
    auto *clearCovers = new QPushButton(tr("Clear Covers"), page);
    clearCovers->setIcon(IconUtils::tinted(QStringLiteral("trash.svg"),
                                           iconColor, 18));
    m_iconButtons.push_back({clearCovers, QStringLiteral("trash.svg")});
    clearCovers->setIconSize(QSize(18, 18));
    clearCovers->setCursor(Qt::PointingHandCursor);
    connect(clearCovers, &QPushButton::clicked,
            this, &SettingsPage::clearCoversRequested);
    layout->addWidget(makeRow(
        tr("Clear Covers"),
        tr("Delete cached track covers and custom playlist covers."),
        clearCovers, page));

    auto *clearCache = new QPushButton(tr("Clear ALL Cache"), page);
    clearCache->setIcon(IconUtils::tinted(QStringLiteral("trash.svg"),
                                          iconColor, 18));
    m_iconButtons.push_back({clearCache, QStringLiteral("trash.svg")});
    clearCache->setIconSize(QSize(18, 18));
    clearCache->setCursor(Qt::PointingHandCursor);
    connect(clearCache, &QPushButton::clicked,
            this, &SettingsPage::clearCacheRequested);
    layout->addWidget(makeRow(
        tr("Clear ALL Cache"),
        tr("Delete all cached images and profile avatars/banners."),
        clearCache, page));

    auto *badges = new QCheckBox(tr("Show metadata source badges"), page);
    badges->setChecked(settings.value(
        QStringLiteral("show_metadata_source_badges"), false).toBool());
    connect(badges, &QCheckBox::toggled, this, [](bool enabled) {
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("show_metadata_source_badges"), enabled);
    });
    layout->addWidget(makeRow(
        tr("Metadata source badges"),
        tr("Display small M/Y/F badges on track covers indicating the metadata source."),
        badges, page));

    layout->addStretch(1);
    return page;
}

QWidget *SettingsPage::buildAppearance() {
    QVBoxLayout *layout = nullptr;
    QWidget *page = makePage(tr("Appearance"), this, layout);

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));

    auto *zoomRow = new QWidget(page);
    auto *zoomLayout = new QHBoxLayout(zoomRow);
    zoomLayout->setContentsMargins(0, 0, 0, 0);
    zoomLayout->setSpacing(8);
    auto *zoom = new QComboBox(zoomRow);
    configureCombo(zoom);
    zoom->addItem(QStringLiteral("100%"), 100);
    zoom->addItem(QStringLiteral("125%"), 125);
    zoom->addItem(QStringLiteral("150%"), 150);
    const int zoomValue = settings.value(QStringLiteral("zoom"), 125).toInt();
    const int zoomIndex = zoom->findData(zoomValue);
    zoom->setCurrentIndex(zoomIndex >= 0 ? zoomIndex : 1);
    auto *resetZoom = new QPushButton(tr("Reset zoom (100%)"), zoomRow);
    connect(resetZoom, &QPushButton::clicked, zoom, [zoom] {
        zoom->setCurrentIndex(zoom->findData(100));
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("zoom"), 100);
    });
    connect(zoom, &QComboBox::currentIndexChanged, this, [this, zoom](int i) {
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("zoom"), zoom->itemData(i));
        showRestartMessage(this);
    });
    zoomLayout->addWidget(zoom);
    zoomLayout->addWidget(resetZoom);
    layout->addWidget(makeRow(
        tr("Interface zoom"),
        tr("Scale of the interface elements. A restart is required."),
        zoomRow, page));

    m_theme = new QComboBox(page);
    configureCombo(m_theme, 240);
    const QStringList themes = Theme::availableThemes();
    for (const QString &theme : themes) {
        QString label = theme;
        label.replace(QLatin1Char('_'), QLatin1Char(' '));
        label.replace(QLatin1Char('-'), QLatin1Char(' '));
        m_theme->addItem(label, theme);
    }
    const QString current =
        settings.value(QStringLiteral("theme"), QStringLiteral("dark")).toString();
    const int index = m_theme->findData(current);
    m_theme->setCurrentIndex(index >= 0 ? index : 0);
    connect(m_theme, &QComboBox::currentIndexChanged, this, [this] {
        emit themeChanged(m_theme->currentData().toString());
    });
    layout->addWidget(makeRow(
        tr("Theme"), tr("Choose the color scheme of the application."),
        m_theme, page));

    layout->addStretch(1);
    return page;
}

QWidget *SettingsPage::buildYouTube() {
    QVBoxLayout *layout = nullptr;
    QWidget *page = makePage(tr("YouTube"), this, layout);

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));

    auto *format = new QComboBox(page);
    configureCombo(format, 280);
    format->addItem(tr("Fast mode (original format)"), QStringLiteral("native"));
    format->addItem(tr("Compatibility (MP3 320 kbps)"), QStringLiteral("mp3"));
    const int formatIndex = format->findData(
        settings.value(QStringLiteral("youtube_download_mode"),
                       QStringLiteral("native")).toString());
    format->setCurrentIndex(formatIndex >= 0 ? formatIndex : 0);
    connect(format, &QComboBox::currentIndexChanged, this, [format](int i) {
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("youtube_download_mode"), format->itemData(i));
    });
    layout->addWidget(makeRow(
        tr("Download format"),
        tr("Fast mode keeps the original M4A/Opus/WebM audio without "
           "re-encoding. Compatibility converts to MP3 320 kbps."),
        format, page));

    auto *cookiesRow = new QWidget(page);
    auto *cookiesLayout = new QVBoxLayout(cookiesRow);
    cookiesLayout->setContentsMargins(0, 0, 0, 0);
    cookiesLayout->setSpacing(6);
    m_cookiesStatus = new QLabel(cookiesRow);
    m_cookiesStatus->setWordWrap(true);
    m_cookiesStatus->setTextInteractionFlags(Qt::TextSelectableByMouse);
    m_cookiesStatus->setMinimumWidth(220);
    auto *cookiesButtons = new QHBoxLayout();
    cookiesButtons->setContentsMargins(0, 0, 0, 0);
    cookiesButtons->setSpacing(8);
    auto *import = new QPushButton(tr("Import cookies.txt"), cookiesRow);
    import->setIcon(IconUtils::tinted(QStringLiteral("download.svg"),
                                      Theme::iconColor(), 18));
    m_iconButtons.push_back({import, QStringLiteral("download.svg")});
    import->setIconSize(QSize(18, 18));
    auto *deleteButton = new QPushButton(tr("Delete cookies"), cookiesRow);
    deleteButton->setIcon(IconUtils::tinted(QStringLiteral("trash.svg"),
                                            Theme::iconColor(), 18));
    m_iconButtons.push_back({deleteButton, QStringLiteral("trash.svg")});
    deleteButton->setIconSize(QSize(18, 18));
    import->setCursor(Qt::PointingHandCursor);
    deleteButton->setCursor(Qt::PointingHandCursor);
    cookiesButtons->addWidget(import);
    cookiesButtons->addWidget(deleteButton);
    cookiesButtons->addStretch(1);
    cookiesLayout->addWidget(m_cookiesStatus);
    cookiesLayout->addLayout(cookiesButtons);
    layout->addWidget(makeRow(
        tr("Cookies file"),
        tr("OctoBeat looks for cookies.txt in the app data folder and in the "
           "music folder. Import a file if YouTube asks you to sign in."),
        cookiesRow, page));

    layout->addStretch(1);

    connect(import, &QPushButton::clicked, this, &SettingsPage::importCookies);
    connect(deleteButton, &QPushButton::clicked, this, [this] {
        QFile::remove(QDir(m_dataDir).filePath(QStringLiteral("cookies.txt")));
        updateCookiesStatus();
    });
    updateCookiesStatus();
    return page;
}

QWidget *SettingsPage::buildData() {
    QVBoxLayout *layout = nullptr;
    QWidget *page = makePage(tr("Data"), this, layout);

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));

    auto *csv = new QPushButton(tr("Import from CSV"), page);
    csv->setIcon(IconUtils::tinted(QStringLiteral("add-music.svg"),
                                    Theme::iconColor(), 18));
    m_iconButtons.push_back({csv, QStringLiteral("add-music.svg")});
    csv->setIconSize(QSize(18, 18));
    csv->setCursor(Qt::PointingHandCursor);
    csv->setToolTip(tr("Import tracks from an Exportify CSV file."));
    connect(csv, &QPushButton::clicked, this,
            &SettingsPage::csvImportRequested);
    layout->addWidget(makeRow(
        tr("Import from CSV"),
        tr("Import a CSV file with tracks (Spotify/Exportify export)."),
        csv, page));

    auto *folderRow = new QWidget(page);
    auto *folderLayout = new QHBoxLayout(folderRow);
    folderLayout->setContentsMargins(0, 0, 0, 0);
    folderLayout->setSpacing(8);
    m_musicPath = pathLabel(m_musicDir, folderRow);
    m_musicPath->setMinimumWidth(140);
    m_musicPath->setMaximumWidth(260);
    folderLayout->addWidget(m_musicPath);
    auto *choose = new QPushButton(tr("Select folder"), folderRow);
    choose->setCursor(Qt::PointingHandCursor);
    connect(choose, &QPushButton::clicked, this, [this] {
        const QString path = QFileDialog::getExistingDirectory(
            this, tr("Select music folder"), m_musicDir);
        if (path.isEmpty()) {
            return;
        }
        m_musicDir = path;
        if (m_musicPath) {
            m_musicPath->setText(path);
        }
        emit musicFolderChanged(path);
    });
    folderLayout->addWidget(choose);
    layout->addWidget(makeRow(
        tr("Music folder"),
        tr("Folder where your music is stored and where downloads go."),
        folderRow, page));

    auto *updates = new QCheckBox(tr("Check for updates automatically"), page);
    updates->setChecked(
        settings.value(QStringLiteral("auto_update"), true).toBool());
    connect(updates, &QCheckBox::toggled, this, [](bool enabled) {
        QSettings s(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
        s.setValue(QStringLiteral("auto_update"), enabled);
    });
    layout->addWidget(makeRow(
        tr("Automatic updates"),
        tr("Check GitHub for new releases on startup."),
        updates, page));

    layout->addStretch(1);

    auto *open = new QPushButton(tr("Open data folder"), page);
    open->setCursor(Qt::PointingHandCursor);
    connect(open, &QPushButton::clicked, this, [this] {
        QDesktopServices::openUrl(QUrl::fromLocalFile(m_dataDir));
    });
    layout->addWidget(open, 0, Qt::AlignLeft);
    return page;
}

QWidget *SettingsPage::buildAbout() {
    QVBoxLayout *layout = nullptr;
    QWidget *page = makePage(tr("About"), this, layout);

    auto *about = new QLabel(
        tr("OctoBeat %1\nA local music player. Rust core + Qt 6 / QML.\n"
           "License: GPLv3. Source: github.com/ukimaka/OctoBeat")
            .arg(QCoreApplication::applicationVersion()),
        page);
    about->setWordWrap(true);
    about->setTextInteractionFlags(Qt::TextSelectableByMouse);
    layout->addWidget(about);

    auto *report = new QPushButton(tr("Report a Bug"), page);
    report->setIcon(IconUtils::tinted(QStringLiteral("bug.svg"),
                                      Theme::iconColor(), 18));
    m_iconButtons.push_back({report, QStringLiteral("bug.svg")});
    report->setIconSize(QSize(18, 18));
    report->setCursor(Qt::PointingHandCursor);
    connect(report, &QPushButton::clicked, this, [] {
        QDesktopServices::openUrl(
            QUrl(QStringLiteral("https://github.com/ukimaka/OctoBeat/issues")));
    });
    layout->addWidget(report, 0, Qt::AlignLeft);
    layout->addStretch(1);
    return page;
}

void SettingsPage::applyTheme() {
    for (const auto &entry : m_iconButtons) {
        entry.first->setIcon(
            IconUtils::tinted(entry.second, Theme::iconColor(), 18));
    }
}

void SettingsPage::setMusicFolderPath(const QString &path) {
    m_musicDir = path;
    if (m_musicPath) {
        m_musicPath->setText(path);
    }
}

void SettingsPage::updateCookiesStatus() {
    if (!m_cookiesStatus) {
        return;
    }
    const QString path = QDir(m_dataDir).filePath(QStringLiteral("cookies.txt"));
    m_cookiesStatus->setText(QFileInfo::exists(path)
                                 ? tr("Using %1").arg(path)
                                 : tr("No cookies.txt found"));
}

void SettingsPage::importCookies() {
    const QString source = QFileDialog::getOpenFileName(
        this, tr("Select cookies.txt"), QString(),
        QStringLiteral("Cookies (*.txt);;All files (*)"));
    if (source.isEmpty()) {
        return;
    }
    const QString target = QDir(m_dataDir).filePath(QStringLiteral("cookies.txt"));
    QFile::remove(target);
    if (!QFile::copy(source, target)) {
        QMessageBox::warning(this, tr("Cookies"),
                             tr("Could not copy cookies.txt to the data folder."));
        return;
    }
    updateCookiesStatus();
}
