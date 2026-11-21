#include "MainWindow.h"

#include <QApplication>
#include <QCloseEvent>
#include <QDir>
#include <QDirIterator>
#include <QFutureWatcher>
#include <QProgressDialog>
#include <QSet>
#include <QtConcurrent>
#include <QEvent>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QHash>
#include <QInputDialog>
#include <QLabel>
#include <QMenu>
#include <QMouseEvent>
#include <QMessageBox>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QResizeEvent>
#include <QSettings>
#include <QShortcut>
#include <QPainter>
#include <QPainterPath>
#include <QStyle>
#include <QSystemTrayIcon>
#include <QTabBar>
#include <QTabWidget>
#include <QToolButton>
#include <QUrl>
#include <QWindow>
#include <QVBoxLayout>

#include <algorithm>
#include <random>

#ifdef Q_OS_WIN
#include <windows.h>
#include <windowsx.h>
#endif

#include "CoverCache.h"
#include "IconUtils.h"
#include "downloads/CsvImportDialog.h"
#include "downloads/DownloadDialog.h"
#include "downloads/SearchCache.h"
#include "downloads/StreamCache.h"
#include "downloads/StreamingPage.h"
#include "FullscreenLyrics.h"
#include "LibraryPage.h"
#include "LocalizedMessageBox.h"
#include "LyricsPanel.h"
#include "LyricsService.h"
#include "ProfilePage.h"
#include "MiniPlayer.h"
#include "MprisService.h"
#include "PlayerBar.h"
#include "PlaylistsPage.h"
#include "SettingsPage.h"
#include "Theme.h"
#include "TitleBar.h"
#include "audio/AudioEngine.h"

namespace {

QString mprisArtUrl(const QString &coverPath) {
    if (coverPath.isEmpty()) {
        return {};
    }
    if (coverPath.startsWith(QStringLiteral("http://")) ||
        coverPath.startsWith(QStringLiteral("https://"))) {
        return coverPath;
    }
    return QUrl::fromLocalFile(coverPath).toString();
}

int countAudioFiles(const QString &directory) {
    static const QSet<QString> extensions = {
        QStringLiteral("mp3"), QStringLiteral("flac"), QStringLiteral("ogg"),
        QStringLiteral("m4a"), QStringLiteral("wav"), QStringLiteral("webm"),
        QStringLiteral("opus")};
    int count = 0;
    QDirIterator iterator(directory, QDir::Files | QDir::NoSymLinks,
                          QDirIterator::Subdirectories);
    while (iterator.hasNext()) {
        iterator.next();
        if (extensions.contains(iterator.fileInfo().suffix().toLower())) {
            ++count;
        }
    }
    return count;
}

QWidget *placeholderPage(const QString &text, QWidget *parent) {
    auto *page = new QWidget(parent);
    auto *layout = new QVBoxLayout(page);
    layout->setContentsMargins(24, 24, 24, 24);
    auto *label = new QLabel(text, page);
    label->setAlignment(Qt::AlignCenter);
    label->setObjectName(QStringLiteral("placeholderText"));
    layout->addWidget(label, 1);
    return page;
}

} // namespace

MainWindow::MainWindow(CoreClient *core,
                       const QString &musicDir,
                       const QString &dataDir,
                       QWidget *parent)
    : QMainWindow(parent),
      m_core(core),
      m_musicDir(musicDir),
      m_dataDir(dataDir) {
    setWindowTitle(QStringLiteral("OctoBeat"));
    setObjectName(QStringLiteral("mainWindow"));
    setWindowFlags(Qt::Window | Qt::FramelessWindowHint);
    setAttribute(Qt::WA_TranslucentBackground, true);
    setAttribute(Qt::WA_NoSystemBackground, false);
    setAutoFillBackground(false);
    setAttribute(Qt::WA_StyledBackground, true);
    resize(1280, 820);

    m_audio = new AudioEngine(this);
    m_mpris = new MprisService(this);
    m_lyricsService = new LyricsService(core, this);
    m_listeningTimer = new QTimer(this);
    m_listeningTimer->setInterval(1000);
    connect(m_listeningTimer, &QTimer::timeout, this,
            &MainWindow::onListeningTick);
    m_streamTimer = new QTimer(this);
    m_streamTimer->setInterval(250);
    connect(m_streamTimer, &QTimer::timeout, this,
            &MainWindow::updateStreamProgress);

    auto *root = new QWidget(this);
    root->setObjectName(QStringLiteral("mainSurface"));
    root->setAttribute(Qt::WA_StyledBackground, true);
    m_surface = root;
    auto *layout = new QVBoxLayout(root);
    m_rootLayout = layout;
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(0);

    m_titleBar = new TitleBar(root);
    layout->addWidget(m_titleBar);

    m_tabs = new QTabWidget(root);
    m_tabs->setObjectName(QStringLiteral("mainTabs"));
    m_tabs->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Expanding);
    m_library = new LibraryPage(core, m_tabs);
    m_tabs->addTab(m_library, tr("Library"));
    m_playlists = new PlaylistsPage(core, m_dataDir, m_tabs);
    m_tabs->addTab(m_playlists, tr("Playlists"));
    m_streaming = new StreamingPage(m_musicDir, m_dataDir, m_tabs);
    m_tabs->addTab(m_streaming, tr("Streaming"));
    m_settings = new SettingsPage(m_dataDir, m_musicDir, m_tabs);
    m_tabs->addTab(m_settings, tr("Settings"));
    m_profile = new ProfilePage(core, m_dataDir, m_tabs);
    m_profileIndex = m_tabs->addTab(m_profile, tr("Profile"));
    m_tabs->tabBar()->setTabVisible(m_profileIndex, false);
    layout->addWidget(m_tabs, 1);

    m_avatarButton = new QToolButton(m_tabs);
    m_avatarButton->setObjectName(QStringLiteral("avatarButton"));
    m_avatarButton->setFixedSize(34, 34);
    m_avatarButton->setIconSize(QSize(28, 28));
    m_avatarButton->setAutoRaise(true);
    m_avatarButton->setCursor(Qt::PointingHandCursor);
    m_avatarButton->setToolTip(tr("Profile"));
    m_tabs->setCornerWidget(m_avatarButton, Qt::TopRightCorner);

    m_playerBar = new PlayerBar(root);
    m_lyricsPanel = new LyricsPanel(root);
    layout->addWidget(m_lyricsPanel);
    layout->addWidget(m_playerBar);
    setCentralWidget(root);
    createResizeHandles();

    connect(m_library, &LibraryPage::playRequested, this, &MainWindow::playTrack);
    connect(m_library, &LibraryPage::scanRequested, this, [this] { scanLibrary(); });
    connect(m_library, &LibraryPage::randomRequested, this, &MainWindow::playRandom);
    connect(m_library, &LibraryPage::importFilesRequested, this,
            &MainWindow::importFiles);
    connect(m_library, &LibraryPage::contextMenuRequested, this,
            [this](const QPoint &pos, qint64 trackId,
                   const QVector<qint64> &ids) {
                showTrackContextMenu(pos, trackId, ids, false);
            });
    connect(m_library, &LibraryPage::removeTrackRequested, this,
            [this](qint64 trackId) {
                removeTracksFromLibrary({trackId});
            });
    connect(m_playlists, &PlaylistsPage::playPlaylistRequested,
            this, &MainWindow::playPlaylist);
    connect(m_playlists, &PlaylistsPage::playPlaylistTrackRequested,
            this, &MainWindow::playPlaylistTrack);
    connect(m_playlists, &PlaylistsPage::contextMenuRequested, this,
            [this](const QPoint &pos, qint64 trackId,
                   const QVector<qint64> &ids) {
                showTrackContextMenu(pos, trackId, ids, true);
            });
    connect(m_settings, &SettingsPage::themeChanged, this, [this](const QString &theme) {
        Theme::apply(theme);
        m_playerBar->applyTheme();
        if (m_library) {
            m_library->applyTheme();
        }
        if (m_playlists) {
            m_playlists->applyTheme();
        }
        if (m_settings) {
            m_settings->applyTheme();
        }
        if (m_miniPlayer) {
            m_miniPlayer->applyTheme();
        }
    });
    connect(m_settings, &SettingsPage::clearCoversRequested, this, [this] {
        if (m_core) {
            m_core->clearCovers();
            CoverCache::clear();
            loadTracks();
        }
    });
    connect(m_settings, &SettingsPage::clearCacheRequested, this, [this] {
        const auto answer = LocalizedMessageBox::question(
            this, tr("Clear ALL Cache"),
            tr("Delete all cached images and profile avatars/banners? "
               "This cannot be undone."),
            QMessageBox::Yes | QMessageBox::No, QMessageBox::No);
        if (answer != QMessageBox::Yes) {
            return;
        }
        if (m_core) {
            m_core->clearAllCache();
            CoverCache::clear();
            SearchCache::clear();
            StreamCache::clear();
            loadTracks();
        }
    });
    connect(m_settings, &SettingsPage::csvImportRequested, this,
            &MainWindow::importCsv);
    connect(m_settings, &SettingsPage::crossfadeChanged, this,
            [this](bool enabled) {
                m_crossfadeEnabled = enabled;
                if (!enabled) {
                    m_crossfadeIndex = -1;
                }
                m_audio->setCrossfadeEnabled(enabled);
            });
    connect(m_settings, &SettingsPage::musicFolderChanged, this,
            [this](const QString &path) {
                if (!m_core || path.isEmpty()) {
                    return;
                }
                const int count = countAudioFiles(path);
                if (count > 1000) {
                    const auto answer = LocalizedMessageBox::question(
                        this, tr("Scan library"),
                        tr("The selected folder contains %1 audio files. "
                           "Scanning may take a while. Continue?")
                            .arg(count));
                    if (answer != QMessageBox::Yes) {
                        if (m_settings) {
                            m_settings->setMusicFolderPath(m_musicDir);
                        }
                        return;
                    }
                }
                m_core->setMusicDir(path);
                m_musicDir = path;
                QSettings settings(QStringLiteral("MusicPlayer"),
                                   QStringLiteral("MusicPlayer"));
                settings.setValue(QStringLiteral("download_dir"), path);
                scanLibrary(false);
            });
    connect(m_streaming, &StreamingPage::streamReady,
            this, &MainWindow::playStream);
    connect(m_streaming, &StreamingPage::libraryChanged, this,
            [this] { scanLibrary(); });
    connect(m_streaming, &StreamingPage::queueChanged, this,
            [this](int size) {
                m_streamQueueSize = size;
                updateMprisCapabilities();
            });
    connect(m_streaming, &StreamingPage::streamHistoryChanged, this,
            [this](bool) { updateMprisCapabilities(); });
    connect(m_streaming, &StreamingPage::streamPreloaded, this,
            &MainWindow::handleStreamPreloaded);
    connect(m_streaming, &StreamingPage::streamPreloadCleared, this, [this] {
        m_preloadedReady = false;
        m_preloadedPath.clear();
    });
    connect(m_streaming, &StreamingPage::streamRecoveryRequested, this,
            [this] {
                m_preloadedReady = false;
                m_streamCrossfading = false;
                m_streamTimer->stop();
                if (m_audio) {
                    m_audio->stop();
                }
            });
    connect(m_streaming, &StreamingPage::streamLocalSeekRequested, this,
            [this](qint64 positionMs) {
                if (!m_streamingActive) {
                    return;
                }
                m_audio->seekTo(positionMs);
                m_streamPositionBase = qMax<qint64>(0, positionMs);
                m_streamClock.start();
                m_streamTimer->start();
                updateStreamProgress();
            });
    connect(m_streaming, &StreamingPage::streamToggleRequested, this, [this] {
        if (!m_streamingActive) {
            return;
        }
        if (m_audio->isPlaying()) {
            pauseStreaming();
        } else {
            resumeStreaming();
        }
    });
    connect(m_profile, &ProfilePage::playRequested, this, &MainWindow::playTrack);
    connect(m_profile, &ProfilePage::playlistRequested, this, &MainWindow::openPlaylist);
    connect(m_profile, &ProfilePage::avatarChanged, this, &MainWindow::refreshAvatar);
    connect(m_avatarButton, &QToolButton::clicked, this, [this] {
        if (m_profileIndex >= 0) {
            m_profile->reload();
            m_tabs->setCurrentIndex(m_profileIndex);
        }
    });
    connect(m_tabs, &QTabWidget::currentChanged, this, [this](int index) {
        if (index == m_profileIndex) {
            m_profile->reload();
        }
    });
    m_avatarButton->setContextMenuPolicy(Qt::CustomContextMenu);
    connect(m_avatarButton, &QToolButton::customContextMenuRequested, this,
            [this](const QPoint &point) {
                QMenu menu(this);
                auto *change = menu.addAction(tr("Change avatar"));
                auto *exit = menu.addAction(tr("Exit"));
                QAction *selected = menu.exec(m_avatarButton->mapToGlobal(point));
                if (selected == change) {
                    m_profile->changeAvatar();
                } else if (selected == exit) {
                    m_quitRequested = true;
                    if (m_audio) {
                        m_audio->stop();
                    }
                    qApp->quit();
                }
            });
    refreshAvatar();
    connect(m_playerBar, &PlayerBar::playPauseRequested, this, &MainWindow::togglePlay);
    connect(m_playerBar, &PlayerBar::nextRequested, this, &MainWindow::nextTrack);
    connect(m_playerBar, &PlayerBar::previousRequested, this, &MainWindow::previousTrack);
    connect(m_playerBar, &PlayerBar::seekRequested, this,
            [this](qint64 milliseconds) {
                if (m_streamingActive) {
                    m_streamCrossfading = false;
                    if (m_streaming) {
                        m_streaming->seekStream(milliseconds);
                    }
                    return;
                }
                m_crossfadeIndex = -1;
                m_audio->seekTo(milliseconds);
            });
    connect(m_playerBar, &PlayerBar::volumeChanged, this,
            &MainWindow::applyVolume);
    connect(m_playerBar, &PlayerBar::repeatModeChanged, this,
            &MainWindow::applyRepeatMode);
    connect(m_playerBar, &PlayerBar::shuffleChanged, this,
            &MainWindow::applyShuffle);
    connect(m_titleBar, &TitleBar::miniPlayerRequested, this, &MainWindow::showMiniPlayer);

    connect(m_mpris, &MprisService::raiseRequested, this, [this] {
        if (m_miniPlayer) {
            m_miniPlayer->hide();
        }
        showNormal();
        raise();
        activateWindow();
    });
    connect(m_mpris, &MprisService::quitRequested, this, [this] {
        m_quitRequested = true;
        m_mprisStopped = true;
        m_mpris->setPlaybackStatus(QStringLiteral("Stopped"));
        if (m_audio) {
            m_audio->stop();
        }
        qApp->quit();
    });
    connect(m_mpris, &MprisService::playRequested, this, [this] {
        if (!m_audio->isPlaying()) {
            togglePlay();
        }
    });
    connect(m_mpris, &MprisService::pauseRequested, this, [this] {
        if (!m_audio->isPlaying()) {
            return;
        }
        if (m_streamingActive) {
            pauseStreaming();
        } else {
            m_audio->pause();
        }
    });
    connect(m_mpris, &MprisService::playPauseRequested, this,
            &MainWindow::togglePlay);
    connect(m_mpris, &MprisService::stopRequested, this, [this] {
        m_crossfadeIndex = -1;
        m_streamCrossfading = false;
        m_preloadedReady = false;
        m_mprisStopped = true;
        m_audio->stop();
        m_mpris->setPosition(0);
        m_mpris->setPlaybackStatus(QStringLiteral("Stopped"));
        updateMprisCapabilities();
    });
    connect(m_mpris, &MprisService::nextRequested, this,
            &MainWindow::nextTrack);
    connect(m_mpris, &MprisService::previousRequested, this,
            &MainWindow::previousTrack);
    connect(m_mpris, &MprisService::seekRequested, this, [this](qint64 us) {
        if (m_streamingActive) {
            if (m_streaming) {
                m_streaming->seekStream(us / 1000);
            }
            return;
        }
        m_crossfadeIndex = -1;
        m_audio->seekTo(us / 1000);
    });
    connect(m_mpris, &MprisService::volumeChangeRequested, this,
            &MainWindow::applyVolume);
    connect(m_mpris, &MprisService::shuffleChangeRequested, this,
            &MainWindow::applyShuffle);
    connect(m_mpris, &MprisService::loopStatusChangeRequested, this,
            [this](const QString &status) {
                applyRepeatMode(status == QStringLiteral("Track")
                                    ? QStringLiteral("one")
                                    : status == QStringLiteral("Playlist")
                                          ? QStringLiteral("all")
                                          : QStringLiteral("off"));
            });

    connect(m_audio, &AudioEngine::positionChanged, this, [this](qint64 value) {
        if (m_streamingActive) {
            // FIFO streams do not expose a seekable time; the streaming
            // clock in updateStreamProgress() owns their timeline.
            return;
        }
        if (m_mpris) {
            m_mpris->setPosition(value * 1000);
        }
        m_playerBar->setPosition(value);
        if (m_miniPlayer) {
            m_miniPlayer->setPosition(value);
        }
        if (m_lyricsService) {
            m_lyricsService->setPosition(value);
        }
    });
    connect(m_audio, &AudioEngine::durationChanged, this, [this](qint64 value) {
        if (value <= 0 && m_streamDurationMs > 0) {
            value = m_streamDurationMs;
        }
        m_playerBar->setDuration(value);
        if (m_miniPlayer) {
            m_miniPlayer->setDuration(value);
        }
        if (m_mpris) {
            m_mpris->setLength(value * 1000);
        }
    });
    connect(m_audio, &AudioEngine::playingChanged, this, [this](bool playing) {
        m_playerBar->setPlaying(playing);
        if (m_miniPlayer) {
            m_miniPlayer->setPlaying(playing);
        }
        if (m_streamingActive && m_streaming) {
            m_streaming->setPlaybackPlaying(playing);
        }
        if (m_mpris) {
            m_mpris->setPlaybackStatus(
                playing ? QStringLiteral("Playing")
                        : (m_mprisStopped ? QStringLiteral("Stopped")
                                          : QStringLiteral("Paused")));
        }
        if (playing) {
            if (m_listeningTimer && !m_listeningTimer->isActive()) {
                m_listeningTimer->start();
            }
        } else {
            if (m_listeningTimer) {
                m_listeningTimer->stop();
            }
            flushListeningTime();
        }
    });
    connect(m_audio, &AudioEngine::endReached, this, [this] {
        m_crossfadeIndex = -1;
        if (m_streamingActive && m_streaming &&
            m_streaming->isTransitioning()) {
            return;
        }
        if (m_streamingActive && m_streamCrossfading) {
            return;
        }
        if (m_streamingActive && m_preloadedReady) {
            // The end arrived before the position timer switched to the
            // prepared track. Use it now instead of silently stopping.
            switchToPreloaded();
            return;
        }
        if (m_streamingActive && m_streaming) {
            const bool continues = m_streaming->setPlaybackEnded();
            qWarning("stream: end continues=%d queue=%d preloaded=%d",
                     continues ? 1 : 0, m_streamQueueSize,
                     m_preloadedReady ? 1 : 0);
            if (!continues) {
                m_streamTimer->stop();
                freezeStreamClock();
                const qint64 finalPosition =
                    m_streamDurationMs > 0 ? m_streamDurationMs
                                           : streamPositionMs();
                m_streamPositionBase = finalPosition;
                m_playerBar->setPosition(finalPosition);
                if (m_miniPlayer) {
                    m_miniPlayer->setPosition(finalPosition);
                }
                if (m_mpris) {
                    m_mpris->setPosition(finalPosition * 1000);
                }
                m_mprisStopped = true;
                if (m_mpris) {
                    m_mpris->setPlaybackStatus(QStringLiteral("Stopped"));
                }
            }
        }
        onEndReached();
    });
    connect(m_audio, &AudioEngine::aboutToFinish, this, [this] {
        prepareCrossfade();
    });
    connect(m_audio, &AudioEngine::crossfadeFinished, this,
            &MainWindow::completeCrossfade);
    connect(m_audio, &AudioEngine::errorOccurred, this, [this](const QString &message) {
        qWarning("audio: error: %s", message.toUtf8().constData());
        if (m_streamingFast) {
            m_streamingFast = false;
            m_streamingActive = false;
            ++m_streamGeneration;
            if (m_streaming) {
                m_streaming->fallbackToCache();
            }
            return;
        }
        QMessageBox::warning(this, tr("Playback error"), message);
    });

    connect(m_lyricsService, &LyricsService::contentChanged, this,
            [this](const QString &mode, const QVector<LyricsLine> &lines,
                   const QString &plain) {
                m_lyricsPanel->setContent(mode, lines, plain);
                if (m_lyricsOverlay) {
                    m_lyricsOverlay->setContent(lines, plain);
                    m_lyricsOverlay->setHighlight(
                        m_lyricsService->lineIndex(),
                        m_lyricsService->wordIndex());
                }
                if (m_karaokeOverlay) {
                    m_karaokeOverlay->setContent(lines, plain);
                    m_karaokeOverlay->setHighlight(
                        m_lyricsService->lineIndex(),
                        m_lyricsService->wordIndex());
                }
            });
    connect(m_lyricsService, &LyricsService::highlightChanged, this,
            [this](int line, int word) {
                m_lyricsPanel->setHighlight(line, word);
                if (m_lyricsOverlay) {
                    m_lyricsOverlay->setHighlight(line, word);
                }
                if (m_karaokeOverlay) {
                    m_karaokeOverlay->setHighlight(line, word);
                }
            });
    connect(m_lyricsService, &LyricsService::offsetChanged, this,
            [this](int offset) {
                if (m_lyricsOverlay) {
                    m_lyricsOverlay->setOffset(offset);
                }
                if (m_karaokeOverlay) {
                    m_karaokeOverlay->setOffset(offset);
                }
            });
    connect(m_playerBar, &PlayerBar::lyricsToggled, this, [this](bool enabled) {
        m_lyricsPanel->setVisible(enabled);
        if (enabled) {
            m_lyricsPanel->scrollToCurrent();
        }
    });
    connect(m_playerBar, &PlayerBar::karaokeRequested, this,
            &MainWindow::showKaraoke);
    connect(m_lyricsPanel, &LyricsPanel::offsetRequested, m_lyricsService,
            &LyricsService::adjustOffset);
    connect(m_lyricsPanel, &LyricsPanel::karaokeRequested, this,
            &MainWindow::showKaraoke);
    connect(m_lyricsPanel, &LyricsPanel::fullscreenRequested, this,
            &MainWindow::showLyricsOverlay);

    auto *searchShortcut = new QShortcut(QKeySequence::Find, this);
    connect(searchShortcut, &QShortcut::activated, this, &MainWindow::focusSearch);
    auto *playShortcut = new QShortcut(QKeySequence(Qt::Key_Space), this);
    connect(playShortcut, &QShortcut::activated, this, &MainWindow::togglePlay);
    auto *nextShortcut = new QShortcut(QKeySequence(Qt::CTRL | Qt::Key_Right), this);
    connect(nextShortcut, &QShortcut::activated, this, &MainWindow::nextTrack);
    auto *previousShortcut = new QShortcut(QKeySequence(Qt::CTRL | Qt::Key_Left), this);
    connect(previousShortcut, &QShortcut::activated, this, &MainWindow::previousTrack);

    if (QSystemTrayIcon::isSystemTrayAvailable()) {
        m_tray = new QSystemTrayIcon(QApplication::windowIcon(), this);
        auto *menu = new QMenu(this);
        auto *open = menu->addAction(tr("Open"));
        auto *quit = menu->addAction(tr("Exit"));
        connect(open, &QAction::triggered, this, [this] {
            if (m_miniPlayer) {
                m_miniPlayer->hide();
            }
            showNormal();
            raise();
            activateWindow();
        });
        connect(quit, &QAction::triggered, this, [this] {
            m_quitRequested = true;
            if (m_audio) {
                m_audio->stop();
            }
            qApp->quit();
        });
        m_tray->setContextMenu(menu);
        m_tray->setToolTip(QStringLiteral("OctoBeat"));
        connect(m_tray, &QSystemTrayIcon::activated, this,
                [this](QSystemTrayIcon::ActivationReason reason) {
                    if (reason == QSystemTrayIcon::Trigger ||
                        reason == QSystemTrayIcon::DoubleClick) {
                        if (m_miniPlayer) {
                            m_miniPlayer->hide();
                        }
                        showNormal();
                        raise();
                        activateWindow();
                    }
                });
        m_tray->show();
    }

    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    m_repeatMode = settings.value(QStringLiteral("repeat_mode"), QStringLiteral("off")).toString();
    m_shuffle = settings.value(QStringLiteral("shuffle"), false).toBool();
    const int volume = qBound(0, settings.value(QStringLiteral("volume"), 70).toInt(), 100);
    m_playerBar->setRepeatMode(m_repeatMode);
    m_playerBar->setShuffle(m_shuffle);
    m_playerBar->setVolume(volume);
    m_audio->setVolume(volume);
    m_crossfadeEnabled =
        settings.value(QStringLiteral("enable_crossfade"), true).toBool();
    m_audio->setCrossfadeEnabled(m_crossfadeEnabled);
    m_streaming->setShuffleEnabled(m_shuffle);
    m_streaming->setRepeatMode(m_repeatMode);
    m_mpris->setVolumePercent(volume);
    m_mpris->setShuffle(m_shuffle);
    m_mpris->setLoopStatus(m_repeatMode == QStringLiteral("one")
                               ? QStringLiteral("Track")
                               : m_repeatMode == QStringLiteral("all")
                                     ? QStringLiteral("Playlist")
                                     : QStringLiteral("None"));
    m_mpris->registerService();
    loadTracks();
}

MainWindow::~MainWindow() {
    flushListeningTime();
    delete m_miniPlayer;
    m_miniPlayer = nullptr;
}

void MainWindow::playFirst() {
    const QVector<Track> ordered = orderedLibraryTracks();
    if (!ordered.isEmpty()) {
        startContext(ordered, 0, tr("Library"));
    }
}

QVector<Track> MainWindow::orderedLibraryTracks() const {
    QVector<Track> ordered;
    if (!m_library) {
        return ordered;
    }
    QHash<qint64, const Track *> byId;
    for (const Track &track : m_tracks) {
        byId.insert(track.id, &track);
    }
    const QVector<qint64> ids = m_library->orderedTrackIds();
    ordered.reserve(ids.size());
    for (qint64 id : ids) {
        const auto it = byId.constFind(id);
        if (it != byId.constEnd()) {
            ordered.push_back(**it);
        }
    }
    return ordered;
}

Track MainWindow::trackForId(qint64 trackId) const {
    for (const Track &track : m_context) {
        if (track.id == trackId) {
            return track;
        }
    }
    for (const Track &track : m_tracks) {
        if (track.id == trackId) {
            return track;
        }
    }
    return {};
}

void MainWindow::startContext(const QVector<Track> &tracks,
                              int index,
                              const QString &name) {
    if (tracks.isEmpty()) {
        return;
    }
    m_streamingActive = false;
    m_streamingFast = false;
    m_streamDurationMs = 0;
    m_contextOriginal = tracks;
    m_context = tracks;
    m_contextName = name;
    if (index < 0 || index >= m_context.size()) {
        index = 0;
    }
    if (m_shuffle) {
        const Track current = m_context[index];
        QVector<Track> others;
        others.reserve(m_contextOriginal.size() - 1);
        for (const Track &track : m_contextOriginal) {
            if (track.id != current.id) {
                others.push_back(track);
            }
        }
        std::mt19937 rng(static_cast<unsigned>(
            QRandomGenerator::global()->generate()));
        std::shuffle(others.begin(), others.end(), rng);
        m_context.clear();
        m_context.push_back(current);
        for (const Track &track : others) {
            m_context.push_back(track);
        }
        index = 0;
    }
    playIndex(index);
}

void MainWindow::shuffleKeepingCurrent() {
    if (m_context.isEmpty() || m_currentIndex < 0 ||
        m_currentIndex >= m_context.size()) {
        return;
    }
    const Track current = m_context[m_currentIndex];
    QVector<Track> others;
    others.reserve(m_contextOriginal.size() - 1);
    for (const Track &track : m_contextOriginal) {
        if (track.id != current.id) {
            others.push_back(track);
        }
    }
    std::mt19937 rng(static_cast<unsigned>(
        QRandomGenerator::global()->generate()));
    std::shuffle(others.begin(), others.end(), rng);
    m_context.clear();
    m_context.push_back(current);
    for (const Track &track : others) {
        m_context.push_back(track);
    }
    m_currentIndex = 0;
}

void MainWindow::restoreOriginalOrder() {
    if (m_context.isEmpty() || m_currentIndex < 0 ||
        m_currentIndex >= m_context.size() || m_contextOriginal.isEmpty()) {
        return;
    }
    const qint64 currentId = m_context[m_currentIndex].id;
    m_context = m_contextOriginal;
    for (int i = 0; i < m_context.size(); ++i) {
        if (m_context[i].id == currentId) {
            m_currentIndex = i;
            return;
        }
    }
}

void MainWindow::autoScan() {
    // Scan in the background on every launch; large libraries get a progress
    // dialog, but no confirmation prompt for the folder the user already chose.
    scanLibrary(false);
}

void MainWindow::setTabIndex(int index) {
    if (m_tabs && index >= 0 && index < m_tabs->count()) {
        m_tabs->setCurrentIndex(index);
    }
}

void MainWindow::openPlaylist(qint64 playlistId) {
    if (m_playlists) {
        setTabIndex(1);
        m_playlists->openPlaylistById(playlistId);
    }
}

void MainWindow::demoDownloadSearch(const QString &query) {
    openDownloadDialog(query);
}

void MainWindow::demoStreamingSearch(const QString &query) {
    setTabIndex(2);
    m_streaming->searchFor(query);
}

void MainWindow::demoStreamingPlay() {
    setTabIndex(2);
    m_streaming->playCurrent();
}

void MainWindow::demoStreamingDownload() {
    setTabIndex(2);
    m_streaming->downloadCurrent();
}

void MainWindow::demoStreamingHover() {
    setTabIndex(2);
    m_streaming->demoHoverFirstResult();
}

void MainWindow::demoStreamingSuggest(const QString &query) {
    setTabIndex(2);
    m_streaming->demoSuggest(query);
}

void MainWindow::demoStreamingArtist(const QString &channelId,
                                     const QString &title) {
    setTabIndex(2);
    m_streaming->demoOpenArtist(channelId, title);
}

void MainWindow::demoStreamingPlaylist(const QString &playlistId,
                                       const QString &title) {
    setTabIndex(2);
    m_streaming->demoOpenPlaylist(playlistId, title);
}

void MainWindow::demoStreamingFilteredSearch(const QString &query, int filter) {
    setTabIndex(2);
    m_streaming->demoFilteredSearch(query, filter);
}

void MainWindow::demoStreamingQueue(const QString &query) {
    setTabIndex(2);
    m_streaming->demoQueue(query);
}

void MainWindow::demoPlayAll() {
    setTabIndex(2);
    m_streaming->playAllCurrent();
}

void MainWindow::demoHomePlay() {
    setTabIndex(2);
    m_streaming->playHomeFirst();
}

void MainWindow::demoPlaylistCardPlay() {
    setTabIndex(2);
    m_streaming->demoPlaylistCardPlay();
}

void MainWindow::demoShowAll() {
    setTabIndex(2);
    m_streaming->demoShowAll();
}

void MainWindow::openDownloadDialog(const QString &query) {
    DownloadDialog dialog(m_musicDir, m_dataDir, this);
    connect(&dialog, &DownloadDialog::libraryChanged, this, [this] {
        scanLibrary();
    });
    if (!query.isEmpty()) {
        dialog.searchFor(query);
    }
    dialog.exec();
}

void MainWindow::importCsv() {
    const QString path = QFileDialog::getOpenFileName(
        this, tr("Select CSV file"), QDir::homePath(),
        tr("CSV files (*.csv);;All files (*)"));
    if (!path.isEmpty()) {
        importCsvFile(path);
    }
}

void MainWindow::importCsvFile(const QString &path) {
    if (path.isEmpty()) {
        return;
    }
    auto *dialog = new CsvImportDialog(path, m_musicDir, m_dataDir, this);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setWindowModality(Qt::WindowModal);
    connect(dialog, &CsvImportDialog::libraryChanged, this,
            [this] { scanLibrary(); });
    dialog->show();
    dialog->start();
}

void MainWindow::importFiles() {
    const QStringList files = QFileDialog::getOpenFileNames(
        this, tr("Import files"), QDir::homePath(),
        QStringLiteral("Audio files (*.mp3 *.flac *.ogg *.wav *.m4a *.webm "
                       "*.opus);;All files (*)"));
    if (files.isEmpty()) {
        return;
    }
    QDir().mkpath(m_musicDir);
    int added = 0;
    int skipped = 0;
    int failed = 0;
    const QString musicRoot = QFileInfo(m_musicDir).absoluteFilePath();
    for (const QString &source : files) {
        const QFileInfo info(source);
        const QString destination =
            QDir(m_musicDir).filePath(info.fileName());
        if (QFileInfo::exists(destination)) {
            ++skipped;
            continue;
        }
        if (info.absolutePath() == musicRoot) {
            ++skipped;
            continue;
        }
        if (QFile::copy(source, destination)) {
            ++added;
        } else {
            ++failed;
        }
    }
    if (added > 0) {
        scanLibrary();
    }
    QMessageBox::information(
        this, tr("Import files"),
        tr("Imported: %1").arg(added) + QLatin1Char('\n') +
            tr("Skipped: %1").arg(skipped) + QLatin1Char('\n') +
            tr("Failed: %1").arg(failed));
}

void MainWindow::refreshAvatar() {
    if (!m_avatarButton || !m_core) {
        return;
    }
    const ProfileData data = m_core->profile();
    QPixmap source;
    if (!data.avatarPath.isEmpty()) {
        source.load(data.avatarPath);
    }
    if (source.isNull()) {
        source = QApplication::windowIcon().pixmap(32, 32);
    }
    if (source.isNull()) {
        return;
    }
    QPixmap rounded(32, 32);
    rounded.fill(Qt::transparent);
    QPainter painter(&rounded);
    painter.setRenderHint(QPainter::Antialiasing, true);
    QPainterPath path;
    path.addEllipse(0, 0, 32, 32);
    painter.setClipPath(path);
    painter.drawPixmap(0, 0, source.scaled(32, 32, Qt::KeepAspectRatioByExpanding,
                                          Qt::SmoothTransformation));
    painter.end();
    m_avatarButton->setIcon(QIcon(rounded));
}

void MainWindow::showMini() {
    showMiniPlayer();
}

void MainWindow::demoLyricsPanel() {
    m_playerBar->setLyricsActive(true);
    m_lyricsPanel->show();
    m_lyricsPanel->scrollToCurrent();
}

void MainWindow::demoKaraoke() {
    showKaraoke();
}

void MainWindow::playTrackById(qint64 trackId) {
    playTrack(trackId);
}

void MainWindow::showAddTracksDialog(qint64 playlistId) {
    if (!m_playlists) {
        return;
    }
    setTabIndex(1);
    m_playlists->openPlaylistById(playlistId);
    m_playlists->showAddTracksDialog();
}

void MainWindow::syncLyricsOverlayContent() {
    FullscreenLyrics *overlays[] = {m_lyricsOverlay, m_karaokeOverlay};
    for (FullscreenLyrics *overlay : overlays) {
        if (!overlay) {
            continue;
        }
        overlay->setContent(m_lyricsService->lines(), m_lyricsService->plain());
        overlay->setOffset(m_lyricsService->offsetMs());
        overlay->setHighlight(m_lyricsService->lineIndex(),
                              m_lyricsService->wordIndex());
    }
}

void MainWindow::showKaraoke() {
    if (!m_karaokeOverlay) {
        m_karaokeOverlay = new FullscreenLyrics(
            FullscreenLyrics::Mode::Karaoke, this);
        connect(m_karaokeOverlay, &FullscreenLyrics::offsetRequested,
                m_lyricsService, &LyricsService::adjustOffset);
    }
    m_playerBar->setLyricsActive(true);
    m_lyricsPanel->show();
    syncLyricsOverlayContent();
    m_karaokeOverlay->showFullScreen();
    m_karaokeOverlay->raise();
    m_karaokeOverlay->activateWindow();
}

void MainWindow::showLyricsOverlay() {
    if (!m_lyricsOverlay) {
        m_lyricsOverlay = new FullscreenLyrics(
            FullscreenLyrics::Mode::Lyrics, this);
        connect(m_lyricsOverlay, &FullscreenLyrics::offsetRequested,
                m_lyricsService, &LyricsService::adjustOffset);
    }
    m_playerBar->setLyricsActive(true);
    m_lyricsPanel->show();
    syncLyricsOverlayContent();
    m_lyricsOverlay->showFullScreen();
    m_lyricsOverlay->raise();
    m_lyricsOverlay->activateWindow();
}

QWidget *MainWindow::miniWidget() const {
    return m_miniPlayer;
}

bool MainWindow::isPlaying() const {
    return m_audio && m_audio->isPlaying();
}

void MainWindow::loadTracks() {
    if (!m_core) {
        return;
    }
    m_tracks = m_core->tracks();
    m_library->setTracks(m_tracks);
    if (m_playlists) {
        m_playlists->setLibraryTracks(m_tracks);
        m_playlists->refresh();
    }
    updateNextTrack();
}

void MainWindow::scanLibrary(bool confirmLarge) {
    if (!m_core) {
        return;
    }
    if (m_scanning) {
        m_scanPending = true;
        m_core->cancelScan();
        return;
    }

    const int total = countAudioFiles(m_musicDir);
    if (confirmLarge && total > 1000) {
        const auto answer = LocalizedMessageBox::question(
            this, tr("Scan library"),
            tr("The selected folder contains %1 audio files. Scanning may "
               "take a while. Continue?")
                .arg(total));
        if (answer != QMessageBox::Yes) {
            return;
        }
    }

    m_scanning = true;
    m_library->setStatus(tr("Scanning library..."));

    QProgressDialog *dialog = nullptr;
    if (total > 1000) {
        dialog = new QProgressDialog(tr("Scanning library..."), tr("Cancel"),
                                     0, total, this);
        dialog->setWindowModality(Qt::WindowModal);
        dialog->setMinimumDuration(300);
        dialog->setAutoClose(false);
        dialog->setAutoReset(false);
        connect(dialog, &QProgressDialog::canceled, this, [this] {
            if (m_core) {
                m_core->cancelScan();
            }
        });
        dialog->show();
    }

    auto *watcher = new QFutureWatcher<bool>(this);
    connect(watcher, &QFutureWatcher<bool>::finished, this,
            [this, watcher, dialog] {
                const bool ok = watcher->result();
                watcher->deleteLater();
                if (dialog) {
                    dialog->close();
                    dialog->deleteLater();
                }
                m_scanning = false;
                CoverCache::clear();
                const QString error = m_core ? m_core->lastError() : QString();
                const bool canceled =
                    error.contains(QStringLiteral("canceled"),
                                   Qt::CaseInsensitive);
                if (!ok && !canceled) {
                    LocalizedMessageBox::warning(
                        this, tr("Scan failed"),
                        tr("Could not scan the music folder."));
                } else if (canceled) {
                    m_library->setStatus(tr("Scan canceled"));
                }
                loadTracks();
                if (m_scanPending) {
                    m_scanPending = false;
                    scanLibrary();
                }
            });

    CoreClient *core = m_core;
    watcher->setFuture(QtConcurrent::run([core, dialog] {
        return core->scan([dialog](int done, int total) {
            if (!dialog) {
                return;
            }
            QMetaObject::invokeMethod(
                dialog,
                [dialog, done, total] {
                    dialog->setMaximum(total);
                    dialog->setValue(done);
                },
                Qt::QueuedConnection);
        });
    }));
}

void MainWindow::playTrack(qint64 trackId) {
    if (!m_core) {
        return;
    }
    const QVector<Track> ordered = orderedLibraryTracks();
    for (int index = 0; index < ordered.size(); ++index) {
        if (ordered[index].id == trackId) {
            startContext(ordered, index, tr("Library"));
            return;
        }
    }
}

void MainWindow::playPlaylist(qint64 playlistId) {
    if (!m_core) {
        return;
    }
    const QVector<Track> tracks = m_core->playlistTracks(playlistId);
    if (tracks.isEmpty()) {
        return;
    }
    QString name = tr("Playlist");
    for (const Playlist &playlist : m_core->playlists()) {
        if (playlist.id == playlistId) {
            name = playlist.name;
            break;
        }
    }
    startContext(tracks, 0, name);
}

void MainWindow::playPlaylistTrack(qint64 playlistId, qint64 trackId) {
    if (!m_core) {
        return;
    }
    const QVector<Track> tracks = m_core->playlistTracks(playlistId);
    for (int index = 0; index < tracks.size(); ++index) {
        if (tracks[index].id == trackId) {
            QString name = tr("Playlist");
            for (const Playlist &playlist : m_core->playlists()) {
                if (playlist.id == playlistId) {
                    name = playlist.name;
                    break;
                }
            }
            startContext(tracks, index, name);
            return;
        }
    }
}

void MainWindow::playStream(const QString &url,
                            const QString &title,
                            const QString &artist,
                            int durationSeconds,
                            qint64 startPositionMs,
                            const QString &thumbnail) {
    if (url.isEmpty()) {
        return;
    }
    m_context.clear();
    m_contextOriginal.clear();
    m_currentIndex = -1;
    m_crossfadeIndex = -1;
    m_streamCrossfading = false;
    m_contextName = tr("Streaming");
    m_streamingActive = true;
    m_streamingFast = url.contains(QStringLiteral("/octobeat-stream/stream-"));
    qWarning("stream: playStream fast=%d duration=%d",
             m_streamingFast ? 1 : 0, durationSeconds);
    m_streamDurationMs =
        qMax(0, durationSeconds) * 1000LL;
    m_streamTitle = title;
    m_streamArtist = artist;
    m_streamThumbnail = thumbnail;
    m_streamPositionBase = qMax<qint64>(0, startPositionMs);
    m_streamClock.start();
    m_streamTimer->start();
    m_playerBar->setSeekEnabled(true);
    if (m_mpris) {
        m_mpris->setCanSeek(true);
        m_mpris->setPosition(m_streamPositionBase * 1000);
    }
    const int generation = ++m_streamGeneration;
    if (m_mpris) {
        m_mprisStopped = false;
        m_mpris->setTrack(title, artist, QString(), thumbnail,
                          m_streamDurationMs * 1000, QString(),
                          QStringLiteral("/org/octobeat/stream/%1")
                              .arg(generation));
        m_mpris->setPlaybackStatus(QStringLiteral("Playing"));
        updateMprisCapabilities();
    }
    if (m_lyricsService) {
        m_lyricsService->clear();
    }
    updateNextTrack();

    Track track;
    track.title = title;
    track.artist = artist;
    m_playerBar->setTrack(track);
    m_playerBar->setContext(m_contextName);
    m_playerBar->setDuration(m_streamDurationMs);
    m_playerBar->setPosition(0);
    if (m_miniPlayer) {
        m_miniPlayer->setTrack(track);
        m_miniPlayer->setCoverUrl(thumbnail);
        m_miniPlayer->setDuration(m_streamDurationMs);
        m_miniPlayer->setSeekEnabled(true);
    }
    m_audio->setDurationHint(m_streamDurationMs);
    m_audio->playFile(url, startPositionMs);
    setWindowTitle(QStringLiteral("OctoBeat — ") +
                   (title.isEmpty() ? tr("Streaming") : title));
}

qint64 MainWindow::streamPositionMs() const {
    qint64 position = m_streamPositionBase;
    if (m_streamClock.isValid()) {
        position += m_streamClock.elapsed();
    }
    return qMax<qint64>(0, position);
}

void MainWindow::freezeStreamClock() {
    if (m_streamClock.isValid()) {
        m_streamPositionBase += m_streamClock.elapsed();
        m_streamClock.invalidate();
    }
}

void MainWindow::pauseStreaming() {
    if (!m_streamingActive) {
        return;
    }
    freezeStreamClock();
    m_streamTimer->stop();
    m_audio->pause();
    updateStreamProgress();
}

void MainWindow::resumeStreaming() {
    if (!m_streamingActive) {
        return;
    }
    if (!m_streamClock.isValid()) {
        m_streamClock.start();
    }
    m_streamTimer->start();
    m_audio->resume();
}

void MainWindow::updateStreamProgress() {
    if (!m_streamingActive) {
        m_streamTimer->stop();
        return;
    }
    qint64 position = streamPositionMs();
    if (m_streamDurationMs > 0) {
        position = qMin(position, m_streamDurationMs);
    }
    m_playerBar->setPosition(position);
    if (m_miniPlayer) {
        m_miniPlayer->setPosition(position);
    }
    if (m_mpris) {
        m_mpris->setPosition(position * 1000);
    }
    if (m_streaming) {
        m_streaming->maybePreload(position);
    }
    if (m_preloadedReady) {
        const qint64 remaining = m_streamDurationMs - position;
        const qint64 threshold =
            (m_crossfadeEnabled && m_audio->isPlaying()) ? 3000 : 250;
        if (remaining <= threshold && remaining > 0) {
            switchToPreloaded();
        }
    }
}

void MainWindow::handleStreamPreloaded(const QString &path,
                                       const QString &title,
                                       const QString &artist,
                                       int durationSeconds,
                                       const QString &thumbnail,
                                       bool manual) {
    m_preloadedPath = path;
    m_preloadedTitle = title;
    m_preloadedArtist = artist;
    m_preloadedThumbnail = thumbnail;
    m_preloadedDuration = durationSeconds;
    m_preloadedReady = true;
    if (manual) {
        switchToPreloaded();
    }
}

void MainWindow::applyStreamMetadata(const QString &title,
                                     const QString &artist,
                                     int durationSeconds,
                                     const QString &thumbnail) {
    m_streamingActive = true;
    m_streamingFast = true;
    m_streamDurationMs = qMax(0, durationSeconds) * 1000LL;
    m_audio->setDurationHint(m_streamDurationMs);
    m_streamTitle = title;
    m_streamArtist = artist;
    m_streamThumbnail = thumbnail;
    m_streamPositionBase = 0;
    m_streamClock.start();
    m_streamTimer->start();
    ++m_streamGeneration;
    Track track;
    track.title = title;
    track.artist = artist;
    m_playerBar->setTrack(track);
    m_playerBar->setContext(m_contextName.isEmpty() ? tr("Streaming")
                                                     : m_contextName);
    m_playerBar->setDuration(m_streamDurationMs);
    m_playerBar->setPosition(0);
    m_playerBar->setSeekEnabled(true);
    if (m_miniPlayer) {
        m_miniPlayer->setTrack(track);
        m_miniPlayer->setCoverUrl(thumbnail);
        m_miniPlayer->setDuration(m_streamDurationMs);
        m_miniPlayer->setPosition(0);
        m_miniPlayer->setSeekEnabled(true);
        m_miniPlayer->setPlaying(true);
    }
    if (m_mpris) {
        m_mprisStopped = false;
        m_mpris->setTrack(
            title, artist, QString(), thumbnail, m_streamDurationMs * 1000,
            QString(),
            QStringLiteral("/org/octobeat/stream/%1").arg(m_streamGeneration));
        m_mpris->setPosition(0);
        m_mpris->setPlaybackStatus(QStringLiteral("Playing"));
        m_mpris->setCanSeek(true);
        updateMprisCapabilities();
    }
    setWindowTitle(QStringLiteral("OctoBeat — ") +
                   (title.isEmpty() ? tr("Streaming") : title));
}

void MainWindow::switchToPreloaded() {
    if (!m_preloadedReady || m_preloadedPath.isEmpty()) {
        return;
    }
    const QString path = m_preloadedPath;
    const QString title = m_preloadedTitle;
    const QString artist = m_preloadedArtist;
    const QString thumbnail = m_preloadedThumbnail;
    const int duration = m_preloadedDuration;
    m_preloadedReady = false;
    m_preloadedPath.clear();

    const bool canCrossfade =
        m_crossfadeEnabled && m_streamingActive && m_audio->isPlaying();
    if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_AUDIO")) {
        qWarning("stream: switchToPreloaded canCrossfade=%d streaming=%d playing=%d",
                 canCrossfade ? 1 : 0, m_streamingActive ? 1 : 0,
                 m_audio->isPlaying() ? 1 : 0);
    }
    if (canCrossfade && m_audio->crossfadeTo(path)) {
        if (!m_streaming->beginPreloadedTransition()) {
            return;
        }
        m_streamCrossfading = true;
        applyStreamMetadata(title, artist, duration, thumbnail);
        return;
    }
    m_streaming->beginPreloadedTransition();
    m_streaming->finishPreloadedTransition();
    playStream(path, title, artist, duration, 0, thumbnail);
}

void MainWindow::onListeningTick() {
    if (!m_audio->isPlaying()) {
        m_listeningTimer->stop();
        flushListeningTime();
        return;
    }
    ++m_listeningPending;
    if (m_listeningPending >= 5) {
        flushListeningTime();
    }
}

void MainWindow::flushListeningTime() {
    const int seconds = m_listeningPending;
    if (seconds <= 0) {
        return;
    }
    m_listeningPending = 0;
    if (m_core) {
        m_core->addListeningTime(seconds);
    }
}

void MainWindow::applyVolume(int volume) {
    volume = qBound(0, volume, 100);
    m_audio->setVolume(volume);
    m_playerBar->setVolume(volume);
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    settings.setValue(QStringLiteral("volume"), volume);
    if (m_mpris) {
        m_mpris->setVolumePercent(volume);
    }
}

void MainWindow::applyRepeatMode(const QString &mode) {
    m_repeatMode = (mode == QStringLiteral("all") ||
                    mode == QStringLiteral("one"))
                       ? mode
                       : QStringLiteral("off");
    m_playerBar->setRepeatMode(m_repeatMode);
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    settings.setValue(QStringLiteral("repeat_mode"), m_repeatMode);
    updateNextTrack();
    if (m_streaming) {
        m_streaming->setRepeatMode(m_repeatMode);
    }
    if (m_mpris) {
        m_mpris->setLoopStatus(m_repeatMode == QStringLiteral("one")
                                   ? QStringLiteral("Track")
                                   : m_repeatMode == QStringLiteral("all")
                                         ? QStringLiteral("Playlist")
                                         : QStringLiteral("None"));
        updateMprisCapabilities();
    }
}

void MainWindow::applyShuffle(bool enabled) {
    if (m_shuffle == enabled) {
        m_playerBar->setShuffle(m_shuffle);
        return;
    }
    m_shuffle = enabled;
    if (enabled) {
        shuffleKeepingCurrent();
    } else {
        restoreOriginalOrder();
    }
    m_playerBar->setShuffle(m_shuffle);
    QSettings settings(QStringLiteral("MusicPlayer"),
                       QStringLiteral("MusicPlayer"));
    settings.setValue(QStringLiteral("shuffle"), enabled);
    updateNextTrack();
    if (m_streaming) {
        m_streaming->setShuffleEnabled(m_shuffle);
    }
    if (m_mpris) {
        m_mpris->setShuffle(m_shuffle);
        updateMprisCapabilities();
    }
}

void MainWindow::updateMprisCapabilities() {
    if (!m_mpris) {
        return;
    }
    const bool hasContext = m_currentIndex >= 0 &&
                            m_currentIndex < m_context.size();
    const bool canNext =
        (m_streamingActive && m_streamQueueSize > 0) ||
        !m_queue.isEmpty() ||
        (hasContext &&
         (m_currentIndex + 1 < m_context.size() ||
          m_repeatMode == QStringLiteral("all")));
    const bool canPrevious =
        (m_streamingActive && m_streaming &&
         m_streaming->canPlayPreviousStream()) ||
        (hasContext &&
         (m_currentIndex > 0 ||
          (m_repeatMode == QStringLiteral("all") && m_context.size() > 1)));
    m_mpris->setCanGoNext(canNext);
    m_mpris->setCanGoPrevious(canPrevious);
}

void MainWindow::playRandom() {
    const QVector<Track> ordered = orderedLibraryTracks();
    if (ordered.isEmpty()) {
        return;
    }
    startContext(ordered, QRandomGenerator::global()->bounded(ordered.size()),
                 tr("Library"));
}

void MainWindow::playIndex(int index) {
    m_crossfadeIndex = -1;
    commitTrackStart(index, true);
}

void MainWindow::commitTrackStart(int index, bool startPlayback) {
    if (index < 0 || index >= m_context.size()) {
        return;
    }
    const Track &track = m_context[index];
    const QString path = m_core->trackPath(track.id);
    if (path.isEmpty()) {
        QMessageBox::warning(this, tr("Cannot play track"),
                             tr("The track file is missing: %1").arg(track.filePath));
        return;
    }

    Track displayTrack = track;
    if (displayTrack.coverPath.isEmpty()) {
        for (const Track &libraryTrack : m_tracks) {
            if (libraryTrack.id == track.id && !libraryTrack.coverPath.isEmpty()) {
                displayTrack.coverPath = libraryTrack.coverPath;
                break;
            }
        }
    }

    m_streamingActive = false;
    m_streamingFast = false;
    m_streamDurationMs = 0;
    m_streamCrossfading = false;
    m_preloadedReady = false;
    m_streamPositionBase = 0;
    m_streamClock.invalidate();
    if (m_streamTimer) {
        m_streamTimer->stop();
    }
    ++m_streamGeneration;
    m_currentIndex = index;
    m_library->setCurrentPlaying(track.id);
    if (m_playlists) {
        m_playlists->setCurrentPlaying(track.id);
    }
    if (m_lyricsService) {
        m_lyricsService->setTrack(track);
    }
    const qint64 startPosition = startPlayback ? 0 : m_audio->position();
    m_playerBar->setTrack(displayTrack);
    m_playerBar->setContext(m_contextName);
    m_playerBar->setDuration(track.duration > 0 ? track.duration * 1000 : 0);
    m_playerBar->setSeekEnabled(true);
    if (m_mpris) {
        m_mpris->setCanSeek(true);
    }
    m_playerBar->setPosition(startPosition);
    if (m_miniPlayer) {
        m_miniPlayer->setTrack(displayTrack);
        m_miniPlayer->setDuration(track.duration > 0 ? track.duration * 1000 : 0);
        m_miniPlayer->setPosition(startPosition);
        m_miniPlayer->setSeekEnabled(true);
    }
    if (m_core) {
        m_core->logPlay(track.id);
    }
    if (m_mpris) {
        m_mprisStopped = false;
        m_mpris->setTrack(
            displayTrack.title, displayTrack.artist, displayTrack.album,
            mprisArtUrl(displayTrack.coverPath),
            track.duration > 0 ? track.duration * 1000000LL : 0,
            QUrl::fromLocalFile(path).toString(),
            QStringLiteral("/org/octobeat/track/%1").arg(track.id));
        m_mpris->setPlaybackStatus(QStringLiteral("Playing"));
        updateMprisCapabilities();
    }
    m_audio->setDurationHint(track.duration > 0 ? track.duration * 1000LL : 0);
    if (startPlayback) {
        m_audio->playFile(path);
    }
    setWindowTitle(QStringLiteral("OctoBeat — ") +
                   (track.title.isEmpty() ? tr("Unknown title") : track.title));
    updateNextTrack();
}

bool MainWindow::prepareCrossfade() {
    if (!m_crossfadeEnabled || m_streamingActive || m_crossfadeIndex >= 0 ||
        !m_core || !m_queue.isEmpty()) {
        return false;
    }
    if (m_context.isEmpty() || m_currentIndex < 0 ||
        m_currentIndex >= m_context.size()) {
        return false;
    }
    int next = -1;
    if (m_repeatMode == QStringLiteral("one")) {
        next = m_currentIndex;
    } else {
        next = m_currentIndex + 1;
        if (next >= m_context.size()) {
            if (m_repeatMode != QStringLiteral("all")) {
                return false;
            }
            next = 0;
        }
    }
    const Track &track = m_context.at(next);
    const QString path = m_core->trackPath(track.id);
    if (path.isEmpty()) {
        return false;
    }
    if (!m_audio->crossfadeTo(path)) {
        return false;
    }
    m_crossfadeIndex = next;
    return true;
}

void MainWindow::completeCrossfade() {
    if (m_streamCrossfading) {
        m_streamCrossfading = false;
        if (m_streaming) {
            m_streaming->finishPreloadedTransition();
        }
        return;
    }
    const int index = m_crossfadeIndex;
    m_crossfadeIndex = -1;
    if (index < 0 || index >= m_context.size()) {
        return;
    }
    commitTrackStart(index, false);
}

void MainWindow::updateNextTrack() {
    if (!m_library) {
        return;
    }
    if (!m_queue.isEmpty()) {
        const Track queued = trackForId(m_queue.first());
        if (!queued.title.isEmpty() || queued.id > 0) {
            m_library->setNextTrack(queued);
            return;
        }
    }
    if (m_context.isEmpty() || m_currentIndex < 0 ||
        m_currentIndex >= m_context.size()) {
        m_library->clearNextTrack();
        return;
    }
    int next = -1;
    if (m_repeatMode == QStringLiteral("one")) {
        next = m_currentIndex;
    } else if (m_currentIndex + 1 < m_context.size()) {
        next = m_currentIndex + 1;
    } else if (m_repeatMode == QStringLiteral("all")) {
        next = 0;
    }
    if (next < 0 || next >= m_context.size()) {
        m_library->clearNextTrack();
        return;
    }
    m_library->setNextTrack(m_context[next]);
}

void MainWindow::addTrackToQueue(qint64 trackId) {
    if (trackId > 0) {
        m_queue.push_back(trackId);
        updateNextTrack();
        updateMprisCapabilities();
    }
}

void MainWindow::demoTrackContextMenu() {
    const QVector<qint64> ids = m_library->orderedTrackIds();
    if (ids.isEmpty()) {
        return;
    }
    showTrackContextMenu(m_library->mapToGlobal(QPoint(240, 320)), ids.first(),
                         {ids.first()}, false);
}

void MainWindow::showTrackContextMenu(const QPoint &globalPos,
                                     qint64 trackId,
                                     const QVector<qint64> &selectedIds,
                                     bool playlistScope) {
    QMenu menu(this);
    const QColor iconColor = Theme::iconColor();

    QMenu *addMenu = menu.addMenu(
        IconUtils::tinted(QStringLiteral("add-to-playlist.svg"), iconColor, 18),
        tr("Add to playlist"));
    const QVector<Playlist> playlists =
        m_core ? m_core->playlists() : QVector<Playlist>();
    if (playlists.isEmpty()) {
        QAction *empty = addMenu->addAction(tr("(no playlists)"));
        empty->setEnabled(false);
    } else {
        for (const Playlist &playlist : playlists) {
            QAction *action = addMenu->addAction(playlist.name);
            connect(action, &QAction::triggered, this,
                    [this, playlist, trackId] {
                        addTrackToPlaylist(playlist.id, trackId);
                    });
        }
    }

    QAction *queue = menu.addAction(
        IconUtils::tinted(QStringLiteral("queue.svg"), iconColor, 18),
        tr("Add to queue"));
    connect(queue, &QAction::triggered, this,
            [this, trackId] { addTrackToQueue(trackId); });

    QAction *favorite = menu.addAction(
        IconUtils::tinted(QStringLiteral("favorite.svg"), iconColor, 18),
        tr("Set as Favorite"));
    connect(favorite, &QAction::triggered, this, [this, trackId] {
        if (m_core) {
            m_core->setProfileField(QStringLiteral("favorite_track_id"),
                                    QString::number(trackId));
            if (m_profile) {
                m_profile->reload();
            }
        }
    });

    QMenu *editMenu = menu.addMenu(
        IconUtils::tinted(QStringLiteral("pencil.svg"), iconColor, 18),
        tr("Edit Track"));
    QAction *metadata = editMenu->addAction(
        IconUtils::tinted(QStringLiteral("pencil.svg"), iconColor, 18),
        tr("Change title && author"));
    connect(metadata, &QAction::triggered, this,
            [this, trackId] { editTrackMetadata(trackId); });
    QAction *lyrics = editMenu->addAction(
        IconUtils::tinted(QStringLiteral("lyrics.svg"), iconColor, 18),
        tr("Add / Edit Lyrics"));
    connect(lyrics, &QAction::triggered, this,
            [this, trackId] { editTrackLyrics(trackId); });
    QAction *cover = editMenu->addAction(
        IconUtils::tinted(QStringLiteral("image.svg"), iconColor, 18),
        tr("Change cover"));
    connect(cover, &QAction::triggered, this,
            [this, trackId] { changeTrackCover(trackId); });
    QAction *trim = editMenu->addAction(
        IconUtils::tinted(QStringLiteral("cut.svg"), iconColor, 18),
        tr("Trim audio"));
    trim->setEnabled(false);
    trim->setToolTip(tr("Trim audio is coming in the next milestone."));

    const bool allSelected = playlistScope
                                 ? (m_playlists && m_playlists->allTracksSelected())
                                 : (m_library && m_library->allTracksSelected());
    QAction *selectAll = menu.addAction(
        IconUtils::tinted(QStringLiteral("select-all.svg"), iconColor, 18),
        allSelected ? tr("Deselect all") : tr("Select all"));
    selectAll->setShortcut(QKeySequence::SelectAll);
    connect(selectAll, &QAction::triggered, this, [this, playlistScope] {
        if (playlistScope) {
            m_playlists->toggleSelectAll();
        } else {
            m_library->toggleSelectAll();
        }
    });

    const bool multiple = selectedIds.size() > 1;
    const QString removeText =
        multiple
            ? tr("Remove selected tracks")
            : (playlistScope ? tr("Remove from this playlist")
                             : tr("Delete"));
    QAction *remove = menu.addAction(
        IconUtils::tinted(QStringLiteral("trash.svg"),
                          playlistScope ? iconColor
                                        : QColor(QStringLiteral("#e05a4a")),
                          18),
        removeText);
    connect(remove, &QAction::triggered, this,
            [this, selectedIds, playlistScope] {
                if (playlistScope) {
                    m_playlists->removeTracksFromPlaylist(selectedIds);
                } else {
                    removeTracksFromLibrary(selectedIds);
                }
            });

    menu.exec(globalPos);
}

void MainWindow::addTrackToPlaylist(qint64 playlistId, qint64 trackId) {
    if (!m_core) {
        return;
    }
    for (const Track &track : m_core->playlistTracks(playlistId)) {
        if (track.id == trackId) {
            QMessageBox::information(
                this, tr("Already there"),
                tr("This track is already in the playlist."));
            return;
        }
    }
    if (m_core->addTrackToPlaylist(playlistId, trackId) && m_playlists) {
        m_playlists->refresh();
    }
}

void MainWindow::editTrackMetadata(qint64 trackId) {
    if (!m_core) {
        return;
    }
    const Track track = trackForId(trackId);
    const QString current =
        (track.artist.isEmpty() ? tr("Unknown artist") : track.artist) +
        QStringLiteral(" - ") +
        (track.title.isEmpty() ? tr("Unknown title") : track.title);
    bool ok = false;
    const QString text = QInputDialog::getText(
        this, tr("Fix metadata"), tr("Enter 'Artist - Title':"),
        QLineEdit::Normal, current, &ok);
    if (!ok || text.trimmed().isEmpty()) {
        return;
    }
    QString artist = tr("Unknown artist");
    QString title = text.trimmed();
    if (text.contains(QStringLiteral(" - "))) {
        const int split = text.indexOf(QStringLiteral(" - "));
        artist = text.left(split).trimmed();
        title = text.mid(split + 3).trimmed();
        if (artist.isEmpty()) {
            artist = tr("Unknown artist");
        }
    }
    if (title.isEmpty()) {
        return;
    }
    const bool isCurrent =
        m_currentIndex >= 0 && m_currentIndex < m_context.size() &&
        m_context[m_currentIndex].id == trackId;
    const bool wasPlaying = isCurrent && m_audio->isPlaying();
    if (isCurrent) {
        m_audio->stop();
    }
    if (!m_core->updateTrackMetadata(trackId, title, artist)) {
        if (wasPlaying) {
            playIndex(m_currentIndex);
        }
        QMessageBox::warning(this, tr("Fix metadata"),
                             tr("Could not write tags to the audio file."));
        return;
    }
    for (Track &entry : m_tracks) {
        if (entry.id == trackId) {
            entry.title = title;
            entry.artist = artist;
        }
    }
    for (Track &entry : m_context) {
        if (entry.id == trackId) {
            entry.title = title;
            entry.artist = artist;
        }
    }
    if (m_library) {
        m_library->setTracks(m_tracks);
    }
    if (m_playlists) {
        m_playlists->setLibraryTracks(m_tracks);
        m_playlists->refresh();
    }
    if (isCurrent) {
        if (wasPlaying) {
            playIndex(m_currentIndex);
        } else {
            m_playerBar->setTrack(m_context[m_currentIndex]);
            if (m_miniPlayer) {
                m_miniPlayer->setTrack(m_context[m_currentIndex]);
            }
        }
    }
}

void MainWindow::editTrackLyrics(qint64 trackId) {
    if (!m_core) {
        return;
    }
    const LyricsData data = m_core->trackLyrics(trackId);
    const QString current =
        data.synced.isEmpty() ? data.plain : data.synced;
    bool ok = false;
    const QString text = QInputDialog::getMultiLineText(
        this, tr("Add / Edit Lyrics"),
        tr("Paste lyrics here. LRC timecodes like [00:12.34] are supported; "
           "plain text is shown without highlighting."),
        current, &ok);
    if (!ok) {
        return;
    }
    const bool synced =
        QRegularExpression(QStringLiteral("\\[\\d{1,3}:\\d{1,2}"))
            .match(text)
            .hasMatch();
    m_core->updateTrackLyrics(trackId, synced ? text : QString(),
                              synced ? QString() : text, true);
    if (m_lyricsService && m_lyricsService->trackId() == trackId) {
        m_lyricsService->reloadCurrent();
    }
}

void MainWindow::changeTrackCover(qint64 trackId) {
    if (!m_core) {
        return;
    }
    const QString source = QFileDialog::getOpenFileName(
        this, tr("Choose cover"), QString(),
        QStringLiteral("Images (*.png *.jpg *.jpeg *.webp)"));
    if (source.isEmpty()) {
        return;
    }
    if (!m_core->setTrackCover(trackId, source)) {
        QMessageBox::warning(this, tr("Change cover"),
                             tr("Could not set the track cover."));
        return;
    }
    CoverCache::clear();
    loadTracks();
    if (m_currentIndex >= 0 && m_currentIndex < m_context.size() &&
        m_context[m_currentIndex].id == trackId) {
        for (const Track &track : m_tracks) {
            if (track.id == trackId) {
                m_playerBar->setTrack(track);
                if (m_miniPlayer) {
                    m_miniPlayer->setTrack(track);
                }
                break;
            }
        }
    }
}

void MainWindow::removeTracksFromLibrary(const QVector<qint64> &trackIds) {
    if (!m_core || trackIds.isEmpty()) {
        return;
    }
    const auto answer = LocalizedMessageBox::question(
        this, tr("Remove from library"),
        trackIds.size() > 1
            ? tr("Delete %1 tracks from the library and from disk? "
                 "This cannot be undone.")
                  .arg(trackIds.size())
            : tr("Delete this track from the library and from disk? "
                 "This cannot be undone."));
    if (answer != QMessageBox::Yes) {
        return;
    }
    bool currentRemoved = false;
    qint64 currentId = 0;
    if (m_currentIndex >= 0 && m_currentIndex < m_context.size()) {
        currentId = m_context[m_currentIndex].id;
    }
    if (currentId > 0 && trackIds.contains(currentId)) {
        m_audio->stop();
    }
    int deleteFailures = 0;
    for (qint64 trackId : trackIds) {
        const Track track = trackForId(trackId);
        const QString path =
            m_core->trackPath(trackId).isEmpty() ? track.filePath
                                                : m_core->trackPath(trackId);
        if (m_currentIndex >= 0 && m_currentIndex < m_context.size() &&
            m_context[m_currentIndex].id == trackId) {
            currentRemoved = true;
        }
        if (!m_core->deleteTrack(trackId)) {
            ++deleteFailures;
            continue;
        }
        if (!path.isEmpty() && !QFile::remove(path)) {
            ++deleteFailures;
        }
        if (!track.coverPath.isEmpty()) {
            QFile::remove(track.coverPath);
        }
        m_queue.removeAll(trackId);
        m_context.erase(
            std::remove_if(m_context.begin(), m_context.end(),
                           [trackId](const Track &entry) {
                               return entry.id == trackId;
                           }),
            m_context.end());
        m_contextOriginal.erase(
            std::remove_if(m_contextOriginal.begin(), m_contextOriginal.end(),
                           [trackId](const Track &entry) {
                               return entry.id == trackId;
                           }),
            m_contextOriginal.end());
    }
    if (currentRemoved) {
        m_audio->stop();
        m_currentIndex = -1;
        m_context.clear();
        m_contextOriginal.clear();
        m_lyricsService->clear();
    } else if (currentId > 0) {
        for (int i = 0; i < m_context.size(); ++i) {
            if (m_context[i].id == currentId) {
                m_currentIndex = i;
                break;
            }
        }
    }
    if (deleteFailures > 0) {
        QMessageBox::warning(
            this, tr("Remove from library"),
            tr("The database entry was removed, but %1 audio file(s) "
               "could not be deleted from disk.")
                .arg(deleteFailures));
    }
    loadTracks();
    updateNextTrack();
}

void MainWindow::nextTrack() {
    if (m_streamingActive) {
        if (m_streaming) {
            m_streaming->playNextQueued();
        }
        return;
    }
    if (!m_queue.isEmpty()) {
        const qint64 queued = m_queue.takeFirst();
        for (int i = 0; i < m_context.size(); ++i) {
            if (m_context[i].id == queued) {
                playIndex(i);
                return;
            }
        }
        playTrack(queued);
        return;
    }
    if (m_context.isEmpty() || m_currentIndex < 0) {
        return;
    }
    int next = m_currentIndex + 1;
    if (next >= m_context.size()) {
        if (m_repeatMode == QStringLiteral("all")) {
            if (m_shuffle && m_contextOriginal.size() > 1) {
                const QVector<Track> previous = m_context;
                const auto sameOrder = [](const QVector<Track> &a,
                                          const QVector<Track> &b) {
                    if (a.size() != b.size()) {
                        return false;
                    }
                    for (int i = 0; i < a.size(); ++i) {
                        if (a[i].id != b[i].id) {
                            return false;
                        }
                    }
                    return true;
                };
                QVector<Track> shuffled = m_contextOriginal;
                std::mt19937 rng(static_cast<unsigned>(
                    QRandomGenerator::global()->generate()));
                for (int attempt = 0; attempt < 8; ++attempt) {
                    std::shuffle(shuffled.begin(), shuffled.end(), rng);
                    if (!sameOrder(shuffled, previous)) {
                        break;
                    }
                }
                if (shuffled.first().id == previous.last().id) {
                    for (int i = 1; i < shuffled.size(); ++i) {
                        if (shuffled[i].id != previous.last().id) {
                            std::swap(shuffled[0], shuffled[i]);
                            break;
                        }
                    }
                }
                m_context = shuffled;
                m_currentIndex = 0;
                playIndex(0);
                return;
            }
            next = 0;
        } else {
            m_mprisStopped = true;
            m_audio->stop();
            updateNextTrack();
            updateMprisCapabilities();
            return;
        }
    }
    playIndex(next);
}

void MainWindow::previousTrack() {
    if (m_streamingActive) {
        if (m_streaming) {
            m_streaming->playPreviousStream();
        }
        return;
    }
    if (m_context.isEmpty() || m_currentIndex < 0) {
        return;
    }
    int previous = m_currentIndex - 1;
    if (previous < 0) {
        previous = (m_repeatMode == QStringLiteral("all"))
                       ? m_context.size() - 1
                       : 0;
    }
    playIndex(previous);
}

void MainWindow::onEndReached() {
    if (m_context.isEmpty()) {
        return;
    }
    if (!m_queue.isEmpty()) {
        nextTrack();
        return;
    }
    if (m_repeatMode == QStringLiteral("one")) {
        playIndex(m_currentIndex);
        return;
    }
    if (m_currentIndex + 1 >= m_context.size() &&
        m_repeatMode != QStringLiteral("all")) {
        m_mprisStopped = true;
        m_audio->stop();
        updateNextTrack();
        updateMprisCapabilities();
        return;
    }
    nextTrack();
}

void MainWindow::togglePlay() {
    if (m_streamingActive) {
        if (m_audio->isPlaying()) {
            pauseStreaming();
        } else {
            resumeStreaming();
        }
        return;
    }
    if (m_context.isEmpty()) {
        if (m_tracks.isEmpty()) {
            return;
        }
        startContext(m_tracks, 0, tr("Library"));
        return;
    }
    if (m_currentIndex < 0) {
        playIndex(0);
        return;
    }
    if (m_audio->isPlaying()) {
        m_audio->pause();
    } else if (m_mprisStopped) {
        playIndex(m_currentIndex);
    } else {
        m_audio->resume();
    }
}

void MainWindow::focusSearch() {
    if (m_library) {
        m_library->focusSearch();
    }
}

void MainWindow::showMiniPlayer() {
    if (!m_miniPlayer) {
        m_miniPlayer = new MiniPlayer(nullptr);
        connect(m_miniPlayer, &MiniPlayer::playPauseRequested,
                this, &MainWindow::togglePlay);
        connect(m_miniPlayer, &MiniPlayer::nextRequested,
                this, &MainWindow::nextTrack);
        connect(m_miniPlayer, &MiniPlayer::previousRequested,
                this, &MainWindow::previousTrack);
        connect(m_miniPlayer, &MiniPlayer::seekRequested, this,
                [this](qint64 milliseconds) {
                    if (m_streamingActive) {
                        if (m_streaming) {
                            m_streaming->seekStream(milliseconds);
                        }
                        return;
                    }
                    m_crossfadeIndex = -1;
                    m_audio->seekTo(milliseconds);
                });
        connect(m_miniPlayer, &MiniPlayer::expandRequested, this, [this] {
            m_miniPlayer->hide();
            show();
            raise();
            activateWindow();
        });
        connect(m_miniPlayer, &MiniPlayer::closeRequested, this, [this] {
            m_miniPlayer->hide();
            show();
            raise();
            activateWindow();
        });
    }

    if (m_streamingActive) {
        Track displayTrack;
        displayTrack.title = m_streamTitle;
        displayTrack.artist = m_streamArtist;
        m_miniPlayer->setTrack(displayTrack);
        m_miniPlayer->setCoverUrl(m_streamThumbnail);
        m_miniPlayer->setDuration(m_streamDurationMs);
        m_miniPlayer->setPosition(streamPositionMs());
        m_miniPlayer->setSeekEnabled(true);
    } else {
        if (m_currentIndex >= 0 && m_currentIndex < m_context.size()) {
            Track displayTrack = m_context[m_currentIndex];
            if (displayTrack.coverPath.isEmpty()) {
                for (const Track &libraryTrack : m_tracks) {
                    if (libraryTrack.id == displayTrack.id &&
                        !libraryTrack.coverPath.isEmpty()) {
                        displayTrack.coverPath = libraryTrack.coverPath;
                        break;
                    }
                }
            }
            m_miniPlayer->setTrack(displayTrack);
        }
        m_miniPlayer->setSeekEnabled(true);
        m_miniPlayer->setDuration(m_audio->duration());
        m_miniPlayer->setPosition(m_audio->position());
    }
    m_miniPlayer->setPlaying(m_audio->isPlaying());
    m_miniPlayer->show();
    hide();
}

bool MainWindow::nativeEvent(const QByteArray &eventType,
                              void *message,
                              qintptr *result) {
#ifdef Q_OS_WIN
    if ((eventType == "windows_generic_MSG" ||
         eventType == "windows_dispatcher_MSG") &&
        message && result && !isMaximized() && !isFullScreen()) {
        auto *msg = static_cast<MSG *>(message);
        if (msg->message == WM_NCHITTEST) {
            RECT windowRect{};
            if (::GetWindowRect(reinterpret_cast<HWND>(winId()),
                                &windowRect)) {
                const int x = GET_X_LPARAM(msg->lParam);
                const int y = GET_Y_LPARAM(msg->lParam);
                const int border =
                    qMax(6, ::GetSystemMetrics(SM_CXSIZEFRAME) + 2);
                const bool left = x >= windowRect.left &&
                                  x < windowRect.left + border;
                const bool right = x < windowRect.right &&
                                   x >= windowRect.right - border;
                const bool top = y >= windowRect.top &&
                                 y < windowRect.top + border;
                const bool bottom = y < windowRect.bottom &&
                                    y >= windowRect.bottom - border;
                if (top && left) {
                    *result = HTTOPLEFT;
                    return true;
                }
                if (top && right) {
                    *result = HTTOPRIGHT;
                    return true;
                }
                if (bottom && left) {
                    *result = HTBOTTOMLEFT;
                    return true;
                }
                if (bottom && right) {
                    *result = HTBOTTOMRIGHT;
                    return true;
                }
                if (left) {
                    *result = HTLEFT;
                    return true;
                }
                if (right) {
                    *result = HTRIGHT;
                    return true;
                }
                if (top) {
                    *result = HTTOP;
                    return true;
                }
                if (bottom) {
                    *result = HTBOTTOM;
                    return true;
                }
            }
        }
    }
#endif
    return QMainWindow::nativeEvent(eventType, message, result);
}

void MainWindow::createResizeHandles() {
    const struct {
        int edges;
        Qt::CursorShape cursor;
    } definitions[] = {
        {static_cast<int>(Qt::LeftEdge), Qt::SizeHorCursor},
        {static_cast<int>(Qt::RightEdge), Qt::SizeHorCursor},
        {static_cast<int>(Qt::TopEdge), Qt::SizeVerCursor},
        {static_cast<int>(Qt::BottomEdge), Qt::SizeVerCursor},
        {static_cast<int>(Qt::LeftEdge | Qt::TopEdge), Qt::SizeFDiagCursor},
        {static_cast<int>(Qt::RightEdge | Qt::TopEdge), Qt::SizeBDiagCursor},
        {static_cast<int>(Qt::LeftEdge | Qt::BottomEdge), Qt::SizeBDiagCursor},
        {static_cast<int>(Qt::RightEdge | Qt::BottomEdge), Qt::SizeFDiagCursor},
    };
    for (const auto &definition : definitions) {
        auto *handle = new QWidget(this);
        handle->setObjectName(QStringLiteral("resizeHandle"));
        handle->setProperty("resizeEdges", definition.edges);
        handle->setCursor(definition.cursor);
        handle->setAttribute(Qt::WA_NoSystemBackground, true);
        handle->setAutoFillBackground(false);
        handle->installEventFilter(this);
        m_resizeHandles.push_back(handle);
    }
    positionResizeHandles();
}

void MainWindow::positionResizeHandles() {
    if (m_resizeHandles.size() != 8) {
        return;
    }
    const int border = 6;
    const int width = this->width();
    const int height = this->height();
    const bool visible = !isMaximized() && !isFullScreen();
    const QVector<QRect> rects = {
        QRect(0, border, border, height - border * 2),
        QRect(width - border, border, border, height - border * 2),
        QRect(border, 0, width - border * 2, border),
        QRect(border, height - border, width - border * 2, border),
        QRect(0, 0, border, border),
        QRect(width - border, 0, border, border),
        QRect(0, height - border, border, border),
        QRect(width - border, height - border, border, border),
    };
    for (int i = 0; i < m_resizeHandles.size(); ++i) {
        QWidget *handle = m_resizeHandles.at(i);
        handle->setGeometry(rects.at(i));
        handle->setVisible(visible);
        if (visible) {
            handle->raise();
        }
    }
}

bool MainWindow::eventFilter(QObject *watched, QEvent *event) {
    auto *handle = qobject_cast<QWidget *>(watched);
    if (handle && m_resizeHandles.contains(handle)) {
        const auto edges =
            static_cast<Qt::Edges>(handle->property("resizeEdges").toInt());
        if (event->type() == QEvent::MouseButtonPress) {
            auto *mouse = static_cast<QMouseEvent *>(event);
            if (mouse->button() == Qt::LeftButton) {
                if (QWindow *window = windowHandle()) {
                    if (window->startSystemResize(edges)) {
                        return true;
                    }
                }
                m_manualResizing = true;
                m_manualResizeEdges = edges;
                m_manualResizeStart = mouse->globalPosition().toPoint();
                m_manualResizeGeometry = geometry();
                handle->grabMouse();
                return true;
            }
        }
        if (m_manualResizing && event->type() == QEvent::MouseMove) {
            auto *mouse = static_cast<QMouseEvent *>(event);
            const QPoint delta =
                mouse->globalPosition().toPoint() - m_manualResizeStart;
            QRect target = m_manualResizeGeometry;
            if (edges & Qt::LeftEdge) {
                target.setLeft(target.left() + delta.x());
            }
            if (edges & Qt::RightEdge) {
                target.setRight(target.right() + delta.x());
            }
            if (edges & Qt::TopEdge) {
                target.setTop(target.top() + delta.y());
            }
            if (edges & Qt::BottomEdge) {
                target.setBottom(target.bottom() + delta.y());
            }
            const QSize minimum = minimumSize();
            if (target.width() < minimum.width()) {
                if (edges & Qt::LeftEdge) {
                    target.setLeft(target.right() - minimum.width() + 1);
                } else {
                    target.setWidth(minimum.width());
                }
            }
            if (target.height() < minimum.height()) {
                if (edges & Qt::TopEdge) {
                    target.setTop(target.bottom() - minimum.height() + 1);
                } else {
                    target.setHeight(minimum.height());
                }
            }
            setGeometry(target);
            return true;
        }
        if (m_manualResizing && event->type() == QEvent::MouseButtonRelease) {
            m_manualResizing = false;
            handle->releaseMouse();
            return true;
        }
    }
    return QMainWindow::eventFilter(watched, event);
}

void MainWindow::resizeEvent(QResizeEvent *event) {
    QMainWindow::resizeEvent(event);
    positionResizeHandles();
}

void MainWindow::changeEvent(QEvent *event) {
    QMainWindow::changeEvent(event);
    if (event->type() == QEvent::WindowStateChange) {
        applyWindowFrameState();
    }
}

void MainWindow::applyWindowFrameState() {
    if (!m_surface || !m_rootLayout) {
        return;
    }
    const bool maximized = isMaximized() || isFullScreen();
    const int margin = maximized ? 0 : 8;
    m_rootLayout->setContentsMargins(margin, margin, margin, margin);
    m_surface->setProperty("windowMaximized", maximized);
    m_surface->style()->unpolish(m_surface);
    m_surface->style()->polish(m_surface);
    m_surface->update();
}

void MainWindow::closeEvent(QCloseEvent *event) {
    if (m_tray && m_tray->isVisible() && !m_quitRequested) {
        hide();
        event->ignore();
        return;
    }
    flushListeningTime();
    if (m_miniPlayer) {
        m_miniPlayer->hide();
    }
    QSettings settings(QStringLiteral("MusicPlayer"), QStringLiteral("MusicPlayer"));
    settings.setValue(QStringLiteral("repeat_mode"), m_repeatMode);
    settings.setValue(QStringLiteral("shuffle"), m_shuffle);
    if (m_audio) {
        m_audio->stop();
    }
    QMainWindow::closeEvent(event);
}
