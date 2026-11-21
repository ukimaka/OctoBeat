#include "MiniPlayer.h"

#include "ClickSlider.h"
#include "CoverCache.h"
#include "IconUtils.h"

#include <QColor>
#include <QFont>
#include <QHBoxLayout>
#include <QLabel>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPaintEvent>
#include <QPixmap>
#include <QPushButton>
#include <QVBoxLayout>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QUrl>
#include <QWindow>

#include <climits>

namespace {
const QColor MiniIconColor(215, 215, 225);

QPixmap roundedCover(const QString &path, int size) {
    QPixmap output = CoverCache::cover(path, size);
    if (output.isNull()) {
        output = QPixmap(size, size);
        output.fill(QColor(36, 36, 40));
        QPainter painter(&output);
        painter.setPen(QColor(141, 141, 152));
        QFont font = painter.font();
        font.setPointSize(28);
        painter.setFont(font);
        painter.drawText(QRect(0, 0, size, size), Qt::AlignCenter,
                         QStringLiteral("♪"));
        return output;
    }

    QPainter painter(&output);
    painter.setRenderHint(QPainter::Antialiasing, true);
    painter.setCompositionMode(QPainter::CompositionMode_DestinationIn);
    QPainterPath clip;
    clip.addRoundedRect(QRectF(0, 0, size, size), 8, 8);
    painter.fillPath(clip, QColor(0, 0, 0, 255));
    return output;
}
} // namespace

MiniPlayer::MiniPlayer(QWidget *parent) : QWidget(parent) {
    setObjectName(QStringLiteral("miniPlayer"));
    setWindowFlags(Qt::Tool | Qt::FramelessWindowHint | Qt::WindowStaysOnTopHint);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAttribute(Qt::WA_StyledBackground, true);
    setFixedSize(390, 188);
    setStyleSheet(QStringLiteral(R"(
        #miniPlayer {
            background: transparent;
            border: none;
        }
        #miniTitle { color: #f2f2f5; }
        #miniArtist { color: #a7a7b2; }
        #miniTime { color: #b8b8c2; font-size: 11px; }
        QPushButton#miniButton, QPushButton#miniExpand, QPushButton#miniClose {
            background: transparent;
            border: none;
        }
        QPushButton#miniButton:hover, QPushButton#miniExpand:hover,
        QPushButton#miniClose:hover {
            background-color: rgba(255, 255, 255, 18);
            border-radius: 6px;
        }
    )"));

    auto *root = new QHBoxLayout(this);
    root->setContentsMargins(14, 14, 14, 14);
    root->setSpacing(12);

    m_cover = new QLabel(this);
    m_cover->setObjectName(QStringLiteral("miniCover"));
    m_cover->setFixedSize(112, 112);
    m_cover->setAlignment(Qt::AlignCenter);
    root->addWidget(m_cover);

    auto *right = new QVBoxLayout();
    right->setContentsMargins(0, 0, 0, 0);
    right->setSpacing(4);

    auto *header = new QHBoxLayout();
    auto *text = new QVBoxLayout();
    text->setSpacing(1);
    m_title = new QLabel(tr("Nothing playing"), this);
    m_title->setObjectName(QStringLiteral("miniTitle"));
    QFont titleFont = m_title->font();
    titleFont.setBold(true);
    titleFont.setPointSize(titleFont.pointSize() + 1);
    m_title->setFont(titleFont);
    m_artist = new QLabel(this);
    m_artist->setObjectName(QStringLiteral("miniArtist"));
    text->addWidget(m_title);
    text->addWidget(m_artist);
    header->addLayout(text, 1);

    m_expand = new QPushButton(this);
    m_expand->setObjectName(QStringLiteral("miniExpand"));
    m_expand->setFixedSize(26, 26);
    m_expand->setFlat(true);
    m_expand->setCursor(Qt::PointingHandCursor);
    m_expand->setToolTip(tr("Expand"));
    m_expand->setIconSize(QSize(14, 14));
    m_close = new QPushButton(this);
    m_close->setObjectName(QStringLiteral("miniClose"));
    m_close->setFixedSize(24, 24);
    m_close->setFlat(true);
    m_close->setCursor(Qt::PointingHandCursor);
    m_close->setIconSize(QSize(12, 12));
    header->addWidget(m_expand, 0, Qt::AlignTop);
    header->addWidget(m_close, 0, Qt::AlignTop);
    right->addLayout(header);

    auto *seekRow = new QHBoxLayout();
    m_seek = new ClickSlider(Qt::Horizontal, this);
    m_seek->setObjectName(QStringLiteral("miniSeek"));
    m_seek->setRange(0, 0);
    m_time = new QLabel(QStringLiteral("0:00"), this);
    m_time->setObjectName(QStringLiteral("miniTime"));
    seekRow->addWidget(m_seek, 1);
    seekRow->addWidget(m_time);
    right->addLayout(seekRow);

    auto *controls = new QHBoxLayout();
    controls->setSpacing(10);
    m_previous = new QPushButton(this);
    m_play = new QPushButton(this);
    m_next = new QPushButton(this);
    for (QPushButton *button : {m_previous, m_next}) {
        button->setObjectName(QStringLiteral("miniButton"));
        button->setFlat(true);
        button->setFixedSize(34, 30);
        button->setIconSize(QSize(20, 20));
        button->setCursor(Qt::PointingHandCursor);
    }
    m_play->setObjectName(QStringLiteral("miniButton"));
    m_play->setFlat(true);
    m_play->setFixedSize(44, 40);
    m_play->setIconSize(QSize(22, 22));
    m_play->setCursor(Qt::PointingHandCursor);
    controls->addStretch(1);
    controls->addWidget(m_previous);
    controls->addWidget(m_play);
    controls->addWidget(m_next);
    controls->addStretch(1);
    right->addLayout(controls);
    root->addLayout(right, 1);

    connect(m_expand, &QPushButton::clicked, this, &MiniPlayer::expandRequested);
    connect(m_close, &QPushButton::clicked, this, &MiniPlayer::closeRequested);
    connect(m_previous, &QPushButton::clicked, this,
            &MiniPlayer::previousRequested);
    connect(m_next, &QPushButton::clicked, this, &MiniPlayer::nextRequested);
    connect(m_play, &QPushButton::clicked, this,
            &MiniPlayer::playPauseRequested);
    connect(m_seek, &ClickSlider::clickedValue, this, [this](int value) {
        m_time->setText(formatTime(value));
        emit seekRequested(value);
    });
    connect(m_seek, &QSlider::sliderPressed, this,
            [this] { m_draggingSeek = true; });
    connect(m_seek, &QSlider::sliderReleased, this, [this] {
        m_draggingSeek = false;
        emit seekRequested(m_seek->value());
    });
    connect(m_seek, &QSlider::sliderMoved, this, [this](int value) {
        m_time->setText(formatTime(value));
    });

    m_network = new QNetworkAccessManager(this);
    applyTheme();
    m_cover->setPixmap(roundedCover(QString(), 112));
}

void MiniPlayer::setTrack(const Track &track) {
    m_title->setText(track.title.isEmpty() ? tr("Unknown title") : track.title);
    m_artist->setText(track.artist.isEmpty() ? tr("Unknown artist")
                                            : track.artist);
    m_coverUrl.clear();
    const QPixmap cover = roundedCover(track.coverPath, 112);
    m_cover->setPixmap(cover);
    if (track.coverPath.isEmpty()) {
        m_tint = QColor();
    } else {
        updateTint(cover);
    }
    update();
}

void MiniPlayer::setCoverUrl(const QString &url) {
    if (url.isEmpty()) {
        m_coverUrl.clear();
        m_tint = QColor();
        m_cover->setPixmap(roundedCover(QString(), 112));
        update();
        return;
    }
    if (m_coverUrl == url) {
        return;
    }
    m_coverUrl = url;
    m_tint = QColor();
    m_cover->setPixmap(roundedCover(QString(), 112));
    update();
    QNetworkRequest request{QUrl(url)};
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("Mozilla/5.0 (X11; Linux x86_64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/131.0.0.0 Safari/537.36"));
    QNetworkReply *reply = m_network->get(request);
    connect(reply, &QNetworkReply::finished, this, [this, reply, url] {
        const QByteArray data = reply->readAll();
        reply->deleteLater();
        if (m_coverUrl != url || data.isEmpty()) {
            return;
        }
        QImage image;
        if (!image.loadFromData(data)) {
            return;
        }
        QPixmap pixmap = CoverCache::crop(QPixmap::fromImage(image),
                                          QSize(112, 112));
        if (pixmap.isNull()) {
            return;
        }
        QPixmap rounded(pixmap.size());
        rounded.setDevicePixelRatio(pixmap.devicePixelRatio());
        rounded.fill(Qt::transparent);
        QPainter painter(&rounded);
        painter.setRenderHint(QPainter::Antialiasing, true);
        QPainterPath clip;
        clip.addRoundedRect(QRectF(0, 0, 112, 112), 8, 8);
        painter.setClipPath(clip);
        painter.drawPixmap(0, 0, pixmap);
        m_cover->setPixmap(rounded);
        updateTint(rounded);
        update();
    });
}

void MiniPlayer::setPlaying(bool playing) {
    m_playing = playing;
    m_play->setIcon(IconUtils::tinted(
        playing ? QStringLiteral("pause.svg") : QStringLiteral("play.svg"),
        MiniIconColor, 22));
}

void MiniPlayer::setDuration(qint64 milliseconds) {
    m_duration = qMax<qint64>(0, milliseconds);
    const qint64 maximum = m_duration > 0
                               ? m_duration
                               : 24LL * 60 * 60 * 1000;
    m_seek->setRange(0, static_cast<int>(qMin<qint64>(maximum, INT_MAX)));
    m_time->setText(formatTime(m_seek->value()));
}

void MiniPlayer::setPosition(qint64 milliseconds) {
    if (m_draggingSeek) {
        return;
    }
    const qint64 maximum = static_cast<qint64>(m_seek->maximum());
    const int value =
        static_cast<int>(qBound<qint64>(0, milliseconds, maximum));
    m_seek->setValue(value);
    m_time->setText(formatTime(value));
}

void MiniPlayer::setSeekEnabled(bool enabled) {
    m_seek->setEnabled(enabled);
    m_seek->setToolTip(enabled ? QString()
                               : tr("Seeking is not available for streams."));
}

void MiniPlayer::applyTheme() {
    m_expand->setIcon(IconUtils::tinted(QStringLiteral("expand.svg"),
                                        MiniIconColor, 14));
    m_close->setIcon(IconUtils::tinted(QStringLiteral("cancel.svg"),
                                       MiniIconColor, 12));
    m_previous->setIcon(IconUtils::tinted(QStringLiteral("prev.svg"),
                                          MiniIconColor, 20));
    m_next->setIcon(IconUtils::tinted(QStringLiteral("next.svg"),
                                      MiniIconColor, 20));
    setPlaying(m_playing);
}

void MiniPlayer::paintEvent(QPaintEvent *event) {
    Q_UNUSED(event);
    QPainter painter(this);
    painter.setRenderHint(QPainter::Antialiasing, true);
    const QRectF rect = QRectF(this->rect()).adjusted(1, 1, -1, -1);
    QPainterPath path;
    path.addRoundedRect(rect, 16, 16);
    QLinearGradient background(rect.topLeft(), rect.bottomRight());
    if (m_tint.isValid()) {
        QColor top = m_tint.darker(180);
        top.setAlpha(245);
        QColor middle = m_tint.darker(320);
        middle.setAlpha(240);
        background.setColorAt(0.0, top);
        background.setColorAt(0.55, middle);
        background.setColorAt(1.0, QColor(4, 4, 7, 250));
    } else {
        background.setColorAt(0.0, QColor(34, 36, 48, 238));
        background.setColorAt(1.0, QColor(10, 10, 14, 244));
    }
    painter.fillPath(path, background);
    painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0));
    painter.drawPath(path);
}

void MiniPlayer::updateTint(const QPixmap &pixmap) {
    if (pixmap.isNull()) {
        m_tint = QColor();
        return;
    }
    const QImage sample = pixmap.toImage().scaled(
        1, 1, Qt::IgnoreAspectRatio, Qt::SmoothTransformation);
    m_tint = sample.isNull() ? QColor() : sample.pixelColor(0, 0);
}

void MiniPlayer::setCoverPixmap(const QPixmap &pixmap) {
    m_cover->setPixmap(pixmap);
    if (pixmap.isNull()) {
        m_tint = QColor();
    } else {
        updateTint(pixmap);
    }
    update();
}

void MiniPlayer::mousePressEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton && windowHandle()) {
        windowHandle()->startSystemMove();
        event->accept();
        return;
    }
    QWidget::mousePressEvent(event);
}

void MiniPlayer::mouseDoubleClickEvent(QMouseEvent *event) {
    if (event->button() == Qt::LeftButton) {
        emit expandRequested();
        event->accept();
        return;
    }
    QWidget::mouseDoubleClickEvent(event);
}

QString MiniPlayer::formatTime(qint64 milliseconds) {
    const qint64 totalSeconds = qMax<qint64>(0, milliseconds) / 1000;
    return QStringLiteral("%1:%2")
        .arg(totalSeconds / 60)
        .arg(totalSeconds % 60, 2, 10, QLatin1Char('0'));
}
