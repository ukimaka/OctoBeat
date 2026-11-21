#pragma once

#include <QPointer>
#include <QVector>
#include <QWidget>

#include "SearchResult.h"

class QScrollArea;
class QVBoxLayout;
class RemoteImageCache;
class StreamCard;

class StreamHomeView : public QWidget {
    Q_OBJECT

public:
    explicit StreamHomeView(RemoteImageCache *images,
                            QWidget *parent = nullptr);

    void setData(const QVector<SearchResult> &recentTracks,
                 const QVector<SearchResult> &artists,
                 const QVector<SearchResult> &playlists);
    void setPlaying(const QString &id, bool playing);

signals:
    void itemActivated(const SearchResult &result);
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void removeRequested(const SearchResult &result);

private:
    void clear();
    void addSection(const QString &title,
                    const QVector<SearchResult> &items);

    RemoteImageCache *m_images = nullptr;
    QScrollArea *m_scroll = nullptr;
    QVector<QPointer<QScrollArea>> m_rowScrollers;
    QVector<QPointer<StreamCard>> m_cards;
    QWidget *m_content = nullptr;
    QVBoxLayout *m_layout = nullptr;
};
