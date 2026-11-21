#pragma once

#include <QFrame>
#include <QHash>
#include <QVector>

#include "SearchResult.h"

class QListWidget;
class QListWidgetItem;
class QPropertyAnimation;
class RemoteImageCache;
class StreamItemRow;

class StreamSearchOverlay : public QFrame {
    Q_OBJECT

public:
    explicit StreamSearchOverlay(RemoteImageCache *images,
                                 QWidget *parent = nullptr);

    void setSuggestions(const QVector<SearchResult> &results);
    void setHistory(const QStringList &history);
    void clear();
    void showPanel();
    void hidePanel();
    bool panelVisible() const { return !isHidden(); }
    void moveSelection(int delta);
    bool activateCurrent();
    void setBusyFor(const QString &id, bool busy);
    void setDownloadProgress(const QString &id, int progress);
    void setPlaying(const QString &id, bool playing);

signals:
    void playRequested(const SearchResult &result);
    void downloadRequested(const SearchResult &result);
    void queueRequested(const SearchResult &result);
    void openRequested(const SearchResult &result);
    void historyRequested(const QString &query);

private:
    void rebuildRows(const QVector<SearchResult> &results);
    void updateHeight(bool animate);
    QString keyFor(const SearchResult &result) const;

    RemoteImageCache *m_images = nullptr;
    QListWidget *m_list = nullptr;
    QPropertyAnimation *m_animation = nullptr;
    QHash<QString, StreamItemRow *> m_rows;
    QHash<QString, SearchResult> m_results;
    bool m_historyMode = false;
    int m_targetHeight = 0;
};
