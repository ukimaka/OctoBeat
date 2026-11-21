#include "YouTubeSearchService.h"

#include "SearchCache.h"
#include "YouTubeParser.h"

#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QRegularExpression>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>

YouTubeSearchService::YouTubeSearchService(QObject *parent)
    : QObject(parent),
      m_network(new QNetworkAccessManager(this)),
      m_timeout(new QTimer(this)) {
    m_timeout->setSingleShot(true);
    m_timeout->setInterval(8000);
    connect(m_timeout, &QTimer::timeout, this, [this] {
        if (!m_reply) {
            return;
        }
        m_finished = true;
        QNetworkReply *reply = m_reply;
        m_reply = nullptr;
        reply->abort();
        reply->deleteLater();
        emit failed(tr("YouTube search timed out."));
    });
}

YouTubeSearchService::~YouTubeSearchService() {
    blockSignals(true);
    cancel();
}

bool YouTubeSearchService::isBusy() const {
    return m_reply != nullptr;
}

QString YouTubeSearchService::filterToken(Filter filter) {
    switch (filter) {
    case Filter::Tracks:
        return QStringLiteral("EgIQAQ%3D%3D");
    case Filter::Artists:
        return QStringLiteral("EgIQAg%3D%3D");
    case Filter::Playlists:
        return QStringLiteral("EgIQAw%3D%3D");
    case Filter::All:
        break;
    }
    return {};
}

void YouTubeSearchService::search(const QString &query,
                                  Filter filter,
                                  int limit) {
    const QString trimmed = query.trimmed();
    if (trimmed.isEmpty()) {
        emit failed(tr("Enter a search query."));
        return;
    }

    if (m_reply) {
        m_canceled = true;
        QNetworkReply *old = m_reply;
        m_reply = nullptr;
        old->abort();
        old->deleteLater();
    }
    m_finished = false;
    m_canceled = false;
    m_limit = qMax(1, limit);
    m_query = trimmed;
    m_filter = filter;
    m_regularFallback = false;
    m_musicRequest = true;
    m_cacheKey = SearchCache::keyFor(trimmed, static_cast<int>(filter),
                                     m_limit);
    QVector<SearchResult> cached;
    if (SearchCache::load(m_cacheKey, cached)) {
        if (cached.size() > m_limit) {
            cached.resize(m_limit);
        }
        const QString cacheKey = m_cacheKey;
        QTimer::singleShot(0, this, [this, cached, cacheKey] {
            if (!m_finished && m_cacheKey == cacheKey) {
                m_finished = true;
                emit finished(cached);
            }
        });
        return;
    }

    QUrl url(QStringLiteral("https://music.youtube.com/search"));
    QUrlQuery queryItems;
    queryItems.addQueryItem(QStringLiteral("q"), trimmed);
    queryItems.addQueryItem(QStringLiteral("hl"), QStringLiteral("en"));
    url.setQuery(queryItems);
    startRequest(url, true);
}

void YouTubeSearchService::startRequest(const QUrl &url, bool music) {
    m_musicRequest = music;
    QNetworkRequest request(url);
    request.setHeader(QNetworkRequest::UserAgentHeader,
                      QStringLiteral("Mozilla/5.0 (X11; Linux x86_64) "
                                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/131.0.0.0 Safari/537.36"));
    request.setRawHeader("Accept-Language", "en-US,en;q=0.9");
    request.setRawHeader("Accept", "text/html,application/xhtml+xml");

    QNetworkReply *reply = m_network->get(request);
    m_reply = reply;
    m_timeout->start();
    connect(reply, &QNetworkReply::finished, this,
            [this, reply] { handleReply(reply); });
}

QVector<SearchResult> YouTubeSearchService::filterResults(
    const QVector<SearchResult> &results,
    Filter filter,
    bool allowNonMusic,
    bool strictMusic) {
    static const QRegularExpression junkTitle(
        QStringLiteral("\\b(reaction|reacts|reacting|pvp|gameplay|"
                       "live\\s*stream|full\\s*stream|podcast|interview|"
                       "review|tutorial|how\\s*to|unboxing|trailer|teaser|"
                       "news|vlog|behind\\s*the\\s*scenes|making\\s*of|"
                       "commentary|playthrough|walkthrough|episode)\\b"),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression junkUploader(
        QStringLiteral("(reacts?|reaction|gaming|highlights|podcast|news)"),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression strictTitle(
        QStringLiteral("\\b(reaction|reacts?|reacting|pvp|gameplay|"
                       "stream|streaming|live\\s*stream|podcast|interview|"
                       "review|tutorial|how\\s*to|unboxing|trailer|teaser|"
                       "news|vlog|behind\\s*the\\s*scenes|making\\s*of|"
                       "commentary|playthrough|walkthrough|episode|highlights|"
                       "compilation|top\\s*\\d+|best\\s*moments|"
                       "funny\\s*moments|shorts?|clip|live)\\b"),
        QRegularExpression::CaseInsensitiveOption);
    static const QRegularExpression strictUploader(
        QStringLiteral("(reacts?|reaction|gaming|highlights|podcast|news|"
                       "clips?|streams?|shorts?)"),
        QRegularExpression::CaseInsensitiveOption);

    QVector<SearchResult> filtered;
    for (const SearchResult &result : results) {
        if (filter == Filter::Tracks &&
            result.kind != SearchResult::Kind::Track) {
            continue;
        }
        if (filter == Filter::Artists &&
            result.kind != SearchResult::Kind::Artist) {
            continue;
        }
        if (filter == Filter::Playlists &&
            result.kind != SearchResult::Kind::Playlist) {
            continue;
        }
        if ((result.kind == SearchResult::Kind::Track ||
             result.kind == SearchResult::Kind::Artist) &&
            result.hasPopularity && result.popularity < 1000) {
            continue;
        }
        if (!allowNonMusic && result.kind == SearchResult::Kind::Track) {
            if ((result.duration > 7200) ||
                junkTitle.match(result.title).hasMatch() ||
                junkUploader.match(result.uploader).hasMatch()) {
                continue;
            }
            if (strictMusic &&
                ((result.duration > 900) ||
                 strictTitle.match(result.title).hasMatch() ||
                 strictUploader.match(result.uploader).hasMatch())) {
                continue;
            }
        }
        filtered.push_back(result);
    }
    return filtered;
}

void YouTubeSearchService::cancel() {
    if (!m_reply) {
        return;
    }
    m_canceled = true;
    m_finished = true;
    m_timeout->stop();
    QNetworkReply *reply = m_reply;
    m_reply = nullptr;
    reply->abort();
    reply->deleteLater();
    emit canceled();
}

void YouTubeSearchService::handleReply(QNetworkReply *reply) {
    if (!reply || reply != m_reply || m_finished) {
        return;
    }
    m_finished = true;
    m_timeout->stop();
    m_reply = nullptr;

    if (m_canceled) {
        reply->deleteLater();
        emit canceled();
        return;
    }
    if (reply->error() != QNetworkReply::NoError) {
        const QString message = reply->errorString();
        reply->deleteLater();
        emit failed(message);
        return;
    }

    const QString html = QString::fromUtf8(reply->readAll());
    reply->deleteLater();

    QVector<SearchResult> results =
        m_regularFallback ? YouTubeParser::parseSearch(html)
                          : YouTubeParser::parseMusicSearch(html);
    if (results.isEmpty() && !m_regularFallback) {
        m_regularFallback = true;
        QUrl fallback(QStringLiteral("https://www.youtube.com/results"));
        QUrlQuery queryItems;
        queryItems.addQueryItem(QStringLiteral("search_query"), m_query);
        const QString token = filterToken(m_filter);
        if (!token.isEmpty()) {
            queryItems.addQueryItem(QStringLiteral("sp"), token);
        }
        queryItems.addQueryItem(QStringLiteral("hl"), QStringLiteral("en"));
        fallback.setQuery(queryItems);
        startRequest(fallback, false);
        return;
    }
    results = filterResults(results, m_filter, !m_regularFallback);
    if (results.isEmpty()) {
        emit failed(tr("No results found."));
        return;
    }
    if (results.size() > m_limit) {
        results.resize(m_limit);
    }
    SearchCache::save(m_cacheKey, results);
    m_finished = true;
    emit finished(results);
}
