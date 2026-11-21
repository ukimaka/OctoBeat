#pragma once

#include <QWidget>

#include "core/CoreClient.h"

class ElidedLabel;
class LyricsButton;
class ClickSlider;
class QLabel;
class QPushButton;

class PlayerBar : public QWidget {
    Q_OBJECT

public:
    explicit PlayerBar(QWidget *parent = nullptr);

    void setTrack(const Track &track);
    void setContext(const QString &name);
    void setPlaying(bool playing);
    void setDuration(qint64 milliseconds);
    void setPosition(qint64 milliseconds);
    void setVolume(int volume);
    void setRepeatMode(const QString &mode);
    void setShuffle(bool enabled);
    void setLyricsActive(bool active);
    void setSeekEnabled(bool enabled);
    void applyTheme();

    QString repeatMode() const { return m_repeatMode; }
    bool shuffle() const { return m_shuffleEnabled; }

signals:
    void playPauseRequested();
    void nextRequested();
    void previousRequested();
    void seekRequested(qint64 milliseconds);
    void volumeChanged(int volume);
    void repeatModeChanged(const QString &mode);
    void shuffleChanged(bool enabled);
    void lyricsToggled(bool enabled);
    void karaokeRequested();

private:
    static QString formatTime(qint64 milliseconds);
    void updateVolumeIcon(int value);

    ElidedLabel *m_title = nullptr;
    QLabel *m_context = nullptr;
    QPushButton *m_play = nullptr;
    QPushButton *m_previous = nullptr;
    QPushButton *m_next = nullptr;
    QPushButton *m_repeat = nullptr;
    QPushButton *m_shuffle = nullptr;
    LyricsButton *m_lyrics = nullptr;
    ClickSlider *m_seek = nullptr;
    QLabel *m_time = nullptr;
    QLabel *m_volumeIcon = nullptr;
    ClickSlider *m_volume = nullptr;
    qint64 m_duration = 0;
    bool m_draggingSeek = false;
    bool m_playing = false;
    bool m_lyricsActive = false;
    QString m_repeatMode = QStringLiteral("off");
    bool m_shuffleEnabled = false;
};
