#include "StreamItemRow.h"

#include "RemoteImageCache.h"
#include "app/ElidedLabel.h"
#include "app/IconUtils.h"
#include "app/SpinnerWidget.h"
#include "app/Theme.h"

#include <QContextMenuEvent>
#include <QEnterEvent>
#include <QHBoxLayout>
#include <QLabel>
#include <QAction>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPointer>
#include <QStackedLayout>
#include <QToolButton>
#include <QVBoxLayout>

namespace {

QString formatDuration(qint64 seconds) {
    if (seconds <= 0) {
        return {};
    }
    const qint64 minutes = seconds / 60;
    const qint64 rest = seconds % 60;
    return QStringLiteral("%1:%2")
        .arg(minutes)
        .arg(rest, 2, 10, QLatin1Char('0'));
}

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
    return result.uploader;
}

} // namespace

StreamItemRow::StreamItemRow(const SearchResult &result,
                             RemoteImageCache *images,
                             QWidget *parent,
                             bool large,
                             int indent)
    : QWidget(parent),
      m_result(result),
      m_images(images),
      m_large(large) {
    setObjectName(QStringLiteral("streamItemRow"));
    setAttribute(Qt::WA_Hover, true);
    setFixedHeight(m_large ? 80 : 64);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);

    auto *layout = new QHBoxLayout(this);
    layout->setContentsMargins(0, 4, 8, 4);
    layout->setSpacing(8);
    if (indent > 0) {
        layout->addSpacing(indent);
    }

    m_playButton = new QToolButton(this);
    m_playButton->setObjectName(QStringLiteral("streamRowButton"));
    const int buttonSize = m_large ? 36 : 32;
    const int playSize = m_large ? 27 : 24;
    const int playIconSize = m_large ? 17 : 15;
    m_playButton->setFixedSize(playSize, playSize);
    m_playButton->setIconSize(QSize(playIconSize, playIconSize));
    m_playButton->setCursor(Qt::PointingHandCursor);
    m_playButton->setAutoRaise(true);
    m_playSpinner = new SpinnerWidget(this);
    m_playSpinner->setFixedSize(m_large ? 22 : 20, m_large ? 22 : 20);
    m_playSpinner->setColor(QColor(232, 232, 244));
    m_playSpinner->hide();
    m_playHost = new QWidget(this);
    m_playHost->setFixedSize(playSize, playSize);
    m_playHost->setStyleSheet(QStringLiteral("background: transparent;"));
    m_playStack = new QStackedLayout(m_playHost);
    m_playStack->setContentsMargins(0, 0, 0, 0);
    m_playStack->addWidget(m_playButton);
    m_playStack->addWidget(m_playSpinner);
    m_playStack->setCurrentWidget(m_playButton);
    layout->addWidget(m_playHost);

    const bool artist = result.kind == SearchResult::Kind::Artist;
    const QSize coverSize(m_large ? 56 : 48, m_large ? 56 : 48);
    m_cover = new QLabel(this);
    m_cover->setFixedSize(coverSize);
    m_cover->setAlignment(Qt::AlignCenter);
    m_cover->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    if (m_images && !result.thumbnail.isEmpty()) {
        QPointer<QLabel> cover(m_cover);
        if (artist) {
            const qreal artistRadius = m_large ? 28.0 : 24.0;
            m_images->requestRaw(result.thumbnail, coverSize.width(),
                                 [cover, coverSize, artistRadius](
                                     const QPixmap &pixmap) {
                                     if (cover) {
                                         cover->setPixmap(roundedPixmap(
                                             pixmap, coverSize,
                                             artistRadius));
                                     }
                                 });
        } else {
            m_images->request(result.thumbnail, coverSize.width(),
                              [cover, coverSize](const QPixmap &pixmap) {
                                  if (cover) {
                                      cover->setPixmap(roundedPixmap(
                                          pixmap, coverSize, 8.0));
                                  }
                              });
        }
    }
    if (m_cover->pixmap().isNull()) {
        m_cover->setStyleSheet(
            QStringLiteral("background: rgba(255,255,255,12);"
                           "border-radius: 8px;"));
    }
    layout->addWidget(m_cover);

    auto *textLayout = new QVBoxLayout();
    textLayout->setContentsMargins(0, 0, 0, 0);
    textLayout->setSpacing(1);
    m_title = new ElidedLabel(result.title, this);
    m_title->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    QFont titleFont = m_title->font();
    titleFont.setPixelSize(m_large ? 16 : 14);
    titleFont.setBold(true);
    m_title->setFont(titleFont);
    m_title->setTextInteractionFlags(Qt::NoTextInteraction);
    m_title->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    m_subtitle = new ElidedLabel(subtitleFor(result), this);
    m_subtitle->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    QPalette subtitlePalette = m_subtitle->palette();
    subtitlePalette.setColor(
        QPalette::WindowText,
        Theme::isDark(Theme::current()) ? QColor(0x8a, 0x8a, 0x8a)
                                        : QColor(0x6a, 0x6a, 0x72));
    m_subtitle->setPalette(subtitlePalette);
    QFont subtitleFont = m_subtitle->font();
    subtitleFont.setPixelSize(m_large ? 13 : 12);
    m_subtitle->setFont(subtitleFont);
    m_subtitle->setTextInteractionFlags(Qt::NoTextInteraction);
    m_subtitle->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    textLayout->addWidget(m_title);
    textLayout->addWidget(m_subtitle);
    layout->addLayout(textLayout, 1);

    m_duration = new QLabel(this);
    m_duration->setAttribute(Qt::WA_TransparentForMouseEvents, true);
    m_duration->setStyleSheet(QStringLiteral("color: #8a8a8a;"));
    QFont durationFont = m_duration->font();
    durationFont.setPixelSize(m_large ? 13 : 12);
    m_duration->setFont(durationFont);
    m_duration->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    if (result.kind == SearchResult::Kind::Track) {
        m_duration->setText(formatDuration(result.duration));
    } else if (result.kind == SearchResult::Kind::Playlist &&
               result.itemCount > 0) {
        m_duration->setText(QStringLiteral("%1 tracks").arg(result.itemCount));
    }
    m_downloadButton = new QToolButton(this);
    m_downloadButton->setObjectName(QStringLiteral("streamRowButton"));
    m_downloadButton->setFixedSize(buttonSize, buttonSize);
    m_downloadButton->setIconSize(QSize(m_large ? 22 : 20,
                                        m_large ? 22 : 20));
    m_downloadButton->setCursor(Qt::PointingHandCursor);
    m_downloadButton->setAutoRaise(true);
    m_downloadButton->setIcon(
        IconUtils::tinted(QStringLiteral("download.svg"),
                          QColor(220, 220, 232), m_large ? 24 : 22));
    m_downloadSpinner = new SpinnerWidget(this);
    m_downloadSpinner->setFixedSize(m_large ? 28 : 26,
                                    m_large ? 28 : 26);
    m_downloadSpinner->setColor(QColor(232, 232, 244));
    m_downloadSpinner->hide();
    auto *downloadHost = new QWidget(this);
    downloadHost->setFixedSize(buttonSize, buttonSize);
    downloadHost->setStyleSheet(QStringLiteral("background: transparent;"));
    m_downloadStack = new QStackedLayout(downloadHost);
    m_downloadStack->setContentsMargins(0, 0, 0, 0);
    m_downloadStack->addWidget(m_downloadButton);
    m_downloadStack->addWidget(m_downloadSpinner);
    m_downloadStack->setCurrentWidget(m_downloadButton);
    layout->addWidget(downloadHost);
    layout->addWidget(m_duration);

    setStyleSheet(QStringLiteral(
        "#streamRowButton { border: none; background: transparent;"
        " border-radius: 12px; }"
        "#streamRowButton:hover { background: rgba(255,255,255,24); }"));

    if (result.kind == SearchResult::Kind::Track) {
        m_playButton->setIcon(
            IconUtils::tinted(QStringLiteral("play-mini.svg"),
                              QColor(220, 220, 232),
                              m_playButton->iconSize().width()));
        connect(m_playButton, &QToolButton::clicked, this,
                [this] { emit playRequested(m_result); });
        connect(m_downloadButton, &QToolButton::clicked, this,
                [this] { emit downloadRequested(m_result); });
    } else if (result.kind == SearchResult::Kind::Playlist) {
        m_playButton->setText(QStringLiteral("›"));
        QFont arrowFont = m_playButton->font();
        arrowFont.setPixelSize(20);
        m_playButton->setFont(arrowFont);
        m_playButton->setStyleSheet(
            QStringLiteral("color: #b8b8c4; border: none;"
                           " background: transparent;"));
        connect(m_playButton, &QToolButton::clicked, this,
                [this] { emit openRequested(m_result); });
        m_duration->clear();
        m_downloadStack->parentWidget()->hide();
    } else {
        // Artist rows have no transport button; the avatar/nickname opens the
        // channel. Removing the slot also aligns the artist to the left.
        m_playHost->hide();
        m_duration->clear();
        m_downloadStack->parentWidget()->hide();
        setCursor(Qt::PointingHandCursor);
    }
}

void StreamItemRow::updatePlayIcon() {
    if (m_result.kind != SearchResult::Kind::Track || m_busy) {
        return;
    }
    const QString icon = m_playing ? QStringLiteral("pause.svg")
                                   : QStringLiteral("play-mini.svg");
    m_playButton->setIcon(
        IconUtils::tinted(icon, QColor(220, 220, 232),
                          m_playButton->iconSize().width()));
}

void StreamItemRow::setBusy(bool busy) {
    if (m_result.kind != SearchResult::Kind::Track) {
        return;
    }
    m_busy = busy;
    if (busy) {
        m_playSpinner->setProgress(-1);
        m_playStack->setCurrentWidget(m_playSpinner);
    } else {
        m_playSpinner->stop();
        m_playStack->setCurrentWidget(m_playButton);
        updatePlayIcon();
    }
}

void StreamItemRow::setPlaying(bool playing) {
    m_playing = playing;
    updatePlayIcon();
    update();
}

void StreamItemRow::setSelected(bool selected) {
    if (m_selected == selected) {
        return;
    }
    m_selected = selected;
    update();
}

void StreamItemRow::setDownloadBusy(bool busy, int progress) {
    if (m_result.kind != SearchResult::Kind::Track) {
        return;
    }
    if (busy) {
        m_downloadSpinner->setProgress(progress);
        m_downloadStack->setCurrentWidget(m_downloadSpinner);
    } else {
        m_downloadSpinner->stop();
        m_downloadStack->setCurrentWidget(m_downloadButton);
    }
}

void StreamItemRow::setDownloadProgress(int progress) {
    if (m_downloadSpinner->isVisible()) {
        m_downloadSpinner->setProgress(progress);
    }
}

void StreamItemRow::paintEvent(QPaintEvent *) {
    QColor color;
    int alpha = 0;
    if (m_playing) {
        color = Theme::accent();
        alpha = 36;
    } else if (m_selected) {
        color = Theme::accent();
        alpha = 26;
    } else if (m_hovered) {
        color = palette().color(QPalette::Highlight);
        alpha = 18;
    }
    if (alpha == 0) {
        return;
    }
    color.setAlpha(alpha);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setPen(Qt::NoPen);
    painter.setBrush(color);
    painter.drawRoundedRect(rect().adjusted(1, 1, -1, -1), 8, 8);
}

void StreamItemRow::mousePressEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton) {
        if (m_result.kind == SearchResult::Kind::Artist) {
            emit openRequested(m_result);
            event->accept();
            return;
        }
        emit activated();
    }
    QWidget::mousePressEvent(event);
}

void StreamItemRow::contextMenuEvent(QContextMenuEvent *event) {
    if (m_result.kind != SearchResult::Kind::Track) {
        QWidget::contextMenuEvent(event);
        return;
    }
    QMenu menu(this);
    QAction *download = menu.addAction(
        IconUtils::tinted(QStringLiteral("download.svg"),
                          QColor(220, 220, 232), 18),
        tr("Download"));
    QAction *queue = menu.addAction(
        IconUtils::tinted(QStringLiteral("queue.svg"),
                          QColor(220, 220, 232), 18),
        tr("Add to queue"));
    QAction *chosen = menu.exec(event->globalPos());
    if (chosen == download) {
        emit downloadRequested(m_result);
    } else if (chosen == queue) {
        emit queueRequested(m_result);
    }
    event->accept();
}

void StreamItemRow::enterEvent(QEnterEvent *event) {
    m_hovered = true;
    update();
    QWidget::enterEvent(event);
}

void StreamItemRow::leaveEvent(QEvent *event) {
    m_hovered = false;
    update();
    QWidget::leaveEvent(event);
}
