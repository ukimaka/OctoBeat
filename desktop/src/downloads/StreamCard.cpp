#include "StreamCard.h"

#include "RemoteImageCache.h"
#include "app/ElidedLabel.h"
#include "app/IconUtils.h"
#include "app/Theme.h"

#include <QContextMenuEvent>
#include <QKeyEvent>
#include <QResizeEvent>
#include <QTimer>
#include <QEnterEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QAction>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPointer>
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

QString subtitleFor(const SearchResult &result) {
    if (result.kind == SearchResult::Kind::Playlist && result.itemCount > 0) {
        return QStringLiteral("%1 · %2 tracks")
            .arg(result.uploader)
            .arg(result.itemCount);
    }
    return result.uploader;
}

} // namespace

StreamCard::StreamCard(const SearchResult &result,
                       RemoteImageCache *images,
                       QWidget *parent)
    : QWidget(parent), m_result(result) {
    setObjectName(QStringLiteral("streamCard"));
    setAttribute(Qt::WA_Hover, true);
    const bool artist = result.kind == SearchResult::Kind::Artist;
    const bool square = artist || result.squareThumbnail;
    const QSize coverSize = square ? QSize(140, 140) : QSize(176, 99);
    setFixedSize(square ? QSize(168, 210) : QSize(192, 185));
    setCursor(Qt::PointingHandCursor);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    setFocusPolicy(Qt::StrongFocus);

    m_layout = new QVBoxLayout(this);
    m_layout->setContentsMargins(8, 8, 8, 8);
    m_layout->setSpacing(5);

    m_cover = new QLabel(this);
    m_cover->setFixedSize(coverSize);
    m_cover->setAlignment(Qt::AlignCenter);
    m_cover->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    if (images && !result.thumbnail.isEmpty()) {
        QPointer<QLabel> cover(m_cover);
        if (artist) {
            images->requestRaw(result.thumbnail, coverSize.width(),
                               [cover, coverSize](const QPixmap &pixmap) {
                                   if (cover) {
                                       cover->setPixmap(roundedPixmap(
                                           pixmap, coverSize, 70.0));
                                   }
                               });
        } else if (square) {
            images->request(result.thumbnail, coverSize.width(),
                            [cover, coverSize](const QPixmap &pixmap) {
                                if (cover) {
                                    cover->setPixmap(roundedPixmap(
                                        pixmap, coverSize, 10.0));
                                }
                            });
        } else {
            images->requestFit(result.thumbnail, coverSize,
                               [cover, coverSize](const QPixmap &pixmap) {
                                   if (cover) {
                                       cover->setPixmap(roundedPixmap(
                                           pixmap, coverSize, 10.0));
                                   }
                               });
        }
    }
    if (m_cover->pixmap().isNull()) {
        m_cover->setStyleSheet(
            QStringLiteral("background: rgba(255,255,255,12);"
                           "border-radius: 12px;"));
    }

    m_play = new QToolButton(this);
    m_play->setObjectName(QStringLiteral("streamCardPlay"));
    m_play->setFixedSize(42, 42);
    m_play->setIconSize(QSize(20, 20));
    m_play->setIcon(IconUtils::tinted(QStringLiteral("play.svg"),
                                      QColor(Qt::white), 20));
    m_play->setCursor(Qt::PointingHandCursor);
    const QColor accent = Theme::accent();
    m_play->setStyleSheet(
        QStringLiteral("QToolButton { background: %1; border: none;"
                       " border-radius: 21px; }"
                       "QToolButton:hover { background: %2; }")
            .arg(accent.name(), accent.lighter(115).name()));
    m_play->hide();
    m_play->raise();
    m_play->installEventFilter(this);
    connect(m_play, &QToolButton::clicked, this,
            [this] { emit playRequested(m_result); });
    QTimer::singleShot(0, this, &StreamCard::updatePlayPosition);

    m_layout->addWidget(m_cover);

    m_title = new ElidedLabel(result.title, this);
    m_title->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    QFont titleFont = m_title->font();
    titleFont.setPixelSize(14);
    titleFont.setBold(true);
    m_title->setFont(titleFont);
    m_title->setTextInteractionFlags(Qt::NoTextInteraction);
    m_layout->addWidget(m_title);

    m_subtitle = new ElidedLabel(subtitleFor(result), this);
    m_subtitle->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    QPalette palette = m_subtitle->palette();
    palette.setColor(
        QPalette::WindowText,
        Theme::isDark(Theme::current()) ? QColor(0x8a, 0x8a, 0x8a)
                                        : QColor(0x6a, 0x6a, 0x72));
    m_subtitle->setPalette(palette);
    QFont subtitleFont = m_subtitle->font();
    subtitleFont.setPixelSize(12);
    m_subtitle->setFont(subtitleFont);
    m_subtitle->setTextInteractionFlags(Qt::NoTextInteraction);
    m_layout->addWidget(m_subtitle);
}

void StreamCard::setCompact(bool compact) {
    if (!m_layout) {
        return;
    }
    m_layout->setContentsMargins(compact ? 0 : 8, compact ? 4 : 8,
                                 compact ? 0 : 8, compact ? 4 : 8);
    m_layout->setSpacing(compact ? 3 : 5);
    if (!compact) {
        return;
    }
    const bool artist = m_result.kind == SearchResult::Kind::Artist;
    const bool square = artist || m_result.squareThumbnail;
    setFixedSize(square ? QSize(140, 194) : QSize(176, 154));
    updatePlayPosition();
}

void StreamCard::setPlaying(bool playing) {
    m_playing = playing;
    if (m_result.kind != SearchResult::Kind::Track) {
        return;
    }
    m_play->setIcon(
        IconUtils::tinted(playing ? QStringLiteral("pause.svg")
                                  : QStringLiteral("play.svg"),
                          QColor(Qt::white),
                          m_play->iconSize().width()));
    if (m_hovered || playing) {
        m_play->show();
    }
}

void StreamCard::paintEvent(QPaintEvent *) {
    if (!m_hovered) {
        return;
    }
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);
    QColor color = palette().color(QPalette::Highlight);
    color.setAlpha(22);
    painter.setPen(Qt::NoPen);
    painter.setBrush(color);
    painter.drawRoundedRect(rect().adjusted(1, 1, -1, -1), 12, 12);
}

void StreamCard::mousePressEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton) {
        if (m_result.kind != SearchResult::Kind::Track) {
            // Artists and playlists navigate on a single click; only tracks
            // reserve single click for focus and require Play/Enter/double.
            emit activated(m_result);
            event->accept();
            return;
        }
        setFocus(Qt::MouseFocusReason);
    }
    QWidget::mousePressEvent(event);
}

void StreamCard::mouseDoubleClickEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton &&
        m_result.kind == SearchResult::Kind::Track) {
        emit activated(m_result);
        event->accept();
        return;
    }
    QWidget::mouseDoubleClickEvent(event);
}

void StreamCard::keyPressEvent(QKeyEvent *event) {
    if (event->key() == Qt::Key_Return ||
        event->key() == Qt::Key_Enter) {
        emit activated(m_result);
        event->accept();
        return;
    }
    QWidget::keyPressEvent(event);
}

void StreamCard::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    updatePlayPosition();
}

void StreamCard::updatePlayPosition() {
    if (!m_cover || !m_play) {
        return;
    }
    const QRect cover = m_cover->geometry();
    m_play->move(cover.x() + cover.width() - m_play->width() - 6,
                 cover.y() + cover.height() - m_play->height() - 6);
    m_play->raise();
}

void StreamCard::contextMenuEvent(QContextMenuEvent *event) {
    QMenu menu(this);
    QAction *download = nullptr;
    QAction *queue = nullptr;
    if (m_result.kind == SearchResult::Kind::Track) {
        download = menu.addAction(
            IconUtils::tinted(QStringLiteral("download.svg"),
                              QColor(220, 220, 232), 18),
            tr("Download"));
        queue = menu.addAction(
            IconUtils::tinted(QStringLiteral("queue.svg"),
                              QColor(220, 220, 232), 18),
            tr("Add to queue"));
        menu.addSeparator();
    }
    QAction *remove = menu.addAction(tr("Remove from home"));
    QAction *chosen = menu.exec(event->globalPos());
    if (download && chosen == download) {
        emit downloadRequested(m_result);
    } else if (queue && chosen == queue) {
        emit queueRequested(m_result);
    } else if (chosen == remove) {
        emit removeRequested(m_result);
    }
    event->accept();
}

void StreamCard::enterEvent(QEnterEvent *event) {
    m_hovered = true;
    m_play->show();
    update();
    QWidget::enterEvent(event);
}

void StreamCard::leaveEvent(QEvent *event) {
    m_hovered = false;
    if (!m_playing) {
        m_play->hide();
    }
    update();
    QWidget::leaveEvent(event);
}

bool StreamCard::eventFilter(QObject *watched, QEvent *event) {
    if (watched == m_play &&
        (event->type() == QEvent::Enter || event->type() == QEvent::Leave)) {
        const bool hovered = event->type() == QEvent::Enter;
        const int size = hovered ? 46 : 42;
        const int iconSize = hovered ? 22 : 20;
        const QColor accent = Theme::accent();
        m_play->setFixedSize(size, size);
        m_play->setIconSize(QSize(iconSize, iconSize));
        m_play->setStyleSheet(
            QStringLiteral("QToolButton { background: %1; border: none;"
                           " border-radius: %2px; }"
                           "QToolButton:hover { background: %3; }")
                .arg(accent.name())
                .arg(size / 2)
                .arg(accent.lighter(120).name()));
        m_play->setIcon(
            IconUtils::tinted(m_playing ? QStringLiteral("pause.svg")
                                        : QStringLiteral("play.svg"),
                              QColor(Qt::white), iconSize));
        updatePlayPosition();
    }
    return QWidget::eventFilter(watched, event);
}
