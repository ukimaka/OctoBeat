#include "LibraryPage.h"

#include "CoverCache.h"
#include "IconUtils.h"
#include "SmoothTreeWidget.h"
#include "Theme.h"
#include "TrackDelegate.h"

#include <QAbstractItemModel>
#include <QAction>
#include <QColor>
#include <QComboBox>
#include <QContextMenuEvent>
#include <QFileInfo>
#include <QFont>
#include <QHash>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QIcon>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPushButton>
#include <QSettings>
#include <QSizePolicy>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVariant>
#include <QVBoxLayout>

#include <algorithm>
#include <functional>

namespace {

QString displayTitle(const Track &track) {
    return track.title.isEmpty() ? QObject::tr("Unknown title") : track.title;
}

QString displayArtist(const Track &track) {
    return track.artist.isEmpty() ? QObject::tr("Unknown artist") : track.artist;
}

} // namespace

LibraryPage::LibraryPage(CoreClient *core, QWidget *parent)
    : QWidget(parent), m_core(core) {
    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(18, 14, 18, 10);
    layout->setSpacing(8);

    auto *toolbar = new QHBoxLayout();
    toolbar->setSpacing(6);

    auto iconButton = [this, toolbar](const QString &icon,
                                      const QString &tooltip,
                                      int iconSize = 20) {
        auto *button = new QPushButton(this);
        button->setObjectName(QStringLiteral("libraryToolButton"));
        button->setFlat(true);
        button->setFixedSize(32, 30);
        button->setIconSize(QSize(iconSize, iconSize));
        button->setIcon(IconUtils::tinted(icon, Theme::iconColor(), iconSize));
        button->setToolTip(tooltip);
        button->setCursor(Qt::PointingHandCursor);
        toolbar->addWidget(button);
        m_iconButtons.push_back({button, icon});
        return button;
    };

    auto *import = iconButton(QStringLiteral("add-music.svg"),
                              tr("Import files"), 24);
    auto *folder = iconButton(QStringLiteral("add-folder.svg"),
                              tr("New folder"), 20);
    auto *update = iconButton(QStringLiteral("update-track-info.svg"),
                              tr("Update track info"), 20);
    auto *random = iconButton(QStringLiteral("random.svg"),
                              tr("Play random"), 20);
    toolbar->addStretch(1);

    m_nextContainer = new QWidget(this);
    m_nextContainer->setObjectName(QStringLiteral("nextTrackContainer"));
    auto *nextLayout = new QHBoxLayout(m_nextContainer);
    nextLayout->setContentsMargins(0, 0, 0, 0);
    nextLayout->setSpacing(6);
    auto *nextCaption = new QLabel(tr("Next in queue"), m_nextContainer);
    nextCaption->setObjectName(QStringLiteral("nextTrackCaption"));
    auto *nextCard = new QWidget(m_nextContainer);
    nextCard->setObjectName(QStringLiteral("nextTrackIsland"));
    nextCard->setAttribute(Qt::WA_StyledBackground, true);
    auto *cardLayout = new QHBoxLayout(nextCard);
    cardLayout->setContentsMargins(6, 3, 10, 3);
    cardLayout->setSpacing(8);
    m_nextCover = new QLabel(nextCard);
    m_nextCover->setFixedSize(28, 28);
    m_nextTitle = new QLabel(nextCard);
    m_nextTitle->setObjectName(QStringLiteral("nextTrackTitle"));
    m_nextTitle->setMaximumWidth(190);
    m_nextArtist = new QLabel(nextCard);
    m_nextArtist->setObjectName(QStringLiteral("nextTrackArtist"));
    m_nextArtist->setMaximumWidth(130);
    cardLayout->addWidget(m_nextCover);
    cardLayout->addWidget(m_nextTitle);
    cardLayout->addWidget(m_nextArtist);
    nextLayout->addWidget(nextCaption);
    nextLayout->addWidget(nextCard);
    m_nextContainer->hide();
    toolbar->addWidget(m_nextContainer, 0);
    toolbar->addSpacing(12);

    m_count = new QLabel(this);
    m_count->setObjectName(QStringLiteral("libraryStatus"));
    toolbar->addWidget(m_count);
    layout->addLayout(toolbar);

    auto *filterRow = new QHBoxLayout();
    filterRow->setSpacing(8);
    m_search = new QLineEdit(this);
    m_search->setObjectName(QStringLiteral("searchEdit"));
    m_search->setPlaceholderText(tr("Search by title or artist..."));
    m_search->setClearButtonEnabled(true);
    m_searchAction = m_search->addAction(
        IconUtils::tinted(QStringLiteral("search.svg"), Theme::iconColor(), 18),
        QLineEdit::LeadingPosition);
    filterRow->addWidget(m_search, 1);

    m_filterIcon = new QLabel(this);
    m_filterIcon->setPixmap(
        IconUtils::tinted(QStringLiteral("filter.svg"), Theme::iconColor(), 20)
            .pixmap(20, 20));
    m_filterIcon->setStyleSheet(QStringLiteral(
        "background: transparent; border: none; padding: 0; margin: 0;"));
    filterRow->addWidget(m_filterIcon);

    m_sort = new QComboBox(this);
    m_sort->setObjectName(QStringLiteral("librarySort"));
    m_sort->addItem(tr("Date added"), QStringLiteral("added"));
    m_sort->addItem(tr("Title"), QStringLiteral("title"));
    m_sort->addItem(tr("Artist"), QStringLiteral("artist"));
    m_sort->addItem(tr("Duration"), QStringLiteral("duration"));
    m_sort->setSizeAdjustPolicy(QComboBox::AdjustToContents);
    m_sort->setMinimumWidth(150);
    filterRow->addWidget(m_sort);
    layout->addLayout(filterRow);

    m_tree = new SmoothTreeWidget(this);
    m_tree->setObjectName(QStringLiteral("libraryList"));
    m_tree->setHeaderHidden(true);
    m_tree->setColumnCount(1);
    m_tree->setRootIsDecorated(true);
    m_tree->setIndentation(6);
    m_tree->setUniformRowHeights(true);
    m_tree->setAnimated(false);
    m_tree->setExpandsOnDoubleClick(false);
    m_tree->setMouseTracking(true);
    m_tree->viewport()->setMouseTracking(true);
    m_tree->setAttribute(Qt::WA_Hover, true);
    m_tree->setIconSize(QSize(50, 50));
    m_tree->setSelectionMode(QAbstractItemView::ExtendedSelection);
    m_tree->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_tree->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_tree->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    m_tree->setMinimumSize(0, 0);
    m_tree->setDragEnabled(true);
    m_tree->setAcceptDrops(true);
    m_tree->setDropIndicatorShown(true);
    m_tree->setDragDropMode(QAbstractItemView::InternalMove);
    m_tree->setDefaultDropAction(Qt::MoveAction);
    m_delegate = new TrackDelegate(m_tree);
    m_tree->setItemDelegate(m_delegate);
    m_tree->setContextMenuPolicy(Qt::CustomContextMenu);
    m_tree->viewport()->installEventFilter(this);
    layout->addWidget(m_tree, 1);

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    for (const QVariant &value : settings.value(QStringLiteral("collapsed_folders")).toList()) {
        bool ok = false;
        const qint64 id = value.toLongLong(&ok);
        if (ok) {
            m_collapsed.insert(id);
        }
    }

    connect(import, &QPushButton::clicked, this,
            &LibraryPage::importFilesRequested);
    connect(folder, &QPushButton::clicked, this, &LibraryPage::createFolder);
    connect(update, &QPushButton::clicked, this, &LibraryPage::scanRequested);
    connect(random, &QPushButton::clicked, this, &LibraryPage::randomRequested);
    connect(m_search, &QLineEdit::textChanged, this,
            [this] { rebuild(); });
    connect(m_sort, &QComboBox::activated, this, [this](int index) {
        const QString key = m_sort->itemData(index).toString();
        if (key == m_sortKey) {
            m_sortAscending = !m_sortAscending;
        } else {
            m_sortKey = key;
            m_sortAscending = key == QStringLiteral("title") ||
                              key == QStringLiteral("artist");
        }
        updateSortIndicator();
        rebuild();
    });
    updateSortIndicator();
    connect(m_tree, &QTreeWidget::customContextMenuRequested, this,
            [this](const QPoint &pos) {
                QTreeWidgetItem *item = m_tree->itemAt(pos);
                if (!item || item->data(0, IsFolderRole).toBool()) {
                    return;
                }
                if (!item->isSelected()) {
                    m_tree->clearSelection();
                    item->setSelected(true);
                    m_tree->setCurrentItem(item);
                }
                const QVector<qint64> ids = selectedTrackIds();
                emit contextMenuRequested(
                    m_tree->viewport()->mapToGlobal(pos),
                    item->data(0, TrackIdRole).toLongLong(), ids);
            });
    connect(m_tree, &QTreeWidget::itemDoubleClicked, this,
            [this](QTreeWidgetItem *item, int) {
                if (item && item->data(0, IsFolderRole).toBool()) {
                    item->setExpanded(!item->isExpanded());
                    return;
                }
                activateItem(item);
            });
    connect(m_tree, &QTreeWidget::itemActivated, this,
            [this](QTreeWidgetItem *item, int) { activateItem(item); });
    connect(m_tree, &QTreeWidget::itemExpanded, this,
            [this](QTreeWidgetItem *item) {
                if (!item) {
                    return;
                }
                m_collapsed.remove(item->data(0, FolderIdRole).toLongLong());
                QSettings settings(QStringLiteral("MusicPlayer"),
                                   QStringLiteral("MusicPlayer"));
                QVariantList list;
                for (qint64 id : m_collapsed) {
                    list.push_back(id);
                }
                settings.setValue(QStringLiteral("collapsed_folders"), list);
            });
    connect(m_tree, &QTreeWidget::itemCollapsed, this,
            [this](QTreeWidgetItem *item) {
                if (!item) {
                    return;
                }
                m_collapsed.insert(item->data(0, FolderIdRole).toLongLong());
                QSettings settings(QStringLiteral("MusicPlayer"),
                                   QStringLiteral("MusicPlayer"));
                QVariantList list;
                for (qint64 id : m_collapsed) {
                    list.push_back(id);
                }
                settings.setValue(QStringLiteral("collapsed_folders"), list);
            });
    connect(m_tree, &SmoothTreeWidget::itemsMoved, this,
            [this] { syncFoldersToDatabase(); });

    rebuild();
}

void LibraryPage::setTracks(const QVector<Track> &tracks) {
    m_tracks = tracks;
    rebuild();
}

void LibraryPage::rebuild() {
    if (!m_tree) {
        return;
    }

    const QString needle = m_search ? m_search->text().trimmed().toLower()
                                    : QString();
    QVector<Track> visible;
    visible.reserve(m_tracks.size());
    for (const Track &track : m_tracks) {
        if (!needle.isEmpty()) {
            const QString haystack =
                (displayTitle(track) + QLatin1Char(' ') + displayArtist(track))
                    .toLower();
            if (!haystack.contains(needle)) {
                continue;
            }
        }
        visible.push_back(track);
    }

    const auto sortTracks = [this](QVector<Track> &tracks) {
        if (m_sortKey == QStringLiteral("title")) {
            std::sort(tracks.begin(), tracks.end(),
                      [this](const Track &a, const Track &b) {
                          if (m_sortAscending) {
                              return displayTitle(a).toLower() <
                                     displayTitle(b).toLower();
                          }
                          return displayTitle(b).toLower() <
                                 displayTitle(a).toLower();
                      });
        } else if (m_sortKey == QStringLiteral("artist")) {
            std::sort(tracks.begin(), tracks.end(),
                      [this](const Track &a, const Track &b) {
                          if (m_sortAscending) {
                              return displayArtist(a).toLower() <
                                     displayArtist(b).toLower();
                          }
                          return displayArtist(b).toLower() <
                                 displayArtist(a).toLower();
                      });
        } else if (m_sortKey == QStringLiteral("duration")) {
            std::sort(tracks.begin(), tracks.end(),
                      [this](const Track &a, const Track &b) {
                          return m_sortAscending ? a.duration < b.duration
                                                 : a.duration > b.duration;
                      });
        } else {
            std::sort(tracks.begin(), tracks.end(),
                      [this](const Track &a, const Track &b) {
                          return m_sortAscending ? a.id < b.id : a.id > b.id;
                      });
        }
    };
    sortTracks(visible);

    QVector<Folder> folders;
    if (m_core) {
        folders = m_core->folders();
    }

    QHash<qint64, QVector<Track>> byFolder;
    QVector<Track> rootTracks;
    for (const Track &track : visible) {
        if (track.folderId > 0) {
            byFolder[track.folderId].push_back(track);
        } else {
            rootTracks.push_back(track);
        }
    }
    for (auto it = byFolder.begin(); it != byFolder.end(); ++it) {
        sortTracks(*it);
    }

    m_tree->setUpdatesEnabled(false);
    m_tree->clear();
    int index = 0;
    for (const Folder &folder : folders) {
        QTreeWidgetItem *folderItem = makeFolderItem(folder);
        m_tree->addTopLevelItem(folderItem);
        const QVector<Track> tracks = byFolder.value(folder.id);
        for (const Track &track : tracks) {
            folderItem->addChild(makeTrackItem(track, ++index));
        }
        folderItem->setExpanded(!m_collapsed.contains(folder.id));
    }
    for (const Track &track : rootTracks) {
        m_tree->addTopLevelItem(makeTrackItem(track, ++index));
    }
    m_tree->setUpdatesEnabled(true);

    if (m_count) {
        m_count->setText(tr("Library (%1 tracks)").arg(visible.size()));
    }
}

QTreeWidgetItem *LibraryPage::makeTrackItem(const Track &track, int index) {
    auto *item = new QTreeWidgetItem();
    item->setData(0, TrackIdRole, track.id);
    item->setData(0, TrackTitleRole, displayTitle(track));
    item->setData(0, TrackArtistRole, displayArtist(track));
    item->setData(0, TrackDurationRole, track.duration);
    item->setData(0, TrackCoverRole, track.coverPath);
    item->setData(0, TrackIndexRole, index);
    item->setData(0, IsFolderRole, false);
    item->setData(0, TrackExistsRole, QFileInfo::exists(track.filePath));
    item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                   Qt::ItemIsDragEnabled);
    item->setSizeHint(0, QSize(0, 60));
    return item;
}

QTreeWidgetItem *LibraryPage::makeFolderItem(const Folder &folder) {
    auto *item = new QTreeWidgetItem();
    item->setData(0, IsFolderRole, true);
    item->setData(0, FolderIdRole, folder.id);
    item->setData(0, FolderNameRole, folder.name);
    item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                   Qt::ItemIsDropEnabled);
    item->setSizeHint(0, QSize(0, 60));
    return item;
}

void LibraryPage::updateSortIndicator() {
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

void LibraryPage::filter() {
    rebuild();
}

void LibraryPage::activateItem(QTreeWidgetItem *item) {
    if (!item) {
        return;
    }
    if (item->data(0, IsFolderRole).toBool()) {
        item->setExpanded(!item->isExpanded());
        return;
    }
    const qint64 id = item->data(0, TrackIdRole).toLongLong();
    if (id > 0) {
        emit playRequested(id);
    }
}

void LibraryPage::createFolder() {
    if (!m_core) {
        return;
    }
    bool ok = false;
    const QString name = QInputDialog::getText(
        this, tr("New folder"), tr("Folder name:"), QLineEdit::Normal,
        QString(), &ok);
    if (!ok || name.trimmed().isEmpty()) {
        return;
    }
    const qint64 id = m_core->createFolder(name.trimmed());
    if (id <= 0) {
        QMessageBox::warning(this, tr("New folder"),
                             tr("A folder with this name already exists."));
        return;
    }
    rebuild();
}

void LibraryPage::syncFoldersToDatabase() {
    if (!m_core) {
        return;
    }
    std::function<void(QTreeWidgetItem *, qint64)> walk;
    walk = [this, &walk](QTreeWidgetItem *item, qint64 folderId) {
        if (!item) {
            return;
        }
        if (item->data(0, IsFolderRole).toBool()) {
            const qint64 id = item->data(0, FolderIdRole).toLongLong();
            for (int i = 0; i < item->childCount(); ++i) {
                walk(item->child(i), id);
            }
            return;
        }
        const qint64 trackId = item->data(0, TrackIdRole).toLongLong();
        if (trackId > 0) {
            m_core->moveTrackToFolder(trackId, folderId);
        }
    };
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        walk(m_tree->topLevelItem(i), 0);
    }
}

QVector<qint64> LibraryPage::orderedTrackIds() const {
    QVector<qint64> ids;
    std::function<void(QTreeWidgetItem *)> walk = [&](QTreeWidgetItem *item) {
        if (!item) {
            return;
        }
        if (item->data(0, IsFolderRole).toBool()) {
            for (int i = 0; i < item->childCount(); ++i) {
                walk(item->child(i));
            }
            return;
        }
        const qint64 id = item->data(0, TrackIdRole).toLongLong();
        if (id > 0) {
            ids.push_back(id);
        }
    };
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        walk(m_tree->topLevelItem(i));
    }
    return ids;
}

void LibraryPage::setStatus(const QString &status) {
    if (m_count) {
        m_count->setText(status);
    }
}

void LibraryPage::setNextTrack(const Track &track) {
    if (!m_nextContainer) {
        return;
    }
    m_nextTitle->setText(displayTitle(track));
    m_nextArtist->setText(displayArtist(track));
    m_nextTitle->setToolTip(displayTitle(track));
    m_nextArtist->setToolTip(displayArtist(track));
    const QPixmap cover = CoverCache::cover(track.coverPath, 28);
    if (!cover.isNull()) {
        m_nextCover->setPixmap(cover);
    } else {
        m_nextCover->clear();
    }
    m_nextContainer->show();
}

void LibraryPage::clearNextTrack() {
    if (m_nextContainer) {
        m_nextContainer->hide();
    }
}

void LibraryPage::setCurrentPlaying(qint64 trackId) {
    if (m_delegate) {
        m_delegate->setCurrentPlaying(trackId);
    }
}

bool LibraryPage::eventFilter(QObject *watched, QEvent *event) {
    if (watched == m_tree->viewport() && event->type() == QEvent::MouseMove) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        QTreeWidgetItem *item = m_tree->itemAt(mouse->position().toPoint());
        qint64 hovered = 0;
        if (item && !item->data(0, IsFolderRole).toBool() &&
            m_delegate) {
            const QRect trash = m_delegate->trashRect(
                m_tree->visualItemRect(item),
                item->data(0, TrackDurationRole).toLongLong());
            if (trash.adjusted(-4, -4, 4, 4)
                    .contains(mouse->position().toPoint())) {
                hovered = item->data(0, TrackIdRole).toLongLong();
            }
        }
        if (m_delegate) {
            m_delegate->setHoveredTrashTrackId(hovered);
        }
    }
    if (watched == m_tree->viewport() && event->type() == QEvent::Leave) {
        if (m_delegate) {
            m_delegate->setHoveredTrashTrackId(0);
        }
    }
    if (m_tree && m_delegate && watched == m_tree->viewport() &&
        event->type() == QEvent::MouseButtonRelease) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            QTreeWidgetItem *item = m_tree->itemAt(mouse->position().toPoint());
            if (item && !item->data(0, IsFolderRole).toBool()) {
                const QRect rect = m_tree->visualItemRect(item);
                const QRect trash = m_delegate->trashRect(
                    rect, item->data(0, TrackDurationRole).toLongLong());
                if (trash.adjusted(-4, -4, 4, 4)
                        .contains(mouse->position().toPoint())) {
                    emit removeTrackRequested(
                        item->data(0, TrackIdRole).toLongLong());
                    return true;
                }
            }
        }
    }
    return QWidget::eventFilter(watched, event);
}

QVector<qint64> LibraryPage::selectedTrackIds() const {
    QVector<qint64> ids;
    for (QTreeWidgetItem *item : m_tree->selectedItems()) {
        if (!item->data(0, IsFolderRole).toBool()) {
            const qint64 id = item->data(0, TrackIdRole).toLongLong();
            if (id > 0) {
                ids.push_back(id);
            }
        }
    }
    return ids;
}

void LibraryPage::toggleSelectAll() {
    if (allTracksSelected()) {
        m_tree->clearSelection();
        return;
    }
    m_tree->clearSelection();
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        QTreeWidgetItem *top = m_tree->topLevelItem(i);
        if (top->data(0, IsFolderRole).toBool()) {
            for (int j = 0; j < top->childCount(); ++j) {
                top->child(j)->setSelected(true);
            }
        } else {
            top->setSelected(true);
        }
    }
}

bool LibraryPage::allTracksSelected() const {
    int total = 0;
    int selected = 0;
    for (int i = 0; i < m_tree->topLevelItemCount(); ++i) {
        QTreeWidgetItem *top = m_tree->topLevelItem(i);
        const auto countItem = [&](QTreeWidgetItem *item) {
            if (!item->data(0, IsFolderRole).toBool()) {
                ++total;
                if (item->isSelected()) {
                    ++selected;
                }
            }
        };
        if (top->data(0, IsFolderRole).toBool()) {
            for (int j = 0; j < top->childCount(); ++j) {
                countItem(top->child(j));
            }
        } else {
            countItem(top);
        }
    }
    return total > 0 && selected >= total;
}

void LibraryPage::applyTheme() {
    for (const auto &entry : m_iconButtons) {
        entry.first->setIcon(
            IconUtils::tinted(entry.second, Theme::iconColor(), 20));
    }
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
    if (m_delegate) {
        m_delegate->resetIcons();
    }
}

void LibraryPage::focusSearch() {
    if (m_search) {
        m_search->setFocus();
        m_search->selectAll();
    }
}

QVector<qint64> LibraryPage::collapsedFolders() const {
    QVector<qint64> ids;
    for (qint64 id : m_collapsed) {
        ids.push_back(id);
    }
    return ids;
}
