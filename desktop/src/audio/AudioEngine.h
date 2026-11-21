#pragma once

#include <QObject>
#include <QString>
#include <QTimer>

#include "audio_engine.h"

class AudioEngine : public QObject {
    Q_OBJECT

public:
    explicit AudioEngine(QObject *parent = nullptr);
    ~AudioEngine() override;

    bool isValid() const { return m_engine != nullptr; }

    void playFile(const QString &path, qint64 startPositionMs = -1);
    void togglePause();
    void pause();
    void resume();
    void stop();
    void setVolume(int volume);
    void seekTo(qint64 milliseconds);
    void setDurationHint(qint64 milliseconds);

    void setCrossfadeEnabled(bool enabled);
    bool crossfadeEnabled() const { return m_crossfadeEnabled; }
    bool crossfadeTo(const QString &path);

    qint64 duration() const;
    qint64 position() const;
    bool isPlaying() const { return m_playing; }
    int activeSlot() const;
    quint64 underruns() const;

signals:
    void positionChanged(qint64 milliseconds);
    void durationChanged(qint64 milliseconds);
    void playingChanged(bool playing);
    void endReached();
    void errorOccurred(const QString &message);
    void aboutToFinish();
    void crossfadeFinished();

private slots:
    void poll();
    void tickFade();

private:
    int effectiveFadeDuration() const;
    void cancelFade();
    void finishFadeNow();
    void applyFadeVolumes(double progress);

    OctoAudioEngine *m_engine = nullptr;
    QTimer m_timer;
    QTimer m_fadeTimer;
    qint64 m_durationHint = 0;
    qint64 m_lastDuration = -1;
    bool m_playing = false;
    bool m_endEmitted = false;
    int m_volume = 70;
    int m_active = 0;

    bool m_crossfadeEnabled = false;
    int m_crossfadeDurationMs = 3000;
    bool m_fading = false;
    bool m_aboutToFinishSent = false;
    int m_fadeStep = 0;
    int m_fadeSteps = 0;
    int m_fadeWarmupTicks = 0;
};
