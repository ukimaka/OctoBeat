#pragma once

#include <QHash>
#include <QVector>
#include <QWidget>

#include "SearchResult.h"

class QLabel;
class QListWidget;
class QListWidgetItem;
class QHBoxLayout;
class QPushButton;
class QWidget;
class RemoteImageCache;
class StreamItemRow;

class StreamCollectionView : public QWidget {
    Q_OBJECT

public:
    explicit StreamCollectionView(RemoteImageCache *images,
                                  QWidget *parent = nullptr);

    void setHeader(const SearchResult &header);
    const SearchResult &header() const { return m_header; }
    void setTracks(const QVector<SearchResult> &tracks);
    void setPlaylists(const QVector<SearchResult> &playlists);
    void setLoading(bool loading);
    void setBusyFor(const QString &id, bool busy);
    void setDownloadProgress(const QString &id, int progress);
    void setPlaying(const QString &id, bool playing);
    void setShowAllAvailable(bool available);
    void demoClickFirstPlaylistPlay();

signals:
    void backRequested();
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void playlistRequested(const SearchResult &result);
    void playAllRequested(const SearchResult &header);
    void showAllRequested(const SearchResult &header);

private:
    void clearTracks();
    void clearPlaylists();
    void updatePlayAllVisibility();
    void updateShowAllVisibility();
    QString keyFor(const SearchResult &result) const;

    RemoteImageCache *m_images = nullptr;
    QLabel *m_cover = nullptr;
    QLabel *m_title = nullptr;
    QLabel *m_subtitle = nullptr;
    QLabel *m_empty = nullptr;
    QPushButton *m_playAll = nullptr;
    QPushButton *m_showAll = nullptr;
    QListWidgetItem *m_showAllItem = nullptr;
    bool m_showAllAvailable = false;
    SearchResult m_header;
    QWidget *m_playlistsSection = nullptr;
    QWidget *m_playlistsRow = nullptr;
    QHBoxLayout *m_playlistsLayout = nullptr;
    QListWidget *m_list = nullptr;
    QHash<QString, StreamItemRow *> m_rows;
    QHash<QString, SearchResult> m_results;
    int m_trackCount = 0;
};
