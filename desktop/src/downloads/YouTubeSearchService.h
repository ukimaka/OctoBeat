#pragma once

#include <QObject>
#include <QString>
#include <QVector>

#include "SearchResult.h"

class QNetworkAccessManager;
class QNetworkReply;
class QTimer;

class YouTubeSearchService : public QObject {
    Q_OBJECT

public:
    enum class Filter { All, Tracks, Artists, Playlists };

    explicit YouTubeSearchService(QObject *parent = nullptr);
    ~YouTubeSearchService() override;

    void search(const QString &query,
                Filter filter = Filter::All,
                int limit = 30);
    void cancel();
    bool isBusy() const;

    static QVector<SearchResult> filterResults(
        const QVector<SearchResult> &results,
        Filter filter,
        bool allowNonMusic,
        bool strictMusic = false);

signals:
    void finished(const QVector<SearchResult> &results);
    void failed(const QString &message);
    void canceled();

private:
    void handleReply(QNetworkReply *reply);
    void startRequest(const QUrl &url, bool music);
    static QString filterToken(Filter filter);

    QNetworkAccessManager *m_network = nullptr;
    QNetworkReply *m_reply = nullptr;
    QTimer *m_timeout = nullptr;
    int m_limit = 30;
    QString m_query;
    Filter m_filter = Filter::All;
    bool m_musicRequest = true;
    bool m_regularFallback = false;
    bool m_canceled = false;
    bool m_finished = false;
    QString m_cacheKey;
};
