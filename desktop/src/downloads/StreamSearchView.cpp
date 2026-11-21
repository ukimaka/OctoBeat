#include "StreamSearchView.h"

#include "RemoteImageCache.h"
#include "StreamItemRow.h"
#include "app/IconUtils.h"
#include "app/SmoothListWidget.h"

#include <QButtonGroup>

#include <algorithm>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidgetItem>
#include <QPushButton>
#include <QToolButton>
#include <QVBoxLayout>

StreamSearchView::StreamSearchView(RemoteImageCache *images, QWidget *parent)
    : QWidget(parent), m_images(images) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(18, 10, 18, 10);
    root->setSpacing(8);

    auto *filters = new QHBoxLayout();
    filters->setSpacing(6);
    auto *group = new QButtonGroup(this);
    m_filterGroup = group;
    group->setExclusive(true);
    const QVector<QPair<QString, YouTubeSearchService::Filter>> filterItems = {
        {tr("All"), YouTubeSearchService::Filter::All},
        {tr("Tracks"), YouTubeSearchService::Filter::Tracks},
        {tr("Artists"), YouTubeSearchService::Filter::Artists},
        {tr("Playlists"), YouTubeSearchService::Filter::Playlists},
    };
    for (int i = 0; i < filterItems.size(); ++i) {
        auto *button = new QPushButton(filterItems[i].first, this);
        button->setObjectName(QStringLiteral("searchFilterButton"));
        button->setCheckable(true);
        button->setCursor(Qt::PointingHandCursor);
        button->setChecked(i == 0);
        group->addButton(button, i);
        filters->addWidget(button);
    }
    filters->addStretch(1);
    connect(group, &QButtonGroup::idClicked, this, [this, filterItems](int id) {
        if (id >= 0 && id < filterItems.size()) {
            emit filterChanged(filterItems[id].second);
        }
    });
    root->addLayout(filters);

    m_empty = new QLabel(this);
    m_empty->setObjectName(QStringLiteral("streamEmpty"));
    m_empty->setAlignment(Qt::AlignCenter);
    m_empty->setWordWrap(true);
    m_empty->hide();
    root->addWidget(m_empty);

    m_list = new SmoothListWidget(this);
    m_list->setObjectName(QStringLiteral("streamSearchResults"));
    m_list->setUniformItemSizes(true);
    m_list->setSelectionMode(QAbstractItemView::SingleSelection);
    m_list->setVerticalScrollMode(QAbstractItemView::ScrollPerPixel);
    m_list->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    root->addWidget(m_list, 1);

    connect(m_list, &QListWidget::currentItemChanged, this,
            [this](QListWidgetItem *current, QListWidgetItem *previous) {
                if (previous) {
                    if (auto *row = qobject_cast<StreamItemRow *>(
                            m_list->itemWidget(previous))) {
                        row->setSelected(false);
                    }
                }
                if (current) {
                    if (auto *row = qobject_cast<StreamItemRow *>(
                            m_list->itemWidget(current))) {
                        row->setSelected(true);
                    }
                }
            });
    connect(m_list, &QListWidget::itemClicked, this,
            [this](QListWidgetItem *item) {
                if (m_historyMode && item) {
                    emit historyRequested(item->text());
                }
            });
    connect(m_list, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem *item) {
                if (!item) {
                    return;
                }
                if (m_historyMode) {
                    emit historyRequested(item->text());
                    return;
                }
                const QString key = item->data(Qt::UserRole).toString();
                const SearchResult result = m_results.value(key);
                if (result.kind == SearchResult::Kind::Track) {
                    emit playRequested(result);
                } else {
                    emit openRequested(result);
                }
            });
    connect(m_list, &QListWidget::itemActivated, this,
            [this](QListWidgetItem *item) {
                if (!item) {
                    return;
                }
                if (m_historyMode) {
                    emit historyRequested(item->text());
                }
            });
}

QString StreamSearchView::keyFor(const SearchResult &result) const {
    return QString::number(static_cast<int>(result.kind)) + QLatin1Char(':') +
           result.id;
}

void StreamSearchView::clearList() {
    m_list->clear();
    m_rows.clear();
    m_results.clear();
}

void StreamSearchView::setQuery(const QString &query) {
    m_query = query;
}

void StreamSearchView::setResults(const QVector<SearchResult> &results) {
    clearList();
    m_historyMode = false;
    if (m_filterGroup) {
        for (QAbstractButton *button : m_filterGroup->buttons()) {
            button->setVisible(true);
        }
    }
    m_empty->hide();
    if (results.isEmpty()) {
        m_empty->setText(tr("Nothing found. Try another query."));
        m_empty->show();
        return;
    }
    QSet<QString> added;
    const auto addRow = [&](const SearchResult &result, int indent) {
        const QString key = keyFor(result);
        if (added.contains(key)) {
            return;
        }
        added.insert(key);
        auto *item = new QListWidgetItem(m_list);
        item->setSizeHint(QSize(0, 80));
        item->setData(Qt::UserRole, key);
        m_results.insert(key, result);
        auto *row =
            new StreamItemRow(result, m_images, m_list, true, indent);
        m_list->setItemWidget(item, row);
        m_rows.insert(key, row);
        connect(row, &StreamItemRow::activated, this, [this, item] {
            m_list->setCurrentItem(item);
        });
        connect(row, &StreamItemRow::playRequested, this,
                &StreamSearchView::playRequested);
        connect(row, &StreamItemRow::downloadRequested, this,
                &StreamSearchView::downloadRequested);
        connect(row, &StreamItemRow::queueRequested, this,
                &StreamSearchView::queueRequested);
        connect(row, &StreamItemRow::openRequested, this,
                &StreamSearchView::openRequested);
    };

    if (m_filter == YouTubeSearchService::Filter::Tracks) {
        QVector<SearchResult> tracks;
        for (const SearchResult &result : results) {
            if (result.kind == SearchResult::Kind::Track) {
                tracks.push_back(result);
            }
        }
        std::stable_sort(tracks.begin(), tracks.end(),
                         [](const SearchResult &a, const SearchResult &b) {
                             const int byArtist =
                                 a.uploader.localeAwareCompare(b.uploader);
                             if (byArtist != 0) {
                                 return byArtist < 0;
                             }
                             const int byChannel =
                                 a.channelId.compare(b.channelId);
                             if (byChannel != 0) {
                                 return byChannel < 0;
                             }
                             return a.title.localeAwareCompare(b.title) < 0;
                         });
        for (const SearchResult &result : tracks) {
            addRow(result, 0);
        }
        m_list->setCurrentRow(0);
        return;
    }
    if (m_filter == YouTubeSearchService::Filter::Artists) {
        for (const SearchResult &result : results) {
            if (result.kind == SearchResult::Kind::Artist) {
                addRow(result, 0);
            }
        }
        m_list->setCurrentRow(0);
        return;
    }

    const bool playlistsOnly =
        m_filter == YouTubeSearchService::Filter::Playlists;

    struct Group {
        SearchResult header;
        QVector<SearchResult> items;
    };
    QVector<Group> groups;
    QHash<QString, int> groupByChannel;
    QHash<QString, QVector<int>> groupsByName;
    QVector<SearchResult> otherResults;

    for (const SearchResult &result : results) {
        if (result.kind == SearchResult::Kind::Artist) {
            Group group;
            group.header = result;
            const int index = groups.size();
            groups.push_back(group);
            if (!result.channelId.isEmpty()) {
                groupByChannel.insert(result.channelId, index);
            }
            groupsByName[result.title.toLower()].push_back(index);
        } else {
            if (playlistsOnly &&
                result.kind != SearchResult::Kind::Playlist) {
                continue;
            }
            otherResults.push_back(result);
        }
    }

    QSet<QString> assigned;
    const auto assign = [&](int groupIndex, const SearchResult &item) {
        const QString key = keyFor(item);
        if (assigned.contains(key) ||
            groups[groupIndex].items.size() >= 20) {
            return false;
        }
        assigned.insert(key);
        groups[groupIndex].items.push_back(item);
        return true;
    };

    // First pass: exact channel ownership. This keeps two artists with the
    // same display name apart.
    for (const SearchResult &item : otherResults) {
        if (item.channelId.isEmpty()) {
            continue;
        }
        const auto it = groupByChannel.constFind(item.channelId);
        if (it != groupByChannel.constEnd()) {
            assign(it.value(), item);
        }
    }

    // Second pass: name match only when exactly one artist has that name.
    for (const SearchResult &item : otherResults) {
        if (assigned.contains(keyFor(item)) || item.uploader.isEmpty()) {
            continue;
        }
        const auto it = groupsByName.constFind(item.uploader.toLower());
        if (it != groupsByName.constEnd() && it.value().size() == 1) {
            assign(it.value().first(), item);
        }
    }

    // Remaining items get a synthetic artist group so the searched track is
    // still shown under its author.
    QHash<QString, int> syntheticByChannel;
    QHash<QString, int> syntheticByName;
    for (const SearchResult &item : otherResults) {
        if (assigned.contains(keyFor(item)) || item.uploader.isEmpty()) {
            continue;
        }
        const QString channelKey = item.channelId;
        int groupIndex = -1;
        if (!channelKey.isEmpty()) {
            groupIndex = syntheticByChannel.value(channelKey, -1);
        }
        if (groupIndex < 0 && groupsByName.value(item.uploader.toLower()).isEmpty()) {
            groupIndex = syntheticByName.value(item.uploader.toLower(), -1);
        }
        if (groupIndex < 0) {
            Group group;
            group.header.kind = SearchResult::Kind::Artist;
            group.header.title = item.uploader;
            group.header.uploader = item.uploader;
            group.header.channelId = item.channelId;
            group.header.id = item.channelId;
            group.header.thumbnail = item.thumbnail;
            group.header.url =
                item.channelId.isEmpty()
                    ? QString()
                    : QStringLiteral("https://www.youtube.com/channel/") +
                          item.channelId + QStringLiteral("/videos");
            groupIndex = groups.size();
            groups.push_back(group);
            if (!channelKey.isEmpty()) {
                syntheticByChannel.insert(channelKey, groupIndex);
            }
            syntheticByName.insert(item.uploader.toLower(), groupIndex);
        }
        assign(groupIndex, item);
    }

    for (const Group &group : groups) {
        if (group.header.title.isEmpty()) {
            continue;
        }
        addRow(group.header, 0);
        for (const SearchResult &item : group.items) {
            addRow(item, 34);
        }
    }
    m_list->setCurrentRow(0);
}

void StreamSearchView::setHistory(const QStringList &history) {
    clearList();
    m_historyMode = true;
    if (m_filterGroup) {
        for (QAbstractButton *button : m_filterGroup->buttons()) {
            button->setVisible(false);
        }
    }
    m_empty->hide();
    if (history.isEmpty()) {
        m_empty->setText(tr("Your search history is empty."));
        m_empty->show();
        return;
    }
    for (const QString &query : history) {
        auto *item = new QListWidgetItem(
            IconUtils::tinted(QStringLiteral("time.svg"),
                              QColor(180, 180, 190), 16),
            query, m_list);
        item->setSizeHint(QSize(0, 40));
    }
}

void StreamSearchView::setFilter(YouTubeSearchService::Filter filter) {
    m_filter = filter;
    if (!m_filterGroup) {
        return;
    }
    int id = 0;
    switch (filter) {
    case YouTubeSearchService::Filter::Tracks:
        id = 1;
        break;
    case YouTubeSearchService::Filter::Artists:
        id = 2;
        break;
    case YouTubeSearchService::Filter::Playlists:
        id = 3;
        break;
    case YouTubeSearchService::Filter::All:
        id = 0;
        break;
    }
    if (QAbstractButton *button = m_filterGroup->button(id)) {
        button->setChecked(true);
    }
}

void StreamSearchView::setLoading(bool loading) {
    Q_UNUSED(loading);
}

void StreamSearchView::setBusyFor(const QString &id, bool busy) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id &&
            it.value().kind == SearchResult::Kind::Track) {
            if (auto *row = m_rows.value(it.key())) {
                row->setBusy(busy);
            }
        }
    }
}

void StreamSearchView::setDownloadProgress(const QString &id, int progress) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id &&
            it.value().kind == SearchResult::Kind::Track) {
            if (auto *row = m_rows.value(it.key())) {
                row->setDownloadBusy(progress >= 0, progress);
            }
        }
    }
}

void StreamSearchView::setPlaying(const QString &id, bool playing) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id &&
            it.value().kind == SearchResult::Kind::Track) {
            if (auto *row = m_rows.value(it.key())) {
                row->setPlaying(playing);
            }
        }
    }
}
