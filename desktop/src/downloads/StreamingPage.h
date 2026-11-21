#pragma once

#include <QHash>
#include <QPoint>
#include <QVector>
#include <QWidget>

#include "SearchResult.h"
#include "YouTubeSearchService.h"

class FastStreamService;
class QLabel;
class QLineEdit;
class QPushButton;
class QStackedWidget;
class QToolButton;
class QTimer;
class RemoteImageCache;
class SpinnerWidget;
class StreamCollectionView;
class StreamHomeView;
class StreamQueuePanel;
class StreamSearchOverlay;
class StreamSearchView;
class YouTubeBrowseService;
class SomeDlService;
class YtDlpService;

class StreamingPage : public QWidget {
    Q_OBJECT

public:
    StreamingPage(const QString &musicDir,
                  const QString &dataDir,
                  QWidget *parent = nullptr);
    ~StreamingPage() override;

    void searchFor(const QString &query);
    void playCurrent();
    void downloadCurrent();
    void demoHoverFirstResult();
    void demoSuggest(const QString &query);
    void demoOpenArtist(const QString &channelId, const QString &title);
    void demoOpenPlaylist(const QString &playlistId, const QString &title);
    void demoFilteredSearch(const QString &query, int filter);
    void demoQueue(const QString &query);
    void fallbackToCache();
    void setPlaybackPlaying(bool playing);
    bool setPlaybackEnded();
    void setShuffleEnabled(bool enabled);
    void setRepeatMode(const QString &mode);
    int queueSize() const { return m_streamQueue.size(); }
    bool playNextQueued();
    bool playPreviousStream();
    void playAllCurrent();
    void playHomeFirst();
    void demoShowAll();
    void demoPlaylistCardPlay();
    bool canPlayPreviousStream() const;
    void seekStream(qint64 milliseconds);
    void maybePreload(qint64 positionMs);
    bool beginPreloadedTransition();
    void finishPreloadedTransition();
    bool isTransitioning() const { return m_transitioning; }

signals:
    void streamReady(const QString &url,
                     const QString &title,
                     const QString &artist,
                     int durationSeconds,
                     qint64 startPositionMs,
                     const QString &thumbnail);
    void libraryChanged();
    void streamToggleRequested();
    void queueChanged(int size);
    void streamHistoryChanged(bool canPrevious);
    void streamLocalSeekRequested(qint64 positionMs);
    void streamPreloadCleared();
    void streamRecoveryRequested();
    void streamPreloaded(const QString &path,
                         const QString &title,
                         const QString &artist,
                         int durationSeconds,
                         const QString &thumbnail,
                         bool manual);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;

private:
    void buildUi();
    void updateSearchWidth();
    void positionOverlay();
    void positionQueueButton();
    void hideOverlay();
    void setSearchContextVisible(bool visible, const QString &text = {});
    void updateQueuePanel();

    void onSearchTextEdited(const QString &text);
    void requestSuggestions();
    void showHistoryOverlay();
    void openFullSearch(const QString &query);
    void runFullSearch(YouTubeSearchService::Filter filter);
    void showSearchHistoryView();
    void handleSearchKey(QKeyEvent *event);

    void showHome();
    void showSearchView();
    void openArtist(const SearchResult &artist, bool autoPlay = false);
    void finishArtistLoad();
    void finishExactSearch();
    void showAllArtistTracks(const SearchResult &header);
    void updateArtistTracksView();
    void openPlaylist(const SearchResult &playlist,
                      bool fromArtist,
                      bool autoPlay = false);
    void showArtistCached();
    void refreshHome();
    void updateHome();
    void removeFromHome(const SearchResult &result);
    void openResult(const SearchResult &result);
    void handlePlayRequest(const SearchResult &result);
    void playArtist(const SearchResult &artist);
    void playPlaylistResult(const SearchResult &playlist);
    void startStreamCollection(const QVector<SearchResult> &tracks);

    void playTrack(const SearchResult &track);
    void playTrackInternal(const SearchResult &track);
    void startFastPlayback();
    void startCacheDownload();
    void startBackgroundCache();
    bool startCachedPlayback();
    void switchToCachedSeek(qint64 targetMs);
    void downloadTrack(const SearchResult &track);
    void addToQueue(const SearchResult &track);
    void handleFastStreamReady(FastStreamService *source,
                               const QString &path,
                               int durationSeconds);
    void handleFastStreamFailed(FastStreamService *source,
                                const QString &message);
    void startPreload(const SearchResult &track,
                      bool manual,
                      bool repeatOne = false);
    void handlePreloadBuffered(const QString &path, int durationSeconds);
    void startWatchdog(int mode);
    void stopWatchdog();
    void handleWatchdogTimeout();
    void recordPlaybackHistory();
    void setTrackBusy(const QString &id, bool busy);
    void setTrackDownload(const QString &id, int progress);
    void setTrackPlaying(const QString &id, bool playing);
    void setStatus(const QString &status, bool autoHide = true);
    void setSearchBusy(bool busy);
    QString cookiesPath() const;

    QString m_musicDir;
    QString m_dataDir;
    QString m_streamDir;
    RemoteImageCache *m_images = nullptr;
    YouTubeSearchService *m_suggestService = nullptr;
    YouTubeSearchService *m_searchService = nullptr;
    YouTubeSearchService *m_artistSearchService = nullptr;
    YouTubeSearchService *m_homePlaylistService = nullptr;
    YouTubeBrowseService *m_browseService = nullptr;
    YouTubeBrowseService *m_searchBrowseService = nullptr;
    YouTubeBrowseService *m_artistAllService = nullptr;
    YtDlpService *m_service = nullptr;
    SomeDlService *m_downloadService = nullptr;
    FastStreamService *m_fastStream = nullptr;
    FastStreamService *m_preloadStream = nullptr;
    YtDlpService *m_preloadResolveService = nullptr;
    YtDlpService *m_cacheService = nullptr;

    QStackedWidget *m_stack = nullptr;
    StreamHomeView *m_homeView = nullptr;
    StreamSearchView *m_searchView = nullptr;
    StreamCollectionView *m_collectionView = nullptr;
    StreamSearchOverlay *m_overlay = nullptr;
    StreamQueuePanel *m_queuePanel = nullptr;
    QWidget *m_searchBar = nullptr;
    QWidget *m_searchContext = nullptr;
    QToolButton *m_searchBack = nullptr;
    QToolButton *m_homeButton = nullptr;
    QLabel *m_searchContextLabel = nullptr;
    QLineEdit *m_search = nullptr;
    QPushButton *m_searchButton = nullptr;
    QToolButton *m_queueButton = nullptr;
    SpinnerWidget *m_searchSpinner = nullptr;
    QTimer *m_statusTimer = nullptr;
    QTimer *m_watchdog = nullptr;
    QTimer *m_cacheStartTimer = nullptr;
    int m_watchdogMode = 0;
    QLabel *m_status = nullptr;
    QTimer *m_suggestTimer = nullptr;

    YouTubeSearchService::Filter m_searchFilter =
        YouTubeSearchService::Filter::All;
    QString m_currentQuery;
    QString m_suggestQuery;
    QString m_artistId;
    QString m_playlistId;
    SearchResult m_artistHeader;
    SearchResult m_playlistHeader;
    QVector<SearchResult> m_artistVideos;
    QVector<SearchResult> m_artistSearchRaw;
    QVector<SearchResult> m_artistPlaylists;
    QVector<SearchResult> m_playlistTracks;
    QVector<SearchResult> m_homeRecentTracks;
    QVector<SearchResult> m_homeArtists;
    QVector<SearchResult> m_homePlaylists;
    QVector<SearchResult> m_lastSearchResults;
    QVector<SearchResult> m_streamQueue;
    QVector<SearchResult> m_streamContext;
    bool m_shuffle = false;
    QString m_repeatMode = QStringLiteral("off");
    QVector<SearchResult> m_streamHistory;
    int m_streamHistoryIndex = -1;

    SearchResult m_pending;
    QString m_playingId;
    QString m_resolvedUrl;
    QString m_resolvedForUrl;
    QString m_resolvingForUrl;
    QString m_cachedUrl;
    QString m_cachedPath;
    QString m_downloadForUrl;
    QString m_bgCacheUrl;
    QString m_bgCachePath;
    QString m_bgCacheKey;
    QString m_fastUrl;
    QString m_downloadingId;
    int m_pendingDuration = 0;
    int m_artistPending = 0;
    bool m_playingState = false;
    bool m_resolving = false;
    bool m_cacheDownloading = false;
    int m_cacheDownloadRetries = 0;
    bool m_bgCacheDownloading = false;
    int m_bgCacheRetries = 0;
    qint64 m_pendingCacheSeekMs = -1;
    bool m_searchFallback = false;
    bool m_playWhenReady = false;
    bool m_suppressCancel = false;
    bool m_suppressSuggestions = false;
    bool m_fastRetryTried = false;
    bool m_fastPlaybackStarted = false;
    bool m_downloading = false;
    bool m_playlistFromArtist = false;
    bool m_artistFromSearch = false;
    bool m_playlistFromSearch = false;
    bool m_playArtistWhenLoaded = false;
    bool m_playPlaylistWhenLoaded = false;
    QHash<QString, SearchResult> m_exactArtists;
    QHash<QString, QVector<SearchResult>> m_exactAlbums;
    int m_exactPending = 0;
    QVector<SearchResult> m_searchBaseResults;
    bool m_preloading = false;
    bool m_preloadReady = false;
    bool m_preloadManual = false;
    bool m_preloadRepeatOne = false;
    bool m_transitioning = false;
    bool m_artistExpanded = false;
    bool m_artistAllLoading = false;
    int m_artistAllPending = 0;
    QString m_artistAllChannel;
    QVector<SearchResult> m_artistAllTracks;
    SearchResult m_preloadTrack;
    QString m_preloadPath;
    QString m_preloadResolvedUrl;
    QString m_preloadCachedPath;
    QString m_preloadCachedUrl;
    int m_preloadDuration = 0;
};
