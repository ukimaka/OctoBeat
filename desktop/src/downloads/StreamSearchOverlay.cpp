#include "StreamSearchOverlay.h"

#include "RemoteImageCache.h"
#include "StreamItemRow.h"
#include "app/IconUtils.h"

#include <QGraphicsDropShadowEffect>
#include <QListWidget>
#include <QListWidgetItem>
#include <QPropertyAnimation>
#include <QVBoxLayout>

namespace {
constexpr int SuggestionHeight = 64;
constexpr int HistoryHeight = 44;
constexpr int PanelPadding = 6;
} // namespace

StreamSearchOverlay::StreamSearchOverlay(RemoteImageCache *images,
                                         QWidget *parent)
    : QFrame(parent), m_images(images) {
    setObjectName(QStringLiteral("streamSearchOverlay"));
    setAttribute(Qt::WA_StyledBackground, true);
    setStyleSheet(QStringLiteral(
        "#streamSearchOverlay { background: rgba(22, 22, 28, 238);"
        " border: 1px solid rgba(255, 255, 255, 30);"
        " border-radius: 12px; }"
        "QListWidget#searchOverlayList { background: transparent;"
        " border: none; outline: none; }"
        "QListWidget#searchOverlayList::item:selected {"
        " background: transparent; color: palette(text); }"));
    hide();

    auto *shadow = new QGraphicsDropShadowEffect(this);
    shadow->setBlurRadius(28);
    shadow->setOffset(0, 6);
    shadow->setColor(QColor(0, 0, 0, 120));
    setGraphicsEffect(shadow);

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(PanelPadding, PanelPadding, PanelPadding,
                               PanelPadding);
    layout->setSpacing(0);

    m_list = new QListWidget(this);
    m_list->setObjectName(QStringLiteral("searchOverlayList"));
    m_list->setFrameShape(QFrame::NoFrame);
    m_list->setFocusPolicy(Qt::NoFocus);
    m_list->setSelectionMode(QAbstractItemView::SingleSelection);
    m_list->setSpacing(0);
    m_list->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_list->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_list->setMouseTracking(true);
    layout->addWidget(m_list);

    m_animation = new QPropertyAnimation(this, "geometry", this);
    m_animation->setDuration(170);
    m_animation->setEasingCurve(QEasingCurve::OutCubic);
    connect(m_animation, &QPropertyAnimation::finished, this, [this] {
        if (height() <= 1) {
            hide();
        }
    });

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
                if (!item) {
                    return;
                }
                if (m_historyMode) {
                    emit historyRequested(item->text());
                    return;
                }
                m_list->setCurrentItem(item);
            });
}

QString StreamSearchOverlay::keyFor(const SearchResult &result) const {
    return QString::number(static_cast<int>(result.kind)) + QLatin1Char(':') +
           result.id;
}

void StreamSearchOverlay::clear() {
    m_list->clear();
    m_rows.clear();
    m_results.clear();
    m_targetHeight = 0;
    hide();
}

void StreamSearchOverlay::rebuildRows(
    const QVector<SearchResult> &results) {
    m_list->clear();
    m_rows.clear();
    m_results.clear();
    m_historyMode = false;
    if (results.isEmpty()) {
        auto *item = new QListWidgetItem(tr("Nothing found"), m_list);
        item->setSizeHint(QSize(0, HistoryHeight));
        m_targetHeight = HistoryHeight + PanelPadding * 2;
        return;
    }
    for (const SearchResult &result : results) {
        auto *item = new QListWidgetItem(m_list);
        item->setSizeHint(QSize(0, SuggestionHeight));
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
                &StreamSearchOverlay::playRequested);
        connect(row, &StreamItemRow::downloadRequested, this,
                &StreamSearchOverlay::downloadRequested);
        connect(row, &StreamItemRow::queueRequested, this,
                &StreamSearchOverlay::queueRequested);
        connect(row, &StreamItemRow::openRequested, this,
                &StreamSearchOverlay::openRequested);
    }
    m_list->setCurrentRow(0);
    m_targetHeight = results.size() * SuggestionHeight + PanelPadding * 2;
}

void StreamSearchOverlay::setSuggestions(
    const QVector<SearchResult> &results) {
    rebuildRows(results);
    updateHeight(panelVisible());
}

void StreamSearchOverlay::setHistory(const QStringList &history) {
    m_list->clear();
    m_rows.clear();
    m_results.clear();
    m_historyMode = true;
    if (history.isEmpty()) {
        auto *item = new QListWidgetItem(tr("No recent searches"), m_list);
        item->setSizeHint(QSize(0, HistoryHeight));
        m_targetHeight = HistoryHeight + PanelPadding * 2;
        updateHeight(panelVisible());
        return;
    }
    const int count = qMin(8, history.size());
    for (int i = 0; i < count; ++i) {
        auto *item = new QListWidgetItem(
            IconUtils::tinted(QStringLiteral("time.svg"),
                              QColor(170, 170, 185), 16),
            history[i], m_list);
        item->setSizeHint(QSize(0, HistoryHeight));
    }
    m_list->setCurrentRow(0);
    m_targetHeight = count * HistoryHeight + PanelPadding * 2;
    updateHeight(panelVisible());
}

void StreamSearchOverlay::updateHeight(bool animate) {
    if (m_targetHeight <= 0) {
        return;
    }
    const QRect current = geometry();
    QRect target(current.x(), current.y(), current.width(), m_targetHeight);
    if (!animate) {
        setGeometry(target);
        return;
    }
    m_animation->stop();
    m_animation->setStartValue(current);
    m_animation->setEndValue(target);
    m_animation->start();
}

void StreamSearchOverlay::showPanel() {
    if (m_targetHeight <= 0) {
        return;
    }
    show();
    raise();
    const QRect current = geometry();
    QRect start(current.x(), current.y(), current.width(), 0);
    QRect target(current.x(), current.y(), current.width(), m_targetHeight);
    m_animation->stop();
    m_animation->setStartValue(start);
    m_animation->setEndValue(target);
    m_animation->start();
}

void StreamSearchOverlay::hidePanel() {
    if (isHidden()) {
        return;
    }
    m_animation->stop();
    const QRect current = geometry();
    QRect target(current.x(), current.y(), current.width(), 0);
    m_animation->setStartValue(current);
    m_animation->setEndValue(target);
    m_animation->start();
}

void StreamSearchOverlay::moveSelection(int delta) {
    if (m_list->count() == 0) {
        return;
    }
    int row = m_list->currentRow();
    if (row < 0) {
        row = 0;
    } else {
        row = qBound(0, row + delta, m_list->count() - 1);
    }
    m_list->setCurrentRow(row);
    if (QListWidgetItem *item = m_list->item(row)) {
        m_list->scrollToItem(item);
    }
}

bool StreamSearchOverlay::activateCurrent() {
    QListWidgetItem *item = m_list->currentItem();
    if (!item) {
        return false;
    }
    if (m_historyMode) {
        emit historyRequested(item->text());
        return true;
    }
    const SearchResult result =
        m_results.value(item->data(Qt::UserRole).toString());
    if (result.id.isEmpty()) {
        return false;
    }
    if (result.kind == SearchResult::Kind::Track) {
        emit playRequested(result);
    } else {
        emit openRequested(result);
    }
    return true;
}

void StreamSearchOverlay::setBusyFor(const QString &id, bool busy) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setBusy(busy);
            }
        }
    }
}

void StreamSearchOverlay::setDownloadProgress(const QString &id, int progress) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setDownloadBusy(progress >= 0, progress);
            }
        }
    }
}

void StreamSearchOverlay::setPlaying(const QString &id, bool playing) {
    for (auto it = m_results.begin(); it != m_results.end(); ++it) {
        if (it.value().id == id) {
            if (auto *row = m_rows.value(it.key())) {
                row->setPlaying(playing);
            }
        }
    }
}
