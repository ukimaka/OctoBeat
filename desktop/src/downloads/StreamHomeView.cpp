#include "StreamHomeView.h"

#include "RemoteImageCache.h"
#include "StreamCard.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QLayoutItem>
#include <QScrollArea>
#include <QScrollBar>
#include <QTimer>
#include <QVBoxLayout>

StreamHomeView::StreamHomeView(RemoteImageCache *images, QWidget *parent)
    : QWidget(parent), m_images(images) {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    m_scroll = new QScrollArea(this);
    m_scroll->setObjectName(QStringLiteral("streamHomeScroll"));
    m_scroll->setWidgetResizable(true);
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);

    m_content = new QWidget(m_scroll);
    m_content->setObjectName(QStringLiteral("streamHomeContent"));
    m_layout = new QVBoxLayout(m_content);
    m_layout->setContentsMargins(20, 8, 20, 24);
    m_layout->setSpacing(16);
    m_scroll->setWidget(m_content);
    root->addWidget(m_scroll);
}

void StreamHomeView::clear() {
    while (QLayoutItem *item = m_layout->takeAt(0)) {
        if (QWidget *widget = item->widget()) {
            // Hide immediately so stale cards never affect the scroll range,
            // but delete later: this can be called from a card's own context
            // menu handler.
            widget->hide();
            widget->deleteLater();
        }
        delete item;
    }
}

void StreamHomeView::addSection(const QString &title,
                                const QVector<SearchResult> &items) {
    if (items.isEmpty()) {
        return;
    }
    auto *section = new QWidget(m_content);
    auto *sectionLayout = new QVBoxLayout(section);
    sectionLayout->setContentsMargins(0, 0, 0, 0);
    sectionLayout->setSpacing(6);

    auto *caption = new QLabel(title, section);
    caption->setObjectName(QStringLiteral("homeSectionTitle"));
    QFont font = caption->font();
    font.setPixelSize(16);
    font.setBold(true);
    caption->setFont(font);
    sectionLayout->addWidget(caption);

    auto *scroll = new QScrollArea(section);
    scroll->setObjectName(QStringLiteral("homeCardScroll"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_rowScrollers.push_back(scroll);
    scroll->setFixedHeight(234);

    auto *row = new QWidget(scroll);
    auto *rowLayout = new QHBoxLayout(row);
    rowLayout->setContentsMargins(0, 0, 0, 0);
    rowLayout->setSpacing(8);
    for (const SearchResult &item : items) {
        auto *card = new StreamCard(item, m_images, row);
        m_cards.push_back(card);
        connect(card, &StreamCard::activated, this,
                &StreamHomeView::itemActivated);
        connect(card, &StreamCard::playRequested, this,
                &StreamHomeView::playRequested);
        connect(card, &StreamCard::downloadRequested, this,
                &StreamHomeView::downloadRequested);
        connect(card, &StreamCard::queueRequested, this,
                &StreamHomeView::queueRequested);
        connect(card, &StreamCard::removeRequested, this,
                &StreamHomeView::removeRequested);
        rowLayout->addWidget(card);
    }
    rowLayout->addStretch(1);
    scroll->setWidget(row);
    sectionLayout->addWidget(scroll);
    m_layout->addWidget(section);
}

void StreamHomeView::setPlaying(const QString &id, bool playing) {
    for (const QPointer<StreamCard> &card : m_cards) {
        if (card && card->result().kind == SearchResult::Kind::Track &&
            card->result().id == id) {
            card->setPlaying(playing);
        }
    }
}

void StreamHomeView::setData(const QVector<SearchResult> &recentTracks,
                             const QVector<SearchResult> &artists,
                             const QVector<SearchResult> &playlists) {
    m_content->setUpdatesEnabled(false);
    m_scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_rowScrollers.clear();
    m_cards.clear();
    clear();

    addSection(tr("Recently played"), recentTracks);
    addSection(tr("Artists"), artists);
    addSection(tr("Playlists"), playlists);

    if (recentTracks.isEmpty() && artists.isEmpty() && playlists.isEmpty()) {
        auto *empty = new QLabel(
            tr("Search YouTube above, play a few tracks and your home page "
               "will fill with recent artists and playlists."),
            m_content);
        empty->setObjectName(QStringLiteral("homeEmpty"));
        empty->setWordWrap(true);
        empty->setAlignment(Qt::AlignCenter);
        empty->setMinimumHeight(160);
        m_layout->addWidget(empty);
    }
    m_layout->addStretch(1);
    m_content->setUpdatesEnabled(true);
    m_content->updateGeometry();
    QTimer::singleShot(50, this, [this] {
        m_scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
        for (const QPointer<QScrollArea> &scroll : m_rowScrollers) {
            if (scroll) {
                scroll->setHorizontalScrollBarPolicy(
                    Qt::ScrollBarAsNeeded);
            }
        }
    });
}
