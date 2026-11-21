#pragma once

#include <QObject>
#include <QProcess>
#include <QString>

class QProcess;
class QTimer;

// Turns a resolved HLS URL into a local ADTS AAC FIFO. ffmpeg downloads the
// audio stream and writes it into the FIFO, while the native engine reads the FIFO as a
// live stream. The FIFO is pre-buffered (up to the Linux pipe limit) so
// playback starts after a few seconds of audio instead of waiting for the
// whole track.
class FastStreamService : public QObject {
    Q_OBJECT

public:
    explicit FastStreamService(QObject *parent = nullptr);
    ~FastStreamService() override;

    void start(const QString &hlsUrl,
               const QString &directory,
               const QString &key,
               int durationSeconds,
               qint64 startMs = 0);
    void stop();
    bool isRunning() const;
    QString path() const { return m_fifoPath; }

signals:
    void ready(const QString &path, int durationSeconds);
    void prebuffered(const QString &path, int durationSeconds);
    void failed(const QString &message);
    void finished();

private:
    void handleProgress();
    void handleFfmpegFinished(int exitCode, QProcess::ExitStatus status);
    void closePipe();
    void cleanupFifo();
    void fail(const QString &message);

    QProcess *m_process = nullptr;
    QTimer *m_startTimeout = nullptr;
    QString m_fifoPath;
    QString m_errorOutput;
    int m_pipeFd = -1;
    int m_durationSeconds = 0;
    qint64 m_startMs = 0;
    int m_generation = 0;
    bool m_ready = false;
    bool m_progressSeen = false;
    bool m_prebuffered = false;
    bool m_stopping = false;
};
