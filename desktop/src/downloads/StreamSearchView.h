#pragma once

#include <QHash>
#include <QVector>
#include <QWidget>

#include "SearchResult.h"
#include "YouTubeSearchService.h"

class QLabel;
class QListWidget;
class QListWidgetItem;
class QButtonGroup;
class QPushButton;
class RemoteImageCache;
class StreamItemRow;

class StreamSearchView : public QWidget {
    Q_OBJECT

public:
    explicit StreamSearchView(RemoteImageCache *images,
                              QWidget *parent = nullptr);

    void setQuery(const QString &query);
    void setResults(const QVector<SearchResult> &results);
    void setHistory(const QStringList &history);
    void setLoading(bool loading);
    void setFilter(YouTubeSearchService::Filter filter);
    void setBusyFor(const QString &id, bool busy);
    void setDownloadProgress(const QString &id, int progress);
    void setPlaying(const QString &id, bool playing);

signals:
    void filterChanged(YouTubeSearchService::Filter filter);
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void openRequested(const SearchResult &result);
    void historyRequested(const QString &query);

private:
    void clearList();
    QString keyFor(const SearchResult &result) const;

    RemoteImageCache *m_images = nullptr;
    QLabel *m_empty = nullptr;
    QListWidget *m_list = nullptr;
    QButtonGroup *m_filterGroup = nullptr;
    QHash<QString, StreamItemRow *> m_rows;
    QHash<QString, SearchResult> m_results;
    YouTubeSearchService::Filter m_filter = YouTubeSearchService::Filter::All;
    QString m_query;
    bool m_historyMode = false;
};
