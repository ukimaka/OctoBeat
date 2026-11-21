#include "StreamQueuePanel.h"

#include "app/ElidedLabel.h"
#include "app/IconUtils.h"
#include "app/Theme.h"

#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPushButton>
#include <QScreen>
#include <QScrollArea>
#include <QToolButton>
#include <QVBoxLayout>

#include <functional>

namespace {

constexpr int PanelWidth = 360;
constexpr int RowHeight = 52;

QString formatDuration(qint64 seconds) {
    if (seconds <= 0) {
        return {};
    }
    const qint64 hours = seconds / 3600;
    const qint64 minutes = (seconds % 3600) / 60;
    const qint64 rest = seconds % 60;
    if (hours > 0) {
        return QStringLiteral("%1:%2:%3")
            .arg(hours)
            .arg(minutes, 2, 10, QLatin1Char('0'))
            .arg(rest, 2, 10, QLatin1Char('0'));
    }
    return QStringLiteral("%1:%2")
        .arg(minutes)
        .arg(rest, 2, 10, QLatin1Char('0'));
}

class QueueRow : public QFrame {
public:
    QueueRow(const SearchResult &result,
             QWidget *parent,
             std::function<void()> play,
             std::function<void()> remove)
        : QFrame(parent), m_play(std::move(play)) {
        setObjectName(QStringLiteral("queueRow"));
        setAttribute(Qt::WA_StyledBackground, true);
        setCursor(Qt::PointingHandCursor);
        setFixedHeight(RowHeight);

        auto *layout = new QHBoxLayout(this);
        layout->setContentsMargins(10, 5, 6, 5);
        layout->setSpacing(8);

        auto *textColumn = new QVBoxLayout();
        textColumn->setContentsMargins(0, 0, 0, 0);
        textColumn->setSpacing(1);

        auto *title = new ElidedLabel(result.title, this);
        QFont titleFont = title->font();
        titleFont.setPixelSize(13);
        titleFont.setWeight(QFont::DemiBold);
        title->setFont(titleFont);
        textColumn->addWidget(title);

        auto *subtitle = new ElidedLabel(result.uploader, this);
        QFont subtitleFont = subtitle->font();
        subtitleFont.setPixelSize(11);
        subtitle->setFont(subtitleFont);
        subtitle->setStyleSheet(
            QStringLiteral("color: rgba(220, 220, 232, 150);"));
        textColumn->addWidget(subtitle);
        layout->addLayout(textColumn, 1);

        const QString duration = formatDuration(result.duration);
        if (!duration.isEmpty()) {
            auto *label = new QLabel(duration, this);
            QFont durationFont = label->font();
            durationFont.setPixelSize(11);
            label->setFont(durationFont);
            label->setStyleSheet(
                QStringLiteral("color: rgba(220, 220, 232, 150);"));
            layout->addWidget(label);
        }

        auto *removeButton = new QToolButton(this);
        removeButton->setObjectName(QStringLiteral("queueRowRemove"));
        removeButton->setFixedSize(24, 24);
        removeButton->setIconSize(QSize(12, 12));
        removeButton->setCursor(Qt::PointingHandCursor);
        removeButton->setAutoRaise(true);
        removeButton->setIcon(
            IconUtils::tinted(QStringLiteral("cancel.svg"),
                              QColor(220, 220, 232), 12));
        removeButton->setToolTip(tr("Remove from queue"));
        connect(removeButton, &QToolButton::clicked, this, std::move(remove));
        layout->addWidget(removeButton);
    }

protected:
    void mousePressEvent(QMouseEvent *event) override {
        if (event->button() == Qt::LeftButton) {
            m_play();
            event->accept();
            return;
        }
        QFrame::mousePressEvent(event);
    }

private:
    std::function<void()> m_play;
};

} // namespace

StreamQueuePanel::StreamQueuePanel(QWidget *parent)
    : QFrame(parent, Qt::Popup | Qt::FramelessWindowHint) {
    setObjectName(QStringLiteral("streamQueuePanel"));
    setAttribute(Qt::WA_StyledBackground, true);
    setStyleSheet(QStringLiteral(
        "#streamQueuePanel { background: rgba(22, 22, 28, 245);"
        " border: 1px solid rgba(255, 255, 255, 30);"
        " border-radius: 12px; }"
        "QFrame#queueRow { background: transparent; border-radius: 8px; }"
        "QFrame#queueRow:hover { background: rgba(255, 255, 255, 16); }"
        "QToolButton#queueRowRemove { background: transparent;"
        " border: none; border-radius: 12px; }"
        "QToolButton#queueRowRemove:hover {"
        " background: rgba(255, 255, 255, 24); }"
        "QPushButton#queueClear { background: transparent; border: none;"
        " color: palette(link); padding: 2px 4px; }"
        "QPushButton#queueClear:hover { color: palette(text); }"));

    auto *layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(4);

    auto *header = new QHBoxLayout();
    header->setContentsMargins(6, 0, 4, 0);
    m_title = new QLabel(tr("Queue"), this);
    QFont titleFont = m_title->font();
    titleFont.setPixelSize(15);
    titleFont.setWeight(QFont::DemiBold);
    m_title->setFont(titleFont);
    header->addWidget(m_title);
    header->addStretch(1);

    auto *clear = new QPushButton(tr("Clear"), this);
    clear->setObjectName(QStringLiteral("queueClear"));
    clear->setCursor(Qt::PointingHandCursor);
    m_clear = clear;
    header->addWidget(clear);
    layout->addLayout(header);

    m_scroll = new QScrollArea(this);
    m_scroll->setObjectName(QStringLiteral("queueScroll"));
    m_scroll->setWidgetResizable(true);
    m_scroll->setFrameShape(QFrame::NoFrame);
    m_scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_scroll->setStyleSheet(
        QStringLiteral("QScrollArea#queueScroll { background: transparent; }"
                       "QScrollBar:vertical { background: transparent;"
                       " width: 8px; }"));
    m_rows = new QWidget(m_scroll);
    m_rows->setStyleSheet(QStringLiteral("background: transparent;"));
    m_rowsLayout = new QVBoxLayout(m_rows);
    m_rowsLayout->setContentsMargins(0, 0, 0, 0);
    m_rowsLayout->setSpacing(2);
    m_scroll->setWidget(m_rows);
    layout->addWidget(m_scroll, 1);

    m_empty = new QLabel(tr("Queue is empty."), this);
    m_empty->setAlignment(Qt::AlignCenter);
    m_empty->setStyleSheet(
        QStringLiteral("color: rgba(220, 220, 232, 140); padding: 28px 0;"));
    layout->addWidget(m_empty, 1);

    connect(clear, &QPushButton::clicked, this,
            &StreamQueuePanel::clearRequested);

    resize(PanelWidth, 160);
}

void StreamQueuePanel::setQueue(const QVector<SearchResult> &queue) {
    m_queue = queue;
    m_title->setText(queue.isEmpty()
                         ? tr("Queue")
                         : tr("Queue (%1)").arg(queue.size()));
    rebuild();
}

void StreamQueuePanel::rebuild() {
    while (QLayoutItem *item = m_rowsLayout->takeAt(0)) {
        if (QWidget *widget = item->widget()) {
            widget->deleteLater();
        }
        delete item;
    }

    const bool empty = m_queue.isEmpty();
    m_clear->setVisible(!empty);
    m_scroll->setVisible(!empty);
    m_empty->setVisible(empty);

    for (const SearchResult &result : m_queue) {
        auto *row = new QueueRow(
            result, m_rows,
            [this, result] {
                hide();
                emit playRequested(result);
            },
            [this, result] { emit removeRequested(result); });
        m_rowsLayout->addWidget(row);
    }
    m_rowsLayout->addStretch(1);

    const int rows = qMin(static_cast<int>(m_queue.size()), 6);
    resize(PanelWidth, empty ? 140 : 56 + rows * (RowHeight + 2));
}

void StreamQueuePanel::openAt(QWidget *anchor) {
    if (!anchor) {
        return;
    }
    const QPoint anchorTop = anchor->mapToGlobal(QPoint(0, 0));
    QPoint position(anchorTop.x() + anchor->width() - width(),
                    anchorTop.y() + anchor->height() + 6);
    if (QScreen *screen = anchor->screen()) {
        const QRect available = screen->availableGeometry();
        position.setX(qBound(available.left() + 8, position.x(),
                             available.right() - width() - 8));
        if (position.y() + height() > available.bottom() - 8) {
            position.setY(anchorTop.y() - height() - 6);
        }
    }
    move(position);
    show();
    raise();
}
