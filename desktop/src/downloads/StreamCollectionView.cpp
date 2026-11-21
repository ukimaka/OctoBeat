#include "StreamCollectionView.h"

#include "RemoteImageCache.h"
#include "StreamCard.h"
#include "StreamItemRow.h"

#include <QApplication>
#include <QMouseEvent>
#include "app/IconUtils.h"
#include "app/SmoothListWidget.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QListWidgetItem>
#include <QPainter>
#include <QPainterPath>
#include <QPointer>
#include <QPushButton>
#include <QScrollArea>
#include <QToolButton>
#include <QVBoxLayout>

namespace {

QPixmap roundedPixmap(const QPixmap &source,
                      const QSize &size,
                      qreal radius) {
    if (source.isNull()) {
        return {};
    }
    QPixmap output(source.size());
    output.setDevicePixelRatio(source.devicePixelRatio());
    output.fill(Qt::transparent);
    QPainter painter(&output);
    painter.setRenderHint(QPainter::Antialiasing, true);
    QPainterPath path;
    path.addRoundedRect(QRectF(0, 0, size.width(), size.height()), radius,
                        radius);
    painter.setClipPath(path);
    painter.drawPixmap(0, 0, source);
    return output;
}

} // namespace

StreamCollectionView::StreamCollectionView(RemoteImageCache *images,
                                           QWidget *parent)
    : QWidget(parent), m_images(images) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(18, 10, 18, 10);
    root->setSpacing(8);

    auto *header = new QHBoxLayout();
    auto *back = new QToolButton(this);
    back->setObjectName(QStringLiteral("streamBackButton"));
    back->setFixedSize(34, 34);
    back->setIcon(IconUtils::tinted(QStringLiteral("back.svg"),
                                    QColor(220, 220, 232), 22));
    back->setIconSize(QSize(22, 22));
    back->setCursor(Qt::PointingHandCursor);
    back->setAutoRaise(true);
    connect(back, &QToolButton::clicked, this,
            &StreamCollectionView::backRequested);
    header->addWidget(back);

    m_cover = new QLabel(this);
    m_cover->setFixedSize(64, 64);
    m_cover->setAlignment(Qt::AlignCenter);
    header->addWidget(m_cover);

    auto *titles = new QVBoxLayout();
    titles->setContentsMargins(0, 0, 0, 0);
    titles->setSpacing(2);
    m_title = new QLabel(this);
    m_title->setObjectName(QStringLiteral("streamViewTitle"));
    QFont titleFont = m_title->font();
    titleFont.setPixelSize(20);
    titleFont.setBold(true);
    m_title->setFont(titleFont);
    m_subtitle = new QLabel(this);
    m_subtitle->setObjectName(QStringLiteral("streamViewSubtitle"));
    m_subtitle->setWordWrap(true);
    titles->addWidget(m_title);
    titles->addWidget(m_subtitle);
    header->addLayout(titles, 1);

    m_playAll = new QPushButton(tr("Play all"), this);
    m_playAll->setObjectName(QStringLiteral("streamPlayAll"));
    m_playAll->setCursor(Qt::PointingHandCursor);
    m_playAll->setIcon(IconUtils::tinted(QStringLiteral("play.svg"),
                                         QColor(220, 220, 232), 16));
    m_playAll->setIconSize(QSize(16, 16));
    m_playAll->hide();
    connect(m_playAll, &QPushButton::clicked, this, [this] {
        emit playAllRequested(m_header);
    });
    header->addWidget(m_playAll, 0, Qt::AlignVCenter);

    root->addLayout(header);

    m_playlistsSection = new QWidget(this);
    auto *playlistsLayout = new QVBoxLayout(m_playlistsSection);
    playlistsLayout->setContentsMargins(0, 4, 0, 0);
    playlistsLayout->setSpacing(4);
    auto *playlistsTitle = new QLabel(tr("Playlists"), m_playlistsSection);
    playlistsTitle->setObjectName(QStringLiteral("homeSectionTitle"));
    QFont sectionFont = playlistsTitle->font();
    sectionFont.setPixelSize(15);
    sectionFont.setBold(true);
    playlistsTitle->setFont(sectionFont);
    playlistsLayout->addWidget(playlistsTitle);

    auto *scroll = new QScrollArea(m_playlistsSection);
    scroll->setObjectName(QStringLiteral("homeCardScroll"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setFixedHeight(234);
    m_playlistsRow = new QWidget(scroll);
    m_playlistsLayout = new QHBoxLayout(m_playlistsRow);
    m_playlistsLayout->setContentsMargins(4, 0, 0, 0);
    m_playlistsLayout->setSpacing(4);
    scroll->setWidget(m_playlistsRow);
    playlistsLayout->addWidget(scroll);
    m_playlistsSection->hide();
    root->addWidget(m_playlistsSection);

    m_empty = new QLabel(this);
    m_empty->setObjectName(QStringLiteral("streamEmpty"));
    m_empty->setAlignment(Qt::AlignCenter);
    m_empty->setWordWrap(true);
    m_empty->hide();
    root->addWidget(m_empty);

    m_list = new SmoothListWidget(this);
    m_list->setObjectName(QStringLiteral("streamCollectionList"));
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
    connect(m_list, &QListWidget::itemDoubleClicked, this,
            [this](QListWidgetItem *item) {
                if (!item) {
                    return;
                }
                const SearchResult result =
                    m_results.value(item->data(Qt::UserRole).toString());
                if (result.kind == SearchResult::Kind::Track) {
                    emit playRequested(result);
                }
            });
}

QString StreamCollectionView::keyFor(const SearchResult &result) const {
    return QString::number(static_cast<int>(result.kind)) + QLatin1Char(':') +
           result.id;
}

void StreamCollectionView::setHeader(const SearchResult &header) {
    m_header = header;
    updateShowAllVisibility();
    m_playAll->setText(header.kind == SearchResult::Kind::Artist
                           ? tr("Play artist")
                           : tr("Play all"));
    m_title->setText(header.title);
    QString subtitle = header.uploader;
    if (header.kind == SearchResult::Kind::Playlist &&
        header.itemCount > 0) {
        subtitle = header.uploader.isEmpty()
                       ? tr("%n track(s)", "", header.itemCount)
                       : QStringLiteral("%1 · %2 tracks")
                             .arg(header.uploader)
                             .arg(header.itemCount);
    }
    m_subtitle->setText(subtitle);
    const bool artist = header.kind == SearchResult::Kind::Artist;
    const bool square = artist || header.squareThumbnail;
    const QSize coverSize = square ? QSize(64, 64) : QSize(96, 54);
    m_cover->setFixedSize(coverSize);
    if (m_images && !header.thumbnail.isEmpty()) {
        QPointer<QLabel> cover(m_cover);
        if (artist) {
            m_images->requestRaw(header.thumbnail, coverSize.width(),
                                 [cover, coverSize](
                                     const QPixmap &pixmap) {
                                     if (!cover) {
                                         return;
                                     }
                                     cover->setPixmap(roundedPixmap(
                                         pixmap, coverSize, 32.0));
                                 });
        } else if (square) {
            m_images->request(header.thumbnail, coverSize.width(),
                              [cover, coverSize](const QPixmap &pixmap) {
                                  if (!cover) {
                                      return;
                                  }
                                  cover->setPixmap(roundedPixmap(
                                      pixmap, coverSize, 10.0));
                              });
        } else {
            m_images->requestFit(header.thumbnail, coverSize,
                                 [cover, coverSize](const QPixmap &pixmap) {
                                     if (!cover) {
                                         return;
                                     }
                                     cover->setPixmap(roundedPixmap(
                                         pixmap, coverSize, 8.0));
                                 });
        }
    }
}

void StreamCollectionView::clearTracks() {
    m_showAllItem = nullptr;
    m_showAll = nullptr;
    m_list->clear();
    m_rows.clear();
    m_results.clear();
}

void StreamCollectionView::clearPlaylists() {
    while (QLayoutItem *item = m_playlistsLayout->takeAt(0)) {
        if (QWidget *widget = item->widget()) {
            widget->deleteLater();
        }
        delete item;
    }
}

void StreamCollectionView::setTracks(const QVector<SearchResult> &tracks) {
    clearTracks();
    m_trackCount = tracks.size();
    m_empty->hide();
    for (const SearchResult &result : tracks) {
        auto *item = new QListWidgetItem(m_list);
        item->setSizeHint(QSize(0, 64));
        const QString key = keyFor(result);
        item->setData(Qt::UserRole, key);
        m_results.insert(key, result);
        auto *row = new StreamItemRow(result, m_images, m_list);
        m_list->setItemWidget(item, row);
        m_rows.insert(key, row);
        connect(row, &StreamItemRow::activated, this, [this, item] {
            m_list->setCurrentItem(item);
        });
        connect(row, &StreamItemRow::playRequested, this,
                &StreamCollectionView::playRequested);
        connect(row, &StreamItemRow::downloadRequested, this,
                &StreamCollectionView::downloadRequested);
        connect(row, &StreamItemRow::queueRequested, this,
                &StreamCollectionView::queueRequested);
    }
    updatePlayAllVisibility();
    updateShowAllVisibility();
    if (tracks.isEmpty() && m_playlistsSection->isHidden()) {
        m_empty->setText(tr("Nothing to show yet."));
        m_empty->show();
    }
}

void StreamCollectionView::setPlaylists(
    const QVector<SearchResult> &playlists) {
    clearPlaylists();
    m_playlistsSection->setVisible(!playlists.isEmpty());
    updatePlayAllVisibility();
    if (!playlists.isEmpty()) {
        m_empty->hide();
    } else if (m_trackCount == 0) {
        m_empty->setText(tr("Nothing to show yet."));
        m_empty->show();
    }
    for (const SearchResult &result : playlists) {
        auto *card = new StreamCard(result, m_images, m_playlistsRow);
        connect(card, &StreamCard::activated, this,
                &StreamCollectionView::playlistRequested);
        connect(card, &StreamCard::playRequested, this,
                &StreamCollectionView::playRequested);
        card->setCompact(true);
        m_playlistsLayout->addWidget(card);
    }
    m_playlistsLayout->addStretch(1);
}

void StreamCollectionView::demoClickFirstPlaylistPlay() {
    const auto cards = m_playlistsRow->findChildren<StreamCard *>();
    for (StreamCard *card : cards) {
        if (auto *button = card->findChild<QToolButton *>(
                QStringLiteral("streamCardPlay"))) {
            button->show();
            button->raise();
            const QPoint global =
                button->mapToGlobal(button->rect().center());
            QWidget *target = QApplication::widgetAt(global);
            if (target == button) {
                const QPoint local = button->mapFromGlobal(global);
                QMouseEvent press(QEvent::MouseButtonPress, local, global,
                                  Qt::LeftButton, Qt::LeftButton,
                                  Qt::NoModifier);
                QMouseEvent release(QEvent::MouseButtonRelease, local, global,
                                    Qt::LeftButton, Qt::NoButton,
                                    Qt::NoModifier);
                QApplication::sendEvent(button, &press);
                QApplication::sendEvent(button, &release);
            }
            return;
        }
    }
}

void StreamCollectionView::setShowAllAvailable(bool available) {
    m_showAllAvailable = available;
    updateShowAllVisibility();
}

void StreamCollectionView::updateShowAllVisibility() {
    const bool visible = m_showAllAvailable &&
                         m_header.kind == SearchResult::Kind::Artist;
    if (!visible) {
        if (m_showAllItem) {
            QWidget *widget = m_list->itemWidget(m_showAllItem);
            m_list->removeItemWidget(m_showAllItem);
            const int row = m_list->row(m_showAllItem);
            if (row >= 0) {
                delete m_list->takeItem(row);
            }
            if (widget) {
                widget->setParent(nullptr);
                widget->deleteLater();
            }
            m_showAllItem = nullptr;
            m_showAll = nullptr;
        }
        return;
    }
    if (m_showAllItem) {
        return;
    }
    m_showAllItem = new QListWidgetItem(m_list);
    m_showAllItem->setSizeHint(QSize(0, 72));
    auto *host = new QWidget(m_list);
    auto *layout = new QHBoxLayout(host);
    layout->setContentsMargins(0, 12, 0, 12);
    layout->addStretch(1);
    m_showAll = new QPushButton(tr("Show all tracks"), host);
    m_showAll->setObjectName(QStringLiteral("streamShowAllPill"));
    m_showAll->setCursor(Qt::PointingHandCursor);
    m_showAll->setFocusPolicy(Qt::NoFocus);
    m_showAll->setToolTip(QString());
    m_showAll->setStyleSheet(
        QStringLiteral("QPushButton#streamShowAllPill {"
                       " background: rgba(255, 255, 255, 18);"
                       " border: 1px solid rgba(255, 255, 255, 30);"
                       " border-radius: 18px; padding: 8px 20px;"
                       " color: #e8e8f0; }"
                       "QPushButton#streamShowAllPill:hover {"
                       " background: rgba(255, 255, 255, 30); }"));
    connect(m_showAll, &QPushButton::clicked, this, [this] {
        const SearchResult header = m_header;
        if (m_showAllItem) {
            m_showAllItem->setHidden(true);
        }
        if (m_showAll) {
            m_showAll->setEnabled(false);
        }
        emit showAllRequested(header);
    });
    layout->addWidget(m_showAll);
    layout->addStretch(1);
    m_list->setItemWidget(m_showAllItem, host);
}

void StreamCollectionView::updatePlayAllVisibility() {
    const bool playableHeader =
        m_header.kind == SearchResult::Kind::Artist ||
        m_header.kind == SearchResult::Kind::Playlist;
    const bool hasTracks = m_list && m_list->count() > 0;
    const bool artistAlbums =
        m_header.kind == SearchResult::Kind::Artist &&
        m_playlistsSection && !m_playlistsSection->isHidden();
    m_playAll->setVisible(playableHeader && (hasTracks || artistAlbums));
}

void StreamCollectionView::setLoading(bool loading) {
    Q_UNUSED(loading);
}

void StreamCollectionView::setBusyFor(const QString &id, bool busy) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setBusy(busy);
            }
        }
    }
}

void StreamCollectionView::setDownloadProgress(const QString &id, int progress) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setDownloadBusy(progress >= 0, progress);
            }
        }
    }
}

void StreamCollectionView::setPlaying(const QString &id, bool playing) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setPlaying(playing);
            }
        }
    }
}
