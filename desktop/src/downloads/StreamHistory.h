#pragma once

#include <QString>
#include <QStringList>
#include <QVector>

#include "SearchResult.h"

class StreamHistory {
public:
    static QVector<SearchResult> tracks(int limit = 20);
    static QVector<SearchResult> artists(int limit = 12);
    static QVector<SearchResult> playlists(int limit = 12);
    static QStringList searches(int limit = 150);

    static void addTrack(const SearchResult &result);
    static void addArtist(const SearchResult &result);
    static void addPlaylist(const SearchResult &result);
    static void addSearch(const QString &query);
    static void removeTrack(const SearchResult &result);
    static void removeArtist(const SearchResult &result);
    static void removePlaylist(const SearchResult &result);
    static void clear();

private:
    static QVector<SearchResult> load(const QString &key, int limit);
    static void save(const QString &key,
                     const QVector<SearchResult> &items,
                     int maxItems);
    static void addItem(const QString &key,
                        const SearchResult &result,
                        int maxItems);
    static void removeItem(const QString &key,
                           const SearchResult &result,
                           int maxItems);
};
