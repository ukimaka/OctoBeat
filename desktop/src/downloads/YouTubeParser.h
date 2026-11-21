#pragma once

#include <QString>
#include <QVector>

#include "SearchResult.h"

namespace YouTubeParser {

QString extractInitialData(const QString &html);
QVector<SearchResult> parseSearch(const QString &html);
QVector<SearchResult> parseMusicSearch(const QString &html);
QVector<SearchResult> parseRelated(const QString &html);
QVector<SearchResult> parseChannelVideos(const QString &html);
QVector<SearchResult> parseChannelPlaylists(const QString &html);
QVector<SearchResult> parsePlaylist(const QString &html);

} // namespace YouTubeParser
