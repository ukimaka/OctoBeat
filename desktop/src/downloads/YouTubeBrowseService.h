#pragma once

#include <QObject>
#include <QString>
#include <QVector>

#include <functional>

#include "SearchResult.h"

class QNetworkAccessManager;
class QNetworkReply;
class QUrl;

class YouTubeBrowseService : public QObject {
    Q_OBJECT

public:
    explicit YouTubeBrowseService(QObject *parent = nullptr);

    void fetchRelated(const QString &videoId);
    void fetchChannelVideos(const QString &channelId);
    void fetchChannelPlaylists(const QString &channelId);
    void fetchPlaylist(const QString &playlistId);

signals:
    void relatedFinished(const QString &videoId,
                         const QVector<SearchResult> &results);
    void channelVideosFinished(const QString &channelId,
                               const QVector<SearchResult> &results);
    void channelPlaylistsFinished(const QString &channelId,
                                  const QVector<SearchResult> &results);
    void playlistFinished(const QString &playlistId,
                          const QVector<SearchResult> &results);
    void failed(const QString &context, const QString &message);

private:
    using Parser = std::function<QVector<SearchResult>(const QString &)>;
    using Handler =
        std::function<void(const QVector<SearchResult> &)>;
    void fetch(const QUrl &url,
               const QString &context,
               Parser parser,
               Handler handler);

    QNetworkAccessManager *m_network = nullptr;
};
