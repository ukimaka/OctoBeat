#include "StreamingPage.h"

#include "FastStreamService.h"
#include "RemoteImageCache.h"
#include "SomeDlService.h"
#include "StreamCollectionView.h"
#include "StreamCache.h"
#include "StreamHistory.h"
#include "StreamHomeView.h"
#include "StreamQueuePanel.h"
#include "StreamSearchOverlay.h"
#include "StreamSearchView.h"
#include "YouTubeBrowseService.h"
#include "YouTubeSearchService.h"
#include "YtDlpService.h"
#include "app/ElidedLabel.h"
#include "app/IconUtils.h"
#include "app/SpinnerWidget.h"
#include "app/Theme.h"

#include <QApplication>

#include <algorithm>
#include <random>
#include <QDir>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPushButton>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QSet>
#include <QResizeEvent>
#include <QStackedWidget>
#include <QToolButton>
#include <QTimer>
#include <QVBoxLayout>

namespace {
constexpr int SearchBarMinWidth = 420;
constexpr int SearchBarMaxWidth = 860;

QString friendlyStreamError(const QString &message) {
    const QString lower = message.toLower();
    if (lower.contains(QStringLiteral("403")) ||
        lower.contains(QStringLiteral("forbidden")) ||
        lower.contains(QStringLiteral("sign in")) ||
        lower.contains(QStringLiteral("not a bot"))) {
        return QCoreApplication::translate(
            "StreamingPage",
            "YouTube blocked the request. Import cookies.txt in Settings or "
            "try again later.");
    }
    return message;
}
} // namespace

StreamingPage::StreamingPage(const QString &musicDir,
                             const QString &dataDir,
                             QWidget *parent)
    : QWidget(parent),
      m_musicDir(musicDir),
      m_dataDir(dataDir),
      m_streamDir(QDir(QDir::tempPath()).filePath(
          QStringLiteral("octobeat-stream"))) {
    m_images = new RemoteImageCache(this);
    m_suggestService = new YouTubeSearchService(this);
    m_searchService = new YouTubeSearchService(this);
    m_artistSearchService = new YouTubeSearchService(this);
    m_homePlaylistService = new YouTubeSearchService(this);
    m_browseService = new YouTubeBrowseService(this);
    m_searchBrowseService = new YouTubeBrowseService(this);
    m_artistAllService = new YouTubeBrowseService(this);
    m_service = new YtDlpService(this);
    m_downloadService = new SomeDlService(m_dataDir, this);
    m_fastStream = new FastStreamService(this);
    m_preloadStream = new FastStreamService(this);
    m_preloadResolveService = new YtDlpService(this);
    m_cacheService = new YtDlpService(this);
    m_cacheStartTimer = new QTimer(this);
    m_cacheStartTimer->setSingleShot(true);
    m_cacheStartTimer->setInterval(2500);
    connect(m_cacheStartTimer, &QTimer::timeout, this,
            &StreamingPage::startBackgroundCache);

    buildUi();

    connect(m_suggestService, &YouTubeSearchService::finished, this,
            [this](const QVector<SearchResult> &results) {
                if (m_search->text().trimmed() != m_suggestQuery ||
                    m_search->text().trimmed().size() < 2) {
                    setSearchBusy(false);
                    return;
                }
                setSearchBusy(false);
                m_overlay->setSuggestions(results);
                positionOverlay();
                m_overlay->showPanel();
                m_overlay->raise();
            });
    connect(m_suggestService, &YouTubeSearchService::failed, this,
            [this](const QString &message) {
                setSearchBusy(false);
                if (m_search->text().trimmed().size() >= 2) {
                    setStatus(message);
                }
            });
    connect(m_suggestService, &YouTubeSearchService::canceled, this,
            [this] { setSearchBusy(false); });

    connect(m_searchService, &YouTubeSearchService::finished, this,
            [this](const QVector<SearchResult> &results) {
                m_lastSearchResults = results;
                m_searchView->setLoading(false);
                m_exactArtists.clear();
                m_exactAlbums.clear();
                m_exactPending = 0;
                m_searchBaseResults = results;
                if ((m_searchFilter == YouTubeSearchService::Filter::All ||
                     m_searchFilter ==
                         YouTubeSearchService::Filter::Playlists) &&
                    !m_currentQuery.trimmed().isEmpty()) {
                    for (const SearchResult &result : results) {
                        if (result.kind != SearchResult::Kind::Artist ||
                            result.channelId.isEmpty() ||
                            result.title.compare(m_currentQuery.trimmed(),
                                                 Qt::CaseInsensitive) != 0) {
                            continue;
                        }
                        if (m_exactArtists.contains(result.channelId) ||
                            m_exactArtists.size() >= 2) {
                            continue;
                        }
                        m_exactArtists.insert(result.channelId, result);
                    }
                }
                if (!m_exactArtists.isEmpty()) {
                    m_exactPending = m_exactArtists.size();
                    for (auto it = m_exactArtists.constBegin();
                         it != m_exactArtists.constEnd(); ++it) {
                        m_searchBrowseService->fetchChannelPlaylists(
                            it.key());
                    }
                    return;
                }
                m_searchView->setResults(results);
                setSearchBusy(false);
                setStatus(tr("%n result(s)", "", results.size()));
            });
    connect(m_searchService, &YouTubeSearchService::failed, this,
            [this](const QString &message) {
                m_searchView->setLoading(false);
                m_searchView->setResults({});
                setSearchBusy(false);
                setStatus(message);
            });
    connect(m_searchService, &YouTubeSearchService::canceled, this,
            [this] {
                m_searchView->setLoading(false);
                setSearchBusy(false);
            });

    connect(m_homePlaylistService, &YouTubeSearchService::finished, this,
            [this](const QVector<SearchResult> &results) {
                m_homePlaylists = results;
                updateHome();
            });
    connect(m_artistSearchService, &YouTubeSearchService::finished, this,
            [this](const QVector<SearchResult> &results) {
                if (m_artistId.isEmpty()) {
                    return;
                }
                m_artistSearchRaw = YouTubeSearchService::filterResults(
                    results, YouTubeSearchService::Filter::Tracks, false, true);
                m_artistPending = qMax(0, m_artistPending - 1);
                if (m_artistPending == 0) {
                    finishArtistLoad();
                }
            });
    connect(m_artistSearchService, &YouTubeSearchService::failed, this,
            [this](const QString &) {
                if (m_artistId.isEmpty()) {
                    return;
                }
                m_artistPending = qMax(0, m_artistPending - 1);
                if (m_artistPending == 0) {
                    finishArtistLoad();
                }
            });
    connect(m_browseService, &YouTubeBrowseService::channelVideosFinished,
            this,
            [this](const QString &channelId,
                   const QVector<SearchResult> &results) {
                if (channelId != m_artistId ||
                    sender() != m_browseService) {
                    return;
                }
                m_artistVideos = YouTubeSearchService::filterResults(
                    results, YouTubeSearchService::Filter::Tracks, false,
                    true);
                if (m_collectionView->isVisible() &&
                    m_artistHeader.id == channelId) {
                    m_collectionView->setTracks(m_artistVideos);
                }
                if (m_playArtistWhenLoaded && !m_artistVideos.isEmpty()) {
                    m_playArtistWhenLoaded = false;
                    startStreamCollection(m_artistVideos);
                }
                m_artistPending = qMax(0, m_artistPending - 1);
                if (m_artistPending == 0) {
                    finishArtistLoad();
                }
            });
    connect(m_browseService, &YouTubeBrowseService::channelPlaylistsFinished,
            this,
            [this](const QString &channelId,
                   const QVector<SearchResult> &results) {
                if (channelId != m_artistId) {
                    return;
                }
                static const QRegularExpression playlistJunk(
                    QStringLiteral("(highlights?|clips?|streams?|vods?|"
                                   "gameplay|podcast|compilation|"
                                   "best\\s*moments|funny\\s*moments)"),
                    QRegularExpression::CaseInsensitiveOption);
                QVector<SearchResult> playlists;
                for (const SearchResult &playlist : results) {
                    if (!playlistJunk.match(playlist.title).hasMatch()) {
                        playlists.push_back(playlist);
                    }
                }
                m_artistPlaylists = playlists;
                if (m_artistHeader.id == channelId) {
                    m_collectionView->setPlaylists(playlists);
                }
                m_artistPending = qMax(0, m_artistPending - 1);
                if (m_artistPending == 0) {
                    finishArtistLoad();
                }
            });
    connect(m_browseService, &YouTubeBrowseService::playlistFinished, this,
            [this](const QString &playlistId,
                   const QVector<SearchResult> &results) {
                if (playlistId != m_playlistId) {
                    return;
                }
                m_playlistTracks = results;
                m_playlistHeader.itemCount = results.size();
                m_collectionView->setHeader(m_playlistHeader);
                m_collectionView->setTracks(results);
                m_collectionView->setLoading(false);
                setSearchBusy(false);
                setStatus(tr("%n track(s)", "", results.size()));
                if (m_playPlaylistWhenLoaded) {
                    m_playPlaylistWhenLoaded = false;
                    startStreamCollection(results);
                }
            });
    connect(m_searchBrowseService,
            &YouTubeBrowseService::channelPlaylistsFinished, this,
            [this](const QString &channelId,
                   const QVector<SearchResult> &results) {
                if (m_exactPending <= 0 ||
                    !m_exactArtists.contains(channelId)) {
                    return;
                }
                m_exactAlbums.insert(channelId, results);
                --m_exactPending;
                if (m_exactPending == 0) {
                    finishExactSearch();
                }
            });
    connect(m_searchBrowseService, &YouTubeBrowseService::failed, this,
            [this](const QString &context, const QString &) {
                if (context != QStringLiteral("channel-playlists") ||
                    m_exactPending <= 0) {
                    return;
                }
                --m_exactPending;
                if (m_exactPending == 0) {
                    finishExactSearch();
                }
            });
    connect(m_artistAllService, &YouTubeBrowseService::playlistFinished, this,
            [this](const QString &playlistId,
                   const QVector<SearchResult> &results) {
                Q_UNUSED(playlistId);
                if (!m_artistAllLoading) {
                    return;
                }
                for (const SearchResult &track : results) {
                    if (track.kind == SearchResult::Kind::Track) {
                        m_artistAllTracks.push_back(track);
                    }
                }
                --m_artistAllPending;
                if (m_artistAllPending > 0) {
                    return;
                }
                m_artistAllLoading = false;
                QHash<QString, SearchResult> merged;
                QVector<SearchResult> ordered;
                for (const SearchResult &track : m_artistVideos) {
                    if (!merged.contains(track.id)) {
                        merged.insert(track.id, track);
                        ordered.push_back(track);
                    }
                }
                for (const SearchResult &track : m_artistAllTracks) {
                    if (!merged.contains(track.id)) {
                        merged.insert(track.id, track);
                        ordered.push_back(track);
                    }
                }
                m_artistVideos = ordered;
                m_artistExpanded = true;
                m_collectionView->setLoading(false);
                m_collectionView->setShowAllAvailable(false);
                updateArtistTracksView();
                setStatus(tr("%n track(s)", "", m_artistVideos.size()));
            });
    connect(m_artistAllService, &YouTubeBrowseService::failed, this,
            [this](const QString &context, const QString &) {
                if (context != QStringLiteral("playlist") ||
                    !m_artistAllLoading) {
                    return;
                }
                --m_artistAllPending;
                if (m_artistAllPending <= 0) {
                    m_artistAllPending = 1;
                    m_artistAllService->playlistFinished(
                        QString(), QVector<SearchResult>());
                }
            });
    connect(m_browseService, &YouTubeBrowseService::failed, this,
            [this](const QString &context, const QString &message) {
                if (context == QStringLiteral("related")) {
                    return;
                }
                if (context.startsWith(QStringLiteral("channel-"))) {
                    m_artistPending = qMax(0, m_artistPending - 1);
                    if (m_artistPending == 0) {
                        finishArtistLoad();
                    }
                    return;
                }
                if (context == QStringLiteral("playlist")) {
                    m_collectionView->setLoading(false);
                    setSearchBusy(false);
                }
                setStatus(message);
            });

    connect(m_service, &YtDlpService::streamResolved, this,
            [this](const QString &url, const QString &, const QString &,
                   int durationSeconds) {
                if (!m_resolving || m_resolvingForUrl != m_pending.url) {
                    qWarning("stream: ignoring stale resolve for %s",
                             m_pending.id.toUtf8().constData());
                    return;
                }
                m_resolving = false;
                m_resolvedUrl = url;
                if (durationSeconds > 0) {
                    m_pendingDuration = durationSeconds;
                }
                m_resolvedForUrl = m_resolvingForUrl;
                if (m_playWhenReady) {
                    startFastPlayback();
                } else {
                    setTrackBusy(m_pending.id, false);
                    setSearchBusy(false);
                    setStatus(tr("Ready to play: %1").arg(m_pending.title));
                }
            });
    connect(m_service, &YtDlpService::failed, this,
            [this](const QString &message) {
                if (m_suppressCancel) {
                    return;
                }
                if (m_cacheDownloading && m_downloadForUrl != m_pending.url) {
                    qWarning("stream: ignoring stale cache failure");
                    return;
                }
                if (m_resolving && m_resolvingForUrl != m_pending.url) {
                    qWarning("stream: ignoring stale resolve failure");
                    return;
                }
                qWarning("stream: yt-dlp failed: %s",
                         message.toUtf8().constData());
                if (m_cacheDownloading) {
                    m_cacheDownloading = false;
                    if (m_cacheDownloadRetries < 1 && m_playWhenReady) {
                        ++m_cacheDownloadRetries;
                        qWarning("stream: retrying cache download: %s",
                                 message.toUtf8().constData());
                        setStatus(tr("Stream interrupted. Retrying…"));
                        QTimer::singleShot(1500, this,
                                           &StreamingPage::startCacheDownload);
                        return;
                    }
                    m_playWhenReady = false;
                    setTrackBusy(m_pending.id, false);
                    setSearchBusy(false);
                    setStatus(friendlyStreamError(message));
                    return;
                }
                if (m_resolving) {
                    m_resolving = false;
                    if (m_playWhenReady) {
                        startCacheDownload();
                    } else {
                        setTrackBusy(m_pending.id, false);
                        setSearchBusy(false);
                        setStatus(message);
                    }
                }
            });
    connect(m_service, &YtDlpService::canceled, this, [this] {
        if (!m_suppressCancel) {
            setSearchBusy(false);
        }
    });
    connect(m_service, &YtDlpService::downloadFinished, this,
            [this](const QString &path) {
                if (!m_cacheDownloading ||
                    m_downloadForUrl != m_pending.url) {
                    qWarning("stream: ignoring stale cache file %s",
                             path.toUtf8().constData());
                    return;
                }
                m_cacheDownloading = false;
                m_cacheDownloadRetries = 0;
                m_downloadForUrl.clear();
                m_cachedPath = path;
                m_cachedUrl = m_pending.url;
                if (m_playWhenReady) {
                    m_playWhenReady = false;
                    m_playingId = m_pending.id;
                    m_playingState = true;
                    recordPlaybackHistory();
                    setTrackBusy(m_pending.id, false);
                    setTrackPlaying(m_pending.id, true);
                    setSearchBusy(false);
                    setStatus(tr("Playing: %1").arg(m_pending.title));
                    emit streamReady(path, m_pending.title, m_pending.uploader,
                                     m_pendingDuration, 0, m_pending.thumbnail);
                } else {
                    setTrackBusy(m_pending.id, false);
                    setSearchBusy(false);
                    setStatus(tr("Ready to play: %1").arg(m_pending.title));
                }
            });
    connect(m_service, &YtDlpService::downloadProgress, this,
            [this](int percent) {
                if (m_cacheDownloading) {
                    setStatus(tr("Buffering stream… %1%").arg(percent));
                }
            });

    connect(m_cacheService, &YtDlpService::downloadFinished, this,
            [this](const QString &path) {
                m_bgCacheDownloading = false;
                if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_STREAM")) {
                    qWarning("stream: cache finished path=%s url=%s pending=%s",
                             path.toUtf8().constData(),
                             m_bgCacheUrl.toUtf8().constData(),
                             m_pending.url.toUtf8().constData());
                }
                if (m_bgCacheUrl != m_pending.url) {
                    return;
                }
                m_bgCachePath = path;
                m_bgCacheRetries = 0;
                if (m_pendingCacheSeekMs >= 0) {
                    const qint64 target = m_pendingCacheSeekMs;
                    m_pendingCacheSeekMs = -1;
                    switchToCachedSeek(target);
                }
            });
    connect(m_cacheService, &YtDlpService::downloadProgress, this,
            [this](int percent) {
                if (m_pendingCacheSeekMs >= 0 && m_bgCacheDownloading) {
                    setStatus(tr("Preparing seek… %1%").arg(percent));
                }
            });
    connect(m_cacheService, &YtDlpService::failed, this,
            [this](const QString &message) {
                m_bgCacheDownloading = false;
                qWarning("stream: cache failed: %s",
                         message.toUtf8().constData());
                if (m_bgCacheRetries < 2 && m_bgCacheUrl == m_pending.url) {
                    ++m_bgCacheRetries;
                    if (m_pendingCacheSeekMs >= 0) {
                        setStatus(tr("Preparing seek… retrying"));
                    }
                    QTimer::singleShot(1500, this,
                                       &StreamingPage::startBackgroundCache);
                    return;
                }
                if (m_pendingCacheSeekMs >= 0) {
                    m_pendingCacheSeekMs = -1;
                    setStatus(tr("Seek is not available: %1").arg(message));
                }
            });
    connect(m_cacheService, &YtDlpService::canceled, this, [this] {
        m_bgCacheDownloading = false;
    });

    const auto attachFastStream = [this](FastStreamService *stream) {
        connect(stream, &FastStreamService::ready, this,
                [this, stream](const QString &path, int durationSeconds) {
                    handleFastStreamReady(stream, path, durationSeconds);
                });
        connect(stream, &FastStreamService::failed, this,
                [this, stream](const QString &message) {
                    handleFastStreamFailed(stream, message);
                });
        connect(stream, &FastStreamService::finished, this,
                [this, stream] {
                    if (stream == m_fastStream) {
                        m_fastUrl.clear();
                    }
                });
    };
    attachFastStream(m_fastStream);

    connect(m_preloadStream, &FastStreamService::prebuffered, this,
            [this](const QString &path, int durationSeconds) {
                handlePreloadBuffered(path, durationSeconds);
            });
    connect(m_preloadStream, &FastStreamService::failed, this,
            [this](const QString &message) {
                if (!m_preloading) {
                    return;
                }
                stopWatchdog();
                m_preloading = false;
                m_preloadReady = false;
                m_preloadStream->stop();
                setTrackBusy(m_preloadTrack.id, false);
                setStatus(tr("Could not prepare the next stream: %1")
                              .arg(message));
            });
    connect(m_preloadResolveService, &YtDlpService::streamResolved, this,
            [this](const QString &url, const QString &, const QString &,
                   int durationSeconds) {
                if (!m_preloading) {
                    return;
                }
                m_preloadResolvedUrl = url;
                if (durationSeconds > 0) {
                    m_preloadDuration = durationSeconds;
                }
                m_preloadStream->start(
                    url, m_streamDir,
                    m_preloadTrack.id + QStringLiteral("-preload"),
                    m_preloadDuration, 0);
            });
    connect(m_preloadResolveService, &YtDlpService::failed, this,
            [this](const QString &message) {
                if (!m_preloading) {
                    return;
                }
                stopWatchdog();
                m_preloading = false;
                m_preloadReady = false;
                setTrackBusy(m_preloadTrack.id, false);
                setStatus(tr("Could not prepare the next stream: %1")
                              .arg(message));
            });

    connect(m_downloadService, &SomeDlService::downloadProgress, this,
            [this](int percent) {
                setTrackDownload(m_downloadingId, percent);
                setStatus(tr("Downloading… %1%").arg(percent), false);
            });
    connect(m_downloadService, &SomeDlService::downloadFinished, this,
            [this](const QString &path) {
                setTrackDownload(m_downloadingId, -1);
                m_downloading = false;
                m_downloadingId.clear();
                setStatus(tr("Downloaded: %1").arg(QFileInfo(path).fileName()));
                emit libraryChanged();
            });
    connect(m_downloadService, &SomeDlService::failed, this,
            [this](const QString &message) {
                setTrackDownload(m_downloadingId, -1);
                m_downloading = false;
                m_downloadingId.clear();
                setStatus(message);
            });
    connect(m_downloadService, &SomeDlService::canceled, this, [this] {
                setTrackDownload(m_downloadingId, -1);
                m_downloading = false;
                m_downloadingId.clear();
            });

    qApp->installEventFilter(this);
    updateSearchWidth();
    refreshHome();
}

StreamingPage::~StreamingPage() {
    qApp->removeEventFilter(this);
    if (m_fastStream) {
        m_fastStream->stop();
    }
}

void StreamingPage::buildUi() {
    auto *root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    auto *searchArea = new QWidget(this);
    auto *searchAreaLayout = new QVBoxLayout(searchArea);
    searchAreaLayout->setContentsMargins(18, 14, 18, 4);
    searchAreaLayout->setSpacing(0);

    auto *centerRow = new QHBoxLayout();
    centerRow->setContentsMargins(0, 0, 0, 0);

    m_searchContext = new QWidget(searchArea);
    auto *contextLayout = new QHBoxLayout(m_searchContext);
    contextLayout->setContentsMargins(0, 0, 0, 0);
    contextLayout->setSpacing(6);
    m_searchBack = new QToolButton(m_searchContext);
    m_searchBack->setObjectName(QStringLiteral("streamBackButton"));
    m_searchBack->setFixedSize(32, 32);
    m_searchBack->setIcon(IconUtils::tinted(
        QStringLiteral("back.svg"), Theme::iconColor(), 20));
    m_searchBack->setIconSize(QSize(20, 20));
    m_searchBack->setCursor(Qt::PointingHandCursor);
    m_searchBack->setAutoRaise(true);
    connect(m_searchBack, &QToolButton::clicked, this,
            &StreamingPage::showHome);
    contextLayout->addWidget(m_searchBack);
    m_searchBack->hide();
    m_searchContextLabel = new QLabel(m_searchContext);
    m_searchContextLabel->setObjectName(
        QStringLiteral("streamViewSubtitle"));
    m_searchContextLabel->setStyleSheet(
        QStringLiteral("color: rgba(220, 220, 232, 170);"));
    QFont contextFont = m_searchContextLabel->font();
    contextFont.setPixelSize(12);
    m_searchContextLabel->setFont(contextFont);
    m_searchContextLabel->setFixedWidth(230);
    contextLayout->addWidget(m_searchContextLabel);
    m_searchContext->hide();
    centerRow->addWidget(m_searchContext, 0, Qt::AlignVCenter);
    centerRow->addStretch(1);
    m_searchBar = new QWidget(searchArea);
    m_searchBar->setObjectName(QStringLiteral("streamSearchBar"));
    auto *barLayout = new QHBoxLayout(m_searchBar);
    barLayout->setContentsMargins(0, 0, 0, 0);
    barLayout->setSpacing(6);

    m_homeButton = new QToolButton(m_searchBar);
    m_homeButton->setObjectName(QStringLiteral("streamHomeButton"));
    m_homeButton->setFixedSize(34, 34);
    m_homeButton->setIcon(IconUtils::tinted(
        QStringLiteral("home.svg"), Theme::iconColor(), 19));
    m_homeButton->setIconSize(QSize(19, 19));
    m_homeButton->setCursor(Qt::PointingHandCursor);
    m_homeButton->setToolTip(tr("Home"));
    m_homeButton->setStyleSheet(
        QStringLiteral("QToolButton#streamHomeButton {"
                       " background: rgba(255, 255, 255, 12);"
                       " border: 1px solid rgba(255, 255, 255, 22);"
                       " border-radius: 17px; }"
                       "QToolButton#streamHomeButton:hover {"
                       " background: rgba(255, 255, 255, 28); }"));
    m_homeButton->hide();
    connect(m_homeButton, &QToolButton::clicked, this,
            &StreamingPage::showHome);
    barLayout->addWidget(m_homeButton);

    m_search = new QLineEdit(m_searchBar);
    m_search->setObjectName(QStringLiteral("streamSearchField"));
    m_search->setPlaceholderText(tr("Search YouTube..."));
    m_search->setClearButtonEnabled(true);
    m_search->installEventFilter(this);
    barLayout->addWidget(m_search, 1);

    m_searchSpinner = new SpinnerWidget(m_searchBar);
    m_searchSpinner->setFixedSize(24, 24);
    m_searchSpinner->setColor(Theme::accent());
    m_searchSpinner->hide();
    barLayout->addWidget(m_searchSpinner);

    m_searchButton = new QPushButton(m_searchBar);
    m_searchButton->setObjectName(QStringLiteral("streamSearchButton"));
    m_searchButton->setFixedSize(36, 34);
    m_searchButton->setIcon(IconUtils::tinted(QStringLiteral("search.svg"),
                                             Theme::iconColor(), 22));
    m_searchButton->setIconSize(QSize(22, 22));
    m_searchButton->setCursor(Qt::PointingHandCursor);
    m_searchButton->setToolTip(tr("Search"));
    barLayout->addWidget(m_searchButton);

    centerRow->addWidget(m_searchBar);
    centerRow->addStretch(1);
    searchAreaLayout->addLayout(centerRow);
    root->addWidget(searchArea);

    m_queueButton = new QToolButton(this);
    m_queueButton->setObjectName(QStringLiteral("streamQueueButton"));
    m_queueButton->setFixedSize(34, 34);
    m_queueButton->setIconSize(QSize(20, 20));
    m_queueButton->setCursor(Qt::PointingHandCursor);
    m_queueButton->setIcon(
        IconUtils::tinted(QStringLiteral("queue.svg"),
                          Theme::iconColor(), 20));
    m_queueButton->setToolTip(tr("Queue"));
    m_queueButton->setStyleSheet(
        QStringLiteral("QToolButton#streamQueueButton {"
                       " background: rgba(255, 255, 255, 10);"
                       " border: none; border-radius: 17px; }"
                       "QToolButton#streamQueueButton:hover {"
                       " background: rgba(255, 255, 255, 24); }"));
    connect(m_queueButton, &QToolButton::clicked, this, [this] {
        updateQueuePanel();
        m_queuePanel->openAt(m_queueButton);
    });

    m_stack = new QStackedWidget(this);
    m_homeView = new StreamHomeView(m_images, m_stack);
    m_searchView = new StreamSearchView(m_images, m_stack);
    m_collectionView = new StreamCollectionView(m_images, m_stack);
    m_stack->addWidget(m_homeView);
    m_stack->addWidget(m_searchView);
    m_stack->addWidget(m_collectionView);
    m_stack->setCurrentWidget(m_homeView);
    connect(m_stack, &QStackedWidget::currentChanged, this, [this] {
        if (m_homeButton) {
            m_homeButton->setVisible(m_stack->currentWidget() != m_homeView);
        }
    });
    root->addWidget(m_stack, 1);

    auto *statusArea = new QWidget(this);
    auto *statusLayout = new QVBoxLayout(statusArea);
    statusLayout->setContentsMargins(18, 0, 18, 4);
    statusLayout->setSpacing(0);
    m_status = new QLabel(statusArea);
    m_status->setObjectName(QStringLiteral("streamingStatus"));
    m_status->setWordWrap(true);
    m_status->hide();
    statusLayout->addWidget(m_status);
    root->addWidget(statusArea);

    m_overlay = new StreamSearchOverlay(m_images, this);
    m_overlay->hide();
    m_overlay->raise();

    m_queuePanel = new StreamQueuePanel(this);
    connect(m_queuePanel, &StreamQueuePanel::playRequested, this,
            &StreamingPage::playTrack);
    connect(m_queuePanel, &StreamQueuePanel::removeRequested, this,
            [this](const SearchResult &result) {
                for (int i = 0; i < m_streamQueue.size(); ++i) {
                    const SearchResult &item = m_streamQueue.at(i);
                    if (item.kind == result.kind && item.id == result.id) {
                        m_streamQueue.removeAt(i);
                        break;
                    }
                }
                updateQueuePanel();
                emit queueChanged(m_streamQueue.size());
                setStatus(tr("Removed from queue: %1").arg(result.title));
            });
    connect(m_queuePanel, &StreamQueuePanel::clearRequested, this, [this] {
        m_streamQueue.clear();
        updateQueuePanel();
        emit queueChanged(0);
        setStatus(tr("Queue cleared"));
    });

    m_watchdog = new QTimer(this);
    m_watchdog->setSingleShot(true);
    connect(m_watchdog, &QTimer::timeout, this,
            &StreamingPage::handleWatchdogTimeout);

    m_statusTimer = new QTimer(this);
    m_statusTimer->setSingleShot(true);
    connect(m_statusTimer, &QTimer::timeout, this, [this] {
        if (m_status) {
            m_status->clear();
            m_status->hide();
        }
    });

    m_suggestTimer = new QTimer(this);
    m_suggestTimer->setSingleShot(true);
    m_suggestTimer->setInterval(300);
    connect(m_suggestTimer, &QTimer::timeout, this,
            &StreamingPage::requestSuggestions);

    connect(m_search, &QLineEdit::textEdited, this,
            &StreamingPage::onSearchTextEdited);
    connect(m_search, &QLineEdit::returnPressed, this, [this] {
        if (m_overlay->panelVisible()) {
            if (m_overlay->activateCurrent()) {
                hideOverlay();
                return;
            }
        }
        openFullSearch(m_search->text());
    });
    connect(m_searchButton, &QPushButton::clicked, this, [this] {
        openFullSearch(m_search->text());
    });

    connect(m_overlay, &StreamSearchOverlay::playRequested, this,
            [this](const SearchResult &result) {
                hideOverlay();
                handlePlayRequest(result);
            });
    connect(m_overlay, &StreamSearchOverlay::downloadRequested, this,
            &StreamingPage::downloadTrack);
    connect(m_overlay, &StreamSearchOverlay::queueRequested, this,
            &StreamingPage::addToQueue);
    connect(m_overlay, &StreamSearchOverlay::openRequested, this,
            [this](const SearchResult &result) {
                hideOverlay();
                openResult(result);
            });
    connect(m_overlay, &StreamSearchOverlay::historyRequested, this,
            [this](const QString &query) {
                hideOverlay();
                openFullSearch(query);
            });

    connect(m_homeView, &StreamHomeView::itemActivated, this,
            &StreamingPage::openResult);
    connect(m_homeView, &StreamHomeView::playRequested, this,
            &StreamingPage::handlePlayRequest);
    connect(m_homeView, &StreamHomeView::downloadRequested, this,
            &StreamingPage::downloadTrack);
    connect(m_homeView, &StreamHomeView::queueRequested, this,
            &StreamingPage::addToQueue);
    connect(m_homeView, &StreamHomeView::removeRequested, this,
            &StreamingPage::removeFromHome);

    connect(m_searchView, &StreamSearchView::filterChanged, this,
            [this](YouTubeSearchService::Filter filter) {
                runFullSearch(filter);
            });
    connect(m_searchView, &StreamSearchView::playRequested, this,
            &StreamingPage::handlePlayRequest);
    connect(m_searchView, &StreamSearchView::downloadRequested, this,
            &StreamingPage::downloadTrack);
    connect(m_searchView, &StreamSearchView::queueRequested, this,
            &StreamingPage::addToQueue);
    connect(m_searchView, &StreamSearchView::openRequested, this,
            &StreamingPage::openResult);
    connect(m_searchView, &StreamSearchView::historyRequested, this,
            &StreamingPage::openFullSearch);

    connect(m_collectionView, &StreamCollectionView::backRequested, this,
            [this] {
                if (m_playlistFromArtist) {
                    showArtistCached();
                } else if (m_artistFromSearch || m_playlistFromSearch) {
                    showSearchView();
                } else {
                    showHome();
                }
            });
    connect(m_collectionView, &StreamCollectionView::playRequested, this,
            &StreamingPage::handlePlayRequest);
    connect(m_collectionView, &StreamCollectionView::downloadRequested, this,
            &StreamingPage::downloadTrack);
    connect(m_collectionView, &StreamCollectionView::queueRequested, this,
            &StreamingPage::addToQueue);
    connect(m_collectionView, &StreamCollectionView::playlistRequested, this,
            [this](const SearchResult &playlist) {
                openPlaylist(playlist, true);
            });
    connect(m_collectionView, &StreamCollectionView::showAllRequested, this,
            &StreamingPage::showAllArtistTracks);
    connect(m_collectionView, &StreamCollectionView::playAllRequested, this,
            [this](const SearchResult &header) {
                if (header.kind == SearchResult::Kind::Artist) {
                    if (!m_artistVideos.isEmpty()) {
                        startStreamCollection(m_artistVideos);
                    } else if (!m_artistPlaylists.isEmpty()) {
                        openPlaylist(m_artistPlaylists.first(), true, true);
                    }
                } else if (header.kind == SearchResult::Kind::Playlist) {
                    startStreamCollection(m_playlistTracks);
                }
            });
}

void StreamingPage::setSearchContextVisible(bool visible,
                                            const QString &text) {
    if (!m_searchContext) {
        return;
    }
    m_searchContextLabel->setText(text);
    m_searchContextLabel->setFixedWidth(width() < 820 ? 130 : 230);
    m_searchContext->setVisible(visible);
}

void StreamingPage::updateSearchWidth() {
    if (!m_searchBar) {
        return;
    }
    const int target = qBound(SearchBarMinWidth,
                              static_cast<int>(width() * 0.62),
                              SearchBarMaxWidth);
    m_searchBar->setFixedWidth(target);
    positionOverlay();
}

void StreamingPage::positionOverlay() {
    if (!m_overlay || !m_searchBar) {
        return;
    }
    const QPoint pos = m_searchBar->mapTo(
        this, QPoint(0, m_searchBar->height() + 6));
    m_overlay->setGeometry(pos.x(), pos.y(), m_searchBar->width(),
                           m_overlay->height() > 0 ? m_overlay->height()
                                                   : 1);
}

void StreamingPage::resizeEvent(QResizeEvent *event) {
    QWidget::resizeEvent(event);
    updateSearchWidth();
    positionOverlay();
    positionQueueButton();
}

void StreamingPage::positionQueueButton() {
    if (!m_queueButton) {
        return;
    }
    m_queueButton->move(width() - m_queueButton->width() - 18, 14);
    m_queueButton->raise();
}

void StreamingPage::updateQueuePanel() {
    if (!m_queuePanel) {
        return;
    }
    m_queuePanel->setQueue(m_streamQueue);
    m_queueButton->setToolTip(
        m_streamQueue.isEmpty()
            ? tr("Queue")
            : tr("Queue (%1)").arg(m_streamQueue.size()));
}

void StreamingPage::setStatus(const QString &status, bool autoHide) {
    if (!m_status) {
        return;
    }
    m_statusTimer->stop();
    m_status->setText(status);
    m_status->setVisible(!status.isEmpty());
    if (!status.isEmpty() && autoHide) {
        m_statusTimer->start(750);
    }
}

void StreamingPage::setSearchBusy(bool busy) {
    if (busy) {
        m_searchSpinner->start();
        m_searchSpinner->show();
    } else {
        m_searchSpinner->stop();
        m_searchSpinner->hide();
    }
}

void StreamingPage::hideOverlay() {
    m_suggestTimer->stop();
    if (m_suggestService->isBusy()) {
        m_suggestService->cancel();
    }
    setSearchBusy(false);
    if (m_overlay) {
        m_overlay->hidePanel();
    }
}

void StreamingPage::onSearchTextEdited(const QString &text) {
    m_suggestTimer->stop();
    const QString trimmed = text.trimmed();
    if (trimmed.size() < 2) {
        hideOverlay();
        if (trimmed.isEmpty() && m_search->hasFocus()) {
            showHistoryOverlay();
        }
        return;
    }
    m_suggestTimer->start();
}

void StreamingPage::requestSuggestions() {
    const QString query = m_search->text().trimmed();
    if (query.size() < 2) {
        return;
    }
    m_suggestQuery = query;
    setSearchBusy(true);
    m_suggestService->search(query, YouTubeSearchService::Filter::All, 5);
}

void StreamingPage::showHistoryOverlay() {
    if (m_search->text().trimmed().size() >= 2) {
        return;
    }
    m_overlay->setHistory(StreamHistory::searches(8));
    positionOverlay();
    m_overlay->showPanel();
    m_overlay->raise();
}

void StreamingPage::openFullSearch(const QString &query) {
    hideOverlay();
    const QString trimmed = query.trimmed();
    if (trimmed.isEmpty()) {
        showSearchHistoryView();
        return;
    }
    StreamHistory::addSearch(trimmed);
    m_currentQuery = trimmed;
    m_searchFilter = YouTubeSearchService::Filter::All;
    m_stack->setCurrentWidget(m_searchView);
    m_searchView->setQuery(trimmed);
    m_searchView->setFilter(YouTubeSearchService::Filter::All);
    runFullSearch(YouTubeSearchService::Filter::All);
}

void StreamingPage::runFullSearch(YouTubeSearchService::Filter filter) {
    if (m_currentQuery.isEmpty()) {
        showSearchHistoryView();
        return;
    }
    m_searchFilter = filter;
    m_searchView->setFilter(filter);
    m_exactArtists.clear();
    m_exactAlbums.clear();
    m_exactPending = 0;
    m_searchView->setQuery(m_currentQuery);
    m_searchView->setLoading(true);
    setSearchBusy(true);
    setStatus(tr("Searching…"));
    const auto serviceFilter =
        filter == YouTubeSearchService::Filter::Playlists
            ? YouTubeSearchService::Filter::All
            : filter;
    m_searchService->search(m_currentQuery, serviceFilter, 60);
}

void StreamingPage::showSearchHistoryView() {
    hideOverlay();
    m_currentQuery.clear();
    m_stack->setCurrentWidget(m_searchView);
    m_searchView->setQuery({});
    m_searchView->setHistory(StreamHistory::searches(150));
    m_searchView->setLoading(false);
    setSearchBusy(false);
    setStatus({});
}

void StreamingPage::showSearchView() {
    hideOverlay();
    m_stack->setCurrentWidget(m_searchView);
    if (m_currentQuery.isEmpty()) {
        showSearchHistoryView();
    } else {
        m_searchView->setQuery(m_currentQuery);
        m_searchView->setResults(m_lastSearchResults);
    }
}

void StreamingPage::openResult(const SearchResult &result) {
    switch (result.kind) {
    case SearchResult::Kind::Track:
        playTrack(result);
        break;
    case SearchResult::Kind::Artist:
        openArtist(result);
        break;
    case SearchResult::Kind::Playlist:
        openPlaylist(result, false);
        break;
    }
}

void StreamingPage::showHome() {
    setSearchContextVisible(false);
    hideOverlay();
    m_stack->setCurrentWidget(m_homeView);
    setStatus({});
    refreshHome();
}

void StreamingPage::refreshHome() {
    m_homeRecentTracks = StreamHistory::tracks(12);
    m_homeArtists = StreamHistory::artists(10);
    m_homePlaylists = StreamHistory::playlists(10);
    updateHome();
    if (m_homePlaylists.isEmpty()) {
        m_homePlaylistService->search(
            QStringLiteral("music mix"),
            YouTubeSearchService::Filter::Playlists, 10);
    }
}

void StreamingPage::removeFromHome(const SearchResult &result) {
    switch (result.kind) {
    case SearchResult::Kind::Track:
        StreamHistory::removeTrack(result);
        break;
    case SearchResult::Kind::Artist:
        StreamHistory::removeArtist(result);
        break;
    case SearchResult::Kind::Playlist:
        StreamHistory::removePlaylist(result);
        break;
    }
    const auto eraseResult = [&result](QVector<SearchResult> &items) {
        items.erase(
            std::remove_if(items.begin(), items.end(),
                           [&result](const SearchResult &item) {
                               return item.kind == result.kind &&
                                      item.id == result.id;
                           }),
            items.end());
    };
    eraseResult(m_homeRecentTracks);
    eraseResult(m_homeArtists);
    eraseResult(m_homePlaylists);
    updateHome();
}

void StreamingPage::updateHome() {
    if (m_homeView) {
        m_homeView->setData(m_homeRecentTracks, m_homeArtists,
                            m_homePlaylists);
        if (!m_playingId.isEmpty()) {
            m_homeView->setPlaying(m_playingId, m_playingState);
        }
    }
}

void StreamingPage::openArtist(const SearchResult &artist, bool autoPlay) {
    if (artist.id.isEmpty()) {
        return;
    }
    m_playArtistWhenLoaded = autoPlay;
    StreamHistory::addArtist(artist);
    m_artistFromSearch = (m_stack->currentWidget() == m_searchView);
    m_playlistFromArtist = false;
    m_artistHeader = artist;
    m_artistId = artist.channelId.isEmpty() ? artist.id : artist.channelId;
    m_artistVideos.clear();
    m_artistSearchRaw.clear();
    m_artistPlaylists.clear();
    m_artistExpanded = false;
    m_artistAllLoading = false;
    m_artistAllPending = 0;
    m_artistAllTracks.clear();
    m_artistPending = 3;
    m_collectionView->setHeader(artist);
    m_collectionView->setTracks({});
    m_collectionView->setPlaylists({});
    m_collectionView->setLoading(true);
    setSearchContextVisible(false);
    m_stack->setCurrentWidget(m_collectionView);
    setSearchBusy(true);
    setStatus(tr("Loading artist…"));
    m_artistSearchService->search(artist.title,
                                  YouTubeSearchService::Filter::Tracks, 20);
    m_browseService->fetchChannelVideos(m_artistId);
    m_browseService->fetchChannelPlaylists(m_artistId);
}

void StreamingPage::finishExactSearch() {
    QVector<SearchResult> merged = m_searchBaseResults;
    QSet<QString> seenPlaylists;
    for (auto it = m_exactAlbums.constBegin();
         it != m_exactAlbums.constEnd(); ++it) {
        const QString artistChannel = it.key();
        const auto artistIt = m_exactArtists.constFind(artistChannel);
        for (SearchResult album : it.value()) {
            if (album.kind != SearchResult::Kind::Playlist ||
                album.playlistId.isEmpty() ||
                seenPlaylists.contains(album.playlistId)) {
                continue;
            }
            seenPlaylists.insert(album.playlistId);
            if (artistIt != m_exactArtists.constEnd()) {
                album.channelId = artistChannel;
                if (!artistIt.value().title.isEmpty()) {
                    album.uploader = artistIt.value().title;
                }
            }
            merged.push_back(album);
        }
    }
    m_lastSearchResults = merged;
    m_searchView->setResults(merged);
    setSearchBusy(false);
    setStatus(tr("%n result(s)", "", merged.size()));
}

void StreamingPage::updateArtistTracksView() {
    QVector<SearchResult> visible = m_artistVideos;
    if (!m_artistExpanded && visible.size() > 20) {
        visible.resize(20);
    }
    m_collectionView->setTracks(visible);
    m_collectionView->setShowAllAvailable(
        !m_artistExpanded &&
        (!m_artistPlaylists.isEmpty() || m_artistVideos.size() > 20));
}

void StreamingPage::showAllArtistTracks(const SearchResult &header) {
    if (m_artistAllLoading || header.kind != SearchResult::Kind::Artist) {
        return;
    }
    QStringList playlistIds;
    for (const SearchResult &playlist : m_artistPlaylists) {
        const QString id = playlist.playlistId.isEmpty()
                               ? playlist.id
                               : playlist.playlistId;
        if (!id.isEmpty() && !playlistIds.contains(id)) {
            playlistIds.push_back(id);
        }
    }
    if (playlistIds.isEmpty()) {
        m_artistExpanded = true;
        m_collectionView->setShowAllAvailable(false);
        updateArtistTracksView();
        return;
    }
    m_artistAllLoading = true;
    m_artistAllChannel = header.channelId;
    m_artistAllTracks.clear();
    m_artistAllPending = playlistIds.size();
    m_collectionView->setShowAllAvailable(false);
    m_collectionView->setLoading(true);
    setStatus(tr("Loading all tracks…"));
    for (const QString &id : playlistIds) {
        m_artistAllService->fetchPlaylist(id);
    }
}

void StreamingPage::finishArtistLoad() {
    QSet<QString> allowedChannels;
    if (!m_artistId.isEmpty()) {
        allowedChannels.insert(m_artistId);
    }
    if (!m_artistHeader.channelId.isEmpty()) {
        allowedChannels.insert(m_artistHeader.channelId);
    }
    for (const SearchResult &playlist : m_artistPlaylists) {
        if (!playlist.channelId.isEmpty()) {
            allowedChannels.insert(playlist.channelId);
        }
    }

    // The channel browse result is authoritative: it is fetched by channel
    // ID, so it cannot mix two artists with the same name. Search results are
    // only supplements when they carry the same channel ID.
    QVector<SearchResult> merged;
    QSet<QString> seen;
    for (const SearchResult &result : m_artistVideos) {
        if (!result.id.isEmpty()) {
            seen.insert(result.id);
            merged.push_back(result);
        }
    }
    for (const SearchResult &result : m_artistSearchRaw) {
        if (!result.id.isEmpty() && !seen.contains(result.id) &&
            allowedChannels.contains(result.channelId)) {
            seen.insert(result.id);
            merged.push_back(result);
        }
    }
    m_artistVideos = merged;
    m_artistExpanded = false;
    if (m_artistHeader.id == m_artistId) {
        updateArtistTracksView();
    }

    m_collectionView->setLoading(false);
    setSearchBusy(false);
    if (m_playArtistWhenLoaded) {
        m_playArtistWhenLoaded = false;
        if (!m_artistVideos.isEmpty()) {
            startStreamCollection(m_artistVideos);
        } else if (!m_artistPlaylists.isEmpty()) {
            openPlaylist(m_artistPlaylists.first(), true, true);
        }
    }
    if (m_artistVideos.isEmpty() && m_artistPlaylists.isEmpty()) {
        setStatus(tr("This artist has no videos or albums."));
    } else {
        setStatus({});
    }
}

void StreamingPage::showArtistCached() {
    if (m_artistHeader.id.isEmpty()) {
        showHome();
        return;
    }
    m_playlistFromArtist = false;
    m_playlistFromSearch = false;
    m_collectionView->setHeader(m_artistHeader);
    updateArtistTracksView();
    m_collectionView->setPlaylists(m_artistPlaylists);
    m_collectionView->setLoading(false);
    m_stack->setCurrentWidget(m_collectionView);
    setStatus({});
}

void StreamingPage::openPlaylist(const SearchResult &playlist,
                                 bool fromArtist,
                                 bool autoPlay) {
    const QString id =
        playlist.playlistId.isEmpty() ? playlist.id : playlist.playlistId;
    if (id.isEmpty()) {
        return;
    }
    m_playPlaylistWhenLoaded = autoPlay;
    StreamHistory::addPlaylist(playlist);
    m_playlistFromArtist = fromArtist;
    m_playlistFromSearch =
        (!fromArtist && m_stack->currentWidget() == m_searchView);
    m_playlistHeader = playlist;
    m_playlistHeader.playlistId = id;
    m_playlistId = id;
    m_playlistTracks.clear();
    m_collectionView->setHeader(m_playlistHeader);
    m_collectionView->setTracks({});
    m_collectionView->setPlaylists({});
    m_collectionView->setLoading(true);
    setSearchContextVisible(false);
    m_stack->setCurrentWidget(m_collectionView);
    setSearchBusy(true);
    setStatus(tr("Loading playlist…"));
    m_browseService->fetchPlaylist(id);
}

void StreamingPage::handlePlayRequest(const SearchResult &result) {
    switch (result.kind) {
    case SearchResult::Kind::Track:
        playTrack(result);
        break;
    case SearchResult::Kind::Artist:
        playArtist(result);
        break;
    case SearchResult::Kind::Playlist:
        playPlaylistResult(result);
        break;
    }
}

void StreamingPage::playArtist(const SearchResult &artist) {
    openArtist(artist, true);
}

void StreamingPage::playPlaylistResult(const SearchResult &playlist) {
    openPlaylist(playlist, false, true);
}

void StreamingPage::startStreamCollection(
    const QVector<SearchResult> &tracks) {
    QVector<SearchResult> playable;
    for (const SearchResult &track : tracks) {
        if (track.kind == SearchResult::Kind::Track && !track.url.isEmpty()) {
            playable.push_back(track);
        }
    }
    if (playable.isEmpty()) {
        return;
    }
    m_streamContext = playable;
    qWarning("stream: collection tracks=%d shuffle=%d", playable.size(),
             m_shuffle ? 1 : 0);
    if (m_shuffle) {
        std::mt19937 rng(static_cast<unsigned>(
            QRandomGenerator::global()->generate()));
        std::shuffle(playable.begin(), playable.end(), rng);
    }
    const SearchResult first = playable.takeFirst();
    m_streamQueue.clear();
    for (const SearchResult &track : playable) {
        m_streamQueue.push_back(track);
    }
    updateQueuePanel();
    emit queueChanged(m_streamQueue.size());
    playTrack(first);
}

void StreamingPage::playTrack(const SearchResult &track) {
    if (track.kind != SearchResult::Kind::Track || track.url.isEmpty()) {
        return;
    }
    if (track.id == m_playingId) {
        emit streamToggleRequested();
        return;
    }
    if (m_streamHistoryIndex + 1 < m_streamHistory.size()) {
        m_streamHistory.resize(m_streamHistoryIndex + 1);
    }
    if (m_streamHistory.isEmpty() ||
        m_streamHistory.last().id != track.id) {
        m_streamHistory.push_back(track);
        if (m_streamHistory.size() > 50) {
            m_streamHistory.removeFirst();
        }
        m_streamHistoryIndex = m_streamHistory.size() - 1;
        emit streamHistoryChanged(canPlayPreviousStream());
    }
#ifndef Q_OS_WIN
    if (!m_playingId.isEmpty() && !m_transitioning) {
        // Keep the old track audible while the new one is prepared.
        startPreload(track, true);
        return;
    }
#endif
    playTrackInternal(track);
}

void StreamingPage::playTrackInternal(const SearchResult &track) {
    if (track.kind != SearchResult::Kind::Track || track.url.isEmpty()) {
        return;
    }
    if (track.id == m_playingId) {
        emit streamToggleRequested();
        return;
    }
    qWarning("stream: play id=%s title=%s queue=%d",
             track.id.toUtf8().constData(),
             track.title.toUtf8().constData(), m_streamQueue.size());
    m_suggestTimer->stop();
    m_suppressCancel = true;
    m_service->cancel();
    m_suppressCancel = false;
    m_fastStream->stop();
    m_preloadStream->stop();
    m_preloadResolveService->cancel();
    stopWatchdog();
    m_preloadReady = false;
    m_preloading = false;
    m_transitioning = false;
    emit streamPreloadCleared();
    if (!m_playingId.isEmpty()) {
        setTrackPlaying(m_playingId, false);
    }
    m_pending = track;
    m_pendingDuration = static_cast<int>(track.duration);
    m_playWhenReady = true;
    m_fastRetryTried = false;
    m_fastPlaybackStarted = false;
    m_resolvedUrl.clear();
    m_resolvedForUrl.clear();
    m_fastUrl.clear();
    m_resolvingForUrl = track.url;
    m_cachedUrl.clear();
    m_cachedPath.clear();
    m_cacheDownloading = false;
    m_cacheDownloadRetries = 0;
    m_downloadForUrl.clear();
    m_bgCacheUrl.clear();
    m_bgCachePath.clear();
    m_bgCacheKey.clear();
    m_bgCacheDownloading = false;
    m_bgCacheRetries = 0;
    m_pendingCacheSeekMs = -1;
    m_cacheStartTimer->stop();
    m_cacheService->cancel();
    m_playingId.clear();
    m_playingState = false;
    if (startCachedPlayback()) {
        return;
    }
    m_resolving = true;
    setTrackBusy(track.id, true);
    setStatus(tr("Preparing stream…"));
    m_service->resolveAudioHls(track.url, cookiesPath());
}

void StreamingPage::startWatchdog(int mode) {
    m_watchdogMode = mode;
    m_watchdog->start(15000);
}

void StreamingPage::stopWatchdog() {
    m_watchdog->stop();
    m_watchdogMode = 0;
}

void StreamingPage::handleWatchdogTimeout() {
    const int mode = m_watchdogMode;
    m_watchdogMode = 0;
    m_preloading = false;
    m_preloadReady = false;
    m_transitioning = false;
    m_preloadStream->stop();
    m_preloadResolveService->cancel();
    setTrackBusy(m_pending.id, false);
    setStatus(tr("Stream timed out. Recovering…"));
    if (mode == 3) {
        emit streamRecoveryRequested();
        if (!m_pending.url.isEmpty()) {
            const SearchResult restart = m_pending;
            m_pending = SearchResult();
            playTrackInternal(restart);
        }
        return;
    }
    if (mode == 1 && m_preloadManual && !m_preloadTrack.url.isEmpty()) {
        const SearchResult target = m_preloadTrack;
        m_preloadManual = false;
        playTrackInternal(target);
        return;
    }
    // Seek/preload timeout: keep the current playback and drop the pending
    // transition.
    m_preloadTrack = SearchResult();
    m_preloadPath.clear();
    m_preloadManual = false;
    m_preloadRepeatOne = false;
}

void StreamingPage::handleFastStreamReady(FastStreamService *source,
                                          const QString &path,
                                          int durationSeconds) {
    if (source != m_fastStream) {
        source->stop();
        return;
    }
    if (m_fastUrl != m_pending.url) {
        return;
    }
    if (durationSeconds > 0) {
        m_pendingDuration = durationSeconds;
    }
    qWarning("stream: fast ready id=%s", m_pending.id.toUtf8().constData());
    m_fastPlaybackStarted = true;
    m_playingId = m_pending.id;
    m_playingState = true;
    recordPlaybackHistory();
    setTrackBusy(m_pending.id, false);
    setTrackPlaying(m_pending.id, true);
    setSearchBusy(false);
    setStatus(tr("Playing: %1").arg(m_pending.title));
    emit streamReady(path, m_pending.title, m_pending.uploader,
                     m_pendingDuration, 0, m_pending.thumbnail);
}

void StreamingPage::handleFastStreamFailed(FastStreamService *source,
                                           const QString &message) {
    if (source != m_fastStream) {
        return;
    }
    if (m_fastUrl != m_pending.url) {
        return;
    }
    qWarning("stream: fast failed id=%s: %s",
             m_pending.id.toUtf8().constData(),
             message.toUtf8().constData());
    m_fastUrl.clear();
    m_resolvedUrl.clear();
    m_resolvedForUrl.clear();
    if (m_fastPlaybackStarted) {
        m_fastPlaybackStarted = false;
        m_playingState = false;
        m_playWhenReady = true;
        startCacheDownload();
        return;
    }
    if (m_playWhenReady && !m_fastRetryTried) {
        m_fastRetryTried = true;
        setStatus(tr("Retrying stream…"));
        m_service->resolveAudioHls(m_pending.url, cookiesPath());
        return;
    }
    m_playWhenReady = false;
    setTrackBusy(m_pending.id, false);
    setSearchBusy(false);
    setStatus(tr("Stream unavailable: %1")
                  .arg(friendlyStreamError(message)));
}

void StreamingPage::startPreload(const SearchResult &track,
                                  bool manual,
                                  bool repeatOne) {
    if (track.kind != SearchResult::Kind::Track || track.url.isEmpty() ||
        m_transitioning) {
        return;
    }
    if (track.id == m_playingId && !repeatOne) {
        return;
    }
    emit streamPreloadCleared();
    m_preloadStream->stop();
    m_preloadTrack = track;
    m_preloadManual = manual;
    m_preloadRepeatOne = repeatOne;
    m_preloading = true;
    m_preloadReady = false;
    m_preloadPath.clear();
    m_preloadResolvedUrl.clear();
    m_preloadCachedPath.clear();
    m_preloadCachedUrl.clear();
    m_preloadDuration = static_cast<int>(track.duration);
    setTrackBusy(track.id, true);

    const QString cached = StreamCache::pathFor(
        StreamCache::keyFor(track.id, track.url));
    if (!cached.isEmpty()) {
        m_preloading = false;
        m_preloadReady = true;
        m_preloadPath = cached;
        m_preloadCachedPath = cached;
        m_preloadCachedUrl = track.url;
        setTrackBusy(track.id, false);
        emit streamPreloaded(cached, track.title, track.uploader,
                             m_preloadDuration, track.thumbnail, manual);
        return;
    }

    startWatchdog(1);
    m_preloadResolveService->resolveAudioHls(track.url, cookiesPath());
}

void StreamingPage::handlePreloadBuffered(const QString &path,
                                          int durationSeconds) {
    if (!m_preloading) {
        return;
    }
    stopWatchdog();
    m_preloading = false;
    m_preloadReady = true;
    m_preloadPath = path;
    if (durationSeconds > 0) {
        m_preloadDuration = durationSeconds;
    }
    setTrackBusy(m_preloadTrack.id, false);
    emit streamPreloaded(path, m_preloadTrack.title,
                         m_preloadTrack.uploader, m_preloadDuration,
                         m_preloadTrack.thumbnail, m_preloadManual);
}

void StreamingPage::maybePreload(qint64 positionMs) {
#ifdef Q_OS_WIN
    Q_UNUSED(positionMs);
    return;
#endif
    if (m_playingId.isEmpty() || m_pending.url.isEmpty() ||
        m_pendingDuration <= 0 ||
        m_preloading || m_preloadReady || m_transitioning) {
        return;
    }
    const qint64 remaining =
        m_pendingDuration * 1000LL - qMax<qint64>(0, positionMs);
    if (remaining > 10000 || remaining <= 1000) {
        return;
    }
    if (m_repeatMode == QStringLiteral("one")) {
        startPreload(m_pending, false, true);
        return;
    }
    if (m_streamQueue.isEmpty()) {
        return;
    }
    const SearchResult next = m_streamQueue.first();
    if (next.id != m_playingId) {
        startPreload(next, false);
    }
}

bool StreamingPage::beginPreloadedTransition() {
    if (!m_preloadReady || !m_preloadStream || m_transitioning) {
        return false;
    }
    const QString oldId = m_playingId;
    if (!m_preloadManual && !m_preloadRepeatOne) {
        for (int i = 0; i < m_streamQueue.size(); ++i) {
            if (m_streamQueue.at(i).id == m_preloadTrack.id) {
                m_streamQueue.removeAt(i);
                break;
            }
        }
        m_pending = m_preloadTrack;
        recordPlaybackHistory();
        updateQueuePanel();
        emit queueChanged(m_streamQueue.size());
    }
    if (!oldId.isEmpty() && oldId != m_preloadTrack.id) {
        setTrackPlaying(oldId, false);
    }
    // The outgoing track no longer needs its background cache; the new track
    // starts a fresh one after the transition (unless it is already cached).
    m_cacheStartTimer->stop();
    m_bgCacheDownloading = false;
    m_bgCacheRetries = 0;
    m_pendingCacheSeekMs = -1;
    m_cacheService->cancel();
    m_bgCacheUrl.clear();
    m_bgCachePath.clear();
    m_bgCacheKey.clear();
    m_pending = m_preloadTrack;
    m_pendingDuration = m_preloadDuration;
    m_playingId = m_preloadTrack.id;
    m_playingState = true;
    m_cachedPath = m_preloadCachedPath;
    m_cachedUrl = m_preloadCachedUrl;
    setTrackPlaying(m_playingId, true);
    m_transitioning = true;
    m_preloadReady = false;
    startWatchdog(3);
    setStatus(tr("Playing: %1").arg(m_preloadTrack.title));
    return true;
}

void StreamingPage::finishPreloadedTransition() {
    if (!m_transitioning) {
        return;
    }
    FastStreamService *old = m_fastStream;
    m_fastStream = m_preloadStream;
    m_preloadStream = old;
    if (m_preloadStream) {
        m_preloadStream->stop();
    }
    m_resolvedUrl = m_preloadResolvedUrl;
    m_resolvedForUrl = m_pending.url;
    m_fastUrl = m_pending.url;
    m_fastPlaybackStarted = true;
    m_transitioning = false;
    stopWatchdog();
    m_preloadTrack = SearchResult();
    m_preloadPath.clear();
    m_preloadResolvedUrl.clear();
    m_preloadDuration = 0;
    m_preloadManual = false;
    m_preloadRepeatOne = false;
    m_preloadCachedPath.clear();
    m_preloadCachedUrl.clear();
}

void StreamingPage::startFastPlayback() {
    if (!m_resolvedUrl.isEmpty() && m_resolvedForUrl != m_pending.url) {
        qWarning("stream: resolved URL belongs to another track");
        m_resolvedUrl.clear();
    }
#ifdef Q_OS_WIN
    // Windows has no POSIX FIFO. Play from the full background cache until a
    // native pipe path is implemented.
    startCacheDownload();
    return;
#endif
    if (m_resolvedUrl.isEmpty()) {
        startCacheDownload();
        return;
    }
    if (m_fastStream->isRunning() && m_fastUrl != m_pending.url) {
        m_fastStream->stop();
    }
    m_fastUrl = m_pending.url;
    m_fastPlaybackStarted = false;
    setTrackBusy(m_pending.id, true);
    setStatus(tr("Starting stream…"));
    m_fastStream->start(m_resolvedUrl, m_streamDir, m_pending.id,
                        m_pendingDuration);
}

void StreamingPage::startCacheDownload() {
    if (m_pending.url.isEmpty()) {
        return;
    }
    if (m_cacheDownloading && m_cachedUrl == m_pending.url) {
        return;
    }
    m_suppressCancel = true;
    m_service->cancel();
    m_suppressCancel = false;
    m_resolving = false;
    m_fastStream->stop();
    m_fastUrl.clear();
    m_cacheDownloading = true;
    m_downloadForUrl = m_pending.url;
    m_playWhenReady = true;
    m_cachedPath.clear();
    m_cachedUrl = m_pending.url;
    setTrackBusy(m_pending.id, true);
    setStatus(tr("Buffering stream…"));
    m_service->downloadForStream(m_pending.url, m_streamDir, cookiesPath());
}

void StreamingPage::fallbackToCache() {
    if (m_pending.url.isEmpty()) {
        return;
    }
    m_preloading = false;
    m_preloadReady = false;
    m_preloadStream->stop();
    if (!m_cachedPath.isEmpty() && m_cachedUrl == m_pending.url) {
        m_playingId = m_pending.id;
        m_playingState = true;
        recordPlaybackHistory();
        setTrackPlaying(m_playingId, true);
        emit streamReady(m_cachedPath, m_pending.title, m_pending.uploader,
                         m_pendingDuration, 0, m_pending.thumbnail);
        return;
    }
    m_playWhenReady = true;
    startCacheDownload();
}

void StreamingPage::addToQueue(const SearchResult &track) {
    if (track.kind != SearchResult::Kind::Track || track.url.isEmpty()) {
        return;
    }
    m_streamQueue.push_back(track);
    updateQueuePanel();
    emit queueChanged(m_streamQueue.size());
    setStatus(tr("Added to queue: %1").arg(track.title));
}

void StreamingPage::downloadTrack(const SearchResult &track) {
    if (track.kind != SearchResult::Kind::Track || track.url.isEmpty()) {
        return;
    }
    if (m_downloading) {
        setStatus(tr("A download is already in progress."), false);
        return;
    }
    if (!QDir().mkpath(m_musicDir)) {
        QMessageBox::warning(
            this, tr("Download error"),
            tr("Could not create the download folder: %1").arg(m_musicDir));
        return;
    }
    m_downloading = true;
    m_downloadingId = track.id;
    setTrackDownload(track.id, 0);
    setStatus(tr("Downloading: %1").arg(track.title), false);
    m_downloadService->download(
        track.uploader.isEmpty()
            ? track.title
            : track.uploader + QStringLiteral(" - ") + track.title,
        m_musicDir, cookiesPath());
}

void StreamingPage::recordPlaybackHistory() {
    if (m_pending.id.isEmpty()) {
        return;
    }
    StreamHistory::addTrack(m_pending);
    if (!m_pending.channelId.isEmpty() && !m_pending.uploader.isEmpty()) {
        SearchResult artist;
        artist.kind = SearchResult::Kind::Artist;
        artist.id = m_pending.channelId;
        artist.channelId = m_pending.channelId;
        artist.title = m_pending.uploader;
        artist.uploader = m_pending.uploader;
        artist.thumbnail = m_pending.thumbnail;
        artist.url = QStringLiteral("https://www.youtube.com/channel/") +
                     artist.channelId + QStringLiteral("/videos");
        StreamHistory::addArtist(artist);
    }
}

void StreamingPage::setTrackBusy(const QString &id, bool busy) {
    if (id.isEmpty()) {
        return;
    }
    m_overlay->setBusyFor(id, busy);
    m_searchView->setBusyFor(id, busy);
    m_collectionView->setBusyFor(id, busy);
}

void StreamingPage::setTrackDownload(const QString &id, int progress) {
    if (id.isEmpty()) {
        return;
    }
    m_overlay->setDownloadProgress(id, progress);
    m_searchView->setDownloadProgress(id, progress);
    m_collectionView->setDownloadProgress(id, progress);
}

void StreamingPage::setTrackPlaying(const QString &id, bool playing) {
    if (id.isEmpty()) {
        return;
    }
    m_overlay->setPlaying(id, playing);
    m_searchView->setPlaying(id, playing);
    m_collectionView->setPlaying(id, playing);
    m_homeView->setPlaying(id, playing);
}

void StreamingPage::setPlaybackPlaying(bool playing) {
    m_playingState = playing;
    if (!m_playingId.isEmpty()) {
        setTrackPlaying(m_playingId, playing);
    }
}

bool StreamingPage::setPlaybackEnded() {
    if (m_transitioning || (m_preloading && m_preloadManual)) {
        qWarning("stream: end swallowed transitioning=%d preloading=%d",
                 m_transitioning ? 1 : 0, m_preloading ? 1 : 0);
        return true;
    }
    m_playingState = false;
    if (!m_playingId.isEmpty()) {
        setTrackPlaying(m_playingId, false);
    }
    const SearchResult finished = m_pending;
    m_playingId.clear();
    if (m_repeatMode == QStringLiteral("one") && !finished.url.isEmpty()) {
        playTrackInternal(finished);
        return true;
    }
    if (playNextQueued()) {
        return true;
    }
    if (m_repeatMode == QStringLiteral("all") && !m_streamContext.isEmpty()) {
        startStreamCollection(m_streamContext);
        return true;
    }
    return false;
}

void StreamingPage::setShuffleEnabled(bool enabled) {
    if (m_shuffle == enabled) {
        return;
    }
    m_shuffle = enabled;
    if (enabled && !m_streamQueue.isEmpty()) {
        std::mt19937 rng(static_cast<unsigned>(
            QRandomGenerator::global()->generate()));
        std::shuffle(m_streamQueue.begin(), m_streamQueue.end(), rng);
        updateQueuePanel();
        emit queueChanged(m_streamQueue.size());
    }
}

void StreamingPage::setRepeatMode(const QString &mode) {
    m_repeatMode = (mode == QStringLiteral("all") ||
                    mode == QStringLiteral("one"))
                       ? mode
                       : QStringLiteral("off");
}

bool StreamingPage::playNextQueued() {
    if (m_streamQueue.isEmpty()) {
        return false;
    }
    const SearchResult next = m_streamQueue.takeFirst();
    updateQueuePanel();
    emit queueChanged(m_streamQueue.size());
    playTrack(next);
    return true;
}

bool StreamingPage::playPreviousStream() {
    if (!canPlayPreviousStream()) {
        return false;
    }
    --m_streamHistoryIndex;
    const SearchResult previous = m_streamHistory.at(m_streamHistoryIndex);
    emit streamHistoryChanged(canPlayPreviousStream());
    playTrackInternal(previous);
    return true;
}

bool StreamingPage::canPlayPreviousStream() const {
    return m_streamHistoryIndex > 0 &&
           m_streamHistoryIndex < m_streamHistory.size();
}

void StreamingPage::demoPlaylistCardPlay() {
    if (m_artistHeader.kind == SearchResult::Kind::Artist) {
        m_collectionView->demoClickFirstPlaylistPlay();
    }
}

void StreamingPage::demoShowAll() {
    if (m_artistHeader.kind == SearchResult::Kind::Artist) {
        showAllArtistTracks(m_artistHeader);
    }
}

void StreamingPage::playHomeFirst() {
    if (!m_homeRecentTracks.isEmpty()) {
        playTrack(m_homeRecentTracks.first());
    }
}

void StreamingPage::playAllCurrent() {
    if (m_stack->currentWidget() != m_collectionView) {
        return;
    }
    if (m_collectionView->header().kind == SearchResult::Kind::Playlist) {
        startStreamCollection(m_playlistTracks);
    } else if (!m_artistVideos.isEmpty()) {
        startStreamCollection(m_artistVideos);
    } else if (!m_artistPlaylists.isEmpty()) {
        openPlaylist(m_artistPlaylists.first(), true, true);
    }
}

void StreamingPage::startBackgroundCache() {
    if (m_pending.url.isEmpty() || m_pending.id.isEmpty()) {
        return;
    }
    if (qEnvironmentVariableIsSet("OCTOBEAT_TRACE_STREAM")) {
        qWarning("stream: start background cache url=%s downloading=%d path=%s",
                 m_pending.url.toUtf8().constData(),
                 m_bgCacheDownloading ? 1 : 0,
                 m_bgCachePath.toUtf8().constData());
    }
    if (!m_bgCachePath.isEmpty() && m_bgCacheUrl == m_pending.url &&
        QFileInfo::exists(m_bgCachePath)) {
        if (m_pendingCacheSeekMs >= 0) {
            const qint64 target = m_pendingCacheSeekMs;
            m_pendingCacheSeekMs = -1;
            switchToCachedSeek(target);
        }
        return;
    }
    const QString logicalUrl = m_pending.url;
    const QString key = StreamCache::keyFor(m_pending.id, logicalUrl);
    const QString existing = StreamCache::pathFor(key);
    if (!existing.isEmpty()) {
        m_bgCacheUrl = logicalUrl;
        m_bgCachePath = existing;
        m_bgCacheKey = key;
        if (m_pendingCacheSeekMs >= 0) {
            const qint64 target = m_pendingCacheSeekMs;
            m_pendingCacheSeekMs = -1;
            switchToCachedSeek(target);
        }
        return;
    }
    if (m_bgCacheDownloading && m_bgCacheUrl == logicalUrl) {
        return;
    }
    m_bgCacheDownloading = false;
    m_cacheService->cancel();
    m_bgCacheUrl = logicalUrl;
    m_bgCachePath.clear();
    m_bgCacheKey = key;
    m_bgCacheDownloading = true;
    m_cacheService->cacheStream(logicalUrl, StreamCache::directory(), key,
                                cookiesPath());
}

bool StreamingPage::startCachedPlayback() {
    const QString path = StreamCache::pathFor(
        StreamCache::keyFor(m_pending.id, m_pending.url));
    if (path.isEmpty()) {
        return false;
    }
    m_resolving = false;
    m_playWhenReady = false;
    m_fastPlaybackStarted = true;
    m_cachedPath = path;
    m_cachedUrl = m_pending.url;
    m_playingId = m_pending.id;
    m_playingState = true;
    recordPlaybackHistory();
    setTrackBusy(m_pending.id, false);
    setTrackPlaying(m_playingId, true);
    setSearchBusy(false);
    setStatus(tr("Playing: %1").arg(m_pending.title));
    emit streamReady(path, m_pending.title, m_pending.uploader,
                     m_pendingDuration, 0, m_pending.thumbnail);
    return true;
}

void StreamingPage::switchToCachedSeek(qint64 targetMs) {
    const QString path = m_bgCachePath;
    if (path.isEmpty() || !QFileInfo::exists(path)) {
        setStatus(tr("Seek is not available for this stream."));
        return;
    }
    stopWatchdog();
    m_preloading = false;
    m_preloadReady = false;
    m_transitioning = false;
    m_fastStream->stop();
    m_preloadStream->stop();
    m_preloadResolveService->cancel();
    m_cacheStartTimer->stop();
    emit streamPreloadCleared();
    m_cachedPath = path;
    m_cachedUrl = m_pending.url;
    m_playingId = m_pending.id;
    m_playingState = true;
    setTrackBusy(m_pending.id, false);
    setTrackPlaying(m_playingId, true);
    setStatus(tr("Playing: %1").arg(m_pending.title));
    emit streamReady(path, m_pending.title, m_pending.uploader,
                     m_pendingDuration, qMax<qint64>(0, targetMs),
                     m_pending.thumbnail);
}

void StreamingPage::seekStream(qint64 milliseconds) {
    if (m_pending.url.isEmpty()) {
        return;
    }
    qint64 target = qMax<qint64>(0, milliseconds);
    if (m_pendingDuration > 0) {
        target = qMin<qint64>(target,
                              qMax<qint64>(0, m_pendingDuration * 1000LL - 500));
    }
    const bool fastRunning =
        m_fastStream && m_fastStream->isRunning();
    if (!m_cachedPath.isEmpty() && m_cachedUrl == m_pending.url &&
        !fastRunning) {
        // Playback already uses a normal local file: the engine seeks directly.
        emit streamLocalSeekRequested(target);
        return;
    }
    // A full background download makes seeking reliable: the engine jumps
    // inside a local file instead of restarting an HLS stream with an expired
    // URL.
    if (!m_bgCachePath.isEmpty() && m_bgCacheUrl == m_pending.url &&
        QFileInfo::exists(m_bgCachePath)) {
        switchToCachedSeek(target);
        return;
    }
    if (m_resolvedUrl.isEmpty() && !m_bgCacheDownloading) {
        setStatus(tr("Seeking is not available for this stream."));
        return;
    }
    if (m_preloading || m_preloadReady) {
        m_preloading = false;
        m_preloadReady = false;
        m_preloadStream->stop();
        m_preloadResolveService->cancel();
        emit streamPreloadCleared();
    }
    if (m_bgCacheDownloading && m_bgCacheUrl == m_pending.url) {
        m_pendingCacheSeekMs = target;
        setTrackBusy(m_pending.id, true);
        setStatus(tr("Preparing seek…"));
        return;
    }
    // The cache has not started yet; keep the current audio and switch to the
    // local file as soon as the background download is ready.
    m_pendingCacheSeekMs = target;
    setTrackBusy(m_pending.id, true);
    setStatus(tr("Preparing seek…"));
    startBackgroundCache();
}

void StreamingPage::handleSearchKey(QKeyEvent *event) {
    switch (event->key()) {
    case Qt::Key_Return:
    case Qt::Key_Enter: {
        if (m_overlay->panelVisible()) {
            if (m_overlay->activateCurrent()) {
                hideOverlay();
                return;
            }
            hideOverlay();
        }
        openFullSearch(m_search->text());
        return;
    }
    case Qt::Key_Down:
        if (!m_overlay->panelVisible()) {
            showHistoryOverlay();
        }
        m_overlay->moveSelection(1);
        return;
    case Qt::Key_Up:
        if (!m_overlay->panelVisible()) {
            showHistoryOverlay();
        }
        m_overlay->moveSelection(-1);
        return;
    case Qt::Key_Escape:
        hideOverlay();
        return;
    default:
        break;
    }
}

bool StreamingPage::eventFilter(QObject *watched, QEvent *event) {
    if (watched == m_search && event->type() == QEvent::FocusIn) {
        if (m_search->text().trimmed().isEmpty()) {
            QTimer::singleShot(0, this, &StreamingPage::showHistoryOverlay);
        }
    }
    if (watched == m_search && event->type() == QEvent::FocusOut) {
        QTimer::singleShot(0, this, [this] {
            QWidget *focus = QApplication::focusWidget();
            if (focus != m_search &&
                !(m_overlay && focus && m_overlay->isAncestorOf(focus))) {
                hideOverlay();
            }
        });
    }
    if (watched == m_search && event->type() == QEvent::KeyPress) {
        auto *keyEvent = static_cast<QKeyEvent *>(event);
        const int key = keyEvent->key();
        if (key == Qt::Key_Return || key == Qt::Key_Enter ||
            key == Qt::Key_Down || key == Qt::Key_Up ||
            key == Qt::Key_Escape) {
            handleSearchKey(keyEvent);
            return true;
        }
    }
    if (event->type() == QEvent::MouseButtonPress && m_overlay &&
        m_overlay->panelVisible()) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        const QPoint global = mouse->globalPosition().toPoint();
        const QRect searchRect(m_searchBar->mapToGlobal(QPoint(0, 0)),
                               m_searchBar->size());
        const QRect overlayRect(m_overlay->mapToGlobal(QPoint(0, 0)),
                                m_overlay->size());
        if (!searchRect.contains(global) && !overlayRect.contains(global)) {
            hideOverlay();
        }
    }
    return QWidget::eventFilter(watched, event);
}

void StreamingPage::searchFor(const QString &query) {
    m_search->setText(query);
    openFullSearch(query);
}

void StreamingPage::playCurrent() {
    for (const SearchResult &result : m_lastSearchResults) {
        if (result.kind == SearchResult::Kind::Track) {
            playTrack(result);
            return;
        }
    }
}

void StreamingPage::downloadCurrent() {
    for (const SearchResult &result : m_lastSearchResults) {
        if (result.kind == SearchResult::Kind::Track) {
            downloadTrack(result);
            return;
        }
    }
}

void StreamingPage::demoHoverFirstResult() {
    if (m_searchView && m_stack->currentWidget() == m_searchView) {
        m_searchView->setFocus();
    }
}

void StreamingPage::demoOpenArtist(const QString &channelId,
                                   const QString &title) {
    SearchResult artist;
    artist.kind = SearchResult::Kind::Artist;
    artist.id = channelId;
    artist.channelId = channelId;
    artist.title = title;
    artist.url = QStringLiteral("https://www.youtube.com/channel/") +
                 channelId + QStringLiteral("/videos");
    openArtist(artist);
}

void StreamingPage::demoOpenPlaylist(const QString &playlistId,
                                     const QString &title) {
    SearchResult playlist;
    playlist.kind = SearchResult::Kind::Playlist;
    playlist.id = playlistId;
    playlist.playlistId = playlistId;
    playlist.title = title;
    playlist.url = QStringLiteral("https://www.youtube.com/playlist?list=") +
                   playlistId;
    openPlaylist(playlist, false);
}

void StreamingPage::demoFilteredSearch(const QString &query, int filter) {
    m_search->setText(query);
    m_currentQuery = query;
    setSearchContextVisible(true, tr("Results for “%1”").arg(query));
    m_stack->setCurrentWidget(m_searchView);
    m_searchView->setQuery(query);
    const auto searchFilter = static_cast<YouTubeSearchService::Filter>(filter);
    m_searchView->setFilter(searchFilter);
    runFullSearch(searchFilter);
}

void StreamingPage::demoQueue(const QString &query) {
    showHome();
    auto *service = new YouTubeSearchService(this);
    connect(service, &YouTubeSearchService::finished, this,
            [this, service](const QVector<SearchResult> &results) {
                service->deleteLater();
                int added = 0;
                for (const SearchResult &result : results) {
                    if (result.kind != SearchResult::Kind::Track) {
                        continue;
                    }
                    m_streamQueue.push_back(result);
                    if (++added >= 4) {
                        break;
                    }
                }
                updateQueuePanel();
                emit queueChanged(m_streamQueue.size());
                m_queuePanel->openAt(m_queueButton);
            });
    connect(service, &YouTubeSearchService::failed, this,
            [service](const QString &) { service->deleteLater(); });
    service->search(query, YouTubeSearchService::Filter::Tracks, 8);
}

void StreamingPage::demoSuggest(const QString &query) {
    m_search->setText(query);
    m_search->setFocus();
    m_suggestTimer->stop();
    if (query.trimmed().isEmpty()) {
        showHistoryOverlay();
        return;
    }
    m_suggestQuery = query.trimmed();
    setSearchBusy(true);
    m_suggestService->search(query, YouTubeSearchService::Filter::All, 5);
}

QString StreamingPage::cookiesPath() const {
    const QStringList candidates = {
        QDir(m_dataDir).filePath(QStringLiteral("cookies.txt")),
        QDir(m_musicDir).filePath(QStringLiteral("cookies.txt")),
    };
    for (const QString &candidate : candidates) {
        if (QFileInfo(candidate).isFile()) {
            return candidate;
        }
    }
    return {};
}
