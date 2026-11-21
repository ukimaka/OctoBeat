#pragma once

#include <QElapsedTimer>
#include <QMainWindow>
#include <QVector>

#include "core/CoreClient.h"

class QSystemTrayIcon;
class QTimer;
class QTabWidget;
class QVBoxLayout;

class LibraryPage;
class MiniPlayer;
class PlayerBar;
class PlaylistsPage;
class ProfilePage;
class SettingsPage;
class StreamingPage;
class TitleBar;
class AudioEngine;
class QToolButton;
class LyricsPanel;
class LyricsService;
class FullscreenLyrics;
class MprisService;

class MainWindow : public QMainWindow {
    Q_OBJECT

public:
    MainWindow(CoreClient *core,
               const QString &musicDir,
               const QString &dataDir,
               QWidget *parent = nullptr);
    ~MainWindow() override;

    void loadTracks();
    void playFirst();
    void autoScan();
    void setTabIndex(int index);
    void openPlaylist(qint64 playlistId);
    void demoDownloadSearch(const QString &query);
    void demoStreamingSearch(const QString &query);
    void demoStreamingPlay();
    void demoStreamingDownload();
    void demoStreamingHover();
    void demoStreamingSuggest(const QString &query);
    void demoStreamingArtist(const QString &channelId, const QString &title);
    void demoStreamingPlaylist(const QString &playlistId, const QString &title);
    void demoStreamingFilteredSearch(const QString &query, int filter);
    void demoStreamingQueue(const QString &query);
    void demoPlayAll();
    void demoHomePlay();
    void demoShowAll();
    void demoPlaylistCardPlay();
    void openDownloadDialog(const QString &query = {});
    void refreshAvatar();
    void importFiles();
    void importCsv();
    void importCsvFile(const QString &path);
    void showAddTracksDialog(qint64 playlistId);
    void addTrackToQueue(qint64 trackId);
    void showTrackContextMenu(const QPoint &globalPos,
                              qint64 trackId,
                              const QVector<qint64> &selectedIds,
                              bool playlistScope);
    void demoTrackContextMenu();
    void demoLyricsPanel();
    void demoKaraoke();
    void playTrackById(qint64 trackId);
    void showMini();
    QWidget *miniWidget() const;
    bool isPlaying() const;

protected:
    void closeEvent(QCloseEvent *event) override;
    void changeEvent(QEvent *event) override;
    void resizeEvent(QResizeEvent *event) override;
    bool eventFilter(QObject *watched, QEvent *event) override;
    bool nativeEvent(const QByteArray &eventType,
                     void *message,
                     qintptr *result) override;

private:
    void createResizeHandles();
    void positionResizeHandles();
    void scanLibrary(bool confirmLarge = true);
    void playTrack(qint64 trackId);
    void commitTrackStart(int index, bool startPlayback);
    bool prepareCrossfade();
    void completeCrossfade();
    void playPlaylist(qint64 playlistId);
    void playPlaylistTrack(qint64 playlistId, qint64 trackId);
    void playStream(const QString &url,
                    const QString &title,
                    const QString &artist,
                    int durationSeconds,
                    qint64 startPositionMs,
                    const QString &thumbnail);
    void playRandom();
    void playIndex(int index);
    void updateNextTrack();
    void nextTrack();
    void previousTrack();
    void onEndReached();
    void togglePlay();
    void applyVolume(int volume);
    void applyRepeatMode(const QString &mode);
    void applyShuffle(bool enabled);
    void updateMprisCapabilities();
    void updateStreamProgress();
    void handleStreamPreloaded(const QString &path,
                               const QString &title,
                               const QString &artist,
                               int durationSeconds,
                               const QString &thumbnail,
                               bool manual);
    void switchToPreloaded();
    void applyStreamMetadata(const QString &title,
                             const QString &artist,
                             int durationSeconds,
                             const QString &thumbnail);
    void pauseStreaming();
    void resumeStreaming();
    void freezeStreamClock();
    qint64 streamPositionMs() const;
    void onListeningTick();
    void flushListeningTime();
    void focusSearch();
    void showMiniPlayer();
    void applyWindowFrameState();
    QVector<Track> orderedLibraryTracks() const;
    void showKaraoke();
    void showLyricsOverlay();
    void syncLyricsOverlayContent();
    void startContext(const QVector<Track> &tracks,
                      int index,
                      const QString &name);
    void shuffleKeepingCurrent();
    void restoreOriginalOrder();
    Track trackForId(qint64 trackId) const;
    void addTrackToPlaylist(qint64 playlistId, qint64 trackId);
    void editTrackMetadata(qint64 trackId);
    void editTrackLyrics(qint64 trackId);
    void changeTrackCover(qint64 trackId);
    void removeTracksFromLibrary(const QVector<qint64> &trackIds);

    CoreClient *m_core = nullptr;
    QString m_musicDir;
    QString m_dataDir;
    AudioEngine *m_audio = nullptr;
    MprisService *m_mpris = nullptr;
    TitleBar *m_titleBar = nullptr;
    LibraryPage *m_library = nullptr;
    PlaylistsPage *m_playlists = nullptr;
    SettingsPage *m_settings = nullptr;
    StreamingPage *m_streaming = nullptr;
    ProfilePage *m_profile = nullptr;
    QToolButton *m_avatarButton = nullptr;
    QTabWidget *m_tabs = nullptr;
    int m_profileIndex = -1;
    QWidget *m_surface = nullptr;
    QVBoxLayout *m_rootLayout = nullptr;
    QSystemTrayIcon *m_tray = nullptr;
    PlayerBar *m_playerBar = nullptr;
    MiniPlayer *m_miniPlayer = nullptr;
    LyricsService *m_lyricsService = nullptr;
    LyricsPanel *m_lyricsPanel = nullptr;
    FullscreenLyrics *m_lyricsOverlay = nullptr;
    FullscreenLyrics *m_karaokeOverlay = nullptr;
    QVector<Track> m_tracks;
    QVector<Track> m_context;
    QVector<Track> m_contextOriginal;
    QVector<qint64> m_queue;
    int m_currentIndex = -1;
    QVector<QWidget *> m_resizeHandles;
    bool m_manualResizing = false;
    Qt::Edges m_manualResizeEdges;
    QPoint m_manualResizeStart;
    QRect m_manualResizeGeometry;
    bool m_scanning = false;
    bool m_scanPending = false;
    bool m_quitRequested = false;
    QString m_repeatMode = QStringLiteral("off");
    bool m_shuffle = false;
    bool m_streamingActive = false;
    bool m_streamingFast = false;
    bool m_mprisStopped = true;
    bool m_crossfadeEnabled = false;
    int m_crossfadeIndex = -1;
    int m_streamQueueSize = 0;
    QElapsedTimer m_streamClock;
    qint64 m_streamPositionBase = 0;
    QTimer *m_streamTimer = nullptr;
    QString m_streamTitle;
    QString m_streamArtist;
    QString m_streamThumbnail;
    QString m_preloadedPath;
    QString m_preloadedTitle;
    QString m_preloadedArtist;
    QString m_preloadedThumbnail;
    int m_preloadedDuration = 0;
    bool m_preloadedReady = false;
    bool m_streamCrossfading = false;
    int m_listeningPending = 0;
    QTimer *m_listeningTimer = nullptr;
    qint64 m_streamDurationMs = 0;
    int m_streamGeneration = 0;
    QString m_contextName;
};
