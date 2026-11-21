#include "AudioEngine.h"

#include <cmath>

namespace {
constexpr double Pi = 3.14159265358979323846;
constexpr int FadeIntervalMs = 50;
constexpr int FadeWarmupMs = 200;
} // namespace

AudioEngine::AudioEngine(QObject *parent) : QObject(parent) {
    m_engine = octobeat_audio_new();
    if (!m_engine) {
        return;
    }
    octobeat_audio_set_volume(m_engine, m_volume);
    octobeat_audio_set_slot_volume(m_engine, 0, 100);
    octobeat_audio_set_slot_volume(m_engine, 1, 0);
    m_timer.setInterval(200);
    connect(&m_timer, &QTimer::timeout, this, &AudioEngine::poll);
    m_fadeTimer.setInterval(FadeIntervalMs);
    connect(&m_fadeTimer, &QTimer::timeout, this, &AudioEngine::tickFade);
}

AudioEngine::~AudioEngine() {
    m_timer.stop();
    m_fadeTimer.stop();
    if (m_engine) {
        octobeat_audio_free(m_engine);
        m_engine = nullptr;
    }
}

void AudioEngine::playFile(const QString &path, qint64 startPositionMs) {
    if (!m_engine) {
        emit errorOccurred(tr("Audio output is unavailable."));
        return;
    }
    if (path.isEmpty()) {
        emit errorOccurred(tr("Cannot play an empty path"));
        return;
    }
    m_fadeTimer.stop();
    m_fading = false;
    m_fadeStep = 0;
    m_fadeSteps = 0;
    m_fadeWarmupTicks = 0;
    m_active = 0;
    m_endEmitted = false;
    m_aboutToFinishSent = false;
    m_lastDuration = -1;
    m_playing = false;
    if (!octobeat_audio_play(m_engine, path.toUtf8().constData(),
                             qMax<qint64>(0, startPositionMs))) {
        char error[1024] = {};
        if (octobeat_audio_take_error(m_engine, error, static_cast<int>(sizeof(error))) > 0) {
            emit errorOccurred(QString::fromUtf8(error));
        } else {
            emit errorOccurred(tr("Could not start audio playback."));
        }
        return;
    }
    m_timer.start();
}

void AudioEngine::togglePause() {
    if (m_fading) {
        finishFadeNow();
    }
    if (!m_engine) {
        return;
    }
    if (octobeat_audio_is_playing(m_engine)) {
        octobeat_audio_pause(m_engine);
    } else {
        octobeat_audio_resume(m_engine);
    }
}

void AudioEngine::pause() {
    if (m_fading) {
        finishFadeNow();
    }
    if (m_engine) {
        octobeat_audio_pause(m_engine);
    }
}

void AudioEngine::resume() {
    if (m_engine) {
        octobeat_audio_resume(m_engine);
    }
}

void AudioEngine::stop() {
    m_timer.stop();
    m_fadeTimer.stop();
    m_fading = false;
    m_fadeStep = 0;
    m_fadeSteps = 0;
    m_fadeWarmupTicks = 0;
    m_active = 0;
    if (m_engine) {
        octobeat_audio_cancel_crossfade(m_engine);
        octobeat_audio_stop(m_engine);
    }
    m_endEmitted = false;
    m_aboutToFinishSent = false;
    m_lastDuration = -1;
    m_playing = false;
    emit playingChanged(false);
}

void AudioEngine::setVolume(int volume) {
    m_volume = qBound(0, volume, 100);
    if (!m_engine) {
        return;
    }
    octobeat_audio_set_volume(m_engine, m_volume);
    if (m_fading) {
        const double progress =
            m_fadeSteps > 0
                ? static_cast<double>(m_fadeStep) / m_fadeSteps
                : 0.0;
        applyFadeVolumes(progress);
    } else {
        octobeat_audio_set_slot_volume(m_engine, m_active, 100);
        octobeat_audio_set_slot_volume(m_engine, 1 - m_active, 0);
    }
}

void AudioEngine::seekTo(qint64 milliseconds) {
    if (!m_engine) {
        return;
    }
    if (m_fading) {
        cancelFade();
    }
    octobeat_audio_seek(m_engine, qMax<qint64>(0, milliseconds));
    m_endEmitted = false;
    m_aboutToFinishSent = false;
    m_lastDuration = -1;
}

void AudioEngine::setDurationHint(qint64 milliseconds) {
    m_durationHint = qMax<qint64>(0, milliseconds);
    if (m_engine) {
        octobeat_audio_set_duration_hint(m_engine, m_durationHint);
    }
}

void AudioEngine::setCrossfadeEnabled(bool enabled) {
    if (m_crossfadeEnabled == enabled) {
        return;
    }
    m_crossfadeEnabled = enabled;
    if (!enabled) {
        cancelFade();
    }
}

bool AudioEngine::crossfadeTo(const QString &path) {
    if (!m_engine || !m_crossfadeEnabled || m_fading || path.isEmpty()) {
        return false;
    }
    if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_AUDIO")) {
        qWarning("audio: crossfade request enabled=%d fading=%d",
                 m_crossfadeEnabled ? 1 : 0, m_fading ? 1 : 0);
    }
    if (!octobeat_audio_crossfade(m_engine, path.toUtf8().constData())) {
        char error[1024] = {};
        octobeat_audio_take_error(m_engine, error, static_cast<int>(sizeof(error)));
        if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_AUDIO")) {
            qWarning("audio: crossfade rejected: %s", error);
        }
        return false;
    }

    const qint64 remaining = duration() - position();
    if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_AUDIO")) {
        qWarning("audio: crossfade remaining=%lld dur=%lld pos=%lld",
                 static_cast<long long>(remaining),
                 static_cast<long long>(duration()),
                 static_cast<long long>(position()));
    }
    if (remaining < 600) {
        octobeat_audio_cancel_crossfade(m_engine);
        return false;
    }
    const int warmupMs =
        qMin(FadeWarmupMs, static_cast<int>(remaining / 4));
    const qint64 available = remaining - warmupMs - 100;
    const int fadeMs =
        qBound(300,
               qMin(effectiveFadeDuration(), static_cast<int>(available)),
               m_crossfadeDurationMs);
    octobeat_audio_set_slot_volume(m_engine, 1 - m_active, 0);
    octobeat_audio_set_slot_volume(m_engine, m_active, 100);
    m_fading = true;
    m_fadeStep = 0;
    m_fadeWarmupTicks = qMax(0, warmupMs / FadeIntervalMs);
    m_fadeSteps = qMax(1, fadeMs / FadeIntervalMs);
    m_fadeTimer.start();
    return true;
}

int AudioEngine::effectiveFadeDuration() const {
    const qint64 length = duration();
    if (length <= 0) {
        return m_crossfadeDurationMs;
    }
    return qMin(m_crossfadeDurationMs,
                qMax(500, static_cast<int>(length / 3)));
}

void AudioEngine::applyFadeVolumes(double progress) {
    const double clamped = qBound(0.0, progress, 1.0);
    const double outGain = std::cos(clamped * Pi / 2.0);
    const double inGain = std::sin(clamped * Pi / 2.0);
    if (!m_engine) {
        return;
    }
    octobeat_audio_set_slot_volume(
        m_engine, m_active, qRound(outGain * 100.0));
    octobeat_audio_set_slot_volume(
        m_engine, 1 - m_active, qRound(inGain * 100.0));
}

void AudioEngine::tickFade() {
    if (!m_fading) {
        m_fadeTimer.stop();
        return;
    }
    if (m_fadeWarmupTicks > 0) {
        --m_fadeWarmupTicks;
        applyFadeVolumes(0.0);
        return;
    }
    ++m_fadeStep;
    const double progress = static_cast<double>(m_fadeStep) / m_fadeSteps;
    applyFadeVolumes(progress);
    if (m_fadeStep >= m_fadeSteps) {
        finishFadeNow();
    }
}

void AudioEngine::finishFadeNow() {
    if (!m_fading) {
        return;
    }
    m_fadeTimer.stop();
    m_fading = false;
    m_fadeStep = 0;
    if (m_engine) {
        octobeat_audio_finish_crossfade(m_engine);
    }
    m_active = 1 - m_active;
    if (m_engine) {
        octobeat_audio_set_slot_volume(m_engine, m_active, 100);
        octobeat_audio_set_slot_volume(m_engine, 1 - m_active, 0);
    }
    m_endEmitted = false;
    m_aboutToFinishSent = false;
    m_lastDuration = -1;
    emit durationChanged(duration());
    emit positionChanged(position());
    emit crossfadeFinished();
}

void AudioEngine::cancelFade() {
    m_fadeTimer.stop();
    if (m_fading) {
        if (m_engine) {
            octobeat_audio_cancel_crossfade(m_engine);
            octobeat_audio_set_slot_volume(m_engine, m_active, 100);
            octobeat_audio_set_slot_volume(m_engine, 1 - m_active, 0);
        }
    }
    m_fading = false;
    m_fadeStep = 0;
    m_fadeSteps = 0;
    m_fadeWarmupTicks = 0;
}

qint64 AudioEngine::duration() const {
    if (m_engine) {
        const qint64 value = octobeat_audio_duration(m_engine);
        if (value > 0) {
            return value;
        }
    }
    return m_durationHint;
}

qint64 AudioEngine::position() const {
    return m_engine ? octobeat_audio_position(m_engine) : 0;
}

int AudioEngine::activeSlot() const {
    return m_engine ? octobeat_audio_active_slot(m_engine) : 0;
}

quint64 AudioEngine::underruns() const {
    return m_engine ? octobeat_audio_underruns(m_engine) : 0;
}

void AudioEngine::poll() {
    if (!m_engine) {
        m_timer.stop();
        return;
    }

    char error[1024] = {};
    if (octobeat_audio_take_error(m_engine, error, static_cast<int>(sizeof(error))) > 0) {
        if (m_fading) {
            cancelFade();
        }
        emit errorOccurred(QString::fromUtf8(error));
    }

    bool playing = octobeat_audio_is_playing(m_engine) != 0;
    if (m_fading) {
        playing = true;
    }
    if (playing != m_playing) {
        m_playing = playing;
        emit playingChanged(m_playing);
    }

    const qint64 currentPosition = position();
    if (!m_fading) {
        emit positionChanged(currentPosition);
    }

    const qint64 length = duration();
    if (length != m_lastDuration) {
        m_lastDuration = length;
        emit durationChanged(length);
    }

    if (m_crossfadeEnabled && !m_fading && !m_aboutToFinishSent &&
        m_playing && length > 0 && currentPosition > 0) {
        const qint64 remaining = length - currentPosition;
        const qint64 threshold = effectiveFadeDuration() + 300;
        if (remaining > 250 && remaining <= threshold) {
            m_aboutToFinishSent = true;
            emit aboutToFinish();
        }
    }

    if (octobeat_audio_has_ended(m_engine) && !m_endEmitted &&
        !m_fading) {
        m_endEmitted = true;
        m_timer.stop();
        emit endReached();
    }
}
