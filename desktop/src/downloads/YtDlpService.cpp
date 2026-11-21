#include "YtDlpService.h"

#include "app/ToolPaths.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QRegularExpression>
#include <QSettings>
#include <QStandardPaths>
#include <QTimer>

namespace {
bool traceEnabled() {
    static const bool enabled =
        qEnvironmentVariableIsSet("OCTOBEAT_TRACE_STREAM");
    return enabled;
}

void trace(const QString &message) {
    if (traceEnabled()) {
        qWarning("yt-dlp: %s", message.toUtf8().constData());
    }
}

// Kill without waiting on the UI thread. Qt's QProcess destructor waits for
// the child, which used to freeze track switches for hundreds of ms.
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

YtDlpService::YtDlpService(QObject *parent) : QObject(parent) {
    m_timeout = new QTimer(this);
    m_timeout->setSingleShot(true);
    connect(m_timeout, &QTimer::timeout, this, [this] {
        if (!m_process) {
            return;
        }
        const Mode mode = m_mode;
        if (mode == Mode::Stream && m_streamClientIndex < m_streamClients.size()) {
            qWarning("yt-dlp: stream client timed out, trying next");
            stopProcess();
            startNextStreamClient();
            return;
        }
        stopProcess();
        emit failed(mode == Mode::Search
                        ? tr("YouTube search timed out.")
                        : tr("yt-dlp did not respond in time."));
    });

    m_stallTimer = new QTimer(this);
    m_stallTimer->setSingleShot(true);
    m_stallTimer->setInterval(45000);
    connect(m_stallTimer, &QTimer::timeout, this, [this] {
        if (!m_process || m_mode != Mode::Download) {
            return;
        }
        stopProcess();
        emit failed(tr("Download stalled: no data for 45 seconds."));
    });
}

YtDlpService::~YtDlpService() {
    stopProcess();
}

QString YtDlpService::executable() const {
    return ToolPaths::executable(QStringLiteral("yt-dlp"));
}

QStringList YtDlpService::commonArgs(const QString &cookiesPath,
                                     bool jsRuntime) const {
    QStringList args;
    // Do not force web_safari,tv here: those clients expose only muxed HLS
    // formats for many videos, which made the downloader save a full video.
    // yt-dlp's default clients provide audio-only formats.
    args << QStringLiteral("--no-color")
         // Many CFR networks have a broken IPv6 route to googlevideo while
         // IPv4 works; yt-dlp otherwise spends minutes timing out on IPv6.
         << QStringLiteral("--force-ipv4");
    if (jsRuntime) {
        args << QStringLiteral("--js-runtimes") << QStringLiteral("deno");
    } else {
        // android_music exposes a direct HLS playlist without needing a JS
        // challenge. Skipping Deno cuts format extraction roughly in half.
        args << QStringLiteral("--no-js-runtimes");
    }
    if (!cookiesPath.isEmpty()) {
        args << QStringLiteral("--cookies") << cookiesPath;
    }
    return args;
}

bool YtDlpService::isBusy() const {
    return m_process && m_process->state() != QProcess::NotRunning;
}

void YtDlpService::search(const QString &query, const QString &cookiesPath) {
    const QString trimmed = query.trimmed();
    if (trimmed.isEmpty()) {
        emit failed(tr("Enter a search query."));
        return;
    }
    QStringList args = commonArgs(cookiesPath);
    args << QStringLiteral("--flat-playlist")
         << QStringLiteral("--dump-single-json")
         << QStringLiteral("--no-warnings")
         << QStringLiteral("--no-playlist")
         << QStringLiteral("--socket-timeout") << QStringLiteral("8")
         << QStringLiteral("--retries") << QStringLiteral("1")
         << QStringLiteral("ytsearch8:") + trimmed;
    start(Mode::Search, args);
}

void YtDlpService::download(const QString &url,
                            const QString &outputDir,
                            const QString &cookiesPath) {
    if (url.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    m_downloadUrl = url;
    m_downloadDir = outputDir;
    m_downloadCookies = cookiesPath;
    m_downloadEmbedded = true;
    startDownloadAttempt(true);
}

void YtDlpService::startDownloadAttempt(bool embed) {
    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    const bool mp3 = settings.value(QStringLiteral("youtube_download_mode"),
                                    QStringLiteral("native"))
                         .toString() == QStringLiteral("mp3");

    QStringList args = commonArgs(m_downloadCookies);
    args << QStringLiteral("--no-playlist")
         << QStringLiteral("--newline")
         << QStringLiteral("--no-warnings")
         << QStringLiteral("--retries") << QStringLiteral("4")
         << QStringLiteral("--fragment-retries") << QStringLiteral("4")
         << QStringLiteral("--retry-sleep") << QStringLiteral("1")
         << QStringLiteral("--embed-metadata");
    if (mp3) {
        args << QStringLiteral("-f") << QStringLiteral("bestaudio/best")
             << QStringLiteral("--extract-audio")
             << QStringLiteral("--audio-format") << QStringLiteral("mp3")
             << QStringLiteral("--audio-quality") << QStringLiteral("320K");
    } else {
        args << QStringLiteral("-f")
             << QStringLiteral("bestaudio[ext=m4a]/bestaudio[ext=opus]/bestaudio");
    }
    if (embed) {
        args << QStringLiteral("--embed-thumbnail")
             << QStringLiteral("--convert-thumbnails") << QStringLiteral("jpg");
    }
    args << QStringLiteral("--print") << QStringLiteral("after_move:filepath")
         << QStringLiteral("-o")
         << (m_downloadDir + QStringLiteral("/%(title)s.%(ext)s"))
         << m_downloadUrl;
    start(Mode::Download, args);
}

void YtDlpService::startNextStreamClient() {
    if (m_streamClientIndex >= m_streamClients.size()) {
        emit failed(tr("Could not resolve the stream."));
        return;
    }
    const QString client = m_streamClients.at(m_streamClientIndex++);
    m_streamAttempt = client == QStringLiteral("android_music")
                          ? StreamAttempt::AudioHls
                          : StreamAttempt::EmbeddedHls;
    qWarning("yt-dlp: stream client=%s attempt=%d",
             client.toUtf8().constData(), m_streamClientIndex);

    QStringList args = commonArgs(
        m_streamCookies, client != QStringLiteral("android_music"));
    args << QStringLiteral("--extractor-args")
         << (QStringLiteral("youtube:player_client=") + client)
         << QStringLiteral("-g")
         << QStringLiteral("--print") << QStringLiteral("%(duration)s")
         << QStringLiteral("-f")
         << QStringLiteral("234/233/bestaudio/best")
         << QStringLiteral("--no-playlist")
         << QStringLiteral("--no-warnings")
         << QStringLiteral("--socket-timeout") << QStringLiteral("8")
         << QStringLiteral("--retries") << QStringLiteral("1")
         << m_streamUrl;
    start(Mode::Stream, args);
}

void YtDlpService::resolveAudioHls(const QString &url,
                                   const QString &cookiesPath) {
    if (url.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    m_streamUrl = url;
    m_streamCookies = cookiesPath;
    m_downloadCookies = cookiesPath;
    m_streamClients = {QStringLiteral("android_music"),
                       QStringLiteral("web_embedded"),
                       QStringLiteral("tv")};
    m_streamClientIndex = 0;
    startNextStreamClient();
}

void YtDlpService::resolveStream(const QString &url, const QString &cookiesPath) {
    if (url.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    m_streamUrl = url;
    m_streamCookies = cookiesPath;
    m_downloadCookies = cookiesPath;
    m_streamClients = {QStringLiteral("web_embedded")};
    m_streamClientIndex = 0;
    startNextStreamClient();
}

void YtDlpService::downloadForStream(const QString &url,
                                     const QString &outputDir,
                                     const QString &cookiesPath) {
    if (url.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    m_downloadUrl = url;
    m_downloadDir = outputDir;
    m_downloadCookies = cookiesPath;
    m_downloadEmbedded = false;

    QStringList args = commonArgs(cookiesPath);
    args << QStringLiteral("-f")
         << QStringLiteral("bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio")
         << QStringLiteral("--no-playlist")
         << QStringLiteral("--newline")
         << QStringLiteral("--no-warnings")
         << QStringLiteral("--retries") << QStringLiteral("4")
         << QStringLiteral("--fragment-retries") << QStringLiteral("4")
         << QStringLiteral("--retry-sleep") << QStringLiteral("1")
         << QStringLiteral("--concurrent-fragments") << QStringLiteral("4")
         << QStringLiteral("--print") << QStringLiteral("after_move:filepath")
         << QStringLiteral("-o")
         << (outputDir + QStringLiteral("/%(title)s.%(ext)s"))
         << url;
    start(Mode::Download, args);
}

void YtDlpService::cacheStream(const QString &url,
                               const QString &cacheDir,
                               const QString &key,
                               const QString &cookiesPath) {
    if (url.isEmpty() || key.isEmpty()) {
        emit failed(tr("No track selected."));
        return;
    }
    if (!QDir().mkpath(cacheDir)) {
        emit failed(tr("Could not create the stream cache folder."));
        return;
    }
    m_downloadUrl = url;
    m_downloadDir = cacheDir;
    m_downloadCookies = cookiesPath;
    m_downloadEmbedded = false;

    QStringList args = commonArgs(cookiesPath);
    args << QStringLiteral("-f")
         << QStringLiteral("bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio")
         << QStringLiteral("--no-playlist")
         << QStringLiteral("--newline")
         << QStringLiteral("--no-warnings")
         << QStringLiteral("--retries") << QStringLiteral("4")
         << QStringLiteral("--fragment-retries") << QStringLiteral("4")
         << QStringLiteral("--retry-sleep") << QStringLiteral("1")
         << QStringLiteral("--concurrent-fragments") << QStringLiteral("2")
         << QStringLiteral("--print") << QStringLiteral("after_move:filepath")
         << QStringLiteral("-o")
         << (cacheDir + QLatin1Char('/') + key + QStringLiteral(".%(ext)s"))
         << url;
    trace(QStringLiteral("cacheStream key=%1").arg(key));
    start(Mode::Download, args);
}

void YtDlpService::cancel() {
    if (!m_process) {
        return;
    }
    stopProcess();
    emit canceled();
}

void YtDlpService::stopProcess() {
    if (m_timeout) {
        m_timeout->stop();
    }
    if (m_stallTimer) {
        m_stallTimer->stop();
    }
    trace(QStringLiteral("stopProcess mode=%1").arg(static_cast<int>(m_mode)));
    m_mode = Mode::None;
    if (!m_process) {
        return;
    }
    QProcess *process = m_process;
    m_process = nullptr;
    retireProcess(process);
}

void YtDlpService::armTimeout(int milliseconds) {
    if (m_timeout) {
        m_timeout->start(milliseconds);
    }
}

void YtDlpService::start(Mode mode, const QStringList &args) {
    stopProcess();

    const QString program = executable();
    if (program.isEmpty()) {
        emit failed(tr("yt-dlp was not found in PATH."));
        return;
    }

    qWarning("yt-dlp: start mode=%d", static_cast<int>(mode));
    m_mode = mode;
    m_output.clear();
    m_lastError.clear();

    m_process = new QProcess(this);
    m_process->setProgram(program);
    m_process->setArguments(args);
    m_process->setProcessEnvironment(ToolPaths::processEnvironment());
    m_process->setProcessChannelMode(QProcess::MergedChannels);

    connect(m_process, &QProcess::readyReadStandardOutput,
            this, &YtDlpService::handleOutput);
    connect(m_process, &QProcess::finished,
            this, &YtDlpService::handleFinished);
    connect(m_process, &QProcess::errorOccurred,
            this, &YtDlpService::handleError);

    m_process->start();
    if (mode == Mode::Search) {
        armTimeout(15000);
    } else if (mode == Mode::Stream) {
        armTimeout(12000);
    } else if (mode == Mode::Download && m_stallTimer) {
        m_stallTimer->start();
    }
}

void YtDlpService::handleOutput() {
    if (!m_process) {
        return;
    }
    const QString chunk = QString::fromUtf8(m_process->readAllStandardOutput());
    m_output += chunk;

    if (m_mode == Mode::Download) {
        if (!chunk.isEmpty() && m_stallTimer) {
            m_stallTimer->start();
        }
        static const QRegularExpression percentRe(
            QStringLiteral("(\\d+(?:\\.\\d+)?)%"));
        const auto matches = percentRe.globalMatch(chunk);
        auto match = matches;
        int last = -1;
        while (match.hasNext()) {
            last = qBound(0, static_cast<int>(match.next().captured(1).toDouble()), 100);
        }
        if (last >= 0) {
            emit downloadProgress(last);
        }
    }
}

QString YtDlpService::cleanOutput(const QString &text) {
    QStringList lines;
    for (const QString &line : text.split(QLatin1Char('\n'))) {
        const QString trimmed = line.trimmed();
        if (!trimmed.isEmpty()) {
            lines.push_back(trimmed);
        }
    }
    while (lines.size() > 14) {
        lines.removeFirst();
    }
    return lines.join(QLatin1Char('\n'));
}

void YtDlpService::handleFinished(int exitCode, QProcess::ExitStatus exitStatus) {
    Q_UNUSED(exitStatus);
    if (m_timeout) {
        m_timeout->stop();
    }
    if (m_stallTimer) {
        m_stallTimer->stop();
    }
    const Mode mode = m_mode;
    m_mode = Mode::None;
    if (m_process) {
        m_process->deleteLater();
        m_process = nullptr;
    }

    if (mode == Mode::Search) {
        const int start = m_output.indexOf(QLatin1Char('{'));
        const int end = m_output.lastIndexOf(QLatin1Char('}'));
        if (exitCode != 0 || start < 0 || end < start) {
            m_lastError = cleanOutput(m_output);
            qWarning("yt-dlp: search failed exit=%d: %s", exitCode,
                     m_lastError.toUtf8().constData());
            emit failed(m_lastError.isEmpty() ? tr("YouTube search failed.") : m_lastError);
            return;
        }
        const QByteArray json = m_output.mid(start, end - start + 1).toUtf8();
        const QJsonDocument document = QJsonDocument::fromJson(json);
        if (!document.isObject()) {
            emit failed(tr("Could not parse the YouTube search result."));
            return;
        }
        QJsonArray entries = document.object().value(QStringLiteral("entries")).toArray();
        QVector<SearchResult> results;
        results.reserve(entries.size());
        for (const QJsonValue &value : entries) {
            if (!value.isObject()) {
                continue;
            }
            const QJsonObject object = value.toObject();
            SearchResult result;
            result.id = object.value(QStringLiteral("id")).toString();
            result.title = object.value(QStringLiteral("title")).toString();
            result.uploader = object.value(QStringLiteral("uploader")).toString();
            if (result.uploader.isEmpty()) {
                result.uploader = object.value(QStringLiteral("channel")).toString();
            }
            result.url = object.value(QStringLiteral("webpage_url")).toString();
            if (result.url.isEmpty() && !result.id.isEmpty()) {
                result.url = QStringLiteral("https://www.youtube.com/watch?v=") + result.id;
            }
            result.thumbnail = object.value(QStringLiteral("thumbnail")).toString();
            if (result.thumbnail.isEmpty() && !result.id.isEmpty()) {
                result.thumbnail =
                    QStringLiteral("https://i.ytimg.com/vi/") + result.id +
                    QStringLiteral("/mqdefault.jpg");
            }
            result.duration = static_cast<qint64>(
                object.value(QStringLiteral("duration")).toDouble());
            if (!result.title.isEmpty() && !result.url.isEmpty()) {
                results.push_back(result);
            }
        }
        emit searchFinished(results);
        return;
    }

    if (mode == Mode::Download) {
        trace(QStringLiteral("download finished exit=%1 file=%2").arg(exitCode).arg(m_output.right(300)));
        if (exitCode != 0) {
            m_lastError = cleanOutput(m_output);
            qWarning("yt-dlp: download failed exit=%d: %s", exitCode,
                     m_lastError.toUtf8().constData());
            const QString lower = m_lastError.toLower();
            if (m_downloadEmbedded &&
                (lower.contains(QStringLiteral("thumbnail")) ||
                 lower.contains(QStringLiteral("embed")) ||
                 lower.contains(QStringLiteral("postprocess")) ||
                 lower.contains(QStringLiteral("ffmpeg")))) {
                m_downloadEmbedded = false;
                QTimer::singleShot(0, this, [this] { startDownloadAttempt(false); });
                return;
            }
            emit failed(m_lastError.isEmpty() ? tr("Download failed.") : m_lastError);
            return;
        }
        QString path;
        const QStringList lines = m_output.split(QLatin1Char('\n'));
        for (auto it = lines.crbegin(); it != lines.crend(); ++it) {
            const QString candidate = it->trimmed();
            if (candidate.startsWith(QLatin1Char('/')) &&
                QFileInfo::exists(candidate)) {
                path = candidate;
                break;
            }
        }
        if (path.isEmpty()) {
            emit failed(tr("Download finished, but the output file was not found."));
            return;
        }
        emit downloadProgress(100);
        emit downloadFinished(path);
        return;
    }

    if (mode == Mode::Stream) {
        QString url;
        int durationSeconds = -1;
        if (exitCode == 0) {
            const QStringList lines = m_output.split(QLatin1Char('\n'));
            for (auto it = lines.crbegin(); it != lines.crend(); ++it) {
                const QString candidate = it->trimmed();
                if (candidate.startsWith(QStringLiteral("http://")) ||
                    candidate.startsWith(QStringLiteral("https://"))) {
                    url = candidate;
                    break;
                }
            }
            for (const QString &line : lines) {
                bool ok = false;
                const double value = line.trimmed().toDouble(&ok);
                if (ok && value > 0) {
                    durationSeconds = qRound(value);
                    break;
                }
            }
        }
        if (url.isEmpty()) {
            m_lastError = cleanOutput(m_output);
            qWarning("yt-dlp: stream resolve failed exit=%d: %s", exitCode,
                     m_lastError.toUtf8().constData());
            if (m_streamClientIndex < m_streamClients.size()) {
                QTimer::singleShot(0, this,
                                   &YtDlpService::startNextStreamClient);
                return;
            }
            emit failed(m_lastError.isEmpty() ? tr("Could not resolve the stream.")
                                             : m_lastError);
            return;
        }
        m_streamAttempt = StreamAttempt::None;
        emit streamResolved(url, QString(), QString(), durationSeconds);
    }
}

void YtDlpService::handleError() {
    if (!m_process) {
        return;
    }
    if (m_timeout) {
        m_timeout->stop();
    }
    if (m_stallTimer) {
        m_stallTimer->stop();
    }
    m_mode = Mode::None;
    m_lastError = m_process->errorString();
    qWarning("yt-dlp: process error: %s", m_lastError.toUtf8().constData());
    trace(QStringLiteral("process error: %1").arg(m_lastError));
    m_process->deleteLater();
    m_process = nullptr;
    emit failed(m_lastError);
}
