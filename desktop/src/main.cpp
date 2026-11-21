#include <QApplication>
#include <QCryptographicHash>
#include <QCommandLineParser>
#include <QDateTime>
#include <QGuiApplication>
#include <QDir>
#include <QFile>
#include <QIcon>
#include <QLocalServer>
#include <QLocalSocket>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFileInfo>
#include <QMessageBox>
#include <QMutex>
#include <QScreen>
#include <QSettings>
#include <QStandardPaths>
#include <QThread>
#include <QTimer>

#include <cstdio>
#include <cstdlib>

#include "app/MainWindow.h"
#include "app/ResourcePaths.h"
#include "app/Theme.h"
#include "app/Translations.h"
#include "core/CoreClient.h"
#include "downloads/CsvImportDialog.h"
#include "downloads/FastStreamService.h"
#include "downloads/YouTubeSearchService.h"
#include "downloads/YtDlpService.h"
#include "audio/AudioEngine.h"

namespace {

QMutex g_logMutex;
QString g_logPath;

void logMessageHandler(QtMsgType type,
                       const QMessageLogContext &,
                       const QString &message) {
    const char *level = "INFO";
    switch (type) {
    case QtDebugMsg:
        level = "DEBUG";
        break;
    case QtInfoMsg:
        level = "INFO";
        break;
    case QtWarningMsg:
        level = "WARN";
        break;
    case QtCriticalMsg:
        level = "ERROR";
        break;
    case QtFatalMsg:
        level = "FATAL";
        break;
    }
    const QString line = QStringLiteral("%1 [%2] %3\n")
                             .arg(QDateTime::currentDateTime()
                                      .toString(Qt::ISODateWithMs),
                                  QString::fromLatin1(level), message);
    const QByteArray utf8 = line.toUtf8();
    {
        QMutexLocker locker(&g_logMutex);
        if (!g_logPath.isEmpty()) {
            QFile file(g_logPath);
            if (file.open(QIODevice::WriteOnly | QIODevice::Append)) {
                file.write(utf8);
            }
        }
    }
#ifndef Q_OS_WIN
    std::fwrite(utf8.constData(), 1, static_cast<size_t>(utf8.size()), stderr);
    std::fflush(stderr);
#endif
    if (type == QtFatalMsg) {
        std::abort();
    }
}

void installLogging(const QString &dataDir) {
    QDir().mkpath(dataDir);
    g_logPath = QDir(dataDir).filePath(QStringLiteral("octobeat.log"));
    const QFileInfo info(g_logPath);
    if (info.size() > 8LL * 1024 * 1024) {
        const QString previous = g_logPath + QStringLiteral(".1");
        QFile::remove(previous);
        QFile::rename(g_logPath, previous);
    }
    qInstallMessageHandler(logMessageHandler);
}

QString defaultDataDir() {
    const QString base =
        QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation);
    if (base.isEmpty()) {
        return QDir::homePath() + QStringLiteral("/.local/share/OctoBeat");
    }
    return QDir(base).filePath(QStringLiteral("OctoBeat"));
}

QString defaultCacheDir() {
    const QString base =
        QStandardPaths::writableLocation(QStandardPaths::GenericCacheLocation);
    if (base.isEmpty()) {
        return QDir::homePath() + QStringLiteral("/.cache/OctoBeat");
    }
    return QDir(base).filePath(QStringLiteral("OctoBeat"));
}

QString defaultMusicDir() {
    QString path = QStandardPaths::writableLocation(QStandardPaths::MusicLocation);
    if (path.isEmpty()) {
        path = QDir::homePath() + QStringLiteral("/Music");
    }
    return path;
}

QString singleInstanceName(const QString &dataDir) {
    const QByteArray digest = QCryptographicHash::hash(
        dataDir.toUtf8(), QCryptographicHash::Sha1);
    return QStringLiteral("octobeat-") + QString::fromLatin1(digest.toHex().left(16));
}

// QT_SCALE_FACTOR must be in the environment before QApplication exists, so
// --config-dir has to be found without the command line parser.
QString configDirFromArgs(int argc, char *argv[]) {
    for (int i = 1; i < argc; ++i) {
        const QString arg = QString::fromLocal8Bit(argv[i]);
        if (arg == QStringLiteral("--config-dir") && i + 1 < argc) {
            return QString::fromLocal8Bit(argv[i + 1]);
        }
        if (arg.startsWith(QStringLiteral("--config-dir="))) {
            return arg.mid(QStringLiteral("--config-dir=").size());
        }
    }
    return {};
}

void applyConfiguredZoom() {
    QSettings settings(QSettings::NativeFormat, QSettings::UserScope,
                       QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    int zoom = settings.value(QStringLiteral("zoom"), 125).toInt();
    if (zoom <= 0) {
        zoom = 125;
    }
    // One-time migration: the old Rust build silently ignored zoom and the
    // interface was too small on high-resolution displays.
    if (!settings.contains(QStringLiteral("zoom_default_125"))) {
        if (zoom == 100) {
            zoom = 125;
            settings.setValue(QStringLiteral("zoom"), zoom);
        }
        settings.setValue(QStringLiteral("zoom_default_125"), true);
    }
    if (zoom < 100) {
        zoom = 100;
        settings.setValue(QStringLiteral("zoom"), zoom);
    }
    if (zoom != 100) {
        qputenv("QT_SCALE_FACTOR", QByteArray::number(zoom / 100.0));
    }
}

} // namespace

int main(int argc, char *argv[]) {
    const QString earlyConfigDir = configDirFromArgs(argc, argv);
    if (!earlyConfigDir.isEmpty()) {
        QSettings::setPath(QSettings::NativeFormat, QSettings::UserScope,
                           earlyConfigDir);
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope,
                           earlyConfigDir);
    }
    applyConfiguredZoom();
    {
        QByteArray rules = qgetenv("QT_LOGGING_RULES");
        if (!rules.isEmpty()) {
            rules += ';';
        }
        rules += "qt.qpa.wayland.textinput=false";
        qputenv("QT_LOGGING_RULES", rules);
    }
    QGuiApplication::setHighDpiScaleFactorRoundingPolicy(
        Qt::HighDpiScaleFactorRoundingPolicy::PassThrough);
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("OctoBeat"));
    QApplication::setOrganizationName(QStringLiteral("MusicPlayer"));
    QApplication::setApplicationVersion(QStringLiteral("1.0.0"));
    QApplication::setStyle(QStringLiteral("Fusion"));

    QCommandLineParser parser;
    parser.setApplicationDescription(QStringLiteral("OctoBeat music player"));
    parser.addHelpOption();
    parser.addVersionOption();

    QCommandLineOption dataOption(
        QStringLiteral("data-dir"),
        QStringLiteral("Application data directory."),
        QStringLiteral("path"));
    QCommandLineOption musicOption(
        QStringLiteral("music-dir"),
        QStringLiteral("Music library directory."),
        QStringLiteral("path"));
    QCommandLineOption dbOption(
        QStringLiteral("db"),
        QStringLiteral("SQLite database path."),
        QStringLiteral("path"));
    QCommandLineOption cacheOption(
        QStringLiteral("cache-dir"),
        QStringLiteral("Cache directory."),
        QStringLiteral("path"));
    QCommandLineOption configOption(
        QStringLiteral("config-dir"),
        QStringLiteral("QSettings directory."),
        QStringLiteral("path"));
    QCommandLineOption smokeOption(
        QStringLiteral("smoke-test"),
        QStringLiteral("Open the core, print the track count and exit."));
    QCommandLineOption scanOption(
        QStringLiteral("scan"),
        QStringLiteral("Scan the music folder before opening the window."));
    QCommandLineOption screenshotOption(
        QStringLiteral("screenshot"),
        QStringLiteral("Save a window screenshot and exit."),
        QStringLiteral("path"));
    QCommandLineOption playFirstOption(
        QStringLiteral("play-first"),
        QStringLiteral("Start playing the first library track (for smoke tests)."));
    QCommandLineOption tabOption(
        QStringLiteral("tab"),
        QStringLiteral("Open tab by index (0 library, 1 playlists, 2 streaming, 3 settings, 4 profile)."),
        QStringLiteral("index"));
    QCommandLineOption smokeDownloadOption(
        QStringLiteral("smoke-download"),
        QStringLiteral("Search and download the first result, then exit."),
        QStringLiteral("query"));
    QCommandLineOption smokeStreamOption(
        QStringLiteral("smoke-stream"),
        QStringLiteral("Search and resolve a stream URL, then exit."),
        QStringLiteral("query"));
    QCommandLineOption miniOption(
        QStringLiteral("mini"),
        QStringLiteral("Open the mini-player (for smoke tests)."));
    QCommandLineOption smokePlayStreamOption(
        QStringLiteral("smoke-play-stream"),
        QStringLiteral("Resolve a stream and play it for a few seconds, then exit."),
        QStringLiteral("query"));
    QCommandLineOption smokeFastStreamOption(
        QStringLiteral("smoke-fast-stream"),
        QStringLiteral("Search, resolve HLS and play through the fast FIFO path."),
        QStringLiteral("query"));
    QCommandLineOption smokeCsvImportOption(
        QStringLiteral("smoke-csv-import"),
        QStringLiteral("Import a CSV file, scan the library and exit."),
        QStringLiteral("path"));
    QCommandLineOption playlistOption(
        QStringLiteral("playlist"),
        QStringLiteral("Open a playlist detail page by id."),
        QStringLiteral("id"));
    QCommandLineOption downloadDialogOption(
        QStringLiteral("download-dialog"),
        QStringLiteral("Open the download dialog (for screenshots)."));
    QCommandLineOption addTracksDialogOption(
        QStringLiteral("add-tracks-dialog"),
        QStringLiteral("Open the Add Tracks dialog for --playlist (for screenshots)."));
    QCommandLineOption lyricsPanelOption(
        QStringLiteral("lyrics-panel"),
        QStringLiteral("Show the lyrics panel (for screenshots)."));
    QCommandLineOption karaokeOption(
        QStringLiteral("karaoke"),
        QStringLiteral("Show the karaoke overlay (for screenshots)."));
    QCommandLineOption playTrackOption(
        QStringLiteral("play-track"),
        QStringLiteral("Play a track by id (for screenshots)."),
        QStringLiteral("id"));
    QCommandLineOption trackMenuOption(
        QStringLiteral("track-menu"),
        QStringLiteral("Open the track context menu (for screenshots)."));
    QCommandLineOption screenshotDelayOption(
        QStringLiteral("screenshot-delay"),
        QStringLiteral("Delay before taking the screenshot, in milliseconds."),
        QStringLiteral("ms"));
    QCommandLineOption demoDownloadOption(
        QStringLiteral("demo-download-search"),
        QStringLiteral("Run a download search before taking a screenshot."),
        QStringLiteral("query"));
    QCommandLineOption demoStreamingOption(
        QStringLiteral("demo-streaming-search"),
        QStringLiteral("Run a streaming search before taking a screenshot."),
        QStringLiteral("query"));
    QCommandLineOption demoStreamingPlayOption(
        QStringLiteral("demo-streaming-play"),
        QStringLiteral("Play the first streaming search result (for screenshots)."));
    QCommandLineOption demoStreamingDownloadOption(
        QStringLiteral("demo-streaming-download"),
        QStringLiteral("Download the first streaming search result (for tests)."));
    QCommandLineOption demoStreamingHoverOption(
        QStringLiteral("demo-streaming-hover"),
        QStringLiteral("Hover the first streaming result (for screenshots)."));
    QCommandLineOption demoStreamingSuggestOption(
        QStringLiteral("demo-streaming-suggest"),
        QStringLiteral("Show streaming search suggestions (for screenshots)."),
        QStringLiteral("query"));
    QCommandLineOption demoStreamingArtistOption(
        QStringLiteral("demo-streaming-artist"),
        QStringLiteral("Open a streaming artist page (for screenshots)."),
        QStringLiteral("channel-id"));
    QCommandLineOption demoStreamingPlaylistOption(
        QStringLiteral("demo-streaming-playlist"),
        QStringLiteral("Open a streaming playlist page (for screenshots)."),
        QStringLiteral("playlist-id"));
    QCommandLineOption demoStreamingFilteredSearchOption(
        QStringLiteral("demo-streaming-filtered-search"),
        QStringLiteral("Run a filtered streaming search (0=all,1=tracks,2=artists,3=playlists)."),
        QStringLiteral("query:filter"));
    QCommandLineOption demoStreamingQueueOption(
        QStringLiteral("demo-streaming-queue"),
        QStringLiteral("Fill the streaming queue and open the queue panel."),
        QStringLiteral("query"));
    QCommandLineOption demoCsvImportOption(
        QStringLiteral("demo-csv-import"),
        QStringLiteral("Open the CSV import dialog for a file."),
        QStringLiteral("path"));
    QCommandLineOption demoPlayAllOption(
        QStringLiteral("demo-play-all"),
        QStringLiteral("Start Play all on a demo artist/playlist page."));
    QCommandLineOption demoHomePlayOption(
        QStringLiteral("demo-home-play"),
        QStringLiteral("Play the first Home card (for screenshots)."));
    QCommandLineOption demoShowAllOption(
        QStringLiteral("demo-show-all"),
        QStringLiteral("Expand the demo artist discography (for screenshots)."));
    QCommandLineOption demoPlaylistCardOption(
        QStringLiteral("demo-playlist-card-play"),
        QStringLiteral("Click the first playlist card Play overlay."));

    parser.addOption(dataOption);
    parser.addOption(musicOption);
    parser.addOption(dbOption);
    parser.addOption(cacheOption);
    parser.addOption(configOption);
    parser.addOption(smokeOption);
    parser.addOption(scanOption);
    parser.addOption(screenshotOption);
    parser.addOption(playFirstOption);
    parser.addOption(tabOption);
    parser.addOption(smokeDownloadOption);
    parser.addOption(smokeStreamOption);
    parser.addOption(miniOption);
    parser.addOption(smokePlayStreamOption);
    parser.addOption(smokeFastStreamOption);
    parser.addOption(smokeCsvImportOption);
    parser.addOption(playlistOption);
    parser.addOption(downloadDialogOption);
    parser.addOption(addTracksDialogOption);
    parser.addOption(lyricsPanelOption);
    parser.addOption(karaokeOption);
    parser.addOption(playTrackOption);
    parser.addOption(trackMenuOption);
    parser.addOption(screenshotDelayOption);
    parser.addOption(demoDownloadOption);
    parser.addOption(demoStreamingOption);
    parser.addOption(demoStreamingPlayOption);
    parser.addOption(demoStreamingDownloadOption);
    parser.addOption(demoStreamingHoverOption);
    parser.addOption(demoStreamingSuggestOption);
    parser.addOption(demoStreamingArtistOption);
    parser.addOption(demoStreamingPlaylistOption);
    parser.addOption(demoStreamingFilteredSearchOption);
    parser.addOption(demoStreamingQueueOption);
    parser.addOption(demoCsvImportOption);
    parser.addOption(demoPlayAllOption);
    parser.addOption(demoHomePlayOption);
    parser.addOption(demoShowAllOption);
    parser.addOption(demoPlaylistCardOption);
    parser.process(app);

    if (parser.isSet(configOption)) {
        QSettings::setPath(QSettings::NativeFormat, QSettings::UserScope,
                           parser.value(configOption));
        QSettings::setPath(QSettings::IniFormat, QSettings::UserScope,
                           parser.value(configOption));
    }

    const QString dataDir = parser.isSet(dataOption) ? parser.value(dataOption)
                                                       : defaultDataDir();
    const QString musicDir =
        parser.isSet(musicOption)
            ? parser.value(musicOption)
            : QSettings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"))
                  .value(QStringLiteral("download_dir"), defaultMusicDir())
                  .toString();
    const QString dbPath = parser.isSet(dbOption)
                               ? parser.value(dbOption)
                               : QDir(dataDir).filePath(QStringLiteral("music.db"));
    const QString cacheDir = parser.isSet(cacheOption)
                                 ? parser.value(cacheOption)
                                 : defaultCacheDir();

    QDir().mkpath(dataDir);
    QDir().mkpath(cacheDir);
    installLogging(dataDir);

    // Keep the pre-port database safe. Only the first launch creates this
    // snapshot; later launches keep the original backup.
    const QString backupPath = dbPath + QStringLiteral(".backup");
    if (QFileInfo(dbPath).isFile() && !QFileInfo(backupPath).exists()) {
        QFile::copy(dbPath, backupPath);
    }

    CoreClient core;
    if (!core.open(dataDir, dbPath, musicDir, cacheDir)) {
        QMessageBox::critical(nullptr, QObject::tr("OctoBeat"),
                              QObject::tr("Could not initialise the Rust core."));
        return 1;
    }

    if (parser.isSet(scanOption)) {
        if (!core.scan()) {
            std::fprintf(stderr, "scan failed\n");
        }
    }

    if (parser.isSet(smokeFastStreamOption)) {
        QElapsedTimer timer;
        timer.start();
        YouTubeSearchService search;
        YtDlpService ytdlp;
        FastStreamService fast;
        AudioEngine engine;
        QEventLoop loop;
        SearchResult pending;
        QString streamDir = QDir(QDir::tempPath())
                                .filePath(QStringLiteral("octobeat-stream-smoke"));
        QDir(streamDir).removeRecursively();
        QDir().mkpath(streamDir);
        QTimer timeout;
        timeout.setSingleShot(true);
        timeout.setInterval(90000);
        QObject::connect(&timeout, &QTimer::timeout, &loop, [&] {
            std::fprintf(stderr, "smoke-fast: timeout\n");
            loop.quit();
        });
        QObject::connect(&search, &YouTubeSearchService::failed, &loop,
                         [&](const QString &message) {
                             std::fprintf(stderr, "smoke-fast: search error: %s\n",
                                          message.toUtf8().constData());
                             loop.quit();
                         });
        QObject::connect(&search, &YouTubeSearchService::finished, &loop,
                         [&](const QVector<SearchResult> &results) {
                             if (results.isEmpty()) {
                                 std::fprintf(stderr, "smoke-fast: no results\n");
                                 loop.quit();
                                 return;
                             }
                             pending = results.first();
                             std::fprintf(stderr,
                                          "smoke-fast: search %lld ms: %s\n",
                                          static_cast<long long>(timer.elapsed()),
                                          pending.title.toUtf8().constData());
                             ytdlp.resolveAudioHls(pending.url);
                         });
        QObject::connect(&ytdlp, &YtDlpService::failed, &loop,
                         [&](const QString &message) {
                             std::fprintf(stderr, "smoke-fast: resolve error: %s\n",
                                          message.toUtf8().constData());
                             loop.quit();
                         });
        QObject::connect(&ytdlp, &YtDlpService::streamResolved, &loop,
                         [&](const QString &url, const QString &, const QString &) {
                             std::fprintf(stderr,
                                          "smoke-fast: resolved %lld ms (hls=%d)\n",
                                          static_cast<long long>(timer.elapsed()),
                                          url.contains(QStringLiteral("m3u8")) ? 1 : 0);
                             fast.start(url, streamDir, QStringLiteral("smoke"),
                                        static_cast<int>(pending.duration));
                         });
        QObject::connect(&fast, &FastStreamService::failed, &loop,
                         [&](const QString &message) {
                             std::fprintf(stderr, "smoke-fast: ffmpeg error: %s\n",
                                          message.toUtf8().constData());
                             loop.quit();
                         });
        QObject::connect(&fast, &FastStreamService::ready, &loop,
                         [&](const QString &path, int) {
                             std::fprintf(stderr,
                                          "smoke-fast: ready %lld ms (%s)\n",
                                          static_cast<long long>(timer.elapsed()),
                                          path.toUtf8().constData());
                             engine.playFile(path);
                             QTimer::singleShot(8000, &loop, [&] {
                                 std::fprintf(stderr,
                                              "smoke-fast: playing=%d\n",
                                              engine.isPlaying() ? 1 : 0);
                                 engine.stop();
                                 loop.quit();
                             });
                         });
        QObject::connect(&engine, &AudioEngine::errorOccurred, &loop,
                         [&](const QString &message) {
                             std::fprintf(stderr, "smoke-fast: audio error: %s\n",
                                          message.toUtf8().constData());
                         });
        timeout.start();
        search.search(parser.value(smokeFastStreamOption),
                      YouTubeSearchService::Filter::Tracks, 8);
        loop.exec();
        fast.stop();
        QDir(streamDir).removeRecursively();
        return 0;
    }

    const bool smokeDownload = parser.isSet(smokeDownloadOption);
    const bool smokeStream = parser.isSet(smokeStreamOption) ||
                             parser.isSet(smokePlayStreamOption);
    const bool smokePlayStream = parser.isSet(smokePlayStreamOption);
    if (smokeDownload || smokeStream) {
        QString cookies;
        for (const QString &candidate : {
                 QDir(dataDir).filePath(QStringLiteral("cookies.txt")),
                 QDir(musicDir).filePath(QStringLiteral("cookies.txt"))}) {
            if (QFileInfo(candidate).isFile()) {
                cookies = candidate;
                break;
            }
        }

        YtDlpService service;
        FastStreamService fast;
        const QString streamDir =
            QDir(QDir::tempPath()).filePath(QStringLiteral("octobeat-stream-smoke"));
        QEventLoop loop;
        AudioEngine streamEngine;
        QObject::connect(&streamEngine, &AudioEngine::errorOccurred, &loop,
                         [](const QString &message) {
                             std::fprintf(stderr, "smoke: audio error: %s\n",
                                          message.toUtf8().constData());
                         });
        QObject::connect(&fast, &FastStreamService::failed, &loop,
                         [](const QString &message) {
                             std::fprintf(stderr, "smoke: stream error: %s\n",
                                          message.toUtf8().constData());
                         });
        QObject::connect(&fast, &FastStreamService::ready, &loop,
                         [&](const QString &path, int) {
                             streamEngine.playFile(path);
                         });
        QTimer timeout;
        timeout.setSingleShot(true);
        timeout.setInterval(180000);
        QObject::connect(&timeout, &QTimer::timeout, &loop, [&] {
            std::fprintf(stderr, "smoke: timeout\n");
            loop.quit();
        });
        QObject::connect(&service, &YtDlpService::failed, &loop,
                         [&](const QString &message) {
                             std::fprintf(stderr, "smoke: error: %s\n",
                                          message.toUtf8().constData());
                             loop.quit();
                         });
        QObject::connect(&service, &YtDlpService::searchFinished, &loop,
                         [&](const QVector<SearchResult> &results) {
                             if (results.isEmpty()) {
                                 std::fprintf(stderr, "smoke: no results\n");
                                 loop.quit();
                                 return;
                             }
                             std::fprintf(stderr, "smoke: first result: %s (%s)\n",
                                          results.first().title.toUtf8().constData(),
                                          results.first().url.toUtf8().constData());
                             if (smokeDownload) {
                                 service.download(results.first().url, musicDir, cookies);
                             } else if (smokePlayStream) {
                                 service.resolveAudioHls(results.first().url, cookies);
                             } else {
                                 service.resolveStream(results.first().url, cookies);
                             }
                         });
        QObject::connect(&service, &YtDlpService::downloadFinished, &loop,
                         [&](const QString &path) {
                             std::fprintf(stderr, "smoke: downloaded: %s\n",
                                          path.toUtf8().constData());
                             loop.quit();
                         });
        QObject::connect(&service, &YtDlpService::streamResolved, &loop,
                         [&](const QString &url, const QString &, const QString &,
                             int durationSeconds) {
                             std::fprintf(stderr, "smoke: stream: %s\n",
                                          url.toUtf8().constData());
                             if (smokePlayStream) {
                                 fast.start(url, streamDir,
                                            QStringLiteral("smoke-play"),
                                            durationSeconds);
                                 QTimer::singleShot(15000, &loop, [&] {
                                     std::fprintf(stderr, "smoke: playing=%d\n",
                                                  streamEngine.isPlaying() ? 1 : 0);
                                     streamEngine.stop();
                                     fast.stop();
                                     QDir(streamDir).removeRecursively();
                                     loop.quit();
                                 });
                             } else {
                                 loop.quit();
                             }
                         });
        timeout.start();
        service.search(parser.value(smokeDownload ? smokeDownloadOption
                                                   : (smokePlayStream
                                                          ? smokePlayStreamOption
                                                          : smokeStreamOption)),
                       cookies);
        loop.exec();
        return 0;
    }

    if (parser.isSet(smokeOption)) {
        const QVector<Track> tracks = core.tracks();
        std::printf("tracks=%d\n", static_cast<int>(tracks.size()));
        if (!tracks.isEmpty()) {
            const Track &first = tracks.first();
            std::printf("first=%lld\t%s\t%s\n",
                        static_cast<long long>(first.id),
                        first.title.toUtf8().constData(),
                        first.artist.toUtf8().constData());
        }
        return 0;
    }

    if (parser.isSet(smokeCsvImportOption)) {
        auto *dialog = new CsvImportDialog(
            parser.value(smokeCsvImportOption), musicDir, dataDir);
        dialog->setAttribute(Qt::WA_DeleteOnClose);
        QObject::connect(dialog, &CsvImportDialog::finished, &app,
                         [&core, &app](int added, int failed) {
                             const bool scanned = core.scan();
                             std::printf(
                                 "smoke-csv: added=%d failed=%d scan=%d "
                                 "tracks=%d\n",
                                 added, failed, scanned ? 1 : 0,
                                 static_cast<int>(core.tracks().size()));
                             app.quit();
                         });
        dialog->show();
        dialog->start();
        return app.exec();
    }

    const QString serverName = singleInstanceName(dataDir);
    if (!parser.isSet(screenshotOption)) {
        for (int attempt = 0; attempt < 8; ++attempt) {
            QLocalSocket socket;
            socket.connectToServer(serverName);
            if (socket.waitForConnected(120)) {
                socket.write("show");
                socket.waitForBytesWritten(120);
                return 0;
            }
            QThread::msleep(60);
        }
    }

    QLocalServer::removeServer(serverName);
    QLocalServer server;
    if (!parser.isSet(screenshotOption) && !server.listen(serverName)) {
        // Another instance may have won the race between the probe and listen.
        QLocalSocket socket;
        socket.connectToServer(serverName);
        if (socket.waitForConnected(300)) {
            socket.write("show");
            socket.waitForBytesWritten(300);
            return 0;
        }
    }

    QIcon icon(ResourcePaths::file(QStringLiteral("icons/OctoBeat.svg")));
    if (!icon.isNull()) {
        QApplication::setWindowIcon(icon);
    }

    {
        QSettings languageSettings(QStringLiteral("MusicPlayer"),
                                   QStringLiteral("MusicPlayer"));
        Translations::install(&app,
                              languageSettings.value(QStringLiteral("language"),
                                                     QStringLiteral("en"))
                                  .toString());
    }

    Theme::apply(Theme::current());

    MainWindow window(&core, musicDir, dataDir);
    window.setWindowIcon(icon);
    window.setMinimumSize(800, 500);
    window.resize(1280, 820);
    window.show();
    if (parser.isSet(tabOption)) {
        bool ok = false;
        const int index = parser.value(tabOption).toInt(&ok);
        if (ok) {
            window.setTabIndex(index);
        }
    }
    QTimer::singleShot(200, &window, [&window] { window.autoScan(); });

    QObject::connect(&server, &QLocalServer::newConnection, &window, [&server, &window] {
        while (server.hasPendingConnections()) {
            QLocalSocket *client = server.nextPendingConnection();
            if (client) {
                client->readAll();
                client->disconnectFromServer();
                client->deleteLater();
            }
        }
        window.showNormal();
        window.raise();
        window.activateWindow();
    });

    if (parser.isSet(playFirstOption)) {
        QTimer::singleShot(1200, &window, [&window] { window.playFirst(); });
    }
    if (parser.isSet(playTrackOption)) {
        bool ok = false;
        const qint64 id = parser.value(playTrackOption).toLongLong(&ok);
        if (ok) {
            QTimer::singleShot(1200, &window, [&window, id] {
                window.playTrackById(id);
            });
        }
    }
    if (parser.isSet(trackMenuOption)) {
        QTimer::singleShot(1500, &window, [&window] {
            window.demoTrackContextMenu();
        });
    }
    if (parser.isSet(lyricsPanelOption)) {
        QTimer::singleShot(2600, &window, [&window] { window.demoLyricsPanel(); });
    }
    if (parser.isSet(karaokeOption)) {
        QTimer::singleShot(3200, &window, [&window] { window.demoKaraoke(); });
    }
    if (parser.isSet(miniOption)) {
        QTimer::singleShot(800, &window, [&window] { window.showMini(); });
    }
    if (parser.isSet(playlistOption)) {
        bool ok = false;
        const qint64 id = parser.value(playlistOption).toLongLong(&ok);
        if (ok) {
            QTimer::singleShot(900, &window, [&window, id] { window.openPlaylist(id); });
        }
    }
    if (parser.isSet(addTracksDialogOption)) {
        bool ok = false;
        qint64 id = parser.value(playlistOption).toLongLong(&ok);
        if (!ok) {
            id = 1;
        }
        QTimer::singleShot(1300, &window, [&window, id] {
            window.showAddTracksDialog(id);
        });
    }
    if (parser.isSet(downloadDialogOption)) {
        QTimer::singleShot(600, &window, [&window] {
            window.openDownloadDialog();
        });
    }
    if (parser.isSet(demoDownloadOption)) {
        const QString query = parser.value(demoDownloadOption);
        QTimer::singleShot(700, &window, [&window, query] {
            window.demoDownloadSearch(query);
        });
    }
    if (parser.isSet(demoStreamingOption)) {
        const QString query = parser.value(demoStreamingOption);
        QTimer::singleShot(700, &window, [&window, query] {
            window.demoStreamingSearch(query);
        });
    }
    if (parser.isSet(demoStreamingPlayOption)) {
        QTimer::singleShot(6000, &window, [&window] {
            window.demoStreamingPlay();
        });
    }
    if (parser.isSet(demoStreamingDownloadOption)) {
        QTimer::singleShot(5000, &window, [&window] {
            window.demoStreamingDownload();
        });
    }
    if (parser.isSet(demoStreamingHoverOption)) {
        QTimer::singleShot(5000, &window, [&window] {
            window.demoStreamingHover();
        });
    }
    if (parser.isSet(demoStreamingSuggestOption)) {
        const QString query = parser.value(demoStreamingSuggestOption);
        QTimer::singleShot(1500, &window, [&window, query] {
            window.demoStreamingSuggest(query);
        });
    }
    if (parser.isSet(demoStreamingArtistOption)) {
        const QString value = parser.value(demoStreamingArtistOption);
        const QString channelId = value.section(QLatin1Char('|'), 0, 0);
        const QString title = value.section(QLatin1Char('|'), 1, 1);
        QTimer::singleShot(1200, &window, [&window, channelId, title] {
            window.demoStreamingArtist(channelId,
                                       title.isEmpty()
                                           ? QStringLiteral("Neuro-sama")
                                           : title);
        });
    }
    if (parser.isSet(demoStreamingPlaylistOption)) {
        const QString value = parser.value(demoStreamingPlaylistOption);
        const QString playlistId = value.section(QLatin1Char('|'), 0, 0);
        const QString title = value.section(QLatin1Char('|'), 1, 1);
        QTimer::singleShot(1200, &window, [&window, playlistId, title] {
            window.demoStreamingPlaylist(playlistId,
                                         title.isEmpty()
                                             ? QStringLiteral("Neurotoxin")
                                             : title);
        });
    }
    if (parser.isSet(demoPlaylistCardOption)) {
        QTimer::singleShot(12000, &window, [&window] {
            window.demoPlaylistCardPlay();
        });
    }
    if (parser.isSet(demoShowAllOption)) {
        QTimer::singleShot(10000, &window, [&window] {
            window.demoShowAll();
        });
    }
    if (parser.isSet(demoHomePlayOption)) {
        QTimer::singleShot(8000, &window, [&window] {
            window.demoHomePlay();
        });
    }
    if (parser.isSet(demoPlayAllOption)) {
        QTimer::singleShot(9000, &window, [&window] {
            window.demoPlayAll();
        });
    }
    if (parser.isSet(demoCsvImportOption)) {
        const QString path = parser.value(demoCsvImportOption);
        QTimer::singleShot(700, &window, [&window, path] {
            window.importCsvFile(path);
        });
    }
    if (parser.isSet(demoStreamingQueueOption)) {
        const QString query = parser.value(demoStreamingQueueOption);
        QTimer::singleShot(1500, &window, [&window, query] {
            window.demoStreamingQueue(query);
        });
    }
    if (parser.isSet(demoStreamingFilteredSearchOption)) {
        const QString value = parser.value(demoStreamingFilteredSearchOption);
        const int split = value.lastIndexOf(QLatin1Char(':'));
        if (split > 0) {
            const QString query = value.left(split);
            const int filter = value.mid(split + 1).toInt();
            QTimer::singleShot(1200, &window, [&window, query, filter] {
                window.demoStreamingFilteredSearch(query, filter);
            });
        }
    }

    if (parser.isSet(screenshotOption)) {
        const QString path = parser.value(screenshotOption);
        int delay = (parser.isSet(demoDownloadOption) ||
                     parser.isSet(demoStreamingOption) ||
                     parser.isSet(demoStreamingPlayOption) ||
                     parser.isSet(demoStreamingDownloadOption) ||
                     parser.isSet(demoStreamingHoverOption) ||
                     parser.isSet(demoStreamingSuggestOption) ||
                     parser.isSet(demoStreamingArtistOption) ||
                     parser.isSet(demoStreamingPlaylistOption) ||
                     parser.isSet(demoStreamingFilteredSearchOption) ||
                     parser.isSet(karaokeOption) ||
                     parser.isSet(lyricsPanelOption) ||
                     parser.isSet(trackMenuOption))
                        ? 9000
                        : 1800;
        if (parser.isSet(screenshotDelayOption)) {
            bool ok = false;
            const int custom = parser.value(screenshotDelayOption).toInt(&ok);
            if (ok && custom > 0) {
                delay = custom;
            }
        }
        QTimer::singleShot(delay, &window, [&window, &app, path] {
            if (QScreen *screen = window.screen()) {
                std::fprintf(stderr,
                             "window=%dx%d hint=%dx%d minHint=%dx%d screen=%dx%d maximized=%d playing=%d\n",
                             window.width(), window.height(),
                             window.sizeHint().width(), window.sizeHint().height(),
                             window.minimumSizeHint().width(), window.minimumSizeHint().height(),
                             screen->geometry().width(), screen->geometry().height(),
                             window.isMaximized() ? 1 : 0,
                             window.isPlaying() ? 1 : 0);
            }
            QWidget *active = QApplication::activeWindow();
            if (QWidget *popup = QApplication::activePopupWidget()) {
                popup->grab().save(path);
            } else if (QWidget *modal = QApplication::activeModalWidget()) {
                modal->grab().save(path);
            } else if (active && active != &window) {
                active->grab().save(path);
            } else if (window.miniWidget() && window.miniWidget()->isVisible()) {
                window.miniWidget()->grab().save(path);
            } else {
                window.grab().save(path);
            }
            app.quit();
        });
    }

    return app.exec();
}
