#include "PlaylistsPage.h"

#include "AddTracksDialog.h"
#include "CoverCache.h"
#include "IconUtils.h"
#include "LocalizedMessageBox.h"
#include "PlaylistCoverDelegate.h"
#include "SmoothListWidget.h"
#include "Theme.h"
#include "TrackDelegate.h"

#include <QApplication>
#include <QColor>
#include <QComboBox>
#include <QContextMenuEvent>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QFont>
#include <QHBoxLayout>
#include <QIcon>
#include <QImage>
#include <QLinearGradient>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMenu>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPixmap>
#include <QPushButton>
#include <QSet>
#include <QShortcut>
#include <QStackedWidget>
#include <QTextEdit>
#include <QVBoxLayout>

#include <algorithm>

namespace {

QColor averageColor(const QPixmap &pixmap) {
    if (pixmap.isNull()) {
        return {};
    }
    const QImage sample = pixmap.toImage().scaled(
        1, 1, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
    return sample.isNull() ? QColor() : sample.pixelColor(0, 0);
}

QColor blend(const QColor &first, const QColor &second, qreal ratio) {
    const qreal value = qBound(0.0, ratio, 1.0);
    return QColor(
        qRound(first.red() * (1.0 - value) + second.red() * value),
        qRound(first.green() * (1.0 - value) + second.green() * value),
        qRound(first.blue() * (1.0 - value) + second.blue() * value));
}

QIcon playlistIcon(const Playlist &playlist) {
    const QPixmap cover = CoverCache::cover(playlist.coverPath, 160);
    if (!cover.isNull()) {
        return QIcon(cover);
    }
    QPixmap placeholder(160, 160);
    placeholder.fill(QColor(38, 38, 42));
    QPainter painter(&placeholder);
    painter.setRenderHint(QPainter::Antialiasing);
    painter.setPen(QColor(210, 210, 220));
    QFont font = painter.font();
    font.setPointSize(38);
    font.setBold(true);
    painter.setFont(font);
    const QString letter = playlist.name.trimmed().isEmpty()
                               ? QStringLiteral("?")
                               : playlist.name.trimmed().left(1).toUpper();
    painter.drawText(placeholder.rect(), Qt::AlignCenter, letter);
    return QIcon(placeholder);
}

class PlaylistDetailPage : public QWidget {
public:
    explicit PlaylistDetailPage(QWidget *parent = nullptr) : QWidget(parent) {
        setObjectName(QStringLiteral("playlistDetail"));
    }

    void setCoverColor(const QColor &color) {
        m_topColor = color;
        update();
    }

protected:
    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        const QColor bottom = QApplication::palette().color(QPalette::Window);
        const bool dark = bottom.lightness() < 128;
        QColor top = m_topColor.isValid()
                         ? blend(m_topColor, bottom, dark ? 0.25 : 0.04)
                         : bottom;
        const QColor mid = blend(top, bottom, dark ? 0.55 : 0.60);
        QLinearGradient gradient(0, 0, 0, height());
        gradient.setColorAt(0.0, top);
        gradient.setColorAt(0.45, mid);
        gradient.setColorAt(1.0, bottom);
        painter.fillRect(rect(), gradient);
    }

private:
    QColor m_topColor;
};

} // namespace

class PlaylistCoverButton : public QPushButton {
public:
    explicit PlaylistCoverButton(QWidget *parent = nullptr)
        : QPushButton(parent) {
        setCursor(Qt::PointingHandCursor);
        setFlat(true);
        setFocusPolicy(Qt::NoFocus);
        setFixedSize(140, 140);
        setAttribute(Qt::WA_Hover, true);
    }

    void setCover(const QPixmap &cover, bool circular = false) {
        m_cover = cover;
        m_circular = circular;
        update();
    }

protected:
    void enterEvent(QEnterEvent *event) override {
        m_hover = true;
        update();
        QPushButton::enterEvent(event);
    }

    void leaveEvent(QEvent *event) override {
        m_hover = false;
        update();
        QPushButton::leaveEvent(event);
    }

    void paintEvent(QPaintEvent *) override {
        QPainter painter(this);
        painter.setRenderHint(QPainter::Antialiasing, true);
        painter.setRenderHint(QPainter::SmoothPixmapTransform, true);
        const QRectF rect = this->rect();
        QPainterPath clip;
        if (m_circular) {
            clip.addEllipse(rect);
        } else {
            clip.addRoundedRect(rect, 8, 8);
        }
        painter.setClipPath(clip);
        if (!m_cover.isNull()) {
            painter.drawPixmap(this->rect(), m_cover);
        } else {
            const QColor base = palette().color(QPalette::Base);
            QLinearGradient gradient(rect.topLeft(), rect.bottomLeft());
            gradient.setColorAt(0.0, base.lighter(125));
            gradient.setColorAt(1.0, base);
            painter.fillRect(rect, gradient);
            const QPixmap note =
                IconUtils::tinted(QStringLiteral("music-note.svg"),
                                  palette().color(QPalette::WindowText), 56)
                    .pixmap(56, 56);
            painter.drawPixmap(
                static_cast<int>(rect.center().x()) - 28,
                static_cast<int>(rect.center().y()) - 28, note);
        }
        if (m_hover) {
            painter.fillRect(rect, QColor(0, 0, 0, 150));
            if (m_pencil.isNull()) {
                m_pencil = IconUtils::tinted(QStringLiteral("pencil.svg"),
                                             QColor(Qt::white), 20)
                               .pixmap(20, 20);
            }
            const QString text =
                QCoreApplication::translate("PlaylistsPage", "Change cover");
            const int iconSize = 16;
            const int gap = 6;
            const int available = this->width() - 12;
            QFont font = painter.font();
            font.setBold(true);
            int pixelSize = 13;
            while (pixelSize > 9) {
                font.setPixelSize(pixelSize);
                if (iconSize + gap +
                        QFontMetrics(font).horizontalAdvance(text) <=
                    available) {
                    break;
                }
                --pixelSize;
            }
            font.setPixelSize(pixelSize);
            painter.setFont(font);
            painter.setPen(Qt::white);
            QFontMetrics metrics(font);
            const QString shown = metrics.elidedText(
                text, Qt::ElideRight,
                qMax(1, available - iconSize - gap));
            const int textWidth = metrics.horizontalAdvance(shown);
            const int total = iconSize + gap + textWidth;
            const int startX =
                static_cast<int>(rect.center().x()) - total / 2;
            const int centerY = static_cast<int>(rect.center().y());
            painter.drawPixmap(startX, centerY - iconSize / 2,
                               m_pencil.scaled(iconSize, iconSize,
                                               Qt::KeepAspectRatio,
                                               Qt::SmoothTransformation));
            painter.drawText(startX + iconSize + gap, centerY - 10,
                             textWidth, 20, Qt::AlignLeft | Qt::AlignVCenter,
                             shown);
        }
        painter.end();
    }

private:
    QPixmap m_cover;
    QPixmap m_pencil;
    bool m_hover = false;
    bool m_circular = false;
};

PlaylistsPage::PlaylistsPage(CoreClient *core,
                             const QString &dataDir,
                             QWidget *parent)
    : QWidget(parent), m_core(core), m_dataDir(dataDir) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    m_stack = new QStackedWidget(this);
    root->addWidget(m_stack, 1);

    auto *gridPage = new QWidget(m_stack);
    auto *gridLayout = new QVBoxLayout(gridPage);
    gridLayout->setContentsMargins(18, 14, 18, 10);
    gridLayout->setSpacing(10);

    auto *toolbar = new QHBoxLayout();
    auto *title = new QLabel(tr("Your playlists"), gridPage);
    title->setObjectName(QStringLiteral("pageTitle"));
    QFont titleFont = title->font();
    titleFont.setBold(true);
    titleFont.setPointSize(titleFont.pointSize() + 4);
    title->setFont(titleFont);
    auto *newButton = new QPushButton(tr("New playlist"), gridPage);
    newButton->setObjectName(QStringLiteral("newPlaylistButton"));
    newButton->setIcon(IconUtils::tinted(QStringLiteral("create-playlist.svg"),
                                         Theme::iconColor(), 18));
    newButton->setIconSize(QSize(16, 16));
    newButton->setCursor(Qt::PointingHandCursor);
    toolbar->addWidget(title);
    toolbar->addStretch(1);
    toolbar->addWidget(newButton);
    gridLayout->addLayout(toolbar);

    m_grid = new SmoothListWidget(gridPage);
    m_grid->setObjectName(QStringLiteral("playlistGrid"));
    m_grid->setViewMode(QListView::IconMode);
    m_grid->setResizeMode(QListView::Adjust);
    m_grid->setMovement(QListView::Static);
    m_grid->setIconSize(QSize(160, 160));
    m_grid->setGridSize(QSize(186, 218));
    m_grid->setSpacing(6);
    m_grid->setUniformItemSizes(true);
    m_grid->setMouseTracking(true);
    m_grid->setAttribute(Qt::WA_Hover, true);
    m_grid->setFocusPolicy(Qt::NoFocus);
    m_grid->viewport()->setMouseTracking(true);
    m_grid->viewport()->installEventFilter(this);
    m_grid->setItemDelegate(new PlaylistCoverDelegate(m_grid));
    gridLayout->addWidget(m_grid, 1);
    m_stack->addWidget(gridPage);

    m_gradientPage = new PlaylistDetailPage(m_stack);
    auto *detailLayout = new QVBoxLayout(m_gradientPage);
    detailLayout->setContentsMargins(24, 20, 24, 18);
    detailLayout->setSpacing(10);

    auto *top = new QHBoxLayout();
    top->setSpacing(16);

    auto *left = new QVBoxLayout();
    left->setContentsMargins(0, 0, 0, 0);
    left->setSpacing(10);
    auto *back = new QPushButton(m_gradientPage);
    back->setObjectName(QStringLiteral("playlistBack"));
    back->setFixedSize(34, 30);
    back->setFlat(true);
    back->setIcon(IconUtils::tinted(QStringLiteral("back.svg"),
                                    Theme::iconColor(), 18));
    back->setIconSize(QSize(16, 16));
    back->setCursor(Qt::PointingHandCursor);
    back->setToolTip(tr("Back to playlists"));
    left->addWidget(back, 0, Qt::AlignLeft);
    m_detailCover = new PlaylistCoverButton(m_gradientPage);
    m_detailCover->setObjectName(QStringLiteral("playlistDetailCover"));
    left->addWidget(m_detailCover, 0, Qt::AlignLeft);
    left->addStretch(1);
    top->addLayout(left, 0);
    top->addSpacing(8);

    auto *right = new QVBoxLayout();
    right->setContentsMargins(0, 0, 0, 0);
    right->setSpacing(6);
    auto *nameRow = new QHBoxLayout();
    nameRow->setSpacing(10);
    m_detailTitle = new QLabel(m_gradientPage);
    m_detailTitle->setObjectName(QStringLiteral("playlistDetailTitle"));
    m_detailTitle->setStyleSheet(
        QStringLiteral("font-size: 32px; font-weight: bold;"));
    nameRow->addWidget(m_detailTitle);
    nameRow->addStretch(1);
    right->addLayout(nameRow);

    m_detailDescription = new QTextEdit(m_gradientPage);
    m_detailDescription->setObjectName(QStringLiteral("playlistDescription"));
    m_detailDescription->setPlaceholderText(tr("Add a description…"));
    m_detailDescription->setMinimumHeight(60);
    m_detailDescription->setMaximumHeight(80);
    m_detailDescription->setFrameStyle(0);
    m_detailDescription->setSizePolicy(QSizePolicy::Expanding,
                                       QSizePolicy::Preferred);
    right->addWidget(m_detailDescription);

    auto *add = new QPushButton(tr("Add tracks"), m_gradientPage);
    add->setObjectName(QStringLiteral("playlistAdd"));
    add->setCursor(Qt::PointingHandCursor);
    add->setIcon(IconUtils::tinted(QStringLiteral("add-music.svg"),
                                   Theme::iconColor(), 16));
    add->setIconSize(QSize(16, 16));
    add->setToolTip(tr("Add tracks"));
    right->addWidget(add, 0, Qt::AlignLeft);
    right->addStretch(1);
    top->addLayout(right, 1);

    auto *deleteButton = new QPushButton(m_gradientPage);
    deleteButton->setObjectName(QStringLiteral("playlistDelete"));
    deleteButton->setFixedSize(34, 32);
    deleteButton->setFlat(true);
    deleteButton->setCursor(Qt::PointingHandCursor);
    deleteButton->setToolTip(tr("Delete playlist"));
    deleteButton->setIcon(IconUtils::tinted(QStringLiteral("trash.svg"),
                                            Theme::iconColor(), 18));
    deleteButton->setIconSize(QSize(18, 18));
    top->addWidget(deleteButton, 0, Qt::AlignTop);
    detailLayout->addLayout(top);

    auto *filterRow = new QHBoxLayout();
    filterRow->setSpacing(8);
    m_search = new QLineEdit(m_gradientPage);
    m_search->setObjectName(QStringLiteral("searchEdit"));
    m_search->setPlaceholderText(tr("Search in playlist..."));
    m_search->setClearButtonEnabled(true);
    m_searchAction = m_search->addAction(
        IconUtils::tinted(QStringLiteral("search.svg"), Theme::iconColor(), 18),
        QLineEdit::LeadingPosition);
    filterRow->addWidget(m_search, 1);
    m_filterIcon = new QLabel(m_gradientPage);
    m_filterIcon->setPixmap(
        IconUtils::tinted(QStringLiteral("filter.svg"), Theme::iconColor(), 20)
            .pixmap(20, 20));
    filterRow->addWidget(m_filterIcon);
    m_sort = new QComboBox(m_gradientPage);
    m_sort->addItem(tr("By order (drag)"), QStringLiteral("order"));
    m_sort->addItem(tr("By title"), QStringLiteral("title"));
    m_sort->addItem(tr("By artist"), QStringLiteral("artist"));
    m_sort->addItem(tr("By duration"), QStringLiteral("duration"));
    m_sort->addItem(tr("By date added"), QStringLiteral("added"));
    m_sort->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_sort->setMinimumWidth(150);
    filterRow->addWidget(m_sort);
    detailLayout->addLayout(filterRow);

    m_trackCount = new QLabel(m_gradientPage);
    m_trackCount->setObjectName(QStringLiteral("playlistTrackCount"));
    detailLayout->addWidget(m_trackCount);

    m_trackList = new SmoothListWidget(m_gradientPage);
    m_trackList->setObjectName(QStringLiteral("playlistTracks"));
    m_trackList->setUniformItemSizes(true);
    m_trackList->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_trackList->setMouseTracking(true);
    m_trackList->viewport()->setMouseTracking(true);
    m_trackList->setAttribute(Qt::WA_Hover, true);
    m_trackList->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_trackList->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_trackDelegate = new TrackDelegate(m_trackList);
    m_trackList->setItemDelegate(m_trackDelegate);
    m_trackList->setContextMenuPolicy(Qt::CustomContextMenu);
    m_trackList->viewport()->installEventFilter(this);
    detailLayout->addWidget(m_trackList, 1);
    m_stack->addWidget(m_gradientPage);

    auto *deleteShortcut =
        new QShortcut(QKeySequence::Delete, m_trackList);
    deleteShortcut->setContext(Qt::WidgetShortcut);

    connect(newButton, &QPushButton::clicked, this,
            &PlaylistsPage::createPlaylist);
    connect(back, &QPushButton::clicked, this, &PlaylistsPage::showGrid);
    connect(add, &QPushButton::clicked, this, &PlaylistsPage::addTracks);
    connect(deleteButton, &QPushButton::clicked, this,
            &PlaylistsPage::deleteCurrentPlaylist);
    connect(m_detailCover, &QPushButton::clicked, this, [this] {
        changePlaylistCover(m_currentPlaylistId);
    });
    connect(deleteShortcut, &QShortcut::activated, this,
            &PlaylistsPage::removeSelectedTracks);
    connect(m_detailDescription, &QTextEdit::textChanged, this, [this] {
        if (m_core && m_currentPlaylistId > 0) {
            m_core->updatePlaylistDescription(m_currentPlaylistId,
                                              m_detailDescription->toPlainText());
        }
    });
    connect(m_grid, &QListWidget::itemClicked, this,
            [this](QListWidgetItem *item) {
                if (item) {
                    openPlaylist(item->data(TrackIdRole).toLongLong());
                }
            });
    m_grid->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(m_grid, &QListWidget::customContextMenuRequested, this,
            [this](const QPoint &point) {
                QListWidgetItem *item = m_grid->itemAt(point);
                if (!item) {
                    return;
                }
                const qint64 playlistId =
                    item->data(TrackIdRole).toLongLong();
                QString playlistName;
                for (const Playlist &playlist : m_playlists) {
                    if (playlist.id == playlistId) {
                        playlistName = playlist.name;
                        break;
                    }
                }
                QMenu menu(this);
                QAction *play = menu.addAction(
                    IconUtils::tinted(QStringLiteral("play.svg"),
                                      Theme::iconColor(), 16),
                    tr("Play"));
                QAction *cover = menu.addAction(
                    IconUtils::tinted(QStringLiteral("pencil.svg"),
                                      Theme::iconColor(), 16),
                    tr("Change cover"));
                menu.addSeparator();
                QAction *remove = menu.addAction(
                    IconUtils::tinted(QStringLiteral("trash.svg"),
                                      QColor(0xE0, 0x5A, 0x4A), 16),
                    tr("Delete playlist"));
                QAction *chosen =
                    menu.exec(m_grid->viewport()->mapToGlobal(point));
                if (chosen == play) {
                    emit playPlaylistRequested(playlistId);
                } else if (chosen == cover) {
                    changePlaylistCover(playlistId);
                } else if (chosen == remove) {
                    const auto answer = LocalizedMessageBox::question(
                        this, tr("Delete playlist"),
                        tr("Delete playlist '%1'?").arg(playlistName),
                        QMessageBox::Yes | QMessageBox::No,
                        QMessageBox::No);
                    if (answer != QMessageBox::Yes) {
                        return;
                    }
                    m_core->deletePlaylist(playlistId);
                    if (m_currentPlaylistId == playlistId) {
                        m_currentPlaylistId = 0;
                        showGrid();
                    }
                    refresh();
                }
            });
    connect(m_trackList, &QListWidget::customContextMenuRequested, this,
            [this](const QPoint &pos) {
                QListWidgetItem *item = m_trackList->itemAt(pos);
                if (!item) {
                    return;
                }
                if (!item->isSelected()) {
                    m_trackList->clearSelection();
                    item->setSelected(true);
                    m_trackList->setCurrentItem(item);
                }
                emit contextMenuRequested(
                    m_trackList->viewport()->mapToGlobal(pos),
                    item->data(TrackIdRole).toLongLong(),
                    selectedTrackIds());
            });
    connect(m_trackList, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem *item) {
                if (item && m_currentPlaylistId > 0) {
                    emit playPlaylistTrackRequested(
                        m_currentPlaylistId,
                        item->data(TrackIdRole).toLongLong());
                }
            });
    connect(m_search, &QLineEdit::textChanged, this,
            [this] { applyTrackFilter(); });
    connect(m_sort, &QComboBox::activated, this, [this](int index) {
        const QString key = m_sort->itemData(index).toString();
        if (key == m_sort->currentData().toString() &&
            key == m_lastSortKey) {
            m_sortAscending = !m_sortAscending;
        } else {
            m_lastSortKey = key;
            m_sortAscending = key == QStringLiteral("order") ||
                              key == QStringLiteral("title") ||
                              key == QStringLiteral("artist");
        }
        updateSortIndicator();
        applyTrackFilter();
    });
    m_lastSortKey = m_sort->currentData().toString();
    updateSortIndicator();

    refresh();
}

void PlaylistsPage::setLibraryTracks(const QVector<Track> &tracks) {
    m_library = tracks;
}

void PlaylistsPage::setCurrentPlaying(qint64 trackId) {
    if (m_trackDelegate) {
        m_trackDelegate->setCurrentPlaying(trackId);
    }
}

void PlaylistsPage::showAddTracksDialog() {
    addTracks();
}

bool PlaylistsPage::eventFilter(QObject *watched, QEvent *event) {
    if (m_grid && watched == m_grid->viewport() &&
        event->type() == QEvent::MouseMove) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        QListWidgetItem *item = m_grid->itemAt(mouse->position().toPoint());
        auto *delegate = static_cast<PlaylistCoverDelegate *>(
            m_grid->itemDelegate());
        if (delegate) {
            if (item && PlaylistCoverDelegate::playRect(
                            m_grid->visualItemRect(item))
                            .adjusted(-2, -2, 2, 2)
                            .contains(mouse->position().toPoint())) {
                delegate->setHoveredPlayRow(m_grid->row(item));
            } else {
                delegate->setHoveredPlayRow(-1);
            }
        }
    }
    if (m_grid && watched == m_grid->viewport() &&
        event->type() == QEvent::Leave) {
        if (auto *delegate = static_cast<PlaylistCoverDelegate *>(
                m_grid->itemDelegate())) {
            delegate->setHoveredPlayRow(-1);
        }
    }
    if (m_trackList && m_trackDelegate && watched == m_trackList->viewport() &&
        event->type() == QEvent::MouseMove) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        QListWidgetItem *item =
            m_trackList->itemAt(mouse->position().toPoint());
        qint64 hovered = 0;
        if (item) {
            const QRect trash = m_trackDelegate->trashRect(
                m_trackList->visualItemRect(item),
                item->data(TrackDurationRole).toLongLong());
            if (trash.adjusted(-4, -4, 4, 4)
                    .contains(mouse->position().toPoint())) {
                hovered = item->data(TrackIdRole).toLongLong();
            }
        }
        m_trackDelegate->setHoveredTrashTrackId(hovered);
    }
    if (m_trackList && m_trackDelegate &&
        watched == m_trackList->viewport() &&
        event->type() == QEvent::Leave) {
        m_trackDelegate->setHoveredTrashTrackId(0);
    }
    if (m_grid && watched == m_grid->viewport() &&
        event->type() == QEvent::MouseButtonRelease) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            QListWidgetItem *item =
                m_grid->itemAt(mouse->position().toPoint());
            if (item && PlaylistCoverDelegate::playRect(
                            m_grid->visualItemRect(item))
                            .contains(mouse->position().toPoint())) {
                emit playPlaylistRequested(
                    item->data(TrackIdRole).toLongLong());
                return true;
            }
        }
    }
    if (m_trackList && m_trackDelegate &&
        watched == m_trackList->viewport() &&
        event->type() == QEvent::MouseButtonRelease) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            QListWidgetItem *item = m_trackList->itemAt(
                mouse->position().toPoint());
            if (item) {
                const QRect rect = m_trackList->visualItemRect(item);
                const QRect trash = m_trackDelegate->trashRect(
                    rect, item->data(TrackDurationRole).toLongLong());
                if (trash.adjusted(-4, -4, 4, 4)
                        .contains(mouse->position().toPoint())) {
                    removeTracksFromPlaylist(
                        {item->data(TrackIdRole).toLongLong()});
                    return true;
                }
            }
        }
    }
    return QWidget::eventFilter(watched, event);
}

QVector<qint64> PlaylistsPage::selectedTrackIds() const {
    QVector<qint64> ids;
    for (QListWidgetItem *item : m_trackList->selectedItems()) {
        const qint64 id = item->data(TrackIdRole).toLongLong();
        if (id > 0) {
            ids.push_back(id);
        }
    }
    return ids;
}

void PlaylistsPage::removeTracksFromPlaylist(const QVector<qint64> &trackIds) {
    if (!m_core || m_currentPlaylistId <= 0) {
        return;
    }
    for (qint64 id : trackIds) {
        m_core->removeTrackFromPlaylist(m_currentPlaylistId, id);
    }
    refreshDetail();
}

void PlaylistsPage::toggleSelectAll() {
    if (allTracksSelected()) {
        m_trackList->clearSelection();
        return;
    }
    m_trackList->selectAll();
}

bool PlaylistsPage::allTracksSelected() const {
    return m_trackList->count() > 0 &&
           m_trackList->selectedItems().size() >= m_trackList->count();
}

void PlaylistsPage::applyTheme() {
    const auto setIcon = [this](const QString &objectName,
                                const QString &fileName) {
        if (auto *button = findChild<QPushButton *>(objectName)) {
            button->setIcon(IconUtils::tinted(fileName, Theme::iconColor(), 18));
        }
    };
    setIcon(QStringLiteral("newPlaylistButton"),
            QStringLiteral("create-playlist.svg"));
    setIcon(QStringLiteral("playlistBack"), QStringLiteral("back.svg"));
    setIcon(QStringLiteral("playlistDelete"), QStringLiteral("trash.svg"));
    if (m_searchAction) {
        m_searchAction->setIcon(
            IconUtils::tinted(QStringLiteral("search.svg"),
                              Theme::iconColor(), 18));
    }
    if (m_filterIcon) {
        m_filterIcon->setPixmap(
            IconUtils::tinted(QStringLiteral("filter.svg"),
                              Theme::iconColor(), 20)
                .pixmap(20, 20));
    }
    if (m_trackDelegate) {
        m_trackDelegate->resetIcons();
    }
}

void PlaylistsPage::openPlaylistById(qint64 playlistId) {
    refresh();
    openPlaylist(playlistId);
}

void PlaylistsPage::refresh() {
    if (!m_core) {
        return;
    }
    m_playlists = m_core->playlists();
    const QString avatarPath = m_core->profile().avatarPath;
    m_grid->clear();
    for (const Playlist &playlist : m_playlists) {
        Playlist display = playlist;
        if (display.coverPath.isEmpty()) {
            const QVector<Track> tracks = m_core->playlistTracks(playlist.id);
            if (!tracks.isEmpty()) {
                display.coverPath = tracks.first().coverPath;
            }
        }
        auto *item = new QListWidgetItem(m_grid);
        item->setData(TrackIdRole, playlist.id);
        item->setData(TrackTitleRole, playlist.name);
        item->setData(TrackCoverRole, display.coverPath);
        item->setData(TrackCoverIsAvatarRole,
                      CoverCache::sameImage(display.coverPath, avatarPath));
        item->setSizeHint(QSize(180, 210));
    }

    if (m_currentPlaylistId > 0) {
        const bool exists = std::any_of(
            m_playlists.cbegin(), m_playlists.cend(),
            [this](const Playlist &p) { return p.id == m_currentPlaylistId; });
        if (!exists) {
            m_currentPlaylistId = 0;
            showGrid();
        } else {
            refreshDetail();
        }
    } else {
        showGrid();
    }
}

void PlaylistsPage::createPlaylist() {
    if (!m_core) {
        return;
    }
    bool ok = false;
    const QString name = QInputDialog::getText(
        this, tr("New playlist"), tr("Playlist name:"), QLineEdit::Normal,
        QString(), &ok);
    if (!ok || name.trimmed().isEmpty()) {
        return;
    }
    const qint64 id = m_core->createPlaylist(name.trimmed());
    if (id <= 0) {
        QMessageBox::warning(
            this, tr("Playlist"),
            tr("Could not create the playlist. The name may already exist."));
        return;
    }
    refresh();
    openPlaylist(id);
}

void PlaylistsPage::openPlaylist(qint64 playlistId) {
    if (m_grid) {
        m_grid->clearSelection();
        m_grid->setCurrentItem(nullptr);
    }
    m_currentPlaylistId = playlistId;
    refreshDetail();
    m_stack->setCurrentIndex(1);
}

void PlaylistsPage::showGrid() {
    m_currentPlaylistId = 0;
    m_stack->setCurrentIndex(0);
    if (m_grid) {
        m_grid->clearSelection();
        m_grid->setCurrentItem(nullptr);
    }
}

void PlaylistsPage::refreshDetail() {
    if (!m_core || m_currentPlaylistId <= 0) {
        return;
    }
    const Playlist *playlist = nullptr;
    for (const Playlist &candidate : m_playlists) {
        if (candidate.id == m_currentPlaylistId) {
            playlist = &candidate;
            break;
        }
    }
    if (!playlist) {
        showGrid();
        return;
    }

    m_detailTitle->setText(playlist->name);
    m_currentTracks = m_core->playlistTracks(m_currentPlaylistId);
    m_detailDescription->blockSignals(true);
    m_detailDescription->setPlainText(playlist->description);
    m_detailDescription->blockSignals(false);

    QString coverPath = playlist->coverPath;
    if (coverPath.isEmpty() && !m_currentTracks.isEmpty()) {
        coverPath = m_currentTracks.first().coverPath;
    }
    const QPixmap cover = CoverCache::cover(coverPath, 140);
    const QString avatarPath = m_core ? m_core->profile().avatarPath : QString();
    m_detailCover->setCover(cover,
                            CoverCache::sameImage(coverPath, avatarPath));
    auto *page = static_cast<PlaylistDetailPage *>(m_gradientPage);
    page->setCoverColor(averageColor(cover));

    m_search->blockSignals(true);
    m_search->clear();
    m_search->blockSignals(false);
    applyTrackFilter();
}

void PlaylistsPage::applyTrackFilter() {
    if (!m_trackList) {
        return;
    }
    const QString needle =
        m_search ? m_search->text().trimmed().toLower() : QString();
    QVector<Track> tracks;
    tracks.reserve(m_currentTracks.size());
    for (const Track &track : m_currentTracks) {
        if (!needle.isEmpty()) {
            const QString haystack =
                (track.title + QLatin1Char(' ') + track.artist).toLower();
            if (!haystack.contains(needle)) {
                continue;
            }
        }
        tracks.push_back(track);
    }

    const QString sortKey =
        m_sort ? m_sort->currentData().toString() : QStringLiteral("order");
    if (sortKey == QStringLiteral("title")) {
        std::sort(tracks.begin(), tracks.end(),
                  [this](const Track &a, const Track &b) {
                      if (m_sortAscending) {
                          return a.title.toLower() < b.title.toLower();
                      }
                      return b.title.toLower() < a.title.toLower();
                  });
    } else if (sortKey == QStringLiteral("artist")) {
        std::sort(tracks.begin(), tracks.end(),
                  [this](const Track &a, const Track &b) {
                      if (m_sortAscending) {
                          return a.artist.toLower() < b.artist.toLower();
                      }
                      return b.artist.toLower() < a.artist.toLower();
                  });
    } else if (sortKey == QStringLiteral("duration")) {
        std::sort(tracks.begin(), tracks.end(),
                  [this](const Track &a, const Track &b) {
                      return m_sortAscending ? a.duration < b.duration
                                             : a.duration > b.duration;
                  });
    } else if (sortKey == QStringLiteral("added")) {
        std::sort(tracks.begin(), tracks.end(),
                  [this](const Track &a, const Track &b) {
                      return m_sortAscending ? a.addedAt < b.addedAt
                                             : a.addedAt > b.addedAt;
                  });
    }

    m_trackList->clear();
    int index = 0;
    for (const Track &track : tracks) {
        auto *item = new QListWidgetItem(m_trackList);
        item->setData(TrackIdRole, track.id);
        item->setData(TrackTitleRole,
                      track.title.isEmpty() ? tr("Unknown title")
                                            : track.title);
        item->setData(TrackArtistRole,
                      track.artist.isEmpty() ? tr("Unknown artist")
                                             : track.artist);
        item->setData(TrackDurationRole, track.duration);
        item->setData(TrackCoverRole, track.coverPath);
        item->setData(TrackIndexRole, ++index);
        item->setData(IsFolderRole, false);
        item->setData(TrackExistsRole, true);
        item->setSizeHint(QSize(0, 60));
    }
    m_trackCount->setText(
        tr("Tracks in playlist (%1)").arg(tracks.size()));
}

void PlaylistsPage::updateSortIndicator() {
    if (!m_sort) {
        return;
    }
    const QString arrow = m_sortAscending ? QStringLiteral(" ↑")
                                          : QStringLiteral(" ↓");
    for (int i = 0; i < m_sort->count(); ++i) {
        QString text = m_sort->itemText(i);
        text.remove(QStringLiteral(" ↑"));
        text.remove(QStringLiteral(" ↓"));
        if (i == m_sort->currentIndex()) {
            text += arrow;
        }
        m_sort->setItemText(i, text);
    }
}

void PlaylistsPage::changePlaylistCover(qint64 playlistId) {
    if (!m_core || playlistId <= 0) {
        return;
    }
    const QString source = QFileDialog::getOpenFileName(
        this, tr("Choose cover image"), QString(),
        tr("Images (*.png *.jpg *.jpeg *.webp *.bmp)"));
    if (source.isEmpty()) {
        return;
    }
    QDir coverDir(QDir(m_dataDir).filePath(QStringLiteral("playlist_covers")));
    if (!QDir().mkpath(coverDir.path())) {
        QMessageBox::warning(this, tr("Change cover"),
                             tr("Could not create the playlist cover folder."));
        return;
    }
    QString suffix = QFileInfo(source).suffix().toLower();
    if (suffix.isEmpty()) {
        suffix = QStringLiteral("jpg");
    }
    const QString target =
        coverDir.filePath(QString::number(playlistId) +
                          QLatin1Char('.') + suffix);
    if (QFileInfo(source).absoluteFilePath() !=
        QFileInfo(target).absoluteFilePath()) {
        const QFileInfoList oldFiles = coverDir.entryInfoList(
            {QString::number(playlistId) + QStringLiteral(".*")}, QDir::Files);
        for (const QFileInfo &old : oldFiles) {
            QFile::remove(old.absoluteFilePath());
        }
        if (!QFile::copy(source, target)) {
            QMessageBox::warning(this, tr("Change cover"),
                                 tr("Could not save the selected cover."));
            return;
        }
    }
    if (!m_core->updatePlaylistCover(playlistId, target)) {
        QMessageBox::warning(this, tr("Change cover"),
                             tr("Could not update the playlist cover."));
        return;
    }
    CoverCache::clear();
    refresh();
    if (m_currentPlaylistId == playlistId &&
        m_stack->currentIndex() == 1) {
        refreshDetail();
    }
}

void PlaylistsPage::deleteCurrentPlaylist() {
    if (!m_core || m_currentPlaylistId <= 0) {
        return;
    }
    const auto answer = LocalizedMessageBox::question(
        this, tr("Delete playlist"), tr("Delete this playlist?"));
    if (answer != QMessageBox::Yes) {
        return;
    }
    m_core->deletePlaylist(m_currentPlaylistId);
    m_currentPlaylistId = 0;
    refresh();
    showGrid();
}

void PlaylistsPage::addTracks() {
    if (!m_core || m_currentPlaylistId <= 0) {
        return;
    }
    QSet<qint64> existing;
    for (const Track &track : m_currentTracks) {
        existing.insert(track.id);
    }
    AddTracksDialog dialog(m_library, existing, this);
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    for (qint64 trackId : dialog.selectedTrackIds()) {
        m_core->addTrackToPlaylist(m_currentPlaylistId, trackId);
    }
    refreshDetail();
}

void PlaylistsPage::removeSelectedTracks() {
    if (!m_core || m_currentPlaylistId <= 0 || !m_trackList) {
        return;
    }
    const QList<QListWidgetItem *> selected = m_trackList->selectedItems();
    for (QListWidgetItem *item : selected) {
        m_core->removeTrackFromPlaylist(
            m_currentPlaylistId, item->data(TrackIdRole).toLongLong());
    }
    refreshDetail();
}

Track PlaylistsPage::trackById(qint64 trackId) const {
    for (const Track &track : m_currentTracks) {
        if (track.id == trackId) {
            return track;
        }
    }
    for (const Track &track : m_library) {
        if (track.id == trackId) {
            return track;
        }
    }
    return {};
}
