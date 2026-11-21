#include "FastStreamService.h"

#include "app/ToolPaths.h"

#include <QDir>
#include <QFile>
#include <QProcess>
#include <QStandardPaths>
#include <QTimer>

#ifndef Q_OS_WIN
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

namespace {
constexpr int PipeSize = 1024 * 1024;

// Kill a process without blocking the UI thread. The finished/error signals
// delete the object later; Qt's QProcess destructor would otherwise wait for
// the child and freeze track switches.
void retireProcess(QProcess *process) {
    if (!process) {
        return;
    }
    process->disconnect();
    process->setParent(nullptr);
    QObject::connect(process,
                     QOverload<int, QProcess::ExitStatus>::of(
                         &QProcess::finished),
                     process, &QObject::deleteLater);
    QObject::connect(process, &QProcess::errorOccurred, process,
                     &QObject::deleteLater);
    if (process->state() != QProcess::NotRunning) {
        process->kill();
    } else {
        process->deleteLater();
    }
}
} // namespace

FastStreamService::FastStreamService(QObject *parent) : QObject(parent) {
    m_startTimeout = new QTimer(this);
    m_startTimeout->setSingleShot(true);
    m_startTimeout->setInterval(7000);
    connect(m_startTimeout, &QTimer::timeout, this, [this] {
        fail(tr("The stream did not start in time."));
    });
}

FastStreamService::~FastStreamService() {
    stop();
}

bool FastStreamService::isRunning() const {
    return m_process && m_process->state() != QProcess::NotRunning;
}

void FastStreamService::start(const QString &hlsUrl,
                              const QString &directory,
                              const QString &key,
                              int durationSeconds,
                              qint64 startMs) {
#ifdef Q_OS_WIN
    Q_UNUSED(hlsUrl);
    Q_UNUSED(directory);
    Q_UNUSED(key);
    Q_UNUSED(durationSeconds);
    Q_UNUSED(startMs);
    stop();
    emit failed(tr("Fast streaming is not available on Windows."));
    return;
#else

    stop();
    if (hlsUrl.isEmpty()) {
        emit failed(tr("No stream URL."));
        return;
    }
    if (!QDir().mkpath(directory)) {
        emit failed(tr("Could not create the stream cache folder."));
        return;
    }

    QString safeKey = key;
    for (QChar &ch : safeKey) {
        if (!ch.isLetterOrNumber() && ch != QLatin1Char('-') &&
            ch != QLatin1Char('_')) {
            ch = QLatin1Char('_');
        }
    }
    if (safeKey.isEmpty()) {
        safeKey = QStringLiteral("current");
    }
    ++m_generation;
    m_fifoPath = QDir(directory).filePath(
        QStringLiteral("stream-%1-%2.aac").arg(safeKey).arg(m_generation));
    m_durationSeconds = durationSeconds;
    m_startMs = qMax<qint64>(0, startMs);
    m_ready = false;
    m_progressSeen = false;
    m_prebuffered = false;
    m_stopping = false;
    m_errorOutput.clear();

    QFile::remove(m_fifoPath);
    const QByteArray nativePath = QFile::encodeName(m_fifoPath);
    if (::mkfifo(nativePath.constData(), 0600) != 0) {
        emit failed(tr("Could not create the stream pipe."));
        return;
    }

    // Keep a read/write descriptor open so ffmpeg can start before the audio engine opens
    // the FIFO. This also lets us grow the pipe buffer to ~60 seconds of
    // audio, which absorbs short network hiccups.
    m_pipeFd = ::open(nativePath.constData(), O_RDWR | O_NONBLOCK);
    if (m_pipeFd < 0) {
        cleanupFifo();
        emit failed(tr("Could not open the stream pipe."));
        return;
    }
    ::fcntl(m_pipeFd, F_SETPIPE_SZ, PipeSize);

    const QString ffmpeg = ToolPaths::executable(QStringLiteral("ffmpeg"));
    if (ffmpeg.isEmpty()) {
        cleanupFifo();
        emit failed(tr("ffmpeg was not found in PATH."));
        return;
    }

    QStringList arguments = {
        QStringLiteral("-hide_banner"),
        QStringLiteral("-y"),
        QStringLiteral("-loglevel"), QStringLiteral("error"),
        QStringLiteral("-nostdin"),
        QStringLiteral("-progress"), QStringLiteral("pipe:1"),
        QStringLiteral("-stats_period"), QStringLiteral("0.1"),
        QStringLiteral("-nostats"),
    };
    if (m_startMs > 0) {
        arguments << QStringLiteral("-ss")
                  << QString::number(m_startMs / 1000.0, 'f', 3);
    }
    arguments << QStringLiteral("-i") << hlsUrl
              << QStringLiteral("-vn")
              << QStringLiteral("-c:a") << QStringLiteral("copy")
              << QStringLiteral("-f") << QStringLiteral("adts")
              << m_fifoPath;
    m_process = new QProcess(this);
    m_process->setProgram(ffmpeg);
    m_process->setArguments(arguments);
    // HLS seeks need a little more time to fetch the first segment.
    m_startTimeout->setInterval(m_startMs > 0 ? 12000 : 7000);
    m_process->setProcessChannelMode(QProcess::SeparateChannels);
    connect(m_process, &QProcess::readyReadStandardOutput, this,
            &FastStreamService::handleProgress);
    connect(m_process, &QProcess::readyReadStandardError, this, [this] {
        if (!m_process) {
            return;
        }
        m_errorOutput +=
            QString::fromUtf8(m_process->readAllStandardError());
        if (m_errorOutput.size() > 4000) {
            m_errorOutput = m_errorOutput.right(4000);
        }
    });
    connect(m_process, &QProcess::finished, this,
            &FastStreamService::handleFfmpegFinished);
    connect(m_process, &QProcess::errorOccurred, this,
            [this](QProcess::ProcessError error) {
                if (error == QProcess::FailedToStart) {
                    fail(tr("Could not start ffmpeg."));
                }
            });

    m_startTimeout->start();
    m_process->start();
    // Hand the FIFO to the audio engine immediately so its output is initialised
    // while ffmpeg is still fetching the first HLS segment. The dummy
    // read/write descriptor above keeps the FIFO open until the audio engine connects.
    QTimer::singleShot(0, this, [this] {
        if (!m_process || m_ready) {
            return;
        }
        m_ready = true;
        emit ready(m_fifoPath, m_durationSeconds);
    });
#endif
}

void FastStreamService::stop() {
    m_stopping = true;
    if (m_startTimeout) {
        m_startTimeout->stop();
    }
    if (m_process) {
        QProcess *process = m_process;
        m_process = nullptr;
        retireProcess(process);
    }
    closePipe();
    cleanupFifo();
    m_ready = false;
    m_prebuffered = false;
    m_stopping = false;
}

void FastStreamService::handleProgress() {
    if (!m_process) {
        return;
    }
    const QString output =
        QString::fromUtf8(m_process->readAllStandardOutput());
    for (const QString &line : output.split(QLatin1Char('\n'))) {
        const QString trimmed = line.trimmed();
        qint64 totalSize = -1;
        if (trimmed.startsWith(QStringLiteral("total_size="))) {
            totalSize =
                trimmed.mid(QStringLiteral("total_size=").size()).toLongLong();
        }
        if (totalSize > 0) {
            m_progressSeen = true;
        }
        if (m_ready) {
            m_startTimeout->stop();
        }
        if (totalSize > 0 && m_ready && !m_prebuffered) {
            m_prebuffered = true;
            emit prebuffered(m_fifoPath, m_durationSeconds);
        }
    }
}

void FastStreamService::handleFfmpegFinished(int exitCode,
                                             QProcess::ExitStatus status) {
    if (m_stopping || !m_process) {
        return;
    }
    const bool wasReady = m_ready;
    if (m_startTimeout) {
        m_startTimeout->stop();
    }
    if (m_process) {
        m_process->deleteLater();
        m_process = nullptr;
    }
    closePipe();

    if (!wasReady || !m_progressSeen || exitCode != 0 ||
        status == QProcess::CrashExit) {
        QString message = m_errorOutput.trimmed();
        if (message.isEmpty()) {
            message = status == QProcess::CrashExit
                          ? tr("ffmpeg crashed.")
                          : tr("ffmpeg could not open the stream.");
        }
        cleanupFifo();
        m_ready = false;
        emit failed(message);
        return;
    }
    m_ready = false;
    emit finished();
}

void FastStreamService::closePipe() {
#ifdef Q_OS_WIN
    m_pipeFd = -1;
#else
    if (m_pipeFd >= 0) {
        ::close(m_pipeFd);
        m_pipeFd = -1;
    }
#endif
}

void FastStreamService::cleanupFifo() {
    closePipe();
    if (!m_fifoPath.isEmpty()) {
        QFile::remove(m_fifoPath);
    }
}

void FastStreamService::fail(const QString &message) {
    if (m_stopping) {
        return;
    }
    m_stopping = true;
    if (m_startTimeout) {
        m_startTimeout->stop();
    }
    if (m_process) {
        QProcess *process = m_process;
        m_process = nullptr;
        retireProcess(process);
    }
    closePipe();
    cleanupFifo();
    m_ready = false;
    m_stopping = false;
    emit failed(message);
}
