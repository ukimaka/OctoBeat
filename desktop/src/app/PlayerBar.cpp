#include "PlayerBar.h"

#include "ClickSlider.h"
#include "ElidedLabel.h"
#include "IconUtils.h"
#include "LyricsButton.h"
#include "Theme.h"

#include <QColor>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QSizePolicy>
#include <QVBoxLayout>

#include <climits>

namespace {
constexpr int VolumeBlockWidth = 150;
constexpr int ControlIconSize = 20;

QColor activeAccent() {
    return QColor(QStringLiteral("#5151ab"));
}
} // namespace

PlayerBar::PlayerBar(QWidget *parent) : QWidget(parent) {
    setObjectName(QStringLiteral("playerBar"));
    setAttribute(Qt::WA_StyledBackground, true);
    setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Fixed);

    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(18, 8, 18, 10);
    root->setSpacing(5);

    // Row 1: current track + playback context.
    auto *row1 = new QHBoxLayout();
    row1->setContentsMargins(0, 0, 0, 0);
    row1->setSpacing(12);
    m_title = new ElidedLabel(tr("Current Track") + QStringLiteral(": —"), this);
    m_title->setObjectName(QStringLiteral("currentTrack"));
    m_title->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
    m_title->setMinimumWidth(0);
    m_context = new QLabel(tr("Playing from") + QStringLiteral(": —"), this);
    m_context->setObjectName(QStringLiteral("contextLabel"));
    m_context->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Preferred);
    row1->addWidget(m_title, 1);
    row1->addWidget(m_context);
    root->addLayout(row1);

    // Row 2: timeline across the full width, time on the right.
    auto *timelineRow = new QHBoxLayout();
    timelineRow->setContentsMargins(0, 0, 0, 0);
    timelineRow->setSpacing(8);
    m_seek = new ClickSlider(Qt::Horizontal, this);
    m_seek->setObjectName(QStringLiteral("seekSlider"));
    m_seek->setRange(0, 0);
    m_time = new QLabel(QStringLiteral("0:00 / 0:00"), this);
    m_time->setObjectName(QStringLiteral("playerTime"));
    m_time->setMinimumWidth(72);
    m_time->setSizePolicy(QSizePolicy::Minimum, QSizePolicy::Preferred);
    timelineRow->addWidget(m_seek, 1);
    timelineRow->addWidget(m_time, 0);
    root->addLayout(timelineRow);

    // Row 3: centered transport controls + fixed-width volume block.
    auto *controls = new QHBoxLayout();
    controls->setContentsMargins(0, 0, 0, 0);
    controls->setSpacing(8);

    m_previous = new QPushButton(this);
    m_previous->setObjectName(QStringLiteral("playerButton"));
    m_previous->setFixedSize(34, 30);
    m_previous->setFlat(true);
    m_previous->setIconSize(QSize(ControlIconSize, ControlIconSize));

    m_play = new QPushButton(this);
    m_play->setObjectName(QStringLiteral("playerPlay"));
    m_play->setFixedSize(46, 40);
    m_play->setFlat(true);
    m_play->setIconSize(QSize(26, 26));

    m_next = new QPushButton(this);
    m_next->setObjectName(QStringLiteral("playerButton"));
    m_next->setFixedSize(34, 30);
    m_next->setFlat(true);
    m_next->setIconSize(QSize(ControlIconSize, ControlIconSize));

    m_repeat = new QPushButton(this);
    m_repeat->setObjectName(QStringLiteral("repeatButton"));
    m_repeat->setFixedSize(32, 28);
    m_repeat->setFlat(true);
    m_repeat->setIconSize(QSize(18, 18));

    m_shuffle = new QPushButton(this);
    m_shuffle->setObjectName(QStringLiteral("shuffleButton"));
    m_shuffle->setFixedSize(32, 28);
    m_shuffle->setFlat(true);
    m_shuffle->setCheckable(true);
    m_shuffle->setIconSize(QSize(18, 18));

    m_lyrics = new LyricsButton(this);
    m_lyrics->setObjectName(QStringLiteral("lyricsButton"));
    m_lyrics->setFixedSize(32, 28);
    m_lyrics->setFlat(true);
    m_lyrics->setCheckable(true);
    m_lyrics->setIconSize(QSize(20, 20));
    m_lyrics->setToolTip(tr("Lyrics"));

    auto *volumeBlock = new QWidget(this);
    volumeBlock->setObjectName(QStringLiteral("volumeBlock"));
    volumeBlock->setFixedWidth(VolumeBlockWidth);
    auto *volumeLayout = new QHBoxLayout(volumeBlock);
    volumeLayout->setContentsMargins(0, 0, 0, 0);
    volumeLayout->setSpacing(6);
    m_volumeIcon = new QLabel(volumeBlock);
    m_volumeIcon->setObjectName(QStringLiteral("volumeIcon"));
    m_volumeIcon->setFixedSize(22, 22);
    m_volume = new ClickSlider(Qt::Horizontal, volumeBlock);
    m_volume->setObjectName(QStringLiteral("volumeSlider"));
    m_volume->setRange(0, 100);
    m_volume->setValue(70);
    m_volume->setFixedWidth(120);
    volumeLayout->addWidget(m_volumeIcon);
    volumeLayout->addWidget(m_volume);

    controls->addSpacing(VolumeBlockWidth);
    controls->addStretch(1);
    controls->addWidget(m_repeat);
    controls->addWidget(m_previous);
    controls->addWidget(m_play);
    controls->addWidget(m_next);
    controls->addWidget(m_shuffle);
    controls->addWidget(m_lyrics);
    controls->addStretch(1);
    controls->addWidget(volumeBlock);
    root->addLayout(controls);

    connect(m_previous, &QPushButton::clicked, this,
            &PlayerBar::previousRequested);
    connect(m_next, &QPushButton::clicked, this, &PlayerBar::nextRequested);
    connect(m_play, &QPushButton::clicked, this, &PlayerBar::playPauseRequested);
    connect(m_repeat, &QPushButton::clicked, this, [this] {
        if (m_repeatMode == QStringLiteral("off")) {
            setRepeatMode(QStringLiteral("all"));
        } else if (m_repeatMode == QStringLiteral("all")) {
            setRepeatMode(QStringLiteral("one"));
        } else {
            setRepeatMode(QStringLiteral("off"));
        }
        emit repeatModeChanged(m_repeatMode);
    });
    connect(m_shuffle, &QPushButton::toggled, this, [this](bool enabled) {
        m_shuffleEnabled = enabled;
        setShuffle(enabled);
        emit shuffleChanged(enabled);
    });
    connect(m_lyrics, &QPushButton::toggled, this, [this](bool enabled) {
        m_lyricsActive = enabled;
        setLyricsActive(enabled);
        emit lyricsToggled(enabled);
    });
    connect(m_lyrics, &LyricsButton::doubleClicked, this,
            &PlayerBar::karaokeRequested);
    connect(m_seek, &ClickSlider::clickedValue, this, [this](int value) {
        m_time->setText(formatTime(value) + QStringLiteral(" / ") +
                        formatTime(m_duration));
        emit seekRequested(value);
    });
    connect(m_seek, &QSlider::sliderPressed, this,
            [this] { m_draggingSeek = true; });
    connect(m_seek, &QSlider::sliderReleased, this, [this] {
        m_draggingSeek = false;
        emit seekRequested(m_seek->value());
    });
    connect(m_seek, &QSlider::sliderMoved, this, [this](int value) {
        m_time->setText(formatTime(value) + QStringLiteral(" / ") +
                        formatTime(m_duration));
    });
    connect(m_volume, &ClickSlider::clickedValue, this,
            [this](int value) { emit volumeChanged(value); });
    connect(m_volume, &QSlider::valueChanged, this, [this](int value) {
        updateVolumeIcon(value);
        emit volumeChanged(value);
    });

    m_play->setCursor(Qt::PointingHandCursor);
    m_previous->setCursor(Qt::PointingHandCursor);
    m_next->setCursor(Qt::PointingHandCursor);
    m_repeat->setCursor(Qt::PointingHandCursor);
    m_shuffle->setCursor(Qt::PointingHandCursor);
    m_lyrics->setCursor(Qt::PointingHandCursor);

    applyTheme();
    updateVolumeIcon(m_volume->value());
}

void PlayerBar::setTrack(const Track &track) {
    const QString title = track.title.isEmpty() ? tr("Unknown title") : track.title;
    m_title->setText(tr("Current Track") + QStringLiteral(": ") + title);
}

void PlayerBar::setContext(const QString &name) {
    m_context->setText(name.isEmpty()
                           ? tr("Playing from") + QStringLiteral(": —")
                           : tr("Playing from") + QStringLiteral(": ") + name);
}

void PlayerBar::setPlaying(bool playing) {
    m_playing = playing;
    m_play->setIcon(IconUtils::tinted(
        playing ? QStringLiteral("pause.svg") : QStringLiteral("play.svg"),
        Theme::iconColor(), 26));
}

void PlayerBar::setDuration(qint64 milliseconds) {
    m_duration = qMax<qint64>(0, milliseconds);
    // Unknown duration (common for live FIFO streams) should not freeze the
    // timeline at 0:00. Give the disabled slider a moving range instead.
    const qint64 maximum = m_duration > 0
                               ? m_duration
                               : 24LL * 60 * 60 * 1000;
    m_seek->setRange(0, static_cast<int>(qMin<qint64>(maximum, INT_MAX)));
    const QString total = m_duration > 0 ? formatTime(m_duration)
                                         : QStringLiteral("--:--");
    m_time->setText(formatTime(m_seek->value()) + QStringLiteral(" / ") +
                    total);
}

void PlayerBar::setPosition(qint64 milliseconds) {
    if (m_draggingSeek) {
        return;
    }
    const qint64 maximum = static_cast<qint64>(m_seek->maximum());
    const int value =
        static_cast<int>(qBound<qint64>(0, milliseconds, maximum));
    m_seek->setValue(value);
    const QString total = m_duration > 0 ? formatTime(m_duration)
                                         : QStringLiteral("--:--");
    m_time->setText(formatTime(value) + QStringLiteral(" / ") + total);
}

void PlayerBar::setVolume(int volume) {
    m_volume->blockSignals(true);
    m_volume->setValue(qBound(0, volume, 100));
    m_volume->blockSignals(false);
    updateVolumeIcon(m_volume->value());
}

void PlayerBar::setRepeatMode(const QString &mode) {
    m_repeatMode = (mode == QStringLiteral("all") ||
                    mode == QStringLiteral("one"))
                       ? mode
                       : QStringLiteral("off");
    const bool active = m_repeatMode != QStringLiteral("off");
    m_repeat->setIcon(IconUtils::tinted(
        m_repeatMode == QStringLiteral("one") ? QStringLiteral("repeat-one.svg")
                                              : QStringLiteral("repeat.svg"),
        active ? activeAccent() : Theme::iconColor(), 18));
    m_repeat->setToolTip(
        m_repeatMode == QStringLiteral("off")
            ? tr("Repeat: off")
            : (m_repeatMode == QStringLiteral("one") ? tr("Repeat: one")
                                                     : tr("Repeat: all")));
}

void PlayerBar::setShuffle(bool enabled) {
    m_shuffleEnabled = enabled;
    m_shuffle->blockSignals(true);
    m_shuffle->setChecked(enabled);
    m_shuffle->blockSignals(false);
    m_shuffle->setIcon(IconUtils::tinted(
        QStringLiteral("shuffle.svg"),
        enabled ? activeAccent() : Theme::iconColor(), 18));
    m_shuffle->setToolTip(enabled ? tr("Shuffle: on") : tr("Shuffle: off"));
}

void PlayerBar::setLyricsActive(bool active) {
    m_lyricsActive = active;
    m_lyrics->blockSignals(true);
    m_lyrics->setChecked(active);
    m_lyrics->blockSignals(false);
    m_lyrics->setIcon(IconUtils::tinted(
        QStringLiteral("karaoke.svg"),
        active ? activeAccent() : Theme::iconColor(), 20));
}

void PlayerBar::setSeekEnabled(bool enabled) {
    m_seek->setEnabled(enabled);
    m_seek->setToolTip(enabled ? QString()
                               : tr("Seeking is not available for streams."));
}

void PlayerBar::applyTheme() {
    const QColor color = Theme::iconColor();
    m_previous->setIcon(IconUtils::tinted(QStringLiteral("prev.svg"), color,
                                          ControlIconSize));
    m_next->setIcon(IconUtils::tinted(QStringLiteral("next.svg"), color,
                                      ControlIconSize));
    m_play->setIcon(IconUtils::tinted(
        m_playing ? QStringLiteral("pause.svg") : QStringLiteral("play.svg"),
        color, 26));
    setRepeatMode(m_repeatMode);
    setShuffle(m_shuffleEnabled);
    setLyricsActive(m_lyricsActive);
    updateVolumeIcon(m_volume ? m_volume->value() : 70);
}

void PlayerBar::updateVolumeIcon(int value) {
    if (!m_volumeIcon) {
        return;
    }
    const QString name = value == 0
                             ? QStringLiteral("volume-mute.svg")
                             : (value < 50 ? QStringLiteral("volume-low.svg")
                                           : QStringLiteral("volume-high.svg"));
    m_volumeIcon->setPixmap(
        IconUtils::tinted(name, Theme::iconColor(), 22).pixmap(22, 22));
}

QString PlayerBar::formatTime(qint64 milliseconds) {
    const qint64 totalSeconds = qMax<qint64>(0, milliseconds) / 1000;
    const qint64 hours = totalSeconds / 3600;
    const qint64 minutes = (totalSeconds % 3600) / 60;
    const qint64 seconds = totalSeconds % 60;
    if (hours > 0) {
        return QStringLiteral("%1:%2:%3")
            .arg(hours)
            .arg(minutes, 2, 10, QLatin1Char('0'))
            .arg(seconds, 2, 10, QLatin1Char('0'));
    }
    return QStringLiteral("%1:%2")
        .arg(minutes)
        .arg(seconds, 2, 10, QLatin1Char('0'));
}
