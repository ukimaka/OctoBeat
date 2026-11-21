#pragma once

#include <QAction>
#include <QPoint>
#include <QVector>
#include <QWidget>

#include "core/CoreClient.h"

class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QPushButton;
class QStackedWidget;
class QTextEdit;
class TrackDelegate;
class PlaylistCoverButton;

class PlaylistsPage : public QWidget {
    Q_OBJECT

public:
    explicit PlaylistsPage(CoreClient *core,
                           const QString &dataDir,
                           QWidget *parent = nullptr);

    void setLibraryTracks(const QVector<Track> &tracks);
    void refresh();
    void openPlaylistById(qint64 playlistId);
    void setCurrentPlaying(qint64 trackId);
    void showAddTracksDialog();
    void applyTheme();
    void removeTracksFromPlaylist(const QVector<qint64> &trackIds);
    void toggleSelectAll();
    bool allTracksSelected() const;

signals:
    void playPlaylistRequested(qint64 playlistId);
    void playPlaylistTrackRequested(qint64 playlistId, qint64 trackId);
    void contextMenuRequested(const QPoint &globalPos,
                              qint64 trackId,
                              const QVector<qint64> &selectedIds);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void createPlaylist();
    void openPlaylist(qint64 playlistId);
    void showGrid();
    void refreshDetail();
    void applyTrackFilter();
    void updateSortIndicator();
    void deleteCurrentPlaylist();
    void changePlaylistCover(qint64 playlistId);
    void addTracks();
    void removeSelectedTracks();
    Track trackById(qint64 trackId) const;
    QVector<qint64> selectedTrackIds() const;

    CoreClient *m_core = nullptr;
    QString m_dataDir;
    QVector<Track> m_library;
    QVector<Track> m_currentTracks;
    QVector<Playlist> m_playlists;
    QStackedWidget *m_stack = nullptr;
    QListWidget *m_grid = nullptr;
    QWidget *m_detailPage = nullptr;
    QListWidget *m_trackList = nullptr;
    TrackDelegate *m_trackDelegate = nullptr;
    PlaylistCoverButton *m_detailCover = nullptr;
    QLabel *m_detailTitle = nullptr;
    QLabel *m_trackCount = nullptr;
    QLineEdit *m_search = nullptr;
    QAction *m_searchAction = nullptr;
    QLabel *m_filterIcon = nullptr;
    QComboBox *m_sort = nullptr;
    QTextEdit *m_detailDescription = nullptr;
    QWidget *m_gradientPage = nullptr;
    qint64 m_currentPlaylistId = 0;
    bool m_sortAscending = true;
    QString m_lastSortKey;
};
