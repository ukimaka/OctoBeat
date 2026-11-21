#include "YouTubeBrowseService.h"

#include "SearchCache.h"
#include "YouTubeParser.h"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QTimer>
#include <QUrl>

YouTubeBrowseService::YouTubeBrowseService(QObject *parent)
    : QObject(parent), m_network(new QNetworkAccessManager(this)) {}

void YouTubeBrowseService::fetch(const QUrl &url,
                                 const QString &context,
                                 Parser parser,
                                 Handler handler) {
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("Mozilla/5.0 (X11; Linux x86_64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/131.0.0.0 Safari/537.36"));
    request.setRawHeader("Accept-Language", "en-US,en;q=0.9");
    request.setRawHeader("Accept", "text/html,application/xhtml+xml");

    QNetworkReply *reply = m_network->get(request);
    QTimer::singleShot(12000, reply, [reply] {
        if (reply->isRunning()) {
            reply->abort();
        }
    });
    connect(reply, &QNetworkReply::finished, this,
            [this, reply, context, parser, handler] {
                const QByteArray data = reply->readAll();
                if (reply->error() != QNetworkReply::NoError) {
                    const QString message = reply->errorString();
                    reply->deleteLater();
                    emit failed(context, message);
                    return;
                }
                reply->deleteLater();
                const QString html = QString::fromUtf8(data);
                const QVector<SearchResult> results = parser(html);
                if (results.isEmpty()) {
                    emit failed(context, tr("No results found."));
                    return;
                }
                handler(results);
            });
}

void YouTubeBrowseService::fetchRelated(const QString &videoId) {
    if (videoId.isEmpty()) {
        return;
    }
    const QString cacheKey = SearchCache::keyFor(
        QStringLiteral("browse-related|") + videoId, 0, 0);
    QVector<SearchResult> cached;
    if (SearchCache::load(cacheKey, cached)) {
        emit relatedFinished(videoId, cached);
        return;
    }
    fetch(QUrl(QStringLiteral("https://www.youtube.com/watch?v=") + videoId),
          QStringLiteral("related"),
          [](const QString &html) {
              QVector<SearchResult> results =
                  YouTubeParser::parseRelated(html);
              if (results.size() > 12) {
                  results.resize(12);
              }
              return results;
          },
          [this, videoId, cacheKey](const QVector<SearchResult> &results) {
              SearchCache::save(cacheKey, results);
              emit relatedFinished(videoId, results);
          });
}

void YouTubeBrowseService::fetchChannelVideos(const QString &channelId) {
    if (channelId.isEmpty()) {
        return;
    }
    const QString cacheKey = SearchCache::keyFor(
        QStringLiteral("browse-channel-videos|") + channelId, 0, 0);
    QVector<SearchResult> cached;
    if (SearchCache::load(cacheKey, cached)) {
        emit channelVideosFinished(channelId, cached);
        return;
    }
    fetch(QUrl(QStringLiteral("https://www.youtube.com/channel/") + channelId +
               QStringLiteral("/videos")),
          QStringLiteral("channel-videos"),
          [](const QString &html) {
              QVector<SearchResult> results =
                  YouTubeParser::parseChannelVideos(html);
              if (results.size() > 24) {
                  results.resize(24);
              }
              return results;
          },
          [this, channelId, cacheKey](const QVector<SearchResult> &results) {
              SearchCache::save(cacheKey, results);
              emit channelVideosFinished(channelId, results);
          });
}

void YouTubeBrowseService::fetchChannelPlaylists(const QString &channelId) {
    if (channelId.isEmpty()) {
        return;
    }
    const QString cacheKey = SearchCache::keyFor(
        QStringLiteral("browse-channel-playlists|") + channelId, 0, 0);
    QVector<SearchResult> cached;
    if (SearchCache::load(cacheKey, cached)) {
        emit channelPlaylistsFinished(channelId, cached);
        return;
    }
    fetch(QUrl(QStringLiteral("https://www.youtube.com/channel/") + channelId +
               QStringLiteral("/playlists")),
          QStringLiteral("channel-playlists"),
          [](const QString &html) {
              QVector<SearchResult> results =
                  YouTubeParser::parseChannelPlaylists(html);
              if (results.size() > 16) {
                  results.resize(16);
              }
              return results;
          },
          [this, channelId, cacheKey](const QVector<SearchResult> &results) {
              SearchCache::save(cacheKey, results);
              emit channelPlaylistsFinished(channelId, results);
          });
}

void YouTubeBrowseService::fetchPlaylist(const QString &playlistId) {
    if (playlistId.isEmpty()) {
        return;
    }
    const QString cacheKey = SearchCache::keyFor(
        QStringLiteral("browse-playlist|") + playlistId, 0, 0);
    QVector<SearchResult> cached;
    if (SearchCache::load(cacheKey, cached)) {
        emit playlistFinished(playlistId, cached);
        return;
    }
    fetch(QUrl(QStringLiteral("https://www.youtube.com/playlist?list=") +
               playlistId),
          QStringLiteral("playlist"),
          [](const QString &html) {
              QVector<SearchResult> results =
                  YouTubeParser::parsePlaylist(html);
              if (results.size() > 100) {
                  results.resize(100);
              }
              return results;
          },
          [this, playlistId, cacheKey](const QVector<SearchResult> &results) {
              SearchCache::save(cacheKey, results);
              emit playlistFinished(playlistId, results);
          });
}
